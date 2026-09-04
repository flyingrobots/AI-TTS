# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Generated contracts for the strict JSONL transport codec."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from aitts.adapters.jsonl import (
    JsonlDecodeError,
    JsonlEncodeError,
    decode_json_object,
    encode_json_object,
)

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("RFC 8259 UTF-8 object grammar and JSONL one-line framing"),
]

unicode_text = st.text(max_size=80)
json_scalars = (
    st.none()
    | st.booleans()
    | st.integers(min_value=-(2**53), max_value=2**53)
    | st.floats(allow_nan=False, allow_infinity=False)
    | unicode_text
)
json_values = st.recursive(
    json_scalars,
    lambda children: (
        st.lists(children, max_size=5) | st.dictionaries(unicode_text, children, max_size=5)
    ),
    max_leaves=20,
)
json_objects = st.dictionaries(unicode_text, json_values, max_size=8)


@settings(max_examples=200, derandomize=True, database=None)
@given(payload=json_objects)
def test_generated_json_objects_round_trip_as_one_physical_line(payload: dict[str, Any]) -> None:
    encoded = encode_json_object(payload)

    assert {
        "decoded": decode_json_object(encoded),
        "terminator": encoded.endswith(b"\n"),
        "line_count": encoded.count(b"\n"),
    } == {"decoded": payload, "terminator": True, "line_count": 1}


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), object()],
    ids=("nan", "positive-infinity", "negative-infinity", "non-json-object"),
)
def test_encoder_rejects_values_outside_strict_json(value: object) -> None:
    with pytest.raises(JsonlEncodeError, match="object is not valid JSON"):
        encode_json_object({"value": value})


@settings(max_examples=500, derandomize=True, database=None)
@example(line=b"\xff\n")
@example(line=(b"[" * 1_000) + (b"]" * 1_000))
@given(line=st.binary(max_size=8_192))
def test_generated_bytes_return_an_object_or_typed_decode_error(line: bytes) -> None:
    try:
        result = decode_json_object(line)
    except JsonlDecodeError as exc:
        outcome = ("typed_error", bool(str(exc)))
    else:
        outcome = ("object", isinstance(result, dict))

    assert outcome in {("typed_error", True), ("object", True)}
