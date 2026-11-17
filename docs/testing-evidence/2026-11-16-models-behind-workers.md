# Every model behind the worker protocol

Change-kind: behavior change, issue [#116](https://github.com/flyingrobots/AI-TTS/issues/116).

The daemon now runs Kokoro, Kokoro MLX and Chatterbox only in worker processes. `configured_engines` builds a `ManagedEngine` for each installed guided runtime and always lists Kokoro; an uninstalled Kokoro refuses every request with `run ai-tts model-setup kokoro` and spawns nothing. The in-process adapter paths (`select_engine`, `mlx_available`, `in_process_available`, `AI_TTS_CHATTERBOX_MODEL_DIR`) are removed from the daemon. `make install` no longer puts Kokoro or spaCy's English model into the daemon tool environment. The worker frame format is unchanged; the worker now writes frames to a private duplicate of descriptor 1 and points descriptor 1 at `/dev/null`, so native library output cannot reach the pipe.

The in-process adapters (`aitts.engines.kokoro`, `kokoro_mlx`, `chatterbox`) remain, because the worker runs them.

## Observed red (parent c0f0a0f)

| Test | Red for the right reason |
|---|---|
| `test_engine_selection.py::test_every_local_engine_is_a_worker_even_with_legacy_configuration` | `AI_TTS_CHATTERBOX_MODEL_DIR` registered an extra in-process `chatterbox` |
| `test_engine_selection.py::test_uninstalled_default_refuses_with_its_setup_command_and_spawns_nothing` | selected default was an in-process `KokoroEngine` |
| `test_engine_selection.py::test_daemon_startup_imports_no_model_package` | `sys.modules` held `aitts.engines.chatterbox` and `aitts.engines.kokoro_mlx` |
| `test_model_setup_daemon.py::test_importable_model_package_never_marks_an_uninstalled_runtime_installed` | importable package reported `installed: True` |
| `test_make_installation.py::test_install_keeps_every_model_package_out_of_the_daemon_environment` | tool install carried `kokoro>=0.9.4`, the spaCy wheel, and torch pins |
| `test_managed_engine.py::test_native_writes_to_the_output_descriptor_cannot_corrupt_frames` | `os.write(1, ...)` in the worker made the next frame invalid JSON |

## Falsification of green-born tests

The worker edge and stress tests passed on the parent, because `ManagedEngine` already handled those cases. Each seeded fault was applied alone and restored:

| Fault | Witness | Result |
|---|---|---|
| EOF from the worker ignored | worker exit during synthesis | pytest timeout |
| `select` deadline ignored | silent worker | pytest timeout |
| buffered frames after the first newline dropped | 1,000 requests to one worker | pytest timeout (lost frame) |
| Kokoro engines built without the streaming adapter | each catalog engine through a worker | `AttributeError: stream_synthesize` |
| descriptor 1 not redirected | native writes | `SynthesisError` from invalid JSON |

An earlier assertion in the silent-worker test (`_process is None`) survived its fault, because the stream's `finally` also stops the worker. It was removed; the deadline is the oracle.

## Time to first audio and resident memory

Machine: Apple M5 Pro, 64 GiB, macOS. Date 2026-11-16. Models: the installed guided runtimes in `~/Library/Application Support/ai-tts/model-runtimes` (no download). Text: "The quick brown fox jumps over the lazy dog." Five warm requests after warmup and one first request. Chatterbox is file-only, so its figure is time to a complete WAV.

- **Before**: the model in the measuring process, as the daemon ran Kokoro before this change. Runtime Python 3.12.14. Load average about 17 (other work on the host).
- **After**: the measuring process imports `aitts.daemon` and talks to a worker running this branch's worker code over the installed venv and assets. Daemon side Python 3.14.7. Load average about 5.

| Engine | Warm first audio, median (runs) before | after | First request after warmup before | after |
|---|---|---|---|---|
| kokoro | 371.5 ms (355–392) | 355.8 ms (350–412) | 827 ms | 940 ms |
| kokoro-mlx | 116.7 ms (112–123) | 108.9 ms (103–113) | 698 ms | 640 ms |
| chatterbox (complete WAV) | 2504 ms (2253–2926) | 2619 ms (2064–2905) | 2574 ms | 2036 ms |

A second "after" run against the installed (older) worker code gave Kokoro 467 ms, MLX 105 ms and Chatterbox 2933 ms warm medians. The run-to-run spread is larger than any difference between the modes. These five-sample runs on a loaded host show no measurable first-audio cost from the boundary; they cannot resolve a cost below about 50 ms.

| Engine | Daemon RSS before (model in process) | Daemon RSS after | Worker RSS after |
|---|---|---|---|
| kokoro | 1525 MiB | 45 MiB | 1462 MiB |
| kokoro-mlx | 950 MiB | 46 MiB | 902 MiB |
| chatterbox | 3733 MiB (peak 6343) | 45 MiB (peak 45) | 3670 MiB |

"Before" RSS is the measuring process without the daemon's own modules; the daemon modules add about 24 MiB (the after process starts at 22 MiB and holds 45 MiB). Total memory is about the same: the model moves to the worker.

These are the real-model golden runs for the streaming workload: both Kokoro engines streamed PCM blocks through a worker, and Chatterbox rendered a WAV through one. They ran by hand and are not in CI.

## Not verified

- No physical listening or speaker output.
- No clean-machine `make install` followed by `ai-tts model-setup kokoro`; installer behavior is checked with the owned-tool test only.
- The installed application is unchanged; this branch has not been installed.

## Reproduction

The measuring script, run as `PYTHON measure.py inproc|worker NAME RUNTIME_ROOT`. For "before", run it with the runtime's `venv/bin/python`, `PYTHONPATH=RUNTIME_ROOT/adapter` and `HF_HUB_OFFLINE=1`. For "after", run it with the checkout's `.venv/bin/python` and a root whose `venv` and `assets` link to the installed runtime and whose `adapter/aitts` is a copy of `src/aitts`.

```python
"""Measure first-audio latency and process RSS, in-process vs worker. Prints one JSON line."""

import json
import os
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TEXT = "The quick brown fox jumps over the lazy dog."  # nine words; close to the agreed eight
RUNS = 5


def rss_mib(pid: int) -> float:
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True)
    return int(out.stdout.strip()) / 1024


def first_audio(engine, voice):
    start = time.perf_counter()
    if hasattr(engine, "stream_synthesize"):
        stream = engine.stream_synthesize(TEXT, voice, 1.0)
        next(iter(stream))
        first = time.perf_counter() - start
        for _ in stream:
            pass
        return first, "first PCM block"
    with tempfile.TemporaryDirectory() as d:
        engine.synthesize(TEXT, voice, 1.0, Path(d) / "c.wav")
    return time.perf_counter() - start, "complete WAV (file-only engine)"


def main():
    mode, name, root = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    base = rss_mib(os.getpid())
    t0 = time.perf_counter()
    if mode == "inproc":
        os.chdir(root)
        os.environ["HF_HUB_OFFLINE"] = "1"
        from aitts import model_worker

        engine = model_worker.local_engine(name, root)
    else:
        import aitts.daemon  # noqa: F401 - daemon import footprint
        from aitts.engines.managed import managed_engine

        engine = managed_engine(name, root)
    engine.warmup()
    voice = engine.list_voices()[0]
    cold, kind = first_audio(engine, voice)
    cold += 0  # first request after warmup
    ready = time.perf_counter() - t0
    warm = [first_audio(engine, voice)[0] for _ in range(RUNS)]
    result = {
        "mode": mode,
        "engine": name,
        "measure": kind,
        "warmup_plus_first_s": round(ready, 3),
        "first_after_warmup_ms": round(cold * 1000, 1),
        "warm_ms": [round(w * 1000, 1) for w in warm],
        "warm_median_ms": round(statistics.median(warm) * 1000, 1),
        "process_rss_mib_start": round(base, 1),
        "process_rss_mib_end": round(rss_mib(os.getpid()), 1),
        "process_maxrss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 1),
        "python": sys.version.split()[0],
    }
    proc = getattr(engine, "_process", None)
    if proc is not None:
        result["worker_rss_mib"] = round(rss_mib(proc.pid), 1)
    print(json.dumps(result))
    close = getattr(engine, "close", None)
    if close:
        close()


main()
```
