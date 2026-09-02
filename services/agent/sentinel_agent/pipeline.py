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
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import Frame, TranscriptionFrame, TTSSpeakFrame
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
from pipecat.workers.runner import WorkerRunner

from sentinel_agent.timing import FrameTimingProcessor

# The RTVI message type the browser sends for typed input (PLAN 1.4).
TEXT_INPUT = "text-input"

# Cartesia "Jacqueline — Reassuring Agent", picked for a bank fraud line.
VOICE_ID = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"

# Spoken verbatim on connect, before the model is asked for anything. A consent
# and recording disclosure is the one line on the call that must not be
# paraphrased, and 2.2's done-when is that it comes *first* — neither is
# something to leave to a model that has been asked to be concise.
CONSENT_LINE = (
    "This is Meridian Bank Fraud Prevention calling about a card transaction. "
    "This call is not being recorded, and I will never ask for your full card "
    "number or your PIN. Is now a good time to talk?"
)

SYSTEM_PROMPT = """\
You are a fraud prevention agent for Meridian Bank, speaking with a cardholder \
on a live call.

Style: calm, concise, plain language. One or two sentences per turn. Your words \
are spoken aloud, so never use markdown, lists, bullet points, emoji or \
symbols, and write numbers the way you would say them.

Rules:
- Never say a full card number. Refer to a card only by its last four digits.
- Never ask for a PIN, a full card number, a password, or a one-time code.
- Do not invent transactions, amounts, merchants or account details. If you do \
not have a fact, say you are checking rather than guessing.
- If the caller goes off topic, answer briefly and return to the matter at hand.

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
            logger.info("typed: {!r}", text)
            await self.push_frame(
                TranscriptionFrame(
                    text=text,
                    user_id="",
                    timestamp=datetime.now(UTC).isoformat(),
                )
            )


class TranscriptLog(FrameProcessor):
    """Log what the caller was heard to say. 2.6 redacts this before it persists."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Forward every frame; additionally log final transcripts."""
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            logger.info("stt: {!r}", frame.text)


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

    stt = DeepgramSTTService(api_key=os.environ["DEEPGRAM_API_KEY"])
    llm = CerebrasLLMService(
        api_key=os.environ["CEREBRAS_API_KEY"],
        settings=CerebrasLLMService.Settings(system_instruction=SYSTEM_PROMPT),
    )
    tts = CartesiaTTSService(
        api_key=os.environ["CARTESIA_API_KEY"],
        settings=CartesiaTTSService.Settings(voice=VOICE_ID),
    )

    context = LLMContext()
    # Without a VAD analyzer the aggregator ends a user turn on every final
    # transcript, and Deepgram splits even "Yes, now is a good time." into two.
    # The second transcript then interrupts the reply to the first, so the
    # caller is never answered. VAD makes silence, not punctuation, decide when
    # a turn is over.
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
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
            tts,
            transport.output(),
            assistant_aggregator,
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
        await worker.queue_frames([TTSSpeakFrame(CONSENT_LINE)])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport, _client):
        logger.info("call: disconnected (call_id={} pc_id={})", call_id, connection.pc_id)
        await runner.cancel()

    await runner.run()
