"""
Tests for API Agents Common Module.

Covers:
- Connection pool management
- SSE stream parsing
- Retry delay calculation
- Session creation
- Error handling
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestConnectionPoolState:
    """Tests for ConnectionPoolState dataclass."""

    def test_reset_clears_state(self):
        """Reset should clear all pool state."""
        from aragora.agents.api_agents.common import ConnectionPoolState

        state = ConnectionPoolState()
        state.connector = MagicMock()
        state.loop_id = 12345
        state.pending_close_tasks.add(MagicMock())

        state.reset()

        assert state.connector is None
        assert state.loop_id is None
        assert len(state.pending_close_tasks) == 0

    def test_lock_is_threading_lock(self):
        """Lock should be a threading lock for thread safety."""
        from aragora.agents.api_agents.common import ConnectionPoolState

        state = ConnectionPoolState()
        # threading.Lock is a factory function creating _thread.lock
        assert "lock" in type(state.lock).__name__.lower()


class TestGetSharedConnector:
    """Tests for get_shared_connector function."""

    @pytest.fixture(autouse=True)
    async def reset_pool_state(self):
        """Reset pool state before and after each test."""
        from aragora.agents.api_agents.common import _pool_state

        _pool_state.reset()
        yield
        _pool_state.reset()

    @pytest.mark.asyncio
    async def test_creates_connector_on_first_call(self):
        """Should create a new connector on first call."""
        from aragora.agents.api_agents.common import _pool_state, get_shared_connector

        assert _pool_state.connector is None

        connector = get_shared_connector()

        assert connector is not None
        assert _pool_state.connector is connector

    @pytest.mark.asyncio
    async def test_returns_same_connector_on_subsequent_calls(self):
        """Should return the same connector on subsequent calls."""
        from aragora.agents.api_agents.common import get_shared_connector

        connector1 = get_shared_connector()
        connector2 = get_shared_connector()

        assert connector1 is connector2

    @pytest.mark.asyncio
    async def test_creates_new_connector_when_closed(self):
        """Should create new connector if existing one is closed."""
        from aragora.agents.api_agents.common import _pool_state, get_shared_connector

        connector1 = get_shared_connector()
        # Simulate closed connector
        _pool_state.connector = MagicMock()
        _pool_state.connector.closed = True

        connector2 = get_shared_connector()

        assert connector2 is not connector1


class TestCalculateRetryDelay:
    """Tests for calculate_retry_delay function."""

    def test_first_attempt_base_delay(self):
        """First attempt should be around base delay."""
        from aragora.agents.api_agents.common import calculate_retry_delay

        delay = calculate_retry_delay(0, base_delay=1.0, jitter_factor=0.0)
        assert delay == 1.0

    def test_exponential_backoff(self):
        """Delay should increase exponentially."""
        from aragora.agents.api_agents.common import calculate_retry_delay

        delay0 = calculate_retry_delay(0, base_delay=1.0, jitter_factor=0.0)
        delay1 = calculate_retry_delay(1, base_delay=1.0, jitter_factor=0.0)
        delay2 = calculate_retry_delay(2, base_delay=1.0, jitter_factor=0.0)

        assert delay1 == 2.0
        assert delay2 == 4.0

    def test_max_delay_cap(self):
        """Delay should be capped at max_delay."""
        from aragora.agents.api_agents.common import calculate_retry_delay

        delay = calculate_retry_delay(10, base_delay=1.0, max_delay=60.0, jitter_factor=0.0)
        assert delay == 60.0

    def test_jitter_adds_randomness(self):
        """Jitter should add randomness within bounds."""
        from aragora.agents.api_agents.common import calculate_retry_delay

        delays = [calculate_retry_delay(0, base_delay=1.0, jitter_factor=0.3) for _ in range(100)]

        # With 30% jitter, delays should be in range [0.7, 1.3]
        # But minimum is 0.1, so effectively [0.7, 1.3]
        assert all(0.1 <= d <= 1.4 for d in delays)
        # Check there's actual variation
        assert len(set(delays)) > 1

    def test_minimum_delay_floor(self):
        """Delay should never be less than 0.1."""
        from aragora.agents.api_agents.common import calculate_retry_delay

        # With extreme negative jitter, delay should still be >= 0.1
        delays = [calculate_retry_delay(0, base_delay=0.1, jitter_factor=1.0) for _ in range(100)]
        assert all(d >= 0.1 for d in delays)


class TestSSEStreamParser:
    """Tests for SSEStreamParser class."""

    @pytest.fixture
    def simple_extractor(self):
        """Simple content extractor for testing."""
        return lambda event: event.get("content", "")

    @pytest.fixture
    def openai_extractor(self):
        """OpenAI-style content extractor."""
        return lambda event: event.get("choices", [{}])[0].get("delta", {}).get("content", "")

    @pytest.mark.asyncio
    async def test_parses_single_event(self, simple_extractor):
        """Should parse a single SSE event."""
        from aragora.agents.api_agents.common import SSEStreamParser

        parser = SSEStreamParser(content_extractor=simple_extractor)

        # Create mock stream - iter_any should return the async iterator directly
        mock_content = MagicMock()
        mock_content.iter_any.return_value = AsyncIterator(
            [b'data: {"content": "Hello"}\n\n', b"data: [DONE]\n\n"]
        )

        chunks = []
        async for chunk in parser.parse_stream(mock_content, "test"):
            chunks.append(chunk)

        assert chunks == ["Hello"]

    @pytest.mark.asyncio
    async def test_parses_multiple_events(self, simple_extractor):
        """Should parse multiple SSE events."""
        from aragora.agents.api_agents.common import SSEStreamParser

        parser = SSEStreamParser(content_extractor=simple_extractor)

        mock_content = MagicMock()
        mock_content.iter_any.return_value = AsyncIterator(
            [
                b'data: {"content": "Hello "}\n\n',
                b'data: {"content": "World"}\n\n',
                b"data: [DONE]\n\n",
            ]
        )

        chunks = []
        async for chunk in parser.parse_stream(mock_content, "test"):
            chunks.append(chunk)

        assert chunks == ["Hello ", "World"]

    @pytest.mark.asyncio
    async def test_handles_partial_chunks(self, simple_extractor):
        """Should handle partial chunks split across network packets."""
        from aragora.agents.api_agents.common import SSEStreamParser

        parser = SSEStreamParser(content_extractor=simple_extractor)

        # Chunk split in the middle
        mock_content = MagicMock()
        mock_content.iter_any.return_value = AsyncIterator(
            [b'data: {"conte', b'nt": "Hello"}\n\n', b"data: [DONE]\n\n"]
        )

        chunks = []
        async for chunk in parser.parse_stream(mock_content, "test"):
            chunks.append(chunk)

        assert chunks == ["Hello"]

    @pytest.mark.asyncio
    async def test_ignores_empty_lines(self, simple_extractor):
        """Should ignore empty lines in SSE stream."""
        from aragora.agents.api_agents.common import SSEStreamParser

        parser = SSEStreamParser(content_extractor=simple_extractor)

        mock_content = MagicMock()
        mock_content.iter_any.return_value = AsyncIterator(
            [b"\n\n", b'data: {"content": "Hello"}\n\n', b"\n", b"data: [DONE]\n\n"]
        )

        chunks = []
        async for chunk in parser.parse_stream(mock_content, "test"):
            chunks.append(chunk)

        assert chunks == ["Hello"]

    @pytest.mark.asyncio
    async def test_ignores_non_data_lines(self, simple_extractor):
        """Should ignore non-data SSE lines like comments."""
        from aragora.agents.api_agents.common import SSEStreamParser

        parser = SSEStreamParser(content_extractor=simple_extractor)

        mock_content = MagicMock()
        mock_content.iter_any.return_value = AsyncIterator(
            [
                b": this is a comment\n",
                b'data: {"content": "Hello"}\n\n',
                b"event: ping\n",
                b"data: [DONE]\n\n",
            ]
        )

        chunks = []
        async for chunk in parser.parse_stream(mock_content, "test"):
            chunks.append(chunk)

        assert chunks == ["Hello"]

    @pytest.mark.asyncio
    async def test_buffer_overflow_protection(self, simple_extractor):
        """Should raise error if buffer exceeds max size."""
        from aragora.agents.api_agents.common import SSEStreamParser
        from aragora.agents.errors import AgentStreamError

        parser = SSEStreamParser(content_extractor=simple_extractor, max_buffer_size=100)

        # Send a chunk larger than max buffer
        mock_content = MagicMock()
        mock_content.iter_any.return_value = AsyncIterator([b"x" * 200])

        with pytest.raises(AgentStreamError, match="buffer exceeded maximum size"):
            async for _ in parser.parse_stream(mock_content, "test"):
                pass

    @pytest.mark.asyncio
    async def test_handles_json_decode_errors(self, simple_extractor):
        """Should handle invalid JSON gracefully."""
        from aragora.agents.api_agents.common import SSEStreamParser

        parser = SSEStreamParser(content_extractor=simple_extractor)

        mock_content = MagicMock()
        mock_content.iter_any.return_value = AsyncIterator(
            [
                b"data: {invalid json}\n\n",
                b'data: {"content": "Valid"}\n\n',
                b"data: [DONE]\n\n",
            ]
        )

        chunks = []
        async for chunk in parser.parse_stream(mock_content, "test"):
            chunks.append(chunk)

        # Should continue after invalid JSON and get valid content
        assert "Valid" in chunks

    @pytest.mark.asyncio
    async def test_openai_style_extraction(self, openai_extractor):
        """Should work with OpenAI-style nested JSON."""
        from aragora.agents.api_agents.common import SSEStreamParser

        parser = SSEStreamParser(content_extractor=openai_extractor)

        mock_content = MagicMock()
        mock_content.iter_any.return_value = AsyncIterator(
            [
                b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n',
                b'data: {"choices": [{"delta": {"content": " World"}}]}\n\n',
                b"data: [DONE]\n\n",
            ]
        )

        chunks = []
        async for chunk in parser.parse_stream(mock_content, "test"):
            chunks.append(chunk)

        assert chunks == ["Hello", " World"]


class TestCreateClientSession:
    """Tests for create_client_session function."""

    @pytest.fixture(autouse=True)
    async def reset_pool_state(self):
        """Reset pool state before and after each test."""
        from aragora.agents.api_agents.common import _pool_state

        _pool_state.reset()
        yield
        _pool_state.reset()

    @pytest.mark.asyncio
    async def test_creates_session_with_shared_connector(self):
        """Should create session using shared connector."""
        from aragora.agents.api_agents.common import _pool_state, create_client_session

        session = create_client_session()

        # Session should use the shared connector
        assert session.connector is _pool_state.connector
        # Connector should NOT be owned by session (for reuse)
        assert session._connector_owner is False

    @pytest.mark.asyncio
    async def test_custom_timeout(self):
        """Should apply custom timeout."""
        from aragora.agents.api_agents.common import create_client_session

        session = create_client_session(timeout=30.0)

        assert session._timeout.total == 30.0

    @pytest.mark.asyncio
    async def test_default_timeout(self):
        """Should use default timeout if not specified."""
        from aragora.agents.api_agents.common import (
            DEFAULT_REQUEST_TIMEOUT,
            create_client_session,
        )

        session = create_client_session()

        assert session._timeout.total == DEFAULT_REQUEST_TIMEOUT


class TestGetConnectionLimits:
    """Tests for _get_connection_limits function."""

    def test_returns_defaults_without_settings(self):
        """Should return defaults when settings don't have custom values."""
        from aragora.agents.api_agents.common import (
            DEFAULT_CONNECTIONS_PER_HOST,
            DEFAULT_TOTAL_CONNECTIONS,
            _get_connection_limits,
        )

        per_host, total = _get_connection_limits()

        # Should return configured or default values
        assert isinstance(per_host, int)
        assert isinstance(total, int)


class TestCloseSharedConnector:
    """Tests for close_shared_connector function."""

    @pytest.fixture(autouse=True)
    def reset_pool_state(self):
        """Reset pool state before and after each test."""
        from aragora.agents.api_agents.common import _pool_state

        _pool_state.reset()
        yield
        _pool_state.reset()

    @pytest.mark.asyncio
    async def test_closes_connector(self):
        """Should close the shared connector."""
        from aragora.agents.api_agents.common import (
            _pool_state,
            close_shared_connector,
            get_shared_connector,
        )

        # Create a connector first
        connector = get_shared_connector()
        assert connector is not None

        await close_shared_connector()

        assert _pool_state.connector is None
        assert _pool_state.loop_id is None

    @pytest.mark.asyncio
    async def test_does_not_hold_lock_while_awaiting_close(self):
        """Connector close should run after lock release to avoid lock contention."""
        from aragora.agents.api_agents.common import _pool_state, close_shared_connector

        class ProbeConnector:
            def __init__(self):
                self.closed = False
                self.lock_held_during_close = False

            async def close(self):
                acquired = _pool_state.lock.acquire(blocking=False)
                if acquired:
                    _pool_state.lock.release()
                else:
                    self.lock_held_during_close = True
                self.closed = True

        probe = ProbeConnector()
        _pool_state.connector = probe  # type: ignore[assignment]
        _pool_state.loop_id = 12345

        await close_shared_connector()

        assert probe.closed is True
        assert probe.lock_held_during_close is False
        assert _pool_state.connector is None
        assert _pool_state.loop_id is None

    @pytest.mark.asyncio
    async def test_safe_to_call_multiple_times(self):
        """Should be safe to call close multiple times."""
        from aragora.agents.api_agents.common import close_shared_connector

        # Should not raise
        await close_shared_connector()
        await close_shared_connector()


class TestTracingIntegration:
    """Tests for tracing integration."""

    def test_get_trace_headers_returns_dict(self):
        """get_trace_headers should return a dict."""
        from aragora.agents.api_agents.common import get_trace_headers

        headers = get_trace_headers()
        assert isinstance(headers, dict)


class TestOpenRouterFallback:
    """Tests for OpenRouter fallback functionality."""

    def test_is_openrouter_fallback_available_returns_bool(self):
        """is_openrouter_fallback_available should return a bool."""
        from aragora.agents.api_agents.common import is_openrouter_fallback_available

        result = is_openrouter_fallback_available()
        assert isinstance(result, bool)


# Helper class for async iteration in tests
class AsyncIterator:
    """Helper class to create async iterators for testing."""

    def __init__(self, items):
        self.items = items
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.items):
            raise StopAsyncIteration
        item = self.items[self.index]
        self.index += 1
        return item
