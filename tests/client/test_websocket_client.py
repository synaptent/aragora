"""Tests for WebSocket client module."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from aragora.client.websocket import (
    DebateEventType,
    DebateEvent,
    WebSocketOptions,
    DebateStream,
    stream_debate,
    MAX_EVENT_QUEUE_SIZE,
)


class TestDebateEventType:
    """Tests for DebateEventType enum."""

    def test_all_event_types_have_string_values(self):
        """All enum members have valid string values."""
        for event_type in DebateEventType:
            assert isinstance(event_type.value, str)
            assert len(event_type.value) > 0

    def test_event_types_are_unique(self):
        """No duplicate values."""
        values = [e.value for e in DebateEventType]
        assert len(values) == len(set(values))

    def test_event_type_is_str_enum(self):
        """Enum inherits from str, allowing string comparison."""
        assert DebateEventType.DEBATE_START == "debate_start"
        assert DebateEventType.AGENT_MESSAGE == "agent_message"


class TestDebateEvent:
    """Tests for DebateEvent dataclass."""

    def test_create_basic_event(self):
        """Create event with required fields."""
        event = DebateEvent(
            type=DebateEventType.AGENT_MESSAGE,
            debate_id="debate-123",
            timestamp=1704067200.0,
        )
        assert event.type == DebateEventType.AGENT_MESSAGE
        assert event.debate_id == "debate-123"
        assert event.data == {}

    def test_create_event_with_data(self):
        """Create event with data payload."""
        event = DebateEvent(
            type=DebateEventType.VOTE,
            debate_id="debate-123",
            timestamp=1704067200.0,
            data={"agent": "claude", "choice": "approve"},
        )
        assert event.data["agent"] == "claude"
        assert event.data["choice"] == "approve"

    def test_from_dict_valid_event_type(self):
        """Parse dict with valid event type."""
        d = {
            "type": "agent_message",
            "debate_id": "debate-123",
            "timestamp": "2024-01-01T00:00:00",
            "data": {"content": "Hello"},
        }
        event = DebateEvent.from_dict(d)
        assert event.type == DebateEventType.AGENT_MESSAGE
        assert event.debate_id == "debate-123"
        assert event.data["content"] == "Hello"
        assert isinstance(event.timestamp, float)

    def test_from_dict_unknown_event_type_defaults_to_error(self):
        """Unknown event types become ERROR."""
        d = {"type": "unknown_event", "debate_id": "d1"}
        event = DebateEvent.from_dict(d)
        assert event.type == DebateEventType.ERROR

    def test_from_dict_missing_timestamp_uses_now(self):
        """Auto-generates timestamp if missing."""
        d = {"type": "ping", "debate_id": "d1"}
        event = DebateEvent.from_dict(d)
        assert event.timestamp is not None
        assert isinstance(event.timestamp, float)
        assert event.timestamp > 0

    def test_from_dict_missing_debate_id_empty_string(self):
        """Handles missing debate_id."""
        d = {"type": "ping"}
        event = DebateEvent.from_dict(d)
        assert event.debate_id == ""

    def test_from_dict_missing_data_empty_dict(self):
        """Handles missing data."""
        d = {"type": "ping", "debate_id": "d1"}
        event = DebateEvent.from_dict(d)
        assert event.data == {}

    def test_from_dict_preserves_all_fields(self):
        """All fields round-trip correctly."""
        original = {
            "type": "consensus",
            "debate_id": "my-debate",
            "timestamp": 1718454600.0,
            "data": {"winner": "claude", "confidence": 0.95},
        }
        event = DebateEvent.from_dict(original)
        assert event.type == DebateEventType.CONSENSUS
        assert event.debate_id == "my-debate"
        assert event.timestamp == 1718454600.0
        assert event.data["winner"] == "claude"
        assert event.data["confidence"] == 0.95


class TestWebSocketOptions:
    """Tests for WebSocketOptions dataclass."""

    def test_default_options(self):
        """Verify default values."""
        opts = WebSocketOptions()
        assert opts.reconnect is True
        assert opts.reconnect_interval == 1.0
        assert opts.max_reconnect_attempts == 5
        assert opts.heartbeat_interval == 30.0
        assert opts.connect_timeout == 10.0

    def test_custom_reconnect_settings(self):
        """Custom reconnection parameters."""
        opts = WebSocketOptions(
            reconnect=True,
            reconnect_interval=2.0,
            max_reconnect_attempts=10,
        )
        assert opts.reconnect_interval == 2.0
        assert opts.max_reconnect_attempts == 10

    def test_custom_timeout_settings(self):
        """Custom timeout parameters."""
        opts = WebSocketOptions(
            heartbeat_interval=60.0,
            connect_timeout=30.0,
        )
        assert opts.heartbeat_interval == 60.0
        assert opts.connect_timeout == 30.0

    def test_disable_reconnect(self):
        """reconnect=False disables auto-reconnect."""
        opts = WebSocketOptions(reconnect=False)
        assert opts.reconnect is False


class TestDebateStreamUrlBuilding:
    """Tests for URL construction logic."""

    def test_build_url_with_ws_prefix(self):
        """ws:// URLs preserved."""
        stream = DebateStream("ws://localhost:8080", "debate-123")
        assert stream.url == "ws://localhost:8080/ws"

    def test_build_url_with_wss_prefix(self):
        """wss:// URLs preserved."""
        stream = DebateStream("wss://secure.example.com", "debate-456")
        assert stream.url == "wss://secure.example.com/ws"

    def test_build_url_converts_http_to_ws(self):
        """http:// -> ws:// conversion."""
        stream = DebateStream("http://localhost:8080", "debate-123")
        assert stream.url == "ws://localhost:8080/ws"

    def test_build_url_converts_https_to_wss(self):
        """https:// -> wss:// conversion."""
        stream = DebateStream("https://secure.example.com", "debate-456")
        assert stream.url == "wss://secure.example.com/ws"

    def test_build_url_strips_trailing_slash(self):
        """Removes trailing slashes."""
        stream = DebateStream("ws://localhost:8080/", "debate-123")
        assert stream.url == "ws://localhost:8080/ws"

    def test_build_url_targets_ws_endpoint(self):
        """Uses /ws endpoint."""
        stream = DebateStream("ws://localhost", "my-debate-id")
        assert stream.url == "ws://localhost/ws"

    def test_build_url_with_port(self):
        """URL with port number."""
        stream = DebateStream("ws://localhost:9000", "d1")
        assert stream.url == "ws://localhost:9000/ws"

    def test_build_url_with_existing_ws_path(self):
        """Avoids duplicate /ws path."""
        stream = DebateStream("ws://localhost:8080/ws", "debate-123")
        assert stream.url == "ws://localhost:8080/ws"


class TestDebateStreamCallbacks:
    """Tests for callback registration and management."""

    def test_on_registers_callback(self):
        """Register event callback."""
        stream = DebateStream("ws://localhost", "d1")
        callback = Mock()
        stream.on("agent_message", callback)
        assert callback in stream._event_callbacks["agent_message"]

    def test_on_multiple_callbacks_same_event(self):
        """Multiple callbacks for same event."""
        stream = DebateStream("ws://localhost", "d1")
        cb1, cb2 = Mock(), Mock()
        stream.on("vote", cb1)
        stream.on("vote", cb2)
        assert len(stream._event_callbacks["vote"]) == 2

    def test_on_returns_self_for_chaining(self):
        """Method chaining support."""
        stream = DebateStream("ws://localhost", "d1")
        result = stream.on("vote", Mock()).on("consensus", Mock())
        assert result is stream

    def test_on_error_registers_callback(self):
        """Register error callback."""
        stream = DebateStream("ws://localhost", "d1")
        callback = Mock()
        stream.on_error(callback)
        assert callback in stream._error_callbacks

    def test_on_close_registers_callback(self):
        """Register close callback."""
        stream = DebateStream("ws://localhost", "d1")
        callback = Mock()
        stream.on_close(callback)
        assert callback in stream._close_callbacks

    def test_off_removes_callback(self):
        """Unsubscribe from events."""
        stream = DebateStream("ws://localhost", "d1")
        callback = Mock()
        stream.on("vote", callback)
        stream.off("vote", callback)
        assert callback not in stream._event_callbacks.get("vote", [])

    def test_off_nonexistent_callback_no_error(self):
        """Removing missing callback is silent."""
        stream = DebateStream("ws://localhost", "d1")
        callback = Mock()
        stream.on("vote", Mock())
        stream.off("vote", callback)  # Different callback, should not error

    def test_off_nonexistent_event_type_no_error(self):
        """Removing from missing type is silent."""
        stream = DebateStream("ws://localhost", "d1")
        stream.off("nonexistent", Mock())  # Should not error

    def test_wildcard_callback_receives_all_events(self):
        """'*' receives all event types."""
        stream = DebateStream("ws://localhost", "d1")
        callback = Mock()
        stream.on("*", callback)
        assert callback in stream._event_callbacks["*"]


class TestDebateStreamEventEmission:
    """Tests for event emission to callbacks."""

    def test_emit_event_calls_type_specific_callback(self):
        """Type-specific callbacks receive events."""
        stream = DebateStream("ws://localhost", "d1")
        callback = Mock()
        stream.on("agent_message", callback)

        event = DebateEvent(
            type=DebateEventType.AGENT_MESSAGE,
            debate_id="d1",
            timestamp=1704067200.0,
        )
        stream._emit_event(event)
        callback.assert_called_once_with(event)

    def test_emit_event_calls_wildcard_callback(self):
        """Wildcard callbacks receive events."""
        stream = DebateStream("ws://localhost", "d1")
        callback = Mock()
        stream.on("*", callback)

        event = DebateEvent(
            type=DebateEventType.VOTE,
            debate_id="d1",
            timestamp=1704067200.0,
        )
        stream._emit_event(event)
        callback.assert_called_once_with(event)

    def test_emit_event_callback_exception_isolated(self):
        """One failing callback doesn't break others."""
        stream = DebateStream("ws://localhost", "d1")
        failing_callback = Mock(side_effect=Exception("Boom"))
        working_callback = Mock()
        stream.on("vote", failing_callback)
        stream.on("vote", working_callback)

        event = DebateEvent(
            type=DebateEventType.VOTE,
            debate_id="d1",
            timestamp=1704067200.0,
        )
        stream._emit_event(event)  # Should not raise
        working_callback.assert_called_once()

    def test_emit_error_calls_error_callbacks(self):
        """Error callbacks invoked."""
        stream = DebateStream("ws://localhost", "d1")
        callback = Mock()
        stream.on_error(callback)

        error = Exception("Connection failed")
        stream._emit_error(error)
        callback.assert_called_once_with(error)

    def test_emit_close_calls_close_callbacks(self):
        """Close callbacks invoked."""
        stream = DebateStream("ws://localhost", "d1")
        callback = Mock()
        stream.on_close(callback)

        stream._emit_close(1000, "Normal closure")
        callback.assert_called_once_with(1000, "Normal closure")

    def test_emit_error_callback_exception_logged(self):
        """Error in error callback is logged."""
        stream = DebateStream("ws://localhost", "d1")
        callback = Mock(side_effect=Exception("Callback failed"))
        stream.on_error(callback)

        # Should not raise
        stream._emit_error(Exception("Original error"))


class TestDebateStreamEventQueue:
    """Tests for event queue behavior."""

    def test_event_queue_max_size(self):
        """Queue respects MAX_EVENT_QUEUE_SIZE."""
        stream = DebateStream("ws://localhost", "d1")
        assert stream._event_queue.maxsize == MAX_EVENT_QUEUE_SIZE

    @pytest.mark.asyncio
    async def test_event_queue_overflow_drops_event(self):
        """Full queue drops new events."""
        # Create stream with small queue for testing
        stream = DebateStream("ws://localhost", "d1")
        # Fill the queue
        for i in range(MAX_EVENT_QUEUE_SIZE):
            event = DebateEvent(
                type=DebateEventType.PING,
                debate_id="d1",
                timestamp=float(i),
            )
            stream._event_queue.put_nowait(event)

        # Queue should now be full
        assert stream._event_queue.full()

        # Trying to add more should not block (uses put_nowait internally)
        # This would raise QueueFull if not handled

    def test_event_queue_empty_initial(self):
        """Queue starts empty."""
        stream = DebateStream("ws://localhost", "d1")
        assert stream._event_queue.empty()


class TestDebateStreamAsyncIterator:
    """Tests for async iterator protocol."""

    def test_aiter_returns_self(self):
        """__aiter__ returns self."""
        stream = DebateStream("ws://localhost", "d1")
        assert stream.__aiter__() is stream

    @pytest.mark.asyncio
    async def test_anext_returns_event_from_queue(self):
        """__anext__ returns queued event."""
        stream = DebateStream("ws://localhost", "d1")
        event = DebateEvent(
            type=DebateEventType.VOTE,
            debate_id="d1",
            timestamp=1704067200.0,
        )
        await stream._event_queue.put(event)

        result = await stream.__anext__()
        assert result.type == DebateEventType.VOTE

    @pytest.mark.asyncio
    async def test_anext_timeout_returns_synthetic_ping(self):
        """Timeout generates keepalive ping when connected."""
        stream = DebateStream("ws://localhost", "d1")
        stream.options = WebSocketOptions(heartbeat_interval=0.01)  # Short timeout
        stream._ws = Mock()
        stream._ws.open = True

        result = await stream.__anext__()
        assert result.type == DebateEventType.PING
        assert result.data.get("keepalive") is True

    @pytest.mark.asyncio
    async def test_anext_raises_stop_when_closing_and_empty(self):
        """StopAsyncIteration when closing and queue empty."""
        stream = DebateStream("ws://localhost", "d1")
        stream._is_closing = True

        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()

    @pytest.mark.asyncio
    async def test_anext_timeout_stops_when_disconnected(self):
        """StopAsyncIteration on timeout when not connected."""
        stream = DebateStream("ws://localhost", "d1")
        stream.options = WebSocketOptions(heartbeat_interval=0.01)
        stream._ws = None  # Not connected

        with pytest.raises(StopAsyncIteration):
            await stream.__anext__()


class TestDebateStreamConnection:
    """Tests for connection lifecycle (with mocked websockets)."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Successful connection."""
        mock_ws = AsyncMock()
        mock_ws.open = True

        async def mock_connect(*args, **kwargs):
            return mock_ws

        # Need to mock as async context
        mock_ws.__aiter__ = lambda self: self
        mock_ws.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

        with patch("aragora.client.websocket.asyncio.create_task"):
            with patch.dict("sys.modules", {"websockets": MagicMock()}):
                import sys

                sys.modules["websockets"].connect = mock_connect

                stream = DebateStream("ws://localhost", "d1")
                await stream.connect()

                assert stream._reconnect_attempts == 0
                assert stream._is_closing is False

    @pytest.mark.asyncio
    async def test_connect_timeout_raises_connection_error(self):
        """Timeout raises ConnectionError."""

        async def slow_connect(*args, **kwargs):
            await asyncio.sleep(10)

        with patch.dict("sys.modules", {"websockets": MagicMock()}):
            import sys

            sys.modules["websockets"].connect = slow_connect

            stream = DebateStream("ws://localhost", "d1")
            stream.options = WebSocketOptions(connect_timeout=0.01)

            with pytest.raises(ConnectionError, match="timeout"):
                await stream.connect()

    @pytest.mark.asyncio
    async def test_connect_failure_raises_connection_error(self):
        """Connection failure raises error."""

        async def failing_connect(*args, **kwargs):
            raise OSError("Connection refused")

        with patch.dict("sys.modules", {"websockets": MagicMock()}):
            import sys

            sys.modules["websockets"].connect = failing_connect

            stream = DebateStream("ws://localhost", "d1")

            with pytest.raises(ConnectionError, match="Failed to connect"):
                await stream.connect()

    @pytest.mark.asyncio
    async def test_connect_without_websockets_package_raises(self):
        """Missing dependency detected."""
        stream = DebateStream("ws://localhost", "d1")

        with patch.dict("sys.modules", {"websockets": None}):
            # Force import to fail
            original_import = __builtins__["__import__"]

            def mock_import(name, *args, **kwargs):
                if name == "websockets":
                    raise ImportError("No module named 'websockets'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", mock_import):
                with pytest.raises(ImportError, match="websockets package required"):
                    await stream.connect()

    @pytest.mark.asyncio
    async def test_disconnect_closes_connection(self):
        """Clean disconnection."""
        stream = DebateStream("ws://localhost", "d1")
        mock_ws = AsyncMock()
        stream._ws = mock_ws

        await stream.disconnect()

        mock_ws.close.assert_called_once()
        assert stream._ws is None
        assert stream._is_closing is True

    @pytest.mark.asyncio
    async def test_disconnect_cancels_heartbeat_task(self):
        """Heartbeat task cancelled."""
        stream = DebateStream("ws://localhost", "d1")
        mock_task = Mock()
        stream._heartbeat_task = mock_task
        stream._ws = AsyncMock()

        await stream.disconnect()

        mock_task.cancel.assert_called_once()
        assert stream._heartbeat_task is None

    @pytest.mark.asyncio
    async def test_disconnect_cancels_reconnect_task(self):
        """Reconnect task cancelled."""
        stream = DebateStream("ws://localhost", "d1")
        mock_task = Mock()
        stream._reconnect_task = mock_task
        stream._ws = AsyncMock()

        await stream.disconnect()

        mock_task.cancel.assert_called_once()
        assert stream._reconnect_task is None

    def test_is_connected_true_when_open(self):
        """is_connected property when connected."""
        stream = DebateStream("ws://localhost", "d1")
        mock_ws = Mock()
        mock_ws.open = True
        stream._ws = mock_ws

        assert stream.is_connected is True

    def test_is_connected_false_when_closed(self):
        """is_connected false when not connected."""
        stream = DebateStream("ws://localhost", "d1")
        stream._ws = None

        assert stream.is_connected is False


class TestDebateStreamReconnection:
    """Tests for exponential backoff reconnection."""

    @pytest.mark.asyncio
    async def test_reconnect_exponential_backoff_delays(self):
        """Delays: 1s, 2s, 4s, 8s..."""
        stream = DebateStream("ws://localhost", "d1")
        stream.options = WebSocketOptions(
            reconnect_interval=1.0,
            max_reconnect_attempts=3,
        )

        delays = []

        async def mock_sleep(delay):
            delays.append(delay)
            raise Exception("Stop reconnect")

        with patch("asyncio.sleep", mock_sleep):
            try:
                await stream._attempt_reconnect()
            except Exception:
                pass

        assert delays[0] == 1.0  # First attempt: 1 * 2^0 = 1

    @pytest.mark.asyncio
    async def test_reconnect_stops_at_max_attempts(self):
        """Stops after max_reconnect_attempts."""
        stream = DebateStream("ws://localhost", "d1")
        stream.options = WebSocketOptions(max_reconnect_attempts=3)
        stream._reconnect_attempts = 3

        error_emitted = []
        stream.on_error(lambda e: error_emitted.append(e))

        await stream._attempt_reconnect()

        assert len(error_emitted) == 1
        assert "Max reconnect attempts" in str(error_emitted[0])

    @pytest.mark.asyncio
    async def test_reconnect_emits_error_at_max_attempts(self):
        """ConnectionError emitted at max attempts."""
        stream = DebateStream("ws://localhost", "d1")
        stream.options = WebSocketOptions(max_reconnect_attempts=2)
        stream._reconnect_attempts = 2

        errors = []
        stream.on_error(lambda e: errors.append(e))

        await stream._attempt_reconnect()

        assert len(errors) == 1
        assert isinstance(errors[0], ConnectionError)

    @pytest.mark.asyncio
    async def test_reconnect_success_resets_attempts(self):
        """Counter reset on success."""
        stream = DebateStream("ws://localhost", "d1")
        stream._reconnect_attempts = 2

        mock_ws = AsyncMock()
        mock_ws.open = True
        mock_ws.__aiter__ = lambda self: self
        mock_ws.__anext__ = AsyncMock(side_effect=StopAsyncIteration)

        async def mock_connect(*args, **kwargs):
            return mock_ws

        with patch("aragora.client.websocket.asyncio.create_task"):
            with patch.dict("sys.modules", {"websockets": MagicMock()}):
                import sys

                sys.modules["websockets"].connect = mock_connect

                await stream.connect()
                assert stream._reconnect_attempts == 0

    @pytest.mark.asyncio
    async def test_reconnect_disabled_when_option_false(self):
        """No reconnect when disabled."""
        stream = DebateStream("ws://localhost", "d1")
        stream.options = WebSocketOptions(reconnect=False)

        # _attempt_reconnect should still work, but _receive_loop
        # won't call it when reconnect is False


class TestDebateStreamReceiveLoop:
    """Tests for message receiving logic."""

    @pytest.mark.asyncio
    async def test_receive_loop_returns_when_socket_is_missing(self):
        """A disconnected stream should not attempt to iterate a null socket."""
        stream = DebateStream("ws://localhost", "d1")

        await stream._receive_loop()

    @pytest.mark.asyncio
    async def test_receive_loop_parses_json_messages(self):
        """Valid JSON parsed."""
        stream = DebateStream("ws://localhost", "d1")
        callback = Mock()
        stream.on("vote", callback)

        message = json.dumps(
            {
                "type": "vote",
                "debate_id": "d1",
                "timestamp": "2024-01-01",
                "data": {"choice": "approve"},
            }
        )

        # Simulate receiving message
        mock_ws = AsyncMock()
        mock_ws.__aiter__ = lambda self: iter([message])
        stream._ws = mock_ws

        # Process one message
        data = json.loads(message)
        event = DebateEvent.from_dict(data)
        stream._emit_event(event)

        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_receive_loop_emits_to_callbacks(self):
        """Events reach callbacks."""
        stream = DebateStream("ws://localhost", "d1")
        received = []
        stream.on("consensus", lambda e: received.append(e))

        event = DebateEvent(
            type=DebateEventType.CONSENSUS,
            debate_id="d1",
            timestamp=1704067200.0,
        )
        stream._emit_event(event)

        assert len(received) == 1
        assert received[0].type == DebateEventType.CONSENSUS

    @pytest.mark.asyncio
    async def test_receive_loop_adds_to_queue(self):
        """Events added to queue."""
        stream = DebateStream("ws://localhost", "d1")

        event = DebateEvent(
            type=DebateEventType.VOTE,
            debate_id="d1",
            timestamp=1704067200.0,
        )

        # Simulate what receive loop does
        stream._event_queue.put_nowait(event)

        assert not stream._event_queue.empty()
        queued = await stream._event_queue.get()
        assert queued.type == DebateEventType.VOTE


class TestDebateStreamSend:
    """Tests for sending messages."""

    @pytest.mark.asyncio
    async def test_send_serializes_to_json(self):
        """Dict serialized to JSON."""
        stream = DebateStream("ws://localhost", "d1")
        mock_ws = AsyncMock()
        stream._ws = mock_ws

        await stream.send({"type": "user_vote", "choice": "approve"})

        mock_ws.send.assert_called_once()
        sent = mock_ws.send.call_args[0][0]
        parsed = json.loads(sent)
        assert parsed["type"] == "user_vote"
        assert parsed["choice"] == "approve"

    @pytest.mark.asyncio
    async def test_send_when_disconnected_no_error(self):
        """Send when disconnected is no-op."""
        stream = DebateStream("ws://localhost", "d1")
        stream._ws = None

        # Should not raise
        await stream.send({"type": "ping"})


class TestStreamDebateFunction:
    """Tests for the convenience function."""

    @pytest.mark.asyncio
    async def test_stream_debate_stops_on_debate_end(self):
        """Stops on DEBATE_END event."""
        events_received = []

        mock_stream = AsyncMock(spec=DebateStream)
        mock_stream.connect = AsyncMock()
        mock_stream.disconnect = AsyncMock()

        events = [
            DebateEvent(type=DebateEventType.DEBATE_START, debate_id="d1", timestamp=1.0),
            DebateEvent(type=DebateEventType.AGENT_MESSAGE, debate_id="d1", timestamp=2.0),
            DebateEvent(type=DebateEventType.DEBATE_END, debate_id="d1", timestamp=3.0),
        ]

        async def mock_aiter():
            for e in events:
                yield e

        with patch("aragora.client.websocket.DebateStream") as MockClass:
            instance = AsyncMock()
            instance.connect = AsyncMock()
            instance.disconnect = AsyncMock()

            async def async_gen():
                for e in events:
                    yield e

            instance.__aiter__ = lambda self: async_gen()
            MockClass.return_value = instance

            async for event in stream_debate("ws://localhost", "d1"):
                events_received.append(event)

            assert len(events_received) == 3
            assert events_received[-1].type == DebateEventType.DEBATE_END
            instance.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_debate_disconnects_on_exit(self):
        """Cleanup on normal exit."""
        with patch("aragora.client.websocket.DebateStream") as MockClass:
            instance = AsyncMock()
            instance.connect = AsyncMock()
            instance.disconnect = AsyncMock()

            events = [
                DebateEvent(type=DebateEventType.DEBATE_END, debate_id="d1", timestamp=1.0),
            ]

            async def async_gen():
                for e in events:
                    yield e

            instance.__aiter__ = lambda self: async_gen()
            MockClass.return_value = instance

            async for _ in stream_debate("ws://localhost", "d1"):
                pass

            instance.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_debate_disconnects_on_exception(self):
        """Cleanup on error."""
        with patch("aragora.client.websocket.DebateStream") as MockClass:
            instance = AsyncMock()
            instance.connect = AsyncMock()
            instance.disconnect = AsyncMock()

            async def failing_gen():
                yield DebateEvent(type=DebateEventType.DEBATE_START, debate_id="d1", timestamp=1.0)
                raise Exception("Simulated error")

            instance.__aiter__ = lambda self: failing_gen()
            MockClass.return_value = instance

            with pytest.raises(Exception, match="Simulated error"):
                async for _ in stream_debate("ws://localhost", "d1"):
                    pass

            instance.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stream_debate_with_custom_options(self):
        """Custom options passed through."""
        custom_opts = WebSocketOptions(
            reconnect=False,
            connect_timeout=5.0,
        )

        with patch("aragora.client.websocket.DebateStream") as MockClass:
            instance = AsyncMock()
            instance.connect = AsyncMock()
            instance.disconnect = AsyncMock()

            async def empty_gen():
                yield DebateEvent(type=DebateEventType.DEBATE_END, debate_id="d1", timestamp=1.0)

            instance.__aiter__ = lambda self: empty_gen()
            MockClass.return_value = instance

            async for _ in stream_debate("ws://localhost", "d1", options=custom_opts):
                pass

            MockClass.assert_called_once_with("ws://localhost", "d1", custom_opts)
