# AI-TTS protocol crate

`aitts-protocol` parses and writes the AI-TTS daemon's JSON-line messages. It
defines the 31 daemon operations, transport-level `subscribe`, their replies,
structured errors, and subscription events. It does not open sockets, run a
daemon, operate models, or depend on `aitts-domain`.

Use `decode_request` and `encode_request` at the request boundary.
`Request::operation()` supplies the context for `decode_reply`: Python replies
do not carry an operation tag. Use `decode_event` and `encode_event` for an
established subscription. Each encoder emits one final newline. Each decoder
accepts one JSON object with optional JSON whitespace and rejects extra objects.

The library returns `WireError` for framing and contract failures. This error
does not retain submitted text or rejected values. A daemon's application
failure is a separate `Reply::Error`, with one of `bad_request`, `not_found`,
`illegal_state`, or `internal`.

## Presence and types

`Presence<T>` distinguishes an omitted field from a supplied value.
`Nullable<T>` permits explicit JSON null without making a required field
optional. For example, a pause reply must contain both `state` and `current`,
even when both are null. A missing submit `source`, an explicit null source,
and a supplied string remain distinct through a round trip.

Known envelopes and nested records reject unknown fields. Counts, identifiers,
flags, lifecycle states, priorities, and known metadata have explicit Rust
types. `Number` retains integer and floating-point JSON number kinds for
timestamps and other numeric fields. Comparison markers such as `<time>`
are not accepted in numeric fields.

The codec checks structure, not daemon business policy. The daemon still owns
voice and engine availability, nonempty text, speed ranges, allowed retention
days, lifecycle legality, and identifier existence. A structurally valid
request is not a claim that an operation can succeed.

`model_setup.refresh_only` is an optional boolean. The codec preserves omission,
false, and true separately and refuses null or other value kinds. True carries
code-only consent; the daemon must refuse a request that needs a full repair.
The protocol crate does not perform that state-dependent admission itself.

## Historical evidence

The producer retains caller arguments and adapter metadata with their
original values. These are the only open historical boundaries:
`provenance.arguments`, and each clip's `generation`, `model`, and `audio`
metadata. Legacy saved arguments can be a scalar, array, object, or null.
`ArchivedValue` keeps that admitted value private under explicit limits.
The other metadata records remain objects or null; `ArchiveObject` admits
their objects. `Evidence<T>` validates the known metadata fields and exposes a typed,
immutable view. An unknown adapter extension survives; a known
`repository` field containing a boolean is refused.

Nested known records, including runtime metadata and model-file identities,
remain closed. The runtime's package-name map and the model's filename map
have arbitrary keys with typed values. These maps do not make the surrounding
message an open JSON envelope.

## Resource and compatibility boundary

Use the public codec functions for untrusted encoded messages. They check
the complete encoded byte count before deserialization:

| Admission | Limit |
| --- | --- |
| Request, including a supplied final newline | 1,048,576 bytes |
| Reply or event, including a supplied final newline | 16,777,216 bytes |
| One historical value's nested depth, root included | 32 |
| Values in one historical record, including containers and leaves | 4,096 |
| Combined UTF-8 bytes in its keys and string values | 65,536 |

The request ceiling matches Python IPC. The response and historical limits
are this Rust library's explicit local limits; Python does not promise these
same response ceilings. Serde's internal parsing can buffer data within the
admitted complete-line limit. Archive collection growth then checks its
separate depth, value-count, and text budgets. Direct use of the types'
Serde implementations is not a substitute for encoded-line admission.

This is a strict supported wire subset, not universal Python-input parity.
Python ignores some extra request fields and some values of the wrong kind;
the Rust codec refuses them. One documented legacy quirk is retained:
`history.limit` and `snapshot.limit` accept literal `true`, which Python
treats as one. Literal `false` is refused. Non-string source or history-cursor
values that Python ignores are not silently coerced by Rust. Requests never
materialize default fields during decoding.

Model catalog `adapter_status` is a named enum or explicit null. Absence is
retained for older producer records. New-producer compatibility evidence is
recorded separately from the pinned reference conversations.

## JSON Schema and verification

`wire_schema()` returns one generated JSON Schema for the whole vocabulary.
To write it as one file:

```sh
cargo run -p aitts-protocol --example schema > aitts-wire.schema.json
```

The schema describes JSON instances. Encoded byte counts, aggregate historical
budgets, and daemon business rules remain codec or application checks. JSON
Schema also treats a numeric value such as `1.0` as an integer when its
mathematical value is integral; Rust integer fields require the integer JSON
number kind. Reply selection still needs the originating operation.

The concrete reference conversations and source-derived corpus have separate
[provenance](tests/fixtures/README.md). They are not model-quality tests or a
replacement for the external daemon socket suite. Run the crate checks with:

```sh
cargo test -p aitts-protocol
cargo test -p aitts-protocol --release
cargo fmt --check
cargo clippy -p aitts-protocol --all-targets -- -D warnings
```

This document is agent-written and has not received human editorial review.
