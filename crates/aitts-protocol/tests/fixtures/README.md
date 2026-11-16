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

`replies.json` and `events.json` are source-derived structural examples at the
same reference commit. They cover every operation reply and all 14 emitted
event shapes, including both forms of `history_changed`. They include synthetic
metadata and counter states; they are not captures of a running daemon. The
Rust types were not used to generate these examples. Daemon policy can reject
a structurally valid request or disallow a synthetic combination of states.

`catalog-7b23b96.json` adds model-catalog projections captured from Python commit
`7b23b96c728317b726a82804b1891aabb48352bb` for issue #164. It records the source
file hashes and four adapter-status cases: explicit null without a private
runtime, a current Kokoro adapter, an unknown legacy Kokoro MLX adapter, and a
stale Chatterbox adapter. The producer used an owned temporary home, fake
engine and sink, and the existing owned installer test helpers. It used no
live model, download, device, or operator state. The capture compared the
`engines.models` and `snapshot.models` projections for equality. The source
file hashes were verified against that committed Git tree before copying.
Rust tests embed these captured arrays in the source-derived reply envelopes;
they do not claim those complete envelopes were captured. The original nine
reference conversations remain unchanged.

`legacy-arguments-aa8d7b3.json` records eight arguments/origin projections from
the public Python `provenance` operation at commit
`aa8d7b395935fde49c33be6990f817914aa3b574`. An owned fake daemon accepted a
synthetic submission over its Unix socket. The fixture then installed each
legacy arguments value in that submission's owned `request.json` and queried
`provenance` over the same public socket path. Null, false, integer, float,
string, array, and object values were preserved. The source-file SHA-256
values were checked against the committed tree. Only the two returned
fields are published here; complete reply envelopes in Rust are structural
test data. A synthetic audio-evidence warning does not establish usable audio
metadata, which this projection does not claim to test.

This fixture record is agent-written and has not received human review.
