# Socket client crate: verification record

Change kind: feature. On 2026-11-16 the `aitts-client` crate was tested against
the acceptance criteria of
[issue #131](https://github.com/flyingrobots/AI-TTS/issues/131). This record is
agent-written and has not received human editorial review.

## Contract

- The client gets correct replies from the Python daemon for each operation in
  the golden transcripts.
- A daemon that is not running gives a typed error and exit status 2.
- A subscription connects again after the daemon restarts.

## Tests and oracles

All tests are medium size: owned temporary directories, loopback Unix sockets,
and threads. None reads ambient time, network, environment, or the user's home.

| Test file | Oracle |
|---|---|
| `tests/golden.rs` (2 tests) | The 30 records captured from the Python daemon at reference `38d967c` (`crates/aitts-protocol/tests/fixtures/wire`). A scripted peer replays each captured reply byte for byte. The client must send the captured request (18 witnesses) and return what `decode_reply` gives for the captured line; a subscription must yield the 9 captured events in order. |
| `tests/edges.rs` (6 tests) | Issue #131 test plan and `src/aitts/client.py` / `cli.py` (`EXIT_UNREACHABLE = 2`): absent socket, close in the middle of a reply, a reply that is not JSON, a silent peer, a 1 MiB reply, and a line over `MAX_RESPONSE_BYTES`. |
| `tests/split.rs` (2 properties, 32 cases each) | Any split of a captured reply, or of the acknowledgement and 9 events, gives the same parsed values as the whole lines. Proptest prints the failing split and seed; shrunk cases are kept in `split.proptest-regressions`. |
| `tests/daemon.rs` (3 tests) | The real `aitts-daemon` serving the Python-written `golden.db`: `list` returns the input queue that the Python `Store` read (`golden.json`); a subscription returns `Resubscribed` and then a broadcast event after the daemon stops and a new daemon starts on the same socket; it returns `Unreachable` when every attempt fails. |

The scripted peer pauses 1 ms between chunks so that a split reaches separate
reads; the pause is pacing, not synchronization. The daemon test broadcasts
until the event arrives, because the daemon registers a subscriber just after
it acknowledges it.

## Observed RED

The tests were committed first against `todo!()` stubs. All 13 failed at the
stubs (`cargo test -p aitts-client --no-fail-fast`).

## Planted faults

Each fault was applied alone, and each made the named tests fail. Source files
were touched after each revert so that cargo rebuilt them.

| Fault | Failing tests |
|---|---|
| End of stream reported as `TimedOut` instead of `Closed` | `a_close_in_the_middle_of_a_reply_is_reported_as_closed`, both reconnect tests |
| Connect failure reported as `Io` | `an_absent_socket_is_unreachable_with_exit_status_2`, `a_subscription_reports_unreachable_when_every_attempt_fails` |
| `WouldBlock` not treated as a timeout (macOS read timeout) | `a_silent_daemon_times_out` |
| Line limit doubled | `a_line_over_the_response_limit_is_refused` |
| Newline scan offset not reset after a line | `a_split_event_stream_parses_as_the_whole_stream` |
| A decode failure returned as a successful error reply | `a_reply_that_is_not_json_is_an_error_not_success` |
| Reconnection returns an error after a successful subscribe | `a_subscription_connects_again_after_the_daemon_restarts` |
| Subscribe acknowledgement refused | every subscription test |

## Live Python daemon

Not in CI, because the Rust CI job has no Python environment. Run once by hand:
`tests/fixture_daemon.py` (fake engine and sink) served an owned temporary home,
and a throwaway example sent every request of the 8 request transcripts (19
requests, including `subscribe` as a request) through `Client::request`. All 19
replies decoded as typed non-error replies for their operations, and a parallel
subscription decoded 19 events before it timed out. The example was not
committed.

## Checks

`cargo fmt --check`, `cargo clippy --workspace --all-targets --locked -- -D
warnings`, `cargo test --workspace --locked`, and `cargo test --workspace
--release --locked` pass.

## Not verified

- The live Python daemon comparison is one manual run, not a CI test.
- Reconnection is tested against the Rust daemon, not the Python daemon.
