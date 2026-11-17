# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Regenerate the Python-written SQLite fixtures for the aitts-store crate.

Run from the repository root: ``uv run python scripts/generate_store_fixtures.py``.
Each ``<name>.db`` is a database exactly as the Python daemon left it. Each
``<name>.json`` is what the Python ``Store`` reads back after it opens the file
and, for the recovery fixtures, after ``Store.recover()`` runs at ``RECOVER_AT``.
"""

from __future__ import annotations

import contextlib
import itertools
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aitts import store as store_module
from aitts.model import Priority, Sensitivity, State
from aitts.store import Store

if TYPE_CHECKING:
    from collections.abc import Callable

HERE = Path(__file__).resolve().parents[1] / "crates/aitts-store/tests/fixtures"
RECOVER_AT = 2_000.0


class Clock:
    """A clock that advances one second per reading."""

    def __init__(self) -> None:
        """Start before every fixture timestamp."""
        self.now = 1_000.0

    def __call__(self) -> float:
        """Advance and read."""
        self.now += 1.0
        return self.now


CLOCK = Clock()
IDS = itertools.count(1)
time.time = CLOCK
vars(store_module)["new_utterance_id"] = lambda: f"utt_{next(IDS):04d}"


def dump(store: Store) -> dict[str, Any]:
    """Project every row the four store interfaces read."""
    rows = store._db.execute("SELECT id FROM utterances ORDER BY id").fetchall()  # noqa: SLF001
    utterances = []
    for row in rows:
        utt = store.get(row["id"])
        if utt is None:
            raise LookupError(row["id"])
        record = {
            name: getattr(utt, name)
            for name in (
                "id",
                "text",
                "voice",
                "speed",
                "order_key",
                "submitted_at",
                "state_changed_at",
                "source",
                "error",
                "duration_ms",
                "played_ms",
                "audio_path",
                "replay_of",
                "generation_artifact_id",
                "engine",
                "playback",
            )
        }
        record |= {
            "sensitivity": utt.sensitivity.value,
            "priority": utt.priority.value,
            "state": utt.state.value,
            "segments": [
                {
                    "index": seg.index,
                    "text": seg.text,
                    "state": seg.state.value,
                    "error": seg.error,
                    "duration_ms": seg.duration_ms,
                    "played_ms": seg.played_ms,
                    "audio_path": seg.audio_path,
                    "generation_artifact_id": seg.generation_artifact_id,
                }
                for seg in store.segments(utt.id)
            ],
        }
        utterances.append(record)
    settings = store._db.execute("SELECT key FROM settings ORDER BY key").fetchall()  # noqa: SLF001
    return {
        "utterances": utterances,
        "input": [u.id for u in store.input_queue()],
        "playback": [u.id for u in store.playback_queue()],
        "history": [u.id for u in store.history()],
        "settings": {row["key"]: store.get_setting(row["key"], "") for row in settings},
        "voices": [
            {"source": v.source, "voice": v.voice, "pinned": v.pinned, "assigned_at": v.assigned_at}
            for v in store.voice_assignments()
        ],
    }


def write(name: str, database: Path, *, recover: bool) -> None:
    """Retain ``database`` as a fixture and record what Python reads from a copy."""
    shutil.copyfile(database, HERE / f"{name}.db")
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "copy.db"
        shutil.copyfile(database, copy)
        store = Store(copy)
        if recover:
            CLOCK.now = RECOVER_AT
            time.time = lambda: RECOVER_AT
            store.recover()
            time.time = CLOCK
        expected = dump(store)
        store.close()
    (HERE / f"{name}.json").write_text(json.dumps(expected, indent=1, sort_keys=True) + "\n")


def golden(scratch: Path) -> None:
    """Rows in every table and most columns, as the Python daemon writes them."""
    database = scratch / "golden.db"
    store = Store(database)
    played = store.submit(
        "played text",
        voice="af_heart",
        speed=1.25,
        source="agent-a",
        sensitivity=Sensitivity.PUBLIC,
        engine="kokoro",
    )
    store.transition(played.id, State.SYNTHESIZING)
    store.transition(played.id, State.READY, audio_path="/cache/played.wav", duration_ms=900)
    store.transition(played.id, State.PLAYING)
    store.transition(played.id, State.PLAYED, played_ms=900)
    failed = store.submit(
        "failed text",
        voice="bm_daniel",
        speed=1.0,
        priority=Priority.URGENT,
        sensitivity=Sensitivity.INTERNAL,
    )
    store.transition(failed.id, State.SYNTHESIZING)
    store.transition(failed.id, State.FAILED, error="engine exploded")
    store.submit("replay", voice="af_heart", speed=1.0, replay_of=played.id, playback=False)
    doc = store.submit("doc", voice="bm_daniel", speed=1.0, spoken_segments=("one", "two"))
    store.transition(doc.id, State.SYNTHESIZING)
    store.transition_segment(doc.id, 0, State.SYNTHESIZING)
    store.transition_segment(doc.id, 0, State.READY, audio_path="/cache/seg0.wav", duration_ms=300)
    store.transition(doc.id, State.READY)
    store.submit("head", voice="v", speed=1.0, priority=Priority.PREEMPT, at_head=True)
    store.set_setting("speed", "1.5")
    store.set_setting("default_voice", "af_heart")
    store.pin_voice("listener-pick", "bm_daniel")
    store.claim_voice("agent-a", "af_heart")
    store.close()
    write("golden", database, recover=False)


def legacy(scratch: Path) -> None:
    """Write a database from before engines, playback flags, and generation identity."""
    database = scratch / "legacy.db"
    db = sqlite3.connect(database)
    db.executescript(
        """
        CREATE TABLE utterances (
            id TEXT PRIMARY KEY, text TEXT NOT NULL, voice TEXT NOT NULL, speed REAL NOT NULL,
            sensitivity TEXT NOT NULL, priority TEXT NOT NULL, state TEXT NOT NULL,
            order_key REAL NOT NULL, submitted_at REAL NOT NULL, state_changed_at REAL NOT NULL,
            source TEXT, error TEXT, duration_ms INTEGER, played_ms INTEGER, audio_path TEXT,
            replay_of TEXT
        );
        CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO utterances VALUES ('utt_old1', 'before engines', 'af_heart', 1.0,
            'confidential', 'normal', 'Played', 1.0, 10.0, 11.0, NULL, NULL, 500, 500,
            '/cache/gen_old1.wav', NULL);
        INSERT INTO utterances VALUES ('utt_old2', 'still queued', 'af_heart', 1.0,
            'public', 'normal', 'Queued', 2.0, 12.0, 12.0, 'agent', NULL, NULL, NULL, NULL, NULL);
        INSERT INTO settings VALUES ('speed', '1.0');
        """
    )
    db.commit()
    db.close()
    write("legacy", database, recover=True)


def _crash_after(store: Store, limit: int) -> Callable[[], None]:
    """Commit, then stop the process stand-in after ``limit`` commits."""
    commits = 0

    def commit() -> None:
        nonlocal commits
        store._db.commit()  # noqa: SLF001
        commits += 1
        if commits == limit:
            raise KeyboardInterrupt

    return commit


def crash_matrix(scratch: Path) -> None:
    """Write the recovery crash matrix: Python recovery stopped after commit 0, 1, 2, or 3."""
    for crash_after in range(4):
        database = scratch / f"crash-{crash_after}.db"
        store = Store(database)
        ids = {
            t: store.submit(t, voice="bm_daniel", speed=1.0).id
            for t in ("queued", "synthesizing-a", "synthesizing-b", "playing", "ready")
        }
        store.transition(ids["synthesizing-a"], State.SYNTHESIZING)
        store.transition(ids["synthesizing-b"], State.SYNTHESIZING)
        store.transition(ids["playing"], State.SYNTHESIZING)
        store.transition(ids["playing"], State.READY, audio_path="playing.wav", duration_ms=1)
        store.transition(ids["playing"], State.PLAYING)
        store.transition(ids["ready"], State.SYNTHESIZING)
        store.transition(ids["ready"], State.READY, audio_path="ready.wav", duration_ms=1)
        if crash_after:
            store._commit_or_rollback = _crash_after(store, crash_after)  # type: ignore[method-assign]  # noqa: SLF001
            with contextlib.suppress(KeyboardInterrupt):
                store.recover()
        store._db.close()  # noqa: SLF001
        write(f"crash-{crash_after}", database, recover=True)


def streaming(scratch: Path) -> None:
    """Unfinished streaming jobs for a playing child and a whole utterance."""
    database = scratch / "streaming.db"
    store = Store(database)
    doc = store.submit("doc", voice="v", speed=1.0, spoken_segments=("first", "second"))
    work = store.claim_for_synthesis()
    if work is None:
        raise LookupError(doc.id)
    store.start_streaming(work)
    store.transition(doc.id, State.PLAYING)
    store.transition_segment(doc.id, 0, State.PLAYING)
    whole = store.submit("whole", voice="v", speed=1.0)
    store.transition(whole.id, State.SYNTHESIZING)
    store._db.execute("INSERT INTO streaming_jobs VALUES ('job-whole', ?, NULL)", (whole.id,))  # noqa: SLF001
    store._db.commit()  # noqa: SLF001
    store.close()
    write("streaming", database, recover=True)


def main() -> int:
    """Write every fixture."""
    with tempfile.TemporaryDirectory() as scratch:
        for build in (golden, legacy, crash_matrix, streaming):
            build(Path(scratch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
