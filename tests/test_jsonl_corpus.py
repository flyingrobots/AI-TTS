# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Replay the permanent minimized JSONL parser corpus."""

from __future__ import annotations

from pathlib import Path

import pytest

from aitts.adapters.jsonl import JsonlDecodeError, decode_json_object

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("checked-in minimized JSONL parser counterexamples"),
]

CORPUS = Path(__file__).parent / "corpus" / "jsonl"
CASES = {
    "invalid-utf8.hex": ("typed_error", "not valid JSON"),
    "malformed.hex": ("typed_error", "not valid JSON"),
    "nonfinite.hex": ("typed_error", "not valid JSON"),
    "nonobject.hex": ("typed_error", "expected a JSON object"),
    "valid-object.hex": ("object", {"op": "status"}),
}


def test_corpus_ledger_names_every_checked_in_seed() -> None:
    assert set(CASES) == {path.name for path in CORPUS.glob("*.hex")}


@pytest.mark.parametrize(("filename", "expected"), CASES.items())
def test_minimized_parser_corpus_has_declared_outcome(
    filename: str, expected: tuple[str, object]
) -> None:
    line = bytes.fromhex((CORPUS / filename).read_text().strip())
    try:
        result = decode_json_object(line)
    except JsonlDecodeError as exc:
        outcome: tuple[str, object] = ("typed_error", str(exc))
    else:
        outcome = ("object", result)

    assert outcome == expected
