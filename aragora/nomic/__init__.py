"""
Nomic Loop Module.

Provides the nomic loop self-improvement cycle with two implementations:

1. **State Machine (New)** - Event-driven, robust, checkpoint-resumable
   - NomicStateMachine: Core state machine
   - NomicState: State enum
   - Event, EventType: Event system
   - CheckpointManager: Persistence
   - RecoveryManager: Error recovery

2. **Integration (Legacy)** - Phase-based, integrated with aragora features
   - NomicIntegration: Integration hub
   - Preflight checks

The nomic loop is a 6-phase cycle:
1. Context - Gather codebase understanding
2. Debate - Multi-agent debate on improvements
3. Design - Design the implementation
4. Implement - Write the code changes
5. Verify - Test and validate changes
6. Commit - Commit approved changes

Migration: The state machine is the recommended approach for new deployments.
Legacy integration is preserved for backward compatibility.
"""

# State Machine (New - recommended)
from aragora.nomic.checkpoints import (
    CheckpointManager,
    cleanup_old_checkpoints,
    list_checkpoints,
    load_checkpoint,
    load_latest_checkpoint,
    save_checkpoint,
)
from aragora.nomic.events import (
    Event,
    EventLog,
    EventType,
    agent_failed_event,
    checkpoint_loaded_event,
    circuit_open_event,
    error_event,
    pause_event,
    phase_complete_event,
    retry_event,
    rollback_event,
    start_event,
    stop_event,
    timeout_event,
)
from aragora.nomic.handlers import (
    create_commit_handler,
    create_context_handler,
    create_debate_handler,
    create_design_handler,
    create_handlers,
    create_implement_handler,
    create_recovery_handler,
    create_verify_handler,
)

# Phase implementations
from aragora.nomic.phases import (
    BeliefContext,
    CommitPhase,
    ContextPhase,
    DebateConfig,
    DebatePhase,
    DesignConfig,
    DesignPhase,
    ImplementPhase,
    LearningContext,
    PostDebateHooks,
    ScopeLimiter,
    VerifyPhase,
    check_design_scope,
)

# Task decomposition
from aragora.nomic.task_decomposer import (
    DecomposerConfig,
    SubTask,
    TaskDecomposer,
    TaskDecomposition,
    analyze_task,
    get_task_decomposer,
)

# Autonomous orchestration
from aragora.nomic.autonomous_orchestrator import (
    AgentAssignment,
    AgentRouter,
    AutonomousOrchestrator,
    FeedbackLoop,
    OrchestrationResult,
    Track,
    TrackConfig,
    get_orchestrator,
    reset_orchestrator,
)

# Parallel orchestration (production-grade multi-agent execution)
from aragora.nomic.parallel_orchestrator import ParallelOrchestrator

# Hierarchical coordination (Planner/Worker/Judge cycle)
from aragora.nomic.hierarchical_coordinator import (
    CoordinationPhase,
    CoordinatorConfig,
    HierarchicalCoordinator,
    HierarchicalResult,
    JudgeVerdict,
    WorkerReport,
)

# Meta-planning (debate-driven goal prioritization)
from aragora.nomic.meta_planner import (
    MetaPlanner,
    MetaPlannerConfig,
    PlanningContext,
    PrioritizedGoal,
)

# Self-correction (cross-cycle pattern analysis)
from aragora.nomic.self_correction import (
    CorrectionReport,
    SelfCorrectionConfig,
    SelfCorrectionEngine,
    StrategyRecommendation,
)

# Branch coordination (parallel development)
from aragora.nomic.branch_coordinator import (
    BranchCoordinator,
    BranchCoordinatorConfig,
    ConflictReport,
    CoordinationResult,
    MergeResult,
    TrackAssignment,
    WorktreeInfo,
)

# Scope guard (track boundary enforcement)
from aragora.nomic.scope_guard import (
    DEFAULT_TRACK_SCOPES,
    PROTECTED_FILES,
    ScopeGuard,
    ScopeViolation,
    TrackScope,
)

# Session manifest (multi-agent session tracking)
from aragora.nomic.session_manifest import (
    SessionEntry,
    SessionManifest,
)

# Event bus (cross-worktree IPC)
from aragora.nomic.event_bus import (
    VALID_EVENT_TYPES,
    EventBus,
    WorktreeEvent,
)

# Development coordination control plane
from aragora.nomic.dev_coordination import (
    CompletionReceipt,
    DevCoordinationStore,
    IntegrationDecision,
    IntegrationDecisionType,
    LeaseConflictError,
    LeaseStatus,
    SalvageCandidate,
    SalvageStatus,
    WorkLease,
)

# Legacy NomicLoop API (compatibility)
from aragora.nomic.loop import NomicLoop

# Gastown Patterns - Beads (git-backed work persistence)
from aragora.nomic.beads import (
    Bead,
    BeadEvent,
    BeadPriority,
    BeadStatus,
    BeadStore,
    BeadType,
    create_bead_store,
    get_bead_store,
    reset_bead_store,
)

# Gastown Patterns - Convoys (grouped work orders)
from aragora.nomic.convoys import (
    Convoy,
    ConvoyManager,
    ConvoyPriority,
    ConvoyProgress,
    ConvoyStatus,
    get_convoy_manager,
    reset_convoy_manager,
)

# Gastown Patterns - Hook Queue (GUPP recovery)
from aragora.nomic.hook_queue import (
    HookEntry,
    HookEntryStatus,
    HookQueue,
    HookQueueRegistry,
    get_hook_queue_registry,
    reset_hook_queue_registry,
)

# Gastown Patterns - Agent Roles (hierarchical coordination)
from aragora.nomic.agent_roles import (
    AgentHierarchy,
    AgentRole,
    RoleAssignment,
    RoleBasedRouter,
    RoleCapability,
    get_agent_hierarchy,
    reset_agent_hierarchy,
)

# Gastown Patterns - Molecules (durable workflows)
from aragora.nomic.molecules import (
    Molecule,
    MoleculeEngine,
    MoleculeResult,
    MoleculeStatus,
    MoleculeStep,
    StepExecutor,
    StepStatus,
    get_molecule_engine,
    reset_molecule_engine,
)

# Global Work Queue (unified priority queue)
from aragora.nomic.global_work_queue import (
    GlobalWorkQueue,
    PriorityCalculator,
    PriorityConfig,
    PrioritizedWork,
    WorkItem,
    WorkStatus,
    WorkType,
    reset_global_work_queue,
)

# SOAR Curriculum (stepping stones for self-improvement)
from aragora.nomic.curriculum import (
    CurriculumPlanner,
    SteppingStoneGenerator,
    SteppingStone,
    Curriculum,
    SkillCategory,
    generate_curriculum,
    CurriculumAwareFeedbackLoop,
    CurriculumConfig,
    integrate_curriculum_with_orchestrator,
)

# Outcome tracking (debate quality regression detection)
from aragora.nomic.outcome_tracker import (
    DebateMetrics,
    DebateScenario,
    NomicOutcomeTracker,
    OutcomeComparison,
)

# Self-improvement pipeline
from aragora.nomic.self_improve import (
    SelfImproveConfig,
    SelfImprovePipeline,
    SelfImproveResult,
)

# Autonomous assessment engine
from aragora.nomic.assessment_engine import (
    AutonomousAssessmentEngine,
    CodebaseHealthReport,
    ImprovementCandidate,
    SignalSource,
)

# Goal generator
from aragora.nomic.goal_generator import GoalGenerator

# Self-improvement daemon
from aragora.nomic.daemon import (
    CycleResult,
    DaemonConfig,
    DaemonState,
    DaemonStatus,
    SelfImprovementDaemon,
)

# Code review agent
from aragora.nomic.code_reviewer import (
    CodeReviewerAgent,
    IssueSeverity,
    ReviewConfig,
    ReviewIssue,
    ReviewResult,
)

# Cross-agent learning bus
from aragora.nomic.learning_bus import (
    Finding,
    LearningBus,
)

# Business context scoring
from aragora.nomic.business_context import (
    BusinessContext,
    BusinessContextConfig,
    GoalScore,
)

# Batch pattern fixer
from aragora.nomic.pattern_fixer import (
    ANTIPATTERNS,
    FixResult,
    PatternFixer,
    PatternMatch,
)

# Forward-fix diagnostics
from aragora.nomic.forward_fixer import (
    DiagnosisResult,
    FailureType,
    ForwardFix,
    ForwardFixer,
)

# Codebase indexer (searchable code structure for planning agents)
from aragora.nomic.codebase_indexer import (
    CodebaseIndexer,
    IndexStats,
    ModuleInfo,
)

# Cross-cycle learning
from aragora.nomic.cycle_record import (
    AgentContribution,
    NomicCycleRecord,
    PatternReinforcement,
    SurpriseEvent,
)
from aragora.nomic.cycle_store import (
    CycleLearningStore,
    get_cycle_store,
    get_recent_cycles,
    save_cycle,
)
from aragora.nomic.metrics import (
    NOMIC_CIRCUIT_BREAKERS_OPEN,
    NOMIC_CURRENT_PHASE,
    NOMIC_CYCLES_IN_PROGRESS,
    NOMIC_CYCLES_TOTAL,
    NOMIC_ERRORS,
    NOMIC_PHASE_DURATION,
    NOMIC_PHASE_LAST_TRANSITION,
    NOMIC_PHASE_TRANSITIONS,
    NOMIC_RECOVERY_DECISIONS,
    NOMIC_RETRIES,
    PHASE_ENCODING,
    check_stuck_phases,
    create_metrics_callback,
    get_nomic_metrics_summary,
    nomic_metrics_callback,
    track_cycle_complete,
    track_cycle_start,
    track_error,
    track_phase_transition,
    track_recovery_decision,
    track_retry,
    update_circuit_breaker_count,
)
from aragora.nomic.recovery import (
    CircuitBreaker,
    CircuitBreakerRegistry,
    RecoveryDecision,
    RecoveryManager,
    RecoveryStrategy,
    calculate_backoff,
    recovery_handler,
)
from aragora.nomic.state_machine import (
    NomicStateMachine,
    StateTimeoutError,
    TransitionError,
    create_nomic_state_machine,
)
from aragora.nomic.states import (
    STATE_CONFIG,
    VALID_TRANSITIONS,
    NomicState,
    StateContext,
    StateMetadata,
    get_state_config,
    is_valid_transition,
)


# Legacy Integration (lazy imports to avoid circular dependencies)
def __getattr__(name):
    """Lazy import legacy integration modules."""
    legacy_integration = {
        "NomicIntegration",
        "BeliefAnalysis",
        "AgentReliability",
        "StalenessReport",
        "PhaseCheckpoint",
        "create_nomic_integration",
    }
    legacy_preflight = {
        "PreflightHealthCheck",
        "PreflightResult",
        "CheckResult",
        "CheckStatus",
        "run_preflight",
    }

    if name in legacy_integration:
        from aragora.nomic import integration

        return getattr(integration, name)
    elif name in legacy_preflight:
        from aragora.nomic import preflight

        return getattr(preflight, name)
    elif name == "HardenedOrchestrator":
        from aragora.nomic.hardened_orchestrator import HardenedOrchestrator

        return HardenedOrchestrator
    elif name == "NomicPipelineBridge":
        from aragora.nomic.pipeline_bridge import NomicPipelineBridge

        return NomicPipelineBridge
    elif name in {
        "OutcomeFeedbackBridge",
        "FeedbackGoal",
    }:
        from aragora.nomic.outcome_feedback import (
            OutcomeFeedbackBridge as _OFB,
            FeedbackGoal as _FG,
        )

        _ofb_map = {
            "OutcomeFeedbackBridge": _OFB,
            "FeedbackGoal": _FG,
        }
        return _ofb_map[name]
    elif name == "GoalEvaluator":
        from aragora.nomic.goal_evaluator import GoalEvaluator

        return GoalEvaluator
    elif name in {
        "ExecutionBridge",
        "ExecutionInstruction",
        "ExecutionResult",
    }:
        from aragora.nomic.execution_bridge import (
            ExecutionBridge as _EB,
            ExecutionInstruction as _EI,
            ExecutionResult as _ER,
        )

        _map = {
            "ExecutionBridge": _EB,
            "ExecutionInstruction": _EI,
            "ExecutionResult": _ER,
        }
        return _map[name]
    elif name in {
        "WorktreeWatchdog",
        "WatchdogConfig",
        "WorktreeSession",
        "HealthReport",
    }:
        from aragora.nomic.worktree_watchdog import (
            WorktreeWatchdog as _WW,
            WatchdogConfig as _WC,
            WorktreeSession as _WS,
            HealthReport as _HR,
        )

        _ww_map = {
            "WorktreeWatchdog": _WW,
            "WatchdogConfig": _WC,
            "WorktreeSession": _WS,
            "HealthReport": _HR,
        }
        return _ww_map[name]
    elif name in {
        "WorktreeAuditor",
        "AuditorConfig",
        "AuditFinding",
        "AuditReport",
        "WorktreeStatus",
    }:
        from aragora.nomic.worktree_auditor import (
            WorktreeAuditor as _WA,
            AuditorConfig as _AC,
            AuditFinding as _AF,
            AuditReport as _AR,
            WorktreeStatus as _WSt,
        )

        _wa_map = {
            "WorktreeAuditor": _WA,
            "AuditorConfig": _AC,
            "AuditFinding": _AF,
            "AuditReport": _AR,
            "WorktreeStatus": _WSt,
        }
        return _wa_map[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # State Machine (New)
    "NomicStateMachine",
    "NomicState",
    "StateContext",
    "StateMetadata",
    "VALID_TRANSITIONS",
    "STATE_CONFIG",
    "is_valid_transition",
    "get_state_config",
    "create_nomic_state_machine",
    "TransitionError",
    "StateTimeoutError",
    # Events
    "Event",
    "EventType",
    "EventLog",
    "start_event",
    "stop_event",
    "pause_event",
    "error_event",
    "timeout_event",
    "retry_event",
    "phase_complete_event",
    "agent_failed_event",
    "circuit_open_event",
    "rollback_event",
    "checkpoint_loaded_event",
    # Checkpoints
    "CheckpointManager",
    "save_checkpoint",
    "load_checkpoint",
    "load_latest_checkpoint",
    "list_checkpoints",
    "cleanup_old_checkpoints",
    # Recovery
    "RecoveryStrategy",
    "RecoveryDecision",
    "RecoveryManager",
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "calculate_backoff",
    "recovery_handler",
    # Metrics
    "NOMIC_PHASE_TRANSITIONS",
    "NOMIC_CURRENT_PHASE",
    "NOMIC_PHASE_DURATION",
    "NOMIC_CYCLES_TOTAL",
    "NOMIC_CYCLES_IN_PROGRESS",
    "NOMIC_PHASE_LAST_TRANSITION",
    "NOMIC_CIRCUIT_BREAKERS_OPEN",
    "NOMIC_ERRORS",
    "NOMIC_RECOVERY_DECISIONS",
    "NOMIC_RETRIES",
    "PHASE_ENCODING",
    "track_phase_transition",
    "track_cycle_start",
    "track_cycle_complete",
    "track_error",
    "track_recovery_decision",
    "track_retry",
    "update_circuit_breaker_count",
    "nomic_metrics_callback",
    "create_metrics_callback",
    "get_nomic_metrics_summary",
    "check_stuck_phases",
    # Handlers
    "create_handlers",
    "create_context_handler",
    "create_debate_handler",
    "create_design_handler",
    "create_implement_handler",
    "create_verify_handler",
    "create_recovery_handler",
    "create_commit_handler",
    # Legacy Integration
    "NomicIntegration",
    "BeliefAnalysis",
    "AgentReliability",
    "StalenessReport",
    "PhaseCheckpoint",
    "create_nomic_integration",
    # Preflight
    "PreflightHealthCheck",
    "PreflightResult",
    "CheckResult",
    "CheckStatus",
    "run_preflight",
    # Phase implementations
    "ContextPhase",
    "DebatePhase",
    "DesignPhase",
    "ImplementPhase",
    "VerifyPhase",
    "CommitPhase",
    "DebateConfig",
    "DesignConfig",
    "LearningContext",
    "BeliefContext",
    "PostDebateHooks",
    "ScopeLimiter",
    "check_design_scope",
    # Task decomposition
    "TaskDecomposer",
    "TaskDecomposition",
    "SubTask",
    "DecomposerConfig",
    "analyze_task",
    "get_task_decomposer",
    # Autonomous orchestration
    "HardenedOrchestrator",
    "NomicPipelineBridge",
    "AutonomousOrchestrator",
    "ParallelOrchestrator",
    "AgentRouter",
    "FeedbackLoop",
    "Track",
    "TrackConfig",
    "AgentAssignment",
    "OrchestrationResult",
    "get_orchestrator",
    "reset_orchestrator",
    # Hierarchical coordination
    "HierarchicalCoordinator",
    "CoordinatorConfig",
    "CoordinationPhase",
    "HierarchicalResult",
    "JudgeVerdict",
    "WorkerReport",
    # Meta-planning
    "MetaPlanner",
    "MetaPlannerConfig",
    "PrioritizedGoal",
    "PlanningContext",
    # Branch coordination
    "BranchCoordinator",
    "BranchCoordinatorConfig",
    "TrackAssignment",
    "WorktreeInfo",
    "ConflictReport",
    "MergeResult",
    "CoordinationResult",
    # Scope guard
    "ScopeGuard",
    "ScopeViolation",
    "TrackScope",
    "DEFAULT_TRACK_SCOPES",
    "PROTECTED_FILES",
    # Session manifest
    "SessionManifest",
    "SessionEntry",
    # Event bus
    "EventBus",
    "WorktreeEvent",
    "VALID_EVENT_TYPES",
    # Development coordination
    "WorkLease",
    "LeaseStatus",
    "LeaseConflictError",
    "CompletionReceipt",
    "IntegrationDecision",
    "IntegrationDecisionType",
    "SalvageCandidate",
    "SalvageStatus",
    "DevCoordinationStore",
    # Outcome tracking
    "NomicOutcomeTracker",
    "DebateMetrics",
    "DebateScenario",
    "OutcomeComparison",
    # Cross-cycle learning
    "NomicCycleRecord",
    "AgentContribution",
    "SurpriseEvent",
    "PatternReinforcement",
    "CycleLearningStore",
    "get_cycle_store",
    "get_recent_cycles",
    "save_cycle",
    # Legacy API
    "NomicLoop",
    # Gastown Patterns - Beads
    "Bead",
    "BeadType",
    "BeadStatus",
    "BeadPriority",
    "BeadStore",
    "BeadEvent",
    "create_bead_store",
    "get_bead_store",
    "reset_bead_store",
    # Gastown Patterns - Convoys
    "Convoy",
    "ConvoyStatus",
    "ConvoyPriority",
    "ConvoyProgress",
    "ConvoyManager",
    "get_convoy_manager",
    "reset_convoy_manager",
    # Gastown Patterns - Hook Queue (GUPP)
    "HookEntry",
    "HookEntryStatus",
    "HookQueue",
    "HookQueueRegistry",
    "get_hook_queue_registry",
    "reset_hook_queue_registry",
    # Gastown Patterns - Agent Roles
    "AgentRole",
    "RoleCapability",
    "RoleAssignment",
    "AgentHierarchy",
    "RoleBasedRouter",
    "get_agent_hierarchy",
    "reset_agent_hierarchy",
    # Gastown Patterns - Molecules
    "Molecule",
    "MoleculeStep",
    "MoleculeStatus",
    "StepStatus",
    "MoleculeResult",
    "MoleculeEngine",
    "StepExecutor",
    "get_molecule_engine",
    "reset_molecule_engine",
    # Global Work Queue
    "GlobalWorkQueue",
    "PriorityCalculator",
    "PriorityConfig",
    "PrioritizedWork",
    "WorkItem",
    "WorkStatus",
    "WorkType",
    "reset_global_work_queue",
    # Self-improvement pipeline
    "SelfImprovePipeline",
    "SelfImproveConfig",
    "SelfImproveResult",
    # Autonomous assessment engine
    "AutonomousAssessmentEngine",
    "CodebaseHealthReport",
    "ImprovementCandidate",
    "SignalSource",
    # Goal generator
    "GoalGenerator",
    # Self-improvement daemon
    "SelfImprovementDaemon",
    "DaemonConfig",
    "DaemonState",
    "DaemonStatus",
    "CycleResult",
    # Codebase indexer
    "CodebaseIndexer",
    "ModuleInfo",
    "IndexStats",
    # Self-correction
    "SelfCorrectionEngine",
    "SelfCorrectionConfig",
    "CorrectionReport",
    "StrategyRecommendation",
    # SOAR Curriculum
    "CurriculumPlanner",
    "SteppingStoneGenerator",
    "SteppingStone",
    "Curriculum",
    "SkillCategory",
    "generate_curriculum",
    "CurriculumAwareFeedbackLoop",
    "CurriculumConfig",
    "integrate_curriculum_with_orchestrator",
    # Outcome Feedback (lazy-loaded)
    "OutcomeFeedbackBridge",
    "FeedbackGoal",
    # Execution Bridge (lazy-loaded)
    "ExecutionBridge",
    "ExecutionInstruction",
    "ExecutionResult",
    # Code Reviewer
    "CodeReviewerAgent",
    "ReviewConfig",
    "ReviewResult",
    "ReviewIssue",
    "IssueSeverity",
    # Learning Bus
    "Finding",
    "LearningBus",
    # Business Context
    "BusinessContext",
    "BusinessContextConfig",
    "GoalScore",
    # Pattern Fixer
    "ANTIPATTERNS",
    "PatternFixer",
    "PatternMatch",
    "FixResult",
    # Forward Fixer
    "ForwardFixer",
    "ForwardFix",
    "DiagnosisResult",
    "FailureType",
    # Goal Evaluator (lazy-loaded)
    "GoalEvaluator",
    # Worktree Watchdog (lazy-loaded)
    "WorktreeWatchdog",
    "WatchdogConfig",
    "WorktreeSession",
    "HealthReport",
    # Worktree Auditor (lazy-loaded)
    "WorktreeAuditor",
    "AuditorConfig",
    "AuditFinding",
    "AuditReport",
    "WorktreeStatus",
]
