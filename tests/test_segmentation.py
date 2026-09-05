# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Document segmentation at the daemon-owned application boundary."""

from __future__ import annotations

import re

import pytest

from aitts.model import ContentFormat
from aitts.segmentation import prepare_speech_segments, segment_text

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "approved composite-document contract in docs/design/architecture.md section 8"
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
