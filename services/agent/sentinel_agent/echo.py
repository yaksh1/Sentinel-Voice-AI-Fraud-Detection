"""The echo pipeline (PLAN 1.1).

Phase 1 proves the transport, not the intelligence: audio in from the browser,
the same audio straight back out, nothing in between. Every later phase keeps
this shape and changes only the middle — 2.1 replaces EchoProcessor with
STT -> LLM -> TTS, and 3.1 puts the state machine validator beside it.
"""

import uuid

from loguru import logger
from pipecat.frames.frames import Frame, InputAudioRawFrame, OutputAudioRawFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.workers.runner import WorkerRunner

from sentinel_agent.timing import FrameTimingProcessor


class EchoProcessor(FrameProcessor):
    """Re-emit microphone audio as speaker audio.

    Not a no-op, despite appearances. The input transport emits
    `InputAudioRawFrame` (a SystemFrame) and the output transport only ever
    plays `OutputAudioRawFrame`, so a bare input -> output pipeline connects
    and stays silent. Re-wrapping the same PCM bytes in the output frame *is*
    the echo. The original frame is forwarded as well, so the processor stays
    non-destructive for anything added downstream later.
    """

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Forward every frame; additionally mirror input audio to the output."""
        await super().process_frame(frame, direction)

        await self.push_frame(frame, direction)

        if isinstance(frame, InputAudioRawFrame):
            await self.push_frame(
                OutputAudioRawFrame(
                    audio=frame.audio,
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels,
                )
            )


async def run_echo_bot(connection: SmallWebRTCConnection, call_id: str | None = None) -> None:
    """Run one echo pipeline for one peer connection, until the client leaves.

    Called as a FastAPI background task, so it starts only after the SDP answer
    has gone back to the browser. One runner per connection: in 3.7 the agent
    holds up to three of these at once plus one pre-warmed.

    `call_id` is minted here for now; from 3.6 the orchestrator supplies it.
    """
    call_id = call_id or str(uuid.uuid4())
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

    pipeline = Pipeline(
        [
            transport.input(),
            FrameTimingProcessor(call_id),
            EchoProcessor(),
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
