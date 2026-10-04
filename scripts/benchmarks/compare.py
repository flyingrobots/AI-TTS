# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Pair candidate and pinned-reference experiments on the same machine."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts.benchmarks.metrics import distribution, regression

REFERENCE_COMMIT = "0290f3cf3a0c3930256f42f31500bda59c1eabeb"


def reference_is_clean(root: Path, commit: str) -> bool:
    """Accept only the pinned, unmodified reference application and playback support."""
    # An inherited GIT_DIR (as in git hooks) overrides `-C` and would inspect another repository.
    environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    revision = subprocess.check_output(  # noqa: S603 - read-only source identity
        ["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"], text=True, env=environment
    ).strip()
    # `git diff HEAD` ignores untracked files, and an untracked module is importable.
    dirty = subprocess.check_output(  # noqa: S603 - reject modified reference code
        [
            "/usr/bin/git",
            "-C",
            str(root),
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "src",
            "tests",
        ],
        text=True,
        env=environment,
    )
    if revision != commit or dirty:
        return False
    # Ignored modules/packages still participate in Python import resolution.
    # NUL delimiters preserve filenames containing whitespace or newlines.
    ignored = subprocess.check_output(  # noqa: S603 - read-only ignored-source inventory
        [
            "/usr/bin/git",
            "-C",
            str(root),
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
            "--",
            "src",
            "tests",
        ],
        env=environment,
    )
    for entry in ignored.split(b"\0"):
        if not entry:
            continue
        path = root / os.fsdecode(entry)
        # Git reports an ignored nested repository as one opaque directory.
        # Its contents cannot be certified by this inventory.
        if path.is_symlink() or path.is_dir():
            return False
        if path.suffix.lower() in {".py", ".pyc", ".pyo", ".so", ".pyd"}:
            if path.suffix == ".pyc" and path.parent.name == "__pycache__":
                try:
                    importlib.util.source_from_cache(str(path))
                except ValueError:
                    return False
                else:
                    continue
            return False
    return True


def validate_inventory(report: dict[str, Any]) -> None:
    """Fail closed if the standard golden workload or durable witnesses disappear."""
    expected = {
        f"ready_queue={backlog},ending={ending},nested={nested}"
        for backlog in [0, 32, 256]
        for ending, nested in [("played", False), ("played", True), ("skip", True), ("fail", True)]
    } | {"holds", "durability"}
    if report["cases"].keys() != expected:
        message = "standard golden case inventory differs"
        raise ValueError(message)
    faults = report["cases"]["durability"]
    if (
        faults["rollback"]["rollback.witnesses"] != 2  # noqa: PLR2004 - two rollback witnesses
        or faults["recovery"]["recovery.witnesses"] != 8  # noqa: PLR2004 - eight recovery witnesses
    ):
        message = "durability witnesses missing"
        raise ValueError(message)


def medians(report: dict[str, Any]) -> dict[str, float]:
    """Extract named wall-time signals, refusing empty correctness evidence."""
    result = {}
    validate_inventory(report)
    for name, case in report["cases"].items():
        if name == "durability":
            continue
        if "samples" not in case:
            message = f"case {name} lacks timing evidence"
            raise ValueError(message)
        if case["witnesses"] <= 0:
            message = f"case {name} lacks correctness witnesses"
            raise ValueError(message)
        for metric, values in case["distributions"].items():
            if metric.endswith(".wall_ms"):
                measured = distribution(case["samples"][metric])
                if measured != values or measured["n"] < 100:  # noqa: PLR2004 - standard profile minimum
                    message = "insufficient or inconsistent raw timing evidence"
                    raise ValueError(message)
                result[name + "/" + metric] = measured["p50"]
        expected_metrics = (
            {"held_resume.wall_ms", "resume_after_skip.wall_ms"}
            if name == "holds"
            else {
                "takeover.wall_ms",
                "resume_after_" + name.split("ending=")[1].split(",")[0] + ".wall_ms",
            }
        )
        if {
            key.removeprefix(name + "/") for key in result if key.startswith(name + "/")
        } != expected_metrics:
            message = "standard golden metric inventory differs"
            raise ValueError(message)
    if not result:
        message = "benchmark report contains no latency signals"
        raise ValueError(message)
    return result


def main() -> int:
    """Retain paired raw reports and fail only on repeated gross regressions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pairs", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260930)
    args = parser.parse_args()
    if args.pairs < 5:  # noqa: PLR2004 - documented regression rule
        parser.error("at least five pairs are required")
    if args.iterations < 100:  # noqa: PLR2004 - minimum for reported p99
        parser.error("at least 100 iterations per block are required")
    if not reference_is_clean(args.baseline_root, REFERENCE_COMMIT):
        parser.error("reference must be the clean pinned commit " + REFERENCE_COMMIT)
    args.output.mkdir(parents=True, exist_ok=True)
    randomizer = random.Random(args.seed)  # noqa: S311 - paired experiment ordering
    observations: dict[str, dict[str, list[float]]] = {"baseline": {}, "candidate": {}}
    orders: list[list[str]] = []
    for pair in range(args.pairs):
        labels = ["baseline", "candidate"]
        randomizer.shuffle(labels)
        orders.append(labels)
        for label in labels:
            root = args.baseline_root if label == "baseline" else args.candidate_root
            output = args.output / f"{pair}-{label}.json"
            command = [
                sys.executable,
                "-m",
                "scripts.benchmarks.run",
                "--source-root",
                str(root),
                "--output",
                str(output),
                "--iterations",
                str(args.iterations),
                "--seed",
                str(args.seed + pair),
            ]
            with (args.output / f"{pair}-{label}.log").open("w") as log:
                subprocess.run(  # noqa: S603 - owned Python and explicit paths
                    command, check=True, timeout=60, stdout=log, stderr=subprocess.STDOUT
                )
            for key, value in medians(json.loads(output.read_text())).items():
                observations[label].setdefault(key, []).append(value)
    if observations["baseline"].keys() != observations["candidate"].keys():
        message = "candidate/reference metric inventories differ"
        raise ValueError(message)
    decisions = {
        name: regression(old, observations["candidate"][name])
        for name, old in observations["baseline"].items()
    }
    report = {
        "schema_version": 1,
        "seed": args.seed,
        "orders": orders,
        "observations": observations,
        "decisions": decisions,
        "gate": "at least five same-machine paired medians; all but one must exceed 3x to fail",
    }
    (args.output / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    failures = [name for name, decision in decisions.items() if decision["failed"]]
    sys.stdout.write(json.dumps({"signals": len(decisions), "regressions": failures}) + "\n")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
