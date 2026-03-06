# Debate Module

Core debate orchestration engine for Aragora's multi-agent deliberation system.

## Overview

The debate module implements a propose-critique-revise consensus loop where 43 agent types across 10+ AI providers collaborate to reach defensible decisions. It supports configurable rounds, convergence detection, multiple consensus mechanisms, and checkpointing for pause/resume workflows.

## Quick Start

```python
from aragora.debate import Arena, DebateProtocol
from aragora import Environment

env = Environment(task="Design a rate limiter for our API")
protocol = DebateProtocol(rounds=9, consensus="hybrid")
arena = Arena(environment=env, agents=agents, protocol=protocol)
result = await arena.run()
```

### Using the Builder Pattern (Recommended)

```python
from aragora.debate import ArenaBuilder

arena = (ArenaBuilder()
    .with_environment(env)
    .with_agents(agents)
    .with_protocol(protocol)
    .with_knowledge(enable_knowledge_retrieval=True)
    .with_audit_trail(enable_receipt_generation=True)
    .build())

async with arena:
    result = await arena.run()
```

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator.py` | Arena class - main debate engine |
| `arena_config.py` | Type-safe configuration with 15 sub-config groups |
| `arena_builder.py` | Fluent builder pattern for Arena construction |
| `protocol.py` | DebateProtocol config, round phases, circuit breaker |
| `consensus.py` | ConsensusProof, claims, dissent tracking |
| `convergence.py` | Semantic similarity detection, early termination |
| `team_selector.py` | Agent selection by ELO, calibration, domain expertise |
| `judge_selector.py` | Judge/panel selection strategies |
| `memory_manager.py` | Multi-tier memory coordination |
| `prompt_builder.py` | Dynamic prompt construction with evidence injection |
| `phases/` | Extracted phase implementations |
| `checkpoint.py` | Debate pause/resume with multiple backends |

## Debate Flow

```
Arena.run()
│
├─ Phase 0: Context Initialization
│  ├─ Gather background evidence (knowledge mound, pulse)
│  ├─ Select agent team (ELO + calibration + domain)
│  └─ Assign cognitive roles (Analyst, Skeptic, Lateral, etc.)
│
├─ Phase 1: Initial Proposals (parallel)
│  └─ All agents generate proposals concurrently
│
├─ Phases 2-7: Debate Rounds
│  ├─ Round 2 (Skeptic): Challenge proposals
│  ├─ Round 3 (Lateral): Alternative perspectives
│  ├─ Round 4 (Devil's Advocate): Strong opposition
│  ├─ Round 5 (Integrator): Connect insights
│  ├─ Round 6 (Quality Challenger): Cross-examination
│  ├─ Round 7 (Synthesizer): Final synthesis
│  └─ Per-round: Convergence check (early termination)
│
├─ Phase 8a: Voting
│  └─ Weighted votes (ELO + calibration + consistency)
│
├─ Phase 8b: Consensus
│  ├─ Judge selection and verdict
│  └─ ConsensusProof generation
│
└─ Feedback Phase
   └─ ELO updates, persona refinement, calibration tracking
```

## Configuration

### DebateProtocol

```python
protocol = DebateProtocol(
    rounds=9,                           # Number of debate rounds
    consensus_threshold=0.66,           # Majority vote threshold
    convergence_threshold=0.85,         # Early termination similarity
    enable_early_termination=True,      # Allow semantic convergence exit
    judge_selection="elo_ranked",       # Judge selection strategy
    consensus_mechanism="hybrid",       # majority|judge|weighted|hybrid
    agent_timeout_seconds=30,           # Per-agent response timeout
    debate_timeout_seconds=300,         # Total debate timeout
    use_circuit_breaker=True,           # Resilience proxy for agents
)
```

### ArenaConfig Sub-groups

| Config | Purpose |
|--------|---------|
| `DebateConfig` | Rounds, thresholds, timeouts |
| `MemoryConfig` | Knowledge retrieval, continuum memory |
| `AgentConfig` | Team size, airlock, hierarchy |
| `HookConfig` | Event hooks, YAML hooks |
| `TrackingConfig` | ELO, persona, flip detection |
| `KnowledgeMoundConfig` | Retrieval, ingestion, extraction |
| `MemoryCoordinationConfig` | Atomic writes, rollback policy |
| `PerformanceFeedbackConfig` | Selection feedback loop |
| `AuditTrailConfig` | Receipt generation, provenance |

## Consensus Mechanisms

| Mechanism | Description |
|-----------|-------------|
| `majority` | Simple majority vote wins |
| `judge` | Single judge renders verdict |
| `weighted` | Votes weighted by ELO/calibration |
| `hybrid` | Combination of voting + judge adjudication |
| `supermajority` | Requires 2/3 agreement |
| `unanimous` | All agents must agree |

## Advanced Features

### Checkpointing

```python
# Save debate state
checkpoint_id = await arena.save_checkpoint(
    debate_id="debate-123",
    label="after-round-3"
)

# Resume from checkpoint
resumed = await arena.restore_from_checkpoint(debate_id, checkpoint_id)
result = await arena.run()
```

### Graph/DAG Debates

```python
from aragora.debate import DebateGraph, GraphDebateOrchestrator

graph = DebateGraph()
graph.add_node("proposal", "Initial proposal phase")
graph.add_node("critique", "Critique round")
graph.add_edge("proposal", "critique")

orchestrator = GraphDebateOrchestrator(arena, graph)
result = await orchestrator.run()
```

### Counterfactual Exploration

```python
from aragora.debate import CounterfactualOrchestrator

orchestrator = CounterfactualOrchestrator(arena)
branch_results = await orchestrator.explore_counterfactual(
    constraint="agent-claude disabled",
    max_branches=3
)
```

## Convergence Detection

Three-tier fallback for semantic similarity:
1. **SentenceTransformer** - Neural embeddings (preferred)
2. **TF-IDF** - Statistical term frequency
3. **Jaccard** - Set-based token overlap

Early termination triggers when proposal similarity exceeds `convergence_threshold` (default 0.85).

## Team Selection

Multi-dimensional scoring combines:
- **ELO rating** - Historical performance
- **Calibration score** - Prediction accuracy
- **Domain expertise** - Topic-specific skills
- **Delegation strategy** - Workload balancing

## Related Modules

- `aragora.agents` - Agent implementations
- `aragora.memory` - Learning and persistence
- `aragora.knowledge` - Knowledge Mound integration
- `aragora.ranking` - ELO system
