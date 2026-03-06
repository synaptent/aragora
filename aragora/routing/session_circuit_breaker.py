"""Session-scoped circuit breaker for OpenRouter pinning.

When a direct provider (Anthropic, OpenAI, Gemini, etc.) fails due to
auth or quota errors, the session circuit breaker permanently marks that
provider as unavailable for the remainder of the process lifetime.
Transient errors (5xx) use a threshold: 3 failures within a sliding
5-minute window before pinning.

This prevents thrashing dead providers and keeps the session on
OpenRouter once a hard failure is detected.

Usage:
    from aragora.routing.session_circuit_breaker import get_session_circuit_breaker

    cb = get_session_circuit_breaker()
    cb.mark_provider_failed("anthropic", reason="401 Unauthorized")

    if not cb.is_provider_available("anthropic"):
        # route through OpenRouter instead
        provider = cb.get_fallback_provider()
"""

from __future__ import annotations

__all__ = [
    "SessionCircuitBreaker",
    "ProviderFailure",
    "get_session_circuit_breaker",
    "reset_session_circuit_breaker",
]

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

# Status codes that cause immediate (permanent) session pinning.
AUTH_FAILURE_CODES = frozenset({401, 403})
QUOTA_FAILURE_CODES = frozenset({429})
PERMANENT_FAILURE_CODES = AUTH_FAILURE_CODES | QUOTA_FAILURE_CODES

# Status codes treated as transient -- require repeated failures to pin.
TRANSIENT_FAILURE_CODES = frozenset({500, 502, 503})

# Transient failure thresholds.
TRANSIENT_FAILURE_THRESHOLD = 3
TRANSIENT_WINDOW_SECONDS = 300.0  # 5 minutes

# OpenRouter is the fallback and should never be pinned as failed.
FALLBACK_PROVIDER = "openrouter"


class FailureCategory(Enum):
    """Classification of provider failure."""

    AUTH = "auth"
    QUOTA = "quota"
    TRANSIENT = "transient"


@dataclass
class ProviderFailure:
    """Record of a provider failure event."""

    provider: str
    status_code: int
    reason: str
    category: FailureCategory
    timestamp: float = field(default_factory=time.monotonic)


class SessionCircuitBreaker:
    """In-memory, session-scoped circuit breaker for provider routing.

    Thread-safe. Resets only when the process restarts.

    Pinning rules:
    - Auth failures (401, 403): immediate permanent pin.
    - Quota failures (429): immediate permanent pin.
    - Transient failures (500, 502, 503): pin after ``TRANSIENT_FAILURE_THRESHOLD``
      failures within ``TRANSIENT_WINDOW_SECONDS``.
    - OpenRouter is never pinned (it is the fallback destination).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Providers permanently pinned as failed.
        self._pinned: dict[str, ProviderFailure] = {}
        # Sliding window of transient failures per provider.
        self._transient_failures: dict[str, list[ProviderFailure]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def mark_provider_failed(
        self,
        provider: str,
        reason: str,
        status_code: int = 0,
    ) -> None:
        """Record a provider failure.

        Auth/quota errors pin the provider immediately. Transient errors
        accumulate and pin only after the threshold is breached.

        Args:
            provider: Provider name (e.g. ``"anthropic"``, ``"openai"``).
            reason: Human-readable failure reason for logging.
            status_code: HTTP status code that triggered the failure.
                If 0, the category is inferred from ``reason`` keywords.
        """
        if provider == FALLBACK_PROVIDER:
            logger.debug(
                "Ignoring failure for fallback provider %s: %s",
                FALLBACK_PROVIDER,
                reason,
            )
            return

        category = self._categorize(status_code, reason)
        failure = ProviderFailure(
            provider=provider,
            status_code=status_code,
            reason=reason,
            category=category,
        )

        with self._lock:
            if provider in self._pinned:
                logger.debug(
                    "Provider %s already pinned as failed, ignoring new failure: %s",
                    provider,
                    reason,
                )
                return

            if category in (FailureCategory.AUTH, FailureCategory.QUOTA):
                self._pinned[provider] = failure
                logger.warning(
                    "Provider %s permanently failed for session (%s): %s",
                    provider,
                    category.value,
                    reason,
                )
                return

            # Transient: accumulate in sliding window.
            window = self._transient_failures.setdefault(provider, [])
            window.append(failure)

            # Prune entries outside the window.
            cutoff = time.monotonic() - TRANSIENT_WINDOW_SECONDS
            window[:] = [f for f in window if f.timestamp >= cutoff]

            if len(window) >= TRANSIENT_FAILURE_THRESHOLD:
                self._pinned[provider] = failure
                logger.warning(
                    "Provider %s pinned after %d transient failures in %.0fs: %s",
                    provider,
                    len(window),
                    TRANSIENT_WINDOW_SECONDS,
                    reason,
                )
                # Clean up transient tracking.
                del self._transient_failures[provider]

    def is_provider_available(self, provider: str) -> bool:
        """Check whether a provider is still usable this session.

        Returns ``True`` if the provider has not been pinned as failed.
        OpenRouter always returns ``True``.
        """
        if provider == FALLBACK_PROVIDER:
            return True
        with self._lock:
            return provider not in self._pinned

    def get_fallback_provider(self) -> str:
        """Return the name of the fallback provider (always ``"openrouter"``)."""
        return FALLBACK_PROVIDER

    def get_session_status(self) -> dict:
        """Return a snapshot of all tracked provider states.

        Returns:
            Dict with keys:

            - ``pinned_providers``: mapping of provider name to failure info.
            - ``transient_failures``: mapping of provider name to current
              failure count in the sliding window.
            - ``fallback_provider``: the fallback provider name.
        """
        with self._lock:
            now = time.monotonic()
            cutoff = now - TRANSIENT_WINDOW_SECONDS

            pinned_info: dict[str, dict] = {}
            for provider, failure in self._pinned.items():
                pinned_info[provider] = {
                    "status_code": failure.status_code,
                    "reason": failure.reason,
                    "category": failure.category.value,
                    "timestamp": failure.timestamp,
                }

            transient_info: dict[str, int] = {}
            for provider, failures in self._transient_failures.items():
                active = [f for f in failures if f.timestamp >= cutoff]
                if active:
                    transient_info[provider] = len(active)

        return {
            "pinned_providers": pinned_info,
            "transient_failures": transient_info,
            "fallback_provider": FALLBACK_PROVIDER,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _categorize(status_code: int, reason: str) -> FailureCategory:
        """Determine failure category from status code and reason text."""
        if status_code in AUTH_FAILURE_CODES:
            return FailureCategory.AUTH
        if status_code in QUOTA_FAILURE_CODES:
            return FailureCategory.QUOTA

        # Keyword-based fallback when status code is ambiguous or zero.
        reason_lower = reason.lower()
        auth_keywords = {"unauthorized", "forbidden", "invalid api key", "expired"}
        quota_keywords = {"quota", "rate limit", "too many requests", "billing", "credit"}
        if any(kw in reason_lower for kw in auth_keywords):
            return FailureCategory.AUTH
        if any(kw in reason_lower for kw in quota_keywords):
            return FailureCategory.QUOTA

        return FailureCategory.TRANSIENT


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------

_session_cb: SessionCircuitBreaker | None = None
_singleton_lock = threading.Lock()


def get_session_circuit_breaker() -> SessionCircuitBreaker:
    """Get or create the process-wide ``SessionCircuitBreaker`` singleton."""
    global _session_cb
    if _session_cb is None:
        with _singleton_lock:
            if _session_cb is None:
                _session_cb = SessionCircuitBreaker()
    return _session_cb


def reset_session_circuit_breaker() -> None:
    """Reset the singleton (primarily for testing)."""
    global _session_cb
    with _singleton_lock:
        _session_cb = None
