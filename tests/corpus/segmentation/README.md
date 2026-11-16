# Segmentation corpus

This draft defines the corpus format for [issue #115](https://github.com/flyingrobots/AI-TTS/issues/115).
The implementation must preserve the input cases and segment arrays across language ports.
This task does not change segmentation behavior.

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

The completed corpus must contain at least 40 inputs across all five kinds.
Empty input, one word, a heading without a body, code, and nested lists are required cases.
Expected outputs require individual review. Do not replace them with unchecked program output.

The Python test and the evidence record will accompany the completed corpus.
This reference is agent-written and awaits human review.
