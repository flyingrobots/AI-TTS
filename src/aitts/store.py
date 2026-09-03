# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""SQLite-backed single source of truth for queues, history and settings.

Components communicate through the store rather than with each other
(architecture.md §4), so every state change in the system flows through
:meth:`Store.transition` and is observable via :attr:`Store.on_transition`.
"""

from __future__ import annotations

import sqlite3
import time
from typing import TYPE_CHECKING, Literal

from aitts.model import (
    TERMINAL,
    Priority,
    Sensitivity,
    State,
    Utterance,
    can_transition,
    new_utterance_id,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

QueueName = Literal["input", "playback"]

_INPUT_STATES = (State.SUBMITTED, State.QUEUED, State.SYNTHESIZING)
_PLAYBACK_STATES = (State.READY, State.PLAYING, State.PAUSED)
_PENDING_STATES = (State.QUEUED, State.SYNTHESIZING, State.READY)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS utterances (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    voice TEXT NOT NULL,
    speed REAL NOT NULL,
    sensitivity TEXT NOT NULL,
    priority TEXT NOT NULL,
    state TEXT NOT NULL,
    order_key REAL NOT NULL,
    submitted_at REAL NOT NULL,
    state_changed_at REAL NOT NULL,
    source TEXT,
    error TEXT,
    duration_ms INTEGER,
    played_ms INTEGER,
    audio_path TEXT,
    replay_of TEXT
);
CREATE INDEX IF NOT EXISTS idx_utterances_state ON utterances(state);
CREATE INDEX IF NOT EXISTS idx_utterances_order ON utterances(order_key);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_COLUMNS = (
    "id, text, voice, speed, sensitivity, priority, state, order_key, "
    "submitted_at, state_changed_at, source, error, duration_ms, played_ms, "
    "audio_path, replay_of"
)


class TransitionError(Exception):
    """Raised when a state change is not permitted by the state machine."""


def _row_to_utterance(row: sqlite3.Row) -> Utterance:
    return Utterance(
        id=row["id"],
        text=row["text"],
        voice=row["voice"],
        speed=row["speed"],
        sensitivity=Sensitivity(row["sensitivity"]),
        priority=Priority(row["priority"]),
        state=State(row["state"]),
        order_key=row["order_key"],
        submitted_at=row["submitted_at"],
        state_changed_at=row["state_changed_at"],
        source=row["source"],
        error=row["error"],
        duration_ms=row["duration_ms"],
        played_ms=row["played_ms"],
        audio_path=row["audio_path"],
        replay_of=row["replay_of"],
    )


class Store:
    """Transactional state for both queues, history, and settings."""

    def __init__(self, db_path: Path) -> None:
        """Open (creating if needed) the state database at ``db_path``."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path))
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(_SCHEMA)
        self._db.commit()
        self.on_transition: list[Callable[[Utterance, State], None]] = []

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()

    # -- submission ------------------------------------------------------

    def submit(  # noqa: PLR0913 - every field of an utterance is set at submit
        self,
        text: str,
        *,
        voice: str,
        speed: float,
        sensitivity: Sensitivity = Sensitivity.CONFIDENTIAL,
        priority: Priority = Priority.NORMAL,
        source: str | None = None,
        replay_of: str | None = None,
        at_head: bool = False,
    ) -> Utterance:
        """Accept text onto the input queue and return the Queued utterance.

        Sensitivity defaults to confidential: a caller cannot leak by
        forgetting, only by explicitly declaring text public (architecture §9).
        """
        now = time.time()
        order_key = self._head_order_key() if at_head else self._tail_order_key()
        utt = Utterance(
            id=new_utterance_id(),
            text=text,
            voice=voice,
            speed=speed,
            sensitivity=sensitivity,
            priority=priority,
            state=State.QUEUED,
            order_key=order_key,
            submitted_at=now,
            state_changed_at=now,
            source=source,
            replay_of=replay_of,
        )
        self._db.execute(
            f"INSERT INTO utterances ({_COLUMNS}) "  # noqa: S608 - constant column list
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                utt.id,
                utt.text,
                utt.voice,
                utt.speed,
                utt.sensitivity.value,
                utt.priority.value,
                utt.state.value,
                utt.order_key,
                utt.submitted_at,
                utt.state_changed_at,
                utt.source,
                utt.error,
                utt.duration_ms,
                utt.played_ms,
                utt.audio_path,
                utt.replay_of,
            ),
        )
        self._db.commit()
        return utt

    def _tail_order_key(self) -> float:
        row = self._db.execute("SELECT MAX(order_key) AS m FROM utterances").fetchone()
        maximum = row["m"] if row["m"] is not None else 0.0
        return float(maximum) + 1.0

    def _head_order_key(self) -> float:
        row = self._db.execute(
            "SELECT MIN(order_key) AS m FROM utterances WHERE state NOT IN "  # noqa: S608 - placeholders only
            f"({','.join('?' * len(TERMINAL))})",
            tuple(s.value for s in TERMINAL),
        ).fetchone()
        minimum = row["m"] if row["m"] is not None else 1.0
        return float(minimum) - 1.0

    # -- reads -----------------------------------------------------------

    def get(self, utt_id: str) -> Utterance | None:
        """Return the utterance with ``utt_id``, or None."""
        row = self._db.execute(
            f"SELECT {_COLUMNS} FROM utterances WHERE id = ?",  # noqa: S608
            (utt_id,),
        ).fetchone()
        return _row_to_utterance(row) if row else None

    def _by_states(self, states: tuple[State, ...]) -> list[Utterance]:
        placeholders = ",".join("?" * len(states))
        rows = self._db.execute(
            f"SELECT {_COLUMNS} FROM utterances WHERE state IN ({placeholders}) "  # noqa: S608
            "ORDER BY order_key",
            tuple(s.value for s in states),
        ).fetchall()
        return [_row_to_utterance(r) for r in rows]

    def input_queue(self) -> list[Utterance]:
        """Utterances still on the input side: Submitted, Queued, Synthesizing."""
        return self._by_states(_INPUT_STATES)

    def playback_queue(self) -> list[Utterance]:
        """Utterances on the playback side: Ready, Playing, Paused."""
        return self._by_states(_PLAYBACK_STATES)

    def pending_queue(self) -> list[Utterance]:
        """Everything that will play after the current utterance, in order."""
        return self._by_states(_PENDING_STATES)

    def head_of_plan(self) -> Utterance | None:
        """Return the earliest non-terminal utterance in plan order."""
        nonterminal = tuple(s for s in State if s not in TERMINAL)
        items = self._by_states(nonterminal)
        return items[0] if items else None

    def next_pending(self, *, exclude: str | None = None) -> Utterance | None:
        """Return the earliest utterance still owed to the listener (not playing)."""
        for utt in self._by_states(_PENDING_STATES):
            if utt.id != exclude:
                return utt
        return None

    def history(self, limit: int = 100, before: str | None = None) -> list[Utterance]:
        """Terminal utterances, newest first, paginated by utterance id."""
        params: list[object] = [s.value for s in TERMINAL]
        placeholders = ",".join("?" * len(TERMINAL))
        where = f"state IN ({placeholders})"
        if before is not None:
            anchor = self.get(before)
            if anchor is not None:
                where += " AND submitted_at < ?"
                params.append(anchor.submitted_at)
        rows = self._db.execute(
            f"SELECT {_COLUMNS} FROM utterances WHERE {where} "  # noqa: S608
            "ORDER BY submitted_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [_row_to_utterance(r) for r in rows]

    def counts(self) -> dict[str, int]:
        """Row counts per state, for status displays."""
        rows = self._db.execute(
            "SELECT state, COUNT(*) AS n FROM utterances GROUP BY state"
        ).fetchall()
        return {row["state"]: row["n"] for row in rows}

    # -- writes ----------------------------------------------------------

    def transition(  # noqa: PLR0913 - keyword-only fields that may change with state
        self,
        utt_id: str,
        to: State,
        *,
        error: str | None = None,
        duration_ms: int | None = None,
        played_ms: int | None = None,
        audio_path: str | None = None,
    ) -> Utterance:
        """Move an utterance to ``to`` through the state machine, or raise.

        Raises ``KeyError`` for an unknown id and :class:`TransitionError`
        for a move the state machine does not permit.
        """
        current = self.get(utt_id)
        if current is None:
            raise KeyError(utt_id)
        if not can_transition(current.state, to):
            msg = f"{current.state.value} -> {to.value} is not a legal transition"
            raise TransitionError(msg)
        sets = ["state = ?", "state_changed_at = ?"]
        params: list[object] = [to.value, time.time()]
        for column, value in (
            ("error", error),
            ("duration_ms", duration_ms),
            ("played_ms", played_ms),
            ("audio_path", audio_path),
        ):
            if value is not None:
                sets.append(f"{column} = ?")
                params.append(value)
        params.append(utt_id)
        self._db.execute(
            f"UPDATE utterances SET {', '.join(sets)} WHERE id = ?",  # noqa: S608
            params,
        )
        self._db.commit()
        after = self.get(utt_id)
        if after is None:  # pragma: no cover - row cannot vanish mid-update
            raise KeyError(utt_id)
        for callback in self.on_transition:
            callback(after, current.state)
        return after

    def claim_for_synthesis(self) -> Utterance | None:
        """Atomically take the earliest Queued utterance into Synthesizing."""
        row = self._db.execute(
            "SELECT id FROM utterances WHERE state = ? ORDER BY order_key LIMIT 1",
            (State.QUEUED.value,),
        ).fetchone()
        if row is None:
            return None
        return self.transition(row["id"], State.SYNTHESIZING)

    def move_to_head(self, utt_id: str) -> Utterance:
        """Reorder an utterance to the front of the plan."""
        current = self.get(utt_id)
        if current is None:
            raise KeyError(utt_id)
        self._db.execute(
            "UPDATE utterances SET order_key = ? WHERE id = ?",
            (self._head_order_key(), utt_id),
        )
        self._db.commit()
        after = self.get(utt_id)
        if after is None:  # pragma: no cover - row cannot vanish mid-update
            raise KeyError(utt_id)
        return after

    def clear_queue(self, queue: QueueName) -> int:
        """Cancel every cancellable utterance on the named queue.

        Clearing playback never touches what is currently being said:
        "stop talking" and "cancel the backlog" are different intentions.
        """
        states = _INPUT_STATES if queue == "input" else (State.READY,)
        cancelled = 0
        for utt in self._by_states(states):
            if can_transition(utt.state, State.CANCELLED):
                self.transition(utt.id, State.CANCELLED)
                cancelled += 1
        return cancelled

    def clear_pending(self) -> int:
        """Cancel everything still owed after the current utterance."""
        cancelled = 0
        for utt in self._by_states(_PENDING_STATES):
            if can_transition(utt.state, State.CANCELLED):
                self.transition(utt.id, State.CANCELLED)
                cancelled += 1
        return cancelled

    def reorder_pending(self, utt_ids: list[str]) -> None:
        """Replace the pending plan order with one exact, complete permutation."""
        pending = self.pending_queue()
        pending_ids = [utt.id for utt in pending]
        if len(utt_ids) != len(set(utt_ids)) or set(utt_ids) != set(pending_ids):
            msg = "ids must name the complete pending plan exactly once"
            raise ValueError(msg)

        current = self._by_states((State.PLAYING, State.PAUSED))
        base = max((utt.order_key for utt in current), default=0.0)
        with self._db:
            self._db.executemany(
                "UPDATE utterances SET order_key = ? WHERE id = ?",
                [(base + index, utt_id) for index, utt_id in enumerate(utt_ids, start=1)],
            )

    def remove_history(self, utt_id: str) -> bool:
        """Remove one terminal history record without touching its cached audio."""
        placeholders = ",".join("?" * len(TERMINAL))
        cursor = self._db.execute(
            f"DELETE FROM utterances WHERE id = ? AND state IN ({placeholders})",  # noqa: S608
            (utt_id, *(state.value for state in TERMINAL)),
        )
        self._db.commit()
        return cursor.rowcount == 1

    def clear_history(self) -> int:
        """Remove all terminal history records without touching cached audio."""
        placeholders = ",".join("?" * len(TERMINAL))
        cursor = self._db.execute(
            f"DELETE FROM utterances WHERE state IN ({placeholders})",  # noqa: S608
            tuple(state.value for state in TERMINAL),
        )
        self._db.commit()
        return cursor.rowcount

    def recover(self) -> None:
        """Repair state after a daemon restart (architecture §6).

        Interrupted synthesis is re-queued (the text exists nowhere else) and
        anything that was playing comes back paused: a daemon that restarts
        and immediately begins speaking talks when nobody expects it.
        """
        for utt in self._by_states((State.SYNTHESIZING,)):
            self.transition(utt.id, State.QUEUED)
        for utt in self._by_states((State.PLAYING,)):
            self.transition(utt.id, State.PAUSED)

    # -- settings --------------------------------------------------------

    def get_setting(self, key: str, default: str) -> str:
        """Read a setting, falling back to ``default``."""
        row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        """Write a setting."""
        self._db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._db.commit()
