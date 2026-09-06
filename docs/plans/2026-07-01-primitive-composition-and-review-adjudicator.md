# Primitive Composition & the Review Adjudicator

**Date:** 2026-07-01
**Author:** Claude Code session (with founder, scarmani)
**Status:** proposed — M0 ready to start; M1-M4 are bounded consolidation missions
**Tracking:** epic #8747 · M0 issue #8748 · this doc PR #8746
**Related:** #8574 (severity-gated dissent), #8729/#8739/#8741 (advisory-settle), #8738 (enablement),
#8745 (frontier reviewer default), docs/plans/2026-06-30-advisory-dissent-settlement-gate-packet.md

## Thesis (two, tightly linked)

1. **Adjudicate review deadlocks with Aragora's own primitives.** The PR-review "nitpick
   treadmill" (two adversarial reviewers who can stall for rounds without both reaching PASS on a
   substantial diff, each surfacing fresh advisory `[P2]/[P3]` nits every round) is a
   *decision-adjudication* problem — exactly what this platform exists to solve. Clean 2-0 remains
   the preferred path after real revisions (a good PR does converge — see #8730); adjudication is
   the *bounded fallback* for a genuine advisory-only stall, never a replacement for earning PASS.
   We already have the machinery; we are not composing it against our
   own gate.

2. **Consolidate by composition, not by rewrite.** The repo is *sprawling around a coherent core*.
   The fix is to make subsystems **compose** the primitives that already exist (Arena, Convergence,
   Trickster, Judge, Prover-Estimator, protocols, base_store) instead of reimplementing them — done
   incrementally, each step shipping value. A big-bang re-modularization is the loop-producing-loop
   substrate-churn we explicitly avoid.

The Review Adjudicator (M0) is the **flagship proof** of thesis 2: the first artifact that composes
existing primitives to solve a real internal pain and emits the audit-ready `DecisionReceipt` the
product already sells.

## Problem, named precisely

### Nitpick treadmill
Adversarial reviewers have **no cost to raising a nit, no convergence pressure, and no distinction
between material and immaterial findings**. Observed live on #8738: claude and grok alternated PASS
and CHANGES-REQUESTED across four rounds, each round a different advisory nit; grok eventually
objected to the *policy itself*. Structural, not a reviewer-quality problem.

Current mitigations are all **policy thresholds** (necessary, shipped, in the right order):
- severity gating (`[P0]/[P1]` block, `[P2]/[P3]` advisory) — #8574
- advisory-settle for Tier 0-2 (hard `[P0]/[P1]` bar intact) — #8741/#8738
- frontier reviewer default (claude+openai) — #8745

The **missing layer is adjudication of the findings themselves**: deciding which advisory dissent is
*materially grounded* vs. *rhetorically-polished-but-thin*. That is an intelligence problem, and we
have the primitives for it.

### Sprawl (evidence)
- **351** `Store` classes (should be ~3); **41** SQLite/Postgres store impls
- **528** `Config` classes (should be ~30)
- **29** `Orchestrator` classes (should be ~2: `Arena` + domain composition)
- 145 top-level modules advertised as equal peers in CLAUDE.md, mixing battle-tested (`debate`:
  659 test files) with scaffolding (`blockchain`, `prediction`, `essay`, `heterogeneity`)
- `swarm`, `nomic`, `fabric` avoid `core`/`protocols` entirely and reimplement locally

Diagnosis: *"a monolith that grew into modules,"* not *"a modular system that composed primitives."*
The primitives exist; subsystems reimplement instead of compose.

## Reusable primitives (production-real unless noted)

| Primitive | Location | Role in adjudication |
|---|---|---|
| `ConvergenceDetector` | `aragora-debate/.../convergence.py` | Detect stalemate: N rounds, unchanged dissents, advisory-only |
| `EvidencePoweredTrickster` + `EvidenceQualityAnalyzer` | `.../trickster.py`, `.../evidence.py` | Score each finding's evidence density / specificity / grounding; suppress thin nits |
| `ProverEstimatorEngine` | `aragora/debate/prover_estimator.py` | Per-claim evidence-weighted probability; `obfuscation_flag` |
| `CruxDetector` / crux-mode | `aragora/reasoning/crux_detector.py`, `aragora/debate/crux_mode.py` | Name the one load-bearing disagreement (framework real; PR-bridging is a fast-follow) |
| `LLMJudge` | `aragora/evaluation/llm_judge.py` | Score findings on evidence/reasoning dimensions; tie-break |
| `ConsensusBuilder` / `DecisionReceipt` | `aragora/debate/consensus.py`, gauntlet receipts | Serialize the adjudication + dissent + severity into a verifiable receipt |
| Quorum gate | `aragora/swarm/quorum_evidence.py`, `aragora/cli/commands/review_queue.py` | Where the adjudicator plugs into the stall path |

## Milestones

### M0 — Review Adjudicator (flagship; bounded)
Fire **only when the quorum stalls** (not on every PR): convergence detector reports *stuck +
advisory-only*, then:
1. score each disputed finding through the evidence/trickster scorer;
2. if **all** are below the evidence bar → **auto-settle**, file findings as follow-ups;
3. if a finding is **evidence-backed** → it is never discarded; by default grounded `[P2]`/`[P3]`
   findings stay capped at advisory follow-up per severity-gated dissent, while callers may
   explicitly promote grounded advisory findings to blocking;
4. if reviewers disagree on something **material** → crux-finder names it, **escalate to human with
   the crux stated** (not a wall of nits);
5. emit a `DecisionReceipt` either way.

**Scope guardrail:** wire `ConvergenceDetector` + the Trickster/evidence scorer into the
`quorum_evidence` stall path and emit a receipt. Crux-finder PR-bridging is a **fast-follow**, not a
blocker. No new primitives — compose existing ones. Tier: this touches merge-authority code
(`review_queue.py`/`quorum_evidence.py`) → **Tier 4**, human-settled.

**Acceptance:**
- On a synthetic stuck cycle (advisory-only dissent, ≥2 unchanged rounds), the adjudicator settles
  and emits a receipt naming the suppressed findings.
- A single evidence-backed `[P2]` (with citation/specific repro) is **not** suppressed; default M0
  caps it at advisory follow-up, with an explicit promotion policy available for callers that want
  it to block.
- A material disagreement produces a crux escalation, not an auto-settle.
- Behavior is opt-in behind a flag; default OFF until proven.

### M1 — Tier the module surface (½ day; legibility)
Split CLAUDE.md's 145 modules into `core / stable / integrated / scaffold / experimental`. Stops the
fleet (and humans) from treating aspirational modules as load-bearing. Pure docs; no code risk.

### M2 — Unify storage on `storage/base_store.py`
Collapse the 41 SQLite/Postgres stores incrementally — **one module per PR**, tests as the safety
net. Target ~3 canonical implementations. No big-bang.

### M3 — Compose orchestration
New orchestrators must wrap `Arena` + domain logic; retire duplicate conductors opportunistically as
they're touched. Target: `Arena` + a small set of domain orchestrators, not 29.

### M4 — Codify one end-to-end integration path
A single reference: `debate → receipt → channel`, so integration knowledge stops living implicitly
in server/CLI/control_plane.

## Guardrails (substrate-freeze discipline)
- **No big-bang rewrite.** Every milestone is independently shippable and reversible.
- **Compose, don't build.** If a milestone tempts a new primitive, stop — the inventory above almost
  certainly already has it.
- **M0 first.** It pays for itself on the next stuck PR and validates the whole "compose the
  primitives" thesis before we touch the 351 stores.
- **Bounded missions.** Each milestone is one mission with explicit acceptance; no open-ended
  refactor crusades.

## Sequencing
M0 (adjudicator) → M1 (tier the surface) → M2/M3 (consolidate, opportunistic) → M4 (codify). M0 and
M1 can run in parallel; M2-M4 are steady-state hygiene, not a sprint.
