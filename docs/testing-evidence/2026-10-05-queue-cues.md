# Queue intro and outro cues

Change-kind: behavior change.

The existing earcon setting now brackets a queue with the user-created ascending
intro and descending outro WAVs. Pending synthesis keeps the session open;
chunks, pause/resume, and speaker changes do not replay the intro. Both WAVs
are included in wheels. Intro PCM is resampled to the existing 24 kHz prefix
contract; the outro uses the serialized sink at normal speed.

The queue test enters through PlaybackController with a deterministic schedule
and an owned audio sink. The oracle is the requested queue behavior. It checks
setting on/off, two speakers, drain, and a subsequent new session. Existing
pause/chunk and source-clock tests remain applicable. The waveform assertion
checks duration and exact source samples at coincident 44.1/24 kHz timestamps.

Falsification: temporarily removing the session-open condition failed the
second-speaker empty-prefix assertion. Temporarily disabling queue completion
failed the expected third playback (outro) assertion. Both seeds were restored.

Focused validation: 37 cue/playback tests passed. Real hardware acoustic
acceptance and replacement of the running installed daemon are not claimed.

Final validation: all 957 Python tests passed; changed-file Ruff lint/format
and focused strict mypy passed. Wheel inspection verified both WAVs byte for
byte against the original assets. Swift was not run because it is unchanged.
