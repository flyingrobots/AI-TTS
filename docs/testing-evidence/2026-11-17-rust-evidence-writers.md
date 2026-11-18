# Rust clip-evidence writers `submitted` and `audio_generated` — 2026-11-17

Part 4b of issue #136. Agent-written evidence, not human acceptance. Change
kind: feature, plus a refactor of the spool's WAV header reading into
`src/wav.rs` (the 14 spool tests are unchanged and pass).

## Oracle

`crates/aitts-artifacts/tests/fixtures/writers` comes from `uv run python
scripts/generate_evidence_writer_fixtures.py`. `soundfile` writes the input WAVs:
PCM_16 mono with full-scale samples; PCM_24 mono; FLOAT stereo with NaN, ±inf,
1.0 and ±0.9999 (exactly the clipping threshold); and a 3-channel PCM_16 WAVEX
file (`WAVE_FORMAT_EXTENSIBLE`). Then the Python `ClipEvidence.submitted` and
`audio_generated` write `root/`, with `time.time()` pinned. The tests compare
`request.json` and `audio.json` as parsed JSON, and `source.txt` as bytes.

## RED to GREEN

Commit `a2dcbf5` added 7 tests against stubs: 5 failed. The 2 refusal tests
passed against the stub because it refuses everything; faults below calibrate
them. After the implementation all 7 passed. Calibration then found three
survivors, so the fixture gained the threshold samples and the WAVEX file, and
two tests were added (`an_extensible_three_channel_clip_gets_the_python_audio_record`,
`a_riff_file_that_is_not_wave_is_refused_without_a_record`).

## Calibration

| Fault | Failing tests |
|---|---|
| `op` kept in `arguments` | request |
| Wrong `source_blake3` | request |
| Clock ignored | request |
| No `source.txt` | source text |
| PCM_16 scaled by 32767 | PCM_16 |
| Clipping uses `>` (found survivor; caught after fixture change) | FLOAT |
| Peak without `abs` | PCM_16 |
| Non-finite samples not counted | FLOAT |
| Frames from 2-byte width | FLOAT, PCM_24 |
| Wrong audio BLAKE3 | all three formats |
| Subtype fixed to PCM_16 | PCM_24, FLOAT |
| PCM_24 low byte dropped | PCM_24 |
| FLOAT refused | FLOAT |
| 8-bit accepted as PCM_16 | PCM_16, unsupported format |
| Extensible tag not resolved (survivor; caught after WAVEX test) | WAVEX |
| Sample rate fixed | PCM_24, FLOAT, spool other-rate |
| No `WAVE` form check (survivor; caught after new test) | RIFF not WAVE |

## Repeated runs

10 shuffled runs of `evidence_writers` and `spool`
(`RUSTC_BOOTSTRAP=1 cargo test -p aitts-artifacts --test evidence_writers --test
spool -- -Z unstable-options --shuffle`): all passed.

## Not covered

`soundfile` reads more formats than the daemon writes (for example 8-bit, 32-bit
integer, 64-bit float, and non-WAV containers). The Rust writer refuses those
with an error instead of writing a record. Python writes no record either; it
logs a warning.
