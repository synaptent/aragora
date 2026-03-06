# API Cookbook: 20 Common Patterns

Practical, runnable examples for the most common Aragora operations.
Each recipe is self-contained -- copy, paste, and run.

---

## Table of Contents

1. [Create a Basic Debate](#1-create-a-basic-debate)
2. [Create a Debate with Custom Agents](#2-create-a-debate-with-custom-agents)
3. [Use Different Consensus Modes](#3-use-different-consensus-modes)
4. [Stream Debate Events via WebSocket](#4-stream-debate-events-via-websocket)
5. [Get a Decision Receipt](#5-get-a-decision-receipt)
6. [Query Historical Debates](#6-query-historical-debates)
7. [Store and Search Knowledge](#7-store-and-search-knowledge)
8. [List and Rank Agents](#8-list-and-rank-agents)
9. [Calibrate Agent Performance](#9-calibrate-agent-performance)
10. [Run a Gauntlet Stress Test](#10-run-a-gauntlet-stress-test)
11. [Read and Write Memory Tiers](#11-read-and-write-memory-tiers)
12. [Run a Compliance Audit](#12-run-a-compliance-audit)
13. [Check RBAC Permissions](#13-check-rbac-permissions)
14. [Use the Workflow Engine](#14-use-the-workflow-engine)
15. [Export Debate Results](#15-export-debate-results)
16. [Configure Circuit Breakers](#16-configure-circuit-breakers)
17. [Run a Graph Debate](#17-run-a-graph-debate)
18. [Use the REST API Directly](#18-use-the-rest-api-directly)
19. [Build a Slack Integration](#19-build-a-slack-integration)
20. [Run Debates from the CLI](#20-run-debates-from-the-cli)

---

## 1. Create a Basic Debate

The minimal debate -- two agents, three rounds, majority consensus.

```python
import asyncio
from aragora import Arena, Environment, Agent
from aragora.debate.protocol import DebateProtocol

async def main():
    env = Environment(task="What database should we use for our analytics pipeline?")
    agents = [
        Agent(name="claude", model="anthropic"),
        Agent(name="gpt4", model="openai"),
    ]
    protocol = DebateProtocol(rounds=3, consensus="majority")
    arena = Arena(environment=env, agents=agents, protocol=protocol)
    result = await arena.run()
    print(result.final_answer)

asyncio.run(main())
```

## 2. Create a Debate with Custom Agents

Assign specific roles and stances for structured argumentation.

```python
import asyncio
from aragora import Arena, Environment, Agent, AgentRole, AgentStance
from aragora.debate.protocol import DebateProtocol

async def main():
    env = Environment(
        task="Should we migrate to Kubernetes?",
        context="We have 12 microservices, 3 engineers, and a $5K/month cloud budget.",
        roles=["proposer", "critic", "synthesizer"],
    )
    agents = [
        Agent(name="advocate", model="anthropic", stance=AgentStance.AFFIRMATIVE),
        Agent(name="skeptic", model="openai", stance=AgentStance.NEGATIVE),
        Agent(name="judge", model="anthropic", role=AgentRole.JUDGE),
    ]
    protocol = DebateProtocol(rounds=5, consensus="judge")
    arena = Arena(environment=env, agents=agents, protocol=protocol)
    result = await arena.run()
    print(f"Judge decision: {result.final_answer}")

asyncio.run(main())
```

## 3. Use Different Consensus Modes

Aragora supports 8 consensus mechanisms. Choose the right one for your use case.

```python
from aragora.debate.protocol import DebateProtocol

# Simple majority -- fastest, good for low-stakes decisions
quick = DebateProtocol(rounds=3, consensus="majority")

# Supermajority -- requires 80% agreement, good for policy decisions
careful = DebateProtocol(rounds=5, consensus="supermajority", consensus_threshold=0.8)

# Judge -- a designated agent makes the final call
judged = DebateProtocol(rounds=5, consensus="judge")

# Weighted -- votes weighted by ELO ratings (better agents count more)
weighted = DebateProtocol(rounds=5, consensus="weighted")

# Unanimous -- all agents must agree (strictest)
unanimous = DebateProtocol(rounds=7, consensus="unanimous")

# Byzantine -- PBFT-style fault-tolerant consensus
byzantine = DebateProtocol(rounds=5, consensus="byzantine")

# High-assurance -- supermajority + hollow consensus detection
high_assurance = DebateProtocol(
    consensus="supermajority",
    consensus_threshold=0.8,
    enable_trickster=True,  # Detect hollow consensus
    formal_verification_enabled=True,
)
```

## 4. Stream Debate Events via WebSocket

Watch a debate unfold in real time.

```python
import asyncio
import json
import websockets

async def stream_debate(debate_id: str):
    uri = f"ws://localhost:8080/ws/debate/{debate_id}"
    async with websockets.connect(uri) as ws:
        async for raw in ws:
            event = json.loads(raw)
            match event["type"]:
                case "debate_start":
                    print(f"Debate started: {event['task']}")
                case "agent_message":
                    print(f"[{event['agent']}] {event['content'][:200]}")
                case "critique":
                    print(f"  critique by {event['critic']}: {event['summary']}")
                case "vote":
                    print(f"  vote: {event['agent']} -> {event['choice']}")
                case "consensus":
                    print(f"CONSENSUS: {event['result']}")
                case "debate_end":
                    print("Debate complete.")
                    break

asyncio.run(stream_debate("debate-abc123"))
```

**Event types:** `debate_start`, `round_start`, `agent_message`, `critique`, `revision`, `vote`, `consensus`, `debate_end`, and 180+ more.

## 5. Get a Decision Receipt

A cryptographic audit trail of the debate outcome.

```python
from aragora.receipts import DecisionReceipt

# After running a debate
receipt = DecisionReceipt.from_debate_result(result)
print(f"Receipt ID: {receipt.receipt_id}")
print(f"Hash: {receipt.content_hash}")  # SHA-256
print(f"Decision: {receipt.decision_summary}")
print(f"Agents: {receipt.participating_agents}")
print(f"Consensus: {receipt.consensus_mechanism}")

# Verify integrity
assert receipt.verify(), "Receipt tampered with!"

# Export as JSON for audit systems
receipt_json = receipt.to_json()
```

## 6. Query Historical Debates

Search past debates by topic, outcome, or time range.

```bash
# Via REST API
curl "http://localhost:8080/api/v1/debates?query=kubernetes&limit=10"

# Get a specific debate
curl "http://localhost:8080/api/v1/debates/debate-abc123"

# Get debate analytics
curl "http://localhost:8080/api/v1/analytics/debates?period=7d"
```

```python
# Via Python SDK
from aragora_sdk import AragoraClient

client = AragoraClient(base_url="http://localhost:8080")
debates = client.debates.list(query="kubernetes", limit=10)
for d in debates:
    print(f"{d.id}: {d.task} -> {d.consensus}")
```

## 7. Store and Search Knowledge

Use the Knowledge Mound for persistent, searchable organizational knowledge.

```python
from aragora.knowledge.mound.coordinator import KnowledgeMoundCoordinator

coordinator = KnowledgeMoundCoordinator()

# Store knowledge
await coordinator.store(
    content="Our SLA requires 99.9% uptime for the payments service.",
    source="engineering-handbook",
    tags=["sla", "payments", "reliability"],
)

# Search by semantic similarity
results = await coordinator.search("what are our uptime requirements?", limit=5)
for r in results:
    print(f"[{r.score:.2f}] {r.content[:100]}")
```

```bash
# Via REST API
curl -X POST "http://localhost:8080/api/v1/knowledge/search" \
  -H "Content-Type: application/json" \
  -d '{"query": "uptime requirements", "limit": 5}'
```

## 8. List and Rank Agents

See which agents perform best across debates.

```python
from aragora.ranking.elo import EloSystem

elo = EloSystem()
rankings = elo.get_rankings()
for agent in rankings:
    print(f"{agent.name}: ELO {agent.rating:.0f} (W/L: {agent.wins}/{agent.losses})")
```

```bash
# Via CLI
aragora agents list
aragora agents rank

# Via REST API
curl "http://localhost:8080/api/v1/agents/rankings"
```

## 9. Calibrate Agent Performance

Track how well agents' confidence matches their actual accuracy.

```python
from aragora.ranking.elo import EloSystem

elo = EloSystem()

# Record a debate outcome
elo.record_match(
    winner="claude",
    loser="gpt4",
    domain="technical-architecture",
)

# Get calibration data
calibration = elo.get_calibration("claude")
print(f"Brier score: {calibration.brier_score:.3f}")  # Lower is better
print(f"Accuracy: {calibration.accuracy:.1%}")
```

## 10. Run a Gauntlet Stress Test

Adversarial probing to find weaknesses in a decision.

```bash
# CLI -- fastest way
aragora gauntlet "We should use MongoDB for our financial ledger"

# With specific probe strategies
aragora gauntlet "Our HIPAA compliance is complete" \
  --probes adversarial,edge_case,regulatory
```

```python
from aragora.gauntlet.runner import GauntletRunner

runner = GauntletRunner()
findings = await runner.run(
    claim="We should use MongoDB for our financial ledger",
    probe_strategies=["adversarial", "edge_case", "consistency"],
)
for f in findings:
    print(f"[{f.severity}] {f.description}")
```

## 11. Read and Write Memory Tiers

Aragora's 4-tier memory system persists knowledge at different time scales.

```python
from aragora.memory.continuum.memory import ContinuumMemory

memory = ContinuumMemory()

# Store in fast tier (1-minute TTL, immediate context)
await memory.store("The user prefers PostgreSQL", tier="fast")

# Store in slow tier (1-day TTL, cross-session learning)
await memory.store(
    "Team consensus: always benchmark before choosing a database",
    tier="slow",
    tags=["decision-pattern"],
)

# Retrieve relevant memories
memories = await memory.recall("database selection criteria", limit=5)
for m in memories:
    print(f"[{m.tier}] {m.content}")
```

| Tier | Default TTL | Use Case |
|------|-------------|----------|
| Fast | 1 minute | Immediate debate context |
| Medium | 1 hour | Session memory |
| Slow | 1 day | Cross-session patterns |
| Glacial | 1 week | Long-term institutional knowledge |

## 12. Run a Compliance Audit

Generate compliance reports against standard frameworks.

```python
from aragora.compliance.framework import ComplianceFramework
from aragora.compliance.report_generator import ReportGenerator

framework = ComplianceFramework.load("soc2")
generator = ReportGenerator(framework)

report = await generator.generate(
    scope=["access-control", "data-encryption", "audit-logging"],
)
print(f"Status: {report.overall_status}")
for control in report.controls:
    print(f"  [{control.status}] {control.id}: {control.name}")
```

```bash
# Via CLI
aragora compliance audit --framework soc2
aragora compliance audit --framework gdpr --scope "data-processing"
```

## 13. Check RBAC Permissions

Fine-grained access control with 360+ permissions.

```python
from aragora.rbac.checker import PermissionChecker
from aragora.rbac.models import AuthorizationContext

checker = PermissionChecker()

# Check a permission
ctx = AuthorizationContext(user_id="user-123", tenant_id="acme")
allowed = await checker.check(ctx, "debates:create")
print(f"Can create debates: {allowed}")

# In route handlers, use the decorator
from aragora.rbac.decorators import require_permission

@require_permission("debates:read")
async def list_debates(ctx: AuthorizationContext):
    return await get_debates(ctx.tenant_id)
```

## 14. Use the Workflow Engine

DAG-based automation for multi-step processes.

```python
from aragora.workflow.engine import WorkflowEngine
from aragora.workflow.nodes import DebateNode, ConditionNode, ActionNode

engine = WorkflowEngine()

# Define a workflow: debate -> review -> notify
workflow = engine.create_workflow("review-pipeline")
workflow.add_node(DebateNode(
    task="Review this PR for security issues",
    agents=["claude", "gpt4"],
    consensus="judge",
))
workflow.add_node(ConditionNode(
    condition=lambda result: result.confidence > 0.8,
    true_branch="approve",
    false_branch="escalate",
))
workflow.add_node(ActionNode(name="approve", action="merge_pr"))
workflow.add_node(ActionNode(name="escalate", action="notify_team"))

result = await engine.run(workflow)
```

## 15. Export Debate Results

Export to JSON, CSV, SARIF, or artifact bundles.

```python
from aragora.export.artifact import ArtifactBuilder
from aragora.export.csv_exporter import CSVExporter

# JSON export
with open("debate_result.json", "w") as f:
    f.write(result.to_json())

# CSV export
exporter = CSVExporter()
exporter.export_debates([result], "debates.csv")

# Full artifact bundle (includes messages, critiques, votes, receipt)
builder = ArtifactBuilder()
artifact = builder.build(result)
artifact.save("debate_artifact/")

# SARIF export (for code review results)
# aragora review path/to/code --sarif -o findings.sarif
```

## 16. Configure Circuit Breakers

Protect against cascading failures when API providers go down.

```python
from aragora.resilience.circuit_breaker import CircuitBreaker

# Circuit breaker opens after 5 failures in 60 seconds
breaker = CircuitBreaker(
    name="anthropic-api",
    failure_threshold=5,
    recovery_timeout=60,
    half_open_max_calls=2,
)

async def call_api():
    async with breaker:
        return await anthropic_client.complete(prompt)

# Check state
print(f"State: {breaker.state}")  # closed, open, or half_open
print(f"Failure count: {breaker.failure_count}")
```

## 17. Run a Graph Debate

Non-linear debates with counterfactual branching.

```python
import asyncio
from aragora import Arena, Environment, Agent
from aragora.debate.protocol import DebateProtocol

async def main():
    env = Environment(task="Design our disaster recovery strategy")
    agents = [
        Agent(name="cloud-architect", model="anthropic"),
        Agent(name="security-lead", model="openai"),
        Agent(name="cost-analyst", model="anthropic"),
    ]
    protocol = DebateProtocol(
        rounds=5,
        consensus="weighted",
        topology="star",  # Hub-and-spoke communication
        enable_forking=True,  # Allow debate branches on disagreement
    )
    arena = Arena(environment=env, agents=agents, protocol=protocol)
    result = await arena.run()
    print(result.final_answer)

asyncio.run(main())
```

## 18. Use the REST API Directly

All operations are available via REST.

```bash
# Start a debate
curl -X POST http://localhost:8080/api/v1/debates \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Should we adopt GraphQL?",
    "rounds": 3,
    "consensus": "majority",
    "agents": ["claude", "gpt4"]
  }'

# Get debate status
curl http://localhost:8080/api/v1/debates/{debate_id}

# Get agent rankings
curl http://localhost:8080/api/v1/agents/rankings

# Search knowledge
curl -X POST http://localhost:8080/api/v1/knowledge/search \
  -H "Content-Type: application/json" \
  -d '{"query": "deployment best practices", "limit": 10}'

# Health check
curl http://localhost:8080/health
```

## 19. Build a Slack Integration

Route debate results to Slack channels.

```python
from aragora.connectors.slack import SlackConnector

slack = SlackConnector(
    token="xoxb-your-slack-token",
    default_channel="#decisions",
)

# After a debate completes
await slack.send_result(
    channel="#architecture-decisions",
    result=result,
    include_receipt=True,
)
```

Or use the built-in Slack bot:

```bash
# Configure in .env
SLACK_BOT_TOKEN=xoxb-your-token
SLACK_SIGNING_SECRET=your-secret

# The bot responds to mentions
# @aragora Should we use Redis or Memcached for caching?
```

See [Bot Integrations](../integrations/BOT_INTEGRATIONS.md) for full setup.

## 20. Run Debates from the CLI

The CLI covers all common operations.

```bash
# Interactive debate
aragora ask "Should we rewrite in Rust?"

# With specific agents
aragora ask "Design a caching strategy" --agents claude,gpt4,gemini

# Quick 3-round debate
aragora ask "Best CI/CD tool for our team?" --rounds 3 --consensus majority

# Review code for issues
aragora review src/auth.py

# Gauntlet stress test
aragora gauntlet "Our deployment is production-ready"

# Start the server
aragora serve --api-port 8080 --ws-port 8765

# Health check
aragora doctor

# Manage backups
aragora backup create
aragora backup list
```

---

## Further Reading

| Resource | Description |
|----------|-------------|
| [Quickstart](QUICKSTART.md) | Get running in 5 minutes |
| [Getting Started](GETTING_STARTED.md) | Full onboarding guide |
| [API Reference](../api/API_REFERENCE.md) | Complete REST API docs |
| [WebSocket Events](../streaming/WEBSOCKET_EVENTS.md) | Real-time event reference |
| [SDK Guide](../SDK_GUIDE.md) | Python SDK |
| [TypeScript SDK](SDK_TYPESCRIPT.md) | TypeScript SDK |
| [Gauntlet](../debate/GAUNTLET.md) | Adversarial stress testing |
| [Knowledge Mound](../knowledge/KNOWLEDGE_MOUND.md) | Knowledge management |
