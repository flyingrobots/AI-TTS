# Quality audits

Audits produced with the framework in [`flyingrobots/code-quality`](https://github.com/flyingrobots/code-quality):
an agent grades this repository against `docs/rubric.md` and the per-metric
consistency guides in `docs/assessments/`, writes the scores into a JSON
payload, and `scripts/quality_auditor.py` normalizes the quantitative metrics,
applies a weight profile, runs the safety circuit-breakers, and compiles the
report.

## Reproducing

```sh
git clone https://github.com/flyingrobots/code-quality
python3 code-quality/scripts/quality_auditor.py \
  docs/quality-audit/2026-09-06-audit-input.json \
  --profile fintech \
  --output /tmp/ai-tts-audit.md
```

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

## Deliberate low scores

`Statelessness` and `Container-friendliness` score low by design and are not
tracked as defects. The daemon is a stateful singleton because exactly one
process may own the audio output device, and it cannot be containerized
because a container has no speakers. Their findings record the deviation
rather than proposing a fix.
