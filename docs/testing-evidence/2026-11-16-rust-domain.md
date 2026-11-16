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
