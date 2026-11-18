# Rust MCP server, part 2a (tool calls without arguments): verification record

Change kind: feature. `tools/call` in `ai-tts mcp` was tested against
[issue #139](https://github.com/flyingrobots/AI-TTS/issues/139) for the 15
tools that take no arguments. The tools with arguments, their input
validation and the argument fuzz test are part 2b. Part 1 is in
`2026-11-18-rust-mcp-protocol.md`. This record is agent-written and has not
received human editorial review.

## Contract

The Python 3.12 `ai-tts-mcp` (`UnixSocketSpeechAdapter` and the Pydantic
public schemas), for each of these tools:

- the daemon request it sends;
- on success, `structuredContent` equal to the daemon reply without `ok`,
  checked against the tool's output schema with defaults filled and whole
  numbers in float fields written as floats, `isError: false`, and the same
  JSON as text content;
- on failure, `isError: true` and the text
  `Error executing tool NAME: CODE: MESSAGE`, where CODE is the daemon error
  type, `unreachable`, or `invalid_response` for a reply outside the schema;
- `Unknown tool: NAME` for a name it does not have.

## Tests and oracles

| Test | Size | Oracle |
|---|---|---|
| `tests/test_mcp_tool_parity.py` (24 cases, Python 3.12 only) | medium | The Python server against a scripted socket peer that replays daemon replies captured once from `tests/fixture_daemon.py`. It keeps `tests/fixtures/mcp_tool_calls.json` equal to what the Python server sends and replies. |
| `crates/aitts-cli/tests/mcp_tools.rs`, cases | medium | The same 24 cases, served in process with a scripted peer. The daemon requests and the whole reply are compared exactly, except that the text of a successful result is compared as parsed JSON: it is Python's `json.dumps` of the structured result, and its key order and spacing are presentation. |
| `crates/aitts-cli/tests/mcp_tools.rs`, property (256 cases) | medium | Any recorded reply, or one with a field replaced by random JSON, gives `isError` and either an error text or a structured result whose text is the same JSON; no panic. |

Cases beyond one per tool: playback held (status with a held queue), a
daemon `not_found` error, a reply with an extra field, a plan item whose id
does not match the utterance-id pattern, captions turned on, whole numbers in
float fields, no daemon, and an unknown tool. `next_speech_chunk` and
`previous_speech_chunk` are recorded as `illegal_state` errors, because the
fixture daemon has no chunked document.

## Observed RED

The tests were committed first, while `tools/call` returned a JSON-RPC error;
the case test failed for every case.

## Planted faults

| Fault | Failing cases |
|---|---|
| `ok` kept in the result | every successful case (`invalid_response`) |
| No schema check | list_speech_queue (bad id), speech_status (extra field) |
| Defaults not filled | list_speech_queue |
| Whole numbers kept as integers in float fields | speech_metrics (integral) |
| Python `[Errno N]` text not reproduced | speech_status (no daemon) |
| Error code left out of the text | the three error cases |
| Queue read from `items`, not `plan` | list_speech_queue |
| Captions read from `earcon_enabled` | get_caption_settings (captions on) |
| `clear` sent with queue `input` | clear_speech_queue (request) |
| Utterance-id pattern not checked | list_speech_queue (bad id) |
| Text content not the structured JSON | the property test |

Three faults first survived (whole numbers, captions, id pattern); the
integral-metrics, captions-on and bad-id cases were added for them.

## Repetition

The `aitts-cli` tests passed 10 times in a row (stable libtest has no
shuffle); the Python file passed 10 times in a row under Python 3.12.

## Not verified

- The tools with arguments (part 2b).
- A success result for `next_speech_chunk` and `previous_speech_chunk`.
- Pydantic's lax conversions beyond whole-number floats (for example a
  numeric string for an integer field).
- Text content byte for byte (see above).
