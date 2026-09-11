"""
Error Recovery Integration Tests.

Tests fault tolerance and recovery mechanisms:
- Circuit breaker state management
- Agent fallback chain activation
- Debate checkpoint and resume
- Concurrent debate failure handling
- Graceful degradation under failure conditions
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    get_circuit_breaker,
    reset_all_circuit_breakers,
    get_circuit_breaker_status,
    get_circuit_breaker_metrics,
    init_circuit_breaker_persistence,
    persist_circuit_breaker,
    load_circuit_breakers,
)
from aragora.agents.fallback import QuotaFallbackMixin, QUOTA_ERROR_KEYWORDS


# =============================================================================
# Circuit Breaker Tests
# =============================================================================


class TestCircuitBreakerBasics:
    """Test basic circuit breaker functionality."""

    def setup_method(self):
        """Reset circuit breakers before each test."""
        reset_all_circuit_breakers()

    def test_circuit_starts_closed(self):
        """New circuit breaker starts in closed state."""
        breaker = CircuitBreaker()
        assert breaker.get_status() == "closed"
        assert breaker.can_proceed()

    def test_circuit_opens_after_threshold_failures(self):
        """Circuit opens after reaching failure threshold."""
        breaker = CircuitBreaker(failure_threshold=3)

        # Record failures up to threshold
        breaker.record_failure()
        assert breaker.get_status() == "closed"

        breaker.record_failure()
        assert breaker.get_status() == "closed"

        breaker.record_failure()
        assert breaker.get_status() == "open"
        assert not breaker.can_proceed()

    def test_circuit_blocks_requests_when_open(self):
        """Open circuit blocks new requests."""
        breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=10)

        # Open the circuit
        breaker.record_failure()
        breaker.record_failure()

        assert not breaker.can_proceed()
        assert breaker.get_status() == "open"

    def test_circuit_closes_after_success(self):
        """Circuit closes after successful request."""
        breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)

        # Open circuit
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.get_status() == "open"

        # Wait for cooldown
        time.sleep(0.15)

        # Record success should close circuit
        breaker.record_success()
        assert breaker.get_status() == "closed"
        assert breaker.can_proceed()

    def test_success_resets_failure_count(self):
        """Success resets the failure counter."""
        breaker = CircuitBreaker(failure_threshold=3)

        breaker.record_failure()
        breaker.record_failure()
        assert breaker.failures == 2

        breaker.record_success()
        assert breaker.failures == 0


# =============================================================================
# Multi-Entity Circuit Breaker Tests
# =============================================================================


class TestMultiEntityCircuitBreaker:
    """Test circuit breaker with multiple entities (agents)."""

    def setup_method(self):
        """Reset circuit breakers before each test."""
        reset_all_circuit_breakers()

    def test_independent_entity_tracking(self):
        """Each entity has independent failure tracking."""
        breaker = CircuitBreaker(failure_threshold=2)

        # Fail agent-1
        breaker.record_failure("agent-1")
        breaker.record_failure("agent-1")

        # agent-1 should be open, agent-2 should be available
        assert not breaker.is_available("agent-1")
        assert breaker.is_available("agent-2")

    def test_filter_available_entities(self):
        """Can filter list to only available entities."""
        breaker = CircuitBreaker(failure_threshold=2)

        # Make agent-2 unavailable
        breaker.record_failure("agent-2")
        breaker.record_failure("agent-2")

        agents = ["agent-1", "agent-2", "agent-3"]
        available = breaker.filter_available_entities(agents)

        assert "agent-1" in available
        assert "agent-2" not in available
        assert "agent-3" in available

    def test_entity_recovery_independent(self):
        """Entities recover independently."""
        breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)

        # Fail both agents
        breaker.record_failure("agent-1")
        breaker.record_failure("agent-1")
        breaker.record_failure("agent-2")
        breaker.record_failure("agent-2")

        # Both should be unavailable
        assert not breaker.is_available("agent-1")
        assert not breaker.is_available("agent-2")

        # Wait for cooldown
        time.sleep(0.15)

        # Recover agent-1 only
        breaker.record_success("agent-1")
        breaker.record_success("agent-1")

        assert breaker.is_available("agent-1")
        # agent-2 is in half-open state after cooldown
        assert breaker.is_available("agent-2")


# =============================================================================
# Circuit Breaker Context Manager Tests
# =============================================================================


class TestCircuitBreakerContextManager:
    """Test async/sync context manager protection."""

    def setup_method(self):
        """Reset circuit breakers before each test."""
        reset_all_circuit_breakers()

    @pytest.mark.asyncio
    async def test_protected_call_success(self):
        """Protected call records success on completion."""
        breaker = CircuitBreaker(failure_threshold=3)

        async with breaker.protected_call("test-agent"):
            pass  # Simulated successful call

        assert breaker.get_status("test-agent") == "closed"

    @pytest.mark.asyncio
    async def test_protected_call_failure(self):
        """Protected call records failure on exception."""
        breaker = CircuitBreaker(failure_threshold=2)

        with pytest.raises(ValueError):
            async with breaker.protected_call("test-agent"):
                raise ValueError("API error")

        # One failure recorded
        assert breaker._failures.get("test-agent") == 1

    @pytest.mark.asyncio
    async def test_protected_call_raises_circuit_open(self):
        """Protected call raises CircuitOpenError when circuit is open."""
        breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)

        # Open the circuit
        breaker.record_failure("test-agent")
        breaker.record_failure("test-agent")

        with pytest.raises(CircuitOpenError) as exc_info:
            async with breaker.protected_call("test-agent"):
                pass

        assert "test-agent" in str(exc_info.value)
        assert exc_info.value.cooldown_remaining > 0

    def test_sync_protected_call(self):
        """Sync context manager works correctly."""
        breaker = CircuitBreaker(failure_threshold=2)

        with breaker.protected_call_sync("sync-agent"):
            pass

        assert breaker.get_status("sync-agent") == "closed"


# =============================================================================
# Global Circuit Breaker Registry Tests
# =============================================================================


class TestCircuitBreakerRegistry:
    """Test global circuit breaker registry."""

    def setup_method(self):
        """Reset circuit breakers before each test."""
        reset_all_circuit_breakers()

    def test_get_circuit_breaker_creates_new(self):
        """get_circuit_breaker creates new breaker if not exists."""
        breaker = get_circuit_breaker("new-service")
        assert breaker is not None
        assert breaker.get_status() == "closed"

    def test_get_circuit_breaker_returns_same(self):
        """get_circuit_breaker returns same instance for same name."""
        breaker1 = get_circuit_breaker("shared-service")
        breaker2 = get_circuit_breaker("shared-service")
        assert breaker1 is breaker2

    def test_get_status_returns_all_breakers(self):
        """get_circuit_breaker_status returns all registered breakers."""
        get_circuit_breaker("service-a")
        get_circuit_breaker("service-b")

        status = get_circuit_breaker_status()

        assert "service-a" in status
        assert "service-b" in status
        assert "_registry_size" in status

    def test_get_metrics_provides_summary(self):
        """get_circuit_breaker_metrics provides health summary."""
        import uuid

        service_name = f"test-metrics-{uuid.uuid4().hex[:8]}"
        breaker = get_circuit_breaker(service_name, failure_threshold=2)
        breaker.record_failure()
        breaker.record_failure()

        metrics = get_circuit_breaker_metrics()

        assert metrics["summary"]["total"] >= 1
        assert metrics["summary"]["open"] >= 1
        assert metrics["health"]["status"] == "degraded"
        # Verify our specific breaker is in the open circuits
        assert service_name in metrics["health"]["open_circuits"]


# =============================================================================
# Circuit Breaker Persistence Tests
# =============================================================================


class TestCircuitBreakerPersistence:
    """Test circuit breaker state persistence."""

    def setup_method(self):
        """Reset circuit breakers before each test."""
        reset_all_circuit_breakers()

    def test_persist_and_load(self):
        """Circuit breaker state survives persistence round-trip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/test_cb.db"
            init_circuit_breaker_persistence(db_path)

            # Create and configure a circuit breaker
            breaker = get_circuit_breaker("persistent-service", failure_threshold=5)
            breaker.record_failure("entity-1")
            breaker.record_failure("entity-1")

            # Persist
            persist_circuit_breaker("persistent-service", breaker)

            # Reset and reload
            reset_all_circuit_breakers()
            loaded = load_circuit_breakers()

            assert loaded >= 1
            # The breaker state should be restored
            reloaded_breaker = get_circuit_breaker("persistent-service")
            assert reloaded_breaker._failures.get("entity-1", 0) == 2


# =============================================================================
# Quota Error Detection Tests
# =============================================================================


class TestQuotaErrorDetection:
    """Test quota/rate limit error detection."""

    def test_429_is_quota_error(self):
        """HTTP 429 is always a quota error."""

        class TestAgent(QuotaFallbackMixin):
            pass

        agent = TestAgent()
        assert agent.is_quota_error(429, "Any message")

    def test_403_with_quota_keyword(self):
        """HTTP 403 with quota keyword is quota error."""

        class TestAgent(QuotaFallbackMixin):
            pass

        agent = TestAgent()
        assert agent.is_quota_error(403, "Quota exceeded for this project")
        assert agent.is_quota_error(403, "Billing issue detected")

    def test_403_without_keyword_is_not_quota(self):
        """HTTP 403 without quota keyword is not quota error."""

        class TestAgent(QuotaFallbackMixin):
            pass

        agent = TestAgent()
        assert not agent.is_quota_error(403, "Access denied")
        assert not agent.is_quota_error(403, "Invalid API key")

    def test_rate_limit_keywords(self):
        """Rate limit keywords in error text are detected."""

        class TestAgent(QuotaFallbackMixin):
            pass

        agent = TestAgent()
        assert agent.is_quota_error(500, "rate limit exceeded")
        assert agent.is_quota_error(500, "too many requests")
        assert agent.is_quota_error(500, "resource exhausted")


# =============================================================================
# Agent Fallback Chain Tests
# =============================================================================


class TestAgentFallbackChain:
    """Test agent fallback chain activation."""

    def test_fallback_model_mapping(self):
        """get_fallback_model() resolves the current model through the
        catalog/upgrade map (frontier-model-refresh, 2026-09-04 review fix
        round 1, item 3), not the (vestigial) OPENROUTER_MODEL_MAP class
        attribute: "gpt-4o" is a legacy OpenAI spelling that upgrades to
        the current frontier; a truly unresolvable model falls back to
        DEFAULT_FALLBACK_MODEL."""

        class TestAgent(QuotaFallbackMixin):
            OPENROUTER_MODEL_MAP = {
                "gpt-4o": "openai/gpt-4o",
                "claude-3": "anthropic/claude-3",
            }
            DEFAULT_FALLBACK_MODEL = "meta-llama/llama-3"

        agent = TestAgent()
        agent.model = "gpt-4o"
        # Terra, not Astra: the GPT-4 line is value-tier by price
        # (gpt-4o listed at $2.50/$10), so it preserves tier rather than
        # over-paying for the $10/$50 flagship -- round-4 re-review of
        # finding C-P3 on #9989.
        assert agent.get_fallback_model() == "openai/gpt-5.6-terra"

        agent.model = "unknown-model"
        assert agent.get_fallback_model() == "meta-llama/llama-3"

    @patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"})
    def test_fallback_agent_creation(self):
        """Fallback agent is created when key is available."""
        from aragora.agents.fallback import QuotaFallbackMixin

        class TestAgent(QuotaFallbackMixin):
            name = "test-agent"
            model = "test-model"
            DEFAULT_FALLBACK_MODEL = "anthropic/claude-sonnet-4"

        agent = TestAgent()

        # Mock the OpenRouterAgent import in api_agents module
        with patch("aragora.agents.api_agents.OpenRouterAgent") as MockAgent:
            MockAgent.return_value = MagicMock()
            fallback = agent._get_openrouter_fallback()
            assert fallback is not None

    @patch.dict("os.environ", {}, clear=True)
    def test_no_fallback_without_key(self):
        """No fallback agent without OPENROUTER_API_KEY."""
        # Remove the key if present
        import os

        os.environ.pop("OPENROUTER_API_KEY", None)

        class TestAgent(QuotaFallbackMixin):
            name = "test-agent"
            model = "test-model"

        agent = TestAgent()
        fallback = agent._get_openrouter_fallback()
        assert fallback is None


# =============================================================================
# Concurrent Failure Handling Tests
# =============================================================================


class TestConcurrentFailureHandling:
    """Test handling of concurrent failures."""

    def setup_method(self):
        """Reset circuit breakers before each test."""
        reset_all_circuit_breakers()

    @pytest.mark.asyncio
    async def test_multiple_agents_some_fail(self):
        """Some agents fail while others complete successfully."""
        breaker = CircuitBreaker(failure_threshold=2)

        results = []
        errors = []

        async def agent_task(name: str, should_fail: bool):
            try:
                if not breaker.is_available(name):
                    raise CircuitOpenError(name, 60.0)

                if should_fail:
                    breaker.record_failure(name)
                    raise RuntimeError(f"{name} failed")

                breaker.record_success(name)
                return f"{name} completed"
            except Exception as e:
                errors.append(e)
                return None

        # Run 5 concurrent tasks, 2 should fail
        tasks = [
            agent_task("agent-1", should_fail=False),
            agent_task("agent-2", should_fail=True),
            agent_task("agent-3", should_fail=False),
            agent_task("agent-4", should_fail=True),
            agent_task("agent-5", should_fail=False),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 3 succeeded, 2 failed
        successful = [r for r in results if r is not None and not isinstance(r, Exception)]
        assert len(successful) == 3
        assert len(errors) == 2

    @pytest.mark.asyncio
    async def test_circuit_opens_under_concurrent_failures(self):
        """Circuit opens under concurrent failure load."""
        breaker = CircuitBreaker(failure_threshold=3)

        async def failing_task(name: str):
            breaker.record_failure(name)
            await asyncio.sleep(0.01)  # Small delay
            breaker.record_failure(name)

        # Concurrent failures for same entity
        await asyncio.gather(
            failing_task("shared-agent"),
            failing_task("shared-agent"),
        )

        # Should exceed threshold and open
        assert not breaker.is_available("shared-agent")


# =============================================================================
# Graceful Degradation Tests
# =============================================================================


class TestGracefulDegradation:
    """Test graceful degradation under failure conditions."""

    def setup_method(self):
        """Reset circuit breakers before each test."""
        reset_all_circuit_breakers()

    def test_partial_availability(self):
        """System remains partially available when some agents fail."""
        breaker = CircuitBreaker(failure_threshold=2)

        agents = ["claude", "gpt", "gemini", "mistral"]

        # Fail some agents
        breaker.record_failure("claude")
        breaker.record_failure("claude")
        breaker.record_failure("gpt")
        breaker.record_failure("gpt")

        available = breaker.filter_available_entities(agents)
        assert len(available) == 2  # gemini and mistral still available
        assert "gemini" in available
        assert "mistral" in available

    def test_health_status_reflects_degradation(self):
        """Health status accurately reflects system degradation."""
        import uuid

        # Use unique names to avoid conflicts with other tests
        service_name = f"health-degradation-{uuid.uuid4().hex[:8]}"

        # Create breaker and open it
        breaker1 = get_circuit_breaker(service_name, failure_threshold=2)

        # Open the circuit
        breaker1.record_failure()
        breaker1.record_failure()

        metrics = get_circuit_breaker_metrics()
        assert metrics["health"]["status"] == "degraded"
        assert service_name in str(metrics["health"]["open_circuits"])

    def test_recovery_from_degraded_state(self):
        """System recovers from degraded state."""
        breaker = get_circuit_breaker(
            "recovering-service", failure_threshold=2, cooldown_seconds=0.1
        )

        # Open circuit
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.get_status() == "open"

        # Wait for cooldown
        time.sleep(0.15)

        # Verify recovery
        assert breaker.can_proceed()
        breaker.record_success()
        assert breaker.get_status() == "closed"


# =============================================================================
# Full Integration Flow Tests
# =============================================================================


class TestFullErrorRecoveryFlow:
    """Test complete error recovery workflows."""

    def setup_method(self):
        """Reset circuit breakers before each test."""
        reset_all_circuit_breakers()

    @pytest.mark.asyncio
    async def test_failure_fallback_recovery_cycle(self):
        """Complete cycle: failure → fallback → recovery."""
        primary_breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)

        # Phase 1: Primary service fails
        primary_breaker.record_failure("primary")
        primary_breaker.record_failure("primary")
        assert not primary_breaker.is_available("primary")

        # Phase 2: Use fallback
        fallback_results = []
        if not primary_breaker.is_available("primary"):
            fallback_results.append("used fallback")

        assert len(fallback_results) == 1

        # Phase 3: Wait for recovery window
        await asyncio.sleep(0.15)

        # Phase 4: Primary recovers
        assert primary_breaker.is_available("primary")  # Half-open
        primary_breaker.record_success("primary")
        primary_breaker.record_success("primary")
        assert primary_breaker.get_status("primary") == "closed"

    def test_cascade_failure_prevention(self):
        """Circuit breakers prevent cascade failures."""
        # Create dependent services with unique names to avoid interference
        db_breaker = get_circuit_breaker("cascade-database", failure_threshold=2)
        cache_breaker = get_circuit_breaker("cascade-cache", failure_threshold=2)
        api_breaker = get_circuit_breaker("cascade-api", failure_threshold=2)

        # Database fails
        db_breaker.record_failure()
        db_breaker.record_failure()

        # Other services should still be available
        assert not db_breaker.can_proceed()
        assert cache_breaker.can_proceed()
        assert api_breaker.can_proceed()

        # Check that database is open but others are not
        assert db_breaker.get_status() == "open"
        assert cache_breaker.get_status() == "closed"
        assert api_breaker.get_status() == "closed"

        # Check metrics shows at least one open circuit
        metrics = get_circuit_breaker_metrics()
        assert metrics["summary"]["open"] >= 1
        assert "cascade-database" in str(metrics["health"]["open_circuits"])
