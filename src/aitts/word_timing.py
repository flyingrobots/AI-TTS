# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Daemon-side word timing: what is being said, where in the submitted text.

The synthesis pool records each clip's timings under its artifact identity
(``Store.save_timings``). While a streaming clip is still generating, its
engine marks so far live in :class:`LiveTimings`, so a listener can follow a
clip that started playing before it finished rendering.

Offsets in responses and events index the utterance's exact submitted
``text`` (Python code points by default, UTF-16 code units on request). A
document's segments are located in that text by :func:`align_spoken_words`;
Markdown syntax the projection did not speak simply has no word on it.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aitts.segmentation import front_matter_length
from aitts.timing import (
    TIMING_VERSION,
    ClipTimings,
    WordMark,
    align_spoken_words,
    sentence_word_ranges,
    timings_from_marks,
    utf16_converter,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from aitts.model import Utterance, UtteranceSegment
    from aitts.store import Store

OFFSET_UNITS = ("codepoint", "utf16")
_MAP_CACHE_SIZE = 8

ClipKey = tuple[str, int | None]
Span = tuple[int, int]


class LiveTimings:
    """Engine marks of clips whose generation has not finished, by clip."""

    def __init__(self) -> None:
        """Create an empty registry shared by synthesis workers and readers."""
        self._lock = threading.Lock()
        self._clips: dict[ClipKey, tuple[str, list[WordMark]]] = {}

    def begin(self, key: ClipKey, text: str) -> None:
        """Start collecting marks for one clip's exact engine text."""
        with self._lock:
            self._clips[key] = (text, [])

    def extend(self, key: ClipKey, marks: Sequence[WordMark]) -> None:
        """Append marks reported by a producer thread."""
        with self._lock:
            clip = self._clips.get(key)
            if clip is not None:
                clip[1].extend(marks)

    def snapshot(self, key: ClipKey) -> ClipTimings | None:
        """Return the timed prefix of a clip still being generated."""
        with self._lock:
            clip = self._clips.get(key)
            if clip is None:
                return None
            text, marks = clip[0], tuple(clip[1])
        return timings_from_marks(text, marks, partial=True) if marks else None

    def discard(self, key: ClipKey) -> None:
        """Forget a clip once its final timings are durable, or it failed."""
        with self._lock:
            self._clips.pop(key, None)


@dataclass(frozen=True, slots=True)
class _SourceMap:
    """Every segment word's span in the submitted text, plus offset conversion."""

    words: tuple[tuple[Span | None, ...], ...]
    # Per clip: inclusive (first word, last word) of each sentence.
    sentences: tuple[tuple[tuple[int, int], ...], ...]
    convert: Callable[[int], int]
    utf16_length: int
    length: int


class WordTimingService:
    """Answer ``timings`` requests and build ``playback_position`` events."""

    def __init__(self, store: Store, live: LiveTimings) -> None:
        """Read durable timings from ``store`` and in-flight marks from ``live``."""
        self._store = store
        self._live = live
        self._maps: OrderedDict[tuple[str, int], _SourceMap] = OrderedDict()
        # Decoded stored timings, reused while the stored value is unchanged.
        self._decoded: OrderedDict[str, tuple[str, ClipTimings | None]] = OrderedDict()

    # -- lookup ------------------------------------------------------------

    def clip_timings(
        self, utterance: Utterance, segment: UtteranceSegment | None
    ) -> tuple[ClipTimings | None, bool]:
        """Return a clip's timings and whether they are final."""
        if segment is None:
            artifact = utterance.generation_artifact_id or utterance.id
            key: ClipKey = (utterance.id, None)
        else:
            artifact = segment.generation_artifact_id or segment.artifact_id
            key = (utterance.id, segment.index)
        stored = self._decode(artifact, self._store.timings(artifact))
        if stored is not None:
            return stored, True
        return self._live.snapshot(key), False

    def _decode(self, artifact: str, raw: str | None) -> ClipTimings | None:
        if raw is None:
            return None
        cached = self._decoded.get(artifact)
        if cached is not None and cached[0] == raw:
            self._decoded.move_to_end(artifact)
            return cached[1]
        decoded = ClipTimings.decode(raw)
        self._decoded[artifact] = (raw, decoded)
        if len(self._decoded) > _MAP_CACHE_SIZE:
            self._decoded.popitem(last=False)
        return decoded

    def _source_map(self, utterance: Utterance, texts: Sequence[str]) -> _SourceMap:
        cache_key = (utterance.id, len(texts))
        cached = self._maps.get(cache_key)
        if cached is not None:
            self._maps.move_to_end(cache_key)
            return cached
        source = utterance.text
        cursor = 0
        # A Markdown projection drops leading front matter; plain text keeps it.
        if texts and not texts[0].lstrip().startswith("---"):
            cursor = front_matter_length(source)
        located: list[tuple[Span | None, ...]] = []
        for text in texts:
            spans, cursor = align_spoken_words(source, text, cursor)
            located.append(tuple(spans))
        convert = utf16_converter(source)
        sentences = tuple(tuple(sentence_word_ranges(text)) for text in texts)
        mapped = _SourceMap(tuple(located), sentences, convert, convert(len(source)), len(source))
        self._maps[cache_key] = mapped
        if len(self._maps) > _MAP_CACHE_SIZE:
            self._maps.popitem(last=False)
        return mapped

    def _clips(self, utterance: Utterance) -> tuple[list[UtteranceSegment | None], list[str]]:
        segments = self._store.segments(utterance.id)
        if not segments:
            return [None], [utterance.text]
        return list(segments), [segment.text for segment in segments]

    # -- timings op --------------------------------------------------------

    def describe(
        self, utterance: Utterance, *, segment_index: int | None, offset_unit: str
    ) -> dict[str, Any]:
        """Describe every (or one) clip's words, sentences and times."""
        clips, texts = self._clips(utterance)
        source = self._source_map(utterance, texts)
        unit = _converter(source, offset_unit)
        described = []
        for index, segment in enumerate(clips):
            if segment_index is not None and index != segment_index:
                continue
            timings, complete = self.clip_timings(utterance, segment)
            described.append(
                self._describe_clip(
                    index,
                    segment,
                    utterance=utterance,
                    located=source.words[index],
                    sentences=source.sentences[index],
                    timings=timings,
                    complete=complete,
                    unit=unit,
                )
            )
        return {
            "ok": True,
            "id": utterance.id,
            "timing_version": TIMING_VERSION,
            "offset_unit": offset_unit,
            "text_length": source.utf16_length if offset_unit == "utf16" else source.length,
            "segment_count": len(clips),
            "segments": described,
        }

    @staticmethod
    def _describe_clip(  # noqa: PLR0913 - one clip, all of its projections
        index: int,
        segment: UtteranceSegment | None,
        *,
        utterance: Utterance,
        located: Sequence[Span | None],
        sentences: Sequence[tuple[int, int]],
        timings: ClipTimings | None,
        complete: bool,
        unit: Callable[[Span | None], tuple[int | None, int | None]],
    ) -> dict[str, Any]:
        times = list(timings.words) if timings is not None else []
        words = []
        for word, span in enumerate(located):
            start, end = unit(span)
            timed = times[word] if word < len(times) else None
            words.append(
                [
                    None if timed is None else timed.start_ms,
                    None if timed is None else timed.end_ms,
                    start,
                    end,
                ]
            )
        mapped = [span for span in located if span is not None]
        bounds = unit((mapped[0][0], mapped[-1][1])) if mapped else (None, None)
        state = segment.state if segment is not None else utterance.state
        duration = segment.duration_ms if segment is not None else utterance.duration_ms
        return {
            "index": index,
            "state": state.value,
            "duration_ms": duration,
            "timing": None if timings is None else timings.source.value,
            "complete": complete and timings is not None,
            "source_start": bounds[0],
            "source_end": bounds[1],
            "words": words,
            "sentences": [
                [*_sentence_span(located, first, last, unit), first, last]
                for first, last in sentences
            ],
        }

    # -- playback_position event --------------------------------------------

    def position(  # noqa: PLR0913 - one observation of the controller
        self,
        *,
        utterance: Utterance | None,
        segment: UtteranceSegment | None,
        position_ms: int | None,
        utterance_position_ms: int | None,
        held: bool,
        rate: float,
        offset_units: Sequence[str],
    ) -> dict[str, dict[str, Any]]:
        """Build one event per requested offset unit for the current instant."""
        base: dict[str, Any] = {
            "event": "playback_position",
            "v": TIMING_VERSION,
            "id": None if utterance is None else utterance.id,
            "state": _state(utterance, held=held),
            "playback_held": held,
            "sampled_at": time.time(),
            "rate": rate,
            "segment_index": None,
            "segment_count": None,
            "position_ms": None,
            "utterance_position_ms": None,
            "timing": None,
            "word_index": None,
            "char_start": None,
            "char_end": None,
            "sentence_start": None,
            "sentence_end": None,
        }
        if utterance is None:
            return {unit: {**base, "offset_unit": unit} for unit in offset_units}
        clips, texts = self._clips(utterance)
        index = segment.index if segment is not None else 0
        if index >= len(clips):
            return {unit: {**base, "offset_unit": unit} for unit in offset_units}
        base.update(
            segment_index=index,
            segment_count=len(clips),
            position_ms=position_ms,
            utterance_position_ms=utterance_position_ms,
        )
        timings, _complete = self.clip_timings(utterance, clips[index])
        source = self._source_map(utterance, texts)
        located = source.words[index]
        word = (
            None if timings is None or position_ms is None else timings.word_index_at(position_ms)
        )
        events = {}
        for unit_name in offset_units:
            unit = _converter(source, unit_name)
            event = {**base, "offset_unit": unit_name}
            if timings is not None:
                event["timing"] = timings.source.value
            if word is not None and word < len(located):
                event["word_index"] = word
                event["char_start"], event["char_end"] = unit(located[word])
                for first, last in source.sentences[index]:
                    if first <= word <= last:
                        event["sentence_start"], event["sentence_end"] = _sentence_span(
                            located, first, last, unit
                        )
                        break
            events[unit_name] = event
        return events


def _state(utterance: Utterance | None, *, held: bool) -> str:
    if utterance is None:
        return "idle"
    if held:
        return "held"
    return "playing" if utterance.state.value == "Playing" else "paused"


def _converter(
    source: _SourceMap, unit: str
) -> Callable[[Span | None], tuple[int | None, int | None]]:
    convert = source.convert if unit == "utf16" else (lambda offset: offset)

    def span(value: Span | None) -> tuple[int | None, int | None]:
        if value is None:
            return None, None
        return convert(value[0]), convert(value[1])

    return span


def _sentence_span(
    located: Sequence[Span | None],
    first: int,
    last: int,
    unit: Callable[[Span | None], tuple[int | None, int | None]],
) -> tuple[int | None, int | None]:
    mapped = [span for span in located[first : last + 1] if span is not None]
    if not mapped:
        return None, None
    return unit((mapped[0][0], mapped[-1][1]))
