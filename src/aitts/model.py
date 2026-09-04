# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The utterance: states, named transitions, and the fields that travel with it.

This module encodes architecture.md §3. Nothing moves between states except
through a transition named here, and the sensitivity classification assigned at
submission never changes.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


class State(enum.StrEnum):
    """Every state an utterance can occupy."""

    SUBMITTED = "Submitted"
    QUEUED = "Queued"
    SYNTHESIZING = "Synthesizing"
    READY = "Ready"
    PLAYING = "Playing"
    PAUSED = "Paused"
    PLAYED = "Played"
    SKIPPED = "Skipped"
    CANCELLED = "Cancelled"
    FAILED = "Failed"


class Sensitivity(enum.StrEnum):
    """Who may speak this text. Assigned at submit, immutable thereafter."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"


class Priority(enum.StrEnum):
    """Queue placement. Urgent inserts at the head of the plan; it never interrupts."""

    NORMAL = "normal"
    URGENT = "urgent"


TERMINAL: frozenset[State] = frozenset({State.PLAYED, State.SKIPPED, State.CANCELLED, State.FAILED})

TRANSITIONS: Mapping[State, frozenset[State]] = MappingProxyType(
    {
        State.SUBMITTED: frozenset({State.QUEUED}),
        # Synthesizing -> Queued is the restart-recovery path (architecture §6):
        # unsynthesized text is not recoverable from anywhere else.
        State.QUEUED: frozenset({State.SYNTHESIZING, State.CANCELLED}),
        State.SYNTHESIZING: frozenset({State.READY, State.FAILED, State.CANCELLED, State.QUEUED}),
        State.READY: frozenset({State.PLAYING, State.CANCELLED}),
        State.PLAYING: frozenset({State.PLAYED, State.PAUSED, State.SKIPPED, State.FAILED}),
        State.PAUSED: frozenset({State.PLAYING, State.PLAYED, State.SKIPPED, State.FAILED}),
        State.PLAYED: frozenset(),
        State.SKIPPED: frozenset(),
        State.CANCELLED: frozenset(),
        State.FAILED: frozenset(),
    }
)


def can_transition(src: State, dst: State) -> bool:
    """Return whether the state machine permits moving from ``src`` to ``dst``."""
    return dst in TRANSITIONS[src]


def new_utterance_id() -> str:
    """Mint a stable utterance identifier."""
    return f"utt_{uuid.uuid4().hex}"


@dataclass(frozen=True, slots=True)
class Utterance:
    """One thing to be said, in whatever state it currently occupies."""

    id: str
    text: str
    voice: str
    speed: float
    sensitivity: Sensitivity
    priority: Priority
    state: State
    order_key: float
    submitted_at: float
    state_changed_at: float
    source: str | None = None
    error: str | None = None
    duration_ms: int | None = None
    played_ms: int | None = None
    audio_path: str | None = None
    replay_of: str | None = None

    @property
    def is_terminal(self) -> bool:
        """Whether this utterance has reached a final state."""
        return self.state in TERMINAL
