# Guided local speech model setup

Change-kind: feature. Settings discovers Kokoro, Kokoro MLX and Chatterbox Turbo,
installs missing models after an explicit download confirmation, reports setup
phases, offers cancellation/retry, and makes default selection a separate action.
Selection is persisted and affects future admissions. Existing clips retain their
engine. Chatterbox falls back to its supported voice and generation speed.

## Boundaries and oracles

`test_model_setup.py` controls an owned installer tool boundary and temporary
runtime directories. Its oracle is complete publication after validation,
incumbent preservation, curated immutable snapshots, compatible worker protocol,
hash-checked dependencies, and owner-only runtime/diagnostic permissions. It also
enters through startup selection to verify persistence independent of the daemon's
optional packages. It is medium.

`test_model_setup_daemon.py` enters through the real owned Unix socket. Controlled
installer events hold downloads while admissions continue, verify single-job
exclusion and cancellation, and show that setup does not select a model. A failed
load with complete assets must rebuild on retry. The oracle is the setup and
future-admission behavior documented in README. It is medium.

`test_managed_engine.py` uses a real owned subprocess and the production JSONL
worker with a controlled model producer. Its oracle is exact WAV/PCM transfer,
actual-runtime provenance, bounded failure, offline restart, and absence of stale
PCM after an aborted producer. It is medium. `test_model_setup_cli.py` enters
through parsing/payload projection; its oracle is the documented setup/cancel IPC
contract and curated input allowlist. It is small.

`UnixSocketSpeechServiceTests` checks native typed command projection, complete
model setup state decoding, and compatibility with snapshots from old daemons.
It is medium, with the public daemon wire contract as oracle.

Retire these assertions when the corresponding installation, private worker, or
selection contract is removed or superseded by a stronger boundary check.

The [falsification receipt](2026-10-01-local-model-setup-calibration.json) records
named failed checks after seeded faults in manifest validation, publication,
cancellation, cleanup, permissions, dependency hashes, startup discovery,
language resource paths, streaming, provenance, engine publication, explicit
selection, retry, compatible speed, CLI projection, and native state decoding.
All mutations were restored. Complete local red logs are in
`.git/codex-scratch/model-setup-*-red.log`.

## Runtime and installed acceptance

Each model uses its own Python 3.12 environment under `model-runtimes`. Setup
stages its runtime and adapter, downloads an allowlisted pinned snapshot, performs
an offline warmup, and atomically publishes an owner-only manifest. Failed or
cancelled candidates are discarded. The daemon keeps current speech available
while downloading and briefly excludes synthesis to publish a ready worker.
Workers are stopped on cancellation, incomplete streams, explicit restart, and
daemon shutdown. Complete streams preserve their resident model.

Real installation exposed eSpeak's native fixed path buffer: a long Application
Support path fell back to the upstream package builder's unavailable data path.
Two setup attempts failed at that boundary before the correction. Workers now
start in their owned runtime and use a short relative language-data path. The
long-path assertion was falsified by restoring the absolute path.

Kokoro, Kokoro MLX, and Chatterbox were each installed with the frozen hashed
requirements and completed real offline warmup. The rebuilt app and daemon were
installed with `UV_REINSTALL_PACKAGE=ai-tts make install`; packaged runtime
requirements were verified in the installed wheel. The
[live receipt](2026-10-01-local-model-setup-live.json) records setup, selection,
and real generated speech through the installed daemon. Initial engine, voice,
speed, and playback hold were restored after checks. This verifies rendering;
physical listening and mouse-driven confirmation/cancellation remain manual UI
acceptance, separate from native projection and socket tests.

The runtime requirements are generated from the existing frozen `uv.lock`:
`uv export --frozen --no-default-groups --extra EXTRA --no-emit-project --output-file FILE`,
using `kokoro`, `mlx`, or `chatterbox`. The two Kokoro exports additionally contain
the same immutable English-language wheel required by the app installer, with
its SHA-256 (`1932429db727d4bff3deed6b34cfc05df17794f4a52eeb26cf8928f7c1a0fb85`).
Regenerate exports when changing the dependency lock and retain that hashed wheel
entry. Guided setup installs with `--require-hashes`. Models and downloaded
runtime generations are separate from the speech cache; there is no model
uninstall UI in this feature. Replaced valid generations are retained.

A saved local model whose runtime disappears now falls back to Kokoro, keeping
the daemon reachable for guided recovery. The new Chatterbox startup regression
was observed red with `HEAD`'s unmodified selection module and green with the
fallback. A per-clip Chatterbox override inherits its supported generation speed
without changing the global default; explicit unsupported speeds remain rejected.
The native speed slider is disabled for Chatterbox and explains playback rate.

Final local verification: 955 Python tests and 147 Swift tests passed; Python
lint and strict typing passed; Swift was built with warnings as errors. The
calibration receipt contains 31 retained red fault cases. Native model-state and
command assertions were falsified through the actual typed-to-wire projection.
