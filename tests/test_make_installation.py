# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Make entrypoints report actual installation and daemon outcomes."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
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
elif args[:1] == ["export"]:
    # The lockfile export is offline and frozen, so the real uv runs it.
    os.execv(os.environ["AITTS_TEST_REAL_UV"], ["uv", *args])
elif args[:2] == ["tool", "install"]:
    (root / "cli-version").write_text("new cli")
    (root / "install-arguments.json").write_text(json.dumps(args))
    if "--constraints" in args:
        constraints = Path(args[args.index("--constraints") + 1])
        (root / "constraints.txt").write_text(constraints.read_text())
elif args[:3] == ["tool", "dir", "--bin"]:
    print(root / "bin")
else:
    sys.exit(8)
"""
    )
    launchctl = commands / "launchctl"
    launchctl.write_text('#!/bin/sh\nexec "$AITTS_TEST_PYTHON" "$0.py" "$@"\n')
    launchctl.chmod(0o755)
    launchctl.with_suffix(".py").write_text(
        """import os, sys, plistlib
from pathlib import Path
root = Path(os.environ["AITTS_TEST_ROOT"])
loaded = root / "service-loaded"
# launchd finishes removing a booted-out service asynchronously: it stays
# visible to this many `print` queries, and bootstrap fails with error 5.
teardown = root / "teardown-remaining"
lingering = int(teardown.read_text()) if teardown.exists() else 0
args = sys.argv[1:]
if args[0] == "print":
    if lingering:
        teardown.write_text(str(lingering - 1))
        sys.exit(0)
    sys.exit(0 if loaded.exists() else 3)
if args[0] == "bootout":
    loaded.unlink(missing_ok=True)
    teardown.write_text(os.environ.get("AITTS_TEST_TEARDOWN_POLLS", "0"))
elif args[0] == "bootstrap" and lingering:
    print("Bootstrap failed: 5: Input/output error", file=sys.stderr)
    sys.exit(5)
elif args[0] == "bootstrap":
    payload = plistlib.loads(Path(args[-1]).read_bytes())
    refuse = os.environ.get("AITTS_TEST_BOOTSTRAP_FAILURE") == "1"
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
    real_uv = shutil.which("uv")
    assert real_uv is not None, "uv is required to export the lockfile"
    env["AITTS_TEST_REAL_UV"] = real_uv
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
    assert "menu-bar app was not launched" in result.stdout


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


def test_install_resolves_the_daemon_environment_to_the_locked_versions(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    """Oracle: uv.lock is the tested runtime graph, so installation must not resolve past it.

    `uv tool install` ignores uv.lock. Without constraints, huggingface-hub 2.0
    made the resolver backtrack transformers to 4.12.2, whose tokenizers 0.10.3
    cannot be built, and every fresh `make install` failed.
    """
    import tomllib  # noqa: PLC0415

    result = run_installation(tmp_path, install_environment)
    assert result.returncode == 0, result.stderr
    arguments = json.loads((tmp_path / "install-arguments.json").read_text())
    assert "--constraints" in arguments, "the tool install resolves without the lockfile"

    pins = dict(
        line.split(";")[0].strip().split("==", 1)
        for line in (tmp_path / "constraints.txt").read_text().splitlines()
        if "==" in line and not line.lstrip().startswith("#")
    )
    lock = tomllib.loads((REPOSITORY / "uv.lock").read_text(encoding="utf-8"))
    locked: dict[str, set[str]] = {}
    for package in lock["package"]:
        locked.setdefault(package["name"], set()).add(package["version"])
    for name in ("kokoro", "transformers", "tokenizers", "huggingface-hub"):
        assert name in pins, f"{name} is not constrained"
        assert pins[name] in locked[name], f"{name}=={pins[name]} is not the locked version"


def test_install_rebuilds_the_checkout_instead_of_reusing_a_cached_build(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    """Oracle: `make install` installs this checkout's code.

    uv caches a local package build keyed on its metadata, not its sources. With
    the version unchanged at 0.1.0, a reinstall reported success and left the
    daemon running the previous code.
    """
    result = run_installation(tmp_path, install_environment)
    assert result.returncode == 0, result.stderr
    arguments = json.loads((tmp_path / "install-arguments.json").read_text())
    assert "--reinstall-package" in arguments, "uv may install a stale cached build"
    assert arguments[arguments.index("--reinstall-package") + 1] == "ai-tts"


def test_install_waits_for_launchd_to_release_the_previous_service(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    """Oracle: launchd's observed behavior, where bootout returns before teardown completes.

    Bootstrapping in that window failed with error 5 after every successful build.
    """
    agent = tmp_path / "agent.plist"
    agent.write_bytes(
        plistlib.dumps(
            {"Label": "com.flyingrobots.ai-tts", "ProgramArguments": ["/old/ai-tts", "daemon"]}
        )
    )
    (tmp_path / "service-loaded").write_text("running")
    env = dict(install_environment, AITTS_TEST_TEARDOWN_POLLS="3")

    result = run_installation(tmp_path, env)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "service-loaded").exists()
    assert plistlib.loads(agent.read_bytes())["ProgramArguments"][0] == str(
        tmp_path / "bin" / "ai-tts"
    )
