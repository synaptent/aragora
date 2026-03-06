# Aragora Focus Strategy: Depth Over Breadth

> **Core thesis**: Aragora's defensible value is adversarial decision integrity —
> not general-purpose agent orchestration. This document defines what to invest in,
> what to maintain, and what to deprioritize.

## The Problem

The codebase has grown to **3,296 Python files / 1.48M LOC** across 120+ top-level modules.
This breadth creates:
- Maintenance burden that outpaces development capacity
- Unclear product identity ("is this a chat bot? a workflow engine? a blockchain project?")
- Difficulty for contributors to understand where to focus

## The One-Line Product

> **Aragora is the open-source adversarial vetting layer for AI-assisted decisions.**

When the decision matters — architecture, compliance, hiring, strategy — one model's
opinion isn't enough. Aragora orchestrates structured adversarial debates across
heterogeneous models, tracks calibrated confidence, and produces cryptographic
decision receipts for your audit file.

---

## Tier 1: Defensible Core (Invest Heavily)

These components are **genuinely unique** — no open-source equivalent exists.
They constitute Aragora's product-market fit.

| Module | Files | LOC | What It Does | Uniqueness |
|--------|-------|-----|--------------|------------|
| `debate/` | 230 | 104K | Adversarial debate engine: propose → critique → revise → synthesize | 9/10 — No OSS equivalent |
| `gauntlet/` | 32 | 14K | Red-team stress testing + cryptographic decision receipts | 8/10 — Novel receipt system |
| `knowledge/` | 161 | 89K | Knowledge Mound: 28-adapter institutional memory hub | 8/10 — Adapter factory unique |
| `ranking/` | 23 | 9K | ELO rankings + Brier calibration + domain-specific trust | 7/10 — Runtime calibration rare |
| `memory/` | 46 | 22K | 4-tier Continuum memory with red-line protection | 7/10 — Tier architecture novel |
| `reasoning/` | 16 | 8K | Belief networks, provenance tracking, claim graphs | 8/10 — Debate-integrated unique |
| `verification/` | 7 | 4K | ThinkPRM process reward model verification | 9/10 — Research paper impl |
| `explainability/` | 3 | 1K | Decision explanation: evidence chains, vote pivots | 6/10 — Useful, not unique |
| `evidence/` | 7 | 6K | Evidence collection and provenance tracking | 7/10 — Integrated with debate |

**Total: 525 files / 257K LOC (17% of codebase, 100% of unique value)**

### Investment priority
- Harden debate engine reliability and performance
- Expand ThinkPRM usage beyond single call site
- Make decision receipts the primary output artifact
- Improve explainability depth (counterfactuals, factor decomposition)

---

## Tier 2: Essential Infrastructure (Maintain)

These components are necessary to make the core accessible but are not
differentiators themselves.

| Module | Files | LOC | Role |
|--------|-------|-----|------|
| `agents/` | 80 | 36K | Agent implementations (Claude, GPT, Gemini, Grok, etc.) |
| `server/` | 946 | 410K | API layer — **oversized, needs pruning** |
| `storage/` | 101 | 52K | PostgreSQL/SQLite/Redis persistence |
| `cli/` | 56 | 23K | Command-line interface |
| `config/` | 14 | 7K | Configuration management |
| `core/` | 20 | 6K | Core types and protocols |
| `resilience/` | 12 | 4K | Circuit breakers, retry, timeout |
| `utils/` | 17 | 4K | Shared utilities |
| `protocols/` | 14 | 4K | Protocol definitions |

**Total: 1,260 files / 546K LOC (37% of codebase)**

### Action items
- **`server/` (946 files, 410K LOC)** is 28% of the entire codebase alone.
  Audit for dead handlers, consolidate, remove unused routes.
- Keep agent implementations lean — the value is in orchestration, not individual agents.
- CLI should prioritize `aragora debate`, `aragora review`, `aragora receipt` commands.

---

## Tier 3: Enterprise Features (Keep, Don't Lead With)

These features are table-stakes for enterprise adoption but don't differentiate.
Every framework adds them eventually.

| Module | Files | LOC | Role |
|--------|-------|-----|------|
| `rbac/` | 35 | 19K | Role-based access control (360+ permissions) |
| `audit/` | 43 | 24K | Audit logging |
| `billing/` | 34 | 23K | Cost tracking, metering, forecasting |
| `security/` | 9 | 7K | Encryption, key rotation, anomaly detection |
| `auth/` | 12 | 7K | OIDC/SAML SSO, MFA, API keys |
| `compliance/` | 5 | 4K | SOC 2, GDPR frameworks |
| `tenancy/` | 8 | 3K | Multi-tenant isolation |
| `privacy/` | 8 | 5K | Anonymization, consent, deletion, retention |
| `backup/` | 6 | 4K | Disaster recovery |
| `observability/` | 59 | 27K | Prometheus, Grafana, OpenTelemetry |
| `events/` | 26 | 10K | Event dispatcher, dead letter queue |

**Total: 245 files / 133K LOC (9% of codebase)**

### Guidance
- Maintain but don't expand unless customer-driven
- RBAC and audit are important for regulated industry positioning
- Observability is useful but 59 files / 27K LOC is oversized for monitoring

---

## Tier 4: Connectors (Necessary, Commodity)

Chat/platform connectors that make the core accessible. Important for adoption
but not differentiating — every platform has these.

| Module | Files | LOC | Role |
|--------|-------|-----|------|
| `connectors/` | 251 | 127K | Chat (8 platforms), enterprise, accounting, legal, medical |
| `integrations/` | 29 | 16K | Slack, email, Discord, Teams, Zapier, LangChain |
| `gateway/` | 73 | 31K | API gateway, routing, protocol |
| `mcp/` | 22 | 8K | Model Context Protocol tools |

**Total: 375 files / 182K LOC (12% of codebase)**

### Guidance
- 8 chat connectors is sufficient. Don't add more.
- `connectors/` at 127K LOC is bloated — many connectors have thin usage.
  Prioritize Slack, Teams, Discord. Consider making others community-maintained.
- Gateway is oversized at 31K LOC. Evaluate what's actually used.

---

## Tier 5: Deprioritize (Scope Creep)

These modules either duplicate functionality available in better-maintained
projects, are too experimental for GA, or don't serve the core product thesis.

| Module | Files | LOC | Why Deprioritize |
|--------|-------|-----|-----------------|
| `workflow/` | 83 | 32K | LangGraph does this better with larger community |
| `nomic/` | 86 | 40K | Self-improvement loop — experimental, safety concerns |
| `control_plane/` | 44 | 25K | Agent registry/scheduler — overkill for current stage |
| `rlm/` | 28 | 13K | Recursive Language Models — niche research |
| `services/` | 43 | 25K | Service layer — evaluate overlap with server/ |
| `blockchain/` | 10 | 2K | ERC-8004 — interesting research, not a product feature |
| `computer_use/` | 9 | 5K | Browser automation — Anthropic's tool, not our value-add |
| `training/` | 12 | 5K | Training pipelines — not core to decision integrity |
| `ml/` | 8 | 4K | ML utilities — use standard libraries instead |
| `voice/` + `speech/` + `transcription/` | 11 | 2K | Audio — not core |
| `canvas/` | 5 | 2K | Visual canvas — not core |
| `genesis/` | 7 | 3K | "Agent evolution" — experimental |
| `evolution/` | 6 | 3K | Evolution system — experimental |
| `sandbox/` | 5 | 3K | Docker sandbox — useful but not differentiating |
| `harnesses/` | 5 | 2K | External tool integration |
| `broadcast/` | 9 | 4K | Broadcasting — commodity |
| `channels/` | 18 | 4K | Channel management — overlaps with connectors/ |
| `bots/` | 7 | 3K | Bot framework — overlaps with connectors/ |
| `documents/` | 18 | 7K | Document handling — commodity |
| `marketplace/` | 4 | 1K | Agent marketplace — premature |
| `fabric/` | 12 | 5K | Fabric system |
| `coordination/` | 2 | 1K | Cross-workspace — premature |
| `coding/` | 2 | 1K | Code generation — not core |
| `replay/` | 6 | 1K | Debate replay |
| `spectate/` | 3 | 0.3K | Spectating |
| `introspection/` | 4 | 0.4K | Agent self-awareness |
| `learning/` | 2 | 0.5K | Continual learning |
| Various small modules | ~30 | ~10K | Misc |

**Total: ~490 files / ~200K LOC (25% of codebase)**

### Recommendations
- **`workflow/`**: Consider replacing with LangGraph integration. 83 files for a
  workflow engine competes with a VC-backed project with 10x the team.
- **`nomic/`**: Keep as experimental/internal. Do not market as production feature.
  Safety implications of self-improving AI are serious.
- **`control_plane/`**: Evaluate actual usage. 25K LOC for agent scheduling may be
  premature for current adoption stage.
- **`blockchain/`**: Interesting research. Keep in `experimental/` namespace but
  don't invest further until there's user demand.
- **Audio/visual/canvas**: Remove from main package or move to `contrib/`.

---

## The Math

| Tier | Files | LOC | % of Codebase | Investment |
|------|-------|-----|---------------|------------|
| 1. Defensible Core | 525 | 257K | 17% | **Invest heavily** |
| 2. Essential Infrastructure | 1,260 | 546K | 37% | Maintain, prune server/ |
| 3. Enterprise Features | 245 | 133K | 9% | Keep, don't expand |
| 4. Connectors | 375 | 182K | 12% | Maintain top 3 platforms |
| 5. Scope Creep | ~490 | ~200K | 25% | Deprioritize or extract |

**Key insight**: 25% of the codebase (Tier 5) doesn't serve the core product thesis.
The remaining 75% can be further optimized by pruning `server/` (410K LOC is excessive).

---

## Standalone Library Strategy

The highest-leverage move is extracting the Tier 1 core as a standalone library:

```bash
pip install aragora-debate
```

This package should contain:
1. **Debate orchestration** — `Arena`, `DebateProtocol`, phases
2. **Agent interface** — Protocol/ABC that any LLM wrapper can implement
3. **Consensus detection** — Majority, weighted, semantic similarity
4. **Decision receipts** — Cryptographic signing, dissent tracking
5. **Calibration** — ELO rankings, Brier scores

It should **not** contain: server, connectors, enterprise features, workflow,
blockchain, self-improvement, or any other Tier 3-5 module.

**Target**: Under 50 files, under 10K LOC, zero infrastructure dependencies.
A developer should be able to run an adversarial debate in 10 lines of code.

---

## Success Metrics

1. **Can a new user run a debate in under 5 minutes?** (Currently: no)
2. **Can someone explain what Aragora does in one sentence?** (Currently: unclear)
3. **Does every PR serve the core thesis?** (Currently: often no)
4. **Is the test suite focused on the core?** (130K tests, but how many test Tier 1?)
