# AI-TTS — menu-bar UI design

Status: **approved and implemented in v0.1.0**.

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

- app identity, daemon status, and a Settings gear;
- the current-playback card;
- a two-way Queue / History segmented control;
- the selected list;
- model, voice, or last-error status.

Settings is a sheet reached from the gear. It is not a third playback tab.
This keeps navigation about playback while retaining immediate voice previews
and speed changes.

## Current playback

The current card never moves when Queue and History switch. It shows the clip's
text, voice, elapsed and total time, progress, and restart/pause/skip controls.
When nothing is playing, the same card becomes a compact idle explanation
instead of disappearing.

Pause and resume preserve position. Restart starts the current clip again.
Skip abandons the current hearing, records the reached position in History, and
allows the next Queue item to begin. Transport never starts a second audio
stream.

## Queue

Queue is the complete pending plan:

- rows stay in the order they will be heard;
- a visible word pill carries Ready, Synthesizing…, or Queued;
- Urgent is a separate blue badge because scheduling intent and processing
  state are orthogonal;
- the grip reorders pending rows;
- the visible remove control cancels one row;
- **Clear queue…** asks for confirmation, then cancels every upcoming row,
  including work currently synthesizing.

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

Speed is continuous from 0.5× to 2.0× and applies to future submissions.
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

The current implementation does not claim waveform scrubbing, partial-text
karaoke highlighting, mute-without-pause, output-device selection, cache
retention controls, history export, or a detachable History window. Those were
ideas in the earlier mockups, not prerequisites of the approved unified
surface.
