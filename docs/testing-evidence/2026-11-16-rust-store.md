# Rust store validation — 2026-11-16

This record covers issue #135 and the new `aitts-store` crate. It is agent-written
evidence, not human acceptance. Change kind: feature. The Python store is unchanged.

## Oracles

- Python reads: `scripts/generate_store_fixtures.py` makes each fixture database
  with the Python `Store` and records what the Python `Store` reads back, after
  `recover()` for the recovery fixtures, at a controlled clock.
- Python operations: `golden_ops.rs` repeats the `golden` operations through Rust
  with the same clock readings; the Rust rows must equal the Python `golden.json`.
- Python schema: a new Rust database must have the same `sqlite_master` rows and
  `user_version` as the Python-written `golden.db`.
- Python reader: `tests/test_store_rust_interop.py` requires the Python `Store` to
  read `rust-written.db` exactly as it reads `golden.db`.
- Transaction rule: a seeded `RAISE(ABORT)` trigger faults the child cancellation
  inside a terminal transition; the parent and children must be unchanged.

| Acceptance criterion | Test |
|---|---|
| The crate reads a Python database correctly | `golden_database_reads_every_row_as_python_does` |
| Python opens a database the crate wrote | `test_python_reads_the_rust_written_database_as_its_own` |
| The schema version does not change | `opening_never_changes_the_schema_version`, `a_new_database_has_the_python_schema_and_version` |
| Restart recovery equals Python for the crash matrix | `restart_recovery_matches_python_after_each_crash_point` (Python stopped after commit 0, 1, 2, 3) |
| Edge: old database without `engine` | `old_database_without_engine_column_migrates_as_python_does` |
| Edge: database in the middle of streaming | `restart_recovery_matches_python_in_the_middle_of_streaming_jobs` |
| Property: random sequences give the same final state | `random_operation_sequences_end_in_the_python_state` |
| Failure mode: half-written transition | `a_fault_inside_a_terminal_transition_leaves_no_half_written_state` |

## RED to GREEN

The tests were written against an API whose operations returned an error.
`cargo test -p aitts-store --no-fail-fast` then failed 7 of 9 Rust tests: all four
Python-fixture tests, the fault test, and both writer tests. The two schema tests
passed from the start, because the schema module was written with them; they
were calibrated by the faults below. After the implementation, all 9 passed.

## Assertion calibration

A local driver applied one fault at a time to the production source, ran the
named test binary, required a test panic (not a compile failure), and restored
the exact source bytes.

| Fault | Detected by |
|---|---|
| `playback` column loses `DEFAULT 1` | `rust_writer` (schema) |
| Migration writes `PRAGMA user_version=1` | `rust_writer` (version) |
| Generation identity is not filled from audio paths | `python_fixtures` (legacy) |
| Recovery moves Playing to Queued, not Paused | `python_fixtures` (crash matrix) |
| Streaming recovery writes `playback_held=false` | `python_fixtures` (streaming) |
| Urgent priority is stored as `normal` | `rust_writer` |
| Terminal transition runs outside one transaction | `commit_fault` |

For the Python reader test, the urgent-as-normal fault was compiled into
`write_golden`, `rust-written.db` was regenerated, and the pytest failed on the
priority of `utt_0002`. The fixture was then regenerated from the restored source
and the test passed.

## Random operation sequences

`tests/support/sequences.rs` generates 128 sequences of 1 to 40 operations with
proptest at fixed seed 135: submissions (every priority and sensitivity, head
placement, segments, playback flag), explicit and legal-successor transitions of
parents and segments, settings, voice claim/pin/release, history removal and
clearing, and recovery. `write_sequences` stores them as `sequences.ops.json`.
The Python generator replays each sequence through the Python `Store` on its own
file and records each step's outcome and the final rows in `sequences.json`. The
Rust test regenerates the sequences, requires them to equal the corpus, replays
them through the Rust store on its own file, and compares outcomes and every row.
The driver sets the clock to `1000 + step` before each step in both stores.

The test passed when first run against the finished crate, so it was calibrated
with planted divergences in the Rust store, each reverted afterwards:

| Planted divergence | Result |
|---|---|
| `submit` stores every priority as `normal` | failed: case 0 rows |
| A terminal transition does not cancel unfinished children | failed: case 0 outcomes |
| An automatic claim replaces a pinned voice | failed: case 4 rows |
| Head placement ignores the terminal-state filter | failed: case 6 rows |
| Recovery moves a Playing parent to Queued | not detected |

The corpus rarely reaches a Playing parent before a recovery step, so the last
fault is caught only by the crash-matrix fixtures above. The corpus records the
Python result at generation time; Python store changes require regeneration.

## Reproduce

```console
cargo test -p aitts-store --locked
cargo run -p aitts-store --example write_sequences
uv run python scripts/generate_store_fixtures.py
uv run pytest tests/test_store_rust_interop.py
```

## Not verified

- The random-sequence corpus is fixed (128 cases); it is not re-randomized per run.
- The crate ports the operations listed in its README, not all 41 Python methods.
- Recovery is one Rust transaction; Python commits in steps. Equivalence is shown
  for the four crash points and the streaming fixture, not for every database.
- Behaviour under a different SQLite build than the bundled one is not tested.
