# Rust conductor bounded channel — 2026-11-18

Part 3 of issue #145. Agent-written evidence, not human acceptance.
Change kind: feature. `conductor::mailbox` adds a bounded channel to the one
conductor owner: `Mailbox::try_request` refuses with `Full`, `Mailbox::request`
waits for space and then the answer, and `Inbox::step` answers one request in
arrival order. Requests after `Shutdown` are dropped unanswered (`Closed`) and
change nothing. No thread is started by the crate; the caller runs the owner.

## Interleavings (annex: concurrency)

The owner is driven one request at a time with `Inbox::step` on the test
thread (controllable concurrency, rung 1). Each test except the last fills the
queue before the owner runs, so it has exactly one possible schedule.

| Promise | Schedule | Test |
|---|---|---|
| Arrival order | queue a, b, clips, shutdown; serve | `requests_are_answered_in_arrival_order` |
| Backpressure: a full channel refuses and changes nothing | capacity 1: a queued, b refused, step | `a_full_channel_refuses_without_sending` |
| Backpressure: a blocked sender enters after a step | capacity 1: a queued; a thread sends b; step a, step b | `a_blocked_sender_proceeds_when_the_owner_takes_a_message` |
| Shutdown with queued commands | before, shutdown, after queued; step, step | `shutdown_answers_earlier_requests_and_drops_later_ones` |
| Requests after the owner stops | inbox dropped | `a_request_after_the_owner_stops_is_closed` |
| Linearizability | two client threads, 5 submits each; the owner records its schedule | `concurrent_clients_give_a_history_equal_to_its_sequential_replay` |

The last test does not loop a racy workload: whatever schedule occurs is
recorded and checked against a sequential replay (oracle: linearizability) and
per-client program order. The schedule is printed on failure. Budget: one
schedule per run; the set of schedules it can see is not enumerated.

## RED to GREEN

Commit on this branch with the stubs (every send refused as `Closed`): 5 of 6
red; `a_request_after_the_owner_stops_is_closed` matched the stub's answer and
was calibrated instead. The implementation commit made all 6 pass.

## Calibration

Each fault was planted alone; every test ran with a 15 s kill limit, and the
file was restored in a `finally` block.

| Fault | Failing tests |
|---|---|
| Full reported as Closed | full channel |
| Closed reported as Full | after the owner stops |
| Shutdown does not stop the owner | full channel, shutdown with queued commands |
| No answer sent | blocked sender, linearizability, arrival order, shutdown |
| Command not applied | all except after-stop |
| Clips answered in reverse | arrival order |

The first round hung three tests on the "shutdown does not stop" and "no
answer" faults. The tests now drop unused senders and step the owner
explicitly, so those faults fail on named assertions.

## Repeats

10 runs with `RUST_TEST_SHUFFLE=1`, and one with `--test-threads=1`: all passed.
