# Earcon and other-app ducking

Change-kind: feature

## Delivered behavior

The user chose **other apps only**, with system-audio permission and a setting
**on by default**. Persisted `ducking_enabled` defaults to true;
`earcon_enabled` defaults to false. Native Settings and CLI accept both controls,
including `settings set earcon on|off` and `settings set ducking on|off`.
There is no master-volume fallback or microphone capture.

The cue is 100 ms of 880 Hz, 24 kHz mono PCM16 with a sine-squared envelope and
12% peak gain. It precedes a new document once, does not repeat between chunks or
on resume, does not inherit speech speed, and advances no source time. Cached
speech is unchanged. Both callback streaming and legacy file output support it;
the file path resamples it to the stream's rate and duplicates it across channels.

The menu-bar app owns a private Core Audio process tap on the default output,
excluding the daemon and app processes. Matching native Float32 layouts are
required before I/O; extra aggregate inputs are rejected. The callback smoothly
ramps other-app output to 30%, retaining channel identity. Pause, completion,
disconnection, disabling, route replacement and quit release routing. Restoration
normally ramps to unity before close; unrecoverable errors close immediately.
Headless daemon playback does not own this native route.

Startup leaves originals unmuted and emits no duplicate output. Only observed
nonzero audio in valid buffers permits changing the tap to muted-when-tapped and
rendering its replacement output. Status stays Waiting until delivery is
confirmed. A 500 ms delivery gap releases originals and rearms an unmuted route;
unsupported buffers close the route and surface an error. Pending readiness and
monitoring cancel on pause/replacement/shutdown. Settings provides status, Retry,
and Audio Privacy Settings; the bundle declares `NSAudioCaptureUsageDescription`.

## Owned contract tests and falsification

- Waveform duration, pitch, envelope and gain; source-clock isolation; persisted
  boolean defaults and CLI mappings:
  [eight-fault calibration](2026-09-30-earcon-calibration.json).
- Once-per-document playback, resume/chunk schedules, typed Swift commands and
  legacy snapshot defaults:
  [wiring calibration](2026-09-30-earcon-wiring-calibration.json).
- Actual file/callback sink output, resampling, channel preservation and consumed
  prefix: [three-fault calibration](2026-09-30-earcon-sink-calibration.json).
- Gain ramps, restoration, route reuse, device/process replacement, stale-release
  cancellation and failure/retry:
  [five-fault calibration](2026-09-30-ducking-calibration.json).
- Readiness gating, sticky invalid layouts, truthful status and asynchronous
  cleanup: [four-fault calibration](2026-09-30-ducking-readiness-calibration.json).
- Missing active monitoring fails its owned witness and cleanup assertion
  (`.git/codex-scratch/ducking-monitor-red.log`). Missing idle rearming fails the
  new-route witness and attempt/cleanup assertions (`ducking-rearm-red.log`).
- A status reader holding the readiness lock originally caused a silent callback.
  The regression was observed red (`ducking-lock-contention-red.log`), then fixed
  with callback-owned last-known rendering state and sticky layout validity. The
  callback never waits for that lock; contention no longer interrupts its output.
- A renamed permission plist key fails the release-bundle assertion
  (`ducking-permission-plist-red.log`); restored distribution tests pass.

All seeded sources were restored. Early missing-module/compiler failures were
scaffolding, not falsification. One initial controller fixture incorrectly waited
for a planning cycle preceding sink resumption; it was corrected to wait for an
owned sink-start event, without claiming a production bug.

Final local checks: **712 Python tests**, **127 Swift tests**, Ruff, formatting,
and mypy pass. Python tier costs were 0.64 s small / 8.32 s medium, wall 9.45 s;
Swift XCTest execution was 0.227 s. Receipts are
`.git/codex-scratch/earcon-ducking-final-{python,swift}.log`. The final permission
assertion additionally passes the focused distribution suite.

## Native evidence and corrections

A non-starting native probe initially found two tap input channels against this
Mac's eight-channel output. Aggregate channel configuration did not coerce the
physical output to stereo. The adapter now taps the selected device's native
stream. Its eight-channel fixture failed the original stereo restriction, then
passed; removing extra-input guards failed the rejection assertion. Receipts:
`ducking-eight-channel-{red,green}.log`, `ducking-extra-input-red.log` and
`ducking-format-probe.log` under `.git/codex-scratch/`.

An ad-hoc signed probe with no owned source received no callbacks, whether run
from the shell or Launch Services. A quiet, generated 440 Hz tone played by a
separate `afplay` process immediately produced `DELIVERY_CONFIRMED`. This disproved
an initial three-second startup timeout: no callbacks alone does **not** establish
permission failure. That timeout was removed; idle startup now waits unmuted.
An early Launch Services attempt raced compilation and signing; its invalid
signature was identified, then signing completed and verification passed before
subsequent measurements. It is not acceptance evidence.

A signed, normally launched diagnostic then exercised the production native tap,
delivery gate and gain renderer against the owned tone. It retained only scalar
input/output energies, never captured audio. After settling each ramp, its 200 ms
measurement windows reported:

| Phase | Callbacks | Input energy | Output/input RMS |
| --- | ---: | ---: | ---: |
| Ducked | 19 | 0.045242481714306663 | 0.30000001231875967 |
| Restored | 18 | 0.04292286115957013 | 1.0 |

The route closed successfully. Receipt:
`.git/codex-scratch/ducking-native-measurement.log`. This measures native callback
samples, not acoustic output. It preceded the final lock-contention correction;
that correction has its own observed-red regression and full Swift green run.
The installed AI-TTS app was not replaced.

## Limits

Physical device switching, permission-denial interaction, long-session acoustic
behavior and the newly built app's installed GUI journey remain manual acceptance
gaps. Controlled lifecycle tests establish cleanup policy, and the native probe
establishes this machine's routing/attenuation/restoration path; neither proves
all hardware or permission configurations. The diagnostic is deliberately
outside CI and does not turn hardware timing into a gate.

Reference: [Apple's Core Audio tap sample](https://developer.apple.com/documentation/CoreAudio/capturing-system-audio-with-core-audio-taps).
