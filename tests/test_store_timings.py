# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Word timings are durable, follow their audio artifact, and leave with history."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aitts.model import State
from aitts.store import Store
from aitts.timing import ClipTimings, TimingSource, WordTiming

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "architecture section 6: SQLite holds state; timings are keyed by generation "
        "artifact identity so cached-audio reuse reuses them"
    ),
]

_TIMINGS = ClipTimings(TimingSource.ENGINE, (WordTiming(0, 100, 0, 5),)).encode()


def _played(store: Store, text: str) -> str:
    utterance = store.submit(text, voice="v", speed=1.0)
    work = store.claim_for_synthesis()
    assert work is not None
    store.save_timings(work.id, _TIMINGS)
    store.finish_synthesis(work, audio_path=f"/x/{work.id}.wav", duration_ms=100)
    store.transition(utterance.id, State.PLAYING)
    store.transition(utterance.id, State.PLAYED)
    return utterance.id


def test_timings_survive_restart_and_are_pruned_only_with_their_last_owner(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "state.db")
    kept = _played(store, "kept")
    removed = _played(store, "removed")
    store.save_timings("orphan_artifact", _TIMINGS)
    store.close()

    reopened = Store(tmp_path / "state.db")
    try:
        reopened.recover()
        assert reopened.timings(kept) == _TIMINGS
        assert reopened.timings(removed) == _TIMINGS
        assert reopened.timings("orphan_artifact") is None  # recovery prunes the unowned

        assert reopened.remove_history(removed)
        assert reopened.timings(removed) is None
        assert reopened.timings(kept) == _TIMINGS
        assert reopened.clear_history() == 1
        assert reopened.timings(kept) is None
    finally:
        reopened.close()


def test_rows_sharing_an_artifact_share_its_timings(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    try:
        original = _played(store, "spoken once")
        replay = store.submit("spoken once", voice="v", speed=1.0, replay_of=original)
        # The daemon's cached replay path: the new row adopts the old audio.
        store.transition(replay.id, State.SYNTHESIZING)
        store.transition(replay.id, State.READY, audio_path=f"/x/{original}.wav", duration_ms=100)
        reused = store.get(replay.id)
        assert reused is not None
        assert reused.generation_artifact_id == original
        assert store.timings(reused.generation_artifact_id) == _TIMINGS

        assert store.remove_history(original)
        assert store.timings(original) == _TIMINGS  # the replay still owns that audio
    finally:
        store.close()
