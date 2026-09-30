# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Suspension publishes segment transitions only after their state is durable."""

from __future__ import annotations

from pathlib import Path

import pytest

from aitts.model import State, UtteranceSegment
from aitts.store import Store

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("Store segment subscribers observe each committed state transition once"),
]


def test_suspending_playback_publishes_the_committed_segment_transition(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    store = Store(path)
    reader = Store(path)
    try:
        item = store.submit("document", voice="v", speed=1.0, spoken_segments=("first", "second"))
        work = store.claim_for_synthesis()
        if work is None:
            pytest.fail("fixture did not provide its first synthesis segment")
        store.finish_synthesis(work, audio_path="/owned/first.wav", duration_ms=1000)
        store.transition(item.id, State.PLAYING)
        store.transition_segment(item.id, 0, State.PLAYING)
        observed = []

        def observe(segment: UtteranceSegment, previous: State) -> None:
            durable = reader.get_segment(item.id, 0)
            parent = reader.get(item.id)
            observed.append(
                (
                    segment.utterance_id,
                    segment.index,
                    previous,
                    segment.state,
                    segment.played_ms,
                    durable.state if durable else None,
                    parent.state if parent else None,
                )
            )

        store.on_segment_transition.append(observe)
        store.suspend_playback(item.id, 0, 200)
        # A later offset refresh has no additional state transition to publish.
        store.suspend_playback(item.id, 0, 250)
        assert observed == [
            (item.id, 0, State.PLAYING, State.PAUSED, 200, State.PAUSED, State.PAUSED)
        ]
    finally:
        reader.close()
        store.close()


@pytest.mark.oracle("offset-only refresh preserves transition time and emits no state-change event")
def test_paused_offset_refresh_does_not_repeat_the_parent_transition(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [10.0]
    monkeypatch.setattr("aitts.store.time.time", lambda: clock[0])
    item = store.submit("clip", voice="v", speed=1.0)
    store.transition(item.id, State.SYNTHESIZING)
    store.transition(item.id, State.READY, audio_path="/owned/clip.wav", duration_ms=1000)
    store.transition(item.id, State.PLAYING)
    events = []
    store.on_transition.append(
        lambda clip, previous: events.append((previous, clip.state, clip.state_changed_at))
    )
    clock[0] = 20.0
    store.suspend_playback(item.id, None, 200)
    clock[0] = 30.0
    store.suspend_playback(item.id, None, 250)
    saved = store.get(item.id)
    if saved is None:
        pytest.fail("suspension unexpectedly removed its utterance")
    assert (events, saved.state_changed_at, saved.played_ms) == (
        [(State.PLAYING, State.PAUSED, 20.0)],
        20.0,
        250,
    )
