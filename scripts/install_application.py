# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Prepare installation artifacts before replacing the installed application."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.build_app_bundle import publish_app_bundle
from scripts.render_launch_agent import render_launch_agent

SPACY_MODEL = (
    "https://github.com/explosion/spacy-models/releases/download/"
    "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
)


def install_application(
    *, app: Path, launch_agent: Path, log_path: Path, python_version: str
) -> None:
    """Stage the app and plist before asking uv to replace the installed CLI."""
    uv = shutil.which("uv")
    launchctl = shutil.which("launchctl")
    if uv is None or launchctl is None:
        message = "uv and launchctl are required to install AI-TTS"
        raise RuntimeError(message)
    repository = Path(__file__).resolve().parents[1]
    if app.exists() and not app.is_dir():
        message = f"app destination is not a directory: {app}"
        raise NotADirectoryError(message)
    app.parent.mkdir(parents=True, exist_ok=True)
    launch_agent.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(dir=app.parent, prefix=f".{app.name}-") as app_staging,
        tempfile.TemporaryDirectory(
            dir=launch_agent.parent, prefix=f".{launch_agent.name}-"
        ) as agent_staging,
    ):
        candidate_app = Path(app_staging) / app.name
        candidate_agent = Path(agent_staging) / launch_agent.name
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
        sys.stdout.write("==> installing the ai-tts and ai-tts-mcp executables\n")
        sys.stdout.flush()
        subprocess.run(  # noqa: S603 - fixed installer and explicit package arguments
            [
                uv,
                "tool",
                "install",
                "--force",
                "--python",
                python_version,
                "--with",
                "kokoro>=0.9.4",
                "--with",
                SPACY_MODEL,
                str(repository),
            ],
            check=True,
        )
        publish_app_bundle(candidate_app, app, force=True)
        candidate_agent.replace(launch_agent)
        domain = f"gui/{os.getuid()}"
        subprocess.run(  # noqa: S603 - fixed per-user launch-agent label
            [launchctl, "bootout", f"{domain}/com.flyingrobots.ai-tts"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(  # noqa: S603 - explicit installed plist
            [launchctl, "bootstrap", domain, str(launch_agent)], check=True
        )
    sys.stdout.write(
        "Installed. The daemon is running; the menu-bar app is not.\n"
        f"Start the app: open {app}\n"
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
