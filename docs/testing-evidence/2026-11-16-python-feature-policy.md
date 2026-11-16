# Python feature policy decision evidence

Date: 2026-11-16. Issue: [#122](https://github.com/flyingrobots/AI-TTS/issues/122).
Author/reviewer: Codex. Change class: deliberate policy change; no runtime change.

## Freshness and decision authority

The repository owner delegated routine project decisions in the active work
session. This supersedes the issue's older instruction to prepare the decision
for the owner without making it.

Live GitHub checks found that the three PRs named as open in the issue had
already merged: #111 on 2026-10-20, #112 on 2026-10-20, and #113 on 2026-10-21.
The later synthesis-only behavior in #168 also merged before this decision.
These features are part of the current reference; this decision does not undo
them or hold them in a queue. The pure domain crate and external-daemon socket
harness are still in development. No complete Rust daemon was assumed.

The chosen policy permits features during the early port, with reference cases
and a named Rust parity task. A freeze begins with the first implementation
draft for #148 and ends only after #151 meets its cutover and rollback criteria.
This supplies a fixed target when it is needed without imposing a freeze
through every foundational task. The maintained policy states the alternatives,
costs, exceptions, reference-update rule, and reconsideration procedure.

## RED and GREEN document acceptance

Before editing, a one-time check for the decision section failed for both
required files: `docs/design/tech-stack.md` and `ROADMAP.md`. Manual inspection
confirmed neither contained a policy for Python features during the Rust port.

After editing, both sections state the same start/end conditions and reason.
The technical decision covers reference commits, parity ownership, defect
corrections, behavior-preserving refactors, Swift scope, new-work tracking, and
the limits of review enforcement. Relative links and anchors were checked.
The initial plan is replaced by this record.

No permanent test asserts the policy's wording. Such a test would reproduce
the document instead of proving that future PRs obey it. No daemon behavior,
runtime dependency, or branch rule changed.

## Validation boundary

Normal plan-commit hooks passed Ruff, formatting, and mypy for 204 files.
Normal plan-push hooks passed 1,193 tests with two existing skips and built the
Swift application. The local Python interpreter was CPython 3.14.7.
The completed document change must also pass normal hooks and hosted CI before
the draft is marked ready. This record does not claim that the future Rust
conformance or cutover acceptance has run.
