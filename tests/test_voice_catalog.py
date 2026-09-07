# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The curated catalog, and the one honest way to add to it.

The voice list is not "whatever the model repository ships". Every entry was
verified to synthesize with the G2P dependencies this project installs, and
the Japanese and Mandarin sets are deliberately absent because they need
extras that build from source — a supply-chain decision, not a voice-list
edit. That is exactly why the list cannot simply become a config file that
anything may write.

It also cannot be closed. Someone who has installed those extras themselves,
or who wants a voice a new upstream release added, should not have to wait for
a release of this project. So the catalog is extended by an explicit
environment variable, and every addition is validated: a typo'd voice that
reached the catalog would become claimable and then fail every synthesis,
which is worse than being told the name is wrong.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from aitts.engines.kokoro import VOICES, KokoroEngine, parse_extra_voices

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("the curated voice catalog documented in README's voices section"),
]


def test_the_catalog_is_the_verified_list_by_default() -> None:
    engine = KokoroEngine()

    assert tuple(engine.list_voices()) == VOICES


def test_a_declared_extra_voice_joins_the_catalog() -> None:
    engine = KokoroEngine(extra_voices=("jf_alpha",))

    catalog = engine.list_voices()
    # Additive, not a replacement: nobody extending the list intends to lose
    # the forty-one voices that were verified.
    assert set(VOICES).issubset(catalog)
    assert "jf_alpha" in catalog


def test_an_extra_voice_already_in_the_catalog_is_not_duplicated() -> None:
    engine = KokoroEngine(extra_voices=("bm_daniel",))

    catalog = engine.list_voices()
    # A duplicate would show twice in every voice picker.
    assert catalog.count("bm_daniel") == 1
    assert tuple(catalog) == VOICES


@pytest.mark.parametrize(
    "declared",
    ["", "  ", "not a voice", "af-heart", "AF_HEART", "../etc/passwd", "af_", "_heart", "af_x/y"],
)
def test_a_malformed_extra_voice_is_refused(declared: str) -> None:
    assert parse_extra_voices(declared) == ()


def test_a_malformed_entry_does_not_discard_its_valid_neighbours() -> None:
    # One typo in a list of four should cost that one entry, not the list.
    assert parse_extra_voices("jf_alpha, not a voice ,jm_beta") == ("jf_alpha", "jm_beta")


def test_declared_voices_are_ordered_and_deduplicated() -> None:
    # The catalog is read into pickers and settings views; a stable order is
    # what keeps a voice in the same place between restarts.
    assert parse_extra_voices("zm_yang,jf_alpha,zm_yang") == ("jf_alpha", "zm_yang")


def test_nothing_declared_adds_nothing() -> None:
    assert parse_extra_voices(None) == ()
    assert parse_extra_voices("") == ()


def test_a_voice_path_is_still_resolved_under_the_repository(tmp_path: Path) -> None:
    from aitts.engines.kokoro import KokoroAssets  # noqa: PLC0415

    seen: list[str] = []

    def record(*, repo_id: str, filename: str, local_files_only: bool) -> str:
        del repo_id, local_files_only
        seen.append(filename)
        path = tmp_path / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"asset")
        return str(path)

    KokoroAssets(repo_id="hexgrad/Kokoro-82M", download=record).voice_path("jf_alpha")

    # An extra voice is still a file in the model repository, resolved the
    # same way as every other. Accepting a name is not accepting a path.
    assert seen == ["voices/jf_alpha.pt"]
