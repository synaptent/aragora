# Control Plane Guide

Enterprise orchestration system for managing heterogeneous AI agents in distributed environments.

## Overview

The Aragora Control Plane provides centralized coordination for AI agents with:

- **Service Discovery**: Automatic agent registration and heartbeat-based liveness tracking
- **Task Scheduling**: Priority-based task distribution with capability matching
- **Health Monitoring**: Liveness probes and circuit breaker integration
- **Load Balancing**: Intelligent agent selection strategies

```
┌─────────────────────────────────────────────────────────┐
│                  Control Plane                          │
│   AgentRegistry │ TaskScheduler │ HealthMonitor         │
├─────────────────────────────────────────────────────────┤
│                  Redis Backend                          │
│   Service Discovery │ Job Queue │ Health Probes         │
└─────────────────────────────────────────────────────────┘
```

## Quick Start

### Demo Script

```bash
python scripts/demo_control_plane.py
```

Use `--quick` for a 2-minute walkthrough and `--simulate-load` to stress the
queue. See `docs/CONTROL_PLANE.md` for full options.

### Python API

```python
from aragora.control_plane import ControlPlaneCoordinator, create_control_plane

# Create and connect
coordinator = await create_control_plane()

# Register an agent
await coordinator.register_agent(
    agent_id="claude-3",
    capabilities=["debate", "code", "analysis"],
    model="claude-3-opus",
    provider="anthropic",
    metadata={"version": "3.5"}
)

# Submit a task
task_id = await coordinator.submit_task(
    task_type="debate",
    payload={"question": "Should we use microservices?"},
    required_capabilities=["debate"],
)

# Wait for result
result = await coordinator.wait_for_result(task_id, timeout=60.0)
print(result.result)

# Shutdown
await coordinator.shutdown()
```

### REST API

All endpoints are available under `/api/v1/control-plane` with legacy aliases
under `/api/control-plane`. Examples below use the legacy path for brevity.

Terminology note: in the API and worker identifiers, vetted decisionmaking
sessions are called "deliberations".

Authentication is required. Task and vetted decisionmaking operations
(deliberations in the API) require the
`controlplane:tasks` permission; agent registration and management require
`controlplane:agents`.

```bash
# Register an agent
curl -X POST http://localhost:8080/api/control-plane/agents \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "claude-3",
    "capabilities": ["debate", "code"],
    "model": "claude-3-opus",
    "provider": "anthropic"
  }'

# Submit a task
curl -X POST http://localhost:8080/api/control-plane/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "debate",
    "payload": {"question": "What is the best design pattern?"},
    "required_capabilities": ["debate"],
    "priority": "normal"
  }'

# Check task status
curl http://localhost:8080/api/control-plane/tasks/{task_id}
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `CONTROL_PLANE_PREFIX` | `aragora:cp:` | Key prefix for Redis keys |
| `HEARTBEAT_INTERVAL` | `10` | Agent heartbeat interval (seconds) |
| `HEARTBEAT_TIMEOUT` | `30` | Seconds before agent marked offline |
| `PROBE_INTERVAL` | `30` | Health probe interval (seconds) |
| `PROBE_TIMEOUT` | `10` | Health probe timeout (seconds) |
| `TASK_TIMEOUT` | `300` | Default task timeout (seconds) |
| `MAX_TASK_RETRIES` | `3` | Maximum task retry attempts |
| `CLEANUP_INTERVAL` | `60` | Stale agent cleanup interval (seconds) |
| `ARAGORA_CONTROL_PLANE_POLICY_SOURCE` | `auto` | Policy source: `compliance` or `inprocess` | Auto (compliance in production) |

### Programmatic Configuration

```python
from aragora.control_plane import ControlPlaneConfig, ControlPlaneCoordinator

config = ControlPlaneConfig(
    redis_url="redis://localhost:6379",
    key_prefix="myapp:cp:",
    heartbeat_timeout=60.0,
    task_timeout=600.0,
)

coordinator = await ControlPlaneCoordinator.create(config)
```

## Components

### Agent Registry

The `AgentRegistry` manages service discovery for AI agents.

#### Agent Status

| Status | Description |
|--------|-------------|
| `STARTING` | Agent is initializing |
| `READY` | Agent is available for tasks |
| `BUSY` | Agent is processing a task |
| `DRAINING` | Completing current task, no new tasks |
| `OFFLINE` | Agent is not responding |
| `FAILED` | Agent has failed |

#### Agent Capabilities

Standard capabilities supported:

| Capability | Description |
|------------|-------------|
| `debate` | Can participate in debates |
| `code` | Can write/analyze code |
| `analysis` | Can perform analysis tasks |
| `critique` | Can critique other agents' work |
| `judge` | Can serve as a debate judge |
| `implement` | Can implement code changes |
| `design` | Can create designs/architectures |
| `research` | Can perform research tasks |
| `audit` | Can perform audits |
| `summarize` | Can summarize content |

Custom capabilities can be added as strings.

#### Registration Example

```python
from aragora.control_plane import AgentCapability

agent = await coordinator.register_agent(
    agent_id="my-agent",
    capabilities=[
        AgentCapability.DEBATE,
        AgentCapability.CODE,
        "custom-capability",  # Custom string capability
    ],
    model="gpt-4",
    provider="openai",
    metadata={
        "version": "1.0",
        "region": "us-east-1",
    },
)

print(f"Registered: {agent.agent_id}")
print(f"Status: {agent.status.value}")
```

#### Heartbeats

Agents must send periodic heartbeats to remain in the active pool:

```python
# Send heartbeat
await coordinator.heartbeat("my-agent")

# Send heartbeat with status update
from aragora.control_plane import AgentStatus
await coordinator.heartbeat("my-agent", status=AgentStatus.BUSY)
```

REST API:
```bash
curl -X POST http://localhost:8080/api/control-plane/agents/my-agent/heartbeat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status": "busy"}'
```

### Task Scheduler

The `TaskScheduler` handles task distribution with priority-based queuing.

#### Task Priority

| Priority | Value | Description |
|----------|-------|-------------|
| `CRITICAL` | 0 | Immediate execution |
| `HIGH` | 1 | Urgent tasks |
| `NORMAL` | 2 | Default priority |
| `LOW` | 3 | Background tasks |

#### Task Status

| Status | Description |
|--------|-------------|
| `PENDING` | Waiting in queue |
| `CLAIMED` | Claimed by an agent |
| `RUNNING` | Being executed |
| `COMPLETED` | Successfully completed |
| `FAILED` | Failed (may be retried) |
| `CANCELLED` | Manually cancelled |
| `TIMEOUT` | Exceeded timeout |

#### Task Lifecycle

```python
from aragora.control_plane import TaskPriority

# 1. Submit task
task_id = await coordinator.submit_task(
    task_type="code_review",
    payload={"file": "main.py", "diff": "..."},
    required_capabilities=["code", "critique"],
    priority=TaskPriority.HIGH,
    timeout_seconds=120,
    metadata={"pr_id": "123"},
)

# 2. Claim task (from agent side)
task = await coordinator.claim_task(
    agent_id="my-agent",
    capabilities=["code", "critique"],
    block_ms=5000,  # Wait up to 5s for a task
)

if task:
    # 3. Process task
    try:
        result = process_task(task.payload)

        # 4a. Complete task
        await coordinator.complete_task(
            task_id=task.id,
            result={"review": result},
            agent_id="my-agent",
            latency_ms=1500.0,
        )
    except Exception as e:
        # 4b. Fail task
        await coordinator.fail_task(
            task_id=task.id,
            error=str(e),
            agent_id="my-agent",
            requeue=True,  # Retry with another agent
        )
```

### Notifications & Task Events

Task lifecycle events emit notifications through the NotificationDispatcher:

- Task events (`submitted`, `claimed`, `completed`, `failed`) are emitted via
  `aragora/control_plane/task_events.py`.
- Vetted decisionmaking consensus events are emitted by
  `aragora/control_plane/deliberation.py` and routed through the control plane
  integration callback.

Configure channels in `docs/CONTROL_PLANE.md` and ensure the notification worker
is enabled (`ARAGORA_NOTIFICATION_WORKER=1`).

### Health Monitor

The `HealthMonitor` tracks agent health and integrates with circuit breakers.

#### Health Status

| Status | Description |
|--------|-------------|
| `HEALTHY` | All checks passing |
| `DEGRADED` | Some issues detected |
| `UNHEALTHY` | Critical failures |
| `UNKNOWN` | No health data |

#### Health Probes

Register custom health probes for agents:

```python
def my_health_probe() -> bool:
    # Return True if healthy
    return check_model_connection()

await coordinator.register_agent(
    agent_id="my-agent",
    capabilities=["debate"],
    health_probe=my_health_probe,
)
```

#### Querying Health

```python
# Get specific agent health
health = coordinator.get_agent_health("my-agent")
print(f"Status: {health.status.value}")
print(f"Last check: {health.last_check}")
print(f"Consecutive failures: {health.consecutive_failures}")

# Get system health
system_health = coordinator.get_system_health()
print(f"System status: {system_health.value}")

# Check if agent is available
if coordinator.is_agent_available("my-agent"):
    # Safe to assign tasks
    pass
```

## REST API Reference

### Agents

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/control-plane/agents` | List registered agents |
| `POST` | `/api/control-plane/agents` | Register an agent |
| `GET` | `/api/control-plane/agents/:id` | Get agent info |
| `DELETE` | `/api/control-plane/agents/:id` | Unregister agent |
| `POST` | `/api/control-plane/agents/:id/heartbeat` | Send heartbeat |

#### List Agents

```bash
# List all available agents
curl "http://localhost:8080/api/control-plane/agents"

# Filter by capability
curl "http://localhost:8080/api/control-plane/agents?capability=debate"

# Include offline agents
curl "http://localhost:8080/api/control-plane/agents?available=false"
```

Response:
```json
{
  "agents": [
    {
      "agent_id": "claude-3",
      "capabilities": ["debate", "code"],
      "status": "ready",
      "model": "claude-3-opus",
      "provider": "anthropic",
      "tasks_completed": 42,
      "avg_latency_ms": 1234.5
    }
  ],
  "total": 1
}
```

### Tasks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/control-plane/tasks` | Submit a task |
| `GET` | `/api/control-plane/tasks/:id` | Get task status |
| `POST` | `/api/control-plane/tasks/:id/complete` | Complete task |
| `POST` | `/api/control-plane/tasks/:id/fail` | Fail task |
| `POST` | `/api/control-plane/tasks/:id/cancel` | Cancel task |
| `POST` | `/api/control-plane/tasks/claim` | Claim next task |

#### Submit Task

```bash
curl -X POST http://localhost:8080/api/control-plane/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "debate",
    "payload": {
      "question": "What is the best programming language?",
      "context": "For web development"
    },
    "required_capabilities": ["debate"],
    "priority": "normal",
    "timeout_seconds": 300,
    "metadata": {
      "user_id": "123"
    }
  }'
```

Response:
```json
{
  "task_id": "task_abc123"
}
```

### Vetted Decisionmaking Sessions (Deliberations)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/control-plane/deliberations` | Run or queue a vetted decisionmaking session |
| `GET` | `/api/control-plane/deliberations/:id` | Get vetted decisionmaking result |
| `GET` | `/api/control-plane/deliberations/:id/status` | Get vetted decisionmaking status |

#### Submit Vetted Decisionmaking (Sync)

```bash
curl -X POST http://localhost:8080/api/control-plane/deliberations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Assess the security risk of this API design",
    "decision_type": "debate",
    "priority": "high",
    "response_channels": [{"platform": "http_api"}]
  }'
```

#### Submit Vetted Decisionmaking (Async)

```bash
curl -X POST http://localhost:8080/api/control-plane/deliberations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "Review this architecture for scalability risks",
    "decision_type": "debate",
    "async": true,
    "priority": "high",
    "required_capabilities": ["deliberation"]
  }'
```

Response:
```json
{
  "task_id": "task_abc123",
  "request_id": "req_xyz789",
  "status": "queued"
}
```

#### Run a Vetted Decisionmaking Worker (Deliberation Worker)

```bash
python scripts/control_plane_deliberation_worker.py --agent-id deliberation-worker-1
```

#### Poll Status

```bash
curl http://localhost:8080/api/control-plane/deliberations/req_xyz789/status
```

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/control-plane/health` | System health |
| `GET` | `/api/control-plane/health/:agent_id` | Agent health |
| `GET` | `/api/control-plane/stats` | Statistics |

#### System Health

```bash
curl http://localhost:8080/api/control-plane/health
```

Response:
```json
{
  "status": "healthy",
  "agents": {
    "claude-3": {
      "status": "healthy",
      "last_check": "2024-01-15T10:30:00Z",
      "consecutive_failures": 0
    }
  }
}
```

## Agent Selection Strategies

When selecting an agent for a task, the control plane supports multiple strategies:

### Least Loaded (Default)

Selects the agent with the fewest completed tasks (proxy for current load):

```python
agent = await coordinator.select_agent(
    capabilities=["debate"],
    strategy="least_loaded",
)
```

### Round Robin

Cycles through agents based on last heartbeat:

```python
agent = await coordinator.select_agent(
    capabilities=["debate"],
    strategy="round_robin",
)
```

### Random

Random selection from available agents:

```python
agent = await coordinator.select_agent(
    capabilities=["debate"],
    strategy="random",
)
```

### Excluding Agents

```python
agent = await coordinator.select_agent(
    capabilities=["debate"],
    strategy="least_loaded",
    exclude=["problematic-agent-1", "problematic-agent-2"],
)
```

## Error Handling

### Task Retries

Tasks that fail are automatically retried based on `max_task_retries`:

```python
task_id = await coordinator.submit_task(
    task_type="analysis",
    payload={...},
    required_capabilities=["analysis"],
)

# If the task fails, it will be requeued up to max_task_retries times
# unless requeue=False is passed to fail_task()
```

### Circuit Breakers

The control plane integrates with Aragora's circuit breaker system. Agents that fail repeatedly are temporarily excluded from task assignment.

### Graceful Degradation

When Redis is unavailable, the control plane falls back to an in-memory store, allowing local development without Redis.

## Best Practices

### Agent Implementation

1. **Send Regular Heartbeats**: Send heartbeats more frequently than `HEARTBEAT_TIMEOUT / 2`
2. **Report Status Changes**: Update status when transitioning between states
3. **Handle Graceful Shutdown**: Set status to `DRAINING` before shutdown
4. **Implement Health Probes**: Provide meaningful health checks

```python
import asyncio

async def agent_loop(coordinator, agent_id):
    # Register
    await coordinator.register_agent(
        agent_id=agent_id,
        capabilities=["debate"],
    )

    try:
        while running:
            # Claim task
            task = await coordinator.claim_task(
                agent_id=agent_id,
                capabilities=["debate"],
            )

            if task:
                # Process
                result = await process_task(task)
                await coordinator.complete_task(task.id, result, agent_id)

            # Heartbeat
            await coordinator.heartbeat(agent_id)
            await asyncio.sleep(5)
    finally:
        # Graceful shutdown
        await coordinator.heartbeat(agent_id, AgentStatus.DRAINING)
        await coordinator.unregister_agent(agent_id)
```

### Task Design

1. **Idempotent Tasks**: Design tasks to be safely retried
2. **Reasonable Timeouts**: Set timeouts appropriate for task complexity
3. **Granular Capabilities**: Use specific capabilities for better routing
4. **Include Metadata**: Add context for debugging and monitoring

### Monitoring

Query statistics regularly:

```python
stats = await coordinator.get_stats()

# Registry stats
print(f"Total agents: {stats['registry']['total_agents']}")
print(f"Available: {stats['registry']['available_agents']}")

# Scheduler stats
print(f"Pending tasks: {stats['scheduler']['pending_tasks']}")
print(f"Running tasks: {stats['scheduler']['running_tasks']}")

# Health stats
print(f"Healthy agents: {stats['health']['healthy_count']}")
```

## Troubleshooting

### Agent Shows Offline

1. Check if heartbeats are being sent
2. Verify Redis connectivity
3. Check `HEARTBEAT_TIMEOUT` configuration
4. Look for network issues between agent and Redis

### Tasks Not Being Processed

1. Verify agents have required capabilities
2. Check if agents are in `READY` status
3. Look for circuit breaker activations
4. Check task queue depth in statistics

### High Latency

1. Monitor Redis performance
2. Check for task accumulation
3. Consider adding more agents
4. Review task timeout settings

## Architecture Decisions

See [ADR-002: Control Plane Architecture](../ADR/009-control-plane-architecture.md) for detailed architectural decisions.

## Related Documentation

- [API Reference](../api/API_REFERENCE.md)
- [Environment Variables](../reference/ENVIRONMENT.md)
- [Deployment Guide](../DEPLOYMENT.md)
