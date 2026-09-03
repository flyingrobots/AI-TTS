# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The CLI: truthful exit codes over a live daemon (features.md §8)."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from aitts.cli import EXIT_DAEMON_ERROR, EXIT_OK, EXIT_UNREACHABLE, main
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink


@pytest.fixture
async def daemon(tmp_path: Path) -> Any:
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-"))
    d = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=["bm_daniel"]),
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
