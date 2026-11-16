# Protocol reference inputs

The nine files in `wire/` contain 30 concrete conversation records from the
Python reference at commit `38d967c26f158472e366dcc7b779258228cc6e3e`.
The reference uses the isolated process fixture in `tests/socket_daemon.py`,
the fake engine and sink in `tests/fixture_daemon.py`, and the scenarios in
`tests/wire_transcripts.py::record_scenario`. It does not use a live daemon,
model, audio device, or operator state.

The capture retained concrete identifiers, numeric times, and numeric process
identifiers. It projected the fixture's owned home path to `/synthetic/ai-tts`.
Both the raw capture and the projected conversations matched the unchanged
`tests/corpus/wire/` goldens through `assert_transcript`. The projection was
checked again before these files were copied here. Comparison markers such as
`<time>` and `<pid>` are not wire values and do not appear in these inputs.

The Rust tests must parse and serialize each concrete request, reply, and event
without changing its JSON value. The Python goldens remain the behavioral
reference; these files make the same scenarios usable by typed decoders.

`requests.json` contains source-derived request examples for all 31 dispatcher
operations and the transport's `subscribe` operation. They are an independent
inventory of field names and value kinds, not captured success responses.
Their oracle is the dispatcher and its helpers at the same reference commit.
For example, a well-formed `get` request does not establish that its identifier
exists or that the daemon can perform the requested operation.

This fixture record is agent-written and has not received human review.
