# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Finite distributions and deliberately coarse same-run regression decisions."""

import math
import statistics
from collections.abc import Sequence

MIN_PAIRS = 5
REGRESSION_LIMIT = 3.0


def distribution(values: Sequence[float]) -> dict[str, float]:
    """Retain count and tail observations; nearest-rank quantiles never extrapolate."""
    if not values or any(not math.isfinite(value) or value < 0 for value in values):
        msg = "benchmark samples must be nonempty, finite and nonnegative"
        raise ValueError(msg)
    ordered = sorted(values)
    result = {"n": float(len(values)), "mean": statistics.mean(values), "max": max(values)}
    for label, quantile in [("p50", 0.5), ("p90", 0.9), ("p95", 0.95), ("p99", 0.99)]:
        result[label] = ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]
    return result


def regression(baseline: Sequence[float], candidate: Sequence[float]) -> dict[str, float | bool]:
    """Require repeated gross median slowdown, not an absolute CI millisecond gate."""
    if len(baseline) != len(candidate) or len(baseline) < MIN_PAIRS:
        msg = "at least five paired block medians are required"
        raise ValueError(msg)
    if any(value <= 0 for value in baseline):
        msg = "baseline medians must be positive"
        raise ValueError(msg)
    # Validate both inputs, including NaNs that otherwise fail comparisons open.
    distribution(baseline)
    distribution(candidate)
    ratios = [new / old for old, new in zip(baseline, candidate, strict=True)]
    ratios_sorted = sorted(ratios)
    # All but at most one block must exceed 3x. This intentionally catches gross
    # regressions only; subtler changes and all tail metrics remain review signals.
    conservative_ratio = ratios_sorted[1]
    return {
        "median_ratio": statistics.median(ratios),
        "conservative_ratio": conservative_ratio,
        "limit": REGRESSION_LIMIT,
        "failed": conservative_ratio > REGRESSION_LIMIT,
    }
