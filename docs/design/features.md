# Feature breakdown

Status: **the v0.1.0 feature set and native OS adapters are implemented**.
Installed Services dispatch, the caption overlay, and App Intent indexing have
direct system evidence; the remaining native work is the representative host,
live Accessibility, and real Shortcuts invocation matrix. This document
preserves the provenance of the original requirements. Later product decisions
supersede the initial proposal labels where noted below.

The post-implementation queue review closed the largest UI question: the daemon keeps distinct synthesis and playback machinery, but the menu-bar app presents one Queue in actual playback order. The current clip is pinned above Queue and History; Queue rows expose processing state, urgency, removal, clearing, and drag reordering. History is newest-first and supports removal, clearing, and re-queueing with a fresh Normal or Urgent choice.

## How to read this

Every feature below carries two labels.

**Where it came from**, which is the important one:

| Label | Meaning |
|---|---|
| **[STATED]** | James asked for it. His words are quoted at the feature or in [Source material](#source-material). |
| **[INFERRED]** | Follows from something he said, but he did not say this part. The reasoning is given so you can reject the inference and not just the feature. |
| **[PROPOSED]** | Ours. He never mentioned it. **Cut these freely** — see [Everything we are proposing, in one list](#everything-we-are-proposing-in-one-list) to cut them in a single pass. |

**Priority**: **MUST** (v1 is not the described product without it) · **SHOULD** (v1 works without it, and will annoy) · **COULD** (later, or never).

A **[STATED]** item can still be a **COULD** — he described a product, not a release plan, and sequencing is ours to propose.

Features are grouped by area rather than by label, because a reader wants everything about the playback queue in one place. The labels do the separating.

## Source material

James, describing the product:

> a lightweight application where you send THE application your text and it has an internal queue of things to say. It will take your input text, put it on THE queue, and then process THE queue by generating THE audio for it and having that audio cached and ready for playback. Separately, there should be a playback queue, and I should have a user interface in my macOS menu bar where I can pause or play THE current audio and view upcoming things that you had to say. I can view THE queue. In other words, I want to be able to view THE input queue, and I want to be able to view THE playback queue, and I want to be able to pause, skip, or rewind. I want to have a history of all THE things you've told me. It should all be there. I want a menu tray icon that when I click on it opens up some sort of UI where I can view those modes… THE BM Daniels setting could be something that is configurable in that application itself.

The capitalised "THE" is a dictation artifact and carries no emphasis.

"BM Daniels" is the voice identifier `bm_daniel`. Treated throughout as *the currently selected voice*, not as a hardcoded default.

Later direct requirements added document-sized queue entries with an internal
queue, structure-aware chunking, one voice for the whole document, Markdown
syntax-tree projection, live playback rates of 0.5×, 0.75×, 1×, 1.5×, 2×, and
3×, and on-screen subtitles. Those requirements supersede the initial
proposal labels on 2.9 and 4.7 and add 2.10, 2.11, and 6.13 below.

A later request asked for deep macOS integration: read highlighted text from a
right-click action or the menu-bar item, and read selected files from Finder.
The accepted design adds the native entry points in §9. It chooses macOS
Services as the primary, permission-free path and treats Accessibility as an
explicit later fallback rather than a continuous selection detector.

### The incident, which is also a requirement

Two utterances played simultaneously:

> All I heard was a jumble of BM Daniel just speaking two things at once, and it was really kind of obnoxious.

Separately, and in the same session, the current setup produced **silence while exiting 0** in three distinct ways, plus a fourth shortly after.

These are not anecdotes. **Serialized playback** and **an exit code that reflects whether audio actually played** are both requirements with direct evidence behind them, and both are called out where they belong below.

### One property of the content, which is ours to raise

This tool speaks whatever its callers hand it, and in practice that includes **material its user is obliged to keep confidential** — personal names and internal identifiers among them.

He did not say this — it is an observation about the material, not an instruction — but it constrains two areas that would otherwise have easy answers: **where history is stored** and **whether synthesis may ever leave the machine**. Both are marked **[INFERRED]** and their original review questions are preserved in [Questions resolved for v0.1.0](#questions-resolved-for-v010).

Stated at this level on purpose. **This repository is public**, so the design constraint belongs here and the specifics of what has passed through the tool do not.

---

## 1. Submission

How text gets into the system.

| # | Feature | Label | Priority |
|---|---|---|---|
| 1.1 | Accept text from a caller and place it on the input queue | **[STATED]** | **MUST** |
| 1.2 | Return control to the caller immediately, without waiting for synthesis or playback | **[INFERRED]** | **MUST** |
| 1.3 | Accept a submission while the app is already speaking, without disturbing what is playing | **[INFERRED]** | **MUST** |
| 1.4 | Reject a submission that cannot be queued, distinguishably from accepting it | **[INFERRED]** | **MUST** |
| 1.5 | Caller-supplied label or tag on an utterance, for display in the queue views | **[PROPOSED]** | **COULD** |
| 1.6 | Priority or "say this next" submission that jumps the queue | **[PROPOSED]** | **COULD** |

**1.1** is *"you send THE application your text and it has an internal queue of things to say"*.

**1.2** is the point of a queue. If submitting blocked until the audio finished, the queue would be an implementation detail rather than a feature, and *"put it on THE queue"* would not describe anything. He never says "asynchronous", so the label is [INFERRED], but rejecting this inference would mean rejecting the queue.

**1.3** is the direct lesson of the jumble. Note that it is a *submission* requirement as well as a playback one: submitting must be able to happen mid-utterance, and must not cause a second stream to start. See §3.1.

**1.4** exists because of the silent exit-0 failures. A caller that cannot tell acceptance from rejection has no way to notice the system has stopped working — which is exactly what happened, four times. See §8.

**1.6 was later approved and implemented.** Urgent means "play next after the current clip"; it never interrupts current playback. Queue rows make urgency visible.

## 2. Synthesis work queue

The internal input queue and the work of turning text into audio. It is not a separate user-facing tab: its states appear inline in the unified Queue.

| # | Feature | Label | Priority |
|---|---|---|---|
| 2.1 | An input queue, distinct from the playback queue | **[STATED]** | **MUST** |
| 2.2 | Process the queue by generating audio for each item | **[STATED]** | **MUST** |
| 2.3 | Cache the generated audio so it is ready before playback needs it | **[STATED]** | **MUST** |
| 2.4 | Synthesise ahead of playback, so the next item is ready when the current one ends | **[INFERRED]** | **MUST** |
| 2.5 | Survive a synthesis failure on one item without stalling the queue | **[INFERRED]** | **MUST** |
| 2.6 | Show a failed item as failed in the UI rather than dropping it silently | **[INFERRED]** | **SHOULD** |
| 2.7 | Bound the cache — by size, age, or count | **[PROPOSED]** | **SHOULD** |
| 2.8 | Reuse cached audio when the identical text is submitted again | **[PROPOSED]** | **COULD** |
| 2.9 | Split one long document into a parent-owned internal clip queue so playback can begin before the whole document is synthesised while later top-level items remain blocked | **[STATED]** | **MUST** |
| 2.10 | Parse Markdown structurally and speak its content without raw syntax | **[STATED]** | **MUST** |
| 2.11 | Bind every internal document clip to the parent's single immutable voice and voice-generation speed | **[STATED]** | **MUST** |
| 2.12 | Keep content interpretation separate from length segmentation: plain speech stays literal and only Markdown-marked input gets AST projection | **[STATED]** | **MUST** |

**2.1–2.3** are close to verbatim: *"process THE queue by generating THE audio for it and having that audio cached and ready for playback"*, and *"Separately, there should be a playback queue"*.

**2.3 and 2.4 are the same sentence read twice.** *"cached and ready for playback"* is the only phrase in his description that implies work happens **ahead of** need. It is the difference between a queue that synthesises on demand — with a gap of silence before every utterance — and one that stays ahead. We read it as the latter. **If that is wrong, most of this section changes.**

**2.5** is unstated and load-bearing. A queue that stops on one bad item is a queue that stops. Given that four failures tonight were silent, the failure mode to design against is *the system quietly ceasing to speak*.

**2.7** is ours, and the confidentiality point applies: cached audio of confidential text accumulating without bound on disk is a real consideration and not merely a housekeeping one. See §5 and [Questions resolved for v0.1.0](#questions-resolved-for-v010).

**2.9–2.12 were later requested and implemented.** The exact submitted input
remains the one queue/history record. Its private child queue prefers structural
and paragraph boundaries, then sentences, with a bounded word fallback. The
first child makes the parent playable; the parent still occupies one place in
the serialized plan until every child is terminal. Explicit Markdown is
projected through an AST rather than stripped with regular expressions; plain
text bypasses that projection. Children resolve voice and generation speed only
through their parent.

## 3. Unified playback plan

What is playing and what comes next. Internally, readiness still crosses from synthesis to playback; externally, each upcoming clip appears exactly once.

| # | Feature | Label | Priority |
|---|---|---|---|
| 3.1 | **Exactly one utterance audible at a time** | **[STATED]** | **MUST** |
| 3.2 | A playback queue, distinct from the input queue | **[STATED]** | **MUST** |
| 3.3 | Play items in order, advancing automatically when one finishes | **[INFERRED]** | **MUST** |
| 3.4 | An item enters the playback queue when its audio is ready | **[INFERRED]** | **MUST** |
| 3.5 | Preserve submission order in playback | **[INFERRED]** | **SHOULD** |
| 3.6 | Continue through the queue after a playback device error | **[INFERRED]** | **SHOULD** |
| 3.7 | Drain or clear the queue on demand | **[PROPOSED]** | **SHOULD** |
| 3.8 | Reorder the queue by dragging in the UI | **[PROPOSED]** | **COULD** |

**3.1 is the highest-confidence requirement in this document** and the only one with a recorded complaint attached. *"a jumble of BM Daniel just speaking two things at once, and it was really kind of obnoxious."* Serialization is the feature; the queue is the mechanism.

**3.5** is separated from 3.3 deliberately. If synthesis runs concurrently, a short item submitted second can finish synthesising first, and *ready order* stops matching *submission order*. **We assume he wants submission order**, but he never says so, and if the ordering ever visibly differs he will notice. Cheap to get right at design time and expensive later.

**3.4** is where the two queues meet, and it is the part of the architecture his description implies without spelling out.

**3.7 and 3.8 were later approved and implemented.** Clearing Queue cancels every upcoming state while the current clip keeps playing. Drag reordering operates on the complete pending plan so no synthesis state can disappear or duplicate.

## 4. Transport controls

| # | Feature | Label | Priority |
|---|---|---|---|
| 4.1 | Pause all playback at any time; incoming speech continues to queue | **[STATED]** | **MUST** |
| 4.2 | Skip | **[STATED]** | **MUST** |
| 4.3 | Rewind | **[STATED]** | **MUST** |
| 4.4 | Resume from the paused position, not from the start | **[INFERRED]** | **MUST** |
| 4.5 | Global keyboard shortcuts for pause / skip | **[PROPOSED]** | **COULD** |
| 4.6 | Volume control in-app | **[PROPOSED]** | **COULD** |
| 4.7 | Change playback speed dynamically during playback using 0.5×, 0.75×, 1×, 1.5×, 2×, or 3× | **[STATED]** | **MUST** |

**4.1 was clarified after the unified Queue shipped.** Pause is a global,
durable playback hold, not merely a control for the current clip. It remains
available while idle and with an empty Queue. New submissions are accepted and
may synthesize while held, but no audio starts until the user explicitly
resumes. **4.2–4.3** retain the original stated meanings: *"pause, skip, or
rewind"*.

**⚠ 4.2 and 4.3 are the least specified features in the document, and their meanings are not obvious.**

- **Skip** could mean: abandon the current utterance and start the next one, or drop the next item without playing it. The first is the common reading. He does not say.
- **Rewind** is ambiguous in two directions at once. **Within the current utterance** — go back some number of seconds, and he does not say how many — or **across the queue**, meaning replay the previous utterance, which is really a history operation. His pairing of it with "pause, skip" suggests a transport control; the existence of a full history (§5) makes the second reading plausible too.

Both are preserved in [Questions resolved for v0.1.0](#questions-resolved-for-v010). The implementation choices remain explicit because these are the two controls the user will press most often and a semantic change must be deliberate.

**4.4** is unstated and would be an obvious bug if missed.

**4.6** is marked **COULD** because macOS already has a system volume control and a per-app mixer. Building a second one is duplicated surface unless he specifically wants it.

**4.7 was later requested and implemented.** It is a persisted playback
setting, separate from voice-generation speed, and applies to an already active
audio source without restarting it.

## 5. History

| # | Feature | Label | Priority |
|---|---|---|---|
| 5.1 | A history of everything spoken | **[STATED]** | **MUST** |
| 5.2 | Complete — *"It should all be there"* | **[STATED]** | **MUST** |
| 5.3 | Persist across application restarts | **[INFERRED]** | **MUST** |
| 5.4 | Record when each item was spoken | **[INFERRED]** | **SHOULD** |
| 5.5 | Record items that were skipped or that failed, distinctly from those spoken in full | **[INFERRED]** | **SHOULD** |
| 5.6 | Replay an item from history | **[PROPOSED]** | **SHOULD** |
| 5.7 | Search history | **[PROPOSED]** | **SHOULD** |
| 5.8 | Copy an item's text to the clipboard | **[PROPOSED]** | **COULD** |
| 5.9 | Export history | **[PROPOSED]** | **COULD** |
| 5.10 | Retention limit or a way to purge | **[INFERRED]** | **SHOULD** |
| 5.11 | Remove one history record or clear all history | **[STATED]** | **MUST** |
| 5.12 | Choose Normal or Urgent when re-queueing history | **[STATED]** | **MUST** |

**5.2 is a strong claim and we have taken it literally.** *"I want to have a history of all THE things you've told me. It should all be there."* We read "all" as *complete, not a recent-items list*, and 5.3 follows: a history that empties on restart is not "all".

**5.6 and 5.7 are ours, and they are the two that make history useful rather than merely present.** He asked for the record; he did not ask to be able to do anything with it. They are marked **SHOULD** rather than **MUST** on that basis — but a complete, permanent, unsearchable log is a strange artifact, and this is the place where his description most likely means more than it says. Worth asking.

**5.11 and 5.12 are later direct requirements.** Re-queue creates a new hearing while retaining the original record and its priority as provenance. Normal appends; Urgent becomes next after the current clip. Deleting history records is intentionally separate from cache eviction.

**5.10 is where the confidentiality point bites.** A complete permanent history of this text is a plaintext record of confidential material sitting in a file on disk. That may be entirely fine — it is his machine — but it should be a decision he makes rather than a consequence of the word "all". The adopted storage, permission, and retention decisions are linked from [Questions resolved for v0.1.0](#questions-resolved-for-v010).

## 6. Menu-bar UI

| # | Feature | Label | Priority |
|---|---|---|---|
| 6.1 | A macOS menu-bar (status-item) icon | **[STATED]** | **MUST** |
| 6.2 | Clicking it opens a UI | **[STATED]** | **MUST** |
| 6.3 | Show input-side processing state in the unified Queue | **[STATED]** | **MUST** |
| 6.4 | Show the exact playback order in that same Queue | **[STATED]** | **MUST** |
| 6.5 | A view of history | **[STATED]** | **MUST** |
| 6.6 | Transport controls reachable from that UI | **[STATED]** | **MUST** |
| 6.7 | See what is currently playing | **[STATED]** | **MUST** |
| 6.8 | See upcoming items — *"view upcoming things that you had to say"* | **[STATED]** | **MUST** |
| 6.9 | Live updates as the queues change, without reopening | **[INFERRED]** | **MUST** |
| 6.10 | Icon indicates state at a glance — idle, speaking, paused | **[PROPOSED]** | **SHOULD** |
| 6.11 | Item count or badge on the icon | **[PROPOSED]** | **COULD** |
| 6.12 | Transport controls in the icon's right-click menu, without opening the panel | **[PROPOSED]** | **COULD** |
| 6.13 | Opt-in phrase-sized on-screen subtitles with source provenance for the segment currently being spoken, never the whole section at once | **[STATED]** | **SHOULD** |
| 6.14 | Enqueue a local plain-text, Markdown, or text-bearing PDF file from the UI | **[STATED]** | **MUST** |

**6.3–6.5 were clarified after use.** Separate Up Next and Queue tabs exposed two internal stages as nearly identical user concepts, and ready voice previews could appear in one while the other looked empty. The approved surface therefore has two tabs, Queue and History, with current playback pinned above both.

**How the three views are presented — tabs, a segmented control, a sidebar, one scrolling panel — is not specified.** *"some sort of UI"* is as far as he goes. That is a mockup question, not a feature question, and mockups are being drawn separately.

**6.9** is unstated and would be immediately obvious as a defect: a queue view that shows a stale queue is worse than no queue view, because it is confidently wrong.

**6.10** is ours and cheap. It is also the fastest way to notice the failure mode that actually occurred — *silence with everything apparently fine*. An icon that shows "idle" when you expected "speaking" surfaces in one glance what four exit-0 successes concealed.

**6.13 was later requested and implemented.** The overlay is opt-in,
non-activating, click-through, and available across Spaces. It shows exact
segment text and document-part progress. It does not claim word timestamps or
karaoke highlighting.

**6.14 was later requested and implemented.** Queue's file picker reads one
explicitly selected file inside the menu app and submits its text through the
same confidential admission path as every other client. UTF-8 text and
Markdown retain exact source syntax; `.md` and `.markdown` select Markdown
projection, while other text and extracted PDF pages select literal plain text.
PDF support uses the native text layer only; locked and image-only documents
fail locally with guidance instead of becoming empty queue entries.
Text and Markdown source is bounded at 512 KiB. PDF source is bounded at 32 MiB
and 500 pages, and page-ordered extraction stops once its UTF-8 text plus page
separators would exceed 512 KiB. These limits admit document-scale speech while
bounding work before the daemon's separate 1 MiB serialized-request limit.

## 7. Configuration

| # | Feature | Label | Priority |
|---|---|---|---|
| 7.1 | Voice (`bm_daniel`) selectable inside the app | **[STATED]** | **MUST** |
| 7.2 | Settings persist across restarts | **[INFERRED]** | **MUST** |
| 7.3 | Settings reachable from the menu-bar UI | **[INFERRED]** | **SHOULD** |
| 7.4 | Voice change applies to items not yet synthesised | **[INFERRED]** | **SHOULD** |
| 7.5 | Independent pitch control | **[PROPOSED]** | **COULD** |
| 7.6 | Output device selection | **[PROPOSED]** | **COULD** |
| 7.7 | Launch at login | **[PROPOSED]** | **COULD** |
| 7.8 | Per-caller voice, so different agents sound different | **[PROPOSED]** | **COULD** |

**7.1** is *"THE BM Daniels setting could be something that is configurable in that application itself"*. Note **his own "could"** — this is the one feature he explicitly softened, and we have kept it **MUST** anyway only because "configurable in the application" is trivially cheap once a settings surface exists. **If a settings surface does not exist in v1, this drops to SHOULD without argument.**

**7.4** matters because of the cache: if audio is synthesised ahead, a voice change mid-queue leaves already-rendered items in the old voice. Re-synthesising them is a choice, not an obvious answer. The immutable-at-admission decision is linked from [Questions resolved for v0.1.0](#questions-resolved-for-v010).

**7.8** is ours and speculative, but it is the kind of thing that is nearly free if the submission API carries a caller identifier from the start (§1.5, §8.2) and awkward to retrofit.

## 8. Agent-facing client interface

The surface an agent uses. He describes this only as *"you send THE application your text"* — the entire area is otherwise inferred or proposed, and it is where tonight's failures live.

| # | Feature | Label | Priority |
|---|---|---|---|
| 8.1 | A documented way for an agent to submit text | **[STATED]** | **MUST** |
| 8.2 | **Success means the utterance was accepted onto the queue, and the exit status says so truthfully** | **[INFERRED]** | **MUST** |
| 8.3 | A distinguishable failure when the app is not running, unreachable, or refusing work | **[INFERRED]** | **MUST** |
| 8.4 | Query current state — what is playing, what is queued | **[PROPOSED]** | **SHOULD** |
| 8.5 | Block until a specific utterance has finished, for callers that need it | **[PROPOSED]** | **SHOULD** |
| 8.6 | Transport control from the client, not only the UI | **[PROPOSED]** | **COULD** |
| 8.7 | Stable utterance identifier returned on submission | **[PROPOSED]** | **SHOULD** |
| 8.8 | Report admission separately from playback hold; paused speakers continue submitting and are spooled | **[STATED]** | **MUST** |
| 8.9 | Default agent speech to literal plain text and require an explicit choice to interpret it as Markdown | **[STATED]** | **MUST** |
| 8.10 | Let agents read and change the same persisted caption preference as the menu UI | **[STATED]** | **MUST** |

**8.2 is the requirement that tonight's evidence most directly demands, and it is the one most likely to be skipped**, because it is not a feature anyone sees.

Four times in one session the current setup **produced no audio and reported success**. From the caller's side that is indistinguishable from working. The consequence is not a missing sound. It is that **nobody finds out**, and a caller who trusts the exit status will keep reporting that things were spoken when they were not.

**The honest contract is narrow, and narrow is the point.** Exit 0 should mean *this utterance was accepted onto the queue* — not *it was heard*, which the application cannot know, and not *it will be heard*, which it cannot promise. Anything the client cannot observe should not be encoded in its exit status. **8.5 and 8.7 exist for callers that genuinely need the stronger guarantee**, and they should have to ask for it explicitly.

**8.7** is unglamorous and enables 8.5, 5.6, and useful log correlation. Nearly free at design time.

**8.8 prevents an agent-side deadlock.** A speaker that sees the word “paused”
may politely refuse to submit, even though holding those submissions is the
entire purpose of global Pause. Machine status therefore says the service is
`accepting`, reports `playback_state` separately, and gives an explicit
`spooled_until_resume` disposition. Enqueue tools must not use playback state
as an admission precondition.

**8.9 prevents the document pipeline from silently changing agent speech.**
CLI and MCP submissions carry `plain_text` by default, so `#`, backticks, and
asterisks remain literal. A caller that is intentionally submitting Markdown
chooses `markdown`; length-based segmentation remains available in either
format.

**8.10 makes caption control observable instead of hopeful.** The daemon owns
one boolean preference. The menu pushes its toggle through the settings wire;
MCP exposes typed read and idempotent set tools; and `settings_changed` wakes
the menu app without increasing its liveness-poll cadence.

**6.13 separates synthesis chunks from reading-sized caption cues.** A document
section remains one active synthesized segment when that is best for the queue,
but the overlay projects it into punctuation-aware cues capped at 12 words and
84 characters. Clip position, duration, and the current playback rate advance
the cues locally. This avoids both whole-section walls of text and a false claim
of word-level alignment. The metadata row preserves the same exact source value
shown in History, adding only a trailing colon; a legacy item without source
provenance omits the label.

## 9. Native OS entry points

How selected text and files enter AI-TTS from other macOS applications. The
complete decision, current-state ledger, and delivery proof are in
[`os-integration.md`](os-integration.md).

| # | Feature | Label | Priority |
|---|---|---|---|
| 9.1 | Expose **Read Selection with AI-TTS** as a macOS Service for a nonempty text selection | **[STATED]** | **MUST** |
| 9.2 | Expose **Read File with AI-TTS** as a macOS Service for one selected supported file | **[STATED]** | **MUST** |
| 9.3 | Let the user assign the selected-text Service a keyboard shortcut through macOS | **[INFERRED]** | **SHOULD** |
| 9.4 | Admit selected text exactly once as confidential, Normal, literal `plain_text` | **[INFERRED]** | **MUST** |
| 9.5 | Route a selected file through the existing `DocumentEnqueueing` application port | **[INFERRED]** | **MUST** |
| 9.6 | Offer **Read Current Selection…** through Accessibility only after explicit invocation and only when compatibility evidence justifies it | **[STATED]** | **SHOULD** |
| 9.7 | Never poll another application's selection in the background or synthesize Command-C | **[INFERRED]** | **MUST** |
| 9.8 | Offer an explicit, non-mutating **Read Clipboard** fallback | **[PROPOSED]** | **COULD** |
| 9.9 | Expose speech and transport actions through App Intents after installed-bundle metadata is proved | **[PROPOSED]** | **COULD** |

**9.1 is the primary selection contract.** macOS supplies the selected string
to the Service when the user invokes it. The app acknowledges admission and
returns without waiting for synthesis or playback. The command is guaranteed
in the Services menu for a compatible host and may also appear in that host's
context menu; AI-TTS does not promise a top-level right-click row in every app.

**9.2 and 9.5 extend the file picker without forking it.** The Service accepts
exactly one UTF-8 text, Markdown, or text-bearing PDF file for its first
implementation. It calls the same `EnqueueDocument` use case as Queue's **Add
file…**, so extension-based Markdown selection, PDF limits, confidentiality,
Normal priority, nested segmentation, and voice consistency stay identical.
Multiple selected files fail before any are admitted; a later batch contract
can choose and test ordering explicitly.

**9.4 keeps selection interpretation explicit.** Highlighted characters do
not carry reliable Markdown provenance, so `#`, backticks, and asterisks remain
literal. A separately named future command may opt into Markdown; this command
never sniffs syntax.

**9.6 is deliberately second.** Accessibility can recover selections from
some hosts that do not cooperate with Services, but it requires broad user
trust and does not expose selected text uniformly. The menu action queries the
previously frontmost process once, after the user asks; it never watches focus
or selection changes. If no selection is available, it reports that boundary
and points to the Service or explicit clipboard action.

**9.7 is a privacy and state-integrity requirement.** Synthetic copy depends on
fragile focus timing and mutates another application's behavior and the global
pasteboard. “Integrated” does not authorize invisible observation or state
changes.

**9.8 and 9.9 were later implemented.** Clipboard admission is one explicit,
read-only action through `SelectionEnqueueing`. Six App Intents expose literal
text, one document, Pause, Resume, Skip, and live playback rate through the
same application ports. The installed bundle is indexed by macOS; a real
Shortcuts invocation remains an acceptance step rather than an implementation
gap.

---

## Everything proposed in the initial design

Nothing below came from the original brief. Several items were later requested or approved explicitly; the notes above are authoritative for v0.1.0.

| # | Feature | Priority |
|---|---|---|
| 1.5 | Caller-supplied label on an utterance | COULD |
| 1.6 | Priority / say-next submission | COULD |
| 2.7 | Bounded audio cache | SHOULD |
| 2.8 | Reuse cached audio for identical text | COULD |
| 2.9 | Chunk long text for earlier playback | COULD |
| 3.7 | Drain / clear the queue | SHOULD |
| 3.8 | Reorder queue by dragging | COULD |
| 4.5 | Global keyboard shortcuts | COULD |
| 4.6 | In-app volume | COULD |
| 4.7 | Playback speed | COULD |
| 5.6 | Replay from history | SHOULD |
| 5.7 | Search history | SHOULD |
| 5.8 | Copy item text | COULD |
| 5.9 | Export history | COULD |
| 6.10 | Icon shows state at a glance | SHOULD |
| 6.11 | Count badge on icon | COULD |
| 6.12 | Transport in the right-click menu | COULD |
| 7.5 | Independent pitch control | COULD |
| 7.6 | Output device selection | COULD |
| 7.7 | Launch at login | COULD |
| 7.8 | Per-caller voice | COULD |
| 8.4 | Query current state | SHOULD |
| 8.5 | Block until spoken | SHOULD |
| 8.6 | Transport from the client | COULD |
| 8.7 | Utterance identifier | SHOULD |

Twenty-five proposals. **Eight are SHOULD** — 2.7, 3.7, 5.6, 5.7, 6.10, 8.4, 8.5, 8.7 — and those are the ones we would argue for. The other seventeen are **COULD** and we would not.

## Questions resolved for v0.1.0

These are the questions that made the original feature proposal reviewable.
They are retained as decision provenance, not as current blockers. The adopted
answers are recorded together in
[`README.md` § How v0.1.0 answered these](README.md#how-v010-answered-these).

**Transport semantics.**

1. **What does *skip* do?** Abandon the current utterance and move to the next, or drop the next item unheard?
2. **What does *rewind* do?** Go back N seconds within the current utterance — and if so, **what is N?** — or replay the previous utterance? Both readings fit what you said, and these are the controls you will press most often.

**History.**

3. **"It should all be there" — forever?** Is there any retention limit, or is a permanent complete record the point?
4. **Should history be searchable and replayable**, or is it a record you read? We think searchable (5.6, 5.7) and have marked both SHOULD, but you did not ask for either.
5. **This text is client-confidential** — it is material you are obliged not to disclose. **Where should history live, and does it need protection beyond ordinary file permissions?** Same question for cached audio, which is the same content in another form.

**Synthesis.**

6. **Must synthesis stay entirely on this machine?** We have assumed yes and designed nothing that sends text off the box. **If any cloud voice is ever acceptable, say so explicitly** — it changes the architecture, and given the content it should be a decision rather than a default.
7. **Does "cached and ready" mean synthesise ahead of playback?** We read it that way (2.4). If you meant only "don't stream it while playing", the queue design simplifies considerably.
8. **On a voice change, what happens to items already rendered in the old voice?** Re-synthesise, or let them play as they are?

**Ordering and scope.**

9. **Is playback order strictly submission order?** If synthesis is concurrent, a short item can be ready first. We assume submission order (3.5).
10. **The input and playback queues remain distinct internally but are one user-facing Queue with per-item state.**
11. **What is in v1?** Everything marked MUST here is roughly *the product as you described it*. That is a large v1. **We can propose a smaller first cut if you would rather see something working sooner** — say the word and that is a separate document.

## What is deliberately not in this document

Architecture, engine choice, storage format, process model, and UI layout. Those are being written separately. This document is only *what the thing does*, and it stops at the boundary where *how* begins.
