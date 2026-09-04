# AGENTS

## Testing

The accepted, binding [Testing Standards](docs/standards/testing.md) apply to every automated assertion in this repository.

Every change must declare whether it is a refactor, feature, bug fix, or deliberate behavior change. New and materially changed load-bearing assertions require recorded falsification evidence. Bug fixes require a regression test observed red on the unfixed code. Tests must enter through the narrowest contractual boundary, name their oracle, control what they observe, and carry an explicit size class. CI may gate only on trustworthy signals described by the standard; coverage percentages and mutation scores are inspection signals, never objectives.

