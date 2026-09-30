# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Recovery reconciles each durable prefix of composite audio publication."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from aitts.model import State
from aitts.store import Store
from tests.test_store import CrashAfterCommit, SeededRecoveryError

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "architecture section 6: committed child audio remains playable after restart"
    ),
]


@pytest.mark.parametrize(
    ("crash_after", "recovery_crash"), [(1, None), (2, None), (1, 1), (1, 2), (1, 3)]
)
def test_first_child_publication_crash_recovers_playable_parent(
    tmp_path: Path, crash_after: int, recovery_crash: int | None
) -> None:
    # Retire only if publication becomes atomic or a stronger crash matrix replaces it.
    connections: list[CrashAfterCommit] = []

    def connect(path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(path, factory=CrashAfterCommit)
        connections.append(connection)
        return connection

    database = tmp_path / "state.db"
    store = Store(database, connect=connect)
    parent = store.submit("document", voice="v", speed=1, spoken_segments=("first", "second"))
    work = store.claim_for_synthesis()
    assert work is not None
    connections[-1].crash_after = crash_after
    with pytest.raises(SeededRecoveryError):
        store.finish_synthesis(work, audio_path="first.wav", duration_ms=10)
    store.close()
    if recovery_crash is not None:
        interrupted = Store(database, connect=connect)
        connections[-1].crash_after = recovery_crash
        with pytest.raises(SeededRecoveryError):
            interrupted.recover()
        interrupted.close()
    restarted = Store(database)
    try:
        restarted.recover()
        restored = restarted.get(parent.id)
        assert restored is not None
        assert restored.state is State.READY
    finally:
        restarted.close()


@pytest.mark.parametrize("playing", [False, True])
def test_child_failure_crash_recovers_failed_parent(tmp_path: Path, *, playing: bool) -> None:
    connections: list[CrashAfterCommit] = []

    def connect(path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(path, factory=CrashAfterCommit)
        connections.append(connection)
        return connection

    database = tmp_path / "state.db"
    store = Store(database, connect=connect)
    parent = store.submit("document", voice="v", speed=1, spoken_segments=("first", "second"))
    work = store.claim_for_synthesis()
    assert work is not None
    if playing:
        store.finish_synthesis(work, audio_path="first.wav", duration_ms=10)
        store.transition(parent.id, State.PLAYING)
        store.transition_segment(parent.id, 0, State.PLAYING)
        work = store.claim_for_synthesis()
        assert work is not None
    connections[-1].crash_after = 1
    with pytest.raises(SeededRecoveryError):
        store.fail_synthesis(work, "controlled failure")
    store.close()
    restarted = Store(database)
    try:
        restarted.recover()
        restored = restarted.get(parent.id)
        assert restored is not None
        assert (restored.state, restored.error) == (
            State.FAILED,
            "segment failed: controlled failure",
        )
    finally:
        restarted.close()
