# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""The frozen JWT parser contains recursive payload failures in its typed API."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import NoReturn

import jwt
import pytest

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("GHSA-42vr-xj54-vc7v: payload decoder RecursionError becomes DecodeError"),
]


def test_recursive_payload_failure_raises_typed_decode_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Retire if PyJWT leaves the dependency graph or conformance replaces this.
    # Only the payload decoder's module reference changes; header decoding is real.
    def exhausted_decoder(_payload: bytes) -> NoReturn:
        message = "controlled payload recursion failure"
        raise RecursionError(message)

    monkeypatch.setattr(jwt.api_jwt, "json", SimpleNamespace(loads=exhausted_decoder))
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=")
    body = base64.urlsafe_b64encode(b'{"value":0}').rstrip(b"=")
    token = header + b"." + body + b".c2ln"
    with pytest.raises(jwt.DecodeError):
        jwt.decode(token, options={"verify_signature": False})
