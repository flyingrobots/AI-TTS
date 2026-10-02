# Copyright 2026 James Ross
# SPDX-License-Identifier: Apache-2.0

"""Manual offline MLX inference/RSS experiment; requires cached model and English assets."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from aitts.engines.kokoro_mlx import KokoroMlxEngine

from scripts.benchmarks.metrics import distribution
from scripts.benchmarks.run import identity, resident_bytes

TEXT = "This is a controlled streaming speech latency test."
VOICE = "bm_daniel"


def provenance(root: Path) -> dict[str, Any]:
    """Identify the measured adapter boundary, its source and the benchmark harness."""
    return identity(
        root,
        sources=("src/aitts/engines/kokoro_mlx.py", "src/aitts/engines/kokoro.py"),
        boundary=(
            "KokoroMlxEngine.synthesize() and KokoroMlxEngine.stream_synthesize() in one "
            "resident process; offline cached assets; no speaker"
        ),
    )


def measure_inference(
    engine: KokoroMlxEngine,
    iterations: int,
    report: dict[str, Any],
    checkpoint: Callable[[str], None],
) -> list[dict[str, float]]:
    """Measure file and streaming adapter boundaries in one resident process."""
    import soundfile as sf  # noqa: PLC0415 - optional manual runtime

    with tempfile.TemporaryDirectory(prefix="aitts-mlx-benchmark-") as folder:
        target = Path(folder) / "speech.wav"
        for trial in range(iterations):
            began = time.perf_counter()
            duration = engine.synthesize(TEXT, VOICE, 1.0, target)
            elapsed = time.perf_counter() - began
            info = sf.info(str(target))
            if info.samplerate != 24000 or info.channels != 1 or info.frames <= 0 or duration <= 0:  # noqa: PLR2004 - PCM format oracle
                message = "invalid WAV from real inference"
                raise RuntimeError(message)
            report["trials"].append(
                {
                    "trial": trial,
                    "wall_ms": elapsed * 1000,
                    "audio_ms": duration,
                    "rtf": elapsed * 1000 / duration,
                }
            )
            if trial % 10 == 0 or trial == iterations - 1:
                checkpoint(f"synthesis_{trial + 1}")
        streaming = []
        for trial in range(iterations):
            began = time.perf_counter()
            chunks = engine.stream_synthesize(TEXT, VOICE, 1.0)
            first = next(chunks)
            first_ms = (time.perf_counter() - began) * 1000
            size = len(first) + sum(len(chunk) for chunk in chunks)
            if not first or size % 2:
                message = "invalid streaming PCM from real inference"
                raise RuntimeError(message)
            streaming.append(
                {
                    "trial": trial,
                    "first_pcm_ms": first_ms,
                    "wall_ms": (time.perf_counter() - began) * 1000,
                    "pcm_bytes": size,
                }
            )
        report["stream_trials"] = streaming
    return streaming


def main() -> int:
    """Measure process RSS separately from MLX allocator and file size, with no speaker output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--idle-seconds", type=float, default=10)
    args = parser.parse_args()
    if args.iterations < 1 or args.idle_seconds < 0:
        parser.error("positive iterations and nonnegative idle time required")
    root = Path.cwd().resolve()
    sys.path.insert(0, str(root / "src"))
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"

    def forbid_network(event: str, _args: tuple[Any, ...]) -> None:
        if event in {"socket.connect", "socket.getaddrinfo"}:
            message = "offline benchmark forbids network access"
            raise RuntimeError(message)

    sys.addaudithook(forbid_network)
    report: dict[str, Any] = {
        "schema_version": 1,
        "size": "large",
        "change_kind": "feature",
        "oracle": "real adapter produces nonempty mono 24kHz WAV and PCM; no network or speakers",
        "environment": provenance(root),
        "text": TEXT,
        "voice": VOICE,
        "speed": 1.0,
        "iterations": args.iterations,
        "idle_seconds": args.idle_seconds,
        "startup_rss_bytes": resident_bytes(),
        "packages": {
            item: importlib.metadata.version(item)
            for item in ["kokoro-mlx", "mlx", "mlx-metal", "numpy", "misaki", "en-core-web-sm"]
        },
        "phases": [],
        "trials": [],
    }
    import mlx.core as mx  # noqa: PLC0415 - optional manual runtime only
    from huggingface_hub import hf_hub_download  # noqa: PLC0415

    from aitts.engines.kokoro import KokoroAssets  # noqa: PLC0415
    from aitts.engines.kokoro_mlx import KokoroMlxEngine  # noqa: PLC0415

    def checkpoint(name: str) -> None:
        report["phases"].append(
            {
                "name": name,
                "rss_bytes": resident_bytes(),
                "mlx_active_bytes": mx.get_active_memory(),
                "mlx_cache_bytes": mx.get_cache_memory(),
                "mlx_peak_bytes": mx.get_peak_memory(),
            }
        )

    def offline(**kwargs: Any) -> str:  # noqa: ANN401 - external download signature
        kwargs["local_files_only"] = True
        return str(hf_hub_download(**kwargs))

    checkpoint("imports")
    engine = KokoroMlxEngine(
        assets=KokoroAssets(repo_id="mlx-community/Kokoro-82M-bf16", download=offline)
    )
    began = time.perf_counter()
    engine.warmup()
    report["warmup_seconds"] = time.perf_counter() - began
    checkpoint("warmup_complete")
    time.sleep(args.idle_seconds)
    checkpoint("loaded_idle")
    streaming = measure_inference(engine, args.iterations, report, checkpoint)
    checkpoint("after_streaming")
    time.sleep(args.idle_seconds)
    checkpoint("post_work_idle")
    report["model"] = engine.evidence(VOICE)
    report["distributions"] = {
        "synthesis_ms": distribution([trial["wall_ms"] for trial in report["trials"]]),
        "rtf": distribution([trial["rtf"] for trial in report["trials"]]),
        "first_pcm_ms": distribution([trial["first_pcm_ms"] for trial in streaming]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    sys.stdout.write(f"Recorded MLX phases and inference trials: {args.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
