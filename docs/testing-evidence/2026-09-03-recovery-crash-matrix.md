# Recovery crash-matrix evidence

Date: 2026-09-03

Change kind: new feature (test instrumentation)

Oracle: architecture sections 3 and 6 require queued text to survive restart,
interrupted synthesis to return to Queued, and persisted Playing state to
recover as Paused before any audio can start

## Fault model

The test seeds five durable records: one Queued, two Synthesizing, one Playing,
and one Ready. `CrashAfterCommit` is injected through
`DatabaseConnectionFactoryPort`; after the selected recovery commit becomes
durable, it raises `SeededRecoveryError` to model process loss between recovery
steps.

Three parameterized seeds cover every recovery write boundary:

- `after_commit_1`
- `after_commit_2`
- `after_commit_3`

Each interrupted connection is closed, the same database is reopened, and
recovery runs again. The one output assertion projects the five known durable
records to `(text, state)`. For every seed, text remains intact, both interrupted
syntheses converge to Queued, the current clip converges to Paused, and the
unaffected Queued and Ready records remain unchanged.

## Calibration

The assertion was shown able to fail by mutating the production recovery scan
from Playing records to Paused records. Seeds 1 and 2 then reported the exact
unsafe state, `Playing` instead of `Paused`; seed 3 additionally reported that
its scheduled crash point was never reached. The mutation was reverted before
the GREEN run.

Replay one seed with:

```console
uv run pytest 'tests/test_store.py::test_recovery_converges_after_each_committed_crash_point[after_commit_2]'
```

## Remaining boundary

This matrix explores every commit boundary in the current recovery algorithm.
It does not simulate torn SQLite/WAL writes, a fault while rollback itself is
failing, or a recovery-time performance objective. Those remain explicit
strengthening opportunities rather than claims made by this release.
