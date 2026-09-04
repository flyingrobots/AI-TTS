# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Store semantics: queues, ordering, history, recovery (architecture.md §4, §6)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from aitts.model import Priority, Sensitivity, State, Utterance
from aitts.store import Store, TransitionError

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "queue, history, and recovery contracts in architecture sections 2, 3, and 6"
    ),
]


def submit(store: Store, text: str = "hello", **kw: object) -> Utterance:
    return store.submit(text, voice="bm_daniel", speed=1.0, **kw)  # type: ignore[arg-type]


class OneShotCommitFailure(sqlite3.Connection):
    fail_next_commit = False

    def commit(self) -> None:
        if self.fail_next_commit:
            self.fail_next_commit = False
            msg = "seeded commit failure"
            raise sqlite3.OperationalError(msg)
        super().commit()


def test_failed_commit_never_leaks_non_durable_state(
    tmp_path: Path,
) -> None:
    real_connect = sqlite3.connect
    connections: list[OneShotCommitFailure] = []

    def connect(path: str) -> sqlite3.Connection:
        connection = real_connect(path, factory=OneShotCommitFailure)
        connections.append(connection)
        return connection

    database = tmp_path / "fault.db"
    store = Store(database, connect=connect)
    connections[0].fail_next_commit = True
    error: str | None = None
    try:
        submit(store, "must be durable")
    except sqlite3.OperationalError as exc:
        error = str(exc)
    visible_after_failure = store.counts()
    store.close()

    reopened = Store(database, connect=connect)
    durable_after_reopen = reopened.counts()
    reopened.close()

    assert {
        "error": error,
        "visible_after_failure": visible_after_failure,
        "durable_after_reopen": durable_after_reopen,
    } == {
        "error": "seeded commit failure",
        "visible_after_failure": {},
        "durable_after_reopen": {},
    }


def test_submit_defaults_to_confidential(store: Store) -> None:
    utt = submit(store)
    assert utt.sensitivity is Sensitivity.CONFIDENTIAL


def test_submit_lands_queued_with_id(store: Store) -> None:
    utt = submit(store)
    assert utt.state is State.QUEUED
    assert utt.id.startswith("utt_")
    assert store.get(utt.id) == utt


def test_submission_order_is_preserved(store: Store) -> None:
    a, b, c = (submit(store, t) for t in ("a", "b", "c"))
    assert [u.id for u in store.input_queue()] == [a.id, b.id, c.id]


def test_at_head_inserts_before_existing(store: Store) -> None:
    a = submit(store, "a")
    b = submit(store, "b", at_head=True)
    assert [u.id for u in store.input_queue()] == [b.id, a.id]


def test_transition_updates_and_notifies(store: Store) -> None:
    seen: list[tuple[str, State, State]] = []
    store.on_transition.append(lambda u, frm: seen.append((u.id, frm, u.state)))
    utt = submit(store)
    store.transition(utt.id, State.SYNTHESIZING)
    store.transition(utt.id, State.READY, audio_path="/cache/x.wav", duration_ms=1200)
    got = store.get(utt.id)
    assert got is not None
    assert got.state is State.READY
    assert got.audio_path == "/cache/x.wav"
    assert got.duration_ms == 1200
    assert seen == [
        (utt.id, State.QUEUED, State.SYNTHESIZING),
        (utt.id, State.SYNTHESIZING, State.READY),
    ]


def test_illegal_transition_raises_and_leaves_state(store: Store) -> None:
    utt = submit(store)
    with pytest.raises(TransitionError):
        store.transition(utt.id, State.PLAYING)
    got = store.get(utt.id)
    assert got is not None
    assert got.state is State.QUEUED


def test_failed_records_error_in_history(store: Store) -> None:
    utt = submit(store)
    store.transition(utt.id, State.SYNTHESIZING)
    store.transition(utt.id, State.FAILED, error="engine exploded")
    items = store.history()
    assert [u.id for u in items] == [utt.id]
    assert items[0].error == "engine exploded"


def test_history_only_terminal_newest_first_with_pagination(store: Store) -> None:
    utts = [submit(store, str(i)) for i in range(5)]
    for u in utts[:3]:
        store.transition(u.id, State.CANCELLED)
    page = store.history(limit=2)
    assert [u.id for u in page] == [utts[2].id, utts[1].id]
    rest = store.history(limit=10, before=page[-1].id)
    assert [u.id for u in rest] == [utts[0].id]


def test_playback_queue_holds_ready_playing_paused(store: Store) -> None:
    a, b, c = (submit(store, t) for t in ("a", "b", "c"))
    for u in (a, b):
        store.transition(u.id, State.SYNTHESIZING)
        store.transition(u.id, State.READY, audio_path="x", duration_ms=1)
    store.transition(a.id, State.PLAYING)
    assert [u.id for u in store.playback_queue()] == [a.id, b.id]
    assert c.id in [u.id for u in store.input_queue()]


def test_head_of_plan_is_earliest_nonterminal(store: Store) -> None:
    a = submit(store, "a")
    submit(store, "b")
    store.transition(a.id, State.CANCELLED)
    head = store.head_of_plan()
    assert head is not None
    assert head.text == "b"


def test_claim_for_synthesis_is_fifo_and_exclusive(store: Store) -> None:
    a = submit(store, "a")
    b = submit(store, "b")
    first = store.claim_for_synthesis()
    second = store.claim_for_synthesis()
    third = store.claim_for_synthesis()
    assert first is not None
    assert second is not None
    assert (first.id, second.id) == (a.id, b.id)
    assert first.state is State.SYNTHESIZING
    assert third is None


def test_move_to_head_reorders_plan(store: Store) -> None:
    a = submit(store, "a")
    b = submit(store, "b")
    store.move_to_head(b.id)
    head = store.head_of_plan()
    assert head is not None
    assert head.id == b.id
    assert [u.id for u in store.input_queue()] == [b.id, a.id]


def test_clear_input_cancels_unsynthesized(store: Store) -> None:
    a = submit(store, "a")
    b = submit(store, "b")
    store.transition(a.id, State.SYNTHESIZING)
    cleared = store.clear_queue("input")
    assert cleared == 2
    got_a, got_b = store.get(a.id), store.get(b.id)
    assert got_a is not None
    assert got_b is not None
    assert got_a.state is State.CANCELLED
    assert got_b.state is State.CANCELLED


def test_clear_playback_cancels_ready_but_not_playing(store: Store) -> None:
    a, b = submit(store, "a"), submit(store, "b")
    for u in (a, b):
        store.transition(u.id, State.SYNTHESIZING)
        store.transition(u.id, State.READY, audio_path="x", duration_ms=1)
    store.transition(a.id, State.PLAYING)
    cleared = store.clear_queue("playback")
    assert cleared == 1
    got_a, got_b = store.get(a.id), store.get(b.id)
    assert got_a is not None
    assert got_b is not None
    assert got_a.state is State.PLAYING
    assert got_b.state is State.CANCELLED


def test_clear_pending_cancels_every_upcoming_state_but_not_playing(store: Store) -> None:
    playing, ready, synthesizing, queued = (submit(store, text) for text in ("a", "b", "c", "d"))
    for utt in (playing, ready):
        store.transition(utt.id, State.SYNTHESIZING)
        store.transition(utt.id, State.READY, audio_path=f"{utt.id}.wav", duration_ms=1)
    store.transition(playing.id, State.PLAYING)
    store.transition(synthesizing.id, State.SYNTHESIZING)

    assert store.clear_pending() == 3
    assert store.get(playing.id).state is State.PLAYING  # type: ignore[union-attr]
    for utt in (ready, synthesizing, queued):
        assert store.get(utt.id).state is State.CANCELLED  # type: ignore[union-attr]


def test_reorder_pending_requires_and_applies_the_complete_pending_plan(store: Store) -> None:
    current, first, second = (submit(store, text) for text in ("current", "first", "second"))
    store.transition(current.id, State.SYNTHESIZING)
    store.transition(current.id, State.READY, audio_path="current.wav", duration_ms=1)
    store.transition(current.id, State.PLAYING)

    store.reorder_pending([second.id, first.id])
    next_item = store.next_pending()
    assert next_item is not None
    assert next_item.id == second.id
    assert [utt.id for utt in store.input_queue()] == [second.id, first.id]

    with pytest.raises(ValueError, match="complete pending plan"):
        store.reorder_pending([first.id])
    with pytest.raises(ValueError, match="complete pending plan"):
        store.reorder_pending([first.id, first.id])


def test_history_rows_can_be_removed_or_cleared_without_touching_active_work(store: Store) -> None:
    first = submit(store, "first", priority=Priority.URGENT)
    second = submit(store, "second")
    active = submit(store, "active")
    store.transition(first.id, State.CANCELLED)
    store.transition(second.id, State.CANCELLED)

    assert store.remove_history(first.id) is True
    assert store.get(first.id) is None
    assert store.remove_history(active.id) is False
    assert store.get(active.id) is not None

    assert store.clear_history() == 1
    assert store.history() == []
    assert store.get(active.id) is not None


def test_settings_roundtrip_and_default(store: Store) -> None:
    assert store.get_setting("voice", "bm_daniel") == "bm_daniel"
    store.set_setting("voice", "af_bella")
    assert store.get_setting("voice", "bm_daniel") == "af_bella"


def test_persistence_across_reopen(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    st = Store(db)
    utt = st.submit("survive", voice="bm_daniel", speed=1.0)
    st.close()
    st2 = Store(db)
    got = st2.get(utt.id)
    assert got is not None
    assert got.text == "survive"
    st2.close()


def test_recover_requeues_synthesizing_and_pauses_playing(tmp_path: Path) -> None:
    db = tmp_path / "state.db"
    st = Store(db)
    a = st.submit("a", voice="v", speed=1.0)
    b = st.submit("b", voice="v", speed=1.0)
    st.transition(a.id, State.SYNTHESIZING)
    st.transition(b.id, State.SYNTHESIZING)
    st.transition(b.id, State.READY, audio_path="x", duration_ms=1)
    st.transition(b.id, State.PLAYING)
    st.close()
    st2 = Store(db)
    st2.recover()
    got_a, got_b = st2.get(a.id), st2.get(b.id)
    assert got_a is not None
    assert got_b is not None
    assert got_a.state is State.QUEUED  # unsynthesized text is not recoverable elsewhere
    assert got_b.state is State.PAUSED  # a restored queue never starts speaking on its own
    st2.close()
