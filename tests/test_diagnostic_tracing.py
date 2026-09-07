# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""One utterance can be followed through the log (architecture §9 bounds).

An utterance passes through submit, segmentation, a synthesis worker, the
playback controller and the sink. Nothing tied those events together, so a
stuck clip meant reading state out of SQLite rather than reading the log.

Distributed tracing would be the wrong instrument for a single local process.
What was missing is narrower: a short correlation token, derived rather than
stored, carried by the events that already exist — and it has to stay inside
the bounded-diagnostics rule that keeps speech text, sources and paths out of
the log entirely.
"""

from __future__ import annotations

import pytest

from aitts.adapters.diagnostic_logging import utterance_trace

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("the bounded-diagnostics policy in architecture section 9"),
]


def test_a_trace_is_derived_from_the_utterance_id() -> None:
    trace = utterance_trace("utt_0123456789abcdef0123456789abcdef")

    # Derived, not stored: no schema change, and the same clip yields the same
    # token in every component that handles it.
    assert trace == "01234567"
    assert utterance_trace("utt_0123456789abcdef0123456789abcdef") == trace


def test_two_utterances_get_different_traces() -> None:
    first = utterance_trace("utt_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    second = utterance_trace("utt_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

    assert first != second


def test_a_trace_carries_nothing_but_the_identifier() -> None:
    trace = utterance_trace("utt_0123456789abcdef0123456789abcdef")

    # The identifier is a random uuid, so the token cannot leak speech, a
    # source label, or a path — which is the whole reason the log is allowed
    # to carry it at all.
    assert len(trace) == 8
    assert all(character in "0123456789abcdef" for character in trace)


@pytest.mark.parametrize("malformed", ["", "utt_", "nonsense", "utt_short"])
def test_a_malformed_identifier_still_yields_a_usable_token(malformed: str) -> None:
    trace = utterance_trace(malformed)

    # A log line is not the place to raise. An unusable id becomes a marker
    # rather than an exception on the hot path.
    assert trace
    assert len(trace) <= 8
