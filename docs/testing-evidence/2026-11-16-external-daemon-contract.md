# External daemon socket contract

Change-kind: feature. Issue: [#114](https://github.com/flyingrobots/AI-TTS/issues/114).

The socket tests can now start the Python reference daemon or a command from
`AI_TTS_DAEMON_CMD`. The selected process receives owned state and socket paths.
Python-only tests retain direct access to the Python fixture. No production
daemon, client, synthesis engine, or Rust code changed.

The baseline is the Python protocol after synthesis-only submission landed in
`d7c490211f2fdfda2863897b7be123b072adb57a`. Its reported version is 0.2.0.
The issue body checked for this work has SHA-256
`a0f3dbb9f087e60f060250c71ee3971b9753041b006cda81a7955ac88e02929c`.
Local checks used CPython 3.14.7 and pytest 9.1.1 on macOS arm64. The fixture
uses the same interpreter as pytest. All paths and speech in the corpus are
synthetic. No installed daemon, model, microphone, or speaker was used.

## RED and failure sensitivity

The new process and transcript tests were written before their helpers. Their
first runs failed on the missing helper imports. With the recorder present,
all nine scenario tests and the corpus ledger failed because the golden files
were absent. Candidates were captured outside the corpus, then inspected one
scenario at a time against the wire contract and current response fields.
The checked-in transcripts are class-5 change-detection evidence. This was
agent inspection, not independent human approval of the protocol.

A later process-lifetime test killed an admitted daemon and showed that the
fixture did not report its unexpected exit. That assertion failed before the
post-scenario process check was added, then passed with the check.

Controlled negative runs exercised the assertions without changing production
source. Each run exited with a test failure:

| Counterfactual | Observation |
| --- | --- |
| Ignore the operator's command | The command-specific state receipt was absent |
| Admit a process before its socket exists | The missing-socket test rejected admission |
| Disable the 64 KiB log limit | Startup timed out instead of reporting the log limit |
| Raise the state limit above the seeded oversized file | Startup timed out instead of reporting the state limit |
| Give distinct utterances the same normalized token | The identity-reference expectation failed |
| Mask identifier-looking text in arbitrary fields | The preservation expectation failed |
| Use Python object equality for transcript comparison | `ok: 1` incorrectly matched `ok: true`; the calibration test failed |
| Make the external daemon reply with `ok: 1` | All nine real socket golden scenarios failed |

The normal comparator uses canonical JSON, so value, type, missing-field, and
extra-field changes fail. Expected files are never passed through the mask.
The normalizer tests pin both its allowed substitutions and values it must
preserve. The executable cases are in `test_socket_daemon.py`,
`test_wire_normalization.py`, and `test_wire_transcripts.py`.

## GREEN and repeatability

```sh
uv run pytest tests/test_ipc.py tests/test_socket_daemon.py \
  tests/test_wire_transcripts.py tests/test_wire_normalization.py
```

The affected suite passed all 78 cases: 10 small and 68 medium. Ten more runs
passed all 780 cases, with file order shuffled using seeds 114 through 123.
The final repeated run used 5.78 medium-tier CPU seconds, including fixture
work and waited children, within the unchanged 120-second budget. Wall time
was 6.33 seconds. These observations are not performance claims for a real
synthesis engine.

After changing log cleanup to drain discarded bytes until EOF, the 16 process
and normalization checks passed again. The explicit `AI_TTS_DAEMON_CMD` route,
pointing to the reference command, passed all 40 `socket_contract` cases.
Ruff and strict mypy checks passed for the seven affected Python files before
publication. Normal commit and push hooks remain enabled.

The first full pre-push run found six failures in Python tests that imported
the old shared fixture name, plus a Darwin cleanup refusal after a child had
already been killed. Those imported fixtures now explicitly select the Python
fixture; their assertions are unchanged. A new RED regression showed cleanup
could signal a reaped group identifier. The fixture now keeps the child
unreaped through the final group signal and reuses the existing verified
Darwin zombie-group handling. Another RED regression cancelled a launcher
thread after it created the child; shielding that launch now retains custody
until cleanup finishes. These are repaired integration failures, not retries
accepted as evidence of success.

The repaired process, existing Python clients, and Darwin signal checks passed
38 cases. The process, IPC, and golden checks then passed 70 cases with the new
ownership protocol. The minimum Python 3.12 path passed all 18 process and
golden checks in a separate environment; it exercises the bounded `ps` fallback
because Darwin exposes `waitid` only from Python 3.13.

With those repairs in place, ten fresh runs passed all 800 affected cases
(80 per run), with the same 114–123 file-order seeds. The final run used
6.95 medium-tier CPU seconds and 7.67 wall seconds. The seven helper negative
controls were run again against this process-ownership implementation.

## Scope and limits

The corpus covers submit, status, list, history, pause, resume, skip, settings,
and subscribe. It includes populated list/history responses and their complete
consumed lifecycle events. The idle transport transcripts are deliberately
small; they do not establish every transport interleaving. Existing semantic
socket tests remain alongside the goldens.

This proves the default Python command and the command-selection boundary. It
does not establish compatibility with a Rust daemon or any other binary that
has not run the suite. Resource monitoring is a fixture guard, not a sandbox
for an untrusted executable. See the
[contract instructions](../../tests/corpus/wire/README.md) for command inputs,
limits, volatile-field rules, and transcript review requirements.

## Review repairs

`PRRT_kwDOUHyfMM64Diuj`: a controlled scan removed an actual child directory
after enumeration but before traversal. The original monitor killed the daemon
and failed the regression. The monitor now ignores a missing named descendant;
missing-root, disappearing-root, permission-denied, and unidentified-path
controls still fail closed. All five cases passed after the repair. This changes monitoring
admission only; it does not suppress other filesystem failures.

`PRRT_kwDOUHyfMM64Diuu`: a child that created 4,100 empty directories escaped
the original file-only budget and reached the startup deadline. That was RED
for the expected state-limit refusal. Directory entries now count toward the
same 4,096-entry budget, including entries excluded from traversal as symlinks.
The directory-only regression passed with the expected refusal and complete
owned-directory cleanup.
