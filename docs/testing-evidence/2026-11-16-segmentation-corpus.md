# Segmentation corpus evidence

Date: 2026-11-16

Change-kind: feature

Scope: [issue #115](https://github.com/flyingrobots/AI-TTS/issues/115).
This change adds test data and tests. Production segmentation is unchanged.

## Oracle and provenance

The [corpus](../../tests/corpus/segmentation/cases.json) contains 40 synthetic inputs, with eight cases for each required kind.
The [reference](../../tests/corpus/segmentation/README.md) defines its portable JSON schema and review procedure.
The pinned baseline is `d7c490211f2fdfda2863897b7be123b072adb57a`.

The expected strings were written independently from the behavior rules before execution.
A temporary helper expanded explicit word ranges. It did not import or call the implementation.
Each case records the reason for its expected projection or boundary.
All 40 expected results matched on the first comparison. No expected output was replaced from observed output.

This is a change-detection oracle for the existing Python behavior.
It is not external conformance evidence, a language-port differential, or a human review.
Codex reviewed each case against the pinned source and the segmentation contract in `docs/design/architecture.md`.
The corpus SHA-256 is `c5965db562eace679e4cff8c89a386904821843217ff8c6ee04190f2589831ba`.

The separate property uses input word order as its oracle.
It generates one to three paragraphs with sizes near 20, 60, 180, and 220 words.
It varies space, LF, CRLF, and whitespace-only paragraph separators.
Unique word tokens expose deletion, duplication, and reordering.

## RED to GREEN and calibration

The first corpus contained no cases. The coverage check failed with `assert 0 >= 40`.
Adding the reviewed data made all 42 new tests pass.
The following independent faults then made the relevant assertions fail.
Temporary fixture edits were restored byte-for-byte. Runtime faults existed only in their test process.

| Fault | Observed result |
| --- | --- |
| Remove one case | The 40-case minimum failed |
| Assign every case to `plain_text` | The required-kind set failed |
| Reuse the first case ID | The unique-ID check failed |
| Append an extra spoken segment | All 40 exact-output cases failed |
| Change the target from 180 words to 179 | Four boundary cases failed |
| Remove added terminal punctuation | Eleven Markdown cases failed |
| Drop the first output word | The word-preservation property failed |

The dropped-word failure reduced to `sizes=[1], separator=" "`.
The input was `p0w0.`; the corrupted output contained no words.
That minimized example is now an explicit Hypothesis example beside the property.
The corpus also retains the named `plain-one-word` case.

This command reproduces the boundary calibration without editing source files.
It must exit with four failed cases.

```sh
uv run python - <<'PY'
import pytest
from aitts import segmentation

segmentation.TARGET_SEGMENT_WORDS = 179
raise SystemExit(pytest.main([
    "tests/test_segmentation_corpus.py::test_segmentation_matches_reviewed_corpus",
    "--tb=short",
]))
PY
```

## Repeated verification

The environment used Python 3.12.14, pytest 9.1.1, Hypothesis 6.167.1, and uv 0.13.8 on macOS arm64.
The new module has 40 exact-output cases, one coverage check, and one generated property.
The corpus checks use the `medium` class. The pure generated property uses `small`.

The combined segmentation suite passed all 68 tests in ten runs.
Two isolated processes each ran five seeds in sequence.
Each process shuffled test order and explicitly applied `hypothesis.seed` to generated tests.
Seeds were recorded before pytest started: `115` through `119`, and `252457533` through `252457537`.
The second range starts from a system-generated random seed.
Each generated property ran up to 60 examples per run, plus its explicit examples.

The tests use `derandomize=True` for ordinary deterministic CI runs.
In the installed Hypothesis version, this setting takes priority over the global `--hypothesis-seed` option.
The local repeat harness therefore used the public `hypothesis.seed` decorator, which takes priority over `derandomize`.
This command reproduces one shuffled, explicitly seeded run.

```sh
uv run python - <<'PY'
import random
import pytest

SEED = 252457533
print(f"Replay segmentation tests with seed {SEED}", flush=True)

class SeededOrder:
    def pytest_collection_modifyitems(self, items):
        from hypothesis import seed
        random.Random(SEED).shuffle(items)
        for item in items:
            if hasattr(item.obj, "hypothesis"):
                seed(SEED)(item.obj)

raise SystemExit(pytest.main([
    "tests/test_segmentation.py",
    "tests/test_segmentation_corpus.py",
], plugins=[SeededOrder()]))
PY
```

Focused Ruff, formatting, and strict mypy checks passed.
Normal commit and push hooks provide the repository checks.
Hosted checks remain part of the PR merge gate.

## Limits

These tests do not synthesize audio or operate a live daemon.
The corpus covers selected Markdown forms and boundary lengths, not every Unicode token or Markdown construct.
The plain-text property compares whitespace-separated input words in order. It does not require preservation of whitespace.
The empty pure-function case does not test daemon admission.
This evidence record is agent-written and does not claim a human acceptance review.
