# Terminal dashboard

Change-kind: feature

## Scope and behavior

Prompt 6 adds optional `ai-tts tui` using Textual (locked 8.2.8). The CLI loads its dependency lazily, honors `--socket`, and explains the extra when absent. The TUI connects to the existing user-only Unix socket; it neither starts nor owns the daemon. Closing it leaves playback running.

Now Playing displays current spoken chunk text, chunk number/count, voice, synthesis speed, playback rate and elapsed/total time. Known durations show progress; unfinished durations stay unknown with an indeterminate bar. Queue and history are independently navigable, and selection survives updates by ID. Rich-looking source remains literal, and terminal control bytes are rendered as visible escapes. Connection and command errors have a persistent status line.

All requested controls are implemented: Space pause/resume, j/k selection, dd cancel, J/K queue movement, n/p chunk stepping, r restart, s skip, q exit. Tab switches tables; Enter replays selected history with recorded voice/model. The two d presses must be consecutive, within one second, on the same identity. Reordering sends the full pending permutation so the daemon rejects stale edits.

The asynchronous client acknowledges subscriptions before snapshot reads, preserves coalesced NDJSON frames, closes sockets on context exit/cancellation, bounds command round trips, and does not retry mutations. Disconnects reconnect without owning playback. Quiet subscriptions have no idle deadline.

## Live meter

The native sink measures peaks from actual callback/file output blocks. An opt-in `playback_progress` subscription carries position, global hold and peak at approximately 10 Hz. Ordinary subscribers receive no new telemetry. The publisher drops transient samples above a 64 KiB write backlog. The UI displays 20 log10 amplitude in dBFS; unavailable measurements remain unknown, while idle/held playback is zero. Sink measurements expire after 250 ms. No captured audio or extra source text is transmitted by telemetry or retained in history.

## Boundary evidence and corrections

- Real-daemon requests and events, owned socket EOF, coalesced frames and malformed replies: [client calibration](2026-09-30-tui-client-calibration.json).
- Pilot global hold/queue controls, subscription opt-in, actual callback peak and dBFS mapping: [UI/meter calibration](2026-09-30-tui-ui-meter-calibration.json).
- Actual chunk stepping, restart, skip and history replay, both movement keys, dd cancellation on an intervening key, reconnect, CLI socket selection and missing-extra guidance: [control calibration](2026-09-30-tui-controls-calibration.json).

All mutations produced named assertion failures or failed owned completion witnesses, then sources were restored. Missing-module/fixture-construction failures were scaffolding, not red/green evidence.

Three regressions were observed red in the draft before correction:

1. An external pause with no current clip emitted no state transition, so the TUI missed the hold. Telemetry now carries hold state and refreshes the snapshot on a change (`.git/codex-scratch/tui-idle-hold-red.log`).
2. Unknown duration was incorrectly replaced with a one-millisecond total. The ProgressBar total assertion failed, then passed with an indeterminate total (`tui-unknown-duration-{red,green}.log`).
3. Rich Text retained an ESC byte from source. The literal-cell assertion failed, then passed after control-character escaping (`tui-control-text-{red,green}.log`).

The initial full run also caught missing README documentation for `tui`; the README was corrected, without weakening the coverage assertion.

Local checks before the shutdown regression below: **728 Python tests**, Ruff, formatting and mypy pass. Small-tier cost is 0.65 s, medium 12.10 s, wall 13.29 s. Receipt: `.git/codex-scratch/tui-final-python.log`. Swift sources are unchanged from the previous prompt's passing build and 127-test suite.

## Visual and dependency acceptance

Owned daemon data was rendered at 100×35 and 80×24; both exported SVG previews were converted to PNG and visually inspected. Now Playing, queue, history and connection status remain readable at both sizes. The footer clips some shortcut labels at 80 columns, while section labels, README and working bindings retain access to the controls. The preview's FakeSink correctly reports unknown level. Artifacts: `.git/codex-scratch/terminal-dashboard{,-80x24}.svg` and `.svg.png`. An early thumbnail process started before SVG completion and was stopped; only the completed-file render is visual acceptance evidence.

A separate Python 3.12 frozen all-extras environment passed strict hashed PyPI advisory checks, pinned-source OSV/hash checks, SBOM and license reconciliation: **164 dependencies**, **189 SBOM components**, **164 license records**, **zero known vulnerabilities**. The pre-existing unknown `espeakng-loader` license remains. See [summary](2026-09-30-tui-dependency-summary.json); raw reports and the command transcript are in `.git/codex-scratch/tui-audit/`. No advisory result establishes absence of undisclosed vulnerabilities. `uv build --offline` passes.

Stale lock (Code Lawyer, 2026-10-01): the summary's `lock_sha256` is `510e5022…022f`, but `uv.lock` at the PR head `a33ce35` hashes to `29be5818…2075`. The audit therefore describes a different lock file. Its counts and its zero-vulnerability result are not evidence for the lock this PR ships. The audit must be re-run against the current `uv.lock` before it can count as acceptance evidence. The summary is left as recorded rather than rewritten with a hash it was not computed from.

## Limits

Tests use owned sockets, FakeEngine/FakeSink or controlled real sink callbacks; they do not establish acoustic loudness or every terminal emulator/size. Physical audio acceptance was not repeated for a display feature. No installed app or CLI was replaced. The user-owned `PROMPTS.md` remains untouched and untracked. This change does not close platform-portability or long-session popping issues.

Primary testing reference: [Textual Pilot guide](https://textual.textualize.io/guide/testing/).

## Shutdown delivery regression

Hosted run `36735472714` exposed a late playback event after Textual removed the audio-meter widget during shutdown. A separate passing run was not used to dismiss this failure or retry it unchanged.

Three medium regression schedules enter through `App.run_test` and an owned async client. A card's public Unmount event, dispatched after its children are removed, gates delivery of progress, a pending snapshot response, or a disconnect. Each schedule witnesses actual delivery and completion, with no timing sleeps or repeated trials. All three failed on the unfixed application with `NoMatches` from the removed meter, now-playing, or connection widget.

Rendering now checks the app lifecycle after asynchronous delivery, and the subscription loop does not reconnect after shutdown. Live missing-widget errors remain errors; no broad exception suppression was added. All three schedules and the existing Pilot journeys pass. Delete these regressions only when UI subscription ownership changes enough that this teardown contract is covered at a stronger boundary. The full suite passes 796 Python tests: 271 small/525 medium, .70/13.63 seconds by tier, 15.01 seconds wall clock. Raw red/green and full-suite logs are under `.git/codex-scratch/tui-shutdown-*`.

The 728 and 796 counts are successive points in this PR's history. At the PR head `a33ce35`, on its current base, the full suite ran 864 tests (279 small, 585 medium) on 2026-10-01.

## Review round (Code Lawyer, 2026-10-01)

Change-kind: bug fixes, plus one deliberate wire addition (the admission event). Each regression test below was run red on its parent commit and green on the fix commit. The CLI fix also gave the existing `test_tui_cli_uses_selected_socket_without_starting_daemon` fake a `return_code = 0`, Textual's value after a clean exit. Its assertions are unchanged.

| Issue | Regression test | Parent (red) | Red output | Fix |
|---|---|---|---|---|
| A clip queued behind a busy worker or warmup produced no event, so subscribers such as the dashboard did not show it until a worker claimed it | `test_submission_behind_a_busy_worker_is_published[submit, requeue]` (medium) | `a33ce35` | `no admission event for the waiting clip: []`; with only the submit path fixed, the requeue case still failed the same way | `3279d5b` |
| The async client capped replies at the 1 MiB request limit, so a snapshot with a few long texts disconnected the dashboard on every retry | `test_reply_longer_than_the_request_line_limit_is_delivered` (medium) | `3279d5b` | `DaemonUnreachableError: Cannot communicate with the daemon: Separator is not found, and chunk exceed the limit` | `5d8e76e` |
| `ai-tts tui` exited 0 after the dashboard crashed, although Textual set `App.return_code` to 1 | `test_tui_crash_is_a_failing_exit_status` (medium; a real headless Textual app whose `compose` raises) | `5d8e76e` | `assert 0 == 1` where `0 = main(['--socket', '/owned/terminal.sock', 'tui'])` | `ed58d34` |

Test determinism (refactor plus a new assertion, no behavior change): the `dd` window read `time.monotonic` directly, so `test_vim_selection_reorder_and_double_delete_use_clip_identity` passed only while each pair of presses and a socket round trip took less than 1 s. `SpeechTUI` now takes an injectable `clock`. That test runs on a frozen clock, and its assertions are unchanged. The new `test_double_delete_expires_after_the_confirmation_window` (medium) steps a fake clock. A second `d` exactly 1.0 s later does not cancel, and one 0.999 s after that does. Falsification on the fix: changing `<` to `<=` failed it with `a late second d cancelled`, and the source was then restored.
