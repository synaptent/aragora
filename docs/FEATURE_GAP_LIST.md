# Aragora Feature Gap List

> **Living document** — tracks features planned, partially built, or in need of hardening. Updated as items are completed or priorities shift.
> Last updated: March 2026

## How to Read This List

- **P0**: GA blockers — ship nothing else until resolved
- **P1**: GTM launch (April–May 2026) — required for revenue
- **P2**: Product hardening (Q2 2026) — required for enterprise adoption
- **P3**: Scale & revenue (Q3–Q4 2026)
- **P4**: Strategic evolution (2026+)
- **Scaffolding**: Code exists but needs hardening/productization

---

## P0 — GA Blockers

| Feature | Status | Notes |
|---------|--------|-------|
| External penetration test | Vendor outreach in progress | Kickoff target: Mar 3, 2026. Only remaining external blocker. |
| Debate output quality | **VALIDATED — 100% pass rate** | Run 012 (Mar 5): composite 8.38-9.39/10. Diverse benchmark (10 domains): 100% pass, avg composite 0.938. Move to Completed next update. |

---

## P1 — GTM Launch (April–May 2026)

| Feature | Status | Notes |
|---------|--------|-------|
| Agent-first beta via REST API | **In progress** | OpenClaw instances as non-human beta users calling `POST /api/v1/debates`. Self-hosted runner fleet deployed for end-to-end dogfooding and CI validation. |
| GitHub Actions pre-merge gate | **Merged (#648)** | `aragora-review.yml` deployed. Gates on critical findings. Needs branch protection config + beta testing with real repos. |
| Public demo at aragora.ai/demo | **Demo page + share URLs live** | Standalone demo page merged (#648). Share URL persistence fixed. Needs frontend routing verification at aragora.ai/demo. |
| EU AI Act compliance package | **Substantially complete** | Art. 9/12/13/14/15 dedicated bundles + CLI export + compliance scoring + demo script + customer playbook. **Deadline: Aug 2, 2026.** |
| First 2 enterprise pilot engagements | Not started | Closed partnerships — target fintech + healthcare |
| Developer onboarding <10 min | **Quickstart exists** | `docs/QUICKSTART.md` covers install → zero-key demo → real AI → TypeScript → Docker → CLI in 7 steps. Needs cold-start user testing. |

---

## P2 — Product Hardening (Q2 2026)

| Feature | Status | Notes |
|---------|--------|-------|
| Semantic convergence (full embedding) | Partial | Sentence-transformers + TF-IDF + Jaccard wired; difflib still used in some paths. Target: 100% embedding-based. |
| ERC-8004 on-chain deployment | Contracts written | Solidity contracts exist; not deployed to any mainnet. Needs chain endpoint config + gas management. |
| OpenClaw end-to-end demo | Partial | Debate → decision works; execution → receipt integration incomplete. |
| Decision-Integrity UI Workbench | Not started | No frontend for knowledge search, agent leaderboard, pipeline canvas. Backend APIs complete. |
| SOC 2 Type II audit engagement | Not started | 98% controls implemented; formal audit vendor not engaged. |
| Smart provider routing | Not started | Cost/quality-optimized routing across Claude/GPT/Mistral/DeepSeek. |
| Enterprise Communication Hub (#293) | **~55%** | Delivery log + retry queue + circuit breakers + event telemetry wired. Remaining: notification templates, user preferences, inbox→debate trigger, Active Triage dashboard. |

---

## P3 — Scale & Revenue (Q3–Q4 2026)

| Feature | Status | Notes |
|---------|--------|-------|
| Cloud marketplace listings | Not started | AWS Marketplace + Azure Marketplace listings. Infrastructure ready. |
| Vertical packages | Not started | Healthcare (FHIR, HIPAA), Financial (SOX, risk), Legal (contracts, discovery). Guides exist; packages not assembled. |
| Skills Marketplace pilot | Scaffolding | SkillRegistry + SkillMarketplace code exists; no public marketplace endpoint. |
| On-premise deployment productization | Partial | Docker Compose + Helm chart exist; on-prem installer/wizard not built. |
| International expansion / EU data residency | Not started | Data residency controls needed for EU enterprise buyers. |
| 10+ agent coordinated debates | Scaffolding | Current practical limit: 2-6 agents. Coordination infrastructure exists; scale testing needed. |
| Compute escrow mechanism | Not started | Settlement stakes via crypto compute escrow. Design in docs/plans/. |

---

## P4 — Strategic Evolution (2026+)

| Feature | Status | Notes |
|---------|--------|-------|
| Prover-Estimator debate protocol | Design only | Beyond consensus to structured truth-seeking. Replaces/supplements current majority-vote consensus. |
| Cross-verification phase (3-pass hallucination detection) | Design only | Three-agent verification pass post-synthesis. |
| Canvas GUI (8-stage visual DAG) | Partial frontend | Prompt-engine page exists; full 8-stage visual canvas missing. |
| Market resolution mechanism | Design only | Long-horizon settlement claim pricing via prediction market. |
| STOP N-candidate for Nomic Loop | Design only | Multi-plan generation before committing to self-improvement path. |
| Meta-improver for debate protocols | Design only | A/B test protocol variants using Nomic Loop. |
| Obsidian bidirectional sync | Design only | Full sync + bidirectional updates from Obsidian vault. |

---

## P5 — Federation (Future)

| Feature | Status | Notes |
|---------|--------|-------|
| Distributed debates across organizations | Design only | Cross-org debate with privacy-preserving knowledge sharing. |
| Cross-organizational knowledge sync | Design only | Federated knowledge graph across org boundaries. |
| Knowledge federation | Design only | Global KM with distributed consensus. |

---

## Scaffolding — Code Exists, Needs Hardening

| Feature | Current State | Gap |
|---------|---------------|-----|
| Self-improving platform quality | Nomic Loop 100% wired; 82 E2E tests; pipeline hardened (PRs #650, #649, #659 merged); safety gates + gauntlet gate + evolution audit | Diverse benchmark validated (100% pass). Production safety gate requires ENABLE_NOMIC_LOOP=true. |
| Blockchain receipts | SHA-256 cryptographic hashing works | On-chain storage with ERC-8004 (not deployed) |
| Semantic convergence | Embedding detection wired (sentence-transformers) | Not default; some debate paths still use difflib |
| OpenClaw execution | Computer use detection works | Production E2E flow (debate → computer use → receipt) not validated |
| RLM context access | Code complete (283 exports) | No user-facing guide; integration with default Arena config unclear |

---

## Completed — Formerly on This List

These items were planned and are now shipped:

| Feature | Shipped |
|---------|---------|
| Nomic Loop end-to-end | Jan 2026 |
| Knowledge Mound Phase A2 (41 adapters) | Feb 2026 |
| Unified Memory Gateway | Feb 2026 |
| Retention Gate (Titans/MIRAS) | Feb 2026 |
| RBAC v2 (14 resource types, 8 actions) | Feb 2026 |
| Multi-tenancy (tenant isolation + metering) | Feb 2026 |
| Voice/TTS integration | Feb 2026 |
| Pipeline orchestration (4-stage) | Feb–Mar 2026 |
| Compliance CLI (EU AI Act artifact export) | Mar 2026 |
| Settlement hooks | Mar 2026 |
| Gauntlet receipts (SHA-256 audit trails) | Feb 2026 |
| Article 9 dedicated artifact bundle | Mar 2026 |
| Debate output quality (10-domain benchmark) | Mar 2026 |
| Nomic Loop safety gates (production gate, gauntlet, audit) | Mar 2026 |
