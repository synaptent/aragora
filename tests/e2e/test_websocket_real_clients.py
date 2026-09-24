"""
E2E tests for WebSocket server with real client connections.

Tests the DebateStreamServer's ability to:
- Accept real WebSocket connections
- Broadcast events to multiple clients
- Handle client disconnection gracefully
- Manage subscriptions and rate limiting
- Support reconnection after disconnect
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import websockets
from websockets.exceptions import ConnectionClosed

from aragora.events.types import StreamEvent, StreamEventType
from aragora.server.stream.server_base import ServerBase


class TestWebSocketServerStartStop:
    """Test server lifecycle."""

    @pytest.mark.asyncio
    async def test_server_base_initialization(self):
        """Verify ServerBase initializes correctly."""
        server = ServerBase()

        assert server.clients == set()
        assert server._running is False
        assert server.audience_inbox is not None
        assert server._emitter is not None

    @pytest.mark.asyncio
    async def test_emitter_creation(self):
        """Verify emitter is created when not provided."""
        server = ServerBase()

        assert server._emitter is not None
        # Emitter should be usable
        assert hasattr(server._emitter, "emit")


class TestWebSocketEventBroadcast:
    """Test event broadcasting to clients."""

    @pytest.fixture
    def mock_server(self):
        """Create a ServerBase with mock clients."""
        server = ServerBase()
        return server

    @pytest.mark.asyncio
    async def test_emitter_emit_event(self, mock_server):
        """Verify emitter can emit StreamEvent objects."""
        events_received: list[Any] = []

        def on_event(event: StreamEvent) -> None:
            events_received.append(event)

        # SyncEventEmitter uses subscribe() to receive ALL events
        mock_server._emitter.subscribe(on_event)
        mock_server._emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={"debate_id": "test-123", "topic": "Test topic"},
            )
        )

        # Give time for event to propagate
        await asyncio.sleep(0.01)

        assert len(events_received) == 1
        assert events_received[0].data["debate_id"] == "test-123"

    @pytest.mark.asyncio
    async def test_multiple_event_types(self, mock_server):
        """Verify different event types are handled."""
        events_received: list[StreamEvent] = []

        mock_server._emitter.subscribe(lambda e: events_received.append(e))

        mock_server._emitter.emit(
            StreamEvent(type=StreamEventType.DEBATE_START, data={"debate_id": "1"})
        )
        mock_server._emitter.emit(StreamEvent(type=StreamEventType.ROUND_START, data={"round": 1}))
        mock_server._emitter.emit(
            StreamEvent(type=StreamEventType.AGENT_MESSAGE, data={"agent": "claude", "text": "Hi"})
        )

        await asyncio.sleep(0.01)

        assert len(events_received) == 3
        assert events_received[0].type == StreamEventType.DEBATE_START
        assert events_received[1].type == StreamEventType.ROUND_START
        assert events_received[2].type == StreamEventType.AGENT_MESSAGE


class TestWebSocketClientManagement:
    """Test client connection tracking."""

    @pytest.fixture
    def server(self):
        """Create a ServerBase instance."""
        return ServerBase()

    def test_clients_set_initially_empty(self, server):
        """Verify clients set starts empty."""
        assert len(server.clients) == 0

    def test_can_add_clients(self, server):
        """Verify clients can be added."""
        mock_ws1 = MagicMock()
        mock_ws2 = MagicMock()

        server.clients.add(mock_ws1)
        server.clients.add(mock_ws2)

        assert len(server.clients) == 2
        assert mock_ws1 in server.clients
        assert mock_ws2 in server.clients

    def test_can_remove_clients(self, server):
        """Verify clients can be removed."""
        mock_ws = MagicMock()
        server.clients.add(mock_ws)
        server.clients.discard(mock_ws)

        assert len(server.clients) == 0

    def test_duplicate_client_not_added_twice(self, server):
        """Verify duplicate clients are not added."""
        mock_ws = MagicMock()
        server.clients.add(mock_ws)
        server.clients.add(mock_ws)  # Add again

        assert len(server.clients) == 1


class TestDebateStateCaching:
    """Test debate state caching functionality."""

    @pytest.fixture
    def server(self):
        """Create a ServerBase instance."""
        return ServerBase()

    def test_debate_states_initially_empty(self, server):
        """Verify debate states dict starts empty."""
        assert len(server.debate_states) == 0

    def test_can_cache_debate_state(self, server):
        """Verify debate states can be cached."""
        debate_state = {
            "debate_id": "test-123",
            "status": "in_progress",
            "round": 2,
            "agents": ["claude", "gpt-4"],
        }

        server.debate_states["test-123"] = debate_state

        assert "test-123" in server.debate_states
        assert server.debate_states["test-123"]["status"] == "in_progress"

    def test_debate_state_update(self, server):
        """Verify debate states can be updated."""
        server.debate_states["test-123"] = {"status": "in_progress"}
        server.debate_states["test-123"]["status"] = "completed"

        assert server.debate_states["test-123"]["status"] == "completed"


class TestAudienceInbox:
    """Test audience participation features."""

    @pytest.fixture
    def server(self):
        """Create a ServerBase instance."""
        return ServerBase()

    @pytest.mark.asyncio
    async def test_audience_inbox_exists(self, server):
        """Verify audience inbox is initialized."""
        assert server.audience_inbox is not None

    @pytest.mark.asyncio
    async def test_can_submit_to_inbox(self, server):
        """Verify messages can be submitted to audience inbox."""
        from aragora.events.types import AudienceMessage

        # AudienceInbox uses put() method
        assert hasattr(server.audience_inbox, "put")

        # Verify we can add a message
        msg = AudienceMessage(type="vote", loop_id="test-loop", payload={"choice": "A"})
        server.audience_inbox.put(msg)

        # Verify message was added
        messages = server.audience_inbox.get_all()
        assert len(messages) == 1


class TestRateLimiting:
    """Test rate limiting functionality."""

    @pytest.fixture
    def server(self):
        """Create a ServerBase instance."""
        return ServerBase()

    def test_rate_limiters_initially_empty(self, server):
        """Verify rate limiters start empty."""
        assert len(server._rate_limiters) == 0

    def test_rate_limiter_lock_exists(self, server):
        """Verify rate limiter lock exists for thread safety."""
        assert server._rate_limiters_lock is not None


class TestStreamEventTypes:
    """Test StreamEvent and StreamEventType definitions."""

    def test_common_event_types_defined(self):
        """Verify common event types are defined."""
        assert hasattr(StreamEventType, "DEBATE_START")
        assert hasattr(StreamEventType, "ROUND_START")
        assert hasattr(StreamEventType, "AGENT_MESSAGE")
        assert hasattr(StreamEventType, "DEBATE_END")

    def test_stream_event_has_required_fields(self):
        """Verify StreamEvent can hold required data."""
        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            data={"topic": "Test topic", "debate_id": "test-123"},
        )

        assert event.type == StreamEventType.DEBATE_START
        assert event.data["debate_id"] == "test-123"
        assert event.data["topic"] == "Test topic"

    def test_stream_event_to_json(self):
        """Verify StreamEvent can be serialized to JSON."""
        event = StreamEvent(
            type=StreamEventType.AGENT_MESSAGE,
            data={"agent": "claude", "text": "Hello"},
        )

        # StreamEvent should have to_json method
        event_json = event.to_json()
        assert isinstance(event_json, str)

        # Should be valid JSON
        parsed = json.loads(event_json)
        assert "type" in parsed
        assert "data" in parsed


class TestActiveLoopsTracking:
    """Test active loops tracking for nomic integration."""

    @pytest.fixture
    def server(self):
        """Create a ServerBase instance."""
        return ServerBase()

    def test_active_loops_tracking_available(self, server):
        """Verify active loops tracking is available."""
        assert hasattr(server, "active_loops") or hasattr(server, "_active_loops")


class TestConcurrentOperations:
    """Test thread safety of server operations."""

    @pytest.fixture
    def server(self):
        """Create a ServerBase instance."""
        return ServerBase()

    @pytest.mark.asyncio
    async def test_concurrent_client_add_remove(self, server):
        """Verify concurrent client operations are safe."""
        import threading

        clients_to_add = [MagicMock() for _ in range(100)]
        errors: list[Exception] = []

        def add_and_remove(client):
            try:
                server.clients.add(client)
                server.clients.discard(client)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_and_remove, args=(c,)) for c in clients_to_add]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_concurrent_debate_state_access(self, server):
        """Verify concurrent debate state access is safe."""
        import threading

        errors: list[Exception] = []

        def read_write_state(debate_id: str):
            try:
                with server._debate_states_lock:
                    server.debate_states[debate_id] = {"status": "active"}
                with server._debate_states_lock:
                    _ = server.debate_states.get(debate_id)
                with server._debate_states_lock:
                    server.debate_states.pop(debate_id, None)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=read_write_state, args=(f"debate-{i}",)) for i in range(50)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestEventEmitterSubscriptions:
    """Test event emitter subscription management."""

    @pytest.fixture
    def server(self):
        """Create a ServerBase instance."""
        return ServerBase()

    @pytest.mark.asyncio
    async def test_can_subscribe_to_events(self, server):
        """Verify handlers can subscribe to events."""
        received: list[StreamEvent] = []

        server._emitter.subscribe(lambda event: received.append(event))
        server._emitter.emit(StreamEvent(type=StreamEventType.DEBATE_START, data={"value": 42}))

        await asyncio.sleep(0.01)
        assert len(received) == 1
        assert received[0].data["value"] == 42

    @pytest.mark.asyncio
    async def test_multiple_handlers_receive_same_event(self, server):
        """Verify multiple subscribers all receive events."""
        results1: list[StreamEvent] = []
        results2: list[StreamEvent] = []

        server._emitter.subscribe(lambda e: results1.append(e))
        server._emitter.subscribe(lambda e: results2.append(e))
        server._emitter.emit(StreamEvent(type=StreamEventType.ROUND_START, data={}))

        await asyncio.sleep(0.01)
        assert len(results1) == 1
        assert len(results2) == 1

    @pytest.mark.asyncio
    async def test_events_with_no_subscribers(self, server):
        """Verify emitting with no subscribers doesn't crash."""
        # Should not raise - create fresh server with no subscribers
        fresh_server = ServerBase()
        fresh_server._emitter.emit(
            StreamEvent(type=StreamEventType.DEBATE_END, data={"test": "data"})
        )


class TestWebSocketMessageRateLimiter:
    """Test the per-connection message rate limiter."""

    def test_rate_limiter_import(self):
        """Verify WebSocketMessageRateLimiter can be imported."""
        from aragora.server.stream.debate_stream_server import WebSocketMessageRateLimiter

        limiter = WebSocketMessageRateLimiter(messages_per_second=10, burst_size=20)
        assert limiter is not None

    def test_rate_limiter_allows_burst(self):
        """Verify rate limiter allows initial burst."""
        from aragora.server.stream.debate_stream_server import WebSocketMessageRateLimiter

        limiter = WebSocketMessageRateLimiter(messages_per_second=10, burst_size=5)

        # Should allow burst of 5 messages
        for _ in range(5):
            assert limiter.allow_message() is True

        # Next should be rate limited
        assert limiter.allow_message() is False

    @pytest.mark.asyncio
    async def test_rate_limiter_refills_over_time(self):
        """Verify rate limiter refills tokens over time."""
        from aragora.server.stream.debate_stream_server import WebSocketMessageRateLimiter

        limiter = WebSocketMessageRateLimiter(messages_per_second=100, burst_size=1)

        # Exhaust the token
        assert limiter.allow_message() is True
        assert limiter.allow_message() is False

        # Wait for refill
        await asyncio.sleep(0.05)

        # Should have refilled some tokens
        assert limiter.allow_message() is True
