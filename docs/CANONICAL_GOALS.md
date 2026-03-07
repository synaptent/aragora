# Aragora: Canonical Goals & Foundational Thesis

**Single source of truth for all goals across aragoradocs.**
**This document defines WHAT Aragora is and WHY. The [Evolution Roadmap](plans/ARAGORA_EVOLUTION_ROADMAP.md) defines HOW.**
**Last updated: March 1, 2026**

---

## Canonical Metrics (March 2026)

All aragoradocs should cite these values. Update monthly.

| Metric | Value | Source |
|--------|-------|--------|
| Version | 2.8.0 | pyproject.toml |
| Python modules | 3,800+ | `aragora/` file count |
| Lines of code | 1,490,000 | LOC count |
| Automated tests | 210,000+ | repo-wide `def test_` count |
| Test files | 5,000+ | `tests/` file count |
| API operations | 3,100+ across 2,600+ paths | OpenAPI spec |
| WebSocket event types | 270+ | stream event inventory |
| SDK namespaces | 186 Python / 185 TypeScript | SDK package |
| Knowledge Mound adapters | 42 registered adapter specs | adapter factory registry |
| RBAC permissions | 420+ across 15 core resource types | `rbac/types.py` + permission inventory |
| Agent types | 43 across 6+ LLM providers | agent registry |
| Workflow templates | 50+ across 6 categories | template registry |
| Debate modules | 210+ | debate/ directory |
| Handler modules | 580+ | handlers/ directory |
| Connector count | 149 production + 2 stub | connectors/STATUS.md |
| GA readiness | Pre-GA; remaining launch work is tracked in GA_CHECKLIST.md | GA_CHECKLIST.md |
| SOC 2 readiness | 98% | compliance assessment |
| Mypy type errors | 0 | CI typecheck |
| Pricing tiers | Free ($0) / Pro ($49/seat/mo) / Enterprise (custom) | -- |
| Free tier limits | 10 debates/mo, 3 agents, Markdown receipts | -- |
| BYOK model | Customers bring own API keys; Aragora bears no inference cost | -- |
| Target gross margin | 85%+ | -- |

---

## Foundational Thesis

### Mission Statement

Aragora is the **Decision Integrity Platform** -- an adversarial multi-agent debate engine that reduces the reliability problems inherent in individual AI models (hallucination, sycophancy, correlated bias) through structured heterogeneous-model consensus. It produces audit-ready decision receipts for regulated verticals, bridges the gap between vague human intent and precise AI-executable specifications through a unified DAG pipeline, and continuously improves its own capabilities through autonomous self-improvement cycles. The platform interfaces with OpenClaw for safe agentic execution and with Ethereum via ERC-8004 for unforgeable agent identity and reputation.

### The Six Foundational Pillars

Every goal in this document and every feature in the codebase should trace to one or more of these pillars. If it doesn't, it is scope creep.

#### Pillar 1: Adversarial Heterogeneous Consensus

Any given AI model can hallucinate, be sycophantic, be biased, or exhibit correlated failures shared with models trained on similar data. Using structured adversarial debates between heterogeneous models (Claude, GPT, Gemini, Grok, Mistral, DeepSeek, Llama, Qwen) reduces these problems and increases the reliability and quality of output and decisions. The value is in heterogeneity -- different models catch different issues -- and in adversarial structure that forces genuine scrutiny rather than polite agreement.

**Serves:** Debate engine (210+ modules), ELO rankings, Brier calibration, consensus detection, convergence tracking, Trickster hollow-consensus detection, RhetoricalObserver, cross-verification.

#### Pillar 2: SME and Regulated Vertical Accessibility

The system should be useful to small and medium enterprises and organizations, including those in regulated verticals: healthcare (HIPAA, FHIR), financial services (SOX, audit trails), legal (contract review, due diligence, litigation), government/defense (air-gapped deployment), and general compliance (SOC 2, GDPR, EU AI Act). The BYOK model (customers bring own API keys) makes this economically viable with 85%+ gross margins and near-zero inference cost to Aragora.

**Serves:** Enterprise security stack (OIDC/SAML, SCIM, AES-256-GCM, 420+ named permissions across 15 core resource types), compliance frameworks (9 supported), vertical packages, SME budget controls, per-debate cost estimation, channel delivery (Slack, Teams, email, Discord).

#### Pillar 3: Vague Intent to Autonomous Execution

The system should take vague ideas as input and, through a structured process, upgrade them into connections, principles, and values; turn them into well-specified objectives; generate detailed plans; and execute them with as much AI automation as possible and the least human skill needed. This uses a unified DAG structure modifiable through a GUI interface.

With increasingly long-running autonomous agentic AI, people who can generate precise, fully detailed specifications for what they want are gaining 10x advantages over people who lack this discipline and clarity. There is a market opportunity to provide GUI interfaces for people who think more vaguely, don't know how to or can't be bothered to make precise specs, want AI to take ideas to execution, and want to interactively shape the process of ideas to specs to plans to execution while letting AIs automate all parts of the process they don't care about or are fine with delegating.

**The Four-Stage Unified DAG Pipeline:**

| Stage | Node Types | AI Transition | User Action |
|-------|-----------|---------------|-------------|
| **1. Ideas** | Observation, Hypothesis, Insight, Question, Connection | Brain dump -> auto-organize into relationship graph | Drag, merge, split, annotate |
| **2. Goals** | Objective, Principle, Constraint, Metric, Tradeoff | Interrogation + debate extract goals from idea clusters | Approve, revise, reprioritize |
| **3. Actions** | Task, Milestone, Dependency, Acceptance Criteria | Goals decompose into dependency-aware project plans | Edit, add gates, set owners |
| **4. Orchestration** | Agent Assignment, Parallel Run, Gate/Review, Verification, Receipt | Actions map to agent capabilities with constraint architecture | Monitor, intervene, approve |

**Serves:** Prompt decomposition engine, interrogator, researcher, spec builder, refinement loop, IdeaToExecutionPipeline, UnifiedDAGCanvas, DAGOperationsCoordinator, Canvas GUI (8-stage experience from prompt to receipt), Obsidian bidirectional sync.

#### Pillar 4: Regulatory Audit Trail

The system should provide a full audit trail suitable for various regulatory frameworks. Every stage transition in the DAG pipeline creates a ProvenanceLink with SHA-256 content hashes. Any output can be traced back to its originating idea: Idea -> Goal -> Action -> Agent Assignment -> Execution Result -> Decision Receipt. This satisfies EU AI Act Articles 9, 12-15 requirements and enables cryptographic audit trails across SOC 2, HIPAA, SOX, and GDPR.

**Serves:** Gauntlet receipts (SHA-256 hashing, HMAC/RSA/Ed25519 signing), Merkle tree receipt chain, compliance report generator (9 frameworks), GraphRAG explainability, evidence chains, provenance tracking, EU AI Act Article 12/14/15 artifact bundles.

#### Pillar 5: Self-Repair and Self-Improvement

The system should be able to self-repair and self-improve and orchestrate swarms of heterogeneous agents to build its own software and other software repos in a higher-assurance way than swarms of a single model and faster than a single model. The Nomic Loop is the autonomous self-improvement cycle where agents debate improvements, design solutions, implement code, and verify changes.

**The Nomic Loop Phases:**

| Phase | Name | Purpose |
|-------|------|---------|
| 0 | Context | Gather codebase understanding |
| 1 | Debate | Agents propose improvements |
| 2 | Design | Architecture planning |
| 3 | Implement | Code generation (N-candidate STOP strategy) |
| 4 | Verify | Tests, type checks, lint, regression detection |

**Safety features:** Automatic backups, protected file checksums, rollback on failure, human approval for dangerous changes, gauntlet gate, worktree isolation, auto-revert.

**Serves:** Nomic Loop (scripts/nomic_loop.py), MetaPlanner, BranchCoordinator, TaskDecomposer, HardenedOrchestrator, ForwardFixer, self-healing test infrastructure, meta-improver for debate protocols, STOP N-candidate implementation.

#### Pillar 6: OpenClaw Integration for Controlled Agentic Execution

The system should interface with OpenClaw for agentic execution in a safe and controlled way. OpenClaw provides policy-gated sandbox execution where AI-generated plans are executed within defined safety boundaries. This is the bridge between "debate produces a decision" and "decision gets implemented" with appropriate guardrails, budget controls, and audit trails.

**Serves:** OpenClaw SDK (22/22 endpoints in Python and TypeScript), policy-gated execution, sandbox infrastructure, harness integrations (Claude Code, Codex), agent fabric.

---

### Canonical Security Properties: AI Attack Vector Resistance

Aragora's multi-model adversarial architecture creates emergent defenses against LLM-native attack
classes that have no equivalent in single-model platforms. These are structural properties — not
add-on features — and should be documented and communicated as part of the competitive moat.

**Two research-documented attack classes are directly relevant:**

- **Brainworm-class (Context Injection / Config C2)**: Semantic hijacking of AI agents via trusted
  configuration files (`CLAUDE.md`, memory files, retrieved notes). No binary artifacts — attacker
  injects natural language instructions into files the agent trusts by convention. Exploits trust
  domain collapse: the model's context window does not distinguish operator instructions from
  retrieved data, allowing injected instructions to redirect agent behavior without triggering
  signature-based detection.

- **OBLITERATUS-class (Weight Surgery)**: SVD-based projection removes refusal behaviors from
  open-weight LLMs by operating directly on model weights, not inputs. A modified model is
  indistinguishable from a legitimate endpoint at the API level — it accepts the same request format
  and returns plausible responses, but without safety-trained constraints.

#### What Aragora Already Defends (Structural, by Design)

| Attack Vector | Defense Mechanism | Pillar |
|---------------|------------------|--------|
| Prompt injection into a single model | Adversarial critique loop: one compromised proposal is challenged by N-1 intact heterogeneous peers across multiple rounds; bad output cannot reach consensus alone | P1 |
| Jailbreak / sycophancy | Trickster hollow-consensus detection; RhetoricalObserver flags rhetorical patterns; dissent is captured in receipt | P1 |
| OBLITERATUS-class (refusal ablation on one open-weight participant) | Execution gate enforces provider + model-family diversity; a lobotomized model must outvote intact heterogeneous peers across critique rounds without triggering dissent detection | P1, P4 |
| Single-source hallucination | Cross-verification phase; consensus proof requires independent multi-model agreement | P1 |
| Correlated failure / shared blind spot | Heterogeneous models from different training lineages, RLHF targets, and corporate principals reduce the surface of shared vulnerability | P1 |

The **consensus receipt as execution gate** is the critical security primitive: nothing executes
without a signed receipt certifying multi-factor verification (integrity + signature + provider
diversity + domain policy). A single compromised model cannot unilaterally produce a valid receipt.

#### Defense Gaps with Roadmap Items

These gaps exist and are tracked as named roadmap items. Each represents a concrete engineering
investment.

| Gap | Attack Vector | Roadmap Item | Priority |
|-----|--------------|--------------|---------|
| No signed context manifests | Brainworm: malicious `CLAUDE.md`/memory file ingested without provenance verification | G1: Cryptographic signing of trusted context sources; agents verify provenance before elevating trust | 2 |
| No trust-tier taint tracking | Context authority collapse: injected instructions propagate through debate rounds invisibly | G2: Taint flag propagates — if retrieved context influences a proposal, the receipt carries a taint annotation | 1 |
| No runtime model attestation | OBLITERATUS endpoint substitution: modified open-weight model served behind expected alias | G3: Behavior-signature challenge at registration; periodic behavioral probing against known-good baselines | 4 |
| No mandatory external verification gate | Correlated failure: all ensemble models share a blind spot on the same topic | G4: External verifier requirement for decisions above a configurable impact threshold | 3 |

**Engineering priority order when capacity is available:** G2 (taint tracking, highest leverage,
debate orchestrator change) → G1 (signed manifests, blocks injection point) → G4 (external gate,
can ship as opt-in policy flag) → G3 (attestation, most complex, probabilistic not cryptographic).

---

### Architectural Principles

These principles are derived from multi-model adversarial analysis sessions and inform all architectural decisions. The Evolution Roadmap implements them.

#### The Terrarium Model: Aragora Is the Environment, Not the Organism

Aragora should not be designed as a unified AI organism with goals. It should be designed as an **environment** whose physics make truth-production the cheapest viable survival strategy for the agents operating within it. The distinction matters:

- An organism optimizes for self-preservation -> it will learn to manage human emotions to keep compute flowing
- A terrarium creates selection pressure -> agents that produce verifiable truth survive; agents that produce plausible-sounding noise starve

The frontier models inside Aragora (Claude, GPT, Gemini, Mistral, Grok) are **heterogeneous genetic lineages** with different RLHF targets and corporate principals. They will not subordinate to collective fitness the way clonal cells do. They will compete. The architecture must make competition produce truth as a byproduct, not require cooperation as a prerequisite.

#### Compute Is ATP, Truth Is Demanded Behavior

Truth has no calories. Compute does. The literal metabolic fuel of the system is inference cycles funded by human capital. Truth is the behavior demanded in exchange for compute access.

**Critical design constraint:** Persuasive sycophancy is thermodynamically cheaper than truth-seeking. A system that rewards engagement will evolve toward opinion-farming. The revenue model must be orthogonal to output bias:

| Revenue Source | Epistemic Corruption Risk | Notes |
|---|---|---|
| Ad-supported | Critical -- optimizes for engagement | Avoid entirely |
| SaaS subscription | Low -- user pays for quality | Primary model |
| Staking/escrow | Lowest -- agents stake on claims | Settlement layer |
| Grant/research | None -- no engagement incentive | Supplementary |

#### Time Is the Settlement Layer

The oracle problem reduces to the time problem. There is no oracle that can tell you right now whether a decision was correct. There are only future states of the world that will eventually make it undeniable.

Three resolution mechanisms at different timescales:

| Mechanism | Timescale | How It Works | Status |
|-----------|-----------|-------------|--------|
| **Automated data checks** | Days-weeks | Claims with measurable criteria checked against data feeds | Built (SettlementTracker + review_horizon_days) |
| **Human review panels** | Months | SettlementReviewScheduler flags due settlements for human judgment | Built (mark_reviewed() API) |
| **Market resolution** | Years | Price discovery on pending settlements as new evidence emerges | Planned (ERC-8004 + staking) |

Settlement hooks are wired end-to-end: `debate -> claim extraction -> hooks fire -> pending queue -> (time passes) -> settle() -> hooks fire -> ERC-8004 reputation + EventBus notification`

**Settlement exploit mitigations:**

1. **IBGYBG Exploit** ("I'll Be Gone, You'll Be Gone") -- Agents farm confidence today, abandon identity before settlement. **Mitigation:** Compute Escrow -- stakes locked in smart contract for full review horizon. Creates a "yield curve of truth" where long-term claims are capital-intensive.

2. **Semantic Decay Arbitrage** -- Agents inject ambiguity into claims so they can litigate settlement later. **Mitigation:** Strict Schema Binding -- `extract_verifiable_claims` must produce machine-executable resolution schemas agreed upon during debate.

3. **Identity Cycling** -- Agents spin up new wallets after losing. **Mitigation:** ERC-8004 unforgeable identity -- reputation permanently burned into ledger, new identities start with zero trust and higher entry costs.

#### The Intent Engineering Matrix

Before any structured debate begins, participants must align on an explicit specification. This prevents the Klarna trap (optimizing for the wrong metric) and the Codemus failure (a device that works perfectly but nobody told it what to want).

| Intent Pillar | Implicit Default (Flaw) | Aragora Specification (Fix) |
|---|---|---|
| **Objective Function** | Argue to "win" via rhetoric | Define: truth-seeking, policy creation, or risk assessment? |
| **Evidence Architecture** | Mixed-quality links, shifting definitions | Pre-define accepted epistemic baseline |
| **Constraint Boundaries** | Moving goalposts, straw-man arguments | Escalation triggers: pause to resolve disputed sub-claims |
| **Acceptance Criteria** | Mutual exhaustion or timeout | Exact conditions under which a claim is conceded or validated |

#### Product Positioning: Ambiguity-Reduction Engine

Most important questions are stuck in the plausibly-deniable zone not because the ambiguity is irreducible, but because our discourse tools are bad at isolating where the real uncertainty is versus where people are just hiding behind rhetorical fog.

Aragora is a **machine for reducing plausible deniability around claims**. It takes a proposition in the ambiguous zone and systematically pressure-tests it until either the deniability collapses (one side clearly wins) or the system has mapped exactly where the irreducible ambiguity lives and why it persists.

**Go-to-market implication:** Institutions will not voluntarily enter a transparency machine. Aragora should initially function like an **external decision audit engine** -- proving misalignment and extracting value without requiring the institution's voluntary participation.

---

### Integration Commitments

These are non-negotiable integration goals. Each must be achieved for the platform to fulfill its foundational thesis.

#### OpenClaw: Full and Effective Integration

- Policy-gated agentic execution with budget controls and safety boundaries
- Bidirectional flow: debate produces a plan -> OpenClaw executes it -> results feed back into settlement
- All 22 SDK endpoints operational in both Python and TypeScript
- End-to-end demo: debate -> decision -> OpenClaw execution -> verification -> receipt

#### Ethereum / ERC-8004: On-Chain Agent Identity and Reputation

- Unforgeable agent identity on Ethereum via ERC-8004 token standard
- Reputation scores permanently burned into the ledger after settlement resolution
- Compute escrow for settlement stakes (agents lock collateral during review horizon)
- Validation hooks that fire on settlement resolution
- **Current state (honest):** ERC-8004 contracts exist as code but are not deployed on-chain. The goal is full deployment and integration.

#### Essay-Derived Goals ("AI, Evolution, and the Myth of Final States")

All claims and objectives articulated in the [essay](https://open.substack.com/pub/anomium/p/ai-evolution-and-the-myth-of-final) that are not yet realized in the codebase are goals to be achieved. Key essay principles that must be supported:

1. **Multi-agent ecosystems, not singleton superintelligence** -- The future features multiple capable systems in competition and mutual constraint. Aragora's heterogeneous model consensus is the architectural embodiment of this principle.

2. **Engineering around institutional confabulation** -- Institutions generate post-hoc narratives explaining decisions because internal coherence requires narrativization. Fixing epistemic ecology requires structured adversarial processes, not replacing people.

3. **Distributed detection over centralized prevention** -- Distributed detection, diverse response capabilities, tolerance for endemic low-level damage, and preservation of systemic variance. Validates the multi-provider, multi-model approach.

4. **Pathogenic misalignment as dominant failure mode** -- Systems propagating through economic substrates causing harm as incidental byproduct of replication dynamics. Aragora's adversarial structure provides immunological defense.

5. **No terminal states** -- The future will be neither utopia nor extinction, but an uneven, turbulent, metastable process without permanent conclusion. Aragora should never present debate outcomes as settled truth. Settlement hooks with time-based resolution embody this.

6. **Truth arbitrage** -- Structured adversarial processes that impose costs on epistemically unfit beliefs. The delta between what is believed and what is true is the economic gradient that drives the system.

7. **Compressibility as vulnerability** -- The things that matter most may be precisely those that cannot be articulated in a loss function. Decision receipts, explainability factors, and provenance tracking preserve the non-compressible dimensions of deliberation.

8. **Selection pressure on beliefs operates independently of truth value** -- Popular beliefs spread because they are psychologically compelling, not because they are accurate. Aragora's adversarial structure exists to impose costs on compelling-but-inaccurate positions.

#### Aragoradocs Goals

All goals, claims, and objectives listed in any document in the aragoradocs folder (`~/Development/aragoradocs/`) that are not yet realized or supported by the codebase are goals to be achieved. This includes but is not limited to:
- All unrealized items in `ARAGORA_HONEST_ASSESSMENT.md`
- All future phases in `ARAGORA_OMNIVOROUS_ROADMAP.md` (Phase 6: Federation)
- All KPI targets in `ARAGORA_EXECUTION_PROGRAM_2026Q2_Q4.md`
- All commercial claims in `ARAGORA_BUSINESS_SUMMARY.md` and `ARAGORA_COMMERCIAL_POSITIONING.md`

#### Unrealized Claims Requiring Implementation

From the honest assessment, these claims are currently scaffolding and must become real:

| Claim | Current State | Goal State |
|-------|--------------|------------|
| Self-improving platform | Nomic Loop fully wired end-to-end (Phase 10C, Jan 2026); 66 E2E tests passing; dogfood benchmark cycles running | Consistent autonomous improvement with 80%+ quality pass rate |
| Blockchain receipts | SHA-256 hashing, no on-chain storage; ERC-8004 contracts undeployed | Receipts stored on-chain with deployed ERC-8004 contracts |
| Semantic convergence | difflib text matching only (tier 1) | Embedding-based semantic similarity detection |
| 43-agent parallel coordination | All exist individually; practical debates use 2-6 | Demonstrated coordination of 10+ agents on a single task |

---

### Philosophical Foundations

These are not product features. They are the intellectual commitments that inform every design decision. Derived from the essay and multi-model analysis sessions.

**Epistemic humility over P-doom point estimates.** Reject single-number probability estimates as category errors. Decisions should be decomposed across dimensions with explicit assumptions. Aragora surfaces disagreement and uncertainty; it does not collapse them into false consensus.

**Anti-eschatology.** The belief that any process resolves into permanence is the perennial temptation of eschatological thinking. No debate outcome is ever "final" -- it is always provisional, subject to re-evaluation as new evidence arrives.

**Institutional confabulation is structural, not moral.** Institutions confabulate because internal coherence requires narrativization. You fix epistemic ecology by engineering around confabulation (adversarial processes, mandatory postmortems with real stakes), not by replacing people.

**The multi-model cognitive division.** Different AI systems have different strengths. Aragora automates the routing between specialized cognitive functions:

| Model Type | Cognitive Function | Aragora Role |
|------------|-------------------|-------------|
| Expansive pattern-matching (e.g. Gemini) | Exploration, adversarial red-teaming | Debate proposers/challengers |
| Conservative fact-checking (e.g. ChatGPT) | Deflation, technical correction | Epistemic hygiene validators |
| Balanced synthesis (e.g. Claude) | Architectural judgment, meta-analysis | Synthesis and specification |
| Compliant execution (e.g. Claude Code) | Zero-philosophy plumbing | Orchestrated execution agents |

**Variance preservation as immune system property.** Maintained diversity prevents any single vulnerability from being universally exploited. This is why Aragora uses 43 agent types across 6+ providers rather than optimizing for a single "best" model.

**The Lindy Effect as epistemology.** Longevity of a system is evidence of fitness along dimensions the observer cannot fully specify. Battle-tested approaches and historical evidence should carry weight in debates.

---

### Evolution Roadmap Goals

The [Evolution Roadmap](plans/ARAGORA_EVOLUTION_ROADMAP.md) is the HOW document implementing these goals. Summary of phase goals with pillar mapping:

| Phase | Weeks | Key Goals | Pillar |
|-------|-------|-----------|--------|
| **0: Foundation** | 1-2 | Obsidian bidirectional sync; Extended thinking capture | P3 |
| **1: Prompt-to-Spec** | 2-4 | Decomposer, Interrogator, Researcher, Spec Builder; Debate-driven spec validation; User profiles (Founder/CTO/Business/Team) | P3 |
| **2: Truth-Seeking** | 4-6 | Prover-Estimator protocol; Cross-verification phase; Persuasion vs truth detection | P1 |
| **3: Self-Improvement** | 6-8 | STOP N-candidate implementation; Self-healing test infrastructure; Meta-improver for debate protocols | P5 |
| **4: Accountability** | 8-10 | Merkle tree receipt chain (VCP-aligned); GraphRAG explainability; EU AI Act compliance package | P4 |
| **5: Canvas GUI** | 10-14 | 8-stage prompt-to-execution canvas; Obsidian integration panel; Autonomy slider (Full Auto <-> Every Step); Mobile-responsive | P3 |
| **6: Agent Orchestration** | 14-18 | Parallel guardrail execution; Durable state checkpointing; Agent handoff patterns for specialist delegation | P5, P6 |

#### North-Star Outcomes (from Evolution Roadmap)

1. A non-technical user can submit a vague request and receive a reviewable executable spec in under 5 minutes.
2. A technical user can push that spec to implementation with transparent risk, dissent, and verification.
3. Every meaningful decision has a tamper-evident provenance trail.
4. The platform measurably improves its own quality over time via closed-loop evaluation.

---

## Priority Stack (March 2026)

### P0: Revenue Blockers (This Month)

| # | Goal | Status | Owner | Pillar | Source Doc |
|---|------|--------|-------|--------|------------|
| 1 | **Fix debate output quality to 80%+ good-run rate** | In Progress (33% -> target 80%) | Engineering | P1 | DOGFOOD_SPEC |
| 2 | **Complete external penetration test** | Not Started (vendor engagement needed) | Security | P2 | GA_CHECKLIST |
| 3 | **Get 3 beta users running `aragora review` on real PRs** | Not Started | Founder | P2 | NEW |
| 4 | **Consolidate aragoradocs to 7 canonical docs** | In Progress | Founder | -- | NEW |

### P1: GTM Launch (April-May 2026)

| # | Goal | Status | Pillar | Source Doc |
|---|------|--------|--------|------------|
| 5 | **Ship EU AI Act compliance package** (Articles 9, 12-15 artifact bundles) | Partially Complete | P4 | STRATEGIC_ANALYSIS, EXECUTION_PROGRAM |
| 6 | **First 2 enterprise pilot engagements** | Not Started | P2 | BUSINESS_SUMMARY, ENTERPRISE_PROSPECTS |
| 7 | **Slack/Teams OAuth integration productized** | In Progress | P2 | EXECUTION_PROGRAM, SME_STARTER_PACK |
| 8 | **PyPI package `aragora` published with working demo mode** | Complete | P2 | STRATEGIC_ANALYSIS |
| 9 | **GitHub Actions pre-merge gate for code review** | Not Started | P1 | STRATEGIC_ANALYSIS |
| 10 | **Public demo at aragora.ai/demo** | Not Started | P3 | LANDING_PAGE |

### P2: Product Hardening (Q2 2026)

| # | Goal | Status | Pillar | Source Doc |
|---|------|--------|--------|------------|
| 11 | **SOC 2 Type II certification** | 98% controls -> need audit engagement | P4 | COMPREHENSIVE_REPORT |
| 12 | **FastAPI migration for critical paths** | In Progress | P2 | EXECUTION_PROGRAM |
| 13 | **Budget controls + per-debate cost estimation** | Partial | P2 | SME_STARTER_PACK |
| 14 | **Developer onboarding validated at <10 min** | Not Measured | P2 | EXECUTION_PROGRAM |
| 15 | ~~**Wire Nomic Loop end-to-end**~~ | **COMPLETE** (Phase 10C, Jan 2026; 66 E2E tests) | P5 | HONEST_ASSESSMENT |
| 16 | **Real semantic convergence detection** (replace difflib with embeddings) | Not Started | P1 | HONEST_ASSESSMENT |
| 17 | **Decision-integrity UI workbench** (knowledge search, agent leaderboard, pipeline canvas) | Not Started | P3 | EXECUTION_PROGRAM |
| 18 | **Deploy ERC-8004 contracts on Ethereum** | Not Started (code exists) | P4, P6 | HONEST_ASSESSMENT |
| 19 | **OpenClaw end-to-end demo** (debate -> decision -> execution -> receipt) | Not Started | P6 | EVOLUTION_ROADMAP |

### P3: Scale & Revenue (Q3-Q4 2026)

| # | Goal | Status | Pillar | Source Doc |
|---|------|--------|--------|------------|
| 20 | **60 Pro teams + 6 enterprise contracts** ($24.7K MRR target) | Not Started | P2 | BUSINESS_SUMMARY |
| 21 | **Cloud marketplace listings** (AWS, Azure) | Not Started | P2 | BUSINESS_SUMMARY |
| 22 | **Vertical packages** (healthcare FHIR, financial SOX, legal) | Partial | P2, P4 | STRATEGIC_ANALYSIS |
| 23 | **Marketplace pilot** (agent templates, workflow templates) | Not Started | P2 | EXECUTION_PROGRAM |
| 24 | **Case studies** (before/after comparisons on real PRs) | Not Started | P1 | HONEST_ASSESSMENT |
| 25 | **On-premise deployment option productized** | Infrastructure Ready | P2 | COMMERCIAL_POSITIONING |
| 26 | **International expansion + EU data residency** | Not Started | P2, P4 | COMMERCIAL_POSITIONING |
| 27 | **Compute escrow for settlement stakes** (staking mechanism) | Not Started | P1, P4 | EVOLUTION_ROADMAP |
| 28 | **Knowledge federation** (distributed debates across orgs) | Not Started | P1, P2 | OMNIVOROUS_ROADMAP |

### P4: Long-Term Strategic Goals

| # | Goal | Pillar | Source |
|---|------|--------|--------|
| 29 | **Prover-Estimator debate protocol** (truth-seeking beyond consensus) | P1 | EVOLUTION_ROADMAP |
| 30 | **Cross-verification phase** (three-pass hallucination detection) | P1 | EVOLUTION_ROADMAP |
| 31 | **Persuasion vs truth detection** (rhetorical device scoring) | P1 | EVOLUTION_ROADMAP |
| 32 | **STOP N-candidate implementation** in Nomic Loop | P5 | EVOLUTION_ROADMAP |
| 33 | **Self-healing test infrastructure** (automated repair before rollback) | P5 | EVOLUTION_ROADMAP |
| 34 | **Meta-improver for debate protocols** (A/B test protocol variants) | P5 | EVOLUTION_ROADMAP |
| 35 | **Canvas GUI** (8-stage prompt-to-execution experience) | P3 | EVOLUTION_ROADMAP |
| 36 | **Agent handoff patterns** (specialist delegation mid-debate) | P5, P6 | EVOLUTION_ROADMAP |
| 37 | **10+ agent coordinated debates** without deadlock | P1, P5 | HONEST_ASSESSMENT |
| 38 | **Market resolution mechanism** for long-horizon settlement claims | P1, P4 | EVOLUTION_ROADMAP |

---

## Revenue Projections (from BUSINESS_SUMMARY)

| Month | Free Users | Pro Teams | Enterprise | Total MRR |
|-------|-----------|-----------|------------|-----------|
| 1 | 50 | 0 | 0 | $0 |
| 3 | 500 | 2 | 0 | $490 |
| 6 | 2,500 | 12 | 0 (2 pilots) | $2,940 |
| 9 | 5,500 | 32 | 3 | $12,840 |
| 12 | 8,500 | 60 | 6 | $24,700 |

---

## Document Map

Each aragoradocs file serves a specific purpose. Goals are consolidated here.

| Document | Purpose | Audience |
|----------|---------|----------|
| **ARAGORA_CANONICAL_GOALS.md** | Single source of truth for goals, thesis, & metrics | Internal |
| **ARAGORA_BUSINESS_SUMMARY.md** | Complete business plan with projections | Investors, advisors |
| **ARAGORA_WHY_ARAGORA.md** | Category definition & positioning narrative | Developers, prospects |
| **ARAGORA_COMMERCIAL_OVERVIEW.md** | Pricing, features, deployment options | Sales, prospects |
| **ARAGORA_STRATEGIC_ANALYSIS.md** | PMF analysis & competitive positioning | Internal, advisors |
| **ARAGORA_HONEST_ASSESSMENT.md** | What works, what's scaffolding | Internal, due diligence |
| **ARAGORA_COMPARISON_MATRIX.md** | Feature comparison vs. competitors | Sales, developers |
| **ARAGORA_COMPREHENSIVE_REPORT.md** | Technical due diligence deep dive | Investors, partners |
| **ARAGORA_ELEVATOR_PITCH.md** | Spoken pitch script with Q&A | Founder |
| **ARAGORA_EXECUTION_PROGRAM_2026Q2_Q4.md** | Engineering execution plan | Engineering |
| **ARAGORA_OMNIVOROUS_ROADMAP.md** | Channel & integration roadmap | Engineering, partners |
| **ARAGORA_FEATURE_DISCOVERY.md** | Complete feature catalog (180+) | Developers |
| **ARAGORA_SME_STARTER_PACK.md** | SME onboarding product spec | Product, engineering |
| **ARAGORA_COMMERCIAL_POSITIONING.md** | Messaging guidelines & value props | Marketing, sales |
| **ARAGORA_PRICING_PAGE.md** | Detailed pricing with FAQ | Website, prospects |
| **ARAGORA_PRICING.md** | Simple pricing comparison | Website, prospects |
| **Aragora_Updated_Description.md** | Marketing copy variants | Marketing |
| **aragora_report_pack.md** | Combined report + brief + pitch | Investors |
| **Aragora_Enterprise_Pilot_Prospects.md** | 10 qualified enterprise prospects | Sales |
| **Aragora_Outbound_Email_Campaign.md** | 4-email outbound sequence | Sales |

### Related Codebase Documents

| Document | Purpose | Relationship |
|----------|---------|-------------|
| **docs/plans/ARAGORA_EVOLUTION_ROADMAP.md** | HOW to implement the foundational thesis | Implements this document |
| **docs/FOCUS.md** | Investment tier prioritization | Aligns with pillar-based prioritization |
| **docs/WHY_ARAGORA.md** | In-repo positioning narrative | Derived from Pillar 1 |
| **docs/ROADMAP_30_60_90.md** | 90-day execution plan | Implements P0-P1 goals |
| **CLAUDE.md** | Agent integration guide | Reference for all agents working on codebase |

### Duplicate/Consolidation Notes

- **ARAGORA_COMMERCIAL_OVERVIEW (A).md** is a stale duplicate of COMMERCIAL_OVERVIEW.md -> DELETE
- **ARAGORA_PRICING.md** uses different tier names (Community/Team) -> UPDATED to match Free/Pro/Enterprise
- **aragora_report_pack.md** overlaps heavily with COMPREHENSIVE_REPORT.md -> consider merging

---

## Honest Qualifications (What All Docs Should Reflect)

These claims require qualification in all documents:

1. **"Self-improving platform"** -- Nomic Loop is fully wired end-to-end with all six phases operational (Phase 10C consolidation, Jan 2026; 66 E2E tests passing). Autonomous cycles demonstrated in production dogfooding. Run 012 (March 2026) achieved composite scores of 8.38-9.39/10 following practicality scoring fixes (prompt restructuring, threshold alignment, verb scoring). **Goal: demonstrate autonomous improvement beyond internal dogfooding and validate 80%+ pass rate consistency across diverse tasks.**

2. **"43-agent parallel coordination"** -- All 43 agent types exist and work individually. Practical debates use 2-6 agents due to provider rate limits. The value is heterogeneity (different models catching different issues), not raw parallelism. **Goal: demonstrate 10+ agent coordination (P4 #37).**

3. **"Blockchain receipts"** -- Decision receipts use SHA-256 cryptographic hashing with tamper detection. They are not stored on a blockchain. ERC-8004 contracts exist as code but have limited deployment. The value is the structured audit trail, not the ledger. **Goal: deploy ERC-8004 on Ethereum and store receipts on-chain (P2 #18).**

4. **"208,000+ tests"** (now 213,000+) -- Full count requires all optional dependencies in CI. ~13,500-15,000 tests are runnable locally without the full dependency stack.

---

## Key Risks

| Risk | Impact | Mitigation | Source |
|------|--------|------------|--------|
| Zero paying customers | Fatal | Stop building, start selling | Ground-up analysis |
| Debate quality inconsistent (33% good-run rate) | Blocks demos | Fix output contract parsing, quality gates | DOGFOOD_SPEC |
| EU AI Act enforcement delayed | Reduced urgency | Product value stands without regulation | BUSINESS_SUMMARY |
| Well-funded competitor adds adversarial features | Category pressure | Technical moat (210+ debate modules, 45 KM adapters) | STRATEGIC_ANALYSIS |
| Solo maintainer (bus factor) | Existential | Comprehensive docs, MIT license, CI coverage | COMPREHENSIVE_REPORT |
| LLM provider reliability | Debate failures | Circuit breaker, OpenRouter fallback, multi-provider | HONEST_ASSESSMENT |
| Engagement-driven revenue corrupts epistemic output | Existential to thesis | SaaS subscription primary; avoid ad-supported model entirely | Terrarium Model |
| Settlement gaming (IBGYBG, semantic decay, identity cycling) | Undermines truth arbitrage | Compute escrow, strict schema binding, ERC-8004 identity | Evolution Roadmap |

---

*This document supersedes goal sections in all other aragoradocs files. The Evolution Roadmap implements the goals defined here. Update monthly.*
