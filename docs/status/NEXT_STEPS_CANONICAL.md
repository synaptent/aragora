# Next Steps (Canonical)

Last updated: 2026-03-07

This is the single source of truth for short-horizon execution priorities.
`docs/CANONICAL_GOALS.md` defines what Aragora is and why.
`docs/plans/ARAGORA_EVOLUTION_ROADMAP.md` defines the long-range architecture and moat.
`docs/FEATURE_GAP_LIST.md` is the current delivery/backlog truth.
This file defines execution order.

## Current Reality

- The product thesis is intact: Aragora is building a decision-integrity platform, not just a debate engine.
- The repo has shipped major backbone, compliance, swarm, and OpenClaw milestones, but `main` still has operational truthfulness gaps in CI/CD and deployment.
- Short-horizon work should optimize for launch credibility: what is claimed in roadmap/status docs must match what actually works on `main`.

## Execution Order

### 1) Mainline CI/CD and Release Truthfulness
- Owner: Platform + DevOps
- Goal: `main` should be a trustworthy signal of ship readiness, not a mixture of real regressions and policy/tooling false positives.
- Acceptance:
  - `Branch Discipline` no longer flags merged-PR commits on `main` as direct pushes.
  - `Deploy Documentation` succeeds on the current runner image or uses a portable archive path that does not require missing host tools.
  - `Deploy to EC2` handles unhealthy or invalid canary instance state explicitly and does not fail rollback because the target instance is unusable.
  - `Main Required Checks Auto Revert` stops flapping on the same underlying failures.
- Evidence today:
  - `Branch Discipline` failed on `739ab5e`, `b441b2d`, and `ea402d2` even though they are merged-history commits.
  - `Deploy Documentation` failed because `gtar` is not present on the runner.
  - `Deploy to EC2` failed because canary instance `i-0dbd51f74a9a11fcc` was not in a valid state.

### 2) GTM Proof Closeout
- Owner: Product + Compliance + GTM
- Goal: convert the "98% GA-ready" narrative into evidence-backed launch readiness.
- Acceptance:
  - EU AI Act customer playbook and appendix are complete and externally usable.
  - External pentest engagement is underway with tracked remediation ownership.
  - SOC 2 Type II audit engagement is initiated.
  - At least two real pilot lanes are actively being converted, not just named in docs.
- Source of truth:
  - `docs/FEATURE_GAP_LIST.md` P0-P2
  - `ROADMAP.md` Q2 2026 priorities

### 3) Agent-First Beta and Public Demo Productization
- Owner: Product + Runtime
- Goal: make the shipped beta and demo surfaces reliable enough for external users, not just internal dogfood.
- Acceptance:
  - Public demo paths remain stable and are verified from the external surface.
  - Agent-first beta workflows (`aragora review`, REST/API, fleet runner path) have a documented and validated customer/operator path.
  - Inbox/comms surfaces are validated end-to-end from intake to debate to action/receipt where claimed.
  - GitHub review gate strategy is explicit: either intentionally manual-only or re-enabled for pre-merge use.

### 4) Prompt-to-Execution Golden Path
- Owner: Pipeline + Decision Integrity
- Goal: deliver the differentiated core loop from vague intent to executable, verified outcome.
- Acceptance:
  - Duplicate-create planning defects are handled deterministically rather than by prompt wording alone.
  - Prompt/spec/debate/execution handoff is reliable enough for a founder or operator to use without manual archaeology.
  - The highest-value path is coherent across CLI, API, and UI surfaces.
  - Receipt/provenance output remains clear when the system executes, fails, or blocks.
- Why this is core:
  - This is the wedge described in `docs/CANONICAL_GOALS.md` Pillar 3 and in `docs/plans/ARAGORA_EVOLUTION_ROADMAP.md`.

### 5) Swarm and Worktree Operating Discipline
- Owner: Platform + Runtime
- Goal: keep multi-agent velocity without reintroducing integration churn.
- Acceptance:
  - Managed worktree maintenance respects all supported session lock types.
  - One merge lane exists for merge-eligible work; cleanup/reconciliation does not race live sessions.
  - Valuable work is preserved before cleanup of stale worktrees, branches, or stashes.
  - Session/worktree state is observable enough that humans can tell what is active, stale, merged, or abandoned.
- Recent progress:
  - PR #751 fixed maintainer detection of Claude and Nomic session locks.

### 6) Strategic Moat Hardening
- Owner: Research + Platform
- Goal: close the gap between shipped scaffolding and the long-term differentiated moat.
- Acceptance:
  - Arena/provider routing is integrated, not just shipped as standalone optimization logic.
  - OpenClaw execution is validated in real production-like loops.
  - Security roadmap items with highest leverage stay visible: trust-tier taint propagation, signed context manifests, and external verification gates.
  - The repo continues converging on the full decision-integrity platform rather than fragmenting into unrelated surfaces.

## Operating Rules
- `docs/FEATURE_GAP_LIST.md` is the delivery truth; `ROADMAP.md` and other summaries must reconcile to it.
- No document should claim "only one blocker remains" unless `main` CI/CD and deployment signals support that claim.
- One merge lane for operational fixes; avoid parallel merge-eligible churn.
- Preserve value before deletion: every stash/worktree/branch should map to a destination commit, PR, or explicit discard decision.
- Required checks must always emit a terminal status.
- If priorities change, update this file first, then update linked summaries.
