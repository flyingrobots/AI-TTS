# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Render a launch-agent plist around an installed AI-TTS executable."""

from __future__ import annotations

import argparse
import os
import plistlib
import sys
from pathlib import Path
from typing import Any

LABEL = "com.flyingrobots.ai-tts"


def _ensure_private_log_directory(path: Path) -> None:
    """Secure the log directory without importing the separately installed package."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        os.fchmod(descriptor, 0o700)
    finally:
        os.close(descriptor)


def render_launch_agent(*, executable: Path, output: Path, log_path: Path) -> Path:
    """Write a shell-free launch-agent plist using absolute installed paths."""
    for name, path in (("executable", executable), ("output", output), ("log_path", log_path)):
        if not path.is_absolute():
            msg = f"{name} must be an absolute path: {path}"
            raise ValueError(msg)
    if output.exists():
        msg = f"refusing to replace existing launch agent: {output}"
        raise FileExistsError(msg)

    payload: dict[str, Any] = {
        "KeepAlive": {"SuccessfulExit": False},
        "Label": LABEL,
        "ProcessType": "Interactive",
        "ProgramArguments": [str(executable), "daemon", "--log-file", str(log_path)],
        "RunAtLoad": True,
        "StandardErrorPath": "/dev/null",
        "StandardOutPath": "/dev/null",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    _ensure_private_log_directory(log_path.parent)
    with output.open("wb") as stream:
        plistlib.dump(payload, stream, sort_keys=True)
    output.chmod(0o644)
    return output


def main(argv: list[str] | None = None) -> int:
    """Render a launch agent from explicit absolute installation paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist",
    )
    parser.add_argument(
        "--log-path",
        type=Path,
        default=Path.home() / "Library" / "Logs" / "AI-TTS" / "daemon.log",
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    executable = args.executable.expanduser().resolve()
    output = args.output.expanduser().resolve()
    log_path = args.log_path.expanduser().absolute()
    if output.exists():
        if not args.force:
            parser.error(f"output already exists: {output}; pass --force to replace it")
        output.unlink()
    render_launch_agent(executable=executable, output=output, log_path=log_path)
    sys.stdout.write(f"{output}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - executable wrapper
    raise SystemExit(main())
