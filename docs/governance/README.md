# Governance

Merge gates, review evidence, operator delegation and repository governance
records. Every page in this directory is listed below once, grouped by topic.
The rules that bind every autonomous agent are in the
[Agent Operating Contract](../AGENT_OPERATING_CONTRACT.md) and the
[Review Authority Principles](../REVIEW_AUTHORITY_PRINCIPLES.md); the pages
here specialize or record them. The full documentation map is in
[docs/README.md](../README.md).

Status notes in the tables come from each page's own header. Proposals, plans
and dated records describe the repository on the date they name; check the
code and the live branch protection before relying on them.

## Merge Gate and Review Evidence

| Page | What it covers |
|------|----------------|
| [TIERED_MERGE_GATE_ENABLEMENT](./TIERED_MERGE_GATE_ENABLEMENT.md) | The tiered merge gate is enabled in CI, and what that changes |
| [QUORUM_EVIDENCE_RUNBOOK](./QUORUM_EVIDENCE_RUNBOOK.md) | Operator runbook for getting `aragora-merge-quorum` to count model review signals on the exact head |
| [MERGE_GATE_RECONCILIATION](./MERGE_GATE_RECONCILIATION.md) | Aligning branch protection on `main` with the review authority rules (status: active) |
| [MERGE_GATE_CARRY_FORWARD_THREAT_MODEL](./MERGE_GATE_CARRY_FORWARD_THREAT_MODEL.md) | Threat model for carrying review evidence forward and for an active settlement controller (status: draft, design only) |
| [BOSS_LOOP_MERGE_GATE_PHASE3_DESIGN](./BOSS_LOOP_MERGE_GATE_PHASE3_DESIGN.md) | Phase 3 resilience design for the boss loop and the merge gate (status: draft, design only) |
| [PR_RUN_CANCELLATION_DIAGNOSIS](./PR_RUN_CANCELLATION_DIAGNOSIS.md) | Why pull-request workflow runs were cancelled (traced to `required-check-priority.yml`) and the mitigation plan |
| [ci-main-guardrails](./ci-main-guardrails.md) | Autonomy boundary for CI, runner, release and main-branch work (governance reference, April 2026) |
| [Gemini reviewer-reliability record](./records/20260716T2200Z-gemini-reviewer-reliability-record.md) | Record of fabricated claims in Gemini merge-quorum reviews (July 2026) |

## Operator Authority and Delegation

| Page | What it covers |
|------|----------------|
| [OPERATOR_DELEGATION_POLICY](./OPERATOR_DELEGATION_POLICY.md) | How routine operator review work is delegated; specializes the operating contract (status: active) |
| [BOUNDED_OPERATOR_DELEGATION_PROPOSAL](./BOUNDED_OPERATOR_DELEGATION_PROPOSAL.md) | Bounded operator delegation for a product-readiness pilot (status: proposed only, default off; issues no grant) |
| [DELEGATION_CONTRACT_V0_1_SPEC](./DELEGATION_CONTRACT_V0_1_SPEC.md) | Schema-first specification of the Aragora Delegation Contract v0.1 (status: draft, May 2026) |
| [ADC_v0.1-v0.4_STACK_AUDIT](./ADC_v0.1-v0.4_STACK_AUDIT.md) | Audit that Delegation Contract versions 0.1 to 0.4 compose cleanly (May 2026) |
| [OPERATOR_GRANT_VERIFICATION](./OPERATOR_GRANT_VERIFICATION.md) | Data verification of operator grants in `aragora.policy.operator_grant` (phase 2A; no live authority) |
| [LOOP_CONTROL_PLANE](./LOOP_CONTROL_PLANE.md) | Read-only inventory that asks whether each standing loop is safe to keep running (v1) |
| [AGENT_DISPATCH_REACH_PLAN](./AGENT_DISPATCH_REACH_PLAN.md) | Plan for reaching agent sessions Aragora did not launch, such as Droid CLI and Codex Desktop (status: plan only) |

## Subsystems and Repository Structure

| Page | What it covers |
|------|----------------|
| [subsystem-ledger](./subsystem-ledger.md) | Classification of every top-level Aragora package into governance buckets (March 2026) |
| [duplicate-subsystem-resolution](./duplicate-subsystem-resolution.md) | Surviving module and migration path for each duplicate subsystem cluster (March 2026) |
| [deprecation-candidates](./deprecation-candidates.md) | Defer-bucket modules that are candidates for deprecation, removal or extraction |
| [phase1-scope-boundaries](./phase1-scope-boundaries.md) | Which subsystem buckets Phase 1 ("Controlled Self-Repair") may change (March 2026) |
| [test-taxonomy](./test-taxonomy.md) | Canonical test categories and coverage expectations per subsystem bucket (status: draft, March 2026) |
| [MODULE_TIER_DRIFT_GUARDIAN](./MODULE_TIER_DRIFT_GUARDIAN.md) | Options and risks for guarding module tier drift (status: proposal, plan only) |
| [receipt-enforcement](./receipt-enforcement.md) | How `CampaignExecutor` in `aragora/swarm/campaign.py` persists a receipt when a project finishes |

## Open Decisions and Runbooks

| Page | What it covers |
|------|----------------|
| [gmail-failures-history-decision](./gmail-failures-history-decision.md) | How to handle `gmail_failures.json` in git history (status: open, operator decision required; June 2026) |
| [PR9320_SUCCESSOR_BACKFILL_RUNBOOK](./PR9320_SUCCESSOR_BACKFILL_RUNBOOK.md) | Runbook for the PR #9320 successor historical backfill (status: preparation only; authorizes no terminal action) |

## Related Pages

- [CI_LANES](../CI_LANES.md): which checks run on draft and ready pull requests
- [Tiered merge gate quorum policy](../specs/TIERED_MERGE_GATE_QUORUM_POLICY.md): the design behind the tiered gate
- [Automation merge contract](../briefs/automation-merge-contract.md): the shared merge contract for automation branches
