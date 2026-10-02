# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Validate the benchmark gauge against known distributions and deliberate slowdowns."""

import pytest
from scripts.benchmarks.metrics import distribution, regression

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("Nearest-rank quantiles and 3x all-but-one paired-block regression policy"),
]


def test_distribution_retains_tail_and_count() -> None:
    assert distribution(list(range(1, 101))) == {
        "n": 100,
        "mean": 50.5,
        "p50": 50,
        "p90": 90,
        "p95": 95,
        "p99": 99,
        "max": 100,
    }


@pytest.mark.parametrize("samples", [[], [-1], [float("nan")], [float("inf")]])
def test_distribution_refuses_untrustworthy_samples(samples: list[float]) -> None:
    with pytest.raises(ValueError, match="nonempty, finite and nonnegative"):
        distribution(samples)


@pytest.mark.parametrize(
    ("candidate", "failed"),
    [
        ([1, 1, 1, 1, 1], False),
        ([100, 1, 1, 1, 1], False),
        ([3, 3, 3, 3, 3], False),
        ([1, 4, 4, 4, 4], True),
    ],
)
def test_guard_detects_repeated_regression_without_gating_one_noisy_block(
    candidate: list[float], *, failed: bool
) -> None:
    assert regression([1] * 5, candidate)["failed"] is failed


@pytest.mark.parametrize(
    ("baseline", "candidate"),
    [([1], [1]), ([1] * 5, [1] * 6), ([0] * 5, [1] * 5), ([1] * 5, [float("nan")] * 5)],
)
def test_guard_refuses_invalid_pairing(baseline: list[float], candidate: list[float]) -> None:
    with pytest.raises(ValueError, match=r"paired block|positive|finite"):
        regression(baseline, candidate)
