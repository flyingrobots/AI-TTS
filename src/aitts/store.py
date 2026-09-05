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
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

from aitts.model import (
    TERMINAL,
    Priority,
    Sensitivity,
    State,
    SynthesisWork,
    Utterance,
    UtteranceSegment,
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
CREATE TABLE IF NOT EXISTS utterance_segments (
    utterance_id TEXT NOT NULL REFERENCES utterances(id) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    state TEXT NOT NULL,
    error TEXT,
    duration_ms INTEGER,
    played_ms INTEGER,
    audio_path TEXT,
    PRIMARY KEY (utterance_id, segment_index)
);
CREATE INDEX IF NOT EXISTS idx_utterance_segments_state ON utterance_segments(state);
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
_SEGMENT_COLUMNS = (
    "utterance_id, segment_index, text, state, error, duration_ms, played_ms, audio_path"
)


class TransitionError(Exception):
    """Raised when a state change is not permitted by the state machine."""


class DatabaseConnectionFactoryPort(Protocol):
    """Construct the SQLite connection consumed by the durable-store adapter."""

    def __call__(self, database: str, /) -> sqlite3.Connection:
        """Open one connection to ``database``."""
        ...


def _sqlite_connect(database: str) -> sqlite3.Connection:
    return sqlite3.connect(database)


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


def _row_to_segment(row: sqlite3.Row) -> UtteranceSegment:
    return UtteranceSegment(
        utterance_id=row["utterance_id"],
        index=row["segment_index"],
        text=row["text"],
        state=State(row["state"]),
        error=row["error"],
        duration_ms=row["duration_ms"],
        played_ms=row["played_ms"],
        audio_path=row["audio_path"],
    )


class Store:
    """Transactional state for both queues, history, and settings."""

    def __init__(
        self,
        db_path: Path,
        *,
        connect: DatabaseConnectionFactoryPort = _sqlite_connect,
    ) -> None:
        """Open (creating if needed) the state database at ``db_path``."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = connect(str(db_path))
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(_SCHEMA)
        self._commit_or_rollback()
        self.on_transition: list[Callable[[Utterance, State], None]] = []
        self.on_segment_transition: list[Callable[[UtteranceSegment, State], None]] = []

    def close(self) -> None:
        """Close the underlying database connection."""
        self._db.close()

    def _commit_or_rollback(self) -> None:
        try:
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

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
        spoken_segments: tuple[str, ...] | None = None,
    ) -> Utterance:
        """Accept text onto the input queue and return the Queued utterance.

        Sensitivity defaults to confidential: a caller cannot leak by
        forgetting, only by explicitly declaring text public (architecture §9).
        """
        if spoken_segments is not None and (
            not spoken_segments or any(not segment.strip() for segment in spoken_segments)
        ):
            msg = "spoken_segments must contain one or more non-empty segments"
            raise ValueError(msg)
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
        if spoken_segments is not None:
            self._db.executemany(
                "INSERT INTO utterance_segments "
                "(utterance_id, segment_index, text, state) VALUES (?, ?, ?, ?)",
                [
                    (utt.id, index, segment, State.QUEUED.value)
                    for index, segment in enumerate(spoken_segments)
                ],
            )
        self._commit_or_rollback()
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

    def segments(self, utt_id: str) -> list[UtteranceSegment]:
        """Return the ordered internal speech queue owned by ``utt_id``."""
        rows = self._db.execute(
            f"SELECT {_SEGMENT_COLUMNS} FROM utterance_segments "  # noqa: S608
            "WHERE utterance_id = ? ORDER BY segment_index",
            (utt_id,),
        ).fetchall()
        return [_row_to_segment(row) for row in rows]

    def get_segment(self, utt_id: str, index: int) -> UtteranceSegment | None:
        """Return one child segment by parent and index, or None."""
        row = self._db.execute(
            f"SELECT {_SEGMENT_COLUMNS} FROM utterance_segments "  # noqa: S608
            "WHERE utterance_id = ? AND segment_index = ?",
            (utt_id, index),
        ).fetchone()
        return _row_to_segment(row) if row else None

    def next_unfinished_segment(self, utt_id: str) -> UtteranceSegment | None:
        """Return the first child still owed within a composite utterance."""
        placeholders = ",".join("?" * len(TERMINAL))
        row = self._db.execute(
            f"SELECT {_SEGMENT_COLUMNS} FROM utterance_segments "  # noqa: S608
            f"WHERE utterance_id = ? AND state NOT IN ({placeholders}) "
            "ORDER BY segment_index LIMIT 1",
            (utt_id, *(state.value for state in TERMINAL)),
        ).fetchone()
        return _row_to_segment(row) if row else None

    def completed_segment_duration_ms(self, utt_id: str, before: int | None = None) -> int:
        """Return duration already played before an optional child index."""
        if before is None:
            row = self._db.execute(
                "SELECT COALESCE(SUM(duration_ms), 0) AS duration FROM utterance_segments "
                "WHERE utterance_id = ? AND state = ?",
                (utt_id, State.PLAYED.value),
            ).fetchone()
        else:
            row = self._db.execute(
                "SELECT COALESCE(SUM(duration_ms), 0) AS duration FROM utterance_segments "
                "WHERE utterance_id = ? AND state = ? AND segment_index < ?",
                (utt_id, State.PLAYED.value, before),
            ).fetchone()
        return int(row["duration"]) if row is not None else 0

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

    def protected_audio_paths(self) -> frozenset[str]:
        """Return cache paths referenced by work that is not yet terminal."""
        placeholders = ",".join("?" * len(TERMINAL))
        rows = self._db.execute(
            f"SELECT audio_path FROM utterances "  # noqa: S608
            f"WHERE audio_path IS NOT NULL AND state NOT IN ({placeholders}) "
            "UNION "
            "SELECT segment.audio_path FROM utterance_segments AS segment "
            "JOIN utterances AS parent ON parent.id = segment.utterance_id "
            f"WHERE segment.audio_path IS NOT NULL AND parent.state NOT IN ({placeholders})",
            (
                *(state.value for state in TERMINAL),
                *(state.value for state in TERMINAL),
            ),
        ).fetchall()
        return frozenset(str(row["audio_path"]) for row in rows)

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
        if to in TERMINAL:
            placeholders = ",".join("?" * len(TERMINAL))
            self._db.execute(
                f"UPDATE utterance_segments SET state = ? "  # noqa: S608
                f"WHERE utterance_id = ? AND state NOT IN ({placeholders})",
                (
                    State.CANCELLED.value,
                    utt_id,
                    *(state.value for state in TERMINAL),
                ),
            )
        self._commit_or_rollback()
        after = self.get(utt_id)
        if after is None:  # pragma: no cover - row cannot vanish mid-update
            raise KeyError(utt_id)
        for callback in self.on_transition:
            callback(after, current.state)
        return after

    def transition_segment(  # noqa: PLR0913 - mirrors the parent transition boundary
        self,
        utt_id: str,
        index: int,
        to: State,
        *,
        error: str | None = None,
        duration_ms: int | None = None,
        played_ms: int | None = None,
        audio_path: str | None = None,
    ) -> UtteranceSegment:
        """Move one child through the same lifecycle rules as its parent."""
        current = self.get_segment(utt_id, index)
        if current is None:
            raise KeyError((utt_id, index))
        if not can_transition(current.state, to):
            msg = f"segment {current.state.value} -> {to.value} is not a legal transition"
            raise TransitionError(msg)
        sets = ["state = ?"]
        params: list[object] = [to.value]
        for column, value in (
            ("error", error),
            ("duration_ms", duration_ms),
            ("played_ms", played_ms),
            ("audio_path", audio_path),
        ):
            if value is not None:
                sets.append(f"{column} = ?")
                params.append(value)
        params.extend((utt_id, index))
        self._db.execute(
            f"UPDATE utterance_segments SET {', '.join(sets)} "  # noqa: S608
            "WHERE utterance_id = ? AND segment_index = ?",
            params,
        )
        self._commit_or_rollback()
        after = self.get_segment(utt_id, index)
        if after is None:  # pragma: no cover - row cannot vanish mid-update
            raise KeyError((utt_id, index))
        for callback in self.on_segment_transition:
            callback(after, current.state)
        return after

    def forget_terminal_audio(self, path: Path) -> int:
        """Clear history references to one evicted artifact while retaining its rows."""
        placeholders = ",".join("?" * len(TERMINAL))
        parent_cursor = self._db.execute(
            f"UPDATE utterances SET audio_path = NULL "  # noqa: S608
            f"WHERE audio_path = ? AND state IN ({placeholders})",
            (str(path), *(state.value for state in TERMINAL)),
        )
        segment_cursor = self._db.execute(
            "UPDATE utterance_segments SET audio_path = NULL WHERE audio_path = ? "  # noqa: S608
            "AND utterance_id IN ("
            f"SELECT id FROM utterances WHERE state IN ({placeholders})"
            ")",
            (str(path), *(state.value for state in TERMINAL)),
        )
        self._commit_or_rollback()
        return parent_cursor.rowcount + segment_cursor.rowcount

    def claim_for_synthesis(self) -> SynthesisWork | None:
        """Atomically claim the earliest parent-owned unit of synthesis work."""
        terminal_placeholders = ",".join("?" * len(TERMINAL))
        row = self._db.execute(
            "SELECT u.id, u.text AS parent_text, u.voice, u.speed, u.state, "  # noqa: S608
            "s.segment_index, s.text AS segment_text "
            "FROM utterances AS u "
            "LEFT JOIN utterance_segments AS s "
            "ON s.utterance_id = u.id AND s.state = ? "
            f"WHERE (s.segment_index IS NOT NULL AND u.state NOT IN ({terminal_placeholders})) "
            "OR (u.state = ? AND NOT EXISTS ("
            "SELECT 1 FROM utterance_segments AS owned WHERE owned.utterance_id = u.id"
            ")) "
            "ORDER BY u.order_key, COALESCE(s.segment_index, -1) LIMIT 1",
            (
                State.QUEUED.value,
                *(state.value for state in TERMINAL),
                State.QUEUED.value,
            ),
        ).fetchone()
        if row is None:
            return None
        segment_index = row["segment_index"]
        if segment_index is None:
            parent = self.transition(row["id"], State.SYNTHESIZING)
            return SynthesisWork(
                id=parent.id,
                utterance_id=parent.id,
                segment_index=None,
                text=parent.text,
                voice=parent.voice,
                speed=parent.speed,
            )

        self._db.execute(
            "UPDATE utterance_segments SET state = ? "
            "WHERE utterance_id = ? AND segment_index = ? AND state = ?",
            (
                State.SYNTHESIZING.value,
                row["id"],
                segment_index,
                State.QUEUED.value,
            ),
        )
        if State(row["state"]) is State.QUEUED:
            self.transition(row["id"], State.SYNTHESIZING)
        else:
            self._commit_or_rollback()
        segment = UtteranceSegment(
            utterance_id=row["id"],
            index=segment_index,
            text=row["segment_text"],
            state=State.SYNTHESIZING,
        )
        return SynthesisWork(
            id=segment.artifact_id,
            utterance_id=row["id"],
            segment_index=segment.index,
            text=segment.text,
            voice=row["voice"],
            speed=row["speed"],
        )

    def synthesis_work_is_active(self, work: SynthesisWork) -> bool:
        """Return whether a claimed engine job may still publish its result."""
        parent = self.get(work.utterance_id)
        if parent is None or parent.is_terminal:
            return False
        if work.segment_index is None:
            return parent.state is State.SYNTHESIZING
        segment = self.get_segment(work.utterance_id, work.segment_index)
        return segment is not None and segment.state is State.SYNTHESIZING

    def finish_synthesis(
        self,
        work: SynthesisWork,
        *,
        audio_path: str,
        duration_ms: int | None,
    ) -> None:
        """Publish lifecycle metadata for one successfully rendered work item."""
        if work.segment_index is None:
            self.transition(
                work.utterance_id,
                State.READY,
                audio_path=audio_path,
                duration_ms=duration_ms,
            )
            return

        self.transition_segment(
            work.utterance_id,
            work.segment_index,
            State.READY,
            audio_path=audio_path,
            duration_ms=duration_ms,
        )
        if work.segment_index == 0:
            parent = self.get(work.utterance_id)
            if parent is not None and parent.state is State.SYNTHESIZING:
                self.transition(parent.id, State.READY)
        self._refresh_composite_duration(work.utterance_id)

    def fail_synthesis(self, work: SynthesisWork, error: str) -> None:
        """Fail one engine job and its owning parent without stalling the queue."""
        if work.segment_index is None:
            self.transition(work.utterance_id, State.FAILED, error=error)
            return
        self._db.execute(
            "UPDATE utterance_segments SET state = ?, error = ? "
            "WHERE utterance_id = ? AND segment_index = ? AND state = ?",
            (
                State.FAILED.value,
                error,
                work.utterance_id,
                work.segment_index,
                State.SYNTHESIZING.value,
            ),
        )
        self._db.execute(
            "UPDATE utterance_segments SET state = ? WHERE utterance_id = ? AND state IN (?, ?, ?)",
            (
                State.CANCELLED.value,
                work.utterance_id,
                State.QUEUED.value,
                State.SYNTHESIZING.value,
                State.READY.value,
            ),
        )
        self._commit_or_rollback()
        parent = self.get(work.utterance_id)
        if parent is not None and not parent.is_terminal:
            self.transition(parent.id, State.FAILED, error=f"segment failed: {error}")

    def _refresh_composite_duration(self, utt_id: str) -> None:
        row = self._db.execute(
            "SELECT COUNT(*) AS total, COUNT(duration_ms) AS measured, "
            "SUM(duration_ms) AS duration FROM utterance_segments WHERE utterance_id = ?",
            (utt_id,),
        ).fetchone()
        if row is not None and row["total"] > 0 and row["total"] == row["measured"]:
            self._db.execute(
                "UPDATE utterances SET duration_ms = ? WHERE id = ?",
                (row["duration"], utt_id),
            )
            self._commit_or_rollback()

    def restart_segments(self, utt_id: str) -> bool:
        """Reset every cached child of an active document for replay from zero."""
        segments = self.segments(utt_id)
        if not segments:
            return False
        resettable = (State.READY, State.PLAYING, State.PAUSED, State.PLAYED)
        placeholders = ",".join("?" * len(resettable))
        self._db.execute(
            f"UPDATE utterance_segments SET state = ?, played_ms = 0 "  # noqa: S608
            f"WHERE utterance_id = ? AND audio_path IS NOT NULL AND state IN ({placeholders})",
            (State.READY.value, utt_id, *(state.value for state in resettable)),
        )
        self._db.execute("UPDATE utterances SET played_ms = 0 WHERE id = ?", (utt_id,))
        self._commit_or_rollback()
        return True

    def skip_segments(self, utt_id: str, active_index: int | None, played_ms: int) -> None:
        """Settle one document's child queue after a parent-level Skip."""
        if active_index is not None:
            active = self.get_segment(utt_id, active_index)
            if active is not None and active.state in (State.PLAYING, State.PAUSED):
                self.transition_segment(
                    utt_id,
                    active_index,
                    State.SKIPPED,
                    played_ms=played_ms,
                )
        placeholders = ",".join("?" * len(TERMINAL))
        self._db.execute(
            f"UPDATE utterance_segments SET state = ? "  # noqa: S608
            f"WHERE utterance_id = ? AND state NOT IN ({placeholders})",
            (State.CANCELLED.value, utt_id, *(state.value for state in TERMINAL)),
        )
        self._commit_or_rollback()

    def move_to_head(self, utt_id: str) -> Utterance:
        """Reorder an utterance to the front of the plan."""
        current = self.get(utt_id)
        if current is None:
            raise KeyError(utt_id)
        self._db.execute(
            "UPDATE utterances SET order_key = ? WHERE id = ?",
            (self._head_order_key(), utt_id),
        )
        self._commit_or_rollback()
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
        self._commit_or_rollback()
        return cursor.rowcount == 1

    def clear_history(self) -> int:
        """Remove all terminal history records without touching cached audio."""
        placeholders = ",".join("?" * len(TERMINAL))
        cursor = self._db.execute(
            f"DELETE FROM utterances WHERE state IN ({placeholders})",  # noqa: S608
            tuple(state.value for state in TERMINAL),
        )
        self._commit_or_rollback()
        return cursor.rowcount

    def recover(self) -> None:
        """Repair state after a daemon restart (architecture §6).

        Interrupted synthesis is re-queued (the text exists nowhere else) and
        anything that was playing comes back paused: a daemon that restarts
        and immediately begins speaking talks when nobody expects it.
        """
        synthesizing_segments = self._segments_by_states((State.SYNTHESIZING,))
        for segment in synthesizing_segments:
            self.transition_segment(segment.utterance_id, segment.index, State.QUEUED)
        playing_segments = self._segments_by_states((State.PLAYING,))
        for segment in playing_segments:
            self.transition_segment(segment.utterance_id, segment.index, State.PAUSED)
        for utt in self._by_states((State.SYNTHESIZING,)):
            self.transition(utt.id, State.QUEUED)
        for utt in self._by_states((State.PLAYING,)):
            self.transition(utt.id, State.PAUSED)

    def _segments_by_states(self, states: tuple[State, ...]) -> list[UtteranceSegment]:
        placeholders = ",".join("?" * len(states))
        rows = self._db.execute(
            f"SELECT {_SEGMENT_COLUMNS} FROM utterance_segments "  # noqa: S608
            f"WHERE state IN ({placeholders}) ORDER BY utterance_id, segment_index",
            tuple(state.value for state in states),
        ).fetchall()
        return [_row_to_segment(row) for row in rows]

    # -- settings --------------------------------------------------------

    def get_setting(self, key: str, default: str) -> str:
        """Read a setting, falling back to ``default``."""
        row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def has_setting(self, key: str) -> bool:
        """Return whether a setting has been explicitly persisted."""
        row = self._db.execute("SELECT 1 FROM settings WHERE key = ?", (key,)).fetchone()
        return row is not None

    def set_setting(self, key: str, value: str) -> None:
        """Write a setting."""
        self._db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._commit_or_rollback()
