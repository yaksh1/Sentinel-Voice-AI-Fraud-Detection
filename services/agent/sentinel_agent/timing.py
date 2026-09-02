"""Per-frame audio arrival timing (PLAN 1.3).

What `net_ms` is, precisely: how far behind the media clock a frame is when it
reaches the pipeline. The first frame sets the baseline, and every frame after
it is compared against where the sample count says it should have arrived. A
frame carrying 20 ms of audio is expected 20 ms after the one before it; if it
turns up 35 ms later, 15 ms of network jitter or buffering has crept in, and
`net_ms` reports the running total.

What it deliberately is not: absolute one-way network latency. That needs the
browser and the server to share a clock, which they do not. The absolute figure
comes from the round trip in `tools/echo_probe.py`, and 4.3 pairs this with the
WebRTC RTT to split it into directions.

`call_id` is minted per connection here. From 3.6 the orchestrator mints it
instead and it ties the browser click, the trace and the audit rows together —
this module only needs it to be the same value for the life of one call.
"""

import statistics
import time

from loguru import logger
from pipecat.frames.frames import Frame, InputAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Per-frame lines are TRACE because there are fifty of them a second; the
# periodic summary at INFO is the one you actually read. AGENT_LOG_LEVEL=TRACE
# turns the individual lines on (see main.py).
SUMMARY_EVERY_SECS = 2.0


class FrameTimingProcessor(FrameProcessor):
    """Log `net_ms` for every inbound audio frame, and a summary as it goes."""

    def __init__(self, call_id: str, *, summary_every: float = SUMMARY_EVERY_SECS, **kwargs):
        super().__init__(**kwargs)
        self._call_id = call_id
        self._summary_every = summary_every
        self._baseline: float | None = None
        self._sample_rate = 0
        self._samples = 0
        self._window: list[float] = []
        self._window_opened = 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Time inbound audio, then pass everything through untouched."""
        if isinstance(frame, InputAudioRawFrame):
            self._measure(frame)
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

    def _measure(self, frame: InputAudioRawFrame) -> None:
        now = time.monotonic()

        if self._baseline is None:
            # The first frame defines "on time", so its own net_ms is 0 and the
            # transport's startup cost is excluded rather than smeared in.
            self._baseline = now
            self._window_opened = now
            self._sample_rate = frame.sample_rate

        expected = self._samples / self._sample_rate
        net_ms = ((now - self._baseline) - expected) * 1000
        self._samples += frame.num_frames

        logger.trace("call_id={} net_ms={:.1f}", self._call_id, net_ms)
        self._window.append(net_ms)

        if now - self._window_opened >= self._summary_every:
            self._flush(now)

    def _flush(self, now: float) -> None:
        ordered = sorted(self._window)
        p95 = ordered[min(int(len(ordered) * 0.95), len(ordered) - 1)]
        logger.info(
            "call_id={} frames={} net_ms p50={:.1f} p95={:.1f} max={:.1f}",
            self._call_id,
            len(ordered),
            statistics.median(ordered),
            p95,
            ordered[-1],
        )
        self._window.clear()
        self._window_opened = now
