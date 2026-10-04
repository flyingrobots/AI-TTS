# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Calibrate ownership in the real-process regression's teardown schedules."""

from __future__ import annotations

import itertools
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from tests import test_deadline_runner

pytestmark = [pytest.mark.small, pytest.mark.oracle("issue #105: owned fixture cleanup")]


class Process:
    """Controlled leader: a reap releases its numeric identity for reuse."""

    pid = 42
    returncode: int | None = None

    def wait(self, timeout: float | None = None) -> int:
        if timeout == 0.05 and self.returncode is None:
            command = "owned command"
            raise subprocess.TimeoutExpired(command, timeout)
        self.returncode = -15
        return self.returncode

    def poll(self) -> int:
        self.returncode = -15
        return self.returncode


@pytest.mark.parametrize("outcome", ["complete", "readiness_failure", "darwin_zombie"])
def test_deadline_fixture_keeps_cleanup_within_its_owned_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    """Delete with the real-process fixture or stronger teardown schedule coverage."""
    unrelated_signals: list[int] = []
    owned_kills: list[int] = []

    process = Process()

    def start(*_args: object, **_kwargs: object) -> Process:
        if outcome != "readiness_failure":
            (tmp_path / "descendant.pid").write_text("43")
        return process

    def signal_group(_pid: int, sig: int) -> None:
        if process.returncode is not None:
            if outcome == "darwin_zombie":
                message = "Darwin zombie-only group"
                raise PermissionError(message)
            unrelated_signals.append(sig)
        elif sig == signal.SIGKILL:
            owned_kills.append(sig)

    clock = itertools.count(0, 10)
    response = subprocess.CompletedProcess(["/bin/ps"], 0, stdout="", stderr="")
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", start)
        patch.setattr(subprocess, "run", lambda *_args, **_kwargs: response)
        patch.setattr(os, "killpg", signal_group)
        patch.setattr(time, "monotonic", lambda: next(clock))
        patch.setattr(time, "sleep", lambda _seconds: None)
        if outcome == "readiness_failure":
            with pytest.raises(RuntimeError, match="owned descendant did not become ready"):
                test_deadline_runner.test_deadline_retires_descendants_after_the_group_leader_exits(
                    tmp_path, monkeypatch
                )
        else:
            test_deadline_runner.test_deadline_retires_descendants_after_the_group_leader_exits(
                tmp_path, monkeypatch
            )

    assert not unrelated_signals, "fixture signalled a replacement group after reaping its leader"
    assert owned_kills, "fixture never retired the group while its identity was still owned"
