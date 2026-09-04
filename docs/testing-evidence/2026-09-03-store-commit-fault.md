# Store commit-fault evidence

Date: 2026-09-03

Change kind: bug fix

Oracle: failed durable writes are invisible both live and after reopen

## Red on the unfixed code

Commit `4c17edf` installs a one-shot SQLite connection whose next `commit()`
raises `OperationalError("seeded commit failure")`. The request enters through
`Store.submit`; no private store state is asserted.

On that commit, the failed submission remains visible from `Store.counts()` as
`{"Queued": 1}` for the life of the connection. Closing and reopening the same
database reports `{}` because SQLite rolls the transaction back then. The live
daemon and its durable state therefore disagree.

## Fix and calibration

`DatabaseConnectionFactoryPort` makes the database dependency explicit at the
SQLite adapter boundary. Every explicit store commit now passes through one
commit-or-rollback operation.

The regression observes only three outputs: the surfaced fault, live counts
after the fault, and counts after reopen. Removing the rollback call was
observed to make the test red again with the original `{"Queued": 1}` live
phantom while reopened state remained empty.

## Remaining boundary

This deterministic fault covers commit failure and rollback visibility. It does
not claim exhaustive crash safety, torn-write simulation, disk-full behavior,
or a failure while already recovering. Those cells remain explicit in the
release risk map.
