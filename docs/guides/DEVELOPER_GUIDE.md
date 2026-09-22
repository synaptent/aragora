# Aragora Developer Guide

Control plane for multi-agent robust decisionmaking across organizational knowledge and channels.

## Quick Start

### Installation

**Python SDK**
```bash
pip install aragora
```

**TypeScript SDK**
```bash
npm install @aragora/sdk
```

### Your First Debate

**Python**
```python
import asyncio
from aragora_sdk import AragoraClient

async def main():
    async with AragoraClient("http://localhost:8080") as client:
        # Run a debate and wait for completion
        debate = await client.debates.run(
            task="Should we adopt microservices architecture?",
            agents=["claude", "gpt-4"],
            max_rounds=3
        )
        print(f"Consensus: {debate.consensus.conclusion}")
        print(f"Confidence: {debate.consensus.confidence}")

asyncio.run(main())
```

**TypeScript**
```typescript
import { createClient } from '@aragora/sdk';

const client = createClient({ baseUrl: 'http://localhost:8080' });

const debate = await client.createDebate({
  task: 'Should we adopt microservices architecture?',
  agents: ['claude', 'gpt-4'],
  max_rounds: 3
});

// Stream debate events
for await (const event of client.streamDebate(debate.id)) {
  console.log(event.type, event.data);
}
```

## I Want To...

| Goal | Documentation |
|------|---------------|
| Run a debate | [SDK Quickstart (Python)](./python-quickstart.md) / [TypeScript](./typescript-quickstart.md) |
| Connect Slack | [Integration Guide](../integrations/INTEGRATIONS.md) |
| Deploy self-hosted | [Deployment Guide](../deployment/DEPLOYMENT.md) |
| Use the REST API | [API Reference](../api/API_REFERENCE.md) |
| Understand the architecture | [Architecture Overview](../architecture/ARCHITECTURE.md) |
| Contribute | [Contributing Guide](CONTRIBUTING.md) |

## SDK Overview

### Python SDK

The Python SDK provides async-first access to all Aragora APIs.

```python
from aragora_sdk import AragoraClient

client = AragoraClient(
    base_url="http://localhost:8080",
    api_key="your-api-key"  # Optional
)
```

**Available APIs:**
- `client.debates` - Create, run, and manage debates
- `client.agents` - Query agent profiles and rankings
- `client.memory` - Access memory analytics
- `client.gauntlet` - Run validation gauntlets
- `client.tournaments` - Manage agent tournaments
- `client.auth` - Authentication and API keys
- `client.tenants` - Multi-tenant management
- `client.organizations` - Organization membership and settings
- `client.policies` - Compliance policy management
- `client.explainability` - Decision explanations and evidence chains
- `client.batch` - Batch debate operations
- `client.routing` - Routing recommendations and rule management
- `client.critiques` - Critique patterns and agent reputation
- `client.a2a` - Agent-to-agent protocol endpoints
- `client.advertising` - Advertising platform integrations
- `client.cross_pollination` - Cross-pollination stats and subscriptions
- `client.bots` - Bot integration webhooks (Teams, Discord, Telegram, Zoom)
- `client.dashboard` - Dashboard overview and quick actions
- `client.deliberations` - Active deliberations and stats
- `client.devices` - Device registration and notifications
- `client.feedback` - NPS surveys and product feedback
- `client.gmail` - Gmail message operations
- `client.metrics` - Operational metrics and health
- `client.plugins` - Plugin management and marketplace
- `client.privacy` - GDPR/CCPA export and privacy preferences
- `client.queue` - Background job queue management
- `client.system` - Admin history, maintenance, and circuit breakers
- `client.threat_intel` - Threat intelligence scanning
- `client.unified_inbox` - Unified inbox routing and actions
- `client.rbac` - Role-based access control
- `client.audit` - Audit logging
- `client.control_plane` - System health and monitoring

### TypeScript SDK

The TypeScript SDK provides type-safe access with streaming support.

```typescript
import { createClient } from '@aragora/sdk';

const client = createClient({
  baseUrl: 'http://localhost:8080',
  apiKey: 'your-api-key'  // Optional
});
```

**Available APIs:**
- `client.createDebate()` / `client.getDebate()` / `client.listDebates()`
- `client.streamDebate()` - Real-time debate events via WebSocket
- `client.listAgents()` / `client.getAgent()`
- `client.createTournament()` / `client.getTournamentStandings()`
- `client.login()` / `client.register()` / `client.refreshToken()`
- `client.listTenants()` / `client.createTenant()`
- `client.listRoles()` / `client.assignRole()`
- `client.listAuditEvents()` / `client.exportAuditLogs()`

## Common Patterns

### Streaming Debates

Stream real-time events during a debate:

**Python**
```python
from aragora_sdk import stream_debate

async for event in stream_debate(client, debate_id):
    if event.type == "agent_message":
        print(f"{event.agent}: {event.content}")
    elif event.type == "consensus":
        print(f"Consensus reached: {event.conclusion}")
```

**TypeScript**
```typescript
const stream = client.streamDebate(debateId);

for await (const event of stream) {
  switch (event.type) {
    case 'agent_message':
      console.log(`${event.agent}: ${event.content}`);
      break;
    case 'consensus':
      console.log(`Consensus: ${event.conclusion}`);
      break;
  }
}
```

### Multi-Tenant Setup

Inspect tenant isolation for enterprise deployments. Tenant membership and quota
administration have no `aragora_sdk` method; call the server API directly.

```python
# List tenants
tenants = client.tenants.list(limit=50, status="active")
```

### Custom Agent Selection

Score and select optimal agent teams:

```python
# Score agents for a task
scores = await client.selection.score_agents(
    task_description="Review security implications of OAuth implementation",
    primary_domain="security"
)

# Select an optimal team
team = await client.selection.select_team(
    task_description="Design a rate limiting strategy",
    min_agents=3,
    max_agents=5,
    diversity_preference=0.7
)

print(f"Selected team: {[a.agent_id for a in team.agents]}")
```

### Gauntlet Validation

Run validation gauntlets on specifications:

```python
# Run a security-focused gauntlet
receipt = await client.gauntlet.run_and_wait(
    input_content=spec_content,
    input_type="spec",
    persona="security"
)

print(f"Findings: {len(receipt.findings)}")
for finding in receipt.findings:
    print(f"  - [{finding.severity}] {finding.title}")
```

## WebSocket Events

Connect to the WebSocket for real-time updates:

```
ws://localhost:8080/api/v1/ws/debates/{debate_id}
```

**Event Types:**
| Event | Description |
|-------|-------------|
| `debate_start` | Debate has started |
| `round_start` | New round beginning |
| `agent_message` | Agent response received |
| `critique` | Agent critique of another's response |
| `vote` | Voting phase update |
| `consensus` | Consensus reached |
| `debate_end` | Debate completed |

## Environment Variables

Required (at least one):
- `ANTHROPIC_API_KEY` - For Claude agents
- `OPENAI_API_KEY` - For GPT agents

Recommended:
- `OPENROUTER_API_KEY` - Fallback when primary APIs fail

Optional:
- `ARAGORA_API_TOKEN` - Server authentication
- `DATABASE_URL` - PostgreSQL connection
- `REDIS_URL` - Caching and sessions

See [Environment Reference](../reference/ENVIRONMENT.md) for full list.

## Error Handling

All SDK methods throw typed exceptions:

**Python**
```python
from aragora_sdk import (
    AragoraError,
    AragoraAuthenticationError,
    AragoraNotFoundError,
    AragoraValidationError,
    AragoraTimeoutError
)

try:
    debate = await client.debates.get("invalid-id")
except AragoraNotFoundError:
    print("Debate not found")
except AragoraAuthenticationError:
    print("Invalid API key")
except AragoraTimeoutError:
    print("Request timed out")
```

**TypeScript**
```typescript
import { AragoraError, NotFoundError, AuthError } from '@aragora/sdk';

try {
  const debate = await client.getDebate('invalid-id');
} catch (error) {
  if (error instanceof NotFoundError) {
    console.log('Debate not found');
  } else if (error instanceof AuthError) {
    console.log('Invalid API key');
  }
}
```

## Rate Limiting

The Aragora server enforces rate limits. Handle 429 responses:

```python
import asyncio
from aragora_sdk import AragoraError

async def retry_with_backoff(fn, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await fn()
        except AragoraError as e:
            if e.status == 429 and attempt < max_retries - 1:
                wait_time = 2 ** attempt
                await asyncio.sleep(wait_time)
            else:
                raise
```

## Resources

- [API Reference](../api/API_REFERENCE.md) - Complete REST API documentation
- [SDK Parity Report](SDK_PARITY.md) - Coverage comparison between SDKs
- [Enterprise Features](../ENTERPRISE_FEATURES.md) - Authentication, RBAC, multi-tenancy
- [Status](../STATUS.md) - Feature implementation status
- [Examples](../../examples/) - Ready-to-run example applications

## Getting Help

- **GitHub Issues**: [github.com/aragora/aragora/issues](https://github.com/aragora/aragora/issues)
- **Documentation**: [docs.aragora.ai](https://docs.aragora.ai)
- **Discord**: [discord.gg/aragora](https://discord.gg/aragora)
