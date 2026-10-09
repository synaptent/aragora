# Memory Tier Operations Guide

This guide covers operational aspects of the Continuum Memory System for SREs and operators. For developer documentation, see [MEMORY_STRATEGY.md](MEMORY_STRATEGY.md).

## Developer Quick Start

### Basic Usage

```python
from aragora.memory.continuum import ContinuumMemory
from aragora.memory.tier_manager import MemoryTier

# Initialize the memory system
memory = ContinuumMemory()

# Store a memory with automatic tier selection
await memory.store(
    content="Agent X performs well on technical debates",
    importance=0.7,
    domain="agent_performance",
    metadata={"agent_id": "agent_x", "topic": "technical"},
)

# Store with explicit tier selection
await memory.store(
    content="Critical security pattern detected",
    importance=0.9,
    tier=MemoryTier.FAST,  # Force fast tier for immediate access
)

# Retrieve relevant memories
memories = await memory.retrieve(
    query="How does Agent X perform?",
    limit=5,
    min_similarity=0.3,
)

for mem in memories:
    print(f"[{mem.tier.value}] {mem.content[:50]}... (score: {mem.relevance:.2f})")
```

### Choosing the Right Tier

```python
from aragora.memory.tier_manager import MemoryTier

# FAST: Immediate, volatile context (1 hour half-life)
# Use for: current debate context, error patterns, hot topics
await memory.store(content="...", tier=MemoryTier.FAST, importance=0.9)

# MEDIUM: Session-level learning (24 hour half-life)
# Use for: daily patterns, session insights, user preferences
await memory.store(content="...", tier=MemoryTier.MEDIUM, importance=0.6)

# SLOW: Strategic patterns (7 day half-life)
# Use for: proven strategies, cross-debate insights, reliability trends
await memory.store(content="...", tier=MemoryTier.SLOW, importance=0.4)

# GLACIAL: Long-term knowledge (30 day half-life)
# Use for: stable facts, compliance rules, historical baselines
await memory.store(content="...", tier=MemoryTier.GLACIAL, importance=0.2)
```

### Integration with Arena

```python
from aragora import Arena, Environment, DebateProtocol

# Enable cross-debate memory in the protocol
protocol = DebateProtocol(
    rounds=3,
    enable_cross_debate_memory=True,  # Inject relevant memories into prompts
    enable_coordinated_writes=True,   # Atomic memory writes
)

# Arena automatically:
# 1. Retrieves relevant memories before each round
# 2. Stores debate outcomes to appropriate tiers
# 3. Updates agent performance patterns
arena = Arena(env, agents, protocol)
result = await arena.run()
```

## Tier Overview

The Continuum Memory System uses four tiers with different update frequencies and retention policies:

| Tier | Half-Life | Update Frequency | Purpose | Typical Size |
|------|-----------|------------------|---------|--------------|
| **Fast** | 1 hour | Per event | Immediate patterns, hot context | 1,000-5,000 |
| **Medium** | 24 hours | Per round | Session-level tactical learning | 500-2,000 |
| **Slow** | 7 days | Per cycle | Strategic cross-debate learning | 200-1,000 |
| **Glacial** | 30 days | Monthly | Foundational knowledge, archives | 100-500 |

## Tier Selection Heuristics

### When Memories Enter Each Tier

**Fast Tier** - Short-lived, high-frequency patterns:
- Agent error patterns (TypeError, rate limit errors)
- Recent critique patterns from ongoing debates
- Hot topic context from last hour
- Temporary debugging information

**Medium Tier** - Session and day-level patterns:
- Successful critique strategies from today's debates
- Agent performance anomalies
- Domain-specific insights discovered in debates
- User preference patterns

**Slow Tier** - Week-level strategic patterns:
- Debate outcome patterns (what approaches consistently win)
- Agent reliability trends
- Cross-domain insights
- Proven architectural patterns

**Glacial Tier** - Long-term foundational knowledge:
- Core system behavior documentation
- Stable agent characteristics
- Historical baseline metrics
- Regulatory/compliance-related patterns

### Automatic Tier Selection

New memories are placed based on:

1. **Source context**: Evidence from web searches starts in FAST; debate outcomes start in SLOW
2. **Importance score**: Higher importance (>0.8) tends toward FAST; lower (<0.3) toward GLACIAL
3. **Domain specificity**: General knowledge goes to SLOW/GLACIAL; domain-specific to FAST/MEDIUM

```python
# Typical tier selection logic
if importance >= 0.8 and is_immediate_context:
    tier = MemoryTier.FAST
elif importance >= 0.5 or is_debate_outcome:
    tier = MemoryTier.SLOW
elif importance >= 0.3:
    tier = MemoryTier.MEDIUM
else:
    tier = MemoryTier.GLACIAL
```

## Promotion and Demotion

### Promotion Triggers (Slower -> Faster)

Memories are promoted when they show unexpected relevance:

| From Tier | Promotion Threshold | Meaning |
|-----------|---------------------|---------|
| Glacial -> Slow | surprise_score > 0.5 | Long-dormant memory suddenly relevant |
| Slow -> Medium | surprise_score > 0.6 | Weekly pattern becoming daily relevant |
| Medium -> Fast | surprise_score > 0.7 | Daily pattern becoming hourly relevant |

**Cooldown**: 24-hour minimum between promotions for the same entry.

### Demotion Triggers (Faster -> Slower)

Memories are demoted when they stabilize:

| From Tier | Demotion Threshold | Requirements |
|-----------|--------------------|--------------|
| Fast -> Medium | stability > 0.2 | 10+ updates, consistently predictable |
| Medium -> Slow | stability > 0.3 | 10+ updates, low surprise |
| Slow -> Glacial | stability > 0.4 | 10+ updates, very stable |

**Stability Score** = 1 - surprise_score

## Retention and Eviction Policies

### Half-Life Decay

Importance decays exponentially based on tier half-life:

```
decayed_importance = base_importance * (0.5 ^ (hours_elapsed / half_life))
```

| Tier | After 1 Day | After 7 Days | After 30 Days |
|------|-------------|--------------|---------------|
| Fast | 0.0001% | ~0% | ~0% |
| Medium | 50% | 0.8% | ~0% |
| Slow | 90.5% | 50% | 4.4% |
| Glacial | 97.7% | 85.2% | 50% |

### Eviction Priority

When tiers exceed max capacity, entries are evicted in order:

1. **Expired entries** - Past TTL (2x half-life by default)
2. **Lowest decayed importance** - After decay calculation
3. **Oldest last access** - Haven't been retrieved recently
4. **Lowest success rate** - Failed more than succeeded

### Max Entries Per Tier

Default limits (configurable via hyperparameters):

```python
max_entries_per_tier = {
    "fast": 5000,
    "medium": 2000,
    "slow": 1000,
    "glacial": 500,
}
```

## Monitoring Commands

### Check Tier Distribution

```sql
-- Via SQLite directly
SELECT tier, COUNT(*) as count,
       AVG(importance) as avg_importance,
       AVG(surprise_score) as avg_surprise
FROM continuum_memory
GROUP BY tier;
```

### Check Memory Health

```bash
# Via CLI (if available)
python -c "
from aragora.memory.continuum import ContinuumMemory
cm = ContinuumMemory()
stats = cm.get_stats()
print(f'Total entries: {stats[\"total_entries\"]}')
for tier, count in stats['tier_counts'].items():
    print(f'  {tier}: {count}')
"
```

### Check Transition Metrics

```python
from aragora.memory.tier_manager import get_tier_manager

manager = get_tier_manager()
metrics = manager.get_metrics_dict()
print(f"Total promotions: {metrics['total_promotions']}")
print(f"Total demotions: {metrics['total_demotions']}")
for transition, count in metrics['promotions'].items():
    print(f"  {transition}: {count}")
```

## Performance Benchmarks

### Expected Retrieval Times

| Operation | Fast Tier | Medium Tier | Slow Tier | Glacial Tier |
|-----------|-----------|-------------|-----------|--------------|
| Single lookup | <5ms | <10ms | <20ms | <50ms |
| Similarity search (5 results) | <50ms | <100ms | <200ms | <500ms |
| Full tier scan | <100ms | <200ms | <500ms | <1s |

### Database Size Expectations

| Entries | Database Size | Index Size |
|---------|---------------|------------|
| 1,000 | ~5 MB | ~1 MB |
| 10,000 | ~50 MB | ~10 MB |
| 100,000 | ~500 MB | ~100 MB |

### Memory Usage

Each entry consumes approximately:
- Base: ~500 bytes (content, metadata)
- With embedding: +1,536 bytes (768-dim float32)
- Index overhead: ~100 bytes

## Troubleshooting

### High Memory Usage

**Symptoms**: Database growing unexpectedly, slow retrievals

**Actions**:
1. Check tier counts - one tier may be over limit
2. Run cleanup: `cm.cleanup_expired_memories()`
3. Force consolidation: `cm.consolidate()`
4. Reduce max_entries_per_tier in hyperparameters

### Slow Retrievals

**Symptoms**: Query times exceeding benchmarks

**Actions**:
1. Check index health: `PRAGMA integrity_check`
2. Rebuild indexes: `REINDEX continuum_memory`
3. Vacuum database: `VACUUM`
4. Consider reducing similarity search limit

### Excessive Promotions

**Symptoms**: Fast tier constantly at capacity, frequent evictions

**Causes**:
- Promotion thresholds too low
- Cooldown too short
- Debate context constantly changing

**Actions**:
1. Increase promotion thresholds in TierConfig
2. Increase promotion_cooldown_hours (default: 24)
3. Review what's being promoted and adjust importance scoring

### Memory Not Being Retrieved

**Symptoms**: Relevant memories exist but aren't returned

**Causes**:
- min_similarity threshold too high
- Embeddings not computed
- Query phrasing mismatch

**Actions**:
1. Lower min_similarity threshold (default: 0.3)
2. Verify embeddings exist: `SELECT COUNT(*) FROM continuum_memory WHERE semantic_centroid IS NULL`
3. Try different query phrasings

## Configuration Reference

### Environment Variables

```bash
# Database location
ARAGORA_MEMORY_DB_PATH=/path/to/memory.db

# Default timeout for database operations
DB_TIMEOUT_SECONDS=30
```

### Hyperparameters

Hyperparameters can be adjusted via MetaLearner or direct configuration:

```python
hyperparams = {
    "surprise_weight_success": 0.4,    # Weight for success rate surprise
    "surprise_weight_semantic": 0.3,   # Weight for semantic novelty
    "surprise_weight_temporal": 0.2,   # Weight for timing surprise
    "surprise_weight_agent": 0.1,      # Weight for agent prediction error
    "consolidation_threshold": 5.0,    # Updates to reach full consolidation
    "promotion_cooldown_hours": 24.0,  # Min time between promotions
    "retention_multiplier": 2.0,       # TTL = multiplier * half_life
    "max_entries_per_tier": {
        "fast": 5000,
        "medium": 2000,
        "slow": 1000,
        "glacial": 500,
    },
}
```

## See Also

- [MEMORY_STRATEGY.md](MEMORY_STRATEGY.md) - Developer architecture documentation
- [MEMORY_ANALYTICS.md](MEMORY_ANALYTICS.md) - Analytics and ROI tracking
- [DATABASE.md](../reference/DATABASE.md) - Database operations guide
- [OPERATIONS.md](../operations/OPERATIONS.md) - General operations runbook
