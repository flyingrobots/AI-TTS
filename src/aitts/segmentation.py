# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Application policy for turning one long submission into playable segments."""

from __future__ import annotations

import re
from dataclasses import dataclass

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

TARGET_SEGMENT_WORDS = 180
MAX_SEGMENT_WORDS = 220
_MIN_BOUNDARY_WORDS = 90
_WORD = re.compile(r"[A-Za-z0-9]+")
_MARKDOWN_HEADING = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+")
_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
_SENTENCE_BREAK = re.compile(r"[.!?](?:[\]\)\"']*)\s")
_PLAIN_MARKDOWN_NODES = frozenset({"root", "paragraph", "inline", "text", "softbreak"})
_INLINE_BREAK_NODES = frozenset({"softbreak", "hardbreak"})
_CODE_NODES = frozenset({"code_block", "fence"})
_TABLE_CELL_NODES = frozenset({"th", "td"})
_TERMINAL_PUNCTUATION = (".", "!", "?", ":", ";")
_TASK_MARKER = re.compile(r"^\[[ xX]\][ \t]+")


@dataclass(frozen=True, slots=True)
class _SpokenBlock:
    text: str
    starts_section: bool = False


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
    body = _without_front_matter(text)
    tree = SyntaxTreeNode(MarkdownIt("gfm-like", {"html": False, "linkify": False}).parse(body))
    if _is_plain_text_tree(tree):
        return segment_text(body)

    sections: list[list[str]] = []
    current: list[str] = []
    for block in _render_blocks(tree):
        if block.starts_section and current:
            sections.append(current)
            current = []
        if block.text:
            current.append(block.text)
    if current:
        sections.append(current)

    return tuple(
        segment
        for section in sections
        for segment in segment_text("\n\n".join(section))
        if segment.strip()
    )


def _without_front_matter(text: str) -> str:
    """Remove one leading YAML metadata fence before Markdown parsing."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in {"---", "..."}:
            return "".join(lines[index + 1 :]).lstrip("\r\n")
    return text


def _is_plain_text_tree(node: SyntaxTreeNode) -> bool:
    return all(
        child.type in _PLAIN_MARKDOWN_NODES and _is_plain_text_tree(child)
        for child in node.children
    )


def _render_blocks(node: SyntaxTreeNode) -> tuple[_SpokenBlock, ...]:
    rendered: list[_SpokenBlock] = []
    for child in node.children:
        if child.type == "heading":
            rendered.append(
                _SpokenBlock(
                    _with_terminal_punctuation(_inline_text(child)),
                    starts_section=True,
                )
            )
        elif child.type == "paragraph":
            rendered.append(_SpokenBlock(_inline_text(child)))
        elif child.type in _CODE_NODES:
            rendered.append(_SpokenBlock(child.content.strip()))
        elif child.type in {"bullet_list", "ordered_list"}:
            rendered.append(_SpokenBlock(_render_list(child)))
        elif child.type == "table":
            rendered.append(_SpokenBlock(_render_table(child)))
        elif child.type != "hr":
            rendered.extend(_render_blocks(child))
    return tuple(rendered)


def _render_list(node: SyntaxTreeNode) -> str:
    start = int(node.attrs.get("start", 1)) if node.type == "ordered_list" else None
    items: list[str] = []
    for offset, item in enumerate(node.children):
        content = " ".join(block.text for block in _render_blocks(item) if block.text)
        content = _TASK_MARKER.sub("", content)
        if start is not None:
            content = f"{start + offset}. {content}"
        items.append(_with_terminal_punctuation(content))
    return "\n".join(items)


def _render_table(node: SyntaxTreeNode) -> str:
    rows: list[str] = []
    for row in _nodes_of_type(node, "tr"):
        cells = [_inline_text(cell) for cell in row.children if cell.type in _TABLE_CELL_NODES]
        rows.append(_with_terminal_punctuation(". ".join(cell for cell in cells if cell)))
    return "\n".join(row for row in rows if row)


def _nodes_of_type(node: SyntaxTreeNode, node_type: str) -> tuple[SyntaxTreeNode, ...]:
    found: list[SyntaxTreeNode] = []
    for child in node.children:
        if child.type == node_type:
            found.append(child)
        else:
            found.extend(_nodes_of_type(child, node_type))
    return tuple(found)


def _inline_text(node: SyntaxTreeNode) -> str:
    pieces: list[str] = []
    for child in node.children:
        if child.type in _INLINE_BREAK_NODES:
            pieces.append(" ")
        elif child.children:
            pieces.append(_inline_text(child))
        elif child.type != "html_inline":
            pieces.append(child.content)
    return re.sub(r"\s+", " ", "".join(pieces)).strip()


def _with_terminal_punctuation(text: str) -> str:
    return text if not text or text.endswith(_TERMINAL_PUNCTUATION) else f"{text}."


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
