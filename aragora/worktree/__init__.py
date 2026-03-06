"""Worktree integration helpers."""

from aragora.worktree.autopilot import (
    AUTOPILOT_ACTIONS,
    AUTOPILOT_STRATEGIES,
    AutopilotRequest,
    build_autopilot_command,
    resolve_repo_root,
    run_autopilot,
)
from aragora.worktree.lifecycle import (
    ManagedWorktreeSession,
    WorktreeLifecycleService,
    WorktreeOperationResult,
)
from aragora.worktree.fleet import (
    FleetCoordinationStore,
    build_fleet_rows,
    infer_orchestration_pattern,
)
from aragora.worktree.integration_worker import (
    FleetIntegrationOutcome,
    FleetIntegrationWorker,
    FleetIntegrationWorkerConfig,
)
from aragora.worktree.integration_target_workspace import FleetIntegrationTargetWorkspace

__all__ = [
    "AUTOPILOT_ACTIONS",
    "AUTOPILOT_STRATEGIES",
    "AutopilotRequest",
    "build_autopilot_command",
    "resolve_repo_root",
    "run_autopilot",
    "ManagedWorktreeSession",
    "WorktreeLifecycleService",
    "WorktreeOperationResult",
    "FleetCoordinationStore",
    "build_fleet_rows",
    "infer_orchestration_pattern",
    "FleetIntegrationOutcome",
    "FleetIntegrationWorker",
    "FleetIntegrationWorkerConfig",
    "FleetIntegrationTargetWorkspace",
]
