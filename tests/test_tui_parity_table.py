# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The terminal-dashboard fixtures still describe the Python ``SpeechTUI``.

``tests/fixtures/tui_parity.json`` holds two oracles for the Rust dashboard:

* ``text``: the Python ``literal_text``, ``clock_text`` and ``format_meter``
  results for chosen inputs;
* ``scenarios``: daemon snapshots captured from a Python daemon, the events
  and keys given to a headless ``SpeechTUI`` with a scripted client and a
  frozen clock, and what it then showed (the now-playing details, spoken text,
  progress, both tables' rows and cursors, the focused table, the status
  line) and the daemon requests it sent.

Re-baseline under Python 3.12 (``UV_PYTHON=3.12 uv run --isolated --frozen
--dev python -m tests.test_tui_parity_table``); review the diff.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("the Python SpeechTUI (Textual 8.2.8) and its text helpers"),
    pytest.mark.skipif(
        sys.version_info[:2] != (3, 12),
        reason="fixtures record the Python 3.12 dashboard; run with UV_PYTHON=3.12",
    ),
]

_FIXTURE = Path(__file__).parent / "fixtures" / "tui_parity.json"

TEXT_INPUTS: list[str] = [
    "plain",
    "[red]markup[/red]",
    "bell\x07 escape\x1b[2J",
    "tab\tnew\nline",
    "del\x7f",
    "c1\x85",
    "é ☃ 日本",
]
CLOCK_INPUTS: list[int | None] = [None, -5, 0, 999, 1000, 61_000, 3_599_999, 3_600_000]
METER_INPUTS: list[float | None] = [None, float("nan"), -1.0, 0.0, 0.001, 0.0316, 0.5, 1.0, 2.0]


def text_table() -> dict[str, Any]:
    """The Python text helpers' outputs."""
    from aitts.tui.app import clock_text, literal_text  # noqa: PLC0415 - optional extra
    from aitts.tui.ascii_meter import format_meter  # noqa: PLC0415 - optional extra

    return {
        "literal_text": [[value, literal_text(value)] for value in TEXT_INPUTS],
        "clock_text": [[value, clock_text(value)] for value in CLOCK_INPUTS],
        "format_meter": [
            [None if value is not None and value != value else value, format_meter(value)]  # noqa: PLR0124 - NaN
            for value in METER_INPUTS
            if value is None or value == value  # noqa: PLR0124 - NaN cannot round-trip in JSON
        ],
    }


async def capture_snapshots() -> dict[str, Any]:
    """Daemon snapshots in the states the scenarios render."""
    from aitts.daemon import Daemon  # noqa: PLC0415 - heavy import for regeneration only
    from aitts.engine import FakeEngine  # noqa: PLC0415
    from aitts.model import State  # noqa: PLC0415
    from aitts.playback import FakeSink  # noqa: PLC0415
    from aitts.tui.client import AsyncClient  # noqa: PLC0415
    from tests.support.playback import make_composite_ready  # noqa: PLC0415

    snapshots: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="tui-", dir="/tmp") as folder:
        home = Path(folder) / "home"
        sink = FakeSink()
        daemon = Daemon(
            home=home,
            socket_path=Path(folder) / "s",
            engine=FakeEngine(voices=["v"]),
            sink=sink,
        )
        await daemon.start()
        try:
            client = AsyncClient(daemon.socket_path)

            async def snapshot() -> Any:
                return await client.request({"op": "snapshot", "limit": 50})

            snapshots["empty"] = await snapshot()
            document = make_composite_ready(
                daemon.store, "Complete source", ("First spoken chunk", "Second spoken chunk")
            )
            for _ in range(200):
                if sink.started:
                    break
                await asyncio.sleep(0.01)
            sink.advance_to(61_500)
            snapshots["playing_chunk"] = await snapshot()
            await client.request({"op": "pause"})
            for text in (
                "First queued   text",
                "[red]Literal[/red]\x1b[2J",
                "x" * 300,
                "a\x1cb\u00a0c\x85d\u2003e",
                "\x1b" * 100,
            ):
                await client.request({"op": "submit", "text": text, "priority": "normal"})
            await client.request({"op": "skip"})
            snapshots["held_queue"] = await snapshot()
            assert daemon.store.get(document.id) is not None
            clip = daemon.store.submit("Still generating this clip", voice="v", speed=1.0)
            daemon.store.transition(clip.id, State.SYNTHESIZING)
            snapshots["held_with_synthesizing"] = await snapshot()
        finally:
            await daemon.stop()
    return snapshots


class ScriptedClient:
    """Serves one snapshot per refresh, records commands, and replays events."""

    def __init__(self, snapshots: list[Any], events: list[Any]) -> None:
        self.snapshots = list(snapshots)
        self.events = list(events)
        self.sent: list[Any] = []
        self.last: Any = snapshots[0]

    async def request(self, payload: dict[str, Any]) -> Any:
        if payload.get("op") == "snapshot":
            if self.snapshots:
                self.last = self.snapshots.pop(0)
            # A copy: the dashboard updates its snapshot in place on progress events.
            return json.loads(json.dumps(self.last))
        self.sent.append(payload)
        return {"ok": True}

    @contextlib.asynccontextmanager
    async def events_context(self) -> AsyncIterator[AsyncIterator[Any]]:
        async def stream() -> AsyncIterator[Any]:
            for event in self.events:
                yield event
            await asyncio.Event().wait()

        yield stream()


def _screen(app: Any) -> dict[str, Any]:
    from textual.widgets import DataTable, ProgressBar, Static  # noqa: PLC0415

    def rows(selector: str) -> list[list[str]]:
        table = app.query_one(selector, DataTable)
        return [[str(cell) for cell in table.get_row_at(i)] for i in range(table.row_count)]

    progress = app.query_one("#progress", ProgressBar)
    focused = app.focused.id if app.focused is not None else None
    return {
        "details": str(app.query_one("#now-details", Static).render()),
        "spoken": str(app.query_one("#spoken-text", Static).render()),
        "meter": str(app.query_one("#audio-meter", Static).render()),
        "progress": {"total": progress.total, "progress": progress.progress},
        "queue": rows("#queue"),
        "queue_cursor": app.query_one("#queue", DataTable).cursor_row,
        "history": rows("#history"),
        "history_cursor": app.query_one("#history", DataTable).cursor_row,
        "focused": focused,
        "status": str(app.query_one("#connection", Static).render()),
    }


async def run_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    """Render ``scenario`` in a headless Python dashboard; fill in what it showed and sent."""
    from aitts.tui.app import SpeechTUI  # noqa: PLC0415 - optional extra

    script = ScriptedClient(scenario["snapshots"], scenario["events"])
    times = iter(scenario["clock"])
    app = SpeechTUI(Path("/nonexistent/ai-tts.sock"), clock=lambda: next(times))
    app.client.request = script.request  # type: ignore[method-assign]
    app.client.events = lambda **_: script.events_context()  # type: ignore[method-assign]
    async with app.run_test(size=(100, 35)) as pilot:
        await asyncio.wait_for(app.updated.wait(), 2)
        await pilot.pause()
        for key in scenario["keys"]:
            await pilot.press(key)
            await pilot.pause()
        screen = _screen(app)
    return {**scenario, "screen": screen, "sent": script.sent}


def scenarios(snapshots: dict[str, Any]) -> list[dict[str, Any]]:
    """The recorded scenarios: what is shown, then what each key does."""
    held = snapshots["held_queue"]
    playing = snapshots["playing_chunk"]
    current = playing["status"]["current"] or {}
    progress = {
        "event": "playback_progress",
        "id": current.get("id"),
        "position_ms": 62_000,
        "audio_peak": 0.5,
        "playback_held": playing["status"]["playback_held"],
    }

    def scenario(name: str, shots: list[Any], keys: list[str], **extra: Any) -> dict[str, Any]:
        return {
            "name": name,
            "snapshots": shots,
            "events": extra.get("events", []),
            "keys": keys,
            "clock": extra.get("clock", [0.0] * 20),
        }

    return [
        scenario("empty", [snapshots["empty"]], []),
        scenario("playing chunk", [playing], []),
        scenario("progress event", [playing, playing], [], events=[progress]),
        scenario("held queue", [held], []),
        scenario("synthesizing", [snapshots["held_with_synthesizing"]], []),
        scenario("space resumes a hold", [held, held], ["space"]),
        scenario("space pauses playback", [playing, playing], ["space"]),
        scenario("transport keys", [playing] * 6, ["n", "p", "r", "s"]),
        scenario("j and k select", [held], ["j", "j", "j", "k"]),
        scenario("J moves down", [held, held], ["J"]),
        scenario("K at the top does nothing", [held], ["K"]),
        scenario("dd cancels", [held, held], ["j", "d", "d"]),
        scenario("d then j does not cancel", [held], ["d", "j", "d"]),
        scenario("dd too slow", [held], ["d", "d"], clock=[0.0, 1.0]),
        scenario("tab then enter replays", [held, held], ["tab", "enter"]),
        scenario("enter on the queue does nothing", [held], ["enter"]),
        scenario("tab then dd does nothing", [held], ["tab", "d", "d"]),
    ]


_RECORDED: dict[str, Any] = json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_text_helpers_match() -> None:
    assert text_table() == _RECORDED["text"]


@pytest.mark.parametrize(
    "index", range(len(_RECORDED["scenarios"])), ids=[s["name"] for s in _RECORDED["scenarios"]]
)
async def test_scenario_matches_the_python_dashboard(index: int) -> None:
    recorded = _RECORDED["scenarios"][index]
    keep = ("name", "snapshots", "events", "keys", "clock")
    assert await run_scenario({key: recorded[key] for key in keep}) == recorded


async def _regenerate() -> None:
    snapshots = await capture_snapshots()
    recorded = [await run_scenario(s) for s in scenarios(snapshots)]
    _FIXTURE.write_text(
        json.dumps({"text": text_table(), "scenarios": recorded}, indent=1, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(_regenerate())
