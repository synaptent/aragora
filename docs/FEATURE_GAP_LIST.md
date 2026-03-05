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
| Debate output quality | Substantially improved — needs consistency validation | Run 012 (Mar 5): composite scores 8.38-9.39/10 (was 3.46-3.55). Practicality scoring fixes merged. Goal: validate 80%+ pass rate consistency across diverse tasks. |

---

## P1 — GTM Launch (April–May 2026)

| Feature | Status | Notes |
|---------|--------|-------|
| 3 beta users with `aragora review` | Not started | Need real PRs reviewed end-to-end via Aragora |
| GitHub Actions pre-merge gate | Not started | AI code review integration for CI pipelines |
| Public demo at aragora.ai/demo | Not started | Live shareable debate demo with persistence |
| EU AI Act compliance package | Partial | Artifact bundles generated for Art. 12, 13, 14. Art. 9 conformity checking included in the report; dedicated Art. 9 artifact bundle is planned (see P2). CLI export works; documentation and customer playbook needed. **Deadline: Aug 2, 2026.** |
| First 2 enterprise pilot engagements | Not started | Closed partnerships — target fintech + healthcare |
| Developer onboarding <10 min | Not measured | No validated onboarding flow; needs user testing |

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
| Article 9 dedicated artifact bundle | Not started | `ComplianceArtifactGenerator` currently produces Art. 12/13/14 bundles only. Art. 9 (Risk Management) conformity is checked via `ConformityReportGenerator` but has no dedicated `article_9_risk_management.json` output file. Needs `Article9Artifact` dataclass + generator method + CLI export. |

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
| Self-improving platform quality | Nomic Loop 100% wired; 66 E2E tests passing; Run 012 scores 8.38-9.39/10 | Validate 80%+ pass rate consistency across diverse tasks (not just dogfood) |
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
