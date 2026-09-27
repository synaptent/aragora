# Reviewer-reliability record: gemini fabricated-claim pattern (founder-directed)

> Provenance: copied verbatim from `.aragora/operator-context/20260716T2200Z-gemini-reviewer-reliability-record.md` (gitignored operator-context original) on 2026-07-17 to make the Tier-4 evidence artifact auditable in-repo.

- **Date:** 2026-07-16
- **Recorded by:** Devin CLI session (founder directive: "log gemini's fabricated
  claims in the reviewer-reliability record — that's now a repeat pattern for
  gemini and its dissent shouldn't count anywhere")
- **Scope:** gemini reviewer family (Antigravity/Gemini API lane) acting as a
  merge-quorum evidence producer.

## Documented fabrications (PR #9075 review rounds, 2026-07-16)

1. **Round G1** (comment 4996054771 context): claimed Claude Fable 5 "was
   released on July 16, 2026" and therefore violated the 14-day availability
   rule. FALSE — Fable 5 has operated in this repo's own tooling since before
   Jul 9 (consult-fable skill default; this session's own reviewer lane), and
   the canonical catalog records release 2026-06-20. Refuted on the PR.
2. **Round G2** (next roll, same head-family): REPEATED the same fabricated
   release date after the refutation was posted, and added a false
   METRICS-drift claim (the test-count delta belonged to the PR's own earlier
   lineage commits, regenerated per the drift-gate contract).
3. Same round: demanded a pricing row for `anthropic/claude-opus-4-8` (dash
   spelling) — a route id that does not exist in the OpenRouter catalog
   (verified live 2026-07-16). Inventing rows for nonexistent routes is
   catalog pollution.

Positive contribution for balance: gemini's G1 round also produced one
genuine P2 (missing `openai/gpt-5.5` / `anthropic/claude-opus-4.8` alias
pricing rows), fixed at 53bb7798a449.

## Founder-directed disposition

- gemini dissent is NOT to be counted anywhere pending roster change.
- Reviewer roster change: replace the gemini evidence lane with **gpt-5.6
  (Sol)** and/or **Kimi K3** per founder message of 2026-07-16. This touches
  `aragora/swarm/quorum_evidence.py` (quorum family eligibility) — **Tier 4**,
  requires founder exact-head settlement. To be prepared as its own PR;
  NOT to be folded silently into another lane.
- Note: Sol itself is soak-held for merge-authority surfaces until
  2026-07-23; Kimi K3 needs live verification + catalog entry before it can
  produce evidence. Roster PR should encode whichever the founder settles.

## Verification pointers

- PR #9075 comments: 4996054771 (refutation), 4996161945 (second refutation
  + treadmill accounting), 4996233860 (adjudication packet).
- Catalog release/soak dates: `aragora/models/catalog.py` (#9355).

---

## In-repo addendum (2026-07-17, PR #9363 settlement trail — not part of the verbatim record above)

`docs/REVIEW_AUTHORITY_PRINCIPLES.md::Family-additive change governance` expects
a `docs/specs/` design document as the Tier-4 pre-approval artifact for a change
to family counting authority. For this demotion, the operator approved
substituting this committed record plus PR #9363's Tier-4 exact-head settlement
for that design-doc requirement. This is an operator-approved exception scoped
to this demotion only — not a precedent relaxing the design-doc requirement for
future family changes.
