# Architecture acceptance for the seven-prompt delivery

Status: Accepted by the user after reviewing the architecture report.  
Change-kind: deliberate behavior change to delivery acceptance criteria only;
no runtime, benchmark, or test behavior changes.

## Scope and authority

This decision resolves the two architecture-review choice blockers only. It
supersedes the corresponding proposed architecture and memory acceptance
criteria for this delivery. It does not declare all original requirements
satisfied. The historical local `PROMPTS.md`, original measured source, and
`benchmark-baseline/2026-09-30` reference remain unchanged.

The [architecture report](../reports/2026-09-30-architecture-review.md) retains
its measurements and their limits. Approval is a product/architecture decision,
not independent verification of repository or hardware results.

## Prompt 1: retain controller ownership

PlaybackController continues to own the device, interruption orchestration,
the live interruption stack, and final post-stop playhead capture. Store owns
durable lifecycle and atomic parent/child position updates. The existing
`suspend_playback` boundary is accepted; do not introduce `preempt_active` or
`resume_preempted` merely to reproduce the proposed method names.

A database transaction does not include the physical audio device. A future
Store API must still specify the observed playback occurrence, final child and
position, failure reconciliation, and recovery ownership.

Queue ranking currently also supplies recovery ancestry. This approval does
not establish correct restoration under every permitted operation history.
Explicit durable suspension history, with the live stack as its projection,
is a possible incremental improvement, not an approved wholesale rewrite.
Demonstrated lost work or incorrect restoration remains a correctness defect.

## Prompt 2: accept the measured configuration footprint

Approximately 180 MB is no longer a completion gate for this delivery and the
reviewed MLX configuration. Retain the measured approximately 994–1,005 MiB
adapter-process RSS baseline. This is not whole-application memory, an enforced
upper bound, the minimum achievable footprint, or achievement of the original
180 MB target. Short warm-input performance does not establish cold or long-input
latency, quality, or workday resource stability.

Investigate ownership and cache policy before model/runtime replacement.
Diagnostic cache clearing is permissible as an experiment, but its post-purge
RSS must not be labeled ordinary loaded-idle behavior. Compare any proposed
production policy's memory savings with next-synthesis latency, speech quality,
and long-running behavior. Keep RSS and allocator gauges separate.

## Tracked follow-up work

The entries below are repository-tracked follow-ups, not additional approval
questions or newly created GitHub issues. Each requires its own scoped change
and evidence before any implementation claim is made.

| ID | Observable outcome and scope | Acceptance evidence | Prerequisite and safe intermediate state |
|---|---|---|---|
| ARCH-F1: restoration ancestry | Establish whether nested A → B → C restoration survives every permitted reorder, cancellation, and clear operation across restart; evaluate explicit durable suspension identity if a gap is found. Excludes wholesale Store ownership migration. | Generated permitted operation histories with exact surviving identities, LIFO ancestry and saved offsets; observed-red case for each demonstrated defect. | Start from current controller/Store contract. A representation change needs backward-compatible migration and silent recovery; current delivery remains unchanged until separately verified. |
| ARCH-F2: crash boundaries | Establish silent restart and recoverable identity/position at sink stop, durable pause, stack update, alert claim, and device start boundaries. Excludes a claim of atomic hardware/database transactions. | Seeded failures at each named boundary; reopen durable state independently; assert no automatic audio and correct explicit-resume identity/offset or truthful regeneration. | Agree the observed-position/reconciliation contract before changing persistence. No dependency on ARCH-F1 merely because files overlap; revisit only if a chosen implementation requires its schema. |
| ARCH-F3: resource lifetime | Characterize and then enforce justified memory/disk admission, eviction and cleanup policies across hours of synthesis, long holds and engine switches without invalidating active playback. Excludes declaring the observed RSS a new budget. | Long-lived ownership and retained-byte observations; controlled cache-policy A/B experiments including next-synthesis latency and quality; active-artifact survival and cleanup fault tests. | Preserve the pinned baseline and define each proposed policy's workload and budget before gating it. Model replacement is not a prerequisite. |

A five-minute soak and coarse timing comparisons do not close these entries.
No new global resource ceiling or implied dependency edge is introduced here.

## Delivery audit after acceptance

This table separates implemented scope from limits; it is not a blanket
completion declaration. Feature PRs remain independently verifiable, one
feature commit each. This decision is maintained with the review PR #47.

| Prompt | Implemented scope and evidence | Accepted deviation or remaining limit |
|---|---|---|
| 1 / PR #27, merged | [Preemption receipt](../testing-evidence/2026-09-30-playback-preemption.md): nested Played/Failed/Skipped restoration, exact child/offset, hold/cancel/clear schedules, restart and PCM stop envelope. | Controller/Store split accepted above. All-history ancestry and expanded crash boundaries remain ARCH-F1/F2. PCM checks do not prove acoustic pop-free hardware. |
| 2 / PR #28, merged | [MLX receipt](../testing-evidence/2026-09-30-kokoro-mlx.md): offline adapter, preparation, fallback, finite mono WAV, native inference; [measured report](../reports/2026-09-30-architecture-review.md) adds repeated inference and loaded-idle RSS. | Reviewed configuration footprint accepted above; optimization remains ARCH-F3. No universal quality, memory or latency guarantee. |
| 3 / PR #34 | [Streaming receipt](../testing-evidence/2026-09-30-streaming-audio.md): first-frame playback, bounded PCM, smooth underrun, exact cache, publication/recovery, holds/seek and review regressions. | User previously accepted measured 194–205 ms startup; [#33](https://github.com/flyingrobots/AI-TTS/issues/33) retains the sub-150 ms target. |
| 4 / PR #35 | [Multi-engine receipt](../testing-evidence/2026-09-30-multi-engine.md): engine selection, per-item routing, local HTTP privacy, Chatterbox native inference and dependency audit. | Native evidence is scoped to measured configurations; resident engine memory is not bounded by the MLX baseline. |
| 5 / PR #37 | [Cue/ducking receipt](../testing-evidence/2026-09-30-earcon-and-ducking.md): once-per-document cue, defaults/settings, native other-app routing, measured 0.30 gain and unity restoration. | Physical route switching, permission-denial interaction, installed GUI journey and long-session acoustics remain manual acceptance gaps. Native app owns ducking; headless daemon does not. |
| 6 / PR #38 | [TUI receipt](../testing-evidence/2026-09-30-terminal-dashboard.md): real daemon socket, NDJSON events, Vim commands, history replay, progress/meter and visual checks. | Display tests and fake-sink journeys do not establish acoustic behavior. |
| 7 / PR #39 | [Paragraph receipt](../testing-evidence/2026-09-30-paragraph-segmentation.md): two/three-paragraph navigation, short atomic inputs, generated preservation/bounds and controller stepping. | The prompt's illustrative 40-word threshold is implemented as 60-word admission with 20-word paragraph groups; semantic and prosody limits remain documented. |

The reviewed integrated source `81be8ca` passed 913 Python tests and hosted
Python, native Swift and dependency-audit checks. Those results establish the
checked contracts, not every manual requirement above. Review PR #47 supplies
golden, soak and failure benchmarks plus calibrated scheduled CI guards; the
scheduled workflow has not yet run from the default branch.

The [popping investigation #25](https://github.com/flyingrobots/AI-TTS/issues/25)
remains open. Neither this acceptance nor green CI establishes its root cause
or resolution. No issue is closed by this decision; no PR merge or installed
application replacement is implied.
