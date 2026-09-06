"""
Tests for Anthropic API Agent.

Tests cover:
- Initialization and configuration
- Web search detection
- Generate and streaming responses
- Quota fallback behavior
- Critique functionality
- Error handling
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.agents.api_agents.common import (
    AgentAPIError,
    AgentRateLimitError,
    AgentStreamError,
)


class TestAnthropicAgentInitialization:
    """Tests for agent initialization."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with default values."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent()

        assert agent.name == "claude-api"
        # frontier-model-refresh, 2026-09-04: claude-opus-5 is superseded.
        assert agent.model == "claude-fable-5-1"
        assert agent.role == "proposer"
        assert agent.timeout == 120
        assert agent.agent_type == "anthropic"
        # Fallback is enabled by default for graceful degradation
        assert agent.enable_fallback is True
        assert agent.enable_web_search is True
        assert "api.anthropic.com" in agent.base_url

    def test_init_with_custom_config(self, mock_env_with_api_keys):
        """Should initialize with custom configuration."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        # An ACTIVE non-default catalog id: a retired one (the old
        # "claude-sonnet-4-20250514") is now upgraded at construction time,
        # which is its own behaviour (see
        # tests/agents/test_retired_model_id_upgrade.py) and would make this
        # test about upgrading rather than about honouring custom config.
        agent = AnthropicAPIAgent(
            name="custom-claude",
            model="claude-opus-4-8",
            role="critic",
            timeout=60,
            enable_fallback=False,
        )

        assert agent.name == "custom-claude"
        assert agent.model == "claude-opus-4-8"
        assert agent.role == "critic"
        assert agent.timeout == 60
        assert agent.enable_fallback is False

    def test_init_with_explicit_api_key(self, mock_env_no_api_keys):
        """Should use explicitly provided API key."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent(api_key="explicit-key-123")

        assert agent.api_key == "explicit-key-123"

    def test_agent_registry_registration(self, mock_env_with_api_keys):
        """Should be registered in agent registry."""
        from aragora.agents.registry import AgentRegistry

        spec = AgentRegistry.get_spec("anthropic-api")

        assert spec is not None
        assert spec.default_model == "claude-fable-5-1"
        assert spec.agent_type == "API"


class TestAnthropicWebSearchDetection:
    """Tests for web search detection."""

    def test_detects_url_in_prompt(self, mock_env_with_api_keys):
        """Should detect URLs indicating web search need."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent()

        assert agent._needs_web_search("Check https://example.com for info") is True
        assert agent._needs_web_search("Visit http://test.org") is True

    def test_detects_github_mentions(self, mock_env_with_api_keys):
        """Should detect GitHub references."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent()

        assert agent._needs_web_search("Check the github.com repo") is True
        assert agent._needs_web_search("Look at the repo for details") is True

    def test_detects_current_info_keywords(self, mock_env_with_api_keys):
        """Should detect keywords for current information."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent()

        assert agent._needs_web_search("What's the latest news?") is True
        assert agent._needs_web_search("Find current market prices") is True
        assert agent._needs_web_search("Get recent updates") is True

    def test_no_web_search_for_basic_prompts(self, mock_env_with_api_keys):
        """Should not trigger web search for basic prompts."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent()

        assert agent._needs_web_search("Write a Python function") is False
        assert agent._needs_web_search("Explain how recursion works") is False

    def test_disabled_web_search(self, mock_env_with_api_keys):
        """Should respect disabled web search setting."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent()
        agent.enable_web_search = False

        assert agent._needs_web_search("Check https://example.com") is False


class TestAnthropicGenerate:
    """Tests for generate method."""

    @pytest.mark.asyncio
    async def test_generate_basic_response(self, mock_env_with_api_keys, mock_anthropic_response):
        """Should generate response from API."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = AnthropicAPIAgent()

        mock_response = MockResponse(status=200, json_data=mock_anthropic_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.anthropic.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.generate("Test prompt")

        assert "test response from Claude" in result

    @pytest.mark.asyncio
    async def test_generate_with_context(
        self, mock_env_with_api_keys, mock_anthropic_response, sample_context
    ):
        """Should include context in prompt."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = AnthropicAPIAgent()

        mock_response = MockResponse(status=200, json_data=mock_anthropic_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.anthropic.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.generate("Test prompt", context=sample_context)

        assert result is not None

    @pytest.mark.asyncio
    async def test_generate_with_web_search_response(
        self, mock_env_with_api_keys, mock_anthropic_web_search_response
    ):
        """Should handle web search results in response."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = AnthropicAPIAgent()

        mock_response = MockResponse(status=200, json_data=mock_anthropic_web_search_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.anthropic.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.generate("Check https://example.com")

        assert "search" in result.lower() or "Example Page" in result

    @pytest.mark.asyncio
    async def test_generate_records_token_usage(
        self, mock_env_with_api_keys, mock_anthropic_response
    ):
        """Should record token usage from response."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = AnthropicAPIAgent()
        agent.reset_token_usage()

        mock_response = MockResponse(status=200, json_data=mock_anthropic_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.anthropic.create_client_session",
            return_value=mock_session,
        ):
            await agent.generate("Test prompt")

        assert agent.last_tokens_in == 100
        assert agent.last_tokens_out == 50
        assert agent.total_tokens_in == 100
        assert agent.total_tokens_out == 50


class TestAnthropicGenerateStream:
    """Tests for streaming generation."""

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self, mock_env_with_api_keys, mock_anthropic_sse_chunks):
        """Should yield text chunks from SSE stream."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
        from tests.agents.api_agents.conftest import MockStreamResponse

        agent = AnthropicAPIAgent()
        agent.enable_web_search = False

        mock_response = MockStreamResponse(status=200, chunks=mock_anthropic_sse_chunks)

        with patch(
            "aragora.agents.api_agents.anthropic.create_client_session"
        ) as mock_create_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_create_session.return_value = mock_session

            chunks = []
            async for chunk in agent.generate_stream("Test prompt"):
                chunks.append(chunk)

            # Verify we got content chunks
            assert len(chunks) > 0


class TestAnthropicQuotaFallback:
    """Tests for quota error fallback behavior."""

    @pytest.mark.asyncio
    async def test_fallback_on_quota_error(
        self, mock_env_with_api_keys, mock_quota_error_response, mock_openai_response
    ):
        """Should fallback to OpenRouter on quota error."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = AnthropicAPIAgent(enable_fallback=True)

        # First response is quota error, second is fallback success
        fallback_response = MockResponse(status=200, json_data=mock_openai_response)
        mock_session = MockClientSession([mock_quota_error_response, fallback_response])

        with patch(
            "aragora.agents.api_agents.anthropic.create_client_session",
            return_value=mock_session,
        ):
            with patch.object(agent, "fallback_generate", new_callable=AsyncMock) as mock_fallback:
                mock_fallback.return_value = "Fallback response"

                result = await agent.generate("Test prompt")

                # Fallback should have been attempted
                assert result == "Fallback response" or mock_fallback.called

    @pytest.mark.asyncio
    async def test_no_fallback_when_disabled(
        self, mock_env_with_api_keys, mock_quota_error_response
    ):
        """Should raise error when fallback is disabled."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent(enable_fallback=False)

        with patch(
            "aragora.agents.api_agents.anthropic.create_client_session"
        ) as mock_create_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_quota_error_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_create_session.return_value = mock_session

            with pytest.raises(AgentAPIError):
                await agent.generate("Test prompt")


class TestAnthropicCritique:
    """Tests for critique method."""

    @pytest.mark.asyncio
    async def test_critique_returns_structured_feedback(self, mock_env_with_api_keys):
        """Should return structured critique."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent()

        critique_response = {
            "content": [
                {
                    "type": "text",
                    "text": """ISSUES:
- Issue one
- Issue two

SUGGESTIONS:
- Suggestion one

SEVERITY: 5.0
REASONING: This is the reasoning.""",
                }
            ],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = critique_response["content"][0]["text"]

            critique = await agent.critique(
                proposal="Test proposal",
                task="Test task",
                target_agent="test-agent",
            )

            assert critique is not None
            assert hasattr(critique, "severity") or hasattr(critique, "issues")


class TestAnthropicErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_api_error(self, mock_env_with_api_keys, mock_api_error_response):
        """Should raise AgentAPIError on API failure."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent()

        with patch(
            "aragora.agents.api_agents.anthropic.create_client_session"
        ) as mock_create_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_api_error_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_create_session.return_value = mock_session

            with pytest.raises(AgentAPIError) as exc_info:
                await agent.generate("Test prompt")

            assert "500" in str(exc_info.value) or "error" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_handles_unexpected_response_format(self, mock_env_with_api_keys):
        """Should handle unexpected response format."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = AnthropicAPIAgent()

        # Missing 'content' field
        bad_response = MockResponse(status=200, json_data={"id": "test", "usage": {}})
        mock_session = MockClientSession([bad_response])

        with patch(
            "aragora.agents.api_agents.anthropic.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentAPIError) as exc_info:
                await agent.generate("Test prompt")

            assert "format" in str(exc_info.value).lower() or "Unexpected" in str(exc_info.value)


class TestAnthropicTokenUsage:
    """Tests for token usage tracking."""

    def test_get_token_usage(self, mock_env_with_api_keys):
        """Should return token usage summary."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent()
        agent._record_token_usage(100, 50)

        usage = agent.get_token_usage()

        assert usage["tokens_in"] == 100
        assert usage["tokens_out"] == 50
        assert usage["total_tokens_in"] == 100
        assert usage["total_tokens_out"] == 50

    def test_reset_token_usage(self, mock_env_with_api_keys):
        """Should reset token counters."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent()
        agent._record_token_usage(100, 50)
        agent.reset_token_usage()

        assert agent.last_tokens_in == 0
        assert agent.last_tokens_out == 0
        assert agent.total_tokens_in == 0
        assert agent.total_tokens_out == 0

    def test_accumulates_token_usage(self, mock_env_with_api_keys):
        """Should accumulate total token usage."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent()
        agent._record_token_usage(100, 50)
        agent._record_token_usage(200, 100)

        assert agent.last_tokens_in == 200
        assert agent.last_tokens_out == 100
        assert agent.total_tokens_in == 300
        assert agent.total_tokens_out == 150


class TestAnthropicGenerationParams:
    """Tests for generation parameters."""

    def test_set_generation_params(self, mock_env_with_api_keys):
        """Should set generation parameters."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent()
        agent.set_generation_params(temperature=0.7, top_p=0.9)

        assert agent.temperature == 0.7
        assert agent.top_p == 0.9

    def test_get_generation_params(self, mock_env_with_api_keys):
        """Should return non-None generation parameters."""
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent()
        agent.temperature = 0.7
        agent.top_p = None

        params = agent.get_generation_params()

        assert "temperature" in params
        assert params["temperature"] == 0.7
        assert "top_p" not in params
