# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Release artifacts install and launch without depending on the checkout."""

from __future__ import annotations

import os
import plistlib
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from scripts.build_app_bundle import assemble_app_bundle  # type: ignore[import-not-found]
from scripts.render_launch_agent import render_launch_agent  # type: ignore[import-not-found]

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("v0.1.0 checkout-independent distribution contract"),
]

REPOSITORY = Path(__file__).parents[1]


def test_app_bundle_has_release_identity_without_checkout_paths(tmp_path: Path) -> None:
    binary = tmp_path / "AITTSMenuBar"
    binary.write_bytes(b"standalone menu executable")
    binary.chmod(0o755)
    bundle = tmp_path / "AI-TTS.app"

    assemble_app_bundle(binary=binary, output=bundle, version="0.1.0")

    executable = bundle / "Contents" / "MacOS" / "AITTSMenuBar"
    info_path = bundle / "Contents" / "Info.plist"
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    assert {
        "binary": executable.read_bytes(),
        "is_executable": bool(executable.stat().st_mode & stat.S_IXUSR),
        "identifier": info.get("CFBundleIdentifier"),
        "version": info.get("CFBundleShortVersionString"),
        "accessory": info.get("LSUIElement"),
        "single_instance": info.get("LSMultipleInstancesProhibited"),
        "checkout_embedded": str(REPOSITORY).encode() in info_path.read_bytes(),
    } == {
        "binary": b"standalone menu executable",
        "is_executable": True,
        "identifier": "com.flyingrobots.ai-tts.menubar",
        "version": "0.1.0",
        "accessory": True,
        "single_instance": True,
        "checkout_embedded": False,
    }


def test_launch_agent_uses_installed_executable_without_shell_expansion(tmp_path: Path) -> None:
    executable = (tmp_path / "tool-bin" / "ai-tts").resolve()
    log_path = (tmp_path / "logs" / "daemon.log").resolve()
    output = tmp_path / "LaunchAgents" / "com.flyingrobots.ai-tts.plist"

    render_launch_agent(executable=executable, output=output, log_path=log_path)

    with output.open("rb") as stream:
        payload = plistlib.load(stream)
    encoded = output.read_bytes()
    assert {
        "arguments": payload.get("ProgramArguments"),
        "stdout": payload.get("StandardOutPath"),
        "stderr": payload.get("StandardErrorPath"),
        "run_at_load": payload.get("RunAtLoad"),
        "keep_alive": payload.get("KeepAlive"),
        "has_shell": b"/bin/sh" in encoded,
        "has_home_expansion": b"$HOME" in encoded,
        "has_checkout": str(REPOSITORY).encode() in encoded,
    } == {
        "arguments": [str(executable), "daemon"],
        "stdout": str(log_path),
        "stderr": str(log_path),
        "run_at_load": True,
        "keep_alive": {"SuccessfulExit": False},
        "has_shell": False,
        "has_home_expansion": False,
        "has_checkout": False,
    }


def test_wheel_installs_cli_entry_points_outside_checkout(tmp_path: Path) -> None:
    uv = shutil.which("uv") or "uv"
    wheel_dir = tmp_path / "wheel"
    build = subprocess.run(  # noqa: S603
        [uv, "build", "--wheel", "--out-dir", str(wheel_dir)],
        cwd=REPOSITORY,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    wheels = sorted(wheel_dir.glob("*.whl"))
    wheel = wheels[0] if len(wheels) == 1 else None
    names: set[str] = set()
    if wheel is not None:
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())

    environment = tmp_path / "environment"
    install: subprocess.CompletedProcess[str] | None = None
    help_result: subprocess.CompletedProcess[str] | None = None
    if wheel is not None:
        subprocess.run(  # noqa: S603
            [uv, "venv", "--python", sys.executable, str(environment)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        install = subprocess.run(  # noqa: S603
            [
                uv,
                "pip",
                "install",
                "--python",
                str(environment / "bin" / "python"),
                "--no-deps",
                str(wheel),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        clean_env = os.environ.copy()
        clean_env.pop("PYTHONPATH", None)
        help_result = subprocess.run(  # noqa: S603
            [str(environment / "bin" / "ai-tts"), "--help"],
            cwd=tmp_path,
            env=clean_env,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    assert {
        "build": build.returncode,
        "wheel_count": len(wheels),
        "typed_marker": "aitts/py.typed" in names,
        "mcp_adapter": "aitts/adapters/mcp.py" in names,
        "entry_points": any(name.endswith(".dist-info/entry_points.txt") for name in names),
        "install": None if install is None else install.returncode,
        "cli_help": None if help_result is None else help_result.returncode,
        "cli_usage": False if help_result is None else "usage: ai-tts" in help_result.stdout,
    } == {
        "build": 0,
        "wheel_count": 1,
        "typed_marker": True,
        "mcp_adapter": True,
        "entry_points": True,
        "install": 0,
        "cli_help": 0,
        "cli_usage": True,
    }, f"wheel build stderr:\n{build.stderr}"
