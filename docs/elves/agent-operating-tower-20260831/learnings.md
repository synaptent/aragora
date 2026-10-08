# Agent Operating Tower learnings

## Existing semantic owners

- Work recommendations and dependency truth already live in
  `aragora/work/models.py` and the existing work CLI/robot surfaces.
- Durable mission state already lives under `aragora/missions/`.
- Session continuity already lives in `aragora/swarm/session_state.py` and the
  agent-bridge/session tools.
- Live ownership and authority facts already live in the lane, lease, steering,
  halt, protected-check, merge-packet, and settlement helpers.
- Commit-addressed repository evidence and planning already live in
  `aragora/nomic/context_builder.py`, `aragora/nomic/meta_planner.py`, and the
  canonical `DecisionReceipt` implementation.

The orientation layer must project these owners. It must not mirror them into a
new store or invent a competing scheduler, authority service, or receipt type.

## Observed integration gaps

- Agents can query work, mission, operator snapshot, and Nomic state separately,
  but no one command yields an exact-anchor, authority-ordered reconstruction.
- A live work recommendation can say `ready` while settlement state is
  `BLOCKED`. This is the representative contradiction: orientation must surface
  both records, preserve their evidence, and block the action using higher live
  authority.
- `MetaPlanner.plan` and context packs already provide the generic planning
  substrate, while the current Nomic CLI does not yet expose the planned generic
  `plan` composition. The implementation should bridge existing APIs rather than
  duplicate planning logic.
- Compactness is a correctness feature. The 16 KB envelope and 800-byte
  unchanged response require deterministic priority/truncation and explicit
  omission facts, not arbitrary text clipping.

## Live staging observations

- `origin/main` at staging was
  `2b94459bc0e316c3c0c1eb285695bf2a0c73c647`.
- The pristine required source suite passed at that exact commit.
- Scheduled production smoke/health jobs were failing outside the protected
  required-context set. They do not authorize source changes in this run.
- VibeProxy successfully routed the bounded Fable consultation. Fable advised a
  contract-first Batch 1 with trace fixtures and no runtime wiring. This agrees
  with the user plan but remains advisory and non-countable.
- Protected paths and governance documents must remain untouched. If a batch
  reveals a need to change them, reclassify and request the appropriate human
  authorization instead of expanding scope.

## Resource and governance lessons to preserve

- Bind head and protected-check verdicts in the same snapshot wherever possible;
  later lookups recreate a time-of-check/time-of-use gap.
- Evidence is generated only after local gates, remote non-quorum protected
  checks, mergeability, scope, and exact refs settle.
- A missing or ambiguous authority-bearing source is not `unknown but probably
  safe`; it is a blocked affordance with a named next legal action.
- Model reasoning may be useful and evidence-linked without being called
  deterministic. Fingerprint source/effect inputs and receipts, not the internal
  reasoning path.
- Experience is proposed, verified, and separately promoted. It never writes
  authoritative memory or calibration merely because an episode completed.
