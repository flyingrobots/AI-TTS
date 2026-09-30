# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Failed upgrades preserve the last working installed artifact."""

from __future__ import annotations

import plistlib
from pathlib import Path
from typing import Any

import pytest
from scripts import render_launch_agent as launch_agent

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("failed installation replacement preserves the incumbent artifact"),
]


@pytest.mark.parametrize("failure", ["log-validation", "serialization"])
def test_forced_launch_agent_failure_preserves_incumbent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    # Retire only with a stronger calibrated installation failure contract.
    output = tmp_path / "agent.plist"
    incumbent = b"known-good incumbent"
    output.write_bytes(incumbent)
    log_parent = tmp_path / "logs"
    if failure == "log-validation":
        log_parent.write_text("not a directory")
    else:

        def broken_dump(payload: Any, stream: Any, **kwargs: Any) -> None:
            del payload, kwargs
            stream.write(b"partial replacement")
            message = "seeded serialization failure"
            raise OSError(message)

        monkeypatch.setattr("scripts.render_launch_agent.plistlib.dump", broken_dump)

    expected_error = "File exists" if failure == "log-validation" else "seeded serialization"
    with pytest.raises(OSError, match=expected_error):
        launch_agent.main(
            [
                "--executable",
                str(tmp_path / "ai-tts"),
                "--output",
                str(output),
                "--log-path",
                str(log_parent / "daemon.log"),
                "--force",
            ]
        )

    assert (output.read_bytes() if output.exists() else None) == incumbent


def test_forced_launch_agent_success_publishes_complete_replacement(tmp_path: Path) -> None:
    output = tmp_path / "agent.plist"
    output.write_bytes(b"old version")
    executable = tmp_path / "new-ai-tts"
    log_path = tmp_path / "logs" / "daemon.log"

    launch_agent.main(
        [
            "--executable",
            str(executable),
            "--output",
            str(output),
            "--log-path",
            str(log_path),
            "--force",
        ]
    )

    assert plistlib.loads(output.read_bytes())["ProgramArguments"] == [
        str(executable),
        "daemon",
        "--log-file",
        str(log_path),
    ]
    assert output.stat().st_mode & 0o777 == 0o644


def test_unforced_launch_agent_preserves_concurrent_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "agent.plist"
    dump = plistlib.dump
    incumbent = b"concurrent installation"

    def racing_dump(payload: Any, stream: Any, **kwargs: Any) -> None:
        dump(payload, stream, **kwargs)
        output.write_bytes(incumbent)

    monkeypatch.setattr("scripts.render_launch_agent.plistlib.dump", racing_dump)
    with pytest.raises(FileExistsError):
        launch_agent.render_launch_agent(
            executable=tmp_path / "ai-tts", output=output, log_path=tmp_path / "logs" / "daemon.log"
        )
    assert output.read_bytes() == incumbent
