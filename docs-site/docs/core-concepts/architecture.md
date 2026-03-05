---
title: Aragora Architecture
description: Aragora Architecture
---

# Aragora Architecture

> **Last Updated:** 2026-01-21


This document describes the high-level architecture of Aragora, the control plane for multi-agent vetted decisionmaking across organizational knowledge and channels. The multi-agent debate system is the engine that powers adversarial validation and decision assurance.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ARAGORA SYSTEM                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                           AGENT LAYER                                  │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐          │  │
│  │  │ Claude  │ │  Codex  │ │ Gemini  │ │  Grok   │ │ OpenAI  │          │  │
│  │  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘          │  │
│  │       │           │           │           │           │                │  │
│  │       └───────────┴─────┬─────┴───────────┴───────────┘                │  │
│  │                         ▼                                              │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │  │
│  │  │                    PersonaManager + EloSystem                    │  │  │
│  │  │            Traits, Expertise, Skill Ratings, Selection           │  │  │
│  │  └─────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                     ▼                                        │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                          DEBATE LAYER                                  │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │  │
│  │  │                    Arena (Orchestrator)                          │  │  │
│  │  │    Role Assignment • Round Management • Context Accumulation     │  │  │
│  │  └─────────────────────────────────────────────────────────────────┘  │  │
│  │                                 │                                      │  │
│  │  ┌──────────────┬───────────────┼───────────────┬──────────────────┐  │  │
│  │  ▼              ▼               ▼               ▼                  ▼  │  │
│  │  DebateGraph   DebateForker   Protocol    ConvergenceDetector  Tracer│  │
│  │  (DAG-based)  (Parallel)    (Sequential)    (Early Stop)      (Audit)│  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                     ▼                                        │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         REASONING LAYER                                │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐  │  │
│  │  │ClaimsKernel │ │BeliefNetwork│ │ProofExecutor│ │FormalVerifier   │  │  │
│  │  │(Structured) │ │(Probabilist)│ │(Executable) │ │(Z3/Lean)        │  │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────┘  │  │
│  │                                 │                                      │  │
│  │  ┌─────────────┐ ┌─────────────┐                                      │  │
│  │  │ Provenance  │ │ Reliability │                                      │  │
│  │  │ (Evidence)  │ │ (Confidence)│                                      │  │
│  │  └─────────────┘ └─────────────┘                                      │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                     ▼                                        │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                          MEMORY LAYER                                  │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐  │  │
│  │  │ContinuumMem │ │MemoryStream │ │ConsensusMem │ │SemanticRetriever│  │  │
│  │  │(Timescales) │ │(Per-Agent)  │ │(Topic Track)│ │(Embeddings)     │  │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────┘  │  │
│  │                                 │                                      │  │
│  │  ┌─────────────┐ ┌─────────────┐                                      │  │
│  │  │CritiqueStore│ │InsightStore │                                      │  │
│  │  │(Patterns)   │ │(Learning)   │                                      │  │
│  │  └─────────────┘ └─────────────┘                                      │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                     ▼                                        │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                        PERSISTENCE LAYER                               │  │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────────┐  │  │
│  │  │   SQLite    │ │  Supabase   │ │ Checkpoint  │ │    Replays      │  │  │
│  │  │ (Local DB)  │ │ (Cloud)     │ │ (Recovery)  │ │ (History)       │  │  │
│  │  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
aragora/
├── agents/                 # Agent implementations
│   ├── base.py            # Abstract Agent class
│   ├── cli_agents.py      # CLI tool wrappers (Claude, Codex, etc.)
│   ├── api_agents.py      # API-based agents (Anthropic, OpenAI, etc.)
│   ├── fallback.py        # QuotaFallbackMixin for provider failover
│   ├── streaming.py       # StreamingMixin for SSE parsing
│   ├── personas.py        # PersonaManager for agent traits
│   ├── laboratory.py      # PersonaLaboratory for A/B testing
│   ├── prober.py          # CapabilityProber for quality assurance
│   ├── grounded.py        # GroundedPersona (truth-based personas)
│   ├── relationships.py   # RelationshipTracker (agent relationships)
│   └── positions.py       # PositionTracker (position history)
│
├── debate/                 # Core debate infrastructure
│   ├── orchestrator.py    # Arena class (~1,500 LOC - coordinator role)
│   ├── arena_initializer.py # ArenaInitializer (extracted initialization)
│   ├── phase_executor.py  # PhaseExecutor (orchestrates all phases)
│   ├── context.py         # DebateContext (shared state across phases)
│   ├── memory_manager.py  # MemoryManager (extracted from orchestrator)
│   ├── prompt_builder.py  # PromptBuilder (extracted from orchestrator)
│   ├── convergence.py     # ConvergenceDetector (semantic similarity)
│   ├── graph.py           # DebateGraph (DAG-based debates)
│   ├── forking.py         # DebateForker (parallel branches)
│   ├── checkpoint.py      # CheckpointManager (recovery)
│   ├── breakpoints.py     # DebateBreakpointManager
│   └── phases/            # Phase executors (18 modules)
│       ├── context_init.py     # Phase 0: Context initialization
│       ├── proposal_phase.py   # Phase 1: Initial proposals
│       ├── debate_rounds.py    # Phase 2: Critique/revision loop
│       ├── consensus_phase.py  # Phase 3: Voting and consensus
│       ├── analytics_phase.py  # Phases 4-6: Metrics and insights
│       ├── feedback_phase.py   # Phase 7: ELO and memory updates
│       ├── vote_collector.py   # Vote collection logic
│       ├── vote_aggregator.py  # Vote aggregation
│       ├── vote_weighter.py    # Vote weight calculation
│       ├── weight_calculator.py# Reputation/calibration weights
│       ├── consensus_verification.py # Result verification
│       ├── roles_manager.py    # Role/stance assignment
│       ├── critique_generator.py  # Parallel critique generation
│       ├── revision_phase.py      # Parallel revision generation
│       ├── evidence_refresh.py    # Evidence refresh during rounds
│       └── context_compressor.py  # RLM context compression
│
├── reasoning/              # Logical reasoning components
│   ├── claims.py          # ClaimsKernel (structured claims)
│   ├── belief.py          # BeliefNetwork (probabilistic)
│   ├── crux_detector.py   # CruxDetector (pivotal claim identification)
│   ├── provenance.py      # ProvenanceManager
│   ├── reliability.py     # ReliabilityScorer
│   └── risk.py            # RiskRegister
│
├── verification/           # Verification subsystems
│   ├── executor.py        # ProofExecutor (code execution)
│   ├── formal.py          # FormalVerificationManager (Z3)
│   └── scenarios.py       # ScenarioMatrix
│
├── memory/                 # Memory systems
│   ├── store.py           # CritiqueStore (SQLite patterns)
│   ├── continuum/         # ContinuumMemory (timescales)
│   ├── stream.py          # MemoryStream (per-agent)
│   ├── consensus.py       # ConsensusMemory (topic tracking)
│   └── embeddings.py      # SemanticRetriever
│
├── evolution/              # Self-improvement
│   ├── prompts.py         # PromptEvolver
│   └── meta.py            # MetaLearner
│
├── connectors/             # External data sources
│   ├── base.py            # BaseConnector protocol
│   ├── local_docs.py      # LocalDocsConnector
│   ├── github.py          # GitHubConnector
│   ├── web.py             # WebConnector
│   ├── youtube_uploader.py# YouTubeUploaderConnector (OAuth 2.0)
│   └── twitter_poster.py  # TwitterPosterConnector (OAuth 1.0a)
│
├── maintenance/            # System maintenance utilities
│   └── db_maintenance.py  # DatabaseMaintenance (WAL, VACUUM)
│
├── monitoring/             # System monitoring
│   └── simple_observer.py # SimpleObserver (agent failure tracking)
│
├── resilience.py          # CircuitBreaker for agent failure handling
│
├── visualization/          # Debate visualization
│   ├── mapper.py          # ArgumentCartographer
│   └── exporter.py        # Graph export utilities
│
├── live/                   # Live dashboard (Next.js)
│   ├── src/               # React components
│   └── public/            # Static assets
│
├── server/                 # WebSocket/HTTP server
│   ├── unified_server.py  # Unified server (3,000+ API operations)
│   ├── handlers/          # Request handlers by domain
│   │   ├── base.py        # BaseHandler, ttl_cache decorator
│   │   ├── debates.py     # Debate CRUD and exports
│   │   ├── agents.py      # Agent profiles and rankings
│   │   ├── analytics.py   # System analytics
│   │   └── ...            # 41 handler modules
│   └── stream/            # Streaming infrastructure (refactored)
│       ├── servers.py     # WebSocket server classes
│       ├── broadcaster.py # Event broadcasting
│       ├── state_manager.py # Connection state
│       ├── loop_manager.py  # Loop lifecycle
│       ├── message_handlers.py # Message routing
│       └── serializers.py # Event serialization
│
├── rlm/                   # Recursive Language Model integration
│   ├── factory.py         # RLM factory and registry
│   ├── bridge.py          # AragoraRLM bridge (debate context access)
│   ├── streaming_mixin.py # Streaming methods (query_stream, compress_stream)
│   ├── debate_adapter.py  # Debate subsystem adapter
│   ├── knowledge_adapter.py # Knowledge Mound adapter
│   └── hierarchy_cache.py # Hierarchical caching
│
├── client/                # Python SDK client
│   ├── client.py          # AragoraClient (HTTP/WebSocket)
│   └── resources/         # API resource modules
│       ├── gauntlet.py    # GauntletAPI
│       ├── graph_debates.py # GraphDebatesAPI
│       ├── matrix_debates.py # MatrixDebatesAPI
│       └── replay.py      # ReplayAPI
│
├── ops/                   # Operational tooling
│   ├── __init__.py        # Module exports
│   └── deployment_validator.py # Runtime validation checks
│       ├── DeploymentValidator  # Environment, storage, DB, Redis checks
│       ├── validate_deployment() # Async full validation
│       └── quick_health_check() # Sync startup check
│
├── core_types.py          # Core types (Message, Critique, Vote, etc.)
└── __init__.py            # Package exports

scripts/
├── nomic_loop.py          # Main nomic loop implementation
└── run_nomic_with_stream.py  # Streaming wrapper

docs/
├── FEATURES.md            # Detailed feature documentation
├── NOMIC_LOOP.md          # Nomic loop documentation
└── ARCHITECTURE.md        # This file
```

## Data Flow

### Standard Debate Flow

```
1. Environment Setup
   ├── Task definition
   ├── Agent selection (AgentSelector)
   └── Protocol configuration

2. Proposal Phase
   ├── Each agent generates initial proposal
   └── Proposals stored as Messages

3. Critique Phase (per round)
   ├── Agents critique each other's proposals
   ├── Critiques have severity scores (0-1)
   └── ArgumentCartographer builds graph

4. Revision Phase
   ├── Proposers incorporate critiques
   ├── ConvergenceDetector checks similarity
   └── Early stop if converged

5. Voting Phase
   ├── Agents vote on best proposal
   ├── Votes weighted by Elo rating
   └── Confidence scores recorded

6. Consensus Phase
   ├── Judge synthesizes final answer
   ├── Dissenting views preserved
   └── DebateResult created

7. Learning Phase
   ├── CritiqueStore records patterns
   ├── InsightExtractor extracts lessons
   ├── PromptEvolver updates prompts
   └── EloSystem updates ratings
```

### Nomic Loop Flow

```
1. Context Gathering (Phase 0)
   ├── All agents read codebase
   ├── LocalDocsConnector provides evidence
   └── Genesis analysis (optional)

2. Proposal (Phase 1)
   ├── Agents propose improvements
   ├── Proposals structured with impact/complexity
   └── ProvenanceManager tracks sources

3. Debate (Phase 2)
   ├── Arena orchestrates critique rounds
   ├── DebateGraph for complex disagreements
   └── DebateForker for parallel exploration

4. Voting (Phase 3)
   ├── Elo-weighted votes
   ├── MetaCritiqueAnalyzer evaluates process
   └── RiskRegister tracks low-consensus items

5. Implementation (Phase 4)
   ├── Winning agent implements via CLI
   ├── Changes sandboxed to approved files
   └── CheckpointManager saves state

6. Verification (Phase 5)
   ├── Syntax check (py_compile)
   ├── Import check (import aragora)
   └── Test suite (pytest)

7. Commit (Phase 6)
   ├── Auto-commit if verification passes
   ├── ReplayRecorder saves cycle
   └── Cycle repeats
```

## Component Interactions

### Memory Integration

```
┌─────────────────────────────────────────────────────────────────┐
│                      MEMORY INTEGRATION                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Before Debate:                                                  │
│  ├── SemanticRetriever: Find similar past critiques             │
│  ├── ConsensusMemory: Check topic status (settled/contested)    │
│  └── CritiqueStore: Retrieve relevant patterns                  │
│                                                                  │
│  During Debate:                                                  │
│  ├── MemoryStream: Agent-specific context                       │
│  ├── ContinuumMemory: Store novel insights                      │
│  └── ProvenanceManager: Track evidence chains                   │
│                                                                  │
│  After Debate:                                                   │
│  ├── InsightExtractor: Extract winning patterns                 │
│  ├── SemanticRetriever: Store critique embeddings               │
│  └── ConsensusMemory: Update topic status                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Agent Evolution

```
┌─────────────────────────────────────────────────────────────────┐
│                      AGENT EVOLUTION                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Structured Thinking Protocols (per-agent cognition)            │
│  ├── Claude:  EXPLORE → PLAN → REASON → PROPOSE                 │
│  ├── Codex:   TRACE → ANALYZE → DESIGN → VALIDATE               │
│  ├── Gemini:  EXPLORE → ENVISION → REASON → PROPOSE             │
│  └── Grok:    DIVERGE → CONNECT → SYNTHESIZE → GROUND           │
│                                                                  │
│  PersonaManager                                                  │
│  ├── Trait storage (expertise, personality)                     │
│  ├── Success tracking by domain                                 │
│  └── Balanced/aggressive/defensive stance                       │
│                                                                  │
│  PersonaLaboratory                                               │
│  ├── A/B testing: Control vs variant personas                   │
│  ├── Emergent trait detection from success patterns             │
│  └── Cross-pollination between agents                           │
│                                                                  │
│  PromptEvolver                                                   │
│  ├── Track prompt → outcome correlations                        │
│  ├── Evolve prompts based on success rate                       │
│  └── Preserve winning prompt elements                           │
│                                                                  │
│  EloSystem                                                       │
│  ├── Skill ratings updated after each debate                    │
│  ├── Domain-specific ratings                                    │
│  └── Used for vote weighting and team selection                 │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Extension Points

### Adding New Agents

1. Create wrapper in `aragora/agents/cli_agents.py`
2. Implement the `Agent` protocol from `aragora/core_types.py`
3. Register in the agent factory

```python
class MyAgent(Agent):
    async def generate(self, prompt: str, context: list[Message] = None) -> str:
        # Call your LLM
        pass

    async def critique(self, proposal: str, task: str, context: list[Message] = None) -> Critique:
        # Generate critique
        pass
```

### Adding New Connectors

1. Inherit from `BaseConnector` in `aragora/connectors/base.py`
2. Implement `search()` and `fetch()` methods
3. Register with ProvenanceManager for evidence tracking

```python
class MyConnector(BaseConnector):
    async def search(self, query: str, limit: int = 10) -> list[Evidence]:
        # Search your data source
        pass

    async def fetch(self, evidence_id: str) -> Evidence:
        # Fetch specific evidence
        pass
```

### Adding New Verification Backends

1. Implement the `FormalBackend` protocol in `aragora/verification/formal.py`
2. Register with FormalVerificationManager

```python
class MyBackend(FormalBackend):
    def verify(self, claim: str, proof: str) -> FormalProofResult:
        # Verify using your prover
        pass
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ARAGORA_DATA_DIR` | Base directory for runtime data | `.nomic` |
| `ARAGORA_DB_MODE` | Database layout: `legacy` or `consolidated` | `legacy` |
| `DATABASE_URL` | PostgreSQL connection string | None |
| `ARAGORA_NOMIC_DIR` | Legacy alias for data dir | `.nomic` |
| `SUPABASE_URL` | Supabase project URL | None |
| `SUPABASE_KEY` | Supabase anon key | None |
| `OPENAI_API_KEY` | OpenAI API key | None |
| `ANTHROPIC_API_KEY` | Anthropic API key | None |
| `GEMINI_API_KEY` | Gemini API key | None |
| `GOOGLE_API_KEY` | Alias for `GEMINI_API_KEY` | None |

### Feature Flags

Features degrade gracefully if dependencies are missing:

```python
try:
    from aragora.feature import FeatureClass
    FEATURE_AVAILABLE = True
except ImportError:
    FEATURE_AVAILABLE = False
```

### Protocol Flags (DebateProtocol)

Opt-in features controlled via protocol configuration:

| Flag | Description | Default |
|------|-------------|---------|
| `enable_calibration` | Record prediction accuracy for calibration curves | `False` |
| `enable_rhetorical_observer` | Passive commentary on debate dynamics | `False` |
| `enable_trickster` | Hollow consensus detection | `False` |
| `trickster_sensitivity` | Threshold for trickster challenges | `0.7` |
| `enable_breakpoints` | Human-in-the-loop intervention points | `False` |
| `role_rotation` | Cognitive role rotation (Heavy3-inspired) | `True` |
| `convergence_detection` | Semantic convergence auto-detection | `True` |
| `vote_grouping` | Merge semantically similar vote choices | `True` |

### ArenaConfig Options

Dependency injection via ArenaConfig:

| Option | Description | Default |
|--------|-------------|---------|
| `performance_monitor` | AgentPerformanceMonitor instance | `None` |
| `enable_performance_monitor` | Auto-create PerformanceMonitor | `False` |
| `enable_telemetry` | Prometheus/Blackbox emission | `False` |
| `use_airlock` | Wrap agents with AirlockProxy | `False` |
| `airlock_config` | Custom AirlockConfig | `None` |
| `population_manager` | Genesis PopulationManager | `None` |
| `auto_evolve` | Trigger evolution after debates (gated) | `False` |
| `breeding_threshold` | Min confidence for evolution | `0.8` |

Safety gates:
- Set `ARAGORA_ALLOW_AUTO_EVOLVE=1` to enable `auto_evolve`.
- Set `ARAGORA_ALLOW_PROMPT_EVOLVE=1` to enable prompt evolution.

## Performance Considerations

1. **Embedding Caching**: SemanticRetriever caches embeddings to avoid recomputation
2. **Checkpoint Intervals**: Configure based on debate length and failure risk
3. **Parallel Debate Branches**: DebateForker runs branches concurrently
4. **Connection Pooling**: Database connections are pooled for efficiency
5. **Lazy Loading**: Heavy components (Z3, embeddings) loaded on demand

## Recent Additions (Phase 3)

### Feature Flags System

Frontend and backend feature flags for gating experimental features:

```typescript
// Frontend: aragora/live/src/lib/featureFlags.ts
import { isFeatureEnabled, FEATURES } from '@/lib/featureFlags';

if (isFeatureEnabled('GRAPH_DEBATES')) {
  // Show graph debates UI
}
```

```python
# Backend: aragora/config/settings.py
from aragora.config.settings import feature_settings

if feature_settings.is_enabled("graph_debates"):
    # Enable graph debates endpoint
```

### MCP Server

Full Model Context Protocol implementation with 8 tools and 4 resource templates:

| Resource | Description |
|----------|-------------|
| `debate://\{id\}` | Access debate results |
| `agent://\{name\}/stats` | Agent statistics and ELO |
| `consensus://\{id\}` | Formal verification proofs |
| `trending://topics` | Pulse trending topics |

See [MCP_INTEGRATION.md](../guides/mcp-integration) for details.

### Nomic Loop Hardening

Pre-flight health checks before self-improvement cycles:

```bash
# Run pre-flight checks only
python scripts/nomic_loop.py preflight

# Full loop with automatic pre-flight
python scripts/nomic_loop.py run
```

Checks include: API key validation, disk space, database connectivity, protected file integrity, git repository state.

### Type Coverage

PEP 561 typed package marker (`aragora/py.typed`) and strict mypy configuration for core modules. See `pyproject.toml` for per-module type checking settings.

### Phase-Based Debate Execution

The debate engine uses a phase-based architecture for maintainability and testability:

```
Phase 0: Context Initialization
    └─→ Inject history, patterns, research context

Phase 1: Proposals
    └─→ Generate initial proposer responses

Phase 2: Debate Rounds
    └─→ Critique/revision loop with convergence detection

Phase 3: Consensus
    └─→ Voting, weight calculation, winner determination

Phases 4-6: Analytics
    └─→ Metrics, insights, verdict generation

Phase 7: Feedback
    └─→ ELO updates, persona refinement, memory persistence
```

Each phase is implemented as a separate class with an `async execute(ctx)` method. See [ADR-001](../analysis/adr/001-phase-based-debate-execution) for details.

## Architecture Decision Records

Key architectural decisions are documented in the [ADR directory](../analysis/adr):

| ADR | Decision |
|-----|----------|
| [001](../analysis/adr/001-phase-based-debate-execution) | Phase-based debate execution |
| [002](../analysis/adr/002-agent-fallback-openrouter) | Agent fallback via OpenRouter |
| [003](../analysis/adr/003-multi-tier-memory-system) | Multi-tier memory system |
| [004](../analysis/adr/004-incremental-type-safety) | Incremental type safety migration |
| [005](../analysis/adr/005-composition-over-inheritance) | Composition over inheritance for APIs |

## Debate Phase Flow (Mermaid)

```mermaid
flowchart TB
    subgraph init["Phase 0: Context Init"]
        A[Environment Setup] --> B[Fetch Knowledge Context]
        B --> C[Inject Belief Cruxes]
        C --> D[Build Agent Context]
    end

    subgraph proposal["Phase 1: Proposals"]
        E[Each Agent Generates Proposal] --> F[Store as Messages]
    end

    subgraph debate["Phase 2: Debate Rounds"]
        G[Critique Phase] --> H{Convergence?}
        H -->|No| I[Revision Phase]
        I --> J{Max Rounds?}
        J -->|No| G
        J -->|Yes| K[Exit Rounds]
        H -->|Yes| K
    end

    subgraph consensus["Phase 3: Consensus"]
        L[Collect Votes] --> M[Weight by ELO/Calibration]
        M --> N[Aggregate Results]
        N --> O{Consensus Mode}
        O -->|majority| P[Plurality Winner]
        O -->|unanimous| Q[All Agree Check]
        O -->|judge| R[Judge Synthesis]
        P --> S[Create DebateResult]
        Q --> S
        R --> S
    end

    subgraph analytics["Phases 4-6: Analytics"]
        T[Record Metrics] --> U[Extract Insights]
        U --> V[Generate Verdict]
        V --> W[Store Patterns]
    end

    subgraph feedback["Phase 7: Feedback"]
        X[Update ELO Ratings] --> Y[Refine Personas]
        Y --> Z[Persist to Memory]
        Z --> AA[Ingest to Knowledge Mound]
    end

    init --> proposal
    proposal --> debate
    debate --> consensus
    consensus --> analytics
    analytics --> feedback

    style init fill:#1a1a2e,stroke:#0f0
    style proposal fill:#1a1a2e,stroke:#0ff
    style debate fill:#1a1a2e,stroke:#ff0
    style consensus fill:#1a1a2e,stroke:#f0f
    style analytics fill:#1a1a2e,stroke:#f90
    style feedback fill:#1a1a2e,stroke:#09f
```

## Data Flow Diagram (Mermaid)

```mermaid
flowchart LR
    subgraph inputs["Inputs"]
        Task[Task/Question]
        Agents[Agent Pool]
        Config[Protocol Config]
    end

    subgraph memory["Memory Systems"]
        KM[Knowledge Mound]
        CM[Consensus Memory]
        Cont[Continuum Memory]
        Crit[Critique Store]
    end

    subgraph core["Debate Engine"]
        Arena[Arena Orchestrator]
        Phases[Phase Executor]
        Conv[Convergence Detector]
    end

    subgraph outputs["Outputs"]
        Result[Debate Result]
        Insights[Insights]
        ELO[ELO Updates]
    end

    Task --> Arena
    Agents --> Arena
    Config --> Arena

    KM -.->|context| Arena
    CM -.->|history| Arena
    Cont -.->|patterns| Arena

    Arena --> Phases
    Phases --> Conv
    Conv -->|early stop| Result
    Phases --> Result

    Result --> Insights
    Result --> ELO
    Result -.->|store| KM
    Insights -.->|store| Crit
    ELO -.->|update| Agents

    style inputs fill:#0d1117,stroke:#238636
    style memory fill:#0d1117,stroke:#1f6feb
    style core fill:#0d1117,stroke:#f78166
    style outputs fill:#0d1117,stroke:#a371f7
```

## Storage Architecture

Aragora supports multiple storage backends for horizontal scaling and persistence.

### Backend Selection

```
ARAGORA_DB_BACKEND=postgres  # or sqlite (default)
DATABASE_URL=postgresql://user:pass@host:5432/aragora
```

### PostgreSQL Store Implementations

| Store | Purpose | Tables |
|-------|---------|--------|
| `PostgresWebhookConfigStore` | Webhook configuration | `webhook_configs` |
| `PostgresIntegrationStore` | Chat platform configs | `integrations`, `user_id_mappings` |
| `PostgresGmailTokenStore` | OAuth token storage | `gmail_tokens` |
| `PostgresFindingWorkflowStore` | Audit workflow state | `finding_workflows` |
| `PostgresGauntletRunStore` | In-flight gauntlet runs | `gauntlet_runs` |
| `PostgresApprovalRequestStore` | Human approval requests | `approval_requests` |
| `PostgresJobQueueStore` | Background job queue | `job_queue` |
| `PostgresMarketplaceStore` | Template marketplace | `marketplace_items` |
| `PostgresTokenBlacklistStore` | JWT revocation | `token_blacklist` |
| `PostgresFederationRegistryStore` | Multi-region federation | `federation_nodes` |
| `PostgresGovernanceStore` | Decision governance | `governance_artifacts` |
| `PostgresUserStore` | User accounts | `users` |
| `PostgresWebhookStore` | Webhook events | `webhooks` |
| `PostgresConsensusMemory` | Topic consensus tracking | `consensus`, `dissent`, `verified_proofs` |
| `PostgresCritiqueStore` | Critique patterns | `debates`, `critiques`, `patterns`, `agent_reputation` |
| `PostgresContinuumMemory` | Multi-tier memory | `continuum_memory`, `tier_transitions` |
| `PostgresEloDatabase` | Agent skill ratings | `elo_ratings`, `tournaments`, `matches` |

### Database Migrations

```bash
# Initialize using Alembic (recommended for production)
python scripts/init_postgres_db.py --alembic

# Or run Alembic directly
alembic upgrade head

# Verify tables
python scripts/init_postgres_db.py --verify
```

### Transaction Safety

Critical operations use explicit transactions:
- `PostgresGovernanceStore.cleanup_old_records_async()` - Atomic multi-table cleanup
- `PostgresFederationRegistryStore.update_sync_status()` - Atomic counter increments

## Performance Characteristics

- **Debate latency**: 2-5 seconds per round (depends on agent response time)
- **Memory tiers**: Fast (1min TTL), Medium (1hr), Slow (1day), Glacial (1week)
- **Test coverage**: 38,000+ test functions across 1,100+ test files
- **Type safety**: 250+ modules in strict mypy mode
- **Source LOC**: 495,713 lines across 1,203 modules
- **Storage tests**: 468 tests covering all backends
