# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Word timing for spoken clips, and its mapping back to the submitted text.

A clip's words are the maximal non-whitespace runs of the exact text an engine
was given. Each word gets a source-audio interval in milliseconds from the
clip's first sample, the clock that playback ``position_ms`` already reports.

Two sources, never conflated (``ClipTimings.source``):

- ``engine``: durations the synthesis model itself predicted for the tokens
  it rendered. Kokoro's duration predictor decides how many frames each
  phoneme lasts, so its token boundaries are the audio's boundaries, quantized
  to the model's 12.5 ms half-frame.
- ``estimated``: a proportional model for engines that report nothing. Word
  weights account for digits and symbols, which are spoken far longer than
  their character count, and clause/sentence boundaries are anchored to pauses
  detected in the actual audio. It is approximate and labelled as such.

Offsets: every character offset here is a Python string index (a Unicode code
point). :func:`utf16_converter` maps them for JavaScript-style clients.
"""

from __future__ import annotations

import bisect
import enum
import itertools
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    import numpy as np
    from numpy.typing import NDArray

TIMING_VERSION = 1

_WORD = re.compile(r"\S+")
_WORD_CHARACTER = re.compile(r"\w")
# A mark's text is searched for this far ahead of the last match. Engines skip
# nothing but punctuation, so a word is found well within it; the bound keeps
# a token the engine invented from capturing a distant later occurrence.
_MARK_SEARCH_WINDOW = 256
# Projected spoken text omits Markdown syntax (link targets, emphasis), so the
# next spoken word can lie further ahead in the source than in the projection.
_SOURCE_SEARCH_WINDOW = 8192
_SOURCE_INSERTION_WINDOW = 256
# Below this share of matched words the engine's tokens describe a different
# text than the one submitted; an estimate is more honest than a partial map.
_MINIMUM_MARK_COVERAGE = 0.5

_CLOSING_MARKS = frozenset("\"'\u2019\u201d)]}\u00bb")
_SENTENCE_END = frozenset(".!?\u2026")
_CLAUSE_END = frozenset(",;:\u2013\u2014")
_SPOKEN_SYMBOLS = frozenset("$%&@#+=\u00a3\u20ac\u00a5")
# Abbreviations whose period does not end a sentence when lowercase text, a
# digit, or (for titles) any word follows. Lowercase, with their periods.
_TITLE_ABBREVIATIONS = frozenset(
    {"mr.", "mrs.", "ms.", "dr.", "prof.", "st.", "sr.", "jr.", "rev.", "gen.", "capt.", "sgt."}
)
_ABBREVIATIONS = _TITLE_ABBREVIATIONS | frozenset(
    {
        "vs.",
        "etc.",
        "e.g.",
        "i.e.",
        "a.m.",
        "p.m.",
        "no.",
        "fig.",
        "approx.",
        "inc.",
        "ltd.",
        "co.",
        "jan.",
        "feb.",
        "mar.",
        "apr.",
        "jun.",
        "jul.",
        "aug.",
        "sep.",
        "sept.",
        "oct.",
        "nov.",
        "dec.",
    }
)
# Estimated weights: one unit per spoken letter. A digit is usually spoken as
# a word or a multi-syllable number fragment; a sentence pause outlasts a
# clause pause. The 2026-10-25 drift receipt calibrates these.
_DIGIT_WEIGHT = 3.5
_SYMBOL_WEIGHT = 4.0
_SENTENCE_GAP_WEIGHT = 6.0
_CLAUSE_GAP_WEIGHT = 3.0
# Measured 1x speaking rates are 13-24 weight units per second (Kokoro,
# Kokoro MLX, Chatterbox; 2026-10-25 receipt). Half again the fastest is
# treated as audio that cannot contain all of its text.
_NOMINAL_RATE = 18.0
_MAXIMUM_RATE = 36.0
# Pause detection over the rendered audio.
_PAUSE_WINDOW_MS = 20
_PAUSE_HOP_MS = 5
_PAUSE_THRESHOLD = 0.03
_MINIMUM_PAUSE_MS = 90
# Cost (in milliseconds of misplacement) of leaving a boundary or pause
# unanchored. A sentence boundary that has no pause near it is suspicious; a
# pause without punctuation is an ordinary breath.
_SKIP_SENTENCE_MS = 3000.0
_SKIP_CLAUSE_MS = 700.0
_SKIP_PAUSE_MS = 250.0


class TimingSource(enum.StrEnum):
    """Where a clip's word times came from."""

    ENGINE = "engine"
    ESTIMATED = "estimated"


@dataclass(frozen=True, slots=True)
class WordMark:
    """One engine token and its interval from the clip's first sample."""

    text: str
    start_ms: float
    end_ms: float


@dataclass(frozen=True, slots=True)
class WordTiming:
    """One spoken word: its audio interval and its span in the clip's text."""

    start_ms: int
    end_ms: int
    char_start: int
    char_end: int


@dataclass(frozen=True, slots=True)
class ClipTimings:
    """Every word of one clip, in order, with a declared timing source."""

    source: TimingSource
    words: tuple[WordTiming, ...]

    def encode(self) -> str:
        """Serialize for durable storage beside the clip's artifact identity."""
        return json.dumps(
            {
                "v": TIMING_VERSION,
                "source": self.source.value,
                "words": [[w.start_ms, w.end_ms, w.char_start, w.char_end] for w in self.words],
            },
            separators=(",", ":"),
        )

    @classmethod
    def decode(cls, raw: str | None) -> ClipTimings | None:
        """Parse stored timings, refusing anything malformed rather than guessing."""
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("v") != TIMING_VERSION:
                return None
            source = TimingSource(payload["source"])
            words = tuple(_decode_word(entry) for entry in payload["words"])
        except (ValueError, KeyError, TypeError):
            return None
        return cls(source, words)

    def word_index_at(self, position_ms: float) -> int | None:
        """Return the word whose start was most recently reached, if any.

        Between two words, in a pause, the earlier word stays current; before
        the first word (leading silence) there is no current word.
        """
        index = bisect.bisect_right([word.start_ms for word in self.words], position_ms) - 1
        return index if index >= 0 else None


def _decode_word(entry: Any) -> WordTiming:  # noqa: ANN401 - untrusted stored JSON
    if (
        not isinstance(entry, list)
        or len(entry) != 4  # noqa: PLR2004 - fixed wire tuple
        or not all(type(value) is int and value >= 0 for value in entry)
        or entry[1] < entry[0]
        or entry[3] < entry[2]
    ):
        msg = "malformed word timing"
        raise ValueError(msg)
    return WordTiming(*entry)


def word_spans(text: str) -> list[tuple[int, int]]:
    """Return the ``(start, end)`` of every maximal non-whitespace run."""
    return [match.span() for match in _WORD.finditer(text)]


def timings_from_marks(
    text: str, marks: Sequence[WordMark], *, partial: bool = False
) -> ClipTimings | None:
    """Attach engine token times to the words of ``text``.

    Each mark is located in ``text`` after the previous match; a word takes
    the earliest start and latest end of the marks inside it. Punctuation-only
    marks carry no word. Words the engine reported nothing for (a lone dash, a
    symbol it skipped) are interpolated between their timed neighbours.
    Returns ``None`` when too few words matched for the marks to be trusted.

    ``partial`` describes a clip still being generated: only the prefix up to
    the last timed word is returned, and coverage is not judged yet.
    """
    spans = word_spans(text)
    if not spans:
        return None
    starts, ends = _mark_intervals(text, spans, marks)
    if partial:
        if all(start is None for start in starts):
            return None
        return ClipTimings(TimingSource.ENGINE, _complete(spans, starts, ends))
    speakable = [i for i, (s, e) in enumerate(spans) if _WORD_CHARACTER.search(text[s:e])]
    matched = [i for i in speakable if starts[i] is not None]
    if not speakable or len(matched) < _MINIMUM_MARK_COVERAGE * len(speakable):
        return None
    return ClipTimings(TimingSource.ENGINE, _complete(spans, starts, ends))


def _mark_intervals(
    text: str, spans: Sequence[tuple[int, int]], marks: Sequence[WordMark]
) -> tuple[list[float | None], list[float | None]]:
    """Locate marks in order and widen each containing word to cover them."""
    starts: list[float | None] = [None] * len(spans)
    ends: list[float | None] = [None] * len(spans)
    cursor = 0
    word = 0
    for mark in marks:
        token = mark.text.strip()
        if not token or not _WORD_CHARACTER.search(token):
            continue
        at = text.find(token, cursor, cursor + _MARK_SEARCH_WINDOW + len(token))
        if at < 0:
            continue
        cursor = at + len(token)
        while word < len(spans) and spans[word][1] <= at:
            word += 1
        if word == len(spans):
            break
        if spans[word][0] <= at:
            current_start = starts[word]
            current_end = ends[word]
            starts[word] = (
                mark.start_ms if current_start is None else min(current_start, mark.start_ms)
            )
            ends[word] = mark.end_ms if current_end is None else max(current_end, mark.end_ms)
    return starts, ends


def _complete(
    spans: list[tuple[int, int]],
    starts: list[float | None],
    ends: list[float | None],
) -> tuple[WordTiming, ...]:
    """Fill untimed runs evenly between timed neighbours; keep times monotonic.

    Words after the last timed word are not returned: nothing says they were
    spoken (a truncated render, or a clip still generating), so they stay
    untimed rather than being stamped at the clip's end.
    """
    timed = [i for i, start in enumerate(starts) if start is not None]
    first, last = timed[0], timed[-1]
    spans, starts, ends = spans[: last + 1], starts[: last + 1], ends[: last + 1]
    result_starts = list(starts)
    result_ends = list(ends)
    first_start = starts[first]
    assert first_start is not None  # noqa: S101 - selected from timed words
    for i in range(first):
        result_starts[i] = result_ends[i] = first_start
    for left, right in itertools.pairwise(timed):
        gap = right - left - 1
        if not gap:
            continue
        low = ends[left]
        high = starts[right]
        assert low is not None  # noqa: S101 - timed neighbour
        assert high is not None  # noqa: S101 - timed neighbour
        high = max(high, low)
        step = (high - low) / gap
        for offset in range(gap):
            result_starts[left + 1 + offset] = low + offset * step
            result_ends[left + 1 + offset] = low + (offset + 1) * step
    words: list[WordTiming] = []
    floor = 0
    for (char_start, char_end), start, end in zip(spans, result_starts, result_ends, strict=True):
        assert start is not None  # noqa: S101 - filled above
        assert end is not None  # noqa: S101 - filled above
        begin = max(floor, round(start))
        words.append(WordTiming(begin, max(begin, round(end)), char_start, char_end))
        floor = begin
    return tuple(words)


def _terminal(word: str) -> str | None:
    for character in reversed(word):
        if character not in _CLOSING_MARKS:
            return character
    return None


def _is_abbreviation(word: str, following: str | None) -> bool:
    core = word.lower().strip("\"'([{\u2018\u201c")
    while core and core[-1] in _CLOSING_MARKS:
        core = core[:-1]
    single_initial = len(core) == 2 and core[0].isalpha() and core[1] == "."  # noqa: PLR2004
    if core not in _ABBREVIATIONS and not single_initial:
        return False
    if following is None:
        return False
    if core in _TITLE_ABBREVIATIONS or single_initial:
        return True
    return not following[:1].isupper()


def boundary_after(text: str, spans: Sequence[tuple[int, int]], index: int) -> str | None:
    """Classify the boundary after word ``index``: ``"sentence"``, ``"clause"`` or None.

    A paragraph break always ends a sentence. A period on a known abbreviation
    does not, when what follows shows the sentence continues.
    """
    start, end = spans[index]
    word = text[start:end]
    following = None
    if index + 1 < len(spans):
        gap = text[end : spans[index + 1][0]]
        if gap.count("\n") >= 2:  # noqa: PLR2004 - a blank line separates paragraphs
            return "sentence"
        following = text[spans[index + 1][0] : spans[index + 1][1]]
    mark = _terminal(word)
    if mark in _SENTENCE_END:
        if mark == "." and _is_abbreviation(word, following):
            return None
        return "sentence"
    if mark in _CLAUSE_END:
        return "clause"
    return None


def sentence_word_ranges(text: str) -> list[tuple[int, int]]:
    """Return inclusive ``(first_word, last_word)`` ranges of each sentence."""
    spans = word_spans(text)
    ranges: list[tuple[int, int]] = []
    first = 0
    for index in range(len(spans)):
        if index == len(spans) - 1 or boundary_after(text, spans, index) == "sentence":
            ranges.append((first, index))
            first = index + 1
    return ranges


def spoken_weight(word: str) -> float:
    """Estimate how long a written word takes to say, in letter units."""
    letters = sum(character.isalpha() for character in word)
    digits = sum(character.isdigit() for character in word)
    symbols = sum(character in _SPOKEN_SYMBOLS for character in word)
    return max(1.0, letters + _DIGIT_WEIGHT * digits + _SYMBOL_WEIGHT * symbols)


def detect_pauses(
    samples: NDArray[np.float32], sample_rate: int, *, minimum_ms: float = _MINIMUM_PAUSE_MS
) -> list[tuple[float, float]]:
    """Return ``(start_ms, end_ms)`` of quiet runs lasting at least ``minimum_ms``.

    Quiet is a 20 ms window whose RMS falls below 3% of the clip's 95th
    percentile window RMS, sampled every 5 ms: relative to the clip, so it
    holds across engine loudness.
    """
    import numpy as np  # noqa: PLC0415 - keep numpy off module import

    audio = np.asarray(samples, dtype=np.float64).reshape(-1)
    hop = max(1, int(sample_rate * _PAUSE_HOP_MS / 1000))
    window = max(1, int(sample_rate * _PAUSE_WINDOW_MS / 1000))
    if len(audio) < window:
        return []
    energy = np.concatenate(([0.0], np.cumsum(audio * audio)))
    starts = np.arange(0, len(audio) - window + 1, hop)
    rms = np.sqrt((energy[starts + window] - energy[starts]) / window)
    reference = float(np.percentile(rms, 95))
    if reference <= 0:
        return [(0.0, len(audio) / sample_rate * 1000)]
    quiet = rms < reference * _PAUSE_THRESHOLD
    pauses: list[tuple[float, float]] = []
    run_start: int | None = None
    for index, is_quiet in enumerate(quiet.tolist()):
        if is_quiet and run_start is None:
            run_start = index
        elif not is_quiet and run_start is not None:
            if (index - run_start) * _PAUSE_HOP_MS >= minimum_ms:
                pauses.append((run_start * _PAUSE_HOP_MS, index * _PAUSE_HOP_MS + 0.0))
            run_start = None
    if run_start is not None:
        pauses.append((run_start * _PAUSE_HOP_MS, len(audio) / sample_rate * 1000))
    return pauses


def estimate_timings(
    text: str,
    duration_ms: float,
    pauses: Sequence[tuple[float, float]] = (),
    *,
    speed: float = 1.0,
) -> ClipTimings | None:
    """Estimate word times from text alone, anchored on the audio's pauses.

    Leading and trailing pauses bound the speech. Interior pauses are matched
    in order to sentence and clause boundaries by a monotone alignment that
    minimizes total misplacement; each matched boundary then ends its word at
    the pause's start and begins the next word at the pause's end. Between
    anchors, time is shared by spoken weight.

    Audio far too short for its text (an apparent rate above
    ``_MAXIMUM_RATE`` weight units per second at generation ``speed``) did
    not say all of it. Only the prefix that fits at ``_NOMINAL_RATE`` is
    timed; the rest is left untimed instead of being squeezed in.
    """
    spans = word_spans(text)
    if not spans or duration_ms <= 0:
        return None
    speech_start, speech_end, interior = _speech_bounds(duration_ms, pauses)
    spoken = _spoken_word_count(text, spans, (speech_end - speech_start) / 1000, speed)
    if spoken == 0:
        return None
    spans = spans[:spoken]
    layout = _SpokenLayout.of(text, spans)
    # Sentences first, against the whole clip; then clauses inside each
    # anchored sentence span, where expected times have drifted far less.
    pieces = layout.split((0, len(spans) - 1, speech_start, speech_end), "sentence", interior)
    pieces = [clause for piece in pieces for clause in layout.split(piece, "clause", interior)]
    starts: list[float] = [0.0] * len(spans)
    ends: list[float] = [0.0] * len(spans)
    for first, last, begin, finish in pieces:
        units = [layout.units(i, last) for i in range(first, last + 1)]
        scale = max(finish - begin, 0.0) / sum(units)
        clock = begin
        for i, unit in zip(range(first, last + 1), units, strict=True):
            starts[i] = clock
            ends[i] = clock + layout.weights[i] * scale
            clock += unit * scale
    timed = tuple(
        WordTiming(round(start), max(round(start), round(end)), char_start, char_end)
        for (char_start, char_end), start, end in zip(spans, starts, ends, strict=True)
    )
    return ClipTimings(TimingSource.ESTIMATED, timed)


def _speech_bounds(
    duration_ms: float, pauses: Sequence[tuple[float, float]]
) -> tuple[float, float, list[tuple[float, float]]]:
    """Split pauses into leading/trailing silence bounds and interior pauses."""
    speech_start = 0.0
    speech_end = float(duration_ms)
    interior: list[tuple[float, float]] = []
    for start, end in pauses:
        if start <= 0:
            speech_start = max(speech_start, end)
        elif end >= duration_ms - _PAUSE_HOP_MS:
            speech_end = min(speech_end, start)
        else:
            interior.append((start, end))
    if speech_end <= speech_start:
        return 0.0, float(duration_ms), interior
    return speech_start, speech_end, interior


def _spoken_word_count(
    text: str, spans: Sequence[tuple[int, int]], seconds: float, speed: float
) -> int:
    """How many leading words the audio can plausibly contain."""
    layout = _SpokenLayout.of(text, spans)
    rate = max(speed, 0.1)
    if sum(layout.weights) + sum(layout.gaps) <= _MAXIMUM_RATE * rate * seconds:
        return len(spans)
    budget = _NOMINAL_RATE * rate * seconds
    spoken = 0
    while spoken < len(spans) and budget > 0:
        budget -= layout.units(spoken, len(spans) - 1)
        spoken += 1
    return spoken


# (first word, last word, start ms, end ms) of one contiguous run of speech.
_Piece = tuple[int, int, float, float]
_Pause = tuple[float, float]


@dataclass(frozen=True, slots=True)
class _SpokenLayout:
    """Word weights and the boundary kind and pause weight after each word."""

    weights: tuple[float, ...]
    kinds: tuple[str | None, ...]
    gaps: tuple[float, ...]

    @classmethod
    def of(cls, text: str, spans: Sequence[tuple[int, int]]) -> _SpokenLayout:
        kinds = tuple(boundary_after(text, spans, i) for i in range(len(spans) - 1))
        return cls(
            weights=tuple(spoken_weight(text[start:end]) for start, end in spans),
            kinds=kinds,
            gaps=tuple(
                _SENTENCE_GAP_WEIGHT if kind == "sentence" else _CLAUSE_GAP_WEIGHT if kind else 0.0
                for kind in kinds
            ),
        )

    def units(self, index: int, last: int) -> float:
        """Weight of a word plus the pause after it, unless it ends its piece."""
        return self.weights[index] + (self.gaps[index] if index < last else 0.0)

    def split(self, piece: _Piece, kind: str, pauses: Sequence[_Pause]) -> list[_Piece]:
        """Split a piece at the boundaries of ``kind`` that anchor to its pauses."""
        first, last, begin, finish = piece
        inside = [(start, end) for start, end in pauses if begin < start and end < finish]
        candidates = [i for i in range(first, last) if self.kinds[i] == kind]
        if not candidates or not inside:
            return [piece]
        total = sum(self.units(i, last) for i in range(first, last + 1))
        expected: list[float] = []
        clock = 0.0
        for i in range(first, last):
            clock += self.weights[i]
            if self.kinds[i] == kind:
                expected.append(begin + (clock + self.gaps[i] / 2) / total * (finish - begin))
            clock += self.gaps[i]
        skip = _SKIP_SENTENCE_MS if kind == "sentence" else _SKIP_CLAUSE_MS
        pieces: list[_Piece] = []
        word, start = first, begin
        for boundary, pause in _monotone_match(expected, [(a + b) / 2 for a, b in inside], skip):
            pieces.append((word, candidates[boundary], start, inside[pause][0]))
            word, start = candidates[boundary] + 1, inside[pause][1]
        pieces.append((word, last, start, finish))
        return pieces


def _monotone_match(
    expected: Sequence[float], observed: Sequence[float], skip_expected: float
) -> list[tuple[int, int]]:
    """Order-preserving matching of expected to observed times at least total cost.

    A match costs its distance in milliseconds; leaving an expected time
    unmatched costs ``skip_expected`` and leaving an observation unmatched
    costs ``_SKIP_PAUSE_MS``. Returns matched ``(expected, observed)`` indexes.
    """
    rows, columns = len(expected), len(observed)
    infinity = float("inf")
    cost = [[infinity] * (columns + 1) for _ in range(rows + 1)]
    back: list[list[tuple[int, int]]] = [[(0, 0)] * (columns + 1) for _ in range(rows + 1)]
    cost[0][0] = 0.0
    for row in range(rows + 1):
        for column in range(columns + 1):
            here = cost[row][column]
            if here == infinity:
                continue
            steps = []
            if row < rows:
                steps.append((row + 1, column, skip_expected))
            if column < columns:
                steps.append((row, column + 1, _SKIP_PAUSE_MS))
            if row < rows and column < columns:
                steps.append((row + 1, column + 1, abs(expected[row] - observed[column])))
            for to_row, to_column, step in steps:
                if here + step < cost[to_row][to_column]:
                    cost[to_row][to_column] = here + step
                    back[to_row][to_column] = (row, column)
    return _matched_path(back, rows, columns)


def _matched_path(
    back: Sequence[Sequence[tuple[int, int]]], rows: int, columns: int
) -> list[tuple[int, int]]:
    """Walk a cost table's back-pointers and keep the diagonal (matched) steps."""
    matches: list[tuple[int, int]] = []
    row, column = rows, columns
    while row or column:
        previous_row, previous_column = back[row][column]
        if (previous_row, previous_column) == (row - 1, column - 1):
            matches.append((previous_row, previous_column))
        row, column = previous_row, previous_column
    matches.reverse()
    return matches


def align_spoken_words(
    source: str, spoken: str, cursor: int = 0
) -> tuple[list[tuple[int, int] | None], int]:
    """Locate each word of ``spoken`` in ``source``, in order, from ``cursor``.

    Plain-text segments are exact substrings of their source, so every word
    is found. A Markdown projection drops syntax and may append terminal
    punctuation or list numbers; a word that is not found whole is retried
    without its edge punctuation nearby, and otherwise maps to ``None``
    without moving the cursor. Returns the spans and the advanced cursor.
    """
    located: list[tuple[int, int] | None] = []
    for start, end in word_spans(spoken):
        word = spoken[start:end]
        at = source.find(word, cursor, cursor + _SOURCE_SEARCH_WINDOW + len(word))
        length = len(word)
        if at < 0:
            core = word.strip("\"'()[]{}*_`.,;:!?\u2018\u2019\u201c\u201d")
            at = (
                source.find(core, cursor, cursor + _SOURCE_INSERTION_WINDOW + len(core))
                if core
                else -1
            )
            length = len(core)
        if at < 0:
            located.append(None)
            continue
        located.append((at, at + length))
        cursor = at + length
    return located, cursor


def utf16_converter(text: str) -> Callable[[int], int]:
    """Return a code-point-offset to UTF-16-offset function for ``text``."""
    if all(ord(character) < 0x10000 for character in text):  # noqa: PLR2004 - BMP bound
        return lambda offset: offset
    prefix = [0]
    for character in text:
        prefix.append(prefix[-1] + (2 if ord(character) >= 0x10000 else 1))  # noqa: PLR2004
    return lambda offset: prefix[offset]
