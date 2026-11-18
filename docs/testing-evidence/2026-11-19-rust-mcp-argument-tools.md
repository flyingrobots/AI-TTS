# Rust MCP server, part 2b (tools with arguments): verification record

Change kind: feature. `tools/call` in `ai-tts mcp` was tested against
[issue #139](https://github.com/flyingrobots/AI-TTS/issues/139) for the 6
tools with arguments. Part 2a is in `2026-11-18-rust-mcp-tool-calls.md`. This
record is agent-written and has not received human editorial review.

## Contract

The Python 3.12 `ai-tts-mcp`, for `enqueue_speech`, `requeue_speech`,
`list_speech_history`, `set_captions_enabled`, `assign_speech_voice` and
`cancel_queued_speech`:

- arguments are checked against the tool's input schema, with Pydantic's lax
  conversions and `NonEmptyText` fields stripped, and defaults filled;
- a valid call sends the daemon request that `UnixSocketSpeechAdapter`
  builds (`submit` with `origin: MCP`; `assign_voice` with `release: true`
  when the voice is null) and returns as in part 2a;
- a refused call sends no daemon request and returns `isError` with text
  that starts `Error executing tool NAME:`, or is exactly
  `Error executing tool NAME` when `EnqueueSpeech` refuses an empty voice or
  source. Pydantic's own message after that prefix is not part of the
  contract.

## Tests and oracles

| Test | Size | Oracle |
|---|---|---|
| `tests/test_mcp_tool_parity.py` (66 cases, Python 3.12 only; one server process serves every case that has a peer) | medium | As in part 2a, with 44 new argument cases: valid calls, the lax conversions (`speed: 1` and `"1.25"`, `preempt: "yes"`, `limit: "3"` and `2.0`, `enabled: "off"` and `1`), stripping, null optional fields, an unknown key, and 21 refusals. |
| `crates/aitts-cli/tests/mcp_tools.rs`, cases | medium | The same 66 cases: the daemon requests exactly, the reply exactly, except the parsed text of a success and only the prefix (above) of a refusal. |
| `crates/aitts-cli/tests/mcp_tools.rs`, argument fuzz (1200 calls) | medium | A seeded corpus (`AITTS_FUZZ_SEED`, default 139, printed): a valid call per tool with up to two keys changed to near misses, extreme floats or random JSON. Every call gives a well-formed result; a success has text equal to its structured content and one request; a refusal has the prefix and no request; a failure has one request. Seed 139 gives 94 successes, 623 refusals and 483 daemon or schema failures, and the test requires each class to occur. |

## CI finding

The first CI run exceeded the medium tier's CPU budget (123.92 s of 120 s): each recorded case started its own Python server. The tie test now serves every case that has a peer from one server process, which is valid because each call completes before the next and the server keeps no per-call state that these tools read; the two no-daemon cases keep their own servers. The file's CPU fell from about 20 s to about 1 s locally, and a changed recorded request still fails its case.

## Observed RED

The tests were committed first, while these tools answered `Unknown tool`;
the case test failed for every argument case, and the fuzz test failed.

## Planted faults

| Fault | Failing test |
|---|---|
| `NonEmptyText` not stripped | cases (`  Hello.  `) |
| Numeric strings not converted | cases (`limit: "3"`) |
| Yes words not read as true | cases (`preempt: "yes"`) |
| Empty voice or source accepted | cases (request sent) |
| Input schema not enforced | cases (requests sent for refusals) |
| `origin: MCP` left out | cases |
| `release: true` left out | cases |
| `before` left out | cases |
| Captions always set to true | cases |
| A panic on a float of 1000 or more | fuzz (after extreme floats were added; it first survived) |

## Finding

The Python server refuses every `requeue_speech` result with
`invalid_response`: the daemon's requeue reply has `composite` and
`segment_count`, which `RequeueSpeechReceipt` does not allow. The Rust server
matches this; the recorded cases show it. Filed as #211.

## Repetition

The `aitts-cli` tests passed 10 times in a row; the Python file passed 10
times in a row under Python 3.12.

## Not verified

- Pydantic's lax conversions beyond those recorded (for example a boolean
  for a number).
- Whether a refused call is truly invalid in the fuzz test: it has no Python
  oracle in CI, so that is covered by the 21 recorded refusals only.
