# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Interrupted service activation restores the prior configuration."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from scripts.install_application import activate_launch_agent

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("activation failure restores prior plist and prior loaded service"),
]


# Retire only when service activation no longer replaces a live configuration.
@pytest.mark.parametrize("interrupted_command", ["bootout", "bootstrap"])
@pytest.mark.parametrize("after_side_effect", [False, True])
@pytest.mark.parametrize("previously_loaded", [False, True])
def test_interrupted_activation_recovers_prior_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupted_command: str,
    *,
    after_side_effect: bool,
    previously_loaded: bool,
) -> None:
    output = tmp_path / "agent.plist"
    output.write_bytes(b"old configuration")
    staging = tmp_path / "staging"
    staging.mkdir()
    candidate = staging / "agent.plist"
    candidate.write_bytes(b"new configuration")
    loaded = b"old configuration" if previously_loaded else None
    interrupted = False

    def launchctl(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal loaded, interrupted
        del kwargs
        command = arguments[1]
        if command == "print":
            return subprocess.CompletedProcess(arguments, 0 if loaded else 3)
        should_interrupt = command == interrupted_command and not interrupted
        if should_interrupt and not after_side_effect:
            interrupted = True
            raise KeyboardInterrupt
        if command == "bootout":
            loaded = None
        if command == "bootstrap":
            loaded = output.read_bytes()
        if should_interrupt:
            interrupted = True
            raise KeyboardInterrupt
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr("scripts.install_application.subprocess.run", launchctl)
    with pytest.raises(KeyboardInterrupt):
        activate_launch_agent(launchctl="/owned/launchctl", candidate=candidate, output=output)

    assert (output.read_bytes(), loaded) == (
        b"old configuration",
        b"old configuration" if previously_loaded else None,
    )
