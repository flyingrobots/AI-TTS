# Rust domain contract

`aitts-domain` provides deterministic speech rules and value types for the Rust daemon work.
The Python implementation remains the production path. This crate does not operate storage,
engines, sockets, devices, or the playback conductor.

## Modules

| Module | Public contract |
| --- | --- |
| `utterance` | Ten states, four terminal states, and exactly 18 legal transitions. Rejected transitions carry the source and destination. |
| `plan` | Stable key order, priority-based head or tail admission, ready preemption, and last-in-first-out resume frames. |
| `segmentation` | Plain-text identity and bounded paragraphs; Markdown speech blocks, headings, code, links, lists, and tables. |
| `voices` | Pinned, requested, claimed, and unclaimed voice precedence; language metadata and automatic pools. |
| `settings` | Typed scalar validation, catalog membership, and canonical automatic language selections. |
| `retention` | A deterministic LRU deletion proposal that excludes protected artifacts and reports an unmet byte limit. |
| `sensitivity` | Public text can use either engine locality. Internal and confidential text require a local engine. |

Callers supply identities, registry snapshots, catalogs, lifecycle states, access times,
byte counts, and engine locality. They remain responsible for validating wire structure,
observing external state, applying effects, and handling races after a decision.
The crate does not accept a storage, engine, clock, or transport handle.

## Queue and retention boundaries

`plan::ordered` preserves snapshot order for equal keys, including positive and negative zero.
Priority affects admission keys; it does not add a second sort over existing queue entries.
Normal admission follows the maximum key from all history. Urgent and preempt admission
precede the minimum nonterminal key. Keys must be finite. If floating point precision cannot
produce a distinct next key, admission returns an error instead of claiming a new position.

Preemption requires ready audio, preempt priority, playback permission, and an open hold.
A candidate must precede a live current speaker. Equal keys do not interrupt.
Resume frames retain segment indices and discard entries that are missing or no longer paused.
The caller must supply a coherent snapshot with unique utterance identities, recheck state
before device effects, and save actual playback positions itself.

`retention::eviction` sorts eligible artifacts by access time and then identity.
Its projected size assumes that every proposed deletion succeeds. A caller must re-inventory
and re-plan after failures or concurrent changes. Protected artifacts can prevent the target
from being reached; `unmet` reports those excess bytes. Duplicate artifact identities and
byte-count overflow are refused. Cache byte counts use `u64`; larger Python integers are
outside this Rust API's representable range and are refused.

## Voice and settings boundaries

Voice decisions use the same precedence as the Python voice-assignment function.
The listener's pin wins. A request for a voice held by another client keeps the requester's
existing claim, or selects the first available catalog voice. Exhaustion permits sharing the
catalog's first voice. An empty catalog is an error only when automatic allocation is needed.
The caller must validate explicit requests, remove stale claims, apply language restrictions,
and exclude the current client's claim from the other clients' taken voices.

Settings preserve value kinds: booleans and numeric strings are not numeric speed values.
Speed accepts the inclusive range 0.5 to 2.0; playback rate accepts the six offered choices.
Cache strings must round-trip as canonical non-negative decimal integers, with surrounding
whitespace allowed. Catalog and language validators consume the caller's chosen engine catalog.
Settings persistence, atomic batch orchestration, and device updates remain outside this crate.

## Segmentation

`segmentation::prepare` returns ordered strings, or a typed parser/resource refusal.
Plain text preserves short input bytes, including empty input and CRLF. The pure function's
empty result does not authorize an empty daemon submission. Missing format means Markdown,
as in the legacy Python API. Paragraph and word boundaries retain the Python policy:
60 words enable paragraph grouping, groups target at least 20 words, and long segments target
180 words with a maximum of 220. ASCII letters and digits define words for this policy.

Markdown uses the locally modified, pinned `markdown` 1.0.0 source with HTML interpretation and automatic bare-URL linkification
disabled. Tables and double-tilde strikethrough are enabled. Code remains spoken text, visible
link text and image alternatives remain, and headings start sections. The crate adapts the
parser's syntax tree; it does not implement a separate Markdown grammar.
The unchanged [40-case corpus](../../tests/corpus/segmentation/README.md), HTML regressions,
and loose-emphasis cases define tested compatibility. They do not prove parity for every
possible Markdown input or every Unicode normalization behavior.

## Resource admission

The domain API refuses oversized input before parsing or copying snapshots. These limits
belong to the new Rust API; they do not assert universal Python parity or change the current
Python daemon. No partial projection or eviction proposal is returned after a refusal.

| Resource | Default hard ceiling |
| --- | --- |
| Submitted text | 1,048,576 UTF-8 bytes, before front-matter removal |
| Container / AST depth | 128; one separately admitted scratch container slot supports recognition |
| AST nodes | 65,536 cumulative nodes, including roots and temporary buffers |
| Parser events and edit records | 4,194,304 cumulative admissions across all tokenizers and resolvers |
| Parser work | 64,000,000 shared charged units |
| Copied queue, voice catalog, or artifact inventory | 65,536 entries |

`prepare_with_limits` can reduce the parser allowances. It cannot increase the hard ceilings.
`InvalidMarkdown::Policy` distinguishes an invalid caller policy from `Limit`, which records
the exceeded resource, observed amount, and maximum. Plain text uses the input-byte allowance;
it has no Markdown parser events or AST. The input ceiling preserves the one-MiB transport
allowance. Many-word shallow prose near that ceiling and 257 flat headings/list entries remain
supported. Deep small input can fail independently of its byte length.

The parser checks each new event, edit record, AST node, and retained container before growth.
The same budget follows child tokenizers and AST buffers. Work charges cover grammar state
steps, resolver and subtokenizer scans, event-map scans/moves/sorting, and AST event visits.
These are defined accounting units, not milliseconds, CPU instructions, or allocator bytes.
The limits bound parser structures; they are not a hard wall-time or process-RSS guarantee.
Callers still need their own execution and process-memory guards at the effect boundary.
The bounded parser excludes MDX callbacks/constructs and GFM bare-link recognition; the
unbounded upstream entrypoints retain those options.

`plan::ordered` and `voices::automatic_pool` return `CollectionLimit` before copying a larger
snapshot. Retention and language-settings errors preserve that refusal. Borrowed identifier
strings are not copied by those helpers. Preemption selection scans the borrowed queue and
allocates no queue copy. The canonical language result has at most nine entries.

## Dependency boundary

The production graph is `aitts-domain` → locally modified `markdown` 1.0.0 → `unicode-id` 0.3.7.
The parser is a path dependency in `vendor/markdown`. Its [patch record](../../vendor/markdown/PATCH.md)
identifies the exact upstream archive, retained MIT license, changed files, and local limits.
It is not an unmodified upstream release.
The crate itself uses `no_std` plus `alloc` and forbids unsafe code. This declaration alone is
not a claim that every linked dependency is independent of the standard library.
The inspected Markdown source declares an unused `extern crate std` in its HTML tag-filter
module; no file, network, process, clock, or device API is used by its enabled source.
Its optional logging and serialization features are disabled. The Unicode dependency uses
pure character tables and forbids unsafe code. Neither dependency has a build script.

[Markdown parser options](https://docs.rs/markdown/1.0.0/markdown/struct.Constructs.html)
provide the explicit HTML controls. [Its package manifest](https://docs.rs/crate/markdown/1.0.0/source/Cargo.toml)
defines the optional features. Recheck the locked source and enabled feature graph before
changing versions or features; a `no_std` label alone is insufficient evidence of no I/O.
Parser-specific AST and error types do not appear in the public domain API.
Test-only JSON and property-test dependencies do not enter the production graph.

## Validation

The workspace pins Rust 1.99.1, including Clippy and rustfmt, and commits `Cargo.lock`.
Run these commands from the repository root with that toolchain's binaries on `PATH`:

```sh
cargo fmt --check
cargo clippy --workspace --all-targets --locked -- -D warnings
cargo test --workspace --locked
cargo test --workspace --release --locked
cargo tree --workspace --edges normal,build,features --locked
```

The Rust CI job runs on Linux; local validation also runs on macOS. Property tests use 128
cases and seed 130 by default. Set `PROPTEST_RNG_SEED` to reproduce or vary a run explicitly.
Each test file records its size and oracle. The state ledger and golden expectations are
independent of the implementation. CI retains the existing Python, Swift, and supply-chain gates.
