# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Release artifacts install and launch without depending on the checkout."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from scripts.build_app_bundle import (
    APP_INTENT_PLAYBACK_RATES,
    assemble_app_bundle,
    validate_app_intents_metadata,
)
from scripts.render_launch_agent import render_launch_agent

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("v0.1.0 checkout-independent distribution contract"),
]

REPOSITORY = Path(__file__).parents[1]
EXPECTED_APP_INTENT_RATES = [
    "0.5\u00d7",
    "0.75\u00d7",
    "1\u00d7",
    "1.5\u00d7",
    "2\u00d7",
    "3\u00d7",
]


def _write_app_intents_metadata(
    root: Path,
    *,
    action_titles: list[str] | None = None,
    shortcut_identifiers: list[str] | None = None,
    playback_rates: list[str] | None = None,
    open_app_when_run: bool = False,
) -> Path:
    metadata = root / "Metadata.appintents"
    metadata.mkdir()
    payload = {
        "actions": [
            {"title": {"key": title}, "openAppWhenRun": open_app_when_run}
            for title in (
                action_titles
                or ["Pause", "Read File", "Read Text", "Resume", "Set Playback Speed", "Skip"]
            )
        ],
        "autoShortcuts": [
            {"actionIdentifier": identifier}
            for identifier in (
                shortcut_identifiers
                or [
                    "PauseSpeechIntent",
                    "ReadFileIntent",
                    "ReadTextIntent",
                    "ResumeSpeechIntent",
                    "SetPlaybackSpeedIntent",
                    "SkipSpeechIntent",
                ]
            )
        ],
        "enums": [
            {
                "cases": [
                    {"displayRepresentation": {"title": {"key": rate}}}
                    for rate in (playback_rates or EXPECTED_APP_INTENT_RATES)
                ]
            }
        ],
    }
    (metadata / "extract.actionsdata").write_text(json.dumps(payload), encoding="utf-8")
    (metadata / "version.json").write_text('{"version": "3.0"}', encoding="utf-8")
    return metadata


def test_app_intents_metadata_validator_accepts_exact_contract(tmp_path: Path) -> None:
    assert APP_INTENT_PLAYBACK_RATES == EXPECTED_APP_INTENT_RATES
    validate_app_intents_metadata(_write_app_intents_metadata(tmp_path))


@pytest.mark.parametrize(
    ("field", "values", "message"),
    [
        ("actions", ["Read Text"], "actions"),
        ("shortcuts", ["ReadTextIntent"], "shortcuts"),
        ("rates", [EXPECTED_APP_INTENT_RATES[2]], "playback rates"),
    ],
)
def test_app_intents_metadata_validator_rejects_incomplete_contract(
    tmp_path: Path, field: str, values: list[str], message: str
) -> None:
    if field == "actions":
        metadata = _write_app_intents_metadata(tmp_path, action_titles=values)
    elif field == "shortcuts":
        metadata = _write_app_intents_metadata(tmp_path, shortcut_identifiers=values)
    else:
        metadata = _write_app_intents_metadata(tmp_path, playback_rates=values)

    with pytest.raises(ValueError, match=message):
        validate_app_intents_metadata(metadata)


def test_app_intents_metadata_validator_rejects_foreground_activation(tmp_path: Path) -> None:
    metadata = _write_app_intents_metadata(tmp_path, open_app_when_run=True)

    with pytest.raises(ValueError, match="background"):
        validate_app_intents_metadata(metadata)


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


def test_app_bundle_advertises_native_text_and_file_services(tmp_path: Path) -> None:
    binary = tmp_path / "AITTSMenuBar"
    binary.write_bytes(b"standalone menu executable")
    binary.chmod(0o755)
    bundle = tmp_path / "AI-TTS.app"

    assemble_app_bundle(binary=binary, output=bundle, version="0.1.0")

    with (bundle / "Contents" / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    assert info.get("NSServices") == [
        {
            "NSMenuItem": {"default": "Read Selection with AI-TTS"},
            "NSMessage": "readSelection",
            "NSPortName": "AI-TTS",
            "NSRequiredContext": {},
            "NSRestricted": False,
            "NSSendTypes": ["public.utf8-plain-text"],
        },
        {
            "NSMenuItem": {"default": "Read File with AI-TTS"},
            "NSMessage": "readFile",
            "NSPortName": "AI-TTS",
            "NSRequiredContext": {},
            "NSRestricted": False,
            "NSSendFileTypes": [
                "public.plain-text",
                "net.daringfireball.markdown",
                "com.adobe.pdf",
            ],
        },
    ]


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
        "arguments": [str(executable), "daemon", "--log-file", str(log_path)],
        "stdout": "/dev/null",
        "stderr": "/dev/null",
        "run_at_load": True,
        "keep_alive": {"SuccessfulExit": False},
        "has_shell": False,
        "has_home_expansion": False,
        "has_checkout": False,
    }
    assert stat.S_IMODE(log_path.parent.stat().st_mode) == 0o700


def test_launch_agent_renderer_runs_as_a_standalone_stdlib_script(tmp_path: Path) -> None:
    script = REPOSITORY / "scripts" / "render_launch_agent.py"
    output = tmp_path / "LaunchAgents" / "com.flyingrobots.ai-tts.plist"
    log_path = tmp_path / "logs" / "daemon.log"
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-I",
            "-S",
            str(script),
            "--executable",
            str(tmp_path / "bin" / "ai-tts"),
            "--output",
            str(output),
            "--log-path",
            str(log_path),
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert (result.returncode, output.exists(), result.stderr) == (0, True, "")


def test_wheel_installs_cli_entry_points_outside_checkout(tmp_path: Path) -> None:
    uv = shutil.which("uv") or "uv"
    wheel_dir = tmp_path / "wheel"
    build = subprocess.run(  # noqa: S603
        [uv, "build", "--offline", "--wheel", "--out-dir", str(wheel_dir)],
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


# -- a toolchain that cannot package App Intents has to say which part ----


def test_app_intents_failure_names_the_toolchain_and_the_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.build_app_bundle import generate_app_intents_metadata  # noqa: PLC0415

    # A toolchain laid out like Xcode's, with the metadata tooling absent —
    # which is what a CI runner on an older default Xcode looks like.
    toolchain = tmp_path / "Xcode_00.0.app/Contents/Developer/Toolchains/X.xctoolchain"
    swiftc = toolchain / "usr" / "bin" / "swiftc"
    swiftc.parent.mkdir(parents=True)
    swiftc.write_text("#!/bin/sh\n")

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")

    def find_swiftc(arguments: list[str]) -> str:
        del arguments
        return str(swiftc)

    monkeypatch.setattr("scripts.build_app_bundle._checked_output", find_swiftc)

    with pytest.raises(RuntimeError) as raised:
        generate_app_intents_metadata(
            repository=tmp_path,
            binary=tmp_path / "bin",
            module_search_path=tmp_path,
            resources=tmp_path / "Resources",
        )

    message = str(raised.value)
    # The original message said only "the active Xcode toolchain cannot
    # extract App Intents metadata", which is true of every cause and points
    # at none of them. On a CI runner that cost an hour to attribute to the
    # default Xcode being older than the one that was developed against.
    assert "appintentsmetadataprocessor" in message
    assert "AppIntents.json" in message
    assert str(toolchain) in message
    assert "xcode-select" in message


def test_app_intents_search_finds_a_relocated_catalog(tmp_path: Path) -> None:
    from scripts.build_app_bundle import find_app_intents_catalog  # noqa: PLC0415

    toolchain = tmp_path / "Toolchains" / "X.xctoolchain"
    moved = toolchain / "usr" / "lib" / "swift" / "SwiftConstantValues" / "AppIntents.json"
    moved.parent.mkdir(parents=True)
    moved.write_text('{"version": 1, "constValueProtocols": ["AppIntent"]}')

    found = find_app_intents_catalog(toolchain)

    # Apple has moved this file between releases. Searching rather than
    # hardcoding one path means a relocation is not indistinguishable from an
    # Xcode that cannot do the job at all.
    assert found == moved


def test_app_intents_search_returns_none_when_no_catalog_exists(tmp_path: Path) -> None:
    from scripts.build_app_bundle import find_app_intents_catalog  # noqa: PLC0415

    (tmp_path / "usr" / "bin").mkdir(parents=True)

    assert find_app_intents_catalog(tmp_path) is None


def test_a_release_bundle_refuses_to_ship_without_app_intents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.build_app_bundle import generate_app_intents_metadata  # noqa: PLC0415

    toolchain = tmp_path / "Xcode.app/Contents/Developer/Toolchains/X.xctoolchain"
    swiftc = toolchain / "usr" / "bin" / "swiftc"
    swiftc.parent.mkdir(parents=True)
    swiftc.write_text("#!/bin/sh\n")
    (toolchain / "usr" / "bin" / "appintentsmetadataprocessor").write_text("#!/bin/sh\n")

    def find_swiftc(arguments: list[str]) -> str:
        del arguments
        return str(swiftc)

    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("scripts.build_app_bundle._checked_output", find_swiftc)

    # Default: refuse. A bundle without this metadata has no Shortcuts
    # integration, and shipping one silently is worse than a failed build.
    with pytest.raises(RuntimeError) as raised:
        generate_app_intents_metadata(
            repository=tmp_path,
            binary=tmp_path / "bin",
            module_search_path=tmp_path,
            resources=tmp_path / "Resources",
        )
    assert "AppIntents.json" in str(raised.value)

    # Opted in explicitly: skip, and return nothing so the caller knows.
    resources = tmp_path / "Resources"
    resources.mkdir()
    assert (
        generate_app_intents_metadata(
            repository=tmp_path,
            binary=tmp_path / "bin",
            module_search_path=tmp_path,
            resources=resources,
            allow_missing_catalog=True,
        )
        is None
    )
