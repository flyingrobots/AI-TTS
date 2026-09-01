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
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from aitts.model import State

if TYPE_CHECKING:
    from aitts.model import Utterance
    from aitts.store import Store

log = logging.getLogger(__name__)


@runtime_checkable
class AudioSink(Protocol):
    """One audio output. ``start`` while active is a contract violation."""

    paused: bool

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
        self._active = False
        self._natural = False
        self._position = 0
        self._ended: asyncio.Event = asyncio.Event()
        self._auto_finish_ms = auto_finish_ms

    def start(self, path: Path, *, position_ms: int = 0) -> None:
        """Record the start; count an overlap if something was already active."""
        if self._active:
            self.overlaps += 1
        self.started.append(path)
        self.start_positions.append(position_ms)
        self._active = True
        self.paused = False
        self._natural = False
        self._position = position_ms
        self._ended = asyncio.Event()
        if self._auto_finish_ms is not None:
            asyncio.get_running_loop().call_later(
                self._auto_finish_ms / 1000, self.finish_current
            )

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
        self._pause_flag = threading.Event()
        self._stop_flag = threading.Event()
        self._frames_played = 0
        self._samplerate = 24000
        self._natural = False
        self._ended: asyncio.Event = asyncio.Event()
        self._thread: threading.Thread | None = None
        self._start_ms = 0

    def start(self, path: Path, *, position_ms: int = 0) -> None:
        """Play ``path`` on the default output device from ``position_ms``."""
        if self._thread is not None and self._thread.is_alive():  # pragma: no cover
            msg = "sink is already active; playback is strictly serialized"
            raise RuntimeError(msg)
        loop = asyncio.get_running_loop()
        self._pause_flag.clear()
        self._stop_flag.clear()
        self.paused = False
        self._natural = False
        self._frames_played = 0
        self._start_ms = position_ms
        self._ended = asyncio.Event()
        ended = self._ended

        def signal_end() -> None:
            loop.call_soon_threadsafe(ended.set)

        self._thread = threading.Thread(
            target=self._play_blocking, args=(path, position_ms, signal_end), daemon=True
        )
        self._thread.start()

    def _play_blocking(self, path: Path, position_ms: int, signal_end: object) -> None:
        import sounddevice as sd  # noqa: PLC0415 - keep audio deps out of test imports
        import soundfile as sf  # noqa: PLC0415

        assert callable(signal_end)  # noqa: S101 - internal invariant
        try:
            with sf.SoundFile(str(path)) as audio:
                self._samplerate = int(audio.samplerate)
                audio.seek(int(position_ms / 1000 * audio.samplerate))
                with sd.OutputStream(
                    samplerate=audio.samplerate, channels=audio.channels, dtype="float32"
                ) as stream:
                    while not self._stop_flag.is_set():
                        if self._pause_flag.is_set():
                            self._stop_flag.wait(0.05)
                            continue
                        block = audio.read(self._BLOCK_FRAMES, dtype="float32")
                        if len(block) == 0:
                            self._natural = True
                            break
                        stream.write(block)
                        self._frames_played += len(block)
        except Exception:  # pragma: no cover - device failures are logged, not fatal
            log.exception("audio output failed")
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
        return self._start_ms + int(self._frames_played / self._samplerate * 1000)

    async def wait(self) -> bool:
        """Wait for the current playback to finish or be stopped."""
        await self._ended.wait()
        return self._natural


class PlaybackController:
    """Serializes playback and answers to the user, not to the queue."""

    def __init__(self, store: Store, sink: AudioSink, *, held: bool = False) -> None:
        """Wrap ``sink``; ``held`` starts the controller without autoplay."""
        self._store = store
        self._sink = sink
        self.held = held
        self._current_id: str | None = None
        self._sink_active = False
        self._wake = asyncio.Event()
        self._watcher: asyncio.Task[None] | None = None

    @property
    def current_id(self) -> str | None:
        """The utterance currently holding the device, if any."""
        return self._current_id

    def notify(self) -> None:
        """Tell the controller the plan may have changed."""
        self._wake.set()

    async def run(self) -> None:
        """Start the next in-order utterance whenever the device is free."""
        while True:
            if self._current_id is None and not self.held:
                nxt = self._store.next_pending()
                if (
                    nxt is not None
                    and nxt.state is State.READY
                    and nxt.audio_path is not None
                ):
                    self._begin(nxt.id, Path(nxt.audio_path), position_ms=0)
                    continue
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=0.1)

    def _begin(self, utt_id: str, path: Path, *, position_ms: int) -> None:
        self._store.transition(utt_id, State.PLAYING)
        self._current_id = utt_id
        self._sink.start(path, position_ms=position_ms)
        self._sink_active = True
        self._watcher = asyncio.get_running_loop().create_task(self._watch())

    async def _watch(self) -> None:
        ended = await self._sink.wait()
        if not ended:
            return  # whoever stopped the sink owns the state change
        utt_id = self._current_id
        if utt_id is None:  # pragma: no cover - stop always precedes clearing
            return
        current = self._store.get(utt_id)
        if current is not None and current.state is State.PLAYING:
            self._store.transition(
                utt_id, State.PLAYED, played_ms=current.duration_ms
            )
        self._current_id = None
        self._sink_active = False
        self.notify()

    def _cancel_watcher(self) -> None:
        if self._watcher is not None:
            self._watcher.cancel()
            self._watcher = None

    async def pause(self) -> None:
        """Hold playback. Synthesis continues; the buffer should fill while paused."""
        self.held = True
        current = self._current()
        if current is not None and current.state is State.PLAYING and self._sink_active:
            self._sink.pause()
            self._store.transition(
                current.id, State.PAUSED, played_ms=self._sink.position_ms()
            )

    async def resume(self) -> None:
        """Release the hold and continue (or adopt a restored paused utterance)."""
        self.held = False
        current = self._current()
        if current is None:
            current = self._adoptable_paused()
            if current is not None:
                self._current_id = current.id
        if current is not None and current.state is State.PAUSED:
            if self._sink_active:
                self._sink.resume()
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
        self.held = False
        if current is not None and current.state in (State.PLAYING, State.PAUSED):
            self._cancel_watcher()
            position = (
                self._sink.position_ms() if self._sink_active else current.played_ms or 0
            )
            if self._sink_active:
                self._sink.stop()
                self._sink_active = False
            self._store.transition(current.id, State.SKIPPED, played_ms=position)
            self._current_id = None
        self.notify()

    async def restart_current(self) -> None:
        """Replay the current utterance from its start."""
        current = self._current()
        if current is None or current.audio_path is None:
            return
        if current.state not in (State.PLAYING, State.PAUSED):  # pragma: no cover
            return
        self.held = False
        self._cancel_watcher()
        if self._sink_active:
            self._sink.stop()
            self._sink_active = False
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
