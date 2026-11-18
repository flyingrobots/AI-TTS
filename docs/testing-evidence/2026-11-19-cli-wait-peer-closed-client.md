# CLI wait test peer and a closed client — 2026-11-19

Closes issue #223. Agent-written evidence, not human acceptance.
Change kind: bug fix in test infrastructure.

The fake daemon in `crates/aitts-cli/tests/wait.rs` unwrapped the write of
each reply. When the client had already passed its deadline and closed, the
write failed with `BrokenPipe` and the peer thread panicked. This failed CI on
PR #222, in a test that PR did not change.

## Red

The peer can now hold one reply until the test releases it
(`serve_gated`). `a_reply_to_a_client_that_already_gave_up_is_not_a_peer_failure`
releases the `get` reply only after `wait --timeout 0` has returned and closed
its connection. It failed in 5 of 5 runs on main: "the peer failed writing to
a closed client".

## Fix

The peer ignores a failed reply write, as it already did for event writes. A
closed client is the client's outcome, which each test asserts. No sleeps or
retries were added.

## Green

`cargo test -q -p aitts-cli --test wait`: 10 of 10 runs passed,
including the forced case.

The other `aitts-cli` fake peers (`tests/support/mod.rs`,
`tests/mcp_tools.rs`) already ignore reply writes to a closed client.
`tests/live.rs` and `tests/mcp_stdio.rs` write only from the client side.

## Observed, not changed

With the `get` reply held, `wait --timeout 0` returned only after about 10 s:
the deadline does not bound the read of the `get` reply. This is filed
separately.
