# Rust domain validation — 2026-11-16

This record covers issue #130 and the new `aitts-domain` crate. It is agent-written evidence,
not human acceptance. The Python runtime remains unchanged. The [domain contract](../design/rust-domain.md)
states the API boundaries and reproduction commands.

## Oracles and RED-to-GREEN evidence

The public-API tests use an independent 18-transition ledger, all 100 state pairs, all six
sensitivity/locality pairs, manually specified queue and voice decisions, typed settings
boundaries, and hand-calculated retention totals. The segmentation oracle is the existing
40-case corpus. Its bytes and expected strings were not changed.

| Step | Observed RED | Observed GREEN |
| --- | --- | --- |
| Lifecycle and disclosure | Reject-all transition stub and allow-all admission stub failed legal-transition and remote-internal cases | Complete state and disclosure tables passed |
| Voice assignment | Default-only stub failed automatic allocation | Pin, request, claim, conflict, and exhaustion cases passed |
| Settings | Reject-all rate and byte parsers failed supported values | Numeric-kind, limit, canonical-string, overflow, toggle, catalog, and language cases passed |
| Queue planning | Identity ordering and empty interruption/resume stubs failed all three example tests | Stable order, admission, interruption gates, and nested resume passed |
| Retention | Empty proposal stub failed LRU totals and duplicate-identity refusal | Ordering, protection, unmet limits, and accounting errors passed |
| Segmentation | Identity stub failed 27 of the 40 cases; plain-text implementation left 16 Markdown failures | All 40 exact arrays passed after spoken rendering |
| HTML compatibility | The first parser left backticks and link syntax inside a raw HTML block | Four separate HTML/Markdown examples passed after selecting a parser with HTML disabled |

The HTML expectations were written from the intended projection, then checked through the
Python `prepare_speech_segments` public API. For example, the input
`<div>\n` followed by inline code and a Markdown link must speak their visible content,
not their syntax. `markdown` 1.0.0 provides this configuration without a custom HTML rewrite.
Six additional cases check loose emphasis, arithmetic asterisks, literal inline code,
multiline prose, and adjacent punctuation.

## Assertion calibration

A temporary local driver changed one source rule at a time, ran the relevant public-API
suite, required an assertion failure, then restored the exact source bytes. Compile failures
did not count. Thirty-three targeted faults produced 33 meaningful failures; the restored
suite returned to GREEN. No fault implementation or synthetic property-regression file is
part of the production change.

| Rules challenged | Faults detected |
| --- | --- |
| Lifecycle and sensitivity | Illegal transition acceptance; incorrect terminal set; internal or confidential remote admission |
| Queue | Reversed order; equal-key interruption; ignored hold; synthesis-only interruption; FIFO resume; terminal history included in head admission |
| Voices | Lost pin; stealing a held voice; wrong exhaustion fallback; wrong source prefix; wrong language; inverted language pool |
| Settings | Moved inclusive speed limit; unsupported playback rate; noncanonical cache integer; truthy numeric toggle; unknown catalog name; unused language selection |
| Retention | Protected artifact eviction; reversed LRU order; wrapping size total; duplicate identity acceptance |
| Segmentation | Changed target or paragraph threshold; lost punctuation; cleaning literal code; enabled HTML interpretation; missing output |
| Generated properties | Illegal lifecycle acceptance and unstable equal-key ordering also failed when only their property test ran |

The ordering property shrank its injected failure to two equal keys `[0, 0]`.
The lifecycle property shrank to a request for `Submitted` from `Submitted`.
An additional focused calibration deleted one plain-text word while retaining the empty
input contract; this shrank to the one-word input `word0` and independently challenged word
conservation, rather than only the nonempty-output assertion. The same source was restored
and the segmentation suite passed.

Two further value-boundary calibrations checked that accepted speeds retain their actual
multiplier and that normal admission follows completed history. Replacing speed with 1.0,
or excluding terminal entries from tail-key selection, produced assertion failures. Restored
sources passed formatting, strict Clippy, and the complete suite.

## Toolchain and repeated execution

Final debug validation used these recorded binaries:

- `rustc 1.99.1 (58cf8f9c3 2026-10-13)`
- `cargo 1.99.1 (5f94df478 2026-08-27)`
- `clippy 0.1.99 (58cf8f9c35 2026-10-13)`
- `rustfmt 1.10.0-stable (58cf8f9c35 2026-10-13)`

An earlier `rustup run` found a different `cargo-clippy` through `PATH`. That lint run is not
claimed as pinned evidence. Final runs put the exact toolchain directory first on `PATH`
and selected its compiler and rustdoc explicitly.

Formatting, strict all-target Clippy, and 21 debug tests passed. Three property tests each
use 128 generated cases. Ten further repetitions shuffled test execution order and supplied
a new explicit seed before launch: 210 of 210 test executions and 3,840 generated cases passed.
Each repetition completed in 0.45–0.50 seconds, excluding compilation and guard measurements.
Each individual test had a two-second wall deadline.

The ten seeds were:

```text
18338971705690860391 3056940758709626927 8299133880587593574
13351798735837877507 5542146200061526773 12480340119960951025
3819417862083626230 14199252730578908437 4862366991269741678
7970507919892128339
```

For example, `PROPTEST_RNG_SEED=3056940758709626927 cargo test --workspace --locked`
reproduces that generated-input stream. The normal harness's test order need not match the
separately shuffled local driver. Test files document their size and independent oracle.

## Resource and validation boundaries

The owned runner used isolated caches and output directories, two build jobs, a five-minute
command deadline, a four-GiB physical allocation ceiling, and process, memory, file, and log
limits. It also checked the aggregate project budgets: 20 GiB build, 4 GiB data, 128 MiB logs,
and at least 50 GiB free disk. The recorded post-repeat owned allocation was about 1.08 GiB;
aggregate measured build output was about 8.64 GiB, data 0.74 GiB, logs 17 MiB, with over
435 GiB free. Existing unrelated Git history was classified as source, not generated data.
No original checkout or model output was removed to obtain these results.

A normal Swift push hook attempted a 12-GiB logical sparse compilation-cache index while
using about 170 MiB of physical output. The user explicitly approved a 16-GiB logical-file
limit only for this branch's Swift hook builds. The owned wrapper raised the soft limit only
for the unchanged `swift build --quiet` child. It retained the normal SIGXFSZ policy, physical
allocation ceiling, aggregate budgets, timeout, and all other guards. Other commands retained
the smaller file limit. A diagnostic that ignored SIGXFSZ was not used as passing hook evidence.

The enabled production dependency graph and actual locked source were inspected for I/O,
unsafe code, features, and build scripts. This is a source review plus graph evidence, not a
universal sandbox proof. Corpus agreement does not establish all-Markdown parity, production
integration, device behavior, persistence recovery, or performance under unbounded inputs.
All 21 tests also passed in release mode. The branch then integrated main through `38d967c`,
including the socket fixture and runtime-manifest repairs. The normal push hook passed
1,239 Python tests with two skips, followed by the unchanged Swift build. Hosted CI and
the final review disposition are reported in the PR against its published head.

## Independent review repairs

The reviewer found that rejecting one embedded star could lose the original preceding
character before the next star. A public-API regression showed `1** hello **` incorrectly
becoming `1*hello`. The cleanup now checks the preceding character in the original source.
That input, `hello** world **`, and `a*** loose ***` remain literal. The targeted RED became
GREEN, and the unchanged corpus and generated properties still passed.

The reviewer also identified CR-only front matter. The RED case spoke the hidden title as
`title: hidden.\n\nHello`. Python's public API returned only `Hello`. The front-matter scan
now handles all nine additional Python line separators, including CR and Unicode separators.
All nine cases and the original LF/CRLF corpus pass. The complete repaired suite has 23 tests.

## Parser resource admission review

The independent reviewer exercised the published `d8eb0ed` release API with nested
blockquotes. A 32,767-byte input (`"> "` repeated 16,381 times, followed by `hello`)
hit a hard two-second CPU guard. This was a guard stop, not a demonstrated parser crash.
The new public API preserves the one-MiB byte allowance and refuses excessive nesting
before deep parsing. It separately bounds AST nodes, parser events/edit records, and work.
Queue, catalog, and inventory copies also have explicit entry admission. Preemption now
scans the borrowed queue without allocating a sorted copy.

A document-wide marker quota was rejected: it would refuse ordinary shallow documents.
A second Markdown preflight grammar was also rejected because it would duplicate parser
semantics. The selected repair vendors the exact MIT-licensed `markdown` 1.0.0 source and
adds parser-owned admission. Its maintenance cost includes 51 changed/new source paths;
396 event-call sites are mechanical error propagation. The patch record and original/modified
hash manifests make that cost explicit. The upstream archive checksum is
`a5cab8f2cadc416a82d2e783a1946388b31654d391d1c7d92cc1f03e295b1deb`.
The local parser is not described as pristine upstream.

The first event allowance of 262,144 records refused realistic shallow prose near one MiB.
The retained default is 4,194,304 cumulative event/edit admissions. Permanent controls cover
257 flat headings and list entries, an exact one-MiB byte boundary, and 209,715 words in
1,048,575 bytes. Cumulative records differ from peak retained records. On the pinned 64-bit
toolchain, measured layouts are: event 80 bytes, edit tuple 40 bytes, vector header 24 bytes,
parser point 32 bytes, AST node 152 bytes. The component allowance in the patch record is
separate from observed process memory and does not claim a hard RSS or wall-time limit.
A direct debug-binary run of the many-word prose control took 0.62 seconds wall time,
115,212,288 bytes maximum RSS, and 113,656,336 bytes peak memory footprint on this host.

The public low-budget sweep exposed an inherited assertion that container exits could
never fail. It failed at that assertion before the repair; it now propagates typed resource
refusals. Four inputs across 1,024 work budgets each, plus three inputs across 512 event
budgets each, return either the unchanged projection or a typed refusal. Generated bounded
Markdown cases independently check the same output/refusal contract.

Ten fault calibrations separately challenged input bytes, AST depth, AST nodes, event
admission, shared event accumulation, work admission, shared work accumulation, the
attention backward scan, event-map shared accounting, and snapshot entry admission.
Each produced a meaningful assertion failure, and the restored suite passed. The vendor
validator also rejected a modified source and a false reconstructed-upstream checksum,
then passed after exact restoration of both records.

Further independent review found uncharged bulk work: repeated emphasis merged growing
vectors and removed sequence entries without charging the copied or shifted records.
The frozen intermediate parser hit SIGXCPU at the two-second guard for 65,536 stars on
each side of `x` (131,073 bytes). It was a guard stop, not a spontaneous parser crash.
A smaller permanent regression with a one-million-work allowance initially reached the
later Depth refusal. It now refuses Work before the bulk operation. The larger witness
returns a typed Work refusal in about 0.19 seconds under the same guard. Bulk append,
split, and shift operations in event maps, attention, lists, containers, and subtokenizers
are precharged before they run.

The unchanged 40-case speech corpus passes. The 52 unit tests shipped in the upstream
crate also pass. A separate comparison compiled the pristine pinned source and the local
patch against the same Unicode dependency: 48 inputs across HTML and CommonMark/GFM/MDX
AST entrypoints produced 192 exact matching unbounded results. This is bounded compatibility
evidence, not a claim that every Markdown input has been compared.

The execution runner cleans its owned process group. It does not claim complete descendant
quiescence for deliberately detached sessions. These Rust checks and probes did not use a
detached service or socket fixture. The project, physical-allocation, process-memory, CPU,
file, log, and time guards remained in place; no execution limit was raised for parser tests.

Final local validation after the bulk-move repair passed workspace formatting, strict
all-target Clippy, all 42 debug tests, and all 42 release tests. The vendor validator passed
its reconstruction check, Ruff, and mypy. Ten shuffled repetitions passed 420 of 420 test
executions and 5,120 generated cases from four properties. Repetitions took 1.73–1.86 seconds,
excluding compilation and guard measurements. Small cases retained a two-second wall limit;
the documented medium resource/prose cases used 15 seconds.

```text
17311276060137030626 12715049642055995299 4138327731582421813
4993854027738240562 2780934508097022382 8059193376940478044
17928322210897406610 2230797780998499840 9147592614922442027
13572548048072183647
```

The 52 upstream unit tests and 192 unbounded API comparisons were repeated after the final
bulk-move changes and passed. Final hosted CI and review status remain tied to the published
PR head; these local results do not substitute for those gates.
