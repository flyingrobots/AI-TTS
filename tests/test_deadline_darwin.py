# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Darwin group-signalling refusal distinguishes zombies from live work."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

import pytest
from scripts import run_with_deadline

pytestmark = [pytest.mark.small, pytest.mark.oracle("timeout 124 and fail-closed cleanup refusal")]


@pytest.mark.parametrize("refused_signal", [signal.SIGTERM, signal.SIGKILL])
@pytest.mark.parametrize(
    ("membership", "benign"),
    [("42 Z\n99 R\n", True), ("42 Z\n42 S\n", False), ("", False)],
    ids=["owned-zombie-only", "owned-live-member", "unconfirmed-membership"],
)
def test_darwin_group_refusal_requires_verified_zombie_only_membership(
    monkeypatch: pytest.MonkeyPatch, refused_signal: int, membership: str, *, benign: bool
) -> None:
    """Delete only when Darwin deadline cleanup is retired or equivalently covered.

    Controlled Darwin boundary returns EPERM at either signal stage; unrelated
    live processes do not alter the owned group's zombie-only classification.
    """

    class Process:
        pid = 42

        def wait(self, timeout: float | None = None) -> int:
            if timeout is not None:
                command = "owned command"
                raise subprocess.TimeoutExpired(command, timeout)
            return -15

    def signal_group(_pid: int, sig: int) -> None:
        if sig == refused_signal:
            message = "Darwin group signal refused"
            raise PermissionError(message)

    response = subprocess.CompletedProcess(["/bin/ps"], 0, stdout=membership, stderr="")
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "darwin")
        patch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: Process())
        patch.setattr(subprocess, "run", lambda *_args, **_kwargs: response)
        patch.setattr(os, "killpg", signal_group)
        patch.setattr(time, "sleep", lambda _seconds: None)
        if benign:
            assert run_with_deadline.main(["0.05", "owned-command"]) == 124
        else:
            with pytest.raises(PermissionError, match="Darwin group signal refused"):
                run_with_deadline.main(["0.05", "owned-command"])
