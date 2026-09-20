# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Calibrate the Store API gate against controlled source examples.

Retire cases when the corresponding gate is removed or stronger analysis
subsumes the failure they reproduce.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle(
        "PR #24 review: Store API checks must report honest source and resource facts"
    ),
]


def test_repository_gate_is_selected_in_the_medium_tier() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_store_surface.py",
            "--collect-only",
            "-m",
            "medium",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
