# Cross-Pollination Architecture

Aragora's cross-pollination system enables different subsystems to communicate and share data through a unified event-driven architecture. This creates powerful synergies where improvements in one area automatically benefit others.

## Quick Start

Cross-pollination features are **enabled by default**. No configuration required.

### CLI Usage

```bash
# Run a debate with all cross-pollination features (default)
aragora ask "What is the best programming language?"

# Disable specific features if needed
aragora ask "..." --no-elo-weighting       # Disable ELO-based vote weights
aragora ask "..." --no-calibration         # Disable calibration tracking
aragora ask "..." --no-evidence-weighting  # Disable evidence quality scoring
aragora ask "..." --no-trending            # Disable Pulse trending topics
```

### Verify Feature Health

Check the cross-pollination health endpoint:

```bash
curl http://localhost:8080/api/health/cross-pollination
```

Response shows status of each feature:
```json
{
  "status": "healthy",
  "active_features": 6,
  "features": {
    "elo_weighting": {"healthy": true, "status": "active"},
    "calibration": {"healthy": true, "status": "active"},
    "evidence_quality": {"healthy": true, "status": "active"},
    "rlm_caching": {"healthy": true, "status": "active", "hit_rate": 0.72},
    "knowledge_mound": {"healthy": true, "status": "active"},
    "trending_topics": {"healthy": true, "status": "active"}
  }
}
```

### Monitoring

Import the Grafana dashboard from `deploy/grafana/dashboards/cross-pollination.json` to visualize:
- RLM cache hit rates
- Calibration error (ECE)
- Voting accuracy
- ELO adjustments
- Evidence quality bonuses

See [OBSERVABILITY.md](../observability/OBSERVABILITY.md#cross-pollination-metrics) for Prometheus metrics.

## Overview

```
Event Flow:
                                    ┌──────────────────────────────────┐
                                    │    CrossSubscriberManager        │
                                    │                                  │
┌─────────────────┐                 │  ┌────────────────────────────┐ │
│ Arena (Debates) │─────Events────▶ │  │ memory_to_rlm              │ │
└─────────────────┘                 │  │ elo_to_debate              │ │
                                    │  │ knowledge_to_memory        │ │
┌─────────────────┐                 │  │ calibration_to_agent       │ │
│ ContinuumMemory │─────Events────▶ │  │ evidence_to_insight        │ │
└─────────────────┘                 │  │ mound_to_memory            │ │
                                    │  └────────────────────────────┘ │
┌─────────────────┐                 └──────────────────────────────────┘
│ KnowledgeMound  │─────Events────▶
└─────────────────┘

┌─────────────────┐
│ ELO System      │─────Events────▶
└─────────────────┘
```

## Key Components

### 1. CrossSubscriberManager

Central hub for cross-subsystem event routing.

```python
from aragora.events.cross_subscribers import get_cross_subscriber_manager

manager = get_cross_subscriber_manager()

# Register a custom handler
@manager.subscribe(StreamEventType.MEMORY_STORED)
def on_memory_stored(event):
    print(f"Memory stored: {event.data}")

# Or register manually
manager.register("my_handler", StreamEventType.AGENT_ELO_UPDATED, my_handler_fn)
```

### 2. Arena Event Bridge

Connects Arena's internal EventBus to the CrossSubscriberManager.

```python
from aragora.debate.arena_bridge import ArenaEventBridge, create_arena_bridge

# Automatic - enabled by default via ArenaBuilder
arena = ArenaBuilder(env, agents).build()

# Manual setup
bridge = create_arena_bridge(arena.event_bus)
bridge.connect_to_cross_subscribers()
```

### 3. Evidence-Provenance Bridge

Links evidence snippets to belief claims for provenance tracking.

```python
from aragora.reasoning.evidence_bridge import get_evidence_bridge

bridge = get_evidence_bridge()

# Register evidence
bridge.register_evidence(evidence_snippet, claim_id="claim_001")

# Link to claims with relevance scoring
bridge.link_to_claim(evidence_id, claim_id, relevance=0.9)

# Create evidence chains
chain = bridge.create_evidence_chain("chain_001", [evidence1, evidence2])
```

### 4. RLM Training Integration

Automatically collects debate trajectories for reinforcement learning.

```python
from aragora.rlm.debate_integration import (
    get_debate_trajectory_collector,
    create_training_hook,
)

# Get collected trajectories
collector = get_debate_trajectory_collector()
trajectories = collector.get_trajectories(limit=100)

# Hook is auto-installed via ArenaBuilder (enabled by default)
arena = ArenaBuilder(env, agents).with_rlm_training(True).build()
```

## Event Types

The system supports these cross-pollination event types:

| Event Type | Source | Description |
|------------|--------|-------------|
| `MEMORY_STORED` | ContinuumMemory | New memory item stored |
| `MEMORY_RETRIEVED` | ContinuumMemory | Memory item accessed |
| `AGENT_ELO_UPDATED` | EloSystem | Agent rating changed |
| `AGENT_CALIBRATION_CHANGED` | CalibrationTracker | Agent calibration updated |
| `AGENT_FALLBACK_TRIGGERED` | Agent | Fallback provider activated |
| `KNOWLEDGE_INDEXED` | KnowledgeMound | New knowledge indexed |
| `KNOWLEDGE_QUERIED` | KnowledgeMound | Knowledge queried |
| `MOUND_UPDATED` | KnowledgeMound | Mound structure changed |

## Built-in Handlers

### memory_to_rlm
Records memory access patterns to inform RLM compression strategies.

### elo_to_debate
Updates AgentPool weights based on ELO changes.

### knowledge_to_memory
Syncs high-confidence knowledge nodes to ContinuumMemory.

### calibration_to_agent
Updates agent confidence weights based on calibration data.

### evidence_to_insight
Stores high-confidence evidence as insights.

### mound_to_memory
Handles knowledge mound structure changes.

## Configuration

Settings can be controlled via environment variables or code:

```python
from aragora.config.settings import get_settings

settings = get_settings()

# Check integration settings
print(settings.integration.rlm_training_enabled)      # True
print(settings.integration.knowledge_mound_enabled)   # True
print(settings.integration.cross_subscribers_enabled) # True
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_INTEGRATION_RLM_TRAINING` | `true` | Enable RLM training collection |
| `ARAGORA_INTEGRATION_KNOWLEDGE_MOUND` | `true` | Enable Knowledge Mound integration |
| `ARAGORA_INTEGRATION_KNOWLEDGE_THRESHOLD` | `0.85` | Min confidence for ingestion |
| `ARAGORA_INTEGRATION_CROSS_SUBSCRIBERS` | `true` | Enable cross-subscribers |
| `ARAGORA_INTEGRATION_ARENA_BRIDGE` | `true` | Enable Arena event bridge |
| `ARAGORA_INTEGRATION_AUTO_REVALIDATION` | `false` | Enable auto revalidation |
| `ARAGORA_INTEGRATION_EVIDENCE_BRIDGE` | `true` | Enable evidence bridge |

## Observability API

Monitor cross-pollination status via HTTP endpoints:

```bash
# Get subscriber statistics
curl http://localhost:8080/api/cross-pollination/stats

# List all registered subscribers
curl http://localhost:8080/api/cross-pollination/subscribers

# Get Arena event bridge status
curl http://localhost:8080/api/cross-pollination/bridge

# Reset statistics (for testing)
curl -X POST http://localhost:8080/api/cross-pollination/reset
```

## Knowledge Revalidation

Automatic staleness detection and revalidation via debates:

```python
from aragora.knowledge.mound import RevalidationScheduler

scheduler = RevalidationScheduler(
    knowledge_mound=mound,
    staleness_threshold=0.7,
    check_interval_seconds=3600,
    revalidation_method="debate",  # or "evidence", "expert"
)

# Start background monitoring
await scheduler.start()

# Manual check
task_ids = await scheduler.check_and_schedule_revalidations()
```

## Best Practices

1. **Enable default integrations** - The defaults are optimized for most use cases
2. **Monitor via observability endpoints** - Check `/api/cross-pollination/stats` regularly
3. **Use ArenaBuilder** - It automatically wires up all integrations
4. **Set appropriate thresholds** - Higher thresholds = less noise, lower thresholds = more data
5. **Consider memory impact** - Disable unused integrations in resource-constrained environments

## Troubleshooting

### Events not being delivered

1. Check if cross-subscribers are enabled: `settings.integration.cross_subscribers_enabled`
2. Verify the Arena event bridge is connected: `GET /api/cross-pollination/bridge`
3. Check for handler errors in logs

### High memory usage

1. Reduce trajectory collection: `.with_rlm_training(False)` in ArenaBuilder
2. Increase knowledge ingestion threshold to reduce stored items
3. Clear collected data periodically: `collector.clear()`

### Slow debate performance

1. Disable auto-revalidation: `ARAGORA_INTEGRATION_AUTO_REVALIDATION=false`
2. Use async handlers for expensive operations
3. Consider sampling events instead of processing all

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ARAGORA SYSTEM                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐ │
│  │   Arena     │    │  Memory     │    │  Knowledge  │    │    ELO      │ │
│  │ (Debates)   │    │ (Continuum) │    │   (Mound)   │    │  (Rankings) │ │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘ │
│         │                  │                  │                  │        │
│         │    Events        │    Events        │    Events        │        │
│         └──────────────────┴──────────────────┴──────────────────┘        │
│                                    │                                       │
│                                    ▼                                       │
│         ┌──────────────────────────────────────────────────────────┐      │
│         │              CrossSubscriberManager                       │      │
│         │                                                           │      │
│         │   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │      │
│         │   │memory_to │ │ elo_to   │ │knowledge │ │evidence_ │   │      │
│         │   │   _rlm   │ │ _debate  │ │_to_memory│ │to_insight│   │      │
│         │   └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘   │      │
│         └────────┼────────────┼────────────┼────────────┼──────────┘      │
│                  │            │            │            │                  │
│         ┌────────▼────┐ ┌─────▼─────┐ ┌────▼────┐ ┌─────▼─────┐          │
│         │ RLM Trainer │ │ AgentPool │ │ Memory  │ │  Insight  │          │
│         │(Trajectories│ │ (Weights) │ │  Sync   │ │  Store    │          │
│         └─────────────┘ └───────────┘ └─────────┘ └───────────┘          │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 9: Cross-Pollination Bridges

In addition to the event-driven architecture, Aragora includes 7 specialized bridges that connect subsystems for self-improving feedback loops.

### Bridge Overview

| Tier | Bridge | Source → Target | Purpose |
|------|--------|-----------------|---------|
| 1 | PerformanceRouterBridge | PerformanceMonitor → AgentRouter | Performance-aware routing |
| 1 | OutcomeComplexityBridge | OutcomeTracker → ComplexityGovernor | Adaptive complexity budgets |
| 1 | AnalyticsSelectionBridge | AnalyticsCoordinator → TeamSelector | Analytics-driven team selection |
| 2 | NoveltySelectionBridge | NoveltyTracker → SelectionFeedbackLoop | Novelty-based selection |
| 2 | RelationshipBiasBridge | RelationshipTracker → BiasMitigation | Echo chamber detection |
| 3 | RLMSelectionBridge | RLMBridge → SelectionFeedbackLoop | RLM efficiency optimization |
| 3 | CalibrationCostBridge | CalibrationTracker → CostTracker | Cost-efficient selection |

### Auto-Initialization

Bridges auto-initialize in `SubsystemCoordinator` when source subsystems are available:

```python
from aragora.debate.subsystem_coordinator import SubsystemCoordinator

coordinator = SubsystemCoordinator(
    performance_monitor=monitor,
    relationship_tracker=tracker,
    calibration_tracker=calibration,
    enable_performance_router=True,
    enable_relationship_bias=True,
    enable_calibration_cost=True,
)

# Check active bridges
status = coordinator.get_status()
print(f"Active bridges: {status['active_bridges_count']}")
```

### Configuration via ArenaConfig

All bridges support configuration through `ArenaConfig`:

```python
from aragora.debate.arena_config import ArenaConfig

config = ArenaConfig(
    # Performance Router Bridge
    enable_performance_router=True,
    performance_router_latency_weight=0.3,
    performance_router_quality_weight=0.4,

    # Relationship Bias Bridge
    enable_relationship_bias=True,
    relationship_bias_alliance_threshold=0.7,
    relationship_bias_vote_penalty=0.3,

    # Calibration Cost Bridge
    enable_calibration_cost=True,
    calibration_cost_min_predictions=20,
)
```

### Key Bridge Features

#### RelationshipBiasBridge - Echo Chamber Detection

```python
from aragora.debate.relationship_bias_bridge import create_relationship_bias_bridge

bridge = create_relationship_bias_bridge(relationship_tracker=tracker)

# Assess team echo chamber risk
risk = bridge.compute_team_echo_risk(["claude", "gpt", "gemini"])
if risk.recommendation == "high_risk":
    print(f"High alliance pairs: {risk.high_alliance_pairs}")

# Get diverse team candidates
candidates = bridge.get_diverse_team_candidates(
    available_agents=all_agents,
    team_size=3,
)
```

#### CalibrationCostBridge - Cost Optimization

```python
from aragora.billing.calibration_cost_bridge import create_calibration_cost_bridge

bridge = create_calibration_cost_bridge(
    calibration_tracker=tracker,
    cost_tracker=cost_tracker,
)

# Get cost-efficient recommendation
agent = bridge.recommend_cost_efficient_agent(
    available_agents=["claude", "gpt", "gemini"],
    min_accuracy=0.7,
)

# Budget-aware selection
agents = bridge.get_budget_aware_selection(
    available_agents=all_agents,
    budget_remaining=Decimal("0.50"),
)
```

### Testing

```bash
# Run bridge unit tests
pytest tests/bridges/ -v

# Run Phase 9 integration tests
pytest tests/integration/test_phase9_bridges.py -v
```

### Bridge Locations

| Bridge | Location |
|--------|----------|
| PerformanceRouterBridge | `aragora/debate/performance_router_bridge.py` |
| OutcomeComplexityBridge | `aragora/debate/outcome_complexity_bridge.py` |
| AnalyticsSelectionBridge | `aragora/debate/analytics_selection_bridge.py` |
| NoveltySelectionBridge | `aragora/debate/novelty_selection_bridge.py` |
| RelationshipBiasBridge | `aragora/debate/relationship_bias_bridge.py` |
| RLMSelectionBridge | `aragora/rlm/rlm_selection_bridge.py` |
| CalibrationCostBridge | `aragora/billing/calibration_cost_bridge.py` |

## Pulse Integration

Pulse (trending topics) integrates with debates to provide real-time context.

### Features

- **Trending Topic Injection**: Automatically inject trending topics into debate prompts
- **Quality Filtering**: Only high-quality, relevant topics are included
- **Source Weighting**: Credibility-scored sources (GitHub > Reliable News > Social Media)
- **Freshness Scoring**: Time-decayed relevance with configurable half-life

### Configuration

```python
from aragora.pulse.ingestor import PulseManager

manager = PulseManager(
    enable_hackernews=True,
    enable_reddit=True,
    enable_twitter=False,  # Requires API key
    quality_threshold=0.6,
    freshness_half_life_hours=24,
)

# Fetch trending for debate context
topics = await manager.get_trending_topics(limit=5)
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_PULSE_ENABLED` | `true` | Enable Pulse integration |
| `ARAGORA_PULSE_QUALITY_THRESHOLD` | `0.6` | Minimum quality score |
| `ARAGORA_PULSE_FRESHNESS_HOURS` | `24` | Freshness half-life |
| `HACKERNEWS_ENABLED` | `true` | Enable HackerNews ingestor |
| `REDDIT_ENABLED` | `true` | Enable Reddit ingestor |
| `TWITTER_API_KEY` | - | Twitter API key (optional) |

### Testing

```bash
# Run Pulse unit tests
pytest tests/pulse/ -v

# Run Pulse integration tests
pytest tests/ -k pulse -v
```
