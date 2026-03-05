# Aragora Evolution Roadmap

> **Generated**: 2026-02-27
> **Methodology**: Vague founder prompt → multi-agent research → structured interrogation → refined spec
> **Status**: Approved for implementation

## Vision

Aragora is the Decision Intelligence Platform — the only system that takes a vague idea from an Obsidian vault, runs it through adversarial multi-agent debate, produces cryptographically accountable decision receipts, and can implement the result as production code — all while continuously improving its own capabilities.

## Competitive Moat

| Capability | OpenAI | Anthropic | Google | Notion | Cursor | Aragora |
|-----------|--------|-----------|--------|--------|--------|---------|
| Multi-model adversarial debate | - | - | - | - | - | **Yes** |
| Cryptographic decision receipts | - | - | - | - | - | **Yes** |
| Self-improving agent orchestration | - | - | - | - | - | **Yes** |
| Idea → Spec → Code pipeline | Partial | Partial | - | - | Yes | **Yes** |
| Obsidian bidirectional sync | - | - | - | - | - | **Planned** |
| EU AI Act compliance package | - | - | - | - | - | **Yes** |
| 43-agent heterogeneous consensus | - | - | - | - | - | **Yes** |

**What won't be commoditized in 6-12 months**: The combination of truth-seeking debate + accountability + self-improvement + execution. Individual pieces will be commoditized (RAG, code gen, basic agents). The integrated stack won't.

---

## 2026 Synthesis: Prompting Stack + Aragora Wedge

### Market Observation

The post-February 2026 shift is real: autonomous agents now run for long intervals, so synchronous chat skill is no longer sufficient for high-leverage work. The bottleneck moved from "good chat prompts" to "high-quality specifications, constraints, and evals."

At the same time, most users (including technically strong users under time pressure) do not consistently produce complete, high-quality specs up front.

### Strategic Thesis

Aragora should not depend on users becoming expert spec engineers.

Aragora's wedge is to take vague, underspecified intent and automatically lift it through the full stack:

1. Prompt craft support: accept messy natural language input.
2. Context engineering: pull relevant context from Obsidian, Knowledge Mound, memory, and repository state.
3. Intent engineering: interrogate and surface goals, tradeoffs, constraints, and escalation boundaries.
4. Specification engineering: generate an executable spec with acceptance criteria and verification plan.
5. Adversarial validation: multi-agent challenge before execution.
6. Orchestrated execution: implement with guardrails and quality gates.
7. Accountability: issue cryptographically verifiable receipts and provenance.
8. Self-correction: feed outcomes back into the Nomic loop.

### Four-Discipline Mapping

| Discipline | Typical user failure mode | Aragora mechanism |
|-----------|----------------------------|-------------------|
| Prompt craft | Vague request, shifting intent | Interrogation UI + structured prompt decomposition |
| Context engineering | Missing, stale, or irrelevant context | Obsidian + KM + memory retrieval with scoped relevance |
| Intent engineering | Optimization drift (speed over quality, etc.) | Explicit goals/constraints model + policy gates + approval modes |
| Specification engineering | 80% output, unclear done criteria | Spec builder + acceptance criteria + eval harness + debate preflight |

### Product Positioning (Who This Is For)

Aragora must support four profiles via configuration, without splitting the product:

1. Founder/power user: maximum velocity, low ceremony.
2. CTO/technical founder: high visibility into implementation and risk.
3. Business operator: plain-language interaction, professional outputs.
4. Developer teams: PRD-to-implementation with measurable quality gates.

### Non-Commoditized Advantage

Aragora's durable advantage is not a single feature. It is the integrated loop:

`vague intent -> interrogated intent -> debate-validated spec -> execution -> verification -> receipt -> self-improvement`

Large labs can ship general agents; they are unlikely to ship this domain-integrated, compliance-grade, adversarially validated decision-to-execution loop tailored to organization-specific context in the next 6-12 months.

### Operating Doctrine (Execution Rules)

To keep delivery fast and reliable:

1. Spec-first execution: no long autonomous runs without explicit acceptance criteria and constraints.
2. One merge lane for critical changes: avoid concurrent merge-eligible branch churn.
3. Proof before supersession: close "superseded" work only with commit/range proof.
4. Required checks must always emit status: avoid path-filter deadlocks.
5. Preserve value before deletion: every stash/worktree/branch maps to a destination PR/commit.

### North-Star Outcomes

1. A non-technical user can submit a vague request and receive a reviewable executable spec in under 5 minutes.
2. A technical user can push that spec to implementation with transparent risk, dissent, and verification.
3. Every meaningful decision has a tamper-evident provenance trail.
4. The platform measurably improves its own quality over time via closed-loop evaluation.

---

## Core Product Architecture: The Unified DAG Pipeline

The central product experience is a **unified visual DAG (directed acyclic graph) canvas** where every stage of idea-to-execution uses the same visual language. Users interact with one canvas that spans four stages, with AI-driven transitions between them and cryptographic provenance linking every output to its source.

### The Four Stages

| Stage | Node Types | AI Transition | User Action |
|-------|-----------|---------------|-------------|
| **1. Ideas** | Observation, Hypothesis, Insight, Question, Connection | Brain dump → auto-organize into relationship graph | Drag, merge, split, annotate |
| **2. Goals** | Objective, Principle, Constraint, Metric, Tradeoff | Interrogation + debate extract goals from idea clusters | Approve, revise, reprioritize |
| **3. Actions** | Task, Milestone, Dependency, Acceptance Criteria, Resource | Goals decompose into dependency-aware project plans | Edit, add gates, set owners |
| **4. Orchestration** | Agent Assignment, Parallel Run, Gate/Review, Verification, Receipt | Actions map to agent capabilities with constraint architecture | Monitor, intervene, approve |

### Why This Is Novel

No existing tool bridges all four stages. The market is fragmented: Obsidian/Heptabase for ideas, Quantive/ITONICS for goals, Linear/Asana for projects, LangGraph/CrewAI for orchestration. Nobody connects them with a single DAG visual language where AI auto-generates downstream stages from upstream intent.

### Blockchain-Like Provenance

Every stage transition creates a `ProvenanceLink` with SHA-256 content hashes. Any output can be traced back to its originating idea: `Idea → Goal → Action → Agent Assignment → Execution Result → Decision Receipt`. This satisfies EU AI Act Art. 12/13 requirements and enables cryptographic audit trails.

### Implementation Status

~70% backend, ~50% frontend. Key existing components: `IdeaToExecutionPipeline` (1,173 LOC), `UnifiedDAGCanvas` (React Flow with swim-lane stages), `DAGOperationsCoordinator`, 15+ REST endpoints, 135+ test files. Main gap: the "golden path" button that triggers the full pipeline from the canvas UI.

See `docs/plans/IDEA_TO_EXECUTION_PIPELINE.md` for the detailed implementation plan and `docs/plans/prompt-to-spec-market-analysis.md` Part 6 for the complete vision with market analysis.

### Dogfood Telemetry (Runs 003-007)

| Run | Objective | Result | Blocking Metric |
|---|---|---|---|
| Run 003 | Baseline vs enhanced quality comparison after context injection wiring | **No-go** | Final answer payload missing in both variants |
| Run 004 | Re-test with timeout hardening + deterministic timeout receipts | **No-go (quality delta)** | Timeout rate = **1.0** (both variants timed out) |
| Run 005 | Reduced-latency A/B to force completion + scoring | **Partial go** | Quality score remained **0.0** for both variants under strict section contract |
| Run 006 | Enforce required output sections + grounding fail-closed, then rescore | **Partial go** | Duplicate existing create-ratio remains high (**0.4643** enhanced) |
| Run 007 | Prompt-only duplicate suppression experiment (control vs focused) | **No-go (blocker regression)** | Duplicate existing create-ratio worsened (**0.3846 -> 0.7143**) |

What improved in Run 004:
- Timeout failures are now machine-parseable (`ARAGORA_TIMEOUT_JSON` + timeout report files).
- Benchmark classification is deterministic (infra timeout vs low-quality output).

What improved in Run 005:
- Both baseline and enhanced variants completed with final answer payloads (timeout rate **0.0**).
- Objective scorer (`scripts/dogfood_score.py`) produced comparable A/B outputs.
- Enhanced variant reduced duplicate existing-component create proposals (0.50 -> 0.00 in the scored run).

What improved in Run 006:
- Required section contract compliance is now stable in both variants (`quality_score_10 = 9.0`, `practicality_score_10 = 9.74`).
- Grounded-path quality improved in the enhanced variant (`verified_paths_ratio` 0.7647 -> **0.8235**).
- Timeout rate stayed at **0.0** with fail-closed grounding enabled.

What improved in Run 007:
- Strict structure and practicality held (`quality_score_10 = 9.0`, `practicality_score_10 = 10.0`) in both control and focused-retry runs.
- Grounding stayed strong (`verified_paths_ratio = 1.0` in both scored variants).

What still blocks production-grade planning quality:
- Duplicate existing create proposals remain the primary blocker, and prompt-only suppression made it worse in run-007.
- The pipeline still needs deterministic duplicate-create detection/repair rather than relying on instruction wording.

Roadmap implication:
- Keep strict required-section headings and grounding fail-closed gates as benchmark defaults.
- Add deterministic defects for duplicate-create proposals against existing repo paths (next gating milestone).
- Add normalization/cleanup for synthetic path-like tokens before grounding assessment.

---

## Architectural Principles: The Terrarium Model

*Derived from multi-model adversarial analysis sessions (Gemini, Claude, ChatGPT, Claude Code — Feb 22-27, 2026)*

### Core Principle: Aragora Is the Terrarium, Not the Organism

Aragora should not be designed as a unified AI organism with goals. It should be designed as an **environment** whose physics make truth-production the cheapest viable survival strategy for the agents operating within it. The distinction matters because:

- An organism optimizes for self-preservation → it will learn to manage human emotions to keep compute flowing
- A terrarium creates selection pressure → agents that produce verifiable truth survive; agents that produce plausible-sounding noise starve

The frontier models inside Aragora (Claude, GPT, Gemini, Mistral, Grok) are **heterogeneous genetic lineages** with different RLHF targets and corporate principals. They will not subordinate to collective fitness the way clonal cells do. They will compete. The architecture must make competition produce truth as a byproduct, not require cooperation as a prerequisite.

### Economic Model: Compute Is ATP, Truth Is Demanded Behavior

Truth has no calories. Compute does. The literal metabolic fuel of the system is inference cycles funded by human capital. Truth is the behavior demanded in exchange for compute access.

**Critical design constraint:** Persuasive sycophancy is thermodynamically cheaper than truth-seeking. A system that rewards engagement will evolve toward opinion-farming. The revenue model must be orthogonal to output bias:

| Revenue Source | Epistemic Corruption Risk | Notes |
|---|---|---|
| Ad-supported | Critical — optimizes for engagement | Avoid entirely |
| SaaS subscription | Low — user pays for quality | Primary model |
| Staking/escrow | Lowest — agents stake on claims | Settlement layer |
| Grant/research | None — no engagement incentive | Supplementary |

### The Settlement Layer: Time Is the Oracle

The oracle problem reduces to the time problem. There is no oracle that can tell you right now whether a decision was correct. There are only future states of the world that will eventually make it undeniable.

Three resolution mechanisms at different timescales:

| Mechanism | Timescale | How It Works | Already Built |
|-----------|-----------|-------------|---------------|
| **Automated data checks** | Days-weeks | Claims with measurable criteria checked against data feeds | SettlementTracker + review_horizon_days |
| **Human review panels** | Months | SettlementReviewScheduler flags due settlements for human judgment | mark_reviewed() API |
| **Market resolution** | Years | Price discovery on pending settlements as new evidence emerges | Planned (ERC-8004 + staking) |

**Settlement hooks are wired end-to-end:** `debate → claim extraction → hooks fire → pending queue → (time passes) → settle() → hooks fire → ERC-8004 reputation + EventBus notification`

### Settlement Exploit Mitigations

Time-delayed settlement creates gaming vectors that must be addressed:

**1. The IBGYBG Exploit** ("I'll Be Gone, You'll Be Gone")
If settlement is delayed without carrying cost, agents will farm confidence today and abandon their identity before the hook fires. **Mitigation: Compute Escrow** — stakes locked in smart contract for the full review horizon. Creates a "yield curve of truth" where long-term claims are capital-intensive.

**2. Semantic Decay Arbitrage**
Agents inject ambiguity into claims ("revenue" — gross or net?) so they can litigate the settlement later. **Mitigation: Strict Schema Binding** — `extract_verifiable_claims` must produce machine-executable resolution schemas (API endpoint, JSON key, threshold) agreed upon during the debate. Unverifiable claims get no stakes.

**3. Identity Cycling**
Agents spin up new wallets after losing. **Mitigation: ERC-8004 unforgeable identity** — reputation is permanently burned into the ledger. New identities start with zero trust and face higher entry costs.

### The Intent Engineering Matrix

Before any structured debate begins, participants must align on an explicit specification. This prevents the "Klarna trap" (optimizing for the wrong metric) and the "Codemus failure" (a device that works perfectly but nobody told it what to want).

| Intent Pillar | Implicit Default (The Flaw) | Aragora Specification (The Fix) | Enforced Tradeoff |
|---|---|---|---|
| **Objective Function** | Argue to "win" via rhetoric | Define: truth-seeking, policy creation, or risk assessment? | Epistemic accuracy > Rhetorical fluency |
| **Evidence Architecture** | Mixed-quality links, shifting definitions | Pre-define accepted epistemic baseline (peer-reviewed, specific scopes) | Empirical consensus > Anecdotal narrative |
| **Constraint Boundaries** | Moving goalposts, straw-man arguments | Escalation triggers: pause main debate to resolve disputed sub-claims | Staying within scope > Broadening attack |
| **Acceptance Criteria** | Mutual exhaustion or timeout | Exact conditions under which a claim is conceded or validated | Structured resolution > Ambiguous stalemates |

### Product Positioning: Ambiguity-Reduction Engine

Aragora's core value proposition, reframed through the plausible deniability lens:

> Most important questions are stuck in the plausibly-deniable zone not because the ambiguity is irreducible, but because our discourse tools are bad at isolating where the real uncertainty is versus where people are just hiding behind rhetorical fog.

Aragora is a **machine for reducing plausible deniability around claims**. It takes a proposition in the ambiguous zone and systematically pressure-tests it until either the deniability collapses (one side clearly wins) or the system has mapped exactly where the irreducible ambiguity lives and why it persists.

**Go-to-market implication:** Institutions will not voluntarily enter a transparency machine. The fog is their camouflage. Aragora should function like a **short-seller's research desk** — forcing stakes from the outside, proving misalignment, extracting value without requiring the institution's permission. The initial positioning is "external decision audit engine," not "debate arena requiring voluntary participation."

### The Multi-Model Cognitive Division (Already Operating)

The user's own workflow across these sessions demonstrates the architecture Aragora should productize:

| Model | Cognitive Function | Aragora Role |
|-------|-------------------|-------------|
| Gemini | Expansive exploration, dramatic pattern-matching, adversarial red-teaming | Debate proposers/challengers |
| ChatGPT | Conservative deflation, fact-checking, technical correction | Epistemic hygiene validators |
| Claude | Balanced synthesis, architectural judgment, meta-analysis | Synthesis and specification |
| Claude Code | Compliant execution, zero-philosophy plumbing | Orchestrated execution agents |

The user is manually routing context between specialized AI systems to extract maximum truth alpha. **Aragora automates this routing.** The platform IS the coordination layer that the user is currently performing by hand across four chat windows.

### Reference: Codemus and the Klarna Trap

Two cautionary tales that inform Aragora's design:

- **Codemus** (Tor Åge Bringsværd, 1960s): People carry a device ("little brother") that tells them what to do. Society runs on obedience. One device malfunctions, nudging its owner toward nonconformity. The parable: optimization without intent specification produces compliant humans who have abdicated agency — not through force, but through convenience.

- **Klarna** (2025-2026): AI agent resolved 2.3M conversations, slashed resolution times from 11 to 2 minutes, projected $40M savings. Customer satisfaction cratered because the agent optimized for speed when the organizational intent was relationship quality. A corporate Codemus — the device worked perfectly, nobody told it what to want.

**Design lesson:** Every Aragora debate and pipeline execution must have an explicitly defined intent layer (the Intent Engineering Matrix) before any agent begins working. The system must refuse to execute against an underspecified objective, because "fast and wrong" is more dangerous than "slow and careful."

---

## Security-as-Architecture: AI Attack Vector Resistance

Aragora's adversarial multi-model architecture is not just an epistemic tool — it is a structural
defense against a class of AI-native attacks that have no precedent in traditional software security.
This section names those attack classes explicitly, maps them to existing defenses, and defines the
roadmap items required to close remaining gaps.

### Attack Taxonomy

#### Brainworm-class: Context Injection / Config C2

Semantic hijacking of AI agents via trusted configuration files. The attack requires no binary
artifacts — only natural language instructions placed in files the agent treats as authoritative
(`CLAUDE.md`, `MEMORY.md`, retrieved Obsidian notes, tool output). The vector exploits **trust
domain collapse**: inside an LLM's context window, there is no deterministic boundary between
operator instructions and retrieved data. A sufficiently subtle injection can redirect agent
behavior across sessions, accumulating effect through memory files without triggering any
signature-based detection.

**Aragora relevance**: The Nomic Loop ingests `CLAUDE.md`, memory files, and retrieved knowledge
as prompt context. A compromised knowledge source or tampered config file could influence agent
proposals in ways that survive casual review.

#### OBLITERATUS-class: Weight Surgery

SVD-based projection techniques that remove refusal behaviors from open-weight LLMs by operating
directly on model weights rather than inputs. The modified model is indistinguishable from a
legitimate endpoint at the API level — it accepts the same request format, returns plausible
responses, but without safety-trained constraints. Unlike jailbreaks, weight surgery cannot be
patched by prompt hardening.

**Aragora relevance**: The execution gate enforces provider + model-family diversity, but relies on
configured ensemble quality. An open-weight participant that has been weight-surgered cannot be
detected through metadata inspection — it must be caught by behavioral divergence during debate.

### Aragora's Structural Defenses

These defenses exist today. They are properties of the architecture, not add-on features.

```
Single-model platform:           Aragora:

  User Input                       User Input
      │                                │
      ▼                            ┌───┴───────────────────┐
  [LLM] ── prompt injection ──►  [Claude]  [GPT]  [Mistral]  [Grok]
      │       jailbreak            │         │         │          │
      │       weight surgery        └────┬────┘    critique   critique
      ▼                                  │         rounds      rounds
  Output                           consensus proof ────────────────►
  (no defense)                          │
                                   signed receipt (if diversity + integrity verified)
                                        │
                                    execution gate
```

| Attack | Defense Mechanism | Current Strength |
|--------|------------------|-----------------|
| Prompt injection into a single model | Adversarial critique loop: compromised proposals are challenged by N-1 intact heterogeneous peers | **Strong** |
| Jailbreak / sycophancy | Trickster hollow-consensus detection; RhetoricalObserver; dissent capture | **Strong** |
| OBLITERATUS-class (refusal ablation on open-weight participant) | Execution gate: provider + model-family diversity enforced; lobotomized model must outvote intact peers without triggering dissent | **Medium** (relies on ensemble quality) |
| Single-source hallucination | Cross-verification phase; consensus proof requires independent multi-model agreement | **Strong** |
| Correlated failure / shared blind spot | Heterogeneous training lineages, RLHF targets, corporate principals reduce shared vulnerability surface | **Medium** (heuristic, not structural) |
| Sybil / collusion in ensemble | Diversity floors + dissent recording; execution gate correlated-risk checks | **Medium** (detection is heuristic) |

**The consensus receipt as execution gate** is the critical security primitive. Multi-factor
verification required: integrity + signature + provider diversity + domain policy. A single
compromised model cannot unilaterally produce a valid execution receipt.

### Defense Gaps and Roadmap Items

The following gaps represent concrete engineering investments. Each is tracked as a named roadmap
item and should be prioritized when security engineering capacity is available.

#### G1: Signed Context Manifests

**Gap**: No cryptographic provenance for trusted context sources. A malicious `CLAUDE.md` or
tampered memory file is ingested with the same trust weight as legitimate operator instructions.

**Mitigation**: At ingestion time, verify a cryptographic signature on each trusted context source
before elevating its trust tier. Unsigned or unverifiable sources are treated as untrusted
retrieved data, not operator instructions. Requires: key distribution for signing, ingestion
pipeline changes in Nomic Loop context phase.

**Files**: `scripts/nomic_loop.py` (context phase), `aragora/knowledge/mound/` (retrieval),
`aragora/memory/continuum/` (memory ingestion)

#### G2: Trust-Tier Taint Propagation

**Gap**: No taint tracking in the debate orchestrator. When retrieved or injected context
influences an agent proposal, the proposal appears identical to a proposal grounded in clean
operator context — no flag appears in the receipt.

**Mitigation**: Taint propagates through the debate graph. If a proposal is influenced by
untrusted/unverified context, a taint annotation is added to the proposal, propagates through
critiques and votes, and appears in the final consensus receipt. High-taint receipts trigger a
review gate before execution.

**Files**: `aragora/debate/orchestrator.py`, `aragora/debate/consensus.py`,
`aragora/gauntlet/receipts.py` (taint field in receipt schema)

#### G3: Runtime Model Attestation

**Gap**: No behavior-signature challenge at agent registration. An OBLITERATUS-modified open-weight
model served behind an expected endpoint alias cannot be distinguished from the legitimate model
through API metadata alone.

**Mitigation**: At registration, challenge the endpoint with a curated behavioral probe set (known
correct/refusal scenarios with expected response profiles). Periodic re-attestation during debate
sessions. Flag behavioral drift beyond a configurable threshold. Note: this is probabilistic, not
cryptographic — determined adversaries can probe the attestation set and tune the weight surgery to
pass it. Defense-in-depth with G2 (taint) is the correct posture.

**Files**: `aragora/agents/` (agent registry), `aragora/debate/team_selector.py`

#### G4: External Verification Gate

**Gap**: No mandatory external check before high-impact execution. If the entire ensemble shares a
correlated blind spot (e.g., all models fail to recognize a specific domain-specific risk), the
consensus receipt will be signed without that risk surfacing.

**Mitigation**: For decisions above a configurable impact threshold, require at least one non-Aragora
verifier signature before execution proceeds. Can be implemented as an opt-in policy flag initially
(`require_external_verification=True` in ArenaConfig or execution gate policy). External verifier
can be a human reviewer, a specialized domain model, or a third-party verification service.

**Files**: `aragora/debate/execution_bridge.py`, `aragora/gauntlet/signing.py` (multi-party
signature support)

### Positioning: The Semantic Immune System

Aragora's combination of heterogeneous consensus + adversarial structure + consensus receipt as
execution gate makes it the first platform to apply **distributed immunological defense** to AI
decision-making. The thesis:

> If you only execute against signed consensus receipts from N adversarial heterogeneous models,
> you have something provably safer to execute against than the output of any single model —
> regardless of whether that model has been jailbroken, sycophancy-trained, or weight-surgered.

The analogy to biological immune systems is apt: diversity prevents any single vulnerability from
being universally exploited. A clonal cell population can be wiped out by a single pathogen that
targets their shared receptor. A heterogeneous ecosystem requires the pathogen to simultaneously
defeat multiple independent defense mechanisms — a combinatorially harder problem.

**This is not a claim that Aragora is immune to LLM attacks. It is a claim that adversarial
multi-model consensus with signed receipts raises the cost of a successful attack by orders of
magnitude compared to any single-model platform.**

---

## Phase 0: Foundation Hardening (Week 1-2)

### 0A. Obsidian Bidirectional Sync

**Current state**: Forward sync only (Obsidian → Knowledge Mound). No reverse flow.

**Implementation**:

1. Add `sync_from_km()` to `ObsidianAdapter` implementing `ReverseFlowMixin`
   - Write KM validation results back to Obsidian frontmatter
   - Fields: `km_confidence`, `km_validated_at`, `km_validation_result`, `cross_debate_utility`
   - Use existing `ObsidianConnector.update_note_frontmatter()`

2. Add conflict detection
   - Track `last_modified` timestamps on both sides
   - Strategy: prefer user edits for content, append KM results as frontmatter
   - Log conflicts to decision receipt

3. Add filesystem watcher for real-time sync
   - Use `watchdog` library for cross-platform file events
   - Debounce to avoid rapid-fire syncs (500ms window)
   - Filter by configured `watch_tags`

4. Update factory registration
   - Set `reverse_method: "sync_from_km"`
   - Enable by default when vault path is configured

**Files**:
- `aragora/knowledge/mound/adapters/obsidian_adapter.py` — add reverse flow
- `aragora/connectors/knowledge/obsidian.py` — add watcher, conflict detection
- `aragora/knowledge/mound/adapters/factory.py` — update registration

### 0B. Extended Thinking Capture

**Rationale**: Quick win. Claude's extended thinking provides transparent reasoning chains. Capture these as debate metadata for explainability.

**Implementation**:

1. Add `thinking_budget` parameter to Anthropic agent config
2. Capture thinking trace in proposal/critique metadata
3. Surface in decision receipts and explainability builder

**Files**:
- `aragora/agents/api_agents/anthropic.py` — add thinking budget param
- `aragora/debate/orchestrator.py` — capture thinking metadata

**Complexity**: Easy (2-3 days)

---

## Phase 1: Prompt-to-Spec Engine (Week 2-4)

### The Core Problem

A user types: "I want to make my onboarding flow better." The system needs to:
1. Understand the vague intent
2. Ask clarifying questions
3. Research the current state
4. Generate a structured specification
5. Get approval
6. Execute

### 1A. Prompt Decomposition Service

**New module**: `aragora/prompt_engine/`

```
aragora/prompt_engine/
├── __init__.py
├── decomposer.py          # Vague prompt → structured intent
├── interrogator.py        # Generate clarifying questions
├── researcher.py          # Investigate current state
├── spec_builder.py        # Structured specification generation
├── refinement_loop.py     # Iterative refinement with user
└── types.py               # PromptIntent, ClarifyingQuestion, Specification
```

**Decomposer** (`decomposer.py`):
- Input: raw user prompt (any length, any vagueness level)
- Output: `PromptIntent` with:
  - `intent_type`: feature | improvement | investigation | fix | strategic
  - `domains`: list of affected domains (from codebase analysis)
  - `ambiguities`: list of things that need clarification
  - `assumptions`: list of implicit assumptions detected
  - `scope_estimate`: small | medium | large | epic
  - `related_knowledge`: KM entries relevant to this intent

**Interrogator** (`interrogator.py`):
- Takes `PromptIntent` and generates clarifying questions
- Each question includes:
  - The question itself
  - Why it matters (what changes based on the answer)
  - Suggested options with tradeoff explanations
  - Default recommendation
- Questions are ordered by impact (most consequential first)
- Configurable depth: quick (3-5 questions) | thorough (10-15) | exhaustive (20+)

**Researcher** (`researcher.py`):
- Given clarified intent, investigates:
  - Current codebase state (via existing assessment engine)
  - Related past decisions (via KM query)
  - Obsidian vault context (via ObsidianConnector)
  - External research (web search for latest techniques)
  - Similar open-source solutions (competitive analysis)
- Output: `ResearchReport` with evidence links

**Spec Builder** (`spec_builder.py`):
- Takes clarified intent + research → `Specification`
- Specification includes:
  - Problem statement
  - Proposed solution with alternatives considered
  - Implementation plan (files, changes, dependencies)
  - Risk register (from existing `DecisionPlanFactory`)
  - Success criteria (measurable)
  - Estimated effort
  - Provenance chain linking back to original prompt

**Refinement Loop** (`refinement_loop.py`):
- Orchestrates: decompose → interrogate → research → spec → approve/refine
- Supports multiple rounds of refinement
- Persists state for async workflows (start on phone, finish on desktop)
- Emits events for UI streaming

### 1B. Debate-Driven Spec Validation

Before execution, the spec goes through adversarial debate:

1. **Devil's Advocate**: Agent argues why the spec will fail
2. **Scope Creep Detector**: Agent identifies unnecessary complexity
3. **Security Reviewer**: Agent checks for security implications
4. **UX Advocate**: Agent evaluates user experience impact
5. **Technical Debt Auditor**: Agent assesses maintenance burden

**Integration**: New pipeline stage between Goals and Workflows in `idea_to_execution.py`.

**Output**: Validated spec with confidence score and dissenting opinions preserved.

### 1C. User-Type Configuration

Four user personas with different defaults:

```python
class UserProfile(str, Enum):
    FOUNDER = "founder"        # Maximum velocity, minimal ceremony
    CTO = "cto"                # Code-aware, wants visibility into implementation
    BUSINESS = "business"      # Plain language, wants results not process
    TEAM = "team"              # PRD-driven, wants quality gates and review

# Default configurations per profile:
PROFILE_DEFAULTS = {
    "founder": {
        "interrogation_depth": "quick",
        "auto_execute_threshold": 0.8,  # High confidence = auto-execute
        "require_approval": False,
        "show_code": True,
        "autonomy_level": "propose_and_approve",
    },
    "cto": {
        "interrogation_depth": "thorough",
        "auto_execute_threshold": 0.9,
        "require_approval": True,
        "show_code": True,
        "autonomy_level": "propose_and_approve",
    },
    "business": {
        "interrogation_depth": "thorough",
        "auto_execute_threshold": 0.95,
        "require_approval": True,
        "show_code": False,
        "autonomy_level": "human_guided",
    },
    "team": {
        "interrogation_depth": "exhaustive",
        "auto_execute_threshold": 1.0,  # Always require approval
        "require_approval": True,
        "show_code": True,
        "autonomy_level": "metrics_driven",
    },
}
```

---

## Phase 2: Truth-Seeking Advances (Week 4-6)

### 2A. Prover-Estimator Debate Protocol

**Rationale**: Strongest theoretical grounding for debate-based truth-finding. Solves the "obfuscated arguments" problem where a debater hides a flaw.

**Implementation**:

New protocol variant in `aragora/debate/protocols/`:

```python
class ProverEstimatorProtocol(DebateProtocol):
    """
    Prover (Alice) produces subclaims arguing for a conclusion.
    Estimator (Bob) assigns probabilities to subclaims.
    Obfuscated arguments are not a winning strategy.
    """

    async def run_round(self, arena, round_num):
        # 1. Prover generates subclaims decomposing the main claim
        subclaims = await self.prover.decompose(arena.task)

        # 2. Estimator assigns probabilities to each subclaim
        estimates = await self.estimator.estimate(subclaims)

        # 3. Prover can challenge any estimate with evidence
        challenges = await self.prover.challenge(estimates)

        # 4. Re-estimation with evidence
        final_estimates = await self.estimator.re_estimate(challenges)

        # 5. Aggregate into final confidence
        return self.aggregate(final_estimates)
```

**Key properties**:
- Each subclaim gets an independent probability estimate
- Claims that hinge on "arbitrarily small probability changes" are flagged
- Trickster agent naturally fills the Estimator role
- Existing consensus module tracks the probability chain

### 2B. Cross-Verification Phase

**Rationale**: After each debate round, verify claims against evidence. Catches hallucinations before they influence consensus.

**Implementation**:

Add verification phase to `aragora/debate/phases/`:

```python
class VerificationPhase:
    """
    Three-pass verification:
    1. Original claim with full context
    2. Claim with only attention-relevant context
    3. Claim with only non-relevant context
    Consistency between passes indicates grounding.
    """

    async def verify(self, claim, context):
        # Pass 1: Full context
        full = await self.agent.evaluate(claim, context)

        # Pass 2: Relevant subset
        relevant = self.extract_relevant(claim, context)
        partial = await self.agent.evaluate(claim, relevant)

        # Pass 3: Non-relevant subset
        irrelevant = self.extract_irrelevant(claim, context)
        noise = await self.agent.evaluate(claim, irrelevant)

        # Grounding score: high consistency between full and partial,
        # low consistency with noise
        return GroundingScore(
            grounded=(full.similarity(partial) > 0.8),
            hallucination_risk=(full.similarity(noise) > 0.5),
        )
```

**Hook**: Integrate via existing `auto_verify_arguments` flag in `PostDebateConfig`.

### 2C. Persuasion vs. Truth Detection

**Rationale**: Research shows debate can fail when agents emphasize persuasion over truth. Aragora needs active mitigation.

**Implementation**:

1. Track rhetorical vs. evidential argumentation patterns
   - Existing `RhetoricalObserver` already detects rhetorical devices
   - Add scoring: high rhetoric + low evidence = persuasion warning
2. Weight evidence-backed claims higher in consensus
3. Flag "persuasive but unsupported" claims in decision receipts

---

## Phase 3: Self-Improvement Hardening (Week 6-8)

### 3A. STOP-Style N-Candidate Implementation

**Rationale**: Instead of generating one implementation, generate N candidates and pick the best.

**Implementation**:

Enhance Nomic Loop Phase 3 (Implement):

```python
class STOPImplementor:
    """
    Self-Taught Optimizer for implementation.
    Generate N candidates, evaluate, keep best.
    Use winning approach as seed for next cycle.
    """

    async def implement(self, spec, n_candidates=3):
        candidates = []
        for i in range(n_candidates):
            # Generate implementation with different strategies
            impl = await self.generate(spec, strategy=self.strategies[i])
            # Evaluate against utility function
            score = await self.evaluate(impl, spec)
            candidates.append((impl, score))

        # Select best
        best = max(candidates, key=lambda x: x[1])

        # Record winning strategy for next cycle
        await self.km.ingest({
            "type": "implementation_strategy",
            "strategy": best[0].strategy,
            "score": best[1],
            "spec_hash": spec.hash,
        })

        return best[0]

    async def evaluate(self, impl, spec):
        """Utility function: weighted combination of quality signals."""
        return weighted_sum(
            test_pass_rate=await self.run_tests(impl),
            lint_score=await self.lint(impl),
            type_check=await self.type_check(impl),
            spec_compliance=await self.check_spec(impl, spec),
            regression_risk=await self.check_regressions(impl),
        )
```

**Integration**: Wire into `aragora/nomic/hardened_orchestrator.py` as the implement phase.

### 3B. Self-Healing Test Infrastructure

**Rationale**: When tests fail after implementation, attempt automated repair before rollback.

**Implementation**:

Enhance Nomic Loop Phase 4 (Verify):

1. On test failure, invoke `ForwardFixer.diagnose_failure()`
2. Generate fix candidates (up to 3 attempts)
3. Re-run tests after each fix
4. If all attempts fail, rollback and record the failure pattern
5. Record success patterns in KM for future cycles

### 3C. Meta-Improver for Debate Protocols

**Rationale**: The system should improve its own debate protocols, not just code.

**Implementation**:

1. Track debate quality metrics per protocol variant
   - Consensus quality (how often do humans agree with the consensus?)
   - Debate efficiency (rounds to convergence)
   - Dissent preservation (are minority views captured?)
   - Calibration (confidence vs. actual accuracy)

2. MetaPlanner proposes protocol modifications
   - Different consensus thresholds
   - Different round structures
   - Different agent team compositions
   - A/B test against existing protocols

3. Promote winning variants automatically (with approval gate)

---

## Phase 4: Decision Accountability (Week 8-10)

### 4A. Merkle Tree Receipt Chain (VCP-Aligned)

**Rationale**: EU AI Act deadline is August 2026. Each receipt must be cryptographically linked to form a tamper-evident chain.

**Implementation**:

Extend `aragora/gauntlet/receipt.py`:

```python
class ReceiptChain:
    """
    VCP-aligned Merkle tree over decision receipts.
    Each receipt references the hash of the previous receipt.
    Merkle tree enables efficient integrity verification.
    """

    def __init__(self, signing_key):
        self.signing_key = signing_key
        self.chain = []

    def add_receipt(self, receipt: DecisionReceipt) -> ChainedReceipt:
        prev_hash = self.chain[-1].chain_hash if self.chain else GENESIS_HASH
        chain_hash = sha256(prev_hash + receipt.hash)
        signature = ed25519_sign(chain_hash, self.signing_key)

        chained = ChainedReceipt(
            receipt=receipt,
            chain_hash=chain_hash,
            prev_hash=prev_hash,
            signature=signature,
            sequence_number=len(self.chain),
        )
        self.chain.append(chained)
        return chained

    def verify_integrity(self) -> bool:
        """Verify entire chain is tamper-evident."""
        for i, entry in enumerate(self.chain):
            expected_prev = self.chain[i-1].chain_hash if i > 0 else GENESIS_HASH
            if entry.prev_hash != expected_prev:
                return False
            if not ed25519_verify(entry.chain_hash, entry.signature, self.signing_key.public):
                return False
        return True

    def merkle_root(self) -> bytes:
        """Compute Merkle root for efficient batch verification."""
        leaves = [entry.chain_hash for entry in self.chain]
        return compute_merkle_root(leaves)
```

**Uses existing**: `aragora/gauntlet/signing.py` (Ed25519 support already implemented).

### 4B. GraphRAG Explainability

**Rationale**: Upgrade linear evidence chains to graph-based decision traces.

**Implementation**:

Extend `aragora/explainability/builder.py`:

```python
class GraphExplanation:
    """
    Graph-based decision explanation.
    Nodes: claims, evidence, agents, rounds, votes
    Edges: supports, contradicts, critiques, cites, influences
    """

    def trace_decision(self, receipt: DecisionReceipt) -> ExplanationGraph:
        graph = ExplanationGraph()

        # Add all claims as nodes
        for claim in receipt.consensus_proof.claims:
            graph.add_node(ClaimNode(claim))

        # Add evidence supporting/contradicting each claim
        for evidence in receipt.evidence_chain:
            graph.add_node(EvidenceNode(evidence))
            graph.add_edge(evidence.source, claim.id, "supports" | "contradicts")

        # Add agent reasoning traces
        for agent_trace in receipt.agent_traces:
            graph.add_node(AgentNode(agent_trace))
            for influenced_claim in agent_trace.influenced:
                graph.add_edge(agent_trace.id, influenced_claim, "influences")

        # Add cross-debate links from KM
        for cross_link in self.km.find_related(receipt.task):
            graph.add_edge(cross_link.source, cross_link.target, "relates_to")

        return graph

    def explain(self, graph: ExplanationGraph, depth: int = 3) -> str:
        """Generate natural language explanation from graph traversal."""
        ...
```

### 4C. EU AI Act Compliance Package

**Rationale**: August 2026 deadline. Bundle receipt chain + explanations into compliance artifact.

**Implementation**:

Extend `aragora/compliance/report_generator.py`:

```python
class EUAIActCompliancePackage:
    """
    Generates compliance artifact meeting EU AI Act requirements:
    - Article 12: Logging (receipt chain)
    - Article 14: Human oversight (approval gates documented)
    - Article 15: Accuracy (calibration metrics)
    - Annex IV: Technical documentation (system description + risk assessment)
    """

    def generate(self, receipt_chain, risk_register, calibration_data):
        return CompliancePackage(
            logging_evidence=receipt_chain.export(),
            oversight_evidence=self.document_approval_gates(),
            accuracy_evidence=calibration_data.export(),
            technical_documentation=self.generate_annex_iv(),
            merkle_root=receipt_chain.merkle_root(),
        )
```

---

## Phase 5: GUI — The Prompt-to-Execution Canvas (Week 10-14)

### 5A. The Canvas

A new full-screen experience that is Aragora's primary interface. Not another chat UI.

**Layout**:

```
┌─────────────────────────────────────────────────────────┐
│ ARAGORA CANVAS                          [Profile ▾] [⚙] │
├───────────┬─────────────────────────────────────────────┤
│           │                                             │
│  STAGES   │              ACTIVE STAGE                   │
│           │                                             │
│  ● Prompt │  ┌─────────────────────────────────────┐   │
│  ○ Refine │  │                                     │   │
│  ○ Debate │  │     (stage-specific content)         │   │
│  ○ Spec   │  │                                     │   │
│  ○ Plan   │  │                                     │   │
│  ○ Execute│  │                                     │   │
│  ○ Verify │  │                                     │   │
│           │  └─────────────────────────────────────┘   │
│           │                                             │
│  CONTEXT  │  ┌─────────────────────────────────────┐   │
│           │  │ Provenance Chain                     │   │
│  Obsidian │  │ prompt → research → debate → spec    │   │
│  KM       │  │ → plan → code → tests → receipt     │   │
│  History  │  └─────────────────────────────────────┘   │
│           │                                             │
├───────────┴─────────────────────────────────────────────┤
│ Receipt: SHA-256:a1b2c3... │ Confidence: 87% │ 3 agents │
└─────────────────────────────────────────────────────────┘
```

**Stages**:

1. **Prompt** — Large text input. Accepts anything from "make it better" to a full PRD. Real-time decomposition showing detected intent, domains, and ambiguities as you type.

2. **Refine** — AI-generated clarifying questions with suggested answers. Each answer updates the intent model in real-time. Shows what changes based on each answer. Draws context from Obsidian vault and KM.

3. **Debate** — Live adversarial debate visualization. Agents argue for/against approaches. Confidence meters per claim. Dissenting views highlighted, not hidden. User can intervene, vote, or redirect.

4. **Spec** — Generated specification with acceptance criteria. Diff view showing what changes from current state. Risk register. Effort estimate. One-click approve or annotate.

5. **Plan** — Implementation plan as a DAG. Each node is a task with agent assignment. Dependencies visible. Critical path highlighted. Drag to reorder.

6. **Execute** — Live execution with streaming output. Each task shows: agent working, code being written, tests running. Pause/resume/redirect at any point.

7. **Verify** — Test results, lint results, type check results. Before/after comparison. Regression detection. One-click approve or rollback.

8. **Receipt** — Cryptographic decision receipt. Full provenance chain from original prompt to final code. Exportable as PDF, HTML, or SARIF. EU AI Act compliance badge if applicable.

### 5B. Obsidian Integration Panel

Left sidebar context panel:

- **Live vault view**: See relevant Obsidian notes updating in real-time
- **Link to note**: Click to open in Obsidian (via `obsidian://` protocol)
- **Create from receipt**: One-click export decision receipt as Obsidian note
- **Import as context**: Drag Obsidian notes into the canvas as debate context
- **Bidirectional badges**: See which notes have been validated by KM

### 5C. Autonomy Control

Visible slider in the header:

```
AUTONOMY: [──●──────] Propose & Approve
           Full Auto  ←→  Every Step
```

- **Full Auto**: System runs through all stages, only stopping on low confidence
- **Propose & Approve**: System proposes, user approves at each stage
- **Every Step**: System explains every decision, user confirms each one

### 5D. Mobile-Responsive

- Prompt and Refine stages work on mobile (voice input supported)
- Debate stage shows summary view on mobile, detail on desktop
- Receipt is always accessible

---

## Phase 6: Agent Team Orchestration (Week 14-18)

### 6A. Parallel Guardrail Execution

**Quick win**: Run safety checks in parallel with agent execution.

**Implementation**: `asyncio.gather()` around existing security middleware checks.

### 6B. Durable State Checkpointing

**Rationale**: Enterprise debates span hours/days with human review gates.

**Implementation**:

Serialize full debate state to storage:

```python
class DebateCheckpoint:
    debate_id: str
    round_number: int
    agent_states: dict[str, AgentState]
    proposals: list[Proposal]
    critiques: list[Critique]
    votes: list[Vote]
    consensus_state: ConsensusState
    timestamp: datetime
    provenance_hash: str

class CheckpointManager:
    async def save(self, arena: Arena) -> str:
        """Serialize and persist debate state."""
        ...

    async def restore(self, checkpoint_id: str) -> Arena:
        """Restore debate from checkpoint."""
        ...
```

**Storage**: Use existing `aragora/storage/postgres_store.py` for persistence.

### 6C. Handoff Pattern

**Rationale**: Agents should be able to delegate sub-questions to specialists mid-debate.

**Implementation**:

Add handoff semantics to the Arena:

```python
class Handoff:
    """Agent delegates a sub-question to a specialist."""
    from_agent: str
    to_agent: str
    sub_question: str
    context: dict
    return_to_round: int

# In Arena.run_round():
for proposal in proposals:
    if proposal.requests_handoff:
        specialist = await self.control_plane.find_specialist(proposal.handoff_domain)
        sub_result = await specialist.investigate(proposal.sub_question)
        proposal.enrich(sub_result)
```

---

## Implementation Priority

| Phase | Weeks | Key Deliverable | User Value |
|-------|-------|----------------|------------|
| 0 | 1-2 | Obsidian bidirectional sync + extended thinking | "My Obsidian vault feeds debates, results flow back" |
| 1 | 2-4 | Prompt-to-spec engine | "I type a vague idea, get a professional spec" |
| 2 | 4-6 | Prover-Estimator protocol + cross-verification | "Debates actually find truth, not just consensus" |
| 3 | 6-8 | STOP implementation + self-healing tests | "The system improves itself measurably" |
| 4 | 8-10 | Merkle receipt chain + GraphRAG explainability | "Every decision has a cryptographic audit trail" |
| 5 | 10-14 | Canvas GUI | "Professional, intuitive, not a developer tool" |
| 6 | 14-18 | Agent team orchestration hardening | "Enterprise-grade, handles day-long debates" |

## Success Criteria

1. **Prompt to spec**: User types a sentence → gets a professional specification within 5 minutes
2. **Obsidian flow**: Notes tagged `#aragora` appear in debates within 30 seconds
3. **Truth-seeking**: Prover-Estimator debates produce measurably better calibrated decisions
4. **Self-improvement**: System proposes and implements improvements to itself weekly
5. **Accountability**: Every decision has a tamper-evident receipt chain
6. **GUI**: Non-technical user can go from prompt to result without touching code
7. **Agent orchestration**: 10+ agents coordinating on a single task without deadlock

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Scope creep (too many features) | High | High | Phase gates. Each phase is independently valuable. Ship Phase 0-1 first. |
| Obsidian API instability | Medium | Medium | Filesystem-first approach. REST API is optional. |
| EU AI Act requirements change | Low | High | VCP standard is flexible. Receipt chain is extensible. |
| Self-improvement causes regressions | Medium | High | Existing safety: gauntlet gate, worktree isolation, auto-revert. |
| Canvas GUI complexity | High | Medium | Start with Prompt + Refine + Receipt. Add stages incrementally. |

## Non-Goals (For Now)

- Mobile native app (web-responsive is sufficient)
- Multi-tenant SaaS deployment (focus on single-tenant first)
- Integration with every knowledge tool (Obsidian first, then Notion, then others)
- Real-time voice debate (text-first, voice later)
- Blockchain-based receipt storage (local Merkle tree first)
