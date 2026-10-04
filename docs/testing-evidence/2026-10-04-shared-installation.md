# Shared default Make installation

Change-kind: refactor. Issue #72 requests one default fake installation shared by read-only consumers, preserving each assertion and keeping stateful/failure-injection fixtures isolated.

## Scope and invariants

Eight tests inspect the same default installation: artifact publication, truthful registration reporting, the English model, menu-bar startup registration, modern tokenizer constraints, locked runtime dependencies, the terminal dashboard, and forced rebuilding of this checkout. A module-scoped fixture performs that installation once. Each test keeps its original assertions and oracle; all consumers only read the shared files and result. Failed builds, daemon/menu registration rollback, incumbent UI retirement, delayed teardown, and uninstall mutation/refusal remain independently owned test environments.

The environment builder explicitly removes inherited Git overrides because the shared module fixture precedes the function-scoped Git-isolation fixture. This preserves the isolation contract established by issue #74 instead of depending on fixture scheduling. The real Make entrypoint, owned tool shims, explicit paths and frozen uv export remain unchanged.

## Evidence so far

The parent is `1c92ee205c485acaf0bff9951e07efc5f4e195a1`. Docker source comparison finds identical assertion syntax trees in all 17 test functions, with 37 assertion statements. Ruff, formatting and Darwin-targeted mypy pass for the changed file. Input hashes and raw output are retained in `static-and-portable.json`.

The attempted Linux subset included four uninstall cases and the doctor case. The four uninstall cases passed, but doctor failed at Make's macOS platform refusal before its expected diagnostic. Doctor is unchanged by this refactor and that run is a failed subset, not a green suite or a native installation measurement. Collection-only execution did not run after the failure. Native fixture execution and controlled before/after per-test timings are still required before this issue can close. No performance improvement is claimed from static inspection alone.

The existing two-CPU, 4 GiB Docker worker and validation lock were reused with sampled allocation/log/deadline guards, a refreshed launch contract and whole-container cleanup. The worker stopped successfully. No installed application, daemon, audio device or host test run was used. Fixture-lifetime sharing remains a candidate until native acceptance and order-independence checks are recorded.

## Native comparison preparation

The retained `measure-native.txt` harness compares the immutable baseline test file at `1c92ee2` with this candidate using baseline/candidate/candidate/baseline ordering, then runs the candidate consumers in reverse order. It instruments the real subprocess boundary to count Make installation calls and records every setup/call/teardown duration, process CPU time and elapsed wall time. Duration observations are not CI thresholds. Each subprocess has fresh owned scratch paths; the same hosted runner, interpreter, dependency graph and production sources are used throughout. The original test file is restored in a `finally` block. Temporary CI measurement steps will be removed after retaining the native results.

Docker syntax compilation of the harness and assertion-AST comparison pass; these checks do not execute or validate the macOS kqueue monitor. The native monitor observes process exit without reaping, then signals the still-anchored group before waiting, including on normal completion. It uses the deadline refusal adapter from issue #105, so the measurement must wait for that fix to land on main. Runtime comparison, reversed-order acceptance, and native measurements remain pending. The reused Docker worker stopped successfully after the syntax check.
