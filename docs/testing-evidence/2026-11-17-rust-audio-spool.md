# Rust audio spool — 2026-11-17

Part 2 of issue #136: `aitts_artifacts::spool::Spool`. Agent-written evidence,
not human acceptance. Change kind: feature. The Python daemon is unchanged.

## Contract and oracles

The contract is the `Spool` API (`create`, `open_cached`, `append`, `fill`,
`read`, `seek`, `seal`, `finish`) and the WAV file it leaves.

- `aitts.streaming.SpoolingPCMStream`: the rules for reads, underflow (no samples,
  no end), `complete` after seal and drain, `ended` only after `finish`, seeks.
- Python's `wave` module: `tests/fixtures/python-cached.wav`, written with
  `wave.open(path, "wb")`, 1 channel, width 2, 24000 Hz, 10 frames where sample
  `i` is `i * 257` little-endian. A sealed Rust spool of the same samples must be
  byte-identical to it.
- A model that keeps every written byte (property test).

The Python stream runs a feeder thread. The Rust type has no thread: the owner
calls `fill`. So the "read while written" edge is a generated, replayable
interleaving of `append`, `fill`, `read` and `seek`, not a racy loop.

## Tests

| Test plan item | Test |
|---|---|
| Golden: Python WAV header | `a_sealed_spool_is_byte_identical_to_the_python_wav` |
| Golden: Python-written WAV read | `a_python_written_wav_streams_its_frames_and_is_unchanged` |
| Owner-only file, symbolic link refused | `a_new_spool_file_is_owner_only`, `a_symbolic_link_in_place_of_the_spool_is_refused` |
| Spool read while written | `a_read_during_production_returns_the_live_bytes`, property test |
| Partial file not read as complete | `a_truncated_cached_wav_reports_an_error_not_a_complete_read` |
| Property: reads give written bytes for random write/seek sequences | `reads_return_the_written_bytes_for_random_write_and_seek_sequences` (256 cases, ring capacity 1–7) and the named case `named_case_a_seek_past_the_written_end_waits_for_production` |

The property test prints `spool property seed <n>` and a replay command, and
reads `PROPTEST_RNG_SEED` (CI sets 130); without it the seed is random. It
classifies its corpus: at least 129 of 256 cases must read frames (seed 1821994119:
239). No counterexample was found, so no corpus file is committed.

## RED to GREEN

Commit 1 added the tests against a stub `Spool` whose operations return errors.
`cargo test -p aitts-artifacts --no-fail-fast`: 12 of 14 `spool` tests and both
property tests failed. The two that passed against the stub (symbolic link
refused, other sample rate refused) pass because the stub refuses everything;
the faults below show they guard their checks. After the implementation all 16
passed.

## Calibration

One fault at a time in `src/spool.rs`, `PROPTEST_RNG_SEED=130`, source restored
and compared after each.

| Fault | Failing tests |
|---|---|
| Live append ignores backlog | named case, property |
| Seek keeps the ring | named case, property |
| Seek leaves the feed offset | backward seek, named case, property |
| `ended` without `finish` | sealed-drained, underflow |
| `complete` needs `finish` | sealed-drained |
| Append fills the ring past capacity | overflow, property |
| RIFF size wrong | byte-identical WAV |
| No sample-rate check | other rate refused |
| No 0600 mode, no `O_NOFOLLOW` | owner-only, symbolic link |
| Read error dropped | truncated cached WAV |
| Half sample accepted | half sample |
| Append after seal accepted | after seal |
| `finish` error dropped | finish error |
| Position never advances | 6 tests |

The first run found that the cached-WAV test looped until `ended` and hung under
the last fault; it now reads a bounded 8 times and asserts `ended`.

## Repeated runs

10 runs, shuffled: `RUSTC_BOOTSTRAP=1 cargo test -p aitts-artifacts --test spool
--test spool_property -- -Z unstable-options --shuffle`. All 10 passed with a
new shuffle seed and a new property seed each run.

Not covered here: the full-disk edge (part 4).
