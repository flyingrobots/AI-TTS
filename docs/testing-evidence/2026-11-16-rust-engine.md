# Rust engine validation — 2026-11-16

This record covers issue #133 and the new `aitts-engine` crate. It is
agent-written evidence, not human acceptance. Change kind: feature. The Python
daemon is unchanged.

## Oracles

- Worker protocol: version 2 of `src/aitts/model_worker.py` (issue #126): a first
  control line `{"protocol": 2}`, JSON control replies, 4-byte big-endian
  length-prefixed PCM frames on descriptor 3, and an empty frame at stream end.
- The fake worker `crates/aitts-engine/tests/fixtures/fake_worker.py` speaks that
  protocol. It asserts the `-m aitts.model_worker serve MODEL ROOT FD` argument
  shape and gives a known stream: each text byte twice.
- Digests: `src/aitts/model_digests.json` (the Python setup's pins) and the
  FIPS 180-4 SHA-256 of `abc`.
- Loopback HTTP: the contract of `src/aitts/engines/openai_compatible.py`.

| Acceptance criterion or plan item | Test |
|---|---|
| The supervisor starts each of the three Python workers and streams audio | `each_python_worker_starts_and_streams_its_known_audio` |
| A worker that exits is reported as failed and can be restarted | `a_worker_that_exits_at_start_is_failed_until_restarted` |
| A silent worker is stopped with its child processes | `a_silent_worker_is_stopped_with_its_children` |
| Setup refuses a file whose digest is not pinned | `a_file_with_another_digest_is_refused`, `a_missing_or_linked_file_is_refused` |
| Edge: worker writes to the wrong pipe | `audio_on_the_control_pipe_is_an_invalid_response` |
| Edge: cancelled setup | `a_cancelled_setup_stops_with_cancelled` |
| Edge: other protocol version | `a_worker_of_another_protocol_version_is_refused` |
| Stress: random frame boundaries and exits | `random_frame_boundaries_and_exits_leave_no_process_and_no_partial_clip` (24 seeds; odd seeds exit) |
| Loopback only, no redirects, byte and length limits | `remote_and_unsafe_urls_are_refused`, `redirects_short_bodies_and_oversized_bodies_are_refused`, `a_known_body_reaches_the_sink_from_the_speech_path` |

All tests are medium (subprocesses, temporary files or a loopback socket) except
the two small unit tests in `registry` and `catalog`. The supervisor suite takes
about 2 seconds.

## RED to GREEN

The implementation was written before its tests, so no test was seen red on
missing code. Each load-bearing assertion was calibrated instead: a fault was
planted in the source, the suite was run, and the fault was reverted. Every
fault below made the named test fail; the clean source passes all 16 crate tests.

| Planted fault | Failing test |
|---|---|
| Stop signals only the leader, not its group | `a_silent_worker_is_stopped_with_its_children` |
| Handshake accepts any protocol version | `a_worker_of_another_protocol_version_is_refused` |
| A request respawns a failed worker | `a_worker_that_exits_at_start_is_failed_until_restarted` |
| A failed stream does not retire the worker | `random_frame_boundaries_...`, `a_silent_worker_...`, `audio_on_the_control_pipe_...` |
| A non-JSON control reply counts as success | `audio_on_the_control_pipe_is_an_invalid_response` |
| Digest comparison skipped | `a_file_with_another_digest_is_refused` |
| Symbolic links followed | `a_missing_or_linked_file_is_refused` |
| Cancel flag ignored | `a_cancelled_setup_stops_with_cancelled` |
| Non-loopback address accepted | `remote_and_unsafe_urls_are_refused` |
| Content-Length not compared | `redirects_short_bodies_and_oversized_bodies_are_refused` |
| HTTP status not checked | `redirects_short_bodies_and_oversized_bodies_are_refused` |

Two first calibrations exposed weak assertions, which were strengthened before
the final run. The random-exit case did not check that the failed worker was
retired, so it now asserts the `Failed` state and no process. The redirect case
had no body, so it passed by the empty-body rule; it now carries a body.

## Checks

Run locally on macOS with rustc 1.100.0 (CI pins 1.99.1): `cargo fmt --check`,
`cargo clippy --workspace --all-targets --locked -- -D warnings`, and
`cargo test --workspace --locked` and `--release --locked` pass.

## Not verified

- No real Python model worker was started; the model runtimes are not in CI.
- The `EPERM` zombie-only group case on Darwin is accepted without the `ps`
  confirmation that `scripts/run_with_deadline.py` uses.
- HTTPS loopback servers, guided download and runtime publication in Rust.
