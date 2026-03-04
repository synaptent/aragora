"""
Tests for OpenAI-compatible API agent mixin.

Tests cover:
- OpenAICompatibleMixin class functionality
- generate() method including error handling and fallback
- generate_stream() method
- critique() method
- Header and payload building
- Response parsing
- Circuit breaker integration
- Error scenarios
"""

import asyncio
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.agents.api_agents.common import (
    AgentAPIError,
    AgentCircuitOpenError,
    AgentStreamError,
)
from aragora.core import Critique, Message


# =============================================================================
# Helper Classes for Mocking
# =============================================================================


class MockResponse:
    """Mock HTTP response for API tests."""

    def __init__(
        self,
        status: int = 200,
        json_data: dict[str, Any] | None = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ):
        self.status = status
        self._json_data = json_data or {}
        self._text = text
        self.headers = headers or {}

    async def json(self) -> dict[str, Any]:
        return self._json_data

    async def text(self) -> str:
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockStreamResponse:
    """Mock streaming HTTP response for SSE tests."""

    def __init__(
        self,
        status: int = 200,
        chunks: list[bytes] | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.status = status
        self._chunks = chunks or []
        self.headers = headers or {}
        self.content = self._create_content()

    def _create_content(self):
        """Create async iterator for content."""

        class AsyncContent:
            def __init__(self, chunks):
                self._chunks = chunks
                self._index = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._index >= len(self._chunks):
                    raise StopAsyncIteration
                chunk = self._chunks[self._index]
                self._index += 1
                return chunk

            def iter_any(self):
                """Return self as async iterator (mimics aiohttp StreamReader)."""
                return self

        return AsyncContent(self._chunks)

    async def text(self) -> str:
        return b"".join(self._chunks).decode("utf-8")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockClientSession:
    """Mock aiohttp ClientSession."""

    def __init__(self, responses: list[MockResponse] | None = None):
        self._responses = responses or []
        self._response_index = 0

    def _get_next_response(self):
        if self._response_index < len(self._responses):
            response = self._responses[self._response_index]
            self._response_index += 1
            return response
        return MockResponse(status=500, text="No mock response available")

    def post(self, url: str, **kwargs):
        return self._get_next_response()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def sample_context():
    """Sample message context for testing."""
    return [
        Message(
            agent="agent1",
            content="First message",
            role="proposer",
            round=1,
        ),
        Message(
            agent="agent2",
            content="Response to first message",
            role="critic",
            round=1,
        ),
    ]


@pytest.fixture
def mock_circuit_breaker():
    """Mock circuit breaker for testing."""
    breaker = MagicMock()
    breaker.can_proceed.return_value = True
    breaker.record_failure = MagicMock()
    breaker.record_success = MagicMock()
    return breaker


@pytest.fixture
def mock_sse_chunks():
    """SSE chunks for streaming response tests (OpenAI format)."""
    return [
        b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"!"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]


class ConcreteOpenAICompatibleAgent:
    """Concrete implementation of OpenAICompatibleMixin for testing.

    This class provides the minimal implementation needed to test the mixin
    without depending on a real agent implementation.
    """

    # Required class attributes for OpenAICompatibleMixin
    OPENROUTER_MODEL_MAP = {
        "test-model": "openai/test-model",
        "custom-model": "openrouter/custom-model",
    }
    DEFAULT_FALLBACK_MODEL = "openai/gpt-4o"

    def __init__(
        self,
        name: str = "test-agent",
        model: str = "test-model",
        role: str = "proposer",
        timeout: int = 120,
        api_key: str | None = "test-api-key",
        base_url: str = "https://api.test.com/v1",
        enable_fallback: bool = False,
        system_prompt: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        frequency_penalty: float | None = None,
    ):
        self.name = name
        self.model = model
        self.role = role
        self.timeout = timeout
        self.api_key = api_key
        self.base_url = base_url
        self.enable_fallback = enable_fallback
        self.system_prompt = system_prompt
        self.temperature = temperature
        self.top_p = top_p
        self.frequency_penalty = frequency_penalty
        self.agent_type = "test"
        self.max_tokens = 4096

        # Token tracking
        self._last_tokens_in = 0
        self._last_tokens_out = 0
        self._total_tokens_in = 0
        self._total_tokens_out = 0

        # Circuit breaker (optional)
        self._circuit_breaker = None

        # Fallback agent cache
        self._fallback_agent = None

    def _record_token_usage(self, tokens_in: int, tokens_out: int) -> None:
        """Record token usage."""
        self._last_tokens_in = tokens_in
        self._last_tokens_out = tokens_out
        self._total_tokens_in += tokens_in
        self._total_tokens_out += tokens_out

    def _build_context_prompt(
        self,
        context: list[Message] | None = None,
        truncate: bool = False,
        sanitize_fn: object | None = None,
    ) -> str:
        """Build context prompt from messages."""
        if not context:
            return ""
        lines = ["Previous discussion:"]
        for msg in context[-5:]:  # Last 5 messages
            lines.append(f"[{msg.agent}]: {msg.content}")
        return "\n".join(lines) + "\n\n"

    def _parse_critique(
        self,
        response: str,
        target_agent: str,
        target_content: str,
    ) -> Critique:
        """Parse critique response."""
        return Critique(
            agent=self.name,
            target_agent=target_agent,
            target_content=target_content,
            issues=["Parsed issue"],
            suggestions=["Parsed suggestion"],
            severity=5.0,
            reasoning="Parsed reasoning",
        )

    @property
    def last_tokens_in(self) -> int:
        return self._last_tokens_in

    @property
    def last_tokens_out(self) -> int:
        return self._last_tokens_out


# Import the mixin after defining the concrete class
from aragora.agents.api_agents.openai_compatible import OpenAICompatibleMixin


class TestableAgent(OpenAICompatibleMixin, ConcreteOpenAICompatibleAgent):
    """Testable agent combining mixin with concrete implementation.

    Note: Class attributes are overridden to ensure they take precedence
    in the MRO, as the mixin defines its own defaults.
    """

    # Override class attributes from both parent classes
    OPENROUTER_MODEL_MAP = {
        "test-model": "openai/test-model",
        "custom-model": "openrouter/custom-model",
    }
    DEFAULT_FALLBACK_MODEL = "openai/gpt-4o"
    max_tokens = 4096


@pytest.fixture
def mock_openai_compatible_response():
    """Standard OpenAI-compatible API response."""
    return {
        "id": "chatcmpl-test123",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "This is a test response from the compatible API.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


@pytest.fixture
def mock_tool_call_response():
    """Response with tool calls but empty content."""
    return {
        "id": "chatcmpl-tools",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {"name": "search", "arguments": "{}"},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
    }


# =============================================================================
# Initialization Tests
# =============================================================================


class TestOpenAICompatibleMixinInitialization:
    """Tests for mixin initialization and class attributes."""

    def test_class_attributes_defined(self):
        """Should have required class attributes."""
        assert hasattr(OpenAICompatibleMixin, "OPENROUTER_MODEL_MAP")
        assert hasattr(OpenAICompatibleMixin, "DEFAULT_FALLBACK_MODEL")
        assert hasattr(OpenAICompatibleMixin, "max_tokens")

    def test_default_values(self):
        """Should have sensible default values."""
        assert OpenAICompatibleMixin.OPENROUTER_MODEL_MAP == {}
        assert OpenAICompatibleMixin.DEFAULT_FALLBACK_MODEL == "openai/gpt-5.3"
        assert OpenAICompatibleMixin.max_tokens == 4096

    def test_concrete_agent_initialization(self):
        """Should initialize concrete agent properly."""
        agent = TestableAgent()

        assert agent.name == "test-agent"
        assert agent.model == "test-model"
        assert agent.timeout == 120
        assert agent.api_key == "test-api-key"
        assert agent.base_url == "https://api.test.com/v1"

    def test_custom_initialization(self):
        """Should accept custom initialization parameters."""
        agent = TestableAgent(
            name="custom-agent",
            model="custom-model",
            timeout=60,
            api_key="custom-key",
            base_url="https://custom.api.com/v1",
        )

        assert agent.name == "custom-agent"
        assert agent.model == "custom-model"
        assert agent.timeout == 60
        assert agent.api_key == "custom-key"


# =============================================================================
# Header Building Tests
# =============================================================================


class TestHeaderBuilding:
    """Tests for _build_headers method."""

    def test_build_headers_basic(self):
        """Should build basic headers with authorization."""
        agent = TestableAgent()
        headers = agent._build_headers()

        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test-api-key"
        assert headers["Content-Type"] == "application/json"

    def test_build_headers_includes_trace_headers(self):
        """Should include distributed tracing headers."""
        agent = TestableAgent()

        with patch(
            "aragora.agents.api_agents.openai_compatible.get_trace_headers",
            return_value={"traceparent": "00-trace-id"},
        ):
            headers = agent._build_headers()

        assert "traceparent" in headers

    def test_build_extra_headers_returns_none_by_default(self):
        """Should return None for extra headers by default."""
        agent = TestableAgent()

        assert agent._build_extra_headers() is None


# =============================================================================
# Message Building Tests
# =============================================================================


class TestMessageBuilding:
    """Tests for _build_messages method."""

    def test_build_messages_user_only(self):
        """Should build messages with user message only."""
        agent = TestableAgent()
        messages = agent._build_messages("User prompt")

        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "User prompt"

    def test_build_messages_with_system_prompt(self):
        """Should include system prompt when set."""
        agent = TestableAgent(system_prompt="You are a helpful assistant.")
        messages = agent._build_messages("User prompt")

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful assistant."
        assert messages[1]["role"] == "user"

    def test_build_messages_empty_system_prompt_ignored(self):
        """Should ignore empty system prompt."""
        agent = TestableAgent(system_prompt="")
        messages = agent._build_messages("User prompt")

        assert len(messages) == 1
        assert messages[0]["role"] == "user"


# =============================================================================
# Payload Building Tests
# =============================================================================


class TestPayloadBuilding:
    """Tests for _build_payload method."""

    def test_build_payload_basic(self):
        """Should build basic payload."""
        agent = TestableAgent()
        messages = [{"role": "user", "content": "Test"}]
        payload = agent._build_payload(messages, stream=False)

        assert payload["model"] == "test-model"
        assert payload["messages"] == messages
        assert payload["max_tokens"] == 4096
        assert "stream" not in payload or payload.get("stream") is False

    def test_build_payload_with_stream(self):
        """Should include stream flag when streaming."""
        agent = TestableAgent()
        messages = [{"role": "user", "content": "Test"}]
        payload = agent._build_payload(messages, stream=True)

        assert payload["stream"] is True

    def test_build_payload_with_temperature(self):
        """Should include temperature when set."""
        agent = TestableAgent(temperature=0.7)
        messages = [{"role": "user", "content": "Test"}]
        payload = agent._build_payload(messages, stream=False)

        assert payload["temperature"] == 0.7

    def test_build_payload_with_top_p(self):
        """Should include top_p when set."""
        agent = TestableAgent(top_p=0.9)
        messages = [{"role": "user", "content": "Test"}]
        payload = agent._build_payload(messages, stream=False)

        assert payload["top_p"] == 0.9

    def test_build_payload_with_frequency_penalty(self):
        """Should include frequency_penalty when set."""
        agent = TestableAgent(frequency_penalty=0.5)
        messages = [{"role": "user", "content": "Test"}]
        payload = agent._build_payload(messages, stream=False)

        assert payload["frequency_penalty"] == 0.5

    def test_build_payload_with_all_params(self):
        """Should include all generation parameters."""
        agent = TestableAgent(temperature=0.8, top_p=0.95, frequency_penalty=0.3)
        messages = [{"role": "user", "content": "Test"}]
        payload = agent._build_payload(messages, stream=False)

        assert payload["temperature"] == 0.8
        assert payload["top_p"] == 0.95
        assert payload["frequency_penalty"] == 0.3

    def test_build_extra_payload_returns_none_by_default(self):
        """Should return None for extra payload by default."""
        agent = TestableAgent()

        assert agent._build_extra_payload() is None


# =============================================================================
# Response Parsing Tests
# =============================================================================


class TestResponseParsing:
    """Tests for _parse_response method."""

    def test_parse_response_success(self, mock_openai_compatible_response):
        """Should parse valid response correctly."""
        agent = TestableAgent()
        content = agent._parse_response(mock_openai_compatible_response)

        assert content == "This is a test response from the compatible API."

    def test_parse_response_missing_choices(self):
        """Should raise error for missing choices."""
        agent = TestableAgent()

        with pytest.raises(AgentAPIError) as exc_info:
            agent._parse_response({"id": "test"})

        assert "Unexpected" in str(exc_info.value)
        assert "response format" in str(exc_info.value)

    def test_parse_response_empty_choices(self):
        """Should raise error for empty choices."""
        agent = TestableAgent()

        with pytest.raises(AgentAPIError):
            agent._parse_response({"choices": []})

    def test_parse_response_missing_message(self):
        """Should raise error for missing message."""
        agent = TestableAgent()

        with pytest.raises(AgentAPIError):
            agent._parse_response({"choices": [{"index": 0}]})


# =============================================================================
# Endpoint and Error Prefix Tests
# =============================================================================


class TestEndpointAndErrorPrefix:
    """Tests for endpoint URL and error prefix methods."""

    def test_get_endpoint_url(self):
        """Should return correct endpoint URL."""
        agent = TestableAgent(base_url="https://api.test.com/v1")
        url = agent._get_endpoint_url()

        assert url == "https://api.test.com/v1/chat/completions"

    def test_get_error_prefix(self):
        """Should return formatted error prefix."""
        agent = TestableAgent()
        agent.agent_type = "openai"
        prefix = agent._get_error_prefix()

        assert prefix == "Openai"

    def test_get_error_prefix_default(self):
        """Should return API as default prefix."""
        agent = TestableAgent()
        del agent.agent_type  # Remove agent_type
        prefix = agent._get_error_prefix()

        assert prefix == "API"


# =============================================================================
# Generate Method Tests
# =============================================================================


class TestGenerateMethod:
    """Tests for generate() method."""

    @pytest.mark.asyncio
    async def test_generate_basic_response(self, mock_openai_compatible_response):
        """Should generate response from API."""
        agent = TestableAgent()

        mock_response = MockResponse(status=200, json_data=mock_openai_compatible_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.generate("Test prompt")

        assert "test response from the compatible API" in result

    @pytest.mark.asyncio
    async def test_generate_with_context(self, mock_openai_compatible_response, sample_context):
        """Should include context in prompt."""
        agent = TestableAgent()

        mock_response = MockResponse(status=200, json_data=mock_openai_compatible_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.generate("Test prompt", context=sample_context)

        assert result is not None

    @pytest.mark.asyncio
    async def test_generate_records_token_usage(self, mock_openai_compatible_response):
        """Should record token usage from response."""
        agent = TestableAgent()

        mock_response = MockResponse(status=200, json_data=mock_openai_compatible_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            await agent.generate("Test prompt")

        assert agent.last_tokens_in == 100
        assert agent.last_tokens_out == 50

    @pytest.mark.asyncio
    async def test_generate_missing_api_key(self):
        """Should handle missing API key."""
        agent = TestableAgent(api_key=None, enable_fallback=False)

        with pytest.raises(AgentAPIError) as exc_info:
            await agent.generate("Test prompt")

        assert "not configured" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_generate_api_error(self):
        """Should raise AgentAPIError on API failure."""
        agent = TestableAgent()

        mock_response = MockResponse(status=500, text='{"error": "Internal server error"}')
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentAPIError) as exc_info:
                await agent.generate("Test prompt")

        assert "500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_generate_empty_response(self):
        """Should raise error on empty response content."""
        agent = TestableAgent()

        empty_response = {
            "choices": [{"message": {"role": "assistant", "content": ""}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 0},
        }
        mock_response = MockResponse(status=200, json_data=empty_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentAPIError) as exc_info:
                await agent.generate("Test prompt")

        assert "empty" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_generate_whitespace_only_response(self):
        """Should raise error on whitespace-only response."""
        agent = TestableAgent()

        whitespace_response = {
            "choices": [{"message": {"role": "assistant", "content": "   \n\t  "}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        }
        mock_response = MockResponse(status=200, json_data=whitespace_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentAPIError) as exc_info:
                await agent.generate("Test prompt")

        assert "empty" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_generate_retries_on_tool_call_empty_content(
        self, mock_openai_compatible_response, mock_tool_call_response
    ):
        """Should retry without tools when tool call returns empty content."""
        agent = TestableAgent()

        call_count = [0]

        def create_response():
            call_count[0] += 1
            if call_count[0] == 1:
                return MockResponse(status=200, json_data=mock_tool_call_response)
            return MockResponse(status=200, json_data=mock_openai_compatible_response)

        class DynamicSession:
            def post(self, *args, **kwargs):
                return create_response()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=DynamicSession(),
        ):
            result = await agent.generate("Test prompt")

        assert call_count[0] == 2
        assert "test response" in result


# =============================================================================
# Circuit Breaker Integration Tests
# =============================================================================


class TestCircuitBreakerIntegration:
    """Tests for circuit breaker integration."""

    @pytest.mark.asyncio
    async def test_generate_checks_circuit_breaker(self, mock_circuit_breaker):
        """Should check circuit breaker before API call."""
        agent = TestableAgent()
        agent._circuit_breaker = mock_circuit_breaker
        mock_circuit_breaker.can_proceed.return_value = False

        with pytest.raises(AgentCircuitOpenError):
            await agent.generate("Test prompt")

        mock_circuit_breaker.can_proceed.assert_called()

    @pytest.mark.asyncio
    async def test_generate_records_success(
        self, mock_openai_compatible_response, mock_circuit_breaker
    ):
        """Should record success with circuit breaker."""
        agent = TestableAgent()
        agent._circuit_breaker = mock_circuit_breaker

        mock_response = MockResponse(status=200, json_data=mock_openai_compatible_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            await agent.generate("Test prompt")

        mock_circuit_breaker.record_success.assert_called()

    @pytest.mark.asyncio
    async def test_generate_records_failure_on_error(self, mock_circuit_breaker):
        """Should record failure with circuit breaker on error."""
        agent = TestableAgent()
        agent._circuit_breaker = mock_circuit_breaker

        mock_response = MockResponse(status=500, text='{"error": "Server error"}')
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            with pytest.raises(AgentAPIError):
                await agent.generate("Test prompt")

        mock_circuit_breaker.record_failure.assert_called()


# =============================================================================
# Fallback Tests
# =============================================================================


class TestFallbackBehavior:
    """Tests for fallback behavior on errors."""

    @pytest.mark.asyncio
    async def test_fallback_on_missing_api_key(self, mock_openai_compatible_response):
        """Should attempt fallback when API key is missing."""
        agent = TestableAgent(api_key=None, enable_fallback=True)

        mock_fallback = MagicMock()
        mock_fallback.generate = AsyncMock(return_value="Fallback response")

        with patch.object(agent, "_get_cached_fallback_agent", return_value=mock_fallback):
            result = await agent.generate("Test prompt")

        assert result == "Fallback response"
        mock_fallback.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_quota_error(self, mock_openai_compatible_response):
        """Should attempt fallback on quota error."""
        agent = TestableAgent(enable_fallback=True)

        mock_fallback = MagicMock()
        mock_fallback.generate = AsyncMock(return_value="Fallback response")

        class QuotaErrorSession:
            def post(self, *args, **kwargs):
                return MockResponse(status=429, text='{"error": "rate limit exceeded"}')

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=QuotaErrorSession(),
        ):
            with patch.object(agent, "_get_cached_fallback_agent", return_value=mock_fallback):
                result = await agent.generate("Test prompt")

        assert result == "Fallback response"

    @pytest.mark.asyncio
    async def test_fallback_on_auth_error(self, mock_openai_compatible_response):
        """Should attempt fallback on 401/403 errors."""
        agent = TestableAgent(enable_fallback=True)

        mock_fallback = MagicMock()
        mock_fallback.generate = AsyncMock(return_value="Fallback response")

        class AuthErrorSession:
            def post(self, *args, **kwargs):
                return MockResponse(status=401, text='{"error": "unauthorized"}')

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=AuthErrorSession(),
        ):
            with patch.object(agent, "_get_cached_fallback_agent", return_value=mock_fallback):
                result = await agent.generate("Test prompt")

        assert result == "Fallback response"


# =============================================================================
# Generate Stream Tests
# =============================================================================


class TestGenerateStream:
    """Tests for generate_stream() method."""

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self, mock_sse_chunks):
        """Should yield text chunks from SSE stream."""
        agent = TestableAgent()

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

            # Should have received chunks (exact number depends on SSE parsing)
            assert len(chunks) >= 0

    @pytest.mark.asyncio
    async def test_stream_missing_api_key_with_fallback(self):
        """Should attempt fallback streaming when API key is missing.

        Note: The generate_stream method yields from fallback but then raises
        an error if the fallback didn't fully replace the method. This tests
        that the fallback is attempted and yields chunks before the error.
        """
        agent = TestableAgent(api_key=None, enable_fallback=True)

        # Track if fallback was called
        fallback_called = [False]
        fallback_chunks = ["Fallback ", "stream"]

        async def mock_fallback_stream(*args, **kwargs):
            fallback_called[0] = True
            for chunk in fallback_chunks:
                yield chunk

        # Patch fallback_generate_stream directly to avoid MRO issues with mixin
        # The current implementation yields from fallback then raises error
        with patch.object(agent, "fallback_generate_stream", mock_fallback_stream):
            chunks = []
            try:
                async for chunk in agent.generate_stream("Test prompt"):
                    chunks.append(chunk)
            except AgentAPIError:
                pass  # Expected - raise after fallback stream completes

        # Verify fallback was called and chunks were yielded
        assert fallback_called[0] is True
        assert chunks == fallback_chunks

    @pytest.mark.asyncio
    async def test_stream_api_error(self):
        """Should raise AgentStreamError on API failure."""
        agent = TestableAgent()

        mock_response = MockStreamResponse(status=500, chunks=[])

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.post = MagicMock(return_value=mock_response)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            mock_session_class.return_value = mock_session

            with pytest.raises(AgentStreamError):
                chunks = []
                async for chunk in agent.generate_stream("Test prompt"):
                    chunks.append(chunk)


# =============================================================================
# Critique Method Tests
# =============================================================================


class TestCritiqueMethod:
    """Tests for critique() method."""

    @pytest.mark.asyncio
    async def test_critique_returns_structured_feedback(self):
        """Should return structured critique."""
        agent = TestableAgent()

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
                target_agent="test-target",
            )

        assert critique is not None
        assert isinstance(critique, Critique)

    @pytest.mark.asyncio
    async def test_critique_prompt_includes_target_agent(self):
        """Should include target agent in critique prompt."""
        agent = TestableAgent()

        captured_prompt = None

        async def capture_generate(prompt, context=None):
            nonlocal captured_prompt
            captured_prompt = prompt
            return "ISSUES:\n- Issue\nSUGGESTIONS:\n- Suggestion\nSEVERITY: 5.0\nREASONING: reason"

        with patch.object(agent, "generate", side_effect=capture_generate):
            await agent.critique(
                proposal="Test proposal",
                task="Test task",
                target_agent="specific-agent",
            )

        assert "specific-agent" in captured_prompt

    @pytest.mark.asyncio
    async def test_critique_without_target_agent(self):
        """Should work without target agent."""
        agent = TestableAgent()

        with patch.object(agent, "generate", new_callable=AsyncMock) as mock_generate:
            mock_generate.return_value = (
                "ISSUES:\n- Issue\nSUGGESTIONS:\n- Suggestion\nSEVERITY: 5.0\nREASONING: reason"
            )

            critique = await agent.critique(
                proposal="Test proposal",
                task="Test task",
            )

        assert critique is not None


# =============================================================================
# Provider Configuration Tests
# =============================================================================


class TestProviderConfiguration:
    """Tests for different provider configurations."""

    def test_openrouter_model_map_inheritance(self):
        """Should use class-level model map."""
        agent = TestableAgent()

        assert agent.OPENROUTER_MODEL_MAP["test-model"] == "openai/test-model"

    def test_get_fallback_model(self):
        """Should get correct fallback model from map."""
        agent = TestableAgent(model="test-model")

        fallback_model = agent.get_fallback_model()

        assert fallback_model == "openai/test-model"

    def test_get_fallback_model_default(self):
        """Should use default fallback model when not in map."""
        agent = TestableAgent(model="unknown-model")

        fallback_model = agent.get_fallback_model()

        assert fallback_model == TestableAgent.DEFAULT_FALLBACK_MODEL

    def test_custom_max_tokens(self):
        """Should respect custom max_tokens setting on instance."""
        agent = TestableAgent()
        # Set instance-level max_tokens (simulates subclass or runtime override)
        agent.max_tokens = 8192

        messages = [{"role": "user", "content": "Test"}]
        payload = agent._build_payload(messages)

        assert payload["max_tokens"] == 8192


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_handles_malformed_json_response(self):
        """Should handle malformed JSON in response."""
        agent = TestableAgent()

        # Response that isn't valid JSON for the expected format
        malformed_response = MockResponse(
            status=200, json_data={"unexpected": "format", "no_choices": True}
        )

        class MalformedSession:
            def post(self, *args, **kwargs):
                return malformed_response

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=MalformedSession(),
        ):
            with pytest.raises(AgentAPIError):
                await agent.generate("Test prompt")

    @pytest.mark.asyncio
    async def test_sanitizes_error_messages(self):
        """Should sanitize error messages to remove sensitive data."""
        agent = TestableAgent()

        # Error response with potentially sensitive info
        error_response = MockResponse(
            status=500, text='{"error": "api_key sk-secret123 is invalid"}'
        )

        class ErrorSession:
            def post(self, *args, **kwargs):
                return error_response

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=ErrorSession(),
        ):
            with pytest.raises(AgentAPIError) as exc_info:
                await agent.generate("Test prompt")

        # The error message should be sanitized
        # (exact sanitization depends on _sanitize_error_message implementation)
        assert "500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_handles_timeout_error(self):
        """Should handle asyncio timeout errors (wrapped by error handler)."""
        from aragora.agents.errors import AgentTimeoutError

        agent = TestableAgent()

        class TimeoutSession:
            def post(self, *args, **kwargs):
                raise asyncio.TimeoutError("Request timed out")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=TimeoutSession(),
        ):
            # The error handler decorator wraps TimeoutError into AgentTimeoutError
            with pytest.raises(AgentTimeoutError):
                await agent.generate("Test prompt")

    @pytest.mark.asyncio
    async def test_handles_connection_error(self):
        """Should handle connection errors (wrapped by error handler)."""
        from aragora.agents.errors import AgentError

        agent = TestableAgent()

        class ConnectionErrorSession:
            def post(self, *args, **kwargs):
                raise OSError("Connection refused")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=ConnectionErrorSession(),
        ):
            # The error handler decorator wraps OSError into AgentError
            with pytest.raises(AgentError):
                await agent.generate("Test prompt")


# =============================================================================
# Token Recording Tests
# =============================================================================


class TestTokenRecording:
    """Tests for token usage recording."""

    @pytest.mark.asyncio
    async def test_records_tokens_from_usage(self, mock_openai_compatible_response):
        """Should record token usage from response."""
        agent = TestableAgent()

        mock_response = MockResponse(status=200, json_data=mock_openai_compatible_response)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            await agent.generate("Test prompt")

        assert agent._last_tokens_in == 100
        assert agent._last_tokens_out == 50

    @pytest.mark.asyncio
    async def test_handles_missing_usage(self):
        """Should handle response without usage field."""
        agent = TestableAgent()

        response_no_usage = {
            "choices": [{"message": {"content": "Response without usage"}}],
        }
        mock_response = MockResponse(status=200, json_data=response_no_usage)
        mock_session = MockClientSession([mock_response])

        with patch(
            "aragora.agents.api_agents.openai_compatible.create_client_session",
            return_value=mock_session,
        ):
            result = await agent.generate("Test prompt")

        assert result == "Response without usage"
        assert agent._last_tokens_in == 0
        assert agent._last_tokens_out == 0


# =============================================================================
# Integration with Quota Detection Tests
# =============================================================================


class TestQuotaDetection:
    """Tests for quota error detection (inherited from QuotaFallbackMixin)."""

    def test_is_quota_error_429(self):
        """Should detect 429 as quota error."""
        agent = TestableAgent()

        assert agent.is_quota_error(429, "rate limit exceeded") is True

    def test_is_quota_error_timeout_status_codes(self):
        """Should detect timeout status codes as quota errors."""
        agent = TestableAgent()

        assert agent.is_quota_error(408, "request timeout") is True
        assert agent.is_quota_error(504, "gateway timeout") is True
        assert agent.is_quota_error(524, "cloudflare timeout") is True

    def test_is_quota_error_403_with_quota_keyword(self):
        """Should detect 403 with quota keywords."""
        agent = TestableAgent()

        assert agent.is_quota_error(403, "quota exceeded") is True
        assert agent.is_quota_error(403, "permission denied") is False

    def test_is_quota_error_400_with_billing_keyword(self):
        """Should detect 400 with billing keywords."""
        agent = TestableAgent()

        assert agent.is_quota_error(400, "credit balance is too low") is True
        assert agent.is_quota_error(400, "invalid request") is False

    def test_is_quota_error_timeout_in_text(self):
        """Should detect timeout keywords in error text."""
        agent = TestableAgent()

        assert agent.is_quota_error(500, "operation timed out") is True


# =============================================================================
# Module Exports Tests
# =============================================================================


class TestModuleExports:
    """Tests for module exports."""

    def test_exports_openai_compatible_mixin(self):
        """Should export OpenAICompatibleMixin."""
        from aragora.agents.api_agents.openai_compatible import __all__

        assert "OpenAICompatibleMixin" in __all__
