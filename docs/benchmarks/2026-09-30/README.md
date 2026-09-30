# Architecture benchmark baseline artifacts

Read the [report](../../reports/2026-09-30-architecture-review.md) for the
as-written/as-planned diagrams, interpretation, limitations and exact commands.
The [testing receipt](../../testing-evidence/2026-09-30-architecture-benchmarks.md)
records gauge calibration and falsification. Change-kind: feature.

Runtime source: `0290f3cf3a0c3930256f42f31500bda59c1eabeb`.
The candidate runtime is unchanged from that reference; the new code is the
benchmark instrument. “Candidate” does not mean the unbuilt planned design.

| Artifact | Contents |
|---|---|
| [manifest.json](manifest.json) | Artifact SHA-256s, archive-time harness hashes, frozen lock digest, hardware, SQLite version and installed dependency inventories for both interpreter lanes |
| [paired.json.gz](paired.json.gz) | All ten raw golden reports from five randomized pairs, plus comparison; every wall/CPU/SQL/commit sample retained |
| [paired-comparison.json](paired-comparison.json) | Uncompressed paired block medians and all 26 guard decisions; zero alarms |
| [slow-calibration.json.gz](slow-calibration.json.gz) | Ten raw reports plus comparison for the deliberately delayed source copy |
| [slow-calibration-comparison.json](slow-calibration-comparison.json) | Actual known-slow result: exit 1, 24 of 26 signals fail |
| [soak.json.gz](soak.json.gz) | Complete five-minute raw timings, intended-arrival lateness, memory checkpoints and PCM observations |
| [soak-summary.json](soak-summary.json) | Readable distributions and memory checkpoints; raw samples remain in compressed artifact |
| [mlx.json](mlx.json) | Real offline native inference trials, phased RSS/allocator observations and model/voice fingerprints |
| [calibration.json](calibration.json) | Ten isolated seeded-fault pytest failures with node ids and output |
| [backlog-red.txt](backlog-red.txt) | Ready-backlog fixture test failing before correction |
| [missing-payload-red.txt](missing-payload-red.txt) | Missing timing payload accepted before comparator hardening |
| [python-suite.txt](python-suite.txt) | Final full Python suite: 831 passing tests, class budgets and wall time |
| [mermaid-parse.txt](mermaid-parse.txt) | All ten diagrams parsed by Mermaid 11.12.0 |

The compressed files contain ordinary UTF-8 JSON, not Python pickle or an
executable archive. For example:

```sh
python3 -c 'import gzip,json; d=json.load(gzip.open("docs/benchmarks/2026-09-30/paired.json.gz","rt")); print(d["0-candidate.json"]["cases"].keys())'
```

The final fail-closed comparator was also run against all 20 retained raw
paired reports after payload validation was tightened; each supplied the full
26-signal inventory. Timing work was sequential, without overlapping tests or
native inference. CPU frequency and other user processes were not controlled.
Measurement boundaries and non-comparability of paced/burst/native profiles
are explicit in the report.

The separate scheduled workflow writes fresh raw results to Actions artifacts
for 30 days. Updating these checked-in baselines, the reference SHA or the 3x
policy requires a reviewable rationale and a repeated known-slow calibration;
there is no automatic re-blessing operation. Archive-time harness hashes
identify the retained tool version, while each run embeds the measured runtime
source hashes. The model run used a pre-existing optional environment; its
installed package inventory is retained rather than assumed identical to the
current frozen development environment.

The [integration-refresh artifacts](integration-refresh/) contain a later
comparison after inheriting mainline's lifecycle/replay/security fixes, plus
per-PR boundary validation. They are separate from the initial unchanged-source
calibration above. The original measured source is retained with the
`benchmark-baseline/2026-09-30` tag; the benchmark still checks the exact SHA.

The subsequent [streaming review follow-up](streaming-review/) retains a new
five-pair comparison (26 signals, zero regressions), per-PR validation and
observed-red streaming regressions. Earlier measurements remain unchanged.
