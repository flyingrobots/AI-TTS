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


class SeededRecoveryError(RuntimeError):
    """Deterministic process-crash stand-in carrying its replay seed."""


class CrashAfterCommit(sqlite3.Connection):
    crash_after: int | None = None

    def commit(self) -> None:
        super().commit()
        if self.crash_after is None:
            return
        self.crash_after -= 1
        if self.crash_after == 0:
            self.crash_after = None
            msg = "seeded recovery crash"
            raise SeededRecoveryError(msg)


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


def test_composite_claims_children_before_later_parent_with_one_parent_profile(
    store: Store,
) -> None:
    parent = store.submit(
        "# Original document",
        voice="bm_george",
        speed=1.25,
        spoken_segments=("First spoken segment.", "Second spoken segment."),
    )
    following = submit(store, "following")

    claims = [store.claim_for_synthesis() for _ in range(3)]
    observed = [
        None if claim is None else (claim.id, claim.text, claim.voice, claim.speed, claim.state)
        for claim in claims
    ]

    assert observed == [
        (
            f"{parent.id}_segment_0000",
            "First spoken segment.",
            "bm_george",
            1.25,
            State.SYNTHESIZING,
        ),
        (
            f"{parent.id}_segment_0001",
            "Second spoken segment.",
            "bm_george",
            1.25,
            State.SYNTHESIZING,
        ),
        (following.id, "following", "bm_daniel", 1.0, State.SYNTHESIZING),
    ]


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


def test_composite_submission_persists_original_and_owned_spoken_segments(
    tmp_path: Path,
) -> None:
    database = tmp_path / "composite.db"
    original = "# Opening\n\nOriginal **Markdown** remains searchable."
    spoken = ("Opening.\n\nOriginal Markdown remains searchable.", "Second section.")
    first = Store(database)
    submitted = first.submit(
        original,
        voice="bm_george",
        speed=1.25,
        spoken_segments=spoken,
    )
    first.close()

    reopened = Store(database)
    parent = reopened.get(submitted.id)
    segments = reopened.segments(submitted.id)
    reopened.close()

    assert {
        "parent": (
            None if parent is None else (parent.text, parent.voice, parent.speed, parent.state)
        ),
        "segments": [(item.index, item.text, item.state) for item in segments],
    } == {
        "parent": (original, "bm_george", 1.25, State.QUEUED),
        "segments": [
            (0, spoken[0], State.QUEUED),
            (1, spoken[1], State.QUEUED),
        ],
    }


def test_composite_audio_is_protected_until_its_parent_is_terminal(
    store: Store,
    tmp_path: Path,
) -> None:
    parent = store.submit(
        "document",
        voice="v",
        speed=1.0,
        spoken_segments=("Only segment.",),
    )
    work = store.claim_for_synthesis()
    assert work is not None
    artifact = tmp_path / "only-segment.wav"
    store.finish_synthesis(work, audio_path=str(artifact), duration_ms=1000)

    protected_while_ready = store.protected_audio_paths()
    store.transition(parent.id, State.CANCELLED)
    protected_after_cancel = store.protected_audio_paths()
    forgotten = store.forget_terminal_audio(artifact)
    segment_after_eviction = store.get_segment(parent.id, 0)

    assert {
        "protected_while_ready": protected_while_ready,
        "protected_after_cancel": protected_after_cancel,
        "forgotten": forgotten,
        "audio_path_after_eviction": (
            None if segment_after_eviction is None else segment_after_eviction.audio_path
        ),
    } == {
        "protected_while_ready": frozenset({str(artifact)}),
        "protected_after_cancel": frozenset(),
        "forgotten": 1,
        "audio_path_after_eviction": None,
    }


def test_cancelling_composite_parent_settles_every_child(store: Store) -> None:
    parent = store.submit(
        "document",
        voice="v",
        speed=1.0,
        spoken_segments=("Ready child.", "Busy child.", "Queued child."),
    )
    ready = store.claim_for_synthesis()
    busy = store.claim_for_synthesis()
    assert ready is not None
    assert busy is not None
    store.finish_synthesis(ready, audio_path="ready.wav", duration_ms=1000)

    store.transition(parent.id, State.CANCELLED)

    assert [segment.state for segment in store.segments(parent.id)] == [
        State.CANCELLED,
        State.CANCELLED,
        State.CANCELLED,
    ]


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


def test_recover_repairs_interrupted_children_without_replaying_completed_work(
    tmp_path: Path,
) -> None:
    database = tmp_path / "composite-recovery.db"
    original = Store(database)
    parent = original.submit(
        "document",
        voice="v",
        speed=1.0,
        spoken_segments=("playing", "synthesizing", "already ready"),
    )
    first = original.claim_for_synthesis()
    second = original.claim_for_synthesis()
    third = original.claim_for_synthesis()
    assert first is not None
    assert second is not None
    assert third is not None
    original.finish_synthesis(first, audio_path="first.wav", duration_ms=1000)
    original.finish_synthesis(third, audio_path="third.wav", duration_ms=1000)
    original.transition(parent.id, State.PLAYING, played_ms=400)
    original.transition_segment(parent.id, 0, State.PLAYING, played_ms=400)
    original.close()

    restarted = Store(database)
    restarted.recover()
    recovered_parent = restarted.get(parent.id)
    recovered_segments = restarted.segments(parent.id)
    restarted.close()

    assert {
        "parent": None
        if recovered_parent is None
        else (recovered_parent.state, recovered_parent.played_ms),
        "segments": [
            (segment.index, segment.state, segment.played_ms, segment.audio_path)
            for segment in recovered_segments
        ],
    } == {
        "parent": (State.PAUSED, 400),
        "segments": [
            (0, State.PAUSED, 400, "first.wav"),
            (1, State.QUEUED, None, None),
            (2, State.READY, None, "third.wav"),
        ],
    }


@pytest.mark.parametrize("crash_after", [1, 2, 3], ids=lambda seed: f"after_commit_{seed}")
def test_recovery_converges_after_each_committed_crash_point(
    tmp_path: Path,
    crash_after: int,
) -> None:
    real_connect = sqlite3.connect
    connections: list[CrashAfterCommit] = []

    def connect(path: str) -> sqlite3.Connection:
        connection = real_connect(path, factory=CrashAfterCommit)
        connections.append(connection)
        return connection

    database = tmp_path / f"recovery-{crash_after}.db"
    original = Store(database, connect=connect)
    queued = submit(original, "queued")
    synthesizing_a = submit(original, "synthesizing-a")
    synthesizing_b = submit(original, "synthesizing-b")
    playing = submit(original, "playing")
    ready = submit(original, "ready")
    original.transition(synthesizing_a.id, State.SYNTHESIZING)
    original.transition(synthesizing_b.id, State.SYNTHESIZING)
    original.transition(playing.id, State.SYNTHESIZING)
    original.transition(playing.id, State.READY, audio_path="playing.wav", duration_ms=1)
    original.transition(playing.id, State.PLAYING)
    original.transition(ready.id, State.SYNTHESIZING)
    original.transition(ready.id, State.READY, audio_path="ready.wav", duration_ms=1)
    original.close()

    interrupted = Store(database, connect=connect)
    connections[-1].crash_after = crash_after
    with pytest.raises(SeededRecoveryError, match="seeded recovery crash"):
        interrupted.recover()
    interrupted.close()

    restarted = Store(database, connect=connect)
    restarted.recover()

    def text_and_state(utterance_id: str) -> tuple[str, State] | None:
        utterance = restarted.get(utterance_id)
        return None if utterance is None else (utterance.text, utterance.state)

    recovered = {
        utterance_id: text_and_state(utterance_id)
        for utterance_id in (
            queued.id,
            synthesizing_a.id,
            synthesizing_b.id,
            playing.id,
            ready.id,
        )
    }
    restarted.close()

    assert recovered == {
        queued.id: ("queued", State.QUEUED),
        synthesizing_a.id: ("synthesizing-a", State.QUEUED),
        synthesizing_b.id: ("synthesizing-b", State.QUEUED),
        playing.id: ("playing", State.PAUSED),
        ready.id: ("ready", State.READY),
    }
