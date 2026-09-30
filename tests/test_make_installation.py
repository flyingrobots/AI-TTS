# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Make entrypoints report actual installation and daemon outcomes."""

from __future__ import annotations

import os
import plistlib
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


@pytest.fixture
def install_environment(tmp_path: Path) -> dict[str, str]:
    import sys  # noqa: PLC0415 - the owned tool shim uses this test interpreter

    commands = tmp_path / "commands"
    commands.mkdir()
    uv = commands / "uv"
    uv.write_text('#!/bin/sh\nexec "$AITTS_TEST_PYTHON" "$0.py" "$@"\n')
    uv.chmod(0o755)
    uv.with_suffix(".py").write_text(
        """import os, sys
from pathlib import Path
root = Path(os.environ["AITTS_TEST_ROOT"])
args = sys.argv[1:]
if args[:3] == ["run", "python", "-m"]:
    os.execv(sys.executable, [sys.executable, *args[2:]])
if args[:2] == ["run", "python"] and args[2].endswith("build_app_bundle.py"):
    if os.environ.get("AITTS_TEST_BUILD_FAILURE") == "1":
        sys.exit(9)
    output = Path(args[args.index("--output") + 1])
    output.mkdir(parents=True)
    (output / "version").write_text("new app")
elif args[:2] == ["tool", "install"]:
    (root / "cli-version").write_text("new cli")
elif args[:3] == ["tool", "dir", "--bin"]:
    print(root / "bin")
else:
    sys.exit(8)
"""
    )
    launchctl = commands / "launchctl"
    launchctl.write_text('#!/bin/sh\nexit "${AITTS_TEST_LAUNCHCTL_EXIT:-8}"\n')
    launchctl.chmod(0o755)
    (tmp_path / "cli-version").write_text("old cli")
    env = dict(os.environ, PATH=f"{commands}:/usr/bin:/bin")
    env["AITTS_TEST_ROOT"] = str(tmp_path)
    env["AITTS_TEST_PYTHON"] = sys.executable
    return env


def test_install_build_failure_does_not_replace_cli(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    env = dict(install_environment, AITTS_TEST_BUILD_FAILURE="1")
    result = subprocess.run(  # noqa: S603 - owned tool commands and artifact destinations
        [
            "/usr/bin/make",
            "--no-print-directory",
            "install",
            f"APP_BUNDLE={tmp_path / 'AI-TTS.app'}",
            f"LAUNCH_AGENT={tmp_path / 'agent.plist'}",
            f"LOG_PATH={tmp_path / 'logs' / 'daemon.log'}",
        ],
        cwd=REPOSITORY,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode != 0, (tmp_path / "cli-version").read_text()) == (True, "old cli")


def test_install_publishes_prepared_artifacts_to_explicit_destinations(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    env = dict(install_environment, AITTS_TEST_LAUNCHCTL_EXIT="0")
    app = tmp_path / "AI-TTS.app"
    agent = tmp_path / "agent.plist"
    log_path = tmp_path / "logs" / "daemon.log"
    result = subprocess.run(  # noqa: S603 - owned command implementations and destinations
        [
            "/usr/bin/make",
            "--no-print-directory",
            "install",
            f"APP_BUNDLE={app}",
            f"LAUNCH_AGENT={agent}",
            f"LOG_PATH={log_path}",
        ],
        cwd=REPOSITORY,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert {
        "cli": (tmp_path / "cli-version").read_text(),
        "app": (app / "version").read_text(),
        "daemon": plistlib.loads(agent.read_bytes())["ProgramArguments"],
    } == {
        "cli": "new cli",
        "app": "new app",
        "daemon": [str(tmp_path / "bin" / "ai-tts"), "daemon", "--log-file", str(log_path)],
    }
