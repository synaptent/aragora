"""
Tests for AgentFallbackChain and related fallback utilities.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from aragora.agents.fallback import (
    AgentFallbackChain,
    AllProvidersExhaustedError,
    FallbackMetrics,
    QUOTA_ERROR_KEYWORDS,
)
from aragora.resilience import CircuitBreaker


class MockAgent:
    """Mock agent for testing."""

    def __init__(self, name: str = "mock", should_fail: bool = False, fail_message: str = "error"):
        self.name = name
        self.should_fail = should_fail
        self.fail_message = fail_message
        self.call_count = 0

    async def generate(self, prompt: str, context=None) -> str:
        self.call_count += 1
        if self.should_fail:
            raise Exception(self.fail_message)
        return f"Response from {self.name}"

    async def generate_stream(self, prompt: str, context=None):
        self.call_count += 1
        if self.should_fail:
            raise Exception(self.fail_message)
        for token in ["Hello", " ", "World"]:
            yield token


class TestFallbackMetrics:
    """Tests for FallbackMetrics."""

    def test_initial_state(self):
        """Metrics should start at zero."""
        metrics = FallbackMetrics()
        assert metrics.primary_attempts == 0
        assert metrics.primary_successes == 0
        assert metrics.fallback_attempts == 0
        assert metrics.fallback_successes == 0
        assert metrics.fallback_rate == 0.0
        assert metrics.success_rate == 0.0

    def test_record_primary_success(self):
        """Recording primary success should increment counters."""
        metrics = FallbackMetrics()
        metrics.record_primary_attempt(success=True)
        assert metrics.primary_attempts == 1
        assert metrics.primary_successes == 1
        assert metrics.total_failures == 0

    def test_record_primary_failure(self):
        """Recording primary failure should increment failure count."""
        metrics = FallbackMetrics()
        metrics.record_primary_attempt(success=False)
        assert metrics.primary_attempts == 1
        assert metrics.primary_successes == 0
        assert metrics.total_failures == 1

    def test_record_fallback_attempt(self):
        """Recording fallback attempt should track provider usage."""
        metrics = FallbackMetrics()
        metrics.record_fallback_attempt("openrouter", success=True)
        assert metrics.fallback_attempts == 1
        assert metrics.fallback_successes == 1
        assert metrics.fallback_providers_used == {"openrouter": 1}

    def test_fallback_rate_calculation(self):
        """Fallback rate should be calculated correctly."""
        metrics = FallbackMetrics()
        # 2 primary, 1 fallback = 33% fallback rate
        metrics.record_primary_attempt(success=True)
        metrics.record_primary_attempt(success=True)
        metrics.record_fallback_attempt("openrouter", success=True)
        assert metrics.fallback_rate == pytest.approx(1 / 3)

    def test_success_rate_calculation(self):
        """Success rate should include both primary and fallback."""
        metrics = FallbackMetrics()
        metrics.record_primary_attempt(success=True)
        metrics.record_primary_attempt(success=False)
        metrics.record_fallback_attempt("openrouter", success=True)
        # 2 successes out of 3 attempts
        assert metrics.success_rate == pytest.approx(2 / 3)


class TestAgentFallbackChain:
    """Tests for AgentFallbackChain."""

    @pytest.mark.asyncio
    async def test_primary_provider_success(self):
        """Should use primary provider when it succeeds."""
        chain = AgentFallbackChain(providers=["openai", "openrouter"])
        primary = MockAgent("openai")
        fallback = MockAgent("openrouter")

        chain.register_provider("openai", lambda: primary)
        chain.register_provider("openrouter", lambda: fallback)

        result = await chain.generate("test prompt")

        assert result == "Response from openai"
        assert primary.call_count == 1
        assert fallback.call_count == 0
        assert chain.metrics.primary_successes == 1
        assert chain.metrics.fallback_attempts == 0

    @pytest.mark.asyncio
    async def test_fallback_on_primary_failure(self):
        """Should fall back when primary provider fails."""
        chain = AgentFallbackChain(providers=["openai", "openrouter"])
        primary = MockAgent("openai", should_fail=True)
        fallback = MockAgent("openrouter")

        chain.register_provider("openai", lambda: primary)
        chain.register_provider("openrouter", lambda: fallback)

        result = await chain.generate("test prompt")

        assert result == "Response from openrouter"
        assert primary.call_count == 1
        assert fallback.call_count == 1
        assert chain.metrics.primary_attempts == 1
        assert chain.metrics.primary_successes == 0
        assert chain.metrics.fallback_successes == 1

    @pytest.mark.asyncio
    async def test_all_providers_exhausted(self):
        """Should raise AllProvidersExhaustedError when all fail."""
        chain = AgentFallbackChain(providers=["openai", "openrouter"])
        primary = MockAgent("openai", should_fail=True, fail_message="openai error")
        fallback = MockAgent("openrouter", should_fail=True, fail_message="openrouter error")

        chain.register_provider("openai", lambda: primary)
        chain.register_provider("openrouter", lambda: fallback)

        with pytest.raises(AllProvidersExhaustedError) as exc_info:
            await chain.generate("test prompt")

        assert exc_info.value.providers == ["openai", "openrouter"]
        assert "openrouter error" in str(exc_info.value.last_error)

    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self):
        """Should skip circuit-broken providers."""
        circuit_breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
        chain = AgentFallbackChain(
            providers=["openai", "openrouter"],
            circuit_breaker=circuit_breaker,
        )

        primary = MockAgent("openai")
        fallback = MockAgent("openrouter")

        chain.register_provider("openai", lambda: primary)
        chain.register_provider("openrouter", lambda: fallback)

        # Trip the circuit breaker for openai
        circuit_breaker.record_failure("openai")
        circuit_breaker.record_failure("openai")

        result = await chain.generate("test prompt")

        # Should skip openai and use openrouter directly
        assert result == "Response from openrouter"
        assert primary.call_count == 0  # Skipped
        assert fallback.call_count == 1

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failures(self):
        """Should record failures to circuit breaker."""
        circuit_breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
        chain = AgentFallbackChain(
            providers=["openai", "openrouter"],
            circuit_breaker=circuit_breaker,
        )

        primary = MockAgent("openai", should_fail=True)
        fallback = MockAgent("openrouter")

        chain.register_provider("openai", lambda: primary)
        chain.register_provider("openrouter", lambda: fallback)

        await chain.generate("test prompt")

        # openai should have 1 failure recorded
        assert circuit_breaker._failures.get("openai", 0) == 1
        # openrouter should have recorded success (resets failures)
        assert circuit_breaker._failures.get("openrouter", 0) == 0

    @pytest.mark.asyncio
    async def test_stream_primary_success(self):
        """Should stream from primary provider when it succeeds."""
        chain = AgentFallbackChain(providers=["openai", "openrouter"])
        primary = MockAgent("openai")
        fallback = MockAgent("openrouter")

        chain.register_provider("openai", lambda: primary)
        chain.register_provider("openrouter", lambda: fallback)

        tokens = []
        async for token in chain.generate_stream("test prompt"):
            tokens.append(token)

        assert tokens == ["Hello", " ", "World"]
        assert primary.call_count == 1
        assert fallback.call_count == 0

    @pytest.mark.asyncio
    async def test_stream_fallback_on_failure(self):
        """Should fall back streaming when primary fails."""
        chain = AgentFallbackChain(providers=["openai", "openrouter"])
        primary = MockAgent("openai", should_fail=True)
        fallback = MockAgent("openrouter")

        chain.register_provider("openai", lambda: primary)
        chain.register_provider("openrouter", lambda: fallback)

        tokens = []
        async for token in chain.generate_stream("test prompt"):
            tokens.append(token)

        assert tokens == ["Hello", " ", "World"]
        assert primary.call_count == 1
        assert fallback.call_count == 1

    def test_get_available_providers(self):
        """Should return only non-circuit-broken providers."""
        circuit_breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
        chain = AgentFallbackChain(
            providers=["openai", "openrouter", "anthropic"],
            circuit_breaker=circuit_breaker,
        )

        # Trip openai
        circuit_breaker.record_failure("openai")
        circuit_breaker.record_failure("openai")

        available = chain.get_available_providers()
        assert available == ["openrouter", "anthropic"]

    def test_get_status(self):
        """Should return current chain status."""
        chain = AgentFallbackChain(providers=["openai", "openrouter"])
        chain.metrics.record_primary_attempt(success=True)
        chain.metrics.record_fallback_attempt("openrouter", success=True)

        status = chain.get_status()

        assert status["providers"] == ["openai", "openrouter"]
        assert status["available_providers"] == ["openai", "openrouter"]
        assert status["metrics"]["primary_attempts"] == 1
        assert status["metrics"]["fallback_attempts"] == 1
        assert "50.0%" in status["metrics"]["fallback_rate"]

    def test_reset_metrics(self):
        """Should reset all metrics."""
        chain = AgentFallbackChain(providers=["openai"])
        chain.metrics.record_primary_attempt(success=True)
        chain.metrics.record_fallback_attempt("openrouter", success=True)

        chain.reset_metrics()

        assert chain.metrics.primary_attempts == 0
        assert chain.metrics.fallback_attempts == 0


class TestRateLimitDetection:
    """Tests for rate limit error detection."""

    def test_detects_rate_limit_keywords(self):
        """Should detect rate limit errors from keywords."""
        chain = AgentFallbackChain(providers=["test"])

        assert chain._is_rate_limit_error(Exception("rate limit exceeded"))
        assert chain._is_rate_limit_error(Exception("quota exceeded"))
        assert chain._is_rate_limit_error(Exception("too many requests"))
        assert chain._is_rate_limit_error(Exception("Resource exhausted"))
        assert not chain._is_rate_limit_error(Exception("Unknown error"))

    def test_quota_error_keywords_coverage(self):
        """Should have comprehensive keyword coverage."""
        # Verify key keywords are present
        assert "rate limit" in QUOTA_ERROR_KEYWORDS
        assert "quota" in QUOTA_ERROR_KEYWORDS
        assert "too many requests" in QUOTA_ERROR_KEYWORDS
        assert "insufficient_quota" in QUOTA_ERROR_KEYWORDS


class TestAllProvidersExhaustedError:
    """Tests for AllProvidersExhaustedError."""

    def test_error_message(self):
        """Should include provider list and last error in message."""
        last_err = ValueError("API error")
        error = AllProvidersExhaustedError(["openai", "openrouter"], last_err)

        assert "openai" in str(error)
        assert "openrouter" in str(error)
        assert "API error" in str(error)
        assert error.providers == ["openai", "openrouter"]
        assert error.last_error is last_err

    def test_error_without_last_error(self):
        """Should work without last error."""
        error = AllProvidersExhaustedError(["openai"])

        assert "openai" in str(error)
        assert error.last_error is None


class TestFallbackTimeoutError:
    """Tests for FallbackTimeoutError exception."""

    def test_error_attributes(self):
        """Should store timeout details."""
        from aragora.agents.fallback import FallbackTimeoutError

        error = FallbackTimeoutError(elapsed=45.5, limit=30.0, tried=["openai", "openrouter"])

        assert error.elapsed == 45.5
        assert error.limit == 30.0
        assert error.tried_providers == ["openai", "openrouter"]
        assert "45.5s" in str(error)
        assert "30" in str(error)
        assert "openai" in str(error)

    def test_error_message_formatting(self):
        """Should format message correctly."""
        from aragora.agents.fallback import FallbackTimeoutError

        error = FallbackTimeoutError(
            elapsed=120.0, limit=60.0, tried=["provider1", "provider2", "provider3"]
        )

        message = str(error)
        assert "120.0s" in message
        assert "60" in message
        assert "provider1" in message
        assert "provider2" in message
        assert "provider3" in message


class TestMaxRetries:
    """Tests for max_retries limit behavior."""

    @pytest.mark.asyncio
    async def test_respects_max_retries_limit(self):
        """Should stop after max_retries providers."""
        chain = AgentFallbackChain(
            providers=["p1", "p2", "p3", "p4", "p5"],
            max_retries=2,
        )

        call_counts = {}
        for name in ["p1", "p2", "p3", "p4", "p5"]:
            agent = MockAgent(name, should_fail=True)
            call_counts[name] = agent
            chain.register_provider(name, lambda a=agent: a)

        with pytest.raises(AllProvidersExhaustedError):
            await chain.generate("test")

        # Only first 2 should be tried
        total_calls = sum(a.call_count for a in call_counts.values())
        assert total_calls == 2

    @pytest.mark.asyncio
    async def test_default_max_retries(self):
        """Should use DEFAULT_MAX_RETRIES when not specified."""
        chain = AgentFallbackChain(providers=["p1"])
        assert chain.max_retries == AgentFallbackChain.DEFAULT_MAX_RETRIES


class TestMaxFallbackTime:
    """Tests for max_fallback_time limit behavior."""

    @pytest.mark.asyncio
    async def test_raises_timeout_when_exceeded(self):
        """Should raise FallbackTimeoutError when time limit exceeded."""
        import asyncio
        import time
        from aragora.agents.fallback import FallbackTimeoutError

        chain = AgentFallbackChain(
            providers=["slow1", "slow2", "slow3"],
            max_fallback_time=0.05,  # 50ms timeout - very short
            max_retries=3,
        )

        class SlowFailingAgent:
            def __init__(self, name):
                self.name = name

            async def generate(self, prompt, context=None):
                # Fail after some delay
                await asyncio.sleep(0.03)
                raise Exception(f"{self.name} failed")

        chain.register_provider("slow1", lambda: SlowFailingAgent("slow1"))
        chain.register_provider("slow2", lambda: SlowFailingAgent("slow2"))
        chain.register_provider("slow3", lambda: SlowFailingAgent("slow3"))

        # The timeout check happens at the start of each loop iteration
        # After 2 slow failures (~60ms), should exceed the 50ms limit
        with pytest.raises((FallbackTimeoutError, AllProvidersExhaustedError)):
            await chain.generate("test")

    def test_default_max_fallback_time(self):
        """Should use DEFAULT_MAX_FALLBACK_TIME when not specified."""
        chain = AgentFallbackChain(providers=["p1"])
        assert chain.max_fallback_time == AgentFallbackChain.DEFAULT_MAX_FALLBACK_TIME


class TestQuotaFallbackMixin:
    """Tests for QuotaFallbackMixin class."""

    def test_is_quota_error_429(self):
        """Should detect 429 as quota error."""
        from aragora.agents.fallback import QuotaFallbackMixin

        class TestAgent(QuotaFallbackMixin):
            pass

        agent = TestAgent()
        assert agent.is_quota_error(429, "any error message") is True

    def test_is_quota_error_403_with_quota_keyword(self):
        """Should detect 403 with quota keywords as quota error."""
        from aragora.agents.fallback import QuotaFallbackMixin

        class TestAgent(QuotaFallbackMixin):
            pass

        agent = TestAgent()
        assert agent.is_quota_error(403, "quota exceeded for this API") is True
        assert agent.is_quota_error(403, "billing issue detected") is True
        assert agent.is_quota_error(403, "limit exceeded") is True
        # 403 without quota keywords is not a quota error
        assert agent.is_quota_error(403, "permission denied") is False

    def test_is_quota_error_with_keyword_in_message(self):
        """Should detect quota keywords in error message."""
        from aragora.agents.fallback import QuotaFallbackMixin

        class TestAgent(QuotaFallbackMixin):
            pass

        agent = TestAgent()
        assert agent.is_quota_error(500, "rate limit exceeded") is True
        assert agent.is_quota_error(500, "resource exhausted") is True
        assert agent.is_quota_error(500, "too many requests") is True
        assert agent.is_quota_error(500, "insufficient_quota") is True
        assert agent.is_quota_error(500, "internal server error") is False

    def test_get_fallback_model_with_mapping(self):
        """get_fallback_model() resolves the current model through the
        catalog/upgrade map (frontier-model-refresh, 2026-09-04 review fix
        round 1, item 3), not the (vestigial) OPENROUTER_MODEL_MAP class
        attribute: "gpt-4o" is a legacy OpenAI spelling that upgrades to
        the current frontier."""
        from aragora.agents.fallback import QuotaFallbackMixin

        class TestAgent(QuotaFallbackMixin):
            OPENROUTER_MODEL_MAP = {
                "gpt-4o": "openai/gpt-4o",
                "claude-3": "anthropic/claude-3-sonnet",
            }
            DEFAULT_FALLBACK_MODEL = "default/model"
            model = "gpt-4o"

        agent = TestAgent()
        # Terra, not Astra: the GPT-4 line is value-tier by price
        # (gpt-4o listed at $2.50/$10), so it preserves tier rather than
        # over-paying for the $10/$50 flagship -- round-4 re-review of
        # finding C-P3 on #9989.
        assert agent.get_fallback_model() == "openai/gpt-5.6-terra"

    def test_get_fallback_model_uses_default(self):
        """Should use default model when no mapping exists."""
        from aragora.agents.fallback import QuotaFallbackMixin

        class TestAgent(QuotaFallbackMixin):
            OPENROUTER_MODEL_MAP = {"other": "other/model"}
            DEFAULT_FALLBACK_MODEL = "my/default"
            model = "unknown-model"

        agent = TestAgent()
        assert agent.get_fallback_model() == "my/default"

    def test_fallback_agent_caching(self):
        """Should cache the fallback agent."""
        from aragora.agents.fallback import QuotaFallbackMixin
        from unittest.mock import patch
        import sys

        class TestAgent(QuotaFallbackMixin):
            name = "test"
            model = "test-model"
            role = "proposer"
            timeout = 60

        agent = TestAgent()

        # Create mock OpenRouterAgent
        mock_instance = MagicMock()
        mock_class = MagicMock(return_value=mock_instance)

        # Patch at the module level where it's imported from
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            with patch.dict(
                "sys.modules", {"aragora.agents.api_agents": MagicMock(OpenRouterAgent=mock_class)}
            ):
                # First call should create agent
                result1 = agent._get_cached_fallback_agent()

                # The agent should be created (either mocked or real)
                assert agent._fallback_agent is not None

                # Second call should return cached agent
                result2 = agent._get_cached_fallback_agent()

                # Both should be the same instance
                assert result1 is result2

    def test_configured_fallback_chain_reorders_available_providers(self):
        """Configured fallback_chain should be preferred before default providers."""
        from aragora.agents.config_loader import AgentConfig
        from aragora.agents.fallback import QuotaFallbackMixin
        from unittest.mock import patch

        class TestAgent(QuotaFallbackMixin):
            name = "primary"
            role = "proposer"
            timeout = 60

            def __init__(self):
                self._config = AgentConfig(
                    name="configured-agent",
                    model_type="anthropic-api",
                    fallback_chain=["gemini", "openai-api"],
                )

        agent = TestAgent()

        with (
            patch.dict(
                "os.environ",
                {
                    "OPENROUTER_API_KEY": "router-key",
                    "OPENAI_API_KEY": "openai-key",
                    "GEMINI_API_KEY": "gemini-key",
                },
                clear=True,
            ),
            patch.object(
                TestAgent,
                "_create_fallback_agent",
                side_effect=lambda provider_key, *args: provider_key,
            ),
        ):
            providers = agent._get_available_fallback_providers()

        assert [provider_name for provider_name, _ in providers] == [
            "gemini",
            "openai",
            "openrouter",
        ]


class TestBuildFallbackChainWithLocal:
    """Tests for build_fallback_chain_with_local function."""

    def test_no_local_when_disabled(self):
        """Should not include local when include_local=False."""
        from aragora.agents.fallback import build_fallback_chain_with_local

        result = build_fallback_chain_with_local(
            primary_providers=["openai", "openrouter"],
            include_local=False,
        )
        assert result == ["openai", "openrouter"]

    def test_returns_primary_when_no_local_available(self):
        """Should return primary providers when no local LLMs available."""
        from aragora.agents.fallback import build_fallback_chain_with_local
        from unittest.mock import patch

        with patch("aragora.agents.fallback.get_local_fallback_providers", return_value=[]):
            result = build_fallback_chain_with_local(
                primary_providers=["openai", "anthropic"],
                include_local=True,
            )
            assert result == ["openai", "anthropic"]

    def test_inserts_local_after_openrouter_by_default(self):
        """Should insert local after OpenRouter by default."""
        from aragora.agents.fallback import build_fallback_chain_with_local
        from unittest.mock import patch

        with patch("aragora.agents.fallback.get_local_fallback_providers", return_value=["ollama"]):
            result = build_fallback_chain_with_local(
                primary_providers=["openai", "openrouter", "anthropic"],
                include_local=True,
                local_priority=False,
            )
            # Local should come after openrouter
            assert result == ["openai", "openrouter", "ollama", "anthropic"]

    def test_inserts_local_before_openrouter_when_priority(self):
        """Should insert local before OpenRouter when local_priority=True."""
        from aragora.agents.fallback import build_fallback_chain_with_local
        from unittest.mock import patch

        with patch(
            "aragora.agents.fallback.get_local_fallback_providers",
            return_value=["ollama", "lm-studio"],
        ):
            result = build_fallback_chain_with_local(
                primary_providers=["openai", "openrouter", "anthropic"],
                include_local=True,
                local_priority=True,
            )
            # Local should come before openrouter
            assert result == ["openai", "ollama", "lm-studio", "openrouter", "anthropic"]

    def test_appends_local_at_end_when_no_openrouter(self):
        """Should append local at end when no OpenRouter in chain."""
        from aragora.agents.fallback import build_fallback_chain_with_local
        from unittest.mock import patch

        with patch("aragora.agents.fallback.get_local_fallback_providers", return_value=["ollama"]):
            result = build_fallback_chain_with_local(
                primary_providers=["openai", "anthropic"],
                include_local=True,
            )
            assert result == ["openai", "anthropic", "ollama"]

    def test_deduplicates_providers(self):
        """Should deduplicate providers in result."""
        from aragora.agents.fallback import build_fallback_chain_with_local
        from unittest.mock import patch

        # If local provider is already in primary, should dedupe
        with patch("aragora.agents.fallback.get_local_fallback_providers", return_value=["ollama"]):
            result = build_fallback_chain_with_local(
                primary_providers=["openai", "ollama", "openrouter"],
                include_local=True,
            )
            # ollama should only appear once
            assert result.count("ollama") == 1


class TestGetLocalFallbackProviders:
    """Tests for get_local_fallback_providers function."""

    def test_returns_available_agents(self):
        """Should return only available local agents."""
        from unittest.mock import patch, MagicMock
        import aragora.agents.fallback as fallback_module

        mock_registry = MagicMock()
        mock_registry.detect_local_agents.return_value = [
            {"name": "ollama", "available": True},
            {"name": "lm-studio", "available": False},
            {"name": "local-ai", "available": True},
        ]

        # Patch the module-level AgentRegistry reference in fallback module
        with patch.object(fallback_module, "_AgentRegistry", mock_registry):
            result = fallback_module.get_local_fallback_providers()
            assert result == ["ollama", "local-ai"]

    def test_returns_empty_on_error(self):
        """Should return empty list on error."""
        import aragora.agents.fallback as fallback_module
        from unittest.mock import patch, MagicMock

        # Patch _AgentRegistry to raise an error on detect_local_agents
        mock_registry = MagicMock()
        mock_registry.detect_local_agents.side_effect = OSError("test error")

        with patch.object(fallback_module, "_AgentRegistry", mock_registry):
            result = fallback_module.get_local_fallback_providers()
            assert result == []


class TestIsLocalLLMAvailable:
    """Tests for is_local_llm_available function."""

    def test_returns_true_when_available(self):
        """Should return True when any local LLM is available."""
        from unittest.mock import patch, MagicMock
        import aragora.agents.fallback as fallback_module

        mock_registry = MagicMock()
        mock_registry.get_local_status.return_value = {"any_available": True}

        # Patch the module-level AgentRegistry reference in fallback module
        with patch.object(fallback_module, "_AgentRegistry", mock_registry):
            assert fallback_module.is_local_llm_available() is True

    def test_returns_false_when_unavailable(self):
        """Should return False when no local LLM is available."""
        from unittest.mock import patch, MagicMock
        import aragora.agents.fallback as fallback_module

        mock_registry = MagicMock()
        mock_registry.get_local_status.return_value = {"any_available": False}

        # Patch the module-level _AgentRegistry reference in fallback module
        with patch.object(fallback_module, "_AgentRegistry", mock_registry):
            assert fallback_module.is_local_llm_available() is False

    def test_returns_false_on_error(self):
        """Should return False on any error."""
        import aragora.agents.fallback as fallback_module
        from unittest.mock import patch, MagicMock

        # Patch _AgentRegistry to raise an error on get_local_status
        mock_registry = MagicMock()
        mock_registry.get_local_status.side_effect = OSError("test error")

        with patch.object(fallback_module, "_AgentRegistry", mock_registry):
            result = fallback_module.is_local_llm_available()
            assert result is False


class TestProviderRegistration:
    """Tests for provider registration behavior."""

    def test_registers_provider_not_in_chain(self):
        """Should register provider even if not in chain (logs warning)."""
        chain = AgentFallbackChain(providers=["openai"])

        # Should not raise, just log warning
        chain.register_provider("unknown", lambda: MockAgent("unknown"))

        # Provider should still be registered
        assert "unknown" in chain._provider_factories

    def test_get_agent_returns_none_for_unregistered(self):
        """Should return None for unregistered provider."""
        chain = AgentFallbackChain(providers=["openai"])
        assert chain._get_agent("openai") is None

    def test_get_agent_caches_instance(self):
        """Should cache created agent instances."""
        chain = AgentFallbackChain(providers=["openai"])
        agent = MockAgent("openai")
        chain.register_provider("openai", lambda: agent)

        # First call creates and caches
        result1 = chain._get_agent("openai")
        assert result1 is agent

        # Second call returns cached
        result2 = chain._get_agent("openai")
        assert result2 is agent

    def test_get_agent_handles_factory_error(self):
        """Should return None if factory raises error."""
        chain = AgentFallbackChain(providers=["openai"])

        def failing_factory():
            raise ValueError("Factory failed")

        chain.register_provider("openai", failing_factory)
        assert chain._get_agent("openai") is None


class TestStreamSkipsNonStreamingProviders:
    """Tests for stream fallback skipping non-streaming providers."""

    @pytest.mark.asyncio
    async def test_skips_provider_without_stream_method(self):
        """Should skip providers that don't support streaming."""
        chain = AgentFallbackChain(providers=["no-stream", "has-stream"])

        class NoStreamAgent:
            async def generate(self, prompt, context=None):
                return "result"

            # No generate_stream method

        class StreamAgent:
            async def generate(self, prompt, context=None):
                return "result"

            async def generate_stream(self, prompt, context=None):
                yield "streaming"

        chain.register_provider("no-stream", lambda: NoStreamAgent())
        chain.register_provider("has-stream", lambda: StreamAgent())

        tokens = []
        async for token in chain.generate_stream("test"):
            tokens.append(token)

        assert tokens == ["streaming"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
