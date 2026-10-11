"""
Nomic Loop Error Recovery System.

Provides structured error handling and recovery strategies for the
nomic loop state machine. Includes circuit breakers, exponential backoff,
and intelligent recovery decisions.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any

from .events import Event
from .states import NomicState, StateContext, get_state_config

logger = logging.getLogger(__name__)


class RecoveryStrategy(Enum):
    """Strategies for recovering from errors."""

    RETRY = auto()  # Retry the same state
    SKIP = auto()  # Skip to next state
    ROLLBACK = auto()  # Rollback to previous state
    RESTART = auto()  # Restart from beginning
    PAUSE = auto()  # Pause and wait for human
    FAIL = auto()  # Mark as failed, stop


@dataclass
class RecoveryDecision:
    """A decision on how to recover from an error."""

    strategy: RecoveryStrategy
    target_state: NomicState | None = None
    delay_seconds: float = 0
    reason: str = ""
    requires_human: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.name,
            "target_state": self.target_state.name if self.target_state else None,
            "delay_seconds": self.delay_seconds,
            "reason": self.reason,
            "requires_human": self.requires_human,
        }


class CircuitBreaker:
    """
    Circuit breaker for agent/service protection.

    Tracks failures and opens the circuit (blocks calls) when
    failure threshold is exceeded. Automatically closes after
    a reset period.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        reset_timeout_seconds: int = 300,
    ):
        """
        Initialize circuit breaker.

        Args:
            name: Identifier for this circuit
            failure_threshold: Failures before opening circuit
            reset_timeout_seconds: Time before attempting reset
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds

        self._failures = 0
        self._last_failure_time: float | None = None
        self._state = "closed"  # closed, open, half-open

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking calls)."""
        if self._state == "closed":
            return False

        if self._state == "open":
            # Check if reset timeout has passed
            if self._last_failure_time:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.reset_timeout_seconds:
                    self._state = "half-open"
                    return False
            return True

        return False  # half-open allows one call

    def record_success(self) -> None:
        """Record a successful call."""
        self._failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        """Record a failed call."""
        self._failures += 1
        self._last_failure_time = time.time()

        if self._failures >= self.failure_threshold:
            self._state = "open"
            logger.warning(
                "Circuit breaker '%s' opened after %s failures", self.name, self._failures
            )

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self._failures = 0
        self._state = "closed"
        self._last_failure_time = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self._state,
            "failures": self._failures,
            "failure_threshold": self.failure_threshold,
            "last_failure": self._last_failure_time,
        }


class CircuitBreakerRegistry:
    """Registry of circuit breakers for agents and services."""

    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 3,
        reset_timeout: int = 300,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                reset_timeout_seconds=reset_timeout,
            )
        return self._breakers[name]

    def get(self, name: str) -> CircuitBreaker | None:
        """Get a circuit breaker by name."""
        return self._breakers.get(name)

    def all_open(self) -> list[str]:
        """Get names of all open circuit breakers."""
        return [name for name, cb in self._breakers.items() if cb.is_open]

    def reset_all(self) -> None:
        """Reset all circuit breakers."""
        for cb in self._breakers.values():
            cb.reset()

    def to_dict(self) -> dict[str, Any]:
        return {name: cb.to_dict() for name, cb in self._breakers.items()}


def calculate_backoff(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 300.0,
    jitter: bool = True,
) -> float:
    """
    Calculate exponential backoff delay.

    Args:
        attempt: The attempt number (1-based)
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        jitter: Whether to add random jitter

    Returns:
        Delay in seconds
    """
    import random

    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)

    if jitter:
        # Add up to 25% jitter
        delay *= 1 + random.uniform(-0.25, 0.25)  # noqa: S311 -- retry jitter

    return delay


class RecoveryManager:
    """
    Manages error recovery for the nomic loop.

    Analyzes errors and decides on recovery strategies based on:
    - Error type and severity
    - Number of retries already attempted
    - Circuit breaker states
    - State criticality
    """

    def __init__(self, circuit_breakers: CircuitBreakerRegistry | None = None):
        """
        Initialize recovery manager.

        Args:
            circuit_breakers: Registry of circuit breakers
        """
        self.circuit_breakers = circuit_breakers or CircuitBreakerRegistry()
        self._recovery_history: list[dict[str, Any]] = []

    def decide_recovery(
        self,
        state: NomicState,
        error: Exception,
        context: StateContext,
    ) -> RecoveryDecision:
        """
        Decide how to recover from an error.

        Args:
            state: The state where the error occurred
            error: The exception that was raised
            context: The current state context

        Returns:
            A RecoveryDecision with the strategy to use
        """
        state_config = get_state_config(state)
        retry_count = context.retry_counts.get(state.name, 0)
        error_type = type(error).__name__

        # Check circuit breakers
        open_circuits = self.circuit_breakers.all_open()
        if open_circuits:
            logger.warning("Open circuits: %s", open_circuits)

        # Classify error severity
        is_transient = self._is_transient_error(error)
        is_critical = state_config.is_critical

        # Decision logic
        decision = self._make_decision(
            state=state,
            error=error,
            error_type=error_type,
            retry_count=retry_count,
            max_retries=state_config.max_retries,
            is_transient=is_transient,
            is_critical=is_critical,
            open_circuits=open_circuits,
        )

        # Record decision
        self._recovery_history.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "state": state.name,
                "error_type": error_type,
                "retry_count": retry_count,
                "decision": decision.to_dict(),
            }
        )

        return decision

    def _is_transient_error(self, error: Exception) -> bool:
        """Determine if an error is transient (likely to succeed on retry)."""
        transient_types = (
            TimeoutError,
            ConnectionError,
            asyncio.TimeoutError,
        )
        transient_messages = (
            "rate limit",
            "timeout",
            "connection reset",
            "temporary",
            "retry",
            "503",
            "429",
        )

        if isinstance(error, transient_types):
            return True

        error_str = str(error).lower()
        return any(msg in error_str for msg in transient_messages)

    def _make_decision(
        self,
        state: NomicState,
        error: Exception,
        error_type: str,
        retry_count: int,
        max_retries: int,
        is_transient: bool,
        is_critical: bool,
        open_circuits: list[str],
    ) -> RecoveryDecision:
        """Make the actual recovery decision."""

        # If too many circuits are open, pause for human intervention
        if len(open_circuits) >= 2:
            return RecoveryDecision(
                strategy=RecoveryStrategy.PAUSE,
                reason=f"Multiple circuit breakers open: {open_circuits}",
                requires_human=True,
            )

        # Transient errors: retry with backoff
        if is_transient and retry_count < max_retries:
            delay = calculate_backoff(retry_count + 1)
            return RecoveryDecision(
                strategy=RecoveryStrategy.RETRY,
                target_state=state,
                delay_seconds=delay,
                reason=f"Transient error, retry {retry_count + 1}/{max_retries}",
            )

        # Non-critical states: try to skip
        if not is_critical and state not in (NomicState.CONTEXT, NomicState.DEBATE):
            next_state = self._get_skip_target(state)
            if next_state:
                return RecoveryDecision(
                    strategy=RecoveryStrategy.SKIP,
                    target_state=next_state,
                    reason=f"Skipping {state.name} after {retry_count} retries",
                )

        # Critical states with retries left: retry
        if retry_count < max_retries:
            delay = calculate_backoff(retry_count + 1, base_delay=5.0)
            return RecoveryDecision(
                strategy=RecoveryStrategy.RETRY,
                target_state=state,
                delay_seconds=delay,
                reason=f"Critical state, retry {retry_count + 1}/{max_retries}",
            )

        # Critical states exhausted: fail
        if is_critical:
            return RecoveryDecision(
                strategy=RecoveryStrategy.FAIL,
                reason=f"Critical state {state.name} failed after {retry_count} retries",
            )

        # Default: pause for human
        return RecoveryDecision(
            strategy=RecoveryStrategy.PAUSE,
            reason=f"Unexpected error in {state.name}: {error_type}",
            requires_human=True,
        )

    def _get_skip_target(self, state: NomicState) -> NomicState | None:
        """Get the target state when skipping."""
        skip_map = {
            NomicState.DESIGN: NomicState.IMPLEMENT,
            NomicState.IMPLEMENT: NomicState.VERIFY,
            NomicState.VERIFY: NomicState.COMMIT,
            NomicState.COMMIT: NomicState.COMPLETED,
        }
        return skip_map.get(state)

    def get_history(self) -> list[dict[str, Any]]:
        """Get recovery decision history."""
        return self._recovery_history

    def clear_history(self) -> None:
        """Clear recovery history."""
        self._recovery_history = []


async def recovery_handler(
    context: StateContext,
    event: Event,
    recovery_manager: RecoveryManager,
) -> tuple[NomicState, dict[str, Any]]:
    """
    Handler for the RECOVERY state.

    Analyzes the error and decides on recovery strategy.

    Args:
        context: The state context
        event: The event that triggered recovery
        recovery_manager: The recovery manager

    Returns:
        Tuple of (next_state, result_data)
    """
    # Get error info from event
    error_msg = event.error_message or "Unknown error"
    error_type = event.error_type or "Exception"

    # Create a synthetic error for analysis
    class SyntheticError(Exception):
        pass

    error = SyntheticError(error_msg)
    error.__class__.__name__ = error_type

    # Get the state where the error occurred
    failed_state = context.previous_state or NomicState.CONTEXT

    # Decide recovery strategy
    decision = recovery_manager.decide_recovery(
        state=failed_state,
        error=error,
        context=context,
    )

    logger.info("Recovery decision: %s -> %s", decision.strategy.name, decision.target_state)

    # Apply delay if needed
    if decision.delay_seconds > 0:
        logger.info("Waiting %.1fs before recovery", decision.delay_seconds)
        await asyncio.sleep(decision.delay_seconds)

    # Determine next state based on strategy
    if decision.strategy == RecoveryStrategy.RETRY:
        next_state = decision.target_state or failed_state

    elif decision.strategy == RecoveryStrategy.SKIP:
        next_state = decision.target_state or NomicState.COMPLETED

    elif decision.strategy == RecoveryStrategy.ROLLBACK:
        # Rollback to start of current cycle
        next_state = NomicState.CONTEXT

    elif decision.strategy == RecoveryStrategy.RESTART:
        next_state = NomicState.IDLE

    elif decision.strategy == RecoveryStrategy.PAUSE:
        next_state = NomicState.PAUSED

    elif decision.strategy == RecoveryStrategy.FAIL:
        next_state = NomicState.FAILED

    else:
        next_state = NomicState.FAILED

    return next_state, {
        "decision": decision.to_dict(),
        "original_error": error_msg,
        "recovered_from": failed_state.name,
    }
