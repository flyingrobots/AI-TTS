# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Strict one-object-per-line JSON encoding for local transport adapters."""

from __future__ import annotations

import json
from typing import Any, NoReturn

MAX_JSONL_LINE_BYTES = 1024 * 1024


class JsonlDecodeError(ValueError):
    """An input line is not one UTF-8 JSON object."""


class JsonlEncodeError(ValueError):
    """An output object cannot be represented as strict JSONL."""


def _reject_nonfinite(token: str) -> NoReturn:
    msg = f"non-finite number is not JSON: {token}"
    raise ValueError(msg)


def decode_json_object(line: bytes) -> dict[str, Any]:
    """Decode one UTF-8 JSON object or raise a transport-typed error."""
    try:
        payload: Any = json.loads(line.decode("utf-8"), parse_constant=_reject_nonfinite)
    except (RecursionError, ValueError) as exc:
        msg = "not valid JSON"
        raise JsonlDecodeError(msg) from exc
    if not isinstance(payload, dict):
        msg = "expected a JSON object"
        raise JsonlDecodeError(msg)
    return payload


def encode_json_object(payload: dict[str, Any]) -> bytes:
    """Encode one strict JSON object followed by exactly one newline."""
    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as exc:
        msg = "object is not valid JSON"
        raise JsonlEncodeError(msg) from exc
    return encoded + b"\n"
