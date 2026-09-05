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
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from aitts.application.playback_schedule import PlaybackCheckpoint
from aitts.model import State

if TYPE_CHECKING:
    from aitts.application.playback_schedule import PlaybackSchedulePort
    from aitts.model import Utterance, UtteranceSegment
    from aitts.store import Store

log = logging.getLogger(__name__)
PLAYBACK_RATES = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)


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


class SoundDeviceSink:
    """Real audio output through PortAudio, one stream at a time."""

    _BLOCK_FRAMES = 2048

    def __init__(self) -> None:
        """Create the sink; nothing is opened until :meth:`start`."""
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
        import numpy as np  # noqa: PLC0415 - keep array setup on the audio thread
        import sounddevice as sd  # noqa: PLC0415 - keep audio deps out of test imports
        import soundfile as sf  # noqa: PLC0415

        assert callable(signal_end)  # noqa: S101 - internal invariant
        try:
            with sf.SoundFile(str(path)) as audio:
                self._samplerate = int(audio.samplerate)
                source_frame = float(int(position_ms / 1000 * audio.samplerate))
                self._set_position_ms(source_frame / self._samplerate * 1000)
                with sd.OutputStream(
                    samplerate=audio.samplerate, channels=audio.channels, dtype="float32"
                ) as stream:
                    while not self._stop_flag.is_set() and source_frame < len(audio):
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
                    if not self._stop_flag.is_set() and source_frame >= len(audio):
                        self._natural = True
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - real device failure
            self.error = str(exc) or type(exc).__name__
            log.warning("event=audio_output_failed")
            self._natural = False
        finally:
            signal_end()

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
            elif self._current_id is not None and not self._sink_active and not self.held:
                current = self._current()
                if current is not None and current.state is State.PLAYING:
                    segment = self._store.next_unfinished_segment(current.id)
                    if segment is not None and segment.state is State.READY:
                        self._begin_segment(current, segment, position_ms=0)
                        continue
            self._wake.clear()
            await self._schedule.checkpoint(PlaybackCheckpoint.PLAN_IDLE)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=0.1)

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
        """Hold playback. Synthesis continues; the buffer should fill while paused."""
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

    async def resume(self) -> None:
        """Release the hold and continue (or adopt a restored paused utterance)."""
        self.held = False
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
        """Abandon the current utterance and let the next one begin.

        Skip is a playback decision, not an editorial one: the audio stays
        cached, the history entry records where it stopped, and the input
        queue is untouched.
        """
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

    async def restart_current(self) -> None:
        """Replay the current utterance from its start."""
        if self.held:
            return
        current = self._current()
        if current is None:
            return
        if current.state not in (State.PLAYING, State.PAUSED):  # pragma: no cover
            return
        if self._store.segments(current.id):
            await self._release_sink()
            self._store.restart_segments(current.id)
            self._current_segment_index = None
            first = self._store.next_unfinished_segment(current.id)
            refreshed = self._store.get(current.id)
            if first is not None and refreshed is not None and first.state is State.READY:
                self._begin_segment(refreshed, first, position_ms=0)
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
