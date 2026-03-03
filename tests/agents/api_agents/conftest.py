"""
Shared fixtures for API agent tests.
"""

import asyncio
from typing import Any, Optional
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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


@pytest.fixture
def mock_anthropic_response():
    """Standard Anthropic API response."""
    return {
        "id": "msg_01XFDUDYJgAACzvnptvVoYEL",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "This is a test response from Claude."}],
        "model": "claude-opus-4-6",
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 50},
    }


@pytest.fixture
def mock_anthropic_web_search_response():
    """Anthropic API response with web search results."""
    return {
        "id": "msg_02XFDUDYJgAACzvnptvVoYEL",
        "type": "message",
        "role": "assistant",
        "content": [
            {"type": "text", "text": "Based on my search, here is the information:"},
            {
                "type": "web_search_tool_result",
                "content": [
                    {
                        "type": "web_search_result",
                        "title": "Example Page",
                        "url": "https://example.com/page",
                    }
                ],
            },
        ],
        "model": "claude-opus-4-6",
        "usage": {"input_tokens": 150, "output_tokens": 75},
    }


@pytest.fixture
def mock_openai_response():
    """Standard OpenAI API response."""
    return {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-5.2",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "This is a test response from GPT."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


@pytest.fixture
def mock_mistral_response():
    """Standard Mistral API response."""
    return {
        "id": "cmpl-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "mistral-large-2512",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "This is a test response from Mistral.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


@pytest.fixture
def mock_openrouter_response():
    """Standard OpenRouter API response."""
    return {
        "id": "gen-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "deepseek/deepseek-chat",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "This is a test response from DeepSeek.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


@pytest.fixture
def mock_sse_chunks():
    """SSE chunks for streaming response tests (OpenAI format)."""
    return [
        b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n',
        b'data: {"choices":[{"delta":{"content":"!"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]


@pytest.fixture
def mock_anthropic_sse_chunks():
    """SSE chunks for Anthropic streaming response tests."""
    return [
        b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n',
        b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n',
        b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" world"}}\n\n',
        b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ]


@pytest.fixture
def mock_rate_limit_response():
    """Rate limit (429) error response."""
    return MockResponse(
        status=429,
        text='{"error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}}',
        headers={"Retry-After": "30"},
    )


@pytest.fixture
def mock_quota_error_response():
    """Quota/billing error response."""
    return MockResponse(
        status=400,
        text='{"error": {"message": "Your credit balance is too low", "type": "billing_error"}}',
    )


@pytest.fixture
def mock_api_error_response():
    """Generic API error response."""
    return MockResponse(
        status=500,
        text='{"error": {"message": "Internal server error", "type": "server_error"}}',
    )


@pytest.fixture
def mock_empty_response():
    """Empty content response."""
    return {
        "id": "chatcmpl-empty",
        "choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10},
    }


@pytest.fixture
def mock_env_with_api_keys(monkeypatch):
    """Set up environment with mock API keys."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-mistral-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
    monkeypatch.setenv("GROK_API_KEY", "test-grok-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    # Keep fallback enabled by default so initialization behavior matches
    # production defaults and explicit test assertions.
    monkeypatch.setenv("ARAGORA_OPENROUTER_FALLBACK_ENABLED", "true")


@pytest.fixture
def mock_env_with_fallback_enabled(monkeypatch):
    """Set up environment with mock API keys and fallback explicitly enabled."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setenv("ARAGORA_OPENROUTER_FALLBACK_ENABLED", "true")


@pytest.fixture
def mock_env_no_api_keys(monkeypatch):
    """Clear all API keys from environment."""
    monkeypatch.setenv("ARAGORA_SKIP_SECRETS_HYDRATION", "1")
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    for key in [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "MISTRAL_API_KEY",
        "OPENROUTER_API_KEY",
        "XAI_API_KEY",
        "GROK_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "KIMI_API_KEY",
    ]:
        monkeypatch.delenv(key, raising=False)
    # Reset secret manager cache so it doesn't reuse previously loaded AWS secrets.
    try:
        from aragora.config.secrets import reset_secret_manager

        reset_secret_manager()
    except Exception:
        pass


@pytest.fixture
def sample_context():
    """Sample message context for testing."""
    from aragora.core import Message

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
def mock_openrouter_limiter():
    """Mock rate limiter for OpenRouter tests."""
    limiter = MagicMock()
    limiter.acquire = AsyncMock(return_value=True)
    limiter.update_from_headers = MagicMock()
    limiter.record_rate_limit_error = MagicMock(return_value=30.0)
    limiter.record_success = MagicMock()
    limiter.release_on_error = MagicMock()
    return limiter


# ============================================================================
# Gemini (Google Generative AI) Mock Responses
# ============================================================================


@pytest.fixture
def mock_gemini_response():
    """Mock Gemini API response."""
    return {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "This is a test response from Gemini."}],
                    "role": "model",
                },
                "finishReason": "STOP",
                "index": 0,
                "safetyRatings": [
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "probability": "NEGLIGIBLE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "probability": "NEGLIGIBLE"},
                    {"category": "HARM_CATEGORY_HARASSMENT", "probability": "NEGLIGIBLE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "probability": "NEGLIGIBLE"},
                ],
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 20,
            "totalTokenCount": 30,
        },
    }


@pytest.fixture
def mock_gemini_stream_chunks():
    """SSE chunks for Gemini streaming response tests."""
    return [
        b'data: {"candidates":[{"content":{"parts":[{"text":"Hello"}],"role":"model"},"index":0}]}\n\n',
        b'data: {"candidates":[{"content":{"parts":[{"text":" from"}],"role":"model"},"index":0}]}\n\n',
        b'data: {"candidates":[{"content":{"parts":[{"text":" Gemini!"}],"role":"model"},"finishReason":"STOP","index":0}]}\n\n',
    ]


@pytest.fixture
def mock_gemini_grounded_response():
    """Mock Gemini response with Google Search grounding."""
    return {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Based on recent web search results..."}],
                    "role": "model",
                },
                "finishReason": "STOP",
                "index": 0,
                "groundingMetadata": {
                    "searchEntryPoint": {"renderedContent": "<html>...</html>"},
                    "groundingChunks": [
                        {"web": {"uri": "https://example.com", "title": "Example"}}
                    ],
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 15,
            "candidatesTokenCount": 25,
            "totalTokenCount": 40,
        },
    }


# ============================================================================
# Grok (xAI) Mock Responses
# ============================================================================


@pytest.fixture
def mock_grok_response():
    """Mock Grok (xAI) API response - OpenAI compatible format."""
    return {
        "id": "chatcmpl-grok-test123",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "grok-3",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "This is a test response from Grok.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


@pytest.fixture
def mock_grok_stream_chunks():
    """SSE chunks for Grok streaming response tests (OpenAI format)."""
    return [
        b'data: {"id":"chatcmpl-grok","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"Hello"}}]}\n\n',
        b'data: {"id":"chatcmpl-grok","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":" from"}}]}\n\n',
        b'data: {"id":"chatcmpl-grok","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":" Grok!"}}]}\n\n',
        b"data: [DONE]\n\n",
    ]


@pytest.fixture
def mock_env_with_gemini_key(monkeypatch):
    """Set up environment with Gemini API key."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")


@pytest.fixture
def mock_env_with_grok_key(monkeypatch):
    """Set up environment with Grok/xAI API key."""
    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
    monkeypatch.setenv("GROK_API_KEY", "test-grok-key")


@pytest.fixture(autouse=True)
def _reset_circuit_breakers_between_tests():
    """Clear all circuit breaker singletons before each test.

    Circuit breakers are shared singletons per agent type.  If an earlier test
    drives a breaker into OPEN state — or patches ``can_proceed`` with a
    MagicMock — the next test inherits that corrupted state.  Clearing the
    dict forces fresh breaker creation.
    """
    from aragora.resilience.circuit_breaker_v2 import (
        _circuit_breakers,
        _circuit_breakers_lock,
    )

    with _circuit_breakers_lock:
        _circuit_breakers.clear()
    yield
    with _circuit_breakers_lock:
        _circuit_breakers.clear()


@pytest.fixture(autouse=True)
def _restore_create_client_session():
    """Re-establish create_client_session on agent modules before each test.

    Several agent modules (crewai_agent, langgraph_agent, lm_studio) bind
    ``create_client_session`` at module level.  When earlier tests in the full
    suite patch this attribute and cleanup goes wrong (e.g. ``delattr`` instead
    of ``setattr`` on restore), the binding disappears and subsequent patches
    fail with ``AttributeError: does not have the attribute``.

    This fixture defensively re-establishes the binding from the canonical
    source (``api_common``) before *and* after every test.
    """
    from aragora.agents.api_agents import common as api_common

    modules_to_fix = []
    for mod_name in (
        "aragora.agents.api_agents.anthropic",
        "aragora.agents.api_agents.crewai_agent",
        "aragora.agents.api_agents.gemini",
        "aragora.agents.api_agents.langgraph_agent",
        "aragora.agents.api_agents.lm_studio",
        "aragora.agents.api_agents.ollama",
        "aragora.agents.api_agents.openai_compatible",
        "aragora.agents.api_agents.openrouter",
    ):
        import sys

        mod = sys.modules.get(mod_name)
        if mod is not None:
            modules_to_fix.append(mod)

    def _ensure_binding():
        for mod in modules_to_fix:
            if not hasattr(mod, "create_client_session") or not callable(
                getattr(mod, "create_client_session", None)
            ):
                mod.create_client_session = api_common.create_client_session

    _ensure_binding()
    yield
    _ensure_binding()


@pytest.fixture(autouse=True)
def _allow_localhost_for_api_agents(monkeypatch):
    """Ensure localhost is allowed for API agent tests.

    Many API agents (AutoGen, CrewAI, etc.) default to localhost URLs.
    This requires:
    1. ARAGORA_SSRF_ALLOW_LOCALHOST=true (from test_environment fixture)
    2. ARAGORA_ENV must NOT be 'production' (blocks localhost even with override)

    This fixture ensures ARAGORA_ENV doesn't block localhost access for these tests.
    """
    monkeypatch.delenv("ARAGORA_ENV", raising=False)
