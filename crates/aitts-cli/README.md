# AI-TTS command-line client crate

`aitts-cli` builds an `ai-tts` binary in Rust. It needs no Python. It keeps the
Python `ai-tts` contract for the commands it has:

- the same subcommands, options, choices and positional arguments, with unique
  long-option prefixes (`--sens` for `--sensitivity`) and repeated options;
- the same request object for each command line, checked with the
  `aitts-protocol` request types before it is sent;
- the daemon reply printed as JSON, and the same exit statuses: 0 when the
  daemon accepted, 1 for a daemon error or a refused command line
  (`assign-voice` without a voice, `settings set` without a value), 2 for an
  unreachable daemon or an argument the grammar refuses;
- the socket from `--socket`, then `AI_TTS_SOCKET`, then
  `AI_TTS_HOME/ai-tts.sock`, then
  `~/Library/Application Support/ai-tts/ai-tts.sock`.

`wait ID` and `say --wait` subscribe to daemon events first, then read the
utterance's current state, then read events until it reaches a terminal state
(`Played`, `Skipped`, `Cancelled` or `Failed`). They print `final_state` and
exit 0 only for `Played`, and 3 for the other terminal states. With
`--timeout SECONDS`, a wait that passes its deadline prints an `unreachable`
error and exits 2. Without it, the wait has no limit; held playback (a pause)
only delays the result. If the subscription connects again after a failure,
the state is read again, because events sent in between are lost.

A request that the protocol types refuse (for example an unknown `--set` key)
is not sent. The client prints a `bad_request` error and exits 1, which is what
the daemon answers for that request.

## MCP server

`ai-tts mcp`, or this binary started under the name `ai-tts-mcp`, is an MCP
server on standard input and output (part of issue #139). It writes only
newline-delimited JSON-RPC 2.0 replies to standard output and gives no reply
to a line that is not a JSON-RPC request. `initialize`, protocol version
negotiation, `ping`, and `tools/list` (the 21 tools of the Python server, from
`src/mcp_tools.json`) answer as the Python `ai-tts-mcp` does. `tools/call` works for
all 21 tools: one daemon request each, the reply without `ok` checked against
the tool's recorded output schema with defaults filled, and
`structuredContent` plus the same JSON as text. Arguments are checked against
the tool's input schema first, with Pydantic's lax conversions (a numeric
string for a number, a whole float for an integer, `0`/`1` or a yes/no word
for a boolean), and `NonEmptyText` fields stripped. A refused call sends no
daemon request. A daemon error, an unreachable daemon, or a reply outside the
schema gives an `isError` result with the Python text
`Error executing tool NAME: CODE: MESSAGE`. `make install` installs this
binary as `ai-tts-mcp`; `make install AITTS_MCP=python` rolls back to the
Python server (see the README).

## Terminal dashboard

`aitts_cli::tui::Dashboard` holds the dashboard's state (part of issue #140):
what it shows from daemon snapshots and events, and what each key does. It
draws nothing and opens no socket; the caller gives it snapshots, events, keys
and the time. It matches the Python `SpeechTUI` on recorded scenarios
(`tests/fixtures/tui_parity.json`). `aitts_cli::tui::draw` draws it with
ratatui in the Python layout: header, a rounded now-playing card (details,
progress, at most five lines of spoken text, meter), the queue and history
tables with the selected row reversed in the focused table, the status line
and the footer. The event loop and `ai-tts tui` itself follow; until then
`ai-tts tui` runs the Python dashboard.

## Commands it does not run itself

- `daemon` and `tui`. The binary hands them, with all arguments, to the
  Python `ai-tts-py` in its own directory (else on `PATH`), and exits 1 if that
  cannot start. The MCP server is the separate `ai-tts-mcp` program.

`make install` installs this binary as `ai-tts`; `make install AITTS_CLI=python`
rolls back to the Python CLI (see the README).

## Tests

`tests/parity.rs` runs every row of `tests/fixtures/cli_parity.json` at the
repository root. `tests/test_cli_parity_table.py` checks the same table against
the Python CLI. `tests/live.rs` compares the printed JSON with the reply of the
real `aitts-daemon`. The record is in
`docs/testing-evidence/2026-11-16-rust-cli.md`.
