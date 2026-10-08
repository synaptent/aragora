"""
Tests for OpenAIAPIAgent.

Tests:
- Agent initialization and configuration
- Successful generation (mock response)
- Rate limit handling (429 → fallback to OpenRouter)
- Timeout handling
- Streaming with various conditions
- Quota error detection
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp

from aragora.agents.api_agents.openai import OpenAIAPIAgent
from aragora.agents.api_agents.common import AgentAPIError, AgentStreamError
from tests.utils.aiohttp_mocks import make_mock_client_session, make_mock_response


class TestOpenAIAgentInitialization:
    """Tests for agent initialization."""

    def test_default_initialization(self):
        """Test agent initializes with defaults."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            agent = OpenAIAPIAgent()

        assert agent.name == "openai-api"
        assert agent.role == "proposer"
        assert agent.agent_type == "openai"
        assert agent.timeout == 120
        # Fallback is enabled by default for graceful degradation
        assert agent.enable_fallback is True

    def test_custom_initialization(self):
        """Test agent with custom parameters."""
        # An ACTIVE non-default catalog id: a retired one (the old
        # "gpt-4-turbo") is now upgraded at construction time, its own
        # behaviour (tests/agents/test_retired_model_id_upgrade.py).
        agent = OpenAIAPIAgent(
            name="my-gpt",
            model="gpt-5.6-terra",
            role="critic",
            timeout=60,
            api_key="custom-key",
            enable_fallback=False,
        )

        assert agent.name == "my-gpt"
        assert agent.model == "gpt-5.6-terra"
        assert agent.role == "critic"
        assert agent.timeout == 60
        assert agent.enable_fallback is False

    def test_fallback_agent_lazy_loading(self):
        """Test fallback agent is lazy-loaded via mixin."""
        agent = OpenAIAPIAgent(api_key="test-key")
        assert agent._fallback_agent is None

        # Fallback agent created on first access via mixin method
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
            fallback = agent._get_cached_fallback_agent()
            assert fallback is not None
            assert "fallback" in fallback.name


class TestOpenAIQuotaErrorDetection:
    """Tests for quota/rate limit error detection using QuotaFallbackMixin."""

    def test_429_is_quota_error(self):
        """Test 429 status is detected as quota error."""
        agent = OpenAIAPIAgent(api_key="test-key")
        # Uses is_quota_error from QuotaFallbackMixin
        assert agent.is_quota_error(429, "Rate limited") is True

    def test_quota_message_detected(self):
        """Test quota message is detected."""
        agent = OpenAIAPIAgent(api_key="test-key")
        assert agent.is_quota_error(400, "You exceeded your quota") is True

    def test_insufficient_quota_detected(self):
        """Test insufficient_quota error is detected."""
        agent = OpenAIAPIAgent(api_key="test-key")
        assert agent.is_quota_error(403, "insufficient_quota") is True

    def test_regular_error_not_quota(self):
        """Test regular errors are not detected as quota errors."""
        agent = OpenAIAPIAgent(api_key="test-key")
        assert agent.is_quota_error(400, "Invalid request") is False
        assert agent.is_quota_error(500, "Internal server error") is False


class TestOpenAIGenerate:
    """Tests for the generate method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return OpenAIAPIAgent(
            name="test-gpt",
            api_key="test-key",
            enable_fallback=False,
        )

    @pytest.mark.asyncio
    async def test_successful_generation(self, agent):
        """Test successful API response."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"choices": [{"message": {"content": "Hello from GPT!"}}]}
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

        assert result == "Hello from GPT!"

    @pytest.mark.asyncio
    async def test_api_error_handled(self, agent):
        """Test a non-quota 5xx raises AgentAPIError without retry."""
        mock_response = make_mock_response(status=500, text="Internal Server Error")
        mock_session = make_mock_client_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(AgentAPIError, match="API error 500") as exc_info:
                await agent.generate("Test prompt")
        assert exc_info.value.status_code == 500
        # Exactly one HTTP call: AgentAPIError is not in the decorator's retryable set.
        assert mock_session.post.call_count == 1

    @pytest.mark.asyncio
    async def test_quota_error_triggers_fallback(self):
        """Test quota error triggers fallback to OpenRouter."""
        agent = OpenAIAPIAgent(
            name="test-gpt",
            api_key="test-key",
            enable_fallback=True,
        )

        # Mock quota error response from OpenAI
        mock_openai_response = MagicMock()
        mock_openai_response.status = 429
        mock_openai_response.text = AsyncMock(return_value="Rate limit exceeded")

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_openai_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        # Mock fallback agent
        mock_fallback = AsyncMock()
        mock_fallback.generate = AsyncMock(return_value="Fallback response")

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
                # Mock the cached fallback agent from QuotaFallbackMixin
                with patch.object(agent, "_get_cached_fallback_agent", return_value=mock_fallback):
                    result = await agent.generate("Test prompt")

        assert result == "Fallback response"
        mock_fallback.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_quota_error_without_openrouter_key_logs_warning(self):
        """Test quota error without OPENROUTER_API_KEY logs warning."""
        agent = OpenAIAPIAgent(
            name="test-gpt",
            api_key="test-key",
            enable_fallback=True,
        )

        mock_response = make_mock_response(status=429, text="Rate limit exceeded")
        mock_session = make_mock_client_session(mock_response)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch.object(agent, "_build_fallback_providers", return_value=[]):
                with patch.dict("os.environ", {"OPENROUTER_API_KEY": ""}, clear=False):
                    # The warning comes from QuotaFallbackMixin.fallback_generate; with no
                    # providers the 429 then surfaces as a non-retryable AgentAPIError.
                    with patch("aragora.agents.fallback.logger") as mock_logger:
                        with pytest.raises(AgentAPIError, match="API error 429") as exc_info:
                            await agent.generate("Test prompt")
                        assert exc_info.value.status_code == 429
                        mock_logger.warning.assert_called()
                        assert any(
                            "no fallback provider" in call.args[0]
                            for call in mock_logger.warning.call_args_list
                        )

    @pytest.mark.asyncio
    async def test_system_prompt_included(self):
        """Test that system prompt is included in messages."""
        agent = OpenAIAPIAgent(api_key="test-key", enable_fallback=False)
        agent.system_prompt = "You are a helpful assistant."

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"choices": [{"message": {"content": "Response"}}]}
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

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await agent.generate("Hello")

        assert captured_payload is not None
        messages = captured_payload["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful assistant."


class TestOpenAIStreaming:
    """Tests for streaming generation."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return OpenAIAPIAgent(
            name="test-gpt",
            api_key="test-key",
            enable_fallback=False,
        )

    @pytest.mark.asyncio
    async def test_successful_streaming(self, agent):
        """Test successful streaming response."""
        # Mock SSE response
        sse_data = b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
        sse_data += b'data: {"choices": [{"delta": {"content": " world"}}]}\n\n'
        sse_data += b"data: [DONE]\n\n"

        async def mock_iter():
            yield sse_data

        mock_content = MagicMock()
        mock_content.__aiter__ = lambda self: mock_iter()

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.content = mock_content

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

        assert "".join(chunks) == "Hello world"

    @pytest.mark.asyncio
    async def test_streaming_error_response(self, agent):
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

    @pytest.mark.asyncio
    async def test_streaming_fallback_on_quota_error(self):
        """Test streaming falls back to OpenRouter on quota error."""
        agent = OpenAIAPIAgent(
            name="test-gpt",
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

        # Mock fallback streaming
        async def mock_fallback_stream(*args, **kwargs):
            yield "Fallback "
            yield "response"

        mock_fallback = MagicMock()
        mock_fallback.generate_stream = mock_fallback_stream

        chunks = []
        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
                # Mock the cached fallback agent from QuotaFallbackMixin
                with patch.object(agent, "_get_cached_fallback_agent", return_value=mock_fallback):
                    async for chunk in agent.generate_stream("Test"):
                        chunks.append(chunk)

        assert "".join(chunks) == "Fallback response"


class TestOpenAICritique:
    """Tests for the critique method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return OpenAIAPIAgent(
            name="test-gpt",
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


class TestOpenAIModelMapping:
    """Tests for OpenRouter model mapping.

    OpenAIAPIAgent no longer carries a static OPENROUTER_MODEL_MAP:
    get_fallback_model() (QuotaFallbackMixin) resolves the current model
    through the catalog and upgrade map instead (frontier-model-refresh,
    2026-09-04 review fix round 1, item 3).
    """

    def test_model_mapping_exists(self):
        """A legacy model spelling resolves to the current row of its own
        TIER: gpt-4o is value tier by price, so it lands on Terra."""
        agent = OpenAIAPIAgent(api_key="test-key", model="gpt-4o")
        assert agent.get_fallback_model() == "openai/gpt-5.6-terra"
        flagship = OpenAIAPIAgent(api_key="test-key", model="gpt-5.5")
        assert flagship.get_fallback_model() == "openai/gpt-6-astra"

    def test_fallback_uses_correct_model(self):
        """Test fallback agent uses the resolved model via the mixin."""
        agent = OpenAIAPIAgent(
            api_key="test-key",
            model="gpt-4o",
        )

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
            fallback = agent._get_cached_fallback_agent()
            assert fallback.model == "openai/gpt-5.6-terra"

    def test_unknown_model_defaults_to_gpt4o(self):
        """Test unknown model falls back to the current OpenAI default."""
        agent = OpenAIAPIAgent(
            api_key="test-key",
            model="gpt-unknown-model",
        )

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
            fallback = agent._get_cached_fallback_agent()
            assert fallback.model == "openai/gpt-6-astra"


class TestOpenAIFallbackDisabled:
    """Tests with fallback disabled."""

    @pytest.mark.asyncio
    async def test_no_fallback_when_disabled(self):
        """Test no fallback attempt when enable_fallback is False."""
        agent = OpenAIAPIAgent(
            name="test-gpt",
            api_key="test-key",
            enable_fallback=False,
        )

        mock_response = make_mock_response(status=429, text="Rate limit")
        mock_session = make_mock_client_session(mock_response)

        # Track whether fallback was called
        fallback_called = False

        def mock_get_fallback():
            nonlocal fallback_called
            fallback_called = True
            return MagicMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
                # Mock the cached fallback agent from QuotaFallbackMixin
                with patch.object(agent, "_get_cached_fallback_agent", mock_get_fallback):
                    # With fallback disabled the 429 must surface as AgentAPIError
                    # rather than being routed to OpenRouter.
                    with pytest.raises(AgentAPIError, match="API error 429") as exc_info:
                        await agent.generate("Test")
                    assert exc_info.value.status_code == 429
                    # Key assertion: fallback should not be called
                    assert not fallback_called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
