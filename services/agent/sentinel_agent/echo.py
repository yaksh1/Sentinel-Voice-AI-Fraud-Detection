"""The echo pipeline (PLAN 1.1, speech added in 2.1).

Still an echo — say something and the agent says it back — but the audio no
longer short-circuits. Deepgram turns speech into a transcript and Cartesia
turns the reply into speech, so the shape is now the one every later phase
keeps: 2.2 puts a persona in the middle, and 3.1 the state machine validator.
"""

import os
import uuid

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi import RTVIClientMessageFrame, RTVIServerMessageFrame
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from sentinel_agent.timing import FrameTimingProcessor

# The RTVI message types text mode speaks. The client sends TEXT_INPUT; the
# reply comes back as a server message tagged TEXT_ECHO.
TEXT_INPUT = "text-input"
TEXT_ECHO = "text-echo"

# Cartesia "Jacqueline — Reassuring Agent", picked for a bank fraud line.
# 2.2 owns the persona and may well change it.
VOICE_ID = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"


class EchoProcessor(FrameProcessor):
    """Say back whatever the caller said, spoken or typed.

    Speech arrives as a `TranscriptionFrame` from Deepgram and leaves as a
    `TTSSpeakFrame` for Cartesia. The reply cannot be the transcript simply
    forwarded on: `TranscriptionFrame` subclasses `TextFrame`, but the TTS
    service deliberately excludes transcription frames so that a pipeline never
    speaks its own input. `TTSSpeakFrame` is the frame for a standalone
    utterance, which is what a reply is.

    Interim results need no filtering here — `InterimTranscriptionFrame` is a
    sibling of `TranscriptionFrame`, not a subclass, so the check below already
    sees only finals.

    Typed text (PLAN 1.4) takes the same path and needs no second transport.
    `PipelineWorker` prepends its `RTVIProcessor` above everything here, so a
    client message arrives as an `RTVIClientMessageFrame` and the reply leaves
    as an `RTVIServerMessageFrame` — text in, text out, for the visitor who
    declined the microphone.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Forward every frame; additionally echo speech and typed text."""
        await super().process_frame(frame, direction)

        await self.push_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            logger.info("stt: {!r}", frame.text)
            await self.push_frame(TTSSpeakFrame(frame.text))
        elif isinstance(frame, RTVIClientMessageFrame) and frame.type == TEXT_INPUT:
            text = (frame.data or {}).get("text", "")
            logger.info("echo: text in {!r}", text)
            await self.push_frame(RTVIServerMessageFrame(data={"type": TEXT_ECHO, "text": text}))


async def run_echo_bot(connection: SmallWebRTCConnection) -> None:
    """Run one echo pipeline for one peer connection, until the client leaves.

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
    tts = CartesiaTTSService(
        api_key=os.environ["CARTESIA_API_KEY"],
        settings=CartesiaTTSService.Settings(voice=VOICE_ID),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            FrameTimingProcessor(call_id),
            stt,
            EchoProcessor(),
            tts,
            transport.output(),
        ]
    )
    worker = PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True))

    # handle_sigint=False: uvicorn owns the process signals, and a per-call
    # runner installing its own handler would tear the whole server down.
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(_transport, _client):
        logger.info("echo: client connected (call_id={} pc_id={})", call_id, connection.pc_id)

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(_transport, _client):
        logger.info("echo: client disconnected (call_id={} pc_id={})", call_id, connection.pc_id)
        await runner.cancel()

    await runner.run()
