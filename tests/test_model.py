# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The utterance state machine is the spec in architecture.md §3."""

from __future__ import annotations

import pytest

from aitts.model import (
    TERMINAL,
    TRANSITIONS,
    Priority,
    Sensitivity,
    State,
    can_transition,
    new_utterance_id,
)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for state in TERMINAL:
        assert TRANSITIONS.get(state, frozenset()) == frozenset()


def test_terminal_set_matches_diagram() -> None:
    assert set(TERMINAL) == {State.PLAYED, State.SKIPPED, State.CANCELLED, State.FAILED}


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (State.SUBMITTED, State.QUEUED),
        (State.QUEUED, State.SYNTHESIZING),
        (State.SYNTHESIZING, State.READY),
        (State.SYNTHESIZING, State.FAILED),
        (State.READY, State.PLAYING),
        (State.PLAYING, State.PLAYED),
        (State.PLAYING, State.PAUSED),
        (State.PAUSED, State.PLAYING),
        (State.PLAYING, State.SKIPPED),
        (State.PAUSED, State.SKIPPED),
        (State.QUEUED, State.CANCELLED),
        (State.SYNTHESIZING, State.CANCELLED),
        (State.READY, State.CANCELLED),
        # Restart recovery paths (architecture §6): re-queue interrupted synthesis.
        (State.SYNTHESIZING, State.QUEUED),
    ],
)
def test_legal_transitions(src: State, dst: State) -> None:
    assert can_transition(src, dst)


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (State.QUEUED, State.PLAYING),  # queueing is not speaking (F1)
        (State.READY, State.PLAYED),  # nothing is played without Playing first
        (State.PLAYED, State.PLAYING),  # terminal is terminal
        (State.FAILED, State.QUEUED),
        (State.CANCELLED, State.READY),
        (State.PLAYING, State.CANCELLED),  # cancel of a playing utterance is skip
        (State.SUBMITTED, State.READY),
    ],
)
def test_illegal_transitions(src: State, dst: State) -> None:
    assert not can_transition(src, dst)


def test_sensitivity_values() -> None:
    assert {s.value for s in Sensitivity} == {"public", "internal", "confidential"}


def test_priority_values() -> None:
    assert {p.value for p in Priority} == {"normal", "urgent"}


def test_utterance_ids_are_prefixed_and_unique() -> None:
    ids = {new_utterance_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(i.startswith("utt_") for i in ids)
