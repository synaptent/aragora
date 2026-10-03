---
title: Aragora Feature Gap List
description: Aragora Feature Gap List
---

# Aragora Feature Gap List

> **Living document** — tracks features planned, partially built, or in need of hardening. Updated as items are completed or priorities shift.
> **For current execution sequencing** (what to work on right now, what is gated, what is delayed), defer to [docs/status/NEXT_STEPS_CANONICAL.md](./next-steps-canonical). Active execution status is tracked in [docs/status/ACTIVE_EXECUTION_ISSUES.md](./active-execution-issues) and linked GitHub issues. **This file is the long-horizon capability and productization backlog** — the P0–P4 tiering expresses intended ordering, not dispatch readiness.
> **For the unified finish-line vision and stage model**, see [docs/CANONICAL_GOALS.md](./canonical-goals). The Decision Integrity Core tranche (crux engine, executable claims, proof-carrying code) is gated on Foreman reliability per [docs/plans/EPISTEMIC_CI_AND_CRUX_ENGINE.md](plans/EPISTEMIC_CI_AND_CRUX_ENGINE.md).
> **For concrete 30/90/365-day timing**, the [3-Horizon Execution Roadmap](plans/2026-04-18-3-horizon-roadmap.md) provides the sprint-level overlay. P0/P1 items map to H1/H2 deliverables; P2/P3 items map to H3; P4 items are the deferred maximalist backlog.
> Last updated: July 11, 2026 (dormant-module activation criteria and disposition policy, [#9046](https://github.com/synaptent/aragora/issues/9046))
> March 2026 priority reframe: product cohesion and PMF proof come before certification. Pentest / SOC 2 stay tracked, but they are no longer the first blocker lane.

## Revision 2026-06-11 — ODR direction (epic [#8223](https://github.com/synaptent/aragora/issues/8223))

This revision reconciles the list against the June 11, 2026 strategy/market/capability investigation (recorded in epic #8223). Three changes:

1. **Active direction:** the [Open Decision Receipt (ODR) tranche](#active-direction--open-decision-receipt-odr-june-2026) is now the priority spine — own the decision-semantics layer (rationale + adversarial quorum + calibrated confidence + crux + human attestation) above action-level agent governance, where Microsoft's Agent Governance Toolkit stops.
2. **Built-but-dormant honesty:** a [dormant-capability table](#built-but-dormant--july-11-2026-capability-map) marks engines that exist in the codebase but have little or no productized surface, so future agents stop re-planning them from scratch.
3. **De-scope annotations:** entries the proof-first shift and the steering-leverage selection filter deliberately excluded (breadth without steering value) are annotated in place, not deleted — the history stays legible.

## Revision 2026-07-11 — Dormant-module activation policy ([#9046](https://github.com/synaptent/aragora/issues/9046))

The dormant-capability map now names the evidence gate, minimum external
exposure, and single open owner issue for every row. These are activation
criteria, not dispatch instructions: a row stays parked until its trigger is
observed and its owning issue authorizes a bounded implementation slice.

The founder decision recorded in [#9046](https://github.com/synaptent/aragora/issues/9046)
on July 8 supersedes removal as the disposition for two June de-scopes without
activating either module: Blockchain expansion remains parked behind CP-4,
with Rekor serving receipt anchoring, and Marketplace remains P3/de-scoped
until an external design partner supplies the activation evidence.

## Revision 2026-08-26 — External research intake (X bookmarks + likes)

Founder bookmark triage ([`docs/research/2026-08-26-x-bookmarks-triage.md`](research/2026-08-26-x-bookmarks-triage.md))
established a standing intake pipeline for externally sourced ideas. These rows are capability
backlog, **not** dispatch priority — the ODR tranche remains the execution spine. Dogfooding rule:
intake candidates are ranked by an Aragora debate and every filed issue links the DecisionReceipt.

| Item | Status | Notes |
|------|--------|-------|
| X bookmarks/likes live ingestion | In progress (this revision) | OAuth2 user-context (`bookmark.read` + `like.read`, owned reads ~$0.001) on the existing `aragora/ideacloud/ingestion/twitter_bookmarks.py` / `twitter_likes.py`; data-export `--file` mode already shipped and remains the zero-auth bridge. |
| MetaPlanner `candidate_goals` | In progress (this revision) | First-class externally supplied candidate list for debate ranking with receipts; removes the 5-item `recent_issues` cap in `build_debate_topic`. |
| Recurring X-intake digest | Planned | Clone of the codex-insights digest pattern: fetch since-cursor → ideacloud ingest/dedup → digest artifact + SHA-256 receipt; creates nothing (issue filing stays human-triggered). |
| Grok Agent-Tools x_search enrichment | Investigation | xAI deprecated Live Search (the 410 fallback in `grok.py` already routes around it); investigate the Agent Tools API before implementing via `_build_extra_payload`. |

## Active Direction — Open Decision Receipt (ODR, June 2026)

Epic: [#8223](https://github.com/synaptent/aragora/issues/8223). Sequencing: ODR-1→2→3 form the spine (a receipt a stranger can verify); 4/5/6 enrich the payload; 7 makes anchoring public. These supersede the P0/P1 ordering below as the current execution priority.

| Item | Issue | Value rationale (one line) |
|------|-------|----------------------------|
| ODR-1 vendor-neutral receipt content profile (JSON Schema + JCS, SCITT-ready) | [#8224](https://github.com/synaptent/aragora/issues/8224) | A receipt format third parties can consume is the wedge; everything else rides on it. |
| ODR-2 Ed25519 public-key signing for DecisionReceipts | [#8225](https://github.com/synaptent/aragora/issues/8225) | HMAC = shared secret = receipts only verify inside Aragora; public-key signing makes them verifiable by strangers. |
| ODR-3 `aragora-verify` standalone offline verifier (PyPI) + `/api/receipts/verify` | [#8226](https://github.com/synaptent/aragora/issues/8226) | The verifier is the product claim: anyone can check a receipt without trusting (or running) Aragora. |
| ODR-4 expose the crux finder (API, CLI flag, SDK, crux set in receipts) | [#8227](https://github.com/synaptent/aragora/issues/8227) | The crux is the highest-value decision-semantics payload; the engine exists with no public surface (see dormant table). |
| ODR-5 calibration report API + calibrated confidence in receipts | [#8229](https://github.com/synaptent/aragora/issues/8229) | Calibration data is collected but opaque to users; auditable confidence is what regulators and buyers actually ask for. |
| ODR-6 human-oversight attestation + EU AI Act Art. 14 / NIST evidence pack | [#8230](https://github.com/synaptent/aragora/issues/8230) | Proof an accountable human governed the decision — demanded by Art. 14 with no tooling owner anywhere. |
| ODR-7 Sigstore Rekor public anchoring for receipts + intent-chain heads | [#8231](https://github.com/synaptent/aragora/issues/8231) | Public transparency-log anchoring closes the tamper-evidence gap without running our own infrastructure. |
| Decision-stakes model routing (wire dormant Pareto optimizer, record rationale in receipts) | [#8233](https://github.com/synaptent/aragora/issues/8233) | "Why was this model trusted with this decision, at what cost" is itself decision-semantics; cost-per-settled-PR becomes a measurable claim. |
| Jury composition optimizer (min-cost heterogeneous quorum for target reliability) | [#8234](https://github.com/synaptent/aragora/issues/8234) | Turns ELO + calibration + outcome data into cheaper quorums with provable reliability targets. |

## Built But Dormant — July 11, 2026 capability map

Engines that exist and substantially work, but have little or no productized surface. Statuses below were re-verified against the codebase on 2026-07-11 (module paths listed). Honesty rule: "dormant" means *unexposed or unused*, not *unbuilt*.

| Capability | Where it lives | Verified state (2026-07-11) | Activation trigger | Minimum first exposure | Owner issue |
|------------|----------------|-----------------------------|--------------------|------------------------|-------------|
| Crux detector | `aragora/reasoning/crux_detector.py`, `aragora/debate/crux_mode.py` | Engine and internal operator CLI surfaces exist; public API, SDK, and receipt exposure remain absent. | ODR-4 is approved to expose decisive disagreement after the receipt spine is stable. | Embed one crux set in an ODR and expose the same read-only result through one external route before adding broader SDK coverage. | [#8227](https://github.com/synaptent/aragora/issues/8227) |
| Blockchain / ERC-8004 | `aragora/blockchain/` | Registries, staking, receipt anchoring, and wallet primitives exist, but no network deployment affects the product loop. | CP-4: a settled reputation delta is ready to change real dispatch eligibility; Rekor remains the anchoring path before then. | Produce one non-production, receipt-linked stake → resolution → reputation-delta proof without making blockchain the default anchor. | [#9046](https://github.com/synaptent/aragora/issues/9046) |
| Marketplace + skills | `aragora/marketplace/`, `aragora/skills/`, `aragora/server/handlers/marketplace_browse.py`, `aragora/server/handlers/marketplace_pilot.py` | Catalog, registry, installer, service, seed content, and browse/pilot handlers are shipped but unadopted; there is no public marketplace deployment, published third-party content, or external consumer. | The first external design partner commits to consume or distribute an Aragora template/protocol. | Run one partner-scoped publish → discover → install path with provenance and a Decision Receipt. | [#9046](https://github.com/synaptent/aragora/issues/9046) |
| Verticals | `aragora/verticals/` | Domain modules exist, but no vertical has a signed pilot or a receipt-backed external journey. | The first vertical pilot is signed; activate only that pilot's vertical. | Add one pilot-specific receipt profile and one domain-specialist path behind the existing decision interface. | [#9046](https://github.com/synaptent/aragora/issues/9046) |
| Genesis | `aragora/genesis/` | Evolution primitives exist outside the default product path. | The AGT CP-2→CP-5 progression reaches a governed experiment that needs an evolution candidate. | Run one opt-in experiment that emits a reviewable receipt and cannot alter default runtime selection. | [#9046](https://github.com/synaptent/aragora/issues/9046) |
| Broadcast | `aragora/broadcast/` | Post-decision communication primitives exist without a paying-user demand signal. | A paying user requests an audio or broadcast form of an accepted decision. | Export one receipt-linked decision summary through one opt-in broadcast channel. | [#9046](https://github.com/synaptent/aragora/issues/9046) |
| Tournaments | `aragora/tournaments/`, `aragora/ranking/` | Competition primitives overlap the live ELO/ranking authority. | A concrete ranking change needs a tournament-derived comparison that ELO alone cannot express. | Fold only the required comparison into `aragora/ranking` and emit one deterministic ranking report; do not launch a parallel tournament product. | [#9046](https://github.com/synaptent/aragora/issues/9046) |
| Inbox trust wedge | `aragora/inbox/`, `aragora triage` | The CLI is receipt-gated end-to-end, but founder testing found the interaction and classification quality below the retest bar. | A design partner agrees to retest a polished web journey with an explicit classification-quality bar. | Deliver one web-only message → proposed action → receipt flow without widening the CLI. | [#9046](https://github.com/synaptent/aragora/issues/9046) |
| Pareto provider router | `aragora/routing/cost_quality_optimizer.py` | The optimizer and runtime hooks exist, but decisions do not expose stakes-based routing rationale. | Decision-stakes routing work is accepted with measurable reliability and cost targets. | Record one model-selection rationale in a receipt before changing default routing behavior. | [#8233](https://github.com/synaptent/aragora/issues/8233) |
| Tamper-evident audit trail | `aragora/server/handlers/audit_trail.py`, `aragora/trail/rekor.py`, `aragora/trail/intent_chain.py`, `/audit-trail`, `docs/specs/TAMPER_EVIDENT_TRAIL.md` | The live trail verifies checksums, and the TET spec, append-only intent chain, and Rekor anchoring client exist; the audit-trail surface still lacks a governed external-witness proof under a compromised-operator threat model. | A governed TET phase requires an external witness after the receipt-verification path is stable. | Anchor one receipt or intent-chain head through an approved transparency service and verify it independently. | [#9046](https://github.com/synaptent/aragora/issues/9046) |

### Dormant-Module Disposition Policy

1. **Integrate or park by default; do not archive for tidiness.** The founder
   decision preserved in
   [`MAXIMALIST_VISION.md`](https://github.com/synaptent/aragora/blob/main/docs/vision/MAXIMALIST_VISION.md) permits removal only
   when a module is actively harmful **and** has no credible integration path.
2. **One activation path and one open owner issue per row.** The owner keeps the
   trigger, minimum exposure, and proof current; the table does not make the
   row dispatch-ready.
   [#9046](https://github.com/synaptent/aragora/issues/9046) is the standing-open
   umbrella owner for rows without dedicated activation issues. It must remain
   open while any row names it; closing or replacing it requires updating every
   affected row in the same change.
3. **Archive, delete, or rebuild proposals must update this table first.** The
   proposal must cite #9046, show why the activation gate is permanently
   unreachable, and explain why composition with the existing module is worse
   than replacement.
4. **Activation requires external evidence.** Name the user or operator need,
   the first API/CLI/SDK/receipt or UI exposure, the owning issue, and a
   measurable proof before implementation starts.

Changing a row to "trigger observed" is still report-only. Normal tiering,
ownership, exact-head review, and settlement rules govern every implementation.

## How to Read This List

- **P0**: PMF blockers — close the product loop before certification
- **P1**: Value-prop proof (Q2 2026)
- **P2**: Product hardening and enterprise readiness after PMF
- **P3**: Scale & revenue after PMF
- **P4**: Strategic evolution (2026+)
- **Scaffolding**: Code exists but needs hardening/productization

---

## P0 — PMF Blockers

| Feature | Status | Notes |
|---------|--------|-------|
| Truthful live founder loop | **PROVEN — moved to Completed** | 5/5 consecutive live runs pass (35-62s, March 24, 2026). Test baseline: `71 passed` (focused) / `125 passed` (extended). Receipts persist to store for API/dashboard visibility. All 7 acceptance checklist items pass. |
| Smart provider routing | **Shipped on `main`; live proof pending** | PR #724 shipped the Pareto optimizer and pricing database. Runtime wiring landed on `main` via [#1167](https://github.com/synaptent/aragora/pull/1167), and downstream runtime hints are applied through the debate path. The remaining obligation is to prove that routing behaves well in the live founder loop rather than to debate whether the wiring exists. Historical lineage: [#813](https://github.com/synaptent/aragora/issues/813). **June 2026:** in practice the optimizer is dormant (see dormant table); decision-stakes routing with receipt-recorded rationale is now [#8233](https://github.com/synaptent/aragora/issues/8233). |
| Complete one working user journey | **Mocked proof passes; live proof still open** | The relevant slices are on `main`: live settings/API-key wiring ([#1146](https://github.com/synaptent/aragora/pull/1146)), live debate creation ([#1147](https://github.com/synaptent/aragora/pull/1147)), onboarding/get-started ([#1170](https://github.com/synaptent/aragora/pull/1170)), quickstart fail-closed behavior ([#1180](https://github.com/synaptent/aragora/pull/1180)), and structured quickstart receipts ([#1192](https://github.com/synaptent/aragora/pull/1192)). The current gap is one repeatable live proof, not another architecture slice. Historical lineage: [#1046](https://github.com/synaptent/aragora/issues/1046). |
| Knowledge Mound reads enrich debate context | **Shipped on `main`; live read/write proof pending** | Retrieval, precedent loading, and writeback groundwork landed via [#1111](https://github.com/synaptent/aragora/pull/1111), [#1131](https://github.com/synaptent/aragora/pull/1131), [#1132](https://github.com/synaptent/aragora/pull/1132), [#1134](https://github.com/synaptent/aragora/pull/1134), [#1151](https://github.com/synaptent/aragora/pull/1151), [#1168](https://github.com/synaptent/aragora/pull/1168), and [#1176](https://github.com/synaptent/aragora/pull/1176). The remaining question is whether that read/write path is visible and trustworthy in the live founder loop. Historical lineage: [#1048](https://github.com/synaptent/aragora/issues/1048). |
| Debate output quality | **VALIDATED — moved to Completed** | Run 012 (Mar 5): composite 8.38-9.39/10. Diverse benchmark (10 domains): 100% pass, avg composite 0.938. |

---

## P1 — Value-Prop Proof (Q2 2026)

| Feature | Status | Notes |
|---------|--------|-------|
| OpenClaw end-to-end demo | **Core loop shipped** | PR #727: CodeImplementationTask, SpecExtractor, ComputerUseActionBundle, receipt linkage. Production validation with live agents remaining. Tracked in [#814](https://github.com/synaptent/aragora/issues/814). |
| Functional frontend paths (5 that matter) | More truthful on `main`; continuity still gated by live founder-loop proof | Recent merged slices improved the real surface: settings/API-key wiring ([#1146](https://github.com/synaptent/aragora/pull/1146)), debate creation ([#1147](https://github.com/synaptent/aragora/pull/1147)), public status truthfulness ([#1148](https://github.com/synaptent/aragora/pull/1148)), pipeline golden-path visibility ([#1150](https://github.com/synaptent/aragora/pull/1150)), onboarding/get-started ([#1170](https://github.com/synaptent/aragora/pull/1170)), and Wave 2 productization ([#1188](https://github.com/synaptent/aragora/pull/1188)). The remaining gap is continuity across debate creation, results, knowledge, settings, receipts, and dashboard state in a live run. Historical lineage: [#1047](https://github.com/synaptent/aragora/issues/1047). |
| 10+ agent coordinated debates | Scaffolding | Current practical limit: 2-6 agents. Coordination infrastructure exists; scale testing needed after the core loop works. Tracked in [#815](https://github.com/synaptent/aragora/issues/815). |
| Agent-first beta via REST API | **Fleet deployed (12 runners)** | `aragora openclaw watch` polls repos, runs multi-agent review, posts findings. 3 Hetzner + 6 EC2 + 3 local Macs. PR watch daemon on Mac Studio via launchd. Shared operator productization is tracked in [#817](https://github.com/synaptent/aragora/issues/817) and [#819](https://github.com/synaptent/aragora/issues/819). |
| GitHub Actions pre-merge gate | **Workflow created** | `aragora-review-gate.yml` manual-only (workflow_dispatch). Re-enable pull_request trigger when ready. |
| Public demo at aragora.ai/demo | **Truthful proof surface** | `/demo` now runs a canonical live-backed proof when the public playground backend is live and labels any non-live fallback or recorded sample explicitly. `/try` remains the primary beta funnel for user-entered questions, persistence, and sharing. Productization is tracked in [#818](https://github.com/synaptent/aragora/issues/818). |
| EU AI Act compliance package | **Substantially complete (90/100)** | Art. 9/10/11/12/13/14/15/43/49 bundle coverage and customer playbook appendix are shipped. Remaining work is packaging polish, regulator-ready validation, and launch collateral hardening. **Deadline: Aug 2, 2026.** |
| First 2 enterprise pilot engagements | Not started | Closed partnerships — target fintech + healthcare |
| Developer onboarding &lt;10 min | **Contract improved; live timing proof still required** | `aragora quickstart` now fails fast on bad TLS ([#1180](https://github.com/synaptent/aragora/pull/1180)) and supports inline provider keys plus structured receipts ([#1192](https://github.com/synaptent/aragora/pull/1192)). That is better than the earlier behavior, but the actionable target is a repeatable live onboarding run with bounded noise and measured timing, not a blanket "already working" claim. |

---

## P2 — Product Hardening And Enterprise Readiness (After PMF)

| Feature | Status | Notes |
|---------|--------|-------|
| External penetration test | Scope and outreach artifacts ready; vendor selection pending | Kickoff stays warm, but certification is intentionally sequenced after the product loop is usable. Operational status is tracked in `security/pentest/VENDOR_OUTREACH_LOG.md`; work remains tracked in [#273](https://github.com/synaptent/aragora/issues/273), [#274](https://github.com/synaptent/aragora/issues/274), and [#509](https://github.com/synaptent/aragora/issues/509). |
| Semantic convergence (full embedding) | **VALIDATED — moved to Completed** | PR #723 migrated 5 similarity modules from difflib to embedding-based. Remaining difflib usage is exclusively for text diff display, not similarity. |
| ERC-8004 on-chain deployment | Contracts written — **de-scoped (June 2026)** | Solidity contracts exist; not deployed to any mainnet. Needs chain endpoint config + gas management. Tracked in [#816](https://github.com/synaptent/aragora/issues/816). **June 2026:** explicitly excluded by the steering-leverage selection filter ("blockchain expansion: breadth, no steering"); public anchoring need is served by Rekor ([#8231](https://github.com/synaptent/aragora/issues/8231)) instead. Kept for history, not dispatch. |
| Decision-Integrity UI Workbench | Partial frontend | Existing workbench pages render, but they do not replace the PMF need for five truthful user-facing paths. Remaining canvas and data wiring work stays secondary to `#1047`. |
| SOC 2 Type II audit engagement | Scope doc ready | 60+ controls implemented (98%); pentest scope doc v3.1.0 finalized; vendor shortlisted (NCC, Bishop Fox, Trail of Bits, Cure53). Blocker: vendor selection + engagement. |
| Enterprise Communication Hub (#293) | **Epic closed** | PR #726: template persistence, router event wiring, E2E tests. Delivery log, retry queue, circuit breakers, event telemetry, user preference UI, Active Triage dashboard, TriageRulesPanel all shipped. Remaining: inbox→debate trigger wiring end-to-end validation, tracked in [#817](https://github.com/synaptent/aragora/issues/817). |

---

## P3 — Scale & Revenue (Q3–Q4 2026)

> **June 2026 annotation:** the proof-first shift and the steering-leverage selection filter de-scoped this tier's breadth items (more verticals, marketplace breadth, generic expansion) until PMF/steering proof exists. Rows are annotated, not deleted.

| Feature | Status | Notes |
|---------|--------|-------|
| Cloud marketplace listings | Not started — de-scoped (June 2026) | AWS Marketplace + Azure Marketplace listings. Infrastructure ready. Parked until PMF proof. |
| Vertical packages | Not started — de-scoped (June 2026) | Healthcare (FHIR, HIPAA), Financial (SOX, risk), Legal (contracts, discovery). Guides exist; packages not assembled. Steering filter: "more verticals = breadth, no steering". |
| Skills Marketplace pilot | Scaffolding — de-scoped (June 2026) | SkillRegistry + SkillMarketplace code exists (~2.5k LOC, see dormant table); no public marketplace endpoint or published content. Parked until PMF proof. |
| On-premise deployment productization | Partial | Docker Compose + Helm chart exist; on-prem installer/wizard not built. |
| International expansion / EU data residency | Not started — de-scoped (June 2026) | Data residency controls needed for EU enterprise buyers. Parked until enterprise pilots exist. |
| Compute escrow mechanism | Not started — de-scoped (June 2026) | Settlement stakes via crypto compute escrow. Design in docs/plans/. Steering filter: blockchain expansion excluded. |

---

## P4 — Strategic Evolution (2026+)

| Feature | Status | Notes |
|---------|--------|-------|
| Prover-Estimator debate protocol | **Shipped and wired** | 581 LOC engine + consensus handler wired into `consensus_phase.py`. Use `protocol.consensus="prover_estimator"` to activate. 5-stage pipeline: decompose→estimate→challenge→re-estimate→aggregate. 33 unit tests pass. |
| Cross-verification phase (3-pass hallucination detection) | **Shipped and wired** | 395 LOC engine wired as optional post-debate enrichment in `orchestrator_runner.py`. Set `arena.enable_cross_verification=True`. Computes grounding_delta, adversarial_resistance, hallucination_risk. |
| Truth scorer integrated into vote weights | **Shipped and wired** | `TruthScorer` (398 LOC) scores evidence-vs-rhetoric ratio per proposal. `apply_truth_ratio_bonuses()` in `VoteBonusCalculator` rewards high truth ratios. Enable via `protocol.enable_truth_ratio_weighting=True`. |
| Epistemic hygiene + anti-sycophancy | **Shipped and integrated** | ~1,695 LOC across `epistemic_hygiene.py`, `trickster.py`, `trickster_calibrator.py`. Fully integrated into consensus, settlement, prompt assembly, and server. ~3,744 LOC tests. |
| Prompt-to-spec engine | **Shipped** | `aragora spec` CLI command completes in ~23s. Decompose→interrogate→research→specify pipeline. `aragora/prompt_engine/` module (decomposer, interrogator, researcher, spec_builder, conductor). |
| Canvas GUI (8-stage visual DAG) | Partial frontend — de-scoped (June 2026) | Prompt-engine page exists; full 8-stage visual canvas missing. Steering filter: "frontend breadth" excluded until steering surfaces prove out. |
| Market resolution mechanism | Design only | Long-horizon settlement claim pricing via prediction market. |
| STOP N-candidate for Nomic Loop | Design only | Multi-plan generation before committing to self-improvement path. |
| Meta-improver for debate protocols | Design only | A/B test protocol variants using Nomic Loop. |
| Obsidian bidirectional sync | **Shipped** | `ObsidianAdapter` with `ReverseFlowMixin` for KM→Obsidian writeback. Forward sync, conflict detection, filesystem watcher. |
| Dialectical Runtime synthesis layer (DIC-23..28) | Planning only | Additive tranche that closes the loop between DIC-20 decay signals, DIC-15 crux-finder, DIC-21 quarantine, and DIC-22 repair proposals. Adds a report-only runtime loop orchestrator (DIC-23 / [#6217](https://github.com/synaptent/aragora/issues/6217)), epistemic genealogy ledger (DIC-24 / [#6218](https://github.com/synaptent/aragora/issues/6218)), adversarial world-state stress-test (DIC-25 / [#6219](https://github.com/synaptent/aragora/issues/6219)), belief coherence monitor (DIC-26 / [#6220](https://github.com/synaptent/aragora/issues/6220)), operator crux arbitration receipts (DIC-27 / [#6221](https://github.com/synaptent/aragora/issues/6221)), and proactive crux gardening (DIC-28 / [#6222](https://github.com/synaptent/aragora/issues/6222)). Epic: [#6223](https://github.com/synaptent/aragora/issues/6223). Activation gated on DIC-20/21/22 production-green plus the proof-first Foreman gate. Design: [docs/plans/2026-04-18-dialectical-runtime-synthesis.md](plans/2026-04-18-dialectical-runtime-synthesis.md). Planning-only labels; no `boss-ready` until the gate opens. |

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
| Self-improving platform quality | Nomic Loop 100% wired; 82 E2E tests; CLB backbone hardened (14/14 issues closed); safety gates + gauntlet gate + evolution audit + golden-path test; **Ralph V14 benchmark validated full autonomous loop** (PRs #1004-#1006) | Diverse benchmark validated (100% pass). Production safety gate requires ENABLE_NOMIC_LOOP=true. Ralph autonomy loop closed for `merge_policy=admin_merge_allowed`. |
| Autonomous self-assessment loop | `IdeaToExecutionPipeline.from_system_metrics()`, `SelfImprovePipeline`, `NomicLoop`, `execute_to_github_issue()`, `plan_from_issue_list()`, worktree autopilot, the canonical assessment compiler, and the pause-refresh shift controller exist on `main` | The remaining truth gap is the control plane: no canonical developer task queue/claim protocol, no universal per-lane run receipt/provenance artifact, and no integrator view tying claims, receipts, heartbeats, and merge readiness together. Tracked in [#1036](https://github.com/synaptent/aragora/issues/1036), [#837](https://github.com/synaptent/aragora/issues/837), [#842](https://github.com/synaptent/aragora/issues/842), [#843](https://github.com/synaptent/aragora/issues/843), and [#990](https://github.com/synaptent/aragora/issues/990). |
| Blockchain receipts | SHA-256 cryptographic hashing works; StakingRegistry (stake/slash/unstake/rewards); ComputeBudgetManager; ReceiptAnchor; SlashEvent model (hollow_consensus, factual_error, calibration_drift) | On-chain storage with ERC-8004 (not deployed); staking/slashing NOT wired into debate outcome loop; agent selection not weighted by compute budget. **June 2026:** ERC-8004 path de-scoped (see dormant table); receipt anchoring proceeds via Sigstore Rekor ([#8231](https://github.com/synaptent/aragora/issues/8231)). |
| Semantic convergence | **Migrated** (PR #723) | All similarity paths use embeddings. Only `unified_diff` (text display) uses difflib. |
| OpenClaw execution | **Core loop shipped** (PR #727) | CodeImplementationTask + SpecExtractor + receipt linkage. Production validation pending. |
| RLM context access | Code complete (92 exports, 27 test files, 15k LOC) | No user-facing guide; integration with default Arena config unclear; training pipeline (buffer/policy/reward/trainer) untested E2E. Tracked in new GitHub issue. |

---

## Completed — Formerly on This List

These items were planned and are now shipped:

| Feature | Shipped |
|---------|---------|
| Nomic Loop end-to-end | Jan 2026 |
| Knowledge Mound Phase A2 (adapter registry + unified memory hardening) | Feb 2026 |
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
| CI setup-python-safe composite action (51 workflows) | Mar 2026 |
| MFA admin enforcement (compliance API, drift alerts, bypass docs) | Mar 2026 |
| Data classification enforcement (runtime, CI PII gate, evidence bundles) | Mar 2026 |
| Closed-loop backbone contracts (IntakeBundle, SpecBundle, DeliberationBundle, ReceiptEnvelope, OutcomeFeedbackRecord) | Mar 2026 |
| Fail-closed spec validation (execution-grade field enforcement) | Mar 2026 |
| Deliberation bundle handoff (dissent + quality gate into planning) | Mar 2026 |
| CI push-to-main noise reduction (35→6 workflows) | Mar 2026 |
| Self-hosted runner fleet (12 runners: 3 Hetzner + 6 EC2 + 3 Mac) | Mar 2026 |
| Decision-Integrity Workbench frontend | Mar 2026 |
| G1 Signed Context Manifests (HMAC-SHA256 + CLI) | Mar 2026 |
| Closed-loop backbone sprint (14 CLB issues) | Mar 2026 |
| ExecutionBundle + VerificationBundle contracts | Mar 2026 |
| Bug-fix loop after verification failure (auto-trigger) | Mar 2026 |
| Receipt envelope normalization (success/fail/blocked) | Mar 2026 |
| Outcome feedback → Nomic goal export pipeline | Mar 2026 |
| Trust-tier + taint propagation across backbone | Mar 2026 |
| External-verifier insertion point (CLB-012) | Mar 2026 |
| Golden-path backbone test (intake → receipt E2E) | Mar 2026 |
| Dogfood backbone profile script | Mar 2026 |
| PR watch daemon fleet (3 Mac machines, 30 reviews/hour) | Mar 2026 |
| Dev swarm coordination layer (lease-aware) | Mar 2026 |
| Swarm supervisor + worker launcher + reconciler (PRs #744-746) | Mar 2026 |
| Inbox trust wedge — receipt-gated email actions (PRs #731-742) | Mar 2026 |
| Session circuit-breaker — auth-state pinning (PRs #736, #740) | Mar 2026 |
| Gmail OAuth setup helper (PR #741) | Mar 2026 |
| Semantic convergence — 5 modules migrated to embeddings (PR #723) | Mar 2026 |
| Smart provider routing Phase 1 — Pareto optimizer + 8-model pricing (PR #724) | Mar 2026 |
| EU AI Act playbook GTM polish + Art. 10/11/43/49 appendix (PR #725) | Mar 2026 |
| Enterprise Comms Hub #293 — template persistence + router wiring (PR #726) | Mar 2026 |
| OpenClaw E2E core loop — CodeImplementationTask + ComputerUseActionBundle (PR #727) | Mar 2026 |
| Stale lease auto-release — PID-based liveness, proactive reaping (PR #1004) | Mar 2026 |
| Reconciler lease reaping — tick_run reaps expired leases (PR #1005) | Mar 2026 |
| Admin merge bypass — autonomous merge when required checks pass (PR #1006) | Mar 2026 |
| Ralph V14 benchmark — full autonomous loop validated (spec→PR→merge, zero intervention) | Mar 2026 |
| Ralph blocker taxonomy — campaign_stalled, needs_human classification (PRs #946-#950) | Mar 2026 |
| **Live founder loop proven repeatable** (5/5 runs, 35-62s, receipts on API/dashboard) | Mar 2026 |
| Prover-Estimator consensus handler wired into debate pipeline | Mar 2026 |
| Cross-verification post-debate enrichment wired into orchestrator | Mar 2026 |
| Truth scorer ratio bonuses wired into vote weight calculation | Mar 2026 |
| Prompt-to-spec CLI (`aragora spec`) — 23s end-to-end | Mar 2026 |
| Inbox trust wedge CLI (`aragora triage auth`, `--dry-run`) | Mar 2026 |
| Quickstart receipt store persistence for API/dashboard visibility | Mar 2026 |
| Embedding rate limit resilience (hash-based fallback on 429) | Mar 2026 |
| Summary preamble cleaning (strip LLM chain-of-thought from CLI output) | Mar 2026 |
| EU AI Act compliance bundle verified end-to-end with real quickstart receipts | Mar 2026 |
