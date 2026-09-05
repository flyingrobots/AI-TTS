# Composite document playback evidence

Date: 2026-09-04

Change kind: feature

Oracle: the approved long-document direction in
`docs/design/architecture.md` section 8, refined by the 2026-09-04 product
decision that one top-level document owns an internal segment queue, blocks
later top-level clips, starts playback before whole-document synthesis, and
binds every segment to one voice profile.

## RED: segmentation contract

The first contract enters through the pure daemon-owned segmentation boundary.
Short text must retain its exact clip identity. Long Markdown must become an
ordered, non-empty, size-bounded segment plan without losing or reordering any
spoken word, and a section heading must remain attached to its following body.

On the pass-through implementation, this command exited 1:

```console
uv run pytest tests/test_segmentation.py -q
```

`test_markdown_document_becomes_lossless_bounded_segment_plan` reported one
522-word segment instead of four segments with a largest size of 180 words;
the `## Details` heading was also not attached to a segment beginning with its
body. The short-text control passed, isolating the missing long-document
behavior rather than a general import or collection failure.

Further synthesis, playback, recovery, and live-rate calibrations will be
recorded here as those boundary slices are introduced.

## GREEN: structure-aware segmenter

The daemon policy now treats Markdown headings as strong section boundaries,
prefers nearby paragraph boundaries, then sentence boundaries, and uses a word
boundary only as the hard fallback. The target is 180 spoken words and the
maximum search window is 220. Text of 180 words or fewer retains byte-for-byte
clip identity.

The focused suite is green:

```console
uv run pytest tests/test_segmentation.py -q
```

The short-clip identity assertion was independently calibrated by temporarily
trimming its returned text. Its focused test exited 1 and displayed the missing
leading spaces and trailing newline. The mutation was reverted before the
green run. The losslessness assertion was separately calibrated by temporarily
dismissing the final segment; its focused test exited 1 on both the expected
segment count and the flattened source-word sequence. That mutation was also
reverted before the green run. The original pass-through RED remains the
calibration for bounded long-document planning and heading attachment.

## RED: Markdown spoken projection

The spoken-projection contract enters through `prepare_speech_segments`, before
engine selection or synthesis. Plain prose must keep exact clip identity.
Markdown headings become isolated, punctuated phrases; inline emphasis and code
markers disappear; links retain their human label but not their destination;
blockquote and bullet markers disappear; table separators are silent while
cell contents remain; and fenced code retains its content without the fence.

With the projection implemented as a plain pass-through, this command exited 1:

```console
uv run pytest tests/test_segmentation.py -q
```

The Markdown example returned every raw marker and the link destination instead
of the expected spoken text. The adjacent plain-text identity control passed,
isolating the missing normalization behavior.

## GREEN: AST-based Markdown projection

`prepare_speech_segments` now parses GitHub-flavored Markdown with
`markdown-it-py` and walks its syntax tree. Structural nodes drive boundaries
and punctuation while leaf text supplies spoken content. HTML interpretation
and automatic URL linking are disabled. Plain-text-only trees still return the
original clip byte for byte.

The focused suite is green:

```console
uv run pytest tests/test_segmentation.py -q
```

The nested-node oracle was calibrated by temporarily dropping traversal into
inline child nodes. Its focused test exited 1 after losing the heading,
emphasis, link label, image alt text, quote, list, and table cell content while
the fenced-code leaf remained. The tree traversal was restored before the
green run.

## RED: durable parent-owned segment queue

The storage contract enters through `Store.submit` and a reopen of its SQLite
database. One parent must preserve the exact original Markdown plus its single
voice and synthesis-speed profile, while an ordered child queue durably stores
the clean spoken segments. Children begin Queued and do not duplicate mutable
voice configuration.

With `spoken_segments` accepted but intentionally discarded, this focused
command exited 1:

```console
uv run pytest tests/test_store.py::test_composite_submission_persists_original_and_owned_spoken_segments -q
```

The reopened parent retained its original text and profile, while the observed
child list was empty instead of the two expected Queued segments.

## GREEN: durable parent-owned segment queue

SQLite now stores child segments under a foreign key and composite primary key
of parent id plus zero-based segment index. Parent submission and ordered child
insertion share one commit. The children contain synthesis/playback lifecycle
data only; voice, speed, sensitivity, priority, source, and original Markdown
remain single-owned by the parent.

The focused reopen test and the complete store suite are green:

```console
uv run pytest tests/test_store.py -q
```

## RED: synthesis claims inside the parent queue

The next storage boundary requires synthesis claims to descend into the first
parent's child queue before claiming a later top-level item. Each returned work
item must contain the child text and artifact identity while resolving voice
and synthesis speed from its immutable parent profile.

The focused claim test exited 1. The legacy claimer returned the raw parent as
the first work item, skipped both persisted children, then claimed the later
top-level utterance. That is precisely the queue-flattening behavior this slice
replaces.

## GREEN: synthesis claims inside the parent queue

The store now returns an explicit `SynthesisWork`. Its cache-safe artifact id
identifies either the legacy parent clip or one child index, while text comes
from that child and voice/speed come from the parent. SQL orders candidates by
top-level plan position and then child index, so a document remains one
blocking queue entry without becoming one giant engine request.

The legacy FIFO claim test and the focused composite claim test are green.

## RED: first-segment readiness

A deterministic engine gate holds the second child inside synthesis. While it
is held, the parent must already be Ready, the first child must be Ready, the
second must remain Synthesizing, and both calls must carry the same parent
voice/speed. This enters through the real `SynthesisPool`, artifact adapter,
and store rather than mocking their collaboration.

The focused test exited 1 at its one-second deterministic deadline: the pool
looked up the child artifact id as though it were a parent id, synthesized
nothing, and therefore never reached the second-child gate.

## GREEN: first-segment readiness

The pool now carries `SynthesisWork` through target allocation, engine calls,
artifact publication, and completion. Publishing child zero marks the parent
Ready immediately; later children continue through the same workers. The
deterministic second-child gate observed the parent and first child Ready while
the second child remained Synthesizing, with `bm_george` at 1.5 on both engine
calls. The full synthesis and store suites are green.

## RED: daemon document admission

The wire contract now submits a 522-word Markdown document through the running
daemon while playback is held. Its public parent must retain the exact source
and requested profile, while the private speech plan contains four clean
segments and the submit response declares that composite shape.

The focused IPC test exited 1. The parent/profile controls passed, but the
daemon reported no composite metadata and persisted zero children, so neither
normalized heading could be found.

## GREEN: daemon document admission

Admission now creates the engine-neutral speech plan before persistence. Exact
single-clip prose stays on the legacy path; normalized Markdown or multi-part
text stores child rows. Empty spoken projections fail closed. The response
reports `segment_count` and `composite`, while all public queue/history text
continues to come from the untouched parent. The focused IPC contract is green.
