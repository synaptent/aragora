# Aragora -- Extended Reference

*Comprehensive technical reference for the Decision Integrity Platform. For the concise overview, see the [README](../README.md).*

---

## Table of Contents

- [Five Pillars](#five-pillars)
- [Debate Engine (Dialectic Roots)](#debate-engine-dialectic-roots)
- [Core Workflows](#core-workflows)
- [Architecture](#architecture)
- [Programmatic Usage](#programmatic-usage)
- [Implemented Features (3,000+ Modules)](#implemented-features-3000-modules)
- [Prerequisites](#prerequisites)
- [Deployment](#deployment)
- [API Endpoints](#api-endpoints)
- [Security](#security)
- [Self-Improvement (Nomic Loop)](#self-improvement-nomic-loop)
- [Inspiration and Citations](#inspiration-and-citations)

---

## Five Pillars

Aragora is built on five architectural commitments.

### 1. SMB-Ready, Enterprise-Grade

Aragora works for a 5-person startup on day one and scales to regulated enterprise without rearchitecting. Enterprise features -- OIDC/SAML SSO, MFA, AES-256-GCM encryption, multi-tenant isolation, RBAC with 7 roles and 50+ permissions, SOC 2 / GDPR / HIPAA compliance frameworks -- are built in, not bolted on. Security hardening (rate limiting, SSRF protection, path traversal guards, input validation, audit trails) is the default, not a premium tier.

### 2. Leading-Edge Memory and Context

Single agents lose context. Aragora's 4-tier Continuum Memory (fast / medium / slow / glacial) and Knowledge Mound with 0 registered adapters give every debate access to institutional history, cross-session learning, and evidence provenance. The RLM (Recursive Language Models) system compresses and structures context to reduce prompt bloat, enabling debates that sustain coherence across long multi-round sessions and large document sets where individual models would degrade.

### 3. Extensible and Modular

Connectors for Slack, Teams, Discord, Telegram, WhatsApp, email, voice, Kafka, RabbitMQ, GitHub, Jira, Salesforce, healthcare HL7/FHIR, and dozens more. SDKs in Python and TypeScript (140 namespaces). 3,000+ API operations across 2,900+ paths and 260+ WebSocket event types. OpenClaw integration for portable agent governance. A workflow engine with DAG execution and 60+ templates. A marketplace for agent personas, debate templates, and workflow patterns. Aragora adapts to your stack.

### 4. Multi-Agent Robustness

Different models have different blind spots. Aragora runs Claude, GPT, Gemini, Grok, Mistral, DeepSeek, Qwen, Kimi, and local models in structured Propose / Critique / Revise debates with configurable consensus (majority, unanimous, judge-based). ELO rankings track agent performance. Calibration scoring measures prediction accuracy. The Trickster detects hollow consensus. The result: outputs that are more robust, less biased, and higher quality than any single model, with a complete dissent trail showing where the models disagreed and why.

### 5. Self-Healing and Self-Extending

The Nomic Loop is Aragora's autonomous self-improvement system: agents debate improvements to the codebase, design solutions, implement code, run tests, and verify changes -- with human approval gates and automatic rollback on failure. Red-team mode stress-tests the platform's own specs. The Gauntlet runs adversarial attacks against proposed changes. The system hardens itself.

---

## Debate Engine (Dialectic Roots)

The dialectic framing is the **internal engine**; users get adversarial validation outputs (decision receipts, risk heatmaps, dissent trails). This section is optional background for those interested in the theoretical foundation.

Aragora's debate engine draws from Hegelian dialectics:

| Dialectical Concept | Aragora Implementation |
|---------------------|------------------------|
| **Thesis > Antithesis > Synthesis** | Propose > Critique > Revise loop |
| **Aufhebung** (sublation) | Judge synthesizes best elements, preserving value while transcending limitations |
| **Contradiction as motor** | Critiques (disagreement) drive improvement, not consensus-seeking |
| **Negation of negation** | Proposal > Critique (negation) > Revision (higher unity) |
| **Truth as totality** | No single agent has complete truth; it emerges from multi-perspectival synthesis |

The **Nomic Loop** (self-modifying rules) mirrors this by debating and refining its own processes. It is experimental -- run in a sandbox with human review before any auto-commit.

### Debate Protocol (Stress-Test Engine)

Each session follows thesis > antithesis > synthesis:

1. **Round 0: Thesis (Initial Proposals)**
   - Proposer agents generate initial responses to the task
   - Multiple perspectives on the same problem

2. **Rounds 1-N: Antithesis (Critique and Revise)**
   - Agents critique each other's proposals (productive negation)
   - Identify issues with severity scores (0-1)
   - Provide concrete suggestions
   - Proposers revise, incorporating valid critiques (negation of negation)

3. **Synthesis (Consensus Phase)**
   - All agents vote on best proposal
   - Judge synthesizes best elements from competing proposals (*Aufhebung*)
   - Judge selection is randomized or voted to prevent systematic bias
   - Final answer transcends individual limitations

### Algorithm Documentation

Deep-dive documentation for core debate algorithms:
- **[Consensus Detection](algorithms/CONSENSUS.md)** -- Multi-agent consensus mechanisms and proof generation
- **[Convergence Detection](algorithms/CONVERGENCE.md)** -- Semantic similarity for debate convergence
- **[ELO and Calibration](algorithms/ELO_CALIBRATION.md)** -- Agent skill rating and team selection

See [algorithms/README.md](algorithms/README.md) for the full algorithm reference.

---

## Core Workflows

### Gauntlet Mode -- Adversarial Stress Testing

Stress-test specifications, architectures, and policies before they ship:

```bash
# Test a specification for security vulnerabilities
aragora gauntlet spec.md --input-type spec --profile quick

# GDPR compliance audit
aragora gauntlet policy.yaml --input-type policy --persona gdpr

# Full adversarial stress test with HTML report
aragora gauntlet architecture.md --profile thorough --output report.html
```

| Attack Type | What It Tests |
|-------------|--------------|
| **Red Team** | Security holes, injection points, auth bypasses |
| **Devil's Advocate** | Logic flaws, hidden assumptions, edge cases |
| **Scaling Critic** | Performance bottlenecks, SPOF, thundering herd |
| **Compliance** | GDPR, HIPAA, SOC 2, AI Act violations |

**Decision receipts** provide cryptographic audit trails for every finding, ready for regulatory review.

CI decision gate:

```bash
aragora gauntlet architecture.md --profile thorough --output receipt.html
```

GitHub Action: `.github/workflows/aragora-gauntlet.yml`

See [GAUNTLET.md](./debate/GAUNTLET.md) for full documentation and [AGENT_SELECTION.md](./debate/AGENT_SELECTION.md) for agent recommendations.

### AI Red Team Code Review

Get **unanimous AI consensus** on your pull requests. When 3 independent AI models agree on an issue, you know it's worth fixing.

```bash
# Review a PR
git diff main | aragora review

# Review a GitHub PR URL
aragora review https://github.com/owner/repo/pull/123

# Try without API keys
aragora review --demo
```

**What you get:**

| Section | What It Means |
|---------|--------------|
| **Unanimous Issues** | All AI models agree -- high confidence, fix first |
| **Split Opinions** | Models disagree -- see the tradeoff, you decide |
| **Risk Areas** | Low confidence -- manual review recommended |

Example output:
```
### Unanimous Issues
> All AI models agree - address these first
- SQL injection in search_users() - user input concatenated into query
- Missing input validation on file upload endpoint

### Split Opinions
| Topic | For | Against |
|-------|-----|---------|
| Add request rate limiting | Claude, GPT-4 | Gemini |
```

**GitHub Actions**: Automatically review every PR with the included workflow.

### Structured Debates

```python
from aragora import Arena, Environment, DebateProtocol
from aragora.agents import create_agent

# Create heterogeneous agents (API-backed)
agents = [
    create_agent("anthropic-api", name="claude_proposer", role="proposer"),
    create_agent("openai-api", name="openai_critic", role="critic"),
    create_agent("gemini", name="gemini_synth", role="synthesizer"),
]

# Define task
env = Environment(
    task="Design a distributed cache with LRU eviction",
    max_rounds=3,
)

# Configure debate
protocol = DebateProtocol(
    rounds=3,
    consensus="majority",
)

# Run with memory
from aragora.memory import CritiqueStore
memory = CritiqueStore("debates.db")
arena = Arena(env, agents, protocol, memory)
result = await arena.run()

print(result.final_answer)
print(f"Consensus: {result.consensus_reached} ({result.confidence:.0%})")
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         ARAGORA FRAMEWORK                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                 AGENT LAYER (30+ Agent Types)             │   │
│  │  Claude | GPT | Gemini | Grok | Mistral | DeepSeek | Qwen │   │
│  │              + Kimi, Yi, Local Models (Ollama)             │   │
│  └───────────────────────────┬──────────────────────────────┘   │
│                               ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    DEBATE ENGINE                          │   │
│  │  • 9-round structured protocol (Propose > Critique > Syn) │   │
│  │  • Graph debates with branching | Matrix debates           │   │
│  │  • Consensus detection | Convergence | Forking             │   │
│  └───────────────────────────┬──────────────────────────────┘   │
│                               ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    KNOWLEDGE LAYER                        │   │
│  │  • Belief networks with Bayesian propagation              │   │
│  │  • Claims kernel with typed relationships                 │   │
│  │  • Evidence provenance with hash chains                   │   │
│  │  • Knowledge Mound (0 registered adapters) + Semantic search  │   │
│  └───────────────────────────┬──────────────────────────────┘   │
│                               ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                  MEMORY SYSTEM (4 tiers)                  │   │
│  │  Fast (1min) > Medium (1hr) > Slow (1d) > Glacial (1wk)  │   │
│  │  • Surprise-based learning | Consolidation scoring        │   │
│  │  • Cross-session pattern extraction | RLM context mgmt    │   │
│  └───────────────────────────┬──────────────────────────────┘   │
│                               ▼                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    OUTPUT LAYER                            │   │
│  │  Decision Receipts | Risk Heatmaps | Dissent Trails       │   │
│  │  Proofs | Explainability | Channel Routing                │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Directory Structure

```
aragora/
├── debate/           # Core debate orchestration (210+ modules)
│   ├── orchestrator.py     # Arena class -- main debate engine
│   ├── phases/             # Extracted phase implementations
│   ├── team_selector.py    # Agent team selection (ELO + calibration)
│   ├── memory_manager.py   # Memory coordination
│   ├── prompt_builder.py   # Prompt construction
│   ├── consensus.py        # Consensus detection and proofs
│   ├── convergence.py      # Semantic similarity detection
│   ├── trickster.py        # Hollow consensus detection
│   ├── topology.py         # Adaptive topology (sparse/all-to-all/ring)
│   └── calibration.py      # Agent confidence calibration
├── agents/           # Agent implementations (18+)
│   ├── cli_agents.py       # CLI agents (claude, codex, gemini, grok)
│   ├── api_agents/         # API agents directory
│   │   ├── anthropic.py    # Anthropic API (Claude)
│   │   ├── openai.py       # OpenAI API (GPT)
│   │   ├── gemini.py       # Google Gemini
│   │   ├── mistral.py      # Mistral (Large, Codestral)
│   │   ├── grok.py         # xAI Grok
│   │   ├── openrouter.py   # OpenRouter (DeepSeek, Llama, Qwen, Yi, Kimi)
│   │   ├── ollama.py       # Local Ollama models
│   │   └── lm_studio.py    # Local LM Studio models
│   ├── fallback.py         # OpenRouter fallback on quota errors
│   └── airlock.py          # AirlockProxy for agent resilience
├── memory/           # Learning and persistence
│   ├── continuum/          # Multi-tier memory (fast/medium/slow/glacial)
│   ├── consensus.py        # Historical debate outcomes
│   ├── coordinator.py      # Atomic cross-system memory writes
│   ├── supermemory.py      # Cross-session external memory
│   └── embeddings.py       # Semantic embedding for retrieval
├── knowledge/        # Unified knowledge management
│   ├── bridges.py          # KnowledgeBridgeHub, MetaLearner, Evidence bridges
│   └── mound/              # KnowledgeMound (0 registered adapters, 4,300+ tests)
│       ├── adapters/       # Belief, Consensus, ELO, Evidence, OpenClaw, etc.
│       ├── semantic.py     # Vector embedding-based search
│       ├── federation.py   # Multi-region sync
│       ├── contradictions.py # Conflict detection
│       └── resilience.py   # Retry, health monitoring, cache invalidation
├── reasoning/        # Formal reasoning
│   ├── belief.py           # Belief network with Bayesian propagation
│   ├── provenance.py       # Cryptographic evidence chains
│   └── claims.py           # Structured typed claims
├── gauntlet/         # Adversarial stress testing
│   ├── runner.py           # Test execution
│   ├── receipts.py         # SHA-256 cryptographic audit trails
│   ├── findings.py         # Findings management
│   ├── defense.py          # Attack/defend cycles
│   └── personas/           # GDPR, SOC2, HIPAA, PCI-DSS, AI Act, NIST CSF
├── server/           # HTTP/WebSocket API (2,000+ operations, 190+ event types)
│   ├── unified_server.py   # Main server
│   ├── handlers/           # HTTP endpoint handlers
│   ├── stream/             # WebSocket streaming (26 modules)
│   ├── debate_origin.py    # Bidirectional chat routing
│   └── result_router.py    # Result delivery to originating platform
├── connectors/       # External integrations
│   ├── chat/               # Slack, Discord, Teams, Telegram, WhatsApp
│   ├── enterprise/         # SharePoint, Confluence, Notion, Salesforce, databases
│   │   ├── streaming/      # Kafka, RabbitMQ
│   │   └── healthcare/     # HL7, FHIR
│   └── advertising/        # Twitter Ads, TikTok Ads
├── auth/             # Authentication (OIDC, SAML, SCIM)
├── tenancy/          # Multi-tenant isolation
├── rbac/             # Role-based access (7 roles, 50+ permissions)
├── compliance/       # SOC 2, GDPR, HIPAA
├── privacy/          # Anonymization, consent, retention, deletion
├── security/         # Encryption, key rotation, SSRF protection
├── observability/    # Prometheus, OpenTelemetry, SLOs
├── control_plane/    # Agent registry, scheduler, health, policies (1,500+ tests)
├── workflow/         # DAG-based automation (60+ templates)
├── nomic/            # Self-improvement (MetaPlanner, BranchCoordinator)
├── rlm/              # Recursive Language Models
├── pulse/            # Trending topics (1,000+ tests)
├── explainability/   # Decision explanations, counterfactuals
├── verification/     # Z3/Lean formal verification
├── genesis/          # Fractal debates, agent evolution
├── sandbox/          # Docker-based safe execution
├── backup/           # Disaster recovery
├── pipeline/         # Decision-to-PR generation
├── marketplace/      # Agent/debate/workflow templates
├── mcp/              # Model Context Protocol server
└── cli/              # Command-line interface
```

**Scale:** 3,000+ Python modules | 208,000+ tests across 4,000+ test files | 185 TypeScript SDK namespaces

---

## Programmatic Usage

### Basic Debate

```python
import asyncio
from aragora.agents import create_agent
from aragora.debate import Arena, DebateProtocol
from aragora.core import Environment
from aragora.memory import CritiqueStore

# Create heterogeneous agents (API-backed)
agents = [
    create_agent("anthropic-api", name="claude_proposer", role="proposer"),
    create_agent("openai-api", name="openai_critic", role="critic"),
    create_agent("gemini", name="gemini_synth", role="synthesizer"),
]

# Define task
env = Environment(
    task="Design a distributed cache with LRU eviction",
    max_rounds=3,
)

# Configure debate
protocol = DebateProtocol(
    rounds=3,
    consensus="majority",
)

# Run with memory
memory = CritiqueStore("debates.db")
arena = Arena(env, agents, protocol, memory)
result = asyncio.run(arena.run())

print(result.final_answer)
print(f"Consensus: {result.consensus_reached} ({result.confidence:.0%})")
```

### Python SDK

```python
from aragora.client import AragoraClient

# Synchronous
client = AragoraClient(base_url="http://localhost:8080")
debate = client.debates.run(task="Should we adopt microservices?")
print(f"Consensus: {debate.consensus.reached}")

# Asynchronous
async with AragoraClient(base_url="http://localhost:8080") as client:
    debate = await client.debates.run_async(task="Design a rate limiter")
    receipt = await client.gauntlet.run_and_wait(input_content="spec.md")
```

See [SDK_GUIDE.md](SDK_GUIDE.md) for full API reference.

### Chat Integrations

Post debate notifications to Discord and Slack:

```python
from aragora.integrations.discord import DiscordConfig, DiscordIntegration

discord = DiscordIntegration(DiscordConfig(
    webhook_url="https://discord.com/api/webhooks/..."
))
await discord.send_consensus_reached(debate_id, topic, "majority", result)
```

See [INTEGRATIONS.md](./integrations/INTEGRATIONS.md) for setup instructions.

### Enable Knowledge Mound

```python
from aragora.debate.arena_config import ArenaConfig

config = ArenaConfig(
    enable_knowledge_mound=True,
    enable_km_belief_sync=True,
    enable_coordinated_writes=True,
)
arena = Arena.from_config(env, agents, protocol, config)
```

### Run with Enterprise Features

```python
from aragora.tenancy import TenantContext
from aragora.rbac.decorators import require_permission

async with TenantContext(tenant_id="acme-corp"):
    result = await arena.run()
```

### CLI Commands

```bash
# Run a decision stress-test
aragora ask "Your task here" --agents anthropic-api,openai-api --rounds 3

# View statistics
aragora stats

# View learned patterns
aragora patterns --type security --limit 20

# Run the API + WebSocket server
aragora serve

# System health check
aragora doctor

# Export for training
aragora export --format jsonl > training_data.jsonl

# Build codebase context (RLM-ready)
aragora context --preview --rlm
```

### SDK Packages

| Package | Purpose | Installation |
|---------|---------|--------------|
| **`aragora`** | Full control plane (server, CLI, SDK) | `pip install aragora` |
| **`aragora-sdk`** | Official Python SDK (remote HTTP API; sync + async + streaming) | `pip install aragora-sdk` |
| **`@aragora/sdk`** | TypeScript/Node.js SDK (140 namespaces) | `npm install @aragora/sdk` |

**Deprecated packages** (avoid for new integrations):
- `aragora-client` -- Legacy async client. Migrate to `aragora-sdk`.
- `aragora-js` -- Use `@aragora/sdk` instead
- `@aragora/client` -- Use `@aragora/sdk` instead

See [SDK_COMPARISON.md](SDK_COMPARISON.md) for detailed feature comparison.

---

## Implemented Features (3,000+ Modules)

Aragora has evolved through 21+ phases of self-improvement, with the Nomic Loop debating and implementing each feature.

### Phase 1: Foundation

| Feature | Description |
|---------|-------------|
| **ContinuumMemory** | Multi-timescale learning (fast/medium/slow tiers) |
| **ReplayRecorder** | Cycle event recording for analysis |
| **MetaLearner** | Self-tuning hyperparameters |
| **IntrospectionAPI** | Agent self-awareness and reflection |
| **ArgumentCartographer** | Real-time debate graph visualization |
| **WebhookDispatcher** | External event notifications |

### Phase 2: Learning

| Feature | Description |
|---------|-------------|
| **ConsensusMemory** | Track settled vs contested topics across debates |
| **InsightExtractor** | Post-debate pattern learning and extraction |

### Phase 3: Evidence and Resilience

| Feature | Description |
|---------|-------------|
| **MemoryStream** | Per-agent persistent memory |
| **LocalDocsConnector** | Evidence grounding from codebase |
| **CounterfactualOrchestrator** | Deadlock resolution via forking |
| **CapabilityProber** | Agent quality assurance testing |
| **DebateTemplates** | Structured debate formats |

### Phase 4: Agent Evolution

| Feature | Description |
|---------|-------------|
| **PersonaManager** | Agent traits and expertise evolution |
| **PromptEvolver** | Prompt evolution from winning patterns |
| **Tournament** | Periodic competitive benchmarking |

### Phase 5: Intelligence

| Feature | Description |
|---------|-------------|
| **ConvergenceDetector** | Early stopping via semantic convergence |
| **MetaCritiqueAnalyzer** | Debate process feedback and recommendations |
| **EloSystem** | Persistent agent skill tracking |
| **AgentSelector** | Smart agent team selection |
| **RiskRegister** | Low-consensus risk tracking |

### Phase 6: Formal Reasoning

| Feature | Description |
|---------|-------------|
| **ClaimsKernel** | Structured typed claims with evidence tracking |
| **ProvenanceManager** | Cryptographic evidence chain integrity |
| **BeliefNetwork** | Probabilistic reasoning over uncertain claims |
| **ProofExecutor** | Executable verification of claims |
| **ScenarioMatrix** | Robustness testing across scenarios |

### Phase 7: Reliability and Audit

| Feature | Description |
|---------|-------------|
| **EnhancedProvenanceManager** | Staleness detection for living documents |
| **CheckpointManager** | Pause/resume and crash recovery |
| **BreakpointManager** | Human intervention breakpoints |
| **ReliabilityScorer** | Claim confidence scoring |
| **DebateTracer** | Audit logs and deterministic replay |

### Phase 8: Advanced Debates

| Feature | Description |
|---------|-------------|
| **PersonaLaboratory** | A/B testing, emergent traits, cross-pollination |
| **SemanticRetriever** | Pattern matching for similar critiques |
| **FormalVerificationManager** | Z3 theorem proving for logical claims |
| **DebateGraph** | DAG-based debates for complex disagreements |
| **DebateForker** | Parallel branch exploration |

### Phase 9: Truth Grounding

| Feature | Description |
|---------|-------------|
| **FlipDetector** | Semantic position reversal detection |
| **CalibrationTracker** | Prediction accuracy tracking (Brier score) |
| **GroundedPersonaManager** | Evidence-linked persona synthesis |
| **PositionTracker** | Agent position history with verification |

### Phase 10: Thread-Safe Audience Participation

| Feature | Description |
|---------|-------------|
| **ArenaMailbox** | Thread-safe event queue for live interaction |
| **LoopScoping** | Session-isolated streaming events |

### Phase 11: Operational Modes

| Feature | Description |
|---------|-------------|
| **OperationalModes** | Agent tool configuration switching |
| **CapabilityProber** | Agent vulnerability testing |
| **RedTeamMode** | Adversarial analysis of proposals |

### Enterprise Features (Production-Ready)

| Feature | Description |
|---------|-------------|
| **Multi-Tenancy** | Tenant isolation with quotas and cost tracking |
| **OIDC/SAML SSO** | Enterprise single sign-on integration |
| **MFA Support** | TOTP/HOTP multi-factor authentication |
| **AES-256 Encryption** | Encryption at rest with key rotation |
| **Audit Logging** | Tamper-evident immutable audit trail |
| **SOC 2 Compliance** | Controls mapping and evidence documentation |
| **Prometheus Metrics** | 14+ custom metrics with Grafana dashboards |
| **OpenTelemetry** | Distributed tracing support |
| **Rate Limiting** | IP, token, and endpoint-based limits |
| **Connection Pooling** | Adaptive pool with health monitoring |
| **SCIM 2.0** | Automated user/group provisioning |
| **RBAC v2** | 7 roles, 50+ permissions, decorator-based enforcement |
| **Backup/DR** | Incremental backups, retention policies, disaster recovery |
| **Control Plane** | Agent registry, task scheduler, health monitoring, policy governance (1,500+ tests) |

See [ENTERPRISE_FEATURES.md](ENTERPRISE_FEATURES.md) for complete enterprise capabilities.

---

## Prerequisites

**API Agents (Recommended):** Set your API keys -- no additional tools needed:

```bash
# Set one or more API keys in .env or environment
ANTHROPIC_API_KEY=sk-ant-xxx    # For Claude (Opus 4.5, Sonnet 4)
OPENAI_API_KEY=sk-xxx           # For GPT models
GEMINI_API_KEY=AIzaSy...        # For Gemini 2.5
XAI_API_KEY=xai-xxx             # For Grok 4
MISTRAL_API_KEY=xxx             # For Mistral Large, Codestral
OPENROUTER_API_KEY=sk-or-xxx    # For DeepSeek, Qwen, Yi (multi-model access)
KIMI_API_KEY=xxx                # For Kimi (Moonshot, China perspective)
```

**CLI Agents (Optional):** For local CLI-based agents, install the corresponding tools:

```bash
npm install -g @anthropic-ai/claude-code   # Claude CLI
npm install -g @openai/codex               # OpenAI Codex CLI
npm install -g @google/gemini-cli          # Google Gemini CLI
npm install -g grok-cli                    # xAI Grok CLI
```

### Supported Entry Points

Stable interfaces (recommended):
- `aragora gauntlet` for decision stress-tests (CLI)
- `aragora ask` for exploratory debates (CLI)
- `aragora serve` for the unified API + WebSocket server
- `python -m aragora` as a CLI alias
- `python -m aragora.server` for the server in scripts/automation

Experimental/research (may change; use in a sandbox):
- `scripts/nomic_loop.py` and `scripts/run_nomic_with_stream.py`
- `aragora improve` (self-improvement mode)

---

## Deployment

### AWS Lightsail (Production)

```bash
# Deploy to Lightsail
./deploy/lightsail-setup.sh

# The server runs at api.aragora.ai via Cloudflare Tunnel
# Frontend at aragora.ai via Cloudflare Pages
```

Configuration:
- **Instance**: Ubuntu 22.04, nano_3_0 ($5/month)
- **HTTP API**: Port 8080
- **WebSocket**: Port 8765 (ws://host:8765 or ws://host:8765/ws)
- **Tunnel**: Cloudflare Tunnel proxies api.aragora.ai

### Local Development

```bash
aragora serve --api-port 8080 --ws-port 8765
```

---

## API Endpoints

The server exposes 3,000+ API operations across 2,900+ paths. Key categories:

| Category | Description |
|----------|-------------|
| `/api/debates/*` | Debate CRUD, forking, export, search |
| `/api/gauntlet/*` | Adversarial stress-testing, receipts, heatmaps |
| `/api/agent/{name}/*` | Agent profiles, calibration, consistency, performance |
| `/api/v1/memory/*` | Multi-tier memory (continuum), search, analytics (legacy `/api/memory/*` supported) |
| `/api/auth/*` | Registration, login, OAuth, API keys |
| `/api/billing/*` | Stripe subscriptions, usage, checkout |
| `/api/tournaments/*` | Competitive brackets, standings, matches |
| `/api/verify/*` | Formal verification with Z3 solver |
| `WS /ws` | Real-time streaming (see `WEBSOCKET_EVENTS.md`) |

**Full API reference**: [API_ENDPOINTS.md](./api/API_ENDPOINTS.md) (auto-generated)
**OpenAPI spec**: `GET /api/openapi` or `GET /api/openapi.yaml`
**Interactive docs**: `GET /api/docs` (Swagger UI)

### WebSocket Events

```typescript
// Event types streamed via WebSocket
type EventType =
  | "debate_start" | "round_start" | "agent_message"
  | "critique" | "vote" | "consensus" | "debate_end"
  | "token_start" | "token_delta" | "token_end"
  | "loop_list" | "audience_metrics" | "grounded_verdict"
  | "gauntlet_start" | "gauntlet_verdict" | "gauntlet_complete"
```

See `WEBSOCKET_EVENTS.md` for the full list and payloads.

---

## Security

Aragora implements defense-in-depth security:

- **Webhook Verification**: Ed25519 signatures for Discord and Slack
- **Rate Limiting**: Thread-safe, multi-layer (IP, token, endpoint) with configurable limits
- **Input Validation**: API parameters validated and capped; content-length enforcement
- **Multipart Limits**: Max 100 parts prevents DoS via form flooding
- **Path Traversal Protection**: Static file serving validates paths against base directory
- **CORS**: Origin allowlist (no wildcards)
- **Security Headers**: X-Frame-Options, X-Content-Type-Options, X-XSS-Protection, Referrer-Policy, CSP, HSTS
- **Error Sanitization**: Internal errors don't leak stack traces; API keys redacted from responses
- **Process Cleanup**: CLI agents properly kill and await zombie processes
- **Backpressure Control**: Stream event queues capped to prevent memory exhaustion
- **WebSocket Limits**: Max message size 64KB, ping/pong (30s/10s), debate timeouts
- **Thread Safety**: Double-checked locking for shared executor initialization
- **Secure Client IDs**: Cryptographically random WebSocket identifiers
- **JSON Parse Timeout**: 5-second timeout prevents CPU-bound DoS
- **Upload Rate Limiting**: IP-based limits (5/min, 30/hour) prevent storage DoS
- **SSRF Protection**: Server-side request forgery prevention
- **AES-256-GCM**: Field-level encryption with key derivation and rotation
- **Cloud KMS**: AWS KMS, Azure Key Vault, GCP Cloud KMS support

Configure security via environment variables:
```bash
export ARAGORA_API_TOKEN="your-secret-token"
export ARAGORA_ALLOWED_ORIGINS="https://aragora.ai,https://www.aragora.ai"
export ARAGORA_TOKEN_TTL=3600
export ARAGORA_WS_MAX_MESSAGE_SIZE=65536
```

### Compliance and Governance

| Document | Purpose |
|----------|---------|
| [SOC 2 Compliance](./enterprise/COMPLIANCE.md) | SOC 2 Type II controls and evidence |
| [Data Classification](./enterprise/DATA_CLASSIFICATION.md) | Data handling policies and sensitivity levels |
| [Incident Response](./deployment/INCIDENT_RESPONSE.md) | Incident playbooks and escalation procedures |
| [Privacy Policy](./enterprise/PRIVACY_POLICY.md) | Data collection and retention policies |
| [Nomic Governance](./enterprise/NOMIC_GOVERNANCE.md) | Autonomous loop safety controls |

---

## Self-Improvement (Nomic Loop)

Aragora's self-improvement system is an autonomous cycle where agents debate and implement improvements to the codebase. Always run in a sandbox with human review.

### Nomic Loop Phases

| Phase | Name | Purpose |
|-------|------|---------|
| 0 | Context | Gather codebase understanding |
| 1 | Debate | Agents propose improvements |
| 2 | Design | Architecture planning |
| 3 | Implement | Code generation (Codex/Claude) |
| 4 | Verify | Tests and checks |

### Running the Nomic Loop

```bash
# Run the nomic loop with streaming
python scripts/run_nomic_with_stream.py run --cycles 3

# Goal-driven self-improvement with human approval
python scripts/self_develop.py --goal "Improve test coverage" --require-approval

# Dry run to preview decomposition
python scripts/self_develop.py --goal "Refactor dashboard" --dry-run

# Run individual phases
python scripts/nomic_staged.py debate
python scripts/nomic_staged.py design
python scripts/nomic_staged.py implement
python scripts/nomic_staged.py verify
```

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| MetaPlanner | `aragora/nomic/meta_planner.py` | Debate-driven goal prioritization |
| BranchCoordinator | `aragora/nomic/branch_coordinator.py` | Parallel branch management |
| TaskDecomposer | `aragora/nomic/task_decomposer.py` | Break complex tasks into subtasks |
| AutonomousOrchestrator | `aragora/nomic/autonomous_orchestrator.py` | End-to-end orchestration |

### Self-Improvement Learning

Aragora learns from successful stress-tests through a structured feedback loop:

1. **Pattern Storage**: Successful critique > fix patterns indexed by issue type
2. **Retrieval**: Future debates retrieve relevant patterns (learning from history)
3. **Prompt Evolution**: Agent system prompts evolve based on what works
4. **Nomic Loop**: The system debates *changes to itself*, making its own rules an object of dialectical inquiry
5. **Export**: Patterns can be exported for fine-tuning

```python
# Retrieve successful patterns
from aragora.memory import CritiqueStore

store = CritiqueStore("debates.db")
security_patterns = store.retrieve_patterns(issue_type="security", min_success=3)

for pattern in security_patterns:
    print(f"Issue: {pattern.issue_text}")
    print(f"Fix: {pattern.suggestion_text}")
    print(f"Success rate: {pattern.success_rate:.0%}")
```

Safety features: automatic backups, protected file checksums, rollback on failure, human approval for dangerous changes.

---

## Channels and Integrations

### Chat Platforms

| Channel | Features |
|---|---|
| **Slack** | Bot + OAuth, webhooks, evidence collection |
| **Microsoft Teams** | Bot + OAuth, meetings, JWT verification |
| **Discord** | Interactions API, guilds, channels, DMs, Ed25519 verification |
| **Telegram** | Bot API with TTS support |
| **WhatsApp** | Business API with voice notes |
| **Google Chat** | Spaces, messages, JWT verification |

### Enterprise Streaming

| System | Features |
|---|---|
| **Apache Kafka** | Consumer groups, offset tracking, JSON/Avro/Protobuf |
| **RabbitMQ** | Exchange/queue binding, DLQ, bidirectional |

### Data Sources

GitHub, GitLab, ArXiv, Wikipedia, SEC filings, HackerNews, Reddit, Twitter/X, SharePoint, Confluence, Notion, Salesforce, HubSpot, Zendesk, Jira, PostgreSQL (CDC), MongoDB, MySQL, SQL Server, Snowflake, HL7v2, FHIR.

### Advertising and Marketing

Twitter/X Ads, TikTok Ads, Mailchimp, Klaviyo, Segment CDP.

### Bidirectional Chat Routing

Results automatically route to the originating channel. Debate Origin Tracking records where each debate started, and the Result Router delivers outputs back to that platform -- including TTS for voice channels.

---

## Inspiration and Citations

### Foundational Inspiration

- **[Stanford Generative Agents](https://github.com/joonspk-research/generative_agents)** -- Memory + reflection architecture
- **[ChatArena](https://github.com/chatarena/chatarena)** -- Game environments for multi-agent interaction
- **[LLM Multi-Agent Debate](https://github.com/composable-models/llm_multiagent_debate)** -- ICML 2024 consensus mechanisms
- **[UniversalBackrooms](https://github.com/scottviteri/UniversalBackrooms)** -- Multi-model infinite conversations
- **[Project Sid](https://github.com/altera-al/project-sid)** -- Emergent civilization with 1000+ agents

### Borrowed Patterns (MIT/Apache Licensed)

| Project | What We Borrowed | License |
|---------|------------------|---------|
| **[ai-counsel](https://github.com/AI-Counsel/ai-counsel)** | Semantic convergence detection (3-tier fallback: SentenceTransformer > TF-IDF > Jaccard), vote option grouping, per-agent similarity tracking | MIT |
| **[DebateLLM](https://github.com/Tsinghua-MARS-Lab/DebateLLM)** | Agreement intensity modulation (0-10 scale), asymmetric debate roles, judge-based termination | Apache 2.0 |
| **[CAMEL-AI](https://github.com/camel-ai/camel)** | Multi-agent orchestration patterns, critic agent design | Apache 2.0 |
| **[CrewAI](https://github.com/joaomdmoura/crewAI)** | Agent role and task patterns | MIT |
| **[AIDO](https://github.com/aido-research/aido)** | Consensus variance tracking, reputation-weighted voting | MIT |
| **[claude-flow](https://github.com/ruvnet/claude-flow)** | Adaptive topology switching, YAML agent configuration, hooks system | MIT |
| **[ccswarm](https://github.com/nwiizo/ccswarm)** | Delegation strategy patterns, channel-based orchestration | MIT |
| **[claude-code-by-agents](https://github.com/baryhuang/claude-code-by-agents)** | Cooperative cancellation tokens with linked parent-child hierarchy | MIT |
| **[claude-squad](https://github.com/smtg-ai/claude-squad)** | Session lifecycle state machine concepts (patterns only, reimplemented) | AGPL-3.0 (patterns only) |
| **[claude-agent-sdk-demos](https://github.com/anthropics/claude-agent-sdk-demos)** | Official Anthropic subagent patterns, parallel execution idioms | MIT |

See implementations in:
- `aragora/debate/convergence.py` -- Semantic convergence detection
- `aragora/debate/orchestrator.py` -- Orchestration patterns
- `aragora/debate/topology.py` -- Adaptive topology (claude-flow)
- `aragora/debate/session.py` -- Session lifecycle (claude-squad patterns)
- `aragora/debate/cancellation.py` -- Cancellation tokens (claude-code-by-agents)

See the full attribution table in [CREDITS.md](./reference/CREDITS.md).

---

## Roadmap

- [x] **Phase 1-21**: Core framework with 65+ integrated features
- [x] **Position Flip Detection**: Track agent position reversals and consistency scores
- [x] **Hybrid Model Architecture**: Gemini=Designer, Claude=Implementer, Codex=Verifier
- [x] **Security Hardening**: API key header auth, rate limiting, input validation
- [x] **Feature Integration**: PerformanceMonitor, CalibrationTracker, Airlock, Telemetry
- [x] **Multi-Provider Agents**: Mistral, DeepSeek, Qwen, Yi, Kimi via direct API and OpenRouter
- [x] **Knowledge Mound Phase A2**: Contradiction detection, confidence decay, RBAC governance
- [x] **OpenClaw Integration**: Portable agent governance via dedicated handlers
- [ ] **LeanBackend**: Lean 4 theorem proving integration
- [ ] **Emergent Society**: Society simulation (a la Project Sid)
- [ ] **Multi-Codebase**: Cross-repository coordination

---

## Related Documentation

| Document | Purpose |
|----------|---------|
| [README](../README.md) | Concise project overview with five pillars |
| [CLAUDE.md](../CLAUDE.md) | Development guide for AI assistants |
| [STATUS.md](STATUS.md) | Detailed feature implementation status |
| [FEATURE_DISCOVERY.md](FEATURE_DISCOVERY.md) | Complete feature catalog (180+) |
| [COMMERCIAL_OVERVIEW.md](COMMERCIAL_OVERVIEW.md) | Commercial positioning |
| [ENTERPRISE_FEATURES.md](ENTERPRISE_FEATURES.md) | Enterprise capabilities reference |
| [API_REFERENCE.md](./api/API_REFERENCE.md) | REST API documentation |
| [SDK_GUIDE.md](SDK_GUIDE.md) | SDK usage guide |
| [GAUNTLET.md](./debate/GAUNTLET.md) | Gauntlet stress-testing guide |
| [INDEX.md](INDEX.md) | Full documentation index |

---

## Contributing

Contributions welcome. Areas of interest:

- Additional agent backends (Cohere, Inflection, Reka)
- Debate visualization enhancements
- Benchmark datasets for agent evaluation
- Prompt engineering for better critiques
- Self-improvement mechanism research
- Lean 4 theorem proving integration

## License

MIT

---

*The name "aragora" evokes the Greek agora -- the public assembly where citizens debated and reached collective decisions through reasoned discourse.*

*Special thanks to the researchers behind Generative Agents, ChatArena, and Project Sid for pioneering this space, and to Hegel for the insight that contradiction is not a flaw to avoid but the engine of development.*
