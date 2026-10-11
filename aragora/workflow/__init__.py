"""
Workflow Engine for Aragora.

The Workflow Engine generalizes Aragora's PhaseExecutor pattern to support
arbitrary multi-step workflows with:

- Sequential, parallel, and conditional execution patterns
- Checkpointing and resume for long-running workflows
- Transitions based on step outputs
- Integration with Knowledge Mound

This is the core runtime for the Enterprise Multi-Agent Control Plane.

Usage:
    from aragora.workflow import (
        WorkflowEngine,
        WorkflowDefinition,
        StepDefinition,
        WorkflowContext,
    )

    # Define a workflow
    definition = WorkflowDefinition(
        id="my-workflow",
        name="My Workflow",
        steps=[
            StepDefinition(
                id="step1",
                name="First Step",
                step_type="agent",
                config={"agent_type": "claude", "prompt": "..."},
                next_steps=["step2"],
            ),
            StepDefinition(
                id="step2",
                name="Second Step",
                step_type="agent",
                config={"agent_type": "gpt4", "prompt": "..."},
            ),
        ],
    )

    # Execute
    engine = WorkflowEngine()
    result = await engine.execute(definition, inputs={"task": "..."})
"""

from aragora.workflow.types import (
    ExecutionPattern,
    StepDefinition,
    StepResult,
    StepStatus,
    TransitionRule,
    WorkflowCheckpoint,
    WorkflowConfig,
    WorkflowDefinition,
    WorkflowResult,
)
from aragora.workflow.step import (
    WorkflowStep,
    WorkflowContext,
    BaseStep,
    AgentStep,
    ParallelStep,
    ConditionalStep,
    LoopStep,
)
from aragora.workflow.engine import (
    WorkflowEngine,
    get_workflow_engine,
    reset_workflow_engine,
    get_workflow_executor,
)
from aragora.workflow.executor_protocol import (
    WorkflowExecutor,
    ResumableExecutor,
    ResourceAwareExecutor,
)
from aragora.workflow.resource_tracker import (
    ResourceTracker,
    MODEL_PRICING,
)
from aragora.workflow.queue_adapter import (
    TaskQueueExecutorAdapter,
    get_queue_adapter,
    reset_queue_adapter,
)
from aragora.workflow.engine_v2 import (
    EnhancedWorkflowEngine,
    ResourceLimits,
    ResourceUsage,
    ResourceType,
    ResourceExhaustedError,
    EnhancedWorkflowResult,
)
from aragora.workflow.schema import (
    validate_workflow,
    validate_workflow_file,
    ValidationResult,
    ValidationMessage,
    WorkflowValidator,
)
from aragora.workflow.coverage_tracker import (
    WorkflowCoverageTracker,
    CoverageReport,
    get_tracker as get_coverage_tracker,
    get_coverage_report,
    track_step,
    track_pattern,
    track_template,
    track_config,
    print_coverage_summary,
    KNOWN_STEP_TYPES,
    KNOWN_PATTERNS,
    KNOWN_TEMPLATES,
    KNOWN_CONFIG_DIMENSIONS,
)
from aragora.workflow.persistent_store import (
    PersistentWorkflowStore,
    get_workflow_store,
    get_async_workflow_store,
    create_postgres_workflow_store,
    reset_workflow_store,
)
from aragora.workflow.postgres_workflow_store import PostgresWorkflowStore

__all__ = [
    # Engines
    "WorkflowEngine",
    "get_workflow_engine",
    "reset_workflow_engine",
    "EnhancedWorkflowEngine",
    # Unified executor interface
    "get_workflow_executor",
    "WorkflowExecutor",
    "ResumableExecutor",
    "ResourceAwareExecutor",
    # Queue adapter
    "TaskQueueExecutorAdapter",
    "get_queue_adapter",
    "reset_queue_adapter",
    # Resource management
    "ResourceTracker",
    "ResourceLimits",
    "ResourceUsage",
    "ResourceType",
    "ResourceExhaustedError",
    "EnhancedWorkflowResult",
    "MODEL_PRICING",
    # Validation
    "validate_workflow",
    "validate_workflow_file",
    "ValidationResult",
    "ValidationMessage",
    "WorkflowValidator",
    # Types
    "ExecutionPattern",
    "StepDefinition",
    "StepResult",
    "StepStatus",
    "TransitionRule",
    "WorkflowCheckpoint",
    "WorkflowConfig",
    "WorkflowDefinition",
    "WorkflowResult",
    # Steps
    "WorkflowStep",
    "WorkflowContext",
    "BaseStep",
    "AgentStep",
    "ParallelStep",
    "ConditionalStep",
    "LoopStep",
    # Coverage tracking
    "WorkflowCoverageTracker",
    "CoverageReport",
    "get_coverage_tracker",
    "get_coverage_report",
    "track_step",
    "track_pattern",
    "track_template",
    "track_config",
    "print_coverage_summary",
    "KNOWN_STEP_TYPES",
    "KNOWN_PATTERNS",
    "KNOWN_TEMPLATES",
    "KNOWN_CONFIG_DIMENSIONS",
    # Persistent storage
    "PersistentWorkflowStore",
    "PostgresWorkflowStore",
    "get_workflow_store",
    "get_async_workflow_store",
    "create_postgres_workflow_store",
    "reset_workflow_store",
]

# The core decision router routes workflow decisions through this registration.
from aragora.workflow.decision_route import register_decision_route as _register_decision_route

_register_decision_route()


# ---------------------------------------------------------------------------
# Golden API collision guard (issue #8780)
#
# This subpackage shares its name with the golden callable
# ``aragora.golden.workflow`` that ``aragora/__init__.py`` exports lazily via
# ``_EXPORT_MAP``. When this subpackage is imported, the import system binds
# the module object onto the ``aragora`` package, shadowing the golden
# callable. Making the module itself callable keeps ``aragora.workflow(...)``
# working in every import order while leaving normal module semantics
# (attribute access, ``__path__``, patch targets) untouched.
# ---------------------------------------------------------------------------
import sys as _sys
import types as _types
from typing import Any as _Any


class _CallableWorkflowModule(_types.ModuleType):
    """Module subclass forwarding calls to :func:`aragora.golden.workflow`."""

    def __call__(self, *args: _Any, **kwargs: _Any) -> _Any:
        from aragora.golden import workflow as _golden_workflow

        return _golden_workflow(*args, **kwargs)


_sys.modules[__name__].__class__ = _CallableWorkflowModule
