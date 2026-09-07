## What this changes

<!-- And why. The why is the part that will still matter in a year. -->

## Evidence

<!-- This repository treats tests as the specification, so a change is
expected to arrive with one. -->

- [ ] A test was written that failed for the right reason before the fix, and
      passes after it. (`docs/standards/testing.md` rule 12. "Red for the
      wrong reason is not evidence" — a test that fails because it is broken
      is not a witness.)
- [ ] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`
      and `uv run mypy` are clean.
- [ ] `swift test --package-path clients/menubar` is clean, if any Swift
      changed.
- [ ] No new warnings anywhere, including pre-existing ones in files you
      touched.

## Documentation

- [ ] `CHANGELOG.md` describes this from the user's side.
- [ ] Anything in `README.md` or `docs/` that this makes untrue is fixed in
      the same commit.
- [ ] If this fixes something in `docs/backlog/`, its file is deleted here.

## Deliberate omissions

<!-- Anything you chose not to do, and why. A stated omission is a decision;
an unstated one is a surprise for the reviewer. -->
