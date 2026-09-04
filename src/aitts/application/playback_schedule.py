# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Application scheduling port for deterministic playback interleavings."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol


class PlaybackCheckpoint(StrEnum):
    """Observable yield boundaries in the playback ownership state machine."""

    BEFORE_PLAN = "before_plan"
    PLAN_IDLE = "plan_idle"
    SINK_RESULT = "sink_result"


class PlaybackSchedulePort(Protocol):
    """Control or observe the controller at explicit interleaving boundaries."""

    async def checkpoint(self, point: PlaybackCheckpoint) -> None:
        """Pass or suspend at ``point`` according to the active scheduler."""
        ...
