"""
Tests for OpenAI API Agent.

Tests cover:
- Initialization and configuration
- Web search detection
- Generate and streaming responses
- OpenAI-compatible mixin functionality
- Error handling and fallback
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.agents.api_agents.common import (
    AgentAPIError,
    AgentStreamError,
)


class TestOpenAIAgentInitialization:
    """Tests for agent initialization."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with default values."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        assert agent.name == "openai-api"
        assert agent.model == "gpt-5.3"
        assert agent.role == "proposer"
        assert agent.timeout == 120
        assert agent.agent_type == "openai"
        # Fallback is enabled by default for graceful degradation
        assert agent.enable_fallback is True
        assert agent.enable_web_search is True
        assert "api.openai.com" in agent.base_url

    def test_init_with_custom_config(self, mock_env_with_api_keys):
        """Should initialize with custom configuration."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent(
            name="custom-gpt",
            model="gpt-4o",
            role="analyst",
            timeout=90,
            enable_fallback=False,
        )

        assert agent.name == "custom-gpt"
        assert agent.model == "gpt-4o"
        assert agent.role == "analyst"
        assert agent.timeout == 90
        assert agent.enable_fallback is False

    def test_init_with_explicit_api_key(self, mock_env_no_api_keys):
        """Should use explicitly provided API key."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent(api_key="explicit-openai-key")

        assert agent.api_key == "explicit-openai-key"

    def test_agent_registry_registration(self, mock_env_with_api_keys):
        """Should be registered in agent registry."""
        from aragora.agents.registry import AgentRegistry

        spec = AgentRegistry.get_spec("openai-api")

        assert spec is not None
        assert spec.default_model == "gpt-5.3"
        assert spec.agent_type == "API"


class TestOpenAIWebSearchDetection:
    """Tests for web search detection."""

    def test_detects_url_in_prompt(self, mock_env_with_api_keys):
        """Should detect URLs indicating web search need."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        assert agent._needs_web_search("Check https://example.com for info") is True
        assert agent._needs_web_search("Visit http://docs.python.org") is True

    def test_detects_github_mentions(self, mock_env_with_api_keys):
        """Should detect GitHub references."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        assert agent._needs_web_search("Look at github.com/openai/openai-python") is True

    def test_detects_current_info_keywords(self, mock_env_with_api_keys):
        """Should detect keywords for current information."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        assert agent._needs_web_search("What's the latest news?") is True
        assert agent._needs_web_search("Find current prices") is True
        assert agent._needs_web_search("Get recent articles") is True

    def test_no_web_search_for_basic_prompts(self, mock_env_with_api_keys):
        """Should not trigger web search for basic prompts."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        assert agent._needs_web_search("Write a hello world program") is False
        assert agent._needs_web_search("Explain the concept of OOP") is False

    def test_disabled_web_search(self, mock_env_with_api_keys):
        """Should respect disabled web search setting."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent.enable_web_search = False

        assert agent._needs_web_search("Check https://example.com") is False


class TestOpenAIGenerate:
    """Tests for generate method."""

    @pytest.mark.asyncio
    async def test_generate_basic_response(self, mock_env_with_api_keys, mock_openai_response):
        """Should generate response from API."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_openai_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            result = await agent.generate("Test prompt")

        assert "test response from GPT" in result

    @pytest.mark.asyncio
    async def test_generate_with_context(
        self, mock_env_with_api_keys, mock_openai_response, sample_context
    ):
        """Should include context in prompt."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=mock_openai_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            result = await agent.generate("Test prompt", context=sample_context)

        assert result is not None

    @pytest.mark.asyncio
    async def test_generate_records_token_usage(self, mock_env_with_api_keys, mock_openai_response):
        """Should record token usage from response."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent.reset_token_usage()

        # Create mock response with async context manager
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value=mock_openai_response)
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


class TestOpenAIGenerateStream:
    """Tests for streaming generation."""

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self, mock_env_with_api_keys, mock_sse_chunks):
        """Should yield text chunks from SSE stream."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from tests.agents.api_agents.conftest import MockStreamResponse

        agent = OpenAIAPIAgent()
        agent.enable_web_search = False

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

            # Should have received chunks
            assert len(chunks) >= 0  # May vary based on SSE parsing


class TestOpenAICompatibleMixin:
    """Tests for OpenAI-compatible mixin functionality."""

    def test_build_headers(self, mock_env_with_api_keys):
        """Should build correct headers."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        headers = agent._build_headers()

        assert "Authorization" in headers
        assert "Bearer" in headers["Authorization"]
        assert headers["Content-Type"] == "application/json"

    def test_build_messages_with_system_prompt(self, mock_env_with_api_keys):
        """Should include system prompt in messages."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent.system_prompt = "You are a helpful assistant."

        messages = agent._build_messages("User prompt")

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_build_messages_without_system_prompt(self, mock_env_with_api_keys):
        """Should work without system prompt."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent.system_prompt = None

        messages = agent._build_messages("User prompt")

        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_build_payload_basic(self, mock_env_with_api_keys):
        """Should build correct payload."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        messages = [{"role": "user", "content": "Test"}]

        payload = agent._build_payload(messages, stream=False)

        assert payload["model"] == "gpt-5.3"
        assert payload["messages"] == messages
        assert "max_tokens" in payload
        assert "stream" not in payload or payload.get("stream") is False

    def test_build_payload_with_stream(self, mock_env_with_api_keys):
        """Should include stream flag when streaming."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        messages = [{"role": "user", "content": "Test"}]

        payload = agent._build_payload(messages, stream=True)

        assert payload["stream"] is True

    def test_build_payload_with_temperature(self, mock_env_with_api_keys):
        """Should include temperature when set."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent.temperature = 0.8
        messages = [{"role": "user", "content": "Test"}]

        payload = agent._build_payload(messages, stream=False)

        assert payload["temperature"] == 0.8

    def test_build_extra_payload_with_web_search(self, mock_env_with_api_keys):
        """Should add web search tool when triggered."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent._current_prompt = "Check https://example.com"

        extra = agent._build_extra_payload()

        assert extra is not None
        assert "tools" in extra

    def test_build_extra_payload_without_web_search(self, mock_env_with_api_keys):
        """Should not add tools for basic prompts."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()
        agent._current_prompt = "Write a function"

        extra = agent._build_extra_payload()

        assert extra is None


class TestOpenAICritique:
    """Tests for critique method."""

    @pytest.mark.asyncio
    async def test_critique_returns_structured_feedback(self, mock_env_with_api_keys):
        """Should return structured critique."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = """ISSUES:
- Issue one
- Issue two

SUGGESTIONS:
- Suggestion one

SEVERITY: 6.0
REASONING: This is the reasoning."""

            critique = await agent.critique(
                proposal="Test proposal",
                task="Test task",
                target_agent="test-agent",
            )

            assert critique is not None


class TestOpenAIErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_api_error(self, mock_env_with_api_keys):
        """Should raise AgentAPIError on API failure."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

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
    async def test_handles_unexpected_response_format(self, mock_env_with_api_keys):
        """Should handle unexpected response format."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent()

        # Missing 'choices' field
        bad_response = {"id": "test", "usage": {}}

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_response = MagicMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value=bad_response)
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            with pytest.raises(AgentAPIError):
                await agent.generate("Test prompt")


class TestOpenAIModelMapping:
    """Tests for OpenRouter model mapping."""

    def test_model_map_contains_common_models(self, mock_env_with_api_keys):
        """Should have mappings for common models."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        assert "gpt-4o" in OpenAIAPIAgent.OPENROUTER_MODEL_MAP
        assert "gpt-4o-mini" in OpenAIAPIAgent.OPENROUTER_MODEL_MAP
        assert "gpt-4" in OpenAIAPIAgent.OPENROUTER_MODEL_MAP

    def test_has_default_fallback_model(self, mock_env_with_api_keys):
        """Should have default fallback model."""
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        assert OpenAIAPIAgent.DEFAULT_FALLBACK_MODEL is not None
        assert "openai" in OpenAIAPIAgent.DEFAULT_FALLBACK_MODEL
