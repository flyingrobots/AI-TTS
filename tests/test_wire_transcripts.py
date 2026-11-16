# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Exact wire change detection against the reviewed Python reference transcripts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.socket_daemon import daemon_process
from tests.wire_transcripts import SCENARIOS, assert_transcript, record_scenario

pytestmark = [
    pytest.mark.medium,
    pytest.mark.socket_contract,
    pytest.mark.oracle("class 5: checked-in Python 0.2.0 wire transcripts; issue #114"),
]

CORPUS = Path(__file__).parent / "corpus" / "wire"


@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_wire_transcript(scenario: str, tmp_path: Path) -> None:
    expected = json.loads((CORPUS / f"{scenario}.json").read_text())
    async with daemon_process(tmp_path) as daemon:
        actual = await record_scenario(daemon.socket_path, scenario)
        assert_transcript(actual, expected, daemon.home)


def test_corpus_contains_exactly_the_required_operations() -> None:
    assert {path.stem for path in CORPUS.glob("*.json")} == {
        "submit",
        "status",
        "list",
        "history",
        "pause",
        "resume",
        "skip",
        "settings",
        "subscribe",
    }
