# Rust synthesis scheduler — 2026-11-18

Part 4 of issue #145. Agent-written evidence, not human acceptance.
Change kind: feature. `aitts_daemon::synthesis::synthesize` takes one clip the
conductor handed to synthesis, looks up its engine in the `aitts-engine`
registry, streams into an `aitts-artifacts` spool, seals it, and reports
`AudioReady` through the conductor mailbox. If the conductor answers
`Discarded` (or refuses), the spool file is removed. An engine, spool-create or
write failure finishes the spool with the error and reports `SynthesisFailed`.

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

The synthesis thread owns its own sender, and the tests drop theirs before the
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

## Repeats

10 runs with `RUST_TEST_SHUFFLE=1`: all passed.

## Not covered

A full disk during streaming (the spool's own tests cover it), restarting a
failed worker, and running synthesis ahead of playback in a loop. Socket wiring
is the final part.
