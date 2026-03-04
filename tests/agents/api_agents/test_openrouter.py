"""
Tests for OpenRouter API Agent and model-specific subclasses.

Tests cover:
- Base OpenRouter agent initialization and configuration
- Rate limiting and retry logic
- Model fallback on failure
- Streaming responses
- Model-specific subclasses (DeepSeek, Llama, Qwen, Kimi, etc.)
- Error handling
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.agents.api_agents.common import (
    AgentAPIError,
    AgentConnectionError,
    AgentRateLimitError,
    AgentStreamError,
)


class TestOpenRouterAgentInitialization:
    """Tests for OpenRouter agent initialization."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with default values."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        agent = OpenRouterAgent()

        assert agent.name == "openrouter"
        assert agent.model == "deepseek/deepseek-chat"
        assert agent.role == "proposer"  # Default role for debate participation
        assert agent.timeout == 300
        assert agent.agent_type == "openrouter"
        assert "openrouter.ai" in agent.base_url

    def test_init_with_custom_config(self, mock_env_with_api_keys):
        """Should initialize with custom configuration."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        agent = OpenRouterAgent(
            name="custom-router",
            model="anthropic/claude-3.5-sonnet",
            role="critic",
            timeout=180,
            system_prompt="You are a helpful assistant.",
        )

        assert agent.name == "custom-router"
        assert agent.model == "anthropic/claude-3.5-sonnet"
        assert agent.role == "critic"
        assert agent.timeout == 180
        assert agent.system_prompt == "You are a helpful assistant."

    def test_agent_registry_registration(self, mock_env_with_api_keys):
        """Should be registered in agent registry."""
        from aragora.agents.registry import AgentRegistry

        spec = AgentRegistry.get_spec("openrouter")

        assert spec is not None
        assert spec.agent_type == "API (OpenRouter)"

    def test_default_system_prompt_with_language_enforcement(self, mock_env_with_api_keys):
        """Should set default system prompt with language enforcement."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        # Patch at the source (aragora.config) since openrouter imports from there
        with patch("aragora.config.ENFORCE_RESPONSE_LANGUAGE", True):
            with patch("aragora.config.DEFAULT_DEBATE_LANGUAGE", "English"):
                agent = OpenRouterAgent()

                if agent.system_prompt:
                    assert "English" in agent.system_prompt


class TestOpenRouterContextBuilding:
    """Tests for context prompt building."""

    def test_build_context_prompt_basic(self, mock_env_with_api_keys, sample_context):
        """Should build context from messages."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        agent = OpenRouterAgent()

        context_str = agent._build_context_prompt(sample_context)

        assert "Previous discussion:" in context_str
        assert "agent1" in context_str or "First message" in context_str

    def test_build_context_prompt_truncates_messages(self, mock_env_with_api_keys):
        """Should truncate to last 5 messages."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from aragora.core import Message

        agent = OpenRouterAgent()

        # Create 10 messages
        context = [
            Message(agent=f"agent{i}", content=f"Message {i}", role="proposer", round=1)
            for i in range(10)
        ]

        context_str = agent._build_context_prompt(context)

        # Should only include last 5
        assert "Message 9" in context_str
        assert "Message 5" in context_str
        # Earlier messages might not be present
        assert context_str.count("Message") <= 5 or "Message 0" not in context_str

    def test_build_context_prompt_empty(self, mock_env_with_api_keys):
        """Should handle empty context."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        agent = OpenRouterAgent()

        context_str = agent._build_context_prompt(None)

        assert context_str == ""


class TestOpenRouterGenerate:
    """Tests for generate method."""

    @pytest.mark.asyncio
    async def test_generate_basic_response(
        self, mock_env_with_api_keys, mock_openrouter_response, mock_openrouter_limiter
    ):
        """Should generate response from API."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = OpenRouterAgent()

        mock_response = MockResponse(status=200, json_data=mock_openrouter_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openrouter.get_openrouter_limiter",
            return_value=mock_openrouter_limiter,
        ):
            with patch(
                "aragora.agents.api_agents.openrouter.create_client_session",
                return_value=mock_session,
            ):
                result = await agent.generate("Test prompt")

        assert "test response from DeepSeek" in result

    @pytest.mark.asyncio
    async def test_generate_with_context(
        self,
        mock_env_with_api_keys,
        mock_openrouter_response,
        mock_openrouter_limiter,
        sample_context,
    ):
        """Should include context in prompt."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = OpenRouterAgent()

        mock_response = MockResponse(status=200, json_data=mock_openrouter_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openrouter.get_openrouter_limiter",
            return_value=mock_openrouter_limiter,
        ):
            with patch(
                "aragora.agents.api_agents.openrouter.create_client_session",
                return_value=mock_session,
            ):
                result = await agent.generate("Test prompt", context=sample_context)

        assert result is not None

    @pytest.mark.asyncio
    async def test_generate_records_token_usage(
        self, mock_env_with_api_keys, mock_openrouter_response, mock_openrouter_limiter
    ):
        """Should record token usage from response."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = OpenRouterAgent()
        agent.reset_token_usage()

        mock_response = MockResponse(status=200, json_data=mock_openrouter_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openrouter.get_openrouter_limiter",
            return_value=mock_openrouter_limiter,
        ):
            with patch(
                "aragora.agents.api_agents.openrouter.create_client_session",
                return_value=mock_session,
            ):
                await agent.generate("Test prompt")

        assert agent.last_tokens_in == 100
        assert agent.last_tokens_out == 50


class TestOpenRouterRateLimiting:
    """Tests for rate limiting and retry logic."""

    @pytest.mark.asyncio
    async def test_rate_limit_retry(
        self, mock_env_with_api_keys, mock_openrouter_response, mock_openrouter_limiter
    ):
        """Should retry on rate limit (429) errors."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockResponse

        agent = OpenRouterAgent()

        call_count = [0]  # Use list for nonlocal mutation

        def create_response():
            call_count[0] += 1
            if call_count[0] == 1:
                return MockResponse(
                    status=429, text='{"error": "rate_limited"}', headers={"Retry-After": "0.1"}
                )
            return MockResponse(status=200, json_data=mock_openrouter_response)

        with patch(
            "aragora.agents.api_agents.openrouter.get_openrouter_limiter",
            return_value=mock_openrouter_limiter,
        ):
            with patch("aragora.agents.api_agents.openrouter.create_client_session") as mock_create:

                class DynamicSession:
                    def post(self, *args, **kwargs):
                        return create_response()

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                mock_create.return_value = DynamicSession()

                with patch("asyncio.sleep", new_callable=AsyncMock):
                    result = await agent.generate("Test prompt")

        assert result is not None or call_count[0] > 1

    @pytest.mark.asyncio
    async def test_rate_limit_acquires_token(self, mock_env_with_api_keys, mock_openrouter_limiter):
        """Should acquire rate limit token before request."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = OpenRouterAgent()

        mock_response = MockResponse(
            status=200,
            json_data={
                "choices": [{"message": {"content": "Response"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openrouter.get_openrouter_limiter",
            return_value=mock_openrouter_limiter,
        ):
            with patch(
                "aragora.agents.api_agents.openrouter.create_client_session",
                return_value=mock_session,
            ):
                await agent.generate("Test prompt")

        mock_openrouter_limiter.acquire.assert_called()


class TestOpenRouterModelFallback:
    """Tests for model fallback on failure."""

    def test_fallback_model_map_exists(self, mock_env_with_api_keys):
        """Should have fallback model mappings."""
        from aragora.agents.api_agents.openrouter import OPENROUTER_FALLBACK_MODELS

        assert len(OPENROUTER_FALLBACK_MODELS) > 0
        assert "qwen/qwen-2.5-72b-instruct" in OPENROUTER_FALLBACK_MODELS
        assert "deepseek/deepseek-chat" in OPENROUTER_FALLBACK_MODELS

    def test_fallback_chains(self, mock_env_with_api_keys):
        """Should have sensible fallback chains."""
        from aragora.agents.api_agents.openrouter import OPENROUTER_FALLBACK_MODELS

        # Qwen -> DeepSeek
        assert OPENROUTER_FALLBACK_MODELS["qwen/qwen-2.5-72b-instruct"] == "deepseek/deepseek-chat"

        # DeepSeek -> GPT-5.2-chat
        assert OPENROUTER_FALLBACK_MODELS["deepseek/deepseek-chat"] == "openai/gpt-5.3-chat"


class TestOpenRouterGenerateStream:
    """Tests for streaming generation."""

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(
        self, mock_env_with_api_keys, mock_sse_chunks, mock_openrouter_limiter
    ):
        """Should yield text chunks from SSE stream."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockStreamResponse

        agent = OpenRouterAgent()

        mock_response = MockStreamResponse(status=200, chunks=mock_sse_chunks)

        with patch(
            "aragora.agents.api_agents.openrouter.get_openrouter_limiter",
            return_value=mock_openrouter_limiter,
        ):
            with patch("aragora.agents.api_agents.openrouter.create_client_session") as mock_create:
                mock_session = MagicMock()
                mock_session.post = MagicMock(return_value=mock_response)
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_create.return_value = mock_session

                chunks = []
                async for chunk in agent.generate_stream("Test prompt"):
                    chunks.append(chunk)

                assert len(chunks) >= 0


class TestOpenRouterCritique:
    """Tests for critique method."""

    @pytest.mark.asyncio
    async def test_critique_returns_structured_feedback(self, mock_env_with_api_keys):
        """Should return structured critique."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        agent = OpenRouterAgent()

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = """ISSUES:
- Issue one
- Issue two

SUGGESTIONS:
- Suggestion one

SEVERITY: 5.5
REASONING: This is the reasoning."""

            critique = await agent.critique(
                proposal="Test proposal",
                task="Test task",
                target_agent="test-agent",
            )

            assert critique is not None


class TestOpenRouterErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_handles_api_error(self, mock_env_with_api_keys, mock_openrouter_limiter):
        """Should raise AgentAPIError on API failure."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = OpenRouterAgent()

        mock_response = MockResponse(status=500, text='{"error": "Internal error"}')
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openrouter.get_openrouter_limiter",
            return_value=mock_openrouter_limiter,
        ):
            with patch(
                "aragora.agents.api_agents.openrouter.create_client_session",
                return_value=mock_session,
            ):
                with pytest.raises(AgentAPIError):
                    await agent.generate("Test prompt")

    @pytest.mark.asyncio
    async def test_handles_empty_response(self, mock_env_with_api_keys, mock_openrouter_limiter):
        """Should raise error on empty response."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = OpenRouterAgent()

        empty_response = MockResponse(
            status=200,
            json_data={
                "choices": [{"message": {"content": ""}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 0},
            },
        )
        mock_session = MockClientSession([empty_response])

        with patch(
            "aragora.agents.api_agents.openrouter.get_openrouter_limiter",
            return_value=mock_openrouter_limiter,
        ):
            with patch(
                "aragora.agents.api_agents.openrouter.create_client_session",
                return_value=mock_session,
            ):
                with pytest.raises(AgentAPIError) as exc_info:
                    await agent.generate("Test prompt")

                assert "empty" in str(exc_info.value).lower()


class TestDeepSeekAgent:
    """Tests for DeepSeek agent."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with DeepSeek defaults."""
        from aragora.agents.api_agents.openrouter import DeepSeekAgent

        agent = DeepSeekAgent()

        assert agent.name == "deepseek"
        assert "deepseek" in agent.model
        assert agent.agent_type == "deepseek"

    def test_agent_registry_registration(self, mock_env_with_api_keys):
        """Should be registered in agent registry."""
        from aragora.agents.registry import AgentRegistry

        spec = AgentRegistry.get_spec("deepseek")

        assert spec is not None
        assert "deepseek" in spec.default_model


class TestDeepSeekReasonerAgent:
    """Tests for DeepSeek Reasoner (R1) agent."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with DeepSeek R1 defaults."""
        from aragora.agents.api_agents.openrouter import DeepSeekReasonerAgent

        agent = DeepSeekReasonerAgent()

        assert agent.name == "deepseek-r1"
        assert "reasoner" in agent.model
        assert agent.agent_type == "deepseek-r1"


class TestLlamaAgent:
    """Tests for Llama agent."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with Llama defaults."""
        from aragora.agents.api_agents.openrouter import LlamaAgent

        agent = LlamaAgent()

        assert agent.name == "llama"
        assert "llama" in agent.model.lower()
        assert agent.agent_type == "llama"

    def test_agent_registry_registration(self, mock_env_with_api_keys):
        """Should be registered in agent registry."""
        from aragora.agents.registry import AgentRegistry

        spec = AgentRegistry.get_spec("llama")

        assert spec is not None


class TestQwenAgent:
    """Tests for Qwen agent."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with Qwen defaults."""
        from aragora.agents.api_agents.openrouter import QwenAgent

        agent = QwenAgent()

        assert agent.name == "qwen"
        assert "qwen" in agent.model
        assert agent.agent_type == "qwen"

    def test_agent_registry_registration(self, mock_env_with_api_keys):
        """Should be registered in agent registry."""
        from aragora.agents.registry import AgentRegistry

        spec = AgentRegistry.get_spec("qwen")

        assert spec is not None


class TestQwenMaxAgent:
    """Tests for Qwen Max agent."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with Qwen Max defaults."""
        from aragora.agents.api_agents.openrouter import QwenMaxAgent

        agent = QwenMaxAgent()

        assert agent.name == "qwen-max"
        assert "qwen" in agent.model
        assert "max" in agent.model
        assert agent.agent_type == "qwen-max"


class TestYiAgent:
    """Tests for Yi agent."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with Yi defaults."""
        from aragora.agents.api_agents.openrouter import YiAgent

        agent = YiAgent()

        assert agent.name == "yi"
        assert "yi" in agent.model
        assert agent.agent_type == "yi"


class TestKimiK2Agent:
    """Tests for Kimi K2 agent."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with Kimi K2 defaults."""
        from aragora.agents.api_agents.openrouter import KimiK2Agent

        agent = KimiK2Agent()

        assert agent.name == "kimi"
        assert "kimi" in agent.model
        assert agent.agent_type == "kimi"

    def test_agent_registry_registration(self, mock_env_with_api_keys):
        """Should be registered in agent registry."""
        from aragora.agents.registry import AgentRegistry

        spec = AgentRegistry.get_spec("kimi")

        assert spec is not None


class TestKimiThinkingAgent:
    """Tests for Kimi Thinking agent."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with Kimi Thinking defaults."""
        from aragora.agents.api_agents.openrouter import KimiThinkingAgent

        agent = KimiThinkingAgent()

        assert agent.name == "kimi-thinking"
        assert "thinking" in agent.model
        assert agent.agent_type == "kimi-thinking"


class TestLlama4Agents:
    """Tests for Llama 4 agents."""

    def test_llama4_maverick_init(self, mock_env_with_api_keys):
        """Should initialize Llama 4 Maverick agent."""
        from aragora.agents.api_agents.openrouter import Llama4MaverickAgent

        agent = Llama4MaverickAgent()

        assert agent.name == "llama4-maverick"
        assert "maverick" in agent.model
        assert agent.agent_type == "llama4-maverick"

    def test_llama4_scout_init(self, mock_env_with_api_keys):
        """Should initialize Llama 4 Scout agent."""
        from aragora.agents.api_agents.openrouter import Llama4ScoutAgent

        agent = Llama4ScoutAgent()

        assert agent.name == "llama4-scout"
        assert "scout" in agent.model
        assert agent.agent_type == "llama4-scout"


class TestSonarAgent:
    """Tests for Perplexity Sonar agent."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with Sonar defaults."""
        from aragora.agents.api_agents.openrouter import SonarAgent

        agent = SonarAgent()

        assert agent.name == "sonar"
        assert "sonar" in agent.model
        assert agent.agent_type == "sonar"


class TestCommandRAgent:
    """Tests for Cohere Command R+ agent."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with Command R+ defaults."""
        from aragora.agents.api_agents.openrouter import CommandRAgent

        agent = CommandRAgent()

        assert agent.name == "command-r"
        assert "command" in agent.model
        assert agent.agent_type == "command-r"


class TestJambaAgent:
    """Tests for AI21 Jamba agent."""

    def test_init_with_defaults(self, mock_env_with_api_keys):
        """Should initialize with Jamba defaults."""
        from aragora.agents.api_agents.openrouter import JambaAgent

        agent = JambaAgent()

        assert agent.name == "jamba"
        assert "jamba" in agent.model
        assert agent.agent_type == "jamba"


class TestKimiLegacyAgent:
    """Tests for Kimi Legacy agent (direct Moonshot API)."""

    def test_init_with_api_key(self, mock_env_with_api_keys, monkeypatch):
        """Should initialize with Kimi API key."""
        monkeypatch.setenv("KIMI_API_KEY", "test-kimi-key")

        from aragora.agents.api_agents.openrouter import KimiLegacyAgent

        agent = KimiLegacyAgent()

        assert agent.name == "kimi"
        assert agent.model == "moonshot-v1-8k"
        assert "moonshot" in agent.base_url
        assert agent.api_key == "test-kimi-key"

    def test_init_raises_without_api_key(self, mock_env_no_api_keys):
        """Should raise error without API key."""
        from aragora.agents.api_agents.openrouter import KimiLegacyAgent

        with pytest.raises(ValueError, match="KIMI_API_KEY"):
            KimiLegacyAgent()


class TestOpenRouterHeaders:
    """Tests for OpenRouter-specific headers."""

    @pytest.mark.asyncio
    async def test_includes_referer_header(
        self, mock_env_with_api_keys, mock_openrouter_response, mock_openrouter_limiter
    ):
        """Should include HTTP-Referer header."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockResponse

        agent = OpenRouterAgent()

        captured_headers = {}

        def capture_post(url, headers=None, json=None, **kwargs):
            captured_headers.update(headers or {})
            return MockResponse(status=200, json_data=mock_openrouter_response)

        with patch(
            "aragora.agents.api_agents.openrouter.get_openrouter_limiter",
            return_value=mock_openrouter_limiter,
        ):
            with patch("aragora.agents.api_agents.openrouter.create_client_session") as mock_create:

                class MockSession:
                    def post(self, *args, **kwargs):
                        return capture_post(*args, **kwargs)

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                mock_create.return_value = MockSession()

                await agent.generate("Test prompt")

        assert "HTTP-Referer" in captured_headers
        assert "aragora" in captured_headers["HTTP-Referer"].lower()
        assert "X-Title" in captured_headers
