"""
Enterprise Control Plane for Aragora Multi-Agent System.

This module provides centralized orchestration of heterogeneous AI agents
with distributed coordination, health monitoring, and task scheduling.

Architecture:
    ┌─────────────────────────────────────────────────────────┐
    │                  Control Plane                          │
    │   AgentRegistry │ TaskScheduler │ HealthMonitor         │
    ├─────────────────────────────────────────────────────────┤
    │                  Redis Backend                          │
    │   Service Discovery │ Job Queue │ Health Probes         │
    └─────────────────────────────────────────────────────────┘

Components:
    - AgentRegistry: Service discovery with heartbeats and capability tracking
    - TaskScheduler: Priority-based task distribution with load balancing
    - HealthMonitor: Liveness probes and circuit breaker integration
    - ControlPlaneCoordinator: High-level API unifying all components

Usage:
    from aragora.control_plane import ControlPlaneCoordinator

    # Initialize control plane
    coordinator = await ControlPlaneCoordinator.create()

    # Register an agent
    await coordinator.register_agent(
        agent_id="claude-3",
        capabilities=["debate", "code", "analysis"],
        metadata={"model": "claude-3-opus", "provider": "anthropic"}
    )

    # Submit a task
    task_id = await coordinator.submit_task(
        task_type="debate",
        payload={"question": "Should we use microservices?"},
        required_capabilities=["debate"],
    )

    # Wait for result
    result = await coordinator.wait_for_result(task_id)

Environment Variables:
    REDIS_URL: Redis connection URL (default: redis://localhost:6379)
    CONTROL_PLANE_PREFIX: Key prefix (default: aragora:cp:)
    HEARTBEAT_INTERVAL: Agent heartbeat interval in seconds (default: 10)
    TASK_TIMEOUT: Default task timeout in seconds (default: 300)

See docs/CONTROL_PLANE.md for full documentation.
"""

from aragora.control_plane.registry import (
    AgentCapability,
    AgentInfo,
    AgentRegistry,
    AgentStatus,
)
from aragora.control_plane.scheduler import (
    RegionRoutingMode,
    Task,
    TaskPriority,
    TaskScheduler,
    TaskStatus,
)
from aragora.control_plane.regional_sync import (
    RegionalEvent,
    RegionalEventBus,
    RegionalEventType,
    RegionalStateManager,
    RegionalSyncConfig,
    RegionHealth,
    get_regional_event_bus,
    init_regional_sync,
    set_regional_event_bus,
)
from aragora.control_plane.health import (
    HealthCheck,
    HealthMonitor,
    HealthStatus,
)
from aragora.control_plane.coordinator import (
    ControlPlaneCoordinator,
    create_control_plane,
)
from aragora.control_plane.leader import (
    LeaderConfig,
    LeaderElection,
    LeaderInfo,
    LeaderState,
    RegionalLeaderConfig,
    RegionalLeaderElection,
    RegionalLeaderInfo,
    get_regional_leader_election,
    init_regional_leader_election,
    set_regional_leader_election,
)
from aragora.control_plane.multi_tenancy import (
    TenantContext,
    TenantEnforcer,
    TenantEnforcementError,
    TenantQuota,
    TenantState,
    get_current_tenant,
    get_global_enforcer,
    set_current_tenant,
    set_global_enforcer,
    with_tenant,
)
from aragora.control_plane.shared_state import (
    AgentState,
    SharedControlPlaneState,
    TaskState,
    close_shared_state,
    get_shared_state,
    get_shared_state_sync,
    set_shared_state,
)
from aragora.control_plane.deliberation_chain import (
    ChainExecution,
    ChainExecutor,
    ChainStatus,
    ChainStore,
    DeliberationChain,
    DeliberationStage,
    StageResult,
    StageStatus,
    StageTransition,
    TemplateEngine,
    create_code_review_chain,
    create_draft_review_chain,
    create_research_synthesis_chain,
)
from aragora.control_plane.channels import (
    ChannelConfig,
    ChannelProvider,
    NotificationChannel,
    NotificationEventType,
    NotificationManager,
    NotificationMessage,
    NotificationPriority,
    NotificationResult,
    create_task_completed_notification,
    create_deliberation_consensus_notification,
    create_sla_violation_notification,
)
from aragora.control_plane.slo_alert_sink import (
    ControlPlaneSLOAlertSink,
    register_slo_alert_sink,
)
from aragora.control_plane.notifications import (
    EmailProvider,
    NotificationDispatcher,
    NotificationDispatcherConfig,
    QueuedNotification,
    RetryConfig,
    create_notification_dispatcher,
    get_default_notification_dispatcher,
    on_notification_event,
    set_default_notification_dispatcher,
)
from aragora.control_plane.task_events import (
    emit_task_cancelled,
    emit_task_claimed,
    emit_task_completed,
    emit_task_failed,
    emit_task_retried,
    emit_task_submitted,
    emit_task_timeout,
    get_task_event_dispatcher,
    set_task_event_dispatcher,
)
from aragora.control_plane.deliberation_events import (
    DeliberationEventType,
)
from aragora.control_plane.arena_bridge import (
    AgentMetrics,
    ArenaControlPlaneBridge,
    ArenaEventAdapter,
    get_arena_bridge,
    init_arena_bridge,
    set_arena_bridge,
)
from aragora.control_plane.policy import (
    ControlPlanePolicy,
    ControlPlanePolicyManager,
    EnforcementLevel,
    PolicyDecision,
    PolicyEvaluationResult,
    PolicyScope,
    PolicyViolation,
    PolicyViolationError,
    RegionConstraint,
    SLARequirements,
    create_agent_tier_policy,
    create_production_policy,
    create_sensitive_data_policy,
    create_sla_policy,
)
from aragora.control_plane.region_router import (
    RegionRouter,
    RegionRoutingDecision,
    RegionStatus,
    RegionHealth as RouterRegionHealth,  # Alias to avoid conflict with regional_sync.RegionHealth
    get_region_router,
    set_region_router,
    init_region_router,
)

__all__ = [
    # Registry
    "AgentRegistry",
    "AgentInfo",
    "AgentStatus",
    "AgentCapability",
    # Scheduler
    "TaskScheduler",
    "Task",
    "TaskStatus",
    "TaskPriority",
    "RegionRoutingMode",
    # Regional Sync
    "RegionalEventBus",
    "RegionalEventType",
    "RegionalEvent",
    "RegionalSyncConfig",
    "RegionalStateManager",
    "RegionHealth",
    "get_regional_event_bus",
    "set_regional_event_bus",
    "init_regional_sync",
    # Health
    "HealthMonitor",
    "HealthCheck",
    "HealthStatus",
    # Coordinator
    "ControlPlaneCoordinator",
    "create_control_plane",
    # Leader Election
    "LeaderElection",
    "LeaderConfig",
    "LeaderInfo",
    "LeaderState",
    # Regional Leader Election
    "RegionalLeaderElection",
    "RegionalLeaderConfig",
    "RegionalLeaderInfo",
    "get_regional_leader_election",
    "set_regional_leader_election",
    "init_regional_leader_election",
    # Multi-Tenancy
    "TenantContext",
    "TenantEnforcer",
    "TenantEnforcementError",
    "TenantQuota",
    "TenantState",
    "get_current_tenant",
    "get_global_enforcer",
    "set_current_tenant",
    "set_global_enforcer",
    "with_tenant",
    # Shared State
    "SharedControlPlaneState",
    "AgentState",
    "TaskState",
    "get_shared_state",
    "get_shared_state_sync",
    "set_shared_state",
    "close_shared_state",
    # Deliberation Chaining
    "DeliberationChain",
    "DeliberationStage",
    "ChainExecution",
    "ChainExecutor",
    "ChainStore",
    "ChainStatus",
    "StageStatus",
    "StageTransition",
    "StageResult",
    "TemplateEngine",
    "create_code_review_chain",
    "create_draft_review_chain",
    "create_research_synthesis_chain",
    # Channels
    "ChannelConfig",
    "ChannelProvider",
    "NotificationChannel",
    "NotificationEventType",
    "NotificationManager",
    "NotificationMessage",
    "NotificationPriority",
    "NotificationResult",
    "create_task_completed_notification",
    "create_deliberation_consensus_notification",
    "create_sla_violation_notification",
    "ControlPlaneSLOAlertSink",
    "register_slo_alert_sink",
    # Notifications (Dispatcher)
    "EmailProvider",
    "NotificationDispatcher",
    "NotificationDispatcherConfig",
    "QueuedNotification",
    "RetryConfig",
    "create_notification_dispatcher",
    "get_default_notification_dispatcher",
    "on_notification_event",
    "set_default_notification_dispatcher",
    # Task Events
    "emit_task_cancelled",
    "emit_task_claimed",
    "emit_task_completed",
    "emit_task_failed",
    "emit_task_retried",
    "emit_task_submitted",
    "emit_task_timeout",
    "get_task_event_dispatcher",
    "set_task_event_dispatcher",
    # Policy
    "ControlPlanePolicy",
    "ControlPlanePolicyManager",
    "EnforcementLevel",
    "PolicyDecision",
    "PolicyEvaluationResult",
    "PolicyScope",
    "PolicyViolation",
    "PolicyViolationError",
    "RegionConstraint",
    "SLARequirements",
    "create_agent_tier_policy",
    "create_production_policy",
    "create_sensitive_data_policy",
    "create_sla_policy",
    # Deliberation Events
    "DeliberationEventType",
    # Arena Bridge
    "AgentMetrics",
    "ArenaControlPlaneBridge",
    "ArenaEventAdapter",
    "get_arena_bridge",
    "init_arena_bridge",
    "set_arena_bridge",
    # Region Router
    "RegionRouter",
    "RegionRoutingDecision",
    "RegionStatus",
    "RouterRegionHealth",
    "get_region_router",
    "set_region_router",
    "init_region_router",
]
