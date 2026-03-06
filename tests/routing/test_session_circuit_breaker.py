"""Tests for session-scoped circuit breaker with OpenRouter pinning."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from aragora.routing.session_circuit_breaker import (
    FALLBACK_PROVIDER,
    TRANSIENT_FAILURE_THRESHOLD,
    TRANSIENT_WINDOW_SECONDS,
    FailureCategory,
    SessionCircuitBreaker,
    get_session_circuit_breaker,
    reset_session_circuit_breaker,
)


@pytest.fixture()
def cb() -> SessionCircuitBreaker:
    """Fresh circuit breaker for each test."""
    return SessionCircuitBreaker()


# ------------------------------------------------------------------
# Auth failures: immediate permanent pin
# ------------------------------------------------------------------


class TestAuthFailurePinning:
    """Auth errors (401, 403) immediately pin the provider."""

    def test_401_pins_provider(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("anthropic", reason="401 Unauthorized", status_code=401)
        assert not cb.is_provider_available("anthropic")

    def test_403_pins_provider(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("openai", reason="403 Forbidden", status_code=403)
        assert not cb.is_provider_available("openai")

    def test_auth_keyword_pins_without_status_code(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("gemini", reason="Invalid API key", status_code=0)
        assert not cb.is_provider_available("gemini")

    def test_auth_pin_is_permanent(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("anthropic", reason="401 Unauthorized", status_code=401)
        # Even after a long delay the provider stays pinned.
        assert not cb.is_provider_available("anthropic")

    def test_auth_pin_shows_in_session_status(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("anthropic", reason="Expired key", status_code=401)
        status = cb.get_session_status()
        assert "anthropic" in status["pinned_providers"]
        info = status["pinned_providers"]["anthropic"]
        assert info["category"] == "auth"
        assert info["status_code"] == 401


# ------------------------------------------------------------------
# Quota failures: immediate permanent pin
# ------------------------------------------------------------------


class TestQuotaFailurePinning:
    """Quota errors (429) immediately pin the provider."""

    def test_429_pins_provider(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("anthropic", reason="429 Too Many Requests", status_code=429)
        assert not cb.is_provider_available("anthropic")

    def test_quota_keyword_pins_without_status_code(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("openai", reason="Quota exceeded", status_code=0)
        assert not cb.is_provider_available("openai")

    def test_rate_limit_keyword_pins(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("gemini", reason="Rate limit reached", status_code=0)
        assert not cb.is_provider_available("gemini")

    def test_billing_keyword_pins(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed(
            "anthropic", reason="Billing issue: credit exhausted", status_code=0
        )
        assert not cb.is_provider_available("anthropic")

    def test_quota_pin_shows_in_session_status(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("openai", reason="429", status_code=429)
        status = cb.get_session_status()
        info = status["pinned_providers"]["openai"]
        assert info["category"] == "quota"


# ------------------------------------------------------------------
# Transient failures: threshold-based pinning
# ------------------------------------------------------------------


class TestTransientFailurePinning:
    """Transient errors (500, 502, 503) pin only after threshold breached."""

    def test_single_transient_does_not_pin(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("anthropic", reason="500 Internal Server Error", status_code=500)
        assert cb.is_provider_available("anthropic")

    def test_two_transient_does_not_pin(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("anthropic", reason="502 Bad Gateway", status_code=502)
        cb.mark_provider_failed("anthropic", reason="503 Service Unavailable", status_code=503)
        assert cb.is_provider_available("anthropic")

    def test_three_transient_within_window_pins(self, cb: SessionCircuitBreaker) -> None:
        for i in range(TRANSIENT_FAILURE_THRESHOLD):
            cb.mark_provider_failed("anthropic", reason=f"500 error #{i + 1}", status_code=500)
        assert not cb.is_provider_available("anthropic")

    def test_transient_outside_window_does_not_pin(self, cb: SessionCircuitBreaker) -> None:
        """Failures spread over > 5 minutes should not accumulate."""
        # Record 2 failures normally.
        cb.mark_provider_failed("anthropic", reason="500 error #1", status_code=500)
        cb.mark_provider_failed("anthropic", reason="500 error #2", status_code=500)

        # Simulate the third failure arriving after the window expires
        # by patching time.monotonic to jump forward.
        original_monotonic = time.monotonic
        offset = TRANSIENT_WINDOW_SECONDS + 1.0

        def shifted_monotonic() -> float:
            return original_monotonic() + offset

        with patch("time.monotonic", side_effect=shifted_monotonic):
            with patch(
                "aragora.routing.session_circuit_breaker.time.monotonic",
                side_effect=shifted_monotonic,
            ):
                cb.mark_provider_failed("anthropic", reason="500 error #3", status_code=500)

        # The first two should have been pruned, so only 1 failure in window.
        assert cb.is_provider_available("anthropic")

    def test_transient_shows_in_session_status(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("anthropic", reason="500 error", status_code=500)
        status = cb.get_session_status()
        assert "anthropic" not in status["pinned_providers"]
        assert status["transient_failures"]["anthropic"] == 1

    def test_pinned_transient_shows_in_pinned(self, cb: SessionCircuitBreaker) -> None:
        for i in range(TRANSIENT_FAILURE_THRESHOLD):
            cb.mark_provider_failed("anthropic", reason=f"500 #{i + 1}", status_code=500)
        status = cb.get_session_status()
        assert "anthropic" in status["pinned_providers"]
        assert status["pinned_providers"]["anthropic"]["category"] == "transient"
        # Transient tracking should be cleaned up after pinning.
        assert "anthropic" not in status["transient_failures"]


# ------------------------------------------------------------------
# OpenRouter is never pinned (the safety net)
# ------------------------------------------------------------------


class TestOpenRouterNeverPinned:
    """OpenRouter is the fallback and must always remain available."""

    def test_openrouter_auth_failure_ignored(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("openrouter", reason="401 Unauthorized", status_code=401)
        assert cb.is_provider_available("openrouter")

    def test_openrouter_quota_failure_ignored(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("openrouter", reason="429 Rate Limited", status_code=429)
        assert cb.is_provider_available("openrouter")

    def test_openrouter_transient_failure_ignored(self, cb: SessionCircuitBreaker) -> None:
        for _ in range(10):
            cb.mark_provider_failed("openrouter", reason="500 error", status_code=500)
        assert cb.is_provider_available("openrouter")


# ------------------------------------------------------------------
# Fallback provider
# ------------------------------------------------------------------


class TestFallbackProvider:
    """get_fallback_provider always returns 'openrouter'."""

    def test_returns_openrouter(self, cb: SessionCircuitBreaker) -> None:
        assert cb.get_fallback_provider() == "openrouter"

    def test_returns_openrouter_when_all_pinned(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("anthropic", reason="401", status_code=401)
        cb.mark_provider_failed("openai", reason="429", status_code=429)
        cb.mark_provider_failed("gemini", reason="403", status_code=403)
        assert cb.get_fallback_provider() == "openrouter"

    def test_fallback_constant(self) -> None:
        assert FALLBACK_PROVIDER == "openrouter"


# ------------------------------------------------------------------
# Multiple independent providers
# ------------------------------------------------------------------


class TestMultipleProviders:
    """Providers are tracked independently."""

    def test_one_pinned_others_available(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("anthropic", reason="401", status_code=401)
        assert not cb.is_provider_available("anthropic")
        assert cb.is_provider_available("openai")
        assert cb.is_provider_available("gemini")

    def test_multiple_pinned_independently(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("anthropic", reason="401", status_code=401)
        cb.mark_provider_failed("openai", reason="429", status_code=429)
        assert not cb.is_provider_available("anthropic")
        assert not cb.is_provider_available("openai")
        assert cb.is_provider_available("gemini")

    def test_session_status_shows_all_pinned(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("anthropic", reason="401", status_code=401)
        cb.mark_provider_failed("openai", reason="429", status_code=429)
        status = cb.get_session_status()
        assert len(status["pinned_providers"]) == 2
        assert "anthropic" in status["pinned_providers"]
        assert "openai" in status["pinned_providers"]

    def test_duplicate_failure_does_not_double_pin(self, cb: SessionCircuitBreaker) -> None:
        cb.mark_provider_failed("anthropic", reason="401 first", status_code=401)
        cb.mark_provider_failed("anthropic", reason="401 second", status_code=401)
        status = cb.get_session_status()
        # Should still only have one entry with the first reason.
        assert status["pinned_providers"]["anthropic"]["reason"] == "401 first"


# ------------------------------------------------------------------
# Initially-available state
# ------------------------------------------------------------------


class TestInitialState:
    """A fresh circuit breaker has all providers available."""

    def test_unknown_provider_is_available(self, cb: SessionCircuitBreaker) -> None:
        assert cb.is_provider_available("some-new-provider")

    def test_empty_session_status(self, cb: SessionCircuitBreaker) -> None:
        status = cb.get_session_status()
        assert status["pinned_providers"] == {}
        assert status["transient_failures"] == {}
        assert status["fallback_provider"] == "openrouter"


# ------------------------------------------------------------------
# Singleton accessor
# ------------------------------------------------------------------


class TestSingleton:
    """get_session_circuit_breaker returns a process-wide singleton."""

    def test_returns_same_instance(self) -> None:
        reset_session_circuit_breaker()
        try:
            cb1 = get_session_circuit_breaker()
            cb2 = get_session_circuit_breaker()
            assert cb1 is cb2
        finally:
            reset_session_circuit_breaker()

    def test_reset_clears_singleton(self) -> None:
        reset_session_circuit_breaker()
        cb1 = get_session_circuit_breaker()
        reset_session_circuit_breaker()
        cb2 = get_session_circuit_breaker()
        assert cb1 is not cb2


# ------------------------------------------------------------------
# Failure categorization
# ------------------------------------------------------------------


class TestFailureCategorization:
    """_categorize classifies failures correctly."""

    def test_401_is_auth(self) -> None:
        assert SessionCircuitBreaker._categorize(401, "") == FailureCategory.AUTH

    def test_403_is_auth(self) -> None:
        assert SessionCircuitBreaker._categorize(403, "") == FailureCategory.AUTH

    def test_429_is_quota(self) -> None:
        assert SessionCircuitBreaker._categorize(429, "") == FailureCategory.QUOTA

    def test_500_is_transient(self) -> None:
        assert SessionCircuitBreaker._categorize(500, "") == FailureCategory.TRANSIENT

    def test_0_with_auth_keyword_is_auth(self) -> None:
        assert SessionCircuitBreaker._categorize(0, "Unauthorized access") == FailureCategory.AUTH

    def test_0_with_quota_keyword_is_quota(self) -> None:
        assert SessionCircuitBreaker._categorize(0, "Rate limit exceeded") == FailureCategory.QUOTA

    def test_0_with_unknown_reason_is_transient(self) -> None:
        assert SessionCircuitBreaker._categorize(0, "Something broke") == FailureCategory.TRANSIENT
