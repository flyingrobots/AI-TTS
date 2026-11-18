# Rust synthesis driver review fixes — 2026-11-19

Fixes the CodeRabbit findings on PR #217 (part of issue #145).
Agent-written evidence, not human acceptance.
Change kind: bug fixes, plus test corrections.

## Changes

- **Start.** The driver takes no work before the socket is bound and
  accepting. Before `start_with` returns, the driver checks its spool
  directory; a missing one fails with `StartError::Io`.
  - The driver reads clips through the conductor (`Ledger::job`,
    `Request::Job`) and opens no store of its own, so no store-open failure can
    go unreported.
  - A failed start ends the API thread before releasing the driver, so it
    returns without waiting for driver work.
- **Stop.** `Running::stop` first tells the driver to take no new clip. The
  driver checks this before each playback turn and each synthesis turn.
- **Fairness.** Each driver step gives playback a turn, then synthesis.
- **Retained spools.** The spool of a kept clip that is no longer owed is
  closed and its file removed. A successful `AudioReady` retry keeps its spool.
- **Reports.** A `SynthesisFailed` report (clip missing or unreadable, never a
  guessed text) and playback reports that the ledger did not record are kept
  and resent before new work, with a doubling wait.
- **Pause.** The conductor lets the paused current speaker finish, so a sink
  that finishes during a pause ends the clip and resume does not replay it.
- **Observation.** `Synthesis::on_idle` is signalled at each idle or retry
  wait.

## Tests (`crates/aitts-daemon/tests/driven_synthesis.rs`)

Each finding has a test with a forced interleaving:

- gate engines and gate sinks report when they are reached and wait for the
  test;
- a SQLite trigger on the store refuses one state, standing in for a ledger
  failure;
- the driver's idle signal is the checkpoint that a planning or retry turn
  ran;
- the stop test learns that stop has begun when its open connection closes.

Where a test must not wake the driver, it reads the store through its own
connection.

| Finding | Test | Red before the fix |
|---|---|---|
| driver started before the socket | `a_failed_start_takes_no_recovered_work` | driver took work |
| silent driver start failure | `start_with_refuses_a_missing_spool_directory` | started Ok |
| playback starvation | `a_ready_clip_plays_while_later_synthesis_is_still_running` | timeout |
| retained spools of cancelled clips | `a_ready_clip_cancelled_while_held_releases_its_audio` | audio kept |
| ready report retry needs a request | `an_unrecorded_ready_report_is_retried_without_a_client_request` | timeout |
| playback report dropped | `an_unrecorded_playback_report_is_retried_until_the_clip_is_played` | stayed Playing |
| outcome during pause | `a_clip_that_finishes_during_a_pause_is_played_and_not_replayed` | stayed Paused |
| shutdown takes new work | `stop_takes_no_new_clip_after_the_one_in_the_sink` | started a clip |
| held test without a checkpoint | `a_held_queue_plans_without_playing_until_resume` | no checkpoint |
| wake test woken by polling | `a_submitted_clip_is_played_after_only_the_submit_and_resume_wakes` | passed; calibrated |
| early-stop sink survivor | `the_discarding_sink_reports_a_read_failure_after_some_frames` | passed; calibrated |

Two findings have no separate test:

- `SynthesisFailed` for a missing or unreadable clip goes through the same
  kept-report path that the playback-report test covers.
- Keeping the spool after a successful retry has no observable effect: the
  driver reopens the sealed file. The fix makes both paths store the spool
  through one `settle`.

## Calibration

Each fault was planted alone, each test run with a 45 s kill limit, and the
file restored in a `finally` block. Every fault below was caught:

| Fault | Failing tests |
|---|---|
| Driver works before the start gate | failed start |
| No spool directory check | missing spool directory |
| Synthesis before playback in a step | starvation |
| No eviction | cancelled ready clip |
| Unrecorded plain report dropped | playback report retry |
| Retry waits for a client request | ready and playback report retries |
| Paused speaker cannot finish | outcome during pause |
| No stop signal | stop |
| Stop not checked between turns | stop |
| Sink stops after the first frame | mid-stream read failure |
| API does not wake the driver | 10 of the driver tests |
| No idle signal | pause, held, ready retry |
| A held queue plays | held, cancelled ready clip |

Calibration first found three weak tests, which were corrected:

- With the start gate removed, the failed-start test **hung**. A failed start
  joined the driver while the API thread still held its wake signal; that order
  is now fixed in `start_inner`.
- The early-stop sink survived, because the read-failure test made only the
  header readable.
- The retry-without-request fault survived the ready-report test, because of
  a stale idle signal.

## Repeats

Ordinary repeats: `cargo test -q -p aitts-daemon --test driven_synthesis`, 10
times; all passed.
