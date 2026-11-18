# Rust daemon submit and requeue — 2026-11-18

Part of issue #145. Agent-written evidence, not human acceptance.
Change kind: feature, plus one deliberate behavior change: the read-operation
test that used `submit` as an example of an unwired operation now uses `skip`.

`submit` resolves a submission on the API thread, then stores and admits it
through the conductor mailbox at the store's order key. Resolving covers text,
sensitivity and engine eligibility, speed, Markdown segmentation, and voice
claims through `aitts_domain::voices` and the store's voice register.
`requeue` replays a history item with `replay_of`.

## Oracles

- The Python reference transcript
  `crates/aitts-protocol/tests/fixtures/wire/submit.json` (pause, a submit, a
  synthesis-only submit). Decoded replies are equal except the generated
  `utt_` id. The test checks the id's format and substitutes it into the
  expected reply.
- The Python handlers `_op_submit`, `_op_requeue`, `_replay`,
  `eligible_engine_names`, `_speech_admission` and `VoiceRegistry.resolve`,
  read as the specification.
- Python `prepare_speech_segments("**bold** text", content_format=markdown)`
  returns `("bold text",)`, so the submission is composite with one segment
  (run with `uv run` at this commit).

## Tests (`submit_operations.rs`, medium; loopback socket)

12 tests:

- the transcript;
- blank text, private speech on a remote engine, public speech on a remote
  engine, and an unknown voice;
- the `preempt` flag;
- composite Markdown;
- agent voice claims;
- requeue of a played item (urgent), of unfinished work, and of an unknown id;
- concurrent clients.

The concurrent-clients test submits from two client threads, 4 items each. Any
arrival order is legal, and the oracle does not depend on it: every
submission is accepted, and each client's items keep their order in the queue.

## RED to GREEN

Against the stub (submit and requeue unwired), 9 of 12 tests failed. The three
`bad_request` refusals passed, because the stub's refusal was also
`bad_request`; they are calibrated below. The implementation commit made all
12 pass.

## Calibration

Each fault was planted alone, each test run with a 30 s kill limit, and the
file restored in a `finally` block.

| Fault | Failing tests |
|---|---|
| Whitespace-only text accepted | blank text |
| Private speech allowed on a remote engine | private remote |
| Public speech refused on a remote engine | public remote |
| Unknown voice accepted | unknown voice |
| `preempt` ignored | preempt |
| Composite judged by segment count only | composite Markdown |
| Voice claim not recorded | agent voice claims |
| Hold inverted in the admission fields | transcript |
| Requeue of unfinished work allowed | requeue unfinished |
| Requeue not at the head | requeue played |
| Requeue without `replay_of` | requeue played |
| Normal work admitted at the head | concurrent clients |
| Upper-case id hex | transcript |

## Repeats

Ordinary repeats (stable libtest does not shuffle):
`cargo test -q -p aitts-daemon --test submit_operations`, 10 times; all passed.

## Not covered (later parts of #145 or follow-ups)

- Language-restricted voice pools for agent sources.
- Per-engine speed restrictions.
- Clip evidence on submit.
- Events.
- Reuse of a replay's cached audio.
- Synthesis, which is the next part.
