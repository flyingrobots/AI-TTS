# History provenance action

Change-kind: bug fix

The medium Swift regression hosts an actual HistoryRow in an owned AppKit
window. Its oracle is a labeled native Show provenance button whose activation
loads evidence for that row's clip; the fake exporter returns the requested ID.
No daemon, network, or private history is involved. The owned run loop drains
completion with a one-second deadline under the suite's 60-second process limit.

- Red on the original DisclosureGroup: existing native-control witness passed;
  the Show provenance button unwrap failed (one failure, 0.115 seconds).
- Green with the native button: one test passed (0.207 seconds).
- Falsification: retaining the button but deleting its action failed the exact
  details assertion: nil versus `Source: CLI; clip: clip`.
- Full local Swift suite: 106 tests passed. This does not clear the separately
  observed hosted XCTest signal-11 failure tracked by issue #6.

Remove this regression only when History no longer offers inline provenance.
Real pointer/VoiceOver acceptance remains outside this in-process check.
