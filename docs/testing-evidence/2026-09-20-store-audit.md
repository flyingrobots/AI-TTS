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

## 5. Consolidate the subsumed assertion

```text
=== [5] [P1] ===================================
Source: PR
File: tests/test_store_surface.py
Lines: L79-L95 at de5121c
Issue: The internal-only test duplicated a subset of the orphan assertion.
```

The new regression enters the surviving gate with an internal-only public
method. Before correction it failed because the gate did not identify that
classification. The corrected gate reports unused and internal-only methods
in one diagnostic. The second test was deleted under the subsumption criterion:
every name it rejected was already rejected by the surviving gate. The
calibration verifies the internal-only diagnostic without a second repository
scan asserting the same condition.

## 6. Async method discovery

```text
=== [6] [P2] ===================================
Source: Self S2
File: tests/test_store_surface.py
Lines: L43-L47 at de5121c
Issue: Async public methods were omitted from discovery.
```

Regression: a controlled Store has a used synchronous method and an unused
async method. Before correction, the gate accepted it and the regression
failed `DID NOT RAISE AssertionError`. Including `AsyncFunctionDef` in the
Store class discovery makes the gate reject `fetch` as unused.

## 7. Ignore prose masquerading as callers

```text
=== [7] [P2] ===================================
Source: Self S1
File: tests/test_store_surface.py
Lines: L57-L60 at de5121c
Issue: Comments and strings could satisfy the caller requirement.
```

Both controlled cases (a comment and a string literal containing
`store.send()`) failed red with `DID NOT RAISE AssertionError`: the gate
incorrectly accepted the method. Caller discovery now uses Python attribute
read nodes. Comments and string constants cannot satisfy it; direct calls,
saved methods, and callback arguments remain recognized. Internal-only
diagnostics use the same syntax-based distinction instead of matching prose.

## Commit ledger and final validation

| Item | Severity | Commit | Outcome |
| --- | --- | --- | --- |
| 1: resource class | P1 | ab003b2 | Medium-tier selection calibrated; thread resolved. |
| 2: class scope | P1 | 8f6123d | Unrelated class and nested-function cases rejected; thread resolved. |
| 3: indirect use | P1 | c302313 | Callback and saved-method cases accepted; thread resolved. |
| 4: non-vacuity | P1 | 1b93ea0 | Empty discovery rejected; assertion-deletion mutation killed; thread resolved. |
| 5: duplication | P1 | 1c7594f | One repository assertion with classified diagnostics; thread resolved. |
| 6: async methods, Self S2 | P2 | 1dc2780 | Unused async method rejected. |
| 7: prose references, Self S1 | P2 | 8df1238 | Comment and string pseudo-callers rejected. |

The complete local Swift suite passed under the required 60-second process
deadline: 97 tests, zero failures. Ruff lint and formatting and mypy passed
for the audited code. Full Python validation also runs in the mandatory
pre-push hook; its result is reported in the PR activity summary.

### Hosted CI observation, Self S3

The earlier published `de5121c` Swift job failed with signal 11 at
`WireProtocolTests.testCaptionPreferenceFollowsDaemonAndPushesChangesWithoutChangingWatchdog`.
Job: https://github.com/flyingrobots/AI-TTS/actions/runs/35527334186/job/106121677110
No Swift files change in this PR. This failure was posted separately with
local counterevidence; the root cause is not established. The new head must
be judged on its own CI receipt. No failed-job rerun was requested.
