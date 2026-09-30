# Intermittent popping investigation

Change-kind: feature (diagnostics). The reported audio defect remains open;
no reproduction or root-cause fix is claimed.

## Evidence and limits

The user reports intermittent speaker-like pops in AI-TTS but not other apps.
Ten local cached WAVs were inspected without recording their text or paths:
all were 24 kHz, finite, and had zero samples at absolute amplitude >= 0.9999.
Peaks ranged from 0.365 to 0.910. This excludes digital clipping in those files,
not other synthesis artifacts. The installed playback rate was 1.0.

A temporary live probe used the production SoundDeviceSink with twelve seconds
of silence while two Kokoro jobs synthesized a fixed synthetic phrase. Its
stream wrapper recorded sounddevice's write result. Both the device-default
latency and a 200 ms comparison produced 141 writes and zero underflows. This
short, uncontrolled hardware experiment did not reproduce the user symptom and
is not a gate or a performance claim. Buffer settings were left unchanged.
Playback already owns a dedicated thread; the two synthesis workers use separate
executor threads in the same process. Shared-process contention remains a
hypothesis, not an established cause.

## Instrument

SoundDeviceSink now consumes OutputStream.write's documented underflow result
and emits `event=audio_output_underflow` once per opened stream when true. It
does not retry an accepted block, change playback rate, or log content/paths.
The production protocol now describes the driver's boolean result.

Oracle: sounddevice's Stream.write contract reports inserted output data via
its underflowed boolean (upstream source and installed sounddevice implementation):
https://python-sounddevice.readthedocs.io/en/latest/_modules/sounddevice.html

The medium test `test_output_underflow_diagnostic_is_bounded_and_truthful` enters
through SoundDeviceSink with an owned WAV, fake device, and stream injecting
all-clean or all-underflow writes. It checks the exact diagnostic sequence.

Calibration:

- Before instrumentation, the underflow case failed: expected one event, got none.
- Removing the once-per-stream guard failed with six events instead of one.
- Logging regardless of the driver status failed the clean case with one false event.
- Both mutations were removed and both cases passed.

Validation: 48 targeted playback/device/diagnostic tests passed; Ruff checks and
formatting passed; repository mypy passed (94 source files); whitespace check
passed. Existing sample-preservation tests remain unchanged. Delete the new
test when this driver diagnostic or playback adapter is retired.

The updated wheel was installed into the existing daemon environment without
changing dependencies, and the idle launch agent was restarted. The next
symptom must be correlated with these events. A clean diagnostic log does not
rule out hardware/conversion artifacts or defects embedded in generated speech.
