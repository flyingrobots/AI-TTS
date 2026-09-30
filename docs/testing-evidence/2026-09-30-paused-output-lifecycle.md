# Paused output stream lifecycle

Change-kind: behavior change.

Deliberately release the device stream while paused and open a fresh stream at
resume, using the saved source frame and current output device. Previously the
stream stayed running without writes for the entire hold. This corrects a
reproduced underflow mechanism following the user's report of microphone-driven
pause/resume cycles, including hours-long holds.

The existing device-change expectation deliberately changes: adopt a device
selected during a pause when playback resumes, rather than opening a running
stream during the hold. The same clip still follows the device and retains all
source frames. No change to synthesis, rate, or sample conversion is involved.

## Regression and calibration

Oracle: paused playback must not leave a running output stream starved of data;
resume must deliver the source samples exactly once in order. Upstream
sounddevice documents the underflow result used for the hardware observation:
https://python-sounddevice.readthedocs.io/en/latest/_modules/sounddevice.html

Medium test `test_repeated_pauses_release_output_and_resume_without_changing_samples`
uses an owned WAV and fake stream with explicit close notifications. It pauses
on a write, awaits stream closure, resumes, and repeats. One-second timeouts
are deadlock guards, not scheduling sleeps or performance assertions.

- Unfixed code failed with `paused playback kept its output stream running`.
- Fixed code passed both close witnesses and exact output-sample equality.
- Mutating the saved resume position to skip one frame per pause failed sample
  equality: shapes `(11998, 1)` versus `(12000, 1)`. Mutation was reverted.

Delete this test if pause/resume support or this output adapter is retired.

## Real-device experiment

A temporary harness wrapped the actual sounddevice stream and production sink,
playing three seconds of silence with two controlled 500 ms pauses on the same
Studio Display output. No user text was played or logged.

| Implementation | Streams opened | Writes | Driver-reported underflows | Natural completion |
| --- | ---: | ---: | ---: | --- |
| Installed code before fix | 1 | 36 | 2 | yes |
| Fixed checkout | 3 | 36 | 0 | yes |

This reproduces the pause-induced driver underrun, not the listener's subjective
popping or an hours-long hardware session. That symptom still needs confirmation
in ordinary use. The stream is now closed for a hold of any length.

49 targeted playback, device, and logging tests passed; Ruff checks and formatting
passed; repository mypy passed (94 files). The updated wheel was installed into
the existing environment without dependency changes, and the idle daemon was
restarted. Previous unrelated workspace changes remain intact.
