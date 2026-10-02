# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""A terminal view of daemon-owned playback, queue and history."""

from __future__ import annotations

import asyncio
import time
import unicodedata
from typing import TYPE_CHECKING, Any, ClassVar

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, ProgressBar, Static

from aitts.client import DaemonError, DaemonUnreachableError
from aitts.tui.ascii_meter import format_meter
from aitts.tui.client import AsyncClient

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from textual import events
    from textual.binding import BindingType

# The two presses of dd must land this close together on the same clip.
_DELETE_WINDOW_SECONDS = 1.0


def literal_text(value: str) -> str:
    """Keep source control bytes visible instead of emitting terminal instructions."""
    return "".join(
        f"\\x{ord(character):02x}"
        if character not in "\n\t" and unicodedata.category(character) == "Cc"
        else character
        for character in value
    )


def clock_text(milliseconds: int | None) -> str:
    """Render an unknown or elapsed duration without inventing a total."""
    if milliseconds is None:
        return "--:--"
    minutes, seconds = divmod(max(0, milliseconds) // 1000, 60)
    return f"{minutes}:{seconds:02d}"


class NowPlayingCard(Vertical):
    """Current source text, transport metadata and progress."""

    def compose(self) -> ComposeResult:
        """Keep text literal, including source that resembles Rich markup."""
        yield Static("Idle", id="now-details", markup=False)
        yield ProgressBar(total=100, show_eta=False, id="progress")
        yield Static("", id="spoken-text", markup=False)
        yield Static("Audio level unavailable", id="audio-meter", markup=False)


class SpeechTUI(App[None]):
    """Control the existing daemon without owning its process or audio device."""

    TITLE = "AI-TTS"
    CSS = """
    NowPlayingCard { height: auto; max-height: 12; padding: 1; border: round $primary; }
    #spoken-text { max-height: 5; overflow-y: auto; }
    #queue, #history { height: 1fr; min-height: 3; }
    .section-title { height: 1; text-style: bold; }
    #connection { height: auto; max-height: 3; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("space", "toggle_playback", "Pause/resume", priority=True),
        Binding("j", "navigate(1)", "Down", show=False),
        Binding("k", "navigate(-1)", "Up", show=False),
        Binding("d", "delete", "dd Cancel", show=False),
        Binding("J", "move(-1)", "Move up", show=False),
        Binding("K", "move(1)", "Move down", show=False),
        Binding("n", "transport('next_segment')", "Next chunk"),
        Binding("p", "transport('previous_segment')", "Previous chunk"),
        Binding("r", "transport('rewind')", "Restart"),
        Binding("s", "transport('skip')", "Skip"),
        Binding("enter", "requeue", "Replay history", priority=True),
        Binding("q", "quit", "Quit", priority=True),
    ]

    def __init__(self, socket_path: Path, *, clock: Callable[[], float] = time.monotonic) -> None:
        """Connect through the public asynchronous socket adapter."""
        super().__init__()
        self._clock = clock
        self.client = AsyncClient(socket_path)
        self.snapshot: dict[str, Any] = {}
        self.connected = False
        self.updated = asyncio.Event()
        self._refresh_lock = asyncio.Lock()
        self._delete_candidate: tuple[str, float] | None = None

    def compose(self) -> ComposeResult:
        """Lay out current speech and independently navigable tables."""
        yield Header()
        yield NowPlayingCard()
        yield Static("Queue · j/k select · dd cancel · J/K move", classes="section-title")
        yield DataTable(id="queue", cursor_type="row")
        yield Static("History · Tab switches tables · Enter replays", classes="section-title")
        yield DataTable(id="history", cursor_type="row")
        yield Static("Connecting…", id="connection", markup=False)
        yield Footer()

    def on_mount(self) -> None:
        """Start subscription before the initial snapshot to avoid missing changes."""
        self.query_one("#queue", DataTable).add_columns("Priority", "Voice", "State", "Text")
        self.query_one("#history", DataTable).add_columns("Voice", "Result", "Text")
        self.query_one("#queue", DataTable).focus()
        self.run_worker(self._listen(), name="daemon subscription", exclusive=True)

    async def _listen(self) -> None:
        while self.is_running:
            try:
                async with self.client.events(playback_progress=True) as events:
                    await self.refresh_snapshot()
                    self.connected = True
                    self._message("Connected · q closes this view; speech keeps running")
                    async for event in events:
                        if event.get("event") == "playback_progress":
                            if event.get("playback_held") != self.snapshot.get("status", {}).get(
                                "playback_held"
                            ):
                                await self.refresh_snapshot()
                            self._render_progress(event)
                        else:
                            await self.refresh_snapshot()
            except (DaemonError, DaemonUnreachableError) as exc:
                self.connected = False
                self._message(f"Disconnected: {exc} · retrying…")
                await asyncio.sleep(1)

    def _message(self, message: str) -> None:
        if not self.is_running:
            return
        self.query_one("#connection", Static).update(literal_text(message))

    async def refresh_snapshot(self) -> None:
        """Refresh daemon state serially and preserve table selection by identity."""
        async with self._refresh_lock:
            self.snapshot = await self.client.request({"op": "snapshot", "limit": 50})
            # Textual may remove widgets while the socket request is in flight.
            if not self.is_running:
                return
            self._render_snapshot()
            self.updated.set()

    @staticmethod
    def _selected(table: DataTable[Text]) -> str | None:
        if not table.row_count:
            return None
        return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)

    def _fill_table(
        self, selector: str, items: list[dict[str, Any]], fields: tuple[str, ...]
    ) -> None:
        table = self.query_one(selector, DataTable)
        selected = self._selected(table)
        previous_row = table.cursor_row
        table.clear()
        for item in items:
            cells = [
                Text(literal_text(" ".join(str(item.get(field, "")).split()))[:160])
                for field in fields
            ]
            table.add_row(*cells, key=item["id"])
        identities = [item["id"] for item in items]
        row = identities.index(selected) if selected in identities else previous_row
        if items:
            table.move_cursor(row=min(row, len(items) - 1))

    def _render_now(self) -> None:
        status = self.snapshot.get("status", {})
        current = status.get("current") or {}
        segment = current.get("active_segment") or {}
        position = current.get("position_ms") or 0
        duration = current.get("duration_ms")
        voice = current.get("voice", status.get("voice", ""))
        speed = current.get("speed", 1)
        rate = self.snapshot.get("settings", {}).get("playback_rate", 1)
        details = (
            f"{status.get('playback_state', 'idle').title()} · {voice} · "
            f"voice speed {speed}x · playback {rate}x · "
            f"{clock_text(position)} / {clock_text(duration)}"
        )
        if segment:
            details += f" · Chunk {segment['number']}/{segment['count']}"
        self.query_one("#now-details", Static).update(literal_text(details))
        self.query_one("#spoken-text", Static).update(
            literal_text(segment.get("text", current.get("text", "")))
        )
        self.query_one("#progress", ProgressBar).update(
            total=duration if current else 1, progress=position
        )

    def _render_snapshot(self) -> None:
        self._render_now()
        pending = [
            item
            for item in self.snapshot.get("plan", [])
            if item["state"] not in ("Playing", "Paused")
        ]
        self._fill_table("#queue", pending, ("priority", "voice", "state", "text"))
        self._fill_table("#history", self.snapshot.get("history", []), ("voice", "state", "text"))

    def _render_progress(self, event: dict[str, Any]) -> None:
        if not self.is_running:
            return
        current = self.snapshot.get("status", {}).get("current") or {}
        if event.get("id") != current.get("id"):
            return
        if current:
            current["position_ms"] = event.get("position_ms")
        self.query_one("#audio-meter", Static).update(format_meter(event.get("audio_peak")))
        self._render_now()

    async def _command(self, payload: dict[str, Any]) -> None:
        if not self.connected:
            self._message("Daemon unavailable; command was not sent.")
            return
        try:
            await self.client.request({**payload, "origin": "tui"})
            await self.refresh_snapshot()
            self._message("Connected")
        except (DaemonError, DaemonUnreachableError) as exc:
            self._message(f"Could not complete command: {exc}")

    async def action_toggle_playback(self) -> None:
        """Toggle the global hold; admission remains independent."""
        held = self.snapshot.get("status", {}).get("playback_held", False)
        await self._command({"op": "resume" if held else "pause"})

    async def action_transport(self, operation: str) -> None:
        """Use the same chunk/transport operations as the native menu."""
        await self._command({"op": operation})

    def action_navigate(self, delta: int) -> None:
        """Move within the focused table."""
        table = (
            self.focused
            if isinstance(self.focused, DataTable)
            else self.query_one("#queue", DataTable)
        )
        table.focus()
        table.move_cursor(row=max(0, min(table.row_count - 1, table.cursor_row + delta)))

    def on_key(self, event: events.Key) -> None:
        """Any intervening key cancels the dd sequence."""
        if event.key != "d":
            self._delete_candidate = None

    async def action_delete(self) -> None:
        """Require two consecutive d presses on the same queued identity."""
        table = self.query_one("#queue", DataTable)
        if self.focused is not table or (identity := self._selected(table)) is None:
            return
        previous = self._delete_candidate
        now = self._clock()
        self._delete_candidate = (identity, now)
        if previous and previous[0] == identity and now - previous[1] < _DELETE_WINDOW_SECONDS:
            self._delete_candidate = None
            await self._command({"op": "cancel", "id": identity})
        else:
            self._message("Press d again to cancel this queued clip.")

    async def action_move(self, delta: int) -> None:
        """Submit an exact permutation; concurrent queue changes are rejected by the daemon."""
        table = self.query_one("#queue", DataTable)
        if self.focused is not table or (identity := self._selected(table)) is None:
            return
        ids = [
            item["id"]
            for item in self.snapshot.get("plan", [])
            if item["state"] not in ("Playing", "Paused")
        ]
        index = ids.index(identity)
        destination = index + delta
        if 0 <= destination < len(ids):
            ids[index], ids[destination] = ids[destination], ids[index]
            await self._command({"op": "reorder", "ids": ids})

    async def action_requeue(self) -> None:
        """Replay the selected history entry with its recorded voice and model."""
        table = self.query_one("#history", DataTable)
        if self.focused is table and (identity := self._selected(table)) is not None:
            await self._command({"op": "requeue", "id": identity})
