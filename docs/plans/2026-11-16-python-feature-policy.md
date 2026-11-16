# Python feature policy during the Rust port

Issue: [#122](https://github.com/flyingrobots/AI-TTS/issues/122)

Change class: deliberate policy change; no runtime behavior change.

## Outcome

Record whether new daemon behavior can enter Python during the port, and how
the operation-set completion task obtains a fixed compatibility target. The
repository owner delegated this decision in the active work session.

## Scope

Update `docs/design/tech-stack.md` and `ROADMAP.md`. Compare a blanket freeze
with continued development, using current merged PRs and contract work.
Do not change runtime code, the Swift application, release behavior, or
the separate model-inference decision.

## Acceptance and verification

- Both maintained documents state the same decision and reason.
- The policy states who pays for added behavior and how the Rust target is fixed.
- Defect corrections and the Swift application remain outside the freeze choice.
- Verify the issue's referenced PR states before relying on its older premise.
- Record the missing decision before editing, then check the completed text,
  relative links, and consistency. Do not add an automated test that merely
  repeats policy prose.
- Run normal hooks and hosted CI. Replace this plan with a completed evidence
  record before marking the draft ready.

## Safe intermediate state

This draft adds only the plan. It does not freeze development or claim that
the Rust daemon or its full compatibility suite exists.
