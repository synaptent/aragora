"""
Agent Performance Telemetry System.

Tracks agent response times, success rates, and failure patterns to enable
data-driven debugging and optimization of the debate system.

Generated from nomic loop proposal by codex-engineer with critique fixes
from gemini-visionary.
"""

from __future__ import annotations

__all__ = [
    "AgentMetric",
    "AgentStats",
    "AgentPerformanceMonitor",
]

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentMetric:
    """Single metric entry for an agent call."""

    agent_name: str
    operation: str
    start_time: float
    end_time: float | None = None
    duration_ms: float | None = None
    success: bool = False
    error: str | None = None
    response_length: int = 0
    phase: str = ""
    round_num: int = 0


@dataclass
class AgentStats:
    """Aggregated statistics for an agent."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    timeout_calls: int = 0
    total_duration_ms: float = 0.0
    min_duration_ms: float = float("inf")
    max_duration_ms: float = 0.0
    avg_duration_ms: float = 0.0
    total_response_chars: int = 0

    def update(self, metric: AgentMetric) -> None:
        """Update stats with a new metric."""
        self.total_calls += 1
        if metric.success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1
            if metric.error and "timeout" in metric.error.lower():
                self.timeout_calls += 1

        if metric.duration_ms is not None:
            self.total_duration_ms += metric.duration_ms
            self.min_duration_ms = min(self.min_duration_ms, metric.duration_ms)
            self.max_duration_ms = max(self.max_duration_ms, metric.duration_ms)
            self.avg_duration_ms = self.total_duration_ms / self.total_calls

        self.total_response_chars += metric.response_length

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.total_calls == 0:
            return 0.0
        return (self.successful_calls / self.total_calls) * 100

    @property
    def timeout_rate(self) -> float:
        """Calculate timeout rate as percentage."""
        if self.total_calls == 0:
            return 0.0
        return (self.timeout_calls / self.total_calls) * 100


class AgentPerformanceMonitor:
    """
    Monitors agent performance for debugging and optimization.

    Usage:
        monitor = AgentPerformanceMonitor()

        # Track a call
        tracking = monitor.track_agent_call("claude", "generate", phase="debate")
        try:
            response = await agent.generate(prompt)
            monitor.record_completion(tracking, success=True, response=response)
        except Exception as e:
            monitor.record_completion(tracking, success=False, error=str(e))

        # Get insights
        insights = monitor.get_performance_insights()
    """

    def __init__(self, session_dir: Path | None = None):
        """
        Initialize the performance monitor.

        Args:
            session_dir: Optional directory to save metrics. If provided,
                        metrics will be persisted on save().
        """
        self.metrics: list[AgentMetric] = []
        self.agent_stats: dict[str, AgentStats] = defaultdict(AgentStats)
        self.session_dir = session_dir
        self._active_trackings: dict[str, AgentMetric] = {}

    def track_agent_call(
        self,
        agent_name: str,
        operation: str = "generate",
        phase: str = "",
        round_num: int = 0,
    ) -> str:
        """
        Start tracking an agent call.

        Args:
            agent_name: Name of the agent being called
            operation: Type of operation (generate, critique, vote, etc.)
            phase: Current debate phase (context, debate, design, implement)
            round_num: Current round number

        Returns:
            Tracking ID to pass to record_completion()
        """
        tracking_id = f"{agent_name}_{operation}_{time.time()}"

        metric = AgentMetric(
            agent_name=agent_name,
            operation=operation,
            start_time=time.time(),
            phase=phase,
            round_num=round_num,
        )

        self._active_trackings[tracking_id] = metric
        logger.debug("perf_track_start agent=%s op=%s phase=%s", agent_name, operation, phase)

        return tracking_id

    def record_completion(
        self,
        tracking_id: str,
        success: bool,
        response: str | None = None,
        error: str | None = None,
    ) -> None:
        """
        Record the completion of a tracked agent call.

        Args:
            tracking_id: ID returned by track_agent_call()
            success: Whether the call succeeded
            response: The response text (for success cases)
            error: Error message (for failure cases)
        """
        if tracking_id not in self._active_trackings:
            logger.warning("perf_unknown_tracking id=%s", tracking_id)
            return

        metric = self._active_trackings.pop(tracking_id)
        metric.end_time = time.time()
        metric.duration_ms = (metric.end_time - metric.start_time) * 1000
        metric.success = success
        metric.error = error

        # Sanitize response - handle None and non-string gracefully
        if response is not None:
            if isinstance(response, str):
                # Remove null bytes as suggested by gemini-visionary
                response = response.replace("\0", "")
                metric.response_length = len(response)
            else:
                metric.response_length = 0

        # Store metric
        self.metrics.append(metric)

        # Update agent stats
        self.agent_stats[metric.agent_name].update(metric)

        # Log performance data
        status = "success" if success else f"error={error}"
        logger.info(
            "perf_complete agent=%s op=%s duration=%.0fms status=%s response_len=%s",
            metric.agent_name,
            metric.operation,
            metric.duration_ms,
            status,
            metric.response_length,
        )

    def get_performance_insights(self) -> dict[str, Any]:
        """
        Get aggregated performance insights.

        Returns:
            Dictionary with performance analysis including:
            - agent_stats: Per-agent statistics
            - slowest_agents: Agents ranked by average response time
            - most_failures: Agents ranked by failure rate
            - recommendations: Suggested optimizations
        """
        if not self.metrics:
            return {"message": "No metrics collected yet"}

        insights: dict[str, Any] = {
            "total_calls": len(self.metrics),
            "total_duration_ms": sum(m.duration_ms for m in self.metrics if m.duration_ms),
            "agent_stats": {},
            "slowest_agents": [],
            "most_failures": [],
            "timeout_prone": [],
            "recommendations": [],
        }

        # Compile agent stats
        for agent_name, stats in self.agent_stats.items():
            insights["agent_stats"][agent_name] = {
                "total_calls": stats.total_calls,
                "success_rate": round(stats.success_rate, 1),
                "timeout_rate": round(stats.timeout_rate, 1),
                "avg_duration_ms": round(stats.avg_duration_ms, 0),
                "min_duration_ms": (
                    round(stats.min_duration_ms, 0) if stats.min_duration_ms != float("inf") else 0
                ),
                "max_duration_ms": round(stats.max_duration_ms, 0),
                "total_response_chars": stats.total_response_chars,
            }

        # Rank by slowness
        sorted_by_speed = sorted(
            self.agent_stats.items(), key=lambda x: x[1].avg_duration_ms, reverse=True
        )
        insights["slowest_agents"] = [
            {"agent": name, "avg_ms": round(stats.avg_duration_ms, 0)}
            for name, stats in sorted_by_speed[:3]
        ]

        # Rank by failure rate
        sorted_by_failures = sorted(
            self.agent_stats.items(), key=lambda x: x[1].failed_calls, reverse=True
        )
        insights["most_failures"] = [
            {
                "agent": name,
                "failures": stats.failed_calls,
                "rate": round(100 - stats.success_rate, 1),
            }
            for name, stats in sorted_by_failures[:3]
            if stats.failed_calls > 0
        ]

        # Identify timeout-prone agents
        for agent_name, stats in self.agent_stats.items():
            if stats.timeout_rate > 20:
                insights["timeout_prone"].append(
                    {
                        "agent": agent_name,
                        "timeout_rate": round(stats.timeout_rate, 1),
                    }
                )

        # Generate recommendations
        for agent_name, stats in self.agent_stats.items():
            if stats.timeout_rate > 30:
                insights["recommendations"].append(
                    f"Agent '{agent_name}' has {stats.timeout_rate:.0f}% timeout rate. "
                    f"Consider increasing timeout or simplifying prompts."
                )
            if stats.avg_duration_ms > 60000:  # > 60 seconds
                insights["recommendations"].append(
                    f"Agent '{agent_name}' averages {stats.avg_duration_ms / 1000:.0f}s per call. "
                    f"Consider prompt optimization or caching."
                )
            if stats.success_rate < 50 and stats.total_calls >= 3:
                insights["recommendations"].append(
                    f"Agent '{agent_name}' has only {stats.success_rate:.0f}% success rate. "
                    f"Check circuit breaker or API availability."
                )

        return insights

    def get_phase_breakdown(self) -> dict[str, dict[str, Any]]:
        """Get performance breakdown by debate phase."""
        phase_metrics: dict[str, list[AgentMetric]] = defaultdict(list)

        for metric in self.metrics:
            if metric.phase:
                phase_metrics[metric.phase].append(metric)

        breakdown = {}
        for phase, metrics in phase_metrics.items():
            total_ms = sum(m.duration_ms or 0 for m in metrics)
            successes = sum(1 for m in metrics if m.success)
            breakdown[phase] = {
                "total_calls": len(metrics),
                "total_duration_ms": round(total_ms, 0),
                "success_rate": round(successes / len(metrics) * 100, 1) if metrics else 0,
                "avg_duration_ms": round(total_ms / len(metrics), 0) if metrics else 0,
            }

        return breakdown

    def save(self, filename: str = "performance_metrics.json") -> Path | None:
        """
        Save metrics to a JSON file.

        Args:
            filename: Name of the file to save to

        Returns:
            Path to saved file, or None if no session_dir configured
        """
        if not self.session_dir:
            logger.debug("perf_save_skipped no session_dir configured")
            return None

        self.session_dir.mkdir(parents=True, exist_ok=True)
        filepath = self.session_dir / filename

        data = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "metrics_count": len(self.metrics),
            "insights": self.get_performance_insights(),
            "phase_breakdown": self.get_phase_breakdown(),
            "raw_metrics": [
                {
                    "agent_name": m.agent_name,
                    "operation": m.operation,
                    "phase": m.phase,
                    "round_num": m.round_num,
                    "duration_ms": m.duration_ms,
                    "success": m.success,
                    "error": m.error,
                    "response_length": m.response_length,
                }
                for m in self.metrics[-100:]  # Last 100 metrics to avoid huge files
            ],
        }

        try:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
            logger.info("perf_saved path=%s metrics=%s", filepath, len(self.metrics))
            return filepath
        except (OSError, TypeError, ValueError) as e:
            logger.error("perf_save_error error=%s", e)
            return None

    def clear(self) -> None:
        """Clear all collected metrics."""
        self.metrics.clear()
        self.agent_stats.clear()
        self._active_trackings.clear()
        logger.debug("perf_cleared")
