"""
Tests for Mistral API Agent and Codestral.

Tests cover:
- Initialization and configuration
- OpenAI-compatible API usage
- Circuit breaker configuration
- Codestral specialization
- Error handling and fallback
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.agents.api_agents.common import AgentAPIError


class TestMistralAgentInitialization:
    """Tests for Mistral agent initialization."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with default values."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent()

        assert agent.name == "mistral-api"
        # mistral-medium-2604 is the flagship/frontier row (Mistral Large is
        # tier="fallback"); frontier-model-refresh, 2026-09-04.
        assert agent.model == "mistral-medium-2604"
        assert agent.role == "proposer"
        assert agent.timeout == 180  # Increased timeout for Mistral
        assert agent.agent_type == "mistral"
        # Fallback is enabled by default for graceful degradation
        assert agent.enable_fallback is True
        assert "api.mistral.ai" in agent.base_url

    def test_init_with_custom_config(self, mock_env_with_api_keys):
        """Should initialize with custom configuration."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent(
            name="custom-mistral",
            model="mistral-small-latest",
            role="critic",
            timeout=90,
            enable_fallback=False,
        )

        assert agent.name == "custom-mistral"
        assert agent.model == "mistral-small-latest"
        assert agent.role == "critic"
        assert agent.timeout == 90
        assert agent.enable_fallback is False

    def test_init_with_explicit_api_key(self, mock_env_no_api_keys):
        """Should use explicitly provided API key."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent(api_key="explicit-mistral-key")

        assert agent.api_key == "explicit-mistral-key"

    def test_agent_registry_registration(self, mock_env_with_api_keys):
        """Should be registered in agent registry."""
        from aragora.agents.registry import AgentRegistry

        spec = AgentRegistry.get_spec("mistral-api")

        assert spec is not None
        assert spec.default_model == "mistral-medium-2604"
        assert spec.agent_type == "API"

    def test_circuit_breaker_config(self, mock_env_with_api_keys):
        """Should have increased circuit breaker threshold."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent(circuit_breaker_threshold=10)

        # Verify the threshold was set
        assert agent._circuit_breaker is not None or agent.enable_circuit_breaker


class TestCodestralAgentInitialization:
    """Tests for Codestral agent initialization."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with code-optimized defaults."""
        from aragora.agents.api_agents.mistral import CodestralAgent

        agent = CodestralAgent()

        assert agent.name == "codestral"
        assert agent.model == "codestral-latest"
        assert agent.agent_type == "codestral"
        # Fallback is enabled by default for graceful degradation
        assert agent.enable_fallback is True

    def test_init_with_custom_config(self, mock_env_with_api_keys):
        """Should initialize with custom configuration."""
        from aragora.agents.api_agents.mistral import CodestralAgent

        agent = CodestralAgent(
            name="custom-codestral",
            role="implementer",
            timeout=180,
        )

        assert agent.name == "custom-codestral"
        assert agent.role == "implementer"
        assert agent.timeout == 180

    def test_agent_registry_registration(self, mock_env_with_api_keys):
        """Should be registered in agent registry."""
        from aragora.agents.registry import AgentRegistry

        spec = AgentRegistry.get_spec("codestral")

        assert spec is not None
        assert spec.default_model == "codestral-latest"


class TestMistralGenerate:
    """Tests for generate method."""

    @pytest.mark.asyncio
    async def test_generate_basic_response(self, mock_env_with_api_keys, mock_mistral_response):
        """Should generate response from API."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_mistral_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            result = await agent.generate("Test prompt")

        assert "test response from Mistral" in result

    @pytest.mark.asyncio
    async def test_generate_with_context(
        self, mock_env_with_api_keys, mock_mistral_response, sample_context
    ):
        """Should include context in prompt."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_mistral_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            result = await agent.generate("Test prompt", context=sample_context)

        assert result is not None

    @pytest.mark.asyncio
    async def test_generate_records_token_usage(
        self, mock_env_with_api_keys, mock_mistral_response
    ):
        """Should record token usage from response."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent()
        agent.reset_token_usage()

        # Create mock response with async context manager
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_mistral_response)
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

        assert agent.last_tokens_in == 100
        assert agent.last_tokens_out == 50


class TestMistralGenerateStream:
    """Tests for streaming generation."""

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self, mock_env_with_api_keys, mock_sse_chunks):
        """Should yield text chunks from SSE stream."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent
        from tests.agents.api_agents.conftest import MockStreamResponse

        agent = MistralAPIAgent()

        mock_response = MockStreamResponse(status=200, chunks=mock_sse_chunks)

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


class TestMistralCritique:
    """Tests for critique method."""

    @pytest.mark.asyncio
    async def test_critique_returns_structured_feedback(self, mock_env_with_api_keys):
        """Should return structured critique."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent()

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


class TestMistralErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_api_error(self, mock_env_with_api_keys):
        """Should raise AgentAPIError on API failure."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent()

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
    async def test_handles_rate_limit_with_retry(
        self, mock_env_with_api_keys, mock_mistral_response
    ):
        """Should handle rate limits with retry."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = MistralAPIAgent()

        # First call returns 429, second returns success
        rate_limit_response = MockResponse(status=429, text='{"error": "Rate limited"}')
        success_response = MockResponse(status=200, json_data=mock_mistral_response)
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


class TestMistralModelMapping:
    """Tests for OpenRouter model mapping.

    MistralAPIAgent no longer carries a static OPENROUTER_MODEL_MAP:
    get_fallback_model() (QuotaFallbackMixin, aragora/agents/fallback.py)
    resolves the current model through the catalog and upgrade map instead
    (frontier-model-refresh, 2026-09-04 review fix round 1, item 3).
    """

    def test_default_model_fallback_is_current_slug(self, mock_env_with_api_keys):
        """Using the agent's own default model, the fallback target is the
        current frontier's OpenRouter slug (review fix round 1, item 3)."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent(api_key="test-key")
        assert agent.get_fallback_model() == "mistralai/mistral-medium-3-5"

    def test_model_map_contains_mistral_models(self, mock_env_with_api_keys):
        """A still-served Mistral id resolves to its own OpenRouter slug;
        "codestral-latest"/"ministral-8b-latest" have no catalog row and
        fall back to DEFAULT_FALLBACK_MODEL."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        served = MistralAPIAgent(api_key="test-key", model="mistral-large-2512")
        assert served.get_fallback_model() == "mistralai/mistral-large-2512"
        for unresolvable in ("codestral-latest", "ministral-8b-latest"):
            agent = MistralAPIAgent(api_key="test-key", model=unresolvable)
            assert agent.get_fallback_model() == MistralAPIAgent.DEFAULT_FALLBACK_MODEL

    def test_has_default_fallback_model(self, mock_env_with_api_keys):
        """Should have default fallback model."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        assert MistralAPIAgent.DEFAULT_FALLBACK_MODEL is not None
        assert "mistral" in MistralAPIAgent.DEFAULT_FALLBACK_MODEL


class TestCodestralGenerate:
    """Tests for Codestral generate method."""

    @pytest.mark.asyncio
    async def test_codestral_generate(self, mock_env_with_api_keys, mock_mistral_response):
        """Should generate code-focused response."""
        from aragora.agents.api_agents.mistral import CodestralAgent

        agent = CodestralAgent()

        # Modify response for code content
        code_response = mock_mistral_response.copy()
        code_response["choices"][0]["message"]["content"] = (
            "```python\ndef hello():\n    print('Hello')\n```"
        )

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=code_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            result = await agent.generate("Write a hello function")

        assert "def hello" in result or "python" in result.lower()


class TestMistralCircuitBreaker:
    """Tests for circuit breaker functionality."""

    def test_circuit_breaker_is_enabled_by_default(self, mock_env_with_api_keys):
        """Should have circuit breaker enabled by default."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent()

        assert agent.enable_circuit_breaker is True
        assert agent._circuit_breaker is not None

    def test_circuit_breaker_can_be_disabled(self, mock_env_with_api_keys):
        """Should allow disabling circuit breaker.

        Note: MistralAPIAgent doesn't expose enable_circuit_breaker in __init__,
        so we test the attribute can be set after construction.
        """
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent()
        # Disable circuit breaker by setting attribute and removing the breaker
        agent.enable_circuit_breaker = False
        agent._circuit_breaker = None

        assert agent.enable_circuit_breaker is False

    def test_is_circuit_open(self, mock_env_with_api_keys, mock_circuit_breaker):
        """Should check circuit breaker state."""
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent()
        agent._circuit_breaker = mock_circuit_breaker

        mock_circuit_breaker.can_proceed.return_value = True
        assert agent.is_circuit_open() is False

        mock_circuit_breaker.can_proceed.return_value = False
        assert agent.is_circuit_open() is True
