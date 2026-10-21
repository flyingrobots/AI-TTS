# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Certifi CA bundle excludes compromised emSign roots in the frozen runtime graph."""

import certifi
import pytest

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle(
        "PYSEC-2026-4320 / GHSA-6q48-6c7w-9gw2: certifi CA bundle must exclude "
        "the compromised emSign ECC Root CA - G3 certificate"
    ),
]


def test_certifi_bundle_excludes_compromised_emsign_root_ca() -> None:
    # Retire if certifi leaves the frozen graph or a stronger trust store check subsumes it.
    bundle_text = certifi.contents()
    assert "emSign ECC Root CA - G3" not in bundle_text
