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

## Remediation after the second snapshot

Every finding from the `e2c7706` snapshot has since been worked. There is no
third snapshot here: re-scoring is the auditor's job, not this repository's,
and a number written by hand would be worth nothing. What the work was is in
`CHANGELOG.md` and in the commits; briefly:

| Finding | What was done |
| --- | --- |
| Observability — Metrics | A `metrics` op, `ai-tts metrics` and a `speech_metrics` tool report the two waits separately, plus queue depth, cache bytes against the cap, and device failures counted apart from cancellations |
| Observability — Tracing | Lifecycle events carry a `trace=` token derived from the utterance id |
| Project Health — Bus Factor | [`docs/design/one-utterance.md`](../design/one-utterance.md) walks one utterance end to end |
| Project Health — Issue & Bug Management | [GitHub Issues](https://github.com/flyingrobots/AI-TTS/issues) is the tracker, with issue and PR templates; see the deviation below |
| Maintainability — SRP violations | `daemon.py` 1097 → 855 lines (`aitts.settings`, `aitts.voice_registry`, `aitts.input_interrupt`); `Views.swift` 1257 lines → six files by surface |
| Code Maturity — Automated Deployment | A tag builds and retains the wheel, sdist and signed bundle after every other job passes, and refuses a tag that disagrees with the tree |
| Accessibility — all three | Transport labels and keys as assertable values, spoken progress, a live-region announcement for the interruption notice, and pause on `p` |
| Cloud-Native — Statelessness, Container-friendliness, 12-Factor | Recorded as decisions with their reasoning in [`architecture.md`](../design/architecture.md) §9a rather than as gaps |

Two of the audit's recommendations were **not** followed, and the reasoning is
recorded where the code is:

- It suggested the extracted Python services go under `src/aitts/application/`.
  They went to the top level instead: that package holds pure logic and ports
  and deliberately does not import `Store`, while these services hold it.
- It suggested a tracked `docs/backlog/` directory of Markdown files. That
  existed briefly and was migrated to GitHub Issues, which is now the only
  tracker. Two lists is one list recorded wrong: an in-repo file and an issue
  for the same defect disagree within a release, and the issue is the one
  people actually find. The private working journal at `.claude/bad_code.md`
  stays untracked for design-level notes with no user-visible consequence.
- It suggested marking the caption overlay as accessibility-announcing. That
  would have VoiceOver read aloud, in a second voice, the words already being
  spoken aloud. The overlay is explicitly hidden from the accessibility tree
  instead, with the reasoning in `CaptionPanelController.swift`.

One recommendation is **deliberately incomplete**: the release job retains its
artifacts on the workflow run rather than attaching them to a GitHub Release,
because attaching needs `contents: write` and this workflow's trust boundary
is that nothing in it can write to the repository. Creating the release stays a
human action.

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

## Errata: three errors in the reports themselves

Found by a pre-push audit on 2026-09-07 and verified by hand. These are not the
citation drift described below — they were wrong at the commit each report
names, so regenerating against a current checkout will not explain them away.
They are recorded here rather than corrected in place, because the reports are
committed verbatim and a hand-edit would be undone by the next regeneration.

**The commit count is wrong by about three and a half times.** Both reports and
both payloads assert "571 commits" — fourteen occurrences in total, used to
support the versioning and single-author findings. The real counts:

```sh
git rev-list --count 8ecbb7f   # 147, the 2026-09-06 report's own commit
git rev-list --count e2c7706   # 160, the 2026-09-07 report's own commit
```

This matters more than the number does. The claim under "What the numbers
mean" below is that quantitative inputs were *measured, not estimated*, and a
headline figure disproved by one command undercuts that for the figures that
were measured correctly.

**The 2026-09-07 report contradicts itself on one page.** Its Level-2 rationale
calls `Views.swift` "a single 900-line file"; its Level-1 matrix, same
document, same commit, says it "has grown to 1169 lines". The cause is visible
in a diff of the two reports: all eleven Level-2 category rationales are
byte-identical between them while the scores and Level-1 rows changed, so the
second audit reused the first's prose against new numbers. The same mismatch
appears on release tooling, where one section says CI builds no artifact and
another describes the Makefile that had just landed.

**The payloads publish a file that is deliberately untracked.** The
`mitigation_prompt` fields are instructions addressed to a coding assistant
rather than findings, and one of them enumerates the contents of
`.claude/bad_code.md` — a gitignored working journal — to justify a
recommendation that was in the end not followed. Four of the items it lists had
already shipped when it was written.

Read the reports with that in mind, and with one more thing: the **PRODUCTION
READY** banner at the top of each is self-administered. The tool, the weight
profile, and the repository are all the same author's. The scores below are
worth what any self-assessment is worth, which is why this file exists.

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
rather than proposing a fix; the full set of such deviations, including
twelve-factor logging and the absence of authentication, is in
[`architecture.md`](../design/architecture.md) §9a.
