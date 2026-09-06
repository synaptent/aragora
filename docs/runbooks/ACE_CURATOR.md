# ACE Fleet-Playbook Curator

`scripts/ace_curator.py` turns bounded, redacted fleet exhaust into an
incremental operational playbook. It is advisory tooling for issue #8976. It
does not alter its inputs, trigger work, or override repository gates.

## Contract

- Inputs are regular, non-symlink Markdown, JSON, or JSONL files. The default
  discovery surface is the local conductor ledger plus `.aragora/incident/`
  and `.aragora/incidents/`.
- Candidate lessons and semantic deduplication come from the bounded Claude
  consult helper. There is no keyword-only production fallback.
- Tests and reproducible reviews can provide `--decisions-json`; this is an
  offline recording of model decisions, not a heuristic classifier.
- Every add or update cites supplied source IDs. Updates require a reason.
- Lesson IDs are derived from model-provided stable causal keys. Existing
  lessons retain their IDs and ordering.
- Deletion is unsupported. Supersession or pruning requires a future explicit
  design rather than silently removing accumulated context.
- Known credential forms are redacted before source text reaches the model or
  playbook. Inputs are byte- and count-bounded.

## Usage

From a repository checkout containing local conductor exhaust:

```bash
python3 scripts/ace_curator.py --json
```

To curate explicit inputs into a reviewable branch artifact:

```bash
python3 scripts/ace_curator.py \
  --input .aragora/conductor_cycles/long_run_ledger.jsonl \
  --input .aragora/incidents/2026-07-09-main-red-typecheck-classification.md \
  --output docs/artifacts/fleet-playbook.md \
  --json
```

Review the diff before committing it. A second run with unchanged model
decisions is idempotent; new lessons append, while model-directed updates edit
the existing stable-ID block in place.

For offline verification, export a JSON object with a `decisions` list and
pass `--decisions-json PATH`. The accepted actions are `add`, `update`, and
`ignore`; see `tests/scripts/test_ace_curator.py` for fixtures.

## Shared Grounding

The current committed playbook is `docs/artifacts/fleet-playbook.md`. Conductor
skills should read it as advisory operational grounding after live steering
and before selecting a new work unit. Live owner, tier, halt, and settlement
state always takes precedence.
