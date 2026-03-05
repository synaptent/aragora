# Coordination System Guide

The `aragora.coordination` module enables multiple Claude Code sessions (or other agents) to work
on the same repository in parallel without stepping on each other. It handles worktree lifecycle,
cross-workspace task dispatch, conflict resolution via debate, and session health monitoring.

## Components

| Component | Class | Location | Purpose |
|-----------|-------|----------|---------|
| Cross-workspace federation | `CrossWorkspaceCoordinator` | `cross_workspace.py` | Secure data sharing and agent dispatch across workspaces |
| Worktree lifecycle | `WorktreeManager` | `worktree_manager.py` | Create, track, and clean up isolated git worktrees |
| Task queue | `TaskDispatcher` | `task_dispatcher.py` | Priority-based task submission with dependency tracking |
| Health monitoring | `HealthWatchdog` | `health_watchdog.py` | Stall detection and automatic task reassignment |
| Conflict resolution | `ConflictResolver` | `resolver.py` | Merge conflict classification and Arena-debate resolution |
| Git reconciliation | `GitReconciler` | `reconciler.py` | Textual and semantic conflict detection across branches |
| Session registry | `SessionRegistry` | `registry.py` | File-backed registry of live agent sessions with PID checks |
| Event bus | `CoordinationBus` | `bus.py` | File-based event passing between agents |
| File claims | `ClaimManager` | `claims.py` | Advisory lock protocol so agents don't edit the same file |

## Worktree Management

Each agent session runs in an isolated git worktree on its own branch. `WorktreeManager` wraps
`git worktree` operations with health tracking and automatic cleanup:

```python
from pathlib import Path
from aragora.coordination import WorktreeManager, WorktreeManagerConfig

config = WorktreeManagerConfig(
    base_branch="main",
    branch_prefix="dev",
    stall_timeout_seconds=600,    # 10 min with no activity
    abandon_timeout_seconds=3600, # 1 hour -> auto-cleanup
    max_worktrees=20,
)
manager = WorktreeManager(repo_path=Path("."), config=config)

# Create an isolated worktree
wt = await manager.create("feature-auth", track="security")
# Agent works in wt.path ...
await manager.destroy(wt.worktree_id)
```

## Session Registry

Agents register on startup and discover peers at runtime. Liveness is checked via
`os.kill(pid, 0)` — stale entries are reaped automatically:

```python
from pathlib import Path
from aragora.coordination import SessionRegistry

reg = SessionRegistry(repo_path=Path("."))

# Register this session
session = reg.register(
    agent="claude",
    worktree=Path("/tmp/worktrees/claude-abc123"),
    focus="SDK parity",
    track="developer",
)

# Discover live peers (dead PIDs auto-reaped)
peers = reg.discover()
for peer in peers:
    print(f"{peer.agent} @ {peer.worktree} — {peer.focus}")

# Heartbeat (update timestamp periodically)
reg.heartbeat(session.session_id)

# Clean up on exit
reg.deregister(session.session_id)
```

Sessions are stored as JSON files under `.aragora_coordination/sessions/`.

## Session Lock (.claude-session-active)

The `.claude-session-active` file in the worktree root prevents the autopilot from deleting a
worktree while a session is active. The `worktree-guard.sh` SessionStart hook creates this file
with the current PID; the Stop hook removes it. `codex_worktree_autopilot.py` checks for this
file and verifies the PID via `os.kill(pid, 0)` before any cleanup.

This is the primary defense against the Node.js `child_process.spawn` ENOENT error that occurs
when the CWD disappears under a running session.

## Cross-Workspace Task Dispatch

`CrossWorkspaceCoordinator` enables one workspace to dispatch agents or share knowledge with
another. All operations require explicit consent and are governed by `FederationPolicy`:

```python
from aragora.coordination import (
    CrossWorkspaceCoordinator,
    FederatedWorkspace,
    FederationPolicy,
    DataSharingConsent,
    SharingScope,
    OperationType,
)

# Define a policy that allows read-only knowledge queries
policy = FederationPolicy(
    name="cross-team-readonly",
    mode="readonly",
    sharing_scope=SharingScope.SUMMARY,
    allowed_operations={OperationType.QUERY_MOUND, OperationType.READ_KNOWLEDGE},
    max_requests_per_hour=100,
    audit_all_requests=True,
)

coordinator = CrossWorkspaceCoordinator()
coordinator.register_policy(policy)

# Dispatch a knowledge query to another workspace
result = await coordinator.request(
    operation=OperationType.QUERY_MOUND,
    source_workspace="workspace-a",
    target_workspace="workspace-b",
    payload={"query": "authentication module findings"},
)
```

`SharingScope` controls data exposure: `NONE`, `METADATA`, `SUMMARY`, `FULL`, or `SELECTIVE`.

## Task Dispatch

`TaskDispatcher` maintains a priority min-heap of tasks and assigns them to available worktrees.
Tasks support dependency chains (`depends_on`) and automatic retry on failure:

```python
from aragora.coordination import TaskDispatcher, DispatcherConfig, Task

dispatcher = TaskDispatcher(config=DispatcherConfig(max_concurrent=12))

# Submit tasks with priorities (1 = highest)
auth_task = dispatcher.submit("Refactor auth module", priority=1, track="security")
tests_task = dispatcher.submit(
    "Add auth tests",
    priority=2,
    track="qa",
    depends_on=[auth_task.task_id],
)

# Assign to a worktree
dispatcher.assign(auth_task.task_id, worktree_id="wt-abc123")
dispatcher.complete(auth_task.task_id)

# Check what's ready to run (dependencies resolved)
ready = dispatcher.ready_tasks
```

## Health Watchdog

`HealthWatchdog` polls active worktrees every 30 seconds (configurable), detects stalls, and
either reassigns the task to another worktree or marks it abandoned:

```python
from aragora.coordination import HealthWatchdog, WatchdogConfig

watchdog = HealthWatchdog(
    worktree_manager=manager,
    task_dispatcher=dispatcher,
    config=WatchdogConfig(
        check_interval_seconds=30.0,
        max_recovery_attempts=3,
        auto_reassign_stalled=True,
        auto_cleanup_abandoned=True,
    ),
)

# Run a single health check (call periodically or via asyncio.create_task)
await watchdog.check_all()

# Inspect recovery history
stats = watchdog.recovery_stats  # RecoveryStats dataclass
print(f"Stalls: {stats.stalls_detected}, Recovered: {stats.recoveries_succeeded}")
```

## Conflict Resolution

When two agents modify the same code, `ConflictResolver` runs a three-layer resolution:

1. **Fast** (`GitReconciler.detect_conflicts`) — textual classification
2. **Deep** (`SemanticConflictDetector.detect`) — AST-aware analysis
3. **Debate** — Arena 2-round debate for semantic conflicts (confidence > 0.7)

Trivial conflicts (import order, whitespace) are auto-resolved. Semantic conflicts get a debate
where agents present their change rationale and a neutral judge picks the winner or proposes a
synthesis:

```python
from pathlib import Path
from aragora.coordination import ConflictResolver

resolver = ConflictResolver(repo_path=Path("."))
result = await resolver.resolve("branch-feature-auth", "branch-feature-rbac")

# result.resolution: "no_conflict" | "auto_merged" | "debate_resolved" | "needs_human"
if result.resolution == "needs_human":
    print(f"Conflicting files: {result.conflicting_files}")
    print(f"Debate summary: {result.debate_summary}")
```

Decision receipts are written to `.aragora_coordination/decisions/` for audit.

## File Claims

`ClaimManager` implements an advisory lock protocol so agents can signal intent before editing a
file, preventing concurrent overwrites:

```python
from aragora.coordination import ClaimManager, ClaimStatus

claims = ClaimManager(repo_path=Path("."))
result = claims.claim("/path/to/file.py", agent_id="claude-session-abc")

if result.status == ClaimStatus.GRANTED:
    # Safe to edit
    ...
    claims.release("/path/to/file.py", agent_id="claude-session-abc")
else:
    # Another agent holds the claim — wait or pick a different file
    print(f"Claimed by: {result.holder}")
```

## Further Reading

- `docs/COORDINATION.md` — Multi-agent coordination overview and conventions
- `docs/AGENT_ASSIGNMENTS.md` — Recommended focus areas by agent track
- `scripts/codex_worktree_autopilot.py` — Background reconcile and cleanup automation
- `scripts/worktree-guard.sh` — SessionStart hook that creates the session lock file
