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

## Not yet in this crate

- `daemon`, `tui` and `mcp`, which are out of scope for issue #138.
- Installing this binary in place of the Python `ai-tts`.

## Tests

`tests/parity.rs` runs every row of `tests/fixtures/cli_parity.json` at the
repository root. `tests/test_cli_parity_table.py` checks the same table against
the Python CLI. `tests/live.rs` compares the printed JSON with the reply of the
real `aitts-daemon`. The record is in
`docs/testing-evidence/2026-11-16-rust-cli.md`.
