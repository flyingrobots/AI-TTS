# Microphone resume and queued speech

Change-kind: bug fix

The user requested automatic release of microphone pauses when no application
uses an input, plus agent guidance to enqueue requested speech during a hold.
The previous default was `manual`, and the distributed and installed speak
skills explicitly told agents to substitute text when paused.

## Contract and oracle

The oracle is the user's 2026-09-20 dictation/reply requirement. The new medium
regression enters through daemon submission/status with a controlled input
activity port and sink, a fake synthesis engine, and an isolated store/socket.
It waits for observed input polls and queue states, rather than sleeping to
infer that the watcher ran. A queued reply must remain silent on an unavailable
input reading, then start when input becomes idle without a Resume command.
Explicit `manual` and `when_idle` settings remain supported.

Delete this regression if microphone interruption is removed or a stronger,
cheaper test subsumes its admission-to-playback contract.

## Falsification receipts

On unchanged production code at `e61e6d8`, the new regression and updated
settings-default expectation both failed:

- `test_default_microphone_hold_releases_and_plays_the_queued_reply` observed
  `playback_held == True` after input became idle, expected False.
- `test_defaults_are_reported_before_anything_is_written` observed `manual`,
  expected `when_idle`.

After the fix, temporary mutations in `input_interrupt.py` were rejected:

- Replacing `reading is False` with `reading is not True` started audio on an
  unavailable reading. The regression failed its empty-started-sink assertion.
- Unconditionally arming resume ignored an explicit manual policy. The
  parameterized configuration test failed with `playback_held == False`,
  expected True for manual.

Both mutations were restored. The post-restoration interruption and settings
suites passed, 114 tests. Existing settings/IPC expectations were updated only
where their complete responses include the deliberately corrected default.

## Validation

- Full Python suite: 559 passed in 12.20 seconds. Small tier: 214 tests,
  0.88 seconds including fixtures. Medium tier: 345 tests, 10.37 seconds.
- Ruff lint and format checks passed; mypy passed for 95 source files.
- Skill frontmatter validation passed for the repository and customized
  installed Claude skill. Existing installer tests passed in the full suite.
- Prose review covered held playback, dictation interruption, manual pause,
  daemon unavailability, and wait timeout. No text-matching test is used as
  evidence of agent compliance. Actual future agent choices remain a manual
  acceptance check.

## Isolated PR branch validation

The fix was cherry-picked onto `origin/main` at `7e78913` in
`/Users/james/git/ai-tts-microphone-resume`, excluding the unrelated local
store refactor `e61e6d8`. Its own frozen development environment passed all
558 Python tests in 13.67 seconds. The test-count difference is due to the
excluded store refactor. Ruff lint and formatting and mypy were also run on
this checkout. No Swift source changed.

## Installed acceptance

The running checkout-backed daemon's policy was set to `when_idle` and its
existing microphone hold armed through `resume-when-idle`. Subsequent live
status reported `input_active: false`, `playback_held: false`, and no
interruption. This confirms a real microphone hold released automatically.

The Codex skill was reinstalled. The customized Claude skill received only
the queueing and silence-guidance edits, retaining its source/voice and
reporting preferences. Existing sessions may need to reread the skill; new
sessions discover the updated copy.

The idle launch agent was reloaded to pick up the status guidance. Its first
bootstrap attempt returned an I/O error immediately after bootout; a second
bootstrap succeeded. Readback confirmed the service running, policy
`when_idle`, and the new enqueue-while-paused guidance. A subsequent microphone
hold reported `resume_armed: true`.

The OS reports an open input device, not vocal silence. Applications that
keep the microphone open keep the microphone hold active. Manual Resume
continues to work in that case. Explicit manual pauses and restart recovery
retain their existing behavior. Previously saved manual policies are not
silently overwritten by the new default; this user's running policy was
changed explicitly as part of the requested fix.
