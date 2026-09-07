# History is not searchable

**Consequence.** History is permanent by design and grows without bound.
Finding something said last week means scrolling.

**Why.** The `history` op paginates by `limit` and `before` and offers no
predicate. The menu bar has no search field, so there is nothing to search
with and nothing to search against.

**Why it is still here.** Search has to happen in the daemon, not the client:
the text is client-confidential and lives in SQLite, and a client-side filter
would only search the page it had already fetched, which is the opposite of
what someone looking for an old clip needs. That makes it a wire-contract
addition — a predicate on the `history` op, its schema, the CLI and the MCP
tool — rather than a UI change, and it was not part of the v0.1.0 MUST set.

`docs/design/features.md` §5.7 states it. It is a genuine gap against the
design rather than a deviation from it.

**Where.** `src/aitts/store.py` (`history`), `src/aitts/daemon.py`
(`_op_history`), `src/aitts/application/schemas.py` (`HistoryQuery`).
