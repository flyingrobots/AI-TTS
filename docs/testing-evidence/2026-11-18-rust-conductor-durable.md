# Rust conductor persistence, restart and requeue — 2026-11-18

Part 2 of issue #145. Agent-written evidence, not human acceptance.
Change kind: feature. Tests are small: in-memory SQLite, one thread, no files.

## Design under test

`conductor::durable::Durable` runs each call on a copy of the conductor,
records the state and order differences through a `Ledger`, and keeps the copy
only when the record succeeds. `StoreLedger` writes through `aitts-store`
(which gains `Queue::reorder`). Recovery runs `Queue::recover`, reads the input
and playback queues, and builds a conductor with the hold taken; paused
speakers restore earliest queue position first. Submissions are not recorded:
the caller stores an utterance before submitting it. `Command::Requeue` admits
a replay of a history item.

## Oracles

- Python `Store.recover` (Synthesizing returns to Queued, Playing comes back
  Paused) and the rule that a restart keeps playback held.
- Python `_op_requeue`: only a terminal item may be re-queued; urgent and
  preempt replays go to the head.
- Crash oracle: after a crash, the recovered queue equals the in-memory state
  before the failed call, with the recovery mapping applied.

## Fault matrix

A crash is a `Ledger` call that fails, injected by a wrapper on a schedule.

| Phase | Fault | Test |
|---|---|---|
| Record | Fail call N, for every N, until the workload completes (11 crashes witnessed) | `crash_at_every_record_leaves_the_state_before_the_failed_call` |
| Record | Memory after a failed record | `a_failed_record_leaves_memory_unchanged` |
| Recover | Before the store repair | `a_crash_before_the_repair_is_recovered_by_the_next_start` |
| Recover | After the repair commits, before the queue is read | `a_crash_after_the_repair_is_recovered_by_the_next_start` |
| Record | Torn write inside one record (the store commits each transition separately) | not covered |
| Recover | A second crash during a retried recovery | not covered |

## Corpus classification (rule 5)

`the_generated_corpus_exercises_every_operation_class` regenerates the property
corpus with the property's seed, runs each case, and counts the cases with at
least one effective step per class. Every class must occur in a tenth of the
cases. Seed 130, 256 cases: urgent submit 216, cancel 181, ready 90, fail 60,
clear 142, reorder 116. The seed is printed with the counts.

## RED to GREEN

Commit `a481984` added the tests against stubs: 3 of 15 conductor tests and 5
of 5 durability tests failed on their assertions. The classification test
passed from the start (it checks the generator), so it was calibrated by a
planted fault instead. Commit `9a9c078` implemented the change; all passed. It
also corrected the durability workload, which had not released the hold that
recovery takes, and bounded the crash loop at 64 calls.

## Calibration

| Fault | Failing tests |
|---|---|
| Requeue ignores priority | urgent requeue |
| Requeue accepts an unfinished source | requeue refuses non-history |
| Restored queue not held | all 4 restart and crash tests, restored preemption |
| Restore latest position first | restored preemption |
| Memory changed before the record | failed record leaves memory unchanged |
| Order changes not recorded | restart, every-record crash, both recovery crashes |
| No store repair in recovery | restart, every-record crash, both recovery crashes |
| Reorder transaction not committed | restart, every-record crash, both recovery crashes |
| Playback queue not read in recovery | restart, every-record crash, both recovery crashes |
| Generator never fails synthesis | corpus classification |

## Repeats

10 runs of the three files with random `PROPTEST_RNG_SEED` values and
`RUST_TEST_SHUFFLE=1`: all passed, including the classification floor.

## Known limitation

After a restart the conductor holds only unfinished clips, while the store
places a normal submission after all history. Later parts must give a submitted
clip the key the store assigned.
