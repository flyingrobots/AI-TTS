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

## 2. Restrict discovery to Store

```text
=== [2] [P1] ===================================
Source: PR
File: tests/test_store_surface.py
Lines: L43-L47
Issue: Unrelated definitions below Store were reported as Store methods.
```

Regression: two controlled source cases append another class or a function
with a nested definition. Both failed before correction, reporting
`{'send', 'unrelated'}` instead of `{'send'}`. Parsing the actual top-level
Store class and selecting its direct function definitions makes both pass.

## 3. Indirect callers

```text
=== [3] [P1] ===================================
Source: PR
File: tests/test_store_surface.py
Lines: L50-L61 at de5121c
Issue: Bound methods passed as callbacks were reported as unused.
```

Two end-to-end gate regressions use a callback argument or saved bound method.
Both failed red with orphan `send`. Counting attribute-name references rather
than requiring a directly following call makes both pass. The gate's module
comment now states its name-collision limitation and the explicit exception
mechanism for dynamic callers instead of claiming false positives impossible.

## 4. Non-vacuity evidence

```text
=== [4] [P1] ===================================
Source: PR
File: tests/test_store_surface.py
Lines: L68 at de5121c
Issue: The nonempty-discovery assertion had no falsification receipt.
```

The controlled source is `class Store: pass`. With the real gate this raises
`Store should define public methods`, proving the guard rejects empty discovery.
Temporarily deleting only that assertion makes the retained calibration fail
with `DID NOT RAISE AssertionError`. Restoring the assertion makes it pass.
No production code changed for this evidence correction.
