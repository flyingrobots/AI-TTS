# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Zed admission contracts through an owned daemon, without producing audio."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pytest

from aitts.client import Client
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink
from aitts.zed import main

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("clients/zed/README.md: admission and failure contracts"),
]


@pytest.fixture
async def daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    socket_dir = Path(tempfile.mkdtemp(prefix="zed-"))
    instance = Daemon(
        home=tmp_path / "home",
        engine=FakeEngine(voices=["bm_daniel"]),
        sink=FakeSink(auto_finish_ms=5),
        socket_path=socket_dir / "d.sock",
    )
    monkeypatch.setenv("AI_TTS_SOCKET", str(instance.socket_path))
    monkeypatch.delenv("ZED_FILE", raising=False)
    monkeypatch.delenv("ZED_SELECTED_TEXT", raising=False)
    await instance.start()
    await asyncio.to_thread(Client(instance.socket_path).request, {"op": "pause"})
    yield instance
    await instance.stop()
    shutil.rmtree(socket_dir)


async def test_selection_is_admitted_literally_without_shell_effects(
    daemon: Daemon,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = "# **Literal**\n'quotes' `commands` $(touch forbidden)\n café 🦊\n"
    monkeypatch.setenv("ZED_SELECTED_TEXT", text)
    assert await asyncio.to_thread(main, ["selection"]) == 0
    output = capsys.readouterr().out
    response = json.loads(output)
    utterance = daemon.store.get(response["id"])
    assert utterance is not None
    assert utterance.text == text
    assert utterance.source == "zed:selection"
    assert utterance.sensitivity.value == "confidential"
    assert utterance.priority.value == "normal"
    assert daemon.store.segments(utterance.id) == []
    assert text not in output
    status = await asyncio.to_thread(Client(daemon.socket_path).request, {"op": "status"})
    assert status["playback_state"] == "paused"


@pytest.mark.parametrize("case", [(".md", "Heading.\n\nBody."), (".txt", "# Heading\n\nBody.")])
async def test_file_format_follows_extension(
    daemon: Daemon,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: tuple[str, str],
) -> None:
    suffix, spoken = case
    path = tmp_path / f"document with 'quotes' and $dollars{suffix}"
    path.write_text("# Heading\n\nBody.", encoding="utf-8")
    monkeypatch.setenv("ZED_FILE", str(path))
    assert await asyncio.to_thread(main, ["file"]) == 0
    response = json.loads(capsys.readouterr().out)
    utterance = daemon.store.get(response["id"])
    assert utterance is not None
    parts = daemon.store.segments(utterance.id)
    actual = "".join(part.text for part in parts) if parts else utterance.text
    assert actual == spoken
    assert utterance.source == "zed:file"
    assert utterance.priority.value == "normal"
    provenance = await asyncio.to_thread(
        Client(daemon.socket_path).request, {"op": "provenance", "id": utterance.id}
    )
    assert provenance["provenance"]["origin"] == "Zed"


@pytest.mark.parametrize(
    "kind",
    [
        "missing-file",
        "invalid-utf8",
        "binary",
        "empty",
        "too-large",
        "missing-selection",
        "blank-selection",
        "large-selection",
        "encoded-selection",
    ],
)
async def test_invalid_input_is_refused_without_admission(
    daemon: Daemon,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    kind: str,
) -> None:
    path = tmp_path / "input.txt"
    content = {
        "invalid-utf8": b"\xff",
        "binary": b"a\x00b",
        "empty": b" \n",
        "too-large": b"a" * (512 * 1024 + 1),
    }
    if kind in content:
        path.write_bytes(content[kind])
    monkeypatch.setenv("ZED_FILE", str(path))
    if kind == "blank-selection":
        monkeypatch.setenv("ZED_SELECTED_TEXT", " \n")
    if kind == "large-selection":
        monkeypatch.setenv("ZED_SELECTED_TEXT", "é" * (256 * 1024 + 1))
    if kind == "encoded-selection":
        monkeypatch.setenv("ZED_SELECTED_TEXT", "é" * (256 * 1024))
    mode = "selection" if "selection" in kind else "file"
    assert await asyncio.to_thread(main, [mode]) == 1
    output = capsys.readouterr()
    assert output.err
    if kind == "encoded-selection":
        assert "encoded" in output.err
    assert not output.out
    snapshot = await asyncio.to_thread(Client(daemon.socket_path).request, {"op": "snapshot"})
    assert snapshot["plan"] == []
    assert snapshot["history"] == []


async def test_file_at_byte_limit_is_admitted(
    daemon: Daemon,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "boundary.txt"
    text = "word " * 104857 + "end"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("ZED_FILE", str(path))
    assert await asyncio.to_thread(main, ["file"]) == 0
    response = json.loads(capsys.readouterr().out)
    utterance = daemon.store.get(response["id"])
    assert utterance is not None
    assert utterance.text == text


async def test_file_at_byte_limit_after_bom_is_admitted(
    daemon: Daemon,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "bom.txt"
    text = "a" * (512 * 1024)
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    monkeypatch.setenv("ZED_FILE", str(path))
    assert await asyncio.to_thread(main, ["file"]) == 0
    response = json.loads(capsys.readouterr().out)
    utterance = daemon.store.get(response["id"])
    assert utterance is not None
    assert utterance.text == text


def test_send_failure_is_reported_as_daemon_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken_request(_self: Client, _payload: dict[str, Any]) -> dict[str, Any]:
        raise BrokenPipeError(32, "Broken pipe")

    monkeypatch.setenv("AI_TTS_SOCKET", str(tmp_path / "d.sock"))
    monkeypatch.setenv("ZED_SELECTED_TEXT", "hello")
    monkeypatch.setattr(Client, "request", broken_request)
    assert main(["selection"]) == 2
    output = capsys.readouterr()
    assert "daemon is unavailable" in output.err
    assert "Cannot read document" not in output.err
    assert not output.out


def test_unreachable_daemon_has_actionable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("AI_TTS_SOCKET", str(tmp_path / "absent.sock"))
    monkeypatch.setenv("ZED_SELECTED_TEXT", "hello")
    assert main(["selection"]) == 2
    output = capsys.readouterr()
    assert "daemon" in output.err.lower()
    assert not output.out
