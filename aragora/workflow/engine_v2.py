"""
Enhanced Workflow Engine with Resource Limits and Pattern Support.

Extends the base WorkflowEngine with:
- Resource tracking (tokens, cost, time)
- Resource limit enforcement
- Pattern-based workflow creation
- Parallel step execution for hive-mind patterns
- Cost estimation and budgeting
- Real-time metrics streaming

Usage:
    from aragora.workflow.engine_v2 import EnhancedWorkflowEngine, ResourceLimits
    from aragora.workflow.patterns import HiveMindPattern

    # Create engine with limits
    engine = EnhancedWorkflowEngine(
        limits=ResourceLimits(
            max_tokens=100000,
            max_cost_usd=5.0,
            timeout_seconds=600,
        )
    )

    # Create and run a pattern-based workflow
    workflow = HiveMindPattern.create(
        name="Contract Review",
        agents=["claude", "gpt4", "gemini"],
        task="Analyze this contract for risks",
    )

    result = await engine.execute(workflow, inputs={"contract": "..."})
    print(f"Total cost: ${result.metrics['total_cost_usd']:.4f}")
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from collections.abc import Callable

from aragora.config import DEFAULT_ROUNDS
from aragora.config.settings import get_settings
from aragora.events.types import StreamEventType
from aragora.models.pricing_mirror import per_1k_rows
from aragora.workflow.engine import WorkflowEngine
from aragora.workflow.types import (
    ExecutionPattern,
    StepDefinition,
    StepResult,
    StepStatus,
    WorkflowConfig,
    WorkflowDefinition,
    WorkflowResult,
)
from aragora.workflow.step import WorkflowContext, WorkflowStep

logger = logging.getLogger(__name__)

# Model pricing, USD per 1K tokens. Hand-written HISTORICAL rows (kept
# verbatim: a stored workflow record naming ``gpt-4o`` must keep pricing at
# gpt-4o's rate, and the family labels are what ``add_tokens`` receives as
# ``agent_type``) plus one generated row per spelling of every active
# catalog row, so a live frontier call no longer falls through to
# ``default``. See aragora/workflow/resource_tracker.py for the same merge.
_LEGACY_MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
    "claude": {"input": 0.003, "output": 0.015},  # Default to sonnet
    # OpenAI
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    # Google
    "gemini-pro": {"input": 0.00025, "output": 0.0005},
    "gemini": {"input": 0.00025, "output": 0.0005},
    # Mistral
    "mistral-large": {"input": 0.004, "output": 0.012},
    "mistral": {"input": 0.004, "output": 0.012},
    # Others
    "grok": {"input": 0.005, "output": 0.015},
    "deepseek": {"input": 0.00014, "output": 0.00028},
    # Default
    "default": {"input": 0.003, "output": 0.015},
}

MODEL_PRICING: dict[str, dict[str, float]] = {**_LEGACY_MODEL_PRICING, **per_1k_rows()}


class ResourceExhaustedError(Exception):
    """Raised when resource limits are exceeded."""

    pass


class ResourceType(Enum):
    """Types of resources tracked."""

    TOKENS = "tokens"
    COST = "cost"
    TIME = "time"
    API_CALLS = "api_calls"


@dataclass
class ResourceLimits:
    """Resource limits for workflow execution."""

    max_tokens: int = 100000
    max_cost_usd: float = 10.0
    timeout_seconds: float = 600.0
    max_api_calls: int = 100
    max_parallel_agents: int = 5
    max_retries_per_step: int = 3

    # Warning thresholds (percentage of limit)
    warning_threshold: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
            "timeout_seconds": self.timeout_seconds,
            "max_api_calls": self.max_api_calls,
            "max_parallel_agents": self.max_parallel_agents,
            "max_retries_per_step": self.max_retries_per_step,
        }


@dataclass
class ResourceUsage:
    """Tracks resource usage during workflow execution."""

    tokens_used: int = 0
    cost_usd: float = 0.0
    time_elapsed_seconds: float = 0.0
    api_calls: int = 0

    # Per-step tracking
    step_tokens: dict[str, int] = field(default_factory=dict)
    step_costs: dict[str, float] = field(default_factory=dict)
    step_durations: dict[str, float] = field(default_factory=dict)

    # Per-agent tracking
    agent_tokens: dict[str, int] = field(default_factory=dict)
    agent_costs: dict[str, float] = field(default_factory=dict)

    def add_tokens(
        self, step_id: str, agent_type: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Add token usage and calculate cost."""
        total_tokens = input_tokens + output_tokens
        self.tokens_used += total_tokens
        self.step_tokens[step_id] = self.step_tokens.get(step_id, 0) + total_tokens
        self.agent_tokens[agent_type] = self.agent_tokens.get(agent_type, 0) + total_tokens

        # Calculate cost
        pricing = MODEL_PRICING.get(agent_type.lower(), MODEL_PRICING["default"])
        cost = (input_tokens / 1000) * pricing["input"] + (output_tokens / 1000) * pricing["output"]
        self.cost_usd += cost
        self.step_costs[step_id] = self.step_costs.get(step_id, 0.0) + cost
        self.agent_costs[agent_type] = self.agent_costs.get(agent_type, 0.0) + cost

        return cost

    def add_api_call(self) -> None:
        """Record an API call."""
        self.api_calls += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "time_elapsed_seconds": self.time_elapsed_seconds,
            "api_calls": self.api_calls,
            "step_tokens": self.step_tokens,
            "step_costs": self.step_costs,
            "agent_tokens": self.agent_tokens,
            "agent_costs": self.agent_costs,
        }


@dataclass
class EnhancedWorkflowResult(WorkflowResult):
    """Extended workflow result with resource metrics."""

    resource_usage: ResourceUsage = field(default_factory=ResourceUsage)
    limits_exceeded: bool = False
    limit_exceeded_type: ResourceType | None = None

    @property
    def metrics(self) -> dict[str, Any]:
        """Get execution metrics."""
        return {
            "total_tokens": self.resource_usage.tokens_used,
            "total_cost_usd": self.resource_usage.cost_usd,
            "total_duration_seconds": self.resource_usage.time_elapsed_seconds,
            "api_calls": self.resource_usage.api_calls,
            "steps_completed": sum(1 for s in self.steps if s.status == StepStatus.COMPLETED),
            "steps_failed": sum(1 for s in self.steps if s.status == StepStatus.FAILED),
            "limits_exceeded": self.limits_exceeded,
            "per_step_costs": self.resource_usage.step_costs,
            "per_agent_costs": self.resource_usage.agent_costs,
        }


class EnhancedWorkflowEngine(WorkflowEngine):
    """
    Enhanced workflow engine with resource tracking and limits.

    Extends the base WorkflowEngine with:
    - Resource usage tracking (tokens, cost, time, API calls)
    - Limit enforcement with configurable thresholds
    - Parallel step execution for hive-mind patterns
    - Cost estimation before execution
    - Real-time metrics callbacks
    """

    def __init__(
        self,
        config: WorkflowConfig | None = None,
        limits: ResourceLimits | None = None,
        step_registry: dict[str, type[WorkflowStep]] | None = None,
        metrics_callback: Callable[[dict[str, Any]], None] | None = None,
    ):
        super().__init__(config, step_registry)
        self._limits = limits or ResourceLimits()
        self._usage = ResourceUsage()
        self._metrics_callback = metrics_callback
        self._start_time: float | None = None
        self._parallel_semaphore: asyncio.Semaphore | None = None
        # Declared here (not only reset in execute()) so its element type is
        # inferable: mypy cannot type an attribute whose first and only
        # assignment is an empty list literal.
        self._results: list[StepResult] = []

    @property
    def limits(self) -> ResourceLimits:
        """Get current resource limits."""
        return self._limits

    @property
    def usage(self) -> ResourceUsage:
        """Get current resource usage."""
        return self._usage

    def set_limits(self, limits: ResourceLimits) -> None:
        """Update resource limits."""
        self._limits = limits

    async def execute(
        self,
        definition: WorkflowDefinition,
        inputs: dict[str, Any] | None = None,
        workflow_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> EnhancedWorkflowResult:
        """
        Execute workflow with resource tracking and limits.

        Args:
            definition: Workflow definition to execute
            inputs: Input parameters for the workflow
            workflow_id: Optional ID (generated if not provided)
            metadata: Optional metadata injected into workflow context
            event_callback: Optional callback for workflow progress events

        Returns:
            EnhancedWorkflowResult with metrics and resource usage
        """
        workflow_id = workflow_id or f"wf_{uuid.uuid4().hex[:12]}"
        inputs = inputs or {}
        metadata = self._merge_metadata(definition, metadata)
        metadata.setdefault("workflow_name", definition.name)

        logger.info("Starting enhanced workflow %s: %s", workflow_id, definition.name)

        # Reset tracking
        self._usage = ResourceUsage()
        self._start_time = time.time()
        self._parallel_semaphore = asyncio.Semaphore(self._limits.max_parallel_agents)

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

        limits_exceeded = False
        limit_exceeded_type = None

        try:
            # Execute with overall timeout
            final_output = await asyncio.wait_for(
                self._execute_workflow_enhanced(definition, context),
                timeout=self._limits.timeout_seconds,
            )
            success = all(r.success for r in self._results)
            error = None

        except asyncio.TimeoutError:
            logger.error("Workflow timed out after %ss", self._limits.timeout_seconds)
            success = False
            error = f"Timeout after {self._limits.timeout_seconds}s"
            limits_exceeded = True
            limit_exceeded_type = ResourceType.TIME
            final_output = None

        except ResourceExhaustedError as e:
            logger.error("Resource limit exceeded: %s", e)
            success = False
            error = "Resource limit exceeded"
            limits_exceeded = True
            # Extract resource type from error message
            err_lower = str(e).lower()
            if "time" in err_lower:
                limit_exceeded_type = ResourceType.TIME
            elif "token" in err_lower:
                limit_exceeded_type = ResourceType.TOKENS
            elif "cost" in err_lower:
                limit_exceeded_type = ResourceType.COST
            elif "api" in err_lower:
                limit_exceeded_type = ResourceType.API_CALLS
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
            logger.exception("Workflow execution failed: %s", e)
            success = False
            error = "Workflow execution failed"
            final_output = None

        # Update elapsed time
        self._usage.time_elapsed_seconds = time.time() - self._start_time

        event_payload = {
            **self._base_event_payload(context),
            "success": success,
            "duration_ms": (time.time() - self._start_time) * 1000,
            "steps_executed": len(self._results),
            "error": error,
        }
        if self._should_terminate:
            self._emit_event(context, StreamEventType.WORKFLOW_TERMINATED, event_payload)
        elif success:
            self._emit_event(context, StreamEventType.WORKFLOW_COMPLETE, event_payload)
        else:
            self._emit_event(context, StreamEventType.WORKFLOW_FAILED, event_payload)

        return EnhancedWorkflowResult(
            workflow_id=workflow_id,
            definition_id=definition.id,
            success=success,
            steps=self._results.copy(),
            total_duration_ms=(time.time() - self._start_time) * 1000,
            final_output=final_output,
            error=error,
            resource_usage=self._usage,
            limits_exceeded=limits_exceeded,
            limit_exceeded_type=limit_exceeded_type,
        )

    async def _execute_workflow_enhanced(
        self,
        definition: WorkflowDefinition,
        context: WorkflowContext,
    ) -> Any:
        """Execute workflow with enhanced tracking."""
        if not definition.entry_step:
            raise ValueError("Workflow has no entry step")

        return await self._execute_from_step_enhanced(
            definition, context, definition.entry_step, set()
        )

    async def _execute_from_step_enhanced(
        self,
        definition: WorkflowDefinition,
        context: WorkflowContext,
        start_step: str,
        completed_steps: set[str],
    ) -> Any:
        """Execute workflow starting from a specific step with resource tracking."""
        current_step_id: str | None = start_step
        final_output = None
        step_count = 0

        while current_step_id and not self._should_terminate:
            # Check resource limits before each step
            self._check_limits()

            step_def = definition.get_step(current_step_id)
            if not step_def:
                logger.error("Step '%s' not found", current_step_id)
                break

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

            # Check for parallel execution pattern
            if step_def.execution_pattern == ExecutionPattern.PARALLEL:
                result = await self._execute_parallel_steps(step_def, context, definition)
            else:
                result = await self._execute_step_enhanced(step_def, context)

            self._results.append(result)
            step_count += 1

            # Emit metrics
            self._emit_metrics(step_def.id)

            # Store output
            if result.output is not None:
                context.step_outputs[current_step_id] = result.output
                final_output = result.output

            # Handle failure
            if not result.success:
                if self._config.stop_on_failure and not step_def.optional:
                    logger.error("Step '%s' failed, stopping", current_step_id)
                    break

            # Create checkpoint if enabled
            if (
                self._config.enable_checkpointing
                and step_count % self._config.checkpoint_interval_steps == 0
            ):
                await self._create_checkpoint(
                    context.workflow_id,
                    definition.id,
                    current_step_id,
                    {r.step_id for r in self._results if r.success},
                    context,
                )

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

    async def _execute_step_enhanced(
        self,
        step_def: StepDefinition,
        context: WorkflowContext,
    ) -> StepResult:
        """Execute a single step with resource tracking."""
        self._current_step = step_def.id
        started_at = datetime.now(timezone.utc)
        start_time = time.time()

        logger.debug("Executing step: %s (%s)", step_def.name, step_def.id)

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

        context.current_step_id = step_def.id
        context.current_step_config = step_def.config

        step = self._get_step_instance(step_def)
        if step is None:
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

        retry_count = 0
        last_error = None
        max_retries = min(step_def.retries, self._limits.max_retries_per_step)

        while retry_count <= max_retries:
            try:
                # Track API call
                self._usage.add_api_call()

                # Execute with step timeout
                output = await asyncio.wait_for(
                    step.execute(context),
                    timeout=step_def.timeout_seconds,
                )

                duration_ms = (time.time() - start_time) * 1000
                self._usage.step_durations[step_def.id] = duration_ms / 1000

                # Track token usage if available
                self._track_step_tokens(step_def, output)

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

            except (
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
                ConnectionError,
                KeyError,
                AttributeError,
            ) as e:
                logger.warning("Workflow step failed: %s", e)
                last_error = "Step execution failed"
                retry_count += 1

        duration_ms = (time.time() - start_time) * 1000
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

    async def _execute_parallel_steps(
        self,
        step_def: StepDefinition,
        context: WorkflowContext,
        definition: WorkflowDefinition,
    ) -> StepResult:
        """Execute parallel steps (hive-mind pattern)."""
        started_at = datetime.now(timezone.utc)
        start_time = time.time()

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
                "execution_pattern": ExecutionPattern.PARALLEL.value,
            },
        )

        # Get sub-steps from config or next_steps
        sub_step_ids = step_def.config.get("parallel_steps", step_def.next_steps)

        if not sub_step_ids:
            return StepResult(
                step_id=step_def.id,
                step_name=step_def.name,
                status=StepStatus.COMPLETED,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                output={"parallel_results": []},
            )

        async def execute_with_semaphore(sub_step_id: str) -> dict[str, Any]:
            semaphore = self._parallel_semaphore
            if semaphore is None:
                semaphore = asyncio.Semaphore(1)
            async with semaphore:
                sub_step = definition.get_step(sub_step_id)
                if not sub_step:
                    return {"step_id": sub_step_id, "error": "Step not found"}

                result = await self._execute_step_enhanced(sub_step, context)
                return {
                    "step_id": sub_step_id,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                }

        # Execute all sub-steps in parallel with semaphore
        tasks = [execute_with_semaphore(sid) for sid in sub_step_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        parallel_results: list[dict[str, Any]] = []
        all_success = True
        for result in results:
            if isinstance(result, BaseException):
                parallel_results.append({"error": str(result)})
                all_success = False
            else:
                parallel_results.append(result)
                if not result.get("success", True):
                    all_success = False

        duration_ms = (time.time() - start_time) * 1000

        self._emit_event(
            context,
            StreamEventType.WORKFLOW_STEP_COMPLETE
            if all_success
            else StreamEventType.WORKFLOW_STEP_FAILED,
            {
                **self._base_event_payload(context),
                "step_id": step_def.id,
                "step_name": step_def.name,
                "step_type": step_def.step_type,
                "status": StepStatus.COMPLETED.value if all_success else StepStatus.FAILED.value,
                "duration_ms": duration_ms,
                "parallel_steps": sub_step_ids,
            },
        )

        return StepResult(
            step_id=step_def.id,
            step_name=step_def.name,
            status=StepStatus.COMPLETED if all_success else StepStatus.FAILED,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            duration_ms=duration_ms,
            output={"parallel_results": parallel_results},
        )

    def _check_limits(self) -> None:
        """Check if any resource limits have been exceeded."""
        if self._usage.tokens_used >= self._limits.max_tokens:
            raise ResourceExhaustedError(
                f"Token limit exceeded: {self._usage.tokens_used} >= {self._limits.max_tokens}"
            )

        if self._usage.cost_usd >= self._limits.max_cost_usd:
            raise ResourceExhaustedError(
                f"Cost limit exceeded: ${self._usage.cost_usd:.4f} >= ${self._limits.max_cost_usd}"
            )

        if self._usage.api_calls >= self._limits.max_api_calls:
            raise ResourceExhaustedError(
                f"API call limit exceeded: {self._usage.api_calls} >= {self._limits.max_api_calls}"
            )

        elapsed = time.time() - self._start_time if self._start_time else 0
        if elapsed >= self._limits.timeout_seconds:
            raise ResourceExhaustedError(
                f"Time limit exceeded: {elapsed:.1f}s >= {self._limits.timeout_seconds}s"
            )

    def _track_step_tokens(self, step_def: StepDefinition, output: Any) -> None:
        """Track token usage from step output."""
        if not isinstance(output, dict):
            return

        # Extract token counts from output (if agent provides them)
        input_tokens = int(output.get("input_tokens", 0) or output.get("prompt_tokens", 0) or 0)
        output_tokens = int(
            output.get("output_tokens", 0) or output.get("completion_tokens", 0) or 0
        )

        # Estimate if not provided
        if input_tokens == 0 and output_tokens == 0:
            response = output.get("response", "")
            if isinstance(response, str):
                # Rough estimate: ~4 chars per token
                output_tokens = len(response) // 4
                input_tokens = output_tokens // 2  # Assume input was half the output

        agent_type = step_def.config.get("agent_type", "default")
        if input_tokens > 0 or output_tokens > 0:
            self._usage.add_tokens(step_def.id, agent_type, input_tokens, output_tokens)

    def _emit_metrics(self, step_id: str) -> None:
        """Emit current metrics via callback."""
        if self._metrics_callback:
            metrics = {
                "step_id": step_id,
                "tokens_used": self._usage.tokens_used,
                "cost_usd": self._usage.cost_usd,
                "api_calls": self._usage.api_calls,
                "elapsed_seconds": time.time() - self._start_time if self._start_time else 0,
            }
            try:
                self._metrics_callback(metrics)
            except (RuntimeError, ValueError, TypeError, OSError, AttributeError) as e:
                logger.warning("Metrics callback failed: %s", e)

    def estimate_cost(self, definition: WorkflowDefinition) -> dict[str, float]:
        """
        Estimate workflow cost before execution.

        Args:
            definition: Workflow definition to estimate

        Returns:
            Dict with estimated costs per agent and total
        """
        estimates = {"total": 0.0}

        for step in definition.steps:
            if step.step_type == "agent":
                agent_type = step.config.get("agent_type", "default")
                pricing = MODEL_PRICING.get(agent_type.lower(), MODEL_PRICING["default"])

                # Estimate ~1000 tokens per agent call (rough average)
                estimated_tokens = step.config.get("estimated_tokens", 1000)
                cost = (estimated_tokens / 1000) * (pricing["input"] + pricing["output"]) / 2

                estimates[agent_type] = estimates.get(agent_type, 0.0) + cost
                estimates["total"] += cost

            elif step.step_type in ("debate", "quick_debate"):
                agents = step.config.get("agents", get_settings().agent.default_agent_list)
                rounds = step.config.get("rounds", DEFAULT_ROUNDS)

                for agent_type in agents:
                    pricing = MODEL_PRICING.get(agent_type.lower(), MODEL_PRICING["default"])
                    cost = rounds * (1000 / 1000) * (pricing["input"] + pricing["output"]) / 2
                    estimates[agent_type] = estimates.get(agent_type, 0.0) + cost
                    estimates["total"] += cost

        return estimates


# Export for convenience
__all__ = [
    "EnhancedWorkflowEngine",
    "ResourceLimits",
    "ResourceUsage",
    "ResourceType",
    "ResourceExhaustedError",
    "EnhancedWorkflowResult",
    "MODEL_PRICING",
]
