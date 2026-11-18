# Rust terminal dashboard, part 1 (state and keys): verification record

Change kind: feature. `aitts_cli::tui::Dashboard` was tested against
[issue #140](https://github.com/flyingrobots/AI-TTS/issues/140) for the
dashboard's state and keys. The screen (an in-memory terminal buffer), the
event loop with reconnection and terminal restore, and installing
`ai-tts tui` follow in later parts. This record is agent-written and has not
received human editorial review.

## Contract

What the Python `SpeechTUI` (Textual 8.2.8, Python 3.12) shows and sends:

- the now-playing line (`Playing · voice · voice speed 1.0x · playback
  1.0x · 1:01 / 0:02 · Chunk 1/2`), the spoken text, the progress total
  (unknown while the duration is unknown) and position, and the level meter;
- queue rows (priority, voice, state, text; not Playing or Paused) and
  history rows (voice, result, text): whitespace runs joined, control
  characters shown as `\x1b`, at most 160 characters;
- the selected row follows its clip across refreshes;
- keys: Space pause or resume, j/k select, dd (same queued clip, within one
  second, no other key between) cancel, J/K reorder with the full pending
  permutation, n/p/r/s chunk and transport, Tab switch tables, Enter replay
  history, q quit; each request carries `origin: tui`;
- a progress event for the current clip moves the position and the meter; a
  change of hold, or any other event, reads a new snapshot;
- the status line for connecting, connected, a command and a failure.

## Tests and oracles

| Test | Size | Oracle |
|---|---|---|
| `tests/test_tui_parity_table.py` (22 scenarios, 25 text cases; Python 3.12 only) | medium | A headless `SpeechTUI` (`run_test`, 100×35) with a scripted client and a frozen clock, over snapshots captured from a Python daemon in five states. It keeps `tests/fixtures/tui_parity.json` equal to what the dashboard shows and sends. |
| `crates/aitts-cli/tests/tui_parity.rs` (2 tests) | small | The same fixture. Every field of the screen and every request is compared exactly, except progress numbers, which are compared as numbers (Textual stores 0 as 0.0). |
| `crates/aitts-cli/tests/tui_keys.rs` (512 cases) | small | Random keys, clock steps, snapshots, progress events, disconnects and command failures: no panic, cursors on a row, cells at most 160 characters, a status line, `origin: tui` on every request, cancel only from `d` on the queue, and only `q` quits. |

## Observed RED

The tests were committed first against `todo!()` stubs; both parity tests
failed.

## Planted faults

| Fault | Failing test |
|---|---|
| Newline and tab escaped | text helpers |
| `str.title()` replaced by upper case | 4 scenarios |
| Meter rounding half away from zero | text helpers (an exact half-cell peak) |
| Cells cut at 100 characters | scenarios |
| U+001C to U+001F not treated as space | scenarios |
| Selection kept by row, not clip | the selection follows a moved clip |
| dd window inclusive | dd too slow |
| No reset of dd on another key | an intervening key resets dd |
| Progress for another clip applied | progress for another clip is ignored |
| No snapshot on a hold change | a hold change reads a snapshot |
| Space sends the opposite operation | both Space scenarios |
| `origin: tui` left out | 4 scenarios |
| `x` quits | the key property test |
| Enter replays from the queue | Enter on the queue does nothing |

Three faults first survived (meter tie, dd reset, selection identity; the
last because the harness read snapshots one step early); the half-cell peaks,
the d j k d scenario and the moved-clip scenario were added, and the harness
was corrected.

## Repetition

The Rust dashboard tests passed 10 times in a row; the Python file passed 10
times in a row under Python 3.12.

## Not verified

- Drawing, terminal sizes (40 columns), the event loop, reconnection,
  terminal restore after a panic, and `ai-tts tui`: later parts.
- The Textual status-line text for a daemon error message; only the success
  and local messages are recorded.
