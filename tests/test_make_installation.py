# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Make entrypoints report actual installation and daemon outcomes."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("README installation and daemon diagnostic command contracts"),
]
REPOSITORY = Path(__file__).parents[1]


def test_doctor_reports_failed_daemon_check_from_uv_tool_directory(tmp_path: Path) -> None:
    commands = tmp_path / "commands"
    commands.mkdir()
    tool_bin = tmp_path / "tool-bin"
    tool_bin.mkdir()
    uv = commands / "uv"
    uv.write_text('#!/bin/sh\nprintf "%s\\n" "$AITTS_TEST_TOOL_BIN"\n')
    uv.chmod(0o755)
    cli = tool_bin / "ai-tts"
    cli.write_text("#!/bin/sh\nexit 7\n")
    cli.chmod(0o755)
    env = dict(os.environ, PATH=f"{commands}:/usr/bin:/bin")
    env["AITTS_TEST_TOOL_BIN"] = str(tool_bin)

    result = subprocess.run(
        ["/usr/bin/make", "--no-print-directory", "doctor", "INSTALLER=/usr/bin/true"],
        cwd=REPOSITORY,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert "daemon is not answering (exit 7)" in result.stdout
