# Shared Rust wire contract plan

Issue: [#125](https://github.com/flyingrobots/AI-TTS/issues/125).
Change kind: feature. No socket client or server is added.

Prerequisite #114 is closed. Base `38d967c` has 31 operations in the daemon
dispatcher plus transport-level `subscribe`. Capture this full inventory,
including success replies, errors, and emitted events. The application schema
module covers only part of the wire; inspect the actual dispatcher and IPC
boundary as well as architecture section 5.

Create `aitts-protocol` with typed requests, operation-specific replies, events,
errors, and a JSON Schema export. Keep absence distinct from explicit null where
the wire permits both. Reject unknown fields with typed errors. Preserve the
1 MiB request admission boundary without adding a socket implementation.

The nine #114 golden transcripts mask identifiers, times, PIDs, and owned
paths. Those markers are comparison notation, not valid wire values. Capture
concrete synthetic reference conversations, verify their normalized form
against the unchanged goldens, and round-trip the concrete JSON through the
Rust types. Never weaken numeric wire fields to accept `<time>` or `<pid>`.
Publish only synthetic paths and content, with the projection documented.

Observe failing public-API tests before implementation. Cover each operation,
all golden conversations, absent and null optional fields, the request size
boundary, unknown fields, and generated value round trips. Validate the schema
against the same accepted and rejected cases; calibrate load-bearing checks by
deliberately breaking the subject. Keep debug/release, format, Clippy, ordinary
hooks, and current-head CI gates.

#130 is independently implementing the Cargo workspace in PR #175. Reuse its
reviewed toolchain, lint policy, and CI after integration instead of inventing
competing root configuration. Shared files are an integration constraint, not
a new logical dependency in the issue graph. Until then, record the wire
inventory and prepare bounded tests in this isolated branch.

Replace this temporary plan with a completed evidence record. Keep the PR
draft until acceptance and local/hosted checks pass. Documentation is
agent-written and has not received human editorial review.

## First implementation checkpoint

The request codec was observed RED with three failing public-API tests before
implementation. All four request tests then passed: the 32 operation examples,
absence/null/false preservation, closed fields and value kinds, and the complete
1 MiB line boundary. A separate transcript test failed against the empty reply
codec, then passed all 30 concrete records from the nine reference conversations.

Provenance tests first failed because no provenance reply was supported. The
three tests now pass with bounded historical objects. Known metadata fields
retain typed validation; historical extensions retain their original values.
Each archived object permits at most 32 value levels, 4096 values including
containers, and 65536 UTF-8 bytes in keys and string values. The complete reply
or event has a separate 16 MiB encoded-line admission ceiling. These are local
Rust limits, not claims about Python's response-size policy.

The current eight tests and strict Clippy pass on Rust 1.99.1. This is a draft
checkpoint. JSON Schema export, the expanded source-derived reply/event corpus,
generated-value checks, fault calibration, release validation, and final CI
remain pending. PR #178 is temporarily based on PR #175's published branch;
it must integrate current main and retarget main after #175 lands.
