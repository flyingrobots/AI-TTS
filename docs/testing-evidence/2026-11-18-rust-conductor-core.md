# Rust conductor queue state core — 2026-11-18

Part 1 of issue #145. Agent-written evidence, not human acceptance.
Change kind: feature. `aitts_daemon::conductor` is pure state: no thread, I/O,
persistence or audio. The tests are small (one process, no threads).

## Oracles

- Conformance (`crates/aitts-daemon/tests/conductor.rs`): the Python rules read as
  the specification: `store.py` `clear_pending` and `reorder_pending`, `daemon.py`
  `_op_cancel` and `_op_clear`, and `playback.py` `_plan_preemption`,
  `_restore_preempted`, `clear_preempted` and `_hold`.
- Property (`crates/aitts-daemon/tests/conductor_property.rs`): a plain list model
  written from those rules, not from the conductor: normal work joins the back,
  urgent work the front, cancel and failure remove, clear empties, reorder
  replaces. 256 cases of up to 40 steps; fixed seed 130 unless
  `PROPTEST_RNG_SEED` is set.

| Test plan item | Test |
|---|---|
| Submit, cancel, clear, reorder, pause, resume | `submit_*`, `cancel_*`, `reorder_*`, `pause_and_resume_*`, `clearing_during_a_preemption_*` |
| One failed synthesis does not stop later clips | `one_failed_synthesis_does_not_stop_later_clips` |
| Preemption and nested preemption order | `nested_preemption_restores_speakers_newest_first` |
| A clip is cancelled during synthesis | `audio_for_a_clip_cancelled_during_synthesis_is_discarded` |
| The queue is cleared during a preemption | `clearing_during_a_preemption_skips_suspended_speakers_and_keeps_the_alert` |
| A hold arrives with the first audio | `a_hold_taken_with_the_first_audio_keeps_the_device_idle` |
| Random operation sequences give the model plan | `random_operations_give_the_model_plan` |

## RED to GREEN

Commit `311294a` added the 13 tests against stubs that refused every command:
12 of 12 conformance tests and the property test failed (property: minimal
input `[Submit(Normal)]`, committed as the regression seed). Commit `17bb60a`
implemented the conductor; all 13 passed.

## Calibration

Each fault was planted alone, the two test files run, and the fault reverted.

| Fault | Failing tests |
|---|---|
| Urgent admitted as normal | submit order, nested preemption, clear during preemption, property |
| No duplicate check | duplicate submit |
| Cancel accepts a playing speaker | cancel the speaker on the device |
| Unknown id reported as duplicate | cancel an unknown id |
| Audio for a cancelled clip accepted | cancelled during synthesis |
| A failed synthesis returns to Queued | one failed synthesis, property |
| Reorder keys placed before the current speaker | reorder after the current speaker |
| No permutation check | partial reorder refused |
| Hold ignored by the planner | hold with the first audio |
| Hold leaves the speaker playing | pause and resume |
| Restore the oldest preempted speaker | nested preemption |
| Clear leaves preempted speakers paused | clear during preemption |

Two first-choice faults were equivalent and were replaced: allowing Playing in
the cancel match (the lifecycle transition still refuses it), and clearing
without emptying the stack (the speakers are still skipped).

## Repeats

10 runs of both files, each with a random `PROPTEST_RNG_SEED` and
`RUST_TEST_SHUFFLE=1`: all passed. Stable libtest may ignore the shuffle request;
the tests share no state.

## Not covered

Requeue, restart recovery with playback held, the conductor thread and its
message channel, the synthesis scheduler, and the conformance suite through the
socket remain for later parts of #145. The property corpus is not classified.
