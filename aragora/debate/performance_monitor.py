"""
Debate Performance Monitoring System.

Tracks debate-level performance metrics for identifying slow debates,
performance bottlenecks, and system health issues.

Features:
- Round-level latency tracking (slow debate threshold: >30s per round)
- Phase-level breakdown within rounds
- Slow debate detection with full context logging
- Integration with Prometheus metrics
- Historical slow debate retrieval for diagnostics

Usage:
    monitor = DebatePerformanceMonitor()

    # Track a debate
    with monitor.track_debate(debate_id, task="Design rate limiter"):
        with monitor.track_round(debate_id, round_num=1):
            with monitor.track_phase(debate_id, "propose"):
                # Run propose phase
                pass

    # Check for slow debates
    slow_debates = monitor.get_slow_debates(threshold_seconds=30)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from collections.abc import Generator

from contextlib import contextmanager

from aragora.debate.triage_diagnostics import (
    DiagnosticSeverity,
    record_triage_diagnostic,
    triage_diagnostics_should_mirror_logs,
)

logger = logging.getLogger(__name__)

# Default threshold for slow debate detection (seconds per round)
DEFAULT_SLOW_ROUND_THRESHOLD = 30.0

# Maximum number of slow debates to retain in memory
MAX_SLOW_DEBATES_HISTORY = 100


def _record_triage_perf_event(
    *,
    code: str,
    summary: str,
    details: str = "",
    debate_id: str | None = None,
) -> bool:
    return record_triage_diagnostic(
        code=code,
        severity=DiagnosticSeverity.DIAGNOSTIC,
        logger_name=__name__,
        summary=summary,
        details=details,
        debate_id=debate_id,
    )


def _should_mirror_triage_perf_logs() -> bool:
    return triage_diagnostics_should_mirror_logs()


@dataclass
class PhaseMetric:
    """Metric for a single phase within a round."""

    phase_name: str
    start_time: float
    end_time: float | None = None
    duration_seconds: float | None = None
    agent_count: int = 0
    error: str | None = None


@dataclass
class RoundMetric:
    """Metric for a single debate round."""

    round_num: int
    start_time: float
    end_time: float | None = None
    duration_seconds: float | None = None
    phases: dict[str, PhaseMetric] = field(default_factory=dict)
    is_slow: bool = False
    slow_threshold: float = DEFAULT_SLOW_ROUND_THRESHOLD

    @property
    def total_phase_time(self) -> float:
        """Sum of all phase durations."""
        return sum(p.duration_seconds or 0 for p in self.phases.values())

    @property
    def slowest_phase(self) -> tuple[str, float] | None:
        """Return (phase_name, duration) of slowest phase."""
        if not self.phases:
            return None
        slowest = max(self.phases.items(), key=lambda x: x[1].duration_seconds or 0)
        return (slowest[0], slowest[1].duration_seconds or 0)


@dataclass
class DebateMetric:
    """Aggregate metrics for a complete debate."""

    debate_id: str
    task: str
    start_time: float
    end_time: float | None = None
    duration_seconds: float | None = None
    rounds: dict[int, RoundMetric] = field(default_factory=dict)
    outcome: str = "in_progress"
    agent_names: list[str] = field(default_factory=list)
    slow_round_count: int = 0

    @property
    def is_slow(self) -> bool:
        """Check if debate has any slow rounds."""
        return self.slow_round_count > 0

    @property
    def avg_round_duration(self) -> float:
        """Average duration per round."""
        completed = [r for r in self.rounds.values() if r.duration_seconds]
        if not completed:
            return 0.0
        return sum(r.duration_seconds or 0 for r in completed) / len(completed)

    def get_slowest_round(self) -> tuple[int, float] | None:
        """Return (round_num, duration) of slowest round."""
        if not self.rounds:
            return None
        slowest = max(self.rounds.items(), key=lambda x: x[1].duration_seconds or 0)
        return (slowest[0], slowest[1].duration_seconds or 0)


@dataclass
class SlowDebateRecord:
    """Record of a slow debate for diagnostics."""

    debate_id: str
    task: str
    detected_at: datetime
    total_duration: float
    round_count: int
    slow_round_count: int
    slowest_round: tuple[int, float] | None
    slowest_phase: tuple[str, float] | None
    agent_names: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "debate_id": self.debate_id,
            "task": self.task[:100] if self.task else "",
            "detected_at": self.detected_at.isoformat(),
            "total_duration_seconds": round(self.total_duration, 2),
            "round_count": self.round_count,
            "slow_round_count": self.slow_round_count,
            "slowest_round": self.slowest_round,
            "slowest_phase": self.slowest_phase,
            "agent_count": len(self.agent_names),
        }


class DebatePerformanceMonitor:
    """
    Monitors debate performance for identifying bottlenecks and slow debates.

    Provides visibility into:
    - Round-level latency (with configurable slow threshold)
    - Phase-level breakdown (propose, critique, vote, consensus)
    - Historical slow debate tracking
    - Integration with Prometheus metrics

    Usage:
        monitor = DebatePerformanceMonitor(slow_round_threshold=30.0)

        # Track debate execution
        with monitor.track_debate(debate_id, task="..."):
            for round_num in range(1, max_rounds + 1):
                with monitor.track_round(debate_id, round_num):
                    with monitor.track_phase(debate_id, "propose"):
                        await run_propose()
                    with monitor.track_phase(debate_id, "critique"):
                        await run_critique()

        # Get diagnostics
        insights = monitor.get_performance_insights(debate_id)
        slow_debates = monitor.get_slow_debates()
    """

    def __init__(
        self,
        slow_round_threshold: float = DEFAULT_SLOW_ROUND_THRESHOLD,
        emit_prometheus: bool = True,
    ):
        """
        Initialize the debate performance monitor.

        Args:
            slow_round_threshold: Seconds per round before flagging as slow
            emit_prometheus: Whether to emit Prometheus metrics
        """
        self.slow_round_threshold = slow_round_threshold
        self.emit_prometheus = emit_prometheus

        # Active debate tracking
        self._active_debates: dict[str, DebateMetric] = {}

        # Slow debate history (bounded)
        self._slow_debates: list[SlowDebateRecord] = []

        # Current round/phase tracking
        self._current_rounds: dict[str, int] = {}
        self._current_phases: dict[str, str] = {}

    @contextmanager
    def track_debate(
        self,
        debate_id: str,
        task: str = "",
        agent_names: list[str] | None = None,
    ) -> Generator[DebateMetric, None, None]:
        """
        Context manager to track a complete debate.

        Args:
            debate_id: Unique debate identifier
            task: Debate task/query
            agent_names: Names of participating agents

        Yields:
            DebateMetric for the debate
        """
        metric = DebateMetric(
            debate_id=debate_id,
            task=task,
            start_time=time.time(),
            agent_names=agent_names or [],
        )
        self._active_debates[debate_id] = metric

        logger.debug(
            "debate_perf_start debate_id=%s task=%s",
            debate_id,
            task[:50] if task else "",
        )

        try:
            yield metric
            metric.outcome = "completed"
        except Exception as e:  # noqa: BLE001 - context manager must record all errors before re-raising
            metric.outcome = f"error: {type(e).__name__}"
            raise
        finally:
            metric.end_time = time.time()
            metric.duration_seconds = metric.end_time - metric.start_time

            # Count slow rounds
            metric.slow_round_count = sum(1 for r in metric.rounds.values() if r.is_slow)

            # Log completion
            self._log_debate_completion(metric)

            # Record slow debate if applicable
            if metric.is_slow:
                self._record_slow_debate(metric)

            # Emit Prometheus metrics
            self._emit_metrics(metric)

            # Cleanup
            self._active_debates.pop(debate_id, None)
            self._current_rounds.pop(debate_id, None)
            self._current_phases.pop(debate_id, None)

    @contextmanager
    def track_round(
        self,
        debate_id: str,
        round_num: int,
    ) -> Generator[RoundMetric, None, None]:
        """
        Context manager to track a debate round.

        Args:
            debate_id: Debate identifier
            round_num: Round number (1-indexed)

        Yields:
            RoundMetric for the round
        """
        debate = self._active_debates.get(debate_id)
        if not debate:
            logger.warning("track_round called for unknown debate: %s", debate_id)
            # Create a dummy metric to avoid breaking the caller
            dummy = RoundMetric(round_num=round_num, start_time=time.time())
            yield dummy
            return

        metric = RoundMetric(
            round_num=round_num,
            start_time=time.time(),
            slow_threshold=self.slow_round_threshold,
        )
        debate.rounds[round_num] = metric
        self._current_rounds[debate_id] = round_num

        logger.debug(
            "round_perf_start debate_id=%s round=%d",
            debate_id,
            round_num,
        )

        try:
            yield metric
        finally:
            metric.end_time = time.time()
            metric.duration_seconds = metric.end_time - metric.start_time

            # Check if slow
            if metric.duration_seconds > self.slow_round_threshold:
                metric.is_slow = True
                slowest = metric.slowest_phase
                summary = (
                    "slow_round_detected debate_id=%s round=%d duration=%.2fs "
                    "threshold=%.2fs slowest_phase=%s"
                ) % (
                    debate_id,
                    round_num,
                    metric.duration_seconds,
                    self.slow_round_threshold,
                    f"{slowest[0]}={slowest[1]:.2f}s" if slowest else "unknown",
                )
                recorded = _record_triage_perf_event(
                    code="slow_round",
                    summary=summary,
                    debate_id=debate_id,
                )
                if not recorded or _should_mirror_triage_perf_logs():
                    logger.warning(
                        summary,
                        extra={
                            "triage_diag_code": "slow_round",
                            "triage_diag_severity": "diagnostic",
                        },
                    )
            else:
                logger.debug(
                    "round_perf_complete debate_id=%s round=%d duration=%.2fs",
                    debate_id,
                    round_num,
                    metric.duration_seconds,
                )

    @contextmanager
    def track_phase(
        self,
        debate_id: str,
        phase_name: str,
        agent_count: int = 0,
    ) -> Generator[PhaseMetric, None, None]:
        """
        Context manager to track a phase within a round.

        Args:
            debate_id: Debate identifier
            phase_name: Phase name (propose, critique, vote, consensus)
            agent_count: Number of agents participating in this phase

        Yields:
            PhaseMetric for the phase
        """
        debate = self._active_debates.get(debate_id)
        round_num = self._current_rounds.get(debate_id, 0)

        metric = PhaseMetric(
            phase_name=phase_name,
            start_time=time.time(),
            agent_count=agent_count,
        )

        # Store in round if available
        if debate and round_num in debate.rounds:
            debate.rounds[round_num].phases[phase_name] = metric

        self._current_phases[debate_id] = phase_name

        try:
            yield metric
        except Exception as e:  # noqa: BLE001 - context manager must record all errors before re-raising
            metric.error = f"phase_error:{type(e).__name__}"
            raise
        finally:
            metric.end_time = time.time()
            metric.duration_seconds = metric.end_time - metric.start_time

            # Emit phase metric
            if self.emit_prometheus:
                try:
                    from aragora.observability.metrics import record_phase_duration

                    record_phase_duration(phase_name, metric.duration_seconds)
                except ImportError:
                    logger.debug("Phase duration metrics not available")

    def get_active_debate(self, debate_id: str) -> DebateMetric | None:
        """Get metrics for an active debate."""
        return self._active_debates.get(debate_id)

    def get_performance_insights(
        self,
        debate_id: str,
    ) -> dict[str, Any]:
        """
        Get performance insights for a specific debate.

        Args:
            debate_id: Debate identifier

        Returns:
            Dictionary with performance analysis
        """
        debate = self._active_debates.get(debate_id)
        if not debate:
            return {"error": f"Debate not found: {debate_id}"}

        insights: dict[str, Any] = {
            "debate_id": debate_id,
            "status": debate.outcome,
            "total_duration_seconds": debate.duration_seconds,
            "round_count": len(debate.rounds),
            "slow_round_count": debate.slow_round_count,
            "avg_round_duration_seconds": round(debate.avg_round_duration, 2),
            "is_slow": debate.is_slow,
            "rounds": {},
        }

        # Add round breakdown
        for round_num, round_metric in sorted(debate.rounds.items()):
            insights["rounds"][round_num] = {
                "duration_seconds": round(round_metric.duration_seconds or 0, 2),
                "is_slow": round_metric.is_slow,
                "phases": {
                    name: round(phase.duration_seconds or 0, 2)
                    for name, phase in round_metric.phases.items()
                },
            }

        # Add slowest round/phase
        slowest_round = debate.get_slowest_round()
        if slowest_round:
            insights["slowest_round"] = {
                "round_num": slowest_round[0],
                "duration_seconds": round(slowest_round[1], 2),
            }

        return insights

    def get_slow_debates(
        self,
        limit: int = 20,
        threshold_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get list of slow debates for diagnostics.

        Args:
            limit: Maximum number of records to return
            threshold_seconds: Optional override for slow threshold

        Returns:
            List of slow debate records as dictionaries
        """
        records = self._slow_debates[-limit:]

        # Filter by threshold if provided
        if threshold_seconds is not None:
            records = [
                r for r in records if r.total_duration / max(r.round_count, 1) > threshold_seconds
            ]

        return [r.to_dict() for r in reversed(records)]

    def get_current_slow_debates(self) -> list[dict[str, Any]]:
        """
        Get currently active debates that are running slow.

        Returns:
            List of active slow debate summaries
        """
        slow = []
        for debate in self._active_debates.values():
            if debate.slow_round_count > 0:
                slow.append(
                    {
                        "debate_id": debate.debate_id,
                        "task": debate.task[:100] if debate.task else "",
                        "elapsed_seconds": round(time.time() - debate.start_time, 2),
                        "rounds_completed": len(debate.rounds),
                        "slow_rounds": debate.slow_round_count,
                    }
                )
        return slow

    def clear_history(self) -> None:
        """Clear slow debate history."""
        self._slow_debates.clear()
        logger.info("debate_perf_history_cleared")

    def _log_debate_completion(self, metric: DebateMetric) -> None:
        """Log debate completion with performance summary."""
        if metric.is_slow:
            slowest = metric.get_slowest_round()
            summary = (
                "slow_debate_complete debate_id=%s duration=%.2fs rounds=%d "
                "slow_rounds=%d avg_round=%.2fs slowest_round=%s outcome=%s"
            ) % (
                metric.debate_id,
                metric.duration_seconds or 0,
                len(metric.rounds),
                metric.slow_round_count,
                metric.avg_round_duration,
                f"r{slowest[0]}={slowest[1]:.2f}s" if slowest else "none",
                metric.outcome,
            )
            recorded = _record_triage_perf_event(
                code="slow_debate",
                summary=summary,
                debate_id=metric.debate_id,
            )
            if not recorded or _should_mirror_triage_perf_logs():
                logger.warning(
                    summary,
                    extra={
                        "triage_diag_code": "slow_debate",
                        "triage_diag_severity": "diagnostic",
                    },
                )
        else:
            logger.info(
                "debate_perf_complete debate_id=%s duration=%.2fs rounds=%d "
                "avg_round=%.2fs outcome=%s",
                metric.debate_id,
                metric.duration_seconds or 0,
                len(metric.rounds),
                metric.avg_round_duration,
                metric.outcome,
            )

    def _record_slow_debate(self, metric: DebateMetric) -> None:
        """Record a slow debate for historical tracking."""
        slowest_round = metric.get_slowest_round()

        # Find slowest phase across all rounds
        slowest_phase: tuple[str, float] | None = None
        for round_metric in metric.rounds.values():
            round_slowest = round_metric.slowest_phase
            if round_slowest:
                if slowest_phase is None or round_slowest[1] > slowest_phase[1]:
                    slowest_phase = round_slowest

        record = SlowDebateRecord(
            debate_id=metric.debate_id,
            task=metric.task,
            detected_at=datetime.now(timezone.utc),
            total_duration=metric.duration_seconds or 0,
            round_count=len(metric.rounds),
            slow_round_count=metric.slow_round_count,
            slowest_round=slowest_round,
            slowest_phase=slowest_phase,
            agent_names=metric.agent_names,
        )

        self._slow_debates.append(record)

        # Trim history if needed
        if len(self._slow_debates) > MAX_SLOW_DEBATES_HISTORY:
            self._slow_debates = self._slow_debates[-MAX_SLOW_DEBATES_HISTORY:]

    def _emit_metrics(self, metric: DebateMetric) -> None:
        """Emit Prometheus metrics for the debate."""
        if not self.emit_prometheus:
            return

        try:
            from aragora.observability.metrics import record_debate_completion

            # Record overall debate completion
            outcome = (
                "consensus"
                if "completed" in metric.outcome
                else ("error" if "error" in metric.outcome else "no_consensus")
            )
            record_debate_completion(
                duration_seconds=metric.duration_seconds or 0,
                rounds=len(metric.rounds),
                outcome=outcome,
            )

        except ImportError:
            logger.debug("Debate completion metrics not available")


# Global instance for convenience
_default_monitor: DebatePerformanceMonitor | None = None


def get_debate_monitor() -> DebatePerformanceMonitor:
    """Get the default debate performance monitor instance."""
    global _default_monitor
    if _default_monitor is None:
        _default_monitor = DebatePerformanceMonitor()
    return _default_monitor


__all__ = [
    "DebatePerformanceMonitor",
    "DebateMetric",
    "RoundMetric",
    "PhaseMetric",
    "SlowDebateRecord",
    "get_debate_monitor",
    "DEFAULT_SLOW_ROUND_THRESHOLD",
]
