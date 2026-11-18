# ai-ttsd drives synthesis with the installed runtime — 2026-11-19

Part of issue #145. Agent-written evidence, not human acceptance.
Change kind: feature.

`aitts-engine` gains `installed`:

- `revision` and `voices`: the Python catalog's pinned revisions and Kokoro
  voices.
- `runtime`: Python `installed_runtime`. A runtime is used only when all of
  these hold:
  - the manifest is not a symbolic link;
  - its revision and worker protocol match the catalog;
  - its directory is a single `<model>-` name;
  - the root is not a link and holds the venv Python, the adapter and every
    pinned asset.
- `NotInstalled`: fails each clip with the model-setup instruction, as
  Python's managed engine does when no runtime is installed.

`ai-ttsd` lists Kokoro's voices and calls `start_with`. It uses the installed
runtime's worker, or `NotInstalled`, with spools under `<home>/spool`, and a
`DiscardingSink`: this binary has no audio device yet.

## Oracles

- The Python catalog sources, read as text so the catalogs cannot drift:
  `src/aitts/model_catalog.py` for revisions and
  `src/aitts/engines/kokoro.py` for `VOICES`.
- Python `installed_runtime`, read as the specification.
- The `aitts-engine` fake worker, installed as the runtime's Python, for the
  process test.

## Tests

- `crates/aitts-engine/tests/installed.rs`: 8 tests. Revisions and voices
  against Python; a complete runtime is found; another revision, another
  protocol, a directory with a parent step, a missing asset, and a link
  manifest are each refused.
- `crates/aitts-daemon/tests/process_synthesis.rs`: the `ai-ttsd` binary.
  With an installed fake runtime, a submitted clip reaches Played. Without
  one, the clip fails and the daemon keeps serving. The test waits until the
  socket accepts: the file appears at bind, before listen.

## RED to GREEN

Against the stubs, 3 of 8 engine tests and 2 of 2 process tests failed. The
five refusal tests passed, because the stub found nothing; they are
calibrated.

## Calibration

Each fault was planted alone, each test run with a 60 s kill limit, and the
file restored in a `finally` block. Every fault below was caught:

| Fault | Failing tests |
|---|---|
| Revision not checked | another revision |
| Protocol not checked | another protocol |
| Directory name not checked | parent-step directory (after the test correction) |
| Assets not checked | missing asset |
| Manifest link followed | link manifest |
| A voice dropped | voices against Python |
| `ai-ttsd` uses plain `start` | both process tests |
| `ai-ttsd` never uses the runtime | installed runtime plays |

## Repeats

Ordinary repeats of both files, 10 times each; all passed.

## Not covered

- An audio device sink.
- Engine selection other than Kokoro (the `engine` setting, `kokoro-mlx`,
  `chatterbox`).
- Model readiness reporting from the running worker.
