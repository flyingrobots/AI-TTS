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
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

from aitts.adapters.callback_output import PreparedCallbackOutput
from aitts.adapters.diagnostic_logging import utterance_trace
from aitts.adapters.platform_audio import platform_audio_device
from aitts.application.playback_schedule import PlaybackCheckpoint
from aitts.model import Priority, State

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from aitts.adapters.clip_evidence import ClipEvidence
    from aitts.application.audio_device import AudioDevicePort
    from aitts.application.playback_schedule import PlaybackSchedulePort
    from aitts.model import Utterance, UtteranceSegment
    from aitts.store import Store

from aitts.streaming import PCMStreamRenderer, SpoolingPCMStream, StreamingRegistry

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

    def write(self, block: Any) -> bool:  # noqa: ANN401 - a numpy block of frames
        """Write frames; return whether the driver inserted data after an underflow."""
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


class CallbackStreamFactory(Protocol):
    """Open a device callback which reads only PCM memory, never files or inference."""

    def __call__(
        self,
        *,
        samplerate: int,
        channels: int,
        render: Callable[[Any, int, bool], bool],
        finished: Callable[[], None],
    ) -> AbstractContextManager[object]:
        """Return a device context; false from render drains its final block."""
        ...


def _open_pcm_callback_stream(
    *,
    samplerate: int,
    channels: int,
    render: Callable[[Any, int, bool], bool],
    finished: Callable[[], None],
) -> AbstractContextManager[object]:
    import sounddevice as sd  # noqa: PLC0415 - lazy native audio binding

    def callback(output: Any, frames: int, timing: Any, status: Any) -> None:  # noqa: ANN401 - untyped PortAudio callback boundary
        del timing
        if not render(output, frames, bool(status.output_underflow)):
            raise sd.CallbackStop

    return cast(
        "AbstractContextManager[object]",
        sd.OutputStream(
            samplerate=samplerate,
            channels=channels,
            dtype="float32",
            blocksize=240,
            callback=callback,
            finished_callback=finished,
        ),
    )


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
        open_callback_stream: CallbackStreamFactory | None = None,
        evidence: ClipEvidence | None = None,
    ) -> None:
        """Create the sink; nothing is opened until :meth:`start`."""
        self._open_callback_stream = open_callback_stream or _open_pcm_callback_stream
        self._prefix_pcm = b""
        self._live_pcm: SpoolingPCMStream | None = None
        self.evidence = evidence
        self.playback_session = ""
        self._audio_path: Path | None = None
        self._stream_underflows = 0
        self._device = device if device is not None else platform_audio_device()
        self._open_stream = open_stream if open_stream is not None else _open_sounddevice_stream
        self._prepared_output: PreparedCallbackOutput | None = None
        self._output_setup = threading.Lock()
        self._output_shutdown = False
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

    def set_prefix(self, pcm: bytes) -> None:
        """Queue a 24 kHz mono PCM16 cue for the next serialized playback session."""
        self._prefix_pcm = pcm

    def prepare_output(self) -> None:
        """Prepare silent callback output before admitting streaming synthesis."""
        with self._output_setup:
            if self._output_shutdown:
                return
            if self._prepared_output is None:
                self._prepared_output = PreparedCallbackOutput(
                    self._device, self._open_callback_stream
                )
            self._prepared_output.prepare()

    def close_output(self) -> None:
        """Release idle callback hardware when the daemon shuts down."""
        with self._output_setup:
            self._output_shutdown = True
            if self._prepared_output is not None:
                self._prepared_output.close()

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
        self._launch(path, position_ms=position_ms, streaming=False)

    def start_stream(
        self, source: SpoolingPCMStream, *, artifact_id: str, position_ms: int = 0
    ) -> None:
        """Play incremental PCM with disk spooling isolated from the device callback."""
        source.retain()
        self._live_pcm = source
        try:
            self._launch(Path(artifact_id), position_ms=position_ms, streaming=True)
        except Exception:
            source.release()
            raise

    def _launch(self, path: Path, *, position_ms: int, streaming: bool) -> None:
        # Completion is the handoff barrier: the stream and file are closed
        # before it is signalled. The old Python thread may still be returning.
        if self._thread is not None and not self._ended.is_set():
            msg = "sink is already active; playback is strictly serialized"
            raise RuntimeError(msg)
        self._audio_path = path
        self.playback_session = uuid.uuid4().hex
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
            self._audio_event("session_ended", natural=self._natural, error=self.error)
            loop.call_soon_threadsafe(ended.set)

        self._audio_event("session_started", runtime=self.evidence.runtime if self.evidence else {})
        self._thread = threading.Thread(
            target=self._play_stream_blocking if streaming else self._play_blocking,
            args=(path, position_ms, signal_end),
            daemon=True,
        )
        self._thread.start()

    def _audio_event(self, event: str, **details: object) -> None:
        if self.evidence is not None and self._audio_path is not None:
            self.evidence.record(
                self._audio_path.stem,
                "playback",
                event,
                playback_session=self.playback_session,
                position_ms=self.position_ms(),
                rate=self._current_rate(),
                **details,
            )

    def _play_blocking(self, path: Path, position_ms: int, signal_end: object) -> None:
        import soundfile as sf  # noqa: PLC0415 - keep audio deps out of test imports

        assert callable(signal_end)  # noqa: S101 - internal invariant
        delegated = False
        try:
            if self._prepared_output is not None:
                try:
                    source = SpoolingPCMStream.from_cached(path)
                except (ValueError, OSError):
                    self._prepared_output.close()
                else:
                    self._live_pcm = source
                    delegated = True
                    self._play_stream_blocking(path, position_ms, signal_end)
                    return
            with sf.SoundFile(str(path)) as audio:
                self._samplerate = int(audio.samplerate)
                source_frame = float(int(position_ms / 1000 * audio.samplerate))
                self._set_position_ms(source_frame / self._samplerate * 1000)
                # Each pass owns one device. A pass ends at the end of the file,
                # on stop, or when the listener moves the system default; only
                # the last of those comes back for another pass.
                while not self._stop_flag.is_set() and source_frame < len(audio):
                    if self._pause_flag.is_set():
                        # No live device stream while held: a blocking output
                        # stream left running without writes will underflow.
                        self._stop_flag.wait(0.05)
                        continue
                    source_frame = self._play_on_current_device(audio, source_frame)
                if not self._stop_flag.is_set() and source_frame >= len(audio):
                    self._natural = True
        except Exception as exc:  # noqa: BLE001 - any device or file failure ends this clip
            self.error = str(exc) or type(exc).__name__
            log.warning("event=audio_output_failed")
            self._natural = False
        finally:
            if not delegated:
                signal_end()

    def _play_stream_blocking(self, path: Path, position_ms: int, signal_end: object) -> None:
        del path
        source = self._live_pcm
        assert source is not None  # noqa: S101 - start_stream owns the source
        assert callable(signal_end)  # noqa: S101 - sink lifecycle callback
        self._samplerate = 24000
        position = int(position_ms * 24)
        try:
            while not self._stop_flag.is_set():
                if self._pause_flag.is_set():
                    self._stop_flag.wait(0.05)
                    continue
                renderer = PCMStreamRenderer(
                    source,
                    position_frames=position,
                    skip_leading_silence=True,
                    prefix_pcm=self._prefix_pcm,
                )
                self._prefix_pcm = b""
                source.wait_buffered(240, timeout=0.02)
                if self._prepared_output is None:
                    self._device.refresh()
                self._opened_on = self._device.default_output_identity()
                self._pending_device = None
                self._pending_confirmations = 0
                self._stream_underflows = 0
                finished = threading.Event()
                reopen = threading.Event()

                factory = (
                    self._prepared_output.session
                    if self._prepared_output is not None
                    else self._open_callback_stream
                )
                with factory(
                    samplerate=24000,
                    channels=1,
                    render=self._pcm_render(renderer, reopen),
                    finished=finished.set,
                ):
                    while not finished.wait(0.05):
                        if self._device_moved_from(self._opened_on):
                            reopen.set()
                position = int(renderer.position_frames)
                self._audio_event(
                    "stream_buffering",
                    underruns=renderer.underruns,
                    output_underflows=self._stream_underflows,
                    skipped_silence_frames=renderer.skipped_silence_frames,
                )
                if renderer.error:
                    self.error = renderer.error
                    break
                if renderer.ended:
                    self._natural = True
                    break
        except Exception as exc:  # noqa: BLE001 - device failure belongs to this clip
            self.error = str(exc) or type(exc).__name__
        finally:
            source.release()
            signal_end()

    def _pcm_render(
        self, renderer: PCMStreamRenderer, reopen: threading.Event
    ) -> Callable[[Any, int, bool], bool]:
        def render(output: Any, frames: int, underflow: bool) -> bool:  # noqa: ANN401, FBT001 - native callback contract
            if underflow:
                self._stream_underflows += 1
            if self._stop_flag.is_set() or self._pause_flag.is_set() or reopen.is_set():
                output[:] = renderer.stop_block(frames)
                return False
            output[:] = renderer.render(frames, rate=self._current_rate())
            self._set_position_ms(renderer.position_frames / 24)
            return not renderer.ended and renderer.error is None

        return render

    def _play_on_current_device(self, audio: Any, source_frame: float) -> float:  # noqa: ANN401
        """Stream from ``source_frame`` until the file ends or the default moves.

        A pause also closes the stream. Returns the frame reached, so the
        caller can resume without repeating or dropping source audio.
        """
        import numpy as np  # noqa: PLC0415 - keep array setup on the audio thread

        # Refreshed with no stream open: re-initializing invalidates live streams.
        self._device.refresh()
        self._opened_on = self._device.default_output_identity()
        self._stream_underflows = 0
        with (
            self._open_stream(samplerate=audio.samplerate, channels=audio.channels) as stream,
            contextlib.ExitStack() as closing,
        ):
            closing.callback(
                lambda: self._audio_event("stream_closing", underflows=self._stream_underflows)
            )
            self._audio_event(
                "stream_opened",
                sample_rate=audio.samplerate,
                channels=audio.channels,
                output_device=self._opened_on,
                latency_seconds=getattr(stream, "latency", None),
                block_frames=self._BLOCK_FRAMES,
            )
            self._play_prefix(stream, audio.samplerate, audio.channels)
            last_sample = None
            while not self._stop_flag.is_set() and source_frame < len(audio):
                if self._device_moved_from(self._opened_on):
                    self._audio_event("output_device_changed")
                    log.info("event=audio_output_device_changed")
                    return source_frame
                if self._pause_flag.is_set():
                    return source_frame
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
                last_sample = block[-1]
                self._write_output(stream, block)
                source_frame = min(float(len(audio)), source_frame + output_frames * rate)
                self._set_position_ms(source_frame / self._samplerate * 1000)
            if self._stop_flag.is_set() and last_sample is not None:
                # End at silence without consuming source frames that must be
                # heard after resumption. Device close drains this short tail.
                ramp = np.linspace(1.0, 0.0, max(2, int(audio.samplerate * 0.005)))
                self._write_output(stream, (ramp[:, None] * last_sample).astype("float32"))
        return source_frame

    def _write_output(self, stream: OutputStream, block: Any) -> None:  # noqa: ANN401 - a numpy block of PCM frames
        if stream.write(block):
            self._stream_underflows += 1
            if self._stream_underflows == 1:
                self._audio_event("output_underflow")
                # One bounded diagnostic per stream. The driver accepted the
                # block: replaying it would duplicate audio, not repair the gap.
                log.warning("event=audio_output_underflow")

    def _play_prefix(self, stream: OutputStream, samplerate: int, channels: int) -> None:
        """Play a cue on the legacy file stream without changing speech position."""
        import numpy as np  # noqa: PLC0415

        if not self._prefix_pcm:
            return
        samples = np.frombuffer(self._prefix_pcm, dtype="<i2") / 32768.0
        self._prefix_pcm = b""
        positions = np.arange(round(len(samples) * samplerate / 24000)) * 24000 / samplerate
        cue = np.repeat(
            np.interp(positions, np.arange(len(samples)), samples)[:, None], channels, axis=1
        )
        for start in range(0, len(cue), self._BLOCK_FRAMES):
            if self._stop_flag.is_set() or self._pause_flag.is_set():
                break
            stream.write(cue[start : start + self._BLOCK_FRAMES].astype("float32"))

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

    def __init__(  # noqa: PLR0913 - injected playback boundaries
        self,
        store: Store,
        sink: AudioSink,
        schedule: PlaybackSchedulePort,
        *,
        held: bool = False,
        evidence: ClipEvidence | None = None,
        streams: StreamingRegistry | None = None,
    ) -> None:
        """Wrap ``sink`` and restore the durable global playback hold."""
        self._streams = streams
        self._evidence = evidence
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
        self._preempted_stack: list[tuple[str, int | None]] = []
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
            # Every accepted takeover ranks ahead of its interrupted clip.
            # Rebuild that durable nesting, independent of wall-clock changes.
            for saved in sorted(
                self._store.playback_queue(), key=lambda item: item.order_key, reverse=True
            ):
                if saved.state is State.PAUSED and saved.id != self._current_id:
                    segment = self._store.next_unfinished_segment(saved.id)
                    index = (
                        segment.index
                        if segment is not None and segment.state is State.PAUSED
                        else None
                    )
                    self._preempted_stack.append((saved.id, index))

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
        self._record_control("rate_changed", "explicit_control")

    async def run(self) -> None:
        """Start the next in-order utterance whenever the device is free."""
        while True:
            await self._schedule.checkpoint(PlaybackCheckpoint.BEFORE_PLAN)
            async with self._transport_lock:
                await self._plan_preemption()
            if self._current_id is None and not self.held:
                nxt = self._store.next_pending()
                if nxt is not None and nxt.state is State.READY:
                    segment = self._store.next_unfinished_segment(nxt.id)
                    if segment is not None and segment.state is State.READY:
                        self._begin_segment(nxt, segment, position_ms=0)
                        continue
                    if segment is None and (
                        nxt.audio_path is not None or self._live_source(nxt.id) is not None
                    ):
                        self._begin(nxt.id, Path(nxt.audio_path or nxt.id), position_ms=0)
                        continue
            elif self._current_id is not None and not self._sink_active:
                current = self._current()
                # Release a document that ended while the controller still held
                # it. A parent can reach a terminal state without the watcher
                # running — a later chunk failing to synthesize does it — and
                # holding onto it stalls everything queued behind it forever.
                if current is None or current.is_terminal:
                    log.info(
                        "event=terminal_current_released trace=%s",
                        utterance_trace(self._current_id),
                    )
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

    async def shutdown(self) -> None:
        """Release the live device before the daemon closes its store and spools."""
        async with self._transport_lock:
            current = self._current()
            if current is not None and not current.is_terminal:
                await self._hold(reason=None, cause="daemon_shutdown")
            await self.stop()

    async def _plan_preemption(self) -> None:
        """Transfer the device only once the interrupting clip can speak."""
        if bool(self.held):
            return
        current = self._current()
        candidate = next(
            (
                item
                for item in self._store.playback_queue()
                if item.priority is Priority.PREEMPT
                and item.state is State.READY
                and (current is None or current.is_terminal or item.order_key < current.order_key)
            ),
            None,
        )
        if candidate is not None:
            await self._suspend_current()
            if self.held:
                return
            refreshed = self._store.get(candidate.id)
            if refreshed is not None and refreshed.state is State.READY:
                self._start_saved(refreshed)
        if self._current_id is None:
            self._restore_preempted()

    def _restore_preempted(self) -> None:
        while self._preempted_stack:
            utt_id, index = self._preempted_stack.pop()
            saved = self._store.get(utt_id)
            if saved is not None and saved.state is State.PAUSED:
                self._start_saved(saved, index)
                self._record_control("resumed", "preemption_complete")
                break

    async def _suspend_current(self) -> None:
        current = self._current()
        if current is not None and not current.is_terminal:
            self._record_control("preempted", "priority_preempt")
            index = self._current_segment_index
            had_sink = self._sink_active
            position = self.current_position_ms() or 0
            if index is None and self._store.segments(current.id):
                position = self._store.completed_segment_duration_ms(current.id)
            await self._release_sink()
            if had_sink:
                position = self._sink.position_ms()
            if self._store.suspend_playback(current.id, index, position):
                self._preempted_stack.append((current.id, index))
            self._current_id = None
            self._current_segment_index = None
        elif self._sink_active:
            await self._release_sink()
            self._current_id = None
            self._current_segment_index = None

    def _start_saved(self, clip: Utterance, index: int | None = None) -> None:
        segment = (
            self._store.get_segment(clip.id, index)
            if index is not None
            else self._store.next_unfinished_segment(clip.id)
        )
        if segment is not None and segment.state in (State.READY, State.PAUSED):
            self._begin_segment(clip, segment, position_ms=segment.played_ms or 0)
        elif segment is None and (
            clip.audio_path is not None or self._live_source(clip.id) is not None
        ):
            self._begin(clip.id, Path(clip.audio_path or clip.id), position_ms=clip.played_ms or 0)
        else:
            self._current_id = clip.id
            self._current_segment_index = None
            if clip.state is State.PAUSED:
                self._store.transition(clip.id, State.PLAYING)

    async def clear_preempted(self) -> int:
        """Drain suspended speech without stopping the current alert."""
        async with self._transport_lock:
            cleared = 0
            while self._preempted_stack:
                utt_id, index = self._preempted_stack.pop()
                clip = self._store.get(utt_id)
                if clip is not None and clip.state is State.PAUSED:
                    segment = self._store.get_segment(utt_id, index) if index is not None else None
                    position = (segment.played_ms or 0) if segment else 0
                    self._store.skip_utterance(utt_id, index, position, played_ms=clip.played_ms)
                    cleared += 1
            return cleared

    def _begin(self, utt_id: str, path: Path, *, position_ms: int) -> None:
        clip = self._store.get(utt_id)
        self._configure_cue(clip is not None and clip.state is State.READY)
        self._store.transition(utt_id, State.PLAYING)
        self._current_id = utt_id
        self._start_audio(utt_id, path, position_ms=position_ms)
        self._sink_active = True
        self._watcher = asyncio.get_running_loop().create_task(self._watch())

    def _begin_segment(
        self,
        parent: Utterance,
        segment: UtteranceSegment,
        *,
        position_ms: int,
    ) -> None:
        self._configure_cue(parent.state is State.READY)
        if parent.state in (State.READY, State.PAUSED):
            self._store.transition(parent.id, State.PLAYING)
        self._store.transition_segment(parent.id, segment.index, State.PLAYING)
        self._current_id = parent.id
        self._current_segment_index = segment.index
        if (
            segment.audio_path is None and self._live_source(segment.artifact_id) is None
        ):  # pragma: no cover
            msg = "ready segment has no audio artifact"
            raise RuntimeError(msg)
        self._start_audio(
            segment.artifact_id,
            Path(segment.audio_path or segment.artifact_id),
            position_ms=position_ms,
        )
        self._sink_active = True
        self._watcher = asyncio.get_running_loop().create_task(self._watch())

    def _configure_cue(self, new_document: bool) -> None:  # noqa: FBT001 - internal state decision
        from aitts.audio_cues import earcon_pcm  # noqa: PLC0415

        set_prefix = getattr(self._sink, "set_prefix", None)
        if callable(set_prefix):
            enabled = self._store.get_setting("earcon_enabled", "false") == "true"
            set_prefix(earcon_pcm() if enabled and new_document else b"")

    def _live_source(self, artifact_id: str) -> SpoolingPCMStream | None:
        return self._streams.get(artifact_id) if self._streams is not None else None

    def _start_audio(self, artifact_id: str, path: Path, *, position_ms: int) -> None:
        source = self._live_source(artifact_id)
        start_stream = getattr(self._sink, "start_stream", None)
        if source is not None and callable(start_stream):
            start_stream(source, artifact_id=artifact_id, position_ms=position_ms)
        else:
            self._sink.start(path, position_ms=position_ms)

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

    async def stop(self) -> None:
        """Retire playback before the owner closes durable state.

        The caller first retires the plan loop and transport requests. Device
        release can advance the playhead, so save its final position afterward.
        """
        had_active_sink = self._sink_active
        await self._release_sink()
        current = self._current()
        if current is not None and had_active_sink:
            self._store.suspend_playback(
                current.id, self._current_segment_index, self._sink.position_ms()
            )
        self._current_id = None
        self._current_segment_index = None

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

    def _record_control(self, event: str, cause: str) -> None:
        current = self._current()
        if self._evidence is None or current is None:
            return
        segment = self.current_segment
        path = segment.audio_path if segment is not None else current.audio_path
        artifact_id = Path(path).stem if path else (segment.artifact_id if segment else current.id)
        self._evidence.record(
            artifact_id,
            "playback",
            event,
            cause=cause,
            utterance_id=current.id,
            position_ms=self.current_position_ms(),
            segment_position_ms=self.current_segment_position_ms(),
            rate=self.playback_rate,
            playback_session=getattr(self._sink, "playback_session", None),
        )

    async def pause(self, *, cause: str = "explicit_control") -> None:
        """Hold playback. Synthesis continues; the buffer should fill while paused.

        This is the listener asking for silence, so it revokes any pending
        automatic resume and any recorded interruption: their newer, explicit
        request outranks a release armed earlier, and the hold is now theirs
        rather than something their microphone caused.
        """
        await self._hold(reason=None, cause=cause)

    async def _hold(self, *, reason: str | None, cause: str = "explicit_control") -> None:
        """Take the durable playback hold, recording why it was taken."""
        self._record_control("pause_requested", "microphone" if reason == _LISTENER else cause)
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
        self._record_control("resume_armed", "input_idle")

    def _clear_interruption(self) -> None:
        self.interrupted_at = None
        self.resume_when_input_idle_armed = False
        self._store.set_setting("playback_hold_reason", "")

    async def resume(self, *, cause: str = "explicit_control") -> None:
        """Release the hold and continue (or adopt a restored paused utterance)."""
        self._record_control("resume_requested", cause)
        self.held = False
        self._clear_interruption()
        self._store.set_setting("playback_held", "false")
        current = self._current()
        if current is None:
            current = self._adoptable_paused()
            if current is not None:
                self._current_id = current.id
                self._preempted_stack = [
                    saved for saved in self._preempted_stack if saved[0] != current.id
                ]
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
                if segment.state is State.PAUSED and (
                    segment.audio_path is not None
                    or self._live_source(segment.artifact_id) is not None
                ):
                    self._begin_segment(current, segment, position_ms=segment.played_ms or 0)
                else:
                    self._store.transition(current.id, State.PLAYING)
            elif current.audio_path is not None or self._live_source(current.id) is not None:
                self._begin(
                    current.id,
                    Path(current.audio_path or current.id),
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
            self._store.skip_utterance(
                current.id, segment_index, segment_position, played_ms=document_position
            )
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
        if previous is None or (
            previous.audio_path is None and self._live_source(previous.artifact_id) is None
        ):
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
        log.warning("event=document_playback_unrecoverable trace=%s", utterance_trace(utt_id))
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
        held_at_request = self.held
        if held_at_request:
            return
        current = self._current()
        if current is None or current.state not in (State.PLAYING, State.PAUSED):
            return
        if self._store.segments(current.id):
            active = self._current_segment_index
            await self._release_sink()
            self._store.restart_segments(current.id)
            self._current_segment_index = None
            first = self._store.next_unfinished_segment(current.id)
            if first is not None and first.state is State.READY:
                self._resume_document_at_next_ready(current.id)
            elif active is not None:
                # restart_segments only reopens children whose audio survives;
                # if none did, the device was released for nothing.
                self._restore_after_failed_step(current.id, active)
            self.notify()
            return
        if current.audio_path is None and self._live_source(current.id) is None:
            return
        await self._release_sink()
        # Generation may publish its WAV while device retirement yields. The
        # pre-release row can still have no path even though its live source
        # has now retired, so resolve the current durable artifact again.
        current = self._store.get(current.id)
        if current is None or current.state not in (State.PLAYING, State.PAUSED):
            self.notify()
            return
        if self.held:
            # Pause can arrive during release. Preserve Restart's zero offset
            # for explicit Resume without acquiring the device through a hold.
            self._store.suspend_playback(current.id, None, 0)
            self.notify()
            return
        if current.state is State.PAUSED:
            self._store.transition(current.id, State.PLAYING)
        self._start_audio(current.id, Path(current.audio_path or current.id), position_ms=0)
        self._sink_active = True
        self._watcher = asyncio.get_running_loop().create_task(self._watch())
        self.notify()

    def _current(self) -> Utterance | None:
        if self._current_id is None:
            return None
        return self._store.get(self._current_id)

    def _adoptable_paused(self) -> Utterance | None:
        paused = [utt for utt in self._store.playback_queue() if utt.state is State.PAUSED]
        return min(paused, key=lambda utt: utt.order_key, default=None)
