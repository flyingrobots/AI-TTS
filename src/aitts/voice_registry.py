# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Which voice each speaking client holds, and who decided it.

Split out of the daemon because it is a durable register with its own rules,
not a step in handling a request. Three of those rules are load-bearing and
were previously only reachable through a whole daemon:

A requested voice is validated *before* the register can record it. Claiming
first and validating afterwards wrote a misspelled voice as a durable claim,
and a held voice outranks every later request, so that source could never
speak again.

Releasing is stated, never implied. Reading an omitted voice as "forget the
one you hold" meant a caller that left the field out destroyed an assignment
while believing it was reading one.

A catalog that shrank between runs is reconciled rather than trusted. An
automatic claim on a withdrawn voice is released so the client claims
something speakable; a pin is the listener's own choice, so it is reported for
repair instead of being silently substituted.

The precedence decision itself lives in
:mod:`aitts.application.voice_assignment`, which is pure. This module is what
holds the store, the catalog and the announcements around it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aitts.application.voice_assignment import decide_speaking_voice
from aitts.ipc import BAD_REQUEST, ILLEGAL_STATE, NOT_FOUND, ApiError

if TYPE_CHECKING:
    from collections.abc import Callable

    from aitts.engine import Engine
    from aitts.model import VoiceAssignment
    from aitts.store import Store

log = logging.getLogger(__name__)


def serialize_assignment(assignment: VoiceAssignment) -> dict[str, Any]:
    """Render one assignment as the wire reports it."""
    return {
        "source": assignment.source,
        "voice": assignment.voice,
        "pinned": assignment.pinned,
        "assigned_at": assignment.assigned_at,
    }


class VoiceRegistry:
    """The per-client voice register: reads, claims, pins and releases."""

    def __init__(
        self,
        store: Store,
        engine: Engine,
        *,
        default_voice: Callable[[], str],
        announce: Callable[[dict[str, Any]], None],
    ) -> None:
        """Create the register over ``store``, offering ``engine``'s catalog.

        ``default_voice`` is read rather than captured because the listener can
        change it while the daemon runs, and ``announce`` publishes each change
        so a client's settings view does not go stale.
        """
        self._store = store
        self._engine = engine
        self._default_voice = default_voice
        self._announce = announce

    def assignments(self) -> list[dict[str, Any]]:
        """Every held assignment, as the wire reports it."""
        return [serialize_assignment(item) for item in self._store.voice_assignments()]

    def resolve(self, *, source: str | None, requested: str | None) -> str:
        """Pick the voice this submission speaks in, and register a new claim.

        The listener's assignment outranks the caller's request; otherwise a
        client keeps whatever voice it already holds, and a client the daemon
        has not heard from claims one nobody else has.
        """
        catalog = self._engine.list_voices()
        # Validated before the register can record it: see the module note on
        # why a misspelled voice must not become a durable claim.
        if requested is not None and requested not in catalog:
            msg = f"unknown voice {requested!r}"
            raise ApiError(BAD_REQUEST, msg)
        assignment = self._store.voice_assignment(source) if source is not None else None
        assignment = self._reconcile(assignment, catalog)
        decision = decide_speaking_voice(
            source=source,
            requested=requested,
            default_voice=self._default_voice(),
            catalog=catalog,
            pinned=assignment.voice if assignment is not None and assignment.pinned else None,
            claimed=assignment.voice if assignment is not None else None,
            taken=self._store.claimed_voices(),
        )
        if decision.claim and source is not None:
            claimed = self._store.claim_voice(source, decision.voice)
            log.info("event=voice_claimed")
            self._announce({"event": "voice_assigned", "assignment": serialize_assignment(claimed)})
            return claimed.voice
        return decision.voice

    def assign(self, *, source: object, voice: object, release: object) -> dict[str, Any] | None:
        """Pin a voice to ``source``, or release the one it holds.

        Returns the assignment as the wire reports it, or ``None`` after a
        release. Every argument arrives from a client as arbitrary JSON, so
        each is checked here rather than trusted.
        """
        if not isinstance(source, str) or not source.strip():
            msg = "assign_voice requires a non-empty 'source'"
            raise ApiError(BAD_REQUEST, msg)
        if type(release) is not bool:
            msg = "'release' must be a boolean"
            raise ApiError(BAD_REQUEST, msg)
        # Releasing is stated, never implied; see the module note.
        if release and voice is not None:
            msg = "assign_voice takes either 'voice' or 'release', not both"
            raise ApiError(BAD_REQUEST, msg)
        if release:
            self._release(source)
            return None
        if voice is None:
            msg = "assign_voice requires a 'voice', or 'release': true to forget one"
            raise ApiError(BAD_REQUEST, msg)
        if voice not in self._engine.list_voices():
            msg = f"unknown voice {voice!r}"
            raise ApiError(BAD_REQUEST, msg)
        assignment = self._store.pin_voice(source, str(voice))
        rendered = serialize_assignment(assignment)
        self._announce({"event": "voice_assigned", "assignment": rendered})
        return rendered

    def _release(self, source: str) -> None:
        if not self._store.release_voice(source):
            msg = f"no voice is assigned to {source!r}"
            raise ApiError(NOT_FOUND, msg)
        self._announce({"event": "voice_released", "source": source})

    def _reconcile(
        self, assignment: VoiceAssignment | None, catalog: list[str]
    ) -> VoiceAssignment | None:
        """Drop a held voice this engine no longer offers; see the module note."""
        if assignment is None or assignment.voice in catalog:
            return assignment
        if assignment.pinned:
            msg = (
                f"voice {assignment.voice!r} assigned to {assignment.source!r} is not "
                f"offered by the {self._engine.name} engine; reassign it with assign_voice"
            )
            raise ApiError(ILLEGAL_STATE, msg)
        self._store.release_voice(assignment.source)
        log.info("event=voice_claim_released_unavailable")
        self._announce({"event": "voice_released", "source": assignment.source})
        return None
