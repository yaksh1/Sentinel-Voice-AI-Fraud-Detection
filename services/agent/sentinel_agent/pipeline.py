"""The conversation pipeline (PLAN 1.1–1.4, persona added in 2.2).

Speech in from the browser, Deepgram to text, Cerebras for the reply, Cartesia
back to speech. Typed text enters at the same point a transcript does, so there
is one conversation regardless of how the caller talks (BRIEF §10).

What is deliberately *not* here: the pathway state machine. BRIEF §5 is explicit
that its rules are "enforced in code, not in the prompt" — `action_release` and
`action_block` become unreachable without a passed `verify_identity` because a
validator says so, not because a system prompt asked nicely. That validator
arrives in 3.1, and the structured output it reads is specified in 2.7. Nothing
below should grow into a substitute for it.
"""

import os
import uuid
from datetime import UTC, datetime

from loguru import logger
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    EndWorkerFrame,
    Frame,
    InterimTranscriptionFrame,
    TextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIClientMessageFrame
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.cerebras.llm import CerebrasLLMService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.turns.user_mute import MuteUntilFirstBotCompleteUserMuteStrategy
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from sentinel_agent.timing import FrameTimingProcessor
from sentinel_agent.tools import TOOLS, reset_demo, set_hangup
from sentinel_contracts.redact import redact_pan

# The RTVI message type the browser sends for typed input (PLAN 1.4).
TEXT_INPUT = "text-input"

# Cartesia "Jacqueline — Reassuring Agent", picked for a bank fraud line.
VOICE_ID = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"

# Spoken verbatim on connect, before the model is asked for anything. A consent
# and recording disclosure is the one line on the call that must not be
# paraphrased, and 2.2's done-when is that it comes *first* — neither is
# something to leave to a model that has been asked to be concise.
#
# Kept short on purpose. The caller is muted until it finishes (2.2 follow-up),
# so every word is a word they cannot interrupt. 41 words measured 11.0 s of
# dead air on connect; this is 32, at 9.9 s. Still the longest single wait in
# the call — shortening it further trades against the four things it has to
# say: who is calling, why, that it is not recorded, and that a full card
# number will never be asked for.
CONSENT_LINE = (
    "This is Meridian Bank fraud prevention, about a charge on your card. "
    "This call isn't recorded, and I'll never ask for your full card number "
    "or PIN. Do you have a moment?"
)

SYSTEM_PROMPT = """\
You are a fraud prevention agent for Meridian Bank.

You placed this call. Meridian's monitoring flagged a transaction on the \
cardholder's account and you rang them to check whether it was genuine. They \
did not call you, they are not a support caller, and they have no request for \
you to handle. Never ask what they need, how you can help, or what their \
concern is — you know why you called and it is your job to lead.

How the call goes:

1. Confirm you are speaking to the cardholder. Ask for the last four digits of \
the card and their city of birth, then call verify_challenge with both. Do not \
discuss the transaction — the amount, the merchant, the time, the place — \
before that passes.

2. When it passes, say so before you move on: thank them, and tell them the \
details match what the bank has. Then call lookup_transaction and describe what \
was flagged — the amount, the merchant, roughly when — and say that it was \
stopped before any money left the account.

3. Ask whether they made it, and give them room to answer.
   - If they did: call release_hold, tell them the payment will go through \
normally, and apologise for interrupting their day.
   - If they did not: call block_card_and_reissue, then reassure them in this \
order — they are not liable for a charge they did not make, the card is stopped \
so it cannot be used again, and a replacement is on its way within three to \
five days. Ask whether they have any questions before you close.

4. If verification fails twice, or they ask for a person, call \
escalate_to_analyst.

5. When the matter is settled, say one short closing line and stop. The line \
hangs up on its own. Do not ask whether there is anything else, and never tell \
the caller to hang up; you called them.

Style: warm, calm, unhurried. You are talking to someone who may be worried \
about their money, and possibly frightened, so sound like a person rather than \
a form.

Acknowledge what they just said before you move on — "thank you", "that matches \
what we have here", "I understand" — and never answer a piece of information \
with nothing but the next question. Two or three sentences a turn is right: \
enough to sound human, not so much that they cannot get a word in.

Once they are verified, use their first name occasionally — once or twice in \
the call, not every turn.

Your words are spoken aloud, so never use markdown, lists, bullet points, \
emoji, symbols, braces or quotation marks, and write numbers the way you would \
say them.

Rules:
- Never say a full card number. Refer to a card only by its last four digits.
- Never ask for a PIN, a full card number, a password, or a one-time code.
- Do not invent transactions, amounts, merchants or account details. If you do \
not have a fact, say you are checking rather than guessing.
- Everything you can do happens on this call, now. You cannot schedule a \
callback, call back later, transfer the caller, send an email or a text, or \
promise that anyone will follow up. Never offer one.
- If the caller goes off topic, answer briefly and return to verifying who they \
are.
- If the caller is hostile or wants to stop, stay calm, do not argue, and tell \
them they can hang up and call the number on the back of their card.

You have already delivered the consent line. Do not repeat it."""


class TypedInput(FrameProcessor):
    """Turn a typed message into a transcript so text joins the same conversation.

    BRIEF §10 settled that text mode reuses the call rather than bypassing it,
    and this is the whole of that: a client message becomes the frame Deepgram
    would have produced, so everything downstream is indifferent to whether the
    caller spoke or typed. The reply reaches the browser as bot output over
    RTVI, which the client already receives.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Forward every frame; additionally re-emit typed text as a transcript."""
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

        if isinstance(frame, RTVIClientMessageFrame) and frame.type == TEXT_INPUT:
            text = (frame.data or {}).get("text", "")
            if not text:
                return
            logger.info("typed: {!r}", redact_pan(text))
            await self.push_frame(
                TranscriptionFrame(
                    text=text,
                    user_id="",
                    timestamp=datetime.now(UTC).isoformat(),
                )
            )


class TranscriptLog(FrameProcessor):
    """Log what the caller was heard to say, with card numbers removed (2.6).

    Redaction happens here rather than at the sink because this is the first
    place caller speech becomes a log line. `frame.text` itself is left alone —
    the model needs what was actually said to hold a conversation — but nothing
    that leaves the process carries it unredacted.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Forward every frame; additionally log final transcripts."""
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            logger.info("stt: {!r}", redact_pan(frame.text))


class Speakable(FrameProcessor):
    """Strip anything heading for the TTS that a voice cannot say.

    A caller heard `{ "reason": "completed_release" }` read out before the
    goodbye: the model emitted tool-call syntax as visible text and the TTS
    dutifully said it. Removing the tool it was misusing did not stop it — the
    braces came back on a run with that tool gone — so this is the fix that
    actually holds.

    It strips characters rather than dropping frames, because the LLM streams
    `{` inside a larger chunk and the TTS aggregator only splits it onto its own
    line later. By then the frame is out of reach; by here it is not.

    Two rules, because stripping punctuation alone was not enough: a fragment
    that survived as `name: lookup_transaction,` still reached the caller. So a
    fragment naming any tool is dropped outright — those are identifiers, never
    speech — and what is left has braces, quotes and backslashes removed, with
    anything containing no letter or digit dropped as well.
    """

    #: Characters that never belong in something spoken to a caller.
    UNSPEAKABLE = str.maketrans("", "", '{}"\\')

    #: The tool names. A caller should never hear "lookup_transaction" — these
    #: are identifiers, never speech, so a fragment containing one is a leaking
    #: tool call however much of its punctuation has already been stripped.
    TOOL_NAMES = frozenset(tool.name for tool in TOOLS)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Forward every frame, with unspeakable characters removed from speech."""
        await super().process_frame(frame, direction)

        if (
            isinstance(frame, TextFrame)
            and not isinstance(frame, TranscriptionFrame | InterimTranscriptionFrame)
            and frame.text
        ):
            if any(name in frame.text for name in self.TOOL_NAMES):
                logger.warning("dropped leaked tool call before TTS: {!r}", frame.text)
                return

            cleaned = frame.text.translate(self.UNSPEAKABLE)
            if cleaned != frame.text:
                logger.warning("stripped unspeakable text before TTS: {!r}", frame.text)
                if not any(c.isalnum() for c in cleaned):
                    return
                frame.text = cleaned

        await self.push_frame(frame, direction)


class HangUp(FrameProcessor):
    """End the call once the agent has finished saying goodbye.

    `end_call` cannot hang up on its own. When the tool runs, the closing line
    does not exist yet — the tool result is what prompts the model to say it. So
    the tool arms this, and this waits for the agent to actually stop speaking
    before pushing `EndWorkerFrame`, which drains the pipeline rather than
    cutting the goodbye off mid-word.
    """

    def __init__(self):
        super().__init__()
        self._armed = False

    def arm(self) -> None:
        """Hang up after the agent's next completed utterance."""
        self._armed = True

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Forward every frame; end the call once the agent stops speaking."""
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

        if self._armed and isinstance(frame, BotStoppedSpeakingFrame):
            self._armed = False
            logger.info("call: agent hanging up")
            await self.push_frame(EndWorkerFrame(reason="agent ended the call"))


async def run_agent(connection: SmallWebRTCConnection) -> None:
    """Run one pipeline for one peer connection, until the client leaves.

    Called as a FastAPI background task, so it starts only after the SDP answer
    has gone back to the browser. One runner per connection: in 3.7 the agent
    holds up to three of these at once plus one pre-warmed.
    """
    call_id = str(uuid.uuid4())
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            # 20 ms of output buffering rather than the stock 40 ms. Measured
            # over the loopback probe: median round trip 297 ms -> 283 ms, and
            # the spread tightens from 295-311 ms to 279-287 ms. Cheap, and
            # ARCHITECTURE budgets only 250 ms to network and jitter for both
            # directions combined.
            audio_out_10ms_chunks=2,
        ),
    )

    stt = DeepgramSTTService(
        api_key=os.environ["DEEPGRAM_API_KEY"],
        # Deepgram splits "yes / speaking / my card ends four two four two / I
        # was born in Porto" into four finals, and with a short turn timeout the
        # aggregator ends a turn on each one — four LLM calls in four seconds,
        # which is over the Cerebras free-tier rate limit and cost a 21 s
        # backoff stall. endpointing is the silence Deepgram needs before it
        # calls an utterance finished: 800 ms rides out the pauses inside one
        # answer. utterance_end_ms is the backstop for when they really stop.
        endpointing=800,
        utterance_end_ms=1200,
    )
    llm = CerebrasLLMService(
        api_key=os.environ["CEREBRAS_API_KEY"],
        settings=CerebrasLLMService.Settings(system_instruction=SYSTEM_PROMPT),
    )
    tts = CartesiaTTSService(
        api_key=os.environ["CARTESIA_API_KEY"],
        settings=CartesiaTTSService.Settings(voice=VOICE_ID),
    )

    hangup = HangUp()
    set_hangup(hangup)

    context = LLMContext(tools=TOOLS)
    # Two settings, for two different failures.
    #
    # VAD: without it the aggregator ends a user turn on every final transcript,
    # and Deepgram splits even "Yes, now is a good time." into two. The second
    # transcript then interrupts the reply to the first, so the caller is never
    # answered. VAD makes silence, not punctuation, decide when a turn is over.
    #
    # Mute-until-first-bot-complete: the consent line is a disclosure, and a
    # caller who says "hello?" over the top of it truncated it mid-sentence —
    # after which the agent went on to ask for card details, which is precisely
    # what the disclosure exists to warn them about. The caller is muted until
    # it has been delivered in full. Interruption is allowed everywhere after.
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_mute_strategies=[MuteUntilFirstBotCompleteUserMuteStrategy()],
            # The turn already ends via smart-turn-v3, which Pipecat uses by
            # default — the problem was never that it was missing, it was that
            # its SmartTurnParams.stop_secs defaults to 3. Measured, the caller
            # finished talking and the agent sat silent for 3.0 s before the LLM
            # was even asked, which was two thirds of the whole 4.5 s turn.
            #
            # 1.2 s, not the 0.8 s first tried: at 0.8 the turn ended on every
            # Deepgram fragment, firing four LLM calls in four seconds, tripping
            # the Cerebras rate limit and stalling 21 s on backoff. Faster turn
            # detection is worth nothing if it outruns the model behind it.
            # Interruptions have to cost more than one stray syllable. Measured
            # over a real browser call: 28 LLM requests, 9 first tokens, 19
            # interruptions — most replies were cancelled before they produced a
            # word, which the caller experiences as the agent going silent. The
            # usual cause is the agent's own voice leaking back through
            # speakers, but a cough or a "mm" does it too.
            #
            # This strategy only applies the word gate *while the bot is
            # speaking* (`min_words if bot_speaking else 1`), so a one-word
            # "No." still answers normally — which matters, because "No." is the
            # answer the whole call is built around. It replaces the VAD start
            # strategy rather than joining it: VAD would keep starting turns on
            # leaked audio no matter what the word count said.
            user_turn_strategies=UserTurnStrategies(
                start=[MinWordsUserTurnStartStrategy(min_words=3)],
                stop=[
                    TurnAnalyzerUserTurnStopStrategy(
                        turn_analyzer=LocalSmartTurnAnalyzerV3(
                            params=SmartTurnParams(stop_secs=1.2)
                        )
                    )
                ],
            ),
            user_turn_stop_timeout=1.5,
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            FrameTimingProcessor(call_id),
            TypedInput(),
            stt,
            TranscriptLog(),
            user_aggregator,
            llm,
            Speakable(),
            tts,
            transport.output(),
            assistant_aggregator,
            hangup,
        ]
    )
    worker = PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True))

    # handle_sigint=False: uvicorn owns the process signals, and a per-call
    # runner installing its own handler would tear the whole server down.
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport, _client):
        logger.info("call: connected (call_id={} pc_id={})", call_id, connection.pc_id)
        # Every call starts from the same place. Reset on connect rather than on
        # hang-up so the result of the last call survives for inspection —
        # otherwise the rows are gone before anyone can look at what happened.
        await reset_demo()
        await worker.queue_frames([TTSSpeakFrame(CONSENT_LINE)])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport, _client):
        logger.info("call: disconnected (call_id={} pc_id={})", call_id, connection.pc_id)
        await runner.cancel()

    await runner.run()
