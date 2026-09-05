# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Document segmentation at the daemon-owned application boundary."""

from __future__ import annotations

import re

import pytest

from aitts.segmentation import segment_text

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
