# Speech composer

Change-kind: feature

The composer is an in-memory, editable source surface. File/clipboard/selection
imports append without enqueueing. Explicit Speak captures a typed request;
failures preserve the draft and successful admission clears it with a queue/hold
confirmation. Its model selector exposes the default and active backend today;
multiple registered models remain the separate prompt-4 routing work.

## Initial boundary evidence (`7af1e62`)

Medium Swift tests use owned document, clipboard, selection, and speech ports;
no user clipboard, Accessibility target, network, model, or speaker is observed.
A main-run-loop deadline drains known operation completion, without XCTest async
method invocation. Import→edit→submit is one user-facing protocol exchange.
The wire contract checks final text, voice, model, interpretation, confidentiality,
and source attribution. Draft validation covers whitespace and aggregate UTF-8
byte limits with atomic refusal of oversized attachments. Existing native reader
tests retain the PDF extraction/limits contract.

Red: omitting the model from the socket projection produced nil versus kokoro.
Python socket red: requesting an unavailable model was incorrectly accepted.
Both passed with explicit model projection and fail-closed admission.

Falsification receipts (all assertion failures, restored before final checks):

- Corrupt request fields: exact text, voice, model, format, confidentiality and
  source assertions each failed; the complete imported submission failed too.
- Remove empty/byte-limit admission checks: refusal assertions failed, and an
  oversized import changed the draft and origins instead of retaining them.
- Leave busy set and suppress success clearing/hold notice: imported sequence,
  completion state, cleared draft, and pause guidance assertions failed.
- Clear on daemon refusal and mislabel it as success: retained text, exact error,
  and absent-success assertions failed.
- Submit during import: zero-submission witness and final single-submit contract
  both failed.
- Change refusal message to omit model: model-specific refusal assertion failed.
- Persist a clip before refusing: all-state store counts changed, failing the
  no-admission assertion.

Full Python suite: 602 tests pass, within class budgets. Ruff, formatting, mypy,
and diff checks pass. All four focused composer tests pass. The final full Swift
run reached the existing async caption-preference test and terminated with
signal 11, matching issue #6. The earlier 110-test run passed before adding the
two controller tests; that is not claimed as a clean final full-suite result.
No retry was used. The runner failure is handled separately from this feature.

Deletion: remove draft tests only when the composer contract is retired; retain
model admission tests while callers can request an explicit model. Live GUI,
Accessibility permissions, and model quality remain manual acceptance surfaces.

## Integrated audit

The historical XCTest invocation failure above is mitigated by the fix already
merged to main; integration passed the full 124-test Swift suite. The composer
wait helper now uses completion events instead of wall-clock polling. See the
[PR 31 audit receipt](2026-09-30-pr31-audit.md) for corrections and calibration.
