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
