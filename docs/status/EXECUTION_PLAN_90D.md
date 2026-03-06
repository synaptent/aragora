# 90-Day Execution Plan (Aragora Core + Gastown + OpenClaw Extensions)

**Last Updated:** 2026-01-28
**Status:** Phase 0-2 COMPLETE, Phase 3 IN PROGRESS

Objective: Preserve Aragora as the enterprise decision control plane while
building extension layers that can reach parity with Gastown (developer
orchestration) and OpenClaw (consumer/device interface).

**Key Decision:** BUILD all features independently in Aragora, adopting patterns
from Gastown and OpenClaw with proper attribution (see `docs/BUILD_VS_INTEGRATE.md`).

See also: `docs/PARITY_MATRIX_GASTOWN_MOLTBOT.md` for the full construct-level
mapping, gap analysis, and build-vs-integrate recommendations.

---

## Progress Summary

| Phase | Description | Status | Completion |
|-------|-------------|--------|------------|
| Phase 0 | Architecture Lock | DONE | 100% |
| Phase 1 | Agent Fabric Foundation | DONE | 100% |
| Phase 2 | Gastown Parity Prototype | DONE | 100% |
| Phase 3 | OpenClaw Parity Prototype | IN PROGRESS | 30% |
| Phase 4 | Safe Computer Use MVP | PENDING | 0% |
| Phase 5 | Integration Hardening | PENDING | 0% |

---

## Guiding Principles

1. **Core stability** -- Extensions must not destabilize the enterprise plane.
   All new modules live under `aragora/fabric/`, `aragora/workspace/`,
   `aragora/gateway/`, and `aragora/sandbox/`. No changes to `aragora/debate/`
   or `aragora/control_plane/` unless fixing bugs.
2. **Fabric first** -- Build the shared Agent Fabric (scheduling, isolation,
   budgets, policy) before any extension UX. Both Gastown and OpenClaw
   extensions depend on it.
3. **Feature flags** -- Every extension capability ships behind a flag so it
   can be disabled without code removal.
4. **Test parity** -- Every new module ships with >80% test coverage from day
   one. No untested code lands on main.
5. **Integration over rewrite** -- Reuse existing TaskScheduler, AgentRegistry,
   TenantContext, CostEnforcer, AirlockProxy, and Workflow Engine wherever
   possible.

---

## Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Extension Layer                           │
│  ┌──────────────────────┐  ┌──────────────────────────────┐ │
│  │ Gastown Extension    │  │ OpenClaw Extension            │ │
│  │ (Dev Orchestration)  │  │ (Consumer/Device Interface)  │ │
│  │                      │  │                              │ │
│  │ workspace/manager    │  │ gateway/server               │ │
│  │ workspace/convoy     │  │ gateway/inbox                │ │
│  │ workspace/rig        │  │ gateway/device_registry      │ │
│  │ workspace/hooks      │  │ onboarding/wizard            │ │
│  │ workspace/refinery   │  │ canvas/ (A2UI)               │ │
│  │ workspace/cli        │  │ voice/wake                   │ │
│  └──────────┬───────────┘  └──────────────┬───────────────┘ │
│             │                             │                  │
│  ┌──────────┴─────────────────────────────┴───────────────┐ │
│  │               Agent Fabric (Shared)                    │ │
│  │                                                        │ │
│  │  fabric/pool      - Agent pool management              │ │
│  │  fabric/queue      - Per-agent work queues             │ │
│  │  fabric/limits     - Resource enforcement              │ │
│  │  fabric/executor   - Execution wrapper + isolation     │ │
│  │  fabric/hooks      - Git worktree persistence (GUPP)   │ │
│  │  fabric/nudge      - Inter-agent messaging             │ │
│  │  sandbox/executor  - Computer use (browser/shell)      │ │
│  │  sandbox/policy    - Approval gates                    │ │
│  └──────────┬─────────────────────────────────────────────┘ │
└─────────────┤                                               │
              │                                               │
┌─────────────┴───────────────────────────────────────────────┘
│                  Aragora Core (Stable)
│
│  control_plane/   - TaskScheduler, AgentRegistry, Health, Watchdog
│  debate/          - Arena, PhaseExecutor, Consensus, Convergence
│  agents/          - CLI + API agents, Airlock, Fallback
│  memory/          - Continuum (4-tier), ConsensusMemory
│  knowledge/       - KnowledgeMound (41 registered adapters)
│  workflow/        - DAG engine, 50+ templates
│  rbac/            - Permissions, roles, middleware
│  resilience.py    - CircuitBreaker
│  gauntlet/        - Receipts, findings, runner
└─────────────────────────────────────────────────────────────
```

---

## Phase 0: Architecture Lock (Weeks 1-2) - COMPLETE

**Goal:** Finalize design documents and module structure. No runtime code yet.

### Deliverables

| # | Deliverable | Output | Status |
|---|-------------|--------|--------|
| 0.1 | Parity matrix finalized | `docs/PARITY_MATRIX_GASTOWN_MOLTBOT.md` | DONE |
| 0.2 | Three-layer architecture diagram | This document (above) | DONE |
| 0.3 | Build vs integrate decisions | `docs/BUILD_VS_INTEGRATE.md` | DONE |
| 0.4 | Agent Fabric interface specs | `aragora/fabric/__init__.py` (72 lines, full exports) | DONE |
| 0.5 | Extension module skeletons | `fabric/`, `workspace/`, `gateway/`, `sandbox/` populated | DONE |
| 0.6 | Feature flag registry | Integrated with existing feature flags | DONE |

### Agent Fabric Interface Spec (0.4)

```python
# aragora/fabric/types.py

@dataclass
class AgentPool:
    pool_id: str
    workspace_id: str           # Links to TenantContext
    max_agents: int             # Pool-level concurrency cap
    affinity: List[str]         # Agent type preferences
    dedicated: bool             # Shared vs dedicated pool
    budget: ResourceBudget      # Token + request + time limits

@dataclass
class ResourceBudget:
    max_tokens_per_hour: int
    max_requests_per_minute: int
    max_execution_seconds: int
    cost_ceiling_usd: float

@dataclass
class AgentSlot:
    slot_id: str
    pool_id: str
    agent_id: str
    status: Literal["idle", "running", "draining", "terminated"]
    current_task: Optional[str]
    resources_used: ResourceUsage

@dataclass
class WorkItem:
    """Bead equivalent -- atomic unit of work."""
    item_id: str                # prefix + 5-char ID (Gastown convention)
    workspace_id: str
    convoy_id: Optional[str]    # Batch grouping
    agent_id: Optional[str]     # Assigned agent (None = unassigned)
    status: Literal["pending", "assigned", "running", "done", "failed"]
    payload: Dict[str, Any]
    git_ref: Optional[str]      # Git worktree ref if persisted
    created_at: float
    updated_at: float
```

### Feature Flags (0.6)

| Flag | Default | Controls |
|------|---------|----------|
| `ENABLE_AGENT_FABRIC` | `false` | Pool manager, queues, limits |
| `ENABLE_GIT_HOOKS` | `false` | Git worktree persistence, GUPP |
| `ENABLE_WORKSPACE_MANAGER` | `false` | Rig abstraction, workspace CLI |
| `ENABLE_CONVOY_TRACKER` | `false` | Work batch lifecycle |
| `ENABLE_LOCAL_GATEWAY` | `false` | Device-local routing daemon |
| `ENABLE_COMPUTER_USE` | `false` | Browser/shell sandbox |
| `ENABLE_INTER_AGENT_NUDGE` | `false` | Cross-debate agent messaging |

---

## Phase 1: Agent Fabric Foundation (Weeks 3-4) - COMPLETE

**Goal:** Shared substrate for scheduling, isolation, and resource enforcement
at 50+ agent scale. Both extensions depend on this.

**Actual Implementation:** 2,744 lines across 8 modules with 2,260 lines of tests (183 tests).

### Modules Created

| Module | File | Lines | Status | Description |
|--------|------|-------|--------|-------------|
| Main Facade | `aragora/fabric/fabric.py` | 646 | DONE | AgentFabric class (35 methods) |
| Scheduler | `aragora/fabric/scheduler.py` | 374 | DONE | Priority-based task scheduling with dependencies |
| Lifecycle | `aragora/fabric/lifecycle.py` | 259 | DONE | Agent spawn/terminate/health (13 methods) |
| Policy Engine | `aragora/fabric/policy.py` | 281 | DONE | Pattern-based policy + approval workflow |
| Budget Manager | `aragora/fabric/budget.py` | 269 | DONE | Token/cost tracking and enforcement |
| Hook Manager | `aragora/fabric/hooks.py` | 563 | DONE | GUPP git worktree-backed persistence (20 methods) |
| Models | `aragora/fabric/models.py` | 280 | DONE | 28 data model definitions |
| Init | `aragora/fabric/__init__.py` | 72 | DONE | Public API exports |

### Key Design Decisions

**Pool Manager (`pool.py`)**
- Wraps `AgentRegistry` -- does not replace it. Adds pool grouping on top.
- Pools are scoped to a `TenantContext` workspace.
- Supports dedicated pools (one workspace) and shared pools (multi-workspace).
- Agent affinity: prefer specific agent types for certain task categories.
- Lifecycle: `provisioning → ready → running → draining → terminated`.

**Work Queue (`queue.py`)**
- Wraps `TaskScheduler` Redis Streams -- does not replace it.
- Adds per-agent semaphore (configurable concurrency per agent slot).
- Backpressure: when queue depth exceeds threshold, new submissions get
  `QueueFullError` instead of silently buffering.
- Supports batch dequeue for convoy-style multi-item processing.

**Resource Limiter (`limits.py`)**
- Extends `CostEnforcer` with per-agent granularity.
- Token rate: sliding window per agent (not just per workspace).
- Request throttle: leaky bucket per agent.
- Execution time: wall-clock budget per work item with hard kill.
- Budget rollup: agent → pool → workspace for cascading enforcement.

**Execution Wrapper (`executor.py`)**
- Wraps `AirlockProxy` for process-level isolation.
- Each agent slot runs in a subprocess (or container, later).
- Captures stdout/stderr, enforces timeout, detects crashes.
- On crash: marks work item as failed, triggers GUPP re-queue (Phase 2).

### Tests

```
tests/fabric/
├── test_pool.py           # 20-25 tests
├── test_queue.py          # 20-25 tests
├── test_limits.py         # 15-20 tests
├── test_executor.py       # 15-20 tests
├── test_telemetry.py      # 10-15 tests
└── test_flags.py          # 5-10 tests
```

### Success Criteria

- [ ] Pool manager can create/destroy pools with quota enforcement
- [ ] Work queue supports per-agent semaphores and backpressure
- [ ] Resource limiter enforces token rate + request throttle + time budget
- [ ] Execution wrapper runs agent in subprocess with timeout and crash recovery
- [ ] All fabric modules have >80% test coverage
- [ ] Existing control plane tests still pass (zero regressions)

---

## Phase 2: Gastown Parity Prototype (Weeks 5-6) - COMPLETE

**Goal:** Git worktree persistence, workspace management, and convoy tracking.
Proves that Aragora can manage software engineering agent workflows.

**Actual Implementation:** 873 lines across 5 workspace modules + 1,700+ lines in nomic/ with 82 tests passing.

### Modules Created

| Module | File | Lines | Status | Description |
|--------|------|-------|--------|-------------|
| Hook Persistence | `aragora/fabric/hooks.py` | 563 | DONE | GUPP git worktree-backed persistence (20 methods) |
| Workspace Manager | `aragora/workspace/manager.py` | 299 | DONE | Top-level orchestration for rigs/convoys/beads |
| Rig Model | `aragora/workspace/rig.py` | 86 | DONE | Per-repo container with config and lifecycle |
| Convoy Tracker | `aragora/workspace/convoy.py` | 230 | DONE | Work batch lifecycle with state machine |
| Bead Manager | `aragora/workspace/bead.py` | 216 | DONE | JSONL-backed atomic work units |
| Refinery | `aragora/workspace/refinery.py` | — | PENDING | Merge queue with backpressure |

**Also implemented in `aragora/nomic/`:**
- `hook_queue.py` (575 lines) - Per-agent persistent queue (GUPP compliant)
- `molecules.py` (multi-step workflow templates)
- `agent_roles.py` (MAYOR/WITNESS/CREW/POLECAT hierarchy)
- `mayor_coordinator.py` (321 lines) - Leader election to role mapping
- `gastown_handoff.py` (595 lines) - Context transfer protocol

### Hook Persistence Design (`hooks.py`)

The hook is the core Gastown concept: a pinned bead (work item) per agent that
represents the agent's current obligation. Key behaviors:

1. **Create hook**: When an agent is assigned work, create a git worktree at
   `.aragora/hooks/<agent_id>/` with the work item serialized as JSONL.
2. **GUPP check**: On startup (or patrol cycle), scan all hooks. If a hook has
   pending work, the agent MUST resume it.
3. **Complete hook**: When work is done, commit the result to the worktree and
   remove the hook.
4. **Crash recovery**: If agent crashes, hook persists. Next patrol cycle picks
   it up and re-assigns or resumes.

```python
# aragora/fabric/hooks.py (key interface)

class HookManager:
    async def create_hook(self, agent_id: str, work_item: WorkItem) -> Hook: ...
    async def check_pending_hooks(self) -> List[Hook]: ...
    async def resume_hook(self, hook: Hook) -> None: ...
    async def complete_hook(self, hook: Hook, result: Any) -> None: ...
    async def abandon_hook(self, hook: Hook, reason: str) -> None: ...
```

### Convoy Tracker Design (`convoy.py`)

A convoy bundles multiple beads (work items) into a tracked batch:

```python
class ConvoyTracker:
    async def create_convoy(self, workspace_id: str, items: List[WorkItem]) -> Convoy: ...
    async def assign_items(self, convoy_id: str) -> None: ...
    async def mark_item_done(self, convoy_id: str, item_id: str, result: Any) -> None: ...
    async def get_convoy_status(self, convoy_id: str) -> ConvoyStatus: ...
    async def merge_convoy(self, convoy_id: str) -> MergeResult: ...
```

States: `created → assigning → executing → merging → done | failed`

### Tests

```
tests/fabric/
└── test_hooks.py          # 20-25 tests

tests/workspace/
├── test_manager.py        # 20-25 tests
├── test_rig.py            # 15-20 tests
├── test_convoy.py         # 20-25 tests
├── test_bead.py           # 15-20 tests
├── test_refinery.py       # 15-20 tests
└── test_cli.py            # 10-15 tests
```

### Success Criteria

- [ ] HookManager creates/resumes/completes git-backed hooks
- [ ] GUPP patrol cycle finds and resumes abandoned hooks
- [ ] Workspace manager creates rigs with isolated agent pools
- [ ] Convoy tracker manages work batch lifecycle end-to-end
- [ ] Refinery gates merges with test + review status
- [ ] CLI exposes workspace/rig/convoy operations
- [ ] All workspace modules have >80% test coverage

---

## Phase 3: OpenClaw Parity Prototype (Weeks 7-8) - IN PROGRESS (30%)

**Goal:** Local gateway, device registry, and unified inbox. Proves that
Aragora can serve as a personal AI assistant runtime.

**Current Status:** 657 lines across 4 gateway modules with 39 tests. HTTP server is stub-only.

### Modules Status

| Module | File | Lines | Status | Description |
|--------|------|-------|--------|-------------|
| Local Gateway | `aragora/gateway/server.py` | 190 | STUB | Needs HTTP/WebSocket server implementation |
| Inbox Aggregator | `aragora/gateway/inbox.py` | 183 | DONE | In-memory unified inbox with threading |
| Device Registry | `aragora/gateway/device_registry.py` | 124 | DONE | Device registration and capabilities |
| Agent Router | `aragora/gateway/router.py` | 121 | DONE | Pattern-based message routing |
| Onboarding Wizard | `aragora/onboarding/wizard.py` | — | PENDING | Guided first-run setup |
| Security Pairing | `aragora/gateway/pairing.py` | — | PENDING | Device allowlist and certificate support |
| Persistence Layer | `aragora/gateway/persistence.py` | — | PENDING | SQLite/PostgreSQL storage |

### Remaining Work

1. **P0: Complete HTTP Server** - Add FastAPI/Starlette server to `gateway/server.py`
2. **P1: Add Persistence** - Create `gateway/persistence.py` with SQLAlchemy
3. **P2: Onboarding Wizard** - Create `onboarding/wizard.py`

### Local Gateway Design (`gateway/server.py`)

The gateway is a lightweight local service that:
1. Runs on the user's device (laptop, phone, server).
2. Routes incoming messages from any channel to the right agent.
3. Enforces local auth (API key or device certificate).
4. Proxies to Aragora cloud services when needed.
5. Maintains local state for offline resilience.

```python
class LocalGateway:
    async def start(self, host: str = "127.0.0.1", port: int = 8090) -> None: ...
    async def route_message(self, channel: str, message: InboxMessage) -> AgentResponse: ...
    async def register_device(self, device: DeviceNode) -> str: ...
    async def get_inbox(self, filters: InboxFilters) -> List[InboxMessage]: ...
```

### Inbox Aggregator Design (`gateway/inbox.py`)

Unified inbox that pulls from all connected channels:

```python
class InboxAggregator:
    async def fetch_messages(self, channels: List[str], since: datetime) -> List[InboxMessage]: ...
    async def mark_read(self, message_ids: List[str]) -> None: ...
    async def reply(self, message_id: str, response: str) -> None: ...
    async def get_threads(self, channel: str) -> List[InboxThread]: ...
```

### Tests

```
tests/gateway/
├── test_server.py             # 15-20 tests
├── test_inbox.py              # 15-20 tests
├── test_device_registry.py    # 10-15 tests
├── test_router.py             # 10-15 tests
├── test_pairing.py            # 10-15 tests
└── test_wizard.py             # 10-15 tests
```

### Success Criteria

- [ ] Local gateway starts on localhost and routes messages
- [ ] Inbox aggregator unifies messages from 3+ channel types
- [ ] Device registry tracks capabilities and permissions
- [ ] Agent router assigns agents per channel/account rules
- [ ] Onboarding wizard completes a guided setup flow
- [ ] All gateway modules have >80% test coverage

---

## Phase 4: Safe Computer Use MVP (Weeks 9-10)

**Goal:** Policy-gated browser and shell interaction with full audit trails.

### Modules to Create

| Module | File | Lines (est.) | Builds On | Description |
|--------|------|-------------|-----------|-------------|
| Sandbox Executor | `aragora/sandbox/executor.py` | 400-500 | Execution Wrapper | Browser automation + shell execution in sandboxed environment |
| Action Policy | `aragora/sandbox/policy.py` | 300-400 | RBAC, Policy engine | Approval gates, allowlists, risk scoring per action |
| Screen Capture | `aragora/sandbox/capture.py` | 200-300 | New | Screenshot/screencast for audit + agent feedback |
| Audit Logger | `aragora/sandbox/audit.py` | 200-300 | Gauntlet receipts | Every action logged with SHA-256 receipt |
| Browser Driver | `aragora/sandbox/browser.py` | 300-400 | Playwright/Selenium | Page navigation, form filling, click actions |
| Shell Runner | `aragora/sandbox/shell.py` | 200-300 | subprocess | Command execution with allowlist, timeout, output capture |

### Policy Design (`sandbox/policy.py`)

Every computer-use action passes through policy evaluation:

```python
class ActionPolicy:
    async def evaluate(self, action: ComputerAction) -> PolicyDecision: ...
    async def request_approval(self, action: ComputerAction) -> bool: ...

@dataclass
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    risk_score: float           # 0.0-1.0
    reason: str
    matching_rules: List[str]   # Which policy rules matched
```

Risk tiers:
- **Low** (0.0-0.3): Read-only actions (screenshots, page reads) → auto-approve
- **Medium** (0.3-0.7): Write actions (form fills, clicks) → approve with audit
- **High** (0.7-1.0): System actions (shell, file writes, installs) → human approval required

### Tests

```
tests/sandbox/
├── test_executor.py       # 20-25 tests
├── test_policy.py         # 20-25 tests
├── test_capture.py        # 10-15 tests
├── test_audit.py          # 10-15 tests
├── test_browser.py        # 15-20 tests
└── test_shell.py          # 15-20 tests
```

### Success Criteria

- [ ] Sandbox executor runs browser actions in isolated environment
- [ ] Action policy evaluates risk and gates approvals
- [ ] Every action is logged with SHA-256 receipt
- [ ] Shell runner enforces command allowlist and timeout
- [ ] Human approval flow works for high-risk actions
- [ ] All sandbox modules have >80% test coverage

---

## Phase 5: Integration Hardening (Weeks 11-12)

**Goal:** Polish, performance validation, and documentation.

### Deliverables

| # | Deliverable | Description |
|---|-------------|-------------|
| 5.1 | Integration test suite | End-to-end tests: Fabric → Workspace → Gateway → Sandbox |
| 5.2 | Performance benchmark | 50-agent simulation with pool management and work queues |
| 5.3 | Extension API docs | OpenAPI specs for gateway, workspace, sandbox APIs |
| 5.4 | Migration guide | How to enable extensions on existing Aragora deployments |
| 5.5 | Security audit | Review all extension modules for OWASP top 10 |
| 5.6 | Feature flag docs | How to enable/disable each extension capability |

### Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Agent pool provisioning | <2s for 50 agents | Time from request to all agents ready |
| Work queue throughput | >100 items/sec | Sustained enqueue/dequeue rate |
| Hook persistence | <100ms per hook | Git worktree create + JSONL write |
| Gateway message routing | <50ms p99 | Inbox message to agent assignment |
| Computer use action | <500ms per step | Policy eval + action execution |

### Integration Tests

```
tests/integration/
├── test_fabric_workspace.py       # Fabric + Workspace end-to-end
├── test_workspace_convoy.py       # Convoy lifecycle with real agents
├── test_gateway_inbox.py          # Gateway + Inbox + Connector
├── test_sandbox_policy.py         # Sandbox + Policy + Audit
└── test_full_pipeline.py          # All extensions working together
```

---

## Success Metrics (90 Days)

| Metric | Target | Verification |
|--------|--------|-------------|
| Agent Fabric supports 50+ concurrent agents | Pool manager + queue + limits working | Benchmark test |
| Gastown extension runs a convoy | Hook persistence + workspace + convoy tracker | Integration test |
| OpenClaw extension accepts input | Local gateway + inbox + device registry | Integration test |
| Computer use MVP is auditable | Sandbox + policy + audit logging | Security review |
| Test coverage for extensions | >80% per module | Coverage report |
| Zero regressions in core | All existing tests pass | CI/CD |
| Documentation complete | API docs + migration guide + feature flags | Docs review |

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Scope creep | Extensions grow beyond MVP | Feature flags, strict phase gates |
| Git worktree complexity | Hook persistence edge cases | Extensive test coverage, fallback to file-based |
| Security surface | Computer use introduces attack vectors | Policy engine, human approval gates, audit trails |
| Performance at scale | 50+ agents overwhelm resources | Pool quotas, backpressure, circuit breakers |
| API instability | Extension APIs change frequently | Versioned APIs from day one, deprecation policy |
| Operational complexity | Too many new services | Single binary deployment, feature flags |

---

## Module Inventory (All New Files)

### Phase 0 (Architecture)
- `aragora/fabric/__init__.py`
- `aragora/fabric/types.py`
- `aragora/fabric/flags.py`
- `aragora/workspace/__init__.py`
- `aragora/gateway/__init__.py`
- `aragora/sandbox/__init__.py`

### Phase 1 (Agent Fabric)
- `aragora/fabric/pool.py`
- `aragora/fabric/queue.py`
- `aragora/fabric/limits.py`
- `aragora/fabric/executor.py`
- `aragora/fabric/telemetry.py`

### Phase 2 (Gastown Extension)
- `aragora/fabric/hooks.py`
- `aragora/workspace/manager.py`
- `aragora/workspace/rig.py`
- `aragora/workspace/convoy.py`
- `aragora/workspace/bead.py`
- `aragora/workspace/refinery.py`
- `aragora/workspace/cli.py`

### Phase 3 (OpenClaw Extension)
- `aragora/gateway/server.py`
- `aragora/gateway/inbox.py`
- `aragora/gateway/device_registry.py`
- `aragora/gateway/router.py`
- `aragora/gateway/pairing.py`
- `aragora/onboarding/wizard.py`

### Phase 4 (Computer Use)
- `aragora/sandbox/executor.py`
- `aragora/sandbox/policy.py`
- `aragora/sandbox/capture.py`
- `aragora/sandbox/audit.py`
- `aragora/sandbox/browser.py`
- `aragora/sandbox/shell.py`

**Total new modules: 28**
**Estimated total new lines: 7,500-10,000**
**Estimated total new tests: 350-450**
