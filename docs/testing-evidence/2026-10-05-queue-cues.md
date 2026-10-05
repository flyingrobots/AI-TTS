# Queue intro and outro cues

Change-kind: behavior change.

The existing earcon setting brackets a queue with the user-created ascending
intro and descending outro WAVs. Pending synthesis keeps the session open;
chunks, pause/resume, and speaker changes do not replay the intro. Both WAVs
are included in wheels. Intro PCM is resampled to the existing 24 kHz prefix
contract; the outro uses the serialized sink at normal speed. There is 150 ms
of source-clock-independent silence after the intro, before each subsequent
new speaker, and before the outro. Disabled earcons add no cue or padding.
A global hold stops an active outro and restores the speech playback rate.

The queue test enters through PlaybackController with a deterministic schedule
and an owned audio sink. The oracle is the requested queue behavior. It checks
setting on/off, two speakers, drain, padding, and a subsequent new session.
Existing pause/chunk and source-clock tests remain applicable. The waveform
assertion checks duration and exact source samples at coincident 44.1/24 kHz
timestamps; the padding test checks 3,600 exact zero PCM16 samples.

Falsification: removing the session-open condition failed the second-speaker
prefix assertion; disabling queue completion failed the expected outro start.
Removing speaker padding failed the queue prefix assertion. Removing outro
hold handling failed the bounded sink-completion observation. Seeds were
restored immediately; they were not retried into green.

On current main, old interruption tests assumed the old product cue was loud
at a specific sample. Their waveform now belongs to the test, using the same
short sine/envelope fixture, so their fade assertions and non-vacuity witnesses
continue to check interruption independently of the new intro's gentle onset.

## Validation

The initial old-branch candidate passed all 957 Python tests. That count is
not evidence for current main. The final candidate is based on main 3345ad6:
59 cue, playback, preemption, and shutdown tests passed. Changed-file Ruff
lint/format and focused strict mypy passed. The full current-main Python suite
and unchanged Swift suite were not run locally; hosted CI remains pending.

The wheel contains both original WAVs byte for byte. The installed Python 3.12
daemon package was refreshed without changing its existing dependencies or
menu-bar app. Installed cue/playback sources were compared byte for byte with
the candidate. The bundled intro and outro resolve from site-packages.

Two sequentially queued voices reached Played in the live padded demo:
utt_bcb46a5d1ab24d0cb2590b185b947cc5 and
utt_7177449e177f4e4698b6a91cbdabbac0. The outro sink recorded natural completion
at normal speed without an error. The user confirmed the audible result.
Acoustic feedback is manual acceptance, not an automated acoustic oracle.

Session scratch evidence and the installed wheel remain under the original
checkout's .scratch/chime (about 1.2 MiB). They can be removed after this PR is
integrated; the installed package does not depend on their continued presence.

## Source release packaging regression

Hosted CI and local `uv build --offline` failed on ab8fb5d because the source
archive omitted assets. The sdist now explicitly includes the original WAVs.
The same complete sdist-to-wheel build succeeds with byte-preserving cues.

## Outro control regressions from review

Both new deterministic boundary tests failed on 7c8ad18: urgent speech remained
blocked behind the outro, and changing speech rate accelerated the outro.
The existing preemption path now releases an active outro before starting the
ready alert; speech-rate updates are saved while the outro stays at normal
speed, and restored when it ends or is stopped. Focused validation includes
61 cue/playback/preemption/shutdown tests.
