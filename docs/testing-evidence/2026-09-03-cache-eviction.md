# Cache-eviction evidence — 2026-09-03

Change kind: bug fix.

Oracle: `docs/design/architecture.md` section 6. The cache is LRU under a
configurable cap; audio referenced by nonterminal work is protected; history
rows outlive evicted audio.

## Red on the unfixed parent

Commit `413ae93` adds the boundary test alone. On its parent, `uv run pytest
tests/test_cache.py -q` exited 2 during collection because
`aitts.adapters.filesystem_cache` did not exist. There was no cache-enforcement
path to exercise.

## Assertion calibration

Each behavior-specific mutation was applied alone and removed immediately
after the named failure was observed.

| Assertion | Calibration mutation | Command | Observed result |
|---|---|---|---|
| Terminal-only LRU eviction | Removed the protected-path filter while the Ready artifact was deliberately oldest | `uv run pytest tests/test_cache.py -q` | exit 1; the report identified the Ready path instead of the oldest terminal path |
| Generated policy model | Removed the protected-path filter | `uv run pytest tests/test_cache_policy.py::test_generated_eviction_plan_matches_lru_reference_model -q` | exit 1; Hypothesis shrank to one protected 1-byte entry and a zero-byte cap |
| Seeded unlink fault | Cleared terminal metadata inside the `OSError` branch | `uv run pytest tests/test_cache_policy.py::test_seeded_unlink_failure_preserves_history_reference_and_reports_debt -q` | exit 1; the failed path appeared in `forgotten` instead of remaining referenced |
| Public settings trigger | Removed immediate enforcement after persisting `cache_max_bytes` | `uv run pytest tests/test_ipc.py::test_cache_cap_setting_immediately_evicts_only_terminal_audio -q` | exit 1; terminal audio still existed and history incorrectly reported it cached |

The generated test uses deterministic Hypothesis generation with shrinking and
no ambient example database. Any future minimized counterexample belongs in
the permanent regression corpus before the defect is closed.
