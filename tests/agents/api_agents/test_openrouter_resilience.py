"""
Tests for OpenRouter streaming resilience: circuit breaker and @handle_stream_errors.

Tests cover:
- Circuit breaker blocking streaming when open
- Circuit breaker recording success after successful stream
- Circuit breaker recording failure on stream errors
- @handle_stream_errors wrapping unexpected errors during iteration
- Rate limit retry still works in streaming path
"""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from aragora.agents.api_agents.common import (
    AgentCircuitOpenError,
    AgentConnectionError,
    AgentRateLimitError,
    AgentStreamError,
)


class TestStreamingCircuitBreaker:
    """Tests for circuit breaker integration in generate_stream."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_blocks_streaming_when_open(self, mock_env_with_api_keys):
        """Should raise AgentCircuitOpenError when circuit breaker is open."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        agent = OpenRouterAgent()
        # Force circuit breaker open
        agent._circuit_breaker = MagicMock()
        agent._circuit_breaker.can_proceed.return_value = False

        with pytest.raises(AgentCircuitOpenError, match="Circuit breaker open"):
            async for _ in agent.generate_stream("Test prompt"):
                pass

    @pytest.mark.asyncio
    async def test_circuit_breaker_allows_streaming_when_closed(
        self, mock_env_with_api_keys, mock_sse_chunks, mock_openrouter_limiter
    ):
        """Should allow streaming when circuit breaker is closed."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockStreamResponse

        agent = OpenRouterAgent()
        agent._circuit_breaker = MagicMock()
        agent._circuit_breaker.can_proceed.return_value = True

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

        # Circuit breaker should record success
        agent._circuit_breaker.record_success.assert_called()

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failure_on_api_error(
        self, mock_env_with_api_keys, mock_openrouter_limiter
    ):
        """Should record circuit breaker failure on non-200 API response."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockResponse

        agent = OpenRouterAgent()
        agent._circuit_breaker = MagicMock()
        agent._circuit_breaker.can_proceed.return_value = True

        mock_response = MockResponse(status=500, text='{"error": "Internal error"}')

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

                with pytest.raises(AgentStreamError, match="500"):
                    async for _ in agent.generate_stream("Test prompt"):
                        pass

        agent._circuit_breaker.record_failure.assert_called()

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failure_on_connection_error(
        self, mock_env_with_api_keys, mock_openrouter_limiter
    ):
        """Should record circuit breaker failure when connection fails after retries."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        agent = OpenRouterAgent()
        agent._circuit_breaker = MagicMock()
        agent._circuit_breaker.can_proceed.return_value = True

        with patch(
            "aragora.agents.api_agents.openrouter.get_openrouter_limiter",
            return_value=mock_openrouter_limiter,
        ):
            with patch("aragora.agents.api_agents.openrouter.create_client_session") as mock_create:
                mock_session = MagicMock()
                mock_session.post = MagicMock(
                    side_effect=aiohttp.ClientConnectorError(
                        connection_key=MagicMock(), os_error=OSError("Connection refused")
                    )
                )
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=None)
                mock_create.return_value = mock_session

                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(AgentConnectionError):
                        async for _ in agent.generate_stream("Test prompt"):
                            pass

        agent._circuit_breaker.record_failure.assert_called()

    @pytest.mark.asyncio
    async def test_circuit_breaker_not_required(
        self, mock_env_with_api_keys, mock_sse_chunks, mock_openrouter_limiter
    ):
        """Should work without circuit breaker (enable_circuit_breaker=False)."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        agent = OpenRouterAgent()
        agent._circuit_breaker = None  # Disable circuit breaker

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.headers = {}
        mock_response.content = MagicMock()

        # Create async iterator for content
        class AsyncContent:
            def __init__(self):
                self._done = False

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._done:
                    raise StopAsyncIteration
                self._done = True
                return b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\ndata: [DONE]\n\n'

            def iter_any(self):
                return self

        mock_response.content = AsyncContent()
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=None)

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

                # Should not raise - no circuit breaker to block
                chunks = []
                async for chunk in agent.generate_stream("Test prompt"):
                    chunks.append(chunk)

                # No circuit breaker means no record_success/failure calls to check
                assert True  # Reached here without error


class TestStreamingRateLimitRetry:
    """Tests for rate limit retry in streaming path."""

    @pytest.mark.asyncio
    async def test_streaming_retries_on_429(
        self, mock_env_with_api_keys, mock_sse_chunks, mock_openrouter_limiter
    ):
        """Should retry streaming request on 429 rate limit."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockResponse, MockStreamResponse

        agent = OpenRouterAgent()

        call_count = [0]

        def create_response():
            call_count[0] += 1
            if call_count[0] == 1:
                return MockResponse(
                    status=429,
                    text='{"error": "rate_limited"}',
                    headers={"Retry-After": "0.1"},
                )
            return MockStreamResponse(status=200, chunks=mock_sse_chunks)

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
                    chunks = []
                    async for chunk in agent.generate_stream("Test prompt"):
                        chunks.append(chunk)

        assert call_count[0] >= 2

    @pytest.mark.asyncio
    async def test_streaming_rate_limit_exhausted_records_failure(
        self, mock_env_with_api_keys, mock_openrouter_limiter
    ):
        """Should record circuit breaker failure when streaming rate limit retries exhausted."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockResponse

        agent = OpenRouterAgent()
        agent._circuit_breaker = MagicMock()
        agent._circuit_breaker.can_proceed.return_value = True

        # Always return 429
        mock_response = MockResponse(
            status=429,
            text='{"error": "rate_limited"}',
            headers={"Retry-After": "0.1"},
        )

        with patch(
            "aragora.agents.api_agents.openrouter.get_openrouter_limiter",
            return_value=mock_openrouter_limiter,
        ):
            with patch("aragora.agents.api_agents.openrouter.create_client_session") as mock_create:

                class AlwaysRateLimitedSession:
                    def post(self, *args, **kwargs):
                        return mock_response

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        pass

                mock_create.return_value = AlwaysRateLimitedSession()

                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(AgentRateLimitError, match="429"):
                        async for _ in agent.generate_stream("Test prompt"):
                            pass

        agent._circuit_breaker.record_failure.assert_called()


class TestGenerateDecoratorIntegration:
    """Tests for @handle_agent_errors decorator on generate path."""

    @pytest.mark.asyncio
    async def test_generate_decorator_retries_on_rate_limit(
        self, mock_env_with_api_keys, mock_openrouter_response, mock_openrouter_limiter
    ):
        """Should retry via decorator when _generate_with_model raises AgentRateLimitError."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        agent = OpenRouterAgent()

        call_count = [0]

        def create_response():
            call_count[0] += 1
            if call_count[0] <= 2:
                return MockResponse(
                    status=429,
                    text='{"error": "rate_limited"}',
                    headers={"Retry-After": "0.1"},
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

                result = await agent.generate("Test prompt")

        assert result is not None
        assert call_count[0] >= 3

    @pytest.mark.asyncio
    async def test_generate_falls_back_after_retries_exhausted(
        self, mock_env_with_api_keys, mock_openrouter_response, mock_openrouter_limiter
    ):
        """Should fall back to alternate model after decorator retries exhausted."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent
        from tests.agents.api_agents.conftest import MockClientSession, MockResponse

        # deepseek-v4-pro is superseded by deepseek-v4-pro-0813
        # (frontier-model-refresh, 2026-09-04); this exercises the real
        # OPENROUTER_FALLBACK_MODELS key for the DeepSeek family.
        agent = OpenRouterAgent(model="deepseek/deepseek-v4-pro-0813")

        call_count = [0]

        def create_response():
            call_count[0] += 1
            if call_count[0] <= 5:
                # Keep returning 429 until the decorator retries and fallback are triggered
                return MockResponse(
                    status=429,
                    text='{"error": "rate_limited"}',
                    headers={"Retry-After": "0.01"},
                )
            # Fallback model succeeds
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

                result = await agent.generate("Test prompt")

        # Should succeed via fallback after primary model exhausts retries
        assert result is not None
        # Primary model retries + fallback model attempts
        assert call_count[0] > 4
