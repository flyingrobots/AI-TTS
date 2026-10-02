# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Real ring/spool correctness and service times, with an owned PCM source and no device."""

import time
import wave
from pathlib import Path

from aitts.streaming import SpoolingPCMStream
from scripts.benchmarks.cases import require

PCM = bytes(range(256)) * 375  # Two seconds of distinguishable PCM16; never sent to speakers.


def round_trip(root: Path) -> dict[str, float]:
    """Generate while held, drain exactly, seek backward, and inspect the durable WAV."""
    path = root / "pcm.wav"
    source = SpoolingPCMStream(path, capacity_frames=2400)
    try:
        starved = source.read(240)
        require(
            not starved.pcm and starved.position_frames == 0 and not starved.ended,
            "underflow neither advances source nor reports EOF",
        )
        began = time.perf_counter_ns()
        for offset in range(0, len(PCM), 4800):
            source.append(PCM[offset : offset + 4800])
        producer_ms = (time.perf_counter_ns() - began) / 1_000_000
        source.seal()
        require(not source.read(0).ended, "seal alone cannot publish playback EOF")
        source.finish()
        restored = bytearray()
        began = time.perf_counter_ns()
        for _ in range(20):
            require(source.wait_buffered(2400, timeout=1), "bounded feeder makes progress")
            restored.extend(source.read(2400).pcm)
        drain_ms = (time.perf_counter_ns() - began) / 1_000_000
        require(bytes(restored) == PCM, "held synthesis and overflow preserve every PCM byte")
        require(source.read(1).ended, "only published complete source reaches EOF")
        began = time.perf_counter_ns()
        source.seek(9000)  # 375 ms at 24 kHz.
        require(source.wait_buffered(2400, timeout=1), "seek refill makes progress")
        replay = source.read(2400)
        seek_ms = (time.perf_counter_ns() - began) / 1_000_000
        require(
            replay.pcm == PCM[18000:22800] and replay.position_frames == 11400,  # noqa: PLR2004 - exact source-frame oracle
            "backward seek restores exact PCM and source clock",
        )
    finally:
        source.close()
    with wave.open(str(path), "rb") as wav:
        require(wav.readframes(wav.getnframes()) == PCM, "durable WAV equals generated PCM")
    return {
        "producer_while_held.wall_ms": producer_ms,
        "drain.wall_ms": drain_ms,
        "seek.wall_ms": seek_ms,
        "witnesses": 27,
    }
