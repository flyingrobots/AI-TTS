# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Launch an owned external daemon for the language-independent socket contract."""

from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
import signal
import sys
import tempfile
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_LOG_LIMIT = 64 * 1024
_STATE_LIMIT = 64 * 1024**2
_FILE_LIMIT = 4096


class DaemonProcessError(RuntimeError):
    """The selected command could not satisfy the bounded fixture contract."""


@dataclass(frozen=True)
class SocketDaemon:
    """Only process custody and wire coordinates cross the fixture boundary."""

    socket_path: Path
    home: Path
    process: asyncio.subprocess.Process


def python_daemon_command() -> list[str]:
    """Return the deterministic Python implementation, without a real audio device."""
    return [sys.executable, str(Path(__file__).with_name("fixture_daemon.py"))]


def _signal_group(process: asyncio.subprocess.Process, signum: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signum)


async def _capture(
    process: asyncio.subprocess.Process,
    output: bytearray,
    failures: list[str],
) -> None:
    if process.stdout is None:
        return
    stopped = False
    while chunk := await process.stdout.read(4096):
        room = _LOG_LIMIT - len(output)
        output.extend(chunk[:room])
        if len(chunk) > room and not stopped:
            failures.append("daemon log limit exceeded")
            _signal_group(process, signal.SIGKILL)
            stopped = True


async def _watch_state(
    process: asyncio.subprocess.Process,
    root: Path,
    failures: list[str],
) -> None:
    try:
        await _check_state(process, root, failures)
    except OSError as exc:
        failures.append(f"daemon state monitor failed: {exc}")
        _signal_group(process, signal.SIGKILL)


async def _check_state(
    process: asyncio.subprocess.Process,
    root: Path,
    failures: list[str],
) -> None:
    def refuse(error: OSError) -> None:
        raise error

    while process.returncode is None:
        size, count = 0, 0
        for folder, directories, files in os.walk(root, followlinks=False, onerror=refuse):
            directories[:] = [
                name for name in directories if not (Path(folder) / name).is_symlink()
            ]
            for name in files:
                with contextlib.suppress(FileNotFoundError):
                    size += (Path(folder) / name).lstat().st_size
                count += 1
                if size > _STATE_LIMIT or count > _FILE_LIMIT:
                    failures.append("daemon state directory limit exceeded")
                    _signal_group(process, signal.SIGKILL)
                    return
        await asyncio.sleep(0.05)


async def _ready(
    daemon: SocketDaemon, output: bytearray, failures: list[str], timeout: float
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if failures:
            raise DaemonProcessError(failures[0])
        if daemon.process.returncode is not None:
            detail = output.decode("utf-8", errors="replace").strip()
            message = f"daemon exited with status {daemon.process.returncode}: {detail}"
            raise DaemonProcessError(message)
        try:
            async with asyncio.timeout_at(deadline):
                _, writer = await asyncio.open_unix_connection(str(daemon.socket_path))
        except TimeoutError:
            break
        except (FileNotFoundError, ConnectionRefusedError):
            pass
        else:
            writer.close()
            await writer.wait_closed()
            return
        if asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(0.01)
    message = "daemon did not open its socket before the startup deadline"
    raise DaemonProcessError(message)


@contextlib.asynccontextmanager
async def daemon_process(
    parent: Path,
    *,
    command: Sequence[str] | None = None,
    startup_timeout: float = 3.0,
) -> AsyncIterator[SocketDaemon]:
    """Start the selected argv without a shell; own its paths, group and resource limits."""
    if command is None:
        selected = os.environ.get("AI_TTS_DAEMON_CMD")
        command = shlex.split(selected) if selected is not None else python_daemon_command()
    if not command:
        message = "AI_TTS_DAEMON_CMD must name an executable"
        raise DaemonProcessError(message)
    argv = list(command)
    if "/" in argv[0] and not Path(argv[0]).is_absolute():
        argv[0] = str(_ROOT / argv[0])
    with (
        tempfile.TemporaryDirectory(prefix="daemon-", dir=parent) as folder,
        tempfile.TemporaryDirectory(prefix="at-") as sockets,
    ):
        root, socket_path = Path(folder), Path(sockets) / "d.sock"
        home = root / "state"
        home.mkdir()
        (root / "tmp").mkdir()
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(root),
            "TMPDIR": str(root / "tmp"),
            "XDG_STATE_HOME": str(home),
            "XDG_CACHE_HOME": str(root / "cache"),
            "AI_TTS_HOME": str(home),
            "AI_TTS_SOCKET": str(socket_path),
            "PYTHONPATH": str(_ROOT / "src"),
            "PYTHONUNBUFFERED": "1",
        }
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=root,
            env=env,
            start_new_session=True,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output = bytearray()
        failures: list[str] = []
        capture = asyncio.create_task(_capture(process, output, failures))
        watcher = asyncio.create_task(_watch_state(process, root, failures))
        daemon = SocketDaemon(socket_path, home, process)
        try:
            await _ready(daemon, output, failures, startup_timeout)
            yield daemon
            if failures:
                raise DaemonProcessError(failures[0])
            if process.returncode is not None:
                message = f"daemon exited during the scenario with status {process.returncode}"
                raise DaemonProcessError(message)
        finally:
            _signal_group(process, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=1)
            except TimeoutError:
                _signal_group(process, signal.SIGKILL)
                await asyncio.wait_for(process.wait(), timeout=1)
            finally:
                _signal_group(process, signal.SIGKILL)
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
                await asyncio.wait_for(capture, timeout=1)
