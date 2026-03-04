"""
Coordination Module.

Multi-agent worktree coordination, cross-workspace federation, and
hierarchical task dispatch for parallel development.

Features:
- Cross-workspace data sharing with consent
- Federated agent execution
- Multi-workspace workflow orchestration
- Secure inter-workspace communication
- Permission delegation and scoping
- Git worktree lifecycle management
- Hierarchical task dispatch with dependencies
- Health watchdog with stall detection and auto-recovery
- Safe git reconciliation with conflict classification
- File-based event bus for agent coordination
- Session registry with PID-based liveness checks
- Advisory file claim protocol
- Conflict resolution via Arena debates
"""

from aragora.coordination.bus import (
    CoordinationBus,
    CoordinationEvent,
)
from aragora.coordination.claims import (
    ClaimManager,
    ClaimResult,
    ClaimStatus,
    FileClaim,
)
from aragora.coordination.cross_workspace import (
    CrossWorkspaceCoordinator,
    FederatedWorkspace,
    FederationPolicy,
    CrossWorkspaceRequest,
    CrossWorkspaceResult,
    DataSharingConsent,
    SharingScope,
)
from aragora.coordination.worktree_manager import (
    WorktreeManager,
    WorktreeManagerConfig,
    WorktreeState,
)
from aragora.coordination.task_dispatcher import (
    TaskDispatcher,
    DispatcherConfig,
    Task,
)
from aragora.coordination.health_watchdog import (
    HealthWatchdog,
    WatchdogConfig,
    HealthEvent,
    RecoveryStats,
)
from aragora.coordination.reconciler import (
    GitReconciler,
    ReconcilerConfig,
    MergeAttempt,
    ConflictInfo,
    ConflictCategory,
)
from aragora.coordination.registry import (
    SessionRegistry,
    SessionInfo,
)
from aragora.coordination.resolver import (
    ConflictResolver,
    Resolution,
    ResolutionResult,
)

__all__ = [
    # Event bus
    "CoordinationBus",
    "CoordinationEvent",
    # File claims
    "ClaimManager",
    "ClaimResult",
    "ClaimStatus",
    "FileClaim",
    # Cross-workspace
    "CrossWorkspaceCoordinator",
    "FederatedWorkspace",
    "FederationPolicy",
    "CrossWorkspaceRequest",
    "CrossWorkspaceResult",
    "DataSharingConsent",
    "SharingScope",
    # Worktree management
    "WorktreeManager",
    "WorktreeManagerConfig",
    "WorktreeState",
    # Task dispatch
    "TaskDispatcher",
    "DispatcherConfig",
    "Task",
    # Health watchdog
    "HealthWatchdog",
    "WatchdogConfig",
    "HealthEvent",
    "RecoveryStats",
    # Git reconciliation
    "GitReconciler",
    "ReconcilerConfig",
    "MergeAttempt",
    "ConflictInfo",
    "ConflictCategory",
    # Session registry
    "SessionRegistry",
    "SessionInfo",
    # Conflict resolver
    "ConflictResolver",
    "Resolution",
    "ResolutionResult",
]
