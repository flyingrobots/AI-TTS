# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Which voice each speaking client gets, and who is allowed to decide.

Distinct voices are how the listener tells agents apart while several are
speaking, and architecture §10 item 6 left client identity open. Leaving the
choice to each client does not work: with the convention written down and
followed in good faith, three separate agents were still observed speaking as
the same voice, because each had picked it independently and nothing was
keeping a register.

So the daemon keeps the register. A client may still ask for a voice, and
usually gets it, but the listener's own assignment outranks the request — an
override the client cannot talk its way past is the only kind worth having.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

# Speech the listener started from the app, a Service, or the voice preview.
# That is them reading to themselves, not an agent introducing itself, so it
# uses the configured default voice and never consumes one from the catalog.
LOCAL_UI_SOURCE_PREFIXES: tuple[str, ...] = ("macos-", "menubar-")


@dataclass(frozen=True, slots=True)
class VoiceDecision:
    """The voice one submission will speak in, and whether that is a new claim."""

    voice: str
    claim: bool


def is_agent_source(source: str | None) -> bool:
    """Whether ``source`` names a client that should hold a voice of its own."""
    if source is None or not source.strip():
        return False
    return not source.startswith(LOCAL_UI_SOURCE_PREFIXES)


def next_unclaimed_voice(catalog: Sequence[str], taken: Collection[str]) -> str:
    """Return the first catalog voice nobody holds, in catalog order.

    Falls back to the head of the catalog once every voice is spoken for:
    sharing a voice is bad, and refusing to speak is worse.
    """
    if not catalog:  # pragma: no cover - the engine always enumerates voices
        msg = "voice catalog is empty"
        raise ValueError(msg)
    for voice in catalog:
        if voice not in taken:
            return voice
    return catalog[0]


def decide_speaking_voice(  # noqa: PLR0911, PLR0913 - one decision, seven precedence branches
    *,
    source: str | None,
    requested: str | None,
    default_voice: str,
    catalog: Sequence[str],
    pinned: str | None,
    claimed: str | None,
    taken: Collection[str],
) -> VoiceDecision:
    """Resolve one submission's voice.

    In order of authority: the listener's pinned override; an explicit requested
    voice if available; the voice this client already holds; otherwise the next
    voice nobody holds.
    """
    if pinned is not None:
        return VoiceDecision(voice=pinned, claim=False)
    if not is_agent_source(source):
        # The listener reading to themselves: honour an explicit request, fall
        # back to the configured default, and never consume a catalog voice.
        return VoiceDecision(voice=requested or default_voice, claim=False)
    if requested is not None:
        if requested == claimed:
            return VoiceDecision(voice=claimed, claim=False)
        if requested not in taken:
            return VoiceDecision(voice=requested, claim=True)
        if claimed is not None:
            return VoiceDecision(voice=claimed, claim=False)
        return VoiceDecision(voice=next_unclaimed_voice(catalog, taken), claim=True)
    if claimed is not None:
        return VoiceDecision(voice=claimed, claim=False)
    return VoiceDecision(voice=next_unclaimed_voice(catalog, taken), claim=True)
