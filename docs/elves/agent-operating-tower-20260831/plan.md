# Agent Operating Tower governed run

## Mission

Make Aragora maximally agent-intuitive, ergonomic, accretive, resource-efficient,
and governable by unifying work recommendations, mission state, session and lease
truth, and commit-addressed Nomic planning into one evidence-preserving operating
loop:

`orient -> investigate -> plan -> propose -> authorize -> commit -> wait/cancel -> verify/reconcile -> learn -> handoff`

The run is finite: at most eight serial PR-sized batches and no later than
2026-09-01T13:10:47Z. It uses one coordinator, one isolated worktree, scoped
ownership, at most two gate attempts per batch, and the repository's existing
authority and settlement machinery.

## Pinned starting state

- Repository: `synaptent/aragora`
- Starting `origin/main`: `2b94459bc0e316c3c0c1eb285695bf2a0c73c647`
- Branch: `codex/agent-operating-tower-20260831`
- Worktree: `$HOME/.codex/worktrees/agent-operating-tower-20260831/aragora`
- Lane: `agent-operating-tower-20260831`
- Lease: `82e882f4-7f4` (Batch 1 exact scope; replaces broad staging lease)
- Coordinator: `codex-agent-operating-tower-20260831`
- Runtime receipts: `.aragora/run-agent-operating-tower-20260831/receipts/`
- Fable advisory: `.aragora/goal_cycles/20260831T130312Z/` in the pristine
  observer checkout; it is strategy input only and never settlement evidence.

The dirty shared checkout is observation-only. Every tracked mutation occurs in
the isolated worktree after steering, lease, halt, main-health, ownership, and
exact-ref checks.

## Non-negotiable architecture

There is one projection tower and no new database or control plane. Higher layers
may summarize lower layers but never increase their authority.

Authority precedence is:

1. Exact Git, halt, lease, permission, and protected-check facts.
2. Durable mission, session, and ledger state.
3. Commit-addressed Nomic evidence and verified receipts.
4. Work recommendations and model-derived beliefs.

`aragora orient` is read-only and never launches a model. `aragora nomic plan`
is the explicit model-bearing operation. Generic Nomic planning remains
repository-read-only; existing `nomic run` behavior is unchanged. No batch may
introduce a service, database, implicit model call, autonomous memory promotion,
or a path around capability, risk-tier, exact-head, protected-check, receipt, or
human-settlement gates.

## Batch sequence

### Batch 1 - Canonical contract and trace baseline

- Predicted tier: Tier 1, with operator review required because this is the first
  PR of a new architectural pattern.
- Establish the canonical design document, `aragora.orientation.v1` schema, tower
  vocabulary, authority rules, freshness and invalidation semantics, and four
  executable trace fixtures: fresh orientation, interrupted resumption,
  uncertain high-risk action, and quiet no-change recheck.
- Do not wire production sources or add mutation behavior.
- Acceptance: schema and trace tests pass; every lower-layer evidence handle is
  portable; derived records cannot claim greater authority than their basis.

### Batch 2 - Orientation protocol types and source observations

- Predicted tier: Tier 1.
- Add the typed protocol records: `OrientationRequest`, `EvidenceHandle`,
  `SourceObservation`, `BeliefRecord`, `QuestionRecord`, `ActionAffordance`,
  `ObligationRecord`, `OrientationEnvelope`, `InvestigationCase`,
  `DecisionFrame`, `PreparedEffect`, `ExecutionEpisode`, `ExperienceProposal`,
  and `LoopHandoff`.
- Only source and effect inputs receive deterministic fingerprints. Model
  reasoning stays explicitly nondeterministic.
- Acceptance: round-trip, fingerprint, invalidator, authority-monotonicity, and
  bounded-cost tests.

### Batch 3 - Read-only source adapters and composition

- Predicted tier: Tier 1.
- Compose native Git, work-board, mission, session, lane, steering, halt, checks,
  and Nomic observations without copying them into a new store.
- Preserve native evidence references and source-health failures. Fail closed on
  ambiguous mission selection, malformed authority-bearing state, anchor drift,
  or unavailable authority-bearing sources.
- Acceptance: fresh and interrupted-resumption journeys reconstruct coherently;
  lower-authority `ready` recommendations are blocked by live higher-authority
  blockers and surfaced as contradictions.

### Batch 4 - `aragora orient` and response budgets

- Predicted tier: Tier 2.
- Implement the additive CLI, stable JSON and human rendering from one payload,
  default 16 KB budget, deterministic truncation, and a no-change response no
  larger than 800 bytes when `--since` matches.
- Every error names the next legal action. Output always includes `mutations: []`.
- Acceptance: one-command fresh orientation stays near 4,000 tokens; unchanged
  recheck stays near 200 tokens; existing CLI entry points remain compatible.

### Batch 5 - Mission and Nomic planning composition

- Predicted tier: Tier 2, unless canonical receipt semantics would change, in
  which case reclassify and stop before implementation.
- Complete `mission status --state PATH --json` and generic `nomic plan` CLI over
  the existing context builder and `MetaPlanner.plan`.
- Discover only verified packs bound to exact repository identity, commit,
  profile, and objective. Surface stale packs without authority. Never promote
  heuristic or one-family output into settled goals.
- Acceptance: exact-commit goals, scores, evidence coverage, dissent, receipts,
  staleness, and pack discovery appear through orientation; `nomic run` is
  unchanged.

### Batch 6 - Investigation and decision layer

- Predicted tier: Tier 3.
- Turn evidence deficits into bounded probes and `InvestigationCase`s; produce a
  `DecisionFrame` with alternatives, rejections, uncertainty, authorization
  needs, evidence, and the selected affordance; bind consequential decisions to
  the canonical `DecisionReceipt` without weakening legacy verification.
- Hard stop with an exact-head settlement packet. No merge without separate human
  risk settlement.

### Batch 7 - Prepared effects and execution episodes

- Predicted tier: Tier 3 for a dry-run-only internal seam. Reclassify as Tier 4
  and stop before implementation if mutation authority, workflow, security,
  persistence, or governance semantics would change.
- Bind expected repository anchor, mutation scope, idempotency key, effect
  fingerprint, authorization, rollback, and verification contract. Delegate to
  existing mission, capability, handoff, and settlement machinery.
- Prove only read-only probes and a fake idempotent executor in this run.
- Hard stop with an exact-head settlement packet; Tier 4 requires explicit
  preapproval before implementation and separate settlement before merge.

### Batch 8 - Learning, handoff, dogfood, and reconciliation

- Predicted tier: Tier 2 for read-only dogfood and documentation; split and park
  any durable learning or calibration change as Tier 3.
- Emit evidence-bounded `ExperienceProposal`s without promoting them; create
  resumable `LoopHandoff`s containing the last orientation fingerprint,
  completed effects, obligations, and one next legal action.
- Dogfood all four journeys against Aragora and temporary Git fixtures, and
  reconcile canonical documentation with implemented reality.

## Gate for every batch

1. Refresh operator steering, heartbeat, lease, halt, exact branch/main refs,
   ownership, main health, tier, and diff scope.
2. Tag the pre-batch branch tip and record the checkpoint.
3. Keep the batch at or below 800 changed lines. No unrelated cleanup.
4. Run focused tests, Ruff check and format check, touched-module MyPy,
   all-files pre-commit, normal pre-push hooks, ownership/diff checks, and
   `scripts/automation_pr_preflight.sh origin/main HEAD`.
5. Open or update one draft PR, wait for protected CI, and require all
   non-quorum protected checks green before countable evidence.
6. Prepare direct grounded Claude and Codex reviews at the exact full head SHA.
   Require 2/2 `PASS`, clean evidence lint, no dissent, and no P0/P1/P2.
   VibeProxy/Fable is advisory and cannot count.
7. Generate and verify the canonical DecisionReceipt and merge packet.
8. Tier 0-2 may use normal protected squash merge-on-green only when the live
   helper authorizes it, exact head/base match, and no admin bypass is needed.
   Tier 3-4 stops for exact-head human settlement. The first architectural PR
   also requires operator review even if otherwise low tier.
9. After any merge, refresh `origin/main`, additively restack, and regenerate all
   exact-head evidence. Never amend, rebase, or force-push published commits.

## Continuation and stop rules

Continue autonomously only while `stop_allowed: false`. External waits are
checked on a 4-5 minute cadence; quorum evidence receives at least 15 minutes
before any failure classification. At most two gate attempts are allowed per
batch.

Stop immediately and record a receipt on main-red state, active halt, lease or
ownership conflict, ref drift at a mutation boundary, unexpected scope,
unresolved P0/P1/P2, repeated transport ambiguity, three identical
infrastructure failures, more than 800 changed lines in one batch, two failed
gate cycles, two hours without material progress, the 24-hour deadline, or a
human gate. A clean infrastructure-only failure is classified separately and
does not authorize repair, rerun, evidence reuse, or bypass.

## Completion definition

The run succeeds only if the implemented layers preserve existing `work`,
`mission`, `operator-snapshot`, `MetaPlanner`, and `nomic run` behavior; fresh
orientation and quiet rechecks meet their budgets; stale Nomic packs never gain
authority; conflicts fail closed; high-risk actions request authorization
without effects; fake execution is idempotent; every episode terminates with
verification and a handoff; and every landed batch has exact-head two-family
proof plus a verified receipt. Parked Tier 3-4 work is an honest governed outcome,
not a failed run.
