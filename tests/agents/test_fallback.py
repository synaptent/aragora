"""
Tests for quota detection and fallback utilities.

Tests the fallback module functionality including:
- QuotaFallbackMixin for quota error detection
- Multi-provider fallback chain (OpenRouter -> other providers with valid API keys)
- Content-policy error detection (non-retryable)
- FallbackMetrics for tracking fallback chain behavior
- AgentFallbackChain for multi-provider sequencing
- Error handling (AllProvidersExhaustedError, FallbackTimeoutError)
- Local LLM provider detection
"""

from __future__ import annotations

import os
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.agents.fallback import QuotaFallbackMixin


# =============================================================================
# QUOTA_ERROR_KEYWORDS Tests
# =============================================================================


class TestQuotaErrorKeywords:
    """Test QUOTA_ERROR_KEYWORDS constant."""

    def test_keywords_is_frozenset(self):
        """Test keywords is a frozenset."""
        from aragora.agents.fallback import QUOTA_ERROR_KEYWORDS

        assert isinstance(QUOTA_ERROR_KEYWORDS, frozenset)

    def test_keywords_contains_rate_limit(self):
        """Test keywords contains rate limit variants."""
        from aragora.agents.fallback import QUOTA_ERROR_KEYWORDS

        assert "rate limit" in QUOTA_ERROR_KEYWORDS
        assert "rate_limit" in QUOTA_ERROR_KEYWORDS
        assert "too many requests" in QUOTA_ERROR_KEYWORDS

    def test_keywords_contains_quota(self):
        """Test keywords contains quota variants."""
        from aragora.agents.fallback import QUOTA_ERROR_KEYWORDS

        assert "quota" in QUOTA_ERROR_KEYWORDS
        assert "exceeded" in QUOTA_ERROR_KEYWORDS
        assert "resource exhausted" in QUOTA_ERROR_KEYWORDS

    def test_keywords_contains_billing(self):
        """Test keywords contains billing variants."""
        from aragora.agents.fallback import QUOTA_ERROR_KEYWORDS

        assert "billing" in QUOTA_ERROR_KEYWORDS
        assert "credit balance" in QUOTA_ERROR_KEYWORDS
        assert "insufficient" in QUOTA_ERROR_KEYWORDS


# =============================================================================
# QuotaFallbackMixin Tests
# =============================================================================


class MockAgentWithMixin(QuotaFallbackMixin):
    """Mock agent class using QuotaFallbackMixin.

    Really inherits the mixin rather than binding one method onto a bare
    class: ``get_fallback_model`` now calls a sibling method on ``self``
    (the stranded-map warning), so a partial graft would only be testing
    the graft.
    """

    OPENROUTER_MODEL_MAP = {
        "gpt-4o": "openai/gpt-4o",
        "claude-3-opus": "anthropic/claude-3-opus",
    }
    DEFAULT_FALLBACK_MODEL = "anthropic/claude-sonnet-4"

    def __init__(self, name: str = "test", model: str = "gpt-4o", enable_fallback: bool = True):
        self.name = name
        self.model = model
        self.enable_fallback = enable_fallback
        self.role = "proposer"
        self.timeout = 120
        self.system_prompt = None
        self._fallback_agent = None


class TestQuotaFallbackMixin:
    """Test QuotaFallbackMixin functionality."""

    def test_get_fallback_model_with_mapping(self):
        """get_fallback_model() resolves the current model through the
        catalog/upgrade map (frontier-model-refresh, 2026-09-04 review fix
        round 1, item 3), not the (vestigial) OPENROUTER_MODEL_MAP class
        attribute: "gpt-4o" is a legacy OpenAI spelling that upgrades to
        the current frontier."""
        agent = MockAgentWithMixin(model="gpt-4o")

        result = agent.get_fallback_model()

        # Terra, not Astra: the GPT-4 line is value-tier by price
        # (gpt-4o listed at $2.50/$10), so it preserves tier rather than
        # over-paying for the $10/$50 flagship -- round-4 re-review of
        # finding C-P3 on #9989.
        assert result == "openai/gpt-5.6-terra"

    def test_get_fallback_model_for_haiku_45_uses_its_own_slug(self):
        """2026-09-05 merge-gate finding C-P3 on #9989.

        ``claude-haiku-4-5-20251001`` was in the pre-refresh Anthropic model
        map but had no catalog row, so the fallback fell through to the
        agent's DEFAULT_FALLBACK_MODEL -- Opus 5, a ~5x-priced flagship --
        while every other legacy Claude spelling upgraded correctly. Now that
        it is cataloged, the fallback is its OWN OpenRouter slug.
        """
        for spelling in ("claude-haiku-4-5-20251001", "claude-haiku-4-5", "claude-haiku-4.5"):
            agent = MockAgentWithMixin(model=spelling)
            assert agent.get_fallback_model() == "anthropic/claude-haiku-4.5", spelling

    def test_get_fallback_model_uses_default(self):
        """Test getting fallback model falls back to default."""
        agent = MockAgentWithMixin(model="unknown-model")

        result = agent.get_fallback_model()

        assert result == "anthropic/claude-sonnet-4"

    def test_stranded_openrouter_model_map_warns_once_per_class(self, caplog) -> None:
        """A subclass that still defines OPENROUTER_MODEL_MAP silently lost
        its mapping at the catalog-first refresh. It now gets exactly one
        WARNING -- not silence, and not one per fallback activation
        (finding C-P3 on #9989)."""
        import logging

        from aragora.agents import fallback as fallback_mod

        key = f"{MockAgentWithMixin.__module__}.{MockAgentWithMixin.__qualname__}"
        was_warned = key in fallback_mod._WARNED_STRANDED_MODEL_MAPS
        fallback_mod._WARNED_STRANDED_MODEL_MAPS.discard(key)
        try:
            with caplog.at_level(logging.WARNING, logger="aragora.agents.fallback"):
                for _ in range(3):
                    assert (
                        MockAgentWithMixin(model="gpt-4o").get_fallback_model()
                        == "openai/gpt-5.6-terra"
                    )
            warnings = [
                r.getMessage() for r in caplog.records if "OPENROUTER_MODEL_MAP" in r.getMessage()
            ]
            assert len(warnings) == 1, warnings
            assert "ignored" in warnings[0]
            assert "get_fallback_model" in warnings[0]
            assert key in warnings[0]
        finally:
            if not was_warned:
                fallback_mod._WARNED_STRANDED_MODEL_MAPS.discard(key)

    def test_empty_openrouter_model_map_does_not_warn(self, caplog) -> None:
        """The base class's empty default is the normal case, not a mistake:
        every in-repo agent would otherwise warn on every fallback."""
        import logging

        class _NoMapAgent(QuotaFallbackMixin):
            DEFAULT_FALLBACK_MODEL = "anthropic/claude-sonnet-4"

            def __init__(self) -> None:
                self.model = "gpt-4o"

        with caplog.at_level(logging.WARNING, logger="aragora.agents.fallback"):
            _NoMapAgent().get_fallback_model()
        assert not [r for r in caplog.records if "OPENROUTER_MODEL_MAP" in r.getMessage()]

    def test_is_quota_error_429(self):
        """Test 429 status is detected as quota error."""
        from aragora.agents.fallback import QuotaFallbackMixin

        agent = MockAgentWithMixin()
        agent.is_quota_error = QuotaFallbackMixin.is_quota_error.__get__(agent, MockAgentWithMixin)

        assert agent.is_quota_error(429, "") is True

    def test_is_quota_error_timeout_codes(self):
        """Test timeout status codes are detected."""
        from aragora.agents.fallback import QuotaFallbackMixin

        agent = MockAgentWithMixin()
        agent.is_quota_error = QuotaFallbackMixin.is_quota_error.__get__(agent, MockAgentWithMixin)

        assert agent.is_quota_error(408, "") is True  # Request Timeout
        assert agent.is_quota_error(504, "") is True  # Gateway Timeout
        assert agent.is_quota_error(524, "") is True  # Cloudflare timeout

    def test_is_quota_error_403_with_quota_keyword(self):
        """Test 403 with quota keyword is detected."""
        from aragora.agents.fallback import QuotaFallbackMixin

        agent = MockAgentWithMixin()
        agent.is_quota_error = QuotaFallbackMixin.is_quota_error.__get__(agent, MockAgentWithMixin)

        assert agent.is_quota_error(403, "Quota exceeded for this project") is True
        assert agent.is_quota_error(403, "Permission denied") is False

    def test_is_quota_error_400_with_billing_keyword(self):
        """Test 400 with billing keyword is detected."""
        from aragora.agents.fallback import QuotaFallbackMixin

        agent = MockAgentWithMixin()
        agent.is_quota_error = QuotaFallbackMixin.is_quota_error.__get__(agent, MockAgentWithMixin)

        assert agent.is_quota_error(400, "Credit balance is too low") is True
        assert agent.is_quota_error(400, "Invalid request") is False

    def test_is_quota_error_timeout_in_text(self):
        """Test timeout keyword in error text is detected."""
        from aragora.agents.fallback import QuotaFallbackMixin

        agent = MockAgentWithMixin()
        agent.is_quota_error = QuotaFallbackMixin.is_quota_error.__get__(agent, MockAgentWithMixin)

        assert agent.is_quota_error(500, "Request timed out") is True
        assert agent.is_quota_error(500, "Connection timeout") is True


# =============================================================================
# FallbackMetrics Tests
# =============================================================================


class TestFallbackMetrics:
    """Test FallbackMetrics dataclass."""

    def test_metrics_initialization(self):
        """Test metrics initializes with zeros."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()

        assert metrics.primary_attempts == 0
        assert metrics.primary_successes == 0
        assert metrics.fallback_attempts == 0
        assert metrics.fallback_successes == 0
        assert metrics.total_failures == 0

    def test_record_primary_attempt_success(self):
        """Test recording successful primary attempt."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()
        metrics.record_primary_attempt(success=True)

        assert metrics.primary_attempts == 1
        assert metrics.primary_successes == 1
        assert metrics.total_failures == 0

    def test_record_primary_attempt_failure(self):
        """Test recording failed primary attempt."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()
        metrics.record_primary_attempt(success=False)

        assert metrics.primary_attempts == 1
        assert metrics.primary_successes == 0
        assert metrics.total_failures == 1

    def test_record_fallback_attempt_success(self):
        """Test recording successful fallback attempt."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()
        metrics.record_fallback_attempt("openrouter", success=True)

        assert metrics.fallback_attempts == 1
        assert metrics.fallback_successes == 1
        assert metrics.fallback_providers_used == {"openrouter": 1}

    def test_record_fallback_attempt_failure(self):
        """Test recording failed fallback attempt."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()
        metrics.record_fallback_attempt("openrouter", success=False)

        assert metrics.fallback_attempts == 1
        assert metrics.fallback_successes == 0
        assert metrics.total_failures == 1

    def test_fallback_rate_calculation(self):
        """Test fallback rate calculation."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()
        metrics.primary_attempts = 8
        metrics.fallback_attempts = 2

        assert metrics.fallback_rate == 0.2  # 2/10

    def test_fallback_rate_zero_attempts(self):
        """Test fallback rate with zero attempts."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()

        assert metrics.fallback_rate == 0.0

    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()
        metrics.primary_attempts = 10
        metrics.primary_successes = 7
        metrics.fallback_attempts = 3
        metrics.fallback_successes = 2

        # Total successes: 7 + 2 = 9
        # Total attempts: 10 + 3 = 13
        expected_rate = 9 / 13
        assert abs(metrics.success_rate - expected_rate) < 0.001

    def test_success_rate_zero_attempts(self):
        """Test success rate with zero attempts."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()

        assert metrics.success_rate == 0.0


# =============================================================================
# Exception Tests
# =============================================================================


class TestAllProvidersExhaustedError:
    """Test AllProvidersExhaustedError exception."""

    def test_error_with_providers(self):
        """Test error with provider list."""
        from aragora.agents.fallback import AllProvidersExhaustedError

        error = AllProvidersExhaustedError(["openai", "openrouter", "anthropic"])

        assert error.providers == ["openai", "openrouter", "anthropic"]
        assert "openai" in str(error)
        assert "openrouter" in str(error)

    def test_error_with_last_error(self):
        """Test error with last error."""
        from aragora.agents.fallback import AllProvidersExhaustedError

        last_error = RuntimeError("API error")
        error = AllProvidersExhaustedError(["openai"], last_error=last_error)

        assert error.last_error is last_error
        assert "API error" in str(error)


class TestFallbackTimeoutError:
    """Test FallbackTimeoutError exception."""

    def test_error_attributes(self):
        """Test error stores attributes correctly."""
        from aragora.agents.fallback import FallbackTimeoutError

        error = FallbackTimeoutError(elapsed=45.5, limit=30.0, tried=["openai", "openrouter"])

        assert error.elapsed == 45.5
        assert error.limit == 30.0
        assert error.tried_providers == ["openai", "openrouter"]

    def test_error_message(self):
        """Test error message format."""
        from aragora.agents.fallback import FallbackTimeoutError

        error = FallbackTimeoutError(elapsed=45.5, limit=30.0, tried=["openai", "openrouter"])

        assert "45.5s" in str(error)
        assert "30" in str(error)
        assert "openai" in str(error)


# =============================================================================
# AgentFallbackChain Tests
# =============================================================================


class TestAgentFallbackChainInit:
    """Test AgentFallbackChain initialization."""

    def test_init_minimal(self):
        """Test minimal initialization."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["openai", "openrouter"])

        assert chain.providers == ["openai", "openrouter"]
        assert chain.max_retries == AgentFallbackChain.DEFAULT_MAX_RETRIES
        assert chain.max_fallback_time == AgentFallbackChain.DEFAULT_MAX_FALLBACK_TIME

    def test_init_with_custom_limits(self):
        """Test initialization with custom limits."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(
            providers=["openai"],
            max_retries=3,
            max_fallback_time=60.0,
        )

        assert chain.max_retries == 3
        assert chain.max_fallback_time == 60.0

    def test_init_with_circuit_breaker(self):
        """Test initialization with circuit breaker."""
        from aragora.agents.fallback import AgentFallbackChain
        from aragora.resilience import CircuitBreaker

        cb = CircuitBreaker(name="test", failure_threshold=3)
        chain = AgentFallbackChain(providers=["openai"], circuit_breaker=cb)

        assert chain.circuit_breaker is cb


class TestAgentFallbackChainProviders:
    """Test AgentFallbackChain provider management."""

    def test_register_provider(self):
        """Test registering a provider factory."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["openai"])

        mock_factory = MagicMock(return_value=MagicMock())
        chain.register_provider("openai", mock_factory)

        assert "openai" in chain._provider_factories

    def test_get_agent_from_factory(self):
        """Test getting agent from registered factory."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["openai"])

        mock_agent = MagicMock()
        mock_factory = MagicMock(return_value=mock_agent)
        chain.register_provider("openai", mock_factory)

        result = chain._get_agent("openai")

        assert result is mock_agent
        mock_factory.assert_called_once()

    def test_get_agent_caches_result(self):
        """Test agent is cached after first creation."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["openai"])

        mock_agent = MagicMock()
        mock_factory = MagicMock(return_value=mock_agent)
        chain.register_provider("openai", mock_factory)

        # Get agent twice
        chain._get_agent("openai")
        result = chain._get_agent("openai")

        # Factory should only be called once
        assert mock_factory.call_count == 1
        assert result is mock_agent

    def test_get_agent_returns_instance_directly(self):
        """Test agent instance is returned directly."""
        from aragora.agents.fallback import AgentFallbackChain

        mock_agent = MagicMock()
        mock_agent.name = "direct-agent"

        chain = AgentFallbackChain(providers=[mock_agent])

        result = chain._get_agent(mock_agent)

        assert result is mock_agent

    def test_provider_key_for_string(self):
        """Test provider key for string provider."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["openai"])

        assert chain._provider_key("openai") == "openai"

    def test_provider_key_for_agent(self):
        """Test provider key for agent instance."""
        from aragora.agents.fallback import AgentFallbackChain

        mock_agent = MagicMock()
        mock_agent.name = "my-agent"

        chain = AgentFallbackChain(providers=[mock_agent])

        assert chain._provider_key(mock_agent) == "my-agent"


class TestAgentFallbackChainAvailability:
    """Test provider availability checking."""

    def test_get_available_providers_without_circuit_breaker(self):
        """Test all providers available without circuit breaker."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["openai", "openrouter"])

        available = chain.get_available_providers()

        assert available == ["openai", "openrouter"]

    def test_is_available_without_circuit_breaker(self):
        """Test provider is available without circuit breaker."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["openai"])

        assert chain._is_available("openai") is True


class TestAgentFallbackChainGenerate:
    """Test generate method."""

    @pytest.mark.asyncio
    async def test_generate_success_first_provider(self):
        """Test successful generation with first provider."""
        from aragora.agents.fallback import AgentFallbackChain

        mock_agent = MagicMock()
        mock_agent.name = "openai"
        mock_agent.generate = AsyncMock(return_value="Response from OpenAI")

        chain = AgentFallbackChain(providers=[mock_agent])

        result = await chain.generate("Test prompt")

        assert result == "Response from OpenAI"
        mock_agent.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_fallback_on_failure(self):
        """Test fallback when primary fails."""
        from aragora.agents.fallback import AgentFallbackChain

        primary = MagicMock()
        primary.name = "openai"
        primary.generate = AsyncMock(side_effect=RuntimeError("API error"))

        fallback = MagicMock()
        fallback.name = "openrouter"
        fallback.generate = AsyncMock(return_value="Response from fallback")

        chain = AgentFallbackChain(providers=[primary, fallback])

        result = await chain.generate("Test prompt")

        assert result == "Response from fallback"
        primary.generate.assert_called_once()
        fallback.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_all_providers_exhausted(self):
        """Test error when all providers fail."""
        from aragora.agents.fallback import AgentFallbackChain, AllProvidersExhaustedError

        agent1 = MagicMock()
        agent1.name = "openai"
        agent1.generate = AsyncMock(side_effect=RuntimeError("Error 1"))

        agent2 = MagicMock()
        agent2.name = "openrouter"
        agent2.generate = AsyncMock(side_effect=RuntimeError("Error 2"))

        chain = AgentFallbackChain(providers=[agent1, agent2])

        with pytest.raises(AllProvidersExhaustedError) as exc_info:
            await chain.generate("Test prompt")

        assert "openai" in exc_info.value.providers
        assert "openrouter" in exc_info.value.providers

    @pytest.mark.asyncio
    async def test_generate_respects_max_retries(self):
        """Test generate respects max_retries limit."""
        from aragora.agents.fallback import AgentFallbackChain

        agents = []
        for i in range(5):
            agent = MagicMock()
            agent.name = f"agent-{i}"
            agent.generate = AsyncMock(side_effect=RuntimeError(f"Error {i}"))
            agents.append(agent)

        chain = AgentFallbackChain(providers=agents, max_retries=2)

        with pytest.raises(Exception):
            await chain.generate("Test prompt")

        # Only first 2 agents should be tried
        agents[0].generate.assert_called_once()
        agents[1].generate.assert_called_once()
        agents[2].generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_records_metrics(self):
        """Test generate records metrics correctly."""
        from aragora.agents.fallback import AgentFallbackChain

        primary = MagicMock()
        primary.name = "openai"
        primary.generate = AsyncMock(side_effect=RuntimeError("API error"))

        fallback = MagicMock()
        fallback.name = "openrouter"
        fallback.generate = AsyncMock(return_value="Response")

        chain = AgentFallbackChain(providers=[primary, fallback])

        await chain.generate("Test prompt")

        assert chain.metrics.primary_attempts == 1
        assert chain.metrics.primary_successes == 0
        assert chain.metrics.fallback_attempts == 1
        assert chain.metrics.fallback_successes == 1


class TestAgentFallbackChainStatus:
    """Test status and metrics methods."""

    def test_get_status(self):
        """Test get_status returns expected structure."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(
            providers=["openai", "openrouter"],
            max_retries=3,
            max_fallback_time=60.0,
        )

        status = chain.get_status()

        assert "providers" in status
        assert "available_providers" in status
        assert "limits" in status
        assert "metrics" in status
        assert status["limits"]["max_retries"] == 3
        assert status["limits"]["max_fallback_time"] == 60.0

    def test_reset_metrics(self):
        """Test reset_metrics clears all counters."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["openai"])
        chain.metrics.primary_attempts = 10
        chain.metrics.fallback_attempts = 5

        chain.reset_metrics()

        assert chain.metrics.primary_attempts == 0
        assert chain.metrics.fallback_attempts == 0


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestGetDefaultFallbackEnabled:
    """Test get_default_fallback_enabled function."""

    def test_returns_boolean(self):
        """Test function returns a boolean."""
        from aragora.agents.fallback import get_default_fallback_enabled

        result = get_default_fallback_enabled()

        assert isinstance(result, bool)


class TestGetLocalFallbackProviders:
    """Test get_local_fallback_providers function."""

    def test_returns_list(self):
        """Test function returns a list."""
        from aragora.agents.fallback import get_local_fallback_providers

        result = get_local_fallback_providers()

        assert isinstance(result, list)


class TestIsLocalLlmAvailable:
    """Test is_local_llm_available function."""

    def test_returns_boolean(self):
        """Test function returns a boolean."""
        from aragora.agents.fallback import is_local_llm_available

        result = is_local_llm_available()

        assert isinstance(result, bool)


# =============================================================================
# Module Exports Tests
# =============================================================================


class TestModuleExports:
    """Test module exports."""

    def test_quota_error_keywords_exportable(self):
        """Test QUOTA_ERROR_KEYWORDS can be imported."""
        from aragora.agents.fallback import QUOTA_ERROR_KEYWORDS

        assert QUOTA_ERROR_KEYWORDS is not None

    def test_mixin_exportable(self):
        """Test QuotaFallbackMixin can be imported."""
        from aragora.agents.fallback import QuotaFallbackMixin

        assert QuotaFallbackMixin is not None

    def test_metrics_exportable(self):
        """Test FallbackMetrics can be imported."""
        from aragora.agents.fallback import FallbackMetrics

        assert FallbackMetrics is not None

    def test_chain_exportable(self):
        """Test AgentFallbackChain can be imported."""
        from aragora.agents.fallback import AgentFallbackChain

        assert AgentFallbackChain is not None

    def test_errors_exportable(self):
        """Test error classes can be imported."""
        from aragora.agents.fallback import (
            AllProvidersExhaustedError,
            FallbackTimeoutError,
        )

        assert AllProvidersExhaustedError is not None
        assert FallbackTimeoutError is not None

    def test_utility_functions_exportable(self):
        """Test utility functions can be imported."""
        from aragora.agents.fallback import (
            build_fallback_chain_with_local,
            get_default_fallback_enabled,
            get_local_fallback_providers,
            is_local_llm_available,
        )

        assert get_default_fallback_enabled is not None
        assert get_local_fallback_providers is not None
        assert is_local_llm_available is not None
        assert build_fallback_chain_with_local is not None


# =============================================================================
# Rate Limit Detection Tests
# =============================================================================


class TestRateLimitDetection:
    """Test rate limit error detection in fallback chain."""

    def test_is_rate_limit_error_true(self):
        """Test rate limit detection returns true for rate limit errors."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["openai"])

        error = RuntimeError("Rate limit exceeded")
        assert chain._is_rate_limit_error(error) is True

    def test_is_rate_limit_error_false(self):
        """Test rate limit detection returns false for other errors."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["openai"])

        error = RuntimeError("Connection refused")
        assert chain._is_rate_limit_error(error) is False

    def test_is_rate_limit_error_quota(self):
        """Test rate limit detection for quota errors."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["openai"])

        error = RuntimeError("Quota exceeded for this API key")
        assert chain._is_rate_limit_error(error) is True


# =============================================================================
# Multi-Provider Fallback Tests
# =============================================================================


class TestContentPolicyDetection:
    """Test content policy error detection."""

    def test_content_policy_400_detected(self):
        """Content policy errors on 400 are detected."""
        from aragora.agents.fallback import QuotaFallbackMixin

        assert QuotaFallbackMixin._is_content_policy_error(
            400, "Request blocked by content policy filter"
        )

    def test_content_policy_moderation(self):
        """Moderation keyword is detected."""
        from aragora.agents.fallback import QuotaFallbackMixin

        assert QuotaFallbackMixin._is_content_policy_error(400, "Blocked by moderation system")

    def test_content_policy_non_400_not_detected(self):
        """Non-400 status codes are not treated as content policy errors."""
        from aragora.agents.fallback import QuotaFallbackMixin

        assert not QuotaFallbackMixin._is_content_policy_error(429, "content policy violation")

    def test_content_policy_400_without_keywords_not_detected(self):
        """400 without policy keywords is not a content policy error."""
        from aragora.agents.fallback import QuotaFallbackMixin

        assert not QuotaFallbackMixin._is_content_policy_error(400, "Invalid request parameters")

    def test_content_policy_safety_filter(self):
        """Safety filter keyword is detected."""
        from aragora.agents.fallback import QuotaFallbackMixin

        assert QuotaFallbackMixin._is_content_policy_error(400, "Blocked by safety filter")


class TestMultiProviderFallbackMixin:
    """Test multi-provider fallback in QuotaFallbackMixin."""

    def _make_mixin_agent(self, name="test-agent", provider="anthropic"):
        """Create a mock agent with QuotaFallbackMixin behavior."""
        from aragora.agents.fallback import QuotaFallbackMixin

        class MockAgent(QuotaFallbackMixin):
            OPENROUTER_MODEL_MAP = {}
            DEFAULT_FALLBACK_MODEL = "anthropic/claude-sonnet-4.6"

            def __init__(self, agent_name, agent_provider):
                self.name = agent_name
                self.model = "test-model"
                self.enable_fallback = True
                self.role = "proposer"
                self.timeout = 120
                self.system_prompt = None
                self._fallback_agent = None
                self._provider = agent_provider

            def _derive_provider_name(self):
                return self._provider

        return MockAgent(name, provider)

    def test_get_available_providers_skips_self(self):
        """Fallback list should not include the agent's own provider."""
        agent = self._make_mixin_agent(provider="anthropic")

        with patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "sk-ant-test",
                "OPENAI_API_KEY": "sk-openai-test",
                "OPENROUTER_API_KEY": "sk-or-test",
            },
            clear=True,
        ):
            # Mock agent creation to avoid real imports
            with patch.object(
                type(agent),
                "_create_fallback_agent",
                side_effect=lambda pk, ak, n, r, t, s: MagicMock(name=f"mock-{pk}")
                if pk != "anthropic"
                else None,
            ):
                providers = agent._get_available_fallback_providers()

        provider_keys = [p[0] for p in providers]
        assert "anthropic" not in provider_keys
        assert "openrouter" in provider_keys
        assert "openai" in provider_keys

    def test_get_available_providers_only_with_keys(self):
        """Only providers with API keys set are returned."""
        agent = self._make_mixin_agent(provider="anthropic")

        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "sk-openai-test"},
            clear=True,
        ):
            with patch.object(
                type(agent),
                "_create_fallback_agent",
                side_effect=lambda pk, ak, n, r, t, s: MagicMock(name=f"mock-{pk}"),
            ):
                providers = agent._get_available_fallback_providers()

        provider_keys = [p[0] for p in providers]
        assert provider_keys == ["openai"]

    def test_get_available_providers_empty_when_no_keys(self):
        """Returns empty list when no API keys are set."""
        agent = self._make_mixin_agent(provider="anthropic")

        with patch.dict(os.environ, {}, clear=True):
            providers = agent._get_available_fallback_providers()

        assert providers == []

    def test_openrouter_is_first(self):
        """OpenRouter should be tried first when available."""
        agent = self._make_mixin_agent(provider="anthropic")

        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "sk-or-test",
                "OPENAI_API_KEY": "sk-openai-test",
                "GEMINI_API_KEY": "sk-gemini-test",
            },
            clear=True,
        ):
            with patch.object(
                type(agent),
                "_create_fallback_agent",
                side_effect=lambda pk, ak, n, r, t, s: MagicMock(name=f"mock-{pk}"),
            ):
                providers = agent._get_available_fallback_providers()

        provider_keys = [p[0] for p in providers]
        assert provider_keys[0] == "openrouter"

    @pytest.mark.asyncio
    async def test_fallback_generate_tries_multiple_providers(self):
        """fallback_generate tries providers sequentially until one succeeds."""
        agent = self._make_mixin_agent(provider="anthropic")

        openrouter_agent = MagicMock()
        openrouter_agent.generate = AsyncMock(side_effect=RuntimeError("Rate limit"))

        openai_agent = MagicMock()
        openai_agent.generate = AsyncMock(return_value="Response from OpenAI")

        with patch.object(
            type(agent),
            "_get_available_fallback_providers",
            return_value=[("openrouter", openrouter_agent), ("openai", openai_agent)],
        ):
            result = await agent.fallback_generate("Test prompt", status_code=429)

        assert result == "Response from OpenAI"
        openrouter_agent.generate.assert_called_once()
        openai_agent.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_generate_returns_first_success(self):
        """fallback_generate returns on first successful provider."""
        agent = self._make_mixin_agent(provider="anthropic")

        openrouter_agent = MagicMock()
        openrouter_agent.generate = AsyncMock(return_value="OpenRouter response")

        openai_agent = MagicMock()
        openai_agent.generate = AsyncMock(return_value="OpenAI response")

        with patch.object(
            type(agent),
            "_get_available_fallback_providers",
            return_value=[("openrouter", openrouter_agent), ("openai", openai_agent)],
        ):
            result = await agent.fallback_generate("Test prompt", status_code=429)

        assert result == "OpenRouter response"
        openrouter_agent.generate.assert_called_once()
        openai_agent.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_generate_returns_none_when_all_fail(self):
        """fallback_generate returns None when all providers fail."""
        agent = self._make_mixin_agent(provider="anthropic")

        openrouter_agent = MagicMock()
        openrouter_agent.generate = AsyncMock(side_effect=RuntimeError("OR fail"))

        openai_agent = MagicMock()
        openai_agent.generate = AsyncMock(side_effect=RuntimeError("OAI fail"))

        with patch.object(
            type(agent),
            "_get_available_fallback_providers",
            return_value=[("openrouter", openrouter_agent), ("openai", openai_agent)],
        ):
            result = await agent.fallback_generate("Test prompt", status_code=429)

        assert result is None
        openrouter_agent.generate.assert_called_once()
        openai_agent.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_generate_stops_on_content_policy_error(self):
        """fallback_generate stops trying on content policy errors."""
        agent = self._make_mixin_agent(provider="anthropic")

        openrouter_agent = MagicMock()
        openrouter_agent.generate = AsyncMock(
            side_effect=RuntimeError("Blocked by content policy filter")
        )

        openai_agent = MagicMock()
        openai_agent.generate = AsyncMock(return_value="OpenAI response")

        with patch.object(
            type(agent),
            "_get_available_fallback_providers",
            return_value=[("openrouter", openrouter_agent), ("openai", openai_agent)],
        ):
            result = await agent.fallback_generate("Test prompt", status_code=429)

        assert result is None
        openrouter_agent.generate.assert_called_once()
        # OpenAI should NOT be tried after content policy error
        openai_agent.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_generate_returns_none_when_disabled(self):
        """fallback_generate returns None when enable_fallback is False."""
        agent = self._make_mixin_agent(provider="anthropic")
        agent.enable_fallback = False

        result = await agent.fallback_generate("Test prompt", status_code=429)

        assert result is None

    @pytest.mark.asyncio
    async def test_fallback_generate_returns_none_when_no_providers(self):
        """fallback_generate returns None when no providers are available."""
        agent = self._make_mixin_agent(provider="anthropic")

        with patch.object(
            type(agent),
            "_get_available_fallback_providers",
            return_value=[],
        ):
            result = await agent.fallback_generate("Test prompt", status_code=429)

        assert result is None

    @pytest.mark.asyncio
    async def test_fallback_generate_passes_context(self):
        """fallback_generate passes context to provider agents."""
        agent = self._make_mixin_agent(provider="anthropic")

        openrouter_agent = MagicMock()
        openrouter_agent.generate = AsyncMock(return_value="Response")

        context = [{"role": "user", "content": "Hello"}]

        with patch.object(
            type(agent),
            "_get_available_fallback_providers",
            return_value=[("openrouter", openrouter_agent)],
        ):
            await agent.fallback_generate("Test prompt", context=context, status_code=429)

        openrouter_agent.generate.assert_called_once_with("Test prompt", context)

    @pytest.mark.asyncio
    async def test_fallback_generate_notifies_session_circuit_breaker(self):
        """fallback_generate notifies session circuit breaker."""
        agent = self._make_mixin_agent(provider="anthropic")

        with (
            patch.object(
                type(agent),
                "_get_available_fallback_providers",
                return_value=[],
            ),
            patch.object(
                type(agent),
                "_notify_session_circuit_breaker",
            ) as mock_notify,
        ):
            await agent.fallback_generate("Test prompt", status_code=429)

        mock_notify.assert_called_once_with(429)


class TestCreateFallbackAgent:
    """Test _create_fallback_agent static method."""

    def test_create_openrouter_agent(self):
        """OpenRouter agent can be created."""
        from aragora.agents.fallback import QuotaFallbackMixin

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test"}, clear=False):
            agent = QuotaFallbackMixin._create_fallback_agent(
                "openrouter", "sk-test", "test", "proposer", 120, None
            )

        assert agent is not None
        assert "fallback_openrouter" in agent.name

    def test_create_unknown_provider_returns_none(self):
        """Unknown provider returns None."""
        from aragora.agents.fallback import QuotaFallbackMixin

        agent = QuotaFallbackMixin._create_fallback_agent(
            "unknown_provider", "sk-test", "test", "proposer", 120, None
        )

        assert agent is None

    def test_create_agent_sets_system_prompt(self):
        """System prompt is applied to fallback agent."""
        from aragora.agents.fallback import QuotaFallbackMixin

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-test"}, clear=False):
            agent = QuotaFallbackMixin._create_fallback_agent(
                "openrouter", "sk-test", "test", "proposer", 120, "Be helpful."
            )

        assert agent is not None
        assert agent.system_prompt == "Be helpful."

    def test_create_agent_with_enable_fallback_false(self):
        """Fallback agents are created with enable_fallback=False to prevent recursion."""
        from aragora.agents.fallback import QuotaFallbackMixin

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            agent = QuotaFallbackMixin._create_fallback_agent(
                "openai", "sk-test", "test", "proposer", 120, None
            )

        assert agent is not None
        assert agent.enable_fallback is False

    def test_create_agent_handles_import_error(self):
        """Import errors are caught and None is returned."""
        from aragora.agents.fallback import QuotaFallbackMixin

        # Simulate ImportError by patching the import within the method
        with patch.dict("sys.modules", {"aragora.agents.api_agents": None}):
            agent = QuotaFallbackMixin._create_fallback_agent(
                "openrouter", "sk-test", "test", "proposer", 120, None
            )
            # Should return None when import fails, not crash
            assert agent is None


class TestMultiProviderFallbackStream:
    """Test multi-provider fallback for streaming."""

    def _make_mixin_agent(self, name="test-agent", provider="anthropic"):
        """Create a mock agent with QuotaFallbackMixin behavior."""
        from aragora.agents.fallback import QuotaFallbackMixin

        class MockAgent(QuotaFallbackMixin):
            OPENROUTER_MODEL_MAP = {}
            DEFAULT_FALLBACK_MODEL = "anthropic/claude-sonnet-4.6"

            def __init__(self, agent_name, agent_provider):
                self.name = agent_name
                self.model = "test-model"
                self.enable_fallback = True
                self.role = "proposer"
                self.timeout = 120
                self.system_prompt = None
                self._fallback_agent = None
                self._provider = agent_provider

            def _derive_provider_name(self):
                return self._provider

        return MockAgent(name, provider)

    @pytest.mark.asyncio
    async def test_stream_fallback_tries_multiple_providers(self):
        """Stream fallback tries providers sequentially."""
        agent = self._make_mixin_agent(provider="anthropic")

        async def failing_stream(*args, **kwargs):
            raise RuntimeError("Rate limit")
            yield  # makes this an async generator

        async def successful_stream(*args, **kwargs):
            for token in ["Hello", " world"]:
                yield token

        openrouter_agent = MagicMock()
        openrouter_agent.generate_stream = failing_stream

        openai_agent = MagicMock()
        openai_agent.generate_stream = successful_stream

        tokens = []
        with patch.object(
            type(agent),
            "_get_available_fallback_providers",
            return_value=[("openrouter", openrouter_agent), ("openai", openai_agent)],
        ):
            async for token in agent.fallback_generate_stream("Test prompt", status_code=429):
                tokens.append(token)

        assert tokens == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_stream_fallback_returns_empty_when_disabled(self):
        """Stream fallback yields nothing when disabled."""
        agent = self._make_mixin_agent(provider="anthropic")
        agent.enable_fallback = False

        tokens = []
        async for token in agent.fallback_generate_stream("Test prompt", status_code=429):
            tokens.append(token)

        assert tokens == []

    @pytest.mark.asyncio
    async def test_stream_fallback_stops_on_content_policy_error(self):
        """Stream fallback stops on content policy errors."""
        agent = self._make_mixin_agent(provider="anthropic")

        async def policy_error_stream(*args, **kwargs):
            raise RuntimeError("Blocked by content policy filter")
            yield  # makes this an async generator

        async def successful_stream(*args, **kwargs):
            for token in ["Hello"]:
                yield token

        openrouter_agent = MagicMock()
        openrouter_agent.generate_stream = policy_error_stream

        openai_agent = MagicMock()
        openai_agent.generate_stream = successful_stream

        tokens = []
        with patch.object(
            type(agent),
            "_get_available_fallback_providers",
            return_value=[("openrouter", openrouter_agent), ("openai", openai_agent)],
        ):
            async for token in agent.fallback_generate_stream("Test prompt", status_code=429):
                tokens.append(token)

        # Should be empty - stopped after content policy error
        assert tokens == []

    @pytest.mark.asyncio
    async def test_stream_fallback_skips_non_streaming_providers(self):
        """Providers without generate_stream are skipped."""
        agent = self._make_mixin_agent(provider="anthropic")

        async def successful_stream(*args, **kwargs):
            for token in ["Hello"]:
                yield token

        non_streaming_agent = MagicMock(spec=[])  # No generate_stream attribute

        streaming_agent = MagicMock()
        streaming_agent.generate_stream = successful_stream

        tokens = []
        with patch.object(
            type(agent),
            "_get_available_fallback_providers",
            return_value=[
                ("non_streaming", non_streaming_agent),
                ("streaming", streaming_agent),
            ],
        ):
            async for token in agent.fallback_generate_stream("Test prompt", status_code=429):
                tokens.append(token)

        assert tokens == ["Hello"]


# =============================================================================
# End-to-End Fallback Chain Tests
# =============================================================================


class TestFallbackChainEndToEnd:
    """End-to-end integration tests for multi-provider fallback chain.

    These tests exercise sequential provider failures with realistic HTTP status
    codes and verify the chain traverses through multiple providers correctly.
    """

    def _make_mixin_agent(self, name="test-agent", provider="anthropic"):
        """Create a mock agent with QuotaFallbackMixin behavior."""
        from aragora.agents.fallback import QuotaFallbackMixin

        class MockAgent(QuotaFallbackMixin):
            OPENROUTER_MODEL_MAP = {}
            DEFAULT_FALLBACK_MODEL = "anthropic/claude-sonnet-4.6"

            def __init__(self, agent_name, agent_provider):
                self.name = agent_name
                self.model = "test-model"
                self.enable_fallback = True
                self.role = "proposer"
                self.timeout = 120
                self.system_prompt = None
                self._fallback_agent = None
                self._provider = agent_provider

            def _derive_provider_name(self):
                return self._provider

        return MockAgent(name, provider)

    @pytest.mark.asyncio
    async def test_sequential_failures_reaches_third_provider(self):
        """Chain traverses through 3 failing providers to reach the 4th.

        Provider 1: HTTP 402 Payment Required
        Provider 2: HTTP 429 Too Many Requests
        Provider 3: RuntimeError (generic failure)
        Provider 4: Succeeds with expected response
        """
        agent = self._make_mixin_agent(provider="anthropic")

        provider_1 = MagicMock()
        provider_1.generate = AsyncMock(
            side_effect=RuntimeError("HTTP 402: Payment Required - credit balance is too low")
        )

        provider_2 = MagicMock()
        provider_2.generate = AsyncMock(
            side_effect=RuntimeError("HTTP 429: Too Many Requests - rate limit exceeded")
        )

        provider_3 = MagicMock()
        provider_3.generate = AsyncMock(side_effect=RuntimeError("Connection reset by peer"))

        provider_4 = MagicMock()
        provider_4.generate = AsyncMock(return_value="Success from provider 4")

        providers = [
            ("openrouter", provider_1),
            ("openai", provider_2),
            ("gemini", provider_3),
            ("mistral", provider_4),
        ]

        with patch.object(
            type(agent),
            "_get_available_fallback_providers",
            return_value=providers,
        ):
            result = await agent.fallback_generate("Test prompt", status_code=402)

        assert result == "Success from provider 4"

        # Verify all providers were called in order
        provider_1.generate.assert_called_once_with("Test prompt", None)
        provider_2.generate.assert_called_once_with("Test prompt", None)
        provider_3.generate.assert_called_once_with("Test prompt", None)
        provider_4.generate.assert_called_once_with("Test prompt", None)

    @pytest.mark.asyncio
    async def test_all_providers_fail_returns_none(self):
        """Chain returns None when all 4 providers fail with different errors.

        Provider 1: HTTP 402 Payment Required
        Provider 2: HTTP 429 Too Many Requests
        Provider 3: TimeoutError
        Provider 4: Generic RuntimeError
        """
        agent = self._make_mixin_agent(provider="anthropic")

        provider_1 = MagicMock()
        provider_1.generate = AsyncMock(side_effect=RuntimeError("HTTP 402: Payment Required"))

        provider_2 = MagicMock()
        provider_2.generate = AsyncMock(side_effect=RuntimeError("HTTP 429: Too Many Requests"))

        provider_3 = MagicMock()
        provider_3.generate = AsyncMock(side_effect=TimeoutError("Request timed out after 30s"))

        provider_4 = MagicMock()
        provider_4.generate = AsyncMock(side_effect=RuntimeError("Internal server error"))

        providers = [
            ("openrouter", provider_1),
            ("openai", provider_2),
            ("gemini", provider_3),
            ("mistral", provider_4),
        ]

        with patch.object(
            type(agent),
            "_get_available_fallback_providers",
            return_value=providers,
        ):
            result = await agent.fallback_generate("Test prompt", status_code=402)

        assert result is None

        # Verify all 4 providers were attempted
        provider_1.generate.assert_called_once()
        provider_2.generate.assert_called_once()
        provider_3.generate.assert_called_once()
        provider_4.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_content_policy_error_stops_chain(self):
        """Chain stops immediately when first provider returns content policy error.

        A 400 with 'content policy' in the message is non-retryable and should
        prevent the chain from trying any subsequent providers.
        """
        agent = self._make_mixin_agent(provider="anthropic")

        provider_1 = MagicMock()
        provider_1.generate = AsyncMock(
            side_effect=RuntimeError(
                "HTTP 400: Your request was rejected due to content policy violation"
            )
        )

        provider_2 = MagicMock()
        provider_2.generate = AsyncMock(return_value="Should never be reached")

        provider_3 = MagicMock()
        provider_3.generate = AsyncMock(return_value="Should never be reached")

        provider_4 = MagicMock()
        provider_4.generate = AsyncMock(return_value="Should never be reached")

        providers = [
            ("openrouter", provider_1),
            ("openai", provider_2),
            ("gemini", provider_3),
            ("mistral", provider_4),
        ]

        with patch.object(
            type(agent),
            "_get_available_fallback_providers",
            return_value=providers,
        ):
            result = await agent.fallback_generate("Test prompt", status_code=400)

        assert result is None

        # Only the first provider should be tried
        provider_1.generate.assert_called_once()
        provider_2.generate.assert_not_called()
        provider_3.generate.assert_not_called()
        provider_4.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_fallback_logs_successful_provider(self):
        """When provider #3 succeeds, a log message records which provider was used."""
        agent = self._make_mixin_agent(provider="anthropic")

        provider_1 = MagicMock()
        provider_1.generate = AsyncMock(side_effect=RuntimeError("HTTP 402: Payment Required"))

        provider_2 = MagicMock()
        provider_2.generate = AsyncMock(side_effect=RuntimeError("HTTP 429: Too Many Requests"))

        provider_3 = MagicMock()
        provider_3.generate = AsyncMock(return_value="Response from gemini")

        providers = [
            ("openrouter", provider_1),
            ("openai", provider_2),
            ("gemini", provider_3),
        ]

        with (
            patch.object(
                type(agent),
                "_get_available_fallback_providers",
                return_value=providers,
            ),
            patch("aragora.agents.fallback.logger") as mock_logger,
        ):
            result = await agent.fallback_generate("Test prompt", status_code=402)

        assert result == "Response from gemini"

        # Verify the success log message records the provider name
        info_calls = [call.args for call in mock_logger.info.call_args_list]
        success_logs = [
            args for args in info_calls if len(args) >= 2 and "succeeded" in str(args[0])
        ]
        assert len(success_logs) >= 1, "Expected a success log message"
        # The log format is: "Fallback to %s succeeded for %s (%.2fs)"
        # args[1] is the provider key
        assert any(args[1] == "gemini" for args in success_logs), (
            f"Expected 'gemini' in success log, got: {success_logs}"
        )


class TestProviderEnvKeyOrdering:
    """Test that provider ordering follows the expected precedence."""

    def test_provider_env_keys_order(self):
        """OpenRouter should come first in the provider list."""
        from aragora.agents.fallback import QuotaFallbackMixin

        keys = [entry[1] for entry in QuotaFallbackMixin._PROVIDER_ENV_KEYS]
        assert keys[0] == "openrouter"
        # All expected providers should be present
        assert "openai" in keys
        assert "anthropic" in keys
        assert "gemini" in keys
        assert "mistral" in keys
        assert "grok" in keys

    def test_retryable_status_codes(self):
        """Retryable status codes should include expected values."""
        from aragora.agents.fallback import QuotaFallbackMixin

        codes = QuotaFallbackMixin._RETRYABLE_STATUS_CODES
        assert 402 in codes
        assert 429 in codes
        assert 408 in codes
        assert 504 in codes
        # 400 should NOT be in retryable codes (content policy)
        assert 400 not in codes
