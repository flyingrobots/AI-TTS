# Bounded caption-cue evidence

Date: 2026-09-05

Change kind: feature

Oracle: the caption overlay shows a short phrase from the active spoken segment,
never an entire document section; every cue stays within the approved reading
bounds and advances with clip-level playback progress without claiming word
alignment.

## Human finding

Once the caption panel became visible, a long active segment filled the overlay
with substantially more text than was comfortable to read. In particular, a
Markdown document may use a complete section as a synthesis segment. Reusing
that boundary as the presentation boundary would put the whole section on
screen even though the queue and synthesis behavior were correct.

The approved separation is:

- document segmentation remains the queue and synthesis boundary;
- the native overlay derives smaller, presentation-only caption cues;
- a cue prefers terminal punctuation and otherwise stops at 12 words or 84
  characters;
- the overlay renders at most two lines; and
- the cue clock uses segment position, segment duration, and observed playback
  rate, not invented word timestamps.

## RED: the cue presentation boundary did not exist

The initial four behavior tests were first compiled against the implementation
that rendered `segment.text` directly. The focused command exited 1 because
`CaptionCueTrack` and `CaptionPlaybackTimeline` did not exist:

```console
python3 scripts/run_with_deadline.py 60 swift test \
  --package-path clients/menubar --filter CaptionCueTests
```

A further boundary assertion used one unbroken token longer than 84 characters.
Against the first cue splitter it ran and failed by name because that token still
exceeded the presentation cap. That falsification distinguishes the hard
character promise from ordinary prose wrapping.

## GREEN: bounded, progressively selected cues

The same focused suite now passes five tests. Its witnesses include an 80-word
generated segment whose every cue is harvested for both bounds and whose joined
words equal the input, a natural two-sentence punctuation split, first/last cue
selection across a reported duration, pause/rate/clamp clock behavior, and the
unbroken-token case with no dropped characters.

The cue view constructs a track from each observed active-segment snapshot and
reuses it between observations while a 200 ms local timeline selects the
visible phrase. A successful daemon snapshot records the position-observation
time and playback rate together. State-transition and settings events re-anchor
that estimate, while the existing five-second poll remains a liveness and drift
watchdog rather than a caption-setting transport.

The complete Swift suite passed 65 tests behind its 60-second process-group
deadline. The unchanged Python boundary suite passed 214 tests. Ruff, Ruff
formatting, strict MyPy, and diff hygiene also passed.
