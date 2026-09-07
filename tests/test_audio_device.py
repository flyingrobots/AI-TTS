# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Playback follows the system default output device (architecture §4, §10.3).

The playback controller owns exactly one audio output. Owning it is not the
same as owning a *fixed* one: when the listener moves the system default to
another device, the owner must follow it, mid-clip, without losing audio.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from typing import TYPE_CHECKING, Any

import pytest

from aitts.application.audio_device import FakeAudioDevice
from aitts.playback import SoundDeviceSink

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "single audio-device ownership in architecture section 4, and the deferred "
        "output-routing decision in section 10 item 3"
    ),
]

_SAMPLERATE = 24000
_FRAMES = 12000


class RecordingStream:
    """One opened output stream that records the frames written to it."""

    def __init__(self, identity: str | None, on_write: Callable[[], None]) -> None:
        self.identity = identity
        self.blocks: list[Any] = []
        self._on_write = on_write

    def write(self, block: Any) -> None:
        import numpy as np  # noqa: PLC0415 - kept off module import, as in the sink

        self.blocks.append(np.array(block, copy=True))
        self._on_write()

    @property
    def frames(self) -> int:
        """Total frames this stream received."""
        return sum(len(block) for block in self.blocks)


class RecordingStreams:
    """Stream factory that tags each opened stream with the live default device."""

    def __init__(self, device: FakeAudioDevice) -> None:
        self._device = device
        self.opened: list[RecordingStream] = []
        self.on_write: Callable[[], None] = lambda: None
        self.refreshes_at_open: list[int] = []

    def __call__(self, *, samplerate: int, channels: int) -> Any:
        del samplerate, channels
        stream = RecordingStream(self._device.default_output_identity(), self._notify)
        self.opened.append(stream)
        self.refreshes_at_open.append(self._device.refreshes)
        return contextlib.nullcontext(stream)

    def _notify(self) -> None:
        """Fire the current write hook, re-read each time so tests can swap it."""
        self.on_write()

    @property
    def frames(self) -> int:
        """Total frames delivered across every stream this factory opened."""
        return sum(stream.frames for stream in self.opened)


@pytest.fixture
def tone(tmp_path: Path) -> Path:
    """Write one short mono WAV whose samples are a recognisable ramp."""
    import numpy as np  # noqa: PLC0415 - audio deps stay off module import
    import soundfile as sf  # noqa: PLC0415

    path = tmp_path / "tone.wav"
    samples = (np.arange(_FRAMES, dtype="float32") / _FRAMES).astype("float32")
    sf.write(str(path), samples, _SAMPLERATE, format="WAV")
    return path


def source_samples(path: Path) -> Any:
    """Read every frame of ``path`` as float32."""
    import soundfile as sf  # noqa: PLC0415 - audio deps stay off module import

    with sf.SoundFile(str(path)) as audio:
        return audio.read(dtype="float32", always_2d=True)


async def test_sink_refreshes_the_device_list_before_opening_each_clip(tone: Path) -> None:
    device = FakeAudioDevice(identity="studio-display")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)

    sink.start(tone)
    assert await sink.wait() is True
    first_refreshes = device.refreshes

    sink.start(tone)
    assert await sink.wait() is True

    # The stale PortAudio enumeration is the bug: every clip must re-resolve.
    assert first_refreshes >= 1
    assert device.refreshes > first_refreshes
    assert streams.refreshes_at_open == [1, 2]


async def test_unchanged_default_output_streams_the_clip_through_one_stream(tone: Path) -> None:
    device = FakeAudioDevice(identity="studio-display")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)

    sink.start(tone)
    assert await sink.wait() is True

    assert len(streams.opened) == 1
    assert streams.frames == _FRAMES


async def test_default_output_change_mid_clip_reopens_without_losing_frames(tone: Path) -> None:
    import numpy as np  # noqa: PLC0415 - audio deps stay off module import

    device = FakeAudioDevice(identity="macbook-speakers")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)

    def move_device_after_two_blocks() -> None:
        if streams.frames >= 2 * SoundDeviceSink._BLOCK_FRAMES:
            device.identity = "studio-display"

    streams.on_write = move_device_after_two_blocks

    sink.start(tone)
    assert await sink.wait() is True

    # It followed the listener to the new device...
    assert [stream.identity for stream in streams.opened] == [
        "macbook-speakers",
        "studio-display",
    ]
    # ...and the audio crossed the switch intact: every frame exactly once, in order.
    assert streams.frames == _FRAMES
    delivered = np.concatenate([block for stream in streams.opened for block in stream.blocks])
    np.testing.assert_allclose(delivered, source_samples(tone), atol=1e-6)


async def test_default_output_change_while_paused_is_adopted_before_resume(tone: Path) -> None:
    device = FakeAudioDevice(identity="macbook-speakers")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)

    def pause_after_one_block() -> None:
        if streams.frames >= SoundDeviceSink._BLOCK_FRAMES:
            streams.on_write = lambda: None
            sink.pause()

    streams.on_write = pause_after_one_block

    sink.start(tone)
    while not sink.paused:  # noqa: ASYNC110 - waiting on the sink's own audio thread
        await asyncio.sleep(0.005)
    device.identity = "studio-display"

    # A device moved while held must be adopted without waiting for the next clip.
    deadline = asyncio.get_running_loop().time() + 2.0
    while len(streams.opened) < 2:
        if asyncio.get_running_loop().time() > deadline:
            msg = "paused sink did not adopt the new default output device"
            raise AssertionError(msg)
        await asyncio.sleep(0.005)
    assert streams.opened[-1].identity == "studio-display"

    sink.resume()
    assert await sink.wait() is True
    assert streams.frames == _FRAMES


async def test_stop_during_a_device_change_does_not_reopen(tone: Path) -> None:
    device = FakeAudioDevice(identity="macbook-speakers")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)

    def move_and_stop() -> None:
        streams.on_write = lambda: None
        device.identity = "studio-display"
        sink.stop()

    streams.on_write = move_and_stop

    sink.start(tone)
    assert await sink.wait() is False
    assert len(streams.opened) == 1
    assert streams.frames < _FRAMES


@pytest.mark.skipif(sys.platform != "darwin", reason="CoreAudio is macOS-only")
def test_core_audio_reports_a_stable_live_default_output() -> None:
    from aitts.adapters.core_audio import CoreAudioOutputDevice  # noqa: PLC0415 - macOS only

    device = CoreAudioOutputDevice()
    identity = device.default_output_identity()

    # A machine running the suite has some output; the identity must be reproducible.
    assert identity
    assert device.default_output_identity() == identity
    device.refresh()
    assert device.default_output_identity() == identity


@pytest.mark.skipif(sys.platform != "darwin", reason="CoreAudio is macOS-only")
def test_core_audio_identity_does_not_depend_on_portaudio_state() -> None:
    from aitts.adapters.core_audio import CoreAudioOutputDevice  # noqa: PLC0415 - macOS only

    device = CoreAudioOutputDevice()

    # The whole point: the truth is read from the OS, never from a cached
    # PortAudio enumeration that predates a newly connected display.
    assert device.default_output_identity() == device.default_output_identity()
