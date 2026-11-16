# Segmentation corpus

[cases.json](cases.json) records 40 synthetic inputs and their expected spoken segments.
The [Python test](../../test_segmentation_corpus.py) checks `prepare_speech_segments` against each case.
A language port can use the same inputs and segment arrays.

This is a change-detection corpus for the pinned Python behavior.
It is not an external Markdown standard or a complete specification of segmentation.
No speech engine, daemon, or audio device is required.

## Record format

The corpus uses UTF-8 JSON. A Rust test can read the file without Python.
The top-level object contains `schema_version`, `reference_commit`, and `cases`.
Each case contains these fields:

| Field | Meaning |
| --- | --- |
| `id` | A unique, stable case name |
| `kind` | `plain_text`, `markdown`, `long_paragraph`, `short_blocks`, or `crlf` |
| `content_format` | `plain_text`, `markdown`, or `null` for the legacy wire default |
| `text` | The exact submitted text; JSON escapes preserve CRLF and other whitespace |
| `segments` | The expected ordered array of exact spoken strings |
| `review` | The reason for the expected projection and boundaries |

There are eight cases in each kind.
The cases include empty input, one word, a heading without a body, code, and nested lists.
The `reference_commit` records the Python baseline used for the comparison.

## Expected behavior

Explicit plain text retains markup characters.
Short plain text also retains its whitespace.
Markdown removes formatting syntax but retains code content, visible link text, and image alternative text.
Headings start sections. Lists and tables add spoken punctuation.

Paragraph separation starts at 60 words. Small blocks join adjacent paragraphs until a group has at least 20 words.
Long sections target 180 words, with a maximum of 220 words per segment.
A sentence boundary near the target takes priority over a word split.
Rendered Markdown uses LF. Plain paragraph content can retain CRLF.
Each case states its more specific expectation in `review`.

The empty case tests the pure function only. It does not authorize an empty daemon submission.

## Review and changes

The inputs and expected outputs were written independently, without copying function output into the corpus.
Repetitive word ranges were expanded from explicit boundaries. Each expected result was checked against the applicable rule before execution.
The cases and this reference are agent-written and reviewed by Codex. They do not claim human review.

Do not regenerate expected segments from a failing implementation.
Review the input, the expected projection, and the intended contract first.
If behavior must change, update the contract and its specific cases together.
Preserve case IDs so failures remain traceable.

Run `uv run pytest tests/test_segmentation_corpus.py` to check the corpus.
The [evidence record](../../../docs/testing-evidence/2026-11-16-segmentation-corpus.md) explains calibration and limits.
