# Ignored reference code

Change-kind: bug fix. Issue #62. Oracle: the benchmark comparator must reject importable ignored code in its pinned reference before starting a worker, while permitting ordinary Python caches and unrelated scratch files outside `src`.

## RED and GREEN

Parent `75edb22f0affa6d381e8db033405ae72cb81c881` rejects untracked source with Git status but does not enumerate ignored files. The final 16-test reference suite on that implementation produced nine expected failures and seven passes in Docker. The failures cover an ignored package shadowing a tracked module, five source/native/bytecode filename variants, an external-package symlink, a newline-containing directory, and a bare sourceless module inside `__pycache__`.

The shadowing test first imports the owned package through a fresh Python process and observes `untracked shadow`, then enters the comparator's CLI entrypoint. On the parent, comparison scheduling is reached instead of refusal. The test replaces that scheduling boundary with a failure so no real benchmark worker can escape. On the fixed code the CLI exits with code 2 before creating its output directory. Both ignored and ordinary untracked shadows are covered.

After the fix, all 55 benchmark tests pass in Docker (23 small, 32 medium). The change retains the tracked-edit, wrong-SHA, clean-reference, and inherited-Git-environment guards. NUL-delimited Git output avoids filename quoting ambiguity. Symlinks are rejected conservatively even when their names have no executable suffix. Tagged cache filenames are recognized through Python's cache-path parser; bare importable `.pyc` files are not treated as ordinary caches.

## Limits

The original benchmark pin and all historical results remain untouched. No claim is made that previous benchmark reports were contaminated. Native-module fixtures check admission by filename, not execution of a foreign binary. Ordinary bytecode cache contents are not authenticated; this is a source-identity guard, not a sandbox against an adversarial filesystem or concurrent mutation after validation. Actual paired performance campaigns are not needed to exercise this admission defect and were not run.

Validation used the existing two-CPU, 4 GiB Docker worker with copied source and a 1 GiB temporary filesystem. No new worker, image, or compilation cache was created for this issue.
