# Streaming underrun: soft fade and rebuffer

Change-kind: bug fix, with a deliberate change to an existing test's expected envelope under James's standing authorization.

## Fault

On 2026-10-02, the listener heard pops after replaying three history items within a few seconds from the terminal dashboard. None had cached audio, so each was re-synthesized live while it played. Per-clip evidence for the third, `utt_2365d005…_segment_0000`, recorded `underruns: 42` in 924 ms of audio, with zero output underflows. The unified log showed no CoreAudio overloads in that window, and the prepared callback stream stayed open. The pops were therefore in the written signal.

`PCMStreamRenderer._render_speech` handled every short callback by playing what it had and ramping the last sample to zero over 120 samples (5 ms). It resumed with another 120-sample ramp as soon as any PCM arrived. Under contention, that gave one silence gap per callback. #57 and #34 established that sub-buffer ramps are audible, and #76 tracked this remaining 5 ms path.

## Fix

- **Fade:** when a callback would run short, the renderer fades the real upcoming audio over `SOFT_FADE_FRAMES` (20 ms) with a raised cosine, holding the last sample when less remains. The faded frames are read ahead and not consumed.
- **Rebuffer:** the renderer then stays silent, without advancing the source clock, until `REBUFFER_FRAMES` (300 ms at the stream rate) is buffered or the source has nothing more to give.
- **Resume:** it replays the faded frames under a 20 ms raised-cosine fade-in.
- **Startup:** waiting for the first PCM is latency, not an underrun, so first-audio latency is unchanged.
- **`PCMRead.complete`:** the new field reports a sealed and fully read source. Running out of such a stream is the end of the audio, so a stream awaiting publication plays to its end and is not treated as starving.

## Assertions

Oracle: the listener report and the #57/#34 rule that every mid-clip transition to or from silence uses a 20 ms raised cosine. Size: medium. Both tests use an owned `SpoolingPCMStream` and call the renderer directly.

- `test_device_renderer_fades_underrun_without_advancing_source_clock` previously pinned the 120-sample ramp: a maximum step of `0.5 / 119`, and resumption at full level within 240 frames. Its intent is kept: an underrun must not advance the source clock. Its expectations now follow the new contract:
  - The faded frames are not consumed.
  - A 400-frame trickle below the cushion stays silent.
  - Resumption starts at exact zero.
  - No step exceeds 0.01 across the whole sequence.
  - The position advances only by frames actually heard.

  On `main`'s renderer it failed with `assert 1499.0 == 1024.0`, because the faded frames were consumed.
- `test_trickling_synthesis_rebuffers_once_instead_of_crackling` is new. After an initial 1,200 frames, 300 frames arrive per 1,024-frame callback for 30 callbacks. Playback may restart at most twice, with at most two underruns and no step above 0.01. On `main`'s renderer it failed with `playback restarted 30 times: crackle`.
- Mutations, each restored afterwards:
  - `REBUFFER_FRAMES = 0`: both tests failed, with `playback restarted 30 times` and `restarted before the rebuffer cushion`.
  - An 8-sample fade instead of 20 ms: both tests failed.
- The existing `test_sound_device_callback_starts_live_and_drains_only_after_publication` exposed the sealed-stream case during development. It passes unchanged.

## Validation

- Full Python suite: 341 small and 691 medium tests passed. ruff, ruff format, and mypy (185 files) are clean. Swift was not touched.

Limits: the renderer tests prove the written signal. Whether the replay scenario is now inaudible is the listener's acceptance check on the installed build.
