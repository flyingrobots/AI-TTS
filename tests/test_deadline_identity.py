# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Deadline cleanup preserves ownership across numeric process-group reuse."""

from __future__ import annotations

import os
import subprocess
import time

import pytest
from scripts import run_with_deadline

pytestmark = [pytest.mark.small, pytest.mark.oracle("issue #105: isolate unrelated processes")]


def test_timeout_never_signals_a_replacement_process_group(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retire only with the deadline ownership contract or stronger equivalent coverage.

    The controlled OS reuses the group ID immediately after the leader is reaped.
    A signal to that replacement is the failure, regardless of cleanup choreography.
    """
    owned = True
    unrelated_signals: list[int] = []

    class Process:
        pid = 42

        def wait(self, timeout: float | None = None) -> int:
            nonlocal owned
            if timeout is not None:
                command = "owned command"
                raise subprocess.TimeoutExpired(command, timeout)
            owned = False
            return -15

        def poll(self) -> int:
            nonlocal owned
            owned = False
            return -15

    def signal_group(pid: int, sig: int) -> None:
        if pid == Process.pid and not owned and sig:
            unrelated_signals.append(sig)

    clock = iter((0.0, 0.0, 3.0))
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: Process())
        patch.setattr(os, "killpg", signal_group)
        patch.setattr(time, "monotonic", lambda: next(clock))
        patch.setattr(time, "sleep", lambda _seconds: None)
        run_with_deadline.main(["0.05", "owned-command"])

    assert unrelated_signals == [], "cleanup signalled an unrelated group after numeric ID reuse"
