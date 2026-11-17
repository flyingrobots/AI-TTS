# Rust clip-evidence records — 2026-11-17

Part 4 of issue #136: `aitts_artifacts::records::EvidenceRecorder` (`prepare`,
`record`, `generated`). Agent-written evidence, not human acceptance. Change
kind: feature. The Python daemon is unchanged. `submitted` and
`audio_generated` are not ported.

## Oracle

`crates/aitts-artifacts/tests/fixtures/records` is what the Python `ClipEvidence`
writers leave for one scenario (`uv run python
scripts/generate_evidence_record_fixtures.py`): `prepare`, two `record` calls, a
`generated`, an oversized event, and six events that rotate `clip-b`'s log. The
script steps both clocks by one second per reading, fixes the session and the
runtime, and lowers the log limit to 400 bytes. The Rust test runs the same
scenario with the same clocks and limit and compares the results parsed: JSON
files as values, each log line as a value, and text files as bytes.

| Promise | Test |
|---|---|
| Same files as Python | `the_clip_directories_hold_the_python_file_names` |
| Same JSON records | `json_records_equal_the_python_records` |
| Same events, rotation and omission rows | `event_logs_equal_the_python_logs_line_by_line` |
| Same text files | `text_records_have_the_python_bytes` |
| Rotation at the Python byte limit (Python line length from the fixture) | `two_python_length_lines_fit_a_limit_of_exactly_their_size`, `two_python_length_lines_rotate_under_a_limit_one_byte_smaller` |
| Python's 1 MiB event limit | `an_event_over_the_python_limit_is_replaced_by_an_omission_row` |
| Owner-only (8 files, 3 directories) | `every_record_file_and_directory_is_owner_only` |
| Symbolic links and escaping identities refused | three refusal tests |

## RED to GREEN

Commit `37f5af1` added the fixtures and 9 tests against a stub that returned
errors: 6 failed. The 3 refusal tests passed against the stub because it refuses
everything; the faults below show they guard their checks. After the
implementation all 9 passed. Calibration then found that a one-space change in
line spacing survived (it did not move a rotation in the scenario), so the two
rotation-boundary tests were added; they fail on any line-length difference.

## Calibration

One fault at a time in `src/records.rs`, source restored and compared after each.

| Fault | Failing tests |
|---|---|
| No space after `:` | boundary (one byte smaller) |
| No space after `,` in objects | boundary (one byte smaller) |
| Two spaces after `:` | boundary (exact size) |
| No oversized-event rule | logs, file names, owner-only, 1 MiB |
| Rotation deletes instead of renames | logs, file names, owner-only |
| Rotation note text changed | text files |
| `speed` missing | JSON records |
| Clock ignored for `captured_at` | JSON records, logs |
| `details` dropped | logs, 1 MiB, boundary |
| No `started` event | logs |
| Playback written to the synthesis log | logs, file names, owner-only, log link |
| No `source.txt` | text files, file names, owner-only |
| Clip directory with default mode | owner-only |
| No identity check | escaping identity |

Removing `O_NOFOLLOW` from the append survived: `ensure_private_file` already
refuses a link at that path just before, so the append flag only narrows a race
window that a single-threaded test cannot open.

## Repeated runs

10 shuffled runs (`RUSTC_BOOTSTRAP=1 cargo test -p aitts-artifacts --test
evidence_records -- -Z unstable-options --shuffle`): all 11 tests passed each time.
