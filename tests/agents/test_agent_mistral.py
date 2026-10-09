"""
Tests for MistralAPIAgent and CodestralAgent.

Tests:
- Agent initialization and configuration
- Successful generation (mock response)
- Rate limit handling (429 → fallback to OpenRouter)
- Streaming with various conditions
- Quota error detection
- Codestral variant
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.agents.api_agents.mistral import MistralAPIAgent, CodestralAgent
from aragora.agents.api_agents.common import AgentStreamError
from tests.utils.aiohttp_mocks import make_mock_client_session, make_mock_response


class TestMistralAgentInitialization:
    """Tests for MistralAPIAgent initialization."""

    def test_default_initialization(self):
        """Test agent initializes with defaults."""
        with patch.dict("os.environ", {"MISTRAL_API_KEY": "test-key"}):
            agent = MistralAPIAgent()

        assert agent.name == "mistral-api"
        assert agent.role == "proposer"
        assert agent.agent_type == "mistral"
        assert agent.timeout == 180  # Increased default for complex responses
        # Fallback is enabled by default for graceful degradation
        assert agent.enable_fallback is True

    def test_custom_initialization(self):
        """Test agent with custom parameters."""
        agent = MistralAPIAgent(
            name="my-mistral",
            model="mistral-small-latest",
            role="critic",
            timeout=60,
            api_key="custom-key",
            enable_fallback=False,
        )

        assert agent.name == "my-mistral"
        assert agent.model == "mistral-small-latest"
        assert agent.role == "critic"
        assert agent.timeout == 60
        assert agent.enable_fallback is False

    def test_base_url_configured(self):
        """Test base URL is set to Mistral API."""
        agent = MistralAPIAgent(api_key="test-key")
        assert "api.mistral.ai" in agent.base_url

    def test_fallback_agent_lazy_loading(self):
        """Test fallback agent is lazy-loaded via mixin."""
        agent = MistralAPIAgent(api_key="test-key")
        assert agent._fallback_agent is None

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
            fallback = agent._get_cached_fallback_agent()
            assert fallback is not None
            assert "fallback" in fallback.name


class TestCodestralAgentInitialization:
    """Tests for CodestralAgent initialization."""

    def test_default_initialization(self):
        """Test Codestral initializes with correct defaults."""
        with patch.dict("os.environ", {"MISTRAL_API_KEY": "test-key"}):
            agent = CodestralAgent()

        assert agent.name == "codestral"
        assert agent.model == "codestral-latest"
        assert agent.agent_type == "codestral"

    def test_custom_initialization(self):
        """Test Codestral with custom name."""
        agent = CodestralAgent(
            name="my-codestral",
            role="critic",
            api_key="custom-key",
        )

        assert agent.name == "my-codestral"
        assert agent.role == "critic"


class TestMistralQuotaErrorDetection:
    """Tests for quota/rate limit error detection."""

    def test_429_is_quota_error(self):
        """Test 429 status is detected as quota error."""
        agent = MistralAPIAgent(api_key="test-key")
        assert agent.is_quota_error(429, "Rate limited") is True

    def test_rate_limit_exceeded_message(self):
        """Test rate limit message is detected."""
        agent = MistralAPIAgent(api_key="test-key")
        assert agent.is_quota_error(429, "rate_limit_exceeded") is True

    def test_regular_error_not_quota(self):
        """Test regular errors are not detected as quota errors."""
        agent = MistralAPIAgent(api_key="test-key")
        assert agent.is_quota_error(400, "Invalid request") is False
        assert agent.is_quota_error(500, "Internal server error") is False


class TestMistralGenerate:
    """Tests for the generate method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return MistralAPIAgent(
            name="test-mistral",
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
                "choices": [{"message": {"content": "Hello from Mistral!"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await agent.generate("Test prompt")

        assert result == "Hello from Mistral!"

    @pytest.mark.asyncio
    async def test_token_usage_recorded(self, agent):
        """Test that token usage is recorded from response."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "choices": [{"message": {"content": "Response"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch.object(agent, "_record_token_usage") as mock_record:
                await agent.generate("Test prompt")
                mock_record.assert_called_once_with(tokens_in=100, tokens_out=50)

    @pytest.mark.asyncio
    async def test_quota_error_triggers_fallback(self):
        """Test quota error triggers fallback to OpenRouter."""
        agent = MistralAPIAgent(
            name="test-mistral",
            api_key="test-key",
            enable_fallback=True,
        )

        mock_mistral_response = MagicMock()
        mock_mistral_response.status = 429
        mock_mistral_response.text = AsyncMock(return_value="Rate limit exceeded")

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_mistral_response),
                __aexit__=AsyncMock(return_value=False),
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

    @pytest.mark.asyncio
    async def test_context_included_in_prompt(self, agent):
        """Test that context is included in the prompt."""
        from aragora.agents.api_agents.common import Message

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "choices": [{"message": {"content": "Response with context"}}],
                "usage": {},
            }
        )

        captured_payload = None

        def capture_post(*args, **kwargs):
            nonlocal captured_payload
            captured_payload = kwargs.get("json", {})
            return MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = capture_post

        context = [
            Message(agent="user", role="human", content="Previous message"),
        ]

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await agent.generate("New prompt", context=context)

        assert captured_payload is not None
        user_content = captured_payload["messages"][0]["content"]
        assert "Previous message" in user_content or "Previous discussion" in user_content


class TestMistralStreaming:
    """Tests for streaming generation."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return MistralAPIAgent(
            name="test-mistral",
            api_key="test-key",
            enable_fallback=False,
        )

    @pytest.mark.asyncio
    async def test_streaming_quota_error_triggers_fallback(self):
        """Test streaming quota error triggers fallback."""
        agent = MistralAPIAgent(
            name="test-mistral",
            api_key="test-key",
            enable_fallback=True,
        )

        mock_response = MagicMock()
        mock_response.status = 429
        mock_response.text = AsyncMock(return_value="Rate limit exceeded")

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
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

    @pytest.mark.asyncio
    async def test_streaming_error_handled(self, agent):
        """Test streaming with a non-quota 5xx raises AgentStreamError."""
        mock_response = make_mock_response(status=500, text="Server Error")
        mock_session = make_mock_client_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            chunks: list[str] = []
            with pytest.raises(AgentStreamError, match="streaming API error 500"):
                async for chunk in agent.generate_stream("Test"):
                    chunks.append(chunk)
            # The error is raised before any stream data is read, so nothing is yielded.
            assert chunks == []


class TestMistralCritique:
    """Tests for the critique method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return MistralAPIAgent(
            name="test-mistral",
            api_key="test-key",
        )

    @pytest.mark.asyncio
    async def test_critique_calls_generate(self, agent):
        """Test critique uses generate method."""
        mock_response = """ISSUES:
- Issue 1
- Issue 2

SUGGESTIONS:
- Suggestion 1

SEVERITY: 0.7
REASONING: Test reasoning"""

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = mock_response
            critique = await agent.critique("Test proposal", "Test task")

        assert mock_generate.called
        assert critique is not None
        assert hasattr(critique, "issues")
        assert hasattr(critique, "suggestions")
        assert hasattr(critique, "severity")


class TestMistralModelMapping:
    """Tests for OpenRouter model mapping.

    MistralAPIAgent no longer carries a static OPENROUTER_MODEL_MAP:
    get_fallback_model() (QuotaFallbackMixin) resolves the current model
    through the catalog and upgrade map instead (frontier-model-refresh,
    2026-09-04 review fix round 1, item 3).
    """

    def test_model_mapping_exists(self):
        """A legacy Mistral spelling (catalog alias) resolves to its own
        OpenRouter slug."""
        agent = MistralAPIAgent(api_key="test-key", model="mistral-large-latest")
        assert agent.get_fallback_model() == "mistralai/mistral-large-2512"

    def test_fallback_uses_correct_model(self):
        """ "codestral-latest" has no catalog row: falls back to
        DEFAULT_FALLBACK_MODEL (the Mistral frontier)."""
        agent = MistralAPIAgent(
            api_key="test-key",
            model="codestral-latest",
        )

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
            fallback = agent._get_cached_fallback_agent()
            assert fallback.model == agent.DEFAULT_FALLBACK_MODEL

    def test_default_fallback_model(self):
        """Test unmapped model uses default fallback."""
        agent = MistralAPIAgent(
            api_key="test-key",
            model="mistral-unknown-model",
        )

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
            fallback = agent._get_cached_fallback_agent()
            assert fallback.model == agent.DEFAULT_FALLBACK_MODEL


class TestCodestralGenerate:
    """Tests for Codestral agent generation."""

    @pytest.fixture
    def agent(self):
        """Create test Codestral agent."""
        return CodestralAgent(
            name="test-codestral",
            api_key="test-key",
        )

    @pytest.mark.asyncio
    async def test_successful_generation(self, agent):
        """Test Codestral successful generation."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "choices": [{"message": {"content": "def hello(): return 'world'"}}],
                "usage": {},
            }
        )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            result = await agent.generate("Write a hello function")

        assert "def hello" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
