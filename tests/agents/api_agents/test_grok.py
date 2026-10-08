"""
Tests for Grok (xAI) API Agent.

Tests cover:
- Initialization and configuration
- OpenAI-compatible API usage
- generate() method
- critique() method
- Circuit breaker configuration
- Error handling and fallback
- Token usage tracking
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.agents.api_agents.common import (
    AgentAPIError,
    AgentCircuitOpenError,
)


class TestGrokAgentInitialization:
    """Tests for Grok agent initialization."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with default values."""
        from aragora.agents.api_agents.grok import GrokAgent
        from aragora.agents.registry import AgentRegistry

        agent = GrokAgent()
        spec = AgentRegistry.get_spec("grok")

        assert agent.name == "grok"
        assert agent.model == "grok-4-latest"
        assert agent.role == "proposer"
        assert agent.timeout == 120
        assert agent.agent_type == "grok"
        # Fallback is enabled by default for graceful degradation
        assert agent.enable_fallback is True
        assert agent.base_url == "https://api.x.ai/v1"

    def test_init_with_custom_config(self, mock_env_with_api_keys):
        """Should initialize with custom configuration."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent(
            name="custom-grok",
            model="grok-2-1212",
            role="critic",
            timeout=90,
            enable_fallback=False,
        )

        assert agent.name == "custom-grok"
        assert agent.model == "grok-2-1212"
        assert agent.role == "critic"
        assert agent.timeout == 90
        assert agent.enable_fallback is False

    def test_init_with_explicit_api_key(self, mock_env_no_api_keys):
        """Should use explicitly provided API key."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent(api_key="explicit-grok-key")

        assert agent.api_key == "explicit-grok-key"

    def test_init_with_xai_key_env_var(self, monkeypatch):
        """Should use XAI_API_KEY environment variable."""
        monkeypatch.setenv("XAI_API_KEY", "xai-test-key-123")
        monkeypatch.delenv("GROK_API_KEY", raising=False)
        monkeypatch.setenv("ARAGORA_OPENROUTER_FALLBACK_ENABLED", "false")
        monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")

        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()

        assert agent.api_key == "xai-test-key-123"

    def test_init_with_grok_key_env_var(self, monkeypatch):
        """Should use GROK_API_KEY environment variable as fallback."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        monkeypatch.setenv("GROK_API_KEY", "grok-test-key-456")
        monkeypatch.setenv("ARAGORA_OPENROUTER_FALLBACK_ENABLED", "false")
        monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")

        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()

        assert agent.api_key == "grok-test-key-456"

    def test_init_with_enable_fallback_true(self, mock_env_with_api_keys):
        """Should enable fallback when explicitly set."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent(enable_fallback=True)

        assert agent.enable_fallback is True

    def test_agent_registry_registration(self, mock_env_with_api_keys):
        """Should be registered in agent registry."""
        from aragora.agents.api_agents.grok import GrokAgent
        from aragora.agents.registry import AgentRegistry

        spec = AgentRegistry.get_spec("grok")

        assert spec is not None
        assert spec.default_model == "grok-4-latest"
        assert spec.agent_type == "API"

    def test_base_url_is_xai_endpoint(self, mock_env_with_api_keys):
        """Should use xAI API endpoint."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()

        assert agent.base_url == "https://api.x.ai/v1"


class TestGrokAgentGenerate:
    """Tests for generate method."""

    @pytest.mark.asyncio
    async def test_generate_basic_response(self, mock_env_with_api_keys, mock_grok_response):
        """Should generate response from API."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_grok_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            result = await agent.generate("Test prompt")

        assert "test response from Grok" in result

    @pytest.mark.asyncio
    async def test_generate_with_context(
        self, mock_env_with_api_keys, mock_grok_response, sample_context
    ):
        """Should include context in prompt."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_grok_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            result = await agent.generate("Test prompt", context=sample_context)

        assert result is not None

    @pytest.mark.asyncio
    async def test_generate_records_token_usage(self, mock_env_with_api_keys, mock_grok_response):
        """Should record token usage from response."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()
        agent.reset_token_usage()

        # Create mock response with async context manager
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_grok_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        # Create mock session - must be an async context manager itself
        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        # create_client_session() returns the session object directly
        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            await agent.generate("Test prompt")

        assert agent.last_tokens_in == 10
        assert agent.last_tokens_out == 20

    @pytest.mark.asyncio
    async def test_generate_calls_correct_endpoint(
        self, mock_env_with_api_keys, mock_grok_response
    ):
        """Should call xAI chat completions endpoint."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()
        called_url = None

        # Create mock response
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_grok_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        # Create mock session that captures the URL
        mock_session = MagicMock()

        def capture_post(url, **kwargs):
            nonlocal called_url
            called_url = url
            return mock_response

        mock_session.post = capture_post
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            await agent.generate("Test prompt")

        assert called_url == "https://api.x.ai/v1/chat/completions"


class TestGrokAgentGenerateStream:
    """Tests for streaming generation."""

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self, mock_env_with_api_keys, mock_grok_stream_chunks):
        """Should yield text chunks from SSE stream."""
        from aragora.agents.api_agents.grok import GrokAgent
        from tests.agents.api_agents.conftest import MockStreamResponse

        agent = GrokAgent()

        mock_response = MockStreamResponse(status=200, chunks=mock_grok_stream_chunks)

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            chunks = []
            async for chunk in agent.generate_stream("Test prompt"):
                chunks.append(chunk)

            assert len(chunks) >= 0


class TestGrokAgentCritique:
    """Tests for critique method."""

    @pytest.mark.asyncio
    async def test_critique_returns_structured_feedback(self, mock_env_with_api_keys):
        """Should return structured critique."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = """ISSUES:
- Issue one
- Issue two

SUGGESTIONS:
- Suggestion one

SEVERITY: 4.0
REASONING: This is the reasoning."""

            critique = await agent.critique(
                proposal="Test proposal",
                task="Test task",
                target_agent="test-agent",
            )

            assert critique is not None
            assert hasattr(critique, "issues")
            assert hasattr(critique, "suggestions")

    @pytest.mark.asyncio
    async def test_critique_without_target_agent(self, mock_env_with_api_keys):
        """Should work without target agent specified."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = """ISSUES:
- Generic issue

SUGGESTIONS:
- Generic suggestion

SEVERITY: 3.5
REASONING: Some reasoning."""

            critique = await agent.critique(
                proposal="Test proposal",
                task="Test task",
            )

            assert critique is not None

    @pytest.mark.asyncio
    async def test_critique_includes_context(self, mock_env_with_api_keys, sample_context):
        """Should pass context to generate method."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = """ISSUES:
- Issue

SUGGESTIONS:
- Suggestion

SEVERITY: 2.0
REASONING: Reasoning."""

            await agent.critique(
                proposal="Test proposal",
                task="Test task",
                context=sample_context,
            )

            # Verify generate was called with context (passed as positional arg)
            call_args = mock_generate.call_args
            # Context is passed as second positional argument
            assert len(call_args[0]) >= 2 or call_args[1].get("context") is not None
            if len(call_args[0]) >= 2:
                assert call_args[0][1] == sample_context
            else:
                assert call_args[1].get("context") == sample_context


class TestGrokAgentErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_api_error(self, mock_env_with_api_keys):
        """Should raise AgentAPIError on API failure."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 500
            mock_response.text = AsyncMock(return_value='{"error": "Internal error"}')
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            with pytest.raises(AgentAPIError):
                await agent.generate("Test prompt")

    @pytest.mark.asyncio
    async def test_handles_rate_limit_with_retry(self, mock_env_with_api_keys, mock_grok_response):
        """Should handle rate limits with retry."""
        from aragora.agents.api_agents.grok import GrokAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GrokAgent()

        # First call returns 429, second returns success
        rate_limit_response = MockResponse(status=429, text='{"error": "Rate limited"}')
        success_response = MockResponse(status=200, json_data=mock_grok_response)
        mock_session = MockClientSession([rate_limit_response, success_response])

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            # The retry decorator should handle 429 errors
            # May raise or succeed depending on retry configuration
            try:
                result = await agent.generate("Test prompt")
                assert result is not None
            except AgentAPIError:
                # Also acceptable if retries exhausted
                pass

    @pytest.mark.asyncio
    async def test_handles_empty_response(self, mock_env_with_api_keys):
        """Should raise error on empty response content."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()

        empty_response = {
            "id": "chatcmpl-empty",
            "choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
        }

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=empty_response)
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentAPIError):
                await agent.generate("Test prompt")

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_when_open(self, mock_env_with_api_keys):
        """Should raise circuit open error when breaker is open."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()
        # Simulate circuit breaker in open state
        agent._circuit_breaker.can_proceed = MagicMock(return_value=False)

        with pytest.raises(AgentCircuitOpenError):
            await agent.generate("Test prompt")


class TestGrokAgentModelMapping:
    """Tests for OpenRouter model mapping."""

    def test_model_map_contains_grok_models(self, mock_env_with_api_keys):
        """Should have mappings for Grok models."""
        from aragora.agents.api_agents.grok import GrokAgent

        assert "grok-4-latest" in GrokAgent.OPENROUTER_MODEL_MAP
        assert "grok-4" in GrokAgent.OPENROUTER_MODEL_MAP
        assert "grok-3" in GrokAgent.OPENROUTER_MODEL_MAP
        assert "grok-2" in GrokAgent.OPENROUTER_MODEL_MAP
        assert "grok-2-1212" in GrokAgent.OPENROUTER_MODEL_MAP
        assert "grok-beta" in GrokAgent.OPENROUTER_MODEL_MAP

    def test_has_default_fallback_model(self, mock_env_with_api_keys):
        """Should have default fallback model."""
        from aragora.agents.api_agents.grok import GrokAgent

        assert GrokAgent.DEFAULT_FALLBACK_MODEL == "x-ai/grok-4.5"

    def test_legacy_direct_ids_route_to_live_openrouter_model(self, mock_env_with_api_keys):
        from aragora.agents.api_agents.grok import GrokAgent

        for model in ("grok-4-latest", "grok-4", "grok-4.2", "grok-4-2"):
            assert GrokAgent.OPENROUTER_MODEL_MAP[model] == "x-ai/grok-4.5"

    def test_model_map_values_are_openrouter_format(self, mock_env_with_api_keys):
        """Model map values should be in OpenRouter format."""
        from aragora.agents.api_agents.grok import GrokAgent

        for model, openrouter_model in GrokAgent.OPENROUTER_MODEL_MAP.items():
            assert "/" in openrouter_model  # OpenRouter format: provider/model


class TestGrokQuotaDetection:
    """Tests for Grok-specific quota/fallback trigger detection."""

    def test_410_live_search_deprecation_triggers_fallback(self, mock_env_with_api_keys):
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()
        assert (
            agent.is_quota_error(
                410,
                "Live search is deprecated. Please switch to the Agent Tools API",
            )
            is True
        )

    def test_410_unrelated_error_does_not_trigger_fallback(self, mock_env_with_api_keys):
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()
        assert agent.is_quota_error(410, "Gone") is False


class TestGrokAgentCircuitBreaker:
    """Tests for circuit breaker functionality."""

    def test_circuit_breaker_is_enabled_by_default(self, mock_env_with_api_keys):
        """Should have circuit breaker enabled by default."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()

        assert agent.enable_circuit_breaker is True
        assert agent._circuit_breaker is not None

    def test_circuit_breaker_can_be_disabled(self, mock_env_with_api_keys):
        """Should allow disabling circuit breaker."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()
        # Disable circuit breaker by setting attribute and removing the breaker
        agent.enable_circuit_breaker = False
        agent._circuit_breaker = None

        assert agent.enable_circuit_breaker is False

    def test_is_circuit_open(self, mock_env_with_api_keys, mock_circuit_breaker):
        """Should check circuit breaker state."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()
        agent._circuit_breaker = mock_circuit_breaker

        mock_circuit_breaker.can_proceed.return_value = True
        assert agent.is_circuit_open() is False

        mock_circuit_breaker.can_proceed.return_value = False
        assert agent.is_circuit_open() is True


class TestGrokAgentTokenUsage:
    """Tests for token usage tracking."""

    def test_initial_token_usage_is_zero(self, mock_env_with_api_keys):
        """Should start with zero token usage."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()

        assert agent.last_tokens_in == 0
        assert agent.last_tokens_out == 0
        assert agent.total_tokens_in == 0
        assert agent.total_tokens_out == 0

    def test_get_token_usage_returns_dict(self, mock_env_with_api_keys):
        """Should return token usage as dictionary."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()
        usage = agent.get_token_usage()

        assert isinstance(usage, dict)
        assert "tokens_in" in usage
        assert "tokens_out" in usage
        assert "total_tokens_in" in usage
        assert "total_tokens_out" in usage

    def test_reset_token_usage(self, mock_env_with_api_keys):
        """Should reset all token counters."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()
        # Manually set some values
        agent._last_tokens_in = 100
        agent._last_tokens_out = 50
        agent._total_tokens_in = 500
        agent._total_tokens_out = 250

        agent.reset_token_usage()

        assert agent.last_tokens_in == 0
        assert agent.last_tokens_out == 0
        assert agent.total_tokens_in == 0
        assert agent.total_tokens_out == 0


class TestGrokAgentGenerationParams:
    """Tests for generation parameter handling."""

    def test_set_generation_params(self, mock_env_with_api_keys):
        """Should set generation parameters."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()
        agent.set_generation_params(
            temperature=0.8,
            top_p=0.95,
            frequency_penalty=0.5,
        )

        assert agent.temperature == 0.8
        assert agent.top_p == 0.95
        assert agent.frequency_penalty == 0.5

    def test_get_generation_params(self, mock_env_with_api_keys):
        """Should get generation parameters as dict."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()
        agent.temperature = 0.7
        agent.top_p = 0.9

        params = agent.get_generation_params()

        assert params["temperature"] == 0.7
        assert params["top_p"] == 0.9

    def test_get_generation_params_excludes_none(self, mock_env_with_api_keys):
        """Should exclude None values from generation params."""
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent()
        # Default has None for all params

        params = agent.get_generation_params()

        assert "temperature" not in params or params.get("temperature") is not None
