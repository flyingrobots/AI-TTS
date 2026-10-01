# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Make entrypoints report actual installation and daemon outcomes."""

from __future__ import annotations

import json
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
        """import os, sys, json
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
elif args[:2] == ["tool", "uninstall"]:
    (root / "cli-version").unlink(missing_ok=True)
elif args[:2] == ["tool", "install"]:
    (root / "cli-version").write_text("new cli")
    (root / "install-arguments.json").write_text(json.dumps(args))
elif args[:3] == ["tool", "dir", "--bin"]:
    print(root / "bin")
else:
    sys.exit(8)
"""
    )
    osascript = commands / "osascript"
    osascript.write_text("#!/bin/sh\nexit 0\n")
    osascript.chmod(0o755)
    launchctl = commands / "launchctl"
    launchctl.write_text('#!/bin/sh\nexec "$AITTS_TEST_PYTHON" "$0.py" "$@"\n')
    launchctl.chmod(0o755)
    launchctl.with_suffix(".py").write_text(
        """import os, sys, plistlib
from pathlib import Path
root = Path(os.environ["AITTS_TEST_ROOT"])
args = sys.argv[1:]
label = (plistlib.loads(Path(args[-1]).read_bytes())["Label"]
         if args[0] == "bootstrap" else args[-1].split("/")[-1])
loaded = root / ("menu-bar-loaded" if label.endswith(".menubar") else "service-loaded")
if args[0] == "print":
    sys.exit(0 if loaded.exists() else 3)
if args[0] == "bootout":
    loaded.unlink(missing_ok=True)
elif args[0] == "bootstrap":
    payload = plistlib.loads(Path(args[-1]).read_bytes())
    refuse = os.environ.get("AITTS_TEST_BOOTSTRAP_FAILURE") == "1"
    if (os.environ.get("AITTS_TEST_MENU_BAR_FAILURE") == "1"
            and label.endswith(".menubar")
            and payload["ProgramArguments"][0] != "/old/menu-bar"):
        sys.exit(9)
    if refuse and payload["ProgramArguments"][0] != "/old/ai-tts":
        sys.exit(9)
    loaded.write_text("running")
else:
    sys.exit(8)
"""
    )
    (tmp_path / "cli-version").write_text("old cli")
    env = dict(os.environ, PATH=f"{commands}:/usr/bin:/bin")
    env["AITTS_TEST_ROOT"] = str(tmp_path)
    env["AITTS_TEST_PYTHON"] = sys.executable
    return env


def run_installation(tmp_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the real Make entrypoint with owned tools and installation paths."""
    return subprocess.run(  # noqa: S603 - only owned tools and artifact destinations
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


def test_install_build_failure_does_not_replace_cli(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    env = dict(install_environment, AITTS_TEST_BUILD_FAILURE="1")
    result = run_installation(tmp_path, env)
    assert (result.returncode != 0, (tmp_path / "cli-version").read_text()) == (True, "old cli")


def test_install_publishes_prepared_artifacts_to_explicit_destinations(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    env = dict(install_environment)
    app = tmp_path / "AI-TTS.app"
    agent = tmp_path / "agent.plist"
    log_path = tmp_path / "logs" / "daemon.log"
    result = run_installation(tmp_path, env)
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


@pytest.mark.parametrize("loaded", [False, True])
def test_failed_service_activation_restores_previous_configuration(
    tmp_path: Path, install_environment: dict[str, str], *, loaded: bool
) -> None:
    agent = tmp_path / "agent.plist"
    previous = plistlib.dumps(
        {"Label": "com.flyingrobots.ai-tts", "ProgramArguments": ["/old/ai-tts", "daemon"]}
    )
    agent.write_bytes(previous)
    if loaded:
        (tmp_path / "service-loaded").write_text("running")
    env = dict(install_environment, AITTS_TEST_BOOTSTRAP_FAILURE="1")
    result = run_installation(tmp_path, env)
    assert {
        "failed": result.returncode != 0,
        "configuration": agent.read_bytes(),
        "loaded": (tmp_path / "service-loaded").exists(),
    } == {"failed": True, "configuration": previous, "loaded": loaded}


def test_install_reports_registration_without_claiming_daemon_health(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    # The owned launchctl accepts registration; no daemon process is running.
    result = run_installation(tmp_path, install_environment)

    assert result.returncode == 0, result.stderr
    assert "daemon is registered" in result.stdout
    assert "daemon is running" not in result.stdout
    assert "menu-bar app is registered too" in result.stdout


def test_install_includes_the_english_model_in_the_daemon_environment(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    """Oracle: installed English speech needs no runtime package installer."""
    result = run_installation(tmp_path, install_environment)
    assert result.returncode == 0, result.stderr
    arguments = json.loads((tmp_path / "install-arguments.json").read_text())
    extras = [
        arguments[index + 1] for index, argument in enumerate(arguments) if argument == "--with"
    ]
    assert (
        "https://github.com/explosion/spacy-models/releases/download/"
        "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
    ) in extras


# Retire only when installation no longer owns the menu-bar login/crash policy.
def test_install_registers_independent_menu_bar_startup(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    result = run_installation(tmp_path, install_environment)
    assert result.returncode == 0, result.stderr
    payload = plistlib.loads((tmp_path / "com.flyingrobots.ai-tts.menubar.plist").read_bytes())
    assert {
        "label": payload["Label"],
        "executable": payload["ProgramArguments"],
        "login": payload["RunAtLoad"],
        "restart": payload["KeepAlive"],
        "session": payload["LimitLoadToSessionType"],
        "managed": payload["EnvironmentVariables"],
        "registered": (tmp_path / "menu-bar-loaded").exists(),
        "daemon_registered": (tmp_path / "service-loaded").exists(),
    } == {
        "label": "com.flyingrobots.ai-tts.menubar",
        "executable": [str(tmp_path / "AI-TTS.app" / "Contents" / "MacOS" / "AITTSMenuBar")],
        "login": True,
        "restart": {"SuccessfulExit": False},
        "session": "Aqua",
        "managed": {"AITTS_MENU_BAR_AGENT": "1"},
        "registered": True,
        "daemon_registered": True,
    }


@pytest.mark.parametrize("loaded", [False, True])
def test_failed_menu_bar_activation_preserves_its_incumbent_and_registered_daemon(
    tmp_path: Path, install_environment: dict[str, str], *, loaded: bool
) -> None:
    agent = tmp_path / "com.flyingrobots.ai-tts.menubar.plist"
    previous = plistlib.dumps(
        {"Label": "com.flyingrobots.ai-tts.menubar", "ProgramArguments": ["/old/menu-bar"]}
    )
    agent.write_bytes(previous)
    if loaded:
        (tmp_path / "menu-bar-loaded").write_text("running")
    result = run_installation(tmp_path, dict(install_environment, AITTS_TEST_MENU_BAR_FAILURE="1"))
    assert {
        "failed": result.returncode != 0,
        "configuration": agent.read_bytes(),
        "ui_loaded": (tmp_path / "menu-bar-loaded").exists(),
        "daemon_loaded": (tmp_path / "service-loaded").exists(),
    } == {
        "failed": True,
        "configuration": previous,
        "ui_loaded": loaded,
        "daemon_loaded": True,
    }


def test_uninstall_removes_both_agents_and_preserves_the_app(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    result = run_installation(tmp_path, install_environment)
    assert result.returncode == 0, result.stderr
    result = subprocess.run(  # noqa: S603 - owned tools and installation destinations
        [
            "/usr/bin/make",
            "--no-print-directory",
            "uninstall",
            f"APP_BUNDLE={tmp_path / 'AI-TTS.app'}",
            f"LAUNCH_AGENT={tmp_path / 'agent.plist'}",
        ],
        cwd=REPOSITORY,
        env=install_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert {
        "exit": result.returncode,
        "daemon_plist": (tmp_path / "agent.plist").exists(),
        "ui_plist": (tmp_path / "com.flyingrobots.ai-tts.menubar.plist").exists(),
        "daemon_loaded": (tmp_path / "service-loaded").exists(),
        "ui_loaded": (tmp_path / "menu-bar-loaded").exists(),
        "app": (tmp_path / "AI-TTS.app" / "version").read_text(),
    } == {
        "exit": 0,
        "daemon_plist": False,
        "ui_plist": False,
        "daemon_loaded": False,
        "ui_loaded": False,
        "app": "new app",
    }


def test_install_uses_a_modern_kokoro_tokenizer_with_binary_wheels(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    """Oracle: Kokoro's supported Transformers 4 API avoids the obsolete Rust build."""
    result = run_installation(tmp_path, install_environment)
    assert result.returncode == 0, result.stderr
    arguments = json.loads((tmp_path / "install-arguments.json").read_text())
    extras = [
        arguments[index + 1] for index, argument in enumerate(arguments) if argument == "--with"
    ]
    assert "transformers>=4.46,<5" in extras
