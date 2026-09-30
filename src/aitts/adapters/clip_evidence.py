# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Private, per-artifact synthesis and playback evidence, and local ZIP export."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
import os
import platform
import threading
import time
import uuid
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from blake3 import blake3

from aitts.adapters.private_files import ensure_private_directory, ensure_private_file

if TYPE_CHECKING:
    from aitts.model import SynthesisWork

log = logging.getLogger(__name__)
_CLIPPING_THRESHOLD = 0.9999
_MAX_LOG_BYTES = 1024 * 1024
_PACKAGES = (
    "ai-tts",
    "kokoro",
    "kokoro-mlx",
    "chatterbox-tts",
    "transformers",
    "torchaudio",
    "resemble-perth",
    "mlx",
    "mlx-metal",
    "torch",
    "misaki",
    "spacy",
    "en-core-web-sm",
    "phonemizer",
    "phonemizer-fork",
    "espeakng-loader",
    "numpy",
    "soundfile",
    "sounddevice",
)


def runtime_metadata() -> dict[str, Any]:
    """Capture versions without machine names, account names, or environment secrets."""
    packages: dict[str, str | None] = {}
    for name in _PACKAGES:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "macos": platform.mac_ver()[0],
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "packages": packages,
    }


def file_sha256(path: Path) -> str:
    """Hash a file incrementally, without loading model weights into memory."""
    info = path.stat()
    return _cached_sha256(str(path), info.st_size, info.st_mtime_ns)


@lru_cache(maxsize=128)
def _cached_sha256(path: str, size: int, modified: int) -> str:
    del size, modified
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class ClipEvidence:
    """Keep bounded logs beside the audio; each process and playback has an identity."""

    def __init__(self, root: Path) -> None:
        """Use the daemon's owned cache directory."""
        self.root = root
        self.session = uuid.uuid4().hex
        self.runtime = runtime_metadata()
        self._lock = threading.RLock()

    def _directory_path(self, artifact_id: str) -> Path:
        """Resolve an owned flat identity without creating or modifying storage."""
        if not artifact_id or artifact_id in {".", ".."} or Path(artifact_id).name != artifact_id:
            msg = "invalid artifact identity"
            raise ValueError(msg)
        directory = self.root / artifact_id
        if self.root.is_symlink() or directory.is_symlink():
            msg = "evidence directories must not be symlinks"
            raise ValueError(msg)
        return directory

    def directory(self, artifact_id: str) -> Path:
        """Create or validate an owned directory for writing evidence."""
        directory = self._directory_path(artifact_id)
        ensure_private_directory(self.root)
        ensure_private_directory(directory)
        return directory

    def _write(self, directory: Path, name: str, content: str) -> None:
        path = directory / name
        ensure_private_file(path)
        descriptor = os.open(path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)

    def submitted(self, artifact_id: str, text: str, payload: dict[str, Any]) -> None:
        """Record caller-supplied arguments separately from resolved generation settings."""
        try:
            with self._lock:
                directory = self.directory(artifact_id)
                self._write(directory, "source.txt", text)
                self._write(
                    directory,
                    "request.json",
                    json.dumps(
                        {
                            "arguments": {
                                key: value
                                for key, value in payload.items()
                                if key not in {"text", "op"}
                            },
                            "source_blake3": blake3(text.encode("utf-8")).hexdigest(),
                            "received_at": time.time(),
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                )
        except (OSError, ValueError, TypeError):
            log.warning("event=clip_evidence_capture_failed")

    def read_metadata(self, artifact_id: str, name: str) -> dict[str, Any] | None:
        """Read an owned metadata record, with missing legacy evidence left explicit."""
        try:
            path = self._directory_path(artifact_id) / name
            if path.is_symlink():
                return None
            result = json.loads(path.read_text())
            return result if isinstance(result, dict) else None
        except (OSError, ValueError):
            return None

    def audio_generated(self, artifact_id: str, path: Path) -> None:
        """Snapshot audio identity and numerical diagnostics before publication."""
        try:
            import numpy as np  # noqa: PLC0415
            import soundfile as sf  # noqa: PLC0415

            digest = blake3()
            with path.open("rb") as source:
                while block := source.read(1024 * 1024):
                    digest.update(block)
            with sf.SoundFile(path) as audio:
                peak = 0.0
                clipped = nonfinite = 0
                for samples in audio.blocks(blocksize=65536, dtype="float32", always_2d=True):
                    nonfinite += int(np.count_nonzero(~np.isfinite(samples)))
                    clipped += int(np.count_nonzero(np.abs(samples) >= _CLIPPING_THRESHOLD))
                    finite = samples[np.isfinite(samples)]
                    if finite.size:
                        peak = max(peak, float(np.max(np.abs(finite))))
                metadata = {
                    "blake3": digest.hexdigest(),
                    "sha256": file_sha256(path),
                    "sample_rate": audio.samplerate,
                    "channels": audio.channels,
                    "frames": len(audio),
                    "subtype": audio.subtype,
                    "peak": peak,
                    "clipped_samples": clipped,
                    "nonfinite_samples": nonfinite,
                }
            with self._lock:
                self._write(
                    self.directory(artifact_id), "audio.json", json.dumps(metadata, indent=2)
                )
        except (OSError, ValueError, RuntimeError):
            log.warning("event=clip_evidence_capture_failed")

    def prepare(self, work: SynthesisWork, engine: str) -> None:
        """Save the exact synthesis input and generation environment before rendering."""
        try:
            with self._lock:
                directory = self.directory(work.id)
                self._write(directory, "source.txt", work.text)
                self._write(
                    directory,
                    "generation.json",
                    json.dumps(
                        {
                            "artifact_id": work.id,
                            "utterance_id": work.utterance_id,
                            "segment_index": work.segment_index,
                            "voice": work.voice,
                            "speed": work.speed,
                            "engine": engine,
                            "captured_at": time.time(),
                            "runtime": self.runtime,
                        },
                        indent=2,
                    ),
                )
                self.record(work.id, "synthesis", "started")
        except (OSError, ValueError):
            log.warning("event=clip_evidence_capture_failed")

    def record(self, artifact_id: str, phase: str, event: str, **details: object) -> None:
        """Append one timestamped event; retain at most two 1 MiB logs per phase."""
        try:
            if phase not in {"synthesis", "playback"}:
                msg = "invalid evidence phase"
                raise ValueError(msg)  # noqa: TRY301 - rejected diagnostic is isolated here
            row = {
                "at": time.time(),
                "monotonic": time.monotonic(),
                "process_session": self.session,
                "event": event,
                **details,
            }
            encoded = json.dumps(row, ensure_ascii=False) + "\n"
            if len(encoded.encode()) > _MAX_LOG_BYTES:
                encoded = (
                    json.dumps(
                        {
                            "at": row["at"],
                            "event": "oversized_event_omitted",
                            "process_session": self.session,
                        }
                    )
                    + "\n"
                )
            with self._lock:
                directory = self.directory(artifact_id)
                path = directory / f"{phase}.jsonl"
                ensure_private_file(path)
                if path.stat().st_size + len(encoded.encode()) > _MAX_LOG_BYTES:
                    path.replace(directory / f"{phase}.previous.jsonl")
                    ensure_private_file(path)
                    self._write(
                        directory, "logs-truncated.txt", "Earlier events were rotated out.\n"
                    )
                descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    stream.write(encoded)
        except (OSError, ValueError, TypeError):
            log.warning("event=clip_evidence_capture_failed")

    def generated(self, artifact_id: str, metadata: dict[str, Any]) -> None:
        """Persist actual model/voice identities after the engine has loaded them."""
        try:
            with self._lock:
                self._write(
                    self.directory(artifact_id), "model.json", json.dumps(metadata, indent=2)
                )
        except (OSError, ValueError, TypeError):
            log.warning("event=clip_evidence_capture_failed")

    def export(  # noqa: C901, PLR0915 - one atomic archive and its missing-evidence manifest
        self, destination: Path, item: dict[str, Any], clips: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Create a selected-item ZIP exclusively; never overwrite an existing file."""
        if not destination.is_absolute() or destination.suffix.lower() != ".zip":
            msg = "choose an absolute .zip destination"
            raise ValueError(msg)
        warnings: list[str] = []
        manifest: dict[str, Any] = {
            "format_version": 1,
            "exported_at": time.time(),
            "export_runtime": runtime_metadata(),
            "item": item,
            "clips": [],
            "warnings": warnings,
        }
        descriptor = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        try:
            with (
                os.fdopen(descriptor, "wb") as output,
                zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive,
            ):
                for clip in clips:
                    artifact_id = str(clip["artifact_id"])
                    entry = {key: value for key, value in clip.items() if key != "audio_path"}
                    manifest["clips"].append(entry)
                    folder = f"clips/{artifact_id}"
                    directory = self._directory_path(artifact_id)
                    with self._lock:
                        for name in (
                            "source.txt",
                            "request.json",
                            "audio.json",
                            "generation.json",
                            "model.json",
                            "synthesis.previous.jsonl",
                            "synthesis.jsonl",
                            "playback.previous.jsonl",
                            "playback.jsonl",
                            "logs-truncated.txt",
                        ):
                            path = directory / name
                            if path.is_file() and not path.is_symlink():
                                archive.writestr(f"{folder}/{name}", path.read_bytes())
                            elif name in {"generation.json", "synthesis.jsonl", "playback.jsonl"}:
                                warnings.append(f"{artifact_id}: {name} was not captured")
                        if (directory / "logs-truncated.txt").exists():
                            warnings.append(f"{artifact_id}: older log events were rotated out")
                    # Legacy clips still export their exact source, but never pretend
                    # that today's environment generated yesterday's audio.
                    if not (directory / "source.txt").is_file():
                        archive.writestr(f"{folder}/source.txt", str(clip["text"]))
                    raw_path = clip.get("audio_path")
                    audio = Path(raw_path) if raw_path else None
                    if audio is None or audio.is_symlink() or not audio.is_file():
                        entry["audio_available"] = False
                        warnings.append(f"{artifact_id}: cached audio is missing")
                        continue
                    resolved = audio.resolve()
                    if not resolved.is_relative_to(self.root.resolve()):
                        msg = "audio is outside the owned cache"
                        raise ValueError(msg)  # noqa: TRY301 - removes partial archive on refusal
                    try:
                        with (
                            audio.open("rb") as source,
                            archive.open(f"{folder}/audio.wav", "w") as target,
                        ):
                            digest = hashlib.sha256()
                            blake = blake3()
                            size = 0
                            while block := source.read(1024 * 1024):
                                digest.update(block)
                                blake.update(block)
                                size += len(block)
                                target.write(block)
                        entry.update(
                            audio_available=True,
                            audio_sha256=digest.hexdigest(),
                            audio_blake3=blake.hexdigest(),
                            audio_bytes=size,
                        )
                    except FileNotFoundError:
                        entry["audio_available"] = False
                        warnings.append(f"{artifact_id}: audio was evicted during export")
                archive.writestr(
                    "manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False)
                )
                archive.writestr("source.txt", str(item.get("text", "")))
                archive.writestr(
                    "README.txt",
                    "AI-TTS local audio evidence\n\n"
                    "Contains the selected spoken content. Share only when you choose.\n"
                    "Each clips/ directory contains audio and synthesis/playback JSONL logs.\n"
                    "Times are Unix seconds; monotonic readings share a process_session.\n"
                    "Playback sessions identify replays. See manifest.json for missing evidence.\n"
                    "Generation-time versions live in generation.json, not export_runtime.\n",
                )
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return {"ok": True, "path": str(destination), "warnings": warnings}
