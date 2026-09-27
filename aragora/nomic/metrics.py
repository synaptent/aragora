"""
Nomic Loop Prometheus Metrics.

Provides observability for the nomic loop state machine:
- Phase transitions and durations
- Cycle success/failure rates
- Circuit breaker states
- Stuck phase detection

Usage:
    from aragora.nomic.metrics import (
        track_phase_transition,
        track_cycle_complete,
        nomic_metrics_callback,
    )

    # Track phase transition
    track_phase_transition("context", "debate", 45.2)

    # Register callback with state machine
    machine.on_transition(nomic_metrics_callback)
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from aragora.observability.server_metrics import Counter, Gauge, Histogram

if TYPE_CHECKING:
    from aragora.observability.server_metrics.export import NomicMetricCollection

    from .events import Event
    from .states import NomicState

logger = logging.getLogger(__name__)

# =============================================================================
# Nomic Loop Metrics
# =============================================================================

NOMIC_PHASE_TRANSITIONS = Counter(
    name="aragora_nomic_phase_transitions_total",
    help="Total nomic loop phase transitions",
    label_names=["from_phase", "to_phase"],
)

NOMIC_CURRENT_PHASE = Gauge(
    name="aragora_nomic_current_phase",
    help="Current nomic loop phase (encoded: 0=idle, 1=context, 2=debate, 3=design, 4=implement, 5=verify, 6=commit, 7=completed, 8=failed, 9=paused, 10=recovery)",
    label_names=["cycle_id"],
)

NOMIC_PHASE_DURATION = Histogram(
    name="aragora_nomic_phase_duration_seconds",
    help="Duration of each nomic loop phase in seconds",
    label_names=["phase"],
    buckets=[1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0],
)

NOMIC_CYCLES_TOTAL = Counter(
    name="aragora_nomic_cycles_total",
    help="Total nomic loop cycles by outcome",
    label_names=["outcome"],  # success, failure, aborted
)

NOMIC_CYCLES_IN_PROGRESS = Gauge(
    name="aragora_nomic_cycles_in_progress",
    help="Number of nomic cycles currently running",
    label_names=[],
)

NOMIC_PHASE_LAST_TRANSITION = Gauge(
    name="aragora_nomic_phase_last_transition_timestamp",
    help="Unix timestamp of last phase transition (for staleness detection)",
    label_names=["cycle_id"],
)

NOMIC_CIRCUIT_BREAKERS_OPEN = Gauge(
    name="aragora_nomic_circuit_breakers_open",
    help="Number of nomic circuit breakers in open state",
    label_names=[],
)

NOMIC_ERRORS = Counter(
    name="aragora_nomic_errors_total",
    help="Total nomic loop errors by phase and error type",
    label_names=["phase", "error_type"],
)

NOMIC_RECOVERY_DECISIONS = Counter(
    name="aragora_nomic_recovery_decisions_total",
    help="Total recovery decisions by strategy",
    label_names=["strategy"],  # retry, skip, rollback, restart, pause, fail
)

NOMIC_RETRIES = Counter(
    name="aragora_nomic_retries_total",
    help="Total retries by phase",
    label_names=["phase"],
)

# Phase encoding for gauge (readable in Grafana)
PHASE_ENCODING = {
    "IDLE": 0,
    "CONTEXT": 1,
    "DEBATE": 2,
    "DESIGN": 3,
    "IMPLEMENT": 4,
    "VERIFY": 5,
    "COMMIT": 6,
    "COMPLETED": 7,
    "FAILED": 8,
    "PAUSED": 9,
    "RECOVERY": 10,
}

# =============================================================================
# Tracking Functions
# =============================================================================


def track_phase_transition(
    from_phase: str,
    to_phase: str,
    duration_seconds: float = 0.0,
    cycle_id: str = "unknown",
) -> None:
    """Track a phase transition in the nomic loop.

    Args:
        from_phase: The phase transitioning from
        to_phase: The phase transitioning to
        duration_seconds: Time spent in the from_phase
        cycle_id: Current cycle identifier
    """
    # Increment transition counter
    NOMIC_PHASE_TRANSITIONS.inc(from_phase=from_phase.lower(), to_phase=to_phase.lower())

    # Update current phase gauge
    phase_value = PHASE_ENCODING.get(to_phase.upper(), -1)
    NOMIC_CURRENT_PHASE.set(phase_value, cycle_id=cycle_id)

    # Record phase duration
    if duration_seconds > 0:
        NOMIC_PHASE_DURATION.observe(duration_seconds, phase=from_phase.lower())

    # Update last transition timestamp
    NOMIC_PHASE_LAST_TRANSITION.set(time.time(), cycle_id=cycle_id)

    logger.debug(f"Nomic metric: {from_phase} -> {to_phase} ({duration_seconds:.1f}s)")


def track_cycle_start(cycle_id: str = "unknown") -> None:
    """Track the start of a nomic cycle.

    Args:
        cycle_id: The cycle identifier
    """
    NOMIC_CYCLES_IN_PROGRESS.inc()
    NOMIC_CURRENT_PHASE.set(PHASE_ENCODING["IDLE"], cycle_id=cycle_id)
    NOMIC_PHASE_LAST_TRANSITION.set(time.time(), cycle_id=cycle_id)


def track_cycle_complete(outcome: str, cycle_id: str = "unknown") -> None:
    """Track completion of a nomic cycle.

    Args:
        outcome: The cycle outcome (success, failure, aborted)
        cycle_id: The cycle identifier
    """
    NOMIC_CYCLES_TOTAL.inc(outcome=outcome.lower())
    NOMIC_CYCLES_IN_PROGRESS.dec()

    # Clear the current phase for this cycle
    NOMIC_CURRENT_PHASE.set(-1, cycle_id=cycle_id)


def track_error(phase: str, error_type: str) -> None:
    """Track an error in the nomic loop.

    Args:
        phase: The phase where the error occurred
        error_type: Type of error (timeout, api_error, validation, etc)
    """
    NOMIC_ERRORS.inc(phase=phase.lower(), error_type=error_type.lower())


def track_recovery_decision(strategy: str) -> None:
    """Track a recovery decision.

    Args:
        strategy: The recovery strategy chosen (retry, skip, rollback, etc)
    """
    NOMIC_RECOVERY_DECISIONS.inc(strategy=strategy.lower())


def track_retry(phase: str) -> None:
    """Track a retry attempt.

    Args:
        phase: The phase being retried
    """
    NOMIC_RETRIES.inc(phase=phase.lower())


def update_circuit_breaker_count(open_count: int) -> None:
    """Update the count of open circuit breakers.

    Args:
        open_count: Number of circuit breakers in open state
    """
    NOMIC_CIRCUIT_BREAKERS_OPEN.set(open_count)


# =============================================================================
# State Machine Integration
# =============================================================================


def nomic_metrics_callback(
    from_state: NomicState,
    to_state: NomicState,
    event: Event,
    duration_seconds: float = 0.0,
    cycle_id: str = "unknown",
) -> None:
    """Callback for state machine transitions to track metrics.

    Register this with the state machine:
        machine.on_transition(nomic_metrics_callback)

    Args:
        from_state: The state transitioning from
        to_state: The state transitioning to
        event: The event that triggered the transition
        duration_seconds: Time spent in from_state
        cycle_id: Current cycle identifier
    """
    track_phase_transition(
        from_phase=from_state.name,
        to_phase=to_state.name,
        duration_seconds=duration_seconds,
        cycle_id=cycle_id,
    )

    # Track terminal states
    if to_state.name == "COMPLETED":
        track_cycle_complete("success", cycle_id)
    elif to_state.name == "FAILED":
        track_cycle_complete("failure", cycle_id)


def create_metrics_callback(cycle_id: str = "unknown"):
    """Create a metrics callback with bound cycle_id.

    This is useful when you want to pre-bind the cycle_id.

    Args:
        cycle_id: The cycle identifier to bind

    Returns:
        A callback function suitable for state machine registration
    """
    state_entry_times: dict[str, float] = {}

    def callback(from_state: NomicState, to_state: NomicState, event: Event) -> None:
        # Calculate duration
        duration = 0.0
        if from_state.name in state_entry_times:
            duration = time.time() - state_entry_times[from_state.name]

        # Record entry time for new state
        state_entry_times[to_state.name] = time.time()

        # Call the main metrics callback
        nomic_metrics_callback(
            from_state=from_state,
            to_state=to_state,
            event=event,
            duration_seconds=duration,
            cycle_id=cycle_id,
        )

    return callback


# =============================================================================
# Metrics Summary
# =============================================================================


def get_nomic_metrics_summary() -> dict[str, Any]:
    """Get a summary of nomic loop metrics.

    Returns:
        Dict with current metric values
    """
    return {
        "cycles_in_progress": NOMIC_CYCLES_IN_PROGRESS.get(),
        "circuit_breakers_open": NOMIC_CIRCUIT_BREAKERS_OPEN.get(),
        "transitions": {labels: value for labels, value in NOMIC_PHASE_TRANSITIONS.collect()},
        "cycles": {
            labels.get("outcome", "unknown"): value
            for labels, value in NOMIC_CYCLES_TOTAL.collect()
        },
        "errors": {
            f"{labels.get('phase', 'unknown')}_{labels.get('error_type', 'unknown')}": value
            for labels, value in NOMIC_ERRORS.collect()
        },
    }


# =============================================================================
# Stuck Phase Detection
# =============================================================================


def check_stuck_phases(
    max_idle_seconds: float = 3600.0,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    """Check for phases that appear stuck.

    A phase is considered stuck if no transition has occurred for
    longer than max_idle_seconds.

    Args:
        max_idle_seconds: Maximum time without transition before considering stuck
        cycle_id: Optional specific cycle to check

    Returns:
        Dict with stuck phase information
    """
    now = time.time()
    stuck_info = {
        "is_stuck": False,
        "stuck_duration_seconds": 0.0,
        "last_transition_timestamp": None,
    }

    # Get last transition timestamps
    for labels, timestamp in NOMIC_PHASE_LAST_TRANSITION.collect():
        if cycle_id and labels.get("cycle_id") != cycle_id:
            continue

        if timestamp > 0:
            idle_duration = now - timestamp
            if idle_duration > max_idle_seconds:
                stuck_info["is_stuck"] = True
                stuck_info["stuck_duration_seconds"] = idle_duration
                stuck_info["last_transition_timestamp"] = timestamp
                break

    return stuck_info


def get_prometheus_metrics() -> NomicMetricCollection:
    """Return the live Nomic metric objects through the observability contract."""
    from aragora.observability.server_metrics.export import NomicMetricCollection

    return NomicMetricCollection(
        counters=(
            NOMIC_PHASE_TRANSITIONS,
            NOMIC_CYCLES_TOTAL,
            NOMIC_ERRORS,
            NOMIC_RECOVERY_DECISIONS,
            NOMIC_RETRIES,
        ),
        gauges=(
            NOMIC_CURRENT_PHASE,
            NOMIC_CYCLES_IN_PROGRESS,
            NOMIC_PHASE_LAST_TRANSITION,
            NOMIC_CIRCUIT_BREAKERS_OPEN,
        ),
        histograms=(NOMIC_PHASE_DURATION,),
    )


def register_prometheus_metrics_provider() -> bool:
    """Register Nomic metrics at an application composition root."""
    try:
        from aragora.observability.server_metrics.export import (
            register_nomic_metrics_provider,
        )
    except ImportError as exc:
        logger.debug("Nomic Prometheus metrics provider is unavailable: %s", exc)
        return False

    register_nomic_metrics_provider(get_prometheus_metrics)
    return True


__all__ = [
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
    # Tracking functions
    "track_phase_transition",
    "track_cycle_start",
    "track_cycle_complete",
    "track_error",
    "track_recovery_decision",
    "track_retry",
    "update_circuit_breaker_count",
    # State machine integration
    "nomic_metrics_callback",
    "create_metrics_callback",
    # Utilities
    "get_nomic_metrics_summary",
    "check_stuck_phases",
    "get_prometheus_metrics",
    "register_prometheus_metrics_provider",
    "PHASE_ENCODING",
]
