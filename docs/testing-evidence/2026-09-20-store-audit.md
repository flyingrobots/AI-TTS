# PR #24 audit receipts

Change-kind: bug fix

Audit started from clean `de5121c` in the isolated store-cleanup worktree.
No production playback code is changed by these corrections.

## 1. Repository resource classification

```text
=== [1] [P1] ===================================
Source: PR
File: tests/test_store_surface.py
Lines: L30-L33
Issue: Repository scans were charged to the small tier.
```

Regression: `test_repository_gate_is_selected_in_the_medium_tier` invokes
pytest collection against the actual module and medium-tier selector.
Red before correction: exit 5, zero selected tests and two deselected.
Green after changing the module marker: exit 0. This is a medium subprocess
test, not a check that a particular source string exists.
