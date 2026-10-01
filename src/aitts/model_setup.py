# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Guided installation into private, independently publishable model runtimes."""

from __future__ import annotations

import json
import os
import platform
import select
import shutil
import signal
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from aitts.adapters.private_files import ensure_private_directory
from aitts.engines.managed import runtime_environment
from aitts.model_catalog import MODELS, WORKER_PROTOCOL_VERSION

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

_LOG_LIMIT = 64 * 1024


class ModelSetupError(Exception):
    """A recoverable, content-free setup failure suitable for the native UI."""


class SetupCancelledError(ModelSetupError):
    """The user cancelled; the incumbent runtime remains untouched."""


def supported_model(name: str) -> str | None:
    """Report hardware incompatibility without hiding the model from discovery."""
    model = MODELS[name]
    if model.apple_silicon and (platform.system() != "Darwin" or platform.machine() != "arm64"):
        return "Requires a Mac with Apple Silicon."
    return None


def installed_runtime(home: Path, name: str) -> Path | None:
    """Only complete catalog-matching manifests make a runtime selectable."""
    manifest = home / "model-runtimes" / f"{name}.json"
    try:
        if manifest.is_symlink():
            return None
        payload = json.loads(manifest.read_text())
        directory = payload["directory"]
        if (
            payload.get("revision") != MODELS[name].revision
            or payload.get("worker_protocol") != WORKER_PROTOCOL_VERSION
            or not isinstance(directory, str)
            or not directory.startswith(f"{name}-")
            or Path(directory).name != directory
        ):
            return None
        root = manifest.parent / directory
        if (
            root.is_symlink()
            or not (root / "venv/bin/python").is_file()
            or not (root / "adapter/aitts/model_worker.py").is_file()
        ):
            return None
        if any(not (root / "assets" / file).is_file() for file in MODELS[name].files):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    else:
        return root


class RuntimeInstaller:
    """Build, download and prime a candidate before publishing a durable manifest."""

    def __init__(self, home: Path) -> None:
        """Keep all installation state under the user's private daemon home."""
        self.home = home

    def install(
        self, name: str, cancelled: threading.Event, progress: Callable[[str], None]
    ) -> Path:
        """Install a curated model; a failed/cancelled candidate never replaces the incumbent."""
        if name not in MODELS:
            message = "Unknown speech model."
            raise ModelSetupError(message)
        incompatible = supported_model(name)
        if incompatible:
            raise ModelSetupError(incompatible)
        uv = shutil.which("uv") or next(
            (
                str(path)
                for path in (
                    Path.home() / ".local/bin/uv",
                    Path("/opt/homebrew/bin/uv"),
                    Path("/usr/local/bin/uv"),
                )
                if path.is_file() and os.access(path, os.X_OK)
            ),
            None,
        )
        if uv is None:
            message = "The runtime installer is unavailable. Reinstall AI-TTS, then retry setup."
            raise ModelSetupError(message)
        runtimes = self.home / "model-runtimes"
        ensure_private_directory(runtimes)
        root = runtimes / f"{name}-{uuid.uuid4().hex}"
        ensure_private_directory(root)
        published = False
        try:
            progress("Installing runtime")
            environment = runtime_environment(root)
            environment.pop("HF_HUB_OFFLINE", None)
            environment.pop("TRANSFORMERS_OFFLINE", None)
            environment["HF_HOME"] = str(runtimes / "download-cache")
            self.run([uv, "venv", "--python", "3.12", str(root / "venv")], environment, cancelled)
            self.run(
                [
                    uv,
                    "pip",
                    "install",
                    "--python",
                    str(root / "venv/bin/python"),
                    "--require-hashes",
                    "--requirements",
                    str(Path(__file__).parent / "runtime_requirements" / f"{name}.txt"),
                ],
                environment,
                cancelled,
            )
            # The installed package is the source; no checkout or executable shell text is needed.
            shutil.copytree(
                Path(__file__).parent,
                root / "adapter/aitts",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            progress("Downloading and checking model")
            self.run(
                [
                    str(root / "venv/bin/python"),
                    "-m",
                    "aitts.model_worker",
                    "prepare",
                    name,
                    str(root),
                ],
                environment,
                cancelled,
            )
            if cancelled.is_set():
                raise SetupCancelledError
            if any(not (root / "assets" / file).is_file() for file in MODELS[name].files):
                message = "The model download is incomplete. Retry setup."
                raise ModelSetupError(message)
            manifest = runtimes / f".{name}-{uuid.uuid4().hex}.json"
            try:
                with manifest.open("x", encoding="utf-8") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    json.dump(
                        {
                            "directory": root.name,
                            "revision": MODELS[name].revision,
                            "worker_protocol": WORKER_PROTOCOL_VERSION,
                        },
                        stream,
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                manifest.replace(runtimes / f"{name}.json")
                published = True
            finally:
                manifest.unlink(missing_ok=True)
            return root
        finally:
            if not published:
                shutil.rmtree(root, ignore_errors=True)

    def run(
        self, arguments: list[str], environment: dict[str, str], cancelled: threading.Event
    ) -> None:
        """Bound installer diagnostics and kill the whole tool group on cancellation."""
        if cancelled.is_set():
            raise SetupCancelledError
        tail = bytearray()
        with subprocess.Popen(  # noqa: S603 - curated package/model arguments and owned runtime paths
            arguments,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        ) as process:
            try:
                if process.stdout is None:
                    raise OSError
                while process.poll() is None:
                    if cancelled.is_set():
                        raise SetupCancelledError
                    ready, _, _ = select.select([process.stdout], [], [], 0.1)
                    if ready:
                        tail.extend(os.read(process.stdout.fileno(), 8192))
                        del tail[:-_LOG_LIMIT]
                if process.returncode != 0:
                    message = "Setup failed. Check your connection and free disk space, then retry."
                    raise ModelSetupError(message)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=2)
                # Setup contains no submitted speech; retain only bounded, owner-only tool output.
                diagnostic_path = self.home / "model-runtimes/setup.log"
                with diagnostic_path.open("wb") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(tail[-_LOG_LIMIT:])
