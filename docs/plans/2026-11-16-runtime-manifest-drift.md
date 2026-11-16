# Keep guided-runtime exports current

Issue: [#172](https://github.com/flyingrobots/AI-TTS/issues/172).
Change class: bug fix in generated installation inputs and CI verification.

## Outcome and scope

Guided setup consumes the three checked-in runtime requirement files. Regenerate
them from the current frozen lock, and make CI reject drift between the lock
and those consumed files. Preserve markers, hashes, engine extras, and source
revision pins. Document the reproducible export command.

No model weights, live runtime installation, engine behavior change, dependency
version decision, or source repinning is in scope. The running daemon stays
untouched. Coordinate the supply-chain step with the separate Rust CI job in
#130.

## Verification

1. Reproduce stale exports with the same uv version used by CI, recording a
   failing comparison before regeneration.
2. Regenerate all three files and pass the comparison without changing uv.lock.
3. Corrupt a version and a hash separately; each comparison must fail. Remove
   each deliberate mutation and recheck the original outputs.
4. Check source pins and platform/Python markers, run affected setup/worker
   tests, normal hooks, and the existing hosted supply-chain audit.
5. Replace this plan with actual evidence and boundaries before marking ready.

## Safe intermediate state

This first draft contains the plan only. No install manifest or CI rule has
changed yet. Existing installed model environments are a separate operational
boundary; updated exports do not upgrade them in place.
