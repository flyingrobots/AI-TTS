# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The playback controller: the only component permitted to touch audio output.

Playback is strictly serialized and presented in submission order
(architecture.md §2, §4). Overlap is not prevented by convention but by there
being exactly one owner of the device, and that owner is this module.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from aitts.application.audio_device import platform_audio_device
from aitts.application.playback_schedule import PlaybackCheckpoint
from aitts.model import State

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from aitts.application.audio_device import AudioDevicePort
    from aitts.application.playback_schedule import PlaybackSchedulePort
    from aitts.model import Utterance, UtteranceSegment
    from aitts.store import Store

log = logging.getLogger(__name__)
PLAYBACK_RATES = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
# Recorded as the cause of a hold the listener's own voice took.
_LISTENER = "listener_speaking"
# How long the plan loop waits to be woken. notify() is the real signal; these
# bound the safety net, and the ceiling is what keeps an idle daemon quiet.
_PLAN_WAIT_MIN_SECONDS = 0.1
_PLAN_WAIT_MAX_SECONDS = 2.0


@runtime_checkable
class AudioSink(Protocol):
    """One audio output. ``start`` while active is a contract violation."""

    paused: bool
    error: str | None

    def set_rate(self, rate: float) -> None:
        """Change playback rate without replacing the active source."""
        ...

    def start(self, path: Path, *, position_ms: int = 0) -> None:
        """Begin playing the file at ``path`` from ``position_ms``."""
        ...

    def pause(self) -> None:
        """Hold playback, keeping position."""
        ...

    def resume(self) -> None:
        """Continue from the held position."""
        ...

    def stop(self) -> None:
        """Stop playback; :meth:`wait` then returns False."""
        ...

    def position_ms(self) -> int:
        """Return the current position within the playing file."""
        ...

    async def wait(self) -> bool:
        """Block until the current playback ends; True means it reached the end."""
        ...


class FakeSink:
    """An audio sink for tests: no audio, full control, overlap detection."""

    def __init__(self, *, auto_finish_ms: int | None = None) -> None:
        """Create a sink; ``auto_finish_ms`` ends each playback on a timer."""
        self.started: list[Path] = []
        self.start_positions: list[int] = []
        self.overlaps = 0
        self.paused = False
        self.error: str | None = None
        self._active = False
        self._natural = False
        self._position = 0
        self._ended: asyncio.Event = asyncio.Event()
        self._auto_finish_ms = auto_finish_ms
        self.playback_rate = 1.0
        self.rate_changes: list[float] = []

    def set_rate(self, rate: float) -> None:
        """Record an immediate playback-rate change."""
        self.playback_rate = rate
        self.rate_changes.append(rate)

    def start(self, path: Path, *, position_ms: int = 0) -> None:
        """Record the start; count an overlap if something was already active."""
        if self._active:
            self.overlaps += 1
        self.started.append(path)
        self.start_positions.append(position_ms)
        self._active = True
        self.paused = False
        self.error = None
        self._natural = False
        self._position = position_ms
        self._ended = asyncio.Event()
        if self._auto_finish_ms is not None:
            asyncio.get_running_loop().call_later(self._auto_finish_ms / 1000, self.finish_current)

    def finish_current(self) -> None:
        """Simulate the audio reaching its natural end."""
        if not self._active:
            return
        self._active = False
        self._natural = True
        self._ended.set()

    def stop(self) -> None:
        """Stop playback before its end."""
        if not self._active:
            return
        self._active = False
        self._natural = False
        self._ended.set()

    def fail_current(self, message: str) -> None:
        """Simulate an unexpected playback-device failure."""
        if not self._active:
            return
        self._active = False
        self._natural = False
        self.error = message
        self._ended.set()

    def pause(self) -> None:
        """Hold playback."""
        self.paused = True

    def resume(self) -> None:
        """Continue playback."""
        self.paused = False

    def advance_to(self, position_ms: int) -> None:
        """Move the simulated playhead."""
        self._position = position_ms

    def position_ms(self) -> int:
        """Return the simulated playhead."""
        return self._position

    async def wait(self) -> bool:
        """Wait for the current playback to finish or be stopped."""
        await self._ended.wait()
        return self._natural


class OutputStream(Protocol):
    """The one thing playback asks of an opened output stream."""

    def write(self, block: Any) -> None:  # noqa: ANN401 - a numpy block of frames
        """Write one block of frames, blocking until the device accepts it."""
        ...


class OutputStreamFactory(Protocol):
    """Opens one output stream on the current default device."""

    def __call__(self, *, samplerate: int, channels: int) -> AbstractContextManager[OutputStream]:
        """Return a context-managed stream for ``samplerate`` and ``channels``."""
        ...


def _open_sounddevice_stream(
    *, samplerate: int, channels: int
) -> AbstractContextManager[OutputStream]:
    """Open a PortAudio stream on whatever it currently considers default."""
    import sounddevice as sd  # noqa: PLC0415 - keep audio deps out of test imports

    stream = sd.OutputStream(samplerate=samplerate, channels=channels, dtype="float32")
    return cast("AbstractContextManager[OutputStream]", stream)


class SoundDeviceSink:
    """Real audio output through PortAudio, one stream at a time.

    The stream is reopened whenever the OS default output moves, so playback
    follows the listener between devices instead of continuing to a device
    they have already left (architecture §10 item 3).
    """

    _BLOCK_FRAMES = 2048
    # Consecutive readings agreeing on a new device before it is followed.
    # A single disagreeing reading is noise; two in a row is a decision. The
    # same confirmation idea guards the input-activity reading.
    _DEVICE_CHANGE_CONFIRMATIONS = 2

    def __init__(
        self,
        *,
        device: AudioDevicePort | None = None,
        open_stream: OutputStreamFactory | None = None,
    ) -> None:
        """Create the sink; nothing is opened until :meth:`start`."""
        self._device = device if device is not None else platform_audio_device()
        self._open_stream = open_stream if open_stream is not None else _open_sounddevice_stream
        self.paused = False
        self.error: str | None = None
        self._pause_flag = threading.Event()
        self._stop_flag = threading.Event()
        self._samplerate = 24000
        self._natural = False
        self._ended: asyncio.Event = asyncio.Event()
        self._thread: threading.Thread | None = None
        self._rate = 1.0
        self._rate_lock = threading.Lock()
        self._position = 0.0
        self._position_lock = threading.Lock()
        self._opened_on: str | None = None
        self._pending_device: str | None = None
        self._pending_confirmations = 0

    def set_rate(self, rate: float) -> None:
        """Apply ``rate`` to the active stream at its next audio block."""
        if rate <= 0:
            msg = "playback rate must be positive"
            raise ValueError(msg)
        with self._rate_lock:
            self._rate = rate

    def _current_rate(self) -> float:
        with self._rate_lock:
            return self._rate

    def _set_position_ms(self, position_ms: float) -> None:
        with self._position_lock:
            self._position = position_ms

    def start(self, path: Path, *, position_ms: int = 0) -> None:
        """Play ``path`` on the default output device from ``position_ms``."""
        if self._thread is not None and self._thread.is_alive():  # pragma: no cover
            msg = "sink is already active; playback is strictly serialized"
            raise RuntimeError(msg)
        loop = asyncio.get_running_loop()
        self._pause_flag.clear()
        self._stop_flag.clear()
        self.paused = False
        self.error = None
        self._natural = False
        self._set_position_ms(position_ms)
        self._ended = asyncio.Event()
        ended = self._ended

        def signal_end() -> None:
            loop.call_soon_threadsafe(ended.set)

        self._thread = threading.Thread(
            target=self._play_blocking, args=(path, position_ms, signal_end), daemon=True
        )
        self._thread.start()

    def _play_blocking(self, path: Path, position_ms: int, signal_end: object) -> None:
        import soundfile as sf  # noqa: PLC0415 - keep audio deps out of test imports

        assert callable(signal_end)  # noqa: S101 - internal invariant
        try:
            with sf.SoundFile(str(path)) as audio:
                self._samplerate = int(audio.samplerate)
                source_frame = float(int(position_ms / 1000 * audio.samplerate))
                self._set_position_ms(source_frame / self._samplerate * 1000)
                # Each pass owns one device. A pass ends at the end of the file,
                # on stop, or when the listener moves the system default; only
                # the last of those comes back for another pass.
                while not self._stop_flag.is_set() and source_frame < len(audio):
                    source_frame = self._play_on_current_device(audio, source_frame)
                if not self._stop_flag.is_set() and source_frame >= len(audio):
                    self._natural = True
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - real device failure
            self.error = str(exc) or type(exc).__name__
            log.warning("event=audio_output_failed")
            self._natural = False
        finally:
            signal_end()

    def _play_on_current_device(self, audio: Any, source_frame: float) -> float:  # noqa: ANN401
        """Stream from ``source_frame`` until the file ends or the default moves.

        Returns the frame reached, so the caller can resume there on the new
        device without repeating or dropping audio.
        """
        import numpy as np  # noqa: PLC0415 - keep array setup on the audio thread

        # Refreshed with no stream open: re-initializing invalidates live streams.
        self._device.refresh()
        self._opened_on = self._device.default_output_identity()
        with self._open_stream(samplerate=audio.samplerate, channels=audio.channels) as stream:
            while not self._stop_flag.is_set() and source_frame < len(audio):
                if self._device_moved_from(self._opened_on):
                    log.info("event=audio_output_device_changed")
                    return source_frame
                if self._pause_flag.is_set():
                    self._stop_flag.wait(0.05)
                    continue
                rate = self._current_rate()
                remaining = len(audio) - source_frame
                output_frames = min(
                    self._BLOCK_FRAMES,
                    max(1, math.ceil(remaining / rate)),
                )
                source_positions = source_frame + np.arange(output_frames) * rate
                first_source = int(source_frame)
                final_source = min(len(audio) - 1, math.ceil(float(source_positions[-1])))
                audio.seek(first_source)
                source = audio.read(
                    final_source - first_source + 1,
                    dtype="float32",
                    always_2d=True,
                )
                relative_positions = source_positions - first_source
                source_axis = np.arange(len(source))
                block = np.column_stack(
                    [
                        np.interp(relative_positions, source_axis, source[:, channel])
                        for channel in range(audio.channels)
                    ]
                ).astype("float32")
                stream.write(block)
                source_frame = min(float(len(audio)), source_frame + output_frames * rate)
                self._set_position_ms(source_frame / self._samplerate * 1000)
        return source_frame

    def _device_moved_from(self, opened_on: str | None) -> bool:
        """Whether the OS default output has moved away from ``opened_on``.

        An unreadable identity means the platform could not be asked, which the
        port's contract requires be read as unchanged. Reading it as a change
        would tear down a working stream over a transient failure, and a
        reading that alternated between unreadable and real would reopen on
        every block and never finish the clip.
        """
        current = self._device.default_output_identity()
        if current is None:
            self._pending_device = None
            self._pending_confirmations = 0
            return False
        if opened_on is None:
            # The baseline was unreadable when this stream opened. Adopt the
            # first readable answer instead of latching "unknown" for the whole
            # clip, which disabled following entirely.
            self._opened_on = current
            return False
        if current == opened_on:
            self._pending_device = None
            self._pending_confirmations = 0
            return False
        # A change has to hold still before the device is torn down for it. A
        # reading that disagrees once and then agrees again is noise, and
        # acting on every disagreement reopens the stream per audio block.
        if current == self._pending_device:
            self._pending_confirmations += 1
        else:
            self._pending_device = current
            self._pending_confirmations = 1
        if self._pending_confirmations < self._DEVICE_CHANGE_CONFIRMATIONS:
            return False
        self._pending_device = None
        self._pending_confirmations = 0
        return True

    def pause(self) -> None:
        """Hold playback, keeping position."""
        self.paused = True
        self._pause_flag.set()

    def resume(self) -> None:
        """Continue from the held position."""
        self.paused = False
        self._pause_flag.clear()

    def stop(self) -> None:
        """Stop playback before its end."""
        self._stop_flag.set()

    def position_ms(self) -> int:
        """Best-effort playhead position within the current file."""
        with self._position_lock:
            return int(self._position)

    async def wait(self) -> bool:
        """Wait for the current playback to finish or be stopped."""
        await self._ended.wait()
        return self._natural


class PlaybackController:
    """Serializes playback and answers to the user, not to the queue."""

    def __init__(
        self,
        store: Store,
        sink: AudioSink,
        schedule: PlaybackSchedulePort,
        *,
        held: bool = False,
    ) -> None:
        """Wrap ``sink`` and restore the durable global playback hold."""
        self._store = store
        self._sink = sink
        self._schedule = schedule
        raw_rate = store.get_setting("playback_rate", "1.0")
        try:
            restored_rate = float(raw_rate)
        except ValueError:
            restored_rate = 1.0
        self.playback_rate = restored_rate if restored_rate in PLAYBACK_RATES else 1.0
        self._sink.set_rate(self.playback_rate)
        self.held = held or store.get_setting("playback_held", "false") == "true"
        if self.held:
            self._store.set_setting("playback_held", "true")
        self._current_id: str | None = None
        self._current_segment_index: int | None = None
        self._sink_active = False
        self._wake = asyncio.Event()
        self._watcher: asyncio.Task[None] | None = None
        # Releasing the device is an await, so two transport commands can
        # interleave inside it: each captures the same active chunk, and the
        # loser then settles a chunk the winner has moved past and stops the
        # sink the winner just started. They take turns instead.
        self._transport_lock = asyncio.Lock()
        self._idle_wait = _PLAN_WAIT_MIN_SECONDS
        # The hold an interrupt causes is durable, so its reason has to be
        # too: a listener returning to a restarted daemon would otherwise find
        # silence with nothing on screen to explain it. Wall clock, because a
        # monotonic reading means nothing once the process is gone.
        self.interrupted_at = self._restore_interrupted_at()
        # Arming is deliberately not restored: releasing a hold by itself
        # after a restart is a surprise, and the listener never asked twice.
        self.resume_when_input_idle_armed = False
        if self.held:
            paused = self._adoptable_paused()
            if paused is not None:
                self._current_id = paused.id
                segment = self._store.next_unfinished_segment(paused.id)
                if segment is not None and segment.state is State.PAUSED:
                    self._current_segment_index = segment.index

    @property
    def current_id(self) -> str | None:
        """The utterance currently holding the device, if any."""
        return self._current_id

    @property
    def current_segment(self) -> UtteranceSegment | None:
        """Return the exact active child, when the current item is composite."""
        if self._current_id is None or self._current_segment_index is None:
            return None
        return self._store.get_segment(self._current_id, self._current_segment_index)

    def current_segment_position_ms(self) -> int | None:
        """Return child-relative position for captions and segment progress."""
        segment = self.current_segment
        if segment is None:
            return None
        return self._sink.position_ms() if self._sink_active else segment.played_ms

    def current_position_ms(self) -> int | None:
        """Live playhead position for the current utterance, if there is one."""
        if self._current_id is None:
            return None
        if self._current_segment_index is not None:
            completed = self._store.completed_segment_duration_ms(
                self._current_id,
                before=self._current_segment_index,
            )
            if self._sink_active:
                return completed + self._sink.position_ms()
            segment = self._store.get_segment(self._current_id, self._current_segment_index)
            segment_position = 0 if segment is None else segment.played_ms or 0
            return completed + segment_position
        if self._sink_active:
            return self._sink.position_ms()
        current = self._current()
        return current.played_ms if current is not None else None

    def notify(self) -> None:
        """Tell the controller the plan may have changed."""
        self._wake.set()

    def set_playback_rate(self, rate: float) -> None:
        """Persist and immediately apply one supported transport rate."""
        if rate not in PLAYBACK_RATES:
            msg = f"unsupported playback rate {rate}"
            raise ValueError(msg)
        self._sink.set_rate(rate)
        self._store.set_setting("playback_rate", str(rate))
        self.playback_rate = rate

    async def run(self) -> None:
        """Start the next in-order utterance whenever the device is free."""
        while True:
            await self._schedule.checkpoint(PlaybackCheckpoint.BEFORE_PLAN)
            if self._current_id is None and not self.held:
                nxt = self._store.next_pending()
                if nxt is not None and nxt.state is State.READY:
                    segment = self._store.next_unfinished_segment(nxt.id)
                    if segment is not None and segment.state is State.READY:
                        self._begin_segment(nxt, segment, position_ms=0)
                        continue
                    if segment is None and nxt.audio_path is not None:
                        self._begin(nxt.id, Path(nxt.audio_path), position_ms=0)
                        continue
            elif self._current_id is not None and not self._sink_active:
                current = self._current()
                # Release a document that ended while the controller still held
                # it. A parent can reach a terminal state without the watcher
                # running — a later chunk failing to synthesize does it — and
                # holding onto it stalls everything queued behind it forever.
                if current is None or current.is_terminal:
                    log.info("event=terminal_current_released")
                    self._current_id = None
                    self._current_segment_index = None
                    continue
                if not self.held and current.state is State.PLAYING:
                    segment = self._store.next_unfinished_segment(current.id)
                    if segment is not None and segment.state is State.READY:
                        self._begin_segment(current, segment, position_ms=0)
                        continue
            self._wake.clear()
            await self._schedule.checkpoint(PlaybackCheckpoint.PLAN_IDLE)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._idle_wait)
                # Woken by notify(): whatever changed deserves a prompt look,
                # and the next quiet spell starts over from the short wait.
                self._idle_wait = _PLAN_WAIT_MIN_SECONDS
                continue
            # The wait expired with nothing to do. Back off, because this loop
            # is woken by notify() and the timeout is only a safety net; a
            # fixed short wait meant a store query ten times a second for as
            # long as the daemon sat in the menu bar.
            self._idle_wait = min(self._idle_wait * 2, _PLAN_WAIT_MAX_SECONDS)

    def _begin(self, utt_id: str, path: Path, *, position_ms: int) -> None:
        self._store.transition(utt_id, State.PLAYING)
        self._current_id = utt_id
        self._sink.start(path, position_ms=position_ms)
        self._sink_active = True
        self._watcher = asyncio.get_running_loop().create_task(self._watch())

    def _begin_segment(
        self,
        parent: Utterance,
        segment: UtteranceSegment,
        *,
        position_ms: int,
    ) -> None:
        if parent.state in (State.READY, State.PAUSED):
            self._store.transition(parent.id, State.PLAYING)
        self._store.transition_segment(parent.id, segment.index, State.PLAYING)
        self._current_id = parent.id
        self._current_segment_index = segment.index
        if segment.audio_path is None:  # pragma: no cover - Ready requires a published artifact
            msg = "ready segment has no audio artifact"
            raise RuntimeError(msg)
        self._sink.start(Path(segment.audio_path), position_ms=position_ms)
        self._sink_active = True
        self._watcher = asyncio.get_running_loop().create_task(self._watch())

    async def _watch(self) -> None:
        ended = await self._sink.wait()
        await self._schedule.checkpoint(PlaybackCheckpoint.SINK_RESULT)
        if not ended and self._sink.error is None:
            return  # whoever stopped the sink owns the state change
        utt_id = self._current_id
        if utt_id is None:  # pragma: no cover - stop always precedes clearing
            return
        current = self._store.get(utt_id)
        if current is not None and current.state in (State.PLAYING, State.PAUSED):
            if self._current_segment_index is not None:
                self._finish_segment_playback(
                    current,
                    self._current_segment_index,
                    ended=ended,
                )
            elif ended:
                self._store.transition(utt_id, State.PLAYED, played_ms=current.duration_ms)
            else:
                detail = self._sink.error or "unknown failure"
                self._store.transition(
                    utt_id,
                    State.FAILED,
                    error=f"playback device error: {detail}",
                    played_ms=self._sink.position_ms(),
                )
        self._sink_active = False
        self._current_segment_index = None
        self._watcher = None
        after = self._store.get(utt_id)
        document_finished = self._store.next_unfinished_segment(utt_id) is None
        if after is None or after.is_terminal or document_finished:
            self._current_id = None
        self.notify()

    def _finish_segment_playback(
        self,
        parent: Utterance,
        segment_index: int,
        *,
        ended: bool,
    ) -> None:
        segment = self._store.get_segment(parent.id, segment_index)
        if segment is None:  # pragma: no cover - active segment rows remain owned
            return
        if ended:
            self._store.transition_segment(
                parent.id,
                segment.index,
                State.PLAYED,
                played_ms=segment.duration_ms,
            )
            if self._store.next_unfinished_segment(parent.id) is None:
                played_ms = self._store.completed_segment_duration_ms(parent.id)
                self._store.transition(parent.id, State.PLAYED, played_ms=played_ms)
            return
        detail = self._sink.error or "unknown failure"
        position = self._sink.position_ms()
        self._store.transition_segment(
            parent.id,
            segment.index,
            State.FAILED,
            error=f"playback device error: {detail}",
            played_ms=position,
        )
        played_ms = self._store.completed_segment_duration_ms(parent.id) + position
        self._store.transition(
            parent.id,
            State.FAILED,
            error=f"playback device error: {detail}",
            played_ms=played_ms,
        )

    async def _release_sink(self) -> None:
        """Stop playback and wait until the device can be acquired again."""
        watcher = self._watcher
        self._watcher = None
        if watcher is not None:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        if self._sink_active:
            self._sink.stop()
            await self._sink.wait()
            self._sink_active = False

    async def pause(self) -> None:
        """Hold playback. Synthesis continues; the buffer should fill while paused.

        This is the listener asking for silence, so it revokes any pending
        automatic resume and any recorded interruption: their newer, explicit
        request outranks a release armed earlier, and the hold is now theirs
        rather than something their microphone caused.
        """
        await self._hold(reason=None)

    async def _hold(self, *, reason: str | None) -> None:
        """Take the durable playback hold, recording why it was taken."""
        if reason is None:
            self._clear_interruption()
        self.held = True
        self._store.set_setting("playback_held", "true")
        current = self._current()
        if current is not None and current.state is State.PLAYING:
            position = self.current_position_ms()
            if self._sink_active:
                self._sink.pause()
                if self._current_segment_index is not None:
                    self._store.transition_segment(
                        current.id,
                        self._current_segment_index,
                        State.PAUSED,
                        played_ms=self._sink.position_ms(),
                    )
            self._store.transition(current.id, State.PAUSED, played_ms=position)

    def _restore_interrupted_at(self) -> float | None:
        if not self.held or self._store.get_setting("playback_hold_reason", "") != _LISTENER:
            return None
        try:
            return float(self._store.get_setting("playback_hold_at", ""))
        except ValueError:  # pragma: no cover - written as a float by interrupt()
            return None

    async def interrupt(self) -> bool:
        """Hold playback because the listener started speaking.

        Returns whether this call took the floor. A hold the listener already
        set by hand is left exactly as it is: there is nothing to interrupt,
        and reporting one would put a notice on screen they never caused.
        """
        if self.held:
            return False
        await self._hold(reason=_LISTENER)
        self.interrupted_at = time.time()
        self._store.set_setting("playback_hold_reason", _LISTENER)
        self._store.set_setting("playback_hold_at", str(self.interrupted_at))
        return True

    def arm_resume_when_input_idle(self) -> None:
        """Resume by itself once the listener's input goes quiet again."""
        self.resume_when_input_idle_armed = True

    def _clear_interruption(self) -> None:
        self.interrupted_at = None
        self.resume_when_input_idle_armed = False
        self._store.set_setting("playback_hold_reason", "")

    async def resume(self) -> None:
        """Release the hold and continue (or adopt a restored paused utterance)."""
        self.held = False
        self._clear_interruption()
        self._store.set_setting("playback_held", "false")
        current = self._current()
        if current is None:
            current = self._adoptable_paused()
            if current is not None:
                self._current_id = current.id
        if current is not None and current.state is State.PAUSED:
            if self._sink_active:
                self._sink.resume()
                if self._current_segment_index is not None:
                    self._store.transition_segment(
                        current.id,
                        self._current_segment_index,
                        State.PLAYING,
                    )
                self._store.transition(current.id, State.PLAYING)
            elif (segment := self._store.next_unfinished_segment(current.id)) is not None:
                if segment.state is State.PAUSED and segment.audio_path is not None:
                    self._begin_segment(current, segment, position_ms=segment.played_ms or 0)
                else:
                    self._store.transition(current.id, State.PLAYING)
            elif current.audio_path is not None:
                self._begin(
                    current.id,
                    Path(current.audio_path),
                    position_ms=current.played_ms or 0,
                )
        self.notify()

    async def skip(self) -> None:
        """Take the transport lock, then run the step; see :attr:`_transport_lock`."""
        async with self._transport_lock:
            await self._skip_locked()

    async def _skip_locked(self) -> None:
        """Abandon the current utterance and let the next one begin.

        Skip is a playback decision, not an editorial one: the audio stays
        cached, the history entry records where it stopped, and the input
        queue is untouched.
        """
        self._clear_interruption()
        current = self._current()
        if current is not None and current.state in (State.PLAYING, State.PAUSED):
            document_position = self.current_position_ms() or 0
            segment_position = (
                self._sink.position_ms() if self._sink_active else current.played_ms or 0
            )
            segment_index = self._current_segment_index
            await self._release_sink()
            if self._store.segments(current.id):
                self._store.skip_segments(current.id, segment_index, segment_position)
            self._store.transition(current.id, State.SKIPPED, played_ms=document_position)
            self._current_id = None
            self._current_segment_index = None
        self.notify()

    async def next_segment(self) -> bool:
        """Take the transport lock, then run the step; see :attr:`_transport_lock`."""
        async with self._transport_lock:
            return await self._next_segment_locked()

    async def _next_segment_locked(self) -> bool:
        """Give up the current chunk and move to the next one in the document.

        Skip abandons the whole queue entry; this abandons one chunk of it, so
        it declines on the last chunk rather than quietly becoming Skip.
        """
        target = self._navigable_segment_index()
        if target is None:
            return False
        current, index = target
        if index + 1 >= len(self._store.segments(current.id)):
            return False
        position = self._sink.position_ms() if self._sink_active else 0
        await self._release_sink()
        self._store.transition_segment(current.id, index, State.SKIPPED, played_ms=position)
        self._current_segment_index = None
        self._resume_document_at_next_ready(current.id)
        self.notify()
        return True

    async def previous_segment(self) -> bool:
        """Take the transport lock, then run the step; see :attr:`_transport_lock`."""
        async with self._transport_lock:
            return await self._previous_segment_locked()

    async def _previous_segment_locked(self) -> bool:
        """Replay the chunk before the current one, from its beginning."""
        target = self._navigable_segment_index()
        if target is None:
            return False
        current, index = target
        if index == 0:
            return False
        # Decide before releasing the device. The plan loop only ever starts a
        # Ready child, so a document left Playing with no Ready child and no
        # active sink is silent for good.
        previous = self._store.get_segment(current.id, index - 1)
        if previous is None or previous.audio_path is None:
            return False
        await self._release_sink()
        if not self._store.reset_segments_from(current.id, index - 1):
            # The artifact was there a moment ago. Put the document back on the
            # device rather than leaving it wedged.
            self._restore_after_failed_step(current.id, index)
            return False
        self._current_segment_index = None
        self._resume_document_at_next_ready(current.id)
        self.notify()
        return True

    def _navigable_segment_index(self) -> tuple[Utterance, int] | None:
        """Return the document and active chunk when chunk stepping applies."""
        if self.held:
            return None
        current = self._current()
        if current is None or self._current_segment_index is None:
            return None
        if not self._store.segments(current.id):  # pragma: no cover - index implies children
            return None
        return current, self._current_segment_index

    def _restore_after_failed_step(self, utt_id: str, index: int) -> None:
        """Return the device to a document whose transport step could not land.

        Releasing the sink is not reversible, so the child that was playing is
        reopened and handed back to the plan loop. Anything else leaves the
        document reporting Playing with silence coming out of it.
        """
        if self._store.reset_segments_from(utt_id, index):
            self._current_segment_index = None
            self._resume_document_at_next_ready(utt_id)
            self.notify()
            return
        # Nothing replayable is left at all; settle the document rather than
        # holding a queue slot open forever.
        played = self._store.completed_segment_duration_ms(utt_id)
        with contextlib.suppress(Exception):
            self._store.transition(
                utt_id,
                State.FAILED,
                error="playback stopped: no cached audio remains for this document",
                played_ms=played,
            )
        log.warning("event=document_playback_unrecoverable")
        self._current_id = None
        self._current_segment_index = None
        self.notify()

    def _resume_document_at_next_ready(self, utt_id: str) -> None:
        """Start the next playable chunk now, or leave it to the plan loop."""
        segment = self._store.next_unfinished_segment(utt_id)
        parent = self._store.get(utt_id)
        if segment is None or parent is None:
            return
        if self.held:
            # A hold arrived while the device was being released, which the
            # step could not have seen when it checked. Leave the document
            # resumable instead of starting audio through the hold.
            if parent.state is State.PLAYING:
                self._store.transition(parent.id, State.PAUSED, played_ms=parent.played_ms or 0)
            return
        if segment.state is State.READY:
            self._begin_segment(parent, segment, position_ms=0)

    async def restart_current(self) -> None:
        """Take the transport lock, then run the step; see :attr:`_transport_lock`."""
        async with self._transport_lock:
            await self._restart_current_locked()

    async def _restart_current_locked(self) -> None:
        """Replay the current utterance from its start."""
        if self.held:
            return
        current = self._current()
        if current is None:
            return
        if current.state not in (State.PLAYING, State.PAUSED):  # pragma: no cover
            return
        if self._store.segments(current.id):
            active = self._current_segment_index
            await self._release_sink()
            self._store.restart_segments(current.id)
            self._current_segment_index = None
            first = self._store.next_unfinished_segment(current.id)
            refreshed = self._store.get(current.id)
            if first is not None and refreshed is not None and first.state is State.READY:
                self._begin_segment(refreshed, first, position_ms=0)
            elif active is not None:
                # restart_segments only reopens children whose audio survives;
                # if none did, the device was released for nothing.
                self._restore_after_failed_step(current.id, active)
            self.notify()
            return
        if current.audio_path is None:
            return
        await self._release_sink()
        if current.state is State.PAUSED:
            self._store.transition(current.id, State.PLAYING)
        self._sink.start(Path(current.audio_path), position_ms=0)
        self._sink_active = True
        self._watcher = asyncio.get_running_loop().create_task(self._watch())
        self.notify()

    def _current(self) -> Utterance | None:
        if self._current_id is None:
            return None
        return self._store.get(self._current_id)

    def _adoptable_paused(self) -> Utterance | None:
        for utt in self._store.playback_queue():
            if utt.state is State.PAUSED:
                return utt
        return None
