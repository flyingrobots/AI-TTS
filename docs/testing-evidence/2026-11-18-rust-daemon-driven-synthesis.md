# Rust daemon-driven synthesis and playback — 2026-11-18

Part of issue #145. Agent-written evidence, not human acceptance.
Change kind: feature.

`aitts_daemon::start_with(config, Synthesis)` starts a driver thread on its own
store connection. The driver:

1. asks the conductor for the next clip and runs `synthesis::synthesize`;
2. keeps the sealed spools until the conductor plans the device;
3. plays each transfer through a `Sink` and reports `PlaybackFinished`, or the
   new `PlaybackFailed`;
4. keeps synthesis reports (`Finished::Unreported`) and plain reports
   (`SynthesisFailed`, `PlaybackFinished`, `PlaybackFailed`) that the ledger did
   not record, and resends them before new work. The wait doubles from
   `Synthesis::retry_after` up to `MAX_RETRY_WAIT` and needs no client request.
   This was added by the review fixes in PR #220.

The API thread wakes the driver after each request, and the driver sleeps when
idle. `DiscardingSink` reads and discards every frame. `start(config)` still
runs no driver.

## Oracles

- The `aitts-engine` fake worker (worker protocol 2, real argument shape),
  whose known stream is each text byte twice.
- The conductor contract: a held queue does not play; a clip cancelled during
  synthesis is not played and its audio is removed; a failed synthesis does not
  stop later clips.

## Tests (`driven_synthesis.rs`, medium)

| Test | Promise |
|---|---|
| `a_submitted_clip_is_synthesized_and_played_through_the_sink` | the sink receives the known stream; the clip ends Played |
| `a_held_queue_synthesizes_but_plays_nothing_until_resume` | Ready while held, nothing played, Played after resume |
| `a_clip_cancelled_during_synthesis_is_not_played_and_leaves_no_audio` | forced: the gate engine reports it was reached, the cancel is answered, then the gate opens |
| `a_failed_synthesis_does_not_stop_later_clips` | the worker exits mid-stream; the next clip plays after `Engine::recover` |
| `the_discarding_sink_accepts_a_sealed_spool`, `..._reports_a_spool_that_ended_with_an_error` | `DiscardingSink` contract |

The daemon tests wait on observable states with a 20 s deadline; they never
use bare sleeps.

## RED to GREEN

Against the stub driver (it waited for stop and did nothing), 4 of 4 daemon
tests failed. The cancel test failed because the engine was never reached.
The implementation made all 4 pass. The two sink tests were written after the
implementation and passed; they are calibrated below.

## Calibration

Each fault was planted alone, each test run with a 60 s kill limit, and the
file restored in a `finally` block.

| Fault | Failing tests |
|---|---|
| API does not wake the driver | all four daemon tests |
| Finished playback reported as failed | played, held, failed-then-later |
| Driver stops after a failed synthesis | failed-then-later |
| Driver plays a ready clip without a plan | held queue |
| Sink ignores a spool error | sink error |

Two faults survived the first round. Dropping the in-memory ready spool is
equivalent: the driver reopens the sealed file. A sink that stops reading early
was **not** equivalent, as the record first claimed. A spool can return frames
and then a read error, which an early-stopping sink never sees. PR #220 adds
`the_discarding_sink_reports_a_read_failure_after_some_frames`, which catches
it.

## Repeats

Ordinary repeats:
`cargo test -q -p aitts-daemon --test driven_synthesis`, 10 times; all passed.

## Not covered (remaining for #145)

- Composite clips are spoken as their segments joined into one spool; segment
  rows are not advanced.
- A restored speaker plays from its start, not from where it was paused.
- `ai-ttsd`'s `main` does not call `start_with` yet.
- A replay does not reuse cached audio.
- Events.
