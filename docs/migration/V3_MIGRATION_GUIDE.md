# Aragora v3.0 Migration Guide

> **Current version:** v2.10.0
> **Target version:** v3.0.0 (Q3 2026)
> **Deprecation warnings active since:** v2.7 (still emitted by v2.10)

This guide walks through every breaking change planned for v3.0 and provides concrete migration steps. All deprecated APIs emit `DeprecationWarning` today, so you can find and fix usages before the release.

For the full deprecation catalog, see [BREAKING_CHANGES.md](../BREAKING_CHANGES.md).

---

## Quick Checklist

- [ ] Migrate all `/api/v1/` calls to `/api/v2/`
- [ ] Update deprecated module imports (6 shims)
- [ ] Replace individual Arena kwargs with config objects
- [ ] Replace deprecated function calls (4 functions)
- [ ] Remove `aragora.config.legacy` imports
- [ ] Replace `AgentSpec.parse()` with explicit construction
- [ ] Remove `rlm_backend` parameter usage
- [ ] Rename type aliases (`ValidationResult` -> `FeatureValidationResult`)
- [ ] Rename `.gt` storage dirs to `.aragora_beads`
- [ ] Update renamed environment variables

---

## 1. API v1 Sunset

**Impact:** High
**Deadline:** June 1, 2026 (enforcement), removed in v3.0

All `/api/v1/` endpoints will return HTTP 410 Gone. The `/api/v2/` equivalents use a wrapped response format with metadata.

### Before

```python
response = client.get("/api/v1/debates")
debates = response["debates"]

response = client.post("/api/v1/debate", {
    "topic": "Design a cache",
    "max_rounds": 3,
})
```

### After

```python
response = client.get("/api/v2/debates")
debates = response["data"]["debates"]

response = client.post("/api/v2/debates", {
    "task": "Design a cache",
    "rounds": 3,
})
```

### Key Differences

| v1 | v2 |
|----|-----|
| `POST /api/v1/debate` | `POST /api/v2/debates` (plural) |
| `GET /api/v1/health` | `GET /api/v2/system/health` |
| Direct response body | `{"data": {...}, "meta": {...}}` envelope |
| `topic` field | `task` field |
| `max_rounds` field | `rounds` field |

### Testing Before Enforcement

Enable sunset blocking early to catch remaining v1 calls:

```bash
export ARAGORA_BLOCK_SUNSET_ENDPOINTS=true
pytest tests/ -v
```

Check v1 usage via metrics:

```bash
curl http://localhost:8080/metrics | grep aragora_v1_api
```

---

## 2. Module Relocations

**Impact:** Medium

Six backward-compatibility shims will be removed. Each emits `DeprecationWarning` on import today.

### aragora.schedulers -> aragora.scheduler

```python
# Before
from aragora.schedulers import ReceiptRetentionScheduler

# After
from aragora.scheduler.receipt_retention import ReceiptRetentionScheduler
```

### aragora.operations -> aragora.ops

```python
# Before
from aragora.operations import KeyRotationScheduler

# After
from aragora.ops.key_rotation import KeyRotationScheduler
```

### aragora.gateway.decision_router -> aragora.core.decision_router

```python
# Before
from aragora.gateway.decision_router import DecisionRouter

# After
from aragora.core.decision_router import DecisionRouter
```

### aragora.observability.logging -> aragora.logging_config

```python
# Before
from aragora.observability.logging import StructuredLogger

# After
from aragora.logging_config import StructuredLogger
```

### aragora.connectors.email.gmail_sync -> aragora.connectors.enterprise.communication.gmail

```python
# Before
from aragora.connectors.email.gmail_sync import GmailSyncService

# After
from aragora.connectors.enterprise.communication.gmail import GmailConnector
```

### aragora.modes.gauntlet -> aragora.gauntlet

```python
# Before
from aragora.modes.gauntlet import GauntletOrchestrator

# After
from aragora.gauntlet import GauntletOrchestrator
```

### Finding All Usages

```bash
# Search for deprecated imports
grep -rn "from aragora.schedulers" --include="*.py" .
grep -rn "from aragora.operations" --include="*.py" .
grep -rn "from aragora.gateway.decision_router" --include="*.py" .
grep -rn "from aragora.observability.logging" --include="*.py" .
grep -rn "from aragora.connectors.email.gmail_sync" --include="*.py" .
grep -rn "from aragora.modes.gauntlet" --include="*.py" .
```

---

## 3. Arena Config Consolidation

**Impact:** Medium

Individual keyword arguments for supermemory, RLM, cross-debate, knowledge, evolution, and ML features are deprecated. Use the corresponding config dataclass instead.

### Supermemory -> SupermemoryConfig

```python
# Before
arena = Arena(
    env, agents, protocol,
    enable_supermemory=True,
    supermemory_max_context_items=50,
    supermemory_sync_on_conclusion=True,
)

# After
from aragora.debate.orchestrator_config import SupermemoryConfig

arena = Arena(
    env, agents, protocol,
    supermemory_config=SupermemoryConfig(
        enable_supermemory=True,
        supermemory_max_context_items=50,
        supermemory_sync_on_conclusion=True,
    ),
)
```

### RLM -> MemoryConfig

```python
# Before
arena = Arena(
    env, agents, protocol,
    use_rlm_limiter=True,
    rlm_compression_threshold=3000,
)

# After
from aragora.debate.orchestrator_config import MemoryConfig

arena = Arena(
    env, agents, protocol,
    memory_config=MemoryConfig(
        use_rlm_limiter=True,
        rlm_compression_threshold=3000,
    ),
)
```

### Knowledge -> KnowledgeConfig

```python
# Before
arena = Arena(
    env, agents, protocol,
    enable_knowledge_extraction=True,
    extraction_min_confidence=0.8,
)

# After
from aragora.debate.arena_config import KnowledgeConfig

arena = Arena(
    env, agents, protocol,
    knowledge_config=KnowledgeConfig(
        enable_knowledge_extraction=True,
        extraction_min_confidence=0.8,
    ),
)
```

### Evolution -> EvolutionConfig

```python
# Before
arena = Arena(
    env, agents, protocol,
    auto_evolve=True,
    breeding_threshold=0.9,
)

# After
from aragora.debate.arena_config import EvolutionConfig

arena = Arena(
    env, agents, protocol,
    evolution_config=EvolutionConfig(
        auto_evolve=True,
        breeding_threshold=0.9,
    ),
)
```

### ML -> MLConfig

```python
# Before
arena = Arena(
    env, agents, protocol,
    enable_ml_delegation=True,
    ml_delegation_weight=0.5,
)

# After
from aragora.debate.arena_config import MLConfig

arena = Arena(
    env, agents, protocol,
    ml_config=MLConfig(
        enable_ml_delegation=True,
        ml_delegation_weight=0.5,
    ),
)
```

---

## 4. Deprecated Functions

**Impact:** Low

| Deprecated | Replacement |
|-----------|-------------|
| `DebateFactory._get_persona_prompt()` | `aragora.agents.personas.get_persona_prompt()` |
| `DebateFactory._apply_persona_params()` | `aragora.agents.personas.apply_persona_to_agent()` |
| `debate_utils.wrap_agent_for_streaming()` | `aragora.server.stream.arena_hooks.wrap_agent_for_streaming()` |
| `stream.state_manager.get_state_manager()` | `get_stream_state_manager()` or `aragora.server.state.get_state_manager()` |

All deprecated functions currently delegate to their replacement internally. Update call sites to use the replacement directly.

---

## 5. Legacy Configuration Module

**Impact:** Medium

The entire `aragora.config.legacy` module will be removed, including all `DB_*_PATH` constants.

```python
# Before
from aragora.config.legacy import DB_ELO_PATH, DB_MEMORY_PATH

# After
from aragora.persistence.db_config import get_db_path

elo_path = get_db_path("elo")
memory_path = get_db_path("memory")
```

```python
# Before
from aragora.config.legacy import get_api_key

# After
from aragora.config.settings import get_settings

api_key = get_settings().api_key
```

---

## 6. Agent Spec String Parsing

**Impact:** Low

```python
# Before
specs = AgentSpec.parse_list("anthropic:philosopher,openai:critic")
spec = AgentSpec.parse("anthropic:philosopher")

# After
specs = AgentSpec.create_team([
    {"provider": "anthropic", "persona": "philosopher"},
    {"provider": "openai", "role": "critic"},
])
spec = AgentSpec(provider="anthropic", persona="philosopher")
```

---

## 7. RLM Backend Parameter

**Impact:** Low

The `rlm_backend` parameter is no longer needed. Backend is auto-detected from `rlm_model`.

```python
# Before
limiter = RLMCognitiveLoadLimiter(rlm_backend="openai", rlm_model="gpt-4o")

# After
limiter = RLMCognitiveLoadLimiter(rlm_model="gpt-4o")
```

---

## 8. Type Alias Renames

**Impact:** Low

```python
# Before
from aragora.debate.feature_validator import ValidationResult

# After
from aragora.debate.feature_validator import FeatureValidationResult
```

```python
# Before
from aragora.debate.subsystem_coordinator import RankingAdapter

# After
from aragora.debate.subsystem_coordinator import PerformanceAdapter
```

---

## 9. Storage and Environment Changes

### Storage Directory

```bash
# Rename legacy storage
mv .gt .aragora_beads
```

### Environment Variables

| Old | New |
|-----|-----|
| `ARAGORA_REQUIRE_DISTRIBUTED_STATE` | `ARAGORA_REQUIRE_DISTRIBUTED` |
| `NOMIC_CANONICAL_STORE_PERSIST` | `ARAGORA_CANONICAL_STORE_PERSIST` |
| `ARAGORA_BEAD_DIR` | `ARAGORA_STORE_DIR` |

Both old and new names work in v2.x. Only new names will work in v3.0.

---

## Compatibility Testing

### Step 1: Enable All Deprecation Warnings

```bash
python -W default::DeprecationWarning -m pytest tests/ 2>&1 | grep DeprecationWarning
```

### Step 2: Test V1 Sunset Enforcement

```bash
ARAGORA_BLOCK_SUNSET_ENDPOINTS=true python -m pytest tests/server/ -v
```

### Step 3: Verify Config Object Migration

```bash
python -m pytest tests/debate/test_arena_deprecations.py -v
```

### Step 4: Check Module Shim Usage

```bash
python -m pytest tests/test_module_shims.py -v
```

### Step 5: Log Deprecated API Usage

```bash
ARAGORA_LOG_DEPRECATED_USAGE=true aragora serve --api-port 8080
# Then check logs for "Deprecated endpoint accessed" messages
```

---

## Timeline

| Date | Event |
|------|-------|
| Jan 2026 | v2.0: V1 API deprecated, module shims created |
| Feb 2026 | v2.7-v2.8: Arena config consolidation warnings for knowledge/evolution/ML |
| Jun 1, 2026 | V1 API sunset date (HTTP 410 available via `BLOCK_SUNSET_ENDPOINTS=true`) |
| Q3 2026 | **v3.0 release**: all deprecated items removed |

---

*Last updated: 2026-02-23*
