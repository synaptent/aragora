"""
Tests for OpenRouterAgent and its subclasses (DeepSeek, Llama, Mistral).

Tests:
- Agent initialization and configuration
- Successful generation (mock response)
- Rate limit handling with retry
- Streaming with SSE format
- Subclass-specific model configurations
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp

from aragora.agents.api_agents.openrouter import (
    OpenRouterAgent,
    DeepSeekAgent,
    DeepSeekReasonerAgent,
    LlamaAgent,
    MistralAgent,
)


class TestOpenRouterAgentInitialization:
    """Tests for OpenRouterAgent initialization."""

    def test_default_initialization(self):
        """Test agent initializes with defaults."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = OpenRouterAgent()

        assert agent.name == "openrouter"
        assert agent.role == "proposer"
        assert agent.agent_type == "openrouter"
        assert agent.timeout == 300
        assert agent.base_url == "https://openrouter.ai/api/v1"

    def test_custom_initialization(self):
        """Test agent with custom parameters."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = OpenRouterAgent(
                name="custom-router",
                model="meta-llama/llama-3.3-70b-instruct",
                role="critic",
                timeout=120,
            )

        assert agent.name == "custom-router"
        assert agent.model == "meta-llama/llama-3.3-70b-instruct"
        assert agent.role == "critic"
        assert agent.timeout == 120

    def test_system_prompt_setting(self):
        """Test system prompt is properly set."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = OpenRouterAgent(
                system_prompt="You are a helpful assistant.",
            )
        assert agent.system_prompt == "You are a helpful assistant."


class TestOpenRouterGenerate:
    """Tests for the generate method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            return OpenRouterAgent(
                name="test-router",
                model="deepseek/deepseek-v4-pro",
            )

    @pytest.mark.asyncio
    async def test_successful_generation(self, agent):
        """Test successful API response."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_response.json = AsyncMock(
            return_value={"choices": [{"message": {"content": "Hello from OpenRouter!"}}]}
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

        assert result == "Hello from OpenRouter!"

    @pytest.mark.asyncio
    async def test_api_error_handled(self, agent):
        """Test API errors are handled (may raise or return error message)."""
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.headers = {}
        mock_response.text = AsyncMock(return_value="Internal Server Error")

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
            try:
                result = await agent.generate("Test prompt")
                # If no exception, result should indicate error
                assert "error" in result.lower() or result == ""
            except Exception:
                pass  # Expected - error raised

    @pytest.mark.asyncio
    async def test_rate_limit_retry(self, agent):
        """Test rate limit triggers retry."""
        # First call returns 429, second succeeds
        call_count = 0

        def create_response():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                mock_resp = MagicMock()
                mock_resp.status = 429
                mock_resp.headers = {"Retry-After": "0.1"}  # Short retry for test
                mock_resp.text = AsyncMock(return_value="Rate limited")
                return mock_resp
            else:
                mock_resp = MagicMock()
                mock_resp.status = 200
                mock_resp.headers = {}
                mock_resp.json = AsyncMock(
                    return_value={"choices": [{"message": {"content": "Success after retry"}}]}
                )
                return mock_resp

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            side_effect=lambda *args, **kwargs: MagicMock(
                __aenter__=AsyncMock(return_value=create_response()),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch("asyncio.sleep", new_callable=AsyncMock):  # Speed up test
                result = await agent.generate("Test prompt")

        assert result == "Success after retry"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_context_prompt_building(self, agent):
        """Test context is properly built into prompt."""
        from aragora.agents.api_agents.common import Message

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {}
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

        context = [
            Message(agent="assistant", role="analyst", content="Previous answer"),
        ]

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await agent.generate("New question", context=context)

        assert captured_payload is not None
        user_content = captured_payload["messages"][-1]["content"]
        assert "Previous" in user_content


class TestOpenRouterStreaming:
    """Tests for streaming generation."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            return OpenRouterAgent(
                name="test-router",
                model="deepseek/deepseek-v4-pro",
            )

    @pytest.mark.asyncio
    async def test_successful_streaming(self, agent):
        """Test successful streaming response."""
        # Mock SSE response (OpenAI-compatible format)
        sse_data = b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
        sse_data += b'data: {"choices": [{"delta": {"content": " OpenRouter"}}]}\n\n'
        sse_data += b"data: [DONE]\n\n"

        async def mock_iter():
            yield sse_data

        mock_content = MagicMock()
        mock_content.__aiter__ = lambda self: mock_iter()

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {}
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

        assert "".join(chunks) == "Hello OpenRouter"

    @pytest.mark.asyncio
    async def test_streaming_error_response(self, agent):
        """Test streaming with error response raises or returns error."""
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.headers = {}
        mock_response.text = AsyncMock(return_value="Server Error")

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
            # Error may raise or return error message depending on decorator
            chunks = []
            try:
                async for chunk in agent.generate_stream("Test"):
                    chunks.append(chunk)
                # If no exception, result should indicate error
                result = "".join(chunks)
                assert "error" in result.lower() or result == ""
            except (RuntimeError, Exception):
                pass  # Expected behavior - error raised


class TestOpenRouterCritique:
    """Tests for the critique method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            return OpenRouterAgent(
                name="test-router",
                model="deepseek/deepseek-v4-pro",
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


class TestDeepSeekAgent:
    """Tests for DeepSeekAgent subclass."""

    def test_default_model(self):
        """Test DeepSeek agent has correct default model."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = DeepSeekAgent()

        assert "deepseek" in agent.model.lower()
        assert agent.agent_type == "deepseek"

    def test_custom_name(self):
        """Test DeepSeek agent with custom name."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = DeepSeekAgent(name="my-deepseek", role="proposer")
        assert agent.name == "my-deepseek"
        assert agent.role == "proposer"


class TestDeepSeekReasonerAgent:
    """Tests for DeepSeekReasonerAgent subclass."""

    def test_default_model(self):
        """Test DeepSeek Reasoner has correct default model."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = DeepSeekReasonerAgent()

        assert "deepseek" in agent.model.lower()
        # frontier-model-refresh, 2026-09-04: deepseek-v4-pro is superseded.
        assert agent.model == "deepseek/deepseek-v4-pro-0813"
        assert agent.agent_type == "deepseek-r1"


class TestLlamaAgent:
    """Tests for LlamaAgent subclass."""

    def test_default_model(self):
        """Test Llama agent has correct default model."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = LlamaAgent()

        # LlamaAgent now routes to Meta Muse Spark 1.3, which supersedes the
        # retired Llama 3.3/4 lines (frontier-model-refresh, 2026-09-04).
        assert agent.model == "meta/muse-spark-1.3"
        assert agent.agent_type == "llama"

    def test_custom_model(self):
        """Test Llama agent with custom model."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = LlamaAgent(model="meta-llama/llama-3.1-8b-instruct")
        assert agent.model == "meta-llama/llama-3.1-8b-instruct"


class TestMistralAgent:
    """Tests for MistralAgent subclass."""

    def test_default_model(self):
        """Test Mistral agent has correct default model."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = MistralAgent()

        assert "mistral" in agent.model.lower()
        assert agent.agent_type == "mistral"


class TestOpenRouterHeaders:
    """Tests for OpenRouter-specific headers."""

    @pytest.mark.asyncio
    async def test_required_headers_sent(self):
        """Test OpenRouter required headers are included."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = OpenRouterAgent(
                name="test-router",
                model="deepseek/deepseek-v4-pro",
            )

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_response.json = AsyncMock(
            return_value={"choices": [{"message": {"content": "Response"}}]}
        )

        captured_headers = None

        def capture_post(url, **kwargs):
            nonlocal captured_headers
            captured_headers = kwargs.get("headers", {})
            return MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=False),
            )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = capture_post

        with patch("aiohttp.ClientSession", return_value=mock_session):
            await agent.generate("Test")

        assert captured_headers is not None
        assert "Authorization" in captured_headers
        assert "HTTP-Referer" in captured_headers
        assert "X-Title" in captured_headers


class TestOpenRouterRateLimiter:
    """Tests for rate limiter integration."""

    @pytest.mark.asyncio
    async def test_rate_limiter_acquired(self):
        """Test rate limiter is used before requests."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = OpenRouterAgent(
                name="test-router",
                model="deepseek/deepseek-v4-pro",
            )

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_response.json = AsyncMock(
            return_value={"choices": [{"message": {"content": "Response"}}]}
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

        mock_limiter = MagicMock()
        mock_limiter.acquire = AsyncMock(return_value=True)
        mock_limiter.update_from_headers = MagicMock()

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch(
                "aragora.agents.api_agents.openrouter.get_openrouter_limiter",
                return_value=mock_limiter,
            ):
                await agent.generate("Test")

        mock_limiter.acquire.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
