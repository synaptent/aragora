"""
Integration tests for agent fallback cascade.

Tests the full flow from primary agent failure through fallback chain,
including CircuitBreaker integration and metrics tracking.
"""

import asyncio
import pytest
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Optional

from aragora.agents.fallback import (
    AgentFallbackChain,
    AllProvidersExhaustedError,
    FallbackMetrics,
    QuotaFallbackMixin,
    QUOTA_ERROR_KEYWORDS,
)
from aragora.resilience import CircuitBreaker


# =============================================================================
# Test Fixtures
# =============================================================================


@dataclass
class MockAgent:
    """Mock agent for testing fallback behavior."""

    name: str
    should_fail: bool = False
    fail_count: int = 0  # Number of times to fail before succeeding
    failure_message: str = "Agent failed"
    response: str = "Generated response"
    _call_count: int = 0

    async def generate(self, prompt: str, context: list | None = None) -> str:
        self._call_count += 1
        if self.should_fail or self._call_count <= self.fail_count:
            raise RuntimeError(self.failure_message)
        return f"{self.name}: {self.response}"

    async def generate_stream(self, prompt: str, context: list | None = None):
        self._call_count += 1
        if self.should_fail or self._call_count <= self.fail_count:
            raise RuntimeError(self.failure_message)
        for word in self.response.split():
            yield word


@pytest.fixture
def circuit_breaker():
    """Create a circuit breaker with low thresholds for testing."""
    return CircuitBreaker(
        failure_threshold=2,
        cooldown_seconds=1.0,
        half_open_success_threshold=1,
    )


@pytest.fixture
def fallback_chain(circuit_breaker):
    """Create a fallback chain with test providers."""
    chain = AgentFallbackChain(
        providers=["primary", "secondary", "tertiary"],
        circuit_breaker=circuit_breaker,
    )

    # Register provider factories
    chain.register_provider("primary", lambda: MockAgent(name="primary"))
    chain.register_provider("secondary", lambda: MockAgent(name="secondary"))
    chain.register_provider("tertiary", lambda: MockAgent(name="tertiary"))

    return chain


# =============================================================================
# FallbackMetrics Tests
# =============================================================================


class TestFallbackMetrics:
    """Tests for FallbackMetrics tracking."""

    def test_record_primary_success(self):
        """Primary success should increment counters."""
        metrics = FallbackMetrics()
        metrics.record_primary_attempt(success=True)

        assert metrics.primary_attempts == 1
        assert metrics.primary_successes == 1
        assert metrics.total_failures == 0

    def test_record_primary_failure(self):
        """Primary failure should increment failure counter."""
        metrics = FallbackMetrics()
        metrics.record_primary_attempt(success=False)

        assert metrics.primary_attempts == 1
        assert metrics.primary_successes == 0
        assert metrics.total_failures == 1

    def test_record_fallback_attempt(self):
        """Fallback attempt should track provider usage."""
        metrics = FallbackMetrics()
        metrics.record_fallback_attempt("openrouter", success=True)

        assert metrics.fallback_attempts == 1
        assert metrics.fallback_successes == 1
        assert metrics.fallback_providers_used["openrouter"] == 1
        assert metrics.last_fallback_time > 0

    def test_fallback_rate_calculation(self):
        """Fallback rate should be fallbacks / total attempts."""
        metrics = FallbackMetrics()
        metrics.record_primary_attempt(success=True)
        metrics.record_primary_attempt(success=True)
        metrics.record_primary_attempt(success=False)
        metrics.record_fallback_attempt("openrouter", success=True)

        # 1 fallback out of 4 total = 25%
        assert metrics.fallback_rate == 0.25

    def test_success_rate_calculation(self):
        """Success rate should be successes / total attempts."""
        metrics = FallbackMetrics()
        metrics.record_primary_attempt(success=True)  # +1 success
        metrics.record_primary_attempt(success=False)  # +0 success
        metrics.record_fallback_attempt("openrouter", success=True)  # +1 success

        # 2 successes out of 3 attempts
        assert abs(metrics.success_rate - 0.666) < 0.01

    def test_zero_attempts_rates(self):
        """Rates should be 0 when no attempts made."""
        metrics = FallbackMetrics()
        assert metrics.fallback_rate == 0.0
        assert metrics.success_rate == 0.0


# =============================================================================
# AgentFallbackChain Tests
# =============================================================================


class TestAgentFallbackChain:
    """Tests for AgentFallbackChain behavior."""

    @pytest.mark.asyncio
    async def test_primary_success(self, fallback_chain):
        """Should use primary when it succeeds."""
        result = await fallback_chain.generate("Test prompt")

        assert "primary" in result
        assert fallback_chain.metrics.primary_successes == 1
        assert fallback_chain.metrics.fallback_attempts == 0

    @pytest.mark.asyncio
    async def test_fallback_on_primary_failure(self, circuit_breaker):
        """Should fallback when primary fails."""
        chain = AgentFallbackChain(
            providers=["primary", "secondary"],
            circuit_breaker=circuit_breaker,
        )

        # Primary fails, secondary succeeds
        chain.register_provider(
            "primary",
            lambda: MockAgent(name="primary", should_fail=True, failure_message="Primary failed"),
        )
        chain.register_provider("secondary", lambda: MockAgent(name="secondary"))

        result = await chain.generate("Test prompt")

        assert "secondary" in result
        assert chain.metrics.primary_attempts == 1
        assert chain.metrics.primary_successes == 0
        assert chain.metrics.fallback_attempts == 1
        assert chain.metrics.fallback_successes == 1

    @pytest.mark.asyncio
    async def test_fallback_emits_prometheus_metrics(self, circuit_breaker):
        """Fallback should emit activation and success telemetry."""
        chain = AgentFallbackChain(
            providers=["primary", "secondary"],
            circuit_breaker=circuit_breaker,
        )
        chain.register_provider("primary", lambda: MockAgent(name="primary", should_fail=True))
        chain.register_provider("secondary", lambda: MockAgent(name="secondary"))

        with (
            patch("aragora.agents.fallback.record_fallback_activation") as activation,
            patch("aragora.agents.fallback.record_fallback_success") as success,
        ):
            result = await chain.generate("Test prompt")

        assert "secondary" in result
        activation.assert_called_once()
        assert activation.call_args.kwargs["primary_agent"] == "primary"
        assert activation.call_args.kwargs["fallback_provider"] == "secondary"
        assert activation.call_args.kwargs["error_type"] in {"error", "rate_limit"}

        success.assert_called_once()
        assert success.call_args.args[0] == "secondary"
        assert success.call_args.kwargs["success"] is True

    @pytest.mark.asyncio
    async def test_multi_level_fallback(self, circuit_breaker):
        """Should cascade through multiple fallbacks."""
        chain = AgentFallbackChain(
            providers=["primary", "secondary", "tertiary"],
            circuit_breaker=circuit_breaker,
        )

        # Primary and secondary fail, tertiary succeeds
        chain.register_provider("primary", lambda: MockAgent(name="primary", should_fail=True))
        chain.register_provider("secondary", lambda: MockAgent(name="secondary", should_fail=True))
        chain.register_provider("tertiary", lambda: MockAgent(name="tertiary"))

        result = await chain.generate("Test prompt")

        assert "tertiary" in result
        # Should have tried all three
        assert chain.metrics.primary_attempts == 1
        assert chain.metrics.fallback_attempts == 2  # secondary and tertiary

    @pytest.mark.asyncio
    async def test_all_providers_exhausted(self, circuit_breaker):
        """Should raise AllProvidersExhaustedError when all fail."""
        chain = AgentFallbackChain(
            providers=["primary", "secondary"],
            circuit_breaker=circuit_breaker,
        )

        chain.register_provider(
            "primary",
            lambda: MockAgent(name="primary", should_fail=True, failure_message="Primary error"),
        )
        chain.register_provider(
            "secondary",
            lambda: MockAgent(
                name="secondary", should_fail=True, failure_message="Secondary error"
            ),
        )

        with pytest.raises(AllProvidersExhaustedError) as exc_info:
            await chain.generate("Test prompt")

        assert "primary" in exc_info.value.providers
        assert "secondary" in exc_info.value.providers
        assert exc_info.value.last_error is not None

    @pytest.mark.asyncio
    async def test_circuit_breaker_skips_tripped_providers(self, circuit_breaker):
        """Should skip providers that are circuit-broken."""
        chain = AgentFallbackChain(
            providers=["primary", "secondary"],
            circuit_breaker=circuit_breaker,
        )

        # Trip the circuit breaker for primary
        circuit_breaker.record_failure("primary")
        circuit_breaker.record_failure("primary")  # Now tripped (threshold=2)

        chain.register_provider("primary", lambda: MockAgent(name="primary"))
        chain.register_provider("secondary", lambda: MockAgent(name="secondary"))

        result = await chain.generate("Test prompt")

        # Should skip primary and use secondary directly
        assert "secondary" in result
        # Primary should not have been attempted
        assert chain.metrics.primary_attempts == 0
        assert chain.metrics.fallback_attempts == 1

    @pytest.mark.asyncio
    async def test_circuit_breaker_recovery(self, circuit_breaker):
        """Circuit breaker should allow retry after cooldown."""
        chain = AgentFallbackChain(
            providers=["primary", "secondary"],
            circuit_breaker=circuit_breaker,
        )

        # Trip the circuit breaker for primary
        circuit_breaker.record_failure("primary")
        circuit_breaker.record_failure("primary")

        # Wait for cooldown (1 second)
        await asyncio.sleep(1.1)

        chain.register_provider("primary", lambda: MockAgent(name="primary"))
        chain.register_provider("secondary", lambda: MockAgent(name="secondary"))

        result = await chain.generate("Test prompt")

        # Primary should be tried again after cooldown
        assert "primary" in result

    @pytest.mark.asyncio
    async def test_get_available_providers(self, circuit_breaker):
        """get_available_providers should exclude tripped providers."""
        chain = AgentFallbackChain(
            providers=["primary", "secondary", "tertiary"],
            circuit_breaker=circuit_breaker,
        )

        # Initially all available
        available = chain.get_available_providers()
        assert available == ["primary", "secondary", "tertiary"]

        # Trip primary
        circuit_breaker.record_failure("primary")
        circuit_breaker.record_failure("primary")

        available = chain.get_available_providers()
        assert "primary" not in available
        assert "secondary" in available
        assert "tertiary" in available

    @pytest.mark.asyncio
    async def test_stream_fallback(self, circuit_breaker):
        """Streaming should also support fallback."""
        chain = AgentFallbackChain(
            providers=["primary", "secondary"],
            circuit_breaker=circuit_breaker,
        )

        chain.register_provider("primary", lambda: MockAgent(name="primary", should_fail=True))
        chain.register_provider(
            "secondary", lambda: MockAgent(name="secondary", response="token1 token2 token3")
        )

        tokens = []
        async for token in chain.generate_stream("Test prompt"):
            tokens.append(token)

        assert len(tokens) == 3
        assert tokens == ["token1", "token2", "token3"]

    @pytest.mark.asyncio
    async def test_get_status(self, fallback_chain):
        """get_status should return chain status."""
        await fallback_chain.generate("Test prompt")

        status = fallback_chain.get_status()

        assert status["providers"] == ["primary", "secondary", "tertiary"]
        assert "primary" in status["available_providers"]
        assert "metrics" in status
        assert status["metrics"]["primary_attempts"] == 1

    def test_reset_metrics(self, fallback_chain):
        """reset_metrics should clear all counters."""
        fallback_chain.metrics.record_primary_attempt(success=True)
        fallback_chain.metrics.record_fallback_attempt("secondary", success=True)

        fallback_chain.reset_metrics()

        assert fallback_chain.metrics.primary_attempts == 0
        assert fallback_chain.metrics.fallback_attempts == 0

    @pytest.mark.asyncio
    async def test_rate_limit_error_detection(self, circuit_breaker):
        """Should detect and log rate limit errors."""
        chain = AgentFallbackChain(
            providers=["primary", "secondary"],
            circuit_breaker=circuit_breaker,
        )

        # Primary fails with rate limit error
        chain.register_provider(
            "primary",
            lambda: MockAgent(
                name="primary", should_fail=True, failure_message="Error: rate limit exceeded"
            ),
        )
        chain.register_provider("secondary", lambda: MockAgent(name="secondary"))

        result = await chain.generate("Test prompt")

        assert "secondary" in result


# =============================================================================
# QuotaFallbackMixin Tests
# =============================================================================


class TestQuotaFallbackMixin:
    """Tests for QuotaFallbackMixin behavior."""

    def test_is_quota_error_429(self):
        """429 status should be detected as quota error."""

        class TestAgent(QuotaFallbackMixin):
            pass

        agent = TestAgent()
        assert agent.is_quota_error(429, "Rate limit exceeded")
        assert agent.is_quota_error(429, "")  # 429 is always quota error

    def test_is_quota_error_403_with_quota_text(self):
        """403 with quota keywords should be detected."""

        class TestAgent(QuotaFallbackMixin):
            pass

        agent = TestAgent()
        assert agent.is_quota_error(403, "Quota exceeded for this billing period")
        assert agent.is_quota_error(403, "Resource quota has been exceeded")
        assert not agent.is_quota_error(403, "Forbidden - invalid API key")

    def test_is_quota_error_keyword_detection(self):
        """Should detect quota-related keywords in error text."""

        class TestAgent(QuotaFallbackMixin):
            pass

        agent = TestAgent()

        # Should detect various quota-related messages
        assert agent.is_quota_error(500, "rate_limit exceeded")
        assert agent.is_quota_error(500, "Too many requests")
        assert agent.is_quota_error(500, "Insufficient credits")
        assert agent.is_quota_error(500, "Resource exhausted")

        # Should not detect unrelated errors
        assert not agent.is_quota_error(500, "Internal server error")
        assert not agent.is_quota_error(400, "Invalid request")

    def test_get_fallback_model_with_mapping(self):
        """get_fallback_model() resolves the current model through the
        catalog/upgrade map (frontier-model-refresh, 2026-09-04 review fix
        round 1, item 3), not the (vestigial) OPENROUTER_MODEL_MAP class
        attribute: "gpt-4" is a legacy OpenAI spelling that upgrades to the
        current frontier."""

        class TestAgent(QuotaFallbackMixin):
            OPENROUTER_MODEL_MAP = {
                "gpt-4": "openai/gpt-4",
                "gpt-3.5-turbo": "openai/gpt-3.5-turbo",
            }
            DEFAULT_FALLBACK_MODEL = "openai/gpt-4o"

            def __init__(self, model: str):
                self.model = model

        agent = TestAgent(model="gpt-4")
        # The GPT-4 line preserves its value tier (round-4 re-review of
        # finding C-P3 on #9989), so it resolves to Terra, not the flagship.
        assert agent.get_fallback_model() == "openai/gpt-5.6-terra"

        agent = TestAgent(model="unknown-model")
        assert agent.get_fallback_model() == "openai/gpt-4o"

    @pytest.mark.asyncio
    async def test_fallback_generate_no_key(self):
        """Should return None if OPENROUTER_API_KEY not set."""

        class TestAgent(QuotaFallbackMixin):
            name = "test"
            enable_fallback = True

        agent = TestAgent()

        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "aragora.config.get_api_key",
                side_effect=KeyError("OPENROUTER_API_KEY"),
            ),
        ):
            # Clear cached fallback agent so it re-checks the key
            agent._fallback_agent = None
            result = await agent.fallback_generate("Test prompt")
            assert result is None

    @pytest.mark.asyncio
    async def test_fallback_generate_disabled(self):
        """Should return None if fallback is disabled."""

        class TestAgent(QuotaFallbackMixin):
            name = "test"
            enable_fallback = False

        agent = TestAgent()

        # Even with key, should not fallback
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            result = await agent.fallback_generate("Test prompt")
            assert result is None

    @pytest.mark.asyncio
    async def test_fallback_generate_emits_metrics(self):
        """Fallback generate should emit activation and success metrics."""

        class DummyAgent(QuotaFallbackMixin):
            name = "primary"
            enable_fallback = True

            def __init__(self, fallback_agent):
                self._fallback_agent = fallback_agent

            def _get_cached_fallback_agent(self):
                return self._fallback_agent

        fallback = AsyncMock()
        fallback.generate = AsyncMock(return_value="fallback response")

        agent = DummyAgent(fallback)

        with (
            patch("aragora.agents.fallback.record_fallback_activation") as activation,
            patch("aragora.agents.fallback.record_fallback_success") as success,
        ):
            result = await agent.fallback_generate("Test prompt", status_code=429)

        assert result == "fallback response"
        activation.assert_called_once_with(
            primary_agent="primary",
            fallback_provider="openrouter",
            error_type="rate_limit",
        )
        success.assert_called_once()
        assert success.call_args.args[0] == "openrouter"
        assert success.call_args.kwargs["success"] is True

    @pytest.mark.asyncio
    async def test_fallback_stream_emits_metrics(self):
        """Fallback stream should emit activation and success metrics."""

        class DummyAgent(QuotaFallbackMixin):
            name = "primary"
            enable_fallback = True

            def __init__(self, fallback_agent):
                self._fallback_agent = fallback_agent

            def _get_cached_fallback_agent(self):
                return self._fallback_agent

        async def fallback_stream(*args, **kwargs):
            yield "hello"

        fallback = MagicMock()
        fallback.generate_stream = fallback_stream

        agent = DummyAgent(fallback)

        with (
            patch("aragora.agents.fallback.record_fallback_activation") as activation,
            patch("aragora.agents.fallback.record_fallback_success") as success,
        ):
            tokens = [token async for token in agent.fallback_generate_stream("Test prompt")]

        assert tokens == ["hello"]
        activation.assert_called_once_with(
            primary_agent="primary",
            fallback_provider="openrouter",
            error_type="quota",
        )
        success.assert_called_once()
        assert success.call_args.args[0] == "openrouter"
        assert success.call_args.kwargs["success"] is True


# =============================================================================
# CircuitBreaker Integration Tests
# =============================================================================


class TestCircuitBreakerIntegration:
    """Tests for CircuitBreaker integration with fallback chain."""

    def test_circuit_breaker_tracks_failures(self, circuit_breaker):
        """Circuit breaker should track failures per provider."""
        circuit_breaker.record_failure("provider-a")
        circuit_breaker.record_failure("provider-b")
        circuit_breaker.record_failure("provider-b")

        # provider-a: 1 failure, still available
        assert circuit_breaker.is_available("provider-a")

        # provider-b: 2 failures, tripped (threshold=2)
        assert not circuit_breaker.is_available("provider-b")

    def test_circuit_breaker_recovery_on_success(self, circuit_breaker):
        """Success should reset failure count."""
        circuit_breaker.record_failure("provider")
        circuit_breaker.record_success("provider")

        # Failure count should be reset
        assert circuit_breaker.is_available("provider")

        # Need full threshold to trip again
        circuit_breaker.record_failure("provider")
        assert circuit_breaker.is_available("provider")

    @pytest.mark.asyncio
    async def test_full_fallback_flow_with_circuit_breaker(self, circuit_breaker):
        """Full integration: failures trip breaker, skip provider on next call."""
        chain = AgentFallbackChain(
            providers=["flaky", "stable"],
            circuit_breaker=circuit_breaker,
        )

        # Flaky agent fails first 3 times, then succeeds
        flaky_agent = MockAgent(name="flaky", fail_count=3)
        stable_agent = MockAgent(name="stable")

        chain.register_provider("flaky", lambda: flaky_agent)
        chain.register_provider("stable", lambda: stable_agent)

        # First call: flaky fails, falls back to stable
        result1 = await chain.generate("Prompt 1")
        assert "stable" in result1

        # Second call: flaky fails again, circuit trips, falls back to stable
        result2 = await chain.generate("Prompt 2")
        assert "stable" in result2

        # Third call: flaky is circuit-broken, goes directly to stable
        result3 = await chain.generate("Prompt 3")
        assert "stable" in result3
        # Flaky should only have been called twice (tripped after 2nd failure)

    @pytest.mark.asyncio
    async def test_half_open_state(self):
        """Circuit breaker should try half-open after cooldown."""
        cb = CircuitBreaker(
            failure_threshold=2,
            cooldown_seconds=0.1,  # Fast cooldown for testing
            half_open_success_threshold=1,
        )

        # Trip the circuit
        cb.record_failure("provider")
        cb.record_failure("provider")
        assert not cb.is_available("provider")

        # Wait for cooldown
        await asyncio.sleep(0.15)

        # Should be in half-open state, allowing trial request
        assert cb.is_available("provider")

        # Success closes the circuit fully
        cb.record_success("provider")
        assert cb.is_available("provider")


# =============================================================================
# Full Integration Scenarios
# =============================================================================


class TestFullIntegrationScenarios:
    """End-to-end integration test scenarios."""

    @pytest.mark.asyncio
    async def test_graceful_degradation_scenario(self):
        """Scenario: Primary overloaded, secondary down, tertiary serves traffic."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)

        chain = AgentFallbackChain(
            providers=["premium", "standard", "fallback"],
            circuit_breaker=cb,
        )

        # Premium: rate limited (will fail)
        chain.register_provider(
            "premium",
            lambda: MockAgent(
                name="premium", should_fail=True, failure_message="429: Rate limit exceeded"
            ),
        )

        # Standard: server error (will fail)
        chain.register_provider(
            "standard",
            lambda: MockAgent(
                name="standard", should_fail=True, failure_message="500: Internal server error"
            ),
        )

        # Fallback: working
        chain.register_provider("fallback", lambda: MockAgent(name="fallback"))

        # Make request - should cascade to fallback
        result = await chain.generate("Important request")
        assert "fallback" in result

        # Check metrics reflect the cascade
        status = chain.get_status()
        assert status["metrics"]["primary_attempts"] == 1
        assert status["metrics"]["fallback_attempts"] == 2

    @pytest.mark.asyncio
    async def test_recovery_after_outage(self):
        """Scenario: Primary recovers after being circuit-broken."""
        cb = CircuitBreaker(
            failure_threshold=2,
            cooldown_seconds=0.2,
            half_open_success_threshold=1,
        )

        chain = AgentFallbackChain(
            providers=["primary", "backup"],
            circuit_breaker=cb,
        )

        # Primary starts failing
        primary_agent = MockAgent(name="primary", fail_count=3)
        backup_agent = MockAgent(name="backup")

        chain.register_provider("primary", lambda: primary_agent)
        chain.register_provider("backup", lambda: backup_agent)

        # First two calls fail primary, trip circuit
        await chain.generate("Request 1")
        await chain.generate("Request 2")

        # Primary is now circuit-broken
        assert not cb.is_available("primary")

        # Wait for cooldown
        await asyncio.sleep(0.3)

        # Primary should be tried again (half-open)
        # Reset call count so primary succeeds now
        primary_agent._call_count = 4  # Past fail_count threshold

        result = await chain.generate("Request 3")

        # Primary should be back online
        assert "primary" in result
        assert cb.is_available("primary")

    @pytest.mark.asyncio
    async def test_metrics_accumulation_over_session(self):
        """Metrics should accumulate correctly over multiple requests."""
        cb = CircuitBreaker(failure_threshold=5)

        chain = AgentFallbackChain(
            providers=["main", "alt"],
            circuit_breaker=cb,
        )

        # Main agent: alternates between success and failure
        main_agent = MockAgent(name="main", fail_count=0)
        alt_agent = MockAgent(name="alt")

        chain.register_provider("main", lambda: main_agent)
        chain.register_provider("alt", lambda: alt_agent)

        # Make 5 successful requests
        for _ in range(5):
            await chain.generate("Request")

        assert chain.metrics.primary_attempts == 5
        assert chain.metrics.primary_successes == 5
        assert chain.metrics.fallback_attempts == 0

        # Now make main fail
        main_agent.should_fail = True

        # Make 3 more requests (all fallback)
        for _ in range(3):
            await chain.generate("Request")

        assert chain.metrics.primary_attempts == 8  # 5 + 3
        assert chain.metrics.primary_successes == 5  # Still 5
        assert chain.metrics.fallback_attempts == 3
        assert chain.metrics.fallback_successes == 3

        # Check rates
        assert chain.metrics.fallback_rate == 3 / 11  # 3 fallbacks / 11 total
        assert chain.metrics.success_rate == 8 / 11  # 8 successes / 11 total


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_no_providers_registered(self):
        """Should raise error if no providers are registered."""
        chain = AgentFallbackChain(providers=["missing"])

        with pytest.raises(AllProvidersExhaustedError):
            await chain.generate("Test")

    @pytest.mark.asyncio
    async def test_provider_factory_raises(self):
        """Should handle provider factory that raises exception."""
        cb = CircuitBreaker()
        chain = AgentFallbackChain(
            providers=["broken", "working"],
            circuit_breaker=cb,
        )

        def broken_factory():
            raise RuntimeError("Failed to create agent")

        chain.register_provider("broken", broken_factory)
        chain.register_provider("working", lambda: MockAgent(name="working"))

        # Should skip broken factory and use working provider
        result = await chain.generate("Test")
        assert "working" in result

    @pytest.mark.asyncio
    async def test_concurrent_requests(self, fallback_chain):
        """Should handle concurrent requests correctly."""
        # Make 10 concurrent requests
        tasks = [fallback_chain.generate(f"Request {i}") for i in range(10)]
        results = await asyncio.gather(*tasks)

        # All should succeed
        assert len(results) == 10
        assert all("primary" in r for r in results)
        assert fallback_chain.metrics.primary_attempts == 10

    @pytest.mark.asyncio
    async def test_empty_provider_list(self):
        """Should handle empty provider list."""
        chain = AgentFallbackChain(providers=[])

        with pytest.raises(AllProvidersExhaustedError) as exc_info:
            await chain.generate("Test")

        assert exc_info.value.providers == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
