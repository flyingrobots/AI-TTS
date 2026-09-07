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

## RED: nested playback serialization

The playback contract places a normal clip after a two-child document. The
single sink must start child zero, then child one, then the following parent;
the latter remains Ready until the document reaches one parent-level Played
state. Child lifecycle must be observable and overlap must remain zero.

The focused test exited 1 immediately after the first plan cycle. Both children
and the parent remained Ready and the sink started nothing, because legacy
playback requires a single parent `audio_path`.

## GREEN: nested playback serialization

The controller now owns one parent id plus an optional active child index. It
transitions and plays child artifacts in order, keeps the parent current while
waiting between children, accumulates document position from completed child
durations, and releases the top-level queue only when no child remains. The
focused contract observed child 0, child 1, then the following legacy clip,
with zero overlap; the complete playback suite is green.

## RED: composite crash recovery

The recovery test persists a document with child zero Playing at 400 ms, child
one Synthesizing, and child two already Ready. After reopening, the parent and
active child must be Paused at the recorded position, interrupted synthesis
must be Queued, and the completed artifact must remain Ready rather than being
replayed.

The focused test exited 1. Parent recovery already produced Paused at 400 ms,
but its children remained Playing and Synthesizing; the independently Ready
child stayed correct as the control.

## GREEN: composite crash recovery

Recovery now repairs child lifecycle before aggregating parent state:
Synthesizing becomes Queued, Playing becomes Paused with its stored position,
and Ready/Played children are untouched. The focused crash-state test and full
store suite are green.

## RED: composite restart and skip

Restart while child one is playing must reset the document and begin child zero
from 0 ms using cached artifacts. Skip during child zero must record the
document-relative position, mark that active child Skipped, cancel the remaining
child queue, and immediately unblock the next top-level clip.

Both focused tests exited 1. Restart timed out waiting for a third sink start
because the legacy implementation requires a parent audio path. Skip advanced
the top-level queue and recorded 350 ms, but left its children incorrectly
Playing and Ready.

## GREEN: composite restart and skip

Restart now releases the sink, resets every cached completed/active child to
Ready at 0 ms, and starts child zero without re-synthesis. Skip records local
position on the active child, sums prior child durations for parent-relative
position, cancels every remaining child (including synthesis work), and
unblocks the next parent. The strengthened skip case completed child zero,
skipped child one at 350 ms, cancelled child two, and recorded 1,350 ms on the
parent. The complete playback and store suites are green.

## RED: discrete playback-rate setting

The daemon settings contract must accept exactly the six UI choices (0.5,
0.75, 1, 1.5, 2, and 3), persist the latest choice independently from
synthesis speed, and reject an unsupported 1.25 value as a bad request.

The focused IPC test exited 1: every supported value was rejected as an
unknown setting and nothing was persisted. The unsupported value already
failed closed as the control.

## GREEN: discrete live playback rate

The controller restores a persisted rate, applies changes directly to the
active sink without restarting its source, and keeps playhead position in
source-audio time. The real sink reads each output block at the current source
step, so a rate change takes effect on the next block. The focused active-sink
oracle was calibrated by temporarily omitting `sink.set_rate`: it exited 1 with
the source, position, state, and persistence controls unchanged while the sink
remained at 1.0. The IPC test accepts exactly the six requested choices and
rejects 1.25. The existing exact settings-response test also RED-confirmed the
new field before its expected wire shape was updated.

## RED: menu-bar playback-rate contract

The Swift wire model must expose the daemon's persisted playback rate, and its
UI enum must enumerate exactly the six requested values and labels in dropdown
order. The initial seam deliberately defaults decoded snapshots to 1.0.

`swift test --quiet` exited 1 only at snapshot decoding: the choice/label
contract passed, while a wire value of 1.5 was observed as the deliberate 1.0
default.

## GREEN: menu-bar playback-rate dropdown

The snapshot decoder now carries `playback_rate` into `AppState`. The Now
Playing transport exposes an exact six-value menu and optimistically updates
before sending the settings operation; the existing Settings slider is relabeled
as voice-generation speed to keep the two controls distinct. All 12 Swift tests
are green.

## RED: active-segment caption payload

A dedicated manual sink holds a normalized one-segment Markdown document in
Playing. Status must retain the exact Markdown parent while exposing an
`active_segment` containing only the spoken text, index/number/count, child
state, child duration, and child-relative position.

The focused IPC test exited 1 with the parent controls correct and both
`segment_count` and `active_segment` absent from status.

## GREEN: active-segment caption payload

The controller now exposes its active child and child-relative playhead,
including a recovered Paused child. Daemon serialization annotates every item
with composite progress and status embeds the exact active spoken segment;
legacy clips receive an equivalent one-segment caption payload. The focused
manual-sink contract and full IPC/playback suites are green.

## RED: Swift active-caption decoding

The Swift `Utterance` model must decode document progress and the complete
nested active-segment payload. Its initial seam decodes progress but
deliberately leaves `activeSegment` nil.

`swift test --quiet` exited 1 only on the expected non-nil `ActiveSegment`;
segment count and completed count decoded correctly as controls.

## GREEN: opt-in macOS caption panel

Swift now decodes the complete active segment. A borderless non-activating
`NSPanel` joins all Spaces, floats above ordinary windows, ignores mouse input,
and renders up to four centered lines of the exact spoken segment. A persisted
caption toggle is available beside the playback-rate dropdown and in Settings;
disabled, unreachable, and no-active-segment states all hide the panel. Child
state changes now produce daemon events so captions advance immediately.

The visibility oracle was calibrated by temporarily ignoring the opt-in flag;
its focused Swift test exited 1 on the disabled case while reachable/active
controls stayed valid. The mutation was reverted, and all 13 Swift tests plus
the focused backend caption test are green.

The first full Python suite then exited 1 at the strict public application
adapter because the new `segment_count` and `composite` receipt fields were
correctly rejected as undocumented extras. The public schemas now model those
fields, composite progress, and the optional active segment with backward-safe
legacy defaults.

## RED: composite cache ownership and cancellation

The durable store boundary must protect every cached child artifact while its
top-level document remains non-terminal. Once that parent becomes terminal,
cache eviction must clear the child reference just as it does for a legacy
clip. Parent cancellation must also settle Ready, Synthesizing, and Queued
children so no orphan work remains claimable or indefinitely visible.

The focused command exited 1 with both tests failing:

```console
uv run pytest \
  tests/test_store.py::test_composite_audio_is_protected_until_its_parent_is_terminal \
  tests/test_store.py::test_cancelling_composite_parent_settles_every_child -q
```

The non-terminal child path was absent from protection; terminal eviction
forgot zero references and left the child path intact. The cancelled parent
left its three children Ready, Synthesizing, and Queued instead of settling all
three as Cancelled.

## GREEN: composite cache ownership and cancellation

Protection now unions legacy parent artifacts with child artifacts whose owner
is non-terminal. Eviction clears either kind of terminal reference and reports
the combined row count. A parent terminal transition atomically cancels every
non-terminal child while preserving already terminal child outcomes. Both
focused contracts and the complete store suite are green.

## RED: failure after first-segment readiness

This bug regression runs a one-worker pool over a document whose first child
succeeds and whose second child deterministically fails, followed by an
ordinary clip. Because first-child publication intentionally makes the parent
Ready, the later failure must still move that parent to Failed, settle sibling
work, and leave the worker alive to synthesize the following clip.

The focused test exited 1 against the unfixed state transition. The failed
child and cancelled sibling were recorded, but the pool task crashed on the
illegal Ready-to-Failed parent transition. The parent remained Ready without
an error and the following clip remained Queued.

## GREEN: failure after first-segment readiness

Ready parents may now enter Failed, matching the existing synthesis and
playback failure paths. The regression observes a Failed parent with the
segment error, Cancelled and Failed children, a Ready following clip, and a
still-running synthesis pool. The complete synthesis suite is green.

## RED: composite history replay

The public requeue boundary must create a fresh parent hearing while preserving
the original Markdown, profile, and exact spoken child plan. When every source
child artifact is still cached, the replay must point at those same artifacts
and report its composite shape instead of re-synthesizing the raw Markdown as
one legacy clip.

The focused end-to-end socket test exited 1 against the legacy parent-only
replay path. The fresh parent correctly preserved the original text, profile,
and `replay_of`, but its child list was empty and both `composite` and
`segment_count` were absent from the response.

## GREEN: composite history replay

Replay now clones persisted child text rather than re-parsing or flattening the
original parent. A complete cached source plan is republished synchronously
under the fresh parent, preserving each path and duration; an incomplete cache
falls back to ordinary child synthesis. The response reports the same
composite shape as submission. The focused socket contract and complete IPC
suite are green.

## RED: YAML front matter is not narration

The actual SalesOS Markdown begins with static-site YAML front matter. The
document admission boundary must treat that delimited header as metadata and
begin its spoken projection at the body heading; keys such as `date`,
`visibility`, and `scope` must never become narration.

The focused regression exited 1 against the AST-only Markdown path after the
real document plan exposed its opening as `title: ... date: ...`. It returned
the metadata as an extra first segment before the otherwise-correct body
segment.

## GREEN: YAML front matter is not narration

Admission now recognizes one leading `---` YAML fence (including the standard
`...` closing form), removes it as metadata, and sends only the remaining body
through the Markdown AST. An unterminated or non-leading thematic break remains
ordinary Markdown. The focused regression and complete segmentation suite are
green.

## Final verification

The complete repository gates passed on the final implementation tree:

```console
uv run ruff check
# All checks passed!

uv run ruff format --check
# 84 files already formatted

uv run mypy
# Success: no issues found in 57 source files

uv run pytest
# 194 passed in 4.19s

cd clients/menubar
python3 ../../scripts/run_with_deadline.py 60 swift test
# 13 tests, 0 failures

swift build
# Build complete

cd ../..
uv build
# source distribution and wheel built successfully
```

The production document requested for playback was also projected through the
final admission code without synthesizing it again. Its exact 44,267-character
source became 49 child clips and 5,605 spoken words; the largest clip was 192
words. The first clip begins `SalesOS recent development history.` rather than
the YAML metadata that preceded the body.

## RED: CLI playback-rate parity

The menu and agent-facing CLI must exercise the same numeric settings contract.
The CLI regression sends `settings --set playback_rate=1.5` through the real
socket adapter and expects the persisted 1.5 response. It exited 1 against the
generic string-valued settings parser: the command returned daemon-error exit
code 1 with no settings payload instead of success and 1.5.

## GREEN: CLI playback-rate parity

The CLI now coerces both voice-generation `speed` and `playback_rate` values to
numbers before encoding NDJSON. The focused socket regression returns exit 0,
reports 1.5, and leaves validation of the discrete choice set at the daemon
boundary. The complete CLI suite is green.

## Installed caption-panel acceptance

The signed app installed at `~/Applications/AI-TTS.app` was run
against a private Unix-socket fixture that reported one active segment. The
fixture performed no synthesis and emitted no audio. Captions were enabled from
their originally absent preference only for the run.

macOS reported exactly one on-screen window owned by the isolated AI-TTS
process: a 760 by 132 point, fully opaque layer-3 panel positioned at the bottom
center of the active display. A window-only capture showed the exact fixture
text, `Caption acceptance. No audio is playing.`, centered inside the expected
black rounded panel. The user directly confirmed seeing the captions. The
frontmost application identifier was unchanged throughout, proving this
fixture did not repeat the earlier focus-stealing TextEdit interaction.

The fixture process was then terminated, the previously absent caption
preference was restored to absent/off, and the normal installed app was
relaunched hidden against the real daemon. The real daemon remained accepting,
unheld, and idle.

Two additional assertions close the ordinary-speech and preference boundaries.
A deliberate daemon mutant removed the virtual one-part `active_segment` for a
literal, non-composite agent submission; the focused Python test failed with
`active_segment: None`. A deliberate menu-state mutant made the caption setter
a no-op; the focused Swift test failed three assertions covering observable
state, persisted preference, and the then-current 0.5-second caption refresh
cadence. That cadence was later superseded by the event-driven behavior below.
After both mutants were removed, these commands passed:

```console
.venv/bin/pytest -q \
  tests/test_ipc.py::test_status_exposes_literal_agent_speech_as_one_caption_segment
# 1 passed

python3 scripts/run_with_deadline.py 60 swift test \
  --package-path clients/menubar \
  --filter WireProtocolTests.testCaptionPreferencePersistsWithoutControllingWatchdogCadence
# Executed 1 test, with 0 failures
```

## RED/GREEN: caption toggle does not control polling

A live user check exposed no visible caption despite the setting appearing
enabled. The installed daemon and menu app were healthy, the long-lived event
socket was connected, and the daemon had played the one-segment test clip. The
caption preference was false by the time it was inspected, so that observation
does not establish its value during playback and is not claimed as the root
cause.

The architecture issue discovered alongside it was reproducible: enabling
captions changed the background snapshot cadence from the five-second liveness
watchdog to a 0.5-second poll. The existing medium Swift preference contract
was changed to require the watchdog cadence to remain five seconds. Against the
unfixed implementation, the focused run reached the assertion and failed with
`0.5` not equal to `5.0`.

The toggle at this historical checkpoint updated memory and `UserDefaults`
immediately, performed one snapshot refresh only when being enabled, and
relied on the existing daemon event subscription for subsequent active-segment
changes. The fixed cadence kept the five-second refresh solely as a liveness
watchdog. The later shared-preference feature in
[`2026-09-05-mcp-caption-settings.md`](2026-09-05-mcp-caption-settings.md)
makes the daemon authoritative and gives MCP typed read/write access. Live
visual acceptance of the originally reported symptom remains pending there.
