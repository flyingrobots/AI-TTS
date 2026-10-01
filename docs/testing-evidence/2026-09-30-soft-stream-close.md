# Soft stream close on skip, stop, and pause

Change-kind: bug fix, with a deliberate change to the stop-fade contract that James approved.

## Fault

The listener heard a pop on every skip. Per-clip evidence for the skips at 20:45 on 2026-09-30 showed `stream_opened`, `stream_closing` with zero underflows, and a 146 ms drain before `session_ended`. The digital stream was continuous: the old 5 ms ramp started at the last written sample. Closing the stream drains PortAudio's ring buffer and then stops the CoreAudio output unit, which can truncate the hardware buffer still in flight. The 120-frame ramp was shorter than that buffer, so the cut fell on speech. A natural end does not pop because the clip's own tail is silent. Pause returned without any fade.

This mechanism is inferred from the evidence above and from how PortAudio stops a stream. No automated test reproduces CoreAudio's truncation. The listener's ear on the installed build is the acceptance check.

## Fix

On stop or pause, after the last source block, `SoundDeviceSink` writes one closing block. The block is the next 20 ms of source audio, resampled at the current rate and faded by a raised cosine, followed by 100 ms of silence. The silence exceeds the 78 ms output latency PortAudio reported on the built-in speakers. The fade reads ahead without moving the playhead, so resumption repeats nothing. Device-change reopen paths are unchanged.

## Assertions

Oracle: the listener report and the CoreAudio close behavior above. Size: medium. Each test uses an owned WAV and a recording output stream.

- `test_stop_fades_to_held_silence_without_consuming_more_source` replaces `test_stop_ramps_to_silence_without_consuming_more_source`. The old test pinned the 120-frame ramp and its monotonic shape, which is exactly the behavior being retired. The new test requires that no sample-to-sample step exceeds 0.01, that the final 100 ms is exact silence, that the fade starts at the next source sample, and that the playhead stays at 85 ms. On unfixed code it failed: the stream held 2168 frames, not the 2400 silent frames required.
- `test_repeated_pauses_release_output_and_resume_without_changing_samples` still requires every source frame to be heard exactly once. It now excludes each paused stream's closing block and requires that block to close softly. On unfixed code it failed: the paused stream ended after 2048 frames with no tail.
- `test_default_output_change_while_paused_is_adopted_on_resume` keeps its frame-conservation check, minus the paused stream's closing block, and also requires a soft close.
- Mutations: setting the silence to 0 s failed all three with `the stream closes before its output has gone silent`. Setting the fade to 0 s failed all three with `the fade has an audible step`. Both mutations were restored and the tests went green.

## Validation

- Full Python suite: 239 small and 457 medium tests passed. ruff and mypy are clean.

Limits: the recording stream cannot show CoreAudio's truncation, so these tests prove the written signal, not the absence of a pop. Retire them if the sink stops closing the device between clips.
