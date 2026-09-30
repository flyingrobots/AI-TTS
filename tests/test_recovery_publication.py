# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Recovery reconciles each durable prefix of composite audio publication."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from aitts.adapters.playback_schedule import ImmediatePlaybackSchedule
from aitts.model import State
from aitts.playback import FakeSink, PlaybackController
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


async def test_document_skip_crash_cannot_resume_later_children(tmp_path: Path) -> None:
    connections: list[CrashAfterCommit] = []

    def connect(path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(path, factory=CrashAfterCommit)
        connections.append(connection)
        return connection

    database = tmp_path / "state.db"
    store = Store(database, connect=connect)
    parent = store.submit("document", voice="v", speed=1, spoken_segments=("first", "second"))
    while work := store.claim_for_synthesis():
        store.finish_synthesis(work, audio_path=f"{work.id}.wav", duration_ms=10)
    store.transition(parent.id, State.PLAYING)
    store.transition_segment(parent.id, 0, State.PLAYING)
    store.transition_segment(parent.id, 0, State.PAUSED)
    store.transition(parent.id, State.PAUSED)
    controller = PlaybackController(store, FakeSink(), ImmediatePlaybackSchedule(), held=True)
    await controller.resume()
    # Skip first clears interruption metadata; crash at its next durable write.
    connections[-1].crash_after = 2
    with pytest.raises(SeededRecoveryError):
        await controller.skip()
    store.close()
    restarted = Store(database)
    try:
        restarted.recover()
        restored = restarted.get(parent.id)
        assert restored is not None
        assert (restored.state, [child.state for child in restarted.segments(parent.id)]) == (
            State.SKIPPED,
            [State.SKIPPED, State.CANCELLED],
        )
    finally:
        restarted.close()


@pytest.mark.parametrize("first_state", [State.PLAYED, State.SKIPPED])
@pytest.mark.oracle("architecture section 6: fully heard documents settle after completion crash")
def test_final_child_completion_crash_recovers_terminal_parent(
    tmp_path: Path, first_state: State
) -> None:
    connections: list[CrashAfterCommit] = []

    def connect(path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(path, factory=CrashAfterCommit)
        connections.append(connection)
        return connection

    database = tmp_path / "state.db"
    store = Store(database, connect=connect)
    parent = store.submit("document", voice="v", speed=1, spoken_segments=("first", "last"))
    while work := store.claim_for_synthesis():
        store.finish_synthesis(work, audio_path=f"{work.id}.wav", duration_ms=10)
    store.transition(parent.id, State.PLAYING)
    store.transition_segment(parent.id, 0, State.PLAYING)
    store.transition_segment(parent.id, 0, first_state)
    store.transition_segment(parent.id, 1, State.PLAYING)
    connections[-1].crash_after = 1
    with pytest.raises(SeededRecoveryError):
        store.transition_segment(parent.id, 1, State.PLAYED, played_ms=10)
    store.close()
    restarted = Store(database)
    try:
        restarted.recover()
        restored = restarted.get(parent.id)
        assert restored is not None
        assert (restored.state, restored.played_ms) == (
            State.PLAYED,
            20 if first_state is State.PLAYED else 10,
        )
    finally:
        restarted.close()
