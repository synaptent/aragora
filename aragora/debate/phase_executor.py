"""
Phase Executor for Aragora Debates.

Coordinates the execution of debate phases in sequence.
Extracted from Arena to enable cleaner phase management and testing.

Usage:
    from aragora.debate.phase_executor import PhaseExecutor, PhaseConfig

    # Create executor with phases
    executor = PhaseExecutor(phases, config)

    # Execute debate
    result = await executor.execute(context)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol
from collections.abc import Callable

from aragora.observability.tracing import trace_debate_phase

logger = logging.getLogger(__name__)


class PhaseStatus(Enum):
    """Status of a phase execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class PhaseResult:
    """Result from a single phase execution."""

    phase_name: str
    status: PhaseStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float = 0.0
    output: Any = None
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if phase completed successfully."""
        return self.status in (PhaseStatus.COMPLETED, PhaseStatus.SKIPPED)


@dataclass
class ExecutionResult:
    """Result from full phase execution."""

    debate_id: str
    success: bool
    phases: list[PhaseResult]
    total_duration_ms: float
    final_output: Any = None
    error: str | None = None

    def get_phase_result(self, name: str) -> PhaseResult | None:
        """Get result for a specific phase."""
        for phase in self.phases:
            if phase.phase_name == name:
                return phase
        return None


class Phase(Protocol):
    """Protocol for debate phases."""

    @property
    def name(self) -> str:
        """Phase name."""
        ...

    async def execute(self, context: Any) -> Any:
        """Execute the phase with given context."""
        ...


@dataclass
class PhaseConfig:
    """Configuration for phase execution."""

    # Timeout settings (increased for debates with many agents)
    total_timeout_seconds: float = 600.0  # 10 minutes default
    phase_timeout_seconds: float = 120.0  # Per-phase timeout (2 minutes)

    # Execution behavior
    stop_on_failure: bool = True
    skip_optional_on_timeout: bool = True

    # Tracing
    enable_tracing: bool = True
    trace_callback: Callable[[str, dict[str, Any]], None] | None = None

    # Metrics
    metrics_callback: Callable[[str, float], None] | None = None

    # Checkpoint hooks - called before/after phases
    # pre_phase_callback: async (phase_name, context) -> None
    pre_phase_callback: Callable[[str, Any], Any] | None = None
    # post_phase_callback: async (phase_name, context, result) -> None
    post_phase_callback: Callable[[str, Any, PhaseResult], Any] | None = None


# Phase ordering for standard debate flow
STANDARD_PHASE_ORDER = [
    "context_initializer",  # Phase 0: Gather context
    "proposal",  # Phase 1: Initial proposals
    "debate_rounds",  # Phase 2: Critique/revise cycles
    "consensus",  # Phase 3: Voting and agreement
    "analytics",  # Phases 4-6: Analytics and learning
    "feedback",  # Phase 7: Memory storage
]

# Optional phases that can be skipped
OPTIONAL_PHASES = {"analytics", "feedback"}

# Critical phases that MUST run even if earlier phases fail
# Consensus phase generates synthesis which is required for debate completion
CRITICAL_PHASES = {"consensus"}


class PhaseExecutor:
    """
    Executes debate phases in sequence.

    Features:
    - Sequential phase execution with timeouts
    - Phase-level error handling and recovery
    - Metrics collection and tracing
    - Optional phase skipping
    - Early termination support
    """

    def __init__(
        self,
        phases: dict[str, Phase],
        config: PhaseConfig | None = None,
    ):
        """
        Initialize the phase executor.

        Args:
            phases: Dictionary mapping phase names to phase objects
            config: Optional execution configuration
        """
        self._phases = phases
        self._config = config or PhaseConfig()

        # Execution state
        self._current_phase: str | None = None
        self._should_terminate: bool = False
        self._termination_reason: str | None = None

        # Results tracking
        self._results: list[PhaseResult] = []

    # =========================================================================
    # Main Execution
    # =========================================================================

    async def execute(
        self,
        context: Any,
        debate_id: str = "",
        phase_order: list[str] | None = None,
    ) -> ExecutionResult:
        """
        Execute all phases in sequence.

        Extracted from Arena._run_inner().

        Args:
            context: Debate context object
            debate_id: ID of the debate for tracking
            phase_order: Optional custom phase order

        Returns:
            ExecutionResult with all phase results
        """
        start_time = time.time()
        self._results = []
        self._should_terminate = False
        self._termination_reason = None

        # Determine phase order
        order = phase_order or STANDARD_PHASE_ORDER

        # Filter to available phases
        order = [p for p in order if p in self._phases]

        logger.info("Starting phase execution for debate %s: %s", debate_id, order)

        # Execute with overall timeout
        try:
            final_output = await asyncio.wait_for(
                self._execute_phases(context, order, debate_id),
                timeout=self._config.total_timeout_seconds,
            )
            success = all(r.success for r in self._results)
            error = None
        except asyncio.TimeoutError:
            logger.error("Phase execution timed out after %ss", self._config.total_timeout_seconds)
            success = False
            error = f"Execution timed out after {self._config.total_timeout_seconds}s"
            final_output = None
        except Exception as e:  # noqa: BLE001 - phase execution boundary: user-provided phases can raise any exception
            logger.exception("Phase execution failed: %s", e)
            success = False
            error = f"Execution failed: {type(e).__name__}"
            final_output = None

        total_duration = (time.time() - start_time) * 1000

        return ExecutionResult(
            debate_id=debate_id,
            success=success,
            phases=self._results.copy(),
            total_duration_ms=total_duration,
            final_output=final_output,
            error=error,
        )

    async def _execute_phases(
        self,
        context: Any,
        phase_order: list[str],
        debate_id: str,
    ) -> Any:
        """Execute phases in order."""
        final_output = None

        for phase_name in phase_order:
            # Check for early termination
            if self._should_terminate:
                logger.info("Early termination: %s", self._termination_reason)
                break

            # Execute phase
            result = await self._execute_single_phase(phase_name, context, debate_id)
            self._results.append(result)

            # Track final output from consensus phase
            if phase_name == "consensus" and result.output is not None:
                final_output = result.output

            # Handle failure
            if not result.success:
                if self._config.stop_on_failure:
                    if phase_name not in OPTIONAL_PHASES:
                        # Check if there are critical phases remaining that must run
                        remaining_phases = phase_order[phase_order.index(phase_name) + 1 :]
                        has_critical_remaining = any(p in CRITICAL_PHASES for p in remaining_phases)

                        if has_critical_remaining:
                            logger.warning(
                                "Required phase '%s' failed, but continuing to critical phases",
                                phase_name,
                            )
                            # Continue to ensure consensus/synthesis runs
                        else:
                            logger.error("Required phase '%s' failed, stopping", phase_name)
                            break
                    else:
                        logger.warning("Optional phase '%s' failed, continuing", phase_name)

        return final_output

    async def _execute_single_phase(
        self,
        phase_name: str,
        context: Any,
        debate_id: str,
    ) -> PhaseResult:
        """Execute a single phase with error handling and OpenTelemetry tracing."""
        self._current_phase = phase_name
        phase = self._phases.get(phase_name)

        if phase is None:
            return PhaseResult(
                phase_name=phase_name,
                status=PhaseStatus.SKIPPED,
                error=f"Phase '{phase_name}' not found",
            )

        # Execute pre-phase callback (e.g., checkpoint creation)
        if self._config.pre_phase_callback:
            try:
                result = self._config.pre_phase_callback(phase_name, context)
                if asyncio.iscoroutine(result):
                    await result
            except (TypeError, ValueError, AttributeError, RuntimeError, OSError) as e:
                logger.debug("Pre-phase callback failed for '%s': %s", phase_name, e)

        started_at = datetime.now(timezone.utc)
        start_time = time.time()

        logger.debug("Starting phase: %s", phase_name)
        self._emit_trace(
            "phase_start",
            {
                "debate_id": debate_id,
                "phase": phase_name,
                "started_at": started_at.isoformat(),
            },
        )

        # Use OpenTelemetry tracing when enabled
        if self._config.enable_tracing:
            result = await self._execute_with_tracing(
                phase, phase_name, context, debate_id, started_at, start_time
            )
        else:
            result = await self._execute_without_tracing(
                phase, phase_name, context, started_at, start_time
            )

        self._emit_trace(
            "phase_end",
            {
                "debate_id": debate_id,
                "phase": phase_name,
                "status": result.status.value,
                "success": result.success,
                "duration_ms": result.duration_ms,
                "started_at": result.started_at.isoformat() if result.started_at else None,
                "completed_at": result.completed_at.isoformat() if result.completed_at else None,
                "error": result.error,
            },
        )

        # Execute post-phase callback
        if self._config.post_phase_callback:
            try:
                post_result = self._config.post_phase_callback(phase_name, context, result)
                if asyncio.iscoroutine(post_result):
                    await post_result
            except (TypeError, ValueError, AttributeError, RuntimeError, OSError) as e:
                logger.debug("Post-phase callback failed for '%s': %s", phase_name, e)

        return result

    async def _execute_with_tracing(
        self,
        phase: Phase,
        phase_name: str,
        context: Any,
        debate_id: str,
        started_at: datetime,
        start_time: float,
    ) -> PhaseResult:
        """Execute phase with OpenTelemetry tracing."""
        with trace_debate_phase(phase_name, debate_id) as span:
            try:
                output = await asyncio.wait_for(
                    phase.execute(context),
                    timeout=self._config.phase_timeout_seconds,
                )

                duration_ms = (time.time() - start_time) * 1000
                logger.debug("Completed phase '%s' in %.1fms", phase_name, duration_ms)

                # Add phase-specific attributes to span
                self._add_phase_span_attributes(span, phase_name, context)

                # Report metrics
                if self._config.metrics_callback:
                    self._config.metrics_callback(f"phase_{phase_name}_duration_ms", duration_ms)

                return PhaseResult(
                    phase_name=phase_name,
                    status=PhaseStatus.COMPLETED,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    duration_ms=duration_ms,
                    output=output,
                )

            except asyncio.TimeoutError:
                duration_ms = (time.time() - start_time) * 1000
                span.set_attribute("phase.timeout", True)

                if phase_name in OPTIONAL_PHASES and self._config.skip_optional_on_timeout:
                    logger.warning("Optional phase '%s' timed out, skipping", phase_name)
                    return PhaseResult(
                        phase_name=phase_name,
                        status=PhaseStatus.SKIPPED,
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc),
                        duration_ms=duration_ms,
                        error=f"Timed out after {self._config.phase_timeout_seconds}s",
                    )
                else:
                    logger.error("Phase '%s' timed out", phase_name)
                    return PhaseResult(
                        phase_name=phase_name,
                        status=PhaseStatus.FAILED,
                        started_at=started_at,
                        completed_at=datetime.now(timezone.utc),
                        duration_ms=duration_ms,
                        error=f"Timed out after {self._config.phase_timeout_seconds}s",
                    )

            except Exception as e:  # noqa: BLE001 - phase execution boundary: user-provided phases can raise any exception
                duration_ms = (time.time() - start_time) * 1000
                logger.exception("Phase '%s' failed: %s", phase_name, e)
                span.record_exception(e)

                return PhaseResult(
                    phase_name=phase_name,
                    status=PhaseStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    duration_ms=duration_ms,
                    error=f"Phase '{phase_name}' failed: {type(e).__name__}",
                )

            finally:
                self._current_phase = None

    async def _execute_without_tracing(
        self,
        phase: Phase,
        phase_name: str,
        context: Any,
        started_at: datetime,
        start_time: float,
    ) -> PhaseResult:
        """Execute phase without tracing (for testing or when tracing disabled)."""
        try:
            output = await asyncio.wait_for(
                phase.execute(context),
                timeout=self._config.phase_timeout_seconds,
            )

            duration_ms = (time.time() - start_time) * 1000
            logger.debug("Completed phase '%s' in %.1fms", phase_name, duration_ms)

            if self._config.metrics_callback:
                self._config.metrics_callback(f"phase_{phase_name}_duration_ms", duration_ms)

            return PhaseResult(
                phase_name=phase_name,
                status=PhaseStatus.COMPLETED,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                duration_ms=duration_ms,
                output=output,
            )

        except asyncio.TimeoutError:
            duration_ms = (time.time() - start_time) * 1000

            if phase_name in OPTIONAL_PHASES and self._config.skip_optional_on_timeout:
                logger.warning("Optional phase '%s' timed out, skipping", phase_name)
                return PhaseResult(
                    phase_name=phase_name,
                    status=PhaseStatus.SKIPPED,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    duration_ms=duration_ms,
                    error=f"Timed out after {self._config.phase_timeout_seconds}s",
                )
            else:
                logger.error("Phase '%s' timed out", phase_name)
                return PhaseResult(
                    phase_name=phase_name,
                    status=PhaseStatus.FAILED,
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc),
                    duration_ms=duration_ms,
                    error=f"Timed out after {self._config.phase_timeout_seconds}s",
                )

        except Exception as e:  # noqa: BLE001 - phase execution boundary: user-provided phases can raise any exception
            duration_ms = (time.time() - start_time) * 1000
            logger.exception("Phase '%s' failed: %s", phase_name, e)

            return PhaseResult(
                phase_name=phase_name,
                status=PhaseStatus.FAILED,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                duration_ms=duration_ms,
                error=f"Phase '{phase_name}' failed: {type(e).__name__}",
            )

        finally:
            self._current_phase = None

    def _emit_trace(self, event_type: str, payload: dict[str, Any]) -> None:
        """Emit a lightweight trace event to the configured callback."""
        if not self._config.enable_tracing or self._config.trace_callback is None:
            return
        try:
            self._config.trace_callback(event_type, payload)
        except (RuntimeError, ValueError, TypeError, OSError, AttributeError) as e:
            logger.debug("Phase trace callback failed for '%s': %s", event_type, e)

    def _add_phase_span_attributes(self, span: Any, phase_name: str, context: Any) -> None:
        """Add phase-specific attributes to the tracing span."""
        result = getattr(context, "result", None)
        if result is None:
            return

        if phase_name == "debate_rounds":
            rounds_used = getattr(result, "rounds_used", None)
            if rounds_used is not None:
                span.set_attribute("debate.rounds_used", rounds_used)
        elif phase_name == "consensus":
            consensus_reached = getattr(result, "consensus_reached", None)
            if consensus_reached is not None:
                span.set_attribute("debate.consensus_reached", consensus_reached)

    # =========================================================================
    # Termination Control
    # =========================================================================

    def request_termination(self, reason: str = "Requested") -> None:
        """
        Request early termination of phase execution.

        Args:
            reason: Reason for termination
        """
        self._should_terminate = True
        self._termination_reason = reason
        logger.info("Termination requested: %s", reason)

    def check_termination(self) -> tuple[bool, str | None]:
        """
        Check if termination has been requested.

        Returns:
            Tuple of (should_terminate, reason)
        """
        return self._should_terminate, self._termination_reason

    # =========================================================================
    # Phase Management
    # =========================================================================

    def add_phase(self, name: str, phase: Phase) -> None:
        """
        Add or replace a phase.

        Args:
            name: Phase name
            phase: Phase object
        """
        self._phases[name] = phase

    def remove_phase(self, name: str) -> bool:
        """
        Remove a phase.

        Args:
            name: Phase name

        Returns:
            True if phase was removed
        """
        if name in self._phases:
            del self._phases[name]
            return True
        return False

    def get_phase(self, name: str) -> Phase | None:
        """Get a phase by name."""
        return self._phases.get(name)

    @property
    def phase_names(self) -> list[str]:
        """Get list of available phase names."""
        return list(self._phases.keys())

    @property
    def current_phase(self) -> str | None:
        """Get currently executing phase name."""
        return self._current_phase

    # =========================================================================
    # Results & Metrics
    # =========================================================================

    def get_results(self) -> list[PhaseResult]:
        """Get all phase results from last execution."""
        return self._results.copy()

    def get_metrics(self) -> dict[str, Any]:
        """
        Get execution metrics.

        Returns:
            Dictionary with execution statistics
        """
        total_duration = sum(r.duration_ms for r in self._results)
        completed = sum(1 for r in self._results if r.status == PhaseStatus.COMPLETED)
        failed = sum(1 for r in self._results if r.status == PhaseStatus.FAILED)
        skipped = sum(1 for r in self._results if r.status == PhaseStatus.SKIPPED)

        return {
            "total_phases": len(self._results),
            "completed_phases": completed,
            "failed_phases": failed,
            "skipped_phases": skipped,
            "total_duration_ms": total_duration,
            "phase_durations": {r.phase_name: r.duration_ms for r in self._results},
            "current_phase": self._current_phase,
            "terminated_early": self._should_terminate,
            "termination_reason": self._termination_reason,
        }


__all__ = [
    "PhaseExecutor",
    "PhaseConfig",
    "PhaseResult",
    "PhaseStatus",
    "ExecutionResult",
    "Phase",
    "STANDARD_PHASE_ORDER",
    "OPTIONAL_PHASES",
    "CRITICAL_PHASES",
]
