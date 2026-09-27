# Durable Strategy Capture: Jul 1-5, 2026

**Status:** preservation pass for issue #8856
**Scope:** capture strategy value from the Jul 1-5 operator run into repo-visible
docs, claim manifests, issues, and roadmap links without changing product code.

## Summary

The strongest value from the week was not a single implementation. It was a
repeatable operating pattern: ask evaluative questions that name an outsider,
force live evidence, and authorize one bounded action when the answer is clear.

Most implementation value was preserved in pull requests, tests, receipts, and
issues. The weaker preservation layer was strategy: prompt patterns, question
batteries, roadmap thesis, and adjacent ideas still lived too much in chat or
session memory. Issue #8856 is the parent capture issue for closing that gap.

This document records the durable thesis and points each follow-up at an issue,
artifact, or manifest so the work can be executed by future agents without
reconstructing the chat.

## Best Prompt Patterns And What They Produced

| Prompt pattern | What it forced | Durable result |
|---|---|---|
| "Is what is happening making the project better and more useful to others?" | Split internal improvement from external usefulness; pushed the project toward public proof rather than substrate churn. | Dogfooding artifact `docs/artifacts/2026-07-decision-integrity-dogfooding.md`, ODR/public-verifier work, #8856 capture issue. |
| "Why do we need Jul 29 rather than Jul 4?" | Converted a calendar superstition into data-window triggers. | #8856 item 2: adjudicator stalls, lease-rule quiet days, executor history, issue-close discipline, cancelled-run concurrency. |
| "Nothing is happening" / "why doesn't it work" / "why does 8800 take 30 minutes?" | Treated impatience as instrumentation against silent autonomy failure. | Findings around stale policy, settle/quorum ordering, invoker identity, cancelled-run poisoning, stale rerun traps; captured for taxonomy work under #8856. |
| "What steps do I take over and over, and are any automatable into Aragora?" | Turned operator behavior into product surface. | #8845 Operator Settlement Inbox; #8846 founder status report; follow-on automation issues #8848 and #8849. |
| "Are beads useful, or is meta-beads poor design thinking?" | Forced a live primitive inventory instead of adding another abstraction. | #8851 Convergence Audit; follow-on #8852/#8853; no live bead records until #8851 decides work-primitive authority. |
| "Check whether recent Codex/Factory activity is good, using Aragora tooling and transcripts." | Audited the fleet with the product's own lenses. | Collision/freeze findings, division-of-labor evidence, lease-rule pressure, and #8851 as the coordination authority agenda. |
| "Start from live repo truth; pick the best next bounded unit; proceed." | Made strategy operational: choose one safe unit, execute, stop at a real gate. | Fable goal-cycle artifacts under `.aragora/goal_cycles/`; #8811 exact-head Tier 4 park; #8841 repair after dry-run evidence found a real P2. |
| "Can Aragora adjudicate review nitpicks and escape unproductive cycles?" | Reused debate primitives against Aragora's own review queue. | #8747 primitive-composition plan; review adjudicator work; #8754 merged follow-up; advisory-followup preservation. |
| "Verify this ODR parity issue from live truth, then make the smallest fail-closed fix." | Prevented stale issue text from causing unnecessary production changes. | #8837 parity coverage PR; #8838 unsigned-authenticity follow-up. |
| "How can Zenith-style mission control integrate into Aragora?" | Mapped an external approach onto existing mission primitives. | #8743 native mission-boundary/control PR; future harness enforcement remains proposal work. |
| "Test a public Aragora claim as an outsider and fix the first thing that makes it untrue." | Made outsider reality the proof source. | #8816 README fix; #8815 question batteries; this document and `docs/status/claims/outsider_verifiable_claims.yaml`. |

The meta-pattern: the best prompts were not "do X." They were "is X true, good,
necessary, or useful to someone outside the room; proceed on what the evidence
says."

## Durable Artifact Map

| Artifact | Role |
|---|---|
| #8223 Open Decision Receipt epic | Main decision-semantics product spine: portable receipt, signing, offline verification, crux, calibration, oversight, anchoring. |
| #8815 Epistemic question batteries | Product-side question batteries: falsification, unverified, assumptions, intake interrogation, question personas, scheduled receipt audit. |
| #8845 Operator Settlement Inbox | Productizes repeated operator settlement behavior into packets, scoped action tokens, and exact-head settlement execution. |
| #8851 Convergence Audit | Decides one authority per orchestration concern and whether beads are live work records or deferred/dormant primitives. |
| #8856 Durability capture | Parent issue for Jul 1-5 uncaptured strategy value and wave-4 seeds. |
| #8760 Harvest engine | Mechanism for folding merged, parked, orphaned, and stale outcomes back into backlog decisions. |
| #8846 founder status report | Read-only operator status surface that composes queue blockers, proof-loop health, and latest brief. |
| `docs/artifacts/2026-07-decision-integrity-dogfooding.md` | Frozen public proof that Aragora gates its own merges with its own decision-integrity product. |
| `docs/status/claims/outsider_verifiable_claims.yaml` | Executable-claim manifest for outsider-verifiable public claims and strategy durability. |
| #8837 / #8838 | ODR verifier parity coverage and adjacent unsigned-authenticity gap. |
| #8743 | Native mission-boundary/control implementation. |
| #8754 | Review-adjudicator follow-up merge. |

## Missing Durability Gaps From #8856

These are the remaining wave-4 seeds that need durable execution tracking:

1. **One real outsider (#8858).** A human with no repo context must run the install/demo/
   verify path and every friction must be filed. A simulated agent run does not
   count.
2. **Data-window arming scoreboard (#8859).** The report-only
   [scoreboard](../status/DATA_WINDOW_ARMING_SCOREBOARD.md) replaces the stale
   Jul 29 agenda with live arming data: adjudicator stalls, lease-rule warnings,
   executor history, issue-close discipline, and cancelled-run concurrency.
3. **Reviewer-failure taxonomy (#8860).** Turn naturalistic merge-gate review failures
   into a receipted artifact and adjudicator eval fixtures.
4. **Live dogfood dashboard (#8861).** Regenerate the July dogfooding proof on a schedule
   so receipt, merge, and dissent stats do not go stale.
5. **Skip-audit redesign (#8862).** Count unjustified skips, not all skips; require
   inline skip category and rationale.
6. **Operator question-guide doc (#8863).** Preserve the action-producing prompt forms
   as operator practice, linked to #8815's product-side batteries.
7. **Time-aware truth (#8864).** Claims and roadmap assertions should carry last-verified
   timestamps, freshness SLAs, and stale behavior.

## Updated Thesis

Aragora is not primarily a generic agent runner. It is a decision-integrity
system: an institution for making consequential AI-assisted decisions inspectable,
challengeable, time-aware, and externally verifiable.

The most differentiated pillars are:

1. **Portable ODRs.** The receipt is the unit of truth: a vendor-neutral artifact
   binding decision rationale, adversarial quorum, dissent, confidence, and human
   oversight to a subject that outsiders can verify offline.
2. **Disagreement as evidence.** Model disagreement is not noise to average away.
   It is preserved, classified, adjudicated, and later used to improve gates.
3. **Self-application with public receipts.** The repo's own merges and operator
   loops must keep proving the product under real pressure.
4. **Outsider-verifiable claims.** Public claims should be tested from outside
   the repo first. If the claim fails, make the smallest truthful fix or record
   the blocker.

This keeps external positioning narrower than the maximalist roadmap: say what
is verified, link the proof, and label the rest as roadmap.

## Roadmap And Maximalist Vision

The roadmap should prioritize work that makes the receipt and its surrounding
decision process more load-bearing:

- **Disagreement Atlas.** Publish a living taxonomy of model-review failures with
  receipt links and fixture candidates: diff-blindness, stale-world grounding,
  timezone mistakes, repeated dissent, out-of-scope carousels, and cross-family
  contradictions on settled designs.
- **Institutional epistemics.** Generalize receipts beyond code: vendor choices,
  RFCs, hiring bars, strategy pivots, and policy decisions should carry
  falsification conditions, check-by dates, and reopen rules.
- **Time-aware truth.** Claims need last-verified timestamps, freshness SLAs,
  stale states, and repair/report policies. This applies to public claims,
  roadmap assertions, generated dogfood proof, and issue health.
- **Epistemic middleware.** Export the outsider/falsifier/assumption/deletion
  batteries as a service other agent frameworks can call before acting.
- **Fleet-coordination playbook.** Leases, exact-head evidence, settlement
  ceremonies, and shared-repo coordination are themselves product knowledge.

Deprioritize generic orchestration, connector breadth, chat delivery, and broad
marketplace motion unless they directly strengthen receipts, outsider proof, or
decision afterlife.

## Operator Question Guide

For a reusable live-session version with artifact and stop contracts, see
[Operator Guide: Questions That Produce Action](OPERATOR_ACTION_PROMPTS.md).

Use these prompts when the goal is investigation plus action:

- **Outsider falsification:** "Take our strongest public claim, test it from a
  stranger/customer/auditor point of view against live reality, and fix the first
  thing that makes it untrue."
- **Belief-reality audit:** "What do we believe is working, what evidence would
  prove that wrong, and where is the latest live proof?"
- **Deletion question:** "What should we stop doing, delete, defer, or stop
  routing through agents because it no longer creates proof or user value?"
- **Unverified-assumption audit:** "What did this answer, receipt, plan, or merge
  not verify, and which unverified assumption is most likely to matter?"
- **Should-this-exist prompt:** "Is this work making Aragora more useful to
  outsiders, or only making the system more elaborate?"

These are operator-side practice prompts. The product-side implementation remains
#8815 and should be composed into receipts, intake, modes, and harvest rather
than rebuilt here.

## Follow-Up Tracking

#8856 is the parent epic for this preservation pass. The concrete child issues
are:

- #8858 - one real outsider verification run
- #8859 - [data-window arming scoreboard](../status/DATA_WINDOW_ARMING_SCOREBOARD.md)
- #8860 - Disagreement Atlas artifact and eval fixtures
- #8861 - live dogfood dashboard
- #8862 - skip-audit redesign
- #8863 - operator question-guide doc
- #8864 - time-aware truth layer

These issues should be bead-ready, but this pass deliberately does not create
live bead records. #8851 owns the decision about whether workspace beads become
the live work primitive, an adapter over `nomic.dev_coordination`, or a dormant
surface to archive.
