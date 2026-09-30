# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Security contracts for dependencies shipped in the frozen runtime graph."""

import base64
import hashlib
import hmac

import jwt
import pytest

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "CVE-2026-102266 / GHSA-9j54-fg26-wv3r: empty HMAC keys must be rejected "
        "through PyJWK just as through the raw-key verification path"
    ),
]


def test_empty_hmac_jwk_cannot_verify_a_token_signed_with_the_known_empty_key() -> None:
    # Fixed claims and a real HMAC avoid time, network, and a signing API that
    # might reject the malformed key before the verification contract is tested.
    # Delete when PyJWT leaves the runtime graph or a stronger check subsumes it.
    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=")
    payload = base64.urlsafe_b64encode(b'{"sub":"attacker"}').rstrip(b"=")
    signing_input = header + b"." + payload
    signature = hmac.new(b"", signing_input, hashlib.sha256).digest()
    token = signing_input + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")
    with pytest.raises(jwt.InvalidKeyError):
        jwt.decode(
            token,
            jwt.PyJWK.from_dict({"kty": "oct", "k": "", "alg": "HS256"}),
            algorithms=["HS256"],
        )
