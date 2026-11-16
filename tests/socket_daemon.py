# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Launch an owned external daemon for the language-independent socket contract."""

from __future__ import annotations

import asyncio
import contextlib
import os
import shlex
import signal
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts.run_with_deadline import _signal_owned_group

_ROOT = Path(__file__).resolve().parents[1]
_LOG_LIMIT = 64 * 1024
_STATE_LIMIT = 64 * 1024**2
_ENTRY_LIMIT = 4096


class DaemonProcessError(RuntimeError):
    """The selected command could not satisfy the bounded fixture contract."""


@dataclass(frozen=True)
class SocketDaemon:
    """Only process custody and wire coordinates cross the fixture boundary."""

    socket_path: Path
    home: Path
    process: subprocess.Popen[bytes]

    def has_exited(self) -> bool:
        """Observe child exit without releasing its process-group identity."""
        if self.process.returncode is not None:
            return True
        if sys.platform != "darwin" or sys.version_info >= (3, 13):
            return (
                os.waitid(os.P_PID, self.process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                is not None
            )
        # Python 3.12 on Darwin does not expose waitid. An unreaped child must
        # still exist, so only an observed zombie state confirms its exit.
        result = subprocess.run(  # noqa: S603 - fixed executable and owned numeric child ID
            ["/bin/ps", "-o", "stat=", "-p", str(self.process.pid)],
            capture_output=True,
            text=True,
            check=True,
            timeout=1,
        )
        return result.stdout.strip().startswith("Z")

    async def wait_for_exit(self) -> None:
        """Wait for exit while retaining the unreaped identity anchor."""
        while True:
            if await asyncio.to_thread(self.has_exited):
                return
            await asyncio.sleep(0.01)


def python_daemon_command() -> list[str]:
    """Return the deterministic Python implementation, without a real audio device."""
    return [sys.executable, str(Path(__file__).with_name("fixture_daemon.py"))]


def _signal_group(process: subprocess.Popen[bytes], signum: int) -> None:
    if process.returncode is None:
        _signal_owned_group(process.pid, signum)


async def _retire(daemon: SocketDaemon) -> None:
    if daemon.process.returncode is not None:
        return
    _signal_group(daemon.process, signal.SIGTERM)
    try:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(daemon.wait_for_exit(), timeout=1)
    finally:
        # Keep the unreaped leader until the final group signal. Asyncio's
        # child watcher would otherwise release the ID before this point.
        _signal_group(daemon.process, signal.SIGKILL)
        await asyncio.to_thread(daemon.process.wait, timeout=1)


async def _capture(
    process: subprocess.Popen[bytes],
    output: bytearray,
    failures: list[str],
) -> None:
    if process.stdout is None:
        return
    stopped = False
    while True:
        try:
            chunk = os.read(process.stdout.fileno(), 4096)
        except BlockingIOError:
            await asyncio.sleep(0.01)
            continue
        if not chunk:
            return
        room = _LOG_LIMIT - len(output)
        output.extend(chunk[:room])
        if len(chunk) > room and not stopped:
            failures.append("daemon log limit exceeded")
            _signal_group(process, signal.SIGKILL)
            stopped = True


async def _watch_state(
    process: subprocess.Popen[bytes],
    root: Path,
    failures: list[str],
) -> None:
    try:
        await _check_state(process, root, failures)
    except OSError as exc:
        failures.append(f"daemon state monitor failed: {exc}")
        _signal_group(process, signal.SIGKILL)


async def _check_state(
    process: subprocess.Popen[bytes],
    root: Path,
    failures: list[str],
) -> None:
    def refuse(error: OSError) -> None:
        if (
            isinstance(error, FileNotFoundError)
            and isinstance(error.filename, str)
            and Path(error.filename) != root
            and Path(error.filename).is_relative_to(root)
            and root.is_dir()
        ):
            return
        raise error

    while process.returncode is None:
        size, count = 0, 0
        for folder, directories, files in os.walk(root, followlinks=False, onerror=refuse):
            count += len(directories) + len(files)
            if count > _ENTRY_LIMIT:
                failures.append("daemon state directory limit exceeded")
                _signal_group(process, signal.SIGKILL)
                return
            directories[:] = [
                name for name in directories if not (Path(folder) / name).is_symlink()
            ]
            for name in files:
                with contextlib.suppress(FileNotFoundError):
                    size += (Path(folder) / name).lstat().st_size
                if size > _STATE_LIMIT:
                    failures.append("daemon state directory limit exceeded")
                    _signal_group(process, signal.SIGKILL)
                    return
        await asyncio.sleep(0.05)


async def _ready(
    daemon: SocketDaemon,
    output: bytearray,
    failures: list[str],
    timeout: float,
    capture: asyncio.Task[None],
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        if failures:
            raise DaemonProcessError(failures[0])
        if await asyncio.to_thread(daemon.has_exited):
            await _retire(daemon)
            await asyncio.wait_for(capture, timeout=1)
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
        launch = asyncio.create_task(
            asyncio.to_thread(
                subprocess.Popen,
                argv,
                cwd=root,
                env=env,
                start_new_session=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        )
        try:
            process = await asyncio.shield(launch)
        except asyncio.CancelledError:
            process = await launch
            await _retire(SocketDaemon(socket_path, home, process))
            if process.stdout is not None:
                process.stdout.close()
            raise
        if process.stdout is not None:
            os.set_blocking(process.stdout.fileno(), False)
        output = bytearray()
        failures: list[str] = []
        capture, watcher = (
            asyncio.create_task(_capture(process, output, failures)),
            asyncio.create_task(_watch_state(process, root, failures)),
        )
        daemon = SocketDaemon(socket_path, home, process)
        try:
            await _ready(daemon, output, failures, startup_timeout, capture)
            yield daemon
            if failures:
                raise DaemonProcessError(failures[0])
            if await asyncio.to_thread(daemon.has_exited):
                message = "daemon exited during the scenario"
                raise DaemonProcessError(message)
        finally:
            try:
                await _retire(daemon)
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
                await asyncio.wait_for(capture, timeout=1)
                if process.stdout is not None:
                    process.stdout.close()
