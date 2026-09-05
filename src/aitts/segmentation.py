# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Application policy for turning one long submission into playable segments."""

from __future__ import annotations

import re

TARGET_SEGMENT_WORDS = 180
MAX_SEGMENT_WORDS = 220
_MIN_BOUNDARY_WORDS = 90
_WORD = re.compile(r"[A-Za-z0-9]+")
_MARKDOWN_HEADING = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+")
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
_SENTENCE_BREAK = re.compile(r"[.!?](?:[\]\)\"']*)\s")


def segment_text(text: str) -> tuple[str, ...]:
    """Split long text at structural boundaries without changing short clips."""
    if len(_WORD.findall(text)) <= TARGET_SEGMENT_WORDS:
        return (text,)

    segments = tuple(
        segment
        for section in _structural_sections(text)
        for segment in _bounded_segments(section)
        if segment
    )
    return segments or (text,)


def prepare_speech_segments(text: str) -> tuple[str, ...]:
    """Return the engine-neutral spoken projection of a submitted document."""
    return segment_text(text)


def _structural_sections(text: str) -> tuple[str, ...]:
    headings = list(_MARKDOWN_HEADING.finditer(text))
    if not headings:
        return (text,)
    starts = [match.start() for match in headings]
    if starts[0] > 0 and text[: starts[0]].strip():
        starts.insert(0, 0)
    ends = (*starts[1:], len(text))
    return tuple(text[start:end] for start, end in zip(starts, ends, strict=True))


def _bounded_segments(section: str) -> tuple[str, ...]:
    matches = list(_WORD.finditer(section))
    if len(matches) <= TARGET_SEGMENT_WORDS:
        stripped = section.strip()
        return (stripped,) if stripped else ()

    result: list[str] = []
    first_word = 0
    first_character = 0
    while first_word < len(matches):
        remaining = len(matches) - first_word
        if remaining <= MAX_SEGMENT_WORDS:
            result.append(section[first_character:].strip())
            break
        final_word = _choose_final_word(section, matches, first_word)
        next_character = matches[final_word].start()
        result.append(section[first_character:next_character].strip())
        first_character = next_character
        first_word = final_word
    return tuple(result)


def _choose_final_word(section: str, matches: list[re.Match[str]], first_word: int) -> int:
    target = min(first_word + TARGET_SEGMENT_WORDS, len(matches))
    maximum = min(first_word + MAX_SEGMENT_WORDS, len(matches))
    minimum = min(first_word + _MIN_BOUNDARY_WORDS, target)
    candidates = range(minimum, maximum + 1)
    paragraph = _nearest_boundary(section, matches, candidates, target, _PARAGRAPH_BREAK)
    if paragraph is not None:
        return paragraph
    sentence = _nearest_boundary(section, matches, candidates, target, _SENTENCE_BREAK)
    return sentence if sentence is not None else target


def _nearest_boundary(
    section: str,
    matches: list[re.Match[str]],
    search: range,
    target: int,
    pattern: re.Pattern[str],
) -> int | None:
    candidates = [
        index
        for index in search
        if index < len(matches)
        and pattern.search(section[matches[index - 1].end() : matches[index].start()])
    ]
    return min(candidates, key=lambda index: (abs(index - target), index)) if candidates else None
