# Rust synthesis scheduler — 2026-11-18

Part 4 of issue #145. Agent-written evidence, not human acceptance.
Change kind: feature, then bug fixes for the review findings on PR #209.

`aitts_daemon::synthesis::synthesize` takes one clip that the conductor handed
to synthesis:

1. It finds the clip's engine in the `aitts-engine` registry.
2. It calls `Engine::recover`, so a failed worker restarts before this clip.
3. It streams the audio into a new `aitts-artifacts` spool and seals it.
4. It reports `AudioReady` or `SynthesisFailed` through the conductor mailbox.

The result of the report decides what happens to the audio:

- **Report recorded:** a ready clip returns its spool. A failed clip returns its
  error, plus the partial spool if one was created.
- **Clip no longer owed** (the conductor answers `Discarded` or refuses): the
  spool file is removed. An unlink error other than `NotFound` returns
  `CleanupFailed`.
- **Ledger did not record the report:** `Unreported` returns the report, the
  spool and the error, and nothing is removed. `retry` sends the report again
  without synthesizing again.
- **Conductor stopped before answering:** the unreported audio is removed, and
  the result is `Closed`.

A failure after the spool exists finishes it with the error. If
`Spool::create` itself fails, no spool exists, and the result carries no spool.
The first spool write error is reported over a later engine error.

## Oracles

- The `aitts-engine` fake worker (`crates/aitts-engine/tests/fixtures/fake_worker.py`)
  run through `WorkerSupervisor` in the real `python -m aitts.model_worker serve`
  argument shape, speaking worker protocol 2 with binary frames. Its known
  stream is each text byte twice; mode `random 5 exit` exits after some frames.
- The conductor contract (parts 1-3) and the spool contract: a finished spool
  returns only written frames, its error, and `ended`.

## Interleavings (annex: concurrency)

Synthesis runs on one scoped thread; the conductor owner is stepped on the test
thread, and a gate engine (wrapping the real worker) holds the stream until the
test opens it. Each test has one possible schedule.

| Promise | Forced schedule | Test |
|---|---|---|
| Ready audio is sealed and reported | synthesize; step AudioReady | `synthesis_seals_the_known_stream_and_marks_the_clip_ready` |
| Cancel during synthesis | engine held; step Cancel; open; step AudioReady (Discarded) | `audio_for_a_clip_cancelled_during_synthesis_is_discarded_and_its_file_removed` |
| Preempt audio finishing after a plan | engine held; step PlanPlayback (none); open; step AudioReady; plan | `preempting_audio_that_finishes_after_a_plan_step_takes_the_device_on_the_next_plan` |
| Worker exit mid-stream | synthesize; step SynthesisFailed | `a_worker_exit_mid_stream_fails_the_clip_and_keeps_a_partial_safe_spool` |
| Unknown engine | synthesize; step SynthesisFailed | `an_unknown_engine_fails_the_clip` |
| Failed worker restored before the next clip | clip a fails mid-stream; clip b | `a_failed_worker_is_restored_before_the_next_clip` |
| First write error kept | an engine sends half a sample, then fails | `the_first_write_failure_is_reported_over_a_later_engine_error` |
| Ledger refuses AudioReady | ledger refusing; step; retry with the ledger accepting | `a_ledger_refusing_audio_ready_keeps_the_sealed_audio_for_retry` |
| Ledger refuses SynthesisFailed | ledger refusing; step | `a_ledger_refusing_synthesis_failed_returns_the_failure_unreported` |
| Shutdown before the report | Shutdown answered first; synthesize | `a_shutdown_before_the_ready_report_removes_the_unreported_audio`, `a_shutdown_before_the_failure_report_removes_the_partial_audio` |
| Unlink denied for discarded audio | engine reached (gate signal); cancel; directory made read-only; open | `an_unremovable_discarded_file_is_reported_as_cleanup_failed` |
| A fixture path with an apostrophe | the worker is copied beside its launcher | `a_fixture_path_with_an_apostrophe_starts_the_worker` |

`aitts-artifacts` (`tests/spool_failures.rs`) adds
`a_zero_capacity_create_leaves_no_file` and
`a_reader_drains_the_written_prefix_after_a_producer_failure`.
`aitts-engine` adds `recover_restarts_a_failed_worker_for_the_next_request`.

Gates, inboxes and senders live inside the scope closure, so a failed
assertion drops them and releases the worker thread before the join. The
synthesis thread owns its own sender, and the tests drop theirs before the
owner waits, so a scheduler that returns without reporting ends the wait with
`Stopped` and fails on the named step assertion instead of hanging.

## RED to GREEN

The stub reported nothing: 5 of 5 failed on the owner-step assertion, none hung.
The implementation commit made all 5 pass.

## Calibration

Each fault was planted alone, each test run with a 20 s kill limit, and the file
restored in a `finally` block.

| Fault | Failing tests |
|---|---|
| Ready not reported | ready, cancel, preempt |
| Discarded spool file kept | cancel |
| Discarded answer treated as ready | cancel |
| Failed spool not finished | worker exit |
| Engine error ignored | worker exit |
| Failure reported as ready | worker exit, unknown engine |
| Partial spool dropped | worker exit |

## Review fixes: RED to GREEN

Commit `f4a1377` added the tests with the API changes as stubs that kept the
old behavior; commit `b86df05` fixed the behavior. Red on `f4a1377`: worker
restore (`Engine(WorkerExited)`), both ledger-refusal tests and both shutdown
tests (`Discarded`), first write error (`Engine(ModelFailed)`), both spool
tests, and the engine recover test. The cleanup-failure test was red on
`f4a1377` for a different reason: it raced the spool's creation. The gate now
signals when the engine is reached, and the old behavior was planted to show
the right red (below).

| Planted fault | Failing tests |
|---|---|
| Ledger failure discards the audio | both ledger-refusal tests |
| Closed keeps the audio | both shutdown tests |
| Any unlink error counts as removed | cleanup failure |
| Engine error reported before the write error | first write error |
| No recover before dispatch | worker restored |
| Seal skipped | ready (the WAV no longer reopens through `open_cached`) |
| The old launcher with the path in shell source | apostrophe path |
| An assertion fails before a gate opens | the preempt test fails and does not hang |
| Capacity checked after the file is opened | zero-capacity create |
| A producer error stops `fill` | drain written prefix |
| `WorkerSupervisor::recover` does nothing | engine recover |

## Repeats

These are ordinary repeats. Stable libtest does not shuffle: the
`RUST_TEST_SHUFFLE` variable needs `-Z unstable-options`. The commands, run 10
times each:

- `cargo test -q -p aitts-daemon --test synthesis`
- `cargo test -q -p aitts-artifacts --test spool_failures`

All passed.

## Not covered

A full disk during streaming (the spool's own tests cover it), and running synthesis ahead of playback in a loop. Socket wiring
is the final part.
