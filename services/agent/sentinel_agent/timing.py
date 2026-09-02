"""Per-frame audio arrival timing (PLAN 1.3).

What `net_ms` is, precisely: how far behind the media clock a frame is when it
reaches the pipeline. The first frame sets the baseline, and every frame after
it is compared against where the sample count says it should have arrived. A
frame carrying 20 ms of audio is expected 20 ms after the one before it; if it
turns up 35 ms later, 15 ms of network jitter or buffering has crept in, and
`net_ms` reports the running total.

What it deliberately is not: absolute one-way network latency. That needs the
browser and the server to share a clock, which they do not. The absolute figure
comes from the round trip in `tools/echo_probe.py`.

One line per frame is fifty lines a second, which is what 1.3 asks for and is
usable at this phase. 4.4 turns these into metrics; do not add aggregation here
before then.
"""

import time

from loguru import logger
from pipecat.frames.frames import Frame, InputAudioRawFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class FrameTimingProcessor(FrameProcessor):
    """Log `net_ms` for every inbound audio frame."""

    def __init__(self, call_id: str, **kwargs):
        super().__init__(**kwargs)
        self._call_id = call_id
        self._baseline: float | None = None
        self._sample_rate = 0
        self._samples = 0

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
            self._sample_rate = frame.sample_rate

        expected = self._samples / self._sample_rate
        net_ms = ((now - self._baseline) - expected) * 1000
        self._samples += frame.num_frames

        logger.debug("call_id={} net_ms={:.1f}", self._call_id, net_ms)
