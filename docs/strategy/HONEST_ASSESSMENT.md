# Aragora: Honest Assessment

> A brutally honest evaluation of what works, what doesn't, and why it matters.
> Based on verified code review and test execution across the full codebase.
>
> Last verified: 2026-06-10 (run-20260610 truth-refresh; B0 artifact .aragora/run-20260610/truth_artifact_20260610.json)
>
> **Written:** Early March 2026 (Run 001-003 era). **March 5 update:** Several blockers
> described below have since been resolved — see update notes inline.
> **June 10, 2026 update:** Quantified claims below refreshed against
> [`docs/METRICS.md`](../METRICS.md), [`docs/status/B0_BENCHMARK_TRUTH_STATUS.md`](../status/B0_BENCHMARK_TRUTH_STATUS.md),
> and [`docs/strategy/FOCUS.md`](FOCUS.md) Sprint 1/2 outcomes — see inline update notes.
>
> **Metrics note:** Current live scale numbers are auto-regenerated in
> [`docs/METRICS.md`](../METRICS.md), and that file wins over any stale numeric
> snapshot below. Dated numbers in this document are explicitly labeled as
> point-in-time snapshots.

---

## Table of Contents

- [What Actually Works](#what-actually-works)
- [What's Partially Working](#whats-partially-working)
- [What's Scaffolding](#whats-scaffolding)
- [Defensible Value Proposition](#defensible-value-proposition)
- [What Will Be Eaten by Bigger Companies](#what-will-be-eaten-by-bigger-companies)
- [How to Strengthen the Moat](#how-to-strengthen-the-moat)
- [The Bottom Line](#the-bottom-line)

---

## What Actually Works

These claims are verified by code review and test execution against the actual codebase.

### Core Debate Engine

The debate engine is real, functional, and battle-tested.

`Arena.run()` orchestrates genuine multi-agent debates with real LLM API calls. Agents from different providers -- Anthropic, OpenAI, Google, Mistral, xAI -- actually critique each other's reasoning in structured rounds.

| Capability | Detail |
|---|---|
| Agent types | 35 allowlisted agent types (canonical count in [`docs/METRICS.md`](../METRICS.md)); older marketing claimed 43 across 8 categories — the allowlist is the measured number |
| Phase execution | 7 phases: Context Init, Proposals, Debate Rounds, Consensus, Verification, Analytics, Feedback |
| Consensus modes | 5: judge, majority, supermajority, unanimous, ELO-weighted |
| Cognitive roles | 9 rotations: Analyst, Skeptic, Lateral Thinker, Devil's Advocate, Synthesizer, Domain Expert, Red Team, Pragmatist, Visionary |
| Team selection | 15+ dimensions for intelligent agent composition |
| Fallback | Circuit breaker with OpenRouter fallback on 429 rate limits |
| Hollow consensus | Trickster detection: 3-phase evidence quality analysis with intervention |
| Decision receipts | SHA-256 hashing in Markdown, HTML, SARIF, CSV formats |
| ELO rankings | Domain-specific ratings, Brier score calibration, persistent leaderboards |
| Demo mode | Works end-to-end with no API keys required |
| CLI | `aragora review`, `aragora gauntlet` work in both live and demo modes |
| Test coverage | Historical snapshot; current test-function and mypy-baseline counts live in [`docs/METRICS.md`](../METRICS.md) |

### Idea-to-Execution Pipeline (90% Working)

The pipeline converts raw ideas into executable multi-agent plans across four stages.

| Stage | Status | What It Does |
|---|---|---|
| 1. Ideas | Fully working | Converts raw ideas to Canvas nodes with radial layout |
| 2. Goals | Fully working | SMART scoring, conflict detection, KM precedent enrichment |
| 3. Actions | Fully working | Template-based decomposition into 20+ action steps with dependency graphs |
| 4. Orchestration | Partially working | Generates multi-agent execution plans with ELO-ranked agent assignment. Real execution when engines available; returns "planned" status otherwise (graceful degradation, not failure) |

- CLI: `aragora pipeline run "Build a rate limiter"` works.
- Tests: All 9 pipeline smoke tests pass in 0.6s (March 2026 snapshot).
- Known gap: Pipeline results are in-memory only (not persisted across restarts).

### Enterprise Security and Compliance

This is production-grade infrastructure, not prototyping code.

| Area | Scale | Key Capabilities |
|---|---|---|
| RBAC | 12,969 LOC (Mar 2026 snapshot) | 424 unique permission strings across 1,365 `@require_permission` call sites (canonical in [`docs/METRICS.md`](../METRICS.md)) |
| Billing | 23,114 LOC (Mar 2026 snapshot) | Stripe integration, metering, forecasting |
| Observability | 17,280 LOC (Mar 2026 snapshot) | Prometheus metrics, OpenTelemetry tracing, Grafana dashboards |
| Authentication | Production | OIDC/SAML SSO, MFA (TOTP/HOTP), SCIM 2.0 provisioning |
| Encryption | Production | AES-256-GCM at rest, automated 90-day key rotation |
| Compliance frameworks | 9 | HIPAA, GDPR, PCI-DSS, SOX, ISO 27001, OWASP, FDA 21 CFR Part 11, FedRAMP, NIST 800-53 |
| EU AI Act | Production | Article 12/13/14 artifact generation |
| Handler tests | 19,776 (Feb 2026 snapshot) | 0 failures at snapshot time |

**Open liability (unchanged as of June 2026):** SOC 2 Type II is *not* certified —
the blocker remains an external penetration test that has not been commissioned.
"Production-grade controls" is a code-review claim, not a third-party-attested one.

### Knowledge and Memory

| System | What It Does |
|---|---|
| Continuum Memory | 4-tier (Google's Nested Learning): FAST 1h, MEDIUM 24h, SLOW 7d, GLACIAL 30d with surprise-driven tier transitions |
| Knowledge Mound | 41 registered adapter specs (46 adapter files; canonical in [`docs/METRICS.md`](../METRICS.md)) creating a federated knowledge graph across subsystems |
| ConsensusMemory | Cross-debate institutional learning |
| CritiqueStore | Post-mortem critique-to-fix pattern extraction |

### SDKs and API

| Component | Scale |
|---|---|
| Python SDK | 198 modules (canonical in [`docs/METRICS.md`](../METRICS.md)) |
| TypeScript SDK | 215 modules (canonical in [`docs/METRICS.md`](../METRICS.md)); parity tracked by the SDK-parity CI gate, not a hand-counted percentage |
| REST API | Broad OpenAPI surface; operation/path counts canonical in [`docs/METRICS.md`](../METRICS.md) |
| WebSocket events | 190+ event types for real-time streaming |

---

## What's Partially Working

These capabilities exist and function in part, but have gaps between documented claims and current reality.

### Convergence Detection

- **Documentation claims:** "3-tier similarity detection" (syntactic, semantic, domain).
- **Reality (June 2026):** The earlier "syntactic-only" gap is closed. `aragora/debate/convergence/detector.py` now selects a similarity backend ladder: SentenceTransformer embeddings when the optional dependency is installed, TF-IDF vectors otherwise, with Jaccard pairwise comparison as the final fallback.
- **Remaining qualification:** Semantic depth depends on an *optional* dependency. A default install without `sentence-transformers` silently degrades to TF-IDF/Jaccard, which is lexical, not semantic. There is no warning surfaced to the user when this degradation happens.
- **Impact:** Convergence detection is meaningfully semantic in well-provisioned deployments and lexical in minimal ones. The honest claim is "semantic when configured," not "semantic by default."

### Self-Improvement System (Nomic Loop) -- Fully Wired & Operational

The self-improvement infrastructure is production-grade with all six phases fully wired end-to-end. Phase 10C consolidation (Jan 2026) removed 2,350 lines of deprecated inline stubs and replaced them with extracted phase classes.

**Phase implementation status (all complete):**

| Phase | Component | Status |
|---|---|---|
| 0: Context | ContextPhase | Real multi-agent codebase exploration |
| 1: Debate | DebatePhase | Real Arena orchestration + PostDebateHooks |
| 2: Design | DesignPhase | Real architecture planning with LearningContext |
| 3: Implement | ImplementPhase | Real file writing + syntax validation |
| 4: Verify | VerifyPhase | Real pytest execution + quality checks |
| 5: Commit | CommitPhase | Real git operations with safety gates |

**Supporting infrastructure (complete):** TaskDecomposer (heuristic + debate decomposition), MetaPlanner (debate-driven prioritization), KMFeedbackBridge (cross-cycle learning), BranchCoordinator (worktree isolation), ForwardFixer (failure diagnosis), HardenedOrchestrator (calibration-weighted agent selection), circuit breakers, deadline tracking.

**Testing:** 66 self-improvement E2E tests + 43 Nomic Loop cycle tests passing. Phase transitions, worktree safety, and error recovery all verified.

**Remaining gap:** Output quality consistency -- dogfood benchmark runs show variable pass rates (33-80%) depending on synthesis grounding quality. The loop runs but output quality needs stabilization for reliable autonomous cycles. **[March 5 update: Run 012 shows 8.38-9.39/10 composite scores (was 3.46-3.55). Practicality scoring resolved via prompt restructuring + threshold alignment + verb scoring fixes.]**

**[June 10, 2026 update — measured benchmark truth replaces dogfood scores.]** The
authoritative quality surface is now the fixed B0 benchmark corpus
([`docs/status/B0_BENCHMARK_TRUTH_STATUS.md`](../status/B0_BENCHMARK_TRUTH_STATUS.md),
corpus `tw-01-bounded-execution-v1` rev-6, success contract `mergeable_pr_or_merged_pr`):

| B0 metric (2026-06-06 publication) | Value |
|---|---|
| Verified truth success rate (primary, verified-by-PR-link) | **100.0%** (5/5 verified expected issues) |
| Full-corpus truth success rate (legacy/context) | **69.2%** (9/13) |
| In-progress graduation rate | **50.0%** (4/8 graduated) |
| Ungraduated cohort still open | #5182, #5183, #5184, #5186 |

The 100% headline is real but narrow: it covers only the five strict
verified entries. The honest whole-corpus number is 69.2%, and half the
in-progress cohort has not graduated. Note the Sprint-1 measurement of this
same surface was an honestly-published **0.0%** (2026-05-26 corpus snapshot) —
the improvement is corpus advancement plus real fixes, not metric redefinition.

**Settlement maturity (June 2026):** Autonomous settlement is no longer
theoretical. Tier-4 settlement apply modes were split (PR #7756) and the
redundant quorum status patch fixed (PR #7748). The post-#7496 proof sequence
passed for both an operator run (`validate-env` → `doctor` → `ask
--decision-integrity` → `receipt verify`, all exit 0) and a strict
non-operator demo (`aragora demo --receipt` with no provider keys; receipt
verified `VALID (3/3 checks passed)`) — see `docs/strategy/FOCUS.md` Sprint 2 goal 2.
A boss-loop merge-gate resilience design draft is in flight but not yet on
main, so it is deliberately not cited here as a repo artifact until it
lands. Open governance liability: the operator
design-review of #7472 (advisory-review recognizable headers) is still
pending, so advisory reviews continue to resolve to `unknown_model_reviewer`.

**Assessment:** The wiring gap identified in Feb 2026 is closed. The binding constraint has shifted from integration to output quality — and as of June 2026, from output quality to *graduating the remaining benchmark cohort* and closing the pending operator design review.

### Formal Verification

- Z3 SMT solver works for decidable claims.
- Lean 4 translation is available but optional.
- Semantic alignment checking prevents hallucinated proofs.
- Only used for high-stakes decisions (opt-in), not a general-purpose feature.

---

## What's Scaffolding

These are areas where claims need honest qualification. The code exists, but the capability as marketed overstates current reality.

### "Blockchain/Immutable Receipts"

| Claim | Reality |
|---|---|
| Immutable blockchain receipts | SHA-256 hashes with no on-chain storage |
| Distributed ledger | No distributed consensus mechanism for receipts |
| ERC-8004 agent identity | Contracts exist as code but have not been deployed |
| Tamper-proof records | Deterministic outputs with integrity checking, not tamper-proof immutable records |

**Honest framing:** Decision receipts have cryptographic integrity verification (SHA-256). They are deterministic, reproducible, and auditable. They are not immutable in the blockchain sense. The value is in the structured audit trail, not in the ledger.

### "43-Agent Parallel Coordination"

| Claim | Reality |
|---|---|
| 43 agents running in parallel | 35 allowlisted agent types exist (canonical in [`docs/METRICS.md`](../METRICS.md)) and work individually; the "43" figure predates the allowlist |
| Massive parallelism | Running all agent types simultaneously hits provider rate limits |
| Practical limit | 2-6 agents per debate for real-time, up to 10 for batch |

**Honest framing:** The value is heterogeneity -- different models from different providers challenge each other's reasoning, reducing correlated blind spots. The value is NOT raw parallelism. A debate with Claude + GPT-4 + Gemini + Mistral is more valuable than one with 43 copies of Claude.

### "Self-Improving Platform"

| Claim | Reality |
|---|---|
| Autonomous self-improvement | 80K+ LOC infrastructure exists; individual components are well-tested |
| 21+ self-improvement phases | More accurately describes manual development iterations, not autonomous agent-driven cycles |
| Proven autonomous cycles | First proof run completed 2026-03-02: debate phase produced real multi-agent consensus (Claude Opus 4.6 + GPT-5.2, 80% agreement); design phase hit a 120s agent timeout; implement/verify/commit phases skipped due to upstream failure. The pipeline correctly detected and halted on failure. |

**Honest framing:** Aragora has the most sophisticated self-improvement infrastructure of any open agent framework. The pieces individually work and are tested. The first autonomous proof run (2026-03-02) demonstrated that the debate phase produces high-quality multi-agent output, the pipeline stages chain correctly, and failure detection works as designed. The end-to-end cycle has not yet completed all 5 phases autonomously -- the design phase timeout and ChaosTheater noise leaking into design output are the immediate blockers. This is now a reliability tuning problem (agent timeouts, output filtering), not a wiring or architecture problem. **[March 5 update: Design phase timeout increased to 1800s (configurable via NOMIC_DESIGN_TIMEOUT). Run 012 composite score: 0.84 vs baseline 0.46.]**

**[June 10, 2026 update]:** "Proven autonomous cycles" is no longer a scaffolding
claim — the B0 benchmark corpus now measures end-to-end bounded-execution issue
resolution at 100% verified / 69.2% full-corpus (see
[`docs/status/B0_BENCHMARK_TRUTH_STATUS.md`](../status/B0_BENCHMARK_TRUTH_STATUS.md)
and the Nomic Loop section above). What *remains* honest qualification: the
verified set is only 5 issues; 4 of the 8 in-progress cohort issues (#5182,
#5183, #5184, #5186) have not graduated; and the dominant recorded failure
class is `blocked_not_dispatch_bounded` (12 occurrences), meaning the loop
still frequently stops because work cannot be dispatched within bounds, not
because it chose not to act.

---

## Defensible Value Proposition

### What Aragora Has That Cannot Be Easily Replicated

#### 1. Adversarial Debate + Audit Receipts (THE CORE MOAT)

No other framework combines structured adversarial multi-agent debate with cryptographic decision receipts. LangGraph, CrewAI, AutoGen, and OpenAI Agents SDK all do cooperative task completion. None produce audit-ready decision records.

This is a new category: **Decision Integrity.**

Why it resists commoditization:

- It is architecturally different from cooperative frameworks. Adversarial vs. cooperative is a design philosophy, not a feature toggle.
- The receipt format, dissent tracking, and evidence chains create a document standard that represents years of domain expertise.
- The debate subsystem encodes deep knowledge of structured argumentation that cannot be bolted onto a cooperative framework.

#### 2. Heterogeneous Model Consensus as Bias Countermeasure

Using Claude + GPT + Gemini + Mistral together reduces correlated blind spots. This is not just "use multiple models." It is structured disagreement with tracked dissent, weighted voting, and hollow consensus detection (Trickster).

No funded competitor does this.

#### 3. Calibrated Trust (ELO + Brier)

Agents build track records over time. Per-domain ELO ratings and Brier score calibration mean the system learns which agents are reliable for which types of decisions.

This creates a flywheel: more debates produce better calibration, which produces higher-quality consensus, which drives more debates.

#### 4. Regulatory Timing (EU AI Act)

EU AI Act high-risk enforcement begins **August 2, 2026**. Companies deploying AI in regulated industries need documented validation and audit trails.

Aragora's Decision Receipts are designed to satisfy:

| Article | Requirement | Aragora Capability |
|---|---|---|
| Article 12 | Record-keeping | Full debate transcripts with agent attribution |
| Article 13 | Transparency | Decision factor decomposition, counterfactual analysis |
| Article 14 | Human oversight | Approval gates, spectator mode, veto capability |

This creates a compliance-driven adoption wedge that bigger companies cannot ignore.

#### 5. BYOK Economics

Customers bring their own API keys. Aragora never marks up LLM costs.

| Model | Pricing Approach | Gross Margin Impact |
|---|---|---|
| Inference resellers | 2-3x markup on LLM costs | Margins compress as inference costs drop |
| Aragora (BYOK) | Zero LLM markup; revenue from platform | 85%+ gross margins from day one |

Aragora's model scales without COGS pressure because the product is the orchestration and audit trail, not the inference.

---

## What Will Be Eaten by Bigger Companies

Be honest about where Aragora should NOT try to compete:

| Capability | Who Wins | Why |
|---|---|---|
| Generic agent orchestration | LangGraph | Backed by LangChain ecosystem, massive community |
| Cooperative task automation | CrewAI | Simpler model, faster adoption for basic use cases |
| Single-model tool use | OpenAI Agents SDK | Native integration with the dominant model provider |
| Basic RAG/retrieval | Everyone | Commoditized; no differentiation possible |
| Simple chatbot integrations | Everyone | Table stakes, not a product |

**Strategic implication:** Do not compete on these axes. Competing on general-purpose agent orchestration is a losing game against well-funded incumbents with larger communities. Win on what they cannot easily replicate.

---

## How to Strengthen the Moat

### Immediate (Next 30 Days) — refreshed June 10, 2026

| Priority | Action | Impact |
|---|---|---|
| 1 | Graduate the remaining B0 cohort (#5182, #5183, #5184, #5186) — lift in-progress graduation above 50% and full-corpus truth above 69.2% | Converts the narrow 100%-verified headline into a broad, defensible benchmark claim |
| 2 | Close operator design-review #7472 (advisory-review recognizable headers) | Ends `unknown_model_reviewer` attribution; unblocks the implementation PR |
| 3 | Commission the external penetration test | The single blocker between "98% SOC 2 ready" and an actual SOC 2 Type II certification (~10 weeks after test) |

### Near-Term (30-90 Days)

| Priority | Action | Impact |
|---|---|---|
| 4 | Reduce the dominant `blocked_not_dispatch_bounded` failure class (12 recorded occurrences in B0) | Directly raises no-rescue truth success (currently 69.2%) |
| 5 | Case studies: run Aragora on real PRs in public repos, publish "before/after" comparisons | Demonstrates what adversarial debate catches that single-model review misses (one unmodified frontier adversarial review already survived on PR #7513) |
| 6 | EU AI Act compliance package: bundle receipt generation + compliance artifacts into a single command | Positions Aragora as the compliance solution before the August 2, 2026 enforcement date |

### Medium-Term (90-180 Days)

| Priority | Action | Impact |
|---|---|---|
| 7 | Marketplace: agent templates, workflow templates, vertical-specific packages | Creates ecosystem lock-in and community contribution |
| 8 | Enterprise pilots: 3-5 design partners in regulated industries (FinTech, HealthTech, LegalTech) | Validates pricing, surfaces real requirements, generates case studies |
| 9 | Cloud marketplace listings: AWS, GCP, Azure | Enterprise discovery and procurement compliance |

---

## The Bottom Line

### What Is Real

Aragora's core value proposition is **real and defensible**: multi-agent adversarial debate that produces audit-ready decision receipts.

- The debate engine works.
- The receipts work.
- The CLI works.
- The API works.
- The enterprise security works.
- A large, auto-counted test suite and the quality gates support it; see [`docs/METRICS.md`](../METRICS.md) for current counts.

This combination is unique. No funded competitor does it. It represents a new category -- Decision Integrity -- not a feature added to an existing category.

### What Needs Honest Qualification (refreshed June 10, 2026)

| Gap | Severity | Current state |
|---|---|---|
| B0 benchmark: 100% verified rate covers only 5 issues; full-corpus is 69.2%; 4 of 8 in-progress cohort issues (#5182, #5183, #5184, #5186) ungraduated | Medium | Graduate the cohort; dominant failure class `blocked_not_dispatch_bounded` (12 occurrences) needs reduction |
| No external penetration test; SOC 2 Type II not certified | Medium | Commission the pen test (~10 weeks to certification afterward) |
| Tier-5 scope creep: ~25% of the codebase (~490 files / ~200K LOC per [`docs/strategy/FOCUS.md`](FOCUS.md)) does not serve the core product thesis | Medium | Deprioritize or extract; this share has not materially shrunk since the tiering was published |
| Operator design-review #7472 pending — advisory reviews resolve to `unknown_model_reviewer` | Medium | Requires an operator yes/no on the Tier-4 design doc |
| Semantic convergence degrades silently to TF-IDF/Jaccard without `sentence-transformers` installed | Low | Surface a degradation warning; document the dependency |
| "Blockchain" receipts are SHA-256 hashing | Low | Reframe messaging; the audit trail is the value |
| Multi-agent parallelism is theoretical at full breadth (practical limit 2-6 agents real-time) | Low | Reframe around heterogeneity, not parallelism |

These are fixable gaps, not fundamental flaws. The architecture supports the claimed capabilities; the remaining work is benchmark graduation, third-party attestation, and scope discipline — not wiring.

### The Strategic Insight

Do not try to compete on general agent orchestration. LangGraph wins that game.

Do not try to be the simplest multi-agent framework. CrewAI wins that game.

Win on **decision quality, auditability, and compliance** -- the category Aragora created.

The EU AI Act creates a regulatory forcing function that makes this category inevitable. Every company deploying AI in high-risk domains will need documented decision validation and audit trails. Aragora is built for exactly this.

**Be the standard before someone else is.**
