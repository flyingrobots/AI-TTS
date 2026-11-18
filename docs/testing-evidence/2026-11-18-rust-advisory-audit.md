# Rust advisory audit in the supply-chain job (issue #198)

Change-kind: bug fix. CI audited only the Python lock; a Rust crate with
critical advisories (`zip` 2.6.1, PR #194) merged through a green run.

## Check

`cargo deny --locked --offline check advisories` with cargo-deny 0.21.0 and
`deny.toml` (advisories only; unmaintained, unsound and yanked all deny).

Advisory database: RustSec `advisory-db` commit
`233155b4025b854c68a4b199c0e32d7fd53291a2` (2026-11-17T11:14:35+01:00).

## RED: lock from the merge of PR #194

A throwaway detached worktree at `e0fe8c1` (Cargo.lock pins `zip` 2.6.1),
with this branch's `deny.toml` copied in, after `cargo fetch --locked`.
The vulnerable lock was never committed. Exit status 1, `advisories FAILED`,
six `error[vulnerability]` diagnostics on `zip` 2.6.1:

RUSTSEC-2026-0367, RUSTSEC-2026-0368, RUSTSEC-2026-0369,
RUSTSEC-2026-0429, RUSTSEC-2026-0545, RUSTSEC-2026-0548.

## GREEN: current lock

The same command on this branch (Cargo.lock pins `zip` 9.6.1): exit status 0,
`advisories ok`. The CI step script was also run locally under
`bash -eo pipefail`, which GitHub Actions uses, producing the three evidence
files and exit status 0.

## Oracle

The oracle is the RustSec database at the recorded commit, not this project's
code. A later database revision may add advisories and turn a green lock red;
that is the intended behaviour, and the recorded commit lets a past run be
reproduced.

## Not verified locally

The `cargo install` step on the macos-15 runner; CI on the PR covers it.
