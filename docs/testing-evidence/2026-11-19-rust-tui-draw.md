# Rust terminal dashboard, part 2 (drawing): verification record

Change kind: feature. `aitts_cli::tui::draw` was tested against
[issue #140](https://github.com/flyingrobots/AI-TTS/issues/140) for drawing
the dashboard. Part 1 (state and keys) is in `2026-11-19-rust-tui-model.md`.
This record is agent-written and has not received human editorial review.

## Contract and oracles

The Textual layout is not reproduced cell for cell; Textual and ratatui
differ in borders, padding and bar glyphs, and the issue names screen tests
that depend on the library as a risk. The contract is what each region holds,
in order:

- content: the `Screen` from part 1, which is tied to the Python dashboard by
  recorded scenarios;
- regions, labels and bounds: the Python layout in `src/aitts/tui/app.py`.
  The header names AI-TTS. The now-playing card holds the details line, the
  progress bar, at most 5 lines of spoken text (`#spoken-text` max-height 5)
  and the meter, and is at most 12 rows (`max-height: 12`). The queue title
  and its Priority/Voice/State/Text columns come next, then the history title
  and its Voice/Result/Text columns, the status line, and a footer with the
  bindings Python shows (Pause/resume, Next chunk, Previous chunk, Restart,
  Skip, Replay history, Quit);
- the selected row of the focused table is highlighted (reversed);
- an unknown duration shows no percentage (Textual's indeterminate bar).

## Tests

`crates/aitts-cli/tests/tui_render.rs`, small (ratatui `TestBackend`):

| Test | Checks |
|---|---|
| `each_region_holds_its_content_in_python_order` | 100×35: every region in order, every queue row with its priority and state, the footer bindings. |
| `the_playing_card_shows_chunk_text_progress_and_meter` | chunk text, meter, and a full bar past the end. |
| `an_unknown_duration_shows_no_percentage` | no `%` anywhere. |
| `the_selected_row_of_the_focused_table_is_highlighted` | the cursor cell is reversed, in the queue and in history. |
| `long_clip_text_stays_inside_its_card_and_leaves_the_tables_visible` | 10 000 characters of spoken text: card at most 12 rows, at most 5 text rows, at least 3 queue rows. |
| `forty_columns_keep_every_region_and_cut_lines_at_the_edge` | 40×24: the details line cut at the edge, both titles shown, every line 40 cells. |
| `no_scenario_puts_a_control_character_into_the_buffer_at_any_size` | every scenario at 100×35 down to 0×0. |
| `any_size_draws_without_panic` (256 cases) | random scenario and size up to 160×60. |

## Observed RED

The tests were committed first against a `todo!()` stub of `draw`; all 7
failed. During GREEN, the highlight test's hard-coded cursor (1) was removed:
the fixture now has five queued clips, and the cursor comes from the
Python-tied model (2).

## Planted faults

| Fault | Failing tests |
|---|---|
| Highlight bold instead of reversed | highlight |
| Card height not bounded | region order, long text |
| Skip left out of the footer | region order |
| Bar with a percentage for an unknown duration | unknown duration |
| History column Result named State | region order |
| Queue title drawn in the history title row | 4 tests |
| A BEL character in the details line | none: ratatui drops control characters when it writes a cell |

The control-character test therefore guards the library's behavior rather
than this code; the visible `\x1b` escapes come from part 1's model, which
the region test reads in the queue rows.

## Repetition

The drawing tests passed 10 times in a row.

## Not verified

- The look on a real terminal: no screenshot was taken.
- The event loop, reconnection, terminal restore after a panic, and
  `ai-tts tui`: parts 3 and 4.
