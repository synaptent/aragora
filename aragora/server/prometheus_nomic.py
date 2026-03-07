"""
Nomic Loop metrics for Aragora server.

Extracted from prometheus.py for maintainability.
Provides metrics for Nomic loop phase execution and cycle tracking.
"""

import logging
import time
from functools import wraps
from typing import Any, ParamSpec, TypeVar
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

from aragora.server.prometheus import (
    PROMETHEUS_AVAILABLE,
    _simple_metrics,
)

# Import metric definitions when prometheus is available
if PROMETHEUS_AVAILABLE:
    from aragora.server.prometheus import (
        NOMIC_AGENT_PHASE_DURATION,
        NOMIC_CYCLE_DURATION,
        NOMIC_CYCLE_TOTAL,
        NOMIC_PHASE_DURATION,
        NOMIC_PHASE_TOTAL,
    )


def record_nomic_phase(
    phase: str,
    outcome: str,
    duration_seconds: float,
) -> None:
    """Record a nomic loop phase execution.

    Args:
        phase: Phase name (context, debate, design, implement, verify, commit)
        outcome: Phase outcome (success, failure, skipped)
        duration_seconds: Time spent in the phase
    """
    if PROMETHEUS_AVAILABLE:
        NOMIC_PHASE_DURATION.labels(phase=phase, outcome=outcome).observe(duration_seconds)
        NOMIC_PHASE_TOTAL.labels(phase=phase, outcome=outcome).inc()
    else:
        _simple_metrics.observe_histogram(
            "aragora_nomic_phase_duration_seconds",
            duration_seconds,
            {"phase": phase, "outcome": outcome},
        )
        _simple_metrics.inc_counter(
            "aragora_nomic_phases_total",
            {"phase": phase, "outcome": outcome},
        )


def record_nomic_cycle(
    outcome: str,
    duration_seconds: float,
) -> None:
    """Record a complete nomic cycle execution.

    Args:
        outcome: Cycle outcome (success, failure, partial)
        duration_seconds: Total cycle time
    """
    if PROMETHEUS_AVAILABLE:
        NOMIC_CYCLE_DURATION.labels(outcome=outcome).observe(duration_seconds)
        NOMIC_CYCLE_TOTAL.labels(outcome=outcome).inc()
    else:
        _simple_metrics.observe_histogram(
            "aragora_nomic_cycle_duration_seconds",
            duration_seconds,
            {"outcome": outcome},
        )
        _simple_metrics.inc_counter(
            "aragora_nomic_cycles_total",
            {"outcome": outcome},
        )


def record_nomic_agent_phase(
    phase: str,
    agent: str,
    duration_seconds: float,
) -> None:
    """Record time spent by an agent in a phase.

    Args:
        phase: Phase name (context, debate, design, implement, verify)
        agent: Agent name (claude, codex, gemini, grok)
        duration_seconds: Time the agent spent in this phase
    """
    if PROMETHEUS_AVAILABLE:
        NOMIC_AGENT_PHASE_DURATION.labels(phase=phase, agent=agent).observe(duration_seconds)
    else:
        _simple_metrics.observe_histogram(
            "aragora_nomic_agent_phase_seconds",
            duration_seconds,
            {"phase": phase, "agent": agent},
        )


def timed_nomic_phase(
    phase: str,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Async decorator to time nomic phase execution.

    Args:
        phase: Phase name (context, debate, design, implement, verify, commit)

    Returns:
        Async decorator that wraps phase execution with timing.

    Usage:
        @timed_nomic_phase("debate")
        async def execute(self) -> DebateResult:
            ...
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            outcome = "success"
            try:
                result = await func(*args, **kwargs)
                # Check result for success indicator
                if hasattr(result, "get") and not result.get("success", True):
                    outcome = "failure"
                return result
            except (ValueError, TypeError, KeyError, RuntimeError, OSError, TimeoutError) as e:
                logger.warning("Nomic phase %s failed: %s", phase, e)
                outcome = "failure"
                raise
            finally:
                duration = time.perf_counter() - start
                record_nomic_phase(phase, outcome, duration)

        return wrapper

    return decorator


__all__ = [
    "record_nomic_phase",
    "record_nomic_cycle",
    "record_nomic_agent_phase",
    "timed_nomic_phase",
]
