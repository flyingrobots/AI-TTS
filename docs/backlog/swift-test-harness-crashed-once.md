# `swift test` crashed once in the xctest harness, unreproduced

**Consequence.** If it recurs in CI the Swift job fails with no test failure
attached, which reads as a broken build rather than as a harness fault. That
would block a release until somebody spends time on exactly this note.

**What was seen.** On 2026-09-07, one run of `swift test --package-path
clients/menubar` ended with:

```
error: Process '.../xctest .../AITTSMenuBarPackageTests.xctest'
exited with unexpected signal code 11
```

No test reported a failure. It happened on the first `swift test` invoked
immediately after a Python coverage run in the same shell command.

**Not reproduced.** Thirteen subsequent runs were clean: eight in isolation
and five with the full Python suite running concurrently, which was the
closest reconstruction of the original conditions. So this is recorded, not
diagnosed.

**Why it is probably not this code.** The 93 tests are value-object and
wire-decoding assertions — no concurrency, no manual memory management, no
Objective-C bridging beyond `NSNumber` reads. There is no obvious way for them
to segfault. A fault in the `xctest` harness or the toolchain is the more
likely explanation, and one that this repository cannot fix.

**What to do if it recurs.** Note whether it lands in the same place, and
whether it correlates with concurrent load. Two occurrences with any pattern
between them is worth an upstream report; one is worth this file.

**Where.** `clients/menubar/Tests/AITTSMenuBarTests/`,
`.github/workflows/ci.yml` (the Swift job runs it under
`scripts/run_with_deadline.py`).
