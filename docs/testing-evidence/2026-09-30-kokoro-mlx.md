# Optional Kokoro MLX — September 30, 2026

Change-kind: feature

Prompt 2 of `PROMPTS.md`. The optional backend implements Engine and
PreparingEngine, with restart and evidence support. Configuration is persisted
for the next daemon start, or overridden by `daemon --engine`. Backend probing
checks platform, supported Python, installed package, and Metal availability;
unavailable MLX selects the reference Kokoro adapter and emits a static event.

## Upstream facts inspected

- [kokoro-mlx 0.1.2](https://github.com/gabrimatic/kokoro-mlx): package metadata
  requires Python >=3.10,<3.13 and MLX >=0.31.1. The public interface is
  `KokoroTTS.from_pretrained(local_directory)` and `generate(..., sample_rate=24000)`.
- Its config/model/voice loaders use local files when passed a directory.
  Warmup resolves a complete local snapshot, including the curated voice set,
  before constructing the upstream model. English spaCy assets are required
  explicitly to prevent implicit language-model installation.
- [MLX Metal API](https://ml-explore.github.io/mlx/build/html/python/metal.html)
  provides the availability probe. The lock resolves MLX/Metal 0.32.3.

The package is platform/Python-marked in the optional extra, preserving normal
installs on newer Python and other platforms. The reference backend remains
default. No claim of 180 MB memory consumption is made.

## Red/green and falsification

The first adapter test reached a no-op implementation and failed at
`output.is_file()` before synthesis was implemented. The green test reads the
WAV back and verifies 24 kHz, 2400 frames, 100 ms, and every sample at 0.125;
it also checks exact voice/speed/text forwarding, a local loader directory,
complete cached asset preparation, and no new asset resolution during synthesis.
These are small tests at the Engine/assets/file boundaries. Upstream inference
is an injected controlled result; real inference is recorded separately below.

Fifteen individual seeded faults caused assertion failures or `DID NOT RAISE`:
wrong duration, WAV rate, samples, voice, or speed; missing silent priming;
repeated model loading; omitted voice assets; asset lookup during synthesis;
ignored fallback, persisted preference, or CLI override; omitted format or
finite-sample validation; and a discarded settings write. Every edited module
was restored in `finally`, with its Python caches invalidated.

The daemon readiness test is medium. A thread event blocks warmup while a
pre-existing queued clip is inspected over an owned Unix socket. Removing the
readiness gate made the assertion see `Synthesizing` instead of `Queued`.
Releasing the event permits synthesis. No timing sleep or retry creates green.

Deletion criterion: remove these tests only when their adapter, configuration,
or preparation contracts are removed. They do not pin internal model layers.

## Real Apple Silicon acceptance

A separate Python 3.12.14 environment was synchronized from the frozen lock
with both extras and the English spaCy package. The running app environment was
not used for this experiment. The adapter downloaded missing model files,
loaded and primed the real upstream model, then synthesized a fixed public test
sentence after replacing Hugging Face download functions and Python socket
connect with functions that fail on attempted use. No speakers were used.

Observed:

- Metal availability: true.
- First warmup, including downloads: 67.810 seconds.
- Output: 125400 finite mono samples at 24000 Hz; duration 5225 ms.
- Warm synthesis: 0.290 seconds, approximately 0.0555 real-time factor.
- Peak process memory reported by `getrusage`: 992.61 MiB, not idle residency.
- Config SHA256: `5abb01e2403b072bf03d04fde160443e209d7a0dad49a423be15196b9b43c17f`.
- Weights SHA256: `4e9ecdf03b8b6cf906070390237feda473dc13327cb8d56a43deaa374c02acd8` (327115152 bytes).
- bm_daniel voice SHA256: `b195dec592ee024f57ddc5bf481464596082ba60998a2a295eba90bfc1064f4b`.

These are one-machine observations, not comparative benchmarks or CI gates.
The Python network guards supplement the inspected local-loader paths; they
are not a packet-level network audit. Tests do not establish subjective speech
quality or guarantee a specific memory footprint on every machine.

## Gates

600 Python tests passed (226 small, 374 medium), in 8.02 seconds wall time.
Ruff, format-check, mypy (104 source files), and diff checks passed. Frozen
Python 3.12 all-extras strict PyPI vulnerability audit reported no known
vulnerabilities. No Swift source changed.
