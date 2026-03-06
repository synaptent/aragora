"""
Tests for GrokAgent (xAI's Grok API).

Tests:
- Agent initialization and configuration
- Successful generation (mock response)
- Rate limit handling (429 → fallback to OpenRouter)
- Streaming with various conditions
- Quota error detection
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.agents.api_agents.grok import GrokAgent


class TestGrokAgentInitialization:
    """Tests for GrokAgent initialization."""

    def test_default_initialization(self):
        """Test agent initializes with defaults."""
        with patch.dict("os.environ", {"XAI_API_KEY": "test-key"}):
            agent = GrokAgent()

        assert agent.name == "grok"
        assert agent.role == "proposer"
        assert agent.agent_type == "grok"
        assert agent.timeout == 120
        # Fallback is enabled by default for graceful degradation
        assert agent.enable_fallback is True

    def test_custom_initialization(self):
        """Test agent with custom parameters."""
        agent = GrokAgent(
            name="my-grok",
            model="grok-2",
            role="critic",
            timeout=60,
            api_key="custom-key",
            enable_fallback=False,
        )

        assert agent.name == "my-grok"
        assert agent.model == "grok-2"
        assert agent.role == "critic"
        assert agent.timeout == 60
        assert agent.enable_fallback is False

    def test_base_url_configured(self):
        """Test base URL is set to xAI API."""
        agent = GrokAgent(api_key="test-key")
        assert "api.x.ai" in agent.base_url

    def test_fallback_agent_lazy_loading(self):
        """Test fallback agent is lazy-loaded via mixin."""
        agent = GrokAgent(api_key="test-key")
        assert agent._fallback_agent is None

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
            fallback = agent._get_cached_fallback_agent()
            assert fallback is not None
            assert "fallback" in fallback.name

    def test_alternate_api_key_env_var(self):
        """Test GROK_API_KEY can be used as fallback."""
        with patch(
            "aragora.agents.api_agents.common.get_api_key",
            side_effect=lambda *args, **kwargs: "grok-key",
        ):
            agent = GrokAgent()
            assert agent.api_key == "grok-key"


class TestGrokQuotaErrorDetection:
    """Tests for quota/rate limit error detection."""

    def test_429_is_quota_error(self):
        """Test 429 status is detected as quota error."""
        agent = GrokAgent(api_key="test-key")
        assert agent.is_quota_error(429, "Rate limited") is True

    def test_rate_limit_exceeded_message(self):
        """Test rate limit message is detected."""
        agent = GrokAgent(api_key="test-key")
        assert agent.is_quota_error(429, "rate limit exceeded") is True

    def test_regular_error_not_quota(self):
        """Test regular errors are not detected as quota errors."""
        agent = GrokAgent(api_key="test-key")
        assert agent.is_quota_error(400, "Invalid request") is False
        assert agent.is_quota_error(500, "Internal server error") is False


class TestGrokGenerate:
    """Tests for the generate method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return GrokAgent(
            name="test-grok",
            api_key="test-key",
            enable_fallback=False,
        )

    @pytest.mark.asyncio
    async def test_successful_generation(self, agent):
        """Test successful API response."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "choices": [{"message": {"content": "Hello from Grok!"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock()
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await agent.generate("Test prompt")

        assert result == "Hello from Grok!"

    @pytest.mark.asyncio
    async def test_quota_error_triggers_fallback(self):
        """Test quota error triggers fallback to OpenRouter."""
        agent = GrokAgent(
            name="test-grok",
            api_key="test-key",
            enable_fallback=True,
        )

        mock_grok_response = MagicMock()
        mock_grok_response.status = 429
        mock_grok_response.text = AsyncMock(return_value="Rate limit exceeded")

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_grok_response), __aexit__=AsyncMock()
            )
        )

        mock_fallback = AsyncMock()
        mock_fallback.generate = AsyncMock(return_value="Fallback response")

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
                with patch.object(agent, "_get_cached_fallback_agent", return_value=mock_fallback):
                    result = await agent.generate("Test prompt")

        assert result == "Fallback response"
        mock_fallback.generate.assert_called_once()


class TestGrokStreaming:
    """Tests for streaming generation."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return GrokAgent(
            name="test-grok",
            api_key="test-key",
            enable_fallback=False,
        )

    @pytest.mark.asyncio
    async def test_streaming_quota_error_triggers_fallback(self):
        """Test streaming quota error triggers fallback."""
        agent = GrokAgent(
            name="test-grok",
            api_key="test-key",
            enable_fallback=True,
        )

        mock_response = MagicMock()
        mock_response.status = 429
        mock_response.text = AsyncMock(return_value="Rate limit exceeded")

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response), __aexit__=AsyncMock()
            )
        )

        async def fallback_stream():
            yield "Fallback"
            yield " stream"

        mock_fallback = AsyncMock()
        mock_fallback.generate_stream = MagicMock(return_value=fallback_stream())

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
                with patch.object(agent, "_get_cached_fallback_agent", return_value=mock_fallback):
                    chunks = []
                    async for chunk in agent.generate_stream("Test"):
                        chunks.append(chunk)

        assert "Fallback" in "".join(chunks)


class TestGrokCritique:
    """Tests for the critique method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return GrokAgent(
            name="test-grok",
            api_key="test-key",
        )

    @pytest.mark.asyncio
    async def test_critique_calls_generate(self, agent):
        """Test critique uses generate method."""
        mock_response = """ISSUES:
- Issue 1

SUGGESTIONS:
- Suggestion 1

SEVERITY: 0.5
REASONING: Test reasoning"""

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = mock_response
            critique = await agent.critique("Test proposal", "Test task")

        assert mock_generate.called
        assert critique is not None


class TestGrokModelMapping:
    """Tests for OpenRouter model mapping."""

    def test_model_mapping_exists(self):
        """Test model mapping dictionary exists and has entries."""
        agent = GrokAgent(api_key="test-key")
        assert len(agent.OPENROUTER_MODEL_MAP) > 0
        assert "grok-3" in agent.OPENROUTER_MODEL_MAP

    def test_fallback_uses_correct_model(self):
        """Test fallback agent uses mapped model via mixin."""
        agent = GrokAgent(
            api_key="test-key",
            model="grok-beta",
        )

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
            fallback = agent._get_cached_fallback_agent()
            assert fallback.model == "x-ai/grok-beta"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
