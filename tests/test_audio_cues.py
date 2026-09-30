# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Cue waveform and source-clock contracts, without an audio device."""

import asyncio
import contextlib
import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from aitts.application.audio_device import FakeAudioDevice
from aitts.audio_cues import earcon_pcm
from aitts.playback import FakeSink, SoundDeviceSink
from aitts.store import Store
from aitts.streaming import PCMStreamRenderer, SpoolingPCMStream
from tests.test_audio_device import RecordingStreams
from tests.test_playback import make_composite_ready, playback_controller, start
from tests.test_streaming_pipeline import ManualCallbackDevice


@pytest.mark.small
@pytest.mark.oracle("100 ms 880 Hz mono PCM16 chime, bounded gain and silent endpoints")
def test_earcon_has_expected_duration_pitch_and_envelope() -> None:
    samples = np.frombuffer(earcon_pcm(), dtype="<i2") / 32768.0
    assert len(samples) == 2400
    assert samples[0] == samples[-1] == 0
    assert 0.10 < np.max(np.abs(samples)) <= 0.12
    spectrum = np.abs(np.fft.rfft(samples))
    assert np.argmax(spectrum) * 24000 / len(samples) == 880
    assert np.max(np.abs(np.diff(samples))) < 0.03


@pytest.mark.medium
@pytest.mark.oracle(
    "cue precedes source, leaves cached speech unchanged, and consumes no source time"
)
def test_prefix_precedes_speech_without_advancing_source_clock(tmp_path: Path) -> None:
    path = tmp_path / "speech.wav"
    speech = struct.pack("<1000h", *([4000] * 1000))
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        wav.writeframes(speech)
    original = path.read_bytes()
    source = SpoolingPCMStream.from_cached(path)
    try:
        prefix = struct.pack("<4h", 0, 1000, -1000, 0)
        renderer = PCMStreamRenderer(source, prefix_pcm=prefix)
        assert source.wait_buffered(1000, timeout=1)
        first = renderer.render(2, rate=2.0)
        np.testing.assert_array_equal(first[:, 0], [0, 1000 / 32768])
        assert renderer.position_frames == 0
        assert not renderer.ended
        second = renderer.render(4)
        np.testing.assert_array_equal(second[:2, 0], [-1000 / 32768, 0])
        assert renderer.position_frames == 2
        assert path.read_bytes() == original
        assert renderer.render(4)[-1, 0] == 4000 / 32768
    finally:
        source.close()


@pytest.mark.medium
@pytest.mark.oracle("one cue at new document start; none on resume or contiguous chunks")
@pytest.mark.parametrize("enabled", [False, True])
async def test_document_cue_does_not_repeat_on_pause_or_chunk(
    store: Store, *, enabled: bool
) -> None:
    class CueSink(FakeSink):
        def __init__(self) -> None:
            super().__init__()
            self.prefixes: list[bytes] = []
            self.second_started = asyncio.Event()

        def start(self, path: Path, *, position_ms: int = 0) -> None:
            super().start(path, position_ms=position_ms)
            if len(self.started) == 2:
                self.second_started.set()

        def set_prefix(self, pcm: bytes) -> None:
            self.prefixes.append(pcm)

    sink = CueSink()
    store.set_setting("earcon_enabled", str(enabled).lower())
    make_composite_ready(store, "document", ("first", "second"))
    controller, schedule = playback_controller(store, sink)
    task = await start(controller, schedule)
    try:
        assert sink.prefixes == [earcon_pcm() if enabled else b""]
        await controller.pause()
        await controller.resume()
        assert all(not prefix for prefix in sink.prefixes[1:])
        sink.finish_current()
        async with asyncio.timeout(1):
            await sink.second_started.wait()
        assert len(sink.started) == 2
        assert sink.prefixes[-1] == b""
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await controller.shutdown()


@pytest.mark.medium
@pytest.mark.oracle("file output resamples the cue once, preserves channels and source duration")
async def test_file_sink_emits_cue_once_at_native_rate(tmp_path: Path) -> None:
    path = tmp_path / "stereo.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setparams((2, 2, 48000, 0, "NONE", "not compressed"))
        wav.writeframes(struct.pack("<2h", 8192, -4096) * 480)
    device = FakeAudioDevice()
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)
    sink.set_prefix(struct.pack("<4h", 0, 8192, -8192, 0))
    sink.start(path)
    assert await asyncio.wait_for(sink.wait(), 1)
    first = np.concatenate(streams.opened[0].blocks)
    expected = [0, 0.125, 0.25, 0, -0.25, -0.125, 0, 0]
    np.testing.assert_array_equal(first[:8, 0], expected)
    np.testing.assert_array_equal(first[:8, 1], expected)
    np.testing.assert_array_equal(first[8:], np.tile([0.25, -0.125], (480, 1)))
    assert sink.position_ms() == 10
    sink.start(path)
    assert await asyncio.wait_for(sink.wait(), 1)
    np.testing.assert_array_equal(np.concatenate(streams.opened[1].blocks), first[8:])


@pytest.mark.medium
@pytest.mark.oracle("live output emits cue before speech without consuming source time")
async def test_callback_sink_emits_cue_before_live_speech(tmp_path: Path) -> None:
    device = ManualCallbackDevice()
    source = SpoolingPCMStream(tmp_path / "candidate.wav")
    sink = SoundDeviceSink(device=FakeAudioDevice(), open_callback_stream=device.open)
    try:
        source.append(struct.pack("<480h", *([8192] * 480)))
        source.seal()
        source.finish()
        assert source.wait_buffered(480, timeout=1)
        sink.set_prefix(struct.pack("<240h", *([4096] * 240)))
        sink.start_stream(source, artifact_id="owned")
        assert await asyncio.to_thread(device.opened.wait, 1)
        cue, running = device.block()
        np.testing.assert_array_equal(cue[:, 0], np.full(240, 0.125))
        assert running
        assert sink.position_ms() == 0
        speech, running = device.block()
        assert speech[-1, 0] == 0.25
        assert sink.position_ms() == 10
        device.block()
        device.block()
        assert await asyncio.wait_for(sink.wait(), 1)
    finally:
        sink.stop()
        if device.opened.is_set():
            device.block()
        sink.close_output()
        source.close()
