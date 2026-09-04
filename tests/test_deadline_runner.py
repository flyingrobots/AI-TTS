# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Hard-deadline runner contracts for non-pytest suites."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("binding suite latency-budget requirement"),
]

RUNNER = Path(__file__).parents[1] / "scripts" / "run_with_deadline.py"


def test_deadline_runner_preserves_child_failure() -> None:
    """Oracle: a trustworthy gate must preserve, never absorb, a child's red status."""
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(RUNNER), "5", sys.executable, "-c", "raise SystemExit(7)"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 7


def test_deadline_runner_terminates_suite_overrun() -> None:
    """Oracle: declared suite ceiling is a gate with timeout exit status 124."""
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(RUNNER),
            "0.1",
            sys.executable,
            "-c",
            "import time; time.sleep(10)",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 124
    assert "suite latency budget exceeded" in result.stderr
