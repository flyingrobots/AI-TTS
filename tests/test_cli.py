# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The CLI: truthful exit codes over a live daemon (features.md §8)."""

from __future__ import annotations

import asyncio
import builtins
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path
from typing import Any

import pytest

from aitts.cli import EXIT_DAEMON_ERROR, EXIT_OK, EXIT_UNREACHABLE, main
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("CLI behavior in docs/design/features.md section 8"),
]


@pytest.fixture
async def daemon(tmp_path: Path) -> Any:
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-"))
    alternate = FakeEngine(voices=["af_bella"])
    alternate.name = "alternate"
    d = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel"]),
        engines={"alternate": alternate},
        sink=FakeSink(auto_finish_ms=5),
        socket_path=sock_dir / "d.sock",
    )
    await d.start()
    yield d
    await d.stop()
    shutil.rmtree(sock_dir, ignore_errors=True)


async def run_cli(daemon: Daemon, *argv: str) -> int:
    return await asyncio.to_thread(main, ["--socket", str(daemon.socket_path), *argv])


async def test_say_exits_zero_when_accepted(
    daemon: Daemon, capsys: pytest.CaptureFixture[str]
) -> None:
    code = await run_cli(daemon, "say", "hello there")
    assert code == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["sensitivity"] == "confidential"  # fail closed by default


async def test_say_defaults_to_literal_plain_text(
    daemon: Daemon, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run_cli(daemon, "pause") == EXIT_OK
    capsys.readouterr()
    text = "# Not a heading\n\nSay **stars** literally."

    assert await run_cli(daemon, "say", text) == EXIT_OK
    response = json.loads(capsys.readouterr().out)
    utterance = daemon.store.get(response["id"])

    assert utterance is not None
    assert utterance.text == text
    assert daemon.store.segments(response["id"]) == []


async def test_say_can_explicitly_project_markdown(
    daemon: Daemon, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run_cli(daemon, "pause") == EXIT_OK
    capsys.readouterr()

    assert (
        await run_cli(
            daemon,
            "say",
            "# Actual **heading**\n\nRead `this`.",
            "--format",
            "markdown",
        )
        == EXIT_OK
    )
    response = json.loads(capsys.readouterr().out)

    assert [segment.text for segment in daemon.store.segments(response["id"])] == [
        "Actual heading.\n\nRead this."
    ]


async def test_say_wait_exits_zero_only_for_played(
    daemon: Daemon, capsys: pytest.CaptureFixture[str]
) -> None:
    code = await run_cli(daemon, "say", "hello", "--wait", "--timeout", "10")
    assert code == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["final_state"] == "Played"


async def test_daemon_error_exits_one(daemon: Daemon, capsys: pytest.CaptureFixture[str]) -> None:
    code = await run_cli(daemon, "say", "hello", "--voice", "not_a_voice")
    assert code == EXIT_DAEMON_ERROR
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["type"] == "bad_request"


async def test_unreachable_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = await asyncio.to_thread(main, ["--socket", str(tmp_path / "nowhere.sock"), "status"])
    assert code == EXIT_UNREACHABLE
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["type"] == "unreachable"


async def test_status_and_transport_roundtrip(
    daemon: Daemon, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run_cli(daemon, "pause") == EXIT_OK
    capsys.readouterr()
    assert await run_cli(daemon, "status") == EXIT_OK
    status = json.loads(capsys.readouterr().out)
    assert status["state"] == "accepting"
    assert status["playback_state"] == "paused"
    assert status["accepting_speech"] is True
    assert status["submission_disposition"] == "spooled_until_resume"
    assert await run_cli(daemon, "resume") == EXIT_OK


async def test_settings_set_roundtrip(daemon: Daemon, capsys: pytest.CaptureFixture[str]) -> None:
    code = await run_cli(daemon, "settings", "--set", "speed=1.25")
    assert code == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["settings"]["speed"] == 1.25


async def test_caption_setting_is_boolean_end_to_end(
    daemon: Daemon,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = await run_cli(daemon, "settings", "--set", "captions_enabled=true")
    out = json.loads(capsys.readouterr().out)

    assert code == EXIT_OK
    assert out["settings"]["captions_enabled"] is True


async def test_playback_rate_setting_is_numeric_end_to_end(
    daemon: Daemon,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = await run_cli(daemon, "settings", "--set", "playback_rate=1.5")
    out = json.loads(capsys.readouterr().out)

    assert {
        "exit_code": code,
        "playback_rate": out.get("settings", {}).get("playback_rate"),
    } == {
        "exit_code": EXIT_OK,
        "playback_rate": 1.5,
    }


async def test_purge_cache_reports_and_removes_orphaned_audio(
    daemon: Daemon,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact = tmp_path / "cache" / "orphan.wav"
    artifact.write_bytes(b"private audio")

    code = await run_cli(daemon, "purge-cache")
    response = json.loads(capsys.readouterr().out)

    assert code == EXIT_OK
    assert response == {
        "ok": True,
        "removed_files": 1,
        "removed_bytes": 13,
        "protected_files": 0,
        "protected_bytes": 0,
        "failed_files": 0,
        "failed_bytes": 0,
    }
    assert artifact.exists() is False


# The tray app and the CLI have the same rights (architecture §4): every op the
# menu bar can send must be reachable from a terminal too.


async def test_chunk_stepping_is_reachable_from_the_cli(
    daemon: Daemon, capsys: pytest.CaptureFixture[str]
) -> None:
    # Nothing chunked is playing, so both refuse — but they refuse as the
    # daemon, which proves the command reached it.
    assert await run_cli(daemon, "next-chunk") == EXIT_DAEMON_ERROR
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "illegal_state"
    assert await run_cli(daemon, "prev-chunk") == EXIT_DAEMON_ERROR
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "illegal_state"


async def test_resume_when_idle_is_reachable_from_the_cli(
    daemon: Daemon, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run_cli(daemon, "pause") == EXIT_OK
    capsys.readouterr()

    assert await run_cli(daemon, "resume-when-idle") == EXIT_OK
    assert json.loads(capsys.readouterr().out)["ok"] is True


async def test_the_voice_register_is_readable_and_writable_from_the_cli(
    daemon: Daemon, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run_cli(daemon, "assign-voice", "an-agent", "bm_daniel") == EXIT_OK
    assigned = json.loads(capsys.readouterr().out)
    assert assigned["assignment"]["voice"] == "bm_daniel"
    assert assigned["assignment"]["pinned"] is True

    assert await run_cli(daemon, "voice-map") == EXIT_OK
    listed = json.loads(capsys.readouterr().out)
    # Established agents are seeded, so assert on the one this test made.
    held = {item["source"]: item["voice"] for item in listed["assignments"]}
    assert held["an-agent"] == "bm_daniel"

    assert await run_cli(daemon, "assign-voice", "an-agent", "--release") == EXIT_OK
    assert json.loads(capsys.readouterr().out)["assignment"] is None


async def test_releasing_an_unassigned_source_is_reported(
    daemon: Daemon, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run_cli(daemon, "assign-voice", "nobody", "--release") == EXIT_DAEMON_ERROR
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "not_found"


async def test_interrupt_settings_are_settable_from_the_cli(
    daemon: Daemon, capsys: pytest.CaptureFixture[str]
) -> None:
    code = await run_cli(
        daemon,
        "settings",
        "--set",
        "input_interrupt_enabled=false",
        "--set",
        "input_interrupt_resume=when_idle",
    )
    assert code == EXIT_OK
    settings = json.loads(capsys.readouterr().out)["settings"]
    assert settings["input_interrupt_enabled"] is False
    assert settings["input_interrupt_resume"] == "when_idle"


async def test_version_reports_the_installed_distribution(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from aitts import __version__  # noqa: PLC0415

    # argparse's version action exits rather than returning, which is why an
    # earlier reading of this flag concluded it was missing.
    with pytest.raises(SystemExit) as raised:
        main(["--version"])

    assert raised.value.code == 0
    printed = capsys.readouterr().out
    assert __version__ in printed
    assert "ai-tts" in printed


async def test_metrics_are_reachable_from_the_cli(
    daemon: Daemon, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run_cli(daemon, "metrics") == EXIT_OK

    reported = json.loads(capsys.readouterr().out)
    assert reported["ok"] is True
    assert "synthesis_wait_ms" in reported
    assert "playback_wait_ms" in reported
    assert reported["queue_depth"] == {"input": 0, "playback": 0}


async def test_say_preempt_is_persisted_while_playback_held(
    daemon: Daemon,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await run_cli(daemon, "pause") == EXIT_OK
    capsys.readouterr()
    assert await run_cli(daemon, "say", "alert", "--preempt") == EXIT_OK
    response = json.loads(capsys.readouterr().out)
    clip = daemon.store.get(response["id"])
    assert clip is not None
    assert clip.priority.value == "preempt"
    assert response["playback_held"] is True


@pytest.mark.parametrize(
    "arguments",
    [
        ("settings", "set", "engine", "alternate"),
        ("settings", "--engine", "alternate"),
        ("settings", "--set", "engine=alternate"),
    ],
)
async def test_engine_selection_forms_report_the_selected_backend(
    daemon: Daemon, capsys: pytest.CaptureFixture[str], arguments: tuple[str, ...]
) -> None:
    assert await run_cli(daemon, *arguments) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["settings"]["engine"] == "alternate"


async def test_engine_catalog_and_per_clip_override_reach_daemon(
    daemon: Daemon, capsys: pytest.CaptureFixture[str]
) -> None:
    assert await run_cli(daemon, "engines") == EXIT_OK
    catalog = json.loads(capsys.readouterr().out)["engines"]
    assert [(item["name"], item["is_local"], item["voices"]) for item in catalog] == [
        ("alternate", True, ["af_bella"]),
        ("fake", True, ["bm_daniel"]),
    ]
    assert await run_cli(daemon, "say", "owned source", "--engine", "missing") == EXIT_DAEMON_ERROR
    assert "selected model is not available" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("arguments", "key", "expected"),
    [
        (("settings", "set", "earcon", "on"), "earcon_enabled", True),
        (("settings", "--ducking", "off"), "ducking_enabled", False),
    ],
)
async def test_audio_effect_setting_aliases(
    daemon: Daemon,
    capsys: pytest.CaptureFixture[str],
    arguments: tuple[str, ...],
    key: str,
    *,
    expected: bool,
) -> None:
    assert await run_cli(daemon, *arguments) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["settings"][key] is expected
    assert await run_cli(daemon, "settings") == EXIT_OK
    assert json.loads(capsys.readouterr().out)["settings"][key] is expected


def test_tui_cli_uses_selected_socket_without_starting_daemon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launched: list[Path] = []

    class Terminal:
        return_code = 0  # Textual's value after a clean exit

        def __init__(self, socket_path: Path) -> None:
            self.path = socket_path

        def run(self) -> None:
            launched.append(self.path)

    module = types.ModuleType("aitts.tui.app")
    module.SpeechTUI = Terminal  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aitts.tui.app", module)
    assert main(["--socket", "/owned/terminal.sock", "tui"]) == EXIT_OK
    assert launched == [Path("/owned/terminal.sock")]


@pytest.mark.oracle("Textual App.return_code is 1 after an unhandled exception; 0 means success")
def test_tui_crash_is_a_failing_exit_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from textual.app import App, ComposeResult  # noqa: PLC0415 - optional terminal dependency

    class Crashing(App[None]):
        def __init__(self, socket_path: Path) -> None:
            super().__init__()
            del socket_path

        def compose(self) -> ComposeResult:
            message = "owned dashboard crash"
            raise RuntimeError(message)

        def run(self) -> None:  # type: ignore[override]
            # Headless keeps the test away from the real terminal.
            super().run(headless=True)

    module = types.ModuleType("aitts.tui.app")
    module.SpeechTUI = Crashing  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aitts.tui.app", module)
    assert main(["--socket", "/owned/terminal.sock", "tui"]) == EXIT_DAEMON_ERROR
    assert "owned dashboard crash" in capsys.readouterr().err


def test_tui_missing_extra_explains_installation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    original_import = builtins.__import__

    def without_textual(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "aitts.tui.app":
            message = "No module named textual"
            raise ModuleNotFoundError(message, name="textual")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_textual)
    assert main(["tui"]) == EXIT_DAEMON_ERROR
    assert "ai-tts[tui]" in capsys.readouterr().err
