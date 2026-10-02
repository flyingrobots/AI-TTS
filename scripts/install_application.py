# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Prepare installation artifacts before replacing the installed application."""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from scripts.build_app_bundle import BUNDLE_IDENTIFIER, publish_app_bundle
from scripts.render_launch_agent import MENU_BAR_LABEL, render_launch_agent, render_menu_bar_agent

SPACY_MODEL = (
    "https://github.com/explosion/spacy-models/releases/download/"
    "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
)


# launchd removes a booted-out service asynchronously, and bootstrapping the
# same label before it has gone fails with error 5. Poll this many times, this
# far apart, for it to leave.
TEARDOWN_POLLS = 100
TEARDOWN_POLL_SECONDS = 0.1

# The quit reply can arrive before the old UI exits and releases its
# single-instance lock. Poll this many times, this far apart, for it to leave.
QUIT_POLLS = 100
QUIT_POLL_SECONDS = 0.1


class LaunchdTeardownTimeoutError(RuntimeError):
    """The previous service was still loaded after the teardown allowance."""


def _quit_menu_bar(osascript: str) -> None:
    """Retire a running UI so the registered agent's instance can take the lock."""
    application = f'application id "{BUNDLE_IDENTIFIER}"'
    subprocess.run(  # noqa: S603 - fixed AppleScript, no interpolated user input
        [osascript, "-e", f"if {application} is running then tell {application} to quit"],
        check=True,
    )
    for _ in range(QUIT_POLLS):
        running = subprocess.run(  # noqa: S603 - fixed AppleScript, no interpolated user input
            [osascript, "-e", f"{application} is running"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if running == "false":
            return
        time.sleep(QUIT_POLL_SECONDS)
    message = "the menu-bar app is still quitting; re-run once it has exited"
    raise RuntimeError(message)


def _await_teardown(launchctl: str, service: str, polls: int) -> None:
    for _ in range(polls):
        still_loaded = (
            subprocess.run(  # noqa: S603 - resolved launchctl and fixed service label
                [launchctl, "print", service],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        )
        if not still_loaded:
            return
        time.sleep(TEARDOWN_POLL_SECONDS)
    message = f"launchd is still tearing down {service}; re-run once it has gone"
    raise LaunchdTeardownTimeoutError(message)


def activate_launch_agent(
    *,
    launchctl: str,
    candidate: Path,
    output: Path,
    label: str = "com.flyingrobots.ai-tts",
    teardown_polls: int = TEARDOWN_POLLS,
) -> None:
    """Restore the previous configuration if launchd rejects its replacement."""
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{label}"
    loaded = (
        subprocess.run(  # noqa: S603 - resolved launchctl and fixed service label
            [launchctl, "print", service],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    )
    backup = candidate.with_name(f".previous-{candidate.name}")
    if output.exists():
        shutil.copy2(output, backup)
    elif loaded:
        message = "cannot replace a loaded launch agent without its previous plist"
        raise RuntimeError(message)
    bootstrap_attempted = False
    try:
        candidate.replace(output)
        result = subprocess.run(  # noqa: S603 - resolved launchctl and fixed service label
            [launchctl, "bootout", service],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if loaded:
            result.check_returncode()
        _await_teardown(launchctl, service, teardown_polls)
        bootstrap_attempted = True
        subprocess.run(  # noqa: S603 - explicit installed plist
            [launchctl, "bootstrap", domain, str(output)], check=True
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        LaunchdTeardownTimeoutError,
        KeyboardInterrupt,
    ):
        if backup.exists():
            backup.replace(output)
        else:
            output.unlink(missing_ok=True)
        # A subprocess may complete its side effect before an interrupt reaches
        # Python. Retire a possible replacement before restoring registration.
        if bootstrap_attempted:
            subprocess.run(  # noqa: S603 - fixed service being rolled back
                [launchctl, "bootout", service],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # Let that bootout land before deciding whether to reload the
            # incumbent; a lingering replacement reads as still loaded.
            with contextlib.suppress(LaunchdTeardownTimeoutError):
                _await_teardown(launchctl, service, teardown_polls)
        still_loaded = (
            subprocess.run(  # noqa: S603 - inspect actual recovery state
                [launchctl, "print", service],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
        )
        if loaded and not still_loaded:
            recovery = subprocess.run(  # noqa: S603 - the restored incumbent plist
                [launchctl, "bootstrap", domain, str(output)], check=False
            )
            if recovery.returncode != 0:
                sys.stderr.write(
                    "Previous plist restored, but launchd could not reload it; "
                    "inspect the service before retrying.\n"
                )
        raise


def install_application(
    *, app: Path, launch_agent: Path, log_path: Path, python_version: str
) -> None:
    """Stage the app and plist before asking uv to replace the installed CLI."""
    uv = shutil.which("uv")
    launchctl = shutil.which("launchctl")
    osascript = shutil.which("osascript")
    if uv is None or launchctl is None or osascript is None:
        message = "uv, launchctl and osascript are required to install AI-TTS"
        raise RuntimeError(message)
    repository = Path(__file__).resolve().parents[1]
    if app.exists() and not app.is_dir():
        message = f"app destination is not a directory: {app}"
        raise NotADirectoryError(message)
    app.parent.mkdir(parents=True, exist_ok=True)
    launch_agent.parent.mkdir(parents=True, exist_ok=True)
    menu_bar_agent = launch_agent.with_name(f"{MENU_BAR_LABEL}.plist")
    with (
        tempfile.TemporaryDirectory(dir=app.parent, prefix=f".{app.name}-") as app_staging,
        tempfile.TemporaryDirectory(
            dir=launch_agent.parent, prefix=f".{launch_agent.name}-"
        ) as agent_staging,
    ):
        candidate_app = Path(app_staging) / app.name
        candidate_agent = Path(agent_staging) / launch_agent.name
        candidate_menu_bar = Path(agent_staging) / menu_bar_agent.name
        render_menu_bar_agent(app=app, output=candidate_menu_bar)
        sys.stdout.write("==> preparing the signed app bundle\n")
        sys.stdout.flush()
        subprocess.run(  # noqa: S603 - fixed executable and argument boundaries
            [uv, "run", "python", "scripts/build_app_bundle.py", "--output", str(candidate_app)],
            cwd=repository,
            check=True,
        )
        tool_bin = subprocess.run(  # noqa: S603 - fixed uv inspection command
            [uv, "tool", "dir", "--bin"], check=True, capture_output=True, text=True
        ).stdout.strip()
        render_launch_agent(
            executable=Path(tool_bin) / "ai-tts", output=candidate_agent, log_path=log_path
        )
        # uv tool install ignores uv.lock; constrain it to the locked graph so
        # a new upstream release cannot send the resolver somewhere untested.
        constraints = Path(agent_staging) / "install-constraints.txt"
        subprocess.run(  # noqa: S603 - fixed exporter writing to owned staging
            [
                uv,
                "export",
                "--frozen",
                "--quiet",
                "--no-dev",
                "--no-hashes",
                "--no-emit-project",
                "--extra",
                "kokoro",
                "--output-file",
                str(constraints),
            ],
            cwd=repository,
            check=True,
        )
        sys.stdout.write("==> installing the ai-tts and ai-tts-mcp executables\n")
        sys.stdout.flush()
        subprocess.run(  # noqa: S603 - fixed installer and explicit package arguments
            [
                uv,
                "tool",
                "install",
                "--force",
                # uv keys its cached build of a local package on metadata, not
                # sources; with the version unchanged it reinstalls stale code.
                "--reinstall-package",
                "ai-tts",
                "--python",
                python_version,
                "--constraints",
                str(constraints),
                "--with",
                "kokoro>=0.9.4",
                "--with",
                SPACY_MODEL,
                "--with",
                "transformers>=4.46,<5",
                str(repository),
            ],
            check=True,
        )
        publish_app_bundle(candidate_app, app, force=True)
        activate_launch_agent(launchctl=launchctl, candidate=candidate_agent, output=launch_agent)
        # Retire a manually launched incumbent so launchd owns the new process.
        _quit_menu_bar(osascript)
        activate_launch_agent(
            launchctl=launchctl,
            candidate=candidate_menu_bar,
            output=menu_bar_agent,
            label=MENU_BAR_LABEL,
        )
    sys.stdout.write(
        "Installed. The daemon is registered with launchd; the menu-bar app is registered too.\n"
        "Both start at login and recover abnormal exits. Normal menu-bar Quit stays closed.\n"
        "Check the daemon: make doctor\n"
        "Wire up your agents: make install-agents\n"
    )


def main(argv: list[str] | None = None) -> int:
    """Install using explicit destinations supplied by the Make entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--launch-agent", type=Path, required=True)
    parser.add_argument("--log-path", type=Path, required=True)
    parser.add_argument("--python-version", default="3.12")
    args = parser.parse_args(argv)
    install_application(
        app=args.app.expanduser().resolve(),
        launch_agent=args.launch_agent.expanduser().resolve(),
        log_path=args.log_path.expanduser().absolute(),
        python_version=args.python_version,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
