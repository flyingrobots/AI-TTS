# Report and explicitly refresh stale worker adapters

Change-kind: bug fix.

[Issue #164](https://github.com/flyingrobots/AI-TTS/issues/164) requires an installed runtime's adapter identity to be visible and an effective, explicit Retry without automatic installation or model-weight changes. The accepted issue body has SHA-256 `e0761f909264639424b638154f9c5f233b9bc1c64e77e453ce993eb37a0d7c47`.

1. Record RED evidence at the runtime manifest and model-catalog boundaries for missing identity, mismatched identity and current identity. Catalog reads must not start work or alter existing runtimes.
2. Record a stable content digest of the adapter actually copied into a runtime. Add a nullable catalog status for current, stale or unknown private adapters; retain legacy runtimes as usable.
3. Make existing explicit model setup effective for stale/unknown adapters. Stage a separate adapter with direct references to the existing environment and assets, warm it offline, and publish only after success and the existing quiescence boundary. Preserve the incumbent worker, manifest and weight files on failure or cancellation.
4. Decode the status in the Swift client and offer Retry setup with accurate refresh wording. Preserve ordinary install/use flows. Coordinate the new model-catalog field with the Rust protocol parity task #125 and its separate reference cases.
5. Verify supported catalog states, no automatic work, effective retry, cancellation/failure preservation, unchanged assets, repeated refreshes and Swift action policy. Calibrate load-bearing assertions, run focused and required full checks, and replace this plan with a completed verification record.

Scope excludes live daemon or model actions, weight downloads, in-place adapter replacement, runtime garbage collection and automatic refresh. Local tests use owned fixtures and fake process boundaries; live-model and mouse-driven native UI behavior remain explicit validation limits. The PR remains draft until acceptance, test plan and exact-head CI are complete; clean review precedes merge.

This plan is agent-written and has not received human editorial review.
