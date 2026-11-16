# Input audio retention decision plan

Issue: [#124](https://github.com/flyingrobots/AI-TTS/issues/124).
Change kind: feature (design decision only; no runtime behavior change).

The owner has delegated decision authority in this session. Record a decision
in `docs/design/tech-stack.md` and `ROADMAP.md`, with alternatives and costs.
The scope is captured input audio on disk. Transcript text retention and
generated speech caches remain outside this decision.

Before editing, inspect the README confidentiality contract and the transcript
store issue. Record the missing decision as the RED acceptance state. Select
the policy and verify that both required documents state it consistently,
distinguish proposed work from implemented behavior, and link the downstream
store task. Check cancellation, expiry, recognition failure, and crash
implications in the proposed contract. Do not capture real audio or claim a
runtime privacy guarantee from documentation checks.

Run ordinary hooks and hosted CI. Replace this temporary plan with the final
decision and post evidence in the PR before marking it ready. Documentation
is agent-written and has not received human editorial review.
