# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Document segmentation at the daemon-owned application boundary."""

from __future__ import annotations

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aitts.model import ContentFormat
from aitts.segmentation import prepare_speech_segments, segment_text

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "composite-document contract in architecture section 8 and PROMPTS.md prompt 7"
    ),
]


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", text)


def test_short_text_retains_single_clip_identity() -> None:
    text = "  A short clip should remain exactly as its caller submitted it.\n"

    assert segment_text(text) == (text,)


def test_markdown_document_becomes_lossless_bounded_segment_plan() -> None:
    opening = " ".join(f"opening{i}." for i in range(260))
    details = " ".join(f"detail{i}." for i in range(260))
    text = f"# Opening\n\n{opening}\n\n## Details\n\n{details}"

    segments = segment_text(text)
    observed = {
        "segment_count": len(segments),
        "source_words": words(text),
        "segment_words": [word for segment in segments for word in words(segment)],
        "largest_segment_words": max(len(words(segment)) for segment in segments),
        "empty_segments": sum(not segment.strip() for segment in segments),
        "details_heading_attached": any(
            segment.startswith("## Details") and "detail0" in segment for segment in segments
        ),
    }

    assert observed == {
        "segment_count": 4,
        "source_words": words(text),
        "segment_words": words(text),
        "largest_segment_words": 180,
        "empty_segments": 0,
        "details_heading_attached": True,
    }


def test_plain_text_speech_plan_retains_exact_clip_identity() -> None:
    text = "  Ordinary prose stays exactly as submitted.\n"

    assert prepare_speech_segments(text, content_format=ContentFormat.PLAIN_TEXT) == (text,)


def test_long_plain_text_is_chunked_without_markdown_projection() -> None:
    text = "# Not a heading\n\nSay **stars** literally. " + " ".join(
        f"word{index}." for index in range(300)
    )

    segments = prepare_speech_segments(text, content_format=ContentFormat.PLAIN_TEXT)

    assert {
        "segment_count": len(segments),
        "literal_prefix_preserved": segments[0].startswith(
            "# Not a heading\n\nSay **stars** literally. word0."
        ),
        "source_words": words(text),
        "segment_words": [word for segment in segments for word in words(segment)],
        "largest_segment_words": max(len(words(segment)) for segment in segments),
    } == {
        "segment_count": 2,
        "literal_prefix_preserved": True,
        "source_words": words(text),
        "segment_words": words(text),
        "largest_segment_words": 180,
    }


def test_markdown_speech_plan_removes_syntax_and_adds_prosody_hints() -> None:
    text = """# Revenue **Review**

Read [**SalesOS**](https://example.test) and `OpportunityPort`. ![Pipeline diagram](diagram.png)

> **Important:** no raw markup.

- First item
- Second item

| Metric | Value |
| --- | ---: |
| Win rate | 42% |

```python
print("ready")
```
"""

    assert prepare_speech_segments(text, content_format=ContentFormat.MARKDOWN) == (
        """Revenue Review.

Read SalesOS and OpportunityPort. Pipeline diagram

Important: no raw markup.

First item.
Second item.

Metric. Value.
Win rate. 42%.

print("ready")""",
    )


def test_yaml_front_matter_is_metadata_not_spoken_content() -> None:
    text = """---
title: "Internal document title"
date: 2026-09-04
visibility: private
---

# Spoken title

This body should be heard.
"""

    assert prepare_speech_segments(text, content_format=ContentFormat.MARKDOWN) == (
        "Spoken title.\n\nThis body should be heard.",
    )


def test_markdown_speech_plan_strips_loose_formatting_asterisks() -> None:
    text = "Here is * bold * text and ** spaced ** emphasis."

    assert prepare_speech_segments(text, content_format=ContentFormat.MARKDOWN) == (
        "Here is bold text and spaced emphasis.",
    )


@pytest.mark.parametrize(
    ("text", "spoken"),
    [("2 * 3 * 4", "2 * 3 * 4"), ("Use `* literal *` here.", "Use * literal * here.")],
)
@pytest.mark.oracle(
    "Markdown speech preserves arithmetic operators and literal inline-code content"
)
def test_loose_emphasis_cleanup_preserves_literal_asterisks(text: str, spoken: str) -> None:
    assert prepare_speech_segments(text, content_format=ContentFormat.MARKDOWN) == (spoken,)


@pytest.mark.oracle("loose prose emphasis is removed across line breaks after front matter")
def test_multiline_loose_emphasis_is_removed_after_front_matter() -> None:
    assert prepare_speech_segments(
        "---\ntitle: ignored\n---\n** first\nsecond **", content_format=ContentFormat.MARKDOWN
    ) == ("first\nsecond",)


@pytest.mark.parametrize("text", ["** spaced **.", "** spaced ** ."])
@pytest.mark.oracle("loose prose emphasis accepts adjacent punctuation without introducing a gap")
def test_loose_emphasis_ends_at_punctuation(text: str) -> None:
    assert prepare_speech_segments(text, content_format=ContentFormat.MARKDOWN) == ("spaced.",)


@pytest.mark.parametrize("sizes", [(50, 50), (34, 33, 33)])
@pytest.mark.parametrize("content_format", [ContentFormat.PLAIN_TEXT, ContentFormat.MARKDOWN, None])
def test_hundred_word_paragraphs_are_independently_navigable(
    sizes: tuple[int, ...], content_format: ContentFormat | None
) -> None:
    paragraphs = [
        " ".join(f"p{paragraph}word{word}" for word in range(size))
        for paragraph, size in enumerate(sizes)
    ]
    source = "\n\n".join(paragraphs)
    assert prepare_speech_segments(source, content_format=content_format) == tuple(paragraphs)


@pytest.mark.parametrize("separator", ["\n\n", "\r\n\r\n", "\n \t\n"])
def test_paragraph_threshold_and_short_clip_identity(separator: str) -> None:
    first = " ".join(f"first{index}" for index in range(30))
    second = " ".join(f"second{index}" for index in range(30))
    assert segment_text(first + separator + second) == (first, second)
    shorter = first + separator + " ".join(second.split()[:-1])
    assert segment_text(shorter) == (shorter,)


def test_tiny_leading_and_trailing_blocks_attach_to_substantial_paragraphs() -> None:
    first = " ".join(f"first{index}" for index in range(40))
    second = " ".join(f"second{index}" for index in range(40))
    source = f"Introduction\n\n{first}\n\n{second}\n\nThank you."
    assert segment_text(source) == (f"Introduction\n\n{first}", f"{second}\n\nThank you.")


def test_markdown_structural_blocks_and_heading_stay_attached() -> None:
    first = " ".join(f"first{index}" for index in range(40))
    second = " ".join(f"second{index}" for index in range(40))
    source = f"# **Overview**\n\n> {first}\n\n{second}"
    assert prepare_speech_segments(source, content_format=ContentFormat.MARKDOWN) == (
        f"Overview.\n\n{first}",
        second,
    )


@given(st.lists(st.integers(min_value=1, max_value=400), min_size=1, max_size=6))
@settings(max_examples=60, derandomize=True)
def test_paragraph_plans_preserve_tokens_and_existing_size_bound(sizes: list[int]) -> None:
    paragraphs = [
        " ".join(f"p{paragraph}word{word}!" for word in range(size))
        for paragraph, size in enumerate(sizes)
    ]
    source = "\n\n".join(paragraphs)
    segments = segment_text(source)
    assert [token for segment in segments for token in segment.split()] == source.split()
    assert all(segment.strip() for segment in segments)
    assert all(len(words(segment)) <= 220 for segment in segments)
    if sum(sizes) < 60:
        assert segments == (source,)


def test_fifteen_word_sentence_stays_atomic() -> None:
    sentence = " ".join(f"word{index}" for index in range(15)) + "."
    assert segment_text(sentence) == (sentence,)
