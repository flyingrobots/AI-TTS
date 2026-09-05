# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Public application-schema contracts."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from aitts.application.schemas import EnqueueSpeech
from aitts.model import ContentFormat, Priority, Sensitivity

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("approved public speech-schema contract"),
]

enqueue_requests = st.builds(
    EnqueueSpeech,
    text=st.text(min_size=1, max_size=200).filter(lambda value: bool(value.strip())),
    content_format=st.sampled_from(list(ContentFormat)),
    voice=st.none() | st.text(min_size=1, max_size=40).filter(lambda value: bool(value.strip())),
    speed=st.none() | st.floats(min_value=0.5, max_value=2.0, allow_nan=False),
    sensitivity=st.sampled_from(list(Sensitivity)),
    priority=st.sampled_from(list(Priority)),
    source=st.none() | st.text(min_size=1, max_size=40).filter(lambda value: bool(value.strip())),
)


@settings(max_examples=100, derandomize=True, database=None)
@given(request=enqueue_requests)
def test_enqueue_schema_round_trips_generated_json(request: EnqueueSpeech) -> None:
    """Oracle: Pydantic JSON round-trip contract for every generated legal request."""
    decoded = EnqueueSpeech.model_validate_json(request.model_dump_json())

    assert decoded == request


@pytest.mark.parametrize("text", ["", " ", "\t\n"])
def test_enqueue_schema_rejects_text_without_speech(text: str) -> None:
    """Oracle: approved requirement that enqueue text be non-empty after trimming."""
    with pytest.raises(ValidationError, match="at least 1 character"):
        EnqueueSpeech(text=text)


def test_enqueue_schema_defaults_agent_speech_to_plain_text() -> None:
    request = EnqueueSpeech(text="# Say **this** literally")

    assert request.content_format is ContentFormat.PLAIN_TEXT


def test_public_schema_rejects_unknown_fields() -> None:
    """Oracle: public schemas are closed so adapter drift fails loudly."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EnqueueSpeech.model_validate({"text": "hello", "undocumented": True})
