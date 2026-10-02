# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Interrupted service activation restores the prior configuration."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts.install_application import activate_launch_agent

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("activation failure restores prior plist and prior loaded service"),
]


# Retire only when service activation no longer replaces a live configuration.
@pytest.mark.parametrize("label", ["com.flyingrobots.ai-tts", "com.flyingrobots.ai-tts.menubar"])
@pytest.mark.parametrize("interrupted_command", ["bootout", "bootstrap"])
@pytest.mark.parametrize("after_side_effect", [False, True])
@pytest.mark.parametrize("previously_loaded", [False, True])
def test_interrupted_activation_recovers_prior_service(  # noqa: PLR0913 - fault matrix axes
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupted_command: str,
    *,
    label: str,
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
        if command in {"print", "bootout"}:
            assert arguments[-1].endswith(f"/{label}")
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
        activate_launch_agent(
            launchctl="/owned/launchctl", candidate=candidate, output=output, label=label
        )

    assert (output.read_bytes(), loaded) == (
        b"old configuration",
        b"old configuration" if previously_loaded else None,
    )


def test_activation_waits_for_launchd_teardown_before_registering_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oracle: launchd's transient EIO during bootout must not strand the service."""
    output = tmp_path / "agent.plist"
    output.write_bytes(b"incumbent")
    candidate = tmp_path / "candidate.plist"
    candidate.write_bytes(b"replacement")
    loaded = b"incumbent"
    remaining_teardown = 0

    def launchctl(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal loaded, remaining_teardown
        check = kwargs.get("check")
        command = arguments[1]
        code = 0
        # Observed launchd: the booted-out job stays visible to print for a
        # while, and bootstrap returns EIO (5) until it has gone.
        if command == "print":
            if remaining_teardown:
                remaining_teardown -= 1
            code = 0 if loaded or remaining_teardown else 3
        elif command == "bootout":
            loaded = b""
            remaining_teardown = 2
        elif command == "bootstrap":
            if remaining_teardown:
                code = 5
            else:
                loaded = output.read_bytes()
        if code and check:
            raise subprocess.CalledProcessError(code, arguments)
        return subprocess.CompletedProcess(arguments, code)

    monkeypatch.setattr("scripts.install_application.subprocess.run", launchctl)
    monkeypatch.setattr("scripts.install_application.time.sleep", lambda _seconds: None)
    activate_launch_agent(launchctl="/owned/launchctl", candidate=candidate, output=output)
    assert (output.read_bytes(), loaded) == (b"replacement", b"replacement")


# Retire only when activation no longer runs launchctl bootstrap itself.
def test_rejected_bootstrap_reports_launchd_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Oracle: launchctl's own rejection message reaches the installer's stderr."""
    output = tmp_path / "agent.plist"
    candidate = tmp_path / "candidate.plist"
    candidate.write_bytes(b"replacement")
    diagnostic = "Bootstrap failed: 9: owned launchd diagnostic\n"

    def launchctl(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if arguments[1] != "bootstrap":
            return subprocess.CompletedProcess(arguments, 3)
        # A child writes to an inherited stderr; a piped one goes to the caller.
        if kwargs.get("stderr") is subprocess.PIPE:
            return subprocess.CompletedProcess(arguments, 9, stderr=diagnostic.encode())
        sys.stderr.write(diagnostic)
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(9, arguments)
        return subprocess.CompletedProcess(arguments, 9)

    monkeypatch.setattr("scripts.install_application.subprocess.run", launchctl)
    with pytest.raises(subprocess.CalledProcessError):
        activate_launch_agent(launchctl="/owned/launchctl", candidate=candidate, output=output)
    assert diagnostic in capsys.readouterr().err


@pytest.mark.oracle(
    "launchd's observed behavior: bootout returns before teardown, and bootstrap "
    "fails with error 5 while the old service is still loaded"
)
def test_activation_gives_up_and_restores_when_the_old_service_never_leaves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "agent.plist"
    output.write_bytes(b"old configuration")
    staging = tmp_path / "staging"
    staging.mkdir()
    candidate = staging / "agent.plist"
    candidate.write_bytes(b"new configuration")
    calls: list[str] = []

    def launchctl(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        calls.append(arguments[1])
        # The old service is still loaded on every query; bootout never lands.
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr("scripts.install_application.subprocess.run", launchctl)
    monkeypatch.setattr("scripts.install_application.time.sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match=r"gui/\d+/com\.flyingrobots\.ai-tts"):
        activate_launch_agent(
            launchctl="/owned/launchctl", candidate=candidate, output=output, teardown_polls=3
        )

    assert output.read_bytes() == b"old configuration"
    # Bounded, and never a bootstrap that launchd would refuse.
    assert "bootstrap" not in calls
    assert calls.count("print") <= 1 + 3 + 1


@pytest.mark.oracle(
    "activation failure restores the prior loaded service, even while launchd is "
    "still tearing down the rolled-back replacement"
)
def test_rollback_reloads_the_prior_service_after_a_lingering_teardown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "agent.plist"
    output.write_bytes(b"old configuration")
    staging = tmp_path / "staging"
    staging.mkdir()
    candidate = staging / "agent.plist"
    candidate.write_bytes(b"new configuration")
    loaded: bytes | None = b"old configuration"
    lingering = 0
    interrupted = False

    def launchctl(arguments: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal loaded, lingering, interrupted
        del kwargs
        command = arguments[1]
        if command == "print":
            if lingering:
                lingering -= 1
                return subprocess.CompletedProcess(arguments, 0)
            return subprocess.CompletedProcess(arguments, 0 if loaded else 3)
        if command == "bootout":
            # Only the rollback's bootout of the replacement lingers.
            lingering = 2 if loaded == b"new configuration" else 0
            loaded = None
        if command == "bootstrap":
            if lingering:
                return subprocess.CompletedProcess(arguments, 5)
            loaded = output.read_bytes()
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr("scripts.install_application.subprocess.run", launchctl)
    monkeypatch.setattr("scripts.install_application.time.sleep", lambda _seconds: None)
    with pytest.raises(KeyboardInterrupt):
        activate_launch_agent(launchctl="/owned/launchctl", candidate=candidate, output=output)

    assert (output.read_bytes(), loaded) == (b"old configuration", b"old configuration")
