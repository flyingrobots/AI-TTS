# Quality audits

Audits produced with the framework in [`flyingrobots/code-quality`](https://github.com/flyingrobots/code-quality):
an agent grades this repository against `docs/rubric.md` and the per-metric
consistency guides in `docs/assessments/`, writes the scores into a JSON
payload, and `scripts/quality_auditor.py` normalizes the quantitative metrics,
applies a weight profile, runs the safety circuit-breakers, and compiles the
report.

## Snapshots

| Date | Commit | Fintech | Equal | Startup |
| --- | --- | --- | --- | --- |
| 2026-09-06 | `8ecbb7f` | 3.73 | 3.56 | 3.86 |
| 2026-09-07 | `e2c7706` | 3.78 | 3.62 | 3.94 |

The second was taken after a self-review and an independent review, and the
remediation of both. Movement is small on purpose: the work fixed defects
rather than adding capability, and defect *count* is not a rubric input. The
categories that moved are the ones that should have — Developer Experience
(`+0.25`, a Makefile and a one-command install), Code UX (`+0.16`, transport
correctness), Code Maturity and Project Health (`+0.17` each). Maintainability
went **down** `0.05`: the fixes were added to the four files that were already
too large, so size concentration got worse.

## Reproducing

```sh
git clone https://github.com/flyingrobots/code-quality
python3 code-quality/scripts/quality_auditor.py \
  docs/quality-audit/2026-09-07-audit-input.json \
  --profile fintech \
  --output /tmp/ai-tts-audit.md
```

Use a current checkout of the auditor. Two of its commits change scoring —
one redesigns the lines-of-code curve and one regrades SRP violations — so an
older copy answers a different question and its number is not comparable with
the table above. The same payload scored `3.75` rather than `3.78` on a copy
four commits behind.

`--profile equal` and `--profile startup` reweight the same scores; this
repository was audited under `fintech` because architecture section 9 makes
client-confidential speech a hard constraint, which is what that profile
weights.

## What the numbers mean

Two metrics do not read the way they look:

- **Technology Diversity is inverted.** The rubric scores `0` as best
  ("Minimal Diversity (Excellent)") and the CLI flips it internally, so the
  payload carries the raw rubric value. Python plus Swift scores `1`, which
  the report renders as `4.00`.
- **Cyclomatic Complexity, Code Duplication and Lines of Code** are raw
  measurements under `raw_metrics`, not 0–5 grades. The CLI maps them through
  normalization curves.

Quantitative inputs for the 2026-09-06 audit were measured, not estimated:
mean cyclomatic complexity across 423 Python functions, duplication as
repeated six-line normalized blocks over significant source lines, and LoC as
Python plus Swift source excluding tests.

## This is a dated snapshot, and it drifts

Both files name the commit they were produced against, and every `location`
in the payload is a `path:line` that was correct **at that commit**. Line
numbers move. Read a citation by checking that commit out:

```sh
git show <commit>:src/aitts/daemon.py | sed -n '320,330p'
```

A stale audit was the first thing a review of this repository found: the
payload cited a commit that a history rewrite had made unreachable, and all
three of its line references had drifted onto unrelated code. Regenerate
rather than hand-edit, and re-verify the citations when you do:

```sh
python3 - <<'CHECK'
import json, pathlib
d = json.loads(pathlib.Path("docs/quality-audit/2026-09-06-audit-input.json").read_text())
for metric, finding in d["findings"].items():
    location = finding.get("location", "")
    if ":" not in location:
        continue
    path, line = location.rsplit(":", 1)
    lines = pathlib.Path(path).read_text().splitlines()
    print(f"{metric:28} {location:56} {lines[int(line) - 1].strip()[:40]}")
CHECK
```

There is no CI gate on this, deliberately: the auditor lives in a separate
repository and is not a dependency of this one.

The report is written by that tool and committed verbatim, so its formatting
is the tool's rather than this repository's — its fenced blocks carry no
language, for instance. Do not hand-tidy it; the next regeneration would
undo the edit.

## Deliberate low scores

`Statelessness` and `Container-friendliness` score low by design and are not
tracked as defects. The daemon is a stateful singleton because exactly one
process may own the audio output device, and it cannot be containerized
because a container has no speakers. Their findings record the deviation
rather than proposing a fix.
