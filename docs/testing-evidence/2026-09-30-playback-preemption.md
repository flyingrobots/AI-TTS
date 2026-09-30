# Playback preemption — September 30, 2026

Change-kind: feature

Prompt 1 of the local `PROMPTS.md` backlog. Public behavior: explicit preempt
submissions take the device when their first audio is Ready; ordinary Urgent
submissions retain their queue-only meaning. Nested interruptions unwind in
LIFO order at the saved chunk and source offset. A listener/microphone hold
wins over an in-flight handoff. Queue clearing skips suspended work and leaves
the current alert alone. Recovered paused records require explicit Resume.

## Boundary and controlled schedule

`test_playback_preemption.py` enters through PlaybackController with the real
SQLite Store and the existing contract FakeSink. A condition-driven schedule
witnesses planning turns. A deliberately delayed device release schedules a
hold or cancellation *inside* the handoff; there are no timing sleeps or
stress loops. Tests are medium, with the repository's 15-second ceiling.

The multi-step nested test is one protocol: document chunk 2 at 375 ms → alert
at 125 ms → nested alert → alert at 125 ms → document chunk 2 at 375 ms. Three
terminal outcomes are enumerated: Played, Failed, Skipped. Device overlap must
remain zero. Separate cases cover queue clearing, holds, restart recovery,
cancellation during handoff, and a document waiting for its next synthesis
chunk. The CLI test uses a live owned daemon and FakeEngine; MCP uses its SDK
client and a typed application-port fake. The output-stream test captures real
PCM writes from SoundDeviceSink while substituting only the hardware stream.

## Red before implementation

After adding only the new Priority enum value (so the behavior test could reach
the controller), all three nested terminal cases failed at the first takeover:
`controller.current_id` still named the document instead of the alert. Command:

```
uv run pytest tests/test_playback_preemption.py -q
```

The stop-envelope test failed before the sink change: `len(blocks) == 2` saw
one block. The cancellation schedule exposed a real invalid `Cancelled ->
Playing` transition during handoff; re-reading the alert after device release
fixes it without retrying or suppressing that error.

## Assertion calibration

Each fault below was applied alone, run against its named boundary test, and
restored in `finally`. Python caches for the edited module were invalidated.
All 19 runs failed with assertion failures (exit 1):

| Deliberate fault | Witness |
| --- | --- |
| Bypass preemption planning | First takeover still names the document |
| Pop oldest suspended item | Nested resumption has wrong clip/offset |
| Restart saved chunk at zero | Exact saved source offset differs |
| Save parent progress as zero | Document progress differs from 1375 ms |
| Ignore global hold | Held document is interrupted |
| Leave suspended stack uncleared | Clear receipt is zero and backlog survives |
| Mark cleared clip Played | Expected Skipped history differs |
| Omit recovered suspended entries | Document does not resume after alert |
| Omit stop envelope | Only one PCM block |
| Halve envelope duration | Tail has 60 instead of 120 frames |
| Start envelope below last sample | Discontinuity at splice |
| End envelope above zero | Nonzero final sample |
| Insert increasing sample in envelope | Monotonic fade assertion fails |
| Advance source position for envelope | Saved source position changes |
| Drop CLI preempt flag | Persisted priority is normal |
| Drop MCP preempt argument | Application-port request has false |
| Omit between-chunk progress | Saved 1000 ms becomes zero |
| Reuse device without stopping | Sink overlap counter becomes nonzero |
| Keep stale handoff offset | Final accepted block at 350 ms is lost |

The existing exact Priority inventory/schema assertions were extended with the
new enum value; their previous expectations failed against the added value.
Deletion criterion: remove these tests when preemption or the relevant public
adapter contract is removed, not when implementation details move.

## Limits

The controller cannot interrupt with audio that has not been synthesized yet.
The device handoff waits for the final accepted block and a 5 ms fade; it does
not promise zero latency. Source offsets use the existing integer-millisecond
AudioSink contract. Hardware listening across every output device is not
covered: waveform continuity at stop is measured at the PCM boundary. This
feature does not close the long-session popping investigation (#25).

## Final gates

`uv run pytest -q`: 588 tests passed (215 small, 373 medium), 8.12 seconds
wall time. Ruff check, Ruff format-check, mypy (100 source files), and
`git diff --check` passed. No Swift source changed.
