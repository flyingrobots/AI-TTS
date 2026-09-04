# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Swift test metadata policy as a harvested repository contract."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("binding testing-standard size and oracle metadata requirements"),
]

SWIFT_TEST_ROOT = Path(__file__).parents[1] / "clients" / "menubar" / "Tests"


def test_every_swift_test_file_declares_size_and_oracle() -> None:
    """Oracle: every harvested Swift test file carries both required declarations."""
    files = sorted(SWIFT_TEST_ROOT.rglob("*Tests.swift"))
    violations: list[str] = []
    for path in files:
        source = path.read_text()
        if "// Test-Size:" not in source or "// Test-Oracle:" not in source:
            violations.append(str(path.relative_to(SWIFT_TEST_ROOT)))

    assert files, "oracle witness count is zero: no Swift test files were harvested"
    assert not violations, f"Swift test files missing size/oracle metadata: {violations}"
