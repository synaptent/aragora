"""
Phase recovery and error handling for nomic loop.

Provides structured error recovery with:
- Per-phase retry with exponential backoff
- Phase-specific error classification
- Health metrics tracking
- Automatic rollback triggers
"""

import asyncio
import logging
import os
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)


class PhaseError(Exception):
    """Exception raised when a phase fails."""

    def __init__(
        self,
        phase: str,
        message: str,
        recoverable: bool = True,
        original_error: Exception | None = None,
    ):
        self.phase = phase
        self.recoverable = recoverable
        self.original_error = original_error
        super().__init__(f"[{phase}] {message}")


class PhaseRecovery:
    """
    Structured error recovery for nomic loop phases.

    Features:
    - Per-phase retry with exponential backoff
    - Phase-specific error classification
    - Health metrics tracking
    - Automatic rollback triggers
    """

    # Default retry settings per phase
    PHASE_RETRY_CONFIG = {
        "context": {"max_retries": 2, "base_delay": 5, "critical": False},
        "debate": {"max_retries": 1, "base_delay": 10, "critical": True},
        "design": {"max_retries": 2, "base_delay": 5, "critical": False},
        "implement": {"max_retries": 1, "base_delay": 15, "critical": True},
        "verify": {"max_retries": 3, "base_delay": 5, "critical": False},
        "commit": {"max_retries": 1, "base_delay": 5, "critical": True},
    }

    # Individual phase timeouts (seconds) - complements cycle-level timeout
    # Configurable via environment variables: NOMIC_<PHASE>_TIMEOUT
    PHASE_TIMEOUTS = {
        "context": int(
            os.environ.get("NOMIC_CONTEXT_TIMEOUT", "1200")
        ),  # 20 min (doubled for Codex)
        "debate": int(os.environ.get("NOMIC_DEBATE_TIMEOUT", "1800")),  # 30 min
        "design": int(os.environ.get("NOMIC_DESIGN_TIMEOUT", "900")),  # 15 min
        "implement": int(os.environ.get("NOMIC_IMPLEMENT_TIMEOUT", "2400")),  # 40 min
        "verify": int(os.environ.get("NOMIC_VERIFY_TIMEOUT", "600")),  # 10 min
        "commit": int(os.environ.get("NOMIC_COMMIT_TIMEOUT", "180")),  # 3 min
    }
    # Timeout escalation tuning
    TIMEOUT_ESCALATION_FACTOR = float(os.environ.get("NOMIC_TIMEOUT_ESCALATION", "1.3"))
    TIMEOUT_MAX_MULTIPLIER = float(os.environ.get("NOMIC_TIMEOUT_MAX_MULT", "2.0"))

    # Errors that should NOT be retried
    NON_RETRYABLE_ERRORS = (
        KeyboardInterrupt,
        SystemExit,
        MemoryError,
    )

    # Errors that indicate rate limiting or service issues (should wait longer)
    # Keep in sync with aragora.agents.errors.RATE_LIMIT_PATTERNS
    RATE_LIMIT_PATTERNS = [
        # Rate limiting
        "rate limit",
        "rate_limit",
        "ratelimit",
        "429",
        "too many requests",
        "throttl",
        # Quota/usage limit errors
        "quota exceeded",
        "quota_exceeded",
        "resource exhausted",
        "resource_exhausted",
        "insufficient_quota",
        "limit exceeded",
        "usage_limit",
        "usage limit",
        "limit has been reached",
        # Billing errors
        "billing",
        "credit balance",
        "payment required",
        "purchase credits",
        "402",
        # Capacity/availability errors
        "503",
        "service unavailable",
        "502",
        "bad gateway",
        "overloaded",
        "capacity",
        "temporarily unavailable",
        "try again later",
        "server busy",
        "high demand",
        # API-specific errors
        "model overloaded",
        "model is currently overloaded",
        "engine is currently overloaded",
        # CLI-specific errors
        "argument list too long",
        "broken pipe",
    ]

    def __init__(self, log_func: Callable = print):
        self.log = log_func
        self.phase_health: dict[str, dict] = {}
        self.consecutive_failures: dict[str, int] = {}
        self.current_attempt: dict[str, int] = {}

    def is_retryable(self, error: Exception, phase: str) -> bool:
        """Check if an error should be retried."""
        if isinstance(error, self.NON_RETRYABLE_ERRORS):
            return False

        # Check if phase has retries left
        config = self.PHASE_RETRY_CONFIG.get(phase, {"max_retries": 1})
        failures = self.consecutive_failures.get(phase, 0)

        if failures >= config["max_retries"]:
            return False

        return True

    def get_retry_delay(self, error: Exception, phase: str) -> float:
        """Calculate delay before retry with exponential backoff."""
        config = self.PHASE_RETRY_CONFIG.get(phase, {"base_delay": 5})
        base = config["base_delay"]
        failures = self.consecutive_failures.get(phase, 0)

        # Exponential backoff: base * 2^failures
        delay = base * (2**failures)

        # Check for rate limiting (use longer delay)
        error_str = str(error).lower()
        if any(pattern in error_str for pattern in self.RATE_LIMIT_PATTERNS):
            delay = max(delay, 120)  # Minimum 120s for rate limits
            self.log(f"  [recovery] Rate limit detected, waiting {delay}s")

        return min(delay, 300)  # Cap at 5 minutes

    def get_escalated_timeout(self, phase: str, attempt: int = 0) -> float:
        """
        Calculate escalated timeout for retry attempts.

        Each retry gets more time (up to max multiplier) to handle
        slow but eventually successful operations.
        """
        base_timeout = self.PHASE_TIMEOUTS.get(phase, 600)
        if attempt == 0:
            return base_timeout

        multiplier = min(self.TIMEOUT_ESCALATION_FACTOR**attempt, self.TIMEOUT_MAX_MULTIPLIER)
        return int(base_timeout * multiplier)

    def record_success(self, phase: str) -> None:
        """Record successful phase completion."""
        self.consecutive_failures[phase] = 0
        if phase not in self.phase_health:
            self.phase_health[phase] = {
                "successes": 0,
                "failures": 0,
                "last_error": None,
            }
        self.phase_health[phase]["successes"] += 1

    def record_failure(self, phase: str, error: Exception) -> None:
        """Record phase failure."""
        self.consecutive_failures[phase] = self.consecutive_failures.get(phase, 0) + 1
        if phase not in self.phase_health:
            self.phase_health[phase] = {
                "successes": 0,
                "failures": 0,
                "last_error": None,
            }
        self.phase_health[phase]["failures"] += 1
        self.phase_health[phase]["last_error"] = str(error)[:200]

    def should_trigger_rollback(self, phase: str) -> bool:
        """Check if failures warrant a rollback."""
        config = self.PHASE_RETRY_CONFIG.get(phase, {"critical": False})
        if not config["critical"]:
            return False

        # Rollback if critical phase has consecutive failures
        failures = self.consecutive_failures.get(phase, 0)
        return failures >= 2

    def get_health_report(self) -> dict:
        """Get health metrics for all phases."""
        return {
            "phase_health": self.phase_health,
            "consecutive_failures": self.consecutive_failures,
        }

    async def run_with_recovery(
        self, phase: str, phase_func: Callable, *args, **kwargs
    ) -> tuple[bool, Any]:
        """
        Run a phase function with automatic retry and recovery.

        Returns:
            (success: bool, result: Any or error message)
        """
        config = self.PHASE_RETRY_CONFIG.get(phase, {"max_retries": 1})
        attempts = 0
        self.current_attempt[phase] = 0

        while attempts <= config["max_retries"]:
            try:
                self.current_attempt[phase] = attempts
                result = await phase_func(*args, **kwargs)
                self.record_success(phase)
                self.current_attempt.pop(phase, None)
                return (True, result)

            except self.NON_RETRYABLE_ERRORS:
                raise  # Don't catch these

            except Exception as e:
                attempts += 1
                self.record_failure(phase, e)

                error_msg = f"{type(e).__name__}: {str(e)[:200]}"
                self.log(f"  [recovery] Phase '{phase}' attempt {attempts} failed: {error_msg}")

                if self.is_retryable(e, phase) and attempts <= config["max_retries"]:
                    delay = self.get_retry_delay(e, phase)
                    next_timeout = self.get_escalated_timeout(phase, attempts)
                    self.log(
                        f"  [recovery] Retrying in {delay:.0f}s with {next_timeout}s timeout..."
                    )
                    await asyncio.sleep(delay)
                else:
                    # Log full traceback for debugging
                    logger.error(f"Phase {phase} failed after {attempts} attempts", exc_info=True)

                    if self.should_trigger_rollback(phase):
                        self.log(f"  [recovery] CRITICAL: Phase '{phase}' requires rollback")

                    self.current_attempt.pop(phase, None)
                    return (False, str(e))

        self.current_attempt.pop(phase, None)
        return (False, "Max retries exceeded")
