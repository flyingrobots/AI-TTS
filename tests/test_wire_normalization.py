# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The mask removes only declared volatility, while preserving reference relationships."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.wire_transcripts import assert_transcript, normalize

pytestmark = [pytest.mark.small, pytest.mark.oracle("issue #114 explicit volatility contract")]


def test_known_volatile_values_have_typed_stable_tokens() -> None:
    first, second = "utt_" + "a" * 32, "utt_" + "b" * 32
    value = [
        {"id": first, "enqueued_at": 1760000000.5, "pid": 42},
        {"id": second, "current": first, "finished_at": 1760000001.0},
        {"audio_path": f"/fixture/cache/{first}.wav", "id": first},
    ]
    assert normalize(value, Path("/fixture")) == [
        {"id": "<id:1>", "enqueued_at": "<time>", "pid": "<pid>"},
        {"id": "<id:2>", "current": "<id:1>", "finished_at": "<time>"},
        {"audio_path": "<home>/cache/<id:1>.wav", "id": "<id:1>"},
    ]


@pytest.mark.parametrize(
    "value",
    [
        {"version": "0.2.0", "playback": False, "duration_ms": 100, "state": "Ready"},
        {"text": "utt_" + "a" * 32, "unknown": "utt_" + "a" * 32},
        {"id": "malformed", "pid": True, "finished_at": "yesterday", "enqueued_at": None},
        {"audio_path": "/outside/cache/file.wav", "source": "/fixture/private"},
    ],
)
def test_meaningful_or_malformed_values_are_not_masked(value: dict[str, object]) -> None:
    assert normalize(value, Path("/fixture")) == value


@pytest.mark.parametrize(
    "reply",
    [
        {"ok": 1, "state": "Ready", "version": "0.2.0"},
        {"ok": True, "state": "Played", "version": "0.2.0"},
        {"ok": True, "state": "Ready", "version": "0.1.0"},
        {"ok": True, "state": "Ready", "version": "0.2.0", "extra": False},
        {"ok": True, "state": "Ready"},
    ],
)
def test_comparison_rejects_semantic_type_value_and_shape_changes(reply: dict[str, object]) -> None:
    expected = [{"reply": {"ok": True, "state": "Ready", "version": "0.2.0"}}]
    with pytest.raises(AssertionError):
        assert_transcript([{"reply": reply}], expected, Path("/fixture"))
