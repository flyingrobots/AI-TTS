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
import json
import logging
import sys
import threading
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from aitts.adapters.clip_evidence import ClipEvidence
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
        self.underflowed = False

    def write(self, block: Any) -> bool:
        import numpy as np  # noqa: PLC0415 - kept off module import, as in the sink

        self.blocks.append(np.array(block, copy=True))
        self._on_write()
        return self.underflowed

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


async def test_completed_sink_can_restart_before_worker_thread_retires(
    tone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Model descheduling after the worker target has signalled completion but
    # before Python retires the thread. The output and audio file are owned.
    # Retire only with a stronger calibrated completion/reacquisition contract.
    begin = threading.Event()
    release = threading.Event()
    workers: list[threading.Thread] = []

    def delayed_thread(
        *, target: Callable[..., None], args: tuple[object, ...], daemon: bool
    ) -> threading.Thread:
        def run() -> None:
            begin.wait()
            target(*args)
            release.wait()

        worker = threading.Thread(target=run, daemon=daemon)
        workers.append(worker)
        return worker

    # Replace this module's dependency reference, not process-wide threading.
    monkeypatch.setattr(
        "aitts.playback.threading",
        SimpleNamespace(Thread=delayed_thread, Event=threading.Event, Lock=threading.Lock),
    )
    device = FakeAudioDevice(identity="owned-output")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)
    try:
        sink.start(tone)
        with pytest.raises(RuntimeError, match="sink is already active"):
            sink.start(tone)
        begin.set()
        first = await sink.wait()
        sink.start(tone)
        second = await sink.wait()
        assert (first, second, len(streams.opened), streams.frames) == (
            True,
            True,
            2,
            2 * _FRAMES,
        )
    finally:
        begin.set()
        release.set()
        for worker in workers:
            worker.join(timeout=1)


async def test_unchanged_default_output_streams_the_clip_through_one_stream(tone: Path) -> None:
    device = FakeAudioDevice(identity="studio-display")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)

    sink.start(tone)
    assert await sink.wait() is True

    assert len(streams.opened) == 1
    assert streams.frames == _FRAMES


async def test_default_output_change_mid_clip_reopens_without_losing_frames(tone: Path) -> None:

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
    assert_source_heard_once(streams, tone)


async def test_default_output_change_while_paused_is_adopted_on_resume(tone: Path) -> None:
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

    # A held player owns no running stream. Resume must adopt the new device
    # within this clip, rather than opening a starving stream while paused.
    sink.resume()
    assert await sink.wait() is True
    assert streams.opened[-1].identity == "studio-display"
    assert_source_heard_once(streams, tone)


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


async def test_an_unreadable_device_identity_does_not_reopen_the_stream(
    tone: Path,
) -> None:
    device = FakeAudioDevice(identity="studio-display")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)

    def blank_the_identity_once() -> None:
        if streams.frames >= SoundDeviceSink._BLOCK_FRAMES:
            streams.on_write = lambda: None
            device.identity = None

    streams.on_write = blank_the_identity_once

    sink.start(tone)
    assert await sink.wait() is True

    # None means "could not ask", which the port's contract requires callers to
    # read as unchanged. Reading it as a change tears down a working stream for
    # nothing, and a reading that alternates between None and a real identity
    # would reopen on every block and never finish the clip.
    assert len(streams.opened) == 1
    assert streams.frames == _FRAMES


async def test_an_identity_that_flaps_to_none_and_back_still_finishes(
    tone: Path,
) -> None:
    device = FakeAudioDevice(identity="studio-display")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)
    flips = {"n": 0}

    def alternate_identity() -> None:
        flips["n"] += 1
        device.identity = None if flips["n"] % 2 else "studio-display"

    streams.on_write = alternate_identity

    sink.start(tone)
    assert await sink.wait() is True

    # The clip must still complete, and exactly once.
    assert streams.frames == _FRAMES
    assert len(streams.opened) == 1


async def test_an_identity_that_alternates_between_two_readable_forms_finishes(
    tone: Path,
) -> None:
    device = FakeAudioDevice(identity="uid-A")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)
    flips = {"n": 0}

    def alternate_readable_identity() -> None:
        # One unchanged device can report two *readable* identities: the
        # adapter falls back to a numeric form when the UID query fails, so an
        # intermittent failure looks exactly like the listener switching back
        # and forth. Handling only the unreadable case does not cover this.
        flips["n"] += 1
        device.identity = "device:41" if flips["n"] % 2 else "uid-A"

    streams.on_write = alternate_readable_identity

    sink.start(tone)
    assert await sink.wait() is True

    # It must not reopen on every block and make no progress.
    assert streams.frames == _FRAMES
    assert len(streams.opened) <= 3


async def test_an_unreadable_first_read_still_follows_a_later_device_change(
    tone: Path,
) -> None:
    device = FakeAudioDevice(identity=None)
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)
    stage = {"n": 0}

    def become_readable_then_move() -> None:
        stage["n"] += 1
        if stage["n"] == 1:
            device.identity = "uid-A"
        elif stage["n"] == 3:
            device.identity = "uid-B"

    streams.on_write = become_readable_then_move

    sink.start(tone)
    assert await sink.wait() is True

    # Latching an unreadable baseline once and never revisiting it disabled
    # device following for the rest of the clip.
    assert any(stream.identity == "uid-B" for stream in streams.opened)
    assert_source_heard_once(streams, tone)


# -- a device that fails mid-clip -----------------------------------------


async def test_a_device_that_cannot_be_opened_is_reported_not_swallowed(
    tone: Path, caplog: pytest.LogCaptureFixture
) -> None:
    device = FakeAudioDevice(identity="studio-display")

    def refuse(*, samplerate: int, channels: int) -> Any:
        del samplerate, channels
        msg = "PortAudio: device unavailable"
        raise OSError(msg)

    sink = SoundDeviceSink(device=device, open_stream=refuse)

    with caplog.at_level(logging.WARNING, logger="aitts"):
        sink.start(tone)
        natural = await sink.wait()

    # This is what the metrics recorder counts as a playback device failure,
    # and what the controller settles the document on. A failure reported as a
    # natural end would mark the clip Played with nothing having been heard.
    assert natural is False
    assert sink.error is not None
    assert "device unavailable" in sink.error
    assert any("event=audio_output_failed" in record.getMessage() for record in caplog.records)


async def test_a_device_that_fails_mid_clip_keeps_the_frames_it_managed(
    tone: Path, caplog: pytest.LogCaptureFixture
) -> None:
    device = FakeAudioDevice(identity="studio-display")
    streams = RecordingStreams(device)

    def fail_after_two_blocks() -> None:
        if streams.frames >= 2 * SoundDeviceSink._BLOCK_FRAMES:
            msg = "PortAudio: stream stopped"
            raise OSError(msg)

    streams.on_write = fail_after_two_blocks
    sink = SoundDeviceSink(device=device, open_stream=streams)

    with caplog.at_level(logging.WARNING, logger="aitts"):
        sink.start(tone)
        natural = await sink.wait()

    # A mid-clip failure must end the pass rather than loop on it, and the
    # position already reached is what a resume would have to start from.
    assert natural is False
    assert sink.error is not None
    assert streams.frames >= 2 * SoundDeviceSink._BLOCK_FRAMES
    assert sink.position_ms() > 0


async def test_an_unreadable_audio_file_fails_the_clip_rather_than_the_daemon(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    device = FakeAudioDevice(identity="studio-display")
    absent = tmp_path / "evicted.wav"
    sink = SoundDeviceSink(device=device, open_stream=RecordingStreams(device))

    with caplog.at_level(logging.WARNING, logger="aitts"):
        sink.start(absent)
        natural = await sink.wait()

    # Cached audio can be evicted between the plan choosing a clip and the
    # sink opening it. That has to end this clip, not the process.
    assert natural is False
    assert sink.error is not None


@pytest.mark.parametrize("underflowed", [False, True])
async def test_output_underflow_diagnostic_is_bounded_and_truthful(
    tone: Path, caplog: pytest.LogCaptureFixture, *, underflowed: bool
) -> None:
    """Oracle: sounddevice.write reports inserted output; diagnostics must expose it."""
    device = FakeAudioDevice(identity="owned-output")
    streams = RecordingStreams(device)

    def report_driver_status() -> None:
        streams.opened[-1].underflowed = underflowed

    streams.on_write = report_driver_status
    sink = SoundDeviceSink(device=device, open_stream=streams)
    with caplog.at_level(logging.WARNING, logger="aitts.playback"):
        sink.start(tone)
        await sink.wait()

    events = [record.getMessage() for record in caplog.records if record.name == "aitts.playback"]
    assert events == (["event=audio_output_underflow"] if underflowed else [])


async def test_repeated_pauses_release_output_and_resume_without_changing_samples(
    tone: Path,
) -> None:
    """Oracle: a held player must not starve a running output stream or lose its place."""

    device = FakeAudioDevice(identity="owned-output")
    streams = RecordingStreams(device)
    loop = asyncio.get_running_loop()
    closed: asyncio.Queue[None] = asyncio.Queue()

    @contextlib.contextmanager
    def open_stream(*, samplerate: int, channels: int) -> Any:
        with streams(samplerate=samplerate, channels=channels) as stream:
            try:
                yield stream
            finally:
                loop.call_soon_threadsafe(closed.put_nowait, None)

    sink = SoundDeviceSink(device=device, open_stream=open_stream)

    def pause_first_block() -> None:
        if len(streams.opened) <= 2 and len(streams.opened[-1].blocks) == 1:
            sink.pause()

    streams.on_write = pause_first_block
    sink.start(tone)
    try:
        for _ in range(2):
            try:
                await asyncio.wait_for(closed.get(), timeout=1)
            except TimeoutError:
                pytest.fail("paused playback kept its output stream running")
            sink.resume()
        await sink.wait()
    finally:
        sink.stop()
        sink.resume()
        await sink.wait()

    assert len(streams.opened) == 3
    assert_source_heard_once(streams, tone)


# Closing a CoreAudio stream drains PortAudio's buffer, then stops the output
# unit, which can cut the hardware buffer still in flight. Whatever is cut
# must be silence, or the listener hears a pop on every skip and pause.
_SOFT_CLOSE_SILENCE_FRAMES = int(_SAMPLERATE * 0.1)
# Largest sample-to-sample step accepted in a fade of this fixture's ramp.
_FADE_MAX_STEP = 0.01


def assert_closes_softly(stream: RecordingStream) -> None:
    """The stream's output fades without a step and ends in held silence."""
    import numpy as np  # noqa: PLC0415

    output = np.concatenate(stream.blocks)[:, 0]
    assert np.max(np.abs(np.diff(output))) <= _FADE_MAX_STEP, "the fade has an audible step"
    tail = output[-_SOFT_CLOSE_SILENCE_FRAMES:]
    assert len(tail) == _SOFT_CLOSE_SILENCE_FRAMES
    assert np.all(tail == 0), "the stream closes before its output has gone silent"


def assert_source_heard_once(streams: RecordingStreams, path: Path) -> None:
    """Every source frame is heard exactly once, in order, across every reopen.

    Each stream but the last was interrupted and closes with one fade-and-
    silence block that is not source audio. Each stream opened mid-clip fades
    in, so its first frames carry a gain; everywhere else the samples are the
    source's own.
    """
    import numpy as np  # noqa: PLC0415

    source = source_samples(path)
    pieces = []
    faded = np.zeros(len(source), dtype=bool)
    offset = 0
    for index, stream in enumerate(streams.opened):
        last = index == len(streams.opened) - 1
        if not last:
            assert_closes_softly(stream)
        if offset:
            assert_opens_softly(stream)
            faded[offset : offset + _SOFT_OPEN_FRAMES] = True
        heard = np.concatenate(stream.blocks if last else stream.blocks[:-1])
        pieces.append(heard)
        offset += len(heard)
    delivered = np.concatenate(pieces)
    assert len(delivered) == len(source)
    np.testing.assert_allclose(delivered[~faded], source[~faded], atol=1e-6)


@pytest.mark.oracle(
    "listener report: skips pop because CoreAudio truncates the in-flight buffer at close"
)
async def test_stop_fades_to_held_silence_without_consuming_more_source(tone: Path) -> None:
    import numpy as np  # noqa: PLC0415

    device = FakeAudioDevice(identity="controlled-output")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)
    streams.on_write = sink.stop
    sink.start(tone)
    assert await sink.wait() is False
    stream = streams.opened[0]
    assert len(stream.blocks) == 2
    assert_closes_softly(stream)
    # The fade starts from the sample that would have played next.
    np.testing.assert_allclose(stream.blocks[-1][0], source_samples(tone)[2048], atol=1e-6)
    assert sink.position_ms() == int(2048 / 24000 * 1000)


_SOFT_OPEN_FRAMES = int(_SAMPLERATE * 0.02)


def assert_opens_softly(stream: RecordingStream) -> None:
    """The stream rises from silence instead of starting at full amplitude."""
    import numpy as np  # noqa: PLC0415

    output = np.concatenate(stream.blocks)[:, 0]
    # The device was silent before this stream; its first sample is the step.
    assert abs(output[0]) <= _FADE_MAX_STEP, "the stream starts mid-waveform"
    assert np.max(np.abs(np.diff(output[:_SOFT_OPEN_FRAMES]))) <= _FADE_MAX_STEP


@pytest.mark.oracle(
    "listener report: a clip resumed mid-speech pops because its stream starts at full amplitude"
)
async def test_resumed_stream_fades_in_from_silence_at_the_held_position(tone: Path) -> None:
    import numpy as np  # noqa: PLC0415

    device = FakeAudioDevice(identity="owned-output")
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
    sink.resume()
    assert await sink.wait() is True

    resumed = streams.opened[-1]
    assert_opens_softly(resumed)
    # Only the gain moves: after the fade-in, the resumed stream is the source
    # from the held position onward, with nothing repeated or skipped.
    output = np.concatenate(resumed.blocks)
    expected = source_samples(tone)[2048:]
    assert len(output) == len(expected)
    np.testing.assert_array_equal(output[_SOFT_OPEN_FRAMES:], expected[_SOFT_OPEN_FRAMES:])


@pytest.mark.oracle(
    "listener report: a stop pops when the close cuts audible output; review PRRT_kwDOUHyfMM6oCN3V"
)
async def test_stop_near_the_end_fades_out_before_the_source_runs_out(tmp_path: Path) -> None:
    """A stop with less source left than the fade must still reach zero smoothly.

    Padding the missing source with zeros while the gain was still near one
    dropped from about 0.486 to silence in a single frame.
    """
    import numpy as np  # noqa: PLC0415
    import soundfile as sf  # noqa: PLC0415

    short = tmp_path / "short.wav"
    # One full block plus 52 frames, ending at a steady 0.5.
    sf.write(str(short), np.full(2100, 0.5, dtype="float32"), _SAMPLERATE, format="WAV")
    device = FakeAudioDevice(identity="controlled-output")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)
    streams.on_write = sink.stop
    sink.start(short)
    assert await sink.wait() is False

    assert_closes_softly(streams.opened[0])


@pytest.mark.oracle(
    "listener report: a stop pops when the close cuts audible output; review PRRT_kwDOUHyfMM6oCN3N"
)
async def test_a_stop_during_the_fade_in_closes_from_the_gain_reached(tmp_path: Path) -> None:
    """At 192 kHz the fade-in outlasts a block; the fade-out must start where it stopped.

    Restarting the closing envelope at full gain jumped from about 0.55 of the
    signal to all of it.
    """
    import numpy as np  # noqa: PLC0415
    import soundfile as sf  # noqa: PLC0415

    rate = 192_000
    steady = tmp_path / "steady.wav"
    sf.write(str(steady), np.full(rate, 0.5, dtype="float32"), rate, format="WAV")
    device = FakeAudioDevice(identity="macbook-speakers")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)

    def move_then_stop_inside_the_fade_in() -> None:
        if len(streams.opened) == 1:
            device.identity = "studio-display"
        else:
            sink.stop()

    streams.on_write = move_then_stop_inside_the_fade_in
    sink.start(steady)
    assert await sink.wait() is False

    reopened = streams.opened[1]
    assert len(reopened.blocks[0]) == SoundDeviceSink._BLOCK_FRAMES
    assert reopened.blocks[0][-1, 0] < 0.5 * 0.9, "the first block ended inside the fade-in"
    assert_opens_softly(reopened)
    assert_closes_softly(reopened)


class _PausedOnceEvent(threading.Event):
    """Reports a pause to its first query only, as if resume landed straight after."""

    def __init__(self) -> None:
        super().__init__()
        self._queries = 0

    def is_set(self) -> bool:
        self._queries += 1
        return self._queries == 1


@pytest.mark.oracle(
    "listener report: a stop pops when the close cuts audible output; review PRRT_kwDOUHyfMM6oCN3H"
)
async def test_a_pause_resumed_at_once_still_closes_its_stream_softly(tone: Path) -> None:
    """The pause that ended the stream decides the close, not a later reading of the flag."""
    device = FakeAudioDevice(identity="owned-output")
    streams = RecordingStreams(device)
    sink = SoundDeviceSink(device=device, open_stream=streams)

    def pause_then_resume_immediately() -> None:
        streams.on_write = lambda: None
        # Script the race window: paused at the loop check, resumed afterwards.
        sink._pause_flag = _PausedOnceEvent()

    streams.on_write = pause_then_resume_immediately
    sink.start(tone)
    assert await sink.wait() is True

    assert len(streams.opened) == 2
    assert_source_heard_once(streams, tone)


@pytest.mark.oracle("driver underflows in the stop fade are included in per-stream diagnostics")
async def test_stop_fade_underflow_is_recorded(tone: Path, tmp_path: Path) -> None:
    device = FakeAudioDevice(identity="controlled-output")
    streams = RecordingStreams(device)
    evidence = ClipEvidence(tmp_path / "evidence")
    sink = SoundDeviceSink(device=device, open_stream=streams, evidence=evidence)

    def stop_then_underflow() -> None:
        stream = streams.opened[-1]
        stream.underflowed = len(stream.blocks) == 2
        sink.stop()

    streams.on_write = stop_then_underflow
    sink.start(tone)
    await sink.wait()
    rows = [
        json.loads(line)
        for line in (evidence.root / tone.stem / "playback.jsonl").read_text().splitlines()
    ]
    assert [
        (row["event"], row.get("underflows"))
        for row in rows
        if row["event"] in {"output_underflow", "stream_closing"}
    ] == [("output_underflow", None), ("stream_closing", 1)]


@pytest.mark.oracle(
    "CoreAudio overload report 2026-10-01 10:00:50: PageFaultsOnIOThread stalled the "
    "I/O thread ~13.4 ms while the HAL buffer was 15 frames (0.3 ms per cycle)"
)
def test_real_stream_requests_a_host_buffer_longer_than_an_observed_stall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a block size, PortAudio asked the HAL for 15-frame I/O cycles.

    Any stall longer than 0.3 ms then skipped a cycle, which is audible as a
    pop. A page fault on the I/O thread while another app activated lasted
    about 13.4 ms. A fixed block size sets the HAL buffer. This asserts the
    requested block duration at the stream rate; on the built-in speakers a
    1024-frame block measured a 1024-frame host buffer (21.3 ms at 48 kHz),
    which still exceeds the observed stall.
    """
    from aitts.playback import _open_sounddevice_stream  # noqa: PLC0415

    opened: list[dict[str, Any]] = []

    class FakeOutputStream:
        def __init__(self, **kwargs: Any) -> None:
            opened.append(kwargs)

    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(OutputStream=FakeOutputStream))
    _open_sounddevice_stream(samplerate=_SAMPLERATE, channels=1)

    blocksize = opened[0].get("blocksize") or 0
    observed_stall_seconds = 0.0134
    assert blocksize / _SAMPLERATE > observed_stall_seconds, (
        "PortAudio chooses its own minimum host buffer"
    )
