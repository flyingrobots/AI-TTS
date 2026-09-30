# Surface new speech failures outside History

Change-kind: bug fix

New failed clips now publish a local toast with View History and dismiss actions,
a persistent menu error, and an error tray indicator. The toast disappears after
12 seconds without stealing keyboard focus or requiring notification permission.
The error remains available in the menu until dismissed. Initial History is a
baseline; restarting the app does not announce old failures again.

`SpeechFailureTests` is medium and enters through AppState's typed snapshot application boundary. A
controlled sequence contains old failure history, a newly failed clip, and the
same failure on a later poll. The final test applies snapshots synchronously and observes the published presentation state.
The test's oracle is one visible error and one notice for the new failure, no
startup alert, no repeat alert, and clearing the notice/error on dismissal.

Before the implementation, the test ran against the existing refresh behavior
and failed because `lastError` remained nil after the new failed clip appeared.
After the fix it passes. Temporarily removing the notice publication produced
an additional named assertion failure (`[]` instead of the expected one notice),
then source was restored. The notice contains the failure detail rather than
copying the selected source text into its content.

Automated coverage verifies publication and deduplication, not native panel
rendering or physical clicking. Full diagnostic details remain in History.

## Test-harness investigation

The first full run crashed in `swift_task_localValuePopImpl` called by
`XCTSwiftErrorObservation._observeErrors` as the next existing async test began.
Address Sanitizer reproduced the same null dereference in XCTest/Swift runtime;
it did not identify an application memory error. The original 104-test suite
passed under ASan when the new test was omitted for isolation only.

Changing superclass setup, grouping, wait strategy, or using a clean build did
not reliably remove that harness crash. A temporary empty-test control and a
control omitting only the Combine observer both passed. Explicit observer
cancellation alone did not fix it. These were diagnostic controls only, never
committed or counted as acceptance of the feature.

The final implementation separates typed snapshot application from transport
scheduling. The regression applies snapshots synchronously and asserts the
actual error/notice presented to the user, including dismissing both before the
next duplicate snapshot. It creates no Combine observer. It still catches missing
notice publication and repeated alerts. The original visible-error assertion
was observed red through refresh before the repair; removing notice publication
also makes the final state-based assertion fail.

The complete 105-test suite passes normally with this fixture. No tests are
excluded from the final suite. A subsequent Address Sanitizer run still crashes
at the same XCTest/Swift-runtime frame as the following existing async caption
test starts. Earlier ASan passes with intermediate fixtures are not treated as
proof of resolution. The precise runtime cause remains unknown; these results
do not establish a fix for the older intermittent report in #6.

Explicit outer captures also remove Xcode 27's implicit-strong/inner-weak capture
warnings without changing the existing request lifetime.
