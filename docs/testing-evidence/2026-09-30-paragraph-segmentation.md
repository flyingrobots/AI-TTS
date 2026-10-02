# Paragraph-level transport chunks

Change-kind: feature

## Policy and prompt interpretation

Prompt 7 requests paragraph navigation around 60 words, including both two- and
three-paragraph 100-word examples, while suggesting a 40-word paragraph minimum.
A strict per-paragraph minimum of 40 cannot produce three chunks from 100 words.
The implemented policy therefore uses a **60-word document/section threshold**
and **20-word paragraph-group minimum**, as stated in the progress update.
Tiny leading/intermediate blocks join the following block; a short tail joins
the preceding group. Ordinary text below the threshold or without paragraph
breaks remains exact. Existing explicit Markdown section behavior is preserved.

Long paragraphs still use the 180-word target and 220-word maximum. LF, CRLF and
whitespace-only blank lines delimit paragraphs. Markdown projection precedes
grouping; literal plain text retains its syntax. The parent source is unchanged,
and existing clip plans are not retroactively rewritten.

## Red/green and falsification

Eleven newly added cases failed against the original segmenter, with named
assertion failures for 100-word two/three-paragraph plans in plain, Markdown and
legacy modes; LF/CRLF/whitespace separators; tiny-block attachment; and rendered
Markdown heading/blockquote boundaries. Receipt:
`.git/codex-scratch/paragraph-segmentation-red.log`.

Restored behavior passes those cases, an explicit atomic 15-word sentence, and
60 deterministic generated paragraph layouts checking exact token order,
nonempty children and the existing 220-word ceiling. Eight seeded faults detect
disabled medium paragraph grouping, an excessive paragraph minimum, an early
document threshold, dropped tail, unbounded paragraphs, reversed source order,
split short clips and empty children. See
[calibration](2026-09-30-paragraph-calibration.json). All sources were restored.

An owned FakeEngine/FakeSink daemon test submits the 100-word source through the
actual socket, observes two durable children and an unchanged parent, then
performs next and previous chunk operations. Owned sink-start events establish
completion; no audio hardware or polling sleeps are used. Disabling paragraph
grouping makes this admission-boundary assertion fail.

No schema migration, model change, Swift change or dependency change is needed.
This prompt remains one feature commit and one PR on top of the terminal feature.
No issue is fully closed by this change. Acoustic performance and semantic
paragraph detection beyond the existing word-count policy are not claimed.

Final local checks: **742 Python tests**, Ruff, formatting and mypy pass. Small
and medium tier costs are 0.64 s and 12.07 s, wall 13.22 s. Receipt:
`.git/codex-scratch/paragraph-final-python.log`. Swift and the frozen dependency
graph are unchanged from the preceding passing PR #38 checks.

## Reconciliation with reviewed main

The five open feature commits were replayed onto main `6482b49`, preserving
merged review corrections from prompts 1 and 2 and the existing native UI work.
The paragraph test conflict retains both literal-Markdown regressions from main
and the new paragraph cases. No assertion was dropped to complete the rebase.

The combined tree passed 793 Python tests (271 small, 522 medium; 0.79/12.85
seconds by tier, 14.18 seconds wall clock), Ruff, formatting for 216 files,
and mypy for 138 files. Its 142 Swift tests passed with warnings as errors after
the model-picker API correction recorded in the multi-engine receipt.
The original per-feature red and seeded-fault receipts remain historical
evidence; these integration results do not claim new native acoustic acceptance.

## Reproduced red on the parent segmenter

The red receipts above point to untracked `.git/codex-scratch` logs, so the Code Lawyer audit reproduced them. With `src/aitts/segmentation.py` taken from the PR's parent `a33ce35` and this PR's tests at `e5d06e0`, `uv run --frozen pytest -q -p no:randomly tests/test_segmentation.py tests/test_paragraph_playback.py` failed exactly these 12 cases. The other 14 passed, including the generated token/size invariant and the atomic 15-word case, which hold on both sides by design:

```text
FAILED tests/test_segmentation.py::test_hundred_word_paragraphs_are_independently_navigable[plain_text-sizes0]
FAILED tests/test_segmentation.py::test_hundred_word_paragraphs_are_independently_navigable[plain_text-sizes1]
FAILED tests/test_segmentation.py::test_hundred_word_paragraphs_are_independently_navigable[markdown-sizes0]
FAILED tests/test_segmentation.py::test_hundred_word_paragraphs_are_independently_navigable[markdown-sizes1]
FAILED tests/test_segmentation.py::test_hundred_word_paragraphs_are_independently_navigable[None-sizes0]
FAILED tests/test_segmentation.py::test_hundred_word_paragraphs_are_independently_navigable[None-sizes1]
FAILED tests/test_segmentation.py::test_paragraph_threshold_and_short_clip_identity[\n\n]
FAILED tests/test_segmentation.py::test_paragraph_threshold_and_short_clip_identity[\r\n\r\n]
FAILED tests/test_segmentation.py::test_paragraph_threshold_and_short_clip_identity[\n \t\n]
FAILED tests/test_segmentation.py::test_tiny_leading_and_trailing_blocks_attach_to_substantial_paragraphs
FAILED tests/test_segmentation.py::test_markdown_structural_blocks_and_heading_stay_attached
FAILED tests/test_paragraph_playback.py::test_submitted_paragraphs_support_next_and_previous_without_changing_parent
```

These are the eleven segmentation cases and the daemon transport case described above. The seeded-fault rows in the calibration JSON were not re-run; their logs remain untracked.

## Code Lawyer audit: long-document paragraph grouping

Change-kind: test addition (no behavior change). Parent SHA `e5d06e0`. The long branch of `segment_text` (over 180 words) runs `_paragraph_segments` before `_bounded_segments`, but no test covered it: with the pre-PR loop `for segment in _bounded_segments(section)` restored, all 878 Python tests still passed. `test_long_document_exposes_each_paragraph_group` (small; oracle: architecture section 8) submits five 50-word paragraphs, 250 words, and expects five chunks. Against that seeded fault it fails with `AssertionError: assert ('p0word0 p0w...d48 p4word49') == ('p0word0 p0w...d48 p4word49')`, `At index 0 diff`, because the old loop packs the first four paragraphs into one 200-word chunk. On the restored source it passes.
