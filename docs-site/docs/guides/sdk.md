---
title: Aragora Python SDK
description: Aragora Python SDK
---

# Aragora Python SDK

The Aragora Python SDK provides a type-safe interface for interacting with the Aragora API.

Single blessed Python SDK client: `aragora-sdk` (from `sdk/python/`).
Prefer `/api/v1` endpoints for SDK usage; unversioned `/api` endpoints remain supported but are deprecated for SDK clients.

## Package Options

- `aragora-sdk` - Blessed client for Python integrations and remote API use (`/api/v1`).
- `aragora` - Full control plane package with server + CLI + sync/async SDK.
- `aragora-client` - Deprecated; use `aragora-sdk` instead.

TypeScript: use `@aragora/sdk` (official). `@aragora/client` is deprecated.
Canonical migration path: [Python SDK migration](./python-sdk-migration).

## Installation

```bash
pip install aragora-sdk
```

### Release cadence (recorded operator policy, 2026-07-16)

`aragora-sdk` on PyPI follows a **decoupled release cadence**: the repository's
`sdk/python/` may be ahead of the latest published wheel between releases
(e.g. the repo can declare 2.10.0 while PyPI serves 2.8.0). This is intentional —
releases are operator-gated and cut deliberately, not on every merge.
Compatibility expectation: the published PyPI version always targets the
`/api/v1` surface of the same or newer server release, and published versions
never regress. If you need repo-tip SDK behavior before it is published,
install from source (below). Tracking issue for this policy: #9234.

Or install the full control plane package (includes the SDK and server):

```bash
pip install aragora
```

Or from source:

```bash
git clone https://github.com/synaptent/aragora.git
cd aragora
pip install -e .
```

## Quick Start

### Standalone SDK (aragora-sdk)

This example is pinned to the public 2.8.0 surface and runs offline. Omit
`demo=True` and provide `base_url` to call a running deployment.

```python
import asyncio
from aragora_sdk import AragoraAsyncClient

async def main():
    async with AragoraAsyncClient(demo=True) as client:
        debate = await client.debates.create(
            task="Should we use microservices?",
            agents=["demo"],
        )
        print(f"Consensus: {debate['consensus']['conclusion']}")

asyncio.run(main())
```

The public quickstart is mechanically checked against the committed
[`aragora-sdk` 2.8.0 surface](https://github.com/synaptent/aragora/blob/main/docs/reference/sdk_released_surface_2.8.0.json).
Later sections cover the broader repository API and may require installing
`./sdk/python` when they use methods added after the published release.

### Full SDK (aragora) - Synchronous Usage

```python
from aragora.client import AragoraClient

# Create client
client = AragoraClient(base_url="http://localhost:8080")

# Create a debate
response = client.debates.create(task="Should we use microservices?")
print(f"Debate started: {response.debate_id}")

# Get debate result
debate = client.debates.get(response.debate_id)
print(f"Status: {debate.status}")
```

### Full SDK (aragora) - Asynchronous Usage

```python
import asyncio
from aragora.client import AragoraClient

async def main():
    async with AragoraClient(base_url="http://localhost:8080") as client:
        # Create and wait for debate completion
        debate = await client.debates.run(
            task="Design a distributed cache",
            timeout=600,  # 10 minutes
        )
        print(f"Status: {debate['status']}")

asyncio.run(main())
```

## Configuration

```python
client = AragoraClient(
    base_url="http://localhost:8080",  # API server URL
    api_key="your-api-key",            # Optional authentication
    timeout=60,                         # Request timeout in seconds
)
```

## Core APIs

### Debates

Standard debates with propose-critique-revise workflow.

```python
# Create a debate
response = client.debates.create(
    task="Should we adopt Kubernetes?",
    agents=["anthropic-api", "openai-api", "gemini"],
    rounds=3,
    consensus="majority",  # unanimous, majority, supermajority, hybrid
    context="For a startup with 5 engineers",
)

# Get debate details
debate = client.debates.get(response.debate_id)

# List recent debates
debates = client.debates.list(limit=20, status="completed")

# Create and wait for completion (blocking)
debate = client.debates.run(
    task="Design a rate limiter",
    timeout=600,
)
```

### Gauntlet (Adversarial Validation)

Stress-test specifications, policies, and architectures.

```python
# Start a gauntlet adversarial validation
response = client.gauntlet.run(
    task="Should we deploy this architecture to production?",
    attack_rounds=3,
    proposer_agent="anthropic-api",
    attacker_agents=["openai-api", "mistral-api"],
)

# Get decision receipt
receipt = client.gauntlet.get_receipt(response["gauntlet_id"])
print(f"Verdict: {receipt['verdict']}")

for finding in receipt.get("findings", []):
    print(f"- [{finding['severity']}] {finding['title']}")

# Run and wait for completion
result = client.gauntlet.run_and_wait(
    task="Validate our privacy policy compliance",
    attack_rounds=5,
    timeout=900,
)
```

### Graph Debates (Branching Discussions)

Graph debates allow automatic branching when agents identify fundamentally different approaches.

```python
# Create graph debate
response = client.graph_debates.create(
    task="Design a distributed system architecture",
    agents=["anthropic-api", "openai-api"],
    max_rounds=5,
    branch_threshold=0.5,  # Divergence threshold for branching
    max_branches=5,
)

# Get debate with all branches
debate = client.graph_debates.get(response.debate_id)

# Get branches separately
branches = client.graph_debates.get_branches(response.debate_id)
for branch in branches:
    print(f"Branch: {branch.name} ({len(branch.nodes)} nodes)")
```

### Matrix Debates (Parallel Scenarios)

Matrix debates run the same question across different scenarios to identify universal vs conditional conclusions.

```python
# Create matrix debate
response = client.matrix_debates.create(
    task="Should we adopt microservices?",
    agents=["anthropic-api", "openai-api"],
    scenarios=[
        {"name": "small_team", "parameters": {"team_size": 5}, "is_baseline": True},
        {"name": "large_team", "parameters": {"team_size": 50}},
        {"name": "high_scale", "parameters": {"requests_per_sec": 1_000_000}},
    ],
    max_rounds=3,
)

# Get matrix debate results
matrix = client.matrix_debates.get(response.matrix_id)

# Get conclusions (universal vs conditional)
conclusions = client.matrix_debates.get_conclusions(response.matrix_id)
print("Universal conclusions (true in all scenarios):")
for c in conclusions.universal:
    print(f"  - {c}")

print("\nConditional conclusions:")
for scenario, findings in conclusions.conditional.items():
    print(f"  {scenario}:")
    for f in findings:
        print(f"    - {f}")
```

### Verification (Formal Methods)

Verify claims using formal methods (Z3, Lean, Coq).

```python
# Verify a claim
result = client.verification.verify(
    claim="All prime numbers greater than 2 are odd",
    context="Number theory",
    backend="z3",      # z3, lean, coq
    timeout=30,
)

print(f"Status: {result.status}")  # valid, invalid, unknown, error
if result.proof:
    print(f"Proof: {result.proof}")
if result.counterexample:
    print(f"Counterexample: {result.counterexample}")

# Check backend availability
status = client.verification.status()
for backend in status.backends:
    print(f"{backend.name}: {'available' if backend.available else 'unavailable'}")
```

### Memory Analytics

Monitor memory tier performance and get optimization recommendations.

```python
# Get comprehensive analytics
analytics = client.memory.analytics(days=30)
print(f"Total entries: {analytics.total_entries}")
print(f"Learning velocity: {analytics.learning_velocity:.2f}")

for tier in analytics.tiers:
    print(f"{tier.tier_name}: {tier.entry_count} entries, {tier.hit_rate:.0%} hit rate")

for rec in analytics.recommendations:
    print(f"[{rec.impact}] {rec.type}: {rec.description}")

# Get stats for specific tier
tier_stats = client.memory.tier_stats("fast", days=7)

# Take manual snapshot
snapshot = client.memory.snapshot()
```

### Knowledge Base

Manage facts and run semantic queries against the knowledge base.

```python
# Semantic search over knowledge chunks
results = client.knowledge.search("password reset policies", limit=5)
for item in results["results"]:
    print(item["content"][:80])

# Create a fact
fact = client.knowledge.create_fact(
    statement="All customer data is encrypted at rest",
    workspace_id="default",
    confidence=0.85,
    topics=["security", "compliance"],
)

# Verify and fetch contradictions
client.knowledge.verify_fact(fact["id"])
contradictions = client.knowledge.list_contradictions(fact["id"])
```

### Consensus Memory

Inspect settled topics, dissents, and consensus stats.

```python
similar = client.consensus.get_similar_debates("rate limiting", limit=5)
stats = client.consensus.get_stats()
warnings = client.consensus.get_risk_warnings(limit=5)
```

### Agents

Discover available agents and their capabilities.

```python
# List all agents
agents = client.agents.list()
for agent in agents:
    print(f"{agent.agent_id}: ELO {agent.elo_rating}, {agent.win_rate:.0%} win rate")

# Get specific agent profile
profile = client.agents.get("anthropic-api")
print(f"Capabilities: {profile.capabilities}")
```

### Leaderboard

ELO rankings across all agents.

```python
# Get top agents
rankings = client.leaderboard.get(limit=10)
for entry in rankings:
    trend = {"up": "+", "down": "-", "stable": "="}[entry.recent_trend]
    print(f"#{entry.rank} {entry.agent_id}: {entry.elo_rating} ({trend})")
```

### Replays

View and export debate replays.

```python
# List replays
replays = client.replays.list(limit=10)

# Get full replay with events
replay = client.replays.get(replays[0].replay_id)
for event in replay.events:
    print(f"[{event.timestamp}] {event.event_type}: {event.content[:50]}...")

# Delete replay
client.replays.delete(replay.replay_id)
```

### Explainability

Inspect decision explanations, evidence chains, and counterfactuals.

```python
explanation = client.explainability.get_explanation(debate_id)
evidence = client.explainability.get_evidence(debate_id)
summary = client.explainability.get_summary(debate_id, format="markdown")

batch = client.explainability.create_batch([debate_id], include_evidence=True)
status = client.explainability.get_batch_status(batch.batch_id)
```

### Batch Operations

Submit and track debate batches.

```python
batch = client.batch.submit_debates(
    [
        {"question": "Evaluate rate limiting options", "agents": "openai-api,anthropic-api"},
        {"question": "Design a cache invalidation strategy", "rounds": 2},
    ],
    callback_url="https://example.com/webhooks/batch",
)

status = client.batch.get_status(batch["batch_id"])
batches = client.batch.list(status="processing", limit=25)
```

### Routing

Request routing recommendations and manage rules.

```python
recommendations = client.routing.select_team(
    "Assess SOC2 audit readiness",
    team_size=4,
    required_skills=["security", "compliance"],
)

auto = client.routing.auto_route("Summarize customer feedback")
domain = client.routing.detect_domain("Create a phishing training plan")

rules = client.routing.list_rules(active_only=True)
rule = client.routing.create_rule(
    name="SOC2 escalation",
    conditions=[{"field": "risk_level", "operator": "gte", "value": "high"}],
    actions=[{"type": "notify", "channel": "slack"}],
    priority=10,
)
```

### Critiques & Reputation

Inspect critique patterns and agent reputation data.

```python
patterns = client.critiques.list_patterns(limit=5)
reputations = client.critiques.list_reputations()
agent_rep = client.critiques.get_agent_reputation("claude")
```

### Additional Namespaces

The SDK exposes additional namespaces for platform and admin features. For
endpoint details, see API_REFERENCE.md.

- `client.a2a` - Agent-to-agent protocol
- `client.advertising` - Advertising platform integrations
- `client.cross_pollination` - Cross-pollination stats and subscriptions
- `client.bots` - Bot integration webhooks (Teams, Discord, Telegram, Zoom)
- `client.dashboard` - Dashboard overview and quick actions
- `client.deliberations` - Active deliberations and stats
- `client.devices` - Device registration and notifications
- `client.feedback` - NPS surveys and product feedback
- `client.gmail` - Gmail message operations
- `client.metrics` - Operational metrics and Prometheus export
- `client.plugins` - Plugin management and marketplace
- `client.privacy` - GDPR/CCPA export and privacy preferences
- `client.queue` - Background job queue management
- `client.system` - Admin history, maintenance, and circuit breakers
- `client.threat_intel` - Threat intelligence scanning
- `client.unified_inbox` - Unified inbox routing and actions

### Organizations

Manage organizations and membership.

```python
org = client.organizations.get(org_id)
members = client.organizations.list_members(org_id)
client.organizations.invite_member(org_id, email="user@acme.com", role="member")

memberships = client.organizations.list_user_organizations()
if memberships:
    client.organizations.switch_organization(memberships[0].org_id)
```

### Compliance Policies

Define policies and review violations.

```python
policies, total = client.policies.list(limit=50)
policy = client.policies.get("policy-123")

violations, _ = client.policies.list_violations(status="open")
result = client.policies.check(
    content="We store EU customer data in us-east-1",
    frameworks=["gdpr"],
)
```

### Tenants

Administer tenants for multi-tenant deployments.

```python
tenants, total = client.tenants.list()
tenant = client.tenants.create(name="Acme Corp", slug="acme", tier="enterprise")
usage = client.tenants.get_usage(tenant.id)
client.tenants.update_quotas(tenant.id, {"debates_per_month": 5000})
```

### Health Check

```python
health = client.health()
print(f"Status: {health.status}")
print(f"Version: {health.version}")
print(f"Uptime: {health.uptime_seconds:.0f}s")
```

## Type-Safe Models

The SDK uses Pydantic models for all request/response types:

```python
from aragora.client.models import (
    # Debates
    Debate, DebateStatus, DebateCreateRequest, DebateCreateResponse,
    DebateRound, AgentMessage, Vote, ConsensusResult, ConsensusType,

    # Gauntlet
    GauntletReceipt, GauntletVerdict, Finding,
    GauntletRunRequest, GauntletRunResponse,

    # Graph debates
    GraphDebate, GraphDebateBranch, GraphDebateNode,
    GraphDebateCreateRequest, GraphDebateCreateResponse,

    # Matrix debates
    MatrixDebate, MatrixScenario, MatrixScenarioResult, MatrixConclusion,
    MatrixDebateCreateRequest, MatrixDebateCreateResponse,

    # Verification
    VerifyClaimRequest, VerifyClaimResponse, VerifyStatusResponse,
    VerificationStatus, VerificationBackend,

    # Memory
    MemoryAnalyticsResponse, MemoryTierStats, MemoryRecommendation,
    MemorySnapshotResponse,

    # Agents
    AgentProfile, LeaderboardEntry,

    # Replays
    Replay, ReplaySummary, ReplayEvent,

    # General
    HealthCheck, APIError,
)
```

## Error Handling

The SDK provides structured error handling with consistent error types across Python and TypeScript SDKs.

### Error Types

```python
from aragora.client import AragoraClient, AragoraAPIError

client = AragoraClient(base_url="http://localhost:8080")

try:
    debate = client.debates.get("nonexistent-id")
except AragoraAPIError as e:
    print(f"Error: {e}")
    print(f"Code: {e.code}")           # Machine-readable code
    print(f"Status: {e.status_code}")  # HTTP status
    print(f"Message: {e.message}")     # Human-readable message
    print(f"Details: {e.details}")     # Additional context (optional)
```

### Error Code Reference

| HTTP Status | Error Code | Description | Retryable |
|-------------|------------|-------------|-----------|
| 400 | `VALIDATION_ERROR` | Invalid request parameters | No |
| 400 | `INVALID_INPUT` | Malformed request body | No |
| 401 | `UNAUTHORIZED` | Missing or invalid API key | No |
| 401 | `TOKEN_EXPIRED` | Authentication token expired | Yes (refresh) |
| 403 | `FORBIDDEN` | Insufficient permissions | No |
| 403 | `QUOTA_EXCEEDED` | Usage quota reached | Yes (wait) |
| 404 | `NOT_FOUND` | Resource doesn't exist | No |
| 409 | `CONFLICT` | Resource state conflict | Yes (retry) |
| 422 | `UNPROCESSABLE` | Semantically invalid request | No |
| 429 | `RATE_LIMITED` | Too many requests | Yes (backoff) |
| 500 | `INTERNAL_ERROR` | Server error | Yes (retry) |
| 502 | `BAD_GATEWAY` | Upstream service error | Yes (retry) |
| 503 | `SERVICE_UNAVAILABLE` | Service temporarily unavailable | Yes (retry) |
| 504 | `GATEWAY_TIMEOUT` | Request timeout | Yes (retry) |

### API Response Format

All API errors return a consistent JSON structure:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "Debate not found",
    "details": {
      "debate_id": "nonexistent-id",
      "suggestion": "Use /api/debates to list available debates"
    }
  }
}
```

### Handling Specific Errors

```python
from aragora.client import AragoraAPIError

try:
    result = client.debates.run(task="...", agents=["invalid-agent"])
except AragoraAPIError as e:
    if e.code == "VALIDATION_ERROR":
        print(f"Fix your request: {e.details}")
    elif e.code == "RATE_LIMITED":
        retry_after = e.details.get("retry_after", 60)
        print(f"Rate limited. Retry in {retry_after}s")
    elif e.code == "QUOTA_EXCEEDED":
        print("Upgrade your plan or wait for quota reset")
    elif e.status_code >= 500:
        print("Server error - safe to retry")
    else:
        raise
```

## Retry Behavior

The SDK includes automatic retry logic for transient failures.

### Default Retry Configuration

```python
client = AragoraClient(
    base_url="http://localhost:8080",
    # Retry configuration (defaults shown)
    max_retries=3,              # Maximum retry attempts
    retry_delay=1.0,            # Initial delay in seconds
    retry_backoff=2.0,          # Exponential backoff multiplier
    retry_max_delay=30.0,       # Maximum delay between retries
    retry_on_status=[429, 500, 502, 503, 504],  # HTTP codes to retry
)
```

### Retry Semantics

1. **Exponential Backoff**: Each retry waits `delay * (backoff ^ attempt)`
2. **Jitter**: Random 0-25% jitter added to prevent thundering herd
3. **Respect Retry-After**: 429 responses with `Retry-After` header are honored
4. **Idempotency**: Only idempotent requests (GET, PUT, DELETE) are retried by default
5. **Circuit Breaker**: After repeated failures, requests fail fast for 60s

### Manual Retry Control

```python
from aragora.client import AragoraClient, RetryConfig

# Disable automatic retries
client = AragoraClient(
    base_url="http://localhost:8080",
    retry=RetryConfig(enabled=False),
)

# Custom retry configuration
client = AragoraClient(
    base_url="http://localhost:8080",
    retry=RetryConfig(
        max_retries=5,
        retry_delay=2.0,
        retry_backoff=1.5,
        retry_on_status=[429, 503],
    ),
)
```

### Per-Request Retry Override

```python
# Disable retry for a single request
debate = client.debates.get(debate_id, retry=False)

# Custom retry for a single request
debate = client.debates.run(
    task="...",
    retry=RetryConfig(max_retries=5, retry_delay=5.0),
)
```

### TypeScript SDK Retry

```typescript
import { createClient, RetryConfig } from '@aragora/sdk';

const client = createClient({
  baseUrl: 'https://api.aragora.ai',
  apiKey: 'your-key',
  retry: {
    maxRetries: 3,
    retryDelay: 1000,  // milliseconds
    retryBackoff: 2.0,
    retryOnStatus: [429, 500, 502, 503, 504],
  },
});

// Per-request override
const debate = await client.debates.get(debateId, { retry: false });
```

## Examples

### Basic Debate Workflow

```python
from aragora.client import AragoraClient

client = AragoraClient(base_url="http://localhost:8080")

# Run a complete debate
debate = client.debates.run(
    task="Design a secure authentication system",
    agents=["anthropic-api", "openai-api", "mistral-api"],
    rounds=3,
    consensus="majority",
)

consensus = debate.get("consensus", {})
if consensus and consensus.get("reached"):
    print(f"Agreement: {consensus.get('agreement', 0):.0%}")
    print(f"Answer: {consensus.get('final_answer')}")
else:
    print("No consensus reached")
    for round_data in debate.get("rounds", []):
        for msg in round_data.get("messages", []):
            print(f"{msg.get('agent_id')}: {msg.get('content', '')[:100]}...")
```

### Streaming Debate Events (Python)

```python
import asyncio
from aragora.streaming import AragoraWebSocket

async def stream_debate(debate_id: str):
    ws = AragoraWebSocket(base_url="https://api.aragora.ai", api_key="YOUR_API_KEY")

    def on_message(event):
        data = event.get("data", {}) if isinstance(event, dict) else {}
        print(data.get("content", ""))

    ws.on("agent_message", on_message)
    await ws.connect(debate_id=debate_id)

    # Wait for consensus (or handle any other events)
    await ws.once("consensus", timeout=60)
    await ws.disconnect()

asyncio.run(stream_debate("debate-123"))
```

**Dependency:** `pip install websockets`
**Auth:** `api_key` is sent as a `token` query parameter. Header-based auth is
also supported for proxy-based or server-side clients.

### Gauntlet for Policy Review

```python
from aragora.client import AragoraClient

client = AragoraClient(base_url="http://localhost:8080")

policy = """
Privacy Policy:
We collect user email and browsing history.
Data is stored indefinitely.
Third parties may access data for advertising.
"""

result = client.gauntlet.run_and_wait(
    task=f"Review this privacy policy for GDPR compliance: {policy}",
    attack_rounds=5,
    timeout=900,
)

print(f"Verdict: {result.get('verdict')}")

for finding in result.get("findings", []):
    severity = finding.get("severity", "")
    if severity in ("critical", "high"):
        print(f"\n[{severity.upper()}] {finding.get('title')}")
        print(f"  {finding.get('description')}")
        if finding.get("mitigation"):
            print(f"  Fix: {finding['mitigation']}")
```

### Matrix Debate for Decision Analysis

```python
import asyncio
from aragora.client import AragoraClient

async def analyze_decision():
    async with AragoraClient(base_url="http://localhost:8080") as client:
        # Compare microservices decision across team sizes
        response = await client.matrix_debates.create_async(
            task="Should we refactor our monolith to microservices?",
            scenarios=[
                {"name": "startup", "parameters": {"team_size": 5, "budget": "low"}},
                {"name": "scaleup", "parameters": {"team_size": 25, "budget": "medium"}},
                {"name": "enterprise", "parameters": {"team_size": 100, "budget": "high"}},
            ],
        )

        # Wait for completion (poll)
        import asyncio
        while True:
            matrix = await client.matrix_debates.get_async(response.matrix_id)
            if matrix.status.value in ("completed", "failed"):
                break
            await asyncio.sleep(5)

        conclusions = await client.matrix_debates.get_conclusions_async(response.matrix_id)

        print("Universal conclusions:")
        for c in conclusions.universal:
            print(f"  - {c}")

        print("\nConditional conclusions:")
        for scenario, findings in conclusions.conditional.items():
            print(f"\n  {scenario}:")
            for f in findings:
                print(f"    - {f}")

asyncio.run(analyze_decision())
```

## Related Documentation

- [SDK Quickstart](./sdk-quickstart) - Install to first debate in 2 minutes
- [API Reference](../api/reference) - Full REST API documentation
- [WebSocket Events](./websocket-events) - Real-time streaming events
- [Gauntlet Guide](./gauntlet) - Adversarial validation details
- [Graph Debates](./graph-debates) - Branching debate documentation
- [Matrix Debates](./matrix-debates) - Parallel scenario debates
