# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Installation retires a running menu-bar UI by signal, without Apple events."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from scripts.install_application import retire_menu_bar

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "James's decision F: SIGTERM the installed UI only; a UI that outlives the "
        "allowance is reported and installation continues"
    ),
]

EXECUTABLE = Path("/owned/AI-TTS.app/Contents/MacOS/AITTSMenuBar")


# Retire only when installation no longer retires a running UI itself.
def test_a_ui_that_ignores_sigterm_is_reported_without_failing_installation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    signals: list[list[str]] = []

    def processes(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        if arguments[0] == "/owned/ps":
            listing = f"    1 /sbin/launchd\n 4242 {EXECUTABLE}\n 4243 {EXECUTABLE}-helper\n"
            return subprocess.CompletedProcess(arguments, 0, stdout=listing)
        signals.append(arguments[1:])
        # The UI ignores SIGTERM, so every liveness probe finds it alive.
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr("scripts.install_application.subprocess.run", processes)
    monkeypatch.setattr("scripts.install_application.time.sleep", lambda _seconds: None)

    retire_menu_bar(ps="/owned/ps", kill="/owned/kill", executable=EXECUTABLE, polls=3)

    assert {
        "terminated": [signal for signal in signals if signal[0] == "-TERM"],
        "probes": signals.count(["-0", "4242"]),
        "warned": "menu-bar app (PID 4242) did not exit" in capsys.readouterr().err,
    } == {"terminated": [["-TERM", "4242"]], "probes": 3, "warned": True}
