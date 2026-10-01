# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Streamed children keep truthful failure and skip records in the durable store."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aitts.model import State
from aitts.store import Store

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "architecture lifecycle: a failed generation fails its own segment with its error, "
        "and a segment the listener skipped stays skipped"
    ),
]


@pytest.mark.parametrize("live", [State.READY, State.PLAYING])
def test_generation_failure_fails_the_streamed_segment_with_its_error(
    tmp_path: Path, live: State
) -> None:
    # Retire only when streamed children stop advertising readiness before publication.
    store = Store(tmp_path / "state.db")
    try:
        clip = store.submit("source", voice="v", speed=1, spoken_segments=("first", "second"))
        work = store.claim_for_synthesis()
        assert work is not None
        assert work.segment_index == 0
        store.start_streaming(work)
        if live is State.PLAYING:
            store.transition(clip.id, State.PLAYING)
            store.transition_segment(clip.id, 0, State.PLAYING)
        assert store.synthesis_work_is_active(work)
        store.fail_synthesis(work, "seeded engine failure")
        segment = store.get_segment(clip.id, 0)
        assert segment is not None
        assert (segment.state, segment.error) == (State.FAILED, "seeded engine failure")
        parent = store.get(clip.id)
        assert parent is not None
        assert parent.state is State.FAILED
    finally:
        store.close()
