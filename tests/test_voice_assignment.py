# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Each speaking client gets its own voice (architecture §10 item 6).

Distinct voices are how the listener tells agents apart, and left to
convention they collide: three separate agents were observed speaking as
``bm_daniel`` because each picked its own favourite independently. The daemon
owns the mapping instead, and the listener outranks every agent's preference.
"""

from __future__ import annotations

import ast
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from aitts.daemon import Daemon
from aitts.engine import FakeEngine
from aitts.engines.kokoro import VOICES
from aitts.ipc import ApiError
from aitts.playback import FakeSink

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from aitts.application.voice_assignment import (
    LOCAL_UI_SOURCE_PREFIXES,
    VoiceDecision,
    decide_speaking_voice,
    next_unclaimed_voice,
)

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "client identity in architecture section 10 item 6, and the per-agent voice "
        "convention recorded in the operator's agent instructions"
    ),
]

CATALOG = ("af_heart", "af_bella", "bm_daniel", "bm_george", "im_nicola")
DEFAULT = "bf_emma"
# The daemon default has to be a voice its engine actually offers.
DAEMON_DEFAULT = "im_nicola"


@pytest.fixture
async def voice_daemon(tmp_path: Path) -> AsyncIterator[Daemon]:
    """A daemon whose engine offers exactly CATALOG, so claims are countable."""
    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-voice-"))
    daemon = Daemon(
        home=tmp_path,
        engine=FakeEngine(voices=list(CATALOG)),
        sink=FakeSink(auto_finish_ms=5),
        workers=1,
        socket_path=sock_dir / "d.sock",
    )
    daemon.store.set_setting("voice", DAEMON_DEFAULT)
    await daemon.start()
    yield daemon
    await daemon.stop()
    shutil.rmtree(sock_dir, ignore_errors=True)


def decide(
    *,
    source: str | None = "an-agent",
    requested: str | None = None,
    pinned: str | None = None,
    claimed: str | None = None,
    taken: tuple[str, ...] = (),
) -> VoiceDecision:
    """Decide one submission's voice against a small catalog."""
    return decide_speaking_voice(
        source=source,
        requested=requested,
        default_voice=DEFAULT,
        catalog=CATALOG,
        pinned=pinned,
        claimed=claimed,
        taken=taken,
    )


# -- who wins ------------------------------------------------------------


def test_the_listeners_override_beats_the_agents_own_preference() -> None:
    decision = decide(requested="af_heart", pinned="im_nicola")

    # The whole point of an override: the agent asked, and was overruled.
    assert decision == VoiceDecision(voice="im_nicola", claim=False)


def test_a_first_time_agent_gets_the_voice_it_asks_for_and_keeps_it() -> None:
    decision = decide(requested="af_bella")

    # Granted, and written down — otherwise the register stays empty, because
    # every agent already passes a voice of its own.
    assert decision == VoiceDecision(voice="af_bella", claim=True)


def test_a_held_voice_outranks_a_fresh_request() -> None:
    decision = decide(requested="af_bella", claimed="bm_george")

    # The listener recognises an agent by its voice; an agent changing its
    # mind mid-session is the failure, not the feature.
    assert decision == VoiceDecision(voice="bm_george", claim=False)


def test_an_agent_asking_for_a_voice_someone_else_holds_gets_a_different_one() -> None:
    decision = decide(source="a-latecomer", requested="bm_daniel", taken=("bm_daniel",))

    # This is the collision the register exists to prevent: three agents were
    # observed speaking as bm_daniel, each having chosen it independently.
    assert decision.voice != "bm_daniel"
    assert decision == VoiceDecision(voice="af_heart", claim=True)


def test_an_agent_keeps_the_voice_it_already_claimed() -> None:
    decision = decide(claimed="bm_george")

    assert decision == VoiceDecision(voice="bm_george", claim=False)


def test_an_override_beats_an_existing_claim() -> None:
    decision = decide(claimed="bm_george", pinned="af_heart")

    assert decision == VoiceDecision(voice="af_heart", claim=False)


# -- claiming ------------------------------------------------------------


def test_a_new_agent_claims_a_voice_nobody_else_holds() -> None:
    decision = decide(source="a-new-agent", taken=("af_heart", "af_bella"))

    assert decision == VoiceDecision(voice="bm_daniel", claim=True)


def test_claims_are_handed_out_in_catalog_order() -> None:
    assert next_unclaimed_voice(CATALOG, ()) == "af_heart"
    assert next_unclaimed_voice(CATALOG, ("af_heart",)) == "af_bella"


def test_an_exhausted_catalog_still_answers() -> None:
    # Sharing is only acceptable once there is nothing left to share out.
    voice = next_unclaimed_voice(CATALOG, CATALOG)

    assert voice in CATALOG


def test_an_exhausted_catalog_does_not_wedge_a_submission() -> None:
    decision = decide(source="one-agent-too-many", taken=CATALOG)

    assert decision.voice in CATALOG
    assert decision.claim is True


# -- who is not an agent -------------------------------------------------


def test_speech_with_no_source_uses_the_default_voice() -> None:
    decision = decide(source=None)

    assert decision == VoiceDecision(voice=DEFAULT, claim=False)


@pytest.mark.parametrize("prefix", LOCAL_UI_SOURCE_PREFIXES)
def test_the_listeners_own_reading_uses_the_default_voice(prefix: str) -> None:
    decision = decide(source=f"{prefix}text")

    # Reading a selection or a file is the listener reading to themselves, not
    # an agent speaking, so it must not consume a voice from the catalog.
    assert decision == VoiceDecision(voice=DEFAULT, claim=False)


@pytest.mark.parametrize("prefix", LOCAL_UI_SOURCE_PREFIXES)
def test_a_pinned_voice_still_applies_to_the_listeners_own_reading(prefix: str) -> None:
    decision = decide(source=f"{prefix}text", pinned="im_nicola")

    assert decision == VoiceDecision(voice="im_nicola", claim=False)


# -- through the daemon ---------------------------------------------------


async def test_agents_speaking_for_the_first_time_end_up_on_distinct_voices(
    voice_daemon: Daemon,
) -> None:
    # All three ask for the same voice, exactly as observed in real history.
    for source in ("first-agent", "second-agent", "third-agent"):
        await voice_daemon.dispatch(
            {"op": "submit", "text": "hello", "source": source, "voice": "bm_daniel"}
        )

    spoken = {item.source: item.voice for item in voice_daemon.store.voice_assignments()}
    assert spoken["first-agent"] == "bm_daniel"
    assert len({*spoken.values()}) == 3


async def test_an_agent_keeps_its_voice_across_submissions(voice_daemon: Daemon) -> None:
    first = await voice_daemon.dispatch({"op": "submit", "text": "one", "source": "steady"})
    second = await voice_daemon.dispatch(
        {"op": "submit", "text": "two", "source": "steady", "voice": "im_nicola"}
    )

    one = voice_daemon.store.get(str(first["id"]))
    two = voice_daemon.store.get(str(second["id"]))
    assert one is not None
    assert two is not None
    assert one.voice == two.voice


async def test_the_listener_can_see_and_change_the_mapping(voice_daemon: Daemon) -> None:
    await voice_daemon.dispatch({"op": "submit", "text": "hello", "source": "an-agent"})

    listed = await voice_daemon.dispatch({"op": "voice_assignments"})
    assert [item["source"] for item in listed["assignments"]] == ["an-agent"]
    assert listed["assignments"][0]["pinned"] is False

    pinned = await voice_daemon.dispatch(
        {"op": "assign_voice", "source": "an-agent", "voice": "im_nicola"}
    )
    assert pinned["assignment"] == {
        "source": "an-agent",
        "voice": "im_nicola",
        "pinned": True,
        "assigned_at": pinned["assignment"]["assigned_at"],
    }


async def test_an_override_ignores_what_the_agent_asks_for(voice_daemon: Daemon) -> None:
    await voice_daemon.dispatch({"op": "assign_voice", "source": "an-agent", "voice": "im_nicola"})

    reply = await voice_daemon.dispatch(
        {"op": "submit", "text": "hello", "source": "an-agent", "voice": "bm_daniel"}
    )

    spoken = voice_daemon.store.get(str(reply["id"]))
    assert spoken is not None
    assert spoken.voice == "im_nicola"


async def test_releasing_an_assignment_lets_the_agent_claim_again(
    voice_daemon: Daemon,
) -> None:
    await voice_daemon.dispatch({"op": "assign_voice", "source": "an-agent", "voice": "im_nicola"})

    released = await voice_daemon.dispatch({"op": "assign_voice", "source": "an-agent"})
    assert released["assignment"] is None

    reply = await voice_daemon.dispatch(
        {"op": "submit", "text": "hello", "source": "an-agent", "voice": "bm_daniel"}
    )
    spoken = voice_daemon.store.get(str(reply["id"]))
    assert spoken is not None
    assert spoken.voice == "bm_daniel"


async def test_assigning_an_unknown_voice_is_refused(voice_daemon: Daemon) -> None:
    with pytest.raises(ApiError):
        await voice_daemon.dispatch(
            {"op": "assign_voice", "source": "an-agent", "voice": "not_a_voice"}
        )


async def test_the_listeners_own_reading_does_not_appear_in_the_mapping(
    voice_daemon: Daemon,
) -> None:
    await voice_daemon.dispatch(
        {"op": "submit", "text": "a selection", "source": "macos-service:text"}
    )

    assert voice_daemon.store.voice_assignments() == []


def test_no_client_identity_table_is_hardcoded_in_the_source() -> None:
    """No source file may carry a literal client-identity-to-voice mapping.

    A register keyed on client identity invites baking the operator's real
    client names in as seed data, which is how this project briefly shipped
    them. The check looks for the *shape* rather than for any particular name,
    both because naming one would defeat the purpose and because the next
    mistake will use different names.
    """
    catalog = set(VOICES)
    source_root = Path(__file__).parents[1] / "src"
    offenders: list[str] = []

    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Tuple, ast.List)):
                continue
            pairs = [
                element
                for element in node.elts
                if isinstance(element, (ast.Tuple, ast.List)) and len(element.elts) == 2
            ]
            if not pairs:
                continue
            for pair in pairs:
                identity, voice = pair.elts
                if (
                    isinstance(identity, ast.Constant)
                    and isinstance(identity.value, str)
                    and isinstance(voice, ast.Constant)
                    and voice.value in catalog
                ):
                    relative = path.relative_to(Path(__file__).parents[1])
                    offenders.append(f"{relative}:{pair.lineno} {identity.value!r}")

    assert offenders == []


async def test_an_upgrade_does_not_disturb_assignments_already_held(
    tmp_path: Path,
) -> None:
    from aitts.engines.kokoro import VOICES  # noqa: PLC0415 - the real catalog

    sock_dir = Path(tempfile.mkdtemp(prefix="aitts-upgrade-"))

    def build() -> Daemon:
        return Daemon(
            home=tmp_path,
            engine=FakeEngine(voices=list(VOICES)),
            sink=FakeSink(auto_finish_ms=5),
            workers=1,
            socket_path=sock_dir / "d.sock",
        )

    first = build()
    await first.start()
    try:
        # Nothing is invented at startup: the register begins empty and fills
        # from what clients actually say.
        assert first.store.voice_assignments() == []
        await first.dispatch({"op": "submit", "text": "hello", "source": "an-agent"})
        await first.dispatch({"op": "assign_voice", "source": "codex", "voice": "bm_george"})
        held = {item.source: item.voice for item in first.store.voice_assignments()}
    finally:
        await first.stop()

    restarted = build()
    await restarted.start()
    try:
        after = {item.source: item.voice for item in restarted.store.voice_assignments()}
        assert after == held
    finally:
        await restarted.stop()
        shutil.rmtree(sock_dir, ignore_errors=True)
