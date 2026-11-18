# Rust daemon queue operations and store-keyed submission — 2026-11-18

Part of issue #145. Agent-written evidence, not human acceptance.
Change kinds: a bug fix (store-keyed submission) and a feature (socket wiring).

## Store-keyed submission (bug fix)

The known issue from PR #203: after a restart, the conductor loads no history,
so its own normal key could be lower than the store's `MAX(order_key) + 1`.
`Durable::submit` now stores the utterance through `Ledger::admit`
(`StoreLedger` calls `Queue::submit`), then admits it with
`Command::Admit` at the store's key. A known id is refused before the store is
touched.

Oracle: Python `Store.submit`, read back from the store rows.

| Test (`conductor_admit.rs`) | Red on the stub |
|---|---|
| `a_submission_after_a_restart_takes_the_store_key_after_history` | conductor `[(next, 1.0)]` vs store `[(next, 2.0)]` |
| `a_duplicate_submission_is_refused_and_stores_nothing` | `Ledger(Store(UNIQUE constraint failed))` |
| `a_restart_with_queued_work_keeps_keys_and_holds_playback` | passed (no history); calibrated |

## Socket operations (feature)

The daemon starts one conductor thread on its own store connection. That thread
recovers the queue with playback held, and the API thread reaches it through a
bounded mailbox (capacity 64). `pause`, `resume`, `cancel`, `clear`
(`queue`) and `reorder` are answered in the Python reply shapes.

Oracles:
- The Python reference transcripts in
  `crates/aitts-protocol/tests/fixtures/wire/` (`pause`, `resume`). The decoded
  replies must be equal.
- For cancel, clear and reorder, the Python handlers `_op_cancel`, `_op_clear`,
  `_op_reorder` and `Store.reorder_pending`, read as the specification.
- Every reply decodes through `aitts_protocol::decode_reply`.

There is no audio sink in this daemon, so nothing is played.

`control_operations.rs` (medium; loopback Unix socket):

- the pause and resume transcripts;
- cancel of a queued item, an unknown id (`not_found`) and a history item
  (`illegal_state`);
- clear queue, counting 2 and leaving history alone;
- reorder, and refusal of a partial reorder (`bad_request`, order kept);
- a restart that keeps the reordered queue and holds playback;
- concurrent clients.

Concurrent clients: two client threads cancel disjoint halves of 8 queued
items. Any arrival order is legal, because the conductor serializes them. The
oracle does not depend on order: every cancel succeeds, and every item ends
Cancelled. The forced interleavings of the mailbox itself are in
`conductor_mailbox.rs` (part 3).

Red on the stub (`control::answer` answered nothing): 9 of 10. Partial reorder
passed, because the stub's refusal was also `bad_request`; it is calibrated.

## Calibration

Each fault was planted alone, each test run with a 30 s kill limit, and the
file restored in a `finally` block.

| Fault | Failing tests |
|---|---|
| Hold reported inverted | pause and resume transcripts, restart |
| History cancel reported as not found | history cancel |
| Unknown cancel reported as illegal | unknown cancel |
| Cancel not sent to the conductor | queued, unknown and history cancel; concurrent clients |
| Clear count reported as zero | clear queue |
| Partial reorder reported as internal | partial reorder |
| Reorder reply ids reversed | reorder |
| Admit ignores the store key | after-history key, restart keys |
| No duplicate check before the store | duplicate submission |
| Restored queue not held | restart keys and hold (admission suite) |

## Repeats

Ordinary repeats (stable libtest does not shuffle):
`cargo test -q -p aitts-daemon --test control_operations --test conductor_admit`,
10 times; all passed.

## Not covered (remaining for #145)

- `submit` and `requeue` over the socket: segmentation, voice and engine
  resolution, and the submit reply. That part needs recorded Python
  transcripts for cancel, clear and reorder after a real submit.
- Driving synthesis from the conductor in the daemon, with a sink that
  discards audio.
- Events (`plan_reordered`, state changes) for subscribers.
- `clear` of `history`, `input` and `playback`.
- Persisting the hold to the `playback_held` setting that `status` reads.
