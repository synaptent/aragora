# Aragora

**Aragora is an auditable execution control plane for AI-assisted decisions:
multi-model review in, a verifiable Decision Receipt out.**

It coordinates heterogeneous models to adversarially review a change or a
decision, preserves the dissent and provenance, stops truthfully when evidence
is thin, and emits a portable receipt anyone can verify offline with the
standalone verifier ([`pip install -U 'aragora-verify>=0.1.1'`](https://pypi.org/project/aragora-verify/)).

[![PyPI](https://img.shields.io/pypi/v/aragora)](https://pypi.org/project/aragora/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

> **New here?** The [Quickstart](docs/quickstart.md) gets you a working debate in
> under a minute. Auditors should start with the [Cold Reviewer Guide](docs/COLD_REVIEWER_GUIDE.md).

| I want to… | Command |
|------------|---------|
| Run the standalone debate engine | `pip install aragora-debate` |
| Verify an Open Decision Receipt with the standalone verifier | `pip install -U 'aragora-verify>=0.1.1' && aragora-verify receipt.odr.json` |
| Run the current PyPI zero-key receipt demo | `pip install -U 'aragora>=2.9.0' && aragora demo --offline --receipt aragora-demo-receipt.json && aragora receipt verify aragora-demo-receipt.json` |
| Audit this source checkout's exact CLI | `python3 -m pip install -e . && aragora demo --offline --receipt aragora-demo-receipt.json && aragora receipt verify aragora-demo-receipt.json` |
| Call the Aragora API from Python | `pip install aragora-sdk` |
| Self-host the full platform | `docker compose -f deploy/demo/docker-compose.yml up` |

Use `aragora>=2.9.0` for the explicit offline demo receipt round trip. Earlier
PyPI releases do not support the `--offline` receipt flags. Use the source
checkout path when you need to audit this exact branch or unreleased local
changes.

## The problem

Individual LLMs are unreliable. Their personas shift with context, their
confidence does not correlate with accuracy, and they often optimize for
plausible agreement instead of truth. Aragora treats that as a systems problem:
it makes consequential AI-assisted decisions **inspectable and verifiable**
instead of asking you to trust one model's say-so.

- **Disagreement becomes evidence.** Heterogeneous models challenge each other before work advances; dissent is preserved, not averaged away.
- **Every decision has a receipt.** Verdict, the reviewing models and their independence, dissent, confidence, and provenance stay inspectable.
- **It stops truthfully.** When the quorum can't be formed or evidence is thin, the receipt says so — it never fabricates a consensus.
- **Receipts are portable and verifiable.** A receipt is a schema-conformant artifact (the [Open Decision Receipt](docs/specs/OPEN_DECISION_RECEIPT.md)) that `aragora-verify` checks offline, with no dependency on Aragora.

## The wedge: a governance gate for AI-written code

Drop Aragora into CI. A multi-model quorum reviews each PR and posts a grounded
PR comment — your second opinion, with the same review surface that feeds the
Decision Receipt path.

```yaml
# .github/workflows/aragora-review.yml
name: Aragora Review
on:
  pull_request:
    types: [opened, synchronize, reopened]
permissions:
  contents: read
  pull-requests: write
  issues: write
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: synaptent/aragora@8b600a3a8dbf076f4027ae27f3dcbbf48e75409f
        with:
          anthropic-api-key: ${{ secrets.ANTHROPIC_API_KEY }}
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          post-comment: 'true'
          emit-receipt: 'true'
```

The action posts a PR review comment, uploads the machine-readable review
artifact, and (with `emit-receipt: 'true'` shown above) emits a Decision
Receipt artifact from a second, independent quorum pass. Anyone — a teammate,
an auditor, a customer — can then verify that receipt independently with the
standalone `aragora-verify` verifier (no Aragora dependency):

```bash
pip install -U 'aragora-verify>=0.1.1'
aragora-verify decision-receipt.odr.json

# Add a public key when you need issuer authenticity, not just structure/digest:
aragora-verify decision-receipt.odr.json --pubkey signing-key.pem

# or build from source (this repo, aragora-verify/):
pip install ./aragora-verify
```

> Use **0.1.1+** (`pip install -U 'aragora-verify>=0.1.1'`): it binds each
> signature's recorded `key_id` to the key you supply, so a relabeled signer
> fails as tampering. 0.1.0 lacks that binding — upgrade if you have it.

See the [full Action setup guide](docs/GITHUB_ACTION_SETUP.md#emitting-a-verifiable-decision-receipt)
for the receipt-specific inputs/outputs, secret-dependent limits (receipts are
unsigned; reviewer defaults need reachable provider keys), and a committed
example receipt you can verify right now without running any CI.

We run this gate on our own repository — every substantive merge is reviewed
by a heterogeneous model quorum, dissent preserved, receipts written. The
evidence, with reproducible queries and caught-bug case studies:
[**Decision Integrity, Dogfooded**](https://github.com/synaptent/aragora/blob/main/docs/artifacts/2026-07-decision-integrity-dogfooding.md).

## Try it now

Current PyPI package:

```bash
pip install -U 'aragora>=2.9.0'
aragora demo --offline --receipt aragora-demo-receipt.json
aragora receipt verify aragora-demo-receipt.json
```

Current source checkout:

```bash
python3 -m pip install -e .
aragora demo --offline --receipt aragora-demo-receipt.json
aragora receipt verify aragora-demo-receipt.json
aragora receipt export aragora-demo-receipt.json --format odr -o receipt.odr.json
```

Live review with a provider key:

```bash
export ANTHROPIC_API_KEY=...        # provider credential for live model review
aragora review-pr 123               # multi-agent review of a GitHub PR
```

## Core workflows

- **AI code review** — heterogeneous-model review of a diff or PR, with severity-tagged findings and a receipt. See [docs/CLI_REFERENCE.md](docs/CLI_REFERENCE.md).
- **Gauntlet** — adversarial stress-testing of a claim or spec; attack/defend cycles produce a cryptographic receipt.
- **Structured debates** — multi-round debate with consensus detection and convergence tracking (`aragora ask`).

## The load-bearing core

Aragora is large, but five modules carry the product. Start here:

| Module | Responsibility |
|--------|----------------|
| `aragora/debate/` | The Arena orchestrator — runs rounds, detects consensus/convergence. |
| `aragora/agents/` | Agent implementations (API + CLI), heterogeneous model transport, fallback. |
| `aragora/gauntlet/` | Decision Receipts: the native record, the portable [ODR](docs/specs/OPEN_DECISION_RECEIPT.md), export and signing. |
| `aragora/swarm/` | The merge-quorum gate — collects model-review evidence and tiers settlement. |
| `aragora/server/` | The HTTP/WebSocket API and handlers. |

`aragora-verify/` is a separate verifier project with no Aragora dependency:
the public verifier for receipts. Everything else under `aragora/` is
supporting or experimental surface — treat it as such until it's documented
here.

## Product boundary

Aragora is a **governance and review layer**, not an execution runtime. It is
not a replacement for worker runtimes like Codex, Claude Code, or OpenCode. Use
it when review, provenance, and a verifiable decision record matter; keep your
existing runtimes when raw speed is all you need.

- We do not sell lights-out autonomy as the default story.
- We do not advance work without evidence, review, and clear terminal states.
- Consequential effectors are denied by default unless an admin-scoped approval artifact exists; sandboxed backends are mandatory for browser/host effectors.

See [Boundaries and Scope](docs/strategy/BOUNDARIES_AND_SCOPE.md) for the full non-goals ledger.

## From the wedge to the full vision

The CI review gate is the first rung of a deliberate ladder — each step reuses the
same receipt, memory, and quorum substrate rather than bolting on a new system:

```
CI review gate ─▶ portable Decision Receipt (ODR) ─▶ crux + calibration in the receipt
   ─▶ bounded-backlog foreman (unattended work, receipts + stop conditions)
   ─▶ unified idea→goal→action→orchestration DAG ─▶ organization substrate
```

The narrow product you can adopt today and the long-horizon thesis are the same
system at different stages. The complete scope — every capability, the roadmap, and
the agent-civilization frontier — is in the [Full Vision postscript](#full-vision),
annotated by status and gate.

### Anatomy of a Decision Receipt

The receipt is the unit that carries through every stage. One review produces:

```
decision ──▶ model jury (heterogeneous, independent)
               ├─ proposals / critiques / revisions
               ├─ dissent trail (+ cruxes when a CruxReceipt is supplied — ODR-4)
               └─ per-agent ELO + Brier calibration when provenance present — ODR-5
          ──▶ verdict + confidence
          ──▶ human attestation (optional; EU AI Act Art. 14)   🔄 #8230
          ──▶ Ed25519 signature                                 🔄 #8225
          ──▶ portable ODR JSON  ──▶  aragora-verify <receipt>  ✅ schema+digest+quorum, offline
          ──▶ Rekor public anchoring (tamper-evidence)          🔄 #8231
```

Today's receipts verify on schema, digest, and quorum consistency offline; per the
[ODR spec](docs/specs/OPEN_DECISION_RECEIPT.md), cruxes and calibration carry explicit
*absent markers* unless their source is supplied (ODR-4/5), and public-key signing and
anchoring are in-flight. See the [proof ladder](#proof-ladder).

## Find your path

- **Developer** — [Quickstart](docs/quickstart.md) → `aragora review-pr` → [CLI Reference](docs/CLI_REFERENCE.md) · [SDK Guide](docs/SDK_GUIDE.md)
- **Auditor / reviewer** — [Cold Reviewer Guide](docs/COLD_REVIEWER_GUIDE.md) → [Open Decision Receipt spec](docs/specs/OPEN_DECISION_RECEIPT.md) → `aragora-verify`
- **Founder / operator** — the wedge above → [proof ladder](#proof-ladder) → [Full Vision](#full-vision)
- **Compliance buyer** — [Enterprise features](docs/enterprise/ENTERPRISE_FEATURES.md) → EU AI Act / SOC 2 status in [honest current state](#honest-current-state)
- **Agent / tool builder** — the [ODR](docs/specs/OPEN_DECISION_RECEIPT.md) as the external contract → MCP tools → [API Reference](docs/api/API_REFERENCE.md)

## Documentation

- [Quickstart](docs/quickstart.md) · [Cold Reviewer Guide](docs/COLD_REVIEWER_GUIDE.md) · [CLI Reference](docs/CLI_REFERENCE.md)
- [Open Decision Receipt spec](docs/specs/OPEN_DECISION_RECEIPT.md) · [SDK Guide](docs/SDK_GUIDE.md) · [API Reference](docs/api/API_REFERENCE.md)
- [Feature status](docs/STATUS.md) · [Enterprise features](docs/enterprise/ENTERPRISE_FEATURES.md) · [Architecture deep-dive](docs/EXTENDED_README.md)
- [Inspiration and credits](docs/reference/CREDITS.md)

## Security

Secrets load from AWS Secrets Manager in production (never standing env keys);
local development uses a gitignored `.env`. See the
[security overview](docs/enterprise/SECURITY.md),
[compliance overview](docs/enterprise/COMPLIANCE.md), and
[deployment guide](docs/deployment/DEPLOYMENT.md).

## Contributing & License

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). MIT licensed
(see [LICENSE](LICENSE)).

### Development

Root Python package, from a source checkout with the `dev,test` extras installed
(`pip install -e ".[dev,test]"`):

| Task | Command |
|------|---------|
| Run the API server | `aragora serve --api-port 8080 --ws-port 8765` (or `make serve`) |
| Build the wheel/sdist | `python -m build` (setuptools backend) |
| Test | `make test-fast` (quick tier) · `make test` (full suite) |
| Lint / format | `make lint` · `make format` |
| Type check | `make typecheck` |
| Readiness gate (all apps) | `make readiness-lint && make readiness-typecheck && make readiness-test` |

The `readiness-*` targets fan out to every app in the repo and print
`SKIP <app>: <reason>` when a toolchain is absent; see
[docs/RATCHETS.md](docs/RATCHETS.md) for the baseline ratchets they run.

---

<a id="full-vision"></a>

## Postscript — The Full Vision

> The sections above are what Aragora **is today** and how to use it. What follows
> is the **complete intended scope** — the thesis, the whole capability surface, the
> roadmap, and the long-horizon vision — recorded in one place so that anyone (human
> or agent) who reads to the end sees exactly how large this project means to become.
> It is deliberately dense.
>
> **Read this honestly.** Markers: ✅ shipped/working · 🟡 built but not productized ·
> 🔄 in-flight · 🔮 designed or aspirational. Per our
> [commercial discipline](docs/COMMERCIAL_OVERVIEW.md), *external claims stay narrower
> than this roadmap and tied to measured proof.* Canonical metrics live in
> [`docs/METRICS.md`](docs/METRICS.md); the candid current-state ledger is
> [`docs/HONEST_ASSESSMENT.md`](docs/HONEST_ASSESSMENT.md). Where a number is contested
> across docs it is rounded here on purpose. Every major claim below carries a proof
> link, a status marker, or an explicit aspirational label — start with the proof ladder.

<a id="proof-ladder"></a>

### Proof ladder — how to verify every claim here

| Claim class | Canonical source / gate |
|---|---|
| Scale & metrics | [`docs/METRICS.md`](docs/METRICS.md) — `python scripts/regenerate_metrics.py --check` fails CI on >0.5% drift |
| What's real vs aspirational | [`docs/HONEST_ASSESSMENT.md`](docs/HONEST_ASSESSMENT.md) |
| Receipt format (the external contract) | [Open Decision Receipt spec](docs/specs/OPEN_DECISION_RECEIPT.md) |
| Decision-semantics roadmap | ODR spine epic [#8223](https://github.com/synaptent/aragora/issues/8223); ODR-1..7 → [#8224](https://github.com/synaptent/aragora/issues/8224)/[#8225](https://github.com/synaptent/aragora/issues/8225)/[#8226](https://github.com/synaptent/aragora/issues/8226)/[#8227](https://github.com/synaptent/aragora/issues/8227)/[#8229](https://github.com/synaptent/aragora/issues/8229)/[#8230](https://github.com/synaptent/aragora/issues/8230)/[#8231](https://github.com/synaptent/aragora/issues/8231) |
| Jul 2026 durability capture / outsider-verifiable claims | [Durable strategy capture](docs/strategy/2026-07-05-durable-strategy-capture.md); executable claims manifest [`outsider_verifiable_claims.yaml`](docs/status/claims/outsider_verifiable_claims.yaml); parent capture issue [#8856](https://github.com/synaptent/aragora/issues/8856) |
| Autonomy truth | B0 benchmark [`docs/status/B0_BENCHMARK_TRUTH_STATUS.md`](docs/status/B0_BENCHMARK_TRUTH_STATUS.md) |
| Enterprise / compliance | [GA checklist](docs/GA_CHECKLIST.md) (SOC 2 / pentest gate) · [Enterprise features](docs/enterprise/ENTERPRISE_FEATURES.md) |
| Frontier work is bounded | the proof-first Foreman gate + capability checkpoints CP-1..5 (below) |

### The thesis — Decision Integrity

**The core claim, in one sentence: heterogeneous frontier models adversarially
review a decision; disagreement is preserved, not averaged away; the output is a
signed, dissent-preserving Decision Receipt an auditor can verify offline without
trusting Aragora.**

Aragora orchestrates **heterogeneous, adversarial multi-model debate** to vet,
challenge, and audit consequential decisions *before* they ship — and emits
cryptographic proof that the decision was rigorously examined. This is a distinct
category from cooperative agent orchestration (LangGraph, CrewAI, AutoGen), from
single-provider agent SDKs, and from post-hoc AI observability: those coordinate
graphs or monitor behavior after the fact; Aragora improves decision *quality*
before commit and produces the audit trail as a byproduct.
*(docs/WHY_ARAGORA.md, docs/COMPARISON_MATRIX.md)*

**Why a single model isn't enough.** LLMs exhibit correlated failures (shared
training data and RLHF biases), sycophantic agreement (confidence uncorrelated with
accuracy), and persona instability (minor prompt changes flip answers). Treat each
model as an *unreliable witness* and extract signal from where independent witnesses
disagree. Clinical triage, financial risk, legal review, and architecture decisions
cannot rest on "probably right." The moat: no funded competitor combines structured
adversarial multi-agent debate with portable, verifiable decision receipts.
*(docs/WHY_ARAGORA.md, docs/HONEST_ASSESSMENT.md)*

**Why this is not generic orchestration:**

| | Cooperative orchestration (LangGraph / CrewAI / AutoGen) | Aragora |
|---|---|---|
| Agent disagreement | a bug to resolve | the signal — preserved as dissent + cruxes |
| Primary output | the completed task | a verifiable Decision Receipt |
| Model independence | often single-provider | heterogeneous providers by design |
| When evidence is thin | proceeds | stops truthfully; the receipt says so |
| Delegation | open-ended | bounded; approval artifacts + sandboxed effectors |

*(docs/strategy/BOUNDARIES_AND_SCOPE.md, docs/COMPARISON_MATRIX.md)*

### The Five Pillars *(product framing — docs/EXTENDED_README.md)*

1. **SMB-ready, enterprise-grade.** Works for a 5-person startup on day one; scales
   to regulated enterprise without rearchitecting. SSO/MFA, encryption, RBAC, and
   compliance frameworks are built-in defaults, not premium tiers.
2. **Leading-edge memory & context.** 4-tier Continuum Memory (fast/medium/slow/
   glacial) + Knowledge Mound give every debate institutional history and evidence
   provenance; RLM (Recursive Language Models) sustains coherence over long sessions
   and large corpora where single models degrade.
3. **Extensible & modular.** 12+ model providers, broad connectors, Python + TypeScript
   SDKs, a large REST/WebSocket API surface, and a workflow-template library.
4. **Multi-agent robustness.** Claude, GPT, Gemini, Grok, Mistral, DeepSeek run in
   structured Propose/Critique/Revise debates with multiple consensus modes; ELO and
   Brier calibration track per-domain agent quality; the Trickster flags hollow
   consensus. Output is higher-quality and lower-bias than any single model, with a
   complete dissent trail.
5. **Self-healing & self-extending.** The Nomic Loop lets the platform debate, design,
   implement, and verify improvements to *itself*, with human approval gates and
   automatic rollback.

### The long arc

The full long-horizon vision — the five-stage **Tool → Organization Substrate**
ladder and the eight foundational substrate pillars — lives in
[`docs/vision/MAXIMALIST_VISION.md`](docs/vision/MAXIMALIST_VISION.md), together with
the staged-integration criteria that govern when each piece activates. The near-term
focus narrows hard to what is already earned and externally provable: **cryptographic
receipts & auditability** and **reliable autonomous execution** on bounded backlogs.
The vision is retained in full; the README carries only the claim the code currently
proves. *(docs/CANONICAL_GOALS.md, docs/vision/MAXIMALIST_VISION.md)*

### The complete capability surface

<!-- metrics:begin readme-scale -->
> Scale (canonical counts in [`docs/METRICS.md`](docs/METRICS.md), rounded):
> **~4,300 Python files · ~1.9M LOC · 140+ top-level modules · 200,000+ test
> functions across ~5,500 files · 3,205 API operations across 2,912 paths ·
> 35+ allowlisted agent types across 12+ providers · 41 Knowledge Mound adapter specs
> (46 files) · 360+ RBAC permissions · Python + TypeScript SDKs · v2.10.0.**
> (Practical real-time debate uses 2–6 agents; the value is *heterogeneity*, not raw
> count — see docs/HONEST_ASSESSMENT.md.)
<!-- metrics:end -->

**Core debate (✅).** Arena engine orchestrates Propose/Critique/Revise/Vote phases,
extended multi-round debates, semantic convergence detection, ELO-based team
selection with continuous calibration. Consensus modes: majority, unanimous, weighted/
judge, byzantine, and Prover-Estimator. Enhancements: Trickster (hollow-consensus
detection), Rhetorical Observer, Security Barrier (telemetry redaction), Calibration
Tracker, Performance Monitor, Graph/Matrix topologies, breakpoints (pause/resume).

**Agents (✅).** API providers: Anthropic, OpenAI, Google Gemini, Mistral (Large/
Codestral), xAI Grok, OpenRouter (DeepSeek/Llama/Qwen/Yi/Kimi), local Ollama/LM Studio.
CLI agents: Claude, Codex, Gemini, Grok. Resilience: Airlock circuit breaker,
automatic OpenRouter fallback on 429, session circuit-breaker (auth-state pinning),
per-provider rate limiting, unified error hierarchy.

**Memory & learning (✅).** Continuum Memory (4 tiers, atomic cross-system writes via
Memory Coordinator); Unified Memory Gateway fanning out across Continuum, Knowledge
Mound, Supermemory, and claude-mem with a surprise-driven RetentionGate (Titans/MIRAS)
and SHA-256 + Jaccard dedup; RLM context-as-REPL-variables (not prompt compression);
ELO ratings, tournaments, leaderboards, performance-based selection.

**Knowledge management (✅, Phase A2).** Knowledge Mound: semantic vector search,
graph store with lineage, domain taxonomy, visibility tiers (private→workspace→org→
public→system), time-bounded access grants, cross-workspace federation. Auto-curation:
dedup, contradiction detection, confidence decay, RBAC governance, ResilientPostgres
store, SLO alerting. 40+ registered adapters auto-built from Arena subsystems; bridges
(MetaLearner, Evidence, Pattern); belief networks with claim provenance and cruxes.

**Enterprise & security (✅, production-ready).** OIDC/SAML SSO, TOTP/HOTP MFA, SCIM 2.0
(Okta/Azure/OneLogin), scoped API keys; RBAC v2 (360+ permissions, 7 roles, hierarchy,
decorators, middleware, audit); multi-tenancy (SQL auto-filtering, quotas, metering);
AES-256-GCM field encryption with Cloud KMS + key rotation, PII anonymization, GDPR
erasure; circuit breakers, rate limiting, SSRF protection, security headers; incremental
backup/DR with drills.

**Compliance & governance (mixed).** EU AI Act artifact generation for Articles 9/12/13/
14/15 with risk classification (🔄, bundle ~90/100 complete; enforcement deadline **Aug 2,
2026**); SOC 2 Type II controls implemented (🔄 ~98%; **blocker: external penetration test
not yet commissioned** — *not certified*); GDPR DSAR/erasure/consent/retention (✅);
HIPAA field encryption, Safe Harbor de-identification, breach-notification workflows (✅
controls); SOX-oriented audit profiles (✅). *(docs/HONEST_ASSESSMENT.md, docs/GA_CHECKLIST.md)*

**Integrations & connectors (✅, 50+).** Chat: Slack, Discord, Teams, Google Chat,
Telegram, WhatsApp (with TTS/voice). Streaming: Kafka, RabbitMQ (DLQ, bidirectional).
Enterprise data: SharePoint, Confluence, Notion, PostgreSQL/MongoDB/MySQL/SQL Server/
Snowflake (CDC), Salesforce, HubSpot, Zendesk, Jira. Sources: GitHub, ArXiv, Wikipedia,
SEC filings, HackerNews, Reddit, Twitter/X. Email/voice: Gmail + Outlook sync, Twilio
phone debates, SMTP. Healthcare: HL7v2, FHIR. Bidirectional routing returns results to
the originating platform.

**Observability & control plane (✅).** Prometheus custom metrics, Grafana dashboards,
OpenTelemetry tracing (OTLP, multiple backends), structured JSON logs with PII redaction
and correlation IDs; agent registry with heartbeats, priority scheduler, liveness/
readiness probes; policy governance (conflict detection, Redis cache, background sync,
versioned rollback). 1,500+ control-plane tests.

**Advanced capabilities.** Pulse trending-topic ingestion (✅); Gauntlet adversarial
red-team + cryptographic receipts (✅); Swarm orchestration — bounded work orders,
worker launcher into managed worktrees, reconciler, leases, salvage queue (✅); Inbox
Trust Wedge — Gmail → debate → signed receipt → approval → execute (✅ CLI, 🔮 web GUI
for retest); Live Explainability, structural argument verification, outcome-feedback
loop (✅); Workflow Engine — DAG automation with 50+ templates (✅); Prompt Engine —
vague prompt → validated spec via debate (✅); Computer-Use bridge + OpenClaw
compatibility (🔄).

**SDK & ecosystem (✅/🔄).** `aragora-sdk` (blessed Python client), full `aragora`
package, `@aragora/sdk` (TypeScript); MCP server exposing a large tool surface for
Claude integration with reasoning-trace capture; extensible plugin/marketplace
architecture (🔮 no public marketplace endpoint yet).

**Deployment & HA (✅).** Docker Compose (dev/prod), Kubernetes Helm chart with
multi-region values (US/EU/APAC data residency), HPA/PDB/network policies, External
Secrets Operator, cert-manager; Terraform IaC; SQLite (dev) / PostgreSQL (prod) with
pooling; unified TTL cache + Redis cluster failover; incremental backup to local/S3/GCS,
offline/air-gapped mode.

**Built but not productized (🟡).** Real code in-tree, little or no public surface —
tracked openly, not hidden *(docs/FEATURE_GAP_LIST.md dormant table)*:
- **Crux detector** — engine + operator CLI complete; no public API/SDK or crux-set-in-receipt yet ([#8227](https://github.com/synaptent/aragora/issues/8227), ODR-4).
- **Pareto provider router** — optimizer + pricing DB shipped; the loop doesn't yet route by decision stakes or record rationale ([#8233](https://github.com/synaptent/aragora/issues/8233)).
- **Tamper-evident audit trail** — trail verifies checksums; external-witness append-only anchoring is building (TET spec; Rekor [#8231](https://github.com/synaptent/aragora/issues/8231)).
- **ERC-8004 / blockchain** — registries + handlers in-tree, deployed to no network; **de-scoped** by the steering-leverage filter (the anchoring need is served by Rekor instead).
- **Skills marketplace** — code + seed catalog exist; no public endpoint or third-party content.

### Vertical specialists *(docs/verticals/, 🔄 guides exist; packaged offerings 🔮)*

- **Healthcare** — FHIR R4 (Epic/Cerner via SMART-on-FHIR), drug-interaction and
  contraindication analysis, treatment-pathway debate, HIPAA-compliant receipts.
- **Financial services** — credit underwriting, fraud investigation, investment-committee
  review, stress-testing, audit-grade dissent trails (SOX/SOC 2 workflows).
- **Legal** — clause-by-clause adversarial contract analysis, counterparty modeling,
  missing-clause detection, M&A due diligence (6 concurrent review streams), litigation
  risk.
- **Accounting** — loan risk, equity valuation, deal-structure analysis, materiality
  assessment.

### Self-improvement — the Nomic Loop & the flywheel

**The Nomic Loop (✅, 233+ tests).** A five-phase autonomous self-improvement cycle:
**Context → Debate → Design → Implement → Verify.** Heterogeneous agents propose and
argue improvements, architect a solution, generate code in isolated worktrees, then
gate on automated tests + cross-agent review + merge arbiter + Knowledge Mound learning.
Infrastructure: TaskDecomposer, HardenedOrchestrator (default since Feb 2026),
BranchCoordinator, MetaPlanner, AutonomousOrchestrator. Safety: prompt-injection
scanning, canary tokens, sandbox execution, review-gate scoring, automatic rollback,
protected-file checksums, human approval gates. CLI: `aragora self-improve "<goal>"`,
`scripts/self_develop.py`, `scripts/nomic_staged.py`. *(CLAUDE.md, docs/plans/SELF_IMPROVING_ARAGORA.md)*

**The flywheel.** Aragora uses Aragora to improve Aragora: debates over tradeoffs →
receipts capturing the reasoning → Knowledge Mound learning → better-calibrated next
debate. As the system fixes its own bugs and ships its own features, the verifiable
corpus and the agent-calibration data grow — and that calibration data is the moat. The
strategy-mission cadence that produced *this very README* gated its own merge through
Aragora's quorum→receipt machinery — the flywheel, demonstrated.

**The honest version is stronger than the success story.** In June 2026 the gate was
so genuinely adversarial that it deadlocked our own factory for weeks: adversarial
review never returned empty, repair commits reset review budgets, dissent acted as a
post-hoc veto, and a 240+-PR backlog piled up against a gate that refused to wave
anything through. The receipts for that deadlock — and for the settlement machinery
that fixed it (tiered gates, severity-gated dissent, head-bound evidence, the
adjudicator) — are in this repo's history. Nobody else has published measured failure
modes of adversarial review at this scale, because nobody else has run one this long.
That scar tissue *is* the dogfood evidence.

### The frontier — Agent Civilization Substrate *(🔮 designed; gated, see below)*

Beyond human-operated orgs, Aragora is designed as a substrate for consequential
multi-agent coordination where **reputation is earned against external ground truth,
not closed-loop agreement.** Six tracks (AGT-01..06): activate the CruxDetector in live
debates; an A2A consumer surface where agents register/discover/transact/consume
receipts; Manifold Markets integration with rolling Brier scoring; synthetic GitHub
markets (predict PR merges / issue closures with verifiable resolution); ERC-8004
reputation flow (claims → stakes → resolution → reputation deltas → dispatch
eligibility — *contracts written, no mainnet; de-scoped June 2026 in favor of Sigstore
Rekor anchoring*); and a Verifiable-Improvements-per-Agent-Hour (VIAH) self-justification
metric. *(docs/plans/ agent-civilization designs)*

- **Crux Finder (✅ MVP / 🔮 shaping).** Consensus mode `crux_finder` surfaces the 3–5
  load-bearing disagreements where flipping a belief flips the conclusion; signed
  CruxReceipts, `aragora crux "<question>"`. Crux-shaping prompts and per-round
  claim targeting are deferred pending dogfood runs.
- **Epistemic CI / Decision Integrity Core (🔮 DIC-13..22).** Extend receipts beyond
  debates to *code and organizational claims*: executable claims (evidence + freshness
  SLAs + verification contracts), proof-carrying code units that fail closed when
  assumptions decay, epistemic decay signals proposing bounded repair, and a read-only
  organizational truth map. Initial shape is manifest-based and read-only.
- **Trust-Compound plan (🔄 TCP-1..7).** Make the large surface *legible without
  deletion*: a canonical-metrics manifest verified in CI (so a claim like "46 adapters"
  passes or fails the build), packaging clarity, hotspot-file splits, wire/showcase/
  shelve classification per subsystem, generated artifacts as build outputs, this README
  rewrite, and public CruxSets at `aragora.ai/cruxes`.

### Discipline — capability checkpoints (CP-1..5)

The vision is **bounded, not open-ended.** Booster-stage investment in the frontier must
graduate through checkpoints, each ~4 weeks apart: CP-1 stable self-healing soaks → CP-2
CruxDetector driving real follow-ups → CP-3 stable prediction-calibration curves → CP-4
a reputation delta changing real dispatch → CP-5 positive VIAH trend without an operator-
rescue spike. **Failing a checkpoint downscales the next investment; it does not kill the
vision.** Frontier (AGT-*/DIC-*) work never carries `boss-ready` until the proof-first
gate explicitly opens the upper tranche. *(docs/plans/ trust-compound + checkpoints)*

### Roadmap — priority-gated *(docs/FEATURE_GAP_LIST.md, docs/CANONICAL_GOALS.md)*

**Current execution spine — Open Decision Receipt** (epic [#8223](https://github.com/synaptent/aragora/issues/8223); supersedes the P0/P1 ordering below): **ODR-1** vendor-neutral receipt profile (JSON Schema + JCS) [#8224](https://github.com/synaptent/aragora/issues/8224) → **ODR-2** Ed25519 public-key signing [#8225](https://github.com/synaptent/aragora/issues/8225) → **ODR-3** `aragora-verify` standalone offline verifier + `/api/receipts/verify` [#8226](https://github.com/synaptent/aragora/issues/8226) → **ODR-4** expose the crux finder [#8227](https://github.com/synaptent/aragora/issues/8227) → **ODR-5** calibration report + calibrated confidence [#8229](https://github.com/synaptent/aragora/issues/8229) → **ODR-6** human-oversight attestation + EU AI Act Art. 14 pack [#8230](https://github.com/synaptent/aragora/issues/8230) → **ODR-7** Sigstore Rekor public anchoring [#8231](https://github.com/synaptent/aragora/issues/8231). (1–3 are the spine: a receipt a stranger can verify; 4–6 enrich the payload; 7 makes anchoring public.)

- **P0 — PMF blockers:** truthful live founder loop (✅ 5/5 proved); smart provider
  routing (✅ optimizer + runtime; 🔄 decision-stakes routing); complete repeatable user
  journey (🔄); KM reads enrich debate context (🔄 live proof pending).
- **P1 — value-prop proof (Q2 2026):** OpenClaw end-to-end (🔄); 5 functional frontend
  paths (🔄); 10+ agent coordinated debates (🔄 scale testing); agent-first beta via REST
  (✅ 12-runner fleet); GitHub Actions pre-merge gate (🔄); public demo at aragora.ai/demo
  (🔄); EU AI Act bundle (🔄 ~90/100); <10-min onboarding (🔄).
- **P2 — hardening & enterprise (post-PMF):** external penetration test (🔮 vendor
  shortlisted); Decision-Integrity UI Workbench (🔄 partial); SOC 2 Type II audit (🔄
  ~98% controls); Enterprise Communication Hub (✅ shipped, 🔄 trigger validation).
- **P3 — scale & revenue (Q3–Q4 2026, de-scoped until PMF):** cloud marketplace listings;
  vertical packages; Skills Marketplace pilot; on-prem productization; data residency /
  international.
- **P4 — strategic evolution (2026+):** ✅ Prover-Estimator, cross-verification, truth-
  ratio weighting, anti-sycophancy, prompt-to-spec, Obsidian sync; 🔮 Dialectical Runtime
  synthesis (DIC-23..28), market-resolution mechanism, meta-improver for protocols.
- **P5 — federation (🔮):** distributed debates across orgs, cross-org knowledge sync.

### Focus strategy — depth over breadth *(docs/FOCUS.md)*

The codebase is explicitly tiered for investment: **Tier 1 defensible core** (~17% of
files, ~100% of unique value: debate engine, Gauntlet, Knowledge Mound, ELO/calibration,
Continuum memory, belief networks, verification, explainability) — invest, harden, make
receipts the primary output; **Tier 2 essential infrastructure** (agents, API, storage,
CLI — maintain, prune the oversized server surface); **Tier 3 enterprise** (RBAC, audit,
billing, compliance — keep, don't differentiate); **Tier 4 connectors** (commodity —
sufficient as-is); **Tier 5 scope creep** (some workflow/RLM/blockchain/computer-use/
canvas — move to `contrib/` or shelve until customer demand). The standalone
`aragora-debate` library extracts Tier 1 so anyone can run an adversarial debate in ~10
lines with zero infra dependencies.

<a id="honest-current-state"></a>

### Honest current state *(docs/HONEST_ASSESSMENT.md, docs/GA_CHECKLIST.md)*

**Real and working:** the debate engine (genuine multi-agent debates against live LLM
APIs), multiple consensus modes, hollow-consensus detection, cryptographic receipts with
multi-format export, ELO rankings, Continuum memory, the fully-wired self-improvement
infrastructure, enterprise auth/encryption/key-rotation, and a very large test suite.
GA readiness is tracked at **~98%** (58/59 checklist items).

**Honest qualifications:** the B0 benchmark reports 100% verified-truth on the strict
set, with a separate, lower legacy full-corpus metric tracked alongside it (see
[`docs/status/B0_BENCHMARK_TRUTH_STATUS.md`](docs/status/B0_BENCHMARK_TRUTH_STATUS.md));
**SOC 2 Type II is not certified** (the one open GA
blocker is the external penetration test); semantic convergence degrades to TF-IDF/Jaccard
without the optional `sentence-transformers` dependency; "blockchain" receipts are SHA-256
hashing, *not* an on-chain immutable ledger; and practical real-time parallelism is 2–6
agents, not the larger allowlisted count — the value is heterogeneity. External positioning
should remain **narrower** than this roadmap and anchored to measured proof.

### North stars *(docs/CANONICAL_GOALS.md)*

1. A vague request becomes a reviewable, executable spec in minutes.
2. A bounded backlog runs unattended with clear receipts, stop conditions, and minimal rescue.
3. Any decision is inspectable from one-line summary down to evidence and provenance.
4. Shared memory improves future work without collapsing trust boundaries.
5. Important claims and cruxes stay linked to evidence, receipts, freshness, and delayed settlement.
6. Aragora evolves tool → teammate → foreman → chief of staff → org substrate on one coherent runtime.
7. Agents and humans participate as co-equal consumers with portable reputation tied to external truth oracles.
