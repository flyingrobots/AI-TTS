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
