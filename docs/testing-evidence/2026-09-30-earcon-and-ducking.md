# Earcon and other-app ducking

Change-kind: feature

## Delivered behavior

The user chose **other apps only**, with system-audio permission. The setting was first delivered on by default; on 2026-10-02 James changed it to opt-in and **off by default** (see "Ducking off by default" below). Persisted `ducking_enabled` and `earcon_enabled` both default to false. Native Settings and CLI accept both controls, including `settings set earcon on|off` and `settings set ducking on|off`. There is no master-volume fallback or microphone capture.

The cue is 100 ms of 880 Hz, 24 kHz mono PCM16 with a sine-squared envelope and 12% peak gain. It precedes a new document once, does not repeat between chunks or on resume, does not inherit speech speed, and advances no source time. Cached speech is unchanged. Both callback streaming and legacy file output support it; the file path resamples it to the stream's rate and duplicates it across channels.

The menu-bar app owns a private Core Audio process tap on the default output, excluding the daemon and app processes. Matching native Float32 layouts are required before I/O; extra aggregate inputs are rejected. The callback smoothly ramps other-app output to 30%, retaining channel identity. Pause, completion, disconnection, disabling, route replacement and quit release routing. Restoration normally ramps to unity before close; unrecoverable errors close immediately. Headless daemon playback does not own this native route.

Startup leaves originals unmuted and emits no duplicate output. Only observed nonzero audio in valid buffers permits changing the tap to muted-when-tapped and rendering its replacement output. Status stays Waiting until delivery is confirmed. A 500 ms delivery gap releases originals and rearms an unmuted route; unsupported buffers close the route and surface an error. Pending readiness and monitoring cancel on pause/replacement/shutdown. Settings provides status, Retry, and Audio Privacy Settings; the bundle declares `NSAudioCaptureUsageDescription`.

## Owned contract tests and falsification

- Waveform duration, pitch, envelope and gain; source-clock isolation; persisted boolean defaults and CLI mappings: [eight-fault calibration](2026-09-30-earcon-calibration.json).
- Once-per-document playback, resume/chunk schedules, typed Swift commands and legacy snapshot defaults: [wiring calibration](2026-09-30-earcon-wiring-calibration.json).
- Actual file/callback sink output, resampling, channel preservation and consumed prefix: [three-fault calibration](2026-09-30-earcon-sink-calibration.json).
- Gain ramps, restoration, route reuse, device/process replacement, stale-release cancellation and failure/retry: [five-fault calibration](2026-09-30-ducking-calibration.json).
- Readiness gating, sticky invalid layouts, truthful status and asynchronous cleanup: [four-fault calibration](2026-09-30-ducking-readiness-calibration.json).
- Missing active monitoring fails its owned witness and cleanup assertion (`.git/codex-scratch/ducking-monitor-red.log`). Missing idle rearming fails the new-route witness and attempt/cleanup assertions (`ducking-rearm-red.log`).
- A status reader holding the readiness lock originally caused a silent callback. The regression was observed red (`ducking-lock-contention-red.log`), then fixed with callback-owned last-known rendering state and sticky layout validity. The callback never waits for that lock; contention no longer interrupts its output.
- A renamed permission plist key fails the release-bundle assertion (`ducking-permission-plist-red.log`); restored distribution tests pass.

All seeded sources were restored. Early missing-module/compiler failures were scaffolding, not falsification. One initial controller fixture incorrectly waited for a planning cycle preceding sink resumption; it was corrected to wait for an owned sink-start event, without claiming a production bug.

Final local checks at the time of writing: **712 Python tests**, **127 Swift tests**, Ruff, formatting, and mypy pass. That Python figure predates the branch's current base: at the feature commit `2abae3e` the suite collects 845 Python tests. Python tier costs were 0.64 s small / 8.32 s medium, wall 9.45 s; Swift XCTest execution was 0.227 s. Receipts are `.git/codex-scratch/earcon-ducking-final-{python,swift}.log`, which are local to the author's checkout. The final permission assertion additionally passes the focused distribution suite.

## Native evidence and corrections

A non-starting native probe initially found two tap input channels against this Mac's eight-channel output. Aggregate channel configuration did not coerce the physical output to stereo. The adapter now taps the selected device's native stream. Its eight-channel fixture failed the original stereo restriction, then passed; removing extra-input guards failed the rejection assertion. Receipts: `ducking-eight-channel-{red,green}.log`, `ducking-extra-input-red.log` and `ducking-format-probe.log` under `.git/codex-scratch/`.

An ad-hoc signed probe with no owned source received no callbacks, whether run from the shell or Launch Services. A quiet, generated 440 Hz tone played by a separate `afplay` process immediately produced `DELIVERY_CONFIRMED`. This disproved an initial three-second startup timeout: no callbacks alone does **not** establish permission failure. That timeout was removed; idle startup now waits unmuted. An early Launch Services attempt raced compilation and signing; its invalid signature was identified, then signing completed and verification passed before subsequent measurements. It is not acceptance evidence.

A signed, normally launched diagnostic then exercised the production native tap, delivery gate and gain renderer against the owned tone. It retained only scalar input/output energies, never captured audio. After settling each ramp, its 200 ms measurement windows reported:

| Phase | Callbacks | Input energy | Output/input RMS |
| --- | ---: | ---: | ---: |
| Ducked | 19 | 0.045242481714306663 | 0.30000001231875967 |
| Restored | 18 | 0.04292286115957013 | 1.0 |

The route closed successfully. Receipt: `.git/codex-scratch/ducking-native-measurement.log`. This measures native callback samples, not acoustic output. It preceded the final lock-contention correction; that correction has its own observed-red regression and full Swift green run. The installed AI-TTS app was not replaced.

## Limits

Physical device switching, permission-denial interaction, long-session acoustic behavior and the newly built app's installed GUI journey remain manual acceptance gaps. Controlled lifecycle tests establish cleanup policy, and the native probe establishes this machine's routing/attenuation/restoration path; neither proves all hardware or permission configurations. The diagnostic is deliberately outside CI and does not turn hardware timing into a gate.

Reference: [Apple's Core Audio tap sample](https://developer.apple.com/documentation/CoreAudio/capturing-system-audio-with-core-audio-taps).

## Review round (Code Lawyer, 2026-10-01)

Change-kind: bug fix for each row. Each regression test was run red against its parent, then green on the fix commit. No existing assertion was changed. Size: medium for every new test.

| Issue | Regression test | Parent (red) | Red output | Fix |
| --- | --- | --- | --- | --- |
| A pause or skip during the chime on file playback stopped writing mid-waveform, with no fade and no closing silence | `test_file_sink_cue_interrupted_mid_waveform_closes_softly[stop, pause]` | `2abae3e` | `the stream closes before its output has gone silent`: 2048 frames written, 6848 required | `f946016` |
| An output underflow while the file stream wrote the chime was not counted or logged | `test_file_sink_reports_an_underflow_while_writing_the_cue` | `f946016` | `[] == ['event=audio_output_underflow']` | `994b922` |
| Retry kept a route that was still waiting for delivery, so it retried nothing | `testRetryReplacesARouteStillWaitingForDelivery` | `994b922` | routes 1, not 2; closed `[0]`, not `[1, 0]` | `ce8660b` |
| A cold-start lookup of the not-yet-registered daemon process marked ducking failed until the user pressed Retry | `testPendingSpeechProcessIsRetriedWithoutAnotherSnapshot`, `testPauseCancelsAPendingSpeechProcessRetry` | `ce8660b`, plus the new error case and an unused delay parameter so the tests compile | creation attempts 1, not 2; after pause the status stayed `Waiting for the speech output process.` | `9162e61` |

Oracles: the soft stream close receipt (`2026-09-30-soft-stream-close.md`) on the base branch's merge with main, which requires a 20 ms fade from the next sample and 100 ms of exact silence before an interrupted stream closes; `sounddevice.write` reporting inserted output; and the controller's Retry and readiness contract. The cue close test compares against the uninterrupted cue as the same file stream plays it, and allows no step larger than the cue's own.

`testRetryKeepsARouteThatIsAlreadyDelivering` (new) passed on both sides. It pins that Retry does not close a route that is already delivering, because closing a muted tap would cut other apps' audio.

## Merge-up with main (2026-10-01)

`eb62603` merges `origin/main` (`534549a`, with #34, #35 and #57). Conflicts were resolved by keeping main's soft close, fade-in, device-rate host block and multi-engine text, with this PR's cue call placed before main's file-stream loop. After the merge: 887 Python tests passed and 2 opt-in live UI tests were skipped; 160 Swift tests passed.

After the merge, the callback path closes through `PCMStreamRenderer.close_block`. While the chime was sounding, that method saw `_was_silent` or `_trim_leading` and returned zeros at once, a step from up to 0.12 to silence on a pause or skip during the chime. Change-kind: bug fix. `test_callback_close_during_the_cue_fades_the_rest_of_the_cue[960, 2200]` (medium) requires the close to fade the remaining cue under the 20 ms raised cosine, holding the cue's last sample when less than 20 ms remains, then exact silence, with the source playhead unmoved. Oracle: the soft stream close receipt's `close_block` contract. On the merge commit `eb62603` it failed with `close_block` returning 0.0 where 0.103 was expected (476 of 480 fade samples wrong at 960 frames heard, 182 of 480 at 2200). The fix makes `close_block` fade the remaining prefix first.

AGY's strict review of `2cf1912` approved with one verified P4: the file stream's `_close_cue` padded zeros, not the last sample, when less than 20 ms of cue remained. The built-in chime ends at exactly zero, so it was not audible with the shipped cue. Change-kind: bug fix. `test_file_sink_cue_close_holds_the_last_sample_when_little_remains` (medium) uses a cue that ends at 0.25 with 100 frames left after the first block. It requires no step above 0.01 and exact closing silence. On parent `2cf1912` it failed with a 0.2246 step.

## Ducking off by default (2026-10-02)

Change-kind: deliberate behavior change, approved by James on 2026-10-02. Other-app ducking is now opt-in and off by default. Reason: until [#70](https://github.com/flyingrobots/AI-TTS/issues/70) validates the tap's buffer on hardware, a missed tap cycle would glitch every other app's audio. Only the default changes: a saved `ducking_enabled=true` is still honored.

The default flips in four places: `SettingsService.values()` in `src/aitts/settings.py`, the `Snapshot` initializer default in `SpeechModels.swift`, `AppState.duckingEnabled` in `AppState.swift`, and the snapshot decoder's fallback for a daemon that omits the key in `UnixSocketSpeechService.swift`.

James approved changing these existing assertions from on to off: `test_audio_effect_preferences_have_defaults_and_persist[ducking_enabled-False]` and the `ducking_enabled` value in `tests/test_ipc.py::test_cache_cap_setting_immediately_evicts_only_terminal_audio`. The decoder's Swift test `testAudioEffectPreferencesDecodeDefaultsAndExplicitValues` pinned the same default. Its missing-key case now expects off, and its explicit case now sends `ducking_enabled: true`, so it still proves an explicit value overrides the default.

New tests: `test_an_existing_saved_ducking_opt_in_survives_the_off_default` (small; a stored `"true"` reads back as true), and `DuckingDefaultTests` (medium XCTest: a snapshot without the preference is off; `AppState` starts off and honors a saved opt-in from the daemon).

Red on parent `f1da305`, before the defaults changed: the settings test failed with `assert True is False`; the IPC test failed on the settings response; and the three Swift tests failed with `XCTAssertFalse failed` (`DuckingDefaultTests.swift:18` and `:31`, `UnixSocketSpeechServiceTests.swift:255`). The saved-opt-in test passed on both sides, as a preservation check. Green after the change: 891 Python tests passed (2 opt-in live UI tests skipped) and 162 Swift tests passed.
