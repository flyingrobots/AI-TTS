# Contributing

Thanks for your interest. This is a personal project, kept public because it may
be useful to others.

## Before you write code

**The design documents come first.** Read [`docs/design/`](docs/design/) — the
architecture, the feature breakdown, and the open questions. If a change
contradicts a design decision, raise it as an issue rather than implementing
around it.

**[`docs/design/one-utterance.md`](docs/design/one-utterance.md) is the fastest
way in.** It follows one utterance from an agent's `say` to the state change
that ends it, naming the module at each step. `architecture.md` says what the
parts are and why; that one says what actually runs.

**Check [the open issues](https://github.com/flyingrobots/AI-TTS/issues)
before starting on a defect.** Several known ones are open on purpose, with
the reasoning written into the issue. Disagreeing with that reasoning is
welcome; rediscovering it over an afternoon is not a good use of yours.

## Ground rules

- **Discuss before building anything large.** Open an issue describing the
  problem before writing an implementation for it.
- **Tests are the specification.** New behaviour arrives with a failing test
  first. Do not skip, weaken, or delete a test to get a build green — fix the
  code, or say why the test is wrong.
- **Say what you actually verified.** "Tests pass" means you ran them and saw the
  output. If you did not, say so.
- **Keep the text private.** Never commit spoken content, audio artifacts,
  history databases, or anything else the tool produced at runtime. They are
  gitignored for a reason.
- **Nothing from your own machine.** No absolute paths from your home
  directory, no local agent names, no personal voice assignments. If someone
  cloning this repository would read it and wonder whose setup they were
  looking at, it does not belong here.
- **Zero warnings.** Including ones that were already there in a file you
  touched.

The full testing rules — size classes and their time budgets, what counts as an
oracle, the flakiness policy, and why every assertion must be shown able to
fail — are in [`docs/standards/testing.md`](docs/standards/testing.md), and
several of them are enforced at collection time rather than trusted.

## Commits

Conventional commit messages, with a `Closes #N` footer for the issue a
change closes so the issue closes itself when the commit lands.

Say *why* in the body, not just what. The what is in the diff and will still
be there in a year; the reasoning will not be anywhere else.

GitHub Issues is the only tracker. There is no backlog file in the repository
and no second list to keep in sync — a defect recorded in two places is a
defect recorded wrong within a release.

## Licence

Contributions are accepted under the Apache License 2.0, the same licence as the
project.
