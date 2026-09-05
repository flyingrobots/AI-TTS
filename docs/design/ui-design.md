# AI-TTS — menu-bar UI design

Status: **the menu-bar surface and native OS adapters are approved and
implemented**. Installed Services dispatch, the caption overlay, and App Intent
indexing have direct system evidence. Representative host, live Accessibility,
and real Shortcuts invocation acceptance remain open.

The current design was approved after exercising the original five-tab app.
That use exposed a conceptual leak: **Up Next** and **Queue** were two views of
nearly the same clips, divided by an internal synthesis boundary. A voice
preview could therefore be visibly scheduled in Up Next while Queue said it was
empty. The daemon still needs separate synthesis and playback machinery; the
person listening does not need separate tabs for it.

## Approved reference mockups

The implemented surface follows these 368 × 500 SVG proposals:

- [Unified Queue](mockups/unified-queue-proposal.svg)
- [Unified History](mockups/unified-history-proposal.svg)
- [History re-queue menu](mockups/unified-history-requeue-menu-proposal.svg)

They carry light and dark themes in the same file. The earlier Now Playing,
Up Next, synthesis Queue, and History SVGs remain in mockups/ as design
history; they are superseded where they conflict with the unified proposals.

## The user-facing model

There is one serialized speaking plan:

1. The current clip is pinned at the top.
2. Queue contains every clip that will play next, in playback order.
3. History contains terminal clips, newest first.

Every upcoming clip appears exactly once. Readiness is a property of a Queue
row, not a reason to move the clip into another view:

- Ready — synthesized and waiting for its turn.
- Synthesizing… — audio generation is in progress.
- Queued — waiting for a synthesis worker.

The plan is serialized, but not globally FIFO. Normal submissions retain
acceptance order. Urgent submissions and explicit drag reordering can change
the pending order. None of those operations interrupts the clip already
playing.

## Popover shell

The popover is 368 × 500 points. Its stable vertical structure is:

- app identity, daemon status, a global Pause / Resume control, and a Settings gear;
- the current-playback card;
- a two-way Queue / History segmented control;
- the selected list;
- model, voice, or last-error status.

Settings is a sheet reached from the gear. It is not a third playback tab.
This keeps navigation about playback while retaining immediate voice previews
and speed changes.

## Native OS entry points

The primary selection interaction happens in the source application, not in
the AI-TTS popover. For a compatible text selection, the user invokes
**Services → Read Selection with AI-TTS** or an assigned Service keyboard
shortcut. For one supported Finder selection, they invoke **Services → Read
File with AI-TTS**. A host may surface either command in its contextual menu,
but the UI does not promise a top-level right-click item because the host owns
that menu.

The selected-text Service has no confirmation step. It enqueues the exact
nonempty selection as confidential, Normal, literal text, returns after daemon
acknowledgement, and lets the existing Queue provide visible feedback. The file
Service likewise delegates to the same document admission used by **Read
File…**. Errors are local and actionable; unsupported or multiple files are
rejected before anything is enqueued.

Queue's **Read…** menu includes **Read Current Selection…**. The
ellipsis is intentional: its first use may need the macOS Accessibility prompt,
and any use may report that the previous application does not expose selected
text. Opening the popover must preserve the previously frontmost application
before the popover makes itself key. Invoking the action performs one read of
that application; it never enables selection polling.

If Accessibility cannot obtain the selection, the error identifies the
boundary and offers two next actions: use the macOS Service, or copy explicitly
and choose **Read Clipboard**. **Read
Clipboard** reads but never replaces the pasteboard. Neither fallback silently
synthesizes Command-C.

These entry points are specified in
[`os-integration.md`](os-integration.md). The menu actions are implemented;
product copy must keep live Accessibility/host compatibility distinct from the
contract-tested behavior until installed-system acceptance passes.

## Current playback

The global **Pause** control is always visible, including while idle and while
Queue is empty. It is a playback gate rather than an operation on one row. Once
engaged, it becomes **Resume**; incoming clips continue to enter Queue and may
synthesize, but none can start playing. The hold survives a daemon restart so
silence remains the safe default during a meeting.

The current card never moves when Queue and History switch. It shows the clip's
text, voice, elapsed and total time, progress, and restart/skip controls. A
composite document remains one card and one Queue row while exposing its current
part and total part count.
When nothing is playing, the same card becomes a compact idle explanation
instead of disappearing.

Pause and resume preserve position across internal document clips. Restart
starts the current document again at its first cached clip only
when the global hold is not engaged. Skip abandons the current hearing and
records the reached position in History; while held, the next Queue item stays
ready rather than beginning. Transport never starts a second audio stream.

The current card also exposes a playback-rate dropdown with exactly 0.5×,
0.75×, 1×, 1.5×, 2×, and 3×. It changes the active source immediately and is
separate from voice-generation speed, which affects future synthesis.

## On-screen captions

Captions are off by default and persist as a local UI preference. The caption
bubble beside playback rate toggles a borderless, non-activating panel near the
bottom center of the active display. The panel floats across Spaces, ignores
mouse events, and disappears whenever captions are disabled, the daemon is
unreachable, or no clip is active.

The overlay contains the daemon's exact active spoken segment and, for a
document, `PART n OF m`. It is segment-level transcription: it deliberately
does not fabricate word timing or karaoke highlighting. The menu app refreshes
position while captions are enabled and advances the overlay immediately when
the daemon reports a child-state transition.

## Queue

Queue is the complete pending plan:

- **Read…** contains current-selection, clipboard, and file entry points;
- **Read File…** opens a single-selection picker for UTF-8 plain text,
  Markdown, or PDF;
- rows stay in the order they will be heard;
- a visible word pill carries Ready, Synthesizing…, or Queued;
- Urgent is a separate blue badge because scheduling intent and processing
  state are orthogonal;
- the grip reorders pending rows;
- the visible remove control cancels one row;
- **Clear queue…** asks for confirmation, then cancels every upcoming row,
  including work currently synthesizing.

The menu app—not the daemon—opens and reads the selected URL. Text and Markdown
retain their source exactly. `.md` and `.markdown` are marked for Markdown AST
projection; other supported text and the extractable PDF text layer are marked
literal plain text. A PDF contributes pages in order, separated by paragraph
breaks; the picker does not claim layout reconstruction or OCR. The resulting
text and format use the normal confidential submission boundary, so length
chunking, immutable voice selection, queue ordering, history, and transport
behavior do not fork into a file-specific path.

Clearing Queue never stops the current clip. “Stop talking” is Skip; “cancel
the backlog” is Clear Queue.

The daemon accepts a reorder only when the client supplies every current
pending identifier exactly once. This prevents a stale or partial drag payload
from silently dropping, duplicating, or hiding a clip.

## History

History is durable, searchable, and newest-first. Rows show completion time,
final state, source when present, and the original Urgent badge when
applicable. That priority is provenance: it records how the original hearing
was scheduled.

Each row has:

- **Re-queue**, whose primary action creates a Normal copy at the end of Queue;
- a chevron menu with:
  - **Normal — Add to end of Queue**
  - **Urgent — Play next after current**
- a visible remove control.

Re-queue creates a new utterance and leaves the historical row unchanged. The
fresh urgency selection applies only to the new copy. Cached audio is reused
when it still exists; otherwise synthesis runs again.

**Clear history…** confirms before deleting all terminal records. Removing one
record or clearing History does not cancel active work and does not implicitly
delete cached audio. Cache retention remains a separate storage concern.

## Settings and voice previews

Voice selection is a visible set of radio-style rows rather than a hidden
dropdown. Each voice has a preview control because a model identifier is not an
audible description. Preview creates an Urgent public clip, so it becomes next
after the current clip and is visible in Queue like every other submission.

Voice-generation speed is continuous from 0.5× to 2.0× and applies to future submissions.
On-screen captions can also be enabled or disabled here.
Settings take effect immediately; Done only dismisses the sheet.

## Tray state

The status item uses a monochrome template image so macOS supplies the correct
menu-bar tint. State precedence is:

    error > playing > paused > synthesizing > idle

Only playing and synthesizing animate. Motion therefore always means work is in
flight; paused and error remain visually stable.

## Empty and failure states

- Unreachable: the popover says the daemon is not running and shows the startup
  command.
- Empty Queue: explains that new clips will appear in playback order.
- Empty History: explains that finished clips appear newest-first.
- Empty search result: reports that no rows match without implying History is
  empty.
- Request error: the footer switches from green model health to the last daemon
  error.

## Deliberate boundaries for v0.1.0

The current implementation does not claim waveform scrubbing, word-synchronized
karaoke highlighting, mute-without-pause, output-device selection, cache
retention controls, history export, or a detachable History window. Text/file
Services, explicit Accessibility/clipboard admission, and App Intents are now
part of the implemented surface. Their compatibility claims remain bounded by
the installed evidence in [`os-integration.md`](os-integration.md): Services
dispatch and App Intent indexing are proved locally, while the representative
host, live Accessibility, and real Shortcuts invocation matrix remains open.
