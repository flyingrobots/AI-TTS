# Rust wire contract and schema evidence

Issue: [#125](https://github.com/flyingrobots/AI-TTS/issues/125).
Change kind: feature.
Toolchain: Rust 1.99.1 (`58cf8f9c3`), `aarch64-apple-darwin`.

The `aitts-protocol` crate defines the current daemon's requests, replies,
errors, and subscription events without adding a socket client or server.
It has no dependency on the domain crate. The Cargo workspace is shared
build infrastructure, not a semantic dependency on domain values.

## Reference and scope

The dispatcher at `38d967c26f158472e366dcc7b779258228cc6e3e` has 31 operations;
the IPC transport adds `subscribe`. The request inventory covers all 32.
Reply decoding takes the originating operation because replies have no
operation tag.

The nine concrete reference conversations contain 30 records. Both the raw
capture and its synthetic-home projection matched the unchanged Python
goldens. Rust round trips preserve their JSON values, including numeric
timestamps and explicit false/null fields. The types do not accept comparison
markers such as `<time>` in numeric fields.

The expanded source-derived corpus has 32 operation replies and 14 event
shapes, including both forms of `history_changed`. These examples describe
field names and value kinds; they are not additional runtime captures or
claims that every synthetic state combination is reachable.

A separate fixture records the actual model-catalog projections from
`7b23b96c728317b726a82804b1891aabb48352bb`. Its three source-file SHA-256 values
were checked against the committed tree. Both catalog operations preserve
null/current/unknown/stale adapter status. Older absence remains distinct
from null. The original nine conversations were not changed. See the
[fixture provenance](../../crates/aitts-protocol/tests/fixtures/README.md).

## Observed RED to GREEN

| Increment | Observed failure before implementation | Passing result |
| --- | --- | --- |
| Requests | Three public-API tests failed against the empty decoder | All 32 request shapes round trip; absence/null/false and the complete 1 MiB boundary remain distinct |
| Replies and events | The concrete conversation test failed at the first reply | All 30 captured records round trip without normalization |
| Historical evidence | Two provenance tests failed against the missing reply implementation | Saved extensions survive; known metadata kinds and archive limits are checked |
| JSON Schema | The valid-corpus test failed against an empty false schema | Requests, replies, events, and known invalid cases agree with the documented schema boundary |
| Legacy arguments | Two public-API tests failed when provenance arguments required an object and the new admission constructor was a refusing stub | Eight real Python arguments/origin projections round trip; caller-constructed values obey the same limits |
| Code-only setup consent | Supplied `refresh_only` booleans failed against the closed request type | Omission, false, and true survive codec/schema round trips; null and wrong kinds are refused |

Schema validation also found a real integration defect after the initial
implementation. The derived closed `history_changed` alternatives rejected the
enclosing event tag. An explicit object-level exclusive schema permits either
`cleared` or `removed`, rejects both or neither, and keeps unknown fields closed.

Self-review found a separate compatibility gap in `provenance.arguments`.
Python preserves scalar and array values in legacy saved request metadata.
Eight public socket calls at `aa8d7b3` confirmed null, false, integer, float,
string, array, and object behavior. `ArchivedValue` now admits those values
before copying or storing them. Its private field prevents unchecked mutation.
The other metadata records remain object-only, and the arguments field remains
required. A synthetic audio-evidence warning was outside the captured
arguments/origin projection; this check does not prove usable audio metadata.

## Assertion calibration

Twenty deliberate source faults each produced the intended failing test
assertion. A compiler failure did not count as a calibration result. The
fault runner restored the exact source bytes after each case and checked for
unexpected concurrent edits before restoring.

| Injected fault | Detecting assertion |
| --- | --- |
| Reject the inclusive request-byte boundary | Exact 1 MiB request is accepted |
| Accept unknown request fields | Every request envelope is closed |
| Serialize absent fields as supplied null | Generated optional fields preserve presence |
| Accept unknown transport-reply fields | Every reply envelope is closed |
| Raise the archive depth limit | One extra value level is refused |
| Raise the archive value-count limit | One extra value is refused |
| Raise the archive text-byte limit | One extra UTF-8 byte is refused |
| Skip known metadata validation | Wrong known metadata kinds are refused |
| Allow both history-change forms at once | The schema refuses an ambiguous event |
| Reverse the daemon failure flag | Each error code round trips for every operation |
| Change an event timestamp to a string | Concrete numeric transcript fields remain numeric |
| Serialize only known evidence fields | Historical adapter extensions remain present |
| Make a required nullable field optional | A missing reply field differs from explicit null |
| Remove constructed-archive text admission | UTF-8 bytes are checked before copying |
| Accept unknown nested runtime fields | Complete known records reject an added field |
| Accept an unknown adapter-status token | Catalog status remains a closed vocabulary |
| Return the wrong request operation context | Every request selects its matching reply operation |
| Skip constructed historical-value admission | Oversized caller-constructed legacy arguments are refused |
| Omit supplied setup consent during encoding | Explicit false and true remain present |
| Permit null setup consent | Null is refused by the codec and schema |

Faulted property runs used a fixed seed and disabled saving their deliberately
invalid regression cases. Ordinary generated runs retained the normal
property-test behavior.

## Local checks

The complete suite has 33 tests. It passes in debug and release profiles.
Ten complete debug runs passed with property seeds 1250 through 1259. The
generated tests vary strings, integer and floating-point values, booleans,
closed vocabularies, and optional-field presence across the operation and
event corpus.

Strict Clippy, all-target compilation, and formatting pass:

```sh
cargo test -p aitts-protocol --tests --locked
cargo test -p aitts-protocol --release --locked
cargo fmt --check
cargo clippy -p aitts-protocol --all-targets --locked -- -D warnings
cargo run -p aitts-protocol --example schema --quiet --locked
```

The schema command produced one valid 98,611-byte JSON document. Its SHA-256
is `2dc74c8fded74fe5a1d4dfe1e2caf0363a3a81bccb1304a3e0a22980d3dc3baa`. The schema
tests check valid source-derived messages, unknown fields, required nullable
fields, wrong known metadata kinds, error discriminators, and archival
extensions. JSON Schema's mathematical-integer treatment of `1.0` differs
from Rust's integer JSON-number-kind requirement; an explicit test records
that boundary.

Normal pre-commit checks passed at the first published implementation
checkpoint `fada447`. Normal pre-push checks passed 1,239 Python tests with
two skips and a complete Swift build. The default local Swift backend first
exceeded the unchanged 256 MiB logical per-file ceiling. A narrowly scoped
local invocation shim selected `--build-system native --disable-index-store
--jobs 2` for the same pre-push build. Hooks, compiler checks, exit status,
and resource ceilings were preserved. Default-backend hosted Swift CI
passed at that checkpoint; local backend selection does not replace CI.

## Limits and remaining gates

The library is a strict supported subset of Python's accepted inputs.
Unknown request fields and ignored wrong-kind values are refused. The legacy
`history.limit: true` and `snapshot.limit: true` behavior is retained
explicitly; false is refused. Application policy still owns speed ranges,
available engines and voices, allowed retention days, and lifecycle legality.

Requests have the existing 1 MiB line limit. Replies/events have a local
16 MiB line ceiling. Each historical value has separate limits of 32 value
levels, 4,096 values, and 65,536 UTF-8 bytes in keys and string values.
The complete line is admitted before parsing; Serde can buffer within that
ceiling. These response and archival limits are Rust admission policy, not
claims about Python's existing response limits. The
[crate contract](../../crates/aitts-protocol/README.md) describes the open
historical boundaries and schema limitations.

Local checks used owned caches and output paths, two build jobs, a 300-second
command deadline, a 240-second CPU limit, sampled memory/process limits,
and unchanged project storage budgets. No live model, audio device, operator
daemon, or download was needed. The local runner's process-group cleanup is
not proof of complete descendant custody if a child creates a new session;
no forced-stop test campaign relies on that claim.

At this evidence checkpoint, PR #178 remains draft and temporarily targets
PR #175's published branch. It must integrate current main after #175 lands,
retain the #179 catalog contract, retarget main, and pass fresh CI and review
before readiness and merge. The `refresh_only` type matches the settled #179
request design; its final producer source and runtime capture still need a
compatibility check. Codec tests do not establish the daemon's no-download
admission guarantee. Merge and issue closure remain separate gates.

This evidence record is agent-written and has not received human editorial review.
