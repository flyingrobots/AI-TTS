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
    # This fixture models macOS tools without touching real launchd, on any host.
    uname = commands / "uname"
    uname.write_text('#!/bin/sh\nprintf "Darwin\\n"\n')
    uname.chmod(0o755)
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
    # Installation must not send Apple events, which need Automation consent.
    # This owned osascript also shadows the real one, which could quit a real UI.
    osascript = commands / "osascript"
    osascript.write_text('#!/bin/sh\ntouch "$AITTS_TEST_ROOT/osascript-invoked"\nexit 1\n')
    osascript.chmod(0o755)
    # The owned process table: an incumbent-ui JSON file is a running UI, next
    # to a development build and an unrelated process that must not be touched.
    # SIGTERM leaves the UI alive for two more liveness probes, like AppKit
    # teardown.
    for tool, source in {
        "ps": """import json, os
from pathlib import Path
root = Path(os.environ["AITTS_TEST_ROOT"])
print("    1 /sbin/launchd")
print("   77 /development/.build/debug/AITTSMenuBar")
incumbent = root / "incumbent-ui"
if incumbent.exists():
    process = json.loads(incumbent.read_text())
    print(f" {process['pid']} {process['args']}")
""",
        "kill": """import json, os, sys
from pathlib import Path
root = Path(os.environ["AITTS_TEST_ROOT"])
signal, pid = sys.argv[1:]
with (root / "signals").open("a") as journal:
    journal.write(f"{signal} {pid}\\n")
incumbent = root / "incumbent-ui"
process = json.loads(incumbent.read_text()) if incumbent.exists() else None
if process is None or process["pid"] != pid:
    sys.exit(1)
if signal == "-TERM":
    process["remaining"] = 2
elif signal == "-0" and process.get("remaining") == 0:
    incumbent.unlink()
    sys.exit(1)
elif signal == "-0" and process.get("remaining") is not None:
    process["remaining"] -= 1
incumbent.write_text(json.dumps(process))
""",
    }.items():
        shim = commands / tool
        shim.write_text('#!/bin/sh\nexec "$AITTS_TEST_PYTHON" "$0.py" "$@"\n')
        shim.chmod(0o755)
        shim.with_suffix(".py").write_text(source)
    launchctl = commands / "launchctl"
    launchctl.write_text('#!/bin/sh\nexec "$AITTS_TEST_PYTHON" "$0.py" "$@"\n')
    launchctl.chmod(0o755)
    launchctl.with_suffix(".py").write_text(
        """import os, sys, plistlib
from pathlib import Path
root = Path(os.environ["AITTS_TEST_ROOT"])
# launchd finishes removing a booted-out service asynchronously: it stays
# visible to this many `print` queries, and bootstrap fails with error 5.
teardown = root / "teardown-remaining"
lingering = int(teardown.read_text()) if teardown.exists() else 0
args = sys.argv[1:]
label = (plistlib.loads(Path(args[-1]).read_bytes())["Label"]
         if args[0] == "bootstrap" else args[-1].split("/")[-1])
loaded = root / ("menu-bar-loaded" if label.endswith(".menubar") else "service-loaded")
if args[0] == "print":
    if lingering:
        teardown.write_text(str(lingering - 1))
        sys.exit(0)
    sys.exit(0 if loaded.exists() else 3)
if (args[0] == "bootout" and label.endswith(".menubar")
        and os.environ.get("AITTS_TEST_MENU_BAR_BOOTOUT_FAILURE") == "1"):
    sys.exit(9)
if (args[0] == "bootout" and not label.endswith(".menubar")
        and os.environ.get("AITTS_TEST_DAEMON_BOOTOUT_FAILURE") == "1"):
    sys.exit(9)
if args[0] == "bootout":
    loaded.unlink(missing_ok=True)
    teardown.write_text(os.environ.get("AITTS_TEST_TEARDOWN_POLLS", "0"))
elif args[0] == "bootstrap" and lingering:
    print("Bootstrap failed: 5: Input/output error", file=sys.stderr)
    sys.exit(5)
elif args[0] == "bootstrap":
    payload = plistlib.loads(Path(args[-1]).read_bytes())
    refuse = os.environ.get("AITTS_TEST_BOOTSTRAP_FAILURE") == "1"
    if (os.environ.get("AITTS_TEST_MENU_BAR_FAILURE") == "1"
            and label.endswith(".menubar")
            and payload["ProgramArguments"][0] != "/old/menu-bar"):
        sys.exit(9)
    if refuse and payload["ProgramArguments"][0] != "/old/ai-tts":
        sys.exit(9)
    # RunAtLoad starts the UI now; a live incumbent still holds its lock.
    lost = label.endswith(".menubar") and (root / "incumbent-ui").exists()
    loaded.write_text("lock-lost" if lost else "running")
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


# Retire only when installation no longer quits a running UI before registering it.
def test_install_waits_for_the_quit_menu_bar_to_exit_before_registering_it(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    """Oracle: the registered UI must not lose the single-instance lock to its predecessor."""
    write_incumbent_ui(tmp_path)
    result = run_installation(tmp_path, install_environment)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "menu-bar-loaded").read_text() == "running"


def write_incumbent_ui(tmp_path: Path) -> None:
    """Run the installed UI in the owned process table, as a manual launch would."""
    executable = tmp_path.resolve() / "AI-TTS.app" / "Contents" / "MacOS" / "AITTSMenuBar"
    (tmp_path / "incumbent-ui").write_text(json.dumps({"pid": "4242", "args": str(executable)}))


# Retire only when installation no longer retires a running UI itself.
def test_install_retires_the_running_ui_by_signal_without_apple_events(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    """Oracle: James's decision F; quitting needs no Automation consent and spares other builds."""
    write_incumbent_ui(tmp_path)
    result = run_installation(tmp_path, install_environment)
    assert result.returncode == 0, result.stderr
    signals = (tmp_path / "signals").read_text().splitlines()
    assert {
        "osascript": (tmp_path / "osascript-invoked").exists(),
        "terminated": [line for line in signals if line.startswith("-TERM")],
        "probed": {line.split()[1] for line in signals},
    } == {"osascript": False, "terminated": ["-TERM 4242"], "probed": {"4242"}}


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


@pytest.mark.parametrize("loaded", [False, True])
def test_uninstall_removes_both_agents_and_preserves_the_app(
    tmp_path: Path, install_environment: dict[str, str], *, loaded: bool
) -> None:
    # Enter at uninstall with an owned installation, not the native app publisher.
    (tmp_path / "agent.plist").write_bytes(b"owned daemon plist")
    (tmp_path / "com.flyingrobots.ai-tts.menubar.plist").write_bytes(b"owned menu plist")
    app = tmp_path / "AI-TTS.app"
    app.mkdir()
    (app / "version").write_text("new app")
    if loaded:
        (tmp_path / "service-loaded").write_text("running")
        (tmp_path / "menu-bar-loaded").write_text("running")
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
        "cli_kept": (tmp_path / "cli-version").exists(),
        "app": (tmp_path / "AI-TTS.app" / "version").read_text(),
    } == {
        "exit": 0,
        "daemon_plist": False,
        "ui_plist": False,
        "daemon_loaded": False,
        "ui_loaded": False,
        "cli_kept": False,
        "app": "new app",
    }


# Retire only when uninstall no longer boots out the agents itself.
@pytest.mark.parametrize("agent", ["menu_bar", "daemon"])
def test_uninstall_preserves_files_when_launchd_keeps_an_agent_loaded(
    tmp_path: Path, install_environment: dict[str, str], agent: str
) -> None:
    """Oracle: issue #73; a refused stop must preserve both plists and the CLI."""
    label = "com.flyingrobots.ai-tts" + (".menubar" if agent == "menu_bar" else "")
    plists = [tmp_path / "com.flyingrobots.ai-tts.menubar.plist", tmp_path / "agent.plist"]
    for plist in plists:
        plist.write_bytes(b"owned plist")
    (tmp_path / "menu-bar-loaded").write_text("running")
    (tmp_path / "service-loaded").write_text("running")
    (tmp_path / "cli-version").write_text("installed cli")
    result = subprocess.run(  # noqa: S603 - owned tools and installation destinations
        [
            "/usr/bin/make",
            "--no-print-directory",
            "uninstall",
            f"APP_BUNDLE={tmp_path / 'AI-TTS.app'}",
            f"LAUNCH_AGENT={tmp_path / 'agent.plist'}",
        ],
        cwd=REPOSITORY,
        env={**install_environment, f"AITTS_TEST_{agent.upper()}_BOOTOUT_FAILURE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert {
        "failed": result.returncode != 0,
        "reported": label in result.stderr,
        "plists_kept": all(plist.exists() for plist in plists),
        "cli_kept": (tmp_path / "cli-version").exists(),
        "daemon_loaded": (tmp_path / "service-loaded").exists(),
    } == {
        "failed": True,
        "reported": True,
        "plists_kept": True,
        "cli_kept": True,
        "daemon_loaded": True,
    }, result.stderr


def test_install_uses_a_modern_kokoro_tokenizer_with_binary_wheels(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    """Oracle: the locked constraints deliver a modern tokenizer, avoiding the obsolete Rust build.

    Unconstrained, uv resolved transformers 4.12.2 / tokenizers 0.10.3, whose
    source build failed. A separate `--with` range can contradict uv.lock.
    """
    result = run_installation(tmp_path, install_environment)
    assert result.returncode == 0, result.stderr
    arguments = json.loads((tmp_path / "install-arguments.json").read_text())
    extras = [
        arguments[index + 1] for index, argument in enumerate(arguments) if argument == "--with"
    ]
    assert not [extra for extra in extras if extra.startswith(("transformers", "tokenizers"))]
    pins = dict(
        line.split(";")[0].strip().split("==", 1)
        for line in (tmp_path / "constraints.txt").read_text().splitlines()
        if "==" in line and not line.lstrip().startswith("#")
    )

    def release(name: str) -> tuple[int, int]:
        major, minor = pins[name].split(".")[:2]
        return int(major), int(minor)

    assert release("transformers") >= (4, 46)
    assert release("tokenizers") > (0, 10)


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


def test_install_includes_the_terminal_dashboard_at_its_locked_versions(
    tmp_path: Path, install_environment: dict[str, str]
) -> None:
    """Oracle: README "Terminal dashboard": `ai-tts tui` works after `make install`.

    The installer requested only the daemon's extras, so the installed CLI had
    no Textual. The README's fallback, `uv tool install --force '.[tui]'`,
    replaced the whole tool environment without Kokoro, its English model or
    the lock constraints, which broke speech.
    """
    import tomllib  # noqa: PLC0415

    result = run_installation(tmp_path, install_environment)
    assert result.returncode == 0, result.stderr
    arguments = json.loads((tmp_path / "install-arguments.json").read_text())
    package = arguments[-1]
    assert package.endswith("[tui]"), f"the tool install omits the tui extra: {package}"

    pins = dict(
        line.split(";")[0].strip().split("==", 1)
        for line in (tmp_path / "constraints.txt").read_text().splitlines()
        if "==" in line and not line.lstrip().startswith("#")
    )
    lock = tomllib.loads((REPOSITORY / "uv.lock").read_text(encoding="utf-8"))
    locked = {package["name"]: package["version"] for package in lock["package"]}
    assert pins.get("textual") == locked["textual"], "Textual is not pinned to the lock"


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
