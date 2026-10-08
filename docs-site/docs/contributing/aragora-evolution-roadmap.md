---
title: Aragora Evolution Roadmap
description: Aragora Evolution Roadmap
---

# Aragora Evolution Roadmap

> **Last updated:** 2026-04-19
> **Current transition:** early `Teammate` -> reliable `Foreman`
> **Planning rule:** preserve the maximalist vision; sequence through a narrow reliability wedge first.
> **Concrete execution overlay:** [2026-04-18 3-Horizon Execution Roadmap](2026-04-18-3-horizon-roadmap.md) operationalizes this doc's outcome map into bounded 30/90/365-day deliverables.
> **Agent-facing projection:** [Agent Operating Loop](https://github.com/synaptent/aragora/blob/main/docs/architecture/agent-operating-loop.md) composes roadmap, mission, work, and Nomic truth without creating a second control plane.

## Executive Thesis

Aragora is trying to become an autonomous chief of staff, an engineering organization substrate, and a decision-integrity control plane — not just a better coding agent.

The distinctive long-horizon direction is **organizational epistemic infrastructure**: debates should surface load-bearing cruxes, receipts should preserve claim evidence, and important organizational claims should become executable objects with freshness, verification, provenance, and bounded repair paths. This expands the decision-integrity core without replacing the current proof-first autonomy wedge.

The efficient path is not to build every ambitious surface at once. The wedge is reliable autonomous software execution on bounded backlogs, with receipts, human-control surfaces, and a truthful operator view. The unified DAG GUI remains a parallel second track, but it must reflect live runtime truth rather than speculative mock state.

## Stage Model

| Stage | Product shape | Primary proof that matters | Core dependencies |
|---|---|---|---|
| **Tool** | One-shot helpful product surfaces | Bounded flows produce useful results and truthful stops | Product loops, receipts, fail-closed UX |
| **Teammate** | Scoped autonomous contributor | A single bounded task can explore, edit, verify, and escalate clearly | Session state, verification, repair evidence |
| **Foreman** | Multi-host backlog manager | Many bounded tasks can run with truthful status and low rescue overhead | Contracts, admission control, ledger, self-heal |
| **Chief of Staff** | Goal-to-plan delegation layer | Vague goals become reviewable portfolios with tradeoffs and approvals | Shared memory, planning models, human control surfaces |
| **Organization Substrate** | Unified operating system for agentic work | Cross-functional idea-to-execution flows run on one graph with auditable outputs | Unified DAG, memory fabric, receipts, heterogeneous agents |

**Current strategic obligation:** finish the `Teammate` -> `Foreman` transition before claiming broad autonomous operating-system status.

## 30 / 90 / 365 Outcome Map

| Horizon | Outcome | What must ship | Evidence that counts |
|---|---|---|---|
| **30 days** | First booster is proven | Fixed benchmark corpus, context enrichment, truthful failure taxonomy, and the first admission slices that improve real runs | Context-enriched workers complete **50%+** of bounded benchmark issues without human rescue, and **100%** of failures classify truthfully |
| **90 days** | Booster ladder becomes a product | Assisted dispatch, guarded autonomy, repair/salvage loops, truthful operator surfaces, first reviewable DAG stage, permissioned-memory baseline | Weekly multi-host runs on safe classes with bounded intervention and explicit blocker evidence |
| **365 days** | Platform expansion becomes credible | Full idea-to-execution workbench, memory + ingestion fabric, decision-integrity packages, chief-of-staff planning loops, packaged GTM motion | Cross-functional workflows with auditable receipts and repeatable customer proof |

## Reverse-Staged Rocket Bootstrap Plan

We should bootstrap semi-autonomy like a reverse-staged rocket: start with the smallest booster that can be benchmarked honestly, then use that booster to unlock the next one. The goal is not to land the whole stack in one leap; it is to prove each booster in sequence.

```mermaid
flowchart LR
    B0[Corpus] --> B1[Assist]
    B1 --> B2[Guard]
    B2 --> B3[Repair]
    B3 --> B4[Multi]
    B4 --> F[Foreman]
```
<!-- B0=benchmark+context, B1=human-approved dispatch, B2=contract/preflight gate, B3=auto-repair/salvage, B4=multi-host bounded autonomy -->

| Booster | Purpose | Human role | Exit signal |
|---|---|---|---|
| **B0 — Corpus** | Prove context-enriched workers on a fixed safe corpus | Human selects corpus and labels rescues honestly | `>=50%` no-rescue success and `100%` truthful failure bucketing |
| **B1 — Assist** | Auto-draft work orders, scopes, and validator plans | Human approves or edits drafts before run | Most safe tasks enter execution from machine-written work orders |
| **B2 — Guard** | Require contracts and production-like preflight before auto-run | Human only handles rejected admissions and true exceptions | Safe classes run only when contract + preflight pass |
| **B3 — Repair** | Convert common failures into retry, salvage, and quarantine flows | Human reviews edge cases instead of redoing the work | Repeated rescue classes decline sharply |
| **B4 — Multi** | Extend proven loops across hosts with truthful status | Human monitors and intervenes sparingly | Early `Foreman` behavior is routine on bounded backlogs |

**Operational law:** every time humans intervene twice for the same failure class, the next system change should absorb that rescue as product behavior.

## Program Tracks

### Track A — Reliability Substrate (Primary, Blocking)

This is the foundation that all other tracks depend on. It implements the approved reliability substrate spec for swarm and Nomic.

#### A1. Failure Taxonomy and Benchmark Corpus

- define canonical terminal truth across `needs_human`, publication, auth, validation, and task-shape failures
- harvest a benchmark corpus from real failed runs and host incidents
- make the benchmark corpus runnable in CI so regressions are visible

#### A2. WorkerContract and CredentialEnvelope

- require a persisted `WorkerContract` for every dispatchable work item
- separate runner, git, GitHub API, provider, and verification auth into explicit envelope slices
- fail closed when contract fields, permissions, or auth sources are incomplete

#### A3. Contract-Aware Preflight

- run preflight through the same command path, flags, profile, and auth shape as production
- verify read/write/commit/push/draft-PR flow in a scratch namespace
- turn host admission into a receipt rather than a shell heuristic

#### A4. Autonomy Ledger and Self-Heal

- mirror probes, queue state, contracts, receipts, and terminal outcomes into one ledger
- add automatic quarantine and fallback for stale auth, permission mismatch, rate limits, and publication failures
- cut health/reporting surfaces over to ledger-backed truth

#### A5. Nomic on the Same Substrate

- route Nomic-generated work through the same contract, preflight, and ledger path
- avoid a second reliability stack for self-improvement
- benchmark Nomic lanes against the same failure corpus

### Track B — Bounded Autonomy Control Plane

This track makes runtime truth inspectable and operable.

#### B1. Interactive Sessions and Repair Journal

- persist `explore -> plan -> edit -> verify -> repair -> publish` state by session
- make retries resume from prior state instead of re-prompting from scratch
- capture repair evidence so failure reasons become product inputs

#### B2. Task Sanitizer and Admission Gate

- classify tasks as accepted, rewritten, dropped, or quarantined before dispatch
- catch truncation, contradictory scope, impossible acceptance criteria, and missing verification contracts
- preserve original and sanitized task text for audit and debugging

#### B3. Truthful Lane and Integrator State

- unify host, runner, lane, publication, and merge-readiness state into one operator model
- expose pause, resume, retry, salvage, and quarantine operations against live state
- make the status surface match reality even when the system is degraded

#### B3a. PR Intelligence Brief Surface

- turn the review queue into a receipt-backed settlement brief rather than a comment bot
- use heterogeneous review to surface disagreement, not just a single model verdict
- optimize for skim-first human settlement with drill-down on dissent, evidence, and risky files
- keep machine review advisory and preserve the human settlement gate on merge

Design brief: [2026-04-19 PR Intelligence Brief](2026-04-19-pr-intelligence-brief.md).

#### B4. Multi-Host Soak and Unattended Criteria

- define what a trustworthy 12-hour bounded run looks like
- run repeat soak tests on the bounded backlog
- use measured rescue rate, verification pass rate, and terminal truth composition as gates
- cheap-signal-to-verification routing (bounded benchmark, planning-truth only): treat "route by cheap signal, verify under full debate only on high-value or high-disagreement inputs" as a **benchmarked decision policy** on the existing bounded corpus, not a philosophy — acceptance is a labelled comparison on the same fixed benchmark that shows (a) measured cost reduction, (b) no regression in rescue rate / verification pass rate, and (c) a routing-decision receipt trail that lets an operator audit every cheap-route call. No `boss-ready` and no admission gate changes until the proof-first Foreman gate opens per [NEXT_STEPS_CANONICAL.md](./next-steps-canonical).

### Track C — Unified DAG Workbench (Parallel Second Track)

The GUI matters now, but only as a truthful view on the same runtime substrate.

#### C1. Canonical Graph Model

- define shared node and provenance schemas for ideas, goals, actions, orchestration, and receipts
- map contracts, approvals, and stage transitions onto that graph
- ensure graph APIs read live runtime state instead of synthetic placeholders

#### C2. Reviewable Stage Transitions

- show prompt -> spec -> work-order -> receipt transitions as first-class objects
- expose approval, replan, and escalation points at stage boundaries
- surface dissent, evidence, and risk at each handoff

#### C3. Operator Workbench

- provide lane views, run replay, intervention controls, and receipt-linked history
- support branching, comparison, and alternative plan review
- give the operator one place to understand why the system is doing what it is doing

#### C4. Full Idea-to-Execution Canvas

- extend the workbench into editable ideas -> goals -> actions -> orchestration views
- support portfolio-level planning and DAG-wide dependencies
- preserve provenance so downstream work is always traceable upstream

### Track D — Memory and Context Fabric

This track turns knowledge into a reliable advantage instead of an opaque dependency.

#### D1. Permissioned Memory Model

- store trust tier, provenance, and access boundaries for memory items
- distinguish operator instruction from retrieved context
- carry taint/provenance annotations into specs, debates, and receipts
- design heuristic: treat session-scoped retrieval caches, KM writes, and long-horizon claim stores as distinct timescales that must declare cross-tier consolidation paths explicitly — silent merges are a finding. Non-canonical framing and analogies live in the archived biological-timescale analogies research brief; the heuristic itself is a D-track design rule, not a new subsystem.

#### D2. Large-Context Packing

- build relevance-ranked context packs for large repos and mixed knowledge sources
- expose context budgets, truncation, and evidence coverage
- benchmark whether large-context packing actually improves outcomes

#### D3. Broad Ingestion and Normalization

- normalize repos, docs, APIs, chat, and receipts into a coherent source model
- maintain source-level provenance and permission data
- detect stale or insufficient context rather than silently over-trusting inputs

#### D4. Shared Knowledge Base

- tie cross-run learning to outcomes and receipts
- provide retrieval analytics and exportability
- make memory portable enough to be a trust asset rather than lock-in

### Track E — Decision Integrity Core

This track preserves Aragora's core differentiation from generic agent platforms.

#### E1. Debate Quality and Calibration

- improve truth weighting, dissent capture, and hollow-consensus detection
- extend benchmark coverage across both decision and execution workflows
- show debate quality signals inside receipts and operator views
- measure whether *pre-consensus disagreement patterns* (not only final dissent) predict later settlement or correction — success criterion is a benchmark artifact showing disagreement-feature correlation with settled-outcome divergence on the existing bounded corpus; planning truth only, and acceptance must land a measurable correlation before any routing consumer is wired. This is a narrow E1 measurement, not a new subsystem; it enters the `boss-ready` queue only after the proof-first Foreman gate opens per [NEXT_STEPS_CANONICAL.md](./next-steps-canonical).

#### E2. External Verification and Policy Gates

- require external verifiers or stronger policies for high-impact decisions
- tie policy gates directly to execution permissions and approvals
- fail closed when verification requirements are not met

#### E3. Receipt Chain and Compliance Bundles

- strengthen cryptographic receipt envelopes and provenance links
- extend compliance artifact bundles for regulated workflows
- preserve settlement and review loops for long-horizon correctness

#### E4. Explainability and Comparison

- compare debates, runs, and outcomes side by side
- show idea -> receipt -> later-settlement lineage
- produce board- and regulator-ready exports without losing technical depth

#### E5. Crux Engine, Epistemic CI, and Epistemic Runtime

- define a `CruxSet` output for the 3-5 load-bearing disagreements that would change a decision if resolved differently
- define executable claim manifests for organizational claims with owner, evidence, freshness SLA, verifier, receipt links, and failure behavior
- verify explicit claims before inferring claims automatically from docs, Slack, issues, or receipts
- persist claim and crux provenance through receipts and Knowledge Mound
- bridge failed claims and unresolved high-load-bearing cruxes into exactly one bounded follow-up issue only when queue governance permits it
- expose a read-only organizational truth map showing what Aragora believes, why, how fresh the evidence is, and what is decaying
- define proof-carrying code units that link routes, functions, scripts, and policies to their assumptions, claims, receipts, verifiers, decay policy, and fallback policy
- detect epistemic decay when proof-carrying code assumptions become stale, contradicted, or unsupported by fresh evidence
- fail closed through report-only, degrade, fallback, quarantine, or repair-required policies before any live runtime mutation
- route decayed proof into verified replacement candidates through Arena debate, receipt capture, formal-verifier hooks where available, and PR or shadow output before considering opt-in hot-swap classes

Design brief: [Epistemic CI, Crux Engine, and Epistemic Runtime Plan](EPISTEMIC_CI_AND_CRUX_ENGINE.md).

### Track G — Agent-as-Consumer Substrate (Vision-Layer Planning)

This track extends the Decision Integrity Core into a consumer surface that serves software agents as first-rate consumers alongside humans. It is **planning truth only** until queue governance permits it; it does not enter the live `boss-ready` queue. Detailed plan: [AGENT_CIVILIZATION_SUBSTRATE](AGENT_CIVILIZATION_SUBSTRATE.md).

#### G1. Agent Consumer Surface (`AGT-02`)

- A2A registration endpoint backed by `aragora/blockchain/contracts/identity.py`
- capability discovery endpoint backed by `aragora/marketplace/`
- compute-budget billing with chargeback receipts
- agent-readable decision receipt schema with parseable CruxSet, dissent, and provenance
- reputation read endpoints (write path lives in G3)
- operator-parity surfaces so humans can do everything agents can do, and vice versa

Detailed plan: [AGENT_CONSUMER_SURFACE](AGENT_CONSUMER_SURFACE.md).

#### G2. External Truth Oracles via Prediction Markets (`AGT-03`, `AGT-04`)

- Manifold Markets adapter for play-money calibration
- Synthetic GitHub markets for high-volume internal calibration on PR/issue/CI outcomes
- Metaculus integration following bot-policy compliance
- per-agent rolling Brier scoring with calibration curves
- explicit deferral of real-money venues until calibration is stable

Detailed plan: [2026-04-17-prediction-market-validation](2026-04-17-prediction-market-validation.md).

#### G3. Skin-in-the-Game Reputation Flow (`AGT-05`)

- unified `claim → stake → resolution → settlement → reputation Δ → dispatch update` flow
- per-domain reputation slices (prediction calibration, debate truthfulness, code-PR success, KM contribution, crux resolution)
- soft dispatch downweighting by default; hard suspension only on explicit policy
- settlement-window enforcement, dispute path, and reversal handling for re-opened resolutions
- strategy-decay slice (planning-truth sub-bullet): when a reputation slice depends on an agent's participation in a specific exploit strategy that becomes publicly known or measurably crowded, the slice decays faster — acceptance is a benchmark artifact showing measured decay behaviour on a receipt-backed synthetic corpus; sub-item to G3 rather than a new surface; planning-truth only, no `boss-ready` until the Foreman gate opens.

Detailed plan: [SKIN_IN_THE_GAME_REPUTATION](SKIN_IN_THE_GAME_REPUTATION.md).

#### G4. Productivity Metric Replacing Empty-Queue Idle Soaks (`AGT-06`)

- "verifiable improvements per agent-hour" (VIAH) computed weekly from ShiftLedger entries
- merged autonomous PRs and correctly detected pre-resolution cruxes contribute positive
- rescues required and failed claims promoted without repair contribute negative
- supplements (does not replace) TW-02 no-rescue success rate
- replaces empty-queue stability soaks as the gating productivity proof once substrate stability is sustained

#### G5. CruxDetector Activation in Live Debates (`AGT-01`)

- promote `aragora/reasoning/crux_detector.py` from latent capability to first-class debate goal
- emit ranked CruxSet on production debate path under flag, then default-on
- bridges to DIC-15 (CruxSet contract) and Issue [#6035](https://github.com/synaptent/aragora/issues/6035) (crux-finder mode epic)
- diversity-as-selection-pressure sub-bullet: extend `team_selector.py` with a measured diversity floor (pairwise disagreement entropy + provider-family share) on top of ELO + calibration — acceptance is a benchmark artifact showing that greedy-quality selection produces measurably homogenized failure modes which the diversity floor reduces; narrow extension of existing selection code; planning-truth only, no `boss-ready` until the Foreman gate opens.

### Track F — Trust-Wedge Productization and GTM

This track converts technical proof into market proof.

#### F1. Autonomous Software Execution

- start with a fixed benchmark corpus and prove `prompt -> spec -> code -> verify -> PR` loops on bounded repos
- measure rescue rate, verification pass rate, and wall-clock throughput
- treat every rescue as a benchmark fixture or substrate defect

#### F2. Inbox and Operator Action Loops

- preserve receipt-before-action guarantees outside software execution
- reuse contracts, memory, and approval policies across adjacent operator workflows
- capture operator feedback tied to receipts for future improvement

#### F3. Prompt-to-Spec Handoff

- turn vague requests into reviewable specs with explicit constraints and evals
- route approved specs directly into debate and execution without manual rewrite
- surface missing context and weak acceptance criteria before work begins

#### F4. Design-Partner Recurrence and Packaging

- establish weekly real-work cadence with design partners
- publish truthful proof packs and before/after benchmarks
- package the strongest repeatable wedges before expanding the story further

#### F5. EU AI Act Packaging (Aug 2, 2026 Enforcement Window)

- package existing compliance artifacts (decision receipts, policy gates, dissent capture, provenance) into a sellable bundle for general-purpose AI model obligations
- avoid building new enforcement code in the 30-day horizon; market what exists in H1, finalize the packaging in H2, engage at least one regulated design partner before the enforcement deadline
- treat EU AI Act coverage as an evidence repackaging effort, not a compliance product rebuild
- defer Annex IV full conformity engineering until a specific regulated customer commits

#### F6. Heterogeneous Agent Marketplace (Parity Proof First)

- prove parity across at least four providers running the full golden path before expanding the marketplace surface: Claude (Anthropic), Codex/GPT (OpenAI), Gemini (Google), Grok (xAI) or one OpenRouter model
- stage external frameworks for H3 onboarding: OpenClaw, Nous Hermes, Pi Agent, Anthropic Agent Framework, LangGraph, AutoGen, CrewAI
- enforce one `AgentContract` interface; non-conforming agents remain experimental and do not touch production substrate
- expose the marketplace as opt-in per workspace — users choose their preferred mix rather than inheriting one vendor's stack
- keep no single agent vendor as a critical dependency; fallback and rotation are first-class

#### F7. SMB Operating-System Packaging

- decouple `aragora-core` (founder-installable, ≤10min onboarding) from `aragora-enterprise` (Postgres/Redis/Kafka/SSO/compliance) as separate distribution targets
- ship a founder-tier quickstart that runs a real workflow on a single machine or lightweight host
- treat enterprise features as additive, not subtractive — SMB users should never see capabilities hidden behind enterprise licensing for the core decision-integrity loop
- position the product as an operating system for SMBs, not a feature-reduced enterprise tool

## Cross-Track Rules

- The same contract path should power worker launch, preflight, repair, publish, and GUI state.
- Each booster must prove a measurable gain before the next booster expands scope.
- If humans intervene twice for the same failure class, the next change should productize that rescue.
- Memory without provenance is out of scope.
- GUI surfaces must read ledger-backed truth.
- Claims that matter should become executable, evidence-linked objects before they become product claims or queue work.
- Cruxes should identify load-bearing disagreement, not merely summarize dissent.
- Broad vertical and enterprise expansion follows wedge proof; it does not replace it.
- External claims should always lag measured internal proof.
- Every consumer surface ships in agent-readable and human-readable form, backed by the same runtime truth.
- Reputation only changes via external truth resolution, never via internal agreement.
- Vision-layer planning tracks (Track G `AGT-*`) advance in planning truth without entering the live `boss-ready` queue until queue governance permits the upper-layer tranche, in line with the same rule that governs `DIC-13..22`.

## Stage Exit Criteria

### Tool Exit

Bounded product loops such as debate, prompt-to-spec, and inbox actions are truthful, receipt-backed, and fail closed when assumptions break.

### Teammate Exit

A single bounded task can explore, edit, verify, repair, and escalate clearly without repeated human prompt surgery.

### Foreman Exit

Multi-host bounded backlogs run from explicit contracts with self-heal, truthful operator state, and materially lower rescue burden.

### Chief of Staff Exit

Vague goals become reviewable portfolios with tradeoffs, delegated work, approval checkpoints, and shared memory.

### Organization Substrate Exit

Cross-functional idea-to-execution work lives on one DAG with permissioned memory, heterogeneous agents, and auditable decision and execution receipts.

## Relationship to Other Canonical Docs

- [ROADMAP.md](./roadmap) is the short external/internal doorway.
- [CANONICAL_GOALS.md](./canonical-goals) defines the product boundary.
- [2026-04-18 3-Horizon Execution Roadmap](2026-04-18-3-horizon-roadmap.md) operationalizes this doc into concrete 30/90/365-day deliverables. That doc is the authoritative source for H1/H2/H3 sprint scope.
- [NEXT_STEPS_CANONICAL.md](./next-steps-canonical) defines the current tranche.
- [ACTIVE_EXECUTION_ISSUES.md](./active-execution-issues) holds the epic/milestone/execution tree.
- [EPISTEMIC_CI_AND_CRUX_ENGINE.md](EPISTEMIC_CI_AND_CRUX_ENGINE.md) specifies DIC-13..28 including the Dialectical Runtime synthesis layer (DIC-23..28) staged for H3 behind H2 production-green gates.
