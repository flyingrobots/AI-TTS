# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""A prepared callback device with serialized logical speech sessions."""

from __future__ import annotations

import contextlib
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from aitts.application.audio_device import AudioDevicePort
    from aitts.playback import CallbackStreamFactory


class PreparedCallbackOutput:
    """Keep the device supplied with silence between speech and pause/resume.

    File reads and synthesis never run in this callback. A logical session may
    finish without tearing down the hardware stream; a route change or daemon
    shutdown closes it explicitly.
    """

    def __init__(self, device: AudioDevicePort, factory: CallbackStreamFactory) -> None:
        """Retain the device and native callback boundaries without opening hardware."""
        self._device = device
        self._factory = factory
        self._setup = threading.RLock()
        self._slot = threading.Lock()
        self._active: tuple[Callable[[Any, int, bool], bool], Callable[[], None]] | None = None
        self._ready = threading.Event()
        self._ended = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._identity: str | None = None
        self._error: str | None = None

    def prepare(self) -> None:
        """Open the current output in advance, or reuse its healthy prepared stream."""
        with self._setup:
            identity = self._device.default_output_identity()
            if (
                self._ready.is_set()
                and not self._ended.is_set()
                and self._error is None
                and identity == self._identity
            ):
                return
            self.close()
            self._ready.clear()
            self._ended.clear()
            self._stop.clear()
            self._error = None
            self._thread = threading.Thread(
                target=self._run, name="aitts.callback-output", daemon=True
            )
            self._thread.start()
            if not self._ready.wait(5):
                self.close()
                msg = "audio callback device preparation timed out"
                raise RuntimeError(msg)
            self._raise_if_failed()

    def _raise_if_failed(self) -> None:
        if self._error is not None:
            raise RuntimeError(self._error)

    @contextlib.contextmanager
    def session(
        self,
        *,
        samplerate: int,
        channels: int,
        render: Callable[[Any, int, bool], bool],
        finished: Callable[[], None],
    ) -> Iterator[object]:
        """Attach one PCM renderer while retaining the physical device afterward."""
        if (samplerate, channels) != (24000, 1):
            msg = "prepared PCM output requires mono 24 kHz"
            raise ValueError(msg)
        self.prepare()
        active = (render, finished)
        with self._slot:
            self._raise_if_failed()
            if self._active is not None:
                msg = "prepared audio output already has an owner"
                raise RuntimeError(msg)
            self._active = active
        try:
            yield self
            if self._error is not None:
                raise RuntimeError(self._error)
        finally:
            with self._slot:
                if self._active is active:
                    self._active = None

    def close(self) -> None:
        """Release the hardware device; safe to call again after shutdown."""
        with self._setup:
            self._stop.set()
            self._ended.set()
            thread = self._thread
            if thread is not None:
                thread.join(timeout=5)
                if thread.is_alive():
                    msg = "audio callback device did not close"
                    raise RuntimeError(msg)
            self._thread = None
            self._ready.clear()

    def _render(self, output: Any, frames: int, underflow: bool) -> bool:  # noqa: ANN401, FBT001 - native callback signature
        if self._stop.is_set():
            output.fill(0)
            return False
        with self._slot:
            active = self._active
            if active is None:
                output.fill(0)
                return True
            render, finished = active
            try:
                running = render(output, frames, underflow)
            except Exception as exc:  # noqa: BLE001 - native callbacks cannot propagate exceptions
                self._error = str(exc) or type(exc).__name__
                output.fill(0)
                self._ended.set()
                running = False
            if not running:
                self._active = None
        if not running:
            finished()
        return self._error is None

    def _run(self) -> None:
        try:
            self._device.refresh()
            self._identity = self._device.default_output_identity()
            with self._factory(
                samplerate=24000, channels=1, render=self._render, finished=self._ended.set
            ):
                self._ready.set()
                self._ended.wait()
            if not self._stop.is_set() and self._error is None:
                self._error = "audio callback device stopped unexpectedly"
        except Exception as exc:  # noqa: BLE001 - surface a native device failure to its owner
            self._error = str(exc) or type(exc).__name__
        finally:
            with self._slot:
                active = self._active
                self._active = None
            if active is not None:
                active[1]()
            # Also release a preparation waiter on failure; prepare checks error.
            self._ready.set()
