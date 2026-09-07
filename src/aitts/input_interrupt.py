# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Giving the listener the floor the moment they start speaking.

Split out of the daemon because it is a loop with its own policy rather than a
step in handling a request, and because the policy has three parts that are
easy to get subtly wrong.

The platform reading is coarse and sticky. It says an input device is open,
not that anyone is talking, and dictation software holds the device open for
minutes after a recording ends. Only the cold-to-hot *edge* counts as the
floor changing hands; a level-triggered reading would re-raise the hold
immediately after every Resume, which is indistinguishable from Resume being
broken. The edge detection itself lives in
:mod:`aitts.application.input_activity`.

An armed resume is deliberately not gated on the feature switch. It can only
exist because the listener asked for one while the feature was on, and it is
their standing request rather than the feature acting; dropping it when they
later toggle the feature off would leave playback held with nothing on screen
to explain it.

A poll failure must not stop the daemon. The reading is a convenience on the
path of nothing; losing it means playback no longer stops for the listener's
voice, which the snapshot reports as an unavailable reading rather than as
quiet.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Protocol

from aitts.application.input_activity import InputInterruptDetector

if TYPE_CHECKING:
    from collections.abc import Callable

    from aitts.application.input_activity import InputActivityPort
    from aitts.playback import PlaybackController

log = logging.getLogger(__name__)

# The listener's voice should take the floor within a syllable or two, and
# each poll costs well under a millisecond.
DEFAULT_POLL_SECONDS = 0.15


class InputInterruptPolicy(Protocol):
    """The listener's standing choices about being interrupted."""

    def input_interrupt_enabled(self) -> bool:
        """Whether their own voice stops playback at all."""
        ...

    def input_interrupt_resume(self) -> str:
        """How a hold their voice caused is released."""
        ...


class InputInterruptWatcher:
    """Poll the input reading and hand the floor over on its rising edge."""

    def __init__(
        self,
        activity: InputActivityPort,
        policy: InputInterruptPolicy,
        *,
        controller: Callable[[], PlaybackController],
        announce: Callable[[dict[str, Any]], None],
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        """Create the watcher; ``controller`` is read late because it starts later."""
        self._activity = activity
        self._policy = policy
        self._controller = controller
        self._announce = announce
        self._poll_seconds = poll_seconds
        self._detector = InputInterruptDetector()

    @property
    def input_active(self) -> bool | None:
        """Whether input is hot, or ``None`` when the platform cannot be asked.

        ``None`` is materially different from quiet: nothing is watching, so
        nothing will interrupt, and a client has to be able to say so.
        """
        return self._detector.input_is_hot if self._detector.reading_available else None

    async def run(self) -> None:
        """Watch the input reading until cancelled."""
        while True:
            await self._poll()
            await asyncio.sleep(self._poll_seconds)

    async def _poll(self) -> None:
        try:
            reading = self._activity.input_is_active()
            if self._detector.observe(reading) and self._policy.input_interrupt_enabled():
                await self.interrupt_for_listener()
            elif reading is False:
                # Ungated on purpose; see the module note on armed resumes.
                await self.resume_if_armed()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a poll failure must not stop the daemon
            log.warning("event=input_activity_poll_failed")

    async def interrupt_for_listener(self) -> None:
        """Stop playback for the listener's voice and say so."""
        controller = self._controller()
        if not await controller.interrupt():
            return
        if self._policy.input_interrupt_resume() == "when_idle":
            controller.arm_resume_when_input_idle()
        log.info("event=playback_interrupted_by_listener")
        self._announce(
            {
                "event": "playback_interrupted",
                "reason": "listener_speaking",
                "resume_armed": controller.resume_when_input_idle_armed,
            }
        )

    async def resume_if_armed(self) -> None:
        """Release a hold the listener asked to have released for them."""
        controller = self._controller()
        if controller.resume_when_input_idle_armed:
            await controller.resume()
            log.info("event=playback_resumed_after_listener")
            self._announce({"event": "playback_resumed", "reason": "input_idle"})
