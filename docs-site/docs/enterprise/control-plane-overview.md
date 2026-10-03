---
title: Aragora Control Plane
description: Aragora Control Plane
---

# Aragora Control Plane

**Enterprise orchestration for multi-agent vetted decisionmaking**

---

## Overview

The Aragora Control Plane is the central orchestration layer that manages multi-agent vetted decisionmaking across your organization's knowledge and communication channels. It provides:

- **Agent Orchestration**: Coordinate 46 agent types with role assignment and capability matching
- **Task Scheduling**: Priority-based task distribution with Redis-backed queues
- **Service Discovery**: Agent registry with heartbeat-based liveness tracking
- **Multi-Region Support**: Regional routing for compliance and latency optimization
- **Governance**: Policy enforcement, RBAC, and audit logging

Terminology note: in the API and worker identifiers, vetted decisionmaking
sessions are called "deliberations".

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     ARAGORA CONTROL PLANE                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Coordinator │  │   Registry   │  │  Scheduler   │          │
│  │              │  │              │  │              │          │
│  │ - Unified    │  │ - Service    │  │ - Priority   │          │
│  │   API        │  │   discovery  │  │   queues     │          │
│  │ - State      │  │ - Heartbeat  │  │ - Capability │          │
│  │   management │  │   tracking   │  │   matching   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Leader     │  │  Shared      │  │  Multi-      │          │
│  │   Election   │  │  State       │  │  Tenancy     │          │
│  │              │  │              │  │              │          │
│  │ - Distributed│  │ - Agent/task │  │ - Workspace  │          │
│  │   consensus  │  │   visibility │  │   isolation  │          │
│  │ - Failover   │  │ - Dashboard  │  │ - Quota mgmt │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       AGENT POOL                                │
├─────────────────────────────────────────────────────────────────┤
│  Claude │ GPT │ Gemini │ Grok │ Mistral │ DeepSeek │ Qwen │ ... │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. ControlPlaneCoordinator

The unified API for agent and task coordination.

**Location:** `aragora/control_plane/coordinator.py`

```python
from aragora.control_plane import ControlPlaneCoordinator

coordinator = ControlPlaneCoordinator()

# Register an agent
await coordinator.register_agent(
    agent_id="claude-1",
    capabilities=["reasoning", "code_review", "synthesis"],
    region="us-east-1"
)

# Submit a task
task_id = await coordinator.submit_task(
    task_type="deliberation",
    payload={"topic": "API design review"},
    required_capabilities=["reasoning", "code_review"]
)

# Get task status
status = await coordinator.get_task_status(task_id)
```

### 2. AgentRegistry

Service discovery with heartbeat-based liveness tracking.

**Location:** `aragora/control_plane/registry.py`

Agent states:
- `STARTING` - Agent is initializing
- `READY` - Agent is available for tasks
- `BUSY` - Agent is processing a task
- `DRAINING` - Agent is finishing current work before shutdown
- `OFFLINE` - Agent is not responding
- `FAILED` - Agent encountered an error

### 3. TaskScheduler

Redis-backed priority task distribution with capability matching.

**Location:** `aragora/control_plane/scheduler.py`

Features:
- Priority queues (critical, high, normal, low)
- Capability-based routing
- Regional affinity
- Retry with exponential backoff
- Dead letter queues
- Policy enforcement on submit/claim via `ControlPlanePolicyManager`

### 4. LeaderElection

Distributed leader election for multi-node deployments.

**Location:** `aragora/control_plane/leader.py`

Uses Redis-based locking for leader election with automatic failover.

### 4.1 Policy Sync

In production, control plane policies are loaded from the compliance policy
store. Policies should include a `control_plane_policy` payload in their
metadata to be applied at dispatch time.

Override behavior for testing with:

```bash
# Force in-process policies only (skip store sync)
export ARAGORA_CONTROL_PLANE_POLICY_SOURCE=inprocess
```

### 5. NotificationDispatcher

Resilient notification delivery for control plane events and outputs.

**Location:** `aragora/control_plane/notifications.py`

Features:
- Retry with exponential backoff + jitter
- Circuit breaker per channel
- Redis Streams persistence (optional)
- SMTP email provider for escalation paths
- Task lifecycle events via `aragora/control_plane/task_events.py`
- Vetted decisionmaking consensus notifications from `aragora/control_plane/deliberation.py`

---

## Deployment Modes

### Single-Node (Development)

All control plane components run in a single process.

```bash
aragora serve --api-port 8080 --ws-port 8765
```

### Multi-Instance (Production)

Multiple server instances with shared Redis state.

```bash
export ARAGORA_MULTI_INSTANCE=true
export REDIS_URL=redis://redis:6379

# Start multiple instances
aragora serve --api-port 8080 --ws-port 8765
aragora serve --api-port 8081 --ws-port 8766
```

### Multi-Region (Enterprise)

Regional deployments with cross-region coordination.

```yaml
# deploy/multi-region/helm/aragora/values.yaml
regions:
  - name: us-east-1
    primary: true
  - name: eu-west-1
    primary: false
```

---

## Demo Script

Use the control plane demo to validate orchestration, queues, and channel routing:

```bash
python scripts/demo_control_plane.py
python scripts/demo_control_plane.py --quick
python scripts/demo_control_plane.py --agents 5
python scripts/demo_control_plane.py --simulate-load
```

Requirements:
- Redis running locally (for task queue)
- Optional: `SLACK_WEBHOOK_URL` for demo notifications

---

## REST API

The control plane API is versioned under `/api/v1/control-plane` with legacy
aliases under `/api/control-plane` for backward compatibility.

### Agent Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/control-plane/agents` | Register an agent |
| `GET` | `/api/control-plane/agents` | List all agents |
| `GET` | `/api/control-plane/agents/\{id\}` | Get agent details |
| `DELETE` | `/api/control-plane/agents/\{id\}` | Deregister an agent |
| `POST` | `/api/control-plane/agents/\{id\}/heartbeat` | Send heartbeat |

### Task Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/control-plane/tasks` | Submit a task |
| `GET` | `/api/control-plane/tasks/\{id\}` | Get task status |
| `POST` | `/api/control-plane/tasks/\{id\}/complete` | Complete a task |
| `POST` | `/api/control-plane/tasks/\{id\}/fail` | Fail a task |
| `POST` | `/api/control-plane/tasks/\{id\}/cancel` | Cancel a task |
| `POST` | `/api/control-plane/tasks/claim` | Claim the next task |

### Vetted Decisionmaking Endpoints (Deliberations)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/control-plane/deliberations` | Run or queue a vetted decisionmaking session |
| `GET` | `/api/control-plane/deliberations/\{id\}` | Get vetted decisionmaking result |
| `GET` | `/api/control-plane/deliberations/\{id\}/status` | Get vetted decisionmaking status |

### Queue Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/control-plane/queue` | Pending and running tasks |

### Health & Metrics Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/control-plane/health` | System health |
| `GET` | `/api/control-plane/health/\{agent_id\}` | Agent health |
| `GET` | `/api/control-plane/stats` | Scheduler and registry stats |
| `GET` | `/api/control-plane/metrics` | Dashboard metrics |

### Notification Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/control-plane/notifications` | List recent notifications |
| `GET` | `/api/control-plane/notifications/stats` | Notification delivery statistics |

### Audit Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/control-plane/audit` | Query audit log entries |
| `GET` | `/api/control-plane/audit/stats` | Audit log statistics |
| `GET` | `/api/control-plane/audit/verify` | Verify audit log integrity |

---

## Integration with Knowledge Mound

The control plane integrates with the Knowledge Mound for organizational knowledge accumulation.

```python
from aragora.control_plane import ControlPlaneCoordinator
from aragora.knowledge.mound import KnowledgeMound

coordinator = ControlPlaneCoordinator()
mound = KnowledgeMound()

# Submit a task that uses Knowledge Mound context
task_id = await coordinator.submit_task(
    task_type="deliberation",
    payload={
        "topic": "Security architecture review",
        "knowledge_context": await mound.retrieve_context("security policies")
    }
)
```

---

## Observability

### Metrics

The control plane exports Prometheus metrics:

- `aragora_agents_total` - Total registered agents
- `aragora_agents_active` - Currently active agents
- `aragora_tasks_submitted_total` - Total tasks submitted
- `aragora_tasks_completed_total` - Completed tasks
- `aragora_task_latency_seconds` - Task processing latency

### Dashboard

Access the control plane dashboard at `/control-plane`.

Features:
- Real-time agent status
- Task queue visualization
- Performance metrics
- Audit log viewer

### UI Components

The control plane dashboard includes specialized widgets:

| Component | Purpose |
|-----------|---------|
| `FleetStatusWidget` | Real-time agent fleet overview with health indicators |
| `FleetHealthGauge` | Visual gauge showing fleet health percentage |
| `ActivityFeed` | Real-time event timeline for system activity |
| `DeliberationTracker` | In-flight vetted decisionmaking progress with round tracking |
| `SystemHealthDashboard` | Comprehensive system health monitoring |
| `ConnectorDashboard` | Data connector status and sync timeline |
| `KnowledgeExplorer` | Knowledge Mound browser with graph visualization |

### Demo Script

Run the control plane demo to see all features in action:

```bash
# Full demo
python scripts/demo_control_plane.py

# Quick 2-minute demo
python scripts/demo_control_plane.py --quick

# Custom agent count
python scripts/demo_control_plane.py --agents 10

# Include load simulation
python scripts/demo_control_plane.py --simulate-load
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_MULTI_INSTANCE` | `false` | Enable multi-instance mode |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL |
| `CONTROL_PLANE_HEARTBEAT_INTERVAL` | `30` | Heartbeat interval in seconds |
| `CONTROL_PLANE_AGENT_TIMEOUT` | `90` | Agent timeout in seconds |
| `CONTROL_PLANE_MAX_RETRIES` | `3` | Maximum task retries |

### YAML Configuration

```yaml
# config/control_plane.yaml
control_plane:
  heartbeat_interval: 30
  agent_timeout: 90
  max_retries: 3
  queues:
    critical:
      max_size: 100
      workers: 4
    normal:
      max_size: 1000
      workers: 2
```

---

## Security

### Authentication

The control plane requires API token authentication for all endpoints.

```bash
export ARAGORA_API_TOKEN=your-secret-token
```

### RBAC

Control plane operations require specific permissions:

| Operation | Permission |
|-----------|------------|
| Register agent | `control_plane:agents:write` |
| View agents | `control_plane:agents:read` |
| Submit task | `control_plane:tasks:write` |
| Cancel task | `control_plane:tasks:delete` |

See [GOVERNANCE.md](./governance) for full RBAC documentation.

---

## Channel Notifications

The control plane includes multi-channel notification delivery:

### Supported Channels

| Channel | Description |
|---------|-------------|
| Slack | Workspace integration via webhooks or app |
| Microsoft Teams | Teams channel notifications |
| Email | SMTP-based email delivery |
| Webhook | Generic HTTP webhooks for custom integrations |

### Configuration

```python
from aragora.control_plane.channels import ChannelRouter, ChannelConfig

router = ChannelRouter()

# Configure Slack channel
await router.configure_channel(ChannelConfig(
    channel_type="slack",
    name="#ai-alerts",
    webhook_url=os.environ["SLACK_WEBHOOK_URL"],
    events=["deliberation.consensus", "task.failed", "agent.offline"]
))
```

### Event Types

- `agent.registered` - New agent joined the fleet
- `agent.offline` - Agent became unresponsive
- `task.submitted` - New task queued
- `task.completed` - Task finished successfully
- `task.failed` - Task failed after retries
- `deliberation.started` - Vetted decisionmaking session began
- `deliberation.consensus` - Consensus was reached
- `deliberation.failed` - No consensus reached or vetted decisionmaking failed

---

## Audit Logging

Enterprise-grade immutable audit logging with cryptographic hash chain verification.

### Features

- **Append-only log** - Entries cannot be modified or deleted
- **Hash chain verification** - Cryptographic integrity verification
- **Tamper detection** - Automatic detection of log tampering
- **Queryable** - Filter by action, actor, resource, or time range

### Usage

```python
from aragora.control_plane.audit import AuditLog, AuditAction

audit = AuditLog()

# Log an action
await audit.log(
    action=AuditAction.TASK_SUBMITTED,
    actor="user:admin@company.com",
    resource="task-abc123",
    details={"priority": "high", "type": "deliberation"}
)

# Query recent entries
entries = await audit.query(
    actions=[AuditAction.TASK_COMPLETED, AuditAction.TASK_FAILED],
    since=datetime.utcnow() - timedelta(hours=24)
)

# Verify integrity
is_valid = await audit.verify_integrity()
```

### Audit Actions

| Action | Description |
|--------|-------------|
| `agent.registered` | Agent registered with registry |
| `agent.deregistered` | Agent removed from registry |
| `task.submitted` | Task added to queue |
| `task.claimed` | Task claimed by agent |
| `task.completed` | Task completed successfully |
| `task.failed` | Task failed |
| `deliberation.started` | Vetted decisionmaking initiated |
| `deliberation.consensus` | Consensus reached |
| `notification.sent` | Notification delivered |
| `policy.evaluated` | Policy check performed |

---

## Related Documentation

- [GOVERNANCE.md](./governance) - Policies, RBAC, and audit logging
- [CHANNELS.md](../guides/channels) - Channel integrations and bidirectional communication
- [CONNECTORS.md](../guides/connectors) - Data connectors for organizational knowledge
