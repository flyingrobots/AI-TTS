# Architecture benchmark instrument — 2026-09-30

Change-kind: **feature**. Runtime baseline: `0290f3cf3a0c3930256f42f31500bda59c1eabeb`. Scope: an executable performance/correctness baseline and architecture review; no behavior change to the daemon, model or installed app.

## Oracles and boundaries

- Real PlaybackController + WAL Store + the production-owned contract FakeSink: exact clip/child/offset, hold authority, LIFO and exclusive ownership.
- Store connection factory: commit failure before commit must preserve all parent/child state, including an independently reopened reader.
- Coherent SQLite recovery image: no automatic speech; explicit resume restores nested identities/offsets. This is not a power-loss/torn-write experiment.
- Real SpoolingPCMStream: exact source bytes after held production, bounded-ring overflow, backward seek and WAV finalization; no false progress/EOF on starvation.
- Benchmark metrics/report contract: known interval and nearest-rank quantiles, nonempty sample/witness inventory, consistent raw and summary data, gross repeated same-run relative regression. Counterexamples cannot become timings.
- Manual inference gauge: owned malformed WAV/PCM fixtures are rejected; actual native inference is optional large/manual evidence and has no absolute CI gate.

Tests use the narrow boundary needed for each oracle: numeric and report checks are small; file-backed controller, PCM and inference-gauge checks are medium. A short multistep journey is necessary to witness LIFO restoration rather than merely observing that an alert started. The benchmark intentionally reuses the existing deterministic playback schedule; it does not maintain a competing fake scheduler or artificial production clock.

## Observed red before the benchmark fixture correction

`test_benchmark_backlog_is_ready_playback_work` failed with **0 Ready rows, expected 3** when the fixture submitted only Queued records. It passed after those owned backlog items were prepared through Synthesizing to Ready. The initial Queued-backlog timing run is excluded from baseline evidence. This was an instrument defect found while authoring the feature, not a production bug fix or change to playback behavior.

## Falsification

[Raw named failures](../benchmarks/2026-09-30/calibration.json) retain exit codes, pytest node ids and failure output. Each mutation ran alone, sources restored in `finally`, bytecode invalidated, and no benchmark overlapped these tests.

| Deliberate fault | Observed failing boundary |
|---|---|
| Disable WAV-format rejection | Malformed-WAV gauge test: DID NOT RAISE |
| Disable streaming-PCM rejection | Malformed-PCM gauge test: DID NOT RAISE |
| Force regression decision false | Repeated 4x slowdown no longer fails |
| Shift nearest-rank index by one | Known quantile/count/tail dictionary differs |
| Make semantic `require` a no-op | Lost-resume-offset gauge: DID NOT RAISE |
| Convert ns to the wrong ms scale | Controlled 25 ms interval becomes 25,000 ms |
| Seek one frame past requested PCM offset | Exact backward-seek PCM/source-clock witness fails |
| Skip expected-case validation | Missing-case evidence accepted: DID NOT RAISE |
| Accept zero correctness witnesses | Zero-witness report accepted: DID NOT RAISE |
| Trust inconsistent raw/summary timing | Corrupt-summary report accepted: DID NOT RAISE |

Additional constructive counterexamples exercise missing metric/durability witnesses, insufficient samples, empty/negative/NaN/infinite distributions, unpaired blocks, zero reference medians, a single noisy block and the exact 3x threshold. The PCM scenario checks every block rather than one representative sample. Existing preemption regression/calibration tests continue to carry the underlying production-behavior assertions; this feature does not replace them.

## Performance calibration

Five randomized identical-source reference/candidate pairs, 100 measured cycles per golden case after 10 warmups, produced 26 signals and **zero** coarse alarms. The largest signal's median paired ratio was 1.0172. Reference source is pinned and checked clean; candidate harness and Python environment run both sides.

A separate source copy added `await asyncio.sleep(0.001)` at the beginning of `PlaybackController._plan_preemption`. The exact same five-pair comparator returned **exit 1, 24/26 signals regressed**. All correctness workloads still completed. This verifies an actual slowed implementation can trip the guard, not merely a hand-entered numeric ratio. The two remaining signals did not cross the deliberately generous repeated 3x rule. Neither source copy was installed. Raw paired observations and decisions are retained in the artifact index below.

A controlled clock validates a known 25 ms operation's recorded duration. That calibrates unit conversion and measurement boundaries; it does not claim the Mac scheduler sleeps for exactly a requested interval. Service distributions come from the real controller/Store/PCM operations.

## Validation and limits

- Full Python suite: **831 passed**; small 292 tests / 0.69 s, medium 539 / 13.40 s, wall 14.63 s. Existing 10 s / 45 s tier budgets remain unchanged.
- Ruff clean; 232 files format-clean; mypy clean across 151 source files.
- Ten Mermaid diagrams parsed using Mermaid 11.12.0 with jsdom 26.1.0 in an isolated scratch install. This verifies syntax, not every renderer's layout.
- Native optional MLX run: 30 WAV plus 30 streaming trials, offline, silent, with separate idle RSS and allocator gauges. No model was downloaded or app restarted for the experiment.
- Five-minute soak: 6,000/6,000 intended journeys, 600 PCM round trips, 102,084 controller and 16,200 PCM witnesses, no failed witness; live RSS 51.20 → 52.53 MiB. This does not prove the absence of a slow memory leak.
- Final report-shape hardening: removing an entire case's `samples` payload initially yielded DID NOT RAISE in the new payload test. The comparator now skips only the explicitly named durability case; missing latency evidence raises. The red log is retained alongside the Ready-backlog red receipt.

[Architecture report](../reports/2026-09-30-architecture-review.md) and [artifact index](../benchmarks/2026-09-30/README.md) contain measurements, reproduction commands, model/source identity and the scheduled CI policy. The workflow is configured in this change; local validation is not represented as a hosted scheduled-run result.

Deletion criteria: remove a case only when its documented public behavior is removed or replaced by a stronger boundary experiment. Re-baseline the pinned implementation/tolerance only with old/new evidence and deliberately slow calibration. No coverage percentage or mutation score is a gate.

## Subsequent stack integration

Hosted run `36788914590` passed Python and Swift but failed the strict dependency audit on PyJWT 2.14.0 / CVE-2026-101918. Mainline already contained the security fix. Rebasing the stack onto `954807b` inherits frozen 2.15.1 and its calibrated public error-boundary regression rather than suppressing the finding.

All six refreshed PR boundaries independently pass lock verification, Ruff, formatting, mypy and full Python suites. The final boundary passes 910 tests (313 small / 0.63 s, 597 medium / 17.32 s, wall 18.53 s). A fresh five-pair comparison against the original retained reference finds no coarse regressions in 26 signals. [Integration receipts and raw observations](../benchmarks/2026-09-30/integration-refresh/) are distinct from the initial baseline. The streaming feature's receipt records the two observed-red generation-identity cases discovered during integration. The refreshed native app also builds with warnings-as-errors and passes all 142 Swift tests behind the existing 60-second process deadline.

## Streaming review follow-up

Three further streaming regressions were observed red before correction: rewind after concurrent WAV publication, route adoption after an initially unreadable device identity, and per-clip underflow evidence reset. The [streaming receipt](2026-09-30-streaming-audio.md) describes the controlled schedules and limits. These fixes do not diagnose acoustic pops.

All six updated PR boundaries pass their own full Python suites, Ruff, formatting and mypy; the five dependent boundaries also passed frozen lock verification. The streaming boundary has 771 tests and the final stack has **913 passing tests** (313 small, 600 medium; 17.20 seconds wall clock). A fresh five-pair comparison against the unchanged pinned reference again reports **zero regressions across 26 coarse timing signals**. [Review-follow-up artifacts](../benchmarks/2026-09-30/streaming-review/) preserve raw observations, source identities, the three original failures and validation receipts separately from earlier measurements. No Swift source changed during this follow-up. The original baseline tag remains unchanged.

Retained-evidence caveat: [`streaming-review/boundaries.json`](../benchmarks/2026-09-30/streaming-review/boundaries.json) records five boundary heads (`7558eef`, `2abae3e`, `a33ce35`, `e5d06e0`, `9f0b45b`) with their checks and durations, but no per-boundary pytest summaries. The six-boundary statement, the 771-test streaming count and the 17.20-second wall clock above are therefore not backed by retained artifacts. The 913-test count (313 small, 600 medium) was re-observed at `baba76b` during the PR #47 review. [`integration-refresh/boundaries.json`](../benchmarks/2026-09-30/integration-refresh/boundaries.json) does retain six boundaries with summaries.

## Code Lawyer review fixes

Change-kind: bug fix to the benchmark instrument. Runtime behavior is unchanged.

The paired comparator's reference cleanliness check ran `git diff HEAD -- src`, which ignores untracked files. An untracked module under the reference `src/` is importable but was accepted, which contradicts the report's statement that the comparator rejects a locally modified reference. On parent `baba76b`, with the check first extracted unchanged into `reference_is_clean`, the new boundary test `tests/test_benchmark_reference.py` (medium; oracle: exact commit and no tracked or untracked `src` edits) failed only for the untracked case:

```text
...F                                                                     [100%]
FAILED tests/test_benchmark_reference.py::test_untracked_source_module_is_rejected
>       assert not reference_is_clean(tmp_path, commit)
E       AssertionError: assert not True
```

The check now uses `git status --porcelain --untracked-files=all -- src`, which still honors the reference's own `.gitignore` (so `__pycache__` written by earlier runs does not count). All four cases pass: a clean pin is accepted, and another commit, a tracked edit, and an untracked module are rejected. A real detached checkout of `0290f3c` is still accepted.

Change-kind: bug fix to the benchmark instrument and its test fixture. Git hooks export `GIT_DIR`, which overrides `git -C`. The first push of the fix above ran the new tests inside the pre-push hook, and the fixture's `git init/add/commit` wrote a local commit into the repository running the tests. That commit was never pushed, and the working-tree files were verified byte-identical to the last good commit. `reference_is_clean` had the same defect: it would inspect the launching repository instead of the named reference. The new `test_inherited_git_environment_cannot_redirect_the_check` sets `GIT_DIR`/`GIT_WORK_TREE` to an owned decoy repository. On parent `d13adeb` it was observed red twice, once per defect. First, the fixture's commit was redirected into the decoy:

```text
E   subprocess.CalledProcessError: Command '['/usr/bin/git', '-C', '.../target', ..., 'commit', '--quiet', '-m', 'reference']' returned non-zero exit status 1.
FAILED tests/test_benchmark_reference.py::test_inherited_git_environment_cannot_redirect_the_check
```

Second, with only the fixture corrected, the comparator inspected the clean decoy and accepted the dirty target:

```text
>       assert not reference_is_clean(target, commit)
E       AssertionError: assert not True
FAILED tests/test_benchmark_reference.py::test_inherited_git_environment_cannot_redirect_the_check
```

Both now drop inherited `GIT_*` variables before invoking git. All five reference tests pass, including a run with `GIT_DIR`/`GIT_WORK_TREE` pointed at a nonexistent path, and the real `0290f3c` checkout is still accepted.

Change-kind: bug fix to the benchmark instrument (CodeRabbit thread on `scripts/benchmarks/cases.py`). `session` and the recovery journey in `failures.py` called the shared `start` helper outside their cleanup boundary. `start` creates the controller task before awaiting the first idle boundary, so a failed start left the controller task pending and the Store open. The new `tests/test_benchmark_cleanup.py` (medium; oracle: no pending controller task and every opened Store closed) injects a schedule whose first idle wait raises. On parent `acd8088` it failed for both paths:

```text
>       assert leaked_tasks() == []
E         Left contains 2 more items, first extra item: <Task pending name='Task-3' coro=<PlaybackController._watch() ...>>
>       assert leaked_tasks() == []
E         Left contains one more item: <Task pending name='Task-12' coro=<PlaybackController.run() ...>>
FAILED tests/test_benchmark_cleanup.py::test_session_startup_failure_releases_controller_and_store
FAILED tests/test_benchmark_cleanup.py::test_recovery_startup_failure_releases_controller_and_store
```

Both paths now open their Store inside `try/finally` and start the controller through `cases.running`, which owns the task from creation and always shuts it down, cancels it and awaits it. The shared `tests/test_playback.start` helper on main is unchanged. The measured operations and their timing boundaries are unchanged, and all 21 medium benchmark tests pass.
