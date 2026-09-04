# Testing-policy gate calibration — 2026-09-03

Change kind: feature.

Oracle: the accepted binding `docs/standards/testing.md`, especially rules 6,
9, and 19.

Each calibration mutation was applied alone and removed immediately after the
named failure was observed.

| Gate | Calibration | Command | Observed result |
|---|---|---|---|
| Explicit size class | Removed the module-level `small` marker from `test_model.py` | `uv run pytest tests/test_model.py --collect-only -q` | exit 4; every collected case named `expected exactly one size marker, found []` |
| Whole-suite latency | Set the declared suite budget to `0.0` seconds | `uv run pytest tests/test_model.py::test_priority_values -q` | the test passed, but the run exited 1 with `suite latency budget exceeded` |
| Per-size ceiling | Added a temporary small test containing `time.sleep(3)` | `uv run pytest tests/test_calibration_timeout.py -q` | exit 1 after two seconds with `Timeout (>2.0s) from pytest-timeout` |
| Cross-language deadline status | Changed the deadline runner's timeout result from 124 to 0 | `uv run pytest tests/test_deadline_runner.py::test_deadline_runner_terminates_suite_overrun -q` | assertion reported `0 != 124` while retaining the timeout diagnostic |
| Swift metadata harvesting | Removed `Test-Oracle` from the Swift XCTest file | `uv run pytest tests/test_swift_testing_policy.py -q` | failure named `AITTSMenuBarTests/WireProtocolTests.swift` as missing metadata |

The temporary timeout test was deleted after calibration. It has no product
behavior or permanent deletion criterion; its sole purpose was to calibrate
the gate once at adoption. The gate itself remains in `tests/conftest.py`.
