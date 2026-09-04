# Menu-bar single-instance evidence — 2026-09-03

Change kind: bug fix.

Oracle: one AI-TTS menu process owns one status item. A second process must
refuse startup, and the lock must become available when the owner exits.

Commit `5b75c43` is the test-only red parent. `python3
../../scripts/run_with_deadline.py 60 swift test` failed to compile there with
four `cannot find 'SingleInstanceLock' in scope` diagnostics. The implemented
test acquires an OS advisory lock, proves a second acquisition returns `nil`,
releases the first owner, and proves acquisition succeeds again. Removing the
non-blocking `flock` call makes that same assertion fail by admitting the
second owner.
