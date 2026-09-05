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
