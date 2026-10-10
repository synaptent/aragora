"""
Deliberation Integration for the Aragora Control Plane.

Provides comprehensive integration between the debate/vetted decisionmaking system
and the control plane task scheduler. Deliberations are treated as first-class
tasks that can be:
- Scheduled through the coordinator with priority and SLA settings
- Routed to appropriate agents based on capabilities
- Tracked for compliance with response time SLAs
- Fed back to the ELO ranking system for agent performance updates

This module is critical for the "Control plane for multi-agent vetted decisionmaking"
positioning.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TYPE_CHECKING
from collections.abc import Callable

from aragora.core.decision import (
    DecisionConfig,
    DecisionRequest,
    DecisionResult,
    get_decision_router,
)
from aragora.core.decision_results import save_decision_result

if TYPE_CHECKING:
    from aragora.control_plane.coordinator import ControlPlaneCoordinator

logger = logging.getLogger(__name__)

# =============================================================================
# Constants and Enums
# =============================================================================

DELIBERATION_TASK_TYPE = "deliberation"

# Default SLA settings (in seconds)
DEFAULT_DELIBERATION_TIMEOUT = 300.0  # 5 minutes
DEFAULT_SLA_WARNING_THRESHOLD = 0.8  # Warn at 80% of timeout
DEFAULT_SLA_CRITICAL_THRESHOLD = 0.95  # Critical at 95% of timeout


class DeliberationStatus(Enum):
    """Status of a deliberation task."""

    PENDING = "pending"  # Waiting to be scheduled
    SCHEDULED = "scheduled"  # Submitted to control plane
    IN_PROGRESS = "in_progress"  # Being executed by agents
    CONSENSUS_REACHED = "consensus_reached"  # Successful completion
    NO_CONSENSUS = "no_consensus"  # Completed but no consensus
    FAILED = "failed"  # Error during execution
    TIMEOUT = "timeout"  # Exceeded SLA timeout
    CANCELLED = "cancelled"  # Manually cancelled


class SLAComplianceLevel(Enum):
    """SLA compliance levels."""

    COMPLIANT = "compliant"  # Within normal limits
    WARNING = "warning"  # Approaching timeout
    CRITICAL = "critical"  # Near timeout
    VIOLATED = "violated"  # Exceeded timeout


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class DeliberationSLA:
    """SLA configuration for a deliberation."""

    timeout_seconds: float = DEFAULT_DELIBERATION_TIMEOUT
    warning_threshold: float = DEFAULT_SLA_WARNING_THRESHOLD
    critical_threshold: float = DEFAULT_SLA_CRITICAL_THRESHOLD
    max_rounds: int = 5
    min_agents: int = 2
    consensus_required: bool = True
    notify_on_warning: bool = True
    notify_on_violation: bool = True

    def get_compliance_level(self, elapsed_seconds: float) -> SLAComplianceLevel:
        """Get current SLA compliance level."""
        if elapsed_seconds >= self.timeout_seconds:
            return SLAComplianceLevel.VIOLATED
        if elapsed_seconds >= self.timeout_seconds * self.critical_threshold:
            return SLAComplianceLevel.CRITICAL
        if elapsed_seconds >= self.timeout_seconds * self.warning_threshold:
            return SLAComplianceLevel.WARNING
        return SLAComplianceLevel.COMPLIANT


@dataclass
class DeliberationMetrics:
    """Metrics collected during deliberation execution."""

    started_at: float | None = None
    completed_at: float | None = None
    rounds_completed: int = 0
    total_agent_responses: int = 0
    consensus_confidence: float | None = None
    agent_contributions: dict[str, int] = field(default_factory=dict)
    sla_compliance: SLAComplianceLevel = SLAComplianceLevel.COMPLIANT

    @property
    def duration_seconds(self) -> float | None:
        """Get total duration in seconds."""
        if self.started_at is None:
            return None
        end = self.completed_at or time.time()
        return end - self.started_at


@dataclass
class DeliberationTask:
    """
    A deliberation task that can be scheduled through the control plane.

    This is the primary interface for submitting deliberations as tasks.
    """

    question: str
    context: str | None = None
    agents: list[str] = field(default_factory=list)
    required_capabilities: list[str] = field(default_factory=lambda: ["debate"])
    priority: str = "normal"  # low, normal, high, urgent
    sla: DeliberationSLA = field(default_factory=DeliberationSLA)
    metadata: dict[str, Any] = field(default_factory=dict)

    # Assigned by the system
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: DeliberationStatus = DeliberationStatus.PENDING
    metrics: DeliberationMetrics = field(default_factory=DeliberationMetrics)
    result: DecisionResult | None = None
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """Convert to task payload for scheduler."""
        return {
            "question": self.question,
            "context": self.context,
            "agents": self.agents,
            "request_id": self.request_id,
            "sla": {
                "timeout_seconds": self.sla.timeout_seconds,
                "max_rounds": self.sla.max_rounds,
                "min_agents": self.sla.min_agents,
                "consensus_required": self.sla.consensus_required,
            },
            "metadata": self.metadata,
        }

    @classmethod
    def from_payload(cls, task_id: str, payload: dict[str, Any]) -> DeliberationTask:
        """Create from task payload."""
        sla_data = payload.get("sla", {})
        return cls(
            task_id=task_id,
            question=payload["question"],
            context=payload.get("context"),
            agents=payload.get("agents", []),
            request_id=payload.get("request_id", str(uuid.uuid4())),
            sla=DeliberationSLA(
                timeout_seconds=sla_data.get("timeout_seconds", DEFAULT_DELIBERATION_TIMEOUT),
                max_rounds=sla_data.get("max_rounds", 5),
                min_agents=sla_data.get("min_agents", 2),
                consensus_required=sla_data.get("consensus_required", True),
            ),
            metadata=payload.get("metadata", {}),
        )


@dataclass
class DeliberationOutcome:
    """
    Outcome of a completed deliberation for ELO updates.

    This is fed back to the ranking system to update agent ELO scores.
    """

    task_id: str
    request_id: str
    success: bool
    consensus_reached: bool
    consensus_confidence: float | None = None
    winning_position: str | None = None
    agent_performances: dict[str, AgentPerformance] = field(default_factory=dict)
    duration_seconds: float = 0.0
    sla_compliant: bool = True


@dataclass
class AgentPerformance:
    """Performance metrics for a single agent in a deliberation."""

    agent_id: str
    contributed_to_consensus: bool = False
    response_count: int = 0
    average_confidence: float = 0.0
    position_changed: bool = False  # Did they change their position during debate
    final_position_correct: bool = False  # Was their final position the consensus


# =============================================================================
# Record Builders
# =============================================================================


def build_decision_record(
    request_id: str,
    result: DecisionResult | None = None,
    status: str | None = None,
    error: str | None = None,
    metrics: DeliberationMetrics | None = None,
    org_id: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Build a DecisionResultStore record with optional metrics."""
    resolved_status = status or ("completed" if result and result.success else "failed")
    record = {
        "request_id": request_id,
        "status": resolved_status,
        "result": result.to_dict() if result else {},
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "error": error,
        "org_id": org_id,
        "created_by": created_by,
    }

    if metrics:
        record["metrics"] = {
            "duration_seconds": metrics.duration_seconds,
            "rounds_completed": metrics.rounds_completed,
            "total_agent_responses": metrics.total_agent_responses,
            "consensus_confidence": metrics.consensus_confidence,
            "sla_compliance": metrics.sla_compliance.value,
        }

    return record


# =============================================================================
# Core Functions
# =============================================================================


async def run_deliberation(
    request: DecisionRequest,
    router: Any | None = None,
    *,
    org_id: str | None = None,
    created_by: str | None = None,
) -> DecisionResult:
    """Run a deliberation and persist the result."""
    decision_router = router or get_decision_router()
    result = await decision_router.route(request)
    save_decision_result(
        request.request_id,
        build_decision_record(request.request_id, result, org_id=org_id, created_by=created_by),
    )
    return result


def record_deliberation_error(
    request_id: str,
    error: str,
    status: str = "failed",
    *,
    org_id: str | None = None,
    created_by: str | None = None,
) -> None:
    """Persist a deliberation error result."""
    save_decision_result(
        request_id,
        build_decision_record(
            request_id=request_id,
            result=None,
            status=status,
            error=error,
            org_id=org_id,
            created_by=created_by,
        ),
    )
    logger.warning("deliberation_failed", extra={"request_id": request_id, "error": error})


# =============================================================================
# Deliberation Manager
# =============================================================================


class DeliberationManager:
    """
    Manages deliberations as first-class tasks in the control plane.

    Provides:
    - Task submission and scheduling through the coordinator
    - SLA tracking and compliance monitoring
    - ELO update feeding for agent performance
    - Real-time progress notifications

    Usage:
        manager = DeliberationManager(coordinator)

        # Submit a deliberation
        task_id = await manager.submit_deliberation(
            question="What is the best approach?",
            agents=["claude", "gpt-4"],
            priority="high",
            timeout_seconds=120.0,
        )

        # Wait for completion
        outcome = await manager.wait_for_outcome(task_id, timeout=150.0)

        # Or track progress
        async for update in manager.track_progress(task_id):
            print(f"Round {update.round}: {update.status}")
    """

    def __init__(
        self,
        coordinator: ControlPlaneCoordinator | None = None,
        elo_callback: Callable[[DeliberationOutcome], None] | None = None,
        notification_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        """
        Initialize the deliberation manager.

        Args:
            coordinator: Control plane coordinator for task submission
            elo_callback: Callback to update agent ELO scores
            notification_callback: Callback for SLA/progress notifications
        """
        self._coordinator = coordinator
        self._elo_callback = elo_callback
        self._notification_callback = notification_callback
        self._active_deliberations: dict[str, DeliberationTask] = {}
        self._sla_monitors: dict[str, asyncio.Task[None]] = {}

    def set_coordinator(self, coordinator: ControlPlaneCoordinator) -> None:
        """Set the coordinator after initialization."""
        self._coordinator = coordinator

    async def submit_deliberation(
        self,
        question: str,
        context: str | None = None,
        agents: list[str] | None = None,
        required_capabilities: list[str] | None = None,
        priority: str = "normal",
        timeout_seconds: float = DEFAULT_DELIBERATION_TIMEOUT,
        max_rounds: int = 5,
        min_agents: int = 2,
        consensus_required: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Submit a deliberation task to the control plane.

        Args:
            question: The question or topic to deliberate
            context: Optional context for the deliberation
            agents: Specific agents to use (optional)
            required_capabilities: Required agent capabilities
            priority: Task priority (low, normal, high, urgent)
            timeout_seconds: SLA timeout
            max_rounds: Maximum debate rounds
            min_agents: Minimum agents required
            consensus_required: Whether consensus is required for success
            metadata: Additional metadata

        Returns:
            Task ID for tracking
        """
        if not self._coordinator:
            raise RuntimeError("Coordinator not set. Call set_coordinator() first.")

        # Create deliberation task
        task = DeliberationTask(
            question=question,
            context=context,
            agents=agents or [],
            required_capabilities=required_capabilities or ["debate"],
            priority=priority,
            sla=DeliberationSLA(
                timeout_seconds=timeout_seconds,
                max_rounds=max_rounds,
                min_agents=min_agents,
                consensus_required=consensus_required,
            ),
            metadata=metadata or {},
        )

        # Convert priority string to TaskPriority
        from aragora.control_plane.scheduler import TaskPriority

        priority_map = {
            "low": TaskPriority.LOW,
            "normal": TaskPriority.NORMAL,
            "high": TaskPriority.HIGH,
            "urgent": TaskPriority.URGENT,
        }
        task_priority = priority_map.get(priority.lower(), TaskPriority.NORMAL)

        # Submit to coordinator
        task_id = await self._coordinator.submit_task(
            task_type=DELIBERATION_TASK_TYPE,
            payload=task.to_payload(),
            required_capabilities=task.required_capabilities,
            priority=task_priority,
            timeout_seconds=timeout_seconds,
            metadata={
                "deliberation_request_id": task.request_id,
                **(metadata or {}),
            },
        )

        task.task_id = task_id
        task.status = DeliberationStatus.SCHEDULED
        self._active_deliberations[task_id] = task

        # Start SLA monitoring
        self._start_sla_monitor(task)

        logger.info(
            "deliberation_submitted",
            extra={
                "task_id": task_id,
                "request_id": task.request_id,
                "question_preview": question[:100],
                "priority": priority,
                "timeout_seconds": timeout_seconds,
            },
        )

        return task_id

    async def wait_for_outcome(
        self,
        task_id: str,
        timeout: float | None = None,
    ) -> DeliberationOutcome | None:
        """
        Wait for a deliberation to complete and return the outcome.

        Args:
            task_id: Task ID to wait for
            timeout: Maximum wait time

        Returns:
            DeliberationOutcome if completed, None if timeout/not found
        """
        if not self._coordinator:
            raise RuntimeError("Coordinator not set")

        task = self._active_deliberations.get(task_id)
        if not task:
            return None

        effective_timeout = timeout or task.sla.timeout_seconds

        # Wait for task completion
        completed_task = await self._coordinator.wait_for_result(task_id, timeout=effective_timeout)

        if not completed_task:
            return None

        # Build outcome from completed task
        return self._build_outcome(task, completed_task)

    async def execute_deliberation(
        self,
        task: DeliberationTask,
        router: Any | None = None,
    ) -> DeliberationOutcome:
        """
        Execute a deliberation task (called by worker/agent).

        This is the entry point for workers claiming deliberation tasks.

        Args:
            task: The deliberation task to execute
            router: Optional decision router

        Returns:
            DeliberationOutcome with results
        """
        task.status = DeliberationStatus.IN_PROGRESS
        task.metrics.started_at = time.time()
        # Submitters put the creating org and user next to request_id.
        metadata = task.metadata or {}
        owner = {"org_id": metadata.get("org_id"), "created_by": metadata.get("created_by")}

        try:
            # Create decision request
            request = DecisionRequest(
                request_id=task.request_id,
                content=task.question,
                config=DecisionConfig(
                    agents=task.agents if task.agents else ["anthropic-api", "openai-api"],
                    rounds=task.sla.max_rounds,
                    consensus="unanimous" if task.sla.consensus_required else "majority",
                ),
            )

            # Run the deliberation
            result = await run_deliberation(request, router, **owner)

            # Update metrics
            task.metrics.completed_at = time.time()
            task.metrics.consensus_confidence = getattr(result, "confidence", None)
            task.result = result

            # Determine status
            if result.success:
                task.status = (
                    DeliberationStatus.CONSENSUS_REACHED
                    if getattr(result, "consensus_reached", True)
                    else DeliberationStatus.NO_CONSENSUS
                )
            else:
                task.status = DeliberationStatus.FAILED
                task.error = getattr(result, "error", "Unknown error")

            # Check SLA compliance
            duration = task.metrics.duration_seconds or 0
            task.metrics.sla_compliance = task.sla.get_compliance_level(duration)

            # Build and return outcome
            outcome = self._build_outcome_from_task(task)

            # Emit completion notifications
            self._emit_completion_notification(task, outcome)

            # Feed back to ELO system
            if self._elo_callback:
                try:
                    self._elo_callback(outcome)
                except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided ELO callback
                    logger.error("ELO callback failed: %s", e)

            return outcome

        except asyncio.TimeoutError:
            task.status = DeliberationStatus.TIMEOUT
            task.error = f"Deliberation exceeded SLA timeout of {task.sla.timeout_seconds}s"
            task.metrics.completed_at = time.time()
            task.metrics.sla_compliance = SLAComplianceLevel.VIOLATED
            record_deliberation_error(task.request_id, task.error, status="timeout", **owner)
            outcome = self._build_outcome_from_task(task)
            self._emit_completion_notification(task, outcome)
            return outcome

        except (OSError, ConnectionError, RuntimeError, ValueError) as e:
            task.status = DeliberationStatus.FAILED
            task.error = "Deliberation failed"
            task.metrics.completed_at = time.time()
            logger.warning("Deliberation failed for request %s: %s", task.request_id, e)
            record_deliberation_error(
                task.request_id, "Deliberation failed", status="failed", **owner
            )
            outcome = self._build_outcome_from_task(task)
            self._emit_completion_notification(task, outcome)
            return outcome

        finally:
            # Stop SLA monitor
            self._stop_sla_monitor(task.task_id)

    def get_active_deliberations(self) -> list[DeliberationTask]:
        """Get all active deliberation tasks."""
        return [
            task
            for task in self._active_deliberations.values()
            if task.status
            not in (
                DeliberationStatus.CONSENSUS_REACHED,
                DeliberationStatus.NO_CONSENSUS,
                DeliberationStatus.FAILED,
                DeliberationStatus.TIMEOUT,
                DeliberationStatus.CANCELLED,
            )
        ]

    def get_deliberation_stats(self) -> dict[str, Any]:
        """Get statistics about deliberations."""
        by_status: dict[str, int] = {}
        sla_violations = 0
        durations: list[float] = []

        for task in self._active_deliberations.values():
            status = task.status.value
            by_status[status] = by_status.get(status, 0) + 1

            if task.metrics.sla_compliance == SLAComplianceLevel.VIOLATED:
                sla_violations += 1

            if task.metrics.duration_seconds:
                durations.append(task.metrics.duration_seconds)

        return {
            "total_active": len(self._active_deliberations),
            "by_status": by_status,
            "sla_violations": sla_violations,
            "average_duration_seconds": sum(durations) / len(durations) if durations else 0.0,
        }

    # =========================================================================
    # Internal Methods
    # =========================================================================

    def _start_sla_monitor(self, task: DeliberationTask) -> None:
        """Start SLA monitoring for a task."""

        async def monitor() -> None:
            start_time = time.time()
            while task.task_id in self._active_deliberations:
                await asyncio.sleep(5)  # Check every 5 seconds

                elapsed = time.time() - start_time
                compliance = task.sla.get_compliance_level(elapsed)
                task.metrics.sla_compliance = compliance

                # Send notifications if needed
                if self._notification_callback:
                    if compliance == SLAComplianceLevel.WARNING and task.sla.notify_on_warning:
                        self._notification_callback(
                            "sla_warning",
                            {
                                "task_id": task.task_id,
                                "elapsed_seconds": elapsed,
                                "timeout_seconds": task.sla.timeout_seconds,
                            },
                        )
                    elif compliance == SLAComplianceLevel.VIOLATED and task.sla.notify_on_violation:
                        self._notification_callback(
                            "sla_violated",
                            {
                                "task_id": task.task_id,
                                "elapsed_seconds": elapsed,
                                "timeout_seconds": task.sla.timeout_seconds,
                            },
                        )
                        break  # Stop monitoring after violation

        self._sla_monitors[task.task_id] = asyncio.create_task(monitor())

    def _stop_sla_monitor(self, task_id: str) -> None:
        """Stop SLA monitoring for a task."""
        monitor = self._sla_monitors.pop(task_id, None)
        if monitor and not monitor.done():
            monitor.cancel()

    def _emit_notification(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a notification event if a callback is configured."""
        if not self._notification_callback:
            return
        try:
            self._notification_callback(event_type, data)
        except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided notification callback
            logger.debug("deliberation_notification_failed: %s", str(e))

    def _emit_completion_notification(
        self, task: DeliberationTask, outcome: DeliberationOutcome
    ) -> None:
        """Emit consensus/failure notifications after a deliberation completes."""
        base_data = {
            "task_id": task.task_id,
            "request_id": task.request_id,
            "question": task.question,
            "confidence": outcome.consensus_confidence or 0.0,
            "answer": outcome.winning_position,
            "status": task.status.value,
            "workspace_id": task.metadata.get("workspace_id") if task.metadata else None,
        }

        if outcome.consensus_reached:
            self._emit_notification("consensus_reached", base_data)
        elif outcome.success:
            self._emit_notification("no_consensus", base_data)
        else:
            failure_data = {**base_data, "error": task.error}
            self._emit_notification("deliberation_failed", failure_data)

    def _build_outcome(self, task: DeliberationTask, completed_task: Any) -> DeliberationOutcome:
        """Build outcome from completed coordinator task."""
        result = completed_task.result or {}

        return DeliberationOutcome(
            task_id=task.task_id,
            request_id=task.request_id,
            success=completed_task.status.value == "completed",
            consensus_reached=result.get("consensus_reached", False),
            consensus_confidence=result.get("confidence"),
            winning_position=result.get("final_answer"),
            duration_seconds=task.metrics.duration_seconds or 0.0,
            sla_compliant=task.metrics.sla_compliance != SLAComplianceLevel.VIOLATED,
        )

    def _build_outcome_from_task(self, task: DeliberationTask) -> DeliberationOutcome:
        """Build outcome from internal task state."""
        return DeliberationOutcome(
            task_id=task.task_id,
            request_id=task.request_id,
            success=task.status
            in (DeliberationStatus.CONSENSUS_REACHED, DeliberationStatus.NO_CONSENSUS),
            consensus_reached=task.status == DeliberationStatus.CONSENSUS_REACHED,
            consensus_confidence=task.metrics.consensus_confidence,
            winning_position=task.result.answer if task.result else None,
            duration_seconds=task.metrics.duration_seconds or 0.0,
            sla_compliant=task.metrics.sla_compliance != SLAComplianceLevel.VIOLATED,
        )


# =============================================================================
# Worker Integration
# =============================================================================


async def handle_deliberation_task(
    task_id: str,
    payload: dict[str, Any],
    coordinator: ControlPlaneCoordinator,
    router: Any | None = None,
    elo_callback: Callable[[DeliberationOutcome], None] | None = None,
) -> dict[str, Any]:
    """
    Handle a claimed deliberation task from the scheduler.

    This is the entry point for workers processing deliberation tasks.

    Args:
        task_id: The task ID
        payload: Task payload with deliberation details
        coordinator: Control plane coordinator
        router: Optional decision router
        elo_callback: Optional callback for ELO updates

    Returns:
        Dict with deliberation results
    """
    manager = DeliberationManager(
        coordinator=coordinator,
        elo_callback=elo_callback,
    )

    # Reconstruct deliberation task from payload
    delib_task = DeliberationTask.from_payload(task_id, payload)

    # Execute the deliberation
    outcome = await manager.execute_deliberation(delib_task, router)

    # Return results for task completion
    return {
        "success": outcome.success,
        "consensus_reached": outcome.consensus_reached,
        "consensus_confidence": outcome.consensus_confidence,
        "winning_position": outcome.winning_position,
        "duration_seconds": outcome.duration_seconds,
        "sla_compliant": outcome.sla_compliant,
    }


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Constants
    "DELIBERATION_TASK_TYPE",
    "DEFAULT_DELIBERATION_TIMEOUT",
    # Enums
    "DeliberationStatus",
    "SLAComplianceLevel",
    # Data Classes
    "DeliberationSLA",
    "DeliberationMetrics",
    "DeliberationTask",
    "DeliberationOutcome",
    "AgentPerformance",
    # Functions
    "build_decision_record",
    "run_deliberation",
    "record_deliberation_error",
    "handle_deliberation_task",
    # Classes
    "DeliberationManager",
]
