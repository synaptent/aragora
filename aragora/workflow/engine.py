"""
Workflow Engine for Aragora.

Generalizes the PhaseExecutor pattern from debate orchestration to support
arbitrary multi-step workflows with:
- Sequential, parallel, and conditional execution
- Checkpointing and resume
- Transitions based on step outputs
- Integration with Knowledge Mound

This is the core runtime for the Enterprise Control Plane.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from collections.abc import Callable

from aragora.events.types import StreamEventType
from aragora.workflow.safe_eval import SafeEvalError, safe_eval_bool
from aragora.workflow.types import (
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
    AgentStep,
    ParallelStep,
    ConditionalStep,
    LoopStep,
)
from aragora.workflow.checkpoint_store import (
    CheckpointStore,
    get_checkpoint_store,
    LRUCheckpointCache,
)

# Observability
from aragora.observability import get_logger, create_span, add_span_attributes

logger = get_logger(__name__)


class WorkflowEngine:
    """
    Executes workflows defined by WorkflowDefinition.

    The engine supports:
    - Sequential step execution with configurable order
    - Parallel execution for hive-mind patterns
    - Conditional transitions based on step outputs
    - Checkpointing for long-running workflows
    - Integration with the Phase protocol for Aragora debates

    Usage:
        engine = WorkflowEngine()

        # Register step implementations
        engine.register_step_type("agent", AgentStep)
        engine.register_step_type("parallel", ParallelStep)

        # Execute workflow
        result = await engine.execute(definition, inputs)

        # Resume from checkpoint
        result = await engine.resume(workflow_id, checkpoint)
    """

    def __init__(
        self,
        config: WorkflowConfig | None = None,
        step_registry: dict[str, type[WorkflowStep]] | None = None,
        checkpoint_store: CheckpointStore | None = None,
    ):
        self._config = config or WorkflowConfig()

        # Step type registry
        self._step_types: dict[str, type[WorkflowStep]] = step_registry or {}
        self._register_default_step_types()

        # Step instance cache
        self._step_instances: dict[str, WorkflowStep] = {}

        # Execution state
        self._current_step: str | None = None
        self._should_terminate: bool = False
        self._termination_reason: str | None = None
        self._results: list[StepResult] = []

        # Checkpoint storage - use provided store or fall back to file-based
        self._checkpoint_store: CheckpointStore = checkpoint_store or get_checkpoint_store()
        # LRU cache for fast lookups during execution (bounded to prevent memory growth)
        self._checkpoints_cache: LRUCheckpointCache = LRUCheckpointCache(max_size=100)

        # Timeout tracking for progressive warnings
        self._timeout_warning_thresholds = [0.5, 0.8, 0.9]  # Warn at 50%, 80%, 90%
        self._timeout_warnings_issued: set[float] = set()

    def _register_default_step_types(self) -> None:
        """Register built-in step types."""
        self._step_types["agent"] = AgentStep
        self._step_types["parallel"] = ParallelStep
        self._step_types["conditional"] = ConditionalStep
        self._step_types["loop"] = LoopStep

        # Phase 2: Register new step types for workflow builder
        try:
            from aragora.workflow.nodes import (
                HumanCheckpointStep,
                MemoryReadStep,
                MemoryWriteStep,
                DebateStep,
                DecisionStep,
                TaskStep,
                ConnectorStep,
            )
            from aragora.workflow.nodes.decision import SwitchStep
            from aragora.workflow.nodes.debate import QuickDebateStep

            self._step_types["human_checkpoint"] = HumanCheckpointStep
            self._step_types["memory_read"] = MemoryReadStep
            self._step_types["memory_write"] = MemoryWriteStep
            self._step_types["debate"] = DebateStep
            self._step_types["quick_debate"] = QuickDebateStep
            self._step_types["decision"] = DecisionStep
            self._step_types["switch"] = SwitchStep
            self._step_types["task"] = TaskStep
            self._step_types["connector"] = ConnectorStep
        except ImportError as e:
            logger.debug("Some Phase 2 step types not available: %s", e)

        # Nomic loop step aliases
        try:
            from aragora.workflow.nodes.nomic import NomicLoopStep

            self._step_types["nomic"] = NomicLoopStep
            self._step_types["nomic_loop"] = NomicLoopStep
        except ImportError as e:
            logger.debug("Nomic step type not available: %s", e)

        # Implementation pipeline steps (gold path)
        try:
            from aragora.workflow.nodes.implementation import (
                ImplementationStep,
                VerificationStep,
            )

            self._step_types["implementation"] = ImplementationStep
            self._step_types["verification"] = VerificationStep
        except ImportError as e:
            logger.debug("Implementation step types not available: %s", e)

        # OpenClaw Enterprise Gateway steps
        try:
            from aragora.workflow.nodes.openclaw import (
                OpenClawActionStep,
                OpenClawSessionStep,
            )

            self._step_types["openclaw_action"] = OpenClawActionStep
            self._step_types["openclaw_session"] = OpenClawSessionStep
        except ImportError as e:
            logger.debug("OpenClaw step types not available: %s", e)

        # Computer-use step (Playwright + Claude)
        try:
            from aragora.workflow.nodes.computer_use import ComputerUseTaskStep

            self._step_types["computer_use_task"] = ComputerUseTaskStep
        except ImportError as e:
            logger.debug("Computer-use step type not available: %s", e)

        # Content extraction step
        try:
            from aragora.workflow.nodes.content_extraction import ContentExtractionStep

            self._step_types["content_extraction"] = ContentExtractionStep
        except ImportError as e:
            logger.debug("Content extraction step type not available: %s", e)

    def register_step_type(self, type_name: str, step_class: type[WorkflowStep]) -> None:
        """
        Register a custom step type.

        Args:
            type_name: Name to identify the step type
            step_class: Class implementing WorkflowStep protocol
        """
        self._step_types[type_name] = step_class
        logger.debug("Registered step type: %s", type_name)

    def _check_timeout_progress(
        self,
        start_time: float,
        total_timeout: float,
        workflow_id: str,
    ) -> None:
        """
        Check workflow execution progress and issue timeout warnings.

        Issues warnings at configured thresholds (50%, 80%, 90%) to allow
        for proactive monitoring and intervention.
        """
        if total_timeout <= 0:
            return

        elapsed = time.time() - start_time
        progress = elapsed / total_timeout

        for threshold in self._timeout_warning_thresholds:
            if progress >= threshold and threshold not in self._timeout_warnings_issued:
                self._timeout_warnings_issued.add(threshold)
                remaining = total_timeout - elapsed
                logger.warning(
                    "workflow_timeout_warning",
                    workflow_id=workflow_id,
                    progress_pct=int(progress * 100),
                    elapsed_seconds=round(elapsed, 1),
                    remaining_seconds=round(remaining, 1),
                    threshold_pct=int(threshold * 100),
                )

    def get_checkpoint_cache_stats(self) -> dict[str, Any]:
        """Get statistics about the checkpoint cache."""
        return self._checkpoints_cache.stats

    def _merge_metadata(
        self,
        definition: WorkflowDefinition,
        override: dict[str, Any] | None = None,
        checkpoint_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Merge workflow metadata from definition, checkpoint, and per-execution override."""
        merged: dict[str, Any] = {}
        if isinstance(definition.metadata, dict):
            merged.update(definition.metadata)
        if isinstance(checkpoint_metadata, dict):
            merged.update(checkpoint_metadata)
        if isinstance(override, dict):
            merged.update(override)
        return merged

    def _base_event_payload(self, context: WorkflowContext) -> dict[str, Any]:
        """Build a base payload for workflow lifecycle events."""
        payload: dict[str, Any] = {
            "workflow_id": context.workflow_id,
            "definition_id": context.definition_id,
        }
        metadata = context.metadata if isinstance(context.metadata, dict) else {}
        workflow_name = metadata.get("workflow_name")
        if workflow_name:
            payload["workflow_name"] = workflow_name
        tenant_id = metadata.get("tenant_id") or metadata.get("workspace_id")
        if tenant_id:
            payload["tenant_id"] = tenant_id
        org_id = metadata.get("org_id")
        if org_id:
            payload["org_id"] = org_id
        user_id = metadata.get("user_id")
        if user_id:
            payload["user_id"] = user_id
        plan_id = metadata.get("plan_id")
        if plan_id:
            payload["plan_id"] = plan_id
        execution_mode = metadata.get("execution_mode")
        if execution_mode:
            payload["execution_mode"] = execution_mode
        return payload

    def _emit_event(
        self,
        context: WorkflowContext,
        event_type: StreamEventType | str,
        payload: dict[str, Any],
    ) -> None:
        """Emit workflow event to per-execution and configured callbacks.

        Also dispatches lifecycle events (start, step_complete, complete, failed)
        to the webhook event dispatcher for external delivery.
        """
        event_name = (
            event_type.value if isinstance(event_type, StreamEventType) else str(event_type)
        )

        if context.event_callback:
            try:
                context.event_callback(event_name, payload)
            except (RuntimeError, ValueError, TypeError, OSError, AttributeError) as exc:
                logger.debug("Workflow event callback failed: %s", exc)

        if self._config.trace_callback:
            try:
                self._config.trace_callback(event_name, payload)
            except (RuntimeError, ValueError, TypeError, OSError, AttributeError) as exc:
                logger.debug("Workflow trace callback failed: %s", exc)

        # Bridge to webhook event dispatcher for external delivery
        self._dispatch_to_event_system(event_name, payload)

    def _dispatch_to_event_system(
        self,
        event_name: str,
        payload: dict[str, Any],
    ) -> None:
        """Dispatch workflow lifecycle events to the webhook event system.

        Only dispatches key lifecycle events to avoid flooding webhooks.
        Gracefully degrades if the event dispatcher is unavailable.
        """
        _DISPATCHED_EVENTS = {
            "workflow_start",
            "workflow_step_complete",
            "workflow_complete",
            "workflow_failed",
        }
        if event_name not in _DISPATCHED_EVENTS:
            return

        try:
            from aragora.events.dispatcher import dispatch_event

            dispatch_event(event_name, payload)
        except (ImportError, RuntimeError, OSError) as exc:
            logger.debug("Workflow event dispatch skipped: %s", exc)

    # =========================================================================
    # Main Execution
    # =========================================================================

    async def execute(
        self,
        definition: WorkflowDefinition,
        inputs: dict[str, Any] | None = None,
        workflow_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> WorkflowResult:
        """
        Execute a workflow from the beginning.

        Args:
            definition: Workflow definition to execute
            inputs: Input parameters for the workflow
            workflow_id: Optional ID (generated if not provided)
            metadata: Optional metadata injected into workflow context
            event_callback: Optional callback for workflow progress events

        Returns:
            WorkflowResult with step results and final output
        """
        workflow_id = workflow_id or f"wf_{uuid.uuid4().hex[:12]}"
        inputs = inputs or {}
        metadata = self._merge_metadata(definition, metadata)
        metadata.setdefault("workflow_name", definition.name)

        logger.info(
            "workflow_started",
            workflow_id=workflow_id,
            workflow_name=definition.name,
            step_count=len(definition.steps),
        )

        # Create execution context
        context = WorkflowContext(
            workflow_id=workflow_id,
            definition_id=definition.id,
            inputs=inputs,
            metadata=metadata,
            event_callback=event_callback,
        )

        self._emit_event(
            context,
            StreamEventType.WORKFLOW_START,
            {
                **self._base_event_payload(context),
                "step_count": len(definition.steps),
            },
        )

        # Reset execution state
        self._results = []
        self._should_terminate = False
        self._termination_reason = None

        start_time = time.time()
        checkpoints_created = 0

        with create_span(
            "workflow.execute",
            {
                "workflow_id": workflow_id,
                "workflow_name": definition.name,
                "step_count": len(definition.steps),
            },
        ) as span:
            try:
                # Execute with overall timeout
                final_output = await asyncio.wait_for(
                    self._execute_workflow(definition, context),
                    timeout=self._config.total_timeout_seconds,
                )
                success = all(r.success for r in self._results)
                error = None

            except asyncio.TimeoutError:
                logger.error(
                    "workflow_timeout",
                    workflow_id=workflow_id,
                    timeout_seconds=self._config.total_timeout_seconds,
                )
                success = False
                error = f"Workflow timed out after {self._config.total_timeout_seconds}s"
                final_output = None

            except (
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
                ConnectionError,
                KeyError,
                AttributeError,
            ) as e:
                logger.exception(
                    "workflow_failed",
                    workflow_id=workflow_id,
                    error=str(e),
                )
                success = False
                error = "Workflow execution failed"
                final_output = None

            total_duration = (time.time() - start_time) * 1000
            add_span_attributes(
                span,
                {
                    "success": success,
                    "duration_ms": total_duration,
                    "steps_executed": len(self._results),
                },
            )

            logger.info(
                "workflow_completed",
                workflow_id=workflow_id,
                success=success,
                duration_ms=total_duration,
                steps_executed=len(self._results),
            )

            event_payload = {
                **self._base_event_payload(context),
                "success": success,
                "duration_ms": total_duration,
                "steps_executed": len(self._results),
                "error": error,
            }
            if self._should_terminate:
                self._emit_event(context, StreamEventType.WORKFLOW_TERMINATED, event_payload)
            elif success:
                self._emit_event(context, StreamEventType.WORKFLOW_COMPLETE, event_payload)
            else:
                self._emit_event(context, StreamEventType.WORKFLOW_FAILED, event_payload)

            # Emit aggregate metrics for performance monitoring
            self._emit_event(
                context,
                StreamEventType.WORKFLOW_METRICS,
                {
                    **self._base_event_payload(context),
                    "total_duration_ms": total_duration,
                    "steps_executed": len(self._results),
                    "steps_succeeded": sum(1 for r in self._results if r.success),
                    "steps_failed": sum(1 for r in self._results if not r.success),
                    "checkpoints_created": checkpoints_created,
                    "success": success,
                },
            )

            return WorkflowResult(
                workflow_id=workflow_id,
                definition_id=definition.id,
                success=success,
                steps=self._results.copy(),
                total_duration_ms=total_duration,
                final_output=final_output,
                error=error,
                checkpoints_created=checkpoints_created,
            )

    async def resume(
        self,
        workflow_id: str,
        checkpoint: WorkflowCheckpoint,
        definition: WorkflowDefinition,
        metadata: dict[str, Any] | None = None,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> WorkflowResult:
        """
        Resume a workflow from a checkpoint.

        Args:
            workflow_id: ID of the workflow to resume
            checkpoint: Checkpoint to resume from
            definition: Workflow definition
            metadata: Optional metadata injected into workflow context
            event_callback: Optional callback for workflow progress events

        Returns:
            WorkflowResult from resumed execution
        """
        logger.info("Resuming workflow %s from step %s", workflow_id, checkpoint.current_step)

        metadata = self._merge_metadata(
            definition, metadata, checkpoint.context_state.get("metadata")
        )
        metadata.setdefault("workflow_name", definition.name)

        # Restore context from checkpoint
        context = WorkflowContext(
            workflow_id=workflow_id,
            definition_id=checkpoint.definition_id,
            inputs=checkpoint.context_state.get("inputs", {}),
            step_outputs=checkpoint.step_outputs,
            state=checkpoint.context_state.get("state", {}),
            metadata=metadata,
            event_callback=event_callback,
        )

        self._emit_event(
            context,
            StreamEventType.WORKFLOW_RESUMED,
            {
                **self._base_event_payload(context),
                "checkpoint_id": checkpoint.id,
                "current_step": checkpoint.current_step,
            },
        )

        # Reset execution state
        self._results = []
        self._should_terminate = False

        start_time = time.time()

        try:
            # Execute remaining steps
            final_output = await asyncio.wait_for(
                self._execute_from_step(
                    definition,
                    context,
                    checkpoint.current_step,
                    set(checkpoint.completed_steps),
                ),
                timeout=self._config.total_timeout_seconds,
            )
            success = all(r.success for r in self._results)
            error = None

        except asyncio.TimeoutError:
            success = False
            error = "Workflow timed out"
            final_output = None

        except (
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            ConnectionError,
            KeyError,
            AttributeError,
        ) as e:
            logger.exception("Workflow resume failed: %s", e)
            success = False
            error = "Workflow resume failed"
            final_output = None

        total_duration = (time.time() - start_time) * 1000

        event_payload = {
            **self._base_event_payload(context),
            "success": success,
            "duration_ms": total_duration,
            "steps_executed": len(self._results),
            "error": error,
        }
        if self._should_terminate:
            self._emit_event(context, StreamEventType.WORKFLOW_TERMINATED, event_payload)
        elif success:
            self._emit_event(context, StreamEventType.WORKFLOW_COMPLETE, event_payload)
        else:
            self._emit_event(context, StreamEventType.WORKFLOW_FAILED, event_payload)

        return WorkflowResult(
            workflow_id=workflow_id,
            definition_id=definition.id,
            success=success,
            steps=self._results.copy(),
            total_duration_ms=total_duration,
            final_output=final_output,
            error=error,
        )

    # =========================================================================
    # Internal Execution
    # =========================================================================

    async def _execute_workflow(
        self,
        definition: WorkflowDefinition,
        context: WorkflowContext,
    ) -> Any:
        """Execute workflow from entry step."""
        if not definition.entry_step:
            raise ValueError("Workflow has no entry step")

        return await self._execute_from_step(definition, context, definition.entry_step, set())

    async def _execute_from_step(
        self,
        definition: WorkflowDefinition,
        context: WorkflowContext,
        start_step: str,
        completed_steps: set[str],
    ) -> Any:
        """Execute workflow starting from a specific step."""
        current_step_id = start_step
        final_output = None
        step_count = 0
        workflow_start_time = time.time()

        # Reset timeout warnings for this execution
        self._timeout_warnings_issued = set()

        while current_step_id and not self._should_terminate:
            # Check for progressive timeout warnings
            self._check_timeout_progress(
                workflow_start_time,
                self._config.total_timeout_seconds,
                context.workflow_id,
            )
            step_def = definition.get_step(current_step_id)
            if not step_def:
                logger.error("Step '%s' not found in definition", current_step_id)
                break

            # Skip already completed steps
            if current_step_id in completed_steps:
                next_step = self._get_next_step(definition, current_step_id, context)
                if next_step:
                    self._emit_event(
                        context,
                        StreamEventType.WORKFLOW_TRANSITION,
                        {
                            **self._base_event_payload(context),
                            "from_step": current_step_id,
                            "to_step": next_step,
                        },
                    )
                current_step_id = next_step
                continue

            # Execute the step
            result = await self._execute_step(step_def, context)
            self._results.append(result)
            step_count += 1

            # Store output in context
            if result.output is not None:
                context.step_outputs[current_step_id] = result.output
                final_output = result.output

            # Handle failure
            if not result.success:
                if self._config.stop_on_failure and not step_def.optional:
                    logger.error("Step '%s' failed, stopping workflow", current_step_id)
                    break
                elif step_def.optional:
                    logger.warning("Optional step '%s' failed, continuing", current_step_id)

            # Create checkpoint if enabled
            if (
                self._config.enable_checkpointing
                and step_count % self._config.checkpoint_interval_steps == 0
            ):
                await self._create_checkpoint(
                    context.workflow_id,
                    definition.id,
                    current_step_id,
                    set(r.step_id for r in self._results if r.success),
                    context,
                )

            # Determine next step
            next_step = self._get_next_step(definition, current_step_id, context)
            if next_step:
                self._emit_event(
                    context,
                    StreamEventType.WORKFLOW_TRANSITION,
                    {
                        **self._base_event_payload(context),
                        "from_step": current_step_id,
                        "to_step": next_step,
                    },
                )
            current_step_id = next_step

        return final_output

    async def _execute_step(
        self,
        step_def: StepDefinition,
        context: WorkflowContext,
    ) -> StepResult:
        """Execute a single workflow step."""
        self._current_step = step_def.id
        started_at = datetime.now(timezone.utc)
        start_time = time.time()

        logger.debug(
            "step_started",
            step_id=step_def.id,
            step_name=step_def.name,
            step_type=step_def.step_type,
            workflow_id=context.workflow_id,
        )

        self._emit_event(
            context,
            StreamEventType.WORKFLOW_STEP_START,
            {
                **self._base_event_payload(context),
                "step_id": step_def.id,
                "step_name": step_def.name,
                "step_type": step_def.step_type,
                "optional": step_def.optional,
                "retry_count": 0,
            },
        )

        with create_span(
            "workflow.step",
            {
                "step_id": step_def.id,
                "step_name": step_def.name,
                "step_type": step_def.step_type,
                "workflow_id": context.workflow_id,
            },
        ) as span:
            # Update context with current step info
            context.current_step_id = step_def.id
            context.current_step_config = step_def.config

            # Get or create step instance
            step = self._get_step_instance(step_def)
            if step is None:
                add_span_attributes(span, {"success": False, "error": "unknown_step_type"})
                self._emit_event(
                    context,
                    StreamEventType.WORKFLOW_STEP_FAILED,
                    {
                        **self._base_event_payload(context),
                        "step_id": step_def.id,
                        "step_name": step_def.name,
                        "step_type": step_def.step_type,
                        "status": StepStatus.FAILED.value,
                        "error": f"Unknown step type: {step_def.step_type}",
                    },
                )
                return StepResult(
                    step_id=step_def.id,
                    step_name=step_def.name,
                    status=StepStatus.FAILED,
                    error=f"Unknown step type: {step_def.step_type}",
                )

            # Execute with retries
            retry_count = 0
            last_error = None

            while retry_count <= step_def.retries:
                try:
                    output = await asyncio.wait_for(
                        step.execute(context),
                        timeout=step_def.timeout_seconds,
                    )

                    duration_ms = (time.time() - start_time) * 1000
                    add_span_attributes(
                        span,
                        {
                            "success": True,
                            "duration_ms": duration_ms,
                            "retry_count": retry_count,
                        },
                    )
                    logger.debug(
                        "step_completed",
                        step_id=step_def.id,
                        step_name=step_def.name,
                        duration_ms=duration_ms,
                    )

                    self._emit_event(
                        context,
                        StreamEventType.WORKFLOW_STEP_COMPLETE,
                        {
                            **self._base_event_payload(context),
                            "step_id": step_def.id,
                            "step_name": step_def.name,
                            "step_type": step_def.step_type,
                            "status": StepStatus.COMPLETED.value,
                            "duration_ms": duration_ms,
                            "retry_count": retry_count,
                        },
                    )

                    return StepResult(
                        step_id=step_def.id,
                        step_name=step_def.name,
                        status=StepStatus.COMPLETED,
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc),
                        duration_ms=duration_ms,
                        output=output,
                        retry_count=retry_count,
                    )

                except asyncio.TimeoutError:
                    last_error = f"Timed out after {step_def.timeout_seconds}s"
                    retry_count += 1
                    if retry_count <= step_def.retries:
                        logger.warning(
                            "step_timeout_retry",
                            step_name=step_def.name,
                            retry=retry_count,
                            max_retries=step_def.retries,
                        )

                except (
                    RuntimeError,
                    ValueError,
                    TypeError,
                    OSError,
                    ConnectionError,
                    KeyError,
                    AttributeError,
                ) as e:
                    last_error = "Step execution failed"
                    retry_count += 1
                    if retry_count <= step_def.retries:
                        logger.warning(
                            "step_error_retry",
                            step_name=step_def.name,
                            error=str(e),
                            retry=retry_count,
                            max_retries=step_def.retries,
                        )

            # All retries exhausted
            duration_ms = (time.time() - start_time) * 1000
            add_span_attributes(
                span,
                {
                    "success": False,
                    "duration_ms": duration_ms,
                    "retry_count": retry_count,
                    "error": last_error,
                },
            )

            if step_def.optional and self._config.skip_optional_on_timeout:
                logger.info(
                    "step_skipped",
                    step_id=step_def.id,
                    step_name=step_def.name,
                    reason="optional_timeout",
                )
                self._emit_event(
                    context,
                    StreamEventType.WORKFLOW_STEP_SKIPPED,
                    {
                        **self._base_event_payload(context),
                        "step_id": step_def.id,
                        "step_name": step_def.name,
                        "step_type": step_def.step_type,
                        "status": StepStatus.SKIPPED.value,
                        "duration_ms": duration_ms,
                        "retry_count": retry_count,
                        "error": last_error,
                    },
                )
                return StepResult(
                    step_id=step_def.id,
                    step_name=step_def.name,
                    status=StepStatus.SKIPPED,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    duration_ms=duration_ms,
                    error=last_error,
                    retry_count=retry_count,
                )
            else:
                logger.error(
                    "step_failed",
                    step_id=step_def.id,
                    step_name=step_def.name,
                    error=last_error,
                    retry_count=retry_count,
                )
                self._emit_event(
                    context,
                    StreamEventType.WORKFLOW_STEP_FAILED,
                    {
                        **self._base_event_payload(context),
                        "step_id": step_def.id,
                        "step_name": step_def.name,
                        "step_type": step_def.step_type,
                        "status": StepStatus.FAILED.value,
                        "duration_ms": duration_ms,
                        "retry_count": retry_count,
                        "error": last_error,
                    },
                )
                return StepResult(
                    step_id=step_def.id,
                    step_name=step_def.name,
                    status=StepStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    duration_ms=duration_ms,
                    error=last_error,
                    retry_count=retry_count,
                )

    def _get_step_instance(self, step_def: StepDefinition) -> WorkflowStep | None:
        """Get or create a step instance."""
        cache_key = f"{step_def.id}:{step_def.step_type}"

        if cache_key in self._step_instances:
            return self._step_instances[cache_key]

        step_class = self._step_types.get(step_def.step_type)
        if step_class is None:
            return None

        try:
            # Create step instance with config.
            # Step classes are registered dynamically via register_step_type() and have
            # varying constructor signatures. The WorkflowStep protocol intentionally
            # doesn't specify __init__ to allow flexibility. BaseStep subclasses accept
            # (name, config) but external step types may differ.
            step = step_class(name=step_def.name, config=step_def.config)  # type: ignore[call-arg]
            self._step_instances[cache_key] = step
            return step
        except (TypeError, ValueError, AttributeError, RuntimeError, ImportError) as e:
            logger.error("Failed to create step instance: %s", e)
            return None

    def _get_next_step(
        self,
        definition: WorkflowDefinition,
        current_step_id: str,
        context: WorkflowContext,
    ) -> str | None:
        """Determine the next step based on transitions and step output."""
        step_def = definition.get_step(current_step_id)
        if not step_def:
            return None

        # Check conditional transitions first
        transitions = definition.get_transitions_from(current_step_id)
        for transition in transitions:
            if self._evaluate_transition(transition, context):
                logger.debug("Taking transition %s -> %s", current_step_id, transition.to_step)
                return transition.to_step

        # Fall back to default next steps
        if step_def.next_steps:
            return step_def.next_steps[0]

        return None

    def _evaluate_transition(
        self,
        transition: TransitionRule,
        context: WorkflowContext,
    ) -> bool:
        """Evaluate a transition condition using AST-based evaluator."""
        try:
            namespace = {
                "inputs": context.inputs,
                "outputs": context.step_outputs,
                "state": context.state,
                "step_output": context.step_outputs.get(transition.from_step),
            }
            return safe_eval_bool(transition.condition, namespace)
        except SafeEvalError as e:
            logger.warning("Failed to evaluate transition condition: %s", e)
            return False

    # =========================================================================
    # Checkpointing
    # =========================================================================

    async def _create_checkpoint(
        self,
        workflow_id: str,
        definition_id: str,
        current_step: str,
        completed_steps: set[str],
        context: WorkflowContext,
    ) -> WorkflowCheckpoint:
        """Create a checkpoint of current workflow state."""
        checkpoint_id = f"cp_{uuid.uuid4().hex[:12]}"

        # Create state snapshot
        context_state = {
            "inputs": context.inputs,
            "state": context.state,
            "metadata": context.metadata,
        }

        # Compute checksum
        state_json = json.dumps(context_state, sort_keys=True, default=str)
        checksum = hashlib.sha256(state_json.encode()).hexdigest()[:16]

        checkpoint = WorkflowCheckpoint(
            id=checkpoint_id,
            workflow_id=workflow_id,
            definition_id=definition_id,
            current_step=current_step,
            completed_steps=list(completed_steps),
            step_outputs=context.step_outputs.copy(),
            context_state=context_state,
            created_at=datetime.now(timezone.utc),
            checksum=checksum,
        )

        # Persist checkpoint to storage
        try:
            await self._checkpoint_store.save(checkpoint)
            logger.debug("Persisted checkpoint %s at step %s", checkpoint_id, current_step)
        except (OSError, RuntimeError, ConnectionError, ValueError, TypeError) as e:
            logger.warning("Failed to persist checkpoint %s: %s", checkpoint_id, e)

        # Also cache in memory for fast access during execution
        self._checkpoints_cache.put(checkpoint_id, checkpoint)

        self._emit_event(
            context,
            StreamEventType.WORKFLOW_CHECKPOINT,
            {
                **self._base_event_payload(context),
                "checkpoint_id": checkpoint_id,
                "current_step": current_step,
                "completed_steps": list(completed_steps),
            },
        )

        return checkpoint

    async def get_checkpoint(self, checkpoint_id: str) -> WorkflowCheckpoint | None:
        """Get a checkpoint by ID."""
        # Check cache first
        cached = self._checkpoints_cache.get(checkpoint_id)
        if cached is not None:
            return cached

        # Load from persistent storage
        try:
            checkpoint = await self._checkpoint_store.load(checkpoint_id)
            if checkpoint:
                self._checkpoints_cache.put(checkpoint_id, checkpoint)
            return checkpoint
        except (OSError, RuntimeError, ConnectionError, ValueError, TypeError) as e:
            logger.warning("Failed to load checkpoint %s: %s", checkpoint_id, e)
            return None

    async def get_latest_checkpoint(self, workflow_id: str) -> WorkflowCheckpoint | None:
        """Get the most recent checkpoint for a workflow."""
        try:
            return await self._checkpoint_store.load_latest(workflow_id)
        except (OSError, RuntimeError, ConnectionError, ValueError, TypeError) as e:
            logger.warning("Failed to load latest checkpoint for %s: %s", workflow_id, e)
            return None

    async def list_checkpoints(self, workflow_id: str) -> list[str]:
        """List all checkpoint IDs for a workflow."""
        try:
            return await self._checkpoint_store.list_checkpoints(workflow_id)
        except (OSError, RuntimeError, ConnectionError, ValueError, TypeError) as e:
            logger.warning("Failed to list checkpoints for %s: %s", workflow_id, e)
            return []

    async def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a checkpoint."""
        try:
            # Remove from cache
            self._checkpoints_cache.remove(checkpoint_id)
            # Remove from persistent storage
            return await self._checkpoint_store.delete(checkpoint_id)
        except (OSError, RuntimeError, ConnectionError, ValueError, TypeError) as e:
            logger.warning("Failed to delete checkpoint %s: %s", checkpoint_id, e)
            return False

    # =========================================================================
    # Termination Control
    # =========================================================================

    def request_termination(self, reason: str = "Requested") -> None:
        """Request early termination of workflow execution."""
        self._should_terminate = True
        self._termination_reason = reason
        logger.info("Workflow termination requested: %s", reason)

    def check_termination(self) -> tuple[bool, str | None]:
        """Check if termination has been requested."""
        return self._should_terminate, self._termination_reason

    @property
    def current_step(self) -> str | None:
        """Get currently executing step ID."""
        return self._current_step

    # =========================================================================
    # Metrics
    # =========================================================================

    def get_metrics(self) -> dict[str, Any]:
        """Get execution metrics."""
        total_duration = sum(r.duration_ms for r in self._results)
        completed = sum(1 for r in self._results if r.status == StepStatus.COMPLETED)
        failed = sum(1 for r in self._results if r.status == StepStatus.FAILED)
        skipped = sum(1 for r in self._results if r.status == StepStatus.SKIPPED)

        return {
            "total_steps": len(self._results),
            "completed_steps": completed,
            "failed_steps": failed,
            "skipped_steps": skipped,
            "total_duration_ms": total_duration,
            "step_durations": {r.step_id: r.duration_ms for r in self._results},
            "current_step": self._current_step,
            "terminated_early": self._should_terminate,
            "termination_reason": self._termination_reason,
        }


# Singleton instance
_workflow_engine_instance: WorkflowEngine | None = None


def get_workflow_engine(config: WorkflowConfig | None = None) -> WorkflowEngine:
    """
    Get or create the global WorkflowEngine singleton.

    This provides a shared WorkflowEngine instance that can be used
    across the application for executing workflows.

    Args:
        config: Optional WorkflowConfig for customization

    Returns:
        WorkflowEngine instance
    """
    global _workflow_engine_instance

    if _workflow_engine_instance is None:
        logger.info("[workflow] Creating singleton WorkflowEngine instance")
        _workflow_engine_instance = WorkflowEngine(config=config)

    return _workflow_engine_instance


def reset_workflow_engine() -> None:
    """Reset the global WorkflowEngine singleton (for testing)."""
    global _workflow_engine_instance
    _workflow_engine_instance = None


# Backward-compatible alias
Workflow = WorkflowEngine


# =========================================================================
# Unified Executor Factory
# =========================================================================


def get_workflow_executor(
    mode: str = "default",
    config: WorkflowConfig | None = None,
    resource_limits: Any = None,
) -> Any:
    """
    Get a workflow executor by mode.

    This factory provides a unified way to obtain different workflow
    execution backends through a common interface.

    Args:
        mode: Executor mode - one of:
            - "default": WorkflowEngine (DAG-based with checkpointing)
            - "enhanced": EnhancedWorkflowEngine (resource-aware)
            - "queue": TaskQueueExecutorAdapter (priority queue-based)
        config: Optional WorkflowConfig for customization
        resource_limits: Optional ResourceLimits for enhanced mode

    Returns:
        A workflow executor implementing the WorkflowExecutor protocol

    Example:
        # Get default engine
        executor = get_workflow_executor()

        # Get resource-aware engine
        from aragora.workflow import ResourceLimits
        executor = get_workflow_executor(
            mode="enhanced",
            resource_limits=ResourceLimits(max_cost_usd=5.0)
        )

        # Get queue-based executor
        executor = get_workflow_executor(mode="queue")

        # All executors share the same interface
        result = await executor.execute(definition, inputs)
    """
    if mode == "default":
        return get_workflow_engine(config)

    elif mode == "enhanced":
        from aragora.workflow.engine_v2 import EnhancedWorkflowEngine, ResourceLimits

        limits = resource_limits or ResourceLimits()
        return EnhancedWorkflowEngine(config=config, limits=limits)

    elif mode == "queue":
        from aragora.workflow.queue_adapter import get_queue_adapter

        return get_queue_adapter()

    else:
        raise ValueError(
            f"Unknown executor mode: {mode}. Valid modes are: 'default', 'enhanced', 'queue'"
        )
