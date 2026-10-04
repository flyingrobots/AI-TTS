# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Replay guards must not signal numeric identities after reaping their leaders."""

from __future__ import annotations

import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.small, pytest.mark.oracle("owned validation process cleanup")]
ARTIFACTS = (
    Path(__file__).parents[1] / "docs/testing-evidence/artifacts/2026-10-04-deadline-descendants"
)


@pytest.mark.parametrize("guard", ["host", "inner"])
def test_replay_guard_never_signals_a_reaped_leaders_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, guard: str
) -> None:
    """Retire with these replay guards or stronger equivalent ownership coverage.

    Execute the actual guard entrypoint with controlled Docker/process boundaries.
    A completed leader's ID is immediately reused; no real process is started.
    """
    output = tmp_path / "output"
    filename = f"replay-{guard}-{'guard' if guard == 'host' else 'runner'}.txt"
    source = (ARTIFACTS / filename).read_text()
    source = source.replace("/work/evidence105", str(output))
    script = tmp_path / "guard.py"
    script.write_text(source)
    unrelated_signals: list[int] = []
    free = 60 * 1024**3

    class Process:
        pid = 42
        returncode: int | None = None

        def poll(self) -> int:
            self.returncode = 0
            return self.returncode

        def wait(self, **_kwargs: object) -> int:
            return 0

        def kill(self) -> None:
            if self.returncode is not None:
                unrelated_signals.append(self.pid)

    configuration = {
        "HostConfig": {
            "ReadonlyRootfs": True,
            "Tmpfs": {"/tmp": "rw,exec,size=1g"},  # noqa: S108 - simulated Docker metadata
            "LogConfig": {"Type": "json-file", "Config": {"max-file": "5", "max-size": "20m"}},
            "NanoCpus": 2_000_000_000,
            "Memory": 4 * 1024**3,
        },
        "Mounts": [{"Type": "volume", "Destination": "/work"}],
    }

    def command(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["docker", "inspect"]:
            stdout = json.dumps([configuration])
        elif args[:2] == ["docker", "exec"]:
            stdout = f"0 /work\n0 /tmp\n0 /dev\n{free}\n"
        elif args[:2] == ["docker", "kill"]:
            stdout = "owned worker stopped\n"
        else:
            message = f"unexpected guard command: {args}"
            raise AssertionError(message)
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    process = Process()
    with monkeypatch.context() as patch:
        patch.setattr(sys, "argv", [str(script), str(output)] if guard == "host" else [str(script)])
        patch.setenv("STAGE", "controlled")
        patch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
        patch.setattr(subprocess, "run", command)
        patch.setattr(subprocess, "check_output", lambda *_args, **_kwargs: "0 /owned\n")
        patch.setattr(os, "killpg", lambda pid, _sig: unrelated_signals.append(pid))
        patch.setattr(shutil, "disk_usage", lambda _path: SimpleNamespace(free=free))
        patch.setattr(os, "statvfs", lambda _path: SimpleNamespace(f_bavail=free, f_frsize=1))
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_path(str(script), run_name="__main__")

    assert exit_info.value.code == 0
    assert not unrelated_signals, "replay guard signalled a replacement after reaping its leader"
