# Soft stream close and open

Change-kind: bug fix, with a deliberate change to the stop-fade and frame-conservation test contracts that James approved.

## Fault

The listener heard a pop on every skip. Per-clip evidence for the skips at 20:45 on 2026-09-30 showed `stream_opened`, then `stream_closing` with zero underflows, then a 146 ms drain before `session_ended`. The digital stream was continuous: the old 5 ms stop ramp started at the last written sample. Closing the stream drains PortAudio's ring buffer and then stops the CoreAudio output unit, which can truncate the hardware buffer still in flight. The 120-frame ramp was shorter than that buffer, so the cut fell on speech. A natural end does not pop: all 16 cached clips begin and end in exact digital silence. Pause closed the stream with no fade at all. The device-move path closed the old stream mid-speech with no fade. Every stream opened mid-clip, on resume or after a device move, started at full amplitude.

The CoreAudio truncation mechanism is inferred from the evidence above and from how PortAudio stops a stream. No automated test reproduces it, and the listener's ear on the installed build is the acceptance check. The pop heard on the first installed build was during a daemon restart while the stale old code was still loaded: uv had served its cached 0.1.0 wheel. No skip had yet run on the new code at that point.

## Fix

- Close: when a stream closes mid-clip (stop, pause, or device move), `SoundDeviceSink` writes one closing block. It holds the next 20 ms of source audio at the current rate, faded by a raised cosine, then 100 ms of silence, which exceeds the 78 to 121 ms output latency PortAudio reported. The fade reads ahead without moving the playhead, so resumption repeats nothing.
- Open: a stream opened at a nonzero source position applies a 20 ms raised-cosine fade-in, starting from exactly zero gain. A stream opened at position zero is untouched because the clip already begins in silence.

## Assertions

Oracle: the listener report and the CoreAudio close behavior above. Size: medium. Each test uses an owned WAV and a recording output stream.

- `test_stop_fades_to_held_silence_without_consuming_more_source` replaces `test_stop_ramps_to_silence_without_consuming_more_source`. The old test pinned the 120-frame ramp being retired. The new test requires no sample-to-sample step above 0.01, exact silence in the final 100 ms, a fade starting at the next source sample, and the playhead held at 85 ms. On unfixed code it failed because the stream held 2168 frames, not the 2400 silent frames required.
- `test_resumed_stream_fades_in_from_silence_at_the_held_position` (new) requires the resumed stream to start within 0.01 of silence, rise without a step, and match the source exactly from the held position once the fade-in ends. On unfixed code it failed with `the stream starts mid-waveform` (first sample 0.171).
- `assert_source_heard_once` now carries the frame-conservation oracle of four existing tests: the pause, pause-then-move, mid-clip device move, and unreadable-then-move tests. Previously those tests required byte-identical concatenation or exact frame counts across reopens, which fades cannot satisfy. The helper still requires every source frame to be heard exactly once and in order. It excludes each interrupted stream's closing block, requires that block to close softly, requires each mid-clip stream to open softly, and compares everything outside the 20 ms fade-in windows to the source.
- Mutations, each restored afterwards:
  - silence set to 0 s: the stop and pause tests failed with `the stream closes before its output has gone silent`.
  - fade-out set to 0 s: they failed with `the fade has an audible step`.
  - fade-in removed: five tests failed with `the stream starts mid-waveform`.
  - device-move close not softened: both device-move tests failed.

## Real speech

A scratch harness ran both the `origin/main` sink and the fixed sink on the longest cached Kokoro clip through a recording stream, acting two seconds in:

| Sink | Skip: peak in last 30 ms written | Pause: peak in last 30 ms written | Resume: first sample |
|---|---|---|---|
| origin/main | 0.127 | 0.021 | 0.001 (peak 0.021 in the first 2 ms) |
| fixed | 0.000 | 0.000 | 0.000 (peak 0.000 in the first 2 ms) |

## Validation

- Full Python suite: 239 small and 458 medium tests passed. ruff and mypy are clean.

Limits: the recording stream cannot show CoreAudio's truncation, so these tests prove the written signal, not the absence of a pop. Retire them if the sink stops closing the device between clips.
