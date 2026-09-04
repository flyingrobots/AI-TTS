# JSONL parser corpus

Each `.hex` file is one minimized byte sequence for the daemon's strict JSONL
decoder. Hex encoding keeps malformed UTF-8 and truncated JSON ordinary,
portable Git text. `tests/test_jsonl_corpus.py` declares the expected outcome
for every seed and replays the complete directory in CI.

When generation finds a new failure, shrink it, add the minimal bytes here,
and add its expected outcome to the case ledger. Do not replace an existing
seed with a larger reproducer.
