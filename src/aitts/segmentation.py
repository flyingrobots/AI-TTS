# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Application policy for turning one long submission into playable segments."""

from __future__ import annotations


def segment_text(text: str) -> tuple[str, ...]:
    """Return the ordered speech segments represented by ``text``."""
    return (text,)
