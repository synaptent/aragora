# Python SDK Consolidation Roadmap (Historical)

> **Status (February 2026):** The canonical Python SDK client is `aragora-sdk` in `sdk/python/`.
> The legacy `aragora-client` package (`aragora-py/`) has been removed from the repository.
> This document is retained for historical reference only.

> **Status:** Phase 1 Complete (January 2026)
> **Next Milestone:** v3.0.0 consolidation (Q2 2026)

This document outlines the plan to consolidate the two Python packages (`aragora` and `aragora-client`) into a single unified SDK.

## Current State (v2.5.x / v2.4.x)

Two packages exist with different focuses:

| Aspect | `aragora` | `aragora-client` |
|--------|-----------|------------------|
| **Version** | 2.6.3 | 2.4.0 |
| **Location** | `sdk/python/aragora/` | `aragora-py/aragora_client/` (removed) |
| **API Style** | Both sync + async (`AragoraClient`, `AragoraAsyncClient`) | Async-only (`AragoraClient`) |
| **Namespaces** | 125 namespace modules | 26 modules |
| **Tests** | 55 test files | 20 test files |
| **Best For** | Full-featured applications, type-safe development | Lightweight async integrations, control plane |
| **Type Exports** | 196+ Pydantic types from `generated_types.py` | 70+ dataclass/Pydantic types |

### Feature Matrix

> **Note:** `aragora` (full SDK) has the most comprehensive feature coverage. `aragora-client` focuses on core debate and enterprise APIs.

| Feature | `aragora` | `aragora-client` |
|---------|:---------:|:----------------:|
| Basic debates | Yes | Yes |
| Graph debates | Yes | Yes |
| Matrix debates | Yes | Yes |
| WebSocket streaming | Yes | Yes |
| Sync client | Yes | No |
| Async client | Yes | Yes |
| Control Plane | Yes | Yes |
| Verification (Z3/Lean) | Yes | Yes |
| Gauntlet API | Yes | Yes |
| Team selection | Yes | Yes |
| Workflows | Yes | Yes |
| Explainability | Yes | Yes |
| Marketplace | Yes | Yes |
| Knowledge API | Yes | Yes |
| RBAC | Yes | Yes |
| Tenancy | Yes | Yes |
| Tournaments | Yes | Yes |
| Audit | Yes | Yes |
| Authentication | Yes | Yes |
| Codebase analysis | Yes | Yes |
| Gmail integration | Yes | No |
| Memory API | Yes | No |
| Pulse (trending) | Yes | No |
| Billing | Yes | No |
| Backups | Yes | No |
| Policies | Yes | No |
| Notifications | Yes | No |
| SME quick decisions | Yes | No |
| Pagination helpers | Yes | No |
| Typed WebSocket events | Yes | Yes |
| Threat Intelligence | No | Yes |
| Decisions API | Yes | Yes |
| Replay API | No | Yes |
| Cross-pollination | No | Yes |
| Onboarding | No | Yes |

### Architecture Differences

**`aragora` (Full SDK):**
- Generated types from OpenAPI spec (`generated_types.py`)
- 125 namespace modules for granular API access
- Pydantic v2 models throughout
- Sync and async client variants
- Built-in pagination helpers (`AsyncPaginator`, `SyncPaginator`)
- Typed WebSocket event classes for each event type

**`aragora-client` (Lightweight SDK):**
- Hand-crafted dataclass and Pydantic models
- Async-only design for modern Python patterns
- Focused on control plane and enterprise features
- More comprehensive enterprise API coverage (tenancy, auth, replay)
- Simpler module structure

## Target State (v3.0.0)

A single `aragora` package combining the best of both:

### Goals

- **Single source of truth** - One package to install and maintain
- **Dual API style** - Both sync and async clients
- **Full feature set** - All capabilities from both packages
- **Type-safe** - Pydantic v2 models with full type annotations
- **Enterprise-ready** - Complete control plane, auth, tenancy, and audit APIs
- **Modern Python** - Python 3.10+ with async/await patterns

### Target API Structure

```python
from aragora import AragoraClient, AragoraAsyncClient

# Sync client for simple scripts
client = AragoraClient(
    base_url="https://api.aragora.ai",
    api_key="your-key"
)

# Async client for high-performance applications
async_client = AragoraAsyncClient(
    base_url="https://api.aragora.ai",
    api_key="your-key"
)

# Debates (from both packages)
debate = await async_client.debates.create(task="...")
debates = await async_client.debates.list()
graph = await async_client.graph_debates.create(task="...")
matrix = await async_client.matrix_debates.create(task="...", scenarios=[...])

# Agents
agents = await async_client.agents.list()
profile = await async_client.agents.get("claude")

# Control Plane (from aragora-client)
await async_client.control_plane.register_agent("agent-id", {...})
task = await async_client.control_plane.submit_task("debate", {...})
health = await async_client.control_plane.get_agent_health("agent-id")

# Verification (from aragora-client)
result = await async_client.verification.verify(claim="...", backend="z3")

# Workflows (from aragora)
templates = await async_client.workflows.list_templates()
execution = await async_client.workflows.execute("template-id", {...})

# Explainability (from aragora)
factors = await async_client.explainability.get_factors("debate-id")
counterfactuals = await async_client.explainability.get_counterfactuals("debate-id")

# Gauntlet
receipt = await async_client.gauntlet.run_and_wait(input_content="...")
receipts = await async_client.gauntlet.list_receipts()

# Enterprise (from aragora-client)
await async_client.auth.login(email="...", password="...")
tenants = await async_client.tenants.list()
roles = await async_client.rbac.list_roles()
events = await async_client.audit.list_events()

# Replay & Learning (from aragora-client)
replay = await async_client.replays.get("debate-id")
evolution = await async_client.replays.get_learning_evolution("debate-id")

# WebSocket (unified)
async for event in async_client.stream.subscribe("debate-id"):
    if event.type == "agent_message":
        print(f"{event.data['agent']}: {event.data['content']}")
    elif event.type == "consensus":
        print(f"Consensus: {event.data['conclusion']}")
```

## Migration Timeline

### v2.6.3 (Q1 2026) - COMPLETE

**Goal**: Prepare for consolidation

- [x] Document all methods in both packages
- [x] Identify overlapping functionality
- [x] Ensure feature parity for core debate APIs
- [x] Add comprehensive type exports to `aragora`

**Breaking changes**: None

### v2.6.0 (Q1 2026)

**Goal**: Feature parity in `aragora`

- [ ] Add Replay API to `aragora`
- [ ] Add Cross-pollination API to `aragora`
- [ ] Add Threat Intelligence API to `aragora`
- [ ] Add Onboarding API to `aragora`
- [ ] Port enterprise API improvements from `aragora-client`
- [ ] Add deprecation warnings to `aragora-client`
- [ ] Document migration path

**Breaking changes**: None

### v2.7.0 (Q2 2026)

**Goal**: Consolidation preparation

- [ ] `aragora-client` becomes thin wrapper around `aragora`
- [ ] All tests migrated to unified test suite
- [ ] Performance benchmarking
- [ ] Documentation unified

**Breaking changes**: None (client still works)

### v3.0.0 (Q2 2026)

**Goal**: Single unified SDK

- [ ] `aragora-client` deprecated (no longer published)
- [ ] `aragora` is the only package
- [ ] Full namespace API coverage
- [ ] Sync + async client support
- [ ] Complete type annotations
- [ ] Comprehensive test coverage (100+ test files)

**Breaking changes**:
- `aragora-client` package no longer available
- Some method names standardized (e.g., `run` -> `create` for consistency)
- Exception class names unified

## Migration Guide

### Recommended Package

**`aragora-sdk`** is the canonical Python SDK package.

Use `aragora-sdk` when you need:
- The blessed remote API client for Python integrations
- Current SDK feature work and versioned API compatibility

Use `aragora` when you need:
- The full control plane package (server + CLI + embedded SDK)

~~Use `aragora-client` only when you need:~~
- The `aragora-client` package (`aragora-py/`) has been removed from the repository

### From `aragora-client` to `aragora` v3.0.0 (Historical Plan)

> Current migration target for external SDK consumers is `aragora-sdk`; this section is retained for roadmap history.

```python
# Before (aragora-client)
from aragora_client import AragoraClient
from aragora_client import (
    Debate,
    DebateStatus,
    AragoraError,
    AragoraNotFoundError,
)

async def main():
    client = AragoraClient("http://localhost:8080")
    debate = await client.debates.run(task="Should we use microservices?")
    print(debate.consensus.conclusion)

# After (aragora v3.0.0)
from aragora import AragoraAsyncClient
from aragora import (
    Debate,
    DebateStatus,
    AragoraError,
    NotFoundError,  # Note: renamed from AragoraNotFoundError
)

async def main():
    async with AragoraAsyncClient(
        base_url="http://localhost:8080"
    ) as client:
        debate = await client.debates.run(task="Should we use microservices?")
        print(debate.consensus.conclusion)
```

### Exception Class Mapping

| `aragora-client` | `aragora` |
|------------------|-----------|
| `AragoraError` | `AragoraError` |
| `AragoraConnectionError` | `ConnectionError` |
| `AragoraAuthenticationError` | `AuthenticationError` |
| `AragoraNotFoundError` | `NotFoundError` |
| `AragoraValidationError` | `ValidationError` |
| `AragoraTimeoutError` | `TimeoutError` |

### API Method Differences

| Operation | `aragora-client` | `aragora` |
|-----------|------------------|-----------|
| Run debate to completion | `client.debates.run(...)` | `client.debates.run(...)` (same) |
| Create debate (no wait) | `client.debates.create(...)` | `client.debates.create(...)` (same) |
| Get debate | `client.debates.get(id)` | `client.debates.get(id)` (same) |
| Agent health | `client.control_plane.get_agent_health(id)` | `client.control_plane.agent_health(id)` |

## Implementation Phases

### Phase 1: Analysis (1 week) - COMPLETE

- [x] Document all methods in both packages
- [x] Identify overlapping functionality (see Feature Matrix above)
- [x] Design unified namespace structure
- [x] Plan test migration

### Phase 2: SDK Enhancement (3-4 weeks)

- [ ] Add missing APIs to `aragora`:
  - [ ] Replay API (`replays` namespace)
  - [ ] Cross-pollination API (`cross_pollination` namespace)
  - [ ] Threat Intelligence API (`threat_intel` namespace)
  - [ ] Onboarding API (`onboarding` namespace)
- [ ] Port enterprise API improvements from `aragora-client`
- [ ] Add advanced WebSocket features (reconnect, heartbeat)
- [ ] Merge test suites

### Phase 3: Deprecation (1 week)

- [ ] Add deprecation warnings to `aragora-client`:
  ```python
  import warnings
  warnings.warn(
      "aragora-client is deprecated. Please migrate to aragora-sdk. "
      "See https://docs.aragora.ai/python-migration",
      DeprecationWarning,
      stacklevel=2
  )
  ```
- [ ] Update documentation with migration examples
- [ ] Announce migration timeline
- [ ] Publish v2.6.0 of both packages

### Phase 4: Client Wrapper (1-2 weeks)

- [ ] Make `aragora-client` a thin wrapper around `aragora`
- [ ] Ensure backwards compatibility for all existing methods
- [ ] Test with existing `aragora-client` users
- [ ] Publish v2.7.0

### Phase 5: Final Release (1 week)

- [ ] Remove `aragora-client` source (keep as deprecated PyPI package)
- [ ] Finalize `aragora` v3.0.0
- [ ] Update all documentation
- [ ] Announce final migration with 2-week notice

## Deprecation Policy

Following Aragora's 2 minor version grace period policy:

1. **v2.6.0**: Deprecation warnings added to `aragora-client`
2. **v2.7.0**: `aragora-client` becomes wrapper around `aragora`
3. **v3.0.0**: `aragora-client` no longer published (archived on PyPI)

Users have approximately 3-4 months to migrate during the grace period.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking changes for `aragora-client` users | High | Detailed migration guide, wrapper maintains compatibility |
| Exception class name changes | Medium | Document mapping, consider aliases |
| Test coverage gaps after merge | Medium | Merge all tests, add integration tests |
| Missing features during transition | Low | Feature flags, gradual rollout |
| Performance regression | Medium | Benchmark before/after, optimize hot paths |

## Success Metrics

- [ ] Single PyPI package with all features
- [ ] Zero breaking changes for users following migration guide
- [ ] Test coverage >= 85%
- [ ] Documentation updated on docs.aragora.ai
- [ ] No critical issues within 2 weeks of v3.0.0 release
- [ ] < 100 deprecation warnings reported in first month

## Detailed Migration Examples

### Example 1: Basic Debate Flow

```python
# aragora-client v2.x
from aragora_client import AragoraClient, Debate

async def run_debate_old():
    client = AragoraClient(
        "http://localhost:8080",
        api_key="your-key",
    )
    debate = await client.debates.run(
        task="Evaluate the pros and cons of microservices",
        agents=["anthropic-api", "openai-api"],
        max_rounds=5,
    )
    await client.close()
    return debate

# aragora v3.0.0
from aragora import AragoraAsyncClient, Debate

async def run_debate_new():
    async with AragoraAsyncClient(
        base_url="http://localhost:8080",
        api_key="your-key",
    ) as client:
        debate = await client.debates.run(
            task="Evaluate the pros and cons of microservices",
            agents=["anthropic-api", "openai-api"],
            max_rounds=5,
        )
    return debate
```

### Example 2: WebSocket Streaming

```python
# aragora-client v2.x
from aragora_client import DebateStream

async def stream_old():
    stream = DebateStream("ws://localhost:8765", "debate-123")
    stream.on("agent_message", lambda e: print(f"Agent: {e.data}"))
    stream.on("consensus", lambda e: print("Consensus reached!"))
    await stream.connect()

# aragora v3.0.0
from aragora import AragoraAsyncClient

async def stream_new():
    async with AragoraAsyncClient(base_url="http://localhost:8080") as client:
        async for event in client.stream.subscribe("debate-123"):
            if event.type == "agent_message":
                print(f"Agent: {event.data}")
            elif event.type == "consensus":
                print("Consensus reached!")
                break
```

### Example 3: Control Plane Operations

```python
# aragora-client v2.x
from aragora_client import AragoraClient

async def control_plane_old():
    client = AragoraClient("http://localhost:8080")

    await client.control_plane.register_agent(
        agent_id="my-agent",
        capabilities=["analysis", "coding"],
        metadata={"version": "1.0.0"},
    )

    task = await client.control_plane.submit_task(
        task_type="debate",
        payload={"question": "Review architecture"},
        priority=8,
    )

    result = await client.control_plane.wait_for_task(task.task_id)

# aragora v3.0.0 (same API, different import)
from aragora import AragoraAsyncClient

async def control_plane_new():
    async with AragoraAsyncClient(base_url="http://localhost:8080") as client:
        await client.control_plane.register_agent(
            agent_id="my-agent",
            capabilities=["analysis", "coding"],
            metadata={"version": "1.0.0"},
        )

        task = await client.control_plane.submit_task(
            task_type="debate",
            payload={"question": "Review architecture"},
            priority=8,
        )

        result = await client.control_plane.wait_for_task(task.task_id)
```

### Example 4: Enterprise Authentication

```python
# aragora-client v2.x
from aragora_client import AragoraClient

async def auth_old():
    client = AragoraClient("http://localhost:8080")

    token = await client.auth.login("user@example.com", "password")
    user = await client.auth.get_current_user()

    # MFA setup
    setup = await client.auth.setup_mfa(method="totp")
    await client.auth.verify_mfa_setup(code="123456")

# aragora v3.0.0
from aragora import AragoraAsyncClient

async def auth_new():
    async with AragoraAsyncClient(base_url="http://localhost:8080") as client:
        token = await client.auth.login("user@example.com", "password")
        user = await client.auth.get_current_user()

        # MFA setup
        setup = await client.auth.setup_mfa(method="totp")
        await client.auth.verify_mfa_setup(code="123456")
```

## Compatibility Layer

During the transition period (v2.6.0 - v2.7.0), `aragora-client` will internally
use `aragora` with a compatibility wrapper:

```python
# Internal implementation of aragora-client v2.7.0
import warnings
from aragora import AragoraAsyncClient as SDKClient

warnings.warn(
    "aragora-client is deprecated. Please migrate to aragora-sdk. "
    "See https://docs.aragora.ai/python-migration",
    DeprecationWarning,
    stacklevel=2
)

class AragoraClient:
    """Compatibility wrapper around aragora SDK."""

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._sdk = SDKClient(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            headers=headers,
        )
        self.debates = self._sdk.debates
        self.agents = self._sdk.agents
        self.control_plane = self._sdk.control_plane
        # ... other namespace mappings

    async def __aenter__(self):
        await self._sdk.__aenter__()
        return self

    async def __aexit__(self, *args):
        await self._sdk.__aexit__(*args)

    async def close(self):
        await self._sdk.close()
```

## Related Documentation

- [sdk/python/README.md](../../sdk/python/README.md) - Full SDK documentation
- [docs/SDK_GUIDE.md](../SDK_GUIDE.md) - SDK architecture overview
- [TypeScript SDK Consolidation](../../docs-site/docs/guides/sdk-consolidation.md) - TypeScript equivalent
