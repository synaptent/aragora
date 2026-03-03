"""
Tests for aragora.agents.api_agents.common module.

Tests connection pooling, retry logic, streaming utilities, and SSE parsing.
"""

import asyncio
import json
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from aragora.agents.api_agents.common import (
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_CONNECTIONS_PER_HOST,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_TOTAL_CONNECTIONS,
    SSEStreamParser,
    calculate_retry_delay,
    close_shared_connector,
    create_anthropic_sse_parser,
    create_client_session,
    create_openai_sse_parser,
    get_shared_connector,
    iter_chunks_with_timeout,
)
from aragora.agents.errors import AgentConnectionError, AgentStreamError


class TestConnectionPoolConstants:
    """Test connection pool default constants."""

    def test_default_connections_per_host(self):
        assert DEFAULT_CONNECTIONS_PER_HOST == 10

    def test_default_total_connections(self):
        assert DEFAULT_TOTAL_CONNECTIONS == 100

    def test_default_connect_timeout(self):
        assert DEFAULT_CONNECT_TIMEOUT == 30.0

    def test_default_request_timeout(self):
        assert DEFAULT_REQUEST_TIMEOUT == 120.0


class TestGetSharedConnector:
    """Test get_shared_connector singleton behavior."""

    @pytest.fixture(autouse=True)
    def reset_connector(self):
        """Reset global connector state before each test."""
        import aragora.agents.api_agents.common as common_module

        common_module._shared_connector = None
        common_module._connector_loop_id = None
        yield
        # Cleanup after test
        common_module._shared_connector = None
        common_module._connector_loop_id = None

    @pytest.mark.asyncio
    async def test_creates_connector(self):
        """Test that connector is created on first call."""
        connector = get_shared_connector()
        assert connector is not None
        assert isinstance(connector, aiohttp.TCPConnector)

    @pytest.mark.asyncio
    async def test_returns_same_connector(self):
        """Test singleton pattern - same connector returned."""
        connector1 = get_shared_connector()
        connector2 = get_shared_connector()
        assert connector1 is connector2

    @pytest.mark.asyncio
    async def test_connector_has_correct_limits(self):
        """Test connector is configured with proper limits."""
        connector = get_shared_connector()
        assert connector.limit == DEFAULT_TOTAL_CONNECTIONS
        assert connector.limit_per_host == DEFAULT_CONNECTIONS_PER_HOST


class TestCreateClientSession:
    """Test create_client_session factory."""

    @pytest.fixture(autouse=True)
    def reset_connector(self):
        """Reset global connector state."""
        import aragora.agents.api_agents.common as common_module

        common_module._shared_connector = None
        common_module._connector_loop_id = None
        yield
        common_module._shared_connector = None
        common_module._connector_loop_id = None

    @pytest.mark.asyncio
    async def test_creates_session_with_defaults(self):
        """Test session created with default settings."""
        session = create_client_session()
        assert session is not None
        assert isinstance(session, aiohttp.ClientSession)
        # Session should not own the connector
        assert session._connector_owner is False

    @pytest.mark.asyncio
    async def test_creates_session_with_custom_timeout(self):
        """Test session with custom timeout."""
        session = create_client_session(timeout=60.0)
        assert session is not None
        assert session._timeout.total == 60.0

    @pytest.mark.asyncio
    async def test_creates_session_with_custom_connector(self):
        """Test session with custom connector."""
        custom_connector = aiohttp.TCPConnector(limit=5)
        session = create_client_session(connector=custom_connector)
        assert session.connector is custom_connector


class TestCloseSharedConnector:
    """Test close_shared_connector cleanup."""

    @pytest.fixture(autouse=True)
    def reset_connector(self):
        """Reset global connector state."""
        import aragora.agents.api_agents.common as common_module

        common_module._shared_connector = None
        common_module._connector_loop_id = None
        yield
        common_module._shared_connector = None
        common_module._connector_loop_id = None

    @pytest.mark.asyncio
    async def test_closes_connector(self):
        """Test that connector is properly closed."""
        import aragora.agents.api_agents.common as common_module

        # Create a connector first
        connector = get_shared_connector()
        assert connector is not None
        assert not connector.closed

        # Close it
        await close_shared_connector()

        # Verify global state reset
        assert common_module._shared_connector is None
        assert common_module._connector_loop_id is None

    @pytest.mark.asyncio
    async def test_close_when_none_is_safe(self):
        """Test closing when no connector exists is safe."""
        # Should not raise
        await close_shared_connector()

    @pytest.mark.asyncio
    async def test_close_does_not_await_with_pool_lock_held(self):
        """close_shared_connector should release pool lock before awaiting close."""
        import aragora.agents.api_agents.common as common_module

        class ProbeConnector:
            def __init__(self):
                self.closed = False
                self.lock_held_during_close = False

            async def close(self):
                acquired = common_module._pool_state.lock.acquire(blocking=False)
                if acquired:
                    common_module._pool_state.lock.release()
                else:
                    self.lock_held_during_close = True
                self.closed = True

        probe = ProbeConnector()
        common_module._pool_state.connector = probe  # type: ignore[assignment]
        common_module._pool_state.loop_id = 999

        await close_shared_connector()

        assert probe.closed is True
        assert probe.lock_held_during_close is False


class TestCalculateRetryDelay:
    """Test exponential backoff with jitter."""

    def test_first_attempt_around_base_delay(self):
        """Test first attempt is around base delay."""
        delays = [calculate_retry_delay(0, base_delay=1.0) for _ in range(100)]
        avg = sum(delays) / len(delays)
        # Average should be close to 1.0 (within jitter range)
        assert 0.7 <= avg <= 1.3

    def test_exponential_growth(self):
        """Test delays grow exponentially."""
        delay_0 = calculate_retry_delay(0, base_delay=1.0, jitter_factor=0)
        delay_1 = calculate_retry_delay(1, base_delay=1.0, jitter_factor=0)
        delay_2 = calculate_retry_delay(2, base_delay=1.0, jitter_factor=0)

        assert delay_0 == pytest.approx(1.0)
        assert delay_1 == pytest.approx(2.0)
        assert delay_2 == pytest.approx(4.0)

    def test_respects_max_delay(self):
        """Test delay is capped at max_delay."""
        delay = calculate_retry_delay(10, base_delay=1.0, max_delay=30.0, jitter_factor=0)
        assert delay == 30.0

    def test_minimum_delay(self):
        """Test minimum delay of 0.1s is enforced."""
        # Even with negative jitter, should not go below 0.1
        delays = [calculate_retry_delay(0, base_delay=0.1, jitter_factor=0.9) for _ in range(100)]
        assert all(d >= 0.1 for d in delays)

    def test_jitter_adds_randomness(self):
        """Test jitter creates variation in delays."""
        delays = [calculate_retry_delay(0, base_delay=10.0, jitter_factor=0.3) for _ in range(100)]
        unique_delays = set(round(d, 4) for d in delays)
        # With jitter, we should have many unique values
        assert len(unique_delays) > 10


class TestIterChunksWithTimeout:
    """Test iter_chunks_with_timeout async generator."""

    @pytest.mark.asyncio
    async def test_yields_chunks(self):
        """Test that chunks are yielded correctly."""
        chunks = [b"hello", b" ", b"world"]

        async def mock_iter():
            for chunk in chunks:
                yield chunk

        mock_content = MagicMock()
        mock_content.iter_any.return_value = mock_iter()

        result = []
        async for chunk in iter_chunks_with_timeout(mock_content, chunk_timeout=1.0):
            result.append(chunk)

        assert result == chunks

    @pytest.mark.asyncio
    async def test_timeout_on_stalled_stream(self):
        """Test timeout is raised when stream stalls."""

        async def slow_iter():
            yield b"first"
            await asyncio.sleep(10)  # Stall
            yield b"never"

        mock_content = MagicMock()
        mock_content.iter_any.return_value = slow_iter()

        result = []
        with pytest.raises(asyncio.TimeoutError):
            async for chunk in iter_chunks_with_timeout(mock_content, chunk_timeout=0.1):
                result.append(chunk)

        # Should have received first chunk before timeout
        assert result == [b"first"]

    @pytest.mark.asyncio
    async def test_empty_stream(self):
        """Test empty stream completes normally."""

        async def empty_iter():
            return
            yield  # Make this a generator

        mock_content = MagicMock()
        mock_content.iter_any.return_value = empty_iter()

        result = []
        async for chunk in iter_chunks_with_timeout(mock_content, chunk_timeout=1.0):
            result.append(chunk)

        assert result == []


class TestSSEStreamParser:
    """Test SSE stream parsing."""

    @pytest.mark.asyncio
    async def test_parses_valid_sse_events(self):
        """Test parsing valid SSE data lines."""
        sse_data = b'data: {"content": "hello"}\n\ndata: {"content": "world"}\n\n'

        async def mock_iter():
            yield sse_data

        mock_content = MagicMock()
        mock_content.iter_any.return_value = mock_iter()

        parser = SSEStreamParser(
            content_extractor=lambda e: e.get("content", ""), chunk_timeout=1.0
        )

        result = []
        async for content in parser.parse_stream(mock_content):
            result.append(content)

        assert result == ["hello", "world"]

    @pytest.mark.asyncio
    async def test_handles_done_marker(self):
        """Test parsing stops at DONE marker."""
        sse_data = b'data: {"content": "hello"}\n\ndata: [DONE]\n\ndata: {"content": "ignored"}\n\n'

        async def mock_iter():
            yield sse_data

        mock_content = MagicMock()
        mock_content.iter_any.return_value = mock_iter()

        parser = SSEStreamParser(
            content_extractor=lambda e: e.get("content", ""), chunk_timeout=1.0
        )

        result = []
        async for content in parser.parse_stream(mock_content):
            result.append(content)

        assert result == ["hello"]

    @pytest.mark.asyncio
    async def test_skips_malformed_json(self):
        """Test malformed JSON is skipped gracefully."""
        sse_data = b'data: {"content": "valid"}\n\ndata: {invalid json\n\ndata: {"content": "also valid"}\n\n'

        async def mock_iter():
            yield sse_data

        mock_content = MagicMock()
        mock_content.iter_any.return_value = mock_iter()

        parser = SSEStreamParser(
            content_extractor=lambda e: e.get("content", ""), chunk_timeout=1.0
        )

        result = []
        async for content in parser.parse_stream(mock_content):
            result.append(content)

        assert result == ["valid", "also valid"]

    @pytest.mark.asyncio
    async def test_buffer_overflow_protection(self):
        """Test DoS protection via buffer size limit."""
        # Create data larger than max buffer
        large_data = b"data: " + b"x" * 1000 + b"\n"

        async def mock_iter():
            yield large_data

        mock_content = MagicMock()
        mock_content.iter_any.return_value = mock_iter()

        parser = SSEStreamParser(
            content_extractor=lambda e: e.get("content", ""),
            max_buffer_size=100,  # Small limit
            chunk_timeout=1.0,
        )

        with pytest.raises(AgentStreamError) as exc_info:
            async for _ in parser.parse_stream(mock_content, agent_name="test"):
                pass

        assert "buffer exceeded" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_skips_non_data_lines(self):
        """Test non-data lines are ignored."""
        sse_data = b'event: message\nid: 123\ndata: {"content": "hello"}\n\n'

        async def mock_iter():
            yield sse_data

        mock_content = MagicMock()
        mock_content.iter_any.return_value = mock_iter()

        parser = SSEStreamParser(
            content_extractor=lambda e: e.get("content", ""), chunk_timeout=1.0
        )

        result = []
        async for content in parser.parse_stream(mock_content):
            result.append(content)

        assert result == ["hello"]

    @pytest.mark.asyncio
    async def test_handles_chunked_data(self):
        """Test SSE data split across multiple chunks."""

        async def mock_iter():
            yield b'data: {"con'
            yield b'tent": "hel'
            yield b'lo"}\n\n'

        mock_content = MagicMock()
        mock_content.iter_any.return_value = mock_iter()

        parser = SSEStreamParser(
            content_extractor=lambda e: e.get("content", ""), chunk_timeout=1.0
        )

        result = []
        async for content in parser.parse_stream(mock_content):
            result.append(content)

        assert result == ["hello"]


class TestCreateOpenAISSEParser:
    """Test OpenAI-specific SSE parser."""

    def test_creates_parser(self):
        """Test parser is created successfully."""
        parser = create_openai_sse_parser()
        assert isinstance(parser, SSEStreamParser)

    @pytest.mark.asyncio
    async def test_extracts_openai_content(self):
        """Test extraction of OpenAI delta content."""
        openai_event = b'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'

        async def mock_iter():
            yield openai_event

        mock_content = MagicMock()
        mock_content.iter_any.return_value = mock_iter()

        parser = create_openai_sse_parser()

        result = []
        async for content in parser.parse_stream(mock_content):
            result.append(content)

        assert result == ["Hello"]

    @pytest.mark.asyncio
    async def test_handles_empty_choices(self):
        """Test handling of empty choices array."""
        openai_event = b'data: {"choices": []}\n\n'

        async def mock_iter():
            yield openai_event

        mock_content = MagicMock()
        mock_content.iter_any.return_value = mock_iter()

        parser = create_openai_sse_parser()

        result = []
        async for content in parser.parse_stream(mock_content):
            result.append(content)

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_missing_delta(self):
        """Test handling when delta is missing."""
        openai_event = b'data: {"choices": [{"index": 0}]}\n\n'

        async def mock_iter():
            yield openai_event

        mock_content = MagicMock()
        mock_content.iter_any.return_value = mock_iter()

        parser = create_openai_sse_parser()

        result = []
        async for content in parser.parse_stream(mock_content):
            result.append(content)

        assert result == []


class TestCreateAnthropicSSEParser:
    """Test Anthropic-specific SSE parser."""

    def test_creates_parser(self):
        """Test parser is created successfully."""
        parser = create_anthropic_sse_parser()
        assert isinstance(parser, SSEStreamParser)

    @pytest.mark.asyncio
    async def test_extracts_anthropic_content(self):
        """Test extraction of Anthropic text delta."""
        anthropic_event = b'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}}\n\n'

        async def mock_iter():
            yield anthropic_event

        mock_content = MagicMock()
        mock_content.iter_any.return_value = mock_iter()

        parser = create_anthropic_sse_parser()

        result = []
        async for content in parser.parse_stream(mock_content):
            result.append(content)

        assert result == ["Hello"]

    @pytest.mark.asyncio
    async def test_ignores_non_content_events(self):
        """Test non-content_block_delta events are ignored."""
        events = (
            b'data: {"type": "message_start"}\n\n'
            b'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}}\n\n'
            b'data: {"type": "message_stop"}\n\n'
        )

        async def mock_iter():
            yield events

        mock_content = MagicMock()
        mock_content.iter_any.return_value = mock_iter()

        parser = create_anthropic_sse_parser()

        result = []
        async for content in parser.parse_stream(mock_content):
            result.append(content)

        assert result == ["Hi"]

    @pytest.mark.asyncio
    async def test_ignores_non_text_deltas(self):
        """Test non-text_delta types are ignored."""
        event = b'data: {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "{}"}}\n\n'

        async def mock_iter():
            yield event

        mock_content = MagicMock()
        mock_content.iter_any.return_value = mock_iter()

        parser = create_anthropic_sse_parser()

        result = []
        async for content in parser.parse_stream(mock_content):
            result.append(content)

        assert result == []


class TestConnectionPoolRobustness:
    """Test edge cases and robustness of connection pooling."""

    @pytest.fixture(autouse=True)
    def reset_connector(self):
        """Reset global connector state."""
        import aragora.agents.api_agents.common as common_module

        common_module._shared_connector = None
        common_module._connector_loop_id = None
        yield
        common_module._shared_connector = None
        common_module._connector_loop_id = None

    @pytest.mark.asyncio
    async def test_connector_recreation_after_close(self):
        """Test new connector is created after closing."""
        import aragora.agents.api_agents.common as common_module

        connector1 = get_shared_connector()
        # Manually close it - await the coroutine
        await connector1.close()

        # Should create a new one since the old one is closed
        connector2 = get_shared_connector()
        assert connector2 is not connector1
        assert not connector2.closed

    def test_thread_safety_with_lock(self):
        """Test that _session_lock is used for thread safety."""
        import aragora.agents.api_agents.common as common_module

        # Verify lock exists and is a threading lock
        assert hasattr(common_module, "_session_lock")
        import threading

        assert isinstance(common_module._session_lock, type(threading.Lock()))
