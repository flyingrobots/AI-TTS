# Update the locked PyJWT dependency

Change-kind: bug fix

PR #26's supply-chain job failed against the existing PyJWT 2.13.0 lock with ten
known advisories, each identifying 2.14.0 as a fixed release:
[failed audit run](https://github.com/flyingrobots/AI-TTS/actions/runs/36694974563).
The downloaded audit artifact identified PyJWT as the only vulnerable package.

Updated only PyJWT's version and wheel/source hashes to 2.14.0. Re-exported the
frozen Python 3.12 all-extras graph and ran the same strict PyPI-backed pip-audit
command in an isolated environment: **No known vulnerabilities found**. The
failed CI audit is the red receipt; the strict post-update audit is the green
receipt. This dependency change does not add a new automated assertion.
