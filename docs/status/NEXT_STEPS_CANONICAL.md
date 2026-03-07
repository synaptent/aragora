# Next Steps (Canonical)

Last updated: 2026-03-07

This is the single source of truth for short-horizon execution priorities.
`docs/CANONICAL_GOALS.md` defines what Aragora is and why.
`docs/plans/ARAGORA_EVOLUTION_ROADMAP.md` defines the long-range architecture and moat.
`docs/FEATURE_GAP_LIST.md` is the current capability/backlog truth.
`ACTIVE_EXECUTION_ISSUES.md` links this execution order to the live GitHub issue backlog.
This file defines execution order.

## Current Reality

- The full vision remains the goal; the near-term requirement is sequencing, not scope reduction.
- The moat is the receipt-gated decision kernel: prompt/spec/debate/consensus/cryptographic receipt/policy-gated action.
- GitHub issues now carry active execution status, owners, and acceptance criteria. Docs should summarize context and order, not act as the only operational backlog.
- Truthfulness hardening is already underway on `main`: [#807](https://github.com/synaptent/aragora/issues/807) and [#808](https://github.com/synaptent/aragora/issues/808) are complete, and [#809](https://github.com/synaptent/aragora/issues/809) is the current backlog-canonicalization tranche.
- Surface area should be productized sequentially, not hidden or allowed to drift.

## Execution Order

### 1) Truthfulness And Backlog Canonicalization
- Tracking: [#804](https://github.com/synaptent/aragora/issues/804), [#807](https://github.com/synaptent/aragora/issues/807), [#808](https://github.com/synaptent/aragora/issues/808), [#809](https://github.com/synaptent/aragora/issues/809)
- Goal: `main` and current-source docs should stay truthful, and the active backlog should live in GitHub instead of only in Markdown.
- Acceptance:
  - Launch/readiness claims match what works on `main`.
  - Self-host/readiness docs and gates are evidence-backed.
  - Current execution lanes are tracked in GitHub with owners, priorities, and acceptance criteria.
  - Canonical planning docs link to the issue map instead of carrying operational status alone.

### 2) Decision Integrity Kernel Unification
- Tracking: [#805](https://github.com/synaptent/aragora/issues/805), [#810](https://github.com/synaptent/aragora/issues/810), [#811](https://github.com/synaptent/aragora/issues/811), [#812](https://github.com/synaptent/aragora/issues/812), [#813](https://github.com/synaptent/aragora/issues/813), [#814](https://github.com/synaptent/aragora/issues/814), [#815](https://github.com/synaptent/aragora/issues/815), [#816](https://github.com/synaptent/aragora/issues/816)
- Goal: unify `prompt -> specification -> adversarial debate -> consensus/dissent -> cryptographic decision receipt -> policy gate -> execution` as one canonical runtime.
- Why now:
  - This is the architectural center of Aragora's differentiation.
  - Provider routing, OpenClaw, 10+ agent scale, and ERC-8004 only matter if they plug into the same receipt-gated kernel.

### 3) Sequential Surface Productization
- Tracking: [#806](https://github.com/synaptent/aragora/issues/806), [#817](https://github.com/synaptent/aragora/issues/817), [#818](https://github.com/synaptent/aragora/issues/818), [#819](https://github.com/synaptent/aragora/issues/819), [#820](https://github.com/synaptent/aragora/issues/820)
- Goal: productize every exposed surface in waves, starting from the inbox trust wedge and public proof surfaces.
- Rules:
  - The wedge proves the kernel; it does not replace the whole vision.
  - Keep partial surfaces visible, but label and harden them honestly.
  - Prefer one surface wave at a time over broad parallel productization.

### 4) Assurance And GTM Closeout (Kept Warm, Not Main Product Lane)
- Tracking: [#273](https://github.com/synaptent/aragora/issues/273), [#274](https://github.com/synaptent/aragora/issues/274), [#509](https://github.com/synaptent/aragora/issues/509)
- Goal: keep enterprise assurance truthfulness real without turning pentest/GTM work into the primary execution lane before the core kernel is unified.
- Acceptance:
  - Open assurance work remains visible, owned, and sequenced.
  - Docs do not overclaim GA or launch readiness while these items remain open.

## Operating Rules
- GitHub issues are the live execution backlog; docs summarize context, order, and capability posture.
- `ACTIVE_EXECUTION_ISSUES.md` must stay aligned with the current issue set.
- `docs/FEATURE_GAP_LIST.md` is the capability/backlog truth for planned and partial features; execution status lives in GitHub.
- `ROADMAP.md` and other summary docs must reconcile to `NEXT_STEPS_CANONICAL.md`, `docs/FEATURE_GAP_LIST.md`, and the issue map.
- No document should claim "only one blocker remains" unless `main` CI/CD and deployment signals support that claim.
- Productize exposed surface area sequentially; do not broaden active implementation lanes faster than the kernel can support.
- If priorities change, update the GitHub issues first, then update this file and the linked summaries.
