# M-SIGNAL: reviewer integrity + settlement transport (issue #9241)

Part of the Signal-First Quality Recovery Program (#9039, campaigns 4+5, founder-approved
2026-07-11 with two amendments recorded in the #9039 ledger comment). Overnight elves-aragora
run; operator offline until morning (~08:00 CT 2026-07-12).

## Why (one paragraph that survives compaction)

Today (Jul 11) the reviewer fleet failed in four distinct ways while draining three PRs:
claude credit-walled for hours (family invisible), codex usage-walled mid-drive, gemini emitted
three consecutive hallucinated-P1 dissents on #8809 (reviewing diff hunks without file context),
and grok returned preamble-only output with verdict `unknown` yet `would_count=True`. Separately,
settlement stalled once on GraphQL quota exhaustion (shared 5k/hr user token). Quality-bar
dimension 5 measured 4/10. This run fixes the *integrity* half (what counts) and the *transport*
half (API budget) of settlement.

## Autonomy Contract / Run Control

- Run mode: finite (7 batches), overnight unattended; checkpoint 08:00 CT 2026-07-12
  (delivery target, not hard stop; may continue after).
- Merge policy: NEVER merge. Auto-settle Tier 0-2 packets only. Tier 3 batches: implement,
  gate, park packet for founder settlement. Tier 4 surfaces: DO NOT IMPLEMENT — write a
  design note + queue.
- Gate attempt cap: 2 full cycles per batch (program rule), then park.
- Program WIP cap: this run keeps ≤3 open PRs at any time (program cap 6 shared with two
  Factory missions #9239/#9242).
- Parallel fan-out: max 2 lanes, only file-disjoint pairs (B5 transport vs B1-B4 quorum
  evidence). Lanes registered in .aragora/run-elves-9241/lanes/.
- Per-batch wall-clock budget: 90 min. External-wait pacing: PR CI every 5 min, quorum
  evidence every 15 min, bounded foreground until-loops only.
- Receipt dir: .aragora/run-elves-9241/receipts/
- Branch: elves/m-signal-9241, worktree .worktrees/elves-m-signal-9241
  (base 8b1144146d). PRs: one per batch, stacked off this branch or main as appropriate,
  each referencing #9241.
- Drain-gate note: this is admitted quality-program work per the #9039 ledger.
- Main-red: halts all non-incident mutation (check pristine required checks are green on
  merges, NOT local `make ci-required` — see learnings file; the frozen mypy debt makes raw
  full-tree mypy red by construction).

## Tier pre-classification note

`aragora/cli/commands/review_queue.py` is Tier-4 merge-authority self-modification — DO NOT
TOUCH. `aragora/swarm/quorum_evidence.py` counting rules decide what evidence counts toward
merges: treat counting-rule changes as **Tier 3** (implement + park for founder settlement).
Prompt/grounding/preflight/transport changes are Tier 2.

## Batches

### B1 (Tier 3): no-verdict reviews must never count
- File: aragora/swarm/quorum_evidence.py (+ tests/swarm/)
- A ReviewerResult whose parsed verdict is `unknown`/missing must have would_count=False and
  be classified as malformed reviewer output (infra-adjacent), with the reason string visible
  in collect output. Regression test: grok-style preamble-only body → would_count False.
- Acceptance: zero paths where verdict unknown → counted. Park packet for founder.

### B2 (Tier 3): structured verdict contract + truncation exposure
- Same file. Reject PASS that carries blocking [P0]/[P1] findings as malformed (contradictory
  review); expose output truncation explicitly (flag on the item, never silently truncated
  evidence). Tests for both.
- Park packet for founder.

### B3 (Tier 2): ground reviewers on full changed files, not bare hunks
- Reviewer prompt assembly: include complete post-change contents of changed files (bounded:
  ≤400 lines/file, ≤6 files priority-ordered by diff size; note the bound in the prompt) so
  import-existence claims are verifiable. Regression: prompt for a diff touching
  sdk/python/aragora_sdk/client.py contains the import block.
- Rationale: gemini's 3 false P1s were all "X not imported" claims about files whose import
  blocks were outside the hunks.

### B4 (Tier 2): credential-health preflight + fallback routing
- Extend the existing CLI liveness probe: classify credit-wall/usage-limit/not-logged-in as
  distinct `credential_unhealthy` (fast-fail family, clear infra reason in failures[]), and
  only route OpenRouter fallback (ARAGORA_ENABLE_OPENROUTER_REVIEWER_FALLBACK) after a
  preflight that confirms the fallback itself has credentials. Never a silent no-op.

### B5 (Tier 2): settlement transport — quota-aware GitHub access (#8315)
- One cached PR inventory per collect/reconcile cycle; REST endpoints where equivalents exist;
  GraphQL reserved for queries without REST equivalents; on 403/rate-limit, surface reset time
  in the error instead of failing opaquely. Do NOT provision GitHub App credentials (operator
  work — write the runbook snippet instead).

### B6 (Tier 2): #9129 — evidence-lint infra surfacing
- Read issue #9129 first and revalidate against current code; implement per issue if still
  valid; if already fixed, document fixed-by evidence on the issue instead (closure proposal,
  do not close — operator batch-closes per program).

### B7 (Tier 2): #9133 — cancelled-run guardian, current P2
- Read issue #9133 + linked PR state first. Repair the flagged P2 on the existing work if it
  exists; otherwise implement M1 minimal: rerun externally-cancelled required PR runs once,
  with an idempotency marker. Script/library only — any .github/workflows change is Tier 4:
  write the workflow diff as a design note for the founder, do not push workflow edits.

## Batch order

B1 → B2 (highest integrity value; packets ready for founder's morning) → B4 → B3 → B5 (may
run as parallel lane 2, file-disjoint) → B6 → B7.

## Exit gates (from #9241)

- Zero malformed reviews counted across 100 consecutive review attempts (long-horizon; this
  run delivers the mechanism + tests).
- No settlement blocked solely by GraphQL exhaustion for 30 days (mechanism + tests).
