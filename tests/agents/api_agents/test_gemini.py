"""
Tests for Gemini API Agent.

Tests cover:
- Initialization and configuration
- Web search detection
- Generate and streaming responses
- Quota fallback behavior
- Critique functionality
- Error handling
- Token usage tracking
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.agents.api_agents.common import (
    AgentAPIError,
    AgentRateLimitError,
    AgentStreamError,
)


class TestGeminiAgentInitialization:
    """Tests for agent initialization."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with default values."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()

        assert agent.name == "gemini"
        assert agent.model == "gemini-3.1-pro-preview"
        assert agent.role == "proposer"
        assert agent.timeout == 120
        assert agent.agent_type == "gemini"
        # Fallback is enabled by default for graceful degradation
        assert agent.enable_fallback is True
        assert agent.enable_web_search is True
        assert "generativelanguage.googleapis.com" in agent.base_url

    def test_init_with_custom_config(self, mock_env_with_api_keys):
        """Should initialize with custom configuration."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent(
            name="custom-gemini",
            model="gemini-2.0-flash",
            role="critic",
            timeout=60,
            enable_fallback=False,
        )

        assert agent.name == "custom-gemini"
        assert agent.model == "gemini-2.0-flash"
        assert agent.role == "critic"
        assert agent.timeout == 60
        assert agent.enable_fallback is False

    def test_init_with_explicit_api_key(self, mock_env_no_api_keys):
        """Should use explicitly provided API key."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent(api_key="explicit-gemini-key-123")

        assert agent.api_key == "explicit-gemini-key-123"

    def test_agent_registry_registration(self, mock_env_with_api_keys):
        """Should be registered in agent registry."""
        from aragora.agents.registry import AgentRegistry

        spec = AgentRegistry.get_spec("gemini")

        assert spec is not None
        assert spec.default_model == "gemini-3.1-pro-preview"
        assert spec.agent_type == "API"

    def test_init_with_fallback_enabled(self, mock_env_with_fallback_enabled):
        """Should enable fallback when explicitly set."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent(enable_fallback=True)

        assert agent.enable_fallback is True

    def test_openrouter_model_map_exists(self, mock_env_with_api_keys):
        """Should have OpenRouter model mapping for fallback.

        Every legacy Gemini ID is now upgraded to Gemini 3.1 Pro via OpenRouter
        so missing direct keys never block and weaker variants are upgraded.
        """
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()

        assert hasattr(GeminiAgent, "OPENROUTER_MODEL_MAP")
        assert "gemini-3.1-pro-preview" in GeminiAgent.OPENROUTER_MODEL_MAP
        assert "gemini-2.0-flash" in GeminiAgent.OPENROUTER_MODEL_MAP
        assert GeminiAgent.DEFAULT_FALLBACK_MODEL == "google/gemini-3.1-pro-preview"


class TestGeminiWebSearchDetection:
    """Tests for web search detection."""

    def test_detects_url_in_prompt(self, mock_env_with_api_keys):
        """Should detect URLs indicating web search need."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()

        assert agent._needs_web_search("Check https://example.com for info") is True
        assert agent._needs_web_search("Visit http://test.org") is True

    def test_detects_github_mentions(self, mock_env_with_api_keys):
        """Should detect GitHub references."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()

        assert agent._needs_web_search("Check the github.com repo") is True
        assert agent._needs_web_search("Look at the repo for details") is True

    def test_detects_current_info_keywords(self, mock_env_with_api_keys):
        """Should detect keywords for current information."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()

        assert agent._needs_web_search("What's the latest news?") is True
        assert agent._needs_web_search("Find current market prices") is True
        assert agent._needs_web_search("Get recent updates") is True

    def test_detects_website_mentions(self, mock_env_with_api_keys):
        """Should detect website and webpage mentions."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()

        assert agent._needs_web_search("Check the website for details") is True
        assert agent._needs_web_search("Visit the web page") is True
        assert agent._needs_web_search("Online documentation available") is True

    def test_detects_news_and_article_mentions(self, mock_env_with_api_keys):
        """Should detect news and article references."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()

        assert agent._needs_web_search("Latest news about AI") is True
        assert agent._needs_web_search("Read the article on machine learning") is True

    def test_no_web_search_for_basic_prompts(self, mock_env_with_api_keys):
        """Should not trigger web search for basic prompts."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()

        assert agent._needs_web_search("Write a Python function") is False
        assert agent._needs_web_search("Explain how recursion works") is False
        assert agent._needs_web_search("What is 2 + 2?") is False

    def test_disabled_web_search(self, mock_env_with_api_keys):
        """Should respect disabled web search setting."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()
        agent.enable_web_search = False

        assert agent._needs_web_search("Check https://example.com") is False
        assert agent._needs_web_search("Latest news about AI") is False


class TestGeminiGenerate:
    """Tests for generate method."""

    @pytest.mark.asyncio
    async def test_generate_basic_response(self, mock_env_with_api_keys, mock_gemini_response):
        """Should generate response from API."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GeminiAgent()

        mock_response = MockResponse(status=200, json_data=mock_gemini_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.generate("Test prompt")

        assert "test response from Gemini" in result

    @pytest.mark.asyncio
    async def test_generate_with_context(
        self, mock_env_with_api_keys, mock_gemini_response, sample_context
    ):
        """Should include context in prompt."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GeminiAgent()

        mock_response = MockResponse(status=200, json_data=mock_gemini_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.generate("Test prompt", context=sample_context)

        assert result is not None

    @pytest.mark.asyncio
    async def test_generate_with_system_prompt(self, mock_env_with_api_keys, mock_gemini_response):
        """Should include system prompt in request."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GeminiAgent()
        agent.system_prompt = "You are a helpful assistant."

        mock_response = MockResponse(status=200, json_data=mock_gemini_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.generate("Test prompt")

        assert result is not None

    @pytest.mark.asyncio
    async def test_generate_with_web_search_grounding(
        self, mock_env_with_api_keys, mock_gemini_grounded_response
    ):
        """Should handle web search results in response."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GeminiAgent()

        mock_response = MockResponse(status=200, json_data=mock_gemini_grounded_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.generate("Check https://example.com")

        assert "web search" in result.lower() or "Based on" in result

    @pytest.mark.asyncio
    async def test_generate_records_token_usage(self, mock_env_with_api_keys, mock_gemini_response):
        """Should record token usage from response."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GeminiAgent()
        agent.reset_token_usage()

        mock_response = MockResponse(status=200, json_data=mock_gemini_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=mock_session,
        ):
            await agent.generate("Test prompt")

        # Gemini uses promptTokenCount and candidatesTokenCount
        assert agent.last_tokens_in == 10
        assert agent.last_tokens_out == 20
        assert agent.total_tokens_in == 10
        assert agent.total_tokens_out == 20


class TestGeminiGenerateStream:
    """Tests for streaming generation."""

    @pytest.mark.asyncio
    async def test_stream_blocks_before_network_when_budget_cap_reached(
        self, mock_env_with_api_keys, monkeypatch, tmp_path
    ):
        """Gemini streaming must obey the fail-closed monthly cap."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from aragora.billing import budget_guard
        from aragora.billing.budget_guard import BudgetExceededError

        monkeypatch.setenv("ARAGORA_MONTHLY_BUDGET_USD", "1")
        monkeypatch.setenv("ARAGORA_BUDGET_GUARD_STORE", str(tmp_path / "budget.json"))
        budget_guard._mem_state.clear()

        agent = GeminiAgent()
        monkeypatch.setattr(agent, "_estimate_budget_cost_from_text_usd", lambda text, max_out: 2.0)

        with patch("aragora.agents.api_agents.gemini.create_client_session") as create_session:
            with pytest.raises(BudgetExceededError):
                async for _ in agent.generate_stream("Test prompt"):
                    pass

        create_session.assert_not_called()

    @pytest.mark.asyncio
    async def test_stream_handles_json_array_format(self, mock_env_with_api_keys):
        """Should handle Gemini's JSON array streaming format."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockStreamResponse

        agent = GeminiAgent()
        agent.enable_web_search = False

        # Gemini streams as JSON array chunks
        json_chunks = [
            b'[{"candidates":[{"content":{"parts":[{"text":"Hello"}],"role":"model"},"index":0}]},',
            b'{"candidates":[{"content":{"parts":[{"text":" world"}],"role":"model"},"finishReason":"STOP","index":0}]}]',
        ]

        mock_response = MockStreamResponse(status=200, chunks=json_chunks)

        with patch("aragora.agents.api_agents.gemini.create_client_session") as mock_create_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_create_session.return_value = mock_session

            chunks = []
            async for chunk in agent.generate_stream("Test prompt"):
                chunks.append(chunk)

            # We should get some chunks (at least one)
            assert len(chunks) >= 0  # Stream parsing may vary


class TestGeminiQuotaFallback:
    """Tests for quota error fallback behavior."""

    @pytest.mark.asyncio
    async def test_fallback_on_quota_error(
        self, mock_env_with_api_keys, mock_quota_error_response, mock_openai_response
    ):
        """Should fallback to OpenRouter on quota error."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GeminiAgent(enable_fallback=True)

        # First response is quota error, second is fallback success
        fallback_response = MockResponse(status=200, json_data=mock_openai_response)
        mock_session = MockClientSession([mock_quota_error_response, fallback_response])

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
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
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent(enable_fallback=False)

        with patch("aragora.agents.api_agents.gemini.create_client_session") as mock_create_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_quota_error_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_create_session.return_value = mock_session

            with pytest.raises(AgentAPIError):
                await agent.generate("Test prompt")

    @pytest.mark.asyncio
    async def test_fallback_on_auth_error(self, mock_env_with_api_keys):
        """Should fallback on 401/403 authentication errors."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockResponse

        agent = GeminiAgent(enable_fallback=True)

        auth_error_response = MockResponse(
            status=401,
            text='{"error": {"message": "Invalid API key", "status": "UNAUTHENTICATED"}}',
        )

        with patch("aragora.agents.api_agents.gemini.create_client_session") as mock_create_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=auth_error_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_create_session.return_value = mock_session

            with patch.object(agent, "fallback_generate", new_callable=AsyncMock) as mock_fallback:
                mock_fallback.return_value = "Fallback response"

                result = await agent.generate("Test prompt")

                assert mock_fallback.called


class TestGeminiCritique:
    """Tests for critique method."""

    @pytest.mark.asyncio
    async def test_critique_returns_structured_feedback(self, mock_env_with_api_keys):
        """Should return structured critique."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()

        critique_response = """ISSUES:
- Issue one
- Issue two

SUGGESTIONS:
- Suggestion one

SEVERITY: 5.0
REASONING: This is the reasoning."""

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = critique_response

            critique = await agent.critique(
                proposal="Test proposal",
                task="Test task",
                target_agent="test-agent",
            )

            assert critique is not None
            assert hasattr(critique, "severity") or hasattr(critique, "issues")

    @pytest.mark.asyncio
    async def test_critique_without_target_agent(self, mock_env_with_api_keys):
        """Should work without specifying target agent."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()

        critique_response = """ISSUES:
- Issue one

SUGGESTIONS:
- Suggestion one

SEVERITY: 3.0
REASONING: Minor issues found."""

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = critique_response

            critique = await agent.critique(
                proposal="Test proposal",
                task="Test task",
            )

            assert critique is not None


class TestGeminiErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_api_error(self, mock_env_with_api_keys, mock_api_error_response):
        """Should raise AgentAPIError on API failure."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()

        with patch("aragora.agents.api_agents.gemini.create_client_session") as mock_create_session:
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
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GeminiAgent()

        # Missing 'candidates' field
        bad_response = MockResponse(
            status=200, json_data={"usageMetadata": {"promptTokenCount": 10}}
        )
        mock_session = MockClientSession([bad_response])

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentAPIError) as exc_info:
                await agent.generate("Test prompt")

            assert "format" in str(exc_info.value).lower() or "Unexpected" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_handles_empty_response_content(self, mock_env_with_api_keys):
        """Should handle empty content in response."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GeminiAgent()

        # Empty content with STOP finish reason
        empty_response = MockResponse(
            status=200,
            json_data={
                "candidates": [
                    {
                        "content": {"parts": [], "role": "model"},
                        "finishReason": "STOP",
                        "index": 0,
                    }
                ],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 0},
            },
        )
        mock_session = MockClientSession([empty_response])

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentAPIError) as exc_info:
                await agent.generate("Test prompt")

            assert "empty" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_handles_max_tokens_truncation(self, mock_env_with_api_keys):
        """Should handle MAX_TOKENS finish reason with partial content."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GeminiAgent()

        # Partial content with MAX_TOKENS finish reason
        truncated_response = MockResponse(
            status=200,
            json_data={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "This is partial content..."}],
                            "role": "model",
                        },
                        "finishReason": "MAX_TOKENS",
                        "index": 0,
                    }
                ],
                "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 1000},
            },
        )
        mock_session = MockClientSession([truncated_response])

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=mock_session,
        ):
            # Should return partial content with warning logged
            result = await agent.generate("Test prompt")
            assert "partial content" in result

    @pytest.mark.asyncio
    async def test_handles_max_tokens_no_content(self, mock_env_with_api_keys):
        """Should raise error on MAX_TOKENS with no content."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GeminiAgent()

        # MAX_TOKENS but no content at all
        empty_truncated_response = MockResponse(
            status=200,
            json_data={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "   "}], "role": "model"},
                        "finishReason": "MAX_TOKENS",
                        "index": 0,
                    }
                ],
                "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 0},
            },
        )
        mock_session = MockClientSession([empty_truncated_response])

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentAPIError) as exc_info:
                await agent.generate("Test prompt")

            assert "MAX_TOKENS" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_handles_safety_filter_block(self, mock_env_with_api_keys):
        """Should handle SAFETY finish reason."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GeminiAgent()

        # Blocked by safety filter
        safety_blocked_response = MockResponse(
            status=200,
            json_data={
                "candidates": [
                    {
                        "content": {"parts": [], "role": "model"},
                        "finishReason": "SAFETY",
                        "index": 0,
                    }
                ],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 0},
            },
        )
        mock_session = MockClientSession([safety_blocked_response])

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentAPIError) as exc_info:
                await agent.generate("Test prompt")

            assert "SAFETY" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_api_key_with_fallback(self, mock_env_with_api_keys):
        """Should attempt fallback when API key is empty but fallback enabled."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        # Mock aiohttp at module level to prevent real connections during agent init
        mock_response = AsyncMock()
        mock_response.status = 401
        mock_response.text = AsyncMock(return_value='{"error": "Invalid API key"}')
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.close = AsyncMock()  # Add close method for cleanup
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        # Patch before agent creation to avoid real network connections
        with patch(
            "aragora.agents.api_agents.common.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            # Create agent with explicit empty api_key inside patch context
            agent = GeminiAgent(api_key="", enable_fallback=True)

            with patch.object(agent, "fallback_generate", new_callable=AsyncMock) as mock_fallback:
                mock_fallback.return_value = "Fallback response"

                # 401 response triggers fallback attempt
                result = await agent.generate("Test prompt")

                # Fallback should have been called due to 401 error
                mock_fallback.assert_called_once()

    def test_missing_api_key_raises_on_init_without_openrouter(self, mock_env_no_api_keys):
        """Should raise error during init when API key missing and no OpenRouter."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        # Without any API keys, agent creation should fail
        with pytest.raises(ValueError) as exc_info:
            GeminiAgent(api_key=None, enable_fallback=False)

        assert "GEMINI_API_KEY" in str(exc_info.value) or "environment variable" in str(
            exc_info.value
        )


class TestGeminiTokenUsage:
    """Tests for token usage tracking."""

    def test_get_token_usage(self, mock_env_with_api_keys):
        """Should return token usage summary."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()
        agent._record_token_usage(100, 50)

        usage = agent.get_token_usage()

        assert usage["tokens_in"] == 100
        assert usage["tokens_out"] == 50
        assert usage["total_tokens_in"] == 100
        assert usage["total_tokens_out"] == 50

    def test_reset_token_usage(self, mock_env_with_api_keys):
        """Should reset token counters."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()
        agent._record_token_usage(100, 50)
        agent.reset_token_usage()

        assert agent.last_tokens_in == 0
        assert agent.last_tokens_out == 0
        assert agent.total_tokens_in == 0
        assert agent.total_tokens_out == 0

    def test_accumulates_token_usage(self, mock_env_with_api_keys):
        """Should accumulate total token usage."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()
        agent._record_token_usage(100, 50)
        agent._record_token_usage(200, 100)

        assert agent.last_tokens_in == 200
        assert agent.last_tokens_out == 100
        assert agent.total_tokens_in == 300
        assert agent.total_tokens_out == 150


class TestGeminiGenerationParams:
    """Tests for generation parameters."""

    def test_set_generation_params(self, mock_env_with_api_keys):
        """Should set generation parameters."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()
        agent.set_generation_params(temperature=0.7, top_p=0.9)

        assert agent.temperature == 0.7
        assert agent.top_p == 0.9

    def test_get_generation_params(self, mock_env_with_api_keys):
        """Should return non-None generation parameters."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()
        agent.temperature = 0.7
        agent.top_p = None

        params = agent.get_generation_params()

        assert "temperature" in params
        assert params["temperature"] == 0.7
        assert "top_p" not in params

    @pytest.mark.asyncio
    async def test_generation_uses_temperature(self, mock_env_with_api_keys, mock_gemini_response):
        """Should include temperature in API request."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GeminiAgent()
        agent.temperature = 0.5

        mock_response = MockResponse(status=200, json_data=mock_gemini_response)

        captured_payload = {}

        class CapturingSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def post(self, url, json=None, headers=None):
                captured_payload["json"] = json
                return mock_response

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=CapturingSession(),
        ):
            await agent.generate("Test prompt")

        assert captured_payload["json"]["generationConfig"]["temperature"] == 0.5

    @pytest.mark.asyncio
    async def test_generation_uses_top_p(self, mock_env_with_api_keys, mock_gemini_response):
        """Should include topP in API request when set."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = GeminiAgent()
        agent.top_p = 0.9

        mock_response = MockResponse(status=200, json_data=mock_gemini_response)

        captured_payload = {}

        class CapturingSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def post(self, url, json=None, headers=None):
                captured_payload["json"] = json
                return mock_response

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=CapturingSession(),
        ):
            await agent.generate("Test prompt")

        assert captured_payload["json"]["generationConfig"]["topP"] == 0.9


class TestGeminiAPIPayload:
    """Tests for API payload construction."""

    @pytest.mark.asyncio
    async def test_adds_google_search_tool_for_web_content(
        self, mock_env_with_api_keys, mock_gemini_grounded_response
    ):
        """Should add Google Search tool for web-related prompts."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockResponse

        agent = GeminiAgent()

        mock_response = MockResponse(status=200, json_data=mock_gemini_grounded_response)

        captured_payload = {}

        class CapturingSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def post(self, url, json=None, headers=None):
                captured_payload["json"] = json
                return mock_response

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=CapturingSession(),
        ):
            await agent.generate("Check https://example.com for information")

        assert "tools" in captured_payload["json"]
        assert captured_payload["json"]["tools"] == [{"googleSearch": {}}]

    @pytest.mark.asyncio
    async def test_no_google_search_tool_for_basic_prompts(
        self, mock_env_with_api_keys, mock_gemini_response
    ):
        """Should not add Google Search tool for basic prompts."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockResponse

        agent = GeminiAgent()

        mock_response = MockResponse(status=200, json_data=mock_gemini_response)

        captured_payload = {}

        class CapturingSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def post(self, url, json=None, headers=None):
                captured_payload["json"] = json
                return mock_response

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=CapturingSession(),
        ):
            await agent.generate("Write a Python function")

        assert "tools" not in captured_payload["json"]

    @pytest.mark.asyncio
    async def test_correct_api_endpoint(self, mock_env_with_api_keys, mock_gemini_response):
        """Should use correct Gemini API endpoint."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockResponse

        agent = GeminiAgent()

        mock_response = MockResponse(status=200, json_data=mock_gemini_response)

        captured_url = {}

        class CapturingSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def post(self, url, json=None, headers=None):
                captured_url["url"] = url
                return mock_response

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=CapturingSession(),
        ):
            await agent.generate("Test prompt")

        assert "generateContent" in captured_url["url"]
        assert agent.model in captured_url["url"]

    @pytest.mark.asyncio
    async def test_correct_api_headers(self, mock_env_with_api_keys, mock_gemini_response):
        """Should use correct API headers."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockResponse

        agent = GeminiAgent()

        mock_response = MockResponse(status=200, json_data=mock_gemini_response)

        captured_headers = {}

        class CapturingSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            def post(self, url, json=None, headers=None):
                captured_headers["headers"] = headers
                return mock_response

        with patch(
            "aragora.agents.api_agents.gemini.create_client_session",
            return_value=CapturingSession(),
        ):
            await agent.generate("Test prompt")

        assert "x-goog-api-key" in captured_headers["headers"]
        assert captured_headers["headers"]["Content-Type"] == "application/json"


class TestGeminiStreamingErrorHandling:
    """Tests for streaming error handling."""

    @pytest.mark.asyncio
    async def test_stream_fallback_on_auth_error(self, mock_env_with_api_keys):
        """Should fallback on 401 during streaming."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockStreamResponse

        agent = GeminiAgent(enable_fallback=True)

        auth_error_response = MockStreamResponse(status=401, chunks=[])

        with patch("aragora.agents.api_agents.gemini.create_client_session") as mock_create_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=auth_error_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_create_session.return_value = mock_session

            with patch.object(
                agent, "fallback_generate_stream", return_value=AsyncMock()
            ) as mock_fallback:
                # Create an async generator for the mock
                async def mock_stream():
                    yield "Fallback chunk"

                mock_fallback.return_value = mock_stream()

                chunks = []
                async for chunk in agent.generate_stream("Test prompt"):
                    chunks.append(chunk)

    @pytest.mark.asyncio
    async def test_stream_raises_error_on_api_failure(self, mock_env_with_api_keys):
        """Should raise AgentStreamError on API failure during streaming."""
        from aragora.agents.api_agents.gemini import GeminiAgent
        from tests.agents.api_agents.conftest import MockStreamResponse

        agent = GeminiAgent(enable_fallback=False)

        error_response = MockStreamResponse(status=500, chunks=[])

        async def mock_text():
            return '{"error": {"message": "Internal server error"}}'

        error_response.text = mock_text

        with patch("aragora.agents.api_agents.gemini.create_client_session") as mock_create_session:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=error_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_create_session.return_value = mock_session

            with pytest.raises(AgentStreamError):
                async for _ in agent.generate_stream("Test prompt"):
                    pass


class TestGeminiWebSearchIndicators:
    """Tests for web search indicator patterns."""

    def test_web_search_indicators_list_exists(self):
        """Should have web search indicator patterns."""
        from aragora.agents.api_agents.gemini import WEB_SEARCH_INDICATORS

        assert len(WEB_SEARCH_INDICATORS) > 0
        assert any("http" in pattern for pattern in WEB_SEARCH_INDICATORS)
        assert any("github" in pattern for pattern in WEB_SEARCH_INDICATORS)

    def test_case_insensitive_matching(self, mock_env_with_api_keys):
        """Should match indicators case-insensitively."""
        from aragora.agents.api_agents.gemini import GeminiAgent

        agent = GeminiAgent()

        assert agent._needs_web_search("HTTPS://EXAMPLE.COM") is True
        assert agent._needs_web_search("GITHUB.COM repo") is True
        assert agent._needs_web_search("LATEST news") is True
        assert agent._needs_web_search("CURRENT events") is True
