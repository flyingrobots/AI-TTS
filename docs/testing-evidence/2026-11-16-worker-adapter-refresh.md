# Explicit worker adapter refresh: verification record

Change-kind: bug fix. On 2026-11-16, production commit
`7b23b96c728317b726a82804b1891aabb48352bb` met the bounded contract in
[issue #164](https://github.com/flyingrobots/AI-TTS/issues/164): report the
installed adapter identity, refresh stale or unknown code only on request,
and preserve the incumbent until the replacement is ready. This record also
covers the later identity-property test and documentation additions in this PR.
It is agent-written and has not received human editorial review.

## Contract and decisions

The installer had copied the daemon's package into each runtime without
recording which bytes were copied. A daemon upgrade left that copy unchanged;
setup returned `ready` for an existing ready engine. A Retry button alone could
therefore not update it.

The fix records a framed content digest of the actual copied package and adds
the required nullable `adapter_status` to both catalog operations. Legacy
manifests remain usable and report `unknown`. Reading either catalog starts no
work. [The maintained contract](../design/worker-adapters.md) defines the exact
values and digest format.

Refresh stages a new private adapter, links directly to the existing environment
and assets, warms offline, then publishes after synthesis quiescence. Updating
the incumbent directory in place would expose a live worker to mixed code;
reinstalling the complete runtime for every upgrade would needlessly download
weights. The chosen path does neither. Its cost is retaining old roots that are
still link targets; garbage collection is outside this change.

Review found an additional recovery failure: a failed refresh would preserve
an unknown or stale manifest, causing the next Retry to refresh the same broken
environment forever. A ready incumbent could also hide a failed full repair.
Failed setup or engine state now takes precedence over refresh and the ready
shortcut. Swift presents download/install consent for that complete repair;
cancellation still permits code-only refresh.

## Observed RED and GREEN

The initial plan-only source failed seven regression cases: missing manifest
identity, three missing catalog statuses, and three explicit refresh outcomes
that returned `ready` without doing the requested work. The Swift decoder test
compiled and failed with five absent statuses instead of preserving the three
named statuses followed by null and absence. These became green after the
implementation.

During review, the existing failed-runtime retry fixture was restored to a
legacy installation and extended with a stale manifest. Both variants failed
before repair precedence was fixed. A separate three-request schedule then
failed because a ready incumbent hid a second failed full repair. Swift's
failed-state action assertion also failed before its confirmation policy was
corrected. Commit `7b23b96` made all of these green. The temporarily substituted
current-identity fixture had missed the legacy recovery problem and is not
the final regression oracle.

The final focused family passed 56 cases: 5 small and 51 medium. It includes
existing installer/daemon boundaries and the new identity, catalog, refresh,
staging cancellation and recovery cases. Python tests enter through real
owned runtime files and daemon IPC; model warmup and download effects use
controlled fixture boundaries. No real weights were downloaded.

## Falsification and repetition

[Calibration evidence](artifacts/2026-11-16-worker-adapter-refresh/calibration.json)
records 34 seeded faults, each detected by an assertion and restored byte for
byte. They cover omitted names/content, bytecode and metadata contamination,
hashing the source instead of the copy, wrong catalog statuses, automatic
catalog work, ineffective refresh, premature manifest publication or worker
retirement, weight mutation, link chains, failed/cancelled candidate leakage,
repair precedence, unavailable/external runtimes, and Swift decoding/action
conditions. These are fault witnesses, not a coverage percentage or proof of
all possible failures.

All 30 new or materially changed Python cases passed ten repetitions with two
processes at once and a separately shuffled order for each seed: `16401`
through `16409`, then random seed `2140841753`. The generated identity property
ran 100 passing examples per repetition, with one to three files and both empty
and nonempty content; seeds and orders were recorded outside the test process.
It compares changed creation order, timestamps, modes and ignored bytecode.
No defect counterexample was found. Injected metadata faults shrink to one
empty `a.py`; the permanent property permits that boundary.

The two new Swift cases passed ten repetitions each, alternating their order
and running two independent XCTest processes at once against the rebuilt
bundle. [Repetition evidence](artifacts/2026-11-16-worker-adapter-refresh/repetition.json)
records 300 Python and 20 Swift case executions. These schedules control
warmup and staging with events; no sleep is used to turn a failure green.

## Required checks and reference parity

Normal pre-commit checks passed Ruff lint/format and mypy over 217 source files.
The normal pre-push hook on `7b23b96` passed the complete Python suite:
1,268 passed and two existing opt-in native UI tests skipped. Those require a
signed candidate, an unlocked desktop and Accessibility permission. The full
local Swift suite passed 189 tests with zero failures. Python was 3.14.7 and
Swift was 6.4.2 on macOS arm64.

Local Swift's default build backend hit the unchanged 256 MiB per-file guard
during planning. A narrowly authorized hook shim selects the supported native
backend with index storage disabled and two build jobs; it executes the full
original build and preserves its exit status. The backend emits a deprecation
warning. No hook or resource limit was weakened. The default CI backend remains
mandatory: [run 43938763811](https://github.com/flyingrobots/AI-TTS/actions/runs/43938763811)
passed Python, Swift and dependency checks on `7b23b96`; the tag-only release
job was skipped. The final documentation/test commit requires its own CI before
the PR becomes ready.

The [captured catalog arrays](artifacts/2026-11-16-worker-adapter-refresh/catalog-cases.json)
come from real `engines` and `snapshot` responses against owned synthetic
installations; their arrays were equal. The capture records exact producer
source hashes. The installed capture deliberately has no registered model
worker: `installed: true` and `state: "not installed"` describe separate existing
fields, while adapter identity describes the private files. Rust parity is
assigned to [#125](https://github.com/flyingrobots/AI-TTS/issues/125) /
[PR #178](https://github.com/flyingrobots/AI-TTS/pull/178); its author verified
those source hashes and added separate compatibility cases without changing
the pinned older conversations.

## Limits and retained resources

Commands ran in an isolated clone with a 300-second process-group deadline,
6 GiB sampled RSS limit, 96-process cap, 16 MiB log cap, 240-second hard CPU
limit and 256 MiB hard per-file limit. Aggregate project disk admission was
checked before and during commands. The guard observes its process group;
it does not establish that independently detached descendants have stopped.
No detached-session test runner was nested under it.

This verifies synthetic runtime publication, failure/cancellation preservation,
wire decoding and action policy. It does not verify actual model inference,
downloads, audible playback, a live daemon upgrade or mouse-driven Swift UI.
The installed runtime, model weights and running application were not changed.
Retained private test logs and build caches are evidence and reusable outputs;
they are not part of the product distribution.
