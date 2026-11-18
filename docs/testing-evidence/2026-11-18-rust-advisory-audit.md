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

## Step calibration: pipefail

The audit step pipes into `tee`. Without an explicit `shell:`, GitHub Actions
runs `bash -e {0}` with no pipefail, so the step's status is `tee`'s. The
first version of this PR had that bug. The exact `run:` text, on the
zip 2.6.1 lock in the same throwaway worktree:

- `bash -e`: exit status 0 (the failing audit passed; RED for the step).
- `bash -e -o pipefail`: exit status 1.

The step now declares `shell: bash`, which GitHub runs as
`bash --noprofile --norc -eo pipefail {0}`.

## GREEN: current lock

The exact step text under `bash -e -o pipefail` on this branch (Cargo.lock
pins `zip` 9.6.1): exit status 0, `advisories ok`.

The job timeout stays at 15 minutes: the first CI run of the job took 210 s,
152 s of it installing cargo-deny.

## Oracle

The oracle is the RustSec database at the recorded commit, not this project's
code. A later database revision may add advisories and turn a green lock red;
that is the intended behaviour, and the recorded commit lets a past run be
reproduced.

## Not verified locally

The `cargo install` step on the macos-15 runner; CI on the PR covers it.
