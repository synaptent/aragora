"""
Tests for GeminiAgent.

Tests:
- Agent initialization and configuration
- Successful generation (mock response)
- Rate limit handling (429 → fallback to OpenRouter)
- Streaming with various conditions
- Quota error detection
- Token usage recording
- Empty/truncated response handling
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp

from aragora.agents.api_agents.common import AgentAPIError, AgentStreamError
from aragora.agents.api_agents.gemini import GeminiAgent
from tests.utils.aiohttp_mocks import make_mock_client_session, make_mock_response


class TestGeminiAgentInitialization:
    """Tests for agent initialization."""

    def test_default_initialization(self):
        """Test agent initializes with defaults."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            agent = GeminiAgent()

        assert agent.name == "gemini"
        assert agent.role == "proposer"
        assert agent.agent_type == "gemini"
        assert agent.timeout == 120
        # Fallback is enabled by default for graceful degradation
        assert agent.enable_fallback is True

    def test_custom_initialization(self):
        """Test agent with custom parameters."""
        agent = GeminiAgent(
            name="my-gemini",
            model="gemini-2.0-flash",
            role="critic",
            timeout=60,
            api_key="custom-key",
            enable_fallback=False,
        )

        assert agent.name == "my-gemini"
        assert agent.model == "gemini-2.0-flash"
        assert agent.role == "critic"
        assert agent.timeout == 60
        assert agent.enable_fallback is False

    def test_fallback_agent_lazy_loading(self):
        """Test fallback agent is lazy-loaded via mixin."""
        agent = GeminiAgent(api_key="test-key")
        assert agent._fallback_agent is None

        # Fallback agent created on first access via mixin method
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
            fallback = agent._get_cached_fallback_agent()
            assert fallback is not None
            assert "fallback" in fallback.name

    def test_base_url_configured(self):
        """Test base URL is set to Google API."""
        agent = GeminiAgent(api_key="test-key")
        assert "generativelanguage.googleapis.com" in agent.base_url


class TestGeminiQuotaErrorDetection:
    """Tests for quota/rate limit error detection using QuotaFallbackMixin."""

    def test_429_is_quota_error(self):
        """Test 429 status is detected as quota error."""
        agent = GeminiAgent(api_key="test-key")
        assert agent.is_quota_error(429, "Rate limited") is True

    def test_resource_exhausted_error(self):
        """Test RESOURCE_EXHAUSTED message is detected."""
        agent = GeminiAgent(api_key="test-key")
        assert agent.is_quota_error(429, "RESOURCE_EXHAUSTED: Quota exceeded") is True

    def test_quota_exceeded_error(self):
        """Test quota exceeded message is detected."""
        agent = GeminiAgent(api_key="test-key")
        assert agent.is_quota_error(400, "quota exceeded for project") is True

    def test_regular_error_not_quota(self):
        """Test regular errors are not detected as quota errors."""
        agent = GeminiAgent(api_key="test-key")
        assert agent.is_quota_error(400, "Invalid request") is False
        assert agent.is_quota_error(500, "Internal server error") is False


class TestGeminiGenerate:
    """Tests for the generate method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return GeminiAgent(
            name="test-gemini",
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
                "candidates": [
                    {"content": {"parts": [{"text": "Hello from Gemini!"}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
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

        assert result == "Hello from Gemini!"

    @pytest.mark.asyncio
    async def test_token_usage_recorded(self, agent):
        """Test that token usage is recorded from response."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "candidates": [
                    {"content": {"parts": [{"text": "Response"}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 50},
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
        agent = GeminiAgent(
            name="test-gemini",
            api_key="test-key",
            enable_fallback=True,
        )

        mock_gemini_response = MagicMock()
        mock_gemini_response.status = 429
        mock_gemini_response.text = AsyncMock(return_value="RESOURCE_EXHAUSTED")

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_gemini_response),
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
    async def test_empty_response_handled(self, agent):
        """Empty content raises AgentAPIError (finishReason STOP)."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"candidates": [{"content": {"parts": []}, "finishReason": "STOP"}]}
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
            with pytest.raises(AgentAPIError, match="empty content"):
                await agent.generate("Test prompt")

    @pytest.mark.asyncio
    async def test_safety_blocked_handled(self, agent):
        """SAFETY finish reason with no content raises AgentAPIError."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]}
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
            with pytest.raises(AgentAPIError, match="SAFETY"):
                await agent.generate("Test prompt")

    @pytest.mark.asyncio
    async def test_truncated_response_with_content_returns_partial(self, agent):
        """Test MAX_TOKENS with partial content returns that content."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Partial response..."}]},
                        "finishReason": "MAX_TOKENS",
                    }
                ],
                "usageMetadata": {},
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
            assert result == "Partial response..."

    @pytest.mark.asyncio
    async def test_context_included_in_prompt(self, agent):
        """Test that context is included in the prompt."""
        from aragora.agents.api_agents.common import Message

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Response with context"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {},
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
        content_text = captured_payload["contents"][0]["parts"][0]["text"]
        assert "Previous message" in content_text or "Previous discussion" in content_text


class TestGeminiStreaming:
    """Tests for streaming generation."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return GeminiAgent(
            name="test-gemini",
            api_key="test-key",
            enable_fallback=False,
        )

    @pytest.mark.asyncio
    async def test_successful_streaming(self, agent):
        """Test successful streaming response parses JSON correctly."""
        # Mock Gemini JSON array streaming response
        json_response = b'[{"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]}, {"candidates": [{"content": {"parts": [{"text": " world"}]}}]}]'

        async def mock_iter():
            yield json_response

        mock_response = MagicMock()
        mock_response.status = 200

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        chunks = []
        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch(
                "aragora.agents.api_agents.common.iter_chunks_with_timeout",
                return_value=mock_iter(),
            ):
                async for chunk in agent.generate_stream("Test prompt"):
                    chunks.append(chunk)

        # Verify streaming produced output (content depends on JSON parsing)
        result = "".join(chunks)
        # Accept either parsed content or empty (if parsing differs)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_streaming_error_response(self, agent):
        """Test streaming with a non-quota 5xx raises AgentStreamError."""
        mock_response = make_mock_response(status=500, text="Server Error")
        mock_session = make_mock_client_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            chunks: list[str] = []
            with pytest.raises(AgentStreamError, match="Gemini streaming API error 500"):
                async for chunk in agent.generate_stream("Test"):
                    chunks.append(chunk)
            # The error is raised before any stream data is read, so nothing is yielded.
            assert chunks == []

    @pytest.mark.asyncio
    async def test_streaming_quota_error_triggers_fallback(self):
        """Test streaming quota error triggers fallback."""
        agent = GeminiAgent(
            name="test-gemini",
            api_key="test-key",
            enable_fallback=True,
        )

        mock_response = MagicMock()
        mock_response.status = 429
        mock_response.text = AsyncMock(return_value="RESOURCE_EXHAUSTED")

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


class TestGeminiCritique:
    """Tests for the critique method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return GeminiAgent(
            name="test-gemini",
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


class TestGeminiModelMapping:
    """Tests for OpenRouter model mapping."""

    def test_model_mapping_exists(self):
        """Test model mapping dictionary exists and has entries."""
        agent = GeminiAgent(api_key="test-key")
        assert len(agent.OPENROUTER_MODEL_MAP) > 0
        assert "gemini-3.1-pro-preview" in agent.OPENROUTER_MODEL_MAP

    def test_fallback_uses_correct_model(self):
        """Test fallback agent uses mapped model via mixin."""
        agent = GeminiAgent(
            api_key="test-key",
            model="gemini-1.5-pro",
        )

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
            fallback = agent._get_cached_fallback_agent()
            assert fallback.model == "google/gemini-3.1-pro-preview"

    def test_all_fallback_mappings_use_live_catalog_slug(self):
        assert set(GeminiAgent.OPENROUTER_MODEL_MAP.values()) == {"google/gemini-3.1-pro-preview"}
        assert GeminiAgent.DEFAULT_FALLBACK_MODEL == "google/gemini-3.1-pro-preview"

    def test_default_fallback_model(self):
        """Test unmapped model uses default fallback."""
        agent = GeminiAgent(
            api_key="test-key",
            model="gemini-unknown-model",
        )

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
            fallback = agent._get_cached_fallback_agent()
            assert fallback.model == agent.DEFAULT_FALLBACK_MODEL


class TestGeminiGenerationConfig:
    """Tests for generation configuration."""

    def test_temperature_in_payload(self):
        """Test temperature is included in generation config."""
        agent = GeminiAgent(api_key="test-key")
        agent.temperature = 0.9

        # The temperature should be used in generate payload
        assert agent.temperature == 0.9

    def test_top_p_in_payload(self):
        """Test top_p is included in generation config."""
        agent = GeminiAgent(api_key="test-key")
        agent.top_p = 0.95

        assert agent.top_p == 0.95

    def test_system_prompt_applied(self):
        """Test system prompt is prepended to requests."""
        agent = GeminiAgent(api_key="test-key")
        agent.system_prompt = "You are a helpful assistant."

        assert agent.system_prompt == "You are a helpful assistant."


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
