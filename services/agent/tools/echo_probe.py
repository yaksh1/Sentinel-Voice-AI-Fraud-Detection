"""Measure the agent's audio round trip without a pair of ears (PLAN 1.1).

Connects to /api/offer as a real WebRTC peer, sends silence with periodic
440 Hz bursts, and times how long each burst takes to come back. 1.1's done-when
is "you hear yourself with < 300 ms delay", which is a judgement call; this
turns it into a number that can be re-run after any pipeline change.

    uv run python services/agent/tools/echo_probe.py [port]

Read the result as a round trip, and as an upper bound. Roughly 160 ms of it is
this script's own aiortc stack — jitter buffer and opus on both ends of the
loop, measured against a bare aiortc relay with no pipeline in it. A browser's
WebRTC implementation is better tuned than aiortc's, so what you hear at /dev
should be comfortably below what this prints.
"""

import asyncio
import fractions
import math
import statistics
import sys
import time

import av
import httpx
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError, MediaStreamTrack

RATE = 48000
SAMPLES = 960  # 20 ms
TONE_HZ = 440
WARMUP_S = 4.0  # the pipeline starts only after the SDP answer; skip that window
SILENCE_S = 1.0
BURST_S = 0.20
GAP_S = 0.8
BURSTS = 8

sent_at: list[float] = []
recv_at: list[float] = []


class Tone(MediaStreamTrack):
    """Silence with a periodic tone burst, paced to real time."""

    kind = "audio"

    def __init__(self):
        super().__init__()
        self._n = 0
        self._start = None
        self._armed = True

    async def recv(self):
        if self._start is None:
            self._start = time.monotonic()
        target = self._start + self._n * SAMPLES / RATE
        if (wait := target - time.monotonic()) > 0:
            await asyncio.sleep(wait)

        t = self._n * SAMPLES / RATE - WARMUP_S
        cycle = SILENCE_S + BURST_S + GAP_S
        phase = t % cycle if t >= 0 else 0.0
        burst_index = int(t // cycle) if t >= 0 else -1

        if t >= 0 and SILENCE_S <= phase < SILENCE_S + BURST_S and burst_index < BURSTS:
            idx = np.arange(self._n * SAMPLES, (self._n + 1) * SAMPLES)
            data = (0.5 * np.sin(2 * math.pi * TONE_HZ * idx / RATE) * 32767).astype(np.int16)
            if self._armed:
                sent_at.append(time.monotonic())
                self._armed = False
        else:
            data = np.zeros(SAMPLES, dtype=np.int16)
            if phase < SILENCE_S:
                self._armed = True

        frame = av.AudioFrame.from_ndarray(data.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = RATE
        frame.pts = self._n * SAMPLES
        frame.time_base = fractions.Fraction(1, RATE)
        self._n += 1
        return frame


async def listen(track):
    """Stamp the arrival of each returning burst, until the track closes."""
    armed = True
    try:
        while True:
            frame = await track.recv()
            rms = float(np.sqrt(np.mean(frame.to_ndarray().astype(np.float32) ** 2)))
            if rms > 2000 and armed:
                recv_at.append(time.monotonic())
                armed = False
            elif rms < 200:
                armed = True
    except MediaStreamError:
        pass  # expected: the run ended and the peer connection was closed


async def main(port: int):
    pc = RTCPeerConnection()
    pc.addTrack(Tone())
    pc.on("track", lambda track: asyncio.ensure_future(listen(track)))

    await pc.setLocalDescription(await pc.createOffer())
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"http://127.0.0.1:{port}/api/offer",
            json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
            timeout=30,
        )
        res.raise_for_status()
        answer = res.json()

    print(f"connected: {answer['pc_id']}")
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))

    await asyncio.sleep(WARMUP_S + BURSTS * (SILENCE_S + BURST_S + GAP_S) + 2)
    await pc.close()

    # Pair each echo with the most recent burst preceding it. Pairing by index
    # instead silently adds a whole cycle whenever one burst is dropped.
    latencies = sorted(
        (r - max(prior)) * 1000
        for r in recv_at
        if (prior := [s for s in sent_at if 0 < r - s < GAP_S])
    )

    print(f"bursts sent={len(sent_at)} echoed={len(recv_at)} matched={len(latencies)}")
    if not latencies:
        sys.exit("FAIL: nothing came back")
    print(
        f"round trip: median {statistics.median(latencies):.0f} ms  "
        f"min {latencies[0]:.0f} ms  max {latencies[-1]:.0f} ms"
    )


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 8003))
