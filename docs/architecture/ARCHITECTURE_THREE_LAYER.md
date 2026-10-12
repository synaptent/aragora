# Three-Layer Architecture: Aragora Core + Extensions

This document defines the layered architecture for Aragora as an enterprise
decision control plane with optional Gastown and OpenClaw (formerly Moltbot) extension layers.

## Design Principles

1. **Core stability**: Extensions must not destabilize the enterprise control plane
2. **Shared substrate**: All layers use a common Agent Fabric for orchestration
3. **Clean boundaries**: Each layer has explicit APIs and isolation guarantees
4. **Opt-in extensions**: Enterprise deployments can disable extension layers

## Architecture Overview

```
+------------------------------------------------------------------+
|                     Extension Layer: Consumer                      |
|  (OpenClaw parity: local gateway, voice, canvas, device nodes)     |
+------------------------------------------------------------------+
                              |
                    Extension APIs (gRPC/REST)
                              |
+------------------------------------------------------------------+
|                     Extension Layer: Developer                     |
|  (Gastown parity: workspace mgr, git hooks, convoys, Beads)       |
+------------------------------------------------------------------+
                              |
                    Extension APIs (gRPC/REST)
                              |
+------------------------------------------------------------------+
|                         Agent Fabric                               |
|  (Scheduler, Isolation, Policy, Budget, Telemetry, Lifecycle)     |
+------------------------------------------------------------------+
                              |
                    Internal APIs
                              |
+------------------------------------------------------------------+
|                         Aragora Core                               |
|  (Debate, Evidence, Consensus, Receipts, RBAC, Audit, Channels)   |
+------------------------------------------------------------------+
```

## Layer 1: Aragora Core (Enterprise Decision Control Plane)

**Purpose**: Vetted multi-agent decisionmaking with audit trails and evidence.

**Components**:
- `aragora/debate/` - Debate orchestration, consensus protocols
- `aragora/evidence/` - Evidence collection and provenance
- `aragora/memory/` - Institutional memory and knowledge
- `aragora/knowledge/` - Knowledge mound and bridges
- `aragora/rbac/` - Role-based access control
- `aragora/audit/` - Audit logging and compliance
- `aragora/server/` - HTTP/WebSocket API surface
- `aragora/connectors/` - Channel integrations (Slack, Teams, etc.)

**Guarantees**:
- Decision receipts are immutable and auditable
- Evidence chains are verifiable
- Multi-tenant isolation
- Enterprise SLA compliance

**APIs** (stable, versioned):
- `/api/v2/debates/*` - Debate lifecycle
- `/api/v2/evidence/*` - Evidence management
- `/api/v2/receipts/*` - Decision receipts
- `/api/v2/agents/*` - Agent management
- WebSocket streams for real-time events

## Layer 2: Agent Fabric (Shared Orchestration Substrate)

**Purpose**: High-scale agent scheduling, isolation, and policy enforcement.

**Components** (to build):
- `aragora/fabric/scheduler.py` - Agent task queue and scheduling
- `aragora/fabric/isolation.py` - Per-agent sandboxing and resource limits
- `aragora/fabric/policy.py` - Tool access, approvals, and restrictions
- `aragora/fabric/budget.py` - Cost tracking and enforcement
- `aragora/fabric/lifecycle.py` - Agent spawn, heartbeat, termination
- `aragora/fabric/telemetry.py` - Metrics, traces, and logs

**Capabilities**:
- Schedule 100+ concurrent agents with fair resource allocation
- Isolate agents via process/container boundaries
- Enforce tool access policies (which tools, which data, which actions)
- Track and limit costs per agent/user/tenant
- Full observability for debugging and compliance

**APIs** (internal, extension-facing):
- `fabric.spawn(agent_config)` - Start an agent with given constraints
- `fabric.schedule(task, agent_id)` - Queue work for an agent
- `fabric.enforce_policy(action, context)` - Check policy before execution
- `fabric.track_cost(agent_id, tokens, compute)` - Record usage
- `fabric.terminate(agent_id)` - Clean shutdown

## Layer 3a: Developer Extension (Gastown Parity)

**Purpose**: Developer workflow orchestration for multi-agent software engineering.

**Components** (to build):
- `aragora/extensions/gastown/workspace.py` - Workspace manager (projects, rigs)
- `aragora/worktree/hook_runner.py` - Git worktree persistence layer (re-exported as `aragora.extensions.gastown.hooks`)
- `aragora/extensions/gastown/convoy.py` - Work tracking units and state machine
- `aragora/extensions/gastown/beads.py` - Issue tracking ledger
- `aragora/extensions/gastown/mayor.py` - Coordinator agent interface
- `aragora/extensions/gastown/cli.py` - CLI workflows (gt commands)

**Features**:
- Workspace manager with per-repo "rigs" and agent pools
- Git worktree hooks for persistent agent state across restarts
- Convoy tracking with artifacts and handoffs
- Beads-style issue ledger for structured work tracking
- Dashboard for convoy/hook visibility

**APIs** (extension surface):
- `/api/v2/gastown/workspaces/*` - Workspace management
- `/api/v2/gastown/convoys/*` - Convoy lifecycle
- `/api/v2/gastown/hooks/*` - Hook status and control
- CLI: `aragora gt convoy start|status|complete`

## Layer 3b: Consumer Extension (OpenClaw Parity)

**Purpose**: Consumer-grade personal assistant with device integration.

**Components** (to build):
- `aragora/extensions/moltbot/gateway.py` - Local-first gateway service
- `aragora/extensions/moltbot/inbox.py` - Multi-channel inbox aggregator
- `aragora/extensions/moltbot/voice.py` - Voice wake and talk interface
- `aragora/extensions/moltbot/canvas.py` - Live Canvas (A2UI) renderer
- `aragora/extensions/moltbot/devices.py` - Device node registry
- `aragora/extensions/moltbot/onboarding.py` - Setup wizard
- `aragora/extensions/moltbot/pairing.py` - Security pairing and allowlists

**Features**:
- Local gateway for routing and auth (runs on user device)
- Unified inbox across WhatsApp, Telegram, Slack, Discord, etc.
- Voice wake word detection and speech I/O
- Live Canvas for visual interaction
- Device nodes for companion apps and capabilities
- Onboarding wizard for guided setup
- Security pairing with DM allowlists

**APIs** (extension surface):
- `/api/v2/moltbot/inbox/*` - Inbox management
- `/api/v2/moltbot/devices/*` - Device registration
- `/api/v2/moltbot/voice/*` - Voice session control
- Local gateway: `localhost:7654` (configurable)

## Cross-Cutting: Safe Computer Use

**Purpose**: Auditable, policy-gated computer control for task execution.

**Components**:
- `aragora/computer_use/actions.py` - Action definitions (click, type, scroll, wait)
- `aragora/computer_use/policies.py` - Policy enforcement and rules
- `aragora/computer_use/approval.py` - Explicit user approval gates
- `aragora/computer_use/executor.py` - Playwright-based action executor
- `aragora/computer_use/sandbox.py` - Sandbox providers (process/docker)
- `aragora/computer_use/orchestrator.py` - Orchestrator + audit trail

**Capabilities**:
- Browser automation with screenshot verification
- Shell commands with sandboxed execution
- Screen interaction with OCR and click verification
- Explicit approval prompts for sensitive actions
- Full audit trail with replay capability

## Deployment Profiles

### Enterprise (default)
- Aragora Core: enabled
- Agent Fabric: enabled
- Gastown Extension: disabled (opt-in)
- OpenClaw Extension: disabled (opt-in)
- Computer Use: disabled (opt-in)

### Developer Platform
- Aragora Core: enabled
- Agent Fabric: enabled
- Gastown Extension: enabled
- OpenClaw Extension: disabled
- Computer Use: enabled (with strict policies)

### Consumer Assistant
- Aragora Core: enabled (minimal surface)
- Agent Fabric: enabled
- Gastown Extension: disabled
- OpenClaw Extension: enabled
- Computer Use: enabled (with approval gates)

### Full Platform
- All layers enabled with appropriate isolation

## Security Boundaries

1. **Core <-> Fabric**: Internal APIs, mutual TLS in production
2. **Fabric <-> Extensions**: gRPC/REST with auth tokens
3. **Extensions <-> External**: OAuth2, API keys, device pairing
4. **Computer Use <-> Host**: Sandboxed execution, explicit approvals

## Next Steps

1. Implement Agent Fabric foundation (scheduler, isolation, policy)
2. Build Gastown extension prototype (workspace, hooks, convoys)
3. Build OpenClaw extension prototype (gateway, inbox, onboarding)
4. Add computer use MVP (browser, shell, approvals)
5. Document integration contracts and test extensively
