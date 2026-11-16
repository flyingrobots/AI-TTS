# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""External daemon process admission, isolation and bounded failure contracts."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from tests import socket_daemon
from tests.socket_daemon import DaemonProcessError, daemon_process, python_daemon_command

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("issue #114: operator command, isolated state, bounded startup and cleanup"),
]


async def test_operator_command_gets_owned_paths_and_stops_at_teardown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = (
        "import json,os,pathlib; "
        "pathlib.Path(os.environ['AI_TTS_HOME']).joinpath('command.json').write_text("
        "json.dumps({'home':os.environ['HOME'],'socket':os.environ['AI_TTS_SOCKET']})); "
        f"os.execv({sys.executable!r}, {python_daemon_command()!r})"
    )
    monkeypatch.setenv("AI_TTS_DAEMON_CMD", shlex.join([sys.executable, "-c", script]))
    async with daemon_process(tmp_path) as daemon:
        observed = json.loads((daemon.home / "command.json").read_text())
        assert observed["socket"] == str(daemon.socket_path)
        assert Path(observed["home"]).is_relative_to(tmp_path)
        assert daemon.process.pid != os.getpid()
        assert daemon.socket_path.is_socket()
    assert daemon.process.returncode is not None
    assert not daemon.socket_path.exists()


async def test_early_exit_reports_status_and_bounded_diagnostics(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "print('startup refused', flush=True); raise SystemExit(17)"]
    with pytest.raises(DaemonProcessError, match=r"exited.*17.*startup refused"):
        async with daemon_process(tmp_path, command=command):
            pytest.fail("an exited daemon was admitted")


async def test_missing_socket_expires_and_reaps_the_owned_process(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "import time; time.sleep(60)"]
    with pytest.raises(DaemonProcessError, match=r"socket.*deadline"):
        async with daemon_process(tmp_path, command=command, startup_timeout=0.1):
            pytest.fail("a daemon without a socket was admitted")
    assert not list(tmp_path.iterdir()), "failed startup must remove its owned state directory"


async def test_unbounded_child_output_is_stopped_at_the_log_limit(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-c",
        "import sys,time; sys.stdout.write('x'*100000); sys.stdout.flush(); time.sleep(60)",
    ]
    with pytest.raises(DaemonProcessError, match="log limit"):
        async with daemon_process(tmp_path, command=command):
            pytest.fail("a daemon exceeding its diagnostic budget was admitted")


async def test_state_size_limit_stops_a_child_before_socket_admission(tmp_path: Path) -> None:
    script = (
        "import os,pathlib,time; "
        "p=pathlib.Path(os.environ['AI_TTS_HOME'])/'oversize'; "
        "p.open('wb').truncate(65*1024**2); time.sleep(60)"
    )
    with pytest.raises(DaemonProcessError, match="state directory limit"):
        async with daemon_process(tmp_path, command=[sys.executable, "-c", script]):
            pytest.fail("a daemon exceeding its state budget was admitted")
    assert not list(tmp_path.iterdir())


async def test_exit_after_admission_is_a_fixture_failure(tmp_path: Path) -> None:
    async def kill_during_scenario() -> None:
        async with daemon_process(tmp_path) as daemon:
            os.kill(daemon.process.pid, signal.SIGKILL)
            await asyncio.wait_for(daemon.wait_for_exit(), timeout=1)

    with pytest.raises(DaemonProcessError, match="exited during the scenario"):
        await kill_during_scenario()


def test_cleanup_never_signals_a_reaped_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    released = SimpleNamespace(pid=42, returncode=0)
    socket_daemon._signal_group(cast("Any", released), signal.SIGKILL)
    assert signals == [], "a reaped identity can belong to an unrelated replacement group"


async def test_cancelled_start_retires_a_child_created_by_the_launcher_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started, release = threading.Event(), threading.Event()
    children: list[subprocess.Popen[bytes]] = []
    original = subprocess.Popen
    command = [sys.executable, "-c", "import time; time.sleep(60)"]

    def launch(*args: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
        child = original(*args, **kwargs)
        if args[0] == command:
            children.append(child)
            started.set()
            if not release.wait(2):
                raise TimeoutError
        return child

    async def enter() -> None:
        async with daemon_process(tmp_path, command=command):
            pytest.fail("the command has no socket")

    monkeypatch.setattr(subprocess, "Popen", launch)
    task = asyncio.create_task(enter())
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert children[0].returncode is not None, "cancelled launch left its child running"
    finally:
        release.set()
        for child in children:
            if child.returncode is None:
                socket_daemon._signal_group(child, signal.SIGKILL)
                await asyncio.to_thread(child.wait, timeout=1)
