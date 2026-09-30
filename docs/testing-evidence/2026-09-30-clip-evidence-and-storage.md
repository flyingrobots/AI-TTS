# Clip evidence, storage management, and menu controls

Change-kind: feature

Related bug fixes (build recovery and paused-output lifecycle) have separate
red-on-unfixed receipts in this directory. This feature adds per-artifact
provenance/reporting, generated-storage deletion and retention, caption placement,
and model/daemon controls. Tests enter through the owned filesystem, daemon
NDJSON boundary, and native adapter/presentation contracts.

## Contract checks

- `tests/test_clip_evidence.py` (medium): exact selected-file ZIP membership,
  source and audio bytes, BLAKE3 identity, generation/export environment separation,
  owner-only archive, explicit legacy gaps, exclusive destination, per-audio
  playback causes, and nested audio cache inventory/removal.
- `tests/test_generated_storage.py` (small, profile's owned-tmp-path exception):
  deletion of complete clip directories plus legacy WAVs, protection of active
  and unfinished files, refusal to follow symlinks/outside identities, byte counts,
  default Never and opt-in expiry by last activity. Time is an explicit input.
- `tests/test_ipc.py` additions (medium): clear history plus files preserves queued
  artifacts; retention values are stored and booleans rejected; failed model
  reload reports failed readiness and subsequent successful reload recovers.
- Swift suite (medium): exact storage/clear/reload request projection; daemon
  restart invokes `launchctl kickstart -k`; captions use the requested screen
  edge, including an offset secondary-screen coordinate system.

## Falsification receipts

Temporary product mutations were applied, each test run observed red, and original
source restored before final verification:

| Seeded fault | Detecting contract |
| --- | --- |
| Ignore protected flag during removal | complete deletion/active protection |
| Multiply retention window by ten | expiry selection |
| Ignore clear-history delete-files option | NDJSON clear-both |
| Persist Never instead of requested retention | NDJSON retention |
| Report ready after reload failure | NDJSON model lifecycle |
| Empty generation environment | selected-file ZIP |
| Replace source BLAKE3 with a wrong value | known UTF-8 `abc` BLAKE3 vector |
| Omit missing-audio warning | legacy report gaps |
| Truncate an existing report destination | exclusive export |
| Replace microphone pause cause with explicit control | per-audio playback cause log |
| Omit nested WAVs from cache inventory | nested inventory/removal |
| Omit `-k` from daemon restart | Swift launcher request |
| Swap top/bottom coordinates | Swift caption placement |
| Send `delete_files: false` | Swift storage/clear/reload projection |

An initial generation-environment mutation replacing the initialization snapshot
with a fresh snapshot survived because package data had not changed at synthesis
in that test. It was not counted as evidence. The wrong/empty generation snapshot
fault above was subsequently detected. These calibrations are targeted receipts,
not a mutation-score gate.

## Final verification and installed acceptance

- `make test`: 576 Python tests passed (215 small, 361 medium); 104 Swift tests
  passed. Python charged class times: 0.53s small / 6.99s medium, below 10s / 45s.
- `uv run ruff check .`: passed. `uv run mypy`: passed, 98 source files.
- `make app`: release app built with App Intents metadata and signed at
  `~/Applications/AI-TTS.app`.
- Updated installed Python package plus BLAKE3; restarted idle launch agent and app.
- Real installed Kokoro synthesized and played a short synthetic sentence. Its
  exported ZIP contained WAV, original/source text, request, audio identity,
  generation and model metadata, synthesis log, playback log, and manifest with
  **zero missing-evidence warnings**. Playback events included session start,
  stream open/close, and session end. Source BLAKE3 was 64 hexadecimal characters.
- Installed model reload completed successfully; PID stayed unchanged, readiness
  returned to ready, and active synthesis was zero.
- Read-only installed storage inventory succeeded with retention Never. User
  files were not deleted during live acceptance; destructive behavior was checked
  in owned temporary directories.

## Limits

Historical clips cannot acquire uncaptured generation/playback evidence. Individual
phase logs retain two 1 MiB files; rotation is disclosed in exported reports. WAV
cache eviction can precede configured retention and leave useful sidecars. Storage
retention defaults to Never. UI rendering and actual Finder/save-panel clicking
were not automated. The original long-day subjective popping on the other machine
still needs a captured report; the earlier synthetic paused-output regression is
not proof that every source of audible popping has been eliminated.

### Loose-emphasis assertion calibration (PR #26 follow-up)

Change-kind: bug fix (missing evidence only; no production/test changes).

For `test_markdown_speech_plan_strips_loose_formatting_asterisks`, temporarily
replace `_clean_spoken_text` with the identity function. The unchanged assertion
fails: actual `Here is * bold * text and ** spaced ** emphasis.` versus expected
`Here is bold text and spaced emphasis.`. The check reaches its exact output
assertion, so this is not a syntax/import failure. Restore the implementation;
the targeted assertion and all 12 segmentation tests pass. This supplies the
previously missing assertion-specific falsification record. Size: small; oracle:
approved Markdown-to-speech projection, as declared by the suite.
