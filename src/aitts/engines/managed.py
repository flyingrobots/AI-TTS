# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Engine adapters backed by separately installed, offline local worker processes."""

from __future__ import annotations

import json
import os
import select
import subprocess
import threading
import time
from typing import TYPE_CHECKING, Any

from aitts.engine import SynthesisError
from aitts.model_catalog import MODELS
from aitts.model_worker import FRAME_LIMIT, PROTOCOL_VERSION

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

# Bounds one JSON control line; audio travels on its own pipe.
_LINE_LIMIT = 512 * 1024
_RESPONSE_TIMEOUT = 300


def runtime_environment(root: Path) -> dict[str, str]:
    """Workers import the installed adapter snapshot and perform no network discovery."""
    return {
        **os.environ,
        "PYTHONPATH": str(root / "adapter"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TOKENIZERS_PARALLELISM": "false",
    }


class WorkerProtocolError(SynthesisError):
    """The worker does not speak this daemon's protocol version."""


class _WorkerTimeoutError(SynthesisError):
    """The worker gave no complete reply within the response deadline."""


def read_frame(read: Callable[[int], bytes]) -> bytes:
    """Read one length-prefixed audio frame; ``read(n)`` returns at most ``n`` bytes."""
    length = int.from_bytes(_read_exact(read, 4), "big")
    if length > FRAME_LIMIT:
        message = "model worker returned an invalid response"
        raise SynthesisError(message)
    return _read_exact(read, length)


def _read_exact(read: Callable[[int], bytes], size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        block = read(size - len(data))
        if not block:
            # A partial frame is never a full frame.
            message = "model worker returned an invalid response"
            raise SynthesisError(message)
        data.extend(block)
    return bytes(data)


class ManagedEngine:
    """One serialized worker; installing another model never mutates this runtime."""

    is_local = True

    def __init__(self, name: str, root: Path | None) -> None:
        """Retain a published runtime without starting model inference.

        ``root`` is ``None`` when the model is not installed: the daemon still lists
        and selects it, but every request refuses with the setup command.
        """
        self.name = name
        self.root = root
        if name == "chatterbox":
            self.supported_speeds = (1.0,)
        self._lock = threading.Lock()
        # Guards only detaching the process and audio descriptor; close() never takes _lock.
        self._lifecycle = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._audio: int | None = None
        self._buffer = bytearray()
        self._closed = False
        self.protocol_version: int | None = None

    def list_voices(self) -> list[str]:
        """Return the validated setup catalog without spawning a process."""
        return list(MODELS[self.name].voices)

    def _start(self) -> None:
        if self._closed:
            message = "model worker has been closed"
            raise SynthesisError(message)
        if self.root is None:
            message = f"{self.name} is not installed; run `ai-tts model-setup {self.name}`"
            raise SynthesisError(message)
        if self._process is None:
            audio_read, audio_write = os.pipe()
            self._audio = audio_read
            try:
                self._spawn(self.root, audio_write)
            except BaseException:
                self._audio = None
                os.close(audio_read)
                raise
            finally:
                # Only the worker holds the write end, so its exit is an EOF here.
                os.close(audio_write)
            self._handshake()

    def _spawn(self, root: Path, audio_write: int) -> None:
        self._process = subprocess.Popen(  # noqa: S603 - published runtime and fixed worker arguments
            [
                str(root / "venv/bin/python"),
                "-m",
                "aitts.model_worker",
                "serve",
                self.name,
                str(root),
                str(audio_write),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            pass_fds=(audio_write,),
            env=runtime_environment(root),
        )

    def _handshake(self) -> None:
        """Refuse, typed, any worker whose first message is not this daemon's version."""
        version: object = None
        try:
            version = self._receive().get("protocol")
        except _WorkerTimeoutError:
            raise
        except SynthesisError:
            # An older worker exits on the new start arguments before any reply.
            version = None
        if type(version) is not int or version != PROTOCOL_VERSION:
            self._stop_worker()
            message = (
                f"model worker speaks protocol {version!r}, not {PROTOCOL_VERSION}; "
                "refresh the model worker in model setup"
            )
            raise WorkerProtocolError(message)
        self.protocol_version = version

    def _read_audio(self, size: int) -> bytes:
        """Return at most ``size`` bytes from the audio pipe within the response deadline."""
        audio = self._audio
        if audio is None:
            message = "model worker is unavailable"
            raise SynthesisError(message)
        ready, _, _ = select.select([audio], [], [], _RESPONSE_TIMEOUT)
        if not ready:
            self._stop_worker()
            message = "model worker timed out; retry model setup"
            raise _WorkerTimeoutError(message)
        return os.read(audio, min(size, 65536))

    def _send(self, payload: dict[str, Any]) -> None:
        self._start()
        process = self._process
        if process is None or process.stdin is None:
            message = "model worker is unavailable"
            raise SynthesisError(message)
        try:
            process.stdin.write(json.dumps(payload).encode() + b"\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            message = "model worker stopped; retry model setup"
            raise SynthesisError(message) from exc

    def _receive(self) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            message = "model worker is unavailable"
            raise SynthesisError(message)
        deadline = time.monotonic() + _RESPONSE_TIMEOUT
        while b"\n" not in self._buffer:
            ready, _, _ = select.select(
                [process.stdout], [], [], max(0.0, deadline - time.monotonic())
            )
            if not ready:
                self.close()
                message = "model worker timed out; retry model setup"
                raise _WorkerTimeoutError(message)
            block = os.read(process.stdout.fileno(), 65536)
            if not block or len(self._buffer) + len(block) > _LINE_LIMIT:
                self.close()
                message = "model worker returned an invalid response"
                raise SynthesisError(message)
            self._buffer.extend(block)
        line, _, rest = self._buffer.partition(b"\n")
        self._buffer = bytearray(rest)
        try:
            result: object = json.loads(line)
        except (ValueError, UnicodeError) as exc:
            message = "model could not render audio; retry model setup"
            raise SynthesisError(message) from exc
        if not isinstance(result, dict) or result.get("ok") is False:
            message = "model could not render audio; restart the model"
            raise SynthesisError(message)
        return result

    def warmup(self) -> None:
        """Load only the already installed, offline assets."""
        with self._lock:
            self._send({"op": "warmup"})
            if self._receive().get("ok") is not True:
                message = "model could not prepare"
                raise SynthesisError(message)

    def synthesize(self, text: str, voice: str, speed: float, out_path: Path) -> int:
        """Preserve the existing artifact boundary through the private pipe."""
        with self._lock:
            self._send(
                {
                    "op": "synthesize",
                    "text": text,
                    "voice": voice,
                    "speed": speed,
                    "path": str(out_path),
                }
            )
            reply = self._receive()
            duration = reply.get("duration_ms")
            if reply.get("ok") is not True or type(duration) is not int or duration <= 0:
                message = "model returned invalid audio duration"
                raise SynthesisError(message)
            return duration

    def evidence(self, voice: str) -> dict[str, Any]:
        """Retain actual weight/voice identities and versions from the inference runtime."""
        with self._lock:
            self._send({"op": "evidence", "voice": voice})
            metadata = self._receive().get("metadata")
            if not isinstance(metadata, dict):
                message = "model returned invalid provenance"
                raise SynthesisError(message)
            return metadata

    def restart(self) -> None:
        """Discard a failed worker and prepare its already installed assets again."""
        with self._lock:
            self._stop_worker()
            self._closed = False
        self.warmup()

    def close(self) -> None:
        """Interrupt a stuck inference without waiting on its serialization lock."""
        self._closed = True
        self._stop_worker()

    def _stop_worker(self) -> None:
        # Detach exactly once: a racing caller sees nothing left to stop.
        with self._lifecycle:
            process, self._process = self._process, None
            audio, self._audio = self._audio, None
            self._buffer.clear()
            self.protocol_version = None
        if audio is not None:
            os.close(audio)
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
            if process.stdin is not None:
                process.stdin.close()
            if process.stdout is not None:
                process.stdout.close()


class ManagedStreamingEngine(ManagedEngine):
    """Keep Kokoro's early PCM delivery across the isolated runtime boundary."""

    def stream_synthesize(self, text: str, voice: str, speed: float) -> Iterator[bytes]:
        """Yield actual producer blocks, never synthetic progress audio."""
        with self._lock:
            self._send({"op": "stream", "text": text, "voice": voice, "speed": speed})
            complete = False
            try:
                while pcm := read_frame(self._read_audio):
                    if len(pcm) % 2:
                        message = "model returned invalid PCM"
                        raise SynthesisError(message)
                    yield pcm
                if self._receive().get("ok") is not True:
                    message = "model could not render audio; restart the model"
                    raise SynthesisError(message)
                complete = True
            finally:
                if not complete:
                    # Retire unread responses so the next clip cannot consume stale PCM.
                    self._stop_worker()


def managed_engine(name: str, root: Path | None) -> ManagedEngine:
    """Chatterbox remains file-only; Kokoro retains incremental synthesis."""
    adapter = ManagedEngine if name == "chatterbox" else ManagedStreamingEngine
    return adapter(name, root)
