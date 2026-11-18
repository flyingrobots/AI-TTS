# requeue_speech receipt (#211)

Change kind: bug fix.

## Contract

The protocol's `Requeued` reply (`crates/aitts-protocol/src/control_reply.rs`)
requires `composite` and `segment_count`. `RequeueSpeechReceipt` now models
both, with the defaults `EnqueueSpeechReceipt` uses (`segment_count = 1`,
`composite = false`).

## RED on unfixed main

- Python `tests/test_unix_socket_adapter.py::test_requeue_decodes_the_daemon_requeued_reply`:
  `SpeechServiceError: daemon returned a response outside the public RequeueSpeechReceipt schema`.
- Rust `crates/aitts-cli/tests/mcp_tools.rs::requeue_speech_returns_the_daemons_requeued_reply`:
  `structuredContent` was null; the result was `isError: true` with the same message.

## Re-recording

The fixtures were regenerated from the fixed Python 3.12 server, not edited:

- `UV_PYTHON=3.12 uv run --isolated --frozen --dev python -m tests.test_mcp_tool_parity`
- `UV_PYTHON=3.12 uv run --isolated --frozen --dev python -m tests.test_mcp_parity_table`
- `crates/aitts-cli/src/mcp_tools.json` is the `tools/list` result (id 3) of the
  first recorded session, written with `json.dumps(indent=1)`; the diff is the
  two new output-schema properties only.

`mcp_tool_calls.json` re-captures the fixture daemon's replies, so ids,
timestamps and pids differ throughout. Its semantic change is that both valid
`requeue_speech` cases now succeed and return `composite` and `segment_count`.

## GREEN

Both new tests pass. The Python files (`test_unix_socket_adapter.py`,
`test_mcp_tool_parity.py`) passed 10 runs in a row under Python 3.12, and the
`aitts-cli` `mcp_tools` tests passed 10 runs in a row. The repository has no
test-shuffling plugin, so the Python runs were in file order.
