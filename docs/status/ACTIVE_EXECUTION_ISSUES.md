# Active Execution Issues

Last updated: 2026-03-07

This document links Aragora's current execution program to the live GitHub issue tracker.

- Docs explain thesis, roadmap, and capability posture.
- GitHub issues track active execution status, owners, priorities, and acceptance criteria.
- Use [NEXT_STEPS_CANONICAL](NEXT_STEPS_CANONICAL.md) for execution order and this file for the live issue map.

## Current Execution Order

1. Truthfulness and backlog canonicalization
2. Decision Integrity Kernel unification
3. Sequential surface productization
4. Assurance closeout kept warm, not the main product lane

## Truthfulness And Backlog Canonicalization

Epic: [#804](https://github.com/synaptent/aragora/issues/804)

Current tranche: [#809](https://github.com/synaptent/aragora/issues/809)

Recently completed:
- [#807](https://github.com/synaptent/aragora/issues/807) `CLOSED` - Make launch truthfulness blocking
- [#808](https://github.com/synaptent/aragora/issues/808) `CLOSED` - Make self-host readiness truthful and PR-gated

| Issue | State | Priority | Owner | Milestone | Scope |
|------|-------|----------|-------|-----------|-------|
| [#807](https://github.com/synaptent/aragora/issues/807) | Closed | `priority:critical` | `owner:team-platform` | `2026-M1 Truthfulness + Decision Integrity Core` | Make launch truthfulness blocking |
| [#808](https://github.com/synaptent/aragora/issues/808) | Closed | `priority:high` | `owner:team-platform` | `2026-M1 Truthfulness + Decision Integrity Core` | Make self-host readiness truthful and PR-gated |
| [#809](https://github.com/synaptent/aragora/issues/809) | Open | `priority:high` | `owner:team-platform` | `2026-M1 Truthfulness + Decision Integrity Core` | Canonicalize the active backlog into GitHub issues |

## Decision Integrity Kernel Unification

Epic: [#805](https://github.com/synaptent/aragora/issues/805)

| Issue | State | Priority | Owner | Milestone | Scope |
|------|-------|----------|-------|-----------|-------|
| [#810](https://github.com/synaptent/aragora/issues/810) | Open | `priority:high` | `owner:team-core` | `2026-M1 Truthfulness + Decision Integrity Core` | Add prompt -> specification -> DecisionPlan bridge |
| [#811](https://github.com/synaptent/aragora/issues/811) | Open | `priority:high` | `owner:team-core` | `2026-M1 Truthfulness + Decision Integrity Core` | Collapse prompt/canvas/pipeline to one canonical execution runtime |
| [#812](https://github.com/synaptent/aragora/issues/812) | Open | `priority:high` | `owner:team-core` | `2026-M1 Truthfulness + Decision Integrity Core` | Require cryptographic decision receipts before all action-taking |
| [#813](https://github.com/synaptent/aragora/issues/813) | Open | `priority:high` | `owner:team-core` | `2026-M3 Strategic Moat Scale-Out` | Integrate ProviderRouter into runtime agent selection |
| [#814](https://github.com/synaptent/aragora/issues/814) | Open | `priority:high` | `owner:team-core` | `2026-M3 Strategic Moat Scale-Out` | Make OpenClaw action dispatch real |
| [#815](https://github.com/synaptent/aragora/issues/815) | Open | `priority:high` | `owner:team-core` | `2026-M3 Strategic Moat Scale-Out` | Scale adversarial orchestration to 10+ agents |
| [#816](https://github.com/synaptent/aragora/issues/816) | Open | `priority:high` | `owner:team-core` | `2026-M3 Strategic Moat Scale-Out` | Deploy ERC-8004 identity and settlement integration |

## Sequential Surface Productization

Epic: [#806](https://github.com/synaptent/aragora/issues/806)

| Issue | State | Priority | Owner | Milestone | Scope |
|------|-------|----------|-------|-----------|-------|
| [#817](https://github.com/synaptent/aragora/issues/817) | Open | `priority:high` | `owner:team-integrations` | `2026-M2 Surface Productization` | Consolidate inbox and shared inbox onto the trust wedge |
| [#818](https://github.com/synaptent/aragora/issues/818) | Open | `priority:high` | `owner:team-integrations` | `2026-M2 Surface Productization` | Turn the public demo into a live proof surface |
| [#819](https://github.com/synaptent/aragora/issues/819) | Open | `priority:high` | `owner:team-integrations` | `2026-M2 Surface Productization` | Make the integrations UI trustworthy and non-demo by default |
| [#820](https://github.com/synaptent/aragora/issues/820) | Open | `priority:medium` | `owner:team-integrations` | `2026-M2 Surface Productization` | Productize Wave 2 surfaces: SME onboarding, spectate, and conditional public endpoints |

## Assurance And GTM Issues Kept Warm

These remain open and real, but they are not the primary product lane while the decision kernel and proof surfaces are still being unified.

| Issue | State | Priority | Owner | Milestone | Scope |
|------|-------|----------|-------|-----------|-------|
| [#273](https://github.com/synaptent/aragora/issues/273) | Open | `priority:critical` | `owner:team-risk` | `2026-M2 Channel and FinOps` | Enterprise Assurance Closure epic |
| [#274](https://github.com/synaptent/aragora/issues/274) | Open | `priority:critical` | `owner:team-risk` | `2026-M2 Channel and FinOps` | Execute external penetration test and remediate findings |
| [#509](https://github.com/synaptent/aragora/issues/509) | Open | `priority:critical` | `owner:team-risk` | `none` | Pentest vendor selection and scope sign-off |

## Operating Rule

When the execution program changes:

1. update the GitHub issues first
2. update [NEXT_STEPS_CANONICAL](NEXT_STEPS_CANONICAL.md)
3. update this issue map and any linked summary docs
