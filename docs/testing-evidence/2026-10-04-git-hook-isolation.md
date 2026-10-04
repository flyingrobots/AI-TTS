# Git hook context isolation

Change-kind: bug fix. Issue #74. Oracle: validation tools and owned pytest fixtures must not inherit the launching repository's Git redirection context.

## RED

On parent `2378f24df72384c1e774cfcb7cc8d9244e38718c`, three medium regressions fail for their intended assertions. Both real hook entrypoints pass `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`, `GIT_INDEX_FILE`, and `GIT_PREFIX` into an owned validation-tool shim. A child pytest run using the repository's real conftest executes a naive `git -C <owned target> init --bare`; inherited `GIT_DIR` redirects it into an owned decoy. The intended target is not initialized, and the decoy's configuration changes. No real checkout is exposed to that fault.

## GREEN

Hooks resolve their project directory first and then unset the five repository/index overrides. An autouse function-scoped fixture removes inherited `GIT_*` variables through pytest's restoring monkeypatch fixture. Explicit test-local injection remains supported, as checked by the existing benchmark Git-environment regression.

All three new regressions and all 56 benchmark tests pass in Docker. The four uninstall cases also pass, along with Ruff, formatting, and Darwin-targeted mypy. The broader Linux-compatible suite passes; four macOS-specific installation/integration modules are excluded because their native boundaries already fail on Linux. Hosted macOS CI remains required for the complete suite. Tests skipped for platform or native UI prerequisites are not claimed as executed acceptance.

## Limits

The hook tests run the actual scripts against an owned Git repository and capture every fake `uv` invocation; they do not run real validation from a host Git hook. The pytest regression launches a real child pytest process with the production conftest and an owned decoy. Per-test isolation does not cover module-import side effects or session-scoped fixture setup; those Git callers still need explicitly isolated subprocess environments. No global Git configuration or installed hooks are changed.

Validation reused the bounded Python Docker worker and its dependency cache. Raw RED/GREEN logs record the parent commit, candidate source/test fingerprints, executed commands, and exit statuses.
