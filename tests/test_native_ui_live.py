# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Opt-in signed-app acceptance; never substitute this for human VoiceOver checks."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

import pytest

from aitts.application.input_activity import FakeInputActivity
from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.playback import FakeSink

pytestmark = [
    pytest.mark.large,
    pytest.mark.oracle(
        "the signed app exposes action labels as primary accessibility descriptions"
    ),
    pytest.mark.skipif(
        not os.environ.get("AI_TTS_UI_CANDIDATE"),
        reason="opt-in: requires signed candidate, unlocked desktop, and Accessibility access",
    ),
]


async def command(*arguments: str) -> str:
    process = await asyncio.create_subprocess_exec(
        *arguments, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        output, errors = await asyncio.wait_for(process.communicate(), 8)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(errors.decode() or f"Command failed: {arguments[0]}")
    return output.decode().strip()


async def incumbent_app(probe: Path) -> tuple[int, Path] | None:
    processes = await command("/bin/ps", "-axo", "pid=,command=")
    found = []
    for line in processes.splitlines():
        pid, _, path = line.strip().partition(" ")
        if path.endswith("/Contents/MacOS/AITTSMenuBar"):
            found.append((int(pid), Path(path).parents[2]))
    if len(found) > 1:
        pytest.fail("Multiple menu apps are running; cannot safely restore the session")
    if not found:
        return None
    incumbent = found[0]
    if await command(str(probe), str(incumbent[0]), "windows") != "0":
        pytest.skip("Incumbent app has open windows; close them before live acceptance")
    return incumbent


async def stop_incumbent(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        await asyncio.sleep(0.05)
    pytest.fail("Incumbent app did not exit")


@asynccontextmanager
async def candidate_session(candidate: Path, probe: Path, socket: Path) -> AsyncIterator[int]:
    incumbent = await incumbent_app(probe)
    awake = await asyncio.create_subprocess_exec("/usr/bin/caffeinate", "-d", "-u", "-t", "30")
    app: asyncio.subprocess.Process | None = None
    try:
        if incumbent:
            await stop_incumbent(incumbent[0])
        app = await asyncio.create_subprocess_exec(
            str(candidate / "Contents/MacOS/AITTSMenuBar"),
            env={**os.environ, "AI_TTS_SOCKET": str(socket)},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        yield app.pid
    finally:
        try:
            if app is not None and app.returncode is None:
                app.terminate()
                try:
                    await asyncio.wait_for(app.wait(), 3)
                except TimeoutError:
                    app.kill()
                    await app.wait()
        finally:
            if incumbent:
                await command("/usr/bin/open", str(incumbent[1]))
            if awake.returncode is None:
                awake.terminate()
                await awake.wait()


async def wait_for_control(
    probe: Path, pid: int, label: str, *, attribute: str = "AXDescription", count: int = 1
) -> list[dict[str, str]]:
    for _ in range(40):
        rows = cast("list[dict[str, str]]", json.loads(await command(str(probe), str(pid), "dump")))
        if sum(row.get(attribute) == label for row in rows) >= count:
            return rows
        await asyncio.sleep(0.05)
    pytest.fail(f"Control {label!r} not available; confirm the desktop is unlocked")


@pytest.fixture
async def native_app(tmp_path: Path) -> AsyncIterator[tuple[Path, int, Daemon]]:
    # Retire only with an equivalent calibrated, cross-process native control check.
    # This temporarily restarts an idle menu app, never the installed daemon.
    candidate = Path(os.environ["AI_TTS_UI_CANDIDATE"]).resolve()
    if not (candidate / "Contents/MacOS/AITTSMenuBar").is_file():
        pytest.fail("AI_TTS_UI_CANDIDATE must identify a built app bundle")
    probe = tmp_path / "accessibility-probe"
    await command(
        "/usr/bin/swiftc",
        str(Path(__file__).parent / "native/accessibility_probe.swift"),
        "-o",
        str(probe),
    )
    with tempfile.TemporaryDirectory(prefix="aitts-ui-") as directory:
        daemon = Daemon(
            home=Path(directory),
            engine=FakeEngine(["bm_daniel", "af_bella"], fail_texts={"Owned failing text."}),
            sink=FakeSink(),
            input_activity=FakeInputActivity(),
        )
        await daemon.start()
        try:
            async with candidate_session(candidate, probe, daemon.socket_path) as pid:
                await wait_for_control(probe, pid, "AI-TTS: Ready")
                await command(str(probe), str(pid), "press", "AI-TTS: Ready")
                await wait_for_control(probe, pid, "Speak…")
                yield probe, pid, daemon
        finally:
            await daemon.stop()


async def test_signed_app_settings_control_names_its_action(
    native_app: tuple[Path, int, Daemon],
) -> None:
    probe, pid, _ = native_app
    rows = await wait_for_control(probe, pid, "Speak…")
    settings = [row for row in rows if row.get("AXHelp") == "Settings"]
    assert len(settings) == 1, "The production popover must expose one Settings control"
    assert settings[0].get("AXDescription") == "Settings"


def action_names(rows: list[dict[str, str]]) -> set[str]:
    return {
        row.get("AXTitle") or row.get("AXDescription", "")
        for row in rows
        if row.get("AXRole") in {"AXButton", "AXMenuButton"}
    }


async def test_signed_app_icon_actions_remain_named_after_updates(
    native_app: tuple[Path, int, Daemon],
) -> None:
    # Names are the public action contract, including after unrelated UI redraws.
    probe, pid, daemon = native_app
    await daemon.dispatch({"op": "pause"})
    await daemon.dispatch({"op": "submit", "text": "Owned queue item."})
    item = await daemon.dispatch({"op": "submit", "text": "Owned history item."})
    await daemon.dispatch({"op": "cancel", "id": item["id"]})
    rows = await wait_for_control(probe, pid, "Remove from queue", attribute="AXHelp")
    observed = action_names(rows)
    await command(str(probe), str(pid), "press", "History")
    rows = await wait_for_control(probe, pid, "Re-queue")
    observed |= action_names(rows)
    await daemon.dispatch({"op": "assign_voice", "source": "owned-client", "voice": "af_bella"})
    await command(str(probe), str(pid), "press", "Settings")
    rows = await wait_for_control(probe, pid, "Preview this voice", attribute="AXHelp", count=2)
    observed |= action_names(rows)
    await command(str(probe), str(pid), "press", "Done")
    await command(str(probe), str(pid), "press", "Default voice")
    await command(str(probe), str(pid), "press", "af_bella")
    rows = await wait_for_control(probe, pid, "Dismiss voice confirmation", attribute="AXHelp")
    observed |= action_names(rows)
    await daemon.dispatch({"op": "submit", "text": "Owned failing text."})
    rows = await wait_for_control(probe, pid, "Dismiss error", attribute="AXHelp", count=2)
    observed |= action_names(rows)
    expected = {
        "Settings",
        "Remove from queue",
        "Read full text",
        "Remove from history",
        "Choose re-queue urgency",
        "Release voice assignment",
        "Preview voice bm_daniel",
        "Dismiss voice confirmation",
        "Dismiss error",
    }
    dismissals = [row.get("AXDescription") for row in rows if row.get("AXHelp") == "Dismiss error"]
    result = {
        "missing_actions": sorted(expected - observed),
        "menu_after_redraw": "Choose re-queue urgency" in action_names(rows),
        "toast_and_footer": dismissals,
    }
    assert result == {
        "missing_actions": [],
        "menu_after_redraw": True,
        "toast_and_footer": ["Dismiss error", "Dismiss error"],
    }
