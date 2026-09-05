# CI trust-boundary evidence — 2026-09-05

Change kind: bug fix

Oracle: GitHub-hosted validation must consume reviewed code and dependencies
without granting an unnecessary write token or trusting mutable tool/action
references

## Regression on the unfixed workflow

The medium static contract suite was added while `.github/workflows/ci.yml`
still had its prior configuration:

```text
uv run --frozen pytest tests/test_ci_workflow_security.py
5 failed
```

The failures independently observed that the workflow had no explicit
read-only permission, used mutable `actions/checkout@v4` and
`astral-sh/setup-uv@v5` references, persisted checkout credentials, installed
an unversioned `uv`, and ran dependency-consuming project commands without
`--frozen`.

## Enforced boundary

The workflow now:

- defaults `GITHUB_TOKEN` to `contents: read` and requests no write scope;
- pins `actions/checkout` to commit
  `11d5960a326750d5838078e36cf38b85af677262` (`v4.4.0`);
- pins `astral-sh/setup-uv` to commit
  `d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86` (`v5.4.2`);
- sets `persist-credentials: false` on both checkouts;
- installs the reviewed `uv 0.9.18` and checks the lockfile; and
- uses `--frozen` for every `uv sync` and `uv run` project command.

The action commit/tag associations were resolved directly with
`git ls-remote --tags` on the action repositories. Full commit pins, rather
than the mutable tags, are stored in the workflow.

## Assertion calibration

The first implementation run exposed a test-parser blind spot: it recognized
anonymous `- uses:` steps but not a named step with a following `uses:` key.
The parser was corrected to inventory both shapes before accepting the
workflow.

A temporary `issues: write` scope then made only the no-write test fail. A
second calibration simultaneously changed one checkout to persist credentials,
changed the reviewed `uv` version, and removed one `--frozen`; exactly those
three contract tests failed. All temporary mutations were restored.

## Final verification

The restored workflow passed its six focused tests. `actionlint` accepted the
workflow, and `zizmor 1.28.0` reported no findings in offline mode (with one
suppressed audit). The complete exact tree also passed 224 Python tests, Ruff
lint and format checks, strict mypy, `uv lock --check`, and
`git diff --check`.
