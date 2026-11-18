# Rust daemon subscriber events — 2026-11-19

Part of issue #145. Agent-written evidence, not human acceptance.
Change kind: feature.

`Durable` keeps an event for every change the ledger recorded, and the
conductor thread publishes them to subscribers after each request:

- `state_changed` for each transition. Each event is stamped with the time
  the store wrote (`Queue::save` now returns it; `Ledger::stamp`). Events come
  in Python's order: the speaker leaving the device first, then a preempted
  speaker leaving the stack, then queue order.
- `state_changed` from `null` to Queued for each admission.
- `plan_reordered` for a reorder.

The API thread publishes `voice_assigned` when a submission claims a voice.
A change the ledger did not record produces no event.

## Oracles

Python `_announce_admission`, `_on_transition`, `_op_reorder`,
`_suspend_current` / `_start_saved` (suspend before start),
`clear_preempted` before `clear_pending`, and `VoiceRegistry.resolve`
(`voice_assigned` before the admission), read as the specification. Event
times must equal the store's own stamps, which the test reads through a
separate connection. Every line must decode through `decode_event`.

## Tests

- `conductor_events.rs` (small):
  - preemption order;
  - clear order, with an urgent pending item that sorts before the preempted
    speaker;
  - the reorder event;
  - no event for an unrecorded change.
- `events.rs` (medium; socket):
  - the exact event sequence for submit, an agent submit with a voice claim,
    cancel, submit and reorder;
  - each transition of a driven clip, in order, with the fake worker and
    `DiscardingSink`.

## RED to GREEN

Against the stubs (no events), 5 of 6 failed. The no-event test passed,
because it asserts absence; it is calibrated. Test correction: the socket
test first read each line through a new `BufReader`, which drops lines that
arrive together.

## Calibration

Each fault was planted alone, each test run with a 45 s kill limit, and the
file restored in a `finally` block.

| Fault | Failing tests |
|---|---|
| No device-first ordering | preemption, clear (after the test correction) |
| Events before the record | no-event, clear, preemption |
| Wrong time stamp | clear, preemption, socket sequence |
| No reorder event | reorder, socket sequence |
| No admission event | socket sequence, driven clip |
| Conductor thread does not publish | socket sequence, driven clip |
| No `voice_assigned` | socket sequence |

One fault survived and is equivalent: putting stack speakers before the
device speaker. No single change both moves a Playing clip and moves a
Paused one.

## Repeats

Ordinary repeats:
`cargo test -q -p aitts-daemon --test events --test conductor_events`, 10
times; all passed.

## Not covered (later parts)

- `segment_state_changed`.
- `history_changed` (the history clear part).
- `settings_changed`, `voice_released`, `cache_changed`, `playback_progress`,
  and the model events.
