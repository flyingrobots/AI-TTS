# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The callback path closes and opens streams as softly as the file sink does.

Once output is prepared, every compatible WAV plays through the callback path,
so the soft close and open rules from the September 30 soft-stream-close fix
(docs/testing-evidence/2026-09-30-soft-stream-close.md) must hold here too.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
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


def rising_cosine(frames: int) -> np.ndarray:
    return 0.5 * (1 - np.cos(np.linspace(0.0, np.pi, frames)))


_HELD_MS = 500
_HELD_FRAME = _HELD_MS * SAMPLE_RATE // 1000


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


async def test_a_mid_clip_open_fades_in_from_silence_at_the_held_position(
    tmp_path: Path,
) -> None:
    samples = tone(SAMPLE_RATE)
    device = BlockDevice()
    source = SpoolingPCMStream(tmp_path / "candidate.wav")
    sink = SoundDeviceSink(device=FakeAudioDevice(), open_callback_stream=device.open)
    try:
        source.append(samples.tobytes())
        sink.start_stream(source, artifact_id="resume", position_ms=_HELD_MS)
        assert await asyncio.to_thread(device.opened.wait, 1)
        assert source.wait_buffered(_BLOCK + 1, timeout=1)
        opening, running = device.block_of(_BLOCK)
        assert running is True
        heard = samples[_HELD_FRAME : _HELD_FRAME + _BLOCK] / 32768.0
        np.testing.assert_allclose(
            opening[:_FADE, 0],
            heard[:_FADE] * rising_cosine(_FADE),
            atol=1e-6,
            err_msg="a stream opened mid-clip must fade in over 20 ms from exact zero",
        )
        np.testing.assert_allclose(opening[_FADE:, 0], heard[_FADE:], atol=1e-6)
    finally:
        sink.stop()
        source.release()


async def test_a_stop_during_the_fade_in_closes_from_the_gain_reached(tmp_path: Path) -> None:
    samples = tone(SAMPLE_RATE)
    device = BlockDevice()
    source = SpoolingPCMStream(tmp_path / "candidate.wav")
    sink = SoundDeviceSink(device=FakeAudioDevice(), open_callback_stream=device.open)
    partial = _FADE // 2
    try:
        source.append(samples.tobytes())
        sink.start_stream(source, artifact_id="interrupted", position_ms=_HELD_MS)
        assert await asyncio.to_thread(device.opened.wait, 1)
        assert source.wait_buffered(_BLOCK + 1, timeout=1)
        device.block_of(partial)
        sink.stop()
        closing, _ = device.block_of(_BLOCK)
        start = _HELD_FRAME + partial
        upcoming = samples[start : start + _FADE] / 32768.0
        reached = rising_cosine(_FADE)[partial]
        np.testing.assert_allclose(
            closing[:_FADE, 0],
            upcoming * reached * falling_cosine(_FADE),
            atol=1e-6,
            err_msg="the close must start from the gain the fade-in had reached",
        )
    finally:
        sink.stop()
        source.release()


# The host buffer measured with main's fix, 1024 frames at 48 kHz.
_HOST_BUFFER_TARGET_SECONDS = 1024 / 48_000


@pytest.mark.oracle(
    "CoreAudio overload report 2026-10-01 10:00:50: PageFaultsOnIOThread stalled the "
    "I/O thread ~13.4 ms; measured: the HAL buffer equals the requested block in "
    "device-rate frames, for a 24 kHz callback stream too (240 -> 5 ms, 1024 -> 21.3 ms)"
)
@pytest.mark.parametrize("device_rate", [44_100, 48_000, 96_000, 192_000])
def test_callback_stream_requests_a_host_buffer_longer_than_an_observed_stall(
    monkeypatch: pytest.MonkeyPatch, device_rate: int
) -> None:
    """The callback stream carries every prepared clip, so it needs main's host buffer."""
    # Retire only if the callback stream stops being the prepared output path.
    from aitts.playback import _open_pcm_callback_stream  # noqa: PLC0415

    opened: list[dict[str, Any]] = []

    class FakeOutputStream:
        def __init__(self, **kwargs: Any) -> None:
            opened.append(kwargs)

    def query_devices(*, kind: str) -> dict[str, Any]:
        assert kind == "output"
        return {"default_samplerate": float(device_rate)}

    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(
            OutputStream=FakeOutputStream, query_devices=query_devices, CallbackStop=Exception
        ),
    )
    _open_pcm_callback_stream(
        samplerate=SAMPLE_RATE, channels=1, render=lambda *_: True, finished=lambda: None
    )

    assert len(opened) == 1, "no output stream was constructed"
    assert opened[0]["samplerate"] == SAMPLE_RATE
    assert callable(opened[0]["callback"])
    host_buffer_seconds = (opened[0].get("blocksize") or 0) / device_rate
    assert host_buffer_seconds >= _HOST_BUFFER_TARGET_SECONDS, (
        f"the host buffer must last at least {_HOST_BUFFER_TARGET_SECONDS * 1000:.1f} ms "
        f"at the device's {device_rate} Hz; requested {host_buffer_seconds * 1000:.1f} ms"
    )
