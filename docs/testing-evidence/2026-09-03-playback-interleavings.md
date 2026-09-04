# Playback interleaving evidence

Date: 2026-09-03

Change kind: new feature (test instrumentation)

Oracle: architecture sections 2 and 7 require one playback owner, terminal
outcomes that remain truthful under Pause, and a global hold that prevents the
next clip from starting

## Scheduling boundary

`PlaybackSchedulePort` names the controller's three cooperative scheduling
boundaries: before reading the plan, after deciding the plan is idle, and after
the audio sink reports a result but before that result changes durable state.
The production adapter passes each checkpoint immediately and therefore does
not add a scheduling yield. The test adapter can gate and witness them with
`asyncio.Event` and `asyncio.Condition`.

The same plan-idle witness replaces every fixed `sleep(0.05)` and `sleep(0.02)`
in the playback suite. Negative claims now wait until the controller has
actually evaluated the plan rather than assuming a timer was long enough.

## Explored schedules

The current controller has one shared-ownership race: a sink result can return
while Pause is changing the current item and persistent global hold. The suite
explores the Cartesian product of both sink results and both relevant orders:

- `natural_pause_first`
- `natural_terminal_first`
- `failure_pause_first`
- `failure_terminal_first`

For terminal-first schedules, the next plan read is gated so Pause is ordered
after terminal classification but before another clip can acquire the device.
Each named pytest id is the replay artifact.

Safety assertions require the current clip to become Played or Failed with the
correct error, the following clip to remain Ready, the hold to remain engaged,
the controller to have no current id, and the sink to report zero overlap.
The liveness assertion requires the controller task to reach another idle plan
cycle and remain running after every released schedule.

## Calibration

The one semantic projection was shown able to fail by mutating the plan guard
to ignore global hold. All four schedules then started the following clip,
reported it Playing, installed its id as current, and recorded a second sink
start. The mutation was reverted before the GREEN run.

Replay one schedule with:

```console
uv run pytest 'tests/test_playback.py::test_pause_and_sink_result_interleavings_hold_the_next_clip[failure_terminal_first]'
```

## Remaining boundary

The four schedules exhaust the current event-loop race between the single sink
watcher and Pause; they do not claim to model threads inside CoreAudio or a
future multi-process playback owner. Any new controller await point or transport
transition must add a checkpoint or schedule case before it can inherit this
claim.
