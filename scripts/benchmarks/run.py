# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Run owned controller benchmarks; select implementation before importing it."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import platform
import random
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scripts.benchmarks.metrics import distribution

if TYPE_CHECKING:
    from collections.abc import Sequence


def resident_bytes() -> int:
    """Sample this process's current RSS, separately from high-water memory."""
    output = subprocess.check_output(  # noqa: S603 - fixed process introspection command
        ["/bin/ps", "-o", "rss=", "-p", str(os.getpid())], text=True
    )
    return int(output.strip()) * 1024


CONTROLLER_SOURCES = ("src/aitts/playback.py", "src/aitts/store.py", "src/aitts/streaming.py")
CONTROLLER_BOUNDARY = (
    "real PlaybackController + real Store + contract FakeSink; no model or speaker"
)
# The harness always loads from this checkout, even when --source-root selects another
# implementation, so a paired comparison runs both arms under these exact files.
HARNESS_FILES = (
    *(f"scripts/benchmarks/{name}.py" for name in ("__init__", "cases", "compare", "failures")),
    *(f"scripts/benchmarks/{name}.py" for name in ("metrics", "mlx", "pcm", "run")),
    "tests/test_playback.py",
)


def sha256_files(root: Path, names: Sequence[str]) -> dict[str, str]:
    """Fingerprint named files under one root."""
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}


def identity(
    root: Path,
    sources: Sequence[str] = CONTROLLER_SOURCES,
    boundary: str = CONTROLLER_BOUNDARY,
) -> dict[str, Any]:
    """Record the measured boundary, source, harness, environment and clocks of an experiment."""
    harness = Path(__file__).resolve().parents[2]
    return {
        "source_root": str(root),
        "source_sha256": sha256_files(root, sources),
        "harness_root": str(harness),
        "harness_sha256": sha256_files(harness, HARNESS_FILES),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
        "clock": "perf_counter_ns; process_time_ns",
        "sqlite": "file-backed WAL, production defaults, no filesystem cache flush",
        "boundary": boundary,
    }


async def soak(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Exercise a long-lived process with bounded in-memory measurement retention."""
    from scripts.benchmarks.cases import cycle, held_cycle, session  # noqa: PLC0415
    from scripts.benchmarks.pcm import round_trip  # noqa: PLC0415

    cases: dict[str, Any] = {}
    pcm_samples: dict[str, list[float]] = {}
    pcm_witnesses = 0
    async with session(root) as run:
        for _ in range(args.warmup):
            await cycle(run)
        run.samples.clear()
        memory = [{"iteration": 0, "rss_bytes": resident_bytes()}]
        began = time.perf_counter()
        count = math.ceil(args.seconds / args.interval)
        samples_path = args.output.with_suffix(".samples.jsonl")
        samples_path.write_text("")
        lateness = []
        for index in range(count):
            due = began + index * args.interval
            await asyncio.sleep(max(0, due - time.perf_counter()))
            lateness.append(max(0, time.perf_counter() - due) * 1000)
            await cycle(run, ["played", "skip", "fail"][index % 3], nested=True)
            if index % 10 == 0:
                await held_cycle(run, microphone=index % 20 == 0)
                for metric, value in round_trip(root).items():
                    if metric == "witnesses":
                        pcm_witnesses += int(value)
                    else:
                        pcm_samples.setdefault(metric, []).append(value)
            if index % 100 == 0 or index == count - 1:
                memory.append({"iteration": index + 1, "rss_bytes": resident_bytes()})
                with samples_path.open("a") as samples_file:
                    samples_file.write(json.dumps(run.samples) + "\n")
                run.samples.clear()
        # Reconstruct samples only after live memory observations finish.
        for line in samples_path.read_text().splitlines():
            for name, values in json.loads(line).items():
                run.samples.setdefault(name, []).extend(values)
        cases["soak"] = {
            "samples": run.samples,
            "witnesses": run.witnesses,
            "scheduled_arrivals": count,
            "completed_arrivals": count,
            "arrival_lateness_ms": lateness,
            "memory": memory,
            "wall_seconds": time.perf_counter() - began,
            "database_bytes": sum(
                p.stat().st_size
                for p in root.glob("state.db*")  # noqa: ASYNC240 - owned files after measured operation
            ),
            "policy": "fixed intended arrivals; serialized completion; retain lateness",
        }
    cases["pcm"] = {"samples": pcm_samples, "witnesses": pcm_witnesses}
    return cases


async def golden(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    """Measure queue scaling, nested outcomes, holds and durability faults."""
    from scripts.benchmarks.cases import cycle, held_cycle, session  # noqa: PLC0415
    from scripts.benchmarks.failures import recovery, rollback  # noqa: PLC0415

    cases: dict[str, Any] = {}
    specs = [
        (backlog, ending, nested)
        for backlog in args.backlog
        for ending, nested in [
            ("played", False),
            ("played", True),
            ("skip", True),
            ("fail", True),
        ]
    ]
    random.Random(args.seed).shuffle(specs)  # noqa: S311 - reproducible experiment order
    for number, (backlog, ending, nested) in enumerate(specs):
        home = root / str(number)
        home.mkdir()
        async with session(home, backlog) as run:
            for _ in range(args.warmup):
                await cycle(run, ending, nested=nested)
            run.samples.clear()
            run.witnesses = 0
            for _ in range(args.iterations):
                await cycle(run, ending, nested=nested)
            cases[f"ready_queue={backlog},ending={ending},nested={nested}"] = {
                "samples": run.samples,
                "witnesses": run.witnesses,
            }
    home = root / "holds"
    home.mkdir()
    async with session(home) as run:
        for _ in range(args.iterations):
            await held_cycle(run, microphone=False)
            await held_cycle(run, microphone=True)
        cases["holds"] = {"samples": run.samples, "witnesses": run.witnesses}
    home = root / "failure"
    home.mkdir()
    cases["durability"] = {"rollback": rollback(home), "recovery": await recovery(home)}
    return cases


async def workload(args: argparse.Namespace) -> dict[str, Any]:
    """Summarize distributions after the owned workload has finished."""
    with tempfile.TemporaryDirectory(prefix="aitts-benchmark-") as folder:
        root = Path(folder)
        cases = await soak(args, root) if args.suite == "soak" else await golden(args, root)
    for case in cases.values():
        if "samples" in case:
            case["distributions"] = {
                name: distribution(values) for name, values in case["samples"].items()
            }
    return cases


def main() -> int:
    """Write raw observations and summaries; a contract failure exits nonzero."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--suite", choices=["golden", "soak"], default="golden")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--backlog", type=int, nargs="+", default=[0, 32, 256])
    parser.add_argument("--seed", type=int, default=20260930)
    parser.add_argument("--seconds", type=float, default=300)
    parser.add_argument("--interval", type=float, default=0.05)
    args = parser.parse_args()
    if (
        args.iterations < 1
        or args.warmup < 0
        or min(args.backlog) < 0
        or args.seconds <= 0
        or args.interval <= 0
    ):
        parser.error("counts and durations must be positive; warmup/backlog may be zero")
    root = args.source_root.resolve()
    sys.path.insert(0, str(root / "src"))
    import aitts  # noqa: PLC0415 - implementation selection precedes all application imports

    if not Path(aitts.__file__).resolve().is_relative_to(root):
        parser.error("requested implementation was not imported")
    report: dict[str, Any] = {
        "schema_version": 1,
        "change_kind": "feature",
        "size": "medium" if args.suite == "golden" else "large",
        "oracle": "PROMPTS1: exact offsets/LIFO, holds, one owner, rollback, silent recovery",
        "environment": identity(root),
        "parameters": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "rss_before_bytes": resident_bytes(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report["cases"] = asyncio.run(workload(args))
    report["rss_after_bytes"] = resident_bytes()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report["peak_rss_bytes"] = peak if sys.platform == "darwin" else peak * 1024
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    sys.stdout.write(f"Recorded {len(report['cases'])} cases: {args.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
