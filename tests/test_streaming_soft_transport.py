# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The callback path closes and opens streams as softly as the file sink does.

Once output is prepared, every compatible WAV plays through the callback path,
so the soft close and open rules from the September 30 soft-stream-close fix
(docs/testing-evidence/2026-09-30-soft-stream-close.md) must hold here too.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from aitts.application.audio_device import FakeAudioDevice
from aitts.playback import SoundDeviceSink
from aitts.streaming import SAMPLE_RATE, SpoolingPCMStream
from tests.test_streaming_pipeline import ManualCallbackDevice

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "soft-stream-close receipt: a mid-clip close holds the next 20 ms of source under a "
        "raised cosine without moving the playhead, then 100 ms of silence before a device "
        "close; a mid-clip open fades in over 20 ms from exact zero"
    ),
]

_FADE = SAMPLE_RATE // 50  # 20 ms
_CLOSE_SILENCE = SAMPLE_RATE // 10  # 100 ms
_BLOCK = 1024  # a host-sized callback block, longer than the fade


class BlockDevice(ManualCallbackDevice):
    """A manual callback device whose blocks have a chosen length."""

    def block_of(self, frames: int) -> tuple[Any, bool]:
        output = np.empty((frames, 1), dtype=np.float32)
        running = self.render(output, frames, False)  # noqa: FBT003 - callback contract includes driver underflow
        if not running:
            self.finished()
        return output, running


def tone(frames: int) -> np.ndarray:
    """A 100 Hz tone that never starts on an exact zero, quantized like engine PCM."""
    t = np.arange(frames) / SAMPLE_RATE
    return np.round(0.25 * np.sin(2 * np.pi * 100 * t + 0.5) * 32768).astype("<i2")


def falling_cosine(frames: int) -> np.ndarray:
    return 0.5 * (1 + np.cos(np.linspace(0.0, np.pi, frames)))


async def test_stop_fades_the_upcoming_source_then_holds_silence_before_closing(
    tmp_path: Path,
) -> None:
    samples = tone(SAMPLE_RATE)
    device = BlockDevice()
    source = SpoolingPCMStream(tmp_path / "candidate.wav")
    sink = SoundDeviceSink(device=FakeAudioDevice(), open_callback_stream=device.open)
    try:
        source.append(samples.tobytes())
        sink.start_stream(source, artifact_id="soft-close")
        assert await asyncio.to_thread(device.opened.wait, 1)
        assert source.wait_buffered(_BLOCK + _FADE + 1, timeout=1)
        _, running = device.block_of(_BLOCK)
        assert running is True
        held = sink.position_ms()
        sink.stop()
        closing, running = device.block_of(_BLOCK)
        upcoming = samples[_BLOCK : _BLOCK + _FADE] / 32768.0
        np.testing.assert_allclose(
            closing[:_FADE, 0],
            upcoming * falling_cosine(_FADE),
            atol=1e-6,
            err_msg="the close must fade the next 20 ms of source, not ramp the last sample",
        )
        assert not closing[_FADE:].any()
        assert sink.position_ms() == held, "the fade must not move the playhead"
        silent = _BLOCK - _FADE
        for _ in range(10):
            if not running:
                break
            block, running = device.block_of(_BLOCK)
            assert not block.any()
            silent += _BLOCK
        assert running is False
        assert silent >= _CLOSE_SILENCE, "the stream closed before 100 ms of silence"
        assert await asyncio.wait_for(sink.wait(), timeout=1) is False
    finally:
        sink.stop()
        source.release()


async def test_stop_near_the_end_holds_the_last_sample_under_the_fade(tmp_path: Path) -> None:
    tail = 100
    samples = tone(_BLOCK + tail)
    device = BlockDevice()
    source = SpoolingPCMStream(tmp_path / "candidate.wav")
    sink = SoundDeviceSink(device=FakeAudioDevice(), open_callback_stream=device.open)
    try:
        source.append(samples.tobytes())
        source.seal()
        source.finish()
        sink.start_stream(source, artifact_id="short-tail")
        assert await asyncio.to_thread(device.opened.wait, 1)
        assert source.wait_buffered(_BLOCK + tail, timeout=1)
        _, running = device.block_of(_BLOCK)
        assert running is True
        sink.stop()
        closing, _ = device.block_of(_BLOCK)
        remaining = samples[_BLOCK:] / 32768.0
        held = np.concatenate([remaining, np.full(_FADE - tail, remaining[-1])])
        np.testing.assert_allclose(
            closing[:_FADE, 0],
            held * falling_cosine(_FADE),
            atol=1e-6,
            err_msg="with less source than fade, the last sample is held under the envelope",
        )
    finally:
        sink.stop()
        source.release()
