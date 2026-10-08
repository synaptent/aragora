"""
Debate orchestration metrics.

Provides Prometheus metrics for tracking debate execution,
performance monitoring, phases, and consensus outcomes.
"""

from __future__ import annotations

import logging
from threading import Lock
import time
from contextlib import contextmanager
from typing import Any
from collections.abc import Generator

from aragora.observability.metrics.base import NoOpMetric, get_metrics_enabled
from aragora.observability.server_metrics.api import (
    ACTIVE_DEBATES as _CANONICAL_ACTIVE_DEBATES,
)

logger = logging.getLogger(__name__)

# Global metric variables
DEBATE_DURATION: Any = None
DEBATE_ROUNDS: Any = None
DEBATE_PHASE_DURATION: Any = None
AGENT_PARTICIPATION: Any = None
SLOW_DEBATES_TOTAL: Any = None
SLOW_ROUNDS_TOTAL: Any = None
DEBATE_ROUND_LATENCY: Any = None
ACTIVE_DEBATES: Any = _CANONICAL_ACTIVE_DEBATES
CONSENSUS_RATE: Any = None
DEBATE_EARLY_TERMINATION_TOTAL: Any = None
DEBATE_STABILITY_SCORE: Any = None

_initialized = False
_active_debates_collector_lock = Lock()


class _ActiveDebatesCollector:
    """Prometheus adapter that reads the canonical active-debates gauge."""

    _canonical_gauge = _CANONICAL_ACTIVE_DEBATES

    def collect(self) -> Generator[Any, None, None]:
        from prometheus_client.core import GaugeMetricFamily

        metric = GaugeMetricFamily(
            _CANONICAL_ACTIVE_DEBATES.name,
            _CANONICAL_ACTIVE_DEBATES.help,
        )
        metric.add_metric([], _CANONICAL_ACTIVE_DEBATES.get())
        yield metric


def _ensure_active_debates_collector(registry: Any) -> None:
    """Register one read-only Prometheus view of the canonical gauge."""
    with _active_debates_collector_lock:
        existing = registry._names_to_collectors.get(_CANONICAL_ACTIVE_DEBATES.name)
        if getattr(existing, "_canonical_gauge", None) is _CANONICAL_ACTIVE_DEBATES:
            return
        if existing is not None:
            registry.unregister(existing)
        registry.register(_ActiveDebatesCollector())


def init_debate_metrics() -> None:
    """Initialize debate metrics."""
    global _initialized
    global DEBATE_DURATION, DEBATE_ROUNDS, DEBATE_PHASE_DURATION
    global AGENT_PARTICIPATION, SLOW_DEBATES_TOTAL, SLOW_ROUNDS_TOTAL
    global DEBATE_ROUND_LATENCY, ACTIVE_DEBATES, CONSENSUS_RATE
    global DEBATE_EARLY_TERMINATION_TOTAL, DEBATE_STABILITY_SCORE

    if _initialized:
        return

    if not get_metrics_enabled():
        _init_noop_metrics()
        _initialized = True
        return

    try:
        from prometheus_client import Counter, Gauge, Histogram, REGISTRY

        def _get_or_create_histogram(
            name: str, desc: str, labels: list | None = None, buckets: list | None = None
        ):
            """Get existing metric or create new one."""
            # Try to get from registry first
            collectors = list(REGISTRY._names_to_collectors.values())
            for c in collectors:
                if hasattr(c, "_name") and c._name == name:
                    return c
            # Create new
            if labels:
                return Histogram(name, desc, labels, buckets=buckets or Histogram.DEFAULT_BUCKETS)
            return Histogram(name, desc, buckets=buckets or Histogram.DEFAULT_BUCKETS)

        def _get_or_create_counter(name: str, desc: str, labels: list | None = None):
            """Get existing metric or create new one."""
            collectors = list(REGISTRY._names_to_collectors.values())
            for c in collectors:
                if hasattr(c, "_name") and c._name == name:
                    return c
            if labels:
                return Counter(name, desc, labels)
            return Counter(name, desc)

        def _get_or_create_gauge(name: str, desc: str):
            """Get existing metric or create new one."""
            collectors = list(REGISTRY._names_to_collectors.values())
            for c in collectors:
                if hasattr(c, "_name") and c._name == name:
                    return c
            return Gauge(name, desc)

        DEBATE_DURATION = _get_or_create_histogram(
            "aragora_debate_duration_seconds",
            "Total debate duration in seconds",
            ["outcome"],
            [1, 5, 10, 30, 60, 120, 300, 600, 1200],
        )

        DEBATE_ROUNDS = _get_or_create_histogram(
            "aragora_debate_rounds_total",
            "Number of rounds per debate",
            ["outcome"],
            [1, 2, 3, 4, 5, 7, 10, 15, 20],
        )

        DEBATE_PHASE_DURATION = _get_or_create_histogram(
            "aragora_debate_phase_duration_seconds",
            "Duration of debate phases",
            ["phase"],
            [0.1, 0.5, 1, 2, 5, 10, 30, 60],
        )

        AGENT_PARTICIPATION = _get_or_create_counter(
            "aragora_agent_participation_total",
            "Agent participation in debates",
            ["agent", "role"],
        )

        SLOW_DEBATES_TOTAL = _get_or_create_counter(
            "aragora_slow_debates_total",
            "Count of debates exceeding time threshold",
            ["severity"],
        )

        SLOW_ROUNDS_TOTAL = _get_or_create_counter(
            "aragora_slow_rounds_total",
            "Count of rounds exceeding time threshold",
            ["phase"],
        )

        DEBATE_ROUND_LATENCY = _get_or_create_histogram(
            "aragora_debate_round_latency_seconds",
            "Per-round latency in debates",
            None,
            [0.5, 1, 2, 5, 10, 20, 30, 60],
        )

        ACTIVE_DEBATES = _CANONICAL_ACTIVE_DEBATES
        _ensure_active_debates_collector(REGISTRY)

        CONSENSUS_RATE = _get_or_create_gauge(
            "aragora_consensus_rate",
            "Rolling consensus achievement rate",
        )

        DEBATE_EARLY_TERMINATION_TOTAL = _get_or_create_counter(
            "aragora_debate_early_termination_total",
            "Early debate termination count",
            ["reason"],
        )

        DEBATE_STABILITY_SCORE = _get_or_create_histogram(
            "aragora_debate_stability_score",
            "Debate stability score distribution",
            None,
            [0.1, 0.2, 0.4, 0.6, 0.75, 0.85, 0.9, 0.95, 1.0],
        )

        _initialized = True
        logger.debug("Debate metrics initialized")

    except ImportError:
        _init_noop_metrics()
        _initialized = True


def _init_noop_metrics() -> None:
    """Initialize no-op metrics when Prometheus is disabled."""
    global DEBATE_DURATION, DEBATE_ROUNDS, DEBATE_PHASE_DURATION
    global AGENT_PARTICIPATION, SLOW_DEBATES_TOTAL, SLOW_ROUNDS_TOTAL
    global DEBATE_ROUND_LATENCY, ACTIVE_DEBATES, CONSENSUS_RATE
    global DEBATE_EARLY_TERMINATION_TOTAL, DEBATE_STABILITY_SCORE

    DEBATE_DURATION = NoOpMetric()
    DEBATE_ROUNDS = NoOpMetric()
    DEBATE_PHASE_DURATION = NoOpMetric()
    AGENT_PARTICIPATION = NoOpMetric()
    SLOW_DEBATES_TOTAL = NoOpMetric()
    SLOW_ROUNDS_TOTAL = NoOpMetric()
    DEBATE_ROUND_LATENCY = NoOpMetric()
    ACTIVE_DEBATES = _CANONICAL_ACTIVE_DEBATES
    CONSENSUS_RATE = NoOpMetric()
    DEBATE_EARLY_TERMINATION_TOTAL = NoOpMetric()
    DEBATE_STABILITY_SCORE = NoOpMetric()


def _ensure_init() -> None:
    """Ensure metrics are initialized."""
    if not _initialized:
        init_debate_metrics()


# =============================================================================
# Recording Functions
# =============================================================================


def _observe_metric(metric: Any, value: float, labels: dict[str, str] | None = None) -> None:
    """Observe a metric safely, handling label mismatches."""
    if labels:
        labelnames = getattr(metric, "_labelnames", None)
        # If metric has no labels or labels don't match, try to observe without labels
        if not labelnames or set(labelnames) != set(labels.keys()):
            try:
                # Try with metric's actual labels if they exist
                if labelnames:
                    fallback = {name: labels.get(name, "unknown") for name in labelnames}
                    metric.labels(**fallback).observe(value)
                else:
                    metric.observe(value)
            except (ValueError, TypeError, AttributeError):
                logger.debug("Metric observe failed for %s", getattr(metric, "_name", "unknown"))
            return
        try:
            metric.labels(**labels).observe(value)
            return
        except (ValueError, TypeError) as e:
            # Fallback for mismatched label sets in registry
            logger.debug("Metric label mismatch for %s: %s", getattr(metric, "_name", "unknown"), e)
            return
    try:
        metric.observe(value)
    except TypeError:
        pass  # NoOp metric or other issue


def record_debate_completion(
    duration_seconds: float,
    rounds: int,
    outcome: str,
) -> None:
    """Record debate completion metrics.

    Args:
        duration_seconds: Total debate duration
        rounds: Number of rounds in the debate
        outcome: Debate outcome (consensus, majority, timeout, etc.)
    """
    _ensure_init()
    _observe_metric(DEBATE_DURATION, duration_seconds, {"outcome": outcome})
    _observe_metric(DEBATE_ROUNDS, rounds, {"outcome": outcome})


def record_phase_duration(phase: str, duration_seconds: float) -> None:
    """Record duration of a debate phase.

    Args:
        phase: Phase name (proposal, critique, revision, voting, etc.)
        duration_seconds: Phase duration
    """
    _ensure_init()
    _observe_metric(DEBATE_PHASE_DURATION, duration_seconds, {"phase": phase})


def record_agent_participation(agent: str, role: str) -> None:
    """Record agent participation in a debate.

    Args:
        agent: Agent name
        role: Role in debate (proposer, critic, judge, etc.)
    """
    _ensure_init()
    AGENT_PARTICIPATION.labels(agent=agent, role=role).inc()


def record_slow_debate(severity: str = "warning") -> None:
    """Record a slow debate.

    Args:
        severity: Severity level (warning, critical)
    """
    _ensure_init()
    SLOW_DEBATES_TOTAL.labels(severity=severity).inc()


def record_slow_round(phase: str = "unknown") -> None:
    """Record a slow round.

    Args:
        phase: Phase where slowness occurred
    """
    _ensure_init()
    SLOW_ROUNDS_TOTAL.labels(phase=phase).inc()


def record_round_latency(latency_seconds: float) -> None:
    """Record per-round latency.

    Args:
        latency_seconds: Round latency in seconds
    """
    _ensure_init()
    DEBATE_ROUND_LATENCY.observe(latency_seconds)


def record_debate_stability(score: float) -> None:
    """Record debate stability score."""
    _ensure_init()
    DEBATE_STABILITY_SCORE.observe(score)


def record_early_termination(reason: str) -> None:
    """Record early termination event."""
    _ensure_init()
    DEBATE_EARLY_TERMINATION_TOTAL.labels(reason=reason).inc()


# Backwards-compatible aliases
record_debate_completion_v2 = record_debate_completion
record_phase_duration_v2 = record_phase_duration
record_agent_participation_v2 = record_agent_participation
record_slow_round_v2 = record_slow_round
record_round_latency_v2 = record_round_latency


def set_active_debates(count: int) -> None:
    """Set the number of active debates.

    Args:
        count: Number of currently active debates
    """
    _ensure_init()
    ACTIVE_DEBATES.set(count)


def increment_active_debates() -> None:
    """Increment active debates count."""
    _ensure_init()
    ACTIVE_DEBATES.inc()


def decrement_active_debates() -> None:
    """Decrement active debates count."""
    _ensure_init()
    ACTIVE_DEBATES.dec()


def set_consensus_rate(rate: float) -> None:
    """Set the consensus achievement rate.

    Args:
        rate: Consensus rate (0.0 to 1.0)
    """
    _ensure_init()
    CONSENSUS_RATE.set(rate)


# =============================================================================
# Context Managers
# =============================================================================


@contextmanager
def track_debate() -> Generator[None, None, None]:
    """Context manager to track debate execution.

    Automatically increments/decrements active debates counter.

    Example:
        with track_debate():
            arena.run()
    """
    _ensure_init()
    increment_active_debates()
    try:
        yield
    finally:
        decrement_active_debates()


@contextmanager
def track_phase(phase: str) -> Generator[None, None, None]:
    """Context manager to track debate phase duration.

    Args:
        phase: Phase name

    Example:
        with track_phase("proposal"):
            await generate_proposals()
    """
    _ensure_init()
    start = time.perf_counter()
    try:
        yield
    finally:
        duration = time.perf_counter() - start
        record_phase_duration(phase, duration)


__all__ = [
    # Metrics
    "DEBATE_DURATION",
    "DEBATE_ROUNDS",
    "DEBATE_PHASE_DURATION",
    "AGENT_PARTICIPATION",
    "SLOW_DEBATES_TOTAL",
    "SLOW_ROUNDS_TOTAL",
    "DEBATE_ROUND_LATENCY",
    "ACTIVE_DEBATES",
    "CONSENSUS_RATE",
    # Functions
    "init_debate_metrics",
    "record_debate_completion",
    "record_phase_duration",
    "record_agent_participation",
    "record_slow_debate",
    "record_slow_round",
    "record_round_latency",
    "set_active_debates",
    "increment_active_debates",
    "decrement_active_debates",
    "set_consensus_rate",
    "track_debate",
    "track_phase",
]
