# Explicit worker adapter refresh: verification record

Change-kind: bug fix. On 2026-11-16, production commit
`7b23b96c728317b726a82804b1891aabb48352bb` was tested against the contract in
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
cancelling a healthy refresh still permits code-only refresh.

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

## Review repair: cancelled full repair retains download consent

Review thread `PRRT_kwDOUHyfMM64GlBg` exposed a schedule absent from the
initial checks: a failed incumbent starts full repair, cancellation preserves
that failed incumbent, but the catalog reported only `cancelled`. The client
then offered code-only refresh while daemon admission still required install.

The catalog now preserves effective `failed` state for that schedule and keeps
`Setup cancelled. You can retry.` as its message. A healthy incumbent's cancelled
refresh still reports `cancelled`. This uses the existing state contract; no
wire field was added. Four real IPC schedules cover healthy/failed incumbents
and unknown/stale identities, unchanged runtime files and manifest, and the
next recovery operation. The two failed-incumbent schedules failed before the
repair; all four passed afterward. The surrounding family passed 36 cases.

[Captured recovery rows](artifacts/2026-11-16-worker-adapter-refresh/recovery-catalog-cases.json)
come from those actual `engines` and `snapshot` responses, which were equal.
The Swift decoder/action test consumes the captured rows: before repair it
failed two consent assertions; after repair all three adapter tests passed.
The full Swift suite then passed 190 tests.

[Recovery calibration and repetition](artifacts/2026-11-16-worker-adapter-refresh/recovery-verification.json)
records two detected faults: incorrectly making healthy cancellation look
failed, and deleting Swift's failed-state consent guard. Production bytes were
restored after each fault. The four Python cases passed ten shuffled runs with
two independent processes (40 executions), seeds `16411` through `16419` and
random seed `911524576`. The captured-row Swift case passed ten independent
executions, two at once, against the restored rebuilt bundle. These counts
extend the earlier verification rather than asserting exhaustive interleavings.

## Review repair: bind refresh consent at daemon admission

Thread `PRRT_kwDOUHyfMM64GxAK` identified a different race: after a refresh
dialog opens, a failed engine/setup or missing runtime could turn its generic
setup request into full installation. Re-reading client state would still leave
a race before IPC admission. The Swift dialog now preserves its shown consent
through a distinct typed refresh command and `refresh_only: true`. The daemon
strictly validates the boolean and refuses unavailable refresh before setup
effects. Admitted code-only work never falls back to an install. Omitted/false
requests retain the legacy behavior, including explicit full repair.

Eighteen real IPC cases cover all JSON kinds at this field, the three changed
catalog conditions, current/stale/unknown runtime identities with cold/ready
engines, legacy omission/false, and runtime disappearance between admission
and staging. On `0ce2f8a`, eleven failed and seven controls passed. An initial
oracle used `code` instead of the existing wire envelope's `type`; the corrected
oracle was rerun against that unfixed commit before claiming RED. The final
family passed 54 cases. Swift's request assertion compiled and failed when the
new command interface still sent the old payload; all 19 relevant Swift cases
passed after policy and transport repair.

[Consent calibration and repetition](artifacts/2026-11-16-worker-adapter-refresh/refresh-consent-verification.json)
records six detected faults: rejecting legacy repair, refusing valid refresh,
falling back to install after runtime loss, omitting the wire flag, and each
incorrect Swift consent choice. Each restored the original bytes. The 18 Python
cases passed ten shuffled runs with two processes (180 executions), seeds
`16421` through `16429` and random seed `873671541`; the new Swift wire case
passed ten executions, two at once, against a rebuilt restored bundle.

[Public RPC captures](artifacts/2026-11-16-worker-adapter-refresh/refresh-consent-cases.json)
record 12 actual requests/responses and exact producer source hashes, including
omitted/false/true, strict type refusals and state refusals. All used synthetic
owned runtimes without invoking download commands. These additions are assigned
to Rust parity #125 / PR #178; older reference captures remain unchanged.

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
