# Rust MCP server, part 1 (protocol and tool catalog): verification record

Change kind: feature. `ai-tts mcp` in the `aitts-cli` crate was tested against
[issue #139](https://github.com/flyingrobots/AI-TTS/issues/139) for the
protocol and tool-catalog parts. Tool calls are part 2. This record is
agent-written and has not received human editorial review.

## Contract

The replies of the Python `ai-tts-mcp` (MCP SDK 2.x) to the same messages:

- `initialize`: capabilities, instructions, `serverInfo`; the requested
  protocol version when it is 2024-11-05, 2025-03-26, 2025-06-18 or
  2025-11-25, otherwise 2025-11-25; `-32602` for missing or wrong params.
- `ping` at any time; `tools/list`, `prompts/list`, `resources/list` and
  `resources/templates/list` only after `initialize` (`-32602` before);
  `-32601` with the method as `data` for an unknown method.
- No reply to a notification, to a line that is not JSON, or to an object
  without `"jsonrpc": "2.0"`.
- The 21 tools, with names, descriptions, annotations and input and output
  schemas. (The issue says 16; the Python server has 21.)
- Standard output carries only JSON-RPC lines.

## Tests and oracles

| Test | Size | Oracle |
|---|---|---|
| `tests/test_mcp_parity_table.py` (17 sessions, 1 catalog test) | medium | A fresh Python `ai-tts-mcp` subprocess per session; a message with no reply in 2 s is recorded as `null`. It keeps `tests/fixtures/mcp_session.json` and `crates/aitts-cli/src/mcp_tools.json` equal to the Python server. |
| `crates/aitts-cli/tests/mcp_session.rs`, sessions | small | The same session file, served in process; the replies must equal the non-null recorded replies, in order. |
| `crates/aitts-cli/tests/mcp_session.rs`, property (512 cases) | small | Random requests, notifications and arbitrary lines give only JSON-RPC 2.0 objects with exactly one of `result` or `error`, and no panic. |
| `crates/aitts-cli/tests/mcp_stdio.rs` (2 tests) | medium | The built binary as `ai-tts mcp` and through an `ai-tts-mcp` symbolic link: exit 0, every stdout line is JSON, and replies answer ids 1 and 2 only (a `not json` line and a notification get none). |

## Observed RED

The tests were committed first against a `todo!()` stub of
`aitts_cli::mcp::serve`; all 4 Rust tests failed.

## Planted faults

| Fault | Failing tests |
|---|---|
| Any protocol version echoed | sessions |
| Lists answered before `initialize` | sessions |
| A missing `jsonrpc` accepted | sessions |
| A banner line on stdout | sessions, property, both stdio tests |
| `serverInfo.version` 0.1.0 | sessions |
| One tool dropped from `tools/list` | sessions |
| `ai-tts-mcp` name not recognized | `the_name_ai_tts_mcp_starts_the_same_server` |
| An error reply that also has `result` | sessions, property |
| `capabilities` not required | sessions (added the two `initialize` sessions after this fault first survived) |
| `clientInfo.name`/`version` not required | sessions |
| Fixture `serverInfo.version` changed | 9 Python session tests |
| Catalog `required` emptied | `test_tool_catalog_is_the_python_tools_list` |

## Repetition

The Rust tests passed 10 times in a row (stable libtest has no shuffle); the
Python file passed 10 times under pytest-randomly.

## Not verified

- `tools/call`: part 2.
- A real agent host started against the Rust server.
- The MCP 2026-07-28 modern flow: the Python server answers it with
  2025-11-25 over `initialize`, and only that is matched.
