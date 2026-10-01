# Soft stream close and open

Change-kind: bug fix, with a deliberate change to the stop-fade and frame-conservation test contracts that James approved.

## Fault

The listener heard a pop on every skip. Per-clip evidence for the skips at 20:45 on 2026-09-30 showed `stream_opened`, then `stream_closing` with zero underflows, then a 146 ms drain before `session_ended`. The digital stream was continuous: the old 5 ms stop ramp started at the last written sample. Closing the stream drains PortAudio's ring buffer and then stops the CoreAudio output unit, which can truncate the hardware buffer still in flight. The 120-frame ramp was shorter than that buffer, so the cut fell on speech. A natural end does not pop: all 16 cached clips begin and end in exact digital silence. Pause closed the stream with no fade at all. The device-move path closed the old stream mid-speech with no fade. Every stream opened mid-clip, on resume or after a device move, started at full amplitude.

The CoreAudio truncation mechanism is inferred from the evidence above and from how PortAudio stops a stream. No automated test reproduces it, and the listener's ear on the installed build is the acceptance check. The pop heard on the first installed build was during a daemon restart while the stale old code was still loaded: uv had served its cached 0.1.0 wheel. No skip had yet run on the new code at that point.

## Fix

- Close: when a stream closes mid-clip (stop, pause, or device move), `SoundDeviceSink` writes one closing block. It holds the next 20 ms of source audio at the current rate, faded by a raised cosine, then 100 ms of silence. Closing drains PortAudio's queue before it stops the output unit, so the silence does not need to cover PortAudio's total latency (78 to 248 ms across the measurements here). It needs to cover the host I/O buffer in flight, which the close can cut. That buffer is 21.3 ms with the block size chosen below. The fade reads ahead without moving the playhead, so resumption repeats nothing.
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

- Full Python suite at the merge with main: 258 small and 475 medium tests passed. ruff and mypy are clean.

Limits: the recording stream cannot show CoreAudio's truncation, so these tests prove the written signal, not the absence of a pop. Retire them if the sink stops closing the device between clips.

## Mid-playback pop on app switch: 15-frame HAL buffer

On 2026-10-01, the listener heard a pop while playback was running and Slack came to the front. The per-clip evidence for the clip that started at 10:00:45 showed one stream, zero PortAudio underflows, no device change, and a natural end. The unified log showed what happened:

- 10:00:50.801: WindowServer made Slack the frontmost process.
- 10:00:50.951: inside the daemon process, CoreAudio logged `HALC_ProxyIOContext::IOWorkLoop: skipping cycle due to overload`.
- coreaudiod's overload report gave `cause: PageFaultsOnIOThread`, `io_page_faults: 1`, and `multi_cycle_io_page_faults_duration: 322751` mach ticks (about 13.4 ms). It also gave `io_buffer_size: 15` and `other_active_clients: []`, so Slack was not playing audio.
- Six more overloads in the daemon between 09:23 and 10:17 included four that coincided with a clip's stream opening. Those landed in Kokoro's leading silence.

PortAudio does not count a skipped HAL cycle as an underflow, which is why the clip evidence looked clean.

Measured on the built-in speakers, with the per-process `kAudioDevicePropertyBufferFrameSize` read while the stream was open:

| `sd.OutputStream` request | HAL buffer | PortAudio latency |
|---|---|---|
| default, or `latency='high'` | 15 frames (0.3 ms) | 0.121 s |
| `blocksize=512` | 512 frames (10.7 ms) | 0.141 s |
| `blocksize=1024` | 1024 frames (21.3 ms) | 0.248 s |
| `blocksize=2048` | 2048 frames (42.7 ms) | 0.461 s |
| `latency=0.1` | 1566 frames (32.6 ms) | 0.441 s |

The real stream now opens with `blocksize=1024`. That makes each I/O cycle 21.3 ms instead of 0.3 ms, which is longer than the observed 13.4 ms stall. The cost is about 0.13 s more queued audio before pause and skip are heard. The 100 ms closing silence covers one 21.3 ms host buffer several times over. It is not meant to cover the 0.248 s PortAudio latency, which drains before the output unit stops.

- `test_real_stream_requests_a_host_buffer_longer_than_an_observed_stall` (medium) replaces `sounddevice` with a recording fake and requires the requested block duration to exceed the observed stall. On unfixed code it failed with `PortAudio chooses its own minimum host buffer` (block size 0).
- A real-device probe drove `SoundDeviceSink` ten times with 2 s of digital silence under each setting. Neither setting produced an overload. Without the memory pressure seen in the daemon, the stall did not reproduce on demand. The probe confirms that the new block size plays clips end to end on the device. The overload report and the buffer measurements are the evidence for the fix, and the listener's ear is the acceptance check.
