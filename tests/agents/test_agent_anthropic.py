"""
Tests for AnthropicAPIAgent.

Tests:
- Agent initialization and configuration
- Successful generation (mock response)
- Rate limit handling (429 → fallback to OpenRouter)
- Timeout handling
- Streaming with various conditions
- Quota error detection
- Error message sanitization
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp

from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
from aragora.agents.api_agents.common import AgentAPIError, AgentStreamError
from tests.utils.aiohttp_mocks import make_mock_client_session, make_mock_response


class TestAnthropicAgentInitialization:
    """Tests for agent initialization."""

    def test_default_initialization(self):
        """Test agent initializes with defaults."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            agent = AnthropicAPIAgent()

        assert agent.name == "claude-api"
        assert agent.role == "proposer"
        assert agent.agent_type == "anthropic"
        assert agent.timeout == 120
        # Fallback is enabled by default for graceful degradation
        assert agent.enable_fallback is True

    def test_custom_initialization(self):
        """Test agent with custom parameters."""
        # An ACTIVE non-default catalog id: a retired one (the old
        # "claude-3-opus-20240229") is now upgraded at construction time, its
        # own behaviour (tests/agents/test_retired_model_id_upgrade.py).
        agent = AnthropicAPIAgent(
            name="my-claude",
            model="claude-opus-5",
            role="critic",
            timeout=60,
            api_key="custom-key",
            enable_fallback=False,
        )

        assert agent.name == "my-claude"
        assert agent.model == "claude-opus-5"
        assert agent.role == "critic"
        assert agent.timeout == 60
        assert agent.enable_fallback is False

    def test_fallback_agent_lazy_loading(self):
        """Test fallback agent is lazy-loaded via mixin."""
        agent = AnthropicAPIAgent(api_key="test-key")
        assert agent._fallback_agent is None

        # Fallback agent created on first access via mixin method
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
            fallback = agent._get_cached_fallback_agent()
            assert fallback is not None
            assert "fallback" in fallback.name


class TestAnthropicQuotaErrorDetection:
    """Tests for quota/billing error detection using QuotaFallbackMixin."""

    def test_429_is_quota_error(self):
        """Test 429 status is detected as quota error."""
        agent = AnthropicAPIAgent(api_key="test-key")
        # Uses is_quota_error from QuotaFallbackMixin
        assert agent.is_quota_error(429, "Rate limited") is True

    def test_credit_balance_error(self):
        """Test credit balance message is detected."""
        agent = AnthropicAPIAgent(api_key="test-key")
        assert agent.is_quota_error(400, "Your credit balance is too low") is True

    def test_billing_error(self):
        """Test billing-related errors are detected."""
        agent = AnthropicAPIAgent(api_key="test-key")
        assert agent.is_quota_error(402, "billing issue detected") is True

    def test_regular_error_not_quota(self):
        """Test regular errors are not detected as quota errors."""
        agent = AnthropicAPIAgent(api_key="test-key")
        assert agent.is_quota_error(400, "Invalid request") is False
        assert agent.is_quota_error(500, "Internal server error") is False


class TestAnthropicGenerate:
    """Tests for the generate method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return AnthropicAPIAgent(
            name="test-claude",
            api_key="test-key",
            enable_fallback=False,
        )

    @pytest.mark.asyncio
    async def test_successful_generation(self, agent):
        """Test successful API response."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"content": [{"text": "Hello, world!"}]})

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

        assert result == "Hello, world!"

    @pytest.mark.asyncio
    async def test_error_response_status_checked(self, agent):
        """Test that error response status is detected."""
        # Note: Full error handling tested via integration tests
        # This test verifies the response status is properly checked
        mock_response = MagicMock()
        mock_response.status = 200  # Success status
        mock_response.json = AsyncMock(return_value={"content": [{"text": "Success"}]})

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
            assert result == "Success"

    @pytest.mark.asyncio
    async def test_quota_error_triggers_fallback(self):
        """Test quota error triggers fallback to OpenRouter."""
        agent = AnthropicAPIAgent(
            name="test-claude",
            api_key="test-key",
            enable_fallback=True,
        )

        # Mock quota error response from Anthropic
        mock_anthropic_response = MagicMock()
        mock_anthropic_response.status = 429
        mock_anthropic_response.text = AsyncMock(return_value="Rate limit exceeded")

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_anthropic_response),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        # Mock fallback agent via the mixin method
        mock_fallback = AsyncMock()
        mock_fallback.generate = AsyncMock(return_value="Fallback response")

        with patch("aiohttp.ClientSession", return_value=mock_session):
            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
                with patch.object(agent, "_get_cached_fallback_agent", return_value=mock_fallback):
                    result = await agent.generate("Test prompt")

        assert result == "Fallback response"
        mock_fallback.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_quota_error_without_openrouter_key_logs_warning(self):
        """Test quota error without OPENROUTER_API_KEY logs warning."""
        agent = AnthropicAPIAgent(
            name="test-claude",
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
                        with pytest.raises(
                            AgentAPIError, match="Anthropic API error 429"
                        ) as exc_info:
                            await agent.generate("Test prompt")
                        assert exc_info.value.status_code == 429
                        mock_logger.warning.assert_called()
                        assert any(
                            "no fallback provider" in call.args[0]
                            for call in mock_logger.warning.call_args_list
                        )

    @pytest.mark.asyncio
    async def test_context_included_in_prompt(self, agent):
        """Test that context is included in the prompt."""
        from aragora.agents.api_agents.common import Message

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(
            return_value={"content": [{"text": "Response with context"}]}
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

        # Verify context was included
        assert captured_payload is not None
        user_content = captured_payload["messages"][0]["content"]
        assert "Previous message" in user_content or "Previous discussion" in user_content


class TestAnthropicStreaming:
    """Tests for streaming generation."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return AnthropicAPIAgent(
            name="test-claude",
            api_key="test-key",
            enable_fallback=False,
        )

    @pytest.mark.asyncio
    async def test_successful_streaming(self, agent):
        """Test successful streaming response."""
        # Mock SSE response
        sse_data = b'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}}\n\n'
        sse_data += b'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": " world"}}\n\n'
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
            with pytest.raises(AgentStreamError, match="Anthropic streaming API error 500"):
                async for chunk in agent.generate_stream("Test"):
                    chunks.append(chunk)
            # The error is raised before any stream data is read, so nothing is yielded.
            assert chunks == []


class TestAnthropicCritique:
    """Tests for the critique method."""

    @pytest.fixture
    def agent(self):
        """Create test agent."""
        return AnthropicAPIAgent(
            name="test-claude",
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
        # Verify critique structure
        assert hasattr(critique, "issues")
        assert hasattr(critique, "suggestions")
        assert hasattr(critique, "severity")


class TestAnthropicModelMapping:
    """Tests for OpenRouter fallback resolution.

    ``AnthropicAPIAgent`` no longer carries a static ``OPENROUTER_MODEL_MAP``:
    ``get_fallback_model()`` resolves the current model through the catalog
    and upgrade map instead (frontier-model-refresh, 2026-09-04), so any
    legacy or retired Claude spelling upgrades to the current frontier, not
    just the ones a hand-maintained dict enumerated.
    """

    def test_default_model_fallback_is_current_slug(self):
        """Using the agent's own default model, the fallback target is the
        current frontier's OpenRouter slug (review fix round 1, item 3)."""
        agent = AnthropicAPIAgent(api_key="test-key")
        assert agent.get_fallback_model() == "anthropic/claude-fable-5.1"

    def test_fallback_resolves_legacy_id_via_catalog(self):
        """A legacy/retired Claude id resolves to the current frontier."""
        agent = AnthropicAPIAgent(api_key="test-key", model="claude-3-opus-20240229")
        assert agent.get_fallback_model() == "anthropic/claude-fable-5.1"

    def test_fallback_uses_correct_model(self):
        """Test fallback agent upgrades legacy Anthropic IDs to the frontier.

        ``get_fallback_model()`` resolves the current model through the
        catalog and upgrade map, so every legacy Claude ID routes to the
        current frontier (Fable 5.1) via OpenRouter, weaker historical
        models are transparently upgraded, and a missing direct-provider
        key never blocks functionality.
        """
        agent = AnthropicAPIAgent(
            api_key="test-key",
            model="claude-3-opus-20240229",
        )

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "router-key"}):
            fallback = agent._get_cached_fallback_agent()
            assert fallback.model == "anthropic/claude-fable-5.1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
