# XCTest async invocation mitigation

Change-kind: bug fix

The final composer full-suite run on September 30 terminated with signal 11 at
`testCaptionPreferenceFollowsDaemonAndPushesChangesWithoutChangingWatchdog`.
The owned macOS crash report identifies a null dereference in
`swift_task_localValuePopImpl`, called by `XCTSwiftErrorObservation._observeErrors`
and `XCTFailableInvocation.invokeWithAsynchronousWait`. PRs #28 and #30 also
failed at this existing async-test entry; #29 passed. No run was retried into green.

The five tests did not need Swift async test-method invocation: they operate
callback/Combine boundaries with XCTest expectations. They now use synchronous
`wait(for:timeout:)`, which services their main-run-loop work, retaining every
expectation, assertion, timeout, and per-test execution allowance. Production
code and the suite's process deadline are unchanged. This bypasses the observed
runner path; it is not a diagnosis or repair of the Swift runtime itself.

After the harness change:

- Full Swift suite: 112 tests pass (0.243 seconds reported).
- Address Sanitizer full suite: 112 tests pass (0.285 seconds reported).
- Falsification removes all five completion-signalling sites; the six waits
  time out with the specific unfulfilled expectation rather than passing.

Keep issue #6 open until hosted and subsequent toolchain evidence warrants
closure. Revisit this workaround when the upstream runner/runtime is repaired;
keep the behavior assertions independently of the invocation mechanism.
