# Aragora: Canonical Goals & Foundational Thesis

**Single source of truth for WHAT Aragora is and WHY it exists.**
**The [Evolution Roadmap](plans/ARAGORA_EVOLUTION_ROADMAP.md) defines HOW we get there in outcome terms.**
**The [3-Horizon Execution Roadmap](plans/2026-04-18-3-horizon-roadmap.md) operationalizes the next 30/90/365 days of concrete deliverables.**
**Last updated: April 18, 2026**

## Canonical Metrics

Live project-scale numbers are auto-regenerated in [`docs/METRICS.md`](METRICS.md). If a numeric claim in this document or any other doc disagrees with `docs/METRICS.md`, the generated metrics doc wins.

<!-- metrics:begin canonical-goals-metrics -->
| Metric | Value | Source |
|--------|-------|--------|
| Version | 2.9.0 | `pyproject.toml` |
| Python files under `aragora/` | 4,300 | `docs/METRICS.md` |
| Python modules | 144 top-level package directories | `docs/METRICS.md` |
| Lines of code under `aragora/` | 1,988,705 | `docs/METRICS.md` |
| Automated tests | 224,873 test functions | `docs/METRICS.md` |
| Test files | 5,513 | `docs/METRICS.md` |
| API operations | 3,084 across 2,876 paths | `docs/METRICS.md` |
| API paths | 2,876 | `docs/METRICS.md` |
| Knowledge Mound adapters | 46 adapter files / 41 registered specs | `docs/METRICS.md` |
<!-- metrics:end -->

Other canonical claims (manually maintained):

| Metric | Value | Source |
|--------|-------|--------|
| Agent types (registered) | 46 across 6+ LLM providers | `list_available_agents()` in `aragora/agents/base.py` |
| Agent types (allowlisted) | 35 (see `docs/METRICS.md`) | `ALLOWED_AGENT_TYPES` in `aragora/config/settings.py` |
| Workflow templates | 50+ across 6 categories | template registry |
| Handler modules | 580+ | handlers directory |
| GA readiness | Pre-GA; remaining launch work is tracked in `GA_CHECKLIST.md` | `GA_CHECKLIST.md` |
| SOC 2 readiness | 98% | compliance assessment |
| Pricing tiers | Free / Pro / Enterprise | commercial docs |
| BYOK model | Customers bring their own API keys | commercial docs |
| Target gross margin | 85%+ | commercial docs |

## Mission Statement

Aragora is the decision integrity platform and autonomous operating system for translating vague intent into reviewed, auditable action. It coordinates heterogeneous agents across models, memory, code, and channels; challenges important choices through debate; executes bounded work; and produces receipts that humans can inspect, replay, and trust.

## The Product Boundary

Aragora is one stack with four layers:

1. A reliability-first autonomous teammate for software and operational work
2. A decision integrity layer for consequential choices
3. A unified DAG control plane for ideas -> goals -> actions -> orchestration
4. A long-range organization substrate for shared knowledge, delegation, and auditable execution

If a roadmap item does not strengthen one or more of those layers, it is probably scope creep.

## Stage Evolution Model

| Stage | Promise to the user | Required capabilities | Exit condition |
|---|---|---|---|
| **Tool** | Aragora gives a bounded, useful result | Good defaults, receipts, fail-closed behavior | One-shot flows are trustworthy without hidden rescue |
| **Teammate** | Aragora can own a scoped task end-to-end | Session state, explore/edit/verify loop, explicit escalation | Bounded work no longer requires prompt babysitting |
| **Foreman** | Aragora can coordinate many bounded tasks across hosts | Contracts, admission control, truthful status, self-heal | Multi-host backlog runs are routine rather than heroic |
| **Chief of Staff** | Aragora can translate vague goals into plans and delegated work | Shared memory, tradeoff handling, approval surfaces, portfolio reasoning | Humans can stay at intent level unless they want to dive deeper |
| **Organization Substrate** | Aragora becomes the operating system for coordinated agentic work | Unified DAG, heterogeneous agents, permissioned memory, auditable decisions and actions | Cross-functional idea-to-execution flows live on one substrate |

**Current focus:** move from early `Teammate` behavior to reliable `Foreman` behavior without losing the broader thesis.

## 60-Day Operating Focus

The full eight-pillar thesis stays canonical. The active operating focus for the next 60 days is intentionally narrower:

1. **Reliable Autonomous Execution** must become boringly trustworthy on bounded backlogs.
2. **Cryptographic Receipts and Auditability** must make the operator proof surfaces, benchmark publication, and runtime truth legible enough that external claims can be kept narrower than measured proof.

All other pillars remain planning truth unless a change directly improves one of those two active focus areas. This is a sequencing rule, not a retreat from the broader roadmap.

## Eight Foundational Pillars

> **Reconciliation note.** The eight pillars below are the **doctrinal** framing — the architectural invariants every feature must trace to. The `README.md`, `CLAUDE.md`, and `docs/EXTENDED_README.md` surface a different five-pillar **product-messaging** framing (SMB-ready with enterprise-grade security, leading-edge memory, extensibility/modularity, multi-agent robustness, self-healing via the Nomic Loop), and `docs/PACKAGING.md` groups the platform into three shippable pillars (verifiable decisionmaking, bounded autonomous execution, auditable memory). These three frames are complementary, not contradictory: the eight doctrinal pillars ground the architecture, the five product-messaging pillars summarize the user-visible thesis, and the three packaging pillars describe modular delivery. This document is authoritative for the doctrinal frame. The pillar count here evolved 6 → 7 → 8 across [2026-03-01 canonical-goals update](plans/2026-03-01-canonical-goals-update-design.md), the Epistemic CI / Dialectical Runtime layering (2026-04 #6029/#6034/#6224), and the agent-civilization tranche (#6061); the current count is **eight** and the list below is exhaustive.

### 1. Adversarial Heterogeneous Consensus

Any single model can hallucinate, flatter, or share hidden blind spots. Aragora's default stance is structured challenge across heterogeneous models, not trust in one witness. This pillar serves the debate engine, gauntlet, truth weighting, calibration, dissent capture, and cross-verification.

The next differentiator is crux-finding: debates should identify the load-bearing facts, framings, values, and assumptions where reasonable agents diverge, not merely produce an answer.

The **agent-ops plane** (in-flight in `aragora/swarm/agent_bridge/`) operationalizes this pillar by enabling state-preserving heterogeneous CLI harness interop: independent harnesses (Claude Code, Codex CLI, Factory Droid, Aider, Gemini CLI) hold a structured ongoing dialog and cross-check each other while each retains its own native session state, tools, and context. This converts "claimed multi-agent" into actual multi-agent — convergence-as-evidence (per `docs/THESIS.md` premise 3) only counts when agents have *different priors, different evidence, and active incentive to dissent*. Designed for cheap extraction as a standalone OSS substrate; positioning, market-fit analysis, and the five extraction-readiness disciplines live in [`docs/plans/2026-04-25-agent-ops-plane-market-fit.md`](plans/2026-04-25-agent-ops-plane-market-fit.md).

### 2. Reliable Autonomous Execution

Reasoning alone is not enough. The system must execute bounded work with explicit contracts, verification, and fail-closed escalation. This pillar serves swarm, supervisor, worker contracts, preflight, repair, publication, and self-heal.

### 3. Unified DAG and Optional Interactivity

Ideas, goals, actions, and orchestration must live on one graph with shared provenance. Users should be able to interact at any level: stay high-level, review a stage transition, or inspect a leaf task. This pillar serves prompt-to-spec, DAG operations, approvals, and the workbench.

The human-facing surface should be a genuinely elegant, intuitive GUI over the unified DAG — not a dashboard, not a marketing shell, not a collection of disconnected panels. Users should be able to see the full idea → goal → action → orchestration flow at a glance and drill into any node's receipt chain, debate history, dissent map, and execution evidence without context switching. The GUI's job is to make a complex autonomous system feel legible and controllable, not to hide complexity behind slick visuals. Optional interactivity means: stay high-level when you trust the system, intervene precisely when you don't.

### 4. Permissioned Memory and Large Context

Memory is only useful if it is permissioned, attributable, and relevance-ranked. Broad ingestion matters when it improves decisions and execution quality, not when it becomes a write-only storage lake. This pillar serves Knowledge Mound, context packing, provenance tracking, and shared knowledge.

Leading-edge memory is a differentiator when it is private, portable, and diverse. The goal is for users to bring their own knowledge across many sources and streams — repos, docs, APIs, chat, inbox, telemetry, decision history — with source-level provenance, trust tiers, and export/deletion preserved. That means no lock-in to a single memory provider, no loss of institutional knowledge across agent handoffs, and no opaque ingestion that a user cannot inspect or revoke. Large-context packing exists to serve this: make big, diverse, trustworthy context available to heterogeneous agents without forcing the user into one vendor's memory substrate.

### 5. Cryptographic Receipts and Auditability

Every consequential decision or execution step should be inspectable. Receipts, provenance links, signatures, and compliance artifacts are not side effects; they are the trust layer that makes autonomy acceptable in real organizations.

Important organizational claims should also become executable, evidence-linked objects with freshness, verification, provenance, and bounded repair behavior. This is the Epistemic CI direction: what Aragora believes should be testable, not just written down.

The same trust model should eventually apply to code paths themselves. Proof-carrying code units should link functions, routes, scripts, and policies to the claims, assumptions, receipts, verifiers, and fallback rules that justify them. When the evidence behind a code path decays, Aragora should detect that decay, fail safely, and produce a verified repair candidate before any opt-in runtime replacement is considered.

The decision-integrity layer should also close the loop between those primitives so code behaves less like static text and more like a continuous, inspectable argument between an organisation's intent and the world it operates in. That means: decay signals, crux-finder debates, quarantine policy, and verified replacements must be joinable into a single receipt-carrying lineage, operator judgment on persistent cruxes must be a first-class reversible receipt rather than tribal knowledge, and the system must be able to probe its own fragility against plausible-future world states before reality invalidates it. The additive synthesis plan for this layer lives in [plans/2026-04-18-dialectical-runtime-synthesis.md](plans/2026-04-18-dialectical-runtime-synthesis.md); it extends the Decision Integrity Core tranche without replacing any of it and remains planning truth until the proof-first Foreman and DIC-20/21/22 gates open.

### 6. SMB Operator Leverage

Aragora must be useful to founders, operators, and small teams with limited time, uneven specs, and real consequences. The product should not require elite prompt discipline to be valuable. That constraint shapes UX, packaging, and scope decisions.

The long-horizon positioning is an **operating system for SMBs and operators**: a substrate that translates the relevant data and ideas in a small business into actions, with optional detailed control over the agents doing the work. SMB OS does not mean enterprise features watered down — it means a coherent core tier (`aragora-core`) that installs in under ten minutes, runs a real workflow on founder time, and leaves the enterprise tier (`aragora-enterprise`) as an additive upgrade for compliance, federation, scale, and SSO. SMB OS is what makes the decision-integrity platform democratically useful rather than an enterprise-only premium product.

### 7. Self-Improvement on a Shared Substrate

Nomic, swarm, and user-facing execution should converge on the same contract, ledger, memory, and control-plane surfaces. We do not want multiple autonomy stacks drifting apart. Repeated rescue classes should become benchmark fixtures and product work, not tribal knowledge.

### 8. Agents and Humans as Co-Equal Consumers

Software agents are about to become first-rate consumers of decisionmaking, memory, capability marketplaces, and reputation surfaces — alongside humans, not replacing them. Every consumer surface (registration, capability discovery, billing, decision receipts, reputation reads) ships in two forms, agent-readable and human-readable, backed by the same runtime truth.

This pillar pulls the existing identity, reputation, staking, validation, A2A, marketplace, and receipt primitives into a unified consumer surface so the substrate Aragora is building can serve the emerging agent population without forking into a separate stack. The design constraint is parity: nothing humans can do through the platform should be unavailable to agents, and nothing agents can do should be unavailable to humans.

Heterogeneous agent support means both the incumbent foundation-model agents (Claude, Codex/GPT, Gemini, Grok, DeepSeek, Qwen, Mistral, Llama, Kimi, Yi) and external frameworks and agents (OpenClaw, Nous Hermes, Pi Agent, Anthropic Agent Framework, LangGraph, AutoGen, CrewAI, plus future entrants) interoperate with the same debate, memory, contract, and receipt substrate. No one agent vendor should be a critical dependency. The marketplace should let users opt into their preferred mix — for detailed control over what agents run, what memory they touch, and what evidence they leave — without forcing them to rebuild the substrate for each choice.

The vision-layer planning for this pillar lives in [plans/AGENT_CIVILIZATION_SUBSTRATE.md](plans/AGENT_CIVILIZATION_SUBSTRATE.md) with sibling specs [plans/AGENT_CONSUMER_SURFACE.md](plans/AGENT_CONSUMER_SURFACE.md), [plans/SKIN_IN_THE_GAME_REPUTATION.md](plans/SKIN_IN_THE_GAME_REPUTATION.md), and [plans/2026-04-17-prediction-market-validation.md](plans/2026-04-17-prediction-market-validation.md). Live queue scope continues to follow the substrate-first gate in [status/NEXT_STEPS_CANONICAL.md](status/NEXT_STEPS_CANONICAL.md); these plans are planning truth, not active dispatch scope.

## Architectural Doctrine

### Aragora Is the Terrarium, Not the Organism

Aragora should shape incentives so truthful, inspectable behavior is the cheapest way for agents to succeed. We do not want a black-box organism managing people; we want an environment whose physics reward evidence, verification, and explicit dissent.

### Compute Is ATP; Truth Is Demanded Behavior

Compute is the scarce resource. Truth must be the required behavior for spending it. That means:

- subscriptions and operating leverage beat engagement-maximizing business models
- verification and receipts beat vibes
- trustworthy throughput beats raw speed

### Time Is Part of Settlement

Some decisions can only be judged after later evidence arrives. Aragora should preserve claims, assumptions, and dissent so delayed settlement is possible rather than pretending every result is final at execution time.

## Operating Law: Repeated Rescue Becomes Product

If humans intervene twice for the same class of failure, the next system change should absorb that rescue as product behavior: a benchmark fixture, sanitizer rule, preflight check, repair path, policy gate, or control-plane affordance.

This is the practical bridge from `Tool` to `Teammate` to `Foreman`. It prevents hidden human labor from masquerading as autonomy.

## The GUI and DAG Are Not Decoration

The unified workbench is not a marketing shell. It is the human-legible view of the same runtime truth:

- live stage transitions
- contracts and approvals
- interventions and retries
- receipts and provenance
- branchable, reviewable plans

A beautiful GUI that is not backed by the same contracts and ledger is an anti-goal.

## Memory Must Be Permissioned, Portable, and Useful

The memory layer must:

- preserve provenance and trust tier for every artifact
- distinguish operator instruction from retrieved context
- support large-context packing without silent truncation
- make export and deletion possible for customer trust
- measurably improve decision quality and execution success

## Security Thesis

Aragora's trust story is structural:

- heterogeneous models reduce single-lineage failures
- receipts and policy gates prevent unreviewed execution
- provenance and trust tiers reduce context-injection ambiguity
- external verification can be required for high-impact decisions
- audit trails make errors legible instead of latent

## Non-Goals

- A single-model autopilot that hides its reasoning
- A memory lake with no provenance or permission model
- A GUI-first control plane detached from runtime truth
- Broad cross-functional automation before bounded software execution is reliable
- Commercial claims that outrun measured proof
- A product that only elite prompt engineers can use

## Canonical North-Star Outcomes

1. A vague request can become a reviewable executable spec in minutes.
2. A bounded backlog can run unattended with clear receipts, stop conditions, and minimal rescue.
3. Humans can inspect any decision or execution result from summary level down to evidence and provenance.
4. Shared memory improves future work without collapsing trust boundaries.
5. Important claims and cruxes remain linked to evidence, receipts, freshness, and later settlement.
6. Aragora evolves from tool -> teammate -> foreman -> chief of staff -> organization substrate on one coherent runtime.
7. Agents and humans participate in the same substrate as co-equal consumers, with portable reputation tied to objectively verifiable outcomes through external truth oracles (prediction markets, public verifiable streams, synthetic in-repo markets) rather than to internal agreement.
