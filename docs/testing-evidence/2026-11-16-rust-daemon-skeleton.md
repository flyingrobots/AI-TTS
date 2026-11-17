# Rust daemon skeleton: verification record

Change kind: feature. On 2026-11-16 the `aitts-daemon` crate was tested against
the acceptance criteria of
[issue #143](https://github.com/flyingrobots/AI-TTS/issues/143). This record is
agent-written and has not received human editorial review.

## Contract

- The daemon refuses to start when a second daemon holds the lease.
- The socket has mode 0600.
- The read operations pass the conformance suite against a fixture database.
- A stop signal ends the process in the time limit.

The test plan adds: an old socket file from a dead process, 50 clients at one
time, a client that sends half a line, a slow subscriber, and random bytes on
the socket.

## Tests and oracles

All tests are medium size: owned temporary directories, loopback Unix sockets,
and threads or child processes. None reads ambient time, network, or the user's
home; the process tests clear the environment and set `AI_TTS_HOME`.

| Test file | Oracle |
|---|---|
| `crates/aitts-daemon/tests/read_operations.rs` (15 tests) | Each reply must decode through `aitts_protocol::decode_reply` for its operation, the shared wire contract. Rows, order, and settings must match `crates/aitts-store/tests/fixtures/golden.json`, which the Python `Store` read back from the Python-written `golden.db` that the daemon serves. |
| `crates/aitts-daemon/tests/socket.rs` (11 tests) | `src/aitts/ipc.py` and architecture section 5: one lease owner, a 0600 socket, stale-socket replacement, typed error replies, and no blocking between clients. |
| `crates/aitts-daemon/tests/process.rs` (3 tests) | The built `ai-ttsd` binary: a second process exits with `another daemon is already running`, SIGTERM ends the process successfully within 5 seconds and removes the socket, and a missing home is created with mode 0700. |
| `crates/aitts-store/tests/counts.rs` (1 test) | Python `Store.counts`: rows grouped by stored state, empty states omitted. |

The random-bytes property runs 64 generated single lines of up to 511 bytes.
Each must get a `bad_request` reply unless it decodes as a request, and the
daemon must then answer `status`. Proptest prints the failing input and seed.

## Observed RED

Before the implementation, the daemon tests did not compile (`cannot find
function start in crate aitts_daemon`, 14 times), and the store test did not
compile (`no method named counts found for struct Store`). With a placeholder
`main`, both process tests failed at `the daemon exited before serving`.
The private-home test was added after the first commit and failed on that
commit with `home mode was 755`.

## Failure demonstrations

Each line names a deliberate break, applied alone and then reverted, and the
check that failed.

| Break | Failed check |
|---|---|
| Lease accepts a `WouldBlock` lock | `a_second_daemon_is_refused_while_the_first_holds_the_lease`; `a_second_process_refuses_to_start_while_the_first_runs` (stderr named the live socket, not the lease) |
| Lease never released on stop | `the_lease_is_released_when_the_daemon_stops` |
| Socket mode 0644 | `the_socket_is_private_to_its_owner`: `socket mode was 644` |
| No stale-socket removal | `a_stale_socket_from_a_dead_process_is_replaced` |
| Non-socket entry removed | `a_non_socket_entry_at_the_socket_path_is_refused_and_kept` |
| Accept loop stops after 40 live connections | `fifty_clients_at_one_time_each_get_their_reply` |
| One global lock around each connection | `a_client_holding_half_a_line_does_not_block_other_clients` (reply timed out after 10 s) |
| Half a line at end of input dropped | `half_a_line_at_end_of_input_is_answered_as_one_request` |
| Oversized line closed without a reply | `an_oversized_request_line_is_refused_as_a_bad_request` |
| A full backlog keeps the subscriber | `a_slow_subscriber_does_not_block_other_subscribers`: `the lagging subscriber was never closed` |
| Contract refusals typed `internal` | `random_bytes_get_a_typed_error_and_the_daemon_keeps_serving` |
| 8-second sleep after the signal | `a_term_signal_ends_the_process_in_time_and_removes_the_socket` |
| Input queue reversed | `list_input_returns_the_python_input_queue_in_order` |
| Playback list served from the input queue | `list_playback_returns_the_python_playback_queue_in_order` |
| History reversed; history projected without history fields | `history_returns_terminal_work_newest_first_with_history_fields` (both) |
| History limit plus one | `history_honours_its_limit` |
| Zero limit accepted | `history_refuses_a_zero_limit_as_a_bad_request` |
| Projected text empty | `get_returns_the_stored_utterance` |
| Missing id typed `internal` | `get_of_an_unknown_id_is_not_found` |
| First state count dropped | `status_counts_every_stored_row_by_state`: `left: 3, right: 5` |
| Stored speed ignored | `settings_read_reports_the_stored_speed` |
| `settings` with `set` answered | `settings_with_an_update_is_refused_because_writes_are_out_of_scope` |
| Empty voice catalog | `voices_reports_the_configured_engine_catalog` |
| Input depth counted from playback | `metrics_queue_depth_matches_the_python_queues` |
| Plan not sorted by queue order | `snapshot_plan_orders_all_unfinished_work_by_queue_order` |
| `submit` answered with a status | `an_operation_that_changes_state_is_refused_as_a_bad_request` |
| Home created with mode 0755 | `a_missing_home_is_created_private_to_its_owner`: `home mode was 755` |
| Counts not sorted | `counts_group_every_row_by_state_and_omit_empty_states` |

`snapshot_reports_no_current_speech_because_this_daemon_plays_nothing` has no
failure demonstration: the daemon has no playback controller, so `current` is a
constant. The test documents that limit and will fail when playback is ported.

## Repetition

`cargo test -p aitts-daemon -p aitts-store --test counts --test socket --test
process --test read_operations --locked` ran 10 times: 30 passed and 0 failed
each time, with the default parallel test threads. The stable toolchain has no
test shuffling, so the runs were not shuffled.

## Not verified

- The suite compares against the Python store's reading of the fixture, not
  against replies from a running Python daemon. Status and snapshot fields
  that depend on the playback controller, the listener, or engines have no
  Python oracle here.
- Error messages are not compared with Python messages; only error types are.
- There is no load test beyond 50 clients and no fuzzing campaign beyond the
  64 property cases.
