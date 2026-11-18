# Rust command-line client, part 2 (waiting): verification record

Change kind: feature. On 2026-11-18 `wait` and `say --wait` in the
`aitts-cli` crate were tested against
[issue #138](https://github.com/flyingrobots/AI-TTS/issues/138). Part 1 is in
`2026-11-16-rust-cli.md`. This record is agent-written and has not received
human editorial review.

## Contract

From `aitts.cli` and `aitts.client.Client.wait_for_terminal`:

- the client subscribes before it reads the current state;
- it ends on the first `state_changed` event for its id with a terminal `to`;
- it prints `{"ok": true, "id", "final_state"}` for `wait`, and the submit
  reply with `final_state` added for `say --wait`;
- exit 0 only for `Played`, 3 for `Skipped`, `Cancelled` or `Failed`, 2 when
  `--timeout` passes, 1 for a daemon error such as an unknown id.

## Tests and oracles

`crates/aitts-cli/tests/wait.rs`, 7 tests, size medium (temporary directory,
loopback Unix socket, one peer thread). Replies come from the captured Python
daemon replies (`aitts-protocol/tests/fixtures/wire/submit.json`, with
`playback_held: true`, for the held queue) and the protocol `get` reply fixture.
The peer forces the order: it answers the subscription, then the `get`, and
only then writes events. No test sleeps or retries.

| Test | Edge |
|---|---|
| `wait_exits_zero_when_the_utterance_is_played` | request order `subscribe`, `get` |
| `wait_exits_three_for_each_terminal_state_except_played` | not Played |
| `wait_ignores_events_for_other_utterances_and_non_terminal_states` | other ids, `Playing`, other events |
| `wait_returns_a_state_that_is_already_terminal_without_an_event` | terminal before the wait |
| `wait_past_its_deadline_exits_two_as_unreachable` | `--timeout 0` on a queued item: the deadline has passed before the first read |
| `wait_for_an_unknown_id_reports_the_daemon_error` | `not_found` from `get`, exit 1 |
| `say_wait_in_a_held_queue_reports_the_submit_reply_and_final_state` | held queue, `Played` (0) and `Cancelled` (3) |

## Observed RED

The tests were committed first, while the client still refused waiting with
exit 1. All 7 failed. During GREEN, the `get` reply in the test was changed from
a `list` item (which does not match the `get` reply type) to the protocol `get`
fixture; that was a test fixture error, not a behavior change.

## Planted faults

Each fault was applied alone and reverted.

| Fault | Failing tests |
|---|---|
| Exit 0 for `Failed` instead of `Played` | 5 tests |
| Events for any id accepted | `wait_ignores_events_...` |
| `Playing` treated as terminal | `wait_ignores_events_...` |
| Deadline reported with exit 1 | `wait_past_its_deadline_...` |
| `say --wait` field named `final` | `say_wait_in_a_held_queue_...` |
| `say --wait` exits 0 for any state | `say_wait_in_a_held_queue_...` |
| A `get` error ignored | `wait_for_an_unknown_id_...` (it waits forever without a deadline, so the test passes `--timeout 5`; it fails in 5 s with exit 2) |

## Repetition

All `aitts-cli` tests passed 10 times in a row, and the workspace in debug and
release. Stable libtest has no shuffle option; each test owns its socket.

## Not verified

- A live wait against a daemon that plays audio: the Rust daemon refuses
  `submit`, and CI has no Python daemon in the Rust job.
- Python with `--timeout 0` makes its socket non-blocking; the exact Python
  failure there was not compared.
