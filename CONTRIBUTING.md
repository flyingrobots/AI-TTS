# Contributing

Thanks for your interest. This is a personal project, kept public because it may
be useful to others.

## Before you write code

**The design documents come first.** Read [`docs/design/`](docs/design/) — the
architecture, the feature breakdown, and the open questions. If a change
contradicts a design decision, raise it as an issue rather than implementing
around it.

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

## Commits

Conventional commit messages. Reference the issue a change closes in the footer.

## Licence

Contributions are accepted under the Apache License 2.0, the same licence as the
project.
