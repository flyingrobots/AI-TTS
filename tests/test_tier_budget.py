# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Exercise the real pytest budget gate with owned CPU and reported wall clocks.

Delete when tier CPU budgets retire or a stronger, cheaper policy boundary replaces this suite.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.medium,
    pytest.mark.oracle("issue #80: CPU tier budgets, informational wall totals"),
]
ROOT = Path(__file__).parents[1]


def run_budget(
    tmp_path: Path, *, component: int = 0, phase: str = "call", cpu: float = 1, wall: float = 0.01
) -> subprocess.CompletedProcess[str]:
    """Own the clock boundary, while executing the actual conftest through child pytest."""
    shutil.copyfile(ROOT / "tests/conftest.py", tmp_path / "conftest.py")
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    medium: owned process test\n    oracle(authority): contract\n"
    )
    (tmp_path / "owned_clock.py").write_text(
        f"""import os
import pytest
values = [0.0] * 5
original_times = os.times

def owned_times():
    return os.times_result(values)

def pytest_configure():
    os.times = owned_times

def pytest_unconfigure():
    os.times = original_times

def pytest_runtest_{phase}(item):
    values[{component}] += {cpu!r}

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    outcome.get_result().duration = {wall!r}
"""
    )
    (tmp_path / "test_owned.py").write_text(
        "import pytest\n"
        "pytestmark = [pytest.mark.medium, pytest.mark.oracle('owned budget experiment')]\n"
        "def test_owned():\n    pass\n"
    )
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join((str(tmp_path), str(ROOT / "src")))}
    return subprocess.run(  # fixed child pytest, owned suite and clock plugin
        [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "owned_clock"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_runner_contention_does_not_fail_the_tier_budget(tmp_path: Path) -> None:
    """Oracle: wall totals above the tier ceiling must not fail a low-CPU suite."""
    result = run_budget(tmp_path, wall=41)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("phase", ["setup", "call", "teardown"])
@pytest.mark.parametrize(
    "component", range(4), ids=["user", "system", "child-user", "child-system"]
)
def test_cpu_budget_counts_every_phase_and_waited_child(
    tmp_path: Path, phase: str, component: int
) -> None:
    """Oracle: 121 CPU seconds exceed the 120-second medium tier, even with low wall time."""
    result = run_budget(tmp_path, component=component, phase=phase, cpu=121)
    assert result.returncode == int(pytest.ExitCode.TESTS_FAILED), result.stdout + result.stderr


def test_cpu_budget_accepts_its_exact_boundary(tmp_path: Path) -> None:
    """Oracle: the stated budget is inclusive, matching the existing strict-overrun rule."""
    result = run_budget(tmp_path, cpu=120)
    assert result.returncode == 0, result.stdout + result.stderr
