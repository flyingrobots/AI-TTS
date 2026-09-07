# Backlog

Known defects and deferred work, tracked in the repository rather than in
somebody's head.

One file per item. This exists because a defect a contributor cannot see is a
defect they will rediscover, spend an afternoon on, and then find was already
understood and deliberately left alone.

**What belongs here:** anything with a consequence a user or a contributor
would notice — a wrong number on screen, a missing capability the design
implies, a deliberate deviation somebody will read as an oversight. Each file
says what happens, why it happens, and why it has not been fixed, so the next
person can disagree with the reasoning rather than re-derive it.

**What does not belong here:** design-level notes about the shape of the code
with no user-visible consequence. Those go in the working journal at
`.claude/bad_code.md`, which is deliberately untracked.

**Closing an item** means deleting its file in the commit that fixes it, and
saying so in the commit message. A backlog whose entries are marked "done"
instead of removed stops being readable within a release.

## Open

| Item | Consequence |
| --- | --- |
| [`elapsed-time-ignores-abandoned-chunks.md`](elapsed-time-ignores-abandoned-chunks.md) | The progress bar under-reports after a chunk is skipped |
| [`no-history-search.md`](no-history-search.md) | History is browsable but not searchable |
