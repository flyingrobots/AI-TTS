# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Hard-deadline runner contracts for non-pytest suites."""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from scripts import run_with_deadline

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("binding suite latency-budget requirement"),
]

RUNNER = Path(__file__).parents[1] / "scripts" / "run_with_deadline.py"


def test_deadline_runner_preserves_child_failure() -> None:
    """Oracle: a trustworthy gate must preserve, never absorb, a child's red status."""
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(RUNNER), "5", sys.executable, "-c", "raise SystemExit(7)"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 7


def test_deadline_runner_terminates_suite_overrun() -> None:
    """Oracle: declared suite ceiling is a gate with timeout exit status 124."""
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(RUNNER),
            "0.1",
            sys.executable,
            "-c",
            "import time; time.sleep(10)",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 124
    assert "suite latency budget exceeded" in result.stderr


def test_deadline_retires_descendants_after_the_group_leader_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oracle #105: timeout leaves no running descendant, even one ignoring SIGTERM.

    Delete only when process-group deadline ownership is retired or stronger coverage replaces it.
    """
    ready = tmp_path / "descendant.pid"
    child = (
        "import os,signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"Path({str(ready)!r}).write_text(str(os.getpid())); time.sleep(30)"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); time.sleep(30)"
    )
    constructor = subprocess.Popen
    owned: list[subprocess.Popen[bytes]] = []

    def start_ready(command: list[str], *, start_new_session: bool) -> subprocess.Popen[bytes]:
        # Establish fixture readiness before main starts its real wait deadline.
        process = constructor(command, start_new_session=start_new_session)
        owned.append(process)
        deadline = time.monotonic() + 5
        while not ready.exists() or not ready.read_text().strip():
            if time.monotonic() >= deadline:
                message = "owned descendant did not become ready"
                raise RuntimeError(message)
            time.sleep(0.005)
        return process

    def running(pid: int) -> bool:
        result = subprocess.run(  # noqa: S603 - inspect only the owned descendant
            ["/bin/ps", "-o", "stat=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
            timeout=1,
        )
        if result.returncode not in (0, 1) or result.stderr:
            message = f"owned process-state probe failed: {result.stderr}"
            raise RuntimeError(message)
        state = result.stdout.strip()
        return bool(state) and "Z" not in state

    try:
        with monkeypatch.context() as patch:
            patch.setattr(subprocess, "Popen", start_ready)
            run_with_deadline.main(["0.05", sys.executable, "-c", parent])
        pid = int(ready.read_text())
        deadline = time.monotonic() + 1
        while running(pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not running(pid), "timeout returned while its SIGTERM-resistant descendant ran"
    finally:
        for process in owned:
            # main() may already have reaped the leader; never signal that released ID.
            if process.returncode is None:
                run_with_deadline._signal_owned_group(process.pid, signal.SIGKILL)
                process.wait(timeout=1)
