# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Word timing core: engine marks, estimates, sentences and source offsets."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from aitts.engines.kokoro import duration_marks, token_marks
from aitts.engines.managed import wire_marks
from aitts.model import ContentFormat
from aitts.segmentation import prepare_speech_segments, segment_text
from aitts.timing import (
    ClipTimings,
    TimingSource,
    WordMark,
    WordTiming,
    align_spoken_words,
    boundary_after,
    detect_pauses,
    estimate_timings,
    sentence_word_ranges,
    timings_from_marks,
    utf16_converter,
    word_spans,
)

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "word-timing contract in docs/design/architecture.md section 5 (timings and "
        "playback_position): engine times on the clip clock, offsets into submitted text"
    ),
]


def _words(text: str) -> list[str]:
    return [text[start:end] for start, end in word_spans(text)]


def test_engine_tokens_attach_to_written_words_including_split_numbers() -> None:
    text = "In 1995, Dr. Smith paid $3,450.75."
    # Misaki-style tokens: punctuation and currency are separate tokens.
    marks = [
        WordMark("In", 250, 400),
        WordMark("1995", 400, 1100),
        WordMark(",", 1100, 1180),
        WordMark("Dr.", 1180, 1500),
        WordMark("Smith", 1500, 1800),
        WordMark("paid", 1800, 2000),
        WordMark("$", 2000, 2050),
        WordMark("3,450.75", 2050, 4200),
        WordMark(".", 4200, 4300),
    ]

    timings = timings_from_marks(text, marks)

    assert timings is not None
    assert timings.source is TimingSource.ENGINE
    assert [(w.start_ms, w.end_ms) for w in timings.words] == [
        (250, 400),
        (400, 1100),
        (1180, 1500),
        (1500, 1800),
        (1800, 2000),
        # A currency sign is punctuation to the engine: the word starts with its number.
        (2050, 4200),
    ]
    assert [text[w.char_start : w.char_end] for w in timings.words] == _words(text)


def test_words_the_engine_skipped_are_interpolated_between_timed_neighbours() -> None:
    text = "alpha — — omega"
    timings = timings_from_marks(text, [WordMark("alpha", 0, 300), WordMark("omega", 900, 1200)])

    assert timings is not None
    assert [(w.start_ms, w.end_ms) for w in timings.words] == [
        (0, 300),
        (300, 600),
        (600, 900),
        (900, 1200),
    ]


def test_marks_describing_another_text_are_refused_rather_than_trusted() -> None:
    text = "one two three four five six"
    assert timings_from_marks(text, [WordMark("one", 0, 100), WordMark("zebra", 100, 200)]) is None


def test_partial_marks_describe_only_the_generated_prefix() -> None:
    text = "first second third fourth"
    partial = timings_from_marks(
        text, [WordMark("first", 0, 200), WordMark("second", 200, 450)], partial=True
    )

    assert partial is not None
    assert [w.start_ms for w in partial.words] == [0, 200]
    assert partial.word_index_at(10_000) == 1


def test_word_at_position_keeps_the_last_started_word_through_pauses() -> None:
    timings = ClipTimings(
        TimingSource.ENGINE,
        (WordTiming(250, 500, 0, 3), WordTiming(900, 1200, 4, 7)),
    )

    assert [timings.word_index_at(p) for p in (0, 249, 250, 899, 900, 5000)] == [
        None,
        None,
        0,
        0,
        1,
        1,
    ]


def test_kokoro_duration_port_matches_hand_computed_join_timestamps() -> None:
    # BOS, h I, space, D E r, ., EOS: nine 600-sample frame counts.
    tokens = [
        SimpleNamespace(text="Hi", phonemes="hI", whitespace=" "),
        SimpleNamespace(text="there", phonemes="DEr", whitespace=""),
        SimpleNamespace(text=".", phonemes=".", whitespace=""),
    ]
    durations = [5, 2, 3, 4, 1, 1, 2, 3, 6]

    marks = duration_marks(tokens, durations, offset_ms=1000)

    assert [(m.text, m.start_ms, m.end_ms) for m in marks] == [
        ("Hi", 1050.0, 1225.0),
        ("there", 1225.0, 1375.0),
        (".", 1375.0, 1450.0),
    ]


def test_kokoro_token_times_are_shifted_onto_the_clip_clock() -> None:
    tokens = [
        SimpleNamespace(text="Next", start_ts=0.25, end_ts=0.5),
        SimpleNamespace(text="untimed", start_ts=None, end_ts=None),
    ]

    assert token_marks(tokens, 4000.0) == (WordMark("Next", 4250.0, 4500.0),)
    assert token_marks(None, 0.0) == ()


def test_abbreviations_do_not_end_sentences_but_paragraphs_do() -> None:
    text = "Dr. Smith met Mr. Jones at 3 p.m. on Jan. 5th. They talked, etc. Then\n\nthey left"
    spans = word_spans(text)
    words = _words(text)
    kinds = {words[i]: boundary_after(text, spans, i) for i in range(len(spans))}

    assert kinds["Dr."] is None
    assert kinds["Mr."] is None
    assert kinds["p.m."] is None
    assert kinds["Jan."] is None
    assert kinds["5th."] == "sentence"
    assert kinds["talked,"] == "clause"
    assert kinds["etc."] == "sentence"
    assert kinds["Then"] == "sentence"
    assert [words[a] for a, _ in sentence_word_ranges(text)] == ["Dr.", "They", "Then", "they"]


def _speech(rate: int, layout: list[tuple[str, float]]) -> np.ndarray:
    """Concatenate 220 Hz tone ('speech') and exact silence runs, in ms."""
    pieces = []
    for kind, ms in layout:
        count = int(rate * ms / 1000)
        if kind == "tone":
            t = np.arange(count) / rate
            pieces.append(0.3 * np.sin(2 * np.pi * 220 * t))
        else:
            pieces.append(np.zeros(count))
    return np.concatenate(pieces).astype(np.float32)


def test_pause_detection_finds_exact_silences_and_ignores_short_dips() -> None:
    rate = 24000
    audio = _speech(
        rate,
        [
            ("silence", 300),
            ("tone", 1000),
            ("silence", 40),
            ("tone", 500),
            ("silence", 400),
            ("tone", 800),
        ],
    )

    pauses = detect_pauses(audio, rate)

    assert len(pauses) == 2
    (lead_start, lead_end), (gap_start, gap_end) = pauses
    assert lead_start == 0
    assert abs(lead_end - 300) <= 25
    assert abs(gap_start - 1840) <= 25
    assert abs(gap_end - 2240) <= 25


def test_estimate_anchors_sentence_boundaries_on_audio_pauses() -> None:
    text = "Short one. This second sentence is a good deal longer than the first."
    rate = 24000
    # The first sentence is spoken slowly: far longer than its letters suggest.
    audio = _speech(rate, [("silence", 200), ("tone", 2000), ("silence", 500), ("tone", 2500)])
    duration = len(audio) / rate * 1000

    timings = estimate_timings(text, duration, detect_pauses(audio, rate))

    assert timings is not None
    assert timings.source is TimingSource.ESTIMATED
    words = timings.words
    assert abs(words[0].start_ms - 200) <= 25
    assert abs(words[1].end_ms - 2200) <= 25  # "one." ends where the pause starts
    assert abs(words[2].start_ms - 2700) <= 25  # "This" begins where it ends
    assert abs(words[-1].end_ms - duration) <= 25
    unanchored = estimate_timings(text, duration, [])
    assert unanchored is not None
    assert abs(unanchored.words[2].start_ms - 2700) > 400  # the anchor is load-bearing


_ESTIMATE_WORDS = st.lists(
    st.from_regex(r"[A-Za-z0-9$%,.]{1,9}", fullmatch=True), min_size=1, max_size=60
)


@settings(max_examples=60, deadline=None)
@given(words=_ESTIMATE_WORDS, duration=st.integers(min_value=1, max_value=600_000))
def test_estimates_are_an_ordered_prefix_within_the_clip(words: list[str], duration: int) -> None:
    text = " ".join(words)
    timings = estimate_timings(text, duration)

    if timings is None:
        return
    spans = word_spans(text)
    assert [(w.char_start, w.char_end) for w in timings.words] == spans[: len(timings.words)]
    starts = [w.start_ms for w in timings.words]
    assert starts == sorted(starts)
    assert all(0 <= w.start_ms <= w.end_ms <= duration + 1 for w in timings.words)


@settings(max_examples=60, deadline=None)
@given(words=_ESTIMATE_WORDS)
def test_plausibly_long_audio_times_every_word(words: list[str]) -> None:
    # At most 6 weight units per character; 200 ms each is under 36 units/s.
    text = " ".join(words)
    timings = estimate_timings(text, 200 * len(text))

    assert timings is not None
    assert len(timings.words) == len(word_spans(text))


_PLAIN_WORD = st.from_regex(r"[A-Za-z][a-z]{0,8}[.,]?", fullmatch=True)
_GAP = st.sampled_from([" ", "  ", "\n", "\n\n", " \n\n  "])


@settings(max_examples=40, deadline=None)
@given(st.lists(st.tuples(_PLAIN_WORD, _GAP), min_size=1, max_size=400))
def test_plain_text_segments_map_every_word_to_its_exact_source_span(
    pieces: list[tuple[str, str]],
) -> None:
    source = "".join(word + gap for word, gap in pieces)
    cursor = 0
    previous_end = -1
    for segment in segment_text(source):
        located, cursor = align_spoken_words(source, segment, cursor)
        for span, word in zip(located, _words(segment), strict=True):
            assert span is not None
            assert source[span[0] : span[1]] == word
            assert span[0] > previous_end
            previous_end = span[1] - 1


def test_markdown_projection_maps_spoken_words_past_syntax_and_front_matter() -> None:
    source = (
        "---\ntitle: Rivers\n---\n# Rivers\n\nRivers **carve** [canyons](https://example.com/a)"
        " and `deltas`.\n\n1. First item\n"
    )
    (segment,) = prepare_speech_segments(source, content_format=ContentFormat.MARKDOWN)
    cursor = source.index("# Rivers")

    located, _cursor = align_spoken_words(source, segment, cursor)

    spoken = _words(segment)
    found = [None if span is None else source[span[0] : span[1]] for span in located]
    assert spoken[0] == "Rivers."  # the projection added terminal punctuation
    assert found[0] == "Rivers"
    assert located[0] == (source.index("# Rivers") + 2, source.index("# Rivers") + 8)
    assert "carve" in found
    assert "canyons" in found
    assert "deltas`." in found or "deltas" in found
    assert all(span is not None for span in located)


def test_utf16_offsets_count_astral_characters_twice() -> None:
    text = "hi \U0001f600 there"
    convert = utf16_converter(text)

    assert convert(3) == 3
    assert convert(4) == 5  # after the emoji
    assert convert(len(text)) == len(text) + 1
    assert utf16_converter("plain")(4) == 4


@settings(max_examples=50, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.integers(0, 10**7), st.integers(0, 10**4), st.integers(0, 10**6), st.integers(0, 64)
        ),
        max_size=50,
    ),
    st.sampled_from(list(TimingSource)),
)
def test_stored_timings_round_trip_exactly(
    raw: list[tuple[int, int, int, int]], source: TimingSource
) -> None:
    timings = ClipTimings(source, tuple(WordTiming(s, s + d, c, c + n) for s, d, c, n in raw))

    assert ClipTimings.decode(timings.encode()) == timings


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "not json",
        '{"v": 2, "source": "engine", "words": []}',
        '{"v": 1, "source": "guessed", "words": []}',
        '{"v": 1, "source": "engine", "words": [[5, 1, 0, 1]]}',
        '{"v": 1, "source": "engine", "words": [[0, 1, 0]]}',
        '{"v": 1, "source": "engine", "words": [[0, 1.5, 0, 1]]}',
        '{"v": 1, "source": "engine", "words": [[-1, 1, 0, 1]]}',
    ],
)
def test_malformed_stored_timings_are_refused(raw: str | None) -> None:
    assert ClipTimings.decode(raw) is None


@pytest.mark.parametrize(
    "value",
    [
        None,
        "marks",
        [["word", 0, 10, 1]],
        [[1, 0, 10]],
        [["word", 10, 5]],
        [["word", -1, 5]],
        [["word", True, 5]],
        [["word", 0, float("inf")]],
        [["ok", 0, 1], ["bad"]],
    ],
)
def test_malformed_worker_marks_cost_the_marks_not_the_clip(value: object) -> None:
    assert wire_marks(value) == ()


def test_worker_marks_decode_on_the_clip_clock() -> None:
    assert wire_marks([["Hi", 0, 12.5], ["there", 12.5, 40]]) == (
        WordMark("Hi", 0.0, 12.5),
        WordMark("there", 12.5, 40.0),
    )


def test_words_the_audio_never_reached_stay_untimed_not_squeezed_in() -> None:
    # Issue #99: a render that stops mid-text must not caption its unspoken suffix.
    text = "The first sentence was spoken. The second one never was."
    marks = [WordMark(w, i * 200, (i + 1) * 200) for i, w in enumerate(text.split()[:5])]

    timings = timings_from_marks(text, marks)

    assert timings is not None
    assert len(timings.words) == 5
    assert timings.word_index_at(60_000) == 4


def test_audio_too_short_for_its_text_times_only_what_it_could_hold() -> None:
    sentence = "Each of these sentences takes a speaker about two seconds to say."
    text = " ".join([sentence] * 6)
    rate = 24000
    # 2.2 s of speech: room for about one sentence, not six.
    audio = _speech(rate, [("silence", 100), ("tone", 2200), ("silence", 100)])

    timings = estimate_timings(text, len(audio) / rate * 1000, detect_pauses(audio, rate))
    complete = estimate_timings(text, 14_000)

    assert timings is not None
    assert 8 <= len(timings.words) <= 16  # one sentence is 12 words
    assert timings.words[-1].end_ms <= 2300 + 25
    assert complete is not None
    assert len(complete.words) == len(text.split())  # plausible audio keeps every word
