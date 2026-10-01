# History provenance hover card

Change-kind: behavior change. The user requested a tooltip-style hover card
instead of inline expansion.

The existing native button anchors a SwiftUI popover. Entering it loads the
clip's details; leaving schedules dismissal after 250 ms so the pointer can
cross into the card. Entering the card cancels dismissal. The content is 340
points wide with a scroll area capped at 220 points, selectable text, and an
accessible close button. Activating the trigger also opens/closes the card;
removing the row cancels pending dismissal. No provenance text is inserted
into the History row, and its button label remains stable.

Validation: warnings-as-errors Swift build and all 129 Swift tests passed.
Existing hosted History provenance tests verify accessible activation loads
its clip, removed history discards cached/late details, and loader failures
return on the main actor. No automated assertions were added or materially
changed for this reversible presentation update. These checks do not establish
physical pointer travel, popover placement on every display, or VoiceOver
navigation; those remain manual UI verification limits. No installed app or
daemon was replaced. No Python behavior changed.

## Code Lawyer audit: testable card presentation

Change-kind: refactor. The open, dismiss, and toggle rules moved from private `HistoryRow` state into `ProvenanceCardPresenter`, which takes an injected `ProvenanceCardScheduling` port. Production uses a cancellable task; tests use a manual scheduler, so no wall clock participates. Behavior is unchanged: activation toggles, leaving the trigger dismisses after 250 ms, entering the card cancels that dismissal, and a system-closed popover or a removed row closes the card.

`ProvenanceCardPresenterTests` is a medium XCTest file with the ui-design History provenance bullet as its oracle. Red on parent `3b4be25`: the tests did not compile (`cannot find 'ProvenanceCardPresenter' in scope`). Falsification: making activation re-present instead of close failed the toggle test; making card entry not cancel failed the card test; closing immediately on hover exit failed the grace-period and card tests; a popover binding that ignored system dismissal failed the dismissal test. Each seed was reverted, and all 133 Swift tests passed.
