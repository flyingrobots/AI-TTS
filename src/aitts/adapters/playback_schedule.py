# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Production playback-scheduling adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aitts.application.playback_schedule import PlaybackCheckpoint


class ImmediatePlaybackSchedule:
    """Pass every playback checkpoint without suspending the current task."""

    async def checkpoint(self, point: PlaybackCheckpoint) -> None:
        """Keep production event-loop ordering unchanged."""
        del point
