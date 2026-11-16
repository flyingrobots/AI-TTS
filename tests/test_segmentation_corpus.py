# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Replay reviewed segmentation examples and check plain-text word preservation."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel, ConfigDict, Field

from aitts.model import ContentFormat
from aitts.segmentation import prepare_speech_segments

pytestmark = pytest.mark.oracle("reviewed segmentation corpus and input word-order invariant")

CORPUS_PATH = Path(__file__).parent / "corpus" / "segmentation" / "cases.json"
KINDS = {"plain_text", "markdown", "long_paragraph", "short_blocks", "crlf"}


class Case(BaseModel):
    """One portable example with an explicitly reviewed expected output."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1)
    kind: Literal["plain_text", "markdown", "long_paragraph", "short_blocks", "crlf"]
    content_format: Literal["plain_text", "markdown"] | None
    text: str
    segments: list[str]
    review: str = Field(min_length=1)


class Corpus(BaseModel):
    """Versioned JSON schema which other language test runners can consume."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    reference_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    cases: list[Case]


def _load_corpus() -> Corpus:
    return Corpus.model_validate_json(CORPUS_PATH.read_text(encoding="utf-8"))


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Expose each static case as a separate, named failure."""
    if "case" in metafunc.fixturenames:
        cases = _load_corpus().cases
        metafunc.parametrize("case", cases, ids=[case.id for case in cases])


@pytest.mark.medium
def test_corpus_has_the_required_coverage() -> None:
    cases = _load_corpus().cases

    assert len(cases) >= 40
    assert {case.kind for case in cases} == KINDS
    assert len({case.id for case in cases}) == len(cases)


@pytest.mark.medium
def test_segmentation_matches_reviewed_corpus(case: Case) -> None:
    content_format = ContentFormat(case.content_format) if case.content_format else None

    actual = prepare_speech_segments(case.text, content_format=content_format)

    assert actual == tuple(case.segments), f"{case.id}: {case.review}"


@pytest.mark.small
@example(sizes=[1], separator=" ")
@given(
    sizes=st.lists(
        st.sampled_from([0, 1, 19, 20, 59, 60, 179, 180, 181, 219, 220, 221]),
        min_size=1,
        max_size=3,
    ),
    separator=st.sampled_from([" ", "\n\n", "\r\n\r\n", "\n \t\n"]),
)
@settings(max_examples=60, derandomize=True)
def test_plain_text_segments_preserve_every_input_word_in_order(
    sizes: list[int], separator: str
) -> None:
    paragraphs = [
        " ".join(f"p{paragraph}w{word}." for word in range(size))
        for paragraph, size in enumerate(sizes)
    ]
    text = separator.join(paragraphs)

    segments = prepare_speech_segments(text, content_format=ContentFormat.PLAIN_TEXT)

    assert " ".join(segments).split() == text.split()
