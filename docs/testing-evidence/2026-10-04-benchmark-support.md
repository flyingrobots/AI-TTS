# Source-pinned benchmark support

Change-kind: bug fix. Issue #68. Oracle: a controller benchmark must execute and identify the selected source's playback helpers, and the paired comparator must refuse modified reference support.

## Change

`DeterministicPlaybackSchedule`, `make_composite_ready`, and `settle` move unchanged into `tests/support/playback.py`. Tests import that shared module. Benchmark cases and failure probes load it from the checkout containing the selected `aitts` package. The unchanged pinned reference `0290f3cf3a0c3930256f42f31500bda59c1eabeb` predates this layout, so the loader selects its own `tests/test_playback.py` and `tests/conftest.py`. An already-loaded test package from another checkout is refused rather than reused. The candidate's benchmark harness remains common to both arms; helper versions intentionally follow their measured application.

Reports retain candidate harness hashes and add `environment.playback_support_sha256` for the selected checkout's package and helper modules. The MLX boundary does not claim to use playback helpers. Reference admission now checks `tests` as well as `src`, including ignored importable code, links, and opaque directories under either tree. Normal tagged bytecode caches remain allowed. Source-root execution is not a sandbox; it executes the selected checkout's code.

## RED and GREEN

The retained `red.json` restores five exercised implementation files from `501877b0682323bf79b328394b741b2ec927ccd7` while keeping the candidate regression tests and owned legacy fixture. All nine selected assertions fail for the intended reasons: two alternative-layout runs execute candidate helpers, the preloaded-candidate case incorrectly publishes a report, four modified/ignored helper cases are accepted, and two report checks lack their required helper/harness provenance. The actual PR parent `fad2bc07aa90a96f7f273c5d11cbe01552b421af` changes only documentation relative to that RED revision; these implementation files are identical. This is targeted parent-code execution, not a claim of checking out the entire parent tree in Docker.

`green.json` records the same nine cases passing with the candidate restored. `order.json` records three seeded sequential permutations and two concurrent copies, all passing without retries: 45 case executions. This bounded sample establishes observed order/process isolation, not a statistical flake-rate guarantee. The replay harness is retained as `validation-runner.txt`. Every receipt records commands, exit codes, and the relevant source/test fingerprints.

The existing file-reading provenance tests are now medium-sized rather than mislabeled small. No original playback behavior assertion changes; other test diffs only redirect helper imports. A frozen, minimal historical-layout fixture lets the legacy CLI regression remain meaningful after extraction. Its assertions are fixture mechanics; the test oracle observes the selected module's execution marker, report hash, and completed durability witnesses through the real CLI.

## Compatibility and limits

`extraction.json` compares the three helper definitions by AST: they match both the unfixed candidate and the pinned historical revision exactly. No workload, baseline pin, timing threshold, sample count, or performance gate changes. A one-iteration, zero-warmup, zero-backlog golden smoke run against an archive of the actual pinned source exercises historical helper imports and semantic witnesses; its raw report is retained. This is compatibility evidence, not a new performance comparison or replacement for earlier benchmark measurements.

Historical reports and receipts remain unchanged. In particular, earlier `harness_sha256` maps that included the candidate's `tests/test_playback.py` describe those earlier runs; they do not claim the new source-specific helper provenance. No historical speedup or regression percentage is recalculated by this change.

Validation reuses the bounded Docker worker (two CPUs, 4 GiB RAM, 1 GiB temporary filesystem). The broad Linux-compatible suite excludes the four previously established native-installation modules; complete hosted macOS CI is required before merge. Platform/native prerequisite skips are not counted as acoustic or native desktop acceptance. No installed daemon or real audio device is used.

Deletion criteria: retire the legacy-layout case and fixture when support for pre-extraction references is explicitly removed. Retire the source-selection, mixed-package refusal, and provenance regressions only when their public contract is removed or a stronger, cheaper boundary test covers the same risk. Reference-cleanliness cases remain while external pinned checkouts are supported. Record displaced risk in any deleting commit; a failing result is not a deletion criterion.

The first final-validation invocation omitted `/work/bootstrap/bin` from the worker PATH. Four unrelated distribution/model-setup tests failed because `uv` was unavailable; `validation-missing-uv.json` retains that run. The corrected validation explicitly supplies PATH and records it. This is an environment correction, not a flaky-test retry or a source change.

To replay RED, materialize the five `parent_files` named in `red.json` from its recorded Git parent beneath `/work/parent68`, copy the candidate into `/work/repo`, and execute `validation-runner.txt` with the worker's validation lock. The runner restores candidate bytes in a `finally` block before GREEN and repeat runs. `final-checks-runner.txt` records the static checks, explicit broad-suite exclusions, portable uninstall cases, and pinned-source smoke command. The pinned smoke source is a `git archive` of the recorded reference's `src` and `tests` trees, not a second virtual environment or compiler cache.

Final validation: Ruff and Darwin-targeted mypy pass; the Linux-compatible broad run records 997 passes and four skips, followed by four passing portable uninstall cases. The pinned-source smoke records six golden cases. The formatter's earlier 285-file result precedes documentation synchronization; the final `format-inventory.json` names 287 files (192 Python and 95 Markdown). Source/test fingerprints in RED, GREEN, order, and final validation receipts match the review candidate. The extracted helpers' ASTs also match the pinned reference; no new performance result is inferred from the smoke.
