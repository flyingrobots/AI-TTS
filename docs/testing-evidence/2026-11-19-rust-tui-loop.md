# Rust terminal dashboard, part 3 (loop, reconnect, terminal restore): verification record

Change kind: feature. The dashboard loop (`aitts_cli::tui::run`), the daemon
watcher (`watch`), the crossterm terminal session (`TerminalSession`) and
`start` were tested against
[issue #140](https://github.com/flyingrobots/AI-TTS/issues/140). Parts 1 and
2 are in `2026-11-19-rust-tui-model.md` and `2026-11-19-rust-tui-draw.md`.
This record is agent-written and has not received human editorial review.

## Contract

- The terminal is restored after `q`, after the input ends, after a terminal
  error, after a panic in a command, and after a terminal entered only part
  way: raw mode off, the alternate screen left (`CSI ? 1049 l`), the cursor
  shown (`CSI ? 25 h`). Oracle: issue #140 and its known failure mode ("the
  terminal stays in raw mode after a failure"); the escape sequences are the
  xterm private modes crossterm writes.
- A key's request is sent, then a fresh snapshot is shown (the Python
  `_command`); a key after `q` is not handled.
- The watcher subscribes with `playback_progress: true` (the Python
  `events(playback_progress=True)`), sends a snapshot, forwards events, reports
  a failure as `Disconnected`, waits, and subscribes again (the Python
  `_listen`, which waits 1 s).
- Keys get the Python binding names; Ctrl+C quits.

## Tests

| Test | Size | Oracle and control |
|---|---|---|
| `crates/aitts-cli/tests/tui_loop.rs` (7) | small | A recording `Session` and a scripted `Commands`; restored means `enter` once first and `leave` last. |
| `crates/aitts-cli/tests/tui_terminal.rs` (3) | small | The real `TerminalSession` writing to a byte buffer with a recorded raw-mode switch, after `q` and after a panic; key names. |
| `crates/aitts-cli/tests/tui_reconnect.rs` (3) | medium | The real `aitts-daemon` on the Python-written `golden.db`, stopped and started on the same socket. The watcher's wait hook blocks until the test has started the new daemon, so the order is forced. A recording peer checks the subscribe request; an absent socket gives `Disconnected`. |
| `crates/aitts-client/tests/golden.rs`, progress subscription | medium | The request line is `{"op":"subscribe","playback_progress":true}`. |

No test sleeps. The watcher reads a quiet subscription with a 250 ms limit so
that it notices `stop`; that is a read deadline, not a pause.

## Observed RED

The first test commit failed against `todo!()` stubs: 6 loop, 2 reconnect and
1 client test. The second commit carried the terminal tests with their stubs
(3 failed) and also, by mistake, the loop, watcher and client code that made
the first commit's tests pass; those tests were therefore red in the first
commit and green in the second, with no commit showing them green alone. During GREEN the terminal
test failed for a real defect: when entering failed part way (raw mode on),
`run` returned before its restore guard existed, so raw mode stayed on. The
guard is now made before entering, and `a_failed_enter_still_leaves_the_terminal`
covers it. The terminal test's writer was also changed to a shared buffer,
because ratatui does not expose its backend's writer.

## Planted faults

| Fault | Failing tests |
|---|---|
| No restore on drop | 4 tests (panic, error, failed enter) |
| Guard made after entering | failed enter |
| Raw mode not switched off | both terminal tests |
| Alternate screen not left | both terminal tests |
| Ctrl+C not mapped | key names |
| Failures not reported | the 3 reconnect tests (first a hang; the wait hook now stops the watcher when the test ends) |
| Subscription without progress | progress subscription (added after this fault first survived) |
| No snapshot after a command | command flow (strengthened after it first survived) |
| `q` ignored | `q` restores |
| Client progress flag inverted | both client subscription tests |

## Repetition

The `aitts-cli` and `aitts-client` tests passed 10 times in a row.

## Not verified

- A real terminal: no TTY in CI. `start` (key reader thread, full-screen
  viewport, 1 s retry) has no automated test.
- `ai-tts tui` still runs the Python dashboard (part 4).
