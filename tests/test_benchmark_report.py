# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""CI refuses incomplete or inconsistent benchmark evidence."""

from typing import Any

import pytest
from scripts.benchmarks.compare import medians
from scripts.benchmarks.metrics import distribution

pytestmark = [
    pytest.mark.small,
    pytest.mark.oracle("Golden benchmark evidence schema and inventory"),
]


def report() -> dict[str, Any]:
    cases: dict[str, Any] = {}
    for queue in [0, 32, 256]:
        for ending, nested in [("played", False), ("played", True), ("skip", True), ("fail", True)]:
            samples = {
                "takeover.wall_ms": [1.0] * 100,
                f"resume_after_{ending}.wall_ms": [2.0] * 100,
            }
            cases[f"ready_queue={queue},ending={ending},nested={nested}"] = {
                "samples": samples,
                "witnesses": 800,
                "distributions": {key: distribution(value) for key, value in samples.items()},
            }
    samples = {"held_resume.wall_ms": [1.0] * 100, "resume_after_skip.wall_ms": [2.0] * 100}
    cases["holds"] = {
        "samples": samples,
        "witnesses": 1000,
        "distributions": {key: distribution(value) for key, value in samples.items()},
    }
    cases["durability"] = {
        "rollback": {"rollback.witnesses": 2},
        "recovery": {"recovery.witnesses": 8},
    }
    return {"cases": cases}


def test_complete_evidence_has_all_twenty_six_latency_signals() -> None:
    signals = medians(report())
    assert len(signals) == 26
    assert sorted(signals.values()) == [1.0] * 13 + [2.0] * 13


@pytest.mark.parametrize(
    "fault", ["case", "payload", "metric", "witness", "durability", "sample", "summary"]
)
def test_incomplete_evidence_cannot_pass_the_guard(fault: str) -> None:
    evidence = report()
    case = evidence["cases"]["holds"]
    if fault == "case":
        del evidence["cases"]["holds"]
    elif fault == "payload":
        del case["samples"]
    elif fault == "metric":
        del case["distributions"]["held_resume.wall_ms"]
    elif fault == "witness":
        case["witnesses"] = 0
    elif fault == "durability":
        evidence["cases"]["durability"]["recovery"]["recovery.witnesses"] = 0
    elif fault == "sample":
        case["samples"]["held_resume.wall_ms"].pop()
    else:
        case["distributions"]["held_resume.wall_ms"]["p50"] = 0
    with pytest.raises(ValueError, match=r"inventory|witnesses|timing evidence"):
        medians(evidence)
