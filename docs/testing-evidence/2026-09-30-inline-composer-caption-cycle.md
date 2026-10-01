# Inline speech composer and caption cycle

Change-kind: behavior change, as directly requested by the user.

Speak toggles a scrollable inline composer below current playback, in the area
otherwise occupied by Queue/History. Close restores the previously selected tab;
the AppState-owned draft survives view removal. The separate composer window
and its subscription are removed. External-application tracking remains an
owned observer so selection imports retain their previous target semantics.
The form uses a bounded editor and stacked pickers within the menu's width.

The caption button cycles Off → Bottom → Top → Off. Enablement retains its
daemon command/persistence contract; placement retains its local preference.
Enabling through the cycle always selects Bottom even when the saved position
was Top. Moving Bottom → Top emits no redundant enable command.

The medium WireProtocolTests boundary test records the complete three-state
cycle, persisted preference, and exact daemon commands. Before the change it
was run against a method extracting the old boolean-toggle behavior: six
assertions failed, including wrong placement, wrong enablement and three
commands instead of the expected true/false pair. The initial fixture used
lowercase placement strings; these were corrected to the existing capitalized
wire-independent defaults values and the six failures were observed again
before implementing the cycle. This is falsification for the changed contract,
not a claim that the previously specified binary toggle was defective.

Validation: warnings-as-errors Swift build and all 130 Swift tests passed.
Existing composer tests cover import-before-submit, exact provenance/options,
rejected-draft retention and interpretation preservation. Existing activation
tests still cover external-target changes and observer retirement; only the
observer type name changed. The cycle test records its oracle and deletion
criterion at the boundary. Physical pointer/keyboard traversal, file-picker
presentation inside the installed popover, and multi-display visual layout
remain manual UI verification limits. No installed app or daemon was replaced.

## Review fix: the failure toast reveals History while composing

Change-kind: bug fix. The inline composer replaces the tab bar and History in the popover body. The failure toast's open-History action still only set `selectedTab = .history`, so with the composer open it showed the composer and the failed item stayed hidden. The action now calls `AppState.revealHistory()`, which selects History and collapses the composer. The draft is kept.

Regression: medium `SpeechFailureTests.testRevealingHistoryCollapsesTheInlineComposerAndKeepsTheDraft`. Oracle: after `revealHistory()`, History is selected, the composer is collapsed, and the draft text is unchanged. On parent `5f89043`, with the old toast body moved verbatim into `revealHistory()`, the test was observed red with one failure, `XCTAssertFalse failed - History is not rendered while the composer is open` (SpeechFailureTests.swift:66). The selected-tab and draft assertions passed. After the fix, all 131 Swift tests pass.
