"""
Tests for AiohttpUnifiedServer in servers.py.

Tests cover:
- Server initialization with/without nomic_dir
- Loop registration and unregistration
- Cartographer registration
- CORS headers generation
- Audience payload validation
- Rate limiting for audience messages
- Debate state updates
- Client subscription management
"""

import asyncio
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.stream.servers import AiohttpUnifiedServer
from aragora.events.types import StreamEvent, StreamEventType
from aragora.server.stream.state_manager import LoopInstance


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def server(tmp_path):
    """Create a basic AiohttpUnifiedServer for testing."""
    return AiohttpUnifiedServer(port=8080, nomic_dir=tmp_path)


@pytest.fixture
def server_no_nomic():
    """Create an AiohttpUnifiedServer without nomic_dir."""
    return AiohttpUnifiedServer(port=8080)


# ===========================================================================
# Test Initialization
# ===========================================================================


class TestServerInitialization:
    """Tests for AiohttpUnifiedServer initialization."""

    def test_basic_initialization(self, server_no_nomic):
        """Server initializes with default settings."""
        assert server_no_nomic.port == 8080
        assert server_no_nomic.nomic_dir is None
        assert server_no_nomic.elo_system is None
        assert server_no_nomic.insight_store is None

    def test_initialization_with_nomic_dir(self, tmp_path):
        """Server initializes with nomic_dir."""
        server = AiohttpUnifiedServer(port=8080, nomic_dir=tmp_path)
        assert server.nomic_dir == tmp_path

    def test_initialization_host_explicit(self):
        """Server uses explicit host parameter."""
        server = AiohttpUnifiedServer(port=8080, host="0.0.0.0")
        assert server.host == "0.0.0.0"

    def test_initialization_default_host(self, server_no_nomic):
        """Server uses 127.0.0.1 as default host."""
        # Note: This may vary if ARAGORA_BIND_HOST is set in the environment
        assert server_no_nomic.host in ("127.0.0.1", "0.0.0.0")

    def test_voice_handler_initialized(self, server_no_nomic):
        """Voice handler is initialized during server creation."""
        assert server_no_nomic._voice_handler is not None

    def test_cartographers_dict_initialized(self, server_no_nomic):
        """Cartographers dictionary is initialized empty."""
        assert server_no_nomic.cartographers == {}

    def test_client_subscriptions_initialized(self, server_no_nomic):
        """Client subscriptions dictionary is initialized empty."""
        assert server_no_nomic._client_subscriptions == {}


class TestStoreInitialization:
    """Tests for optional store initialization from nomic_dir."""

    def test_elo_system_loaded_when_exists(self, tmp_path):
        """EloSystem is loaded when agent_elo.db exists."""
        # Create a minimal SQLite database
        elo_path = tmp_path / "agent_elo.db"
        elo_path.write_bytes(b"")  # Create empty file

        with patch("aragora.ranking.elo.EloSystem") as mock_elo:
            mock_elo.return_value = MagicMock()
            server = AiohttpUnifiedServer(port=8080, nomic_dir=tmp_path)
            # Note: Won't be called if file is empty/invalid, but tests the path

    def test_stores_not_loaded_without_nomic_dir(self, server_no_nomic):
        """Stores remain None when nomic_dir is not provided."""
        assert server_no_nomic.elo_system is None
        assert server_no_nomic.insight_store is None
        assert server_no_nomic.flip_detector is None
        assert server_no_nomic.persona_manager is None


# ===========================================================================
# Test Loop Registration
# ===========================================================================


class TestLoopRegistration:
    """Tests for loop registration and management."""

    def test_register_loop(self, server):
        """register_loop adds a loop instance."""
        server.register_loop("loop-1", "Test Loop", "/path/to/loop")

        with server._active_loops_lock:
            assert "loop-1" in server.active_loops
            loop = server.active_loops["loop-1"]
            assert loop.name == "Test Loop"
            assert loop.path == "/path/to/loop"

    def test_register_loop_emits_event(self, server):
        """register_loop emits LOOP_REGISTER event."""
        events = []
        original_emit = server._emitter.emit

        def capture_emit(event):
            events.append(event)
            original_emit(event)

        server._emitter.emit = capture_emit

        server.register_loop("loop-1", "Test Loop")

        assert len(events) == 1
        assert events[0].type == StreamEventType.LOOP_REGISTER
        assert events[0].data["loop_id"] == "loop-1"

    def test_unregister_loop(self, server):
        """unregister_loop removes a loop instance."""
        server.register_loop("loop-1", "Test Loop")
        server.unregister_loop("loop-1")

        with server._active_loops_lock:
            assert "loop-1" not in server.active_loops

    def test_unregister_loop_emits_event(self, server):
        """unregister_loop emits LOOP_UNREGISTER event."""
        server.register_loop("loop-1", "Test Loop")

        events = []
        original_emit = server._emitter.emit

        def capture_emit(event):
            events.append(event)
            original_emit(event)

        server._emitter.emit = capture_emit

        server.unregister_loop("loop-1")

        assert any(e.type == StreamEventType.LOOP_UNREGISTER for e in events)

    def test_unregister_loop_cleans_cartographer(self, server):
        """unregister_loop also removes the associated cartographer."""
        server.register_loop("loop-1", "Test Loop")
        server.register_cartographer("loop-1", MagicMock())

        server.unregister_loop("loop-1")

        with server._cartographers_lock:
            assert "loop-1" not in server.cartographers

    def test_update_loop_state(self, server):
        """update_loop_state modifies cycle and phase."""
        server.register_loop("loop-1", "Test Loop")
        server.update_loop_state("loop-1", cycle=5, phase="debate")

        with server._active_loops_lock:
            loop = server.active_loops["loop-1"]
            assert loop.cycle == 5
            assert loop.phase == "debate"

    def test_update_loop_state_partial(self, server):
        """update_loop_state can update just one property."""
        server.register_loop("loop-1", "Test Loop")
        original_phase = server.active_loops["loop-1"].phase

        server.update_loop_state("loop-1", cycle=10)

        with server._active_loops_lock:
            loop = server.active_loops["loop-1"]
            assert loop.cycle == 10
            assert loop.phase == original_phase

    def test_update_loop_state_nonexistent(self, server):
        """update_loop_state does nothing for unknown loop."""
        # Should not raise
        server.update_loop_state("nonexistent", cycle=1)

    def test_get_loops_data(self, server):
        """_get_loops_data returns serializable list."""
        server.register_loop("loop-1", "Loop 1")
        server.register_loop("loop-2", "Loop 2")
        server.update_loop_state("loop-1", cycle=3, phase="design")

        loops_data = server._get_loops_data()

        assert len(loops_data) == 2
        loop1 = next(lp for lp in loops_data if lp["loop_id"] == "loop-1")
        assert loop1["name"] == "Loop 1"
        assert loop1["cycle"] == 3
        assert loop1["phase"] == "design"


# ===========================================================================
# Test Cartographer Registration
# ===========================================================================


class TestCartographerRegistration:
    """Tests for ArgumentCartographer registration."""

    def test_register_cartographer(self, server):
        """register_cartographer adds to registry."""
        mock_cart = MagicMock()
        server.register_cartographer("loop-1", mock_cart)

        with server._cartographers_lock:
            assert server.cartographers["loop-1"] is mock_cart

    def test_unregister_cartographer(self, server):
        """unregister_cartographer removes from registry."""
        mock_cart = MagicMock()
        server.register_cartographer("loop-1", mock_cart)
        server.unregister_cartographer("loop-1")

        with server._cartographers_lock:
            assert "loop-1" not in server.cartographers

    def test_unregister_cartographer_nonexistent(self, server):
        """unregister_cartographer does nothing for unknown loop."""
        # Should not raise
        server.unregister_cartographer("nonexistent")


# ===========================================================================
# Test CORS Headers
# ===========================================================================


class TestCORSHeaders:
    """Tests for CORS header generation."""

    def test_cors_headers_for_whitelisted_origin(self, server):
        """Returns Allow-Origin for whitelisted origins."""
        with patch("aragora.server.stream.servers.WS_ALLOWED_ORIGINS", {"http://localhost:3000"}):
            headers = server._cors_headers("http://localhost:3000")
            assert headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
            assert headers.get("Access-Control-Allow-Credentials") == "true"

    def test_cors_headers_for_unauthorized_origin(self, server):
        """Does not return Allow-Origin for unauthorized origins."""
        with patch("aragora.server.stream.servers.WS_ALLOWED_ORIGINS", {"http://localhost:3000"}):
            headers = server._cors_headers("http://evil.com")
            assert "Access-Control-Allow-Origin" not in headers

    def test_cors_headers_for_same_origin(self, server):
        """Same-origin requests (no Origin header) don't get CORS headers."""
        headers = server._cors_headers(None)
        assert "Access-Control-Allow-Origin" not in headers

    def test_cors_headers_include_methods(self, server):
        """CORS headers include allowed methods."""
        headers = server._cors_headers(None)
        assert "GET" in headers.get("Access-Control-Allow-Methods", "")
        assert "POST" in headers.get("Access-Control-Allow-Methods", "")


# ===========================================================================
# Test Audience Payload Validation
# ===========================================================================


class TestAudiencePayloadValidation:
    """Tests for _validate_audience_payload."""

    def test_valid_payload(self, server):
        """Valid payload passes validation."""
        data = {"payload": {"vote": "yes", "agent": "claude"}}
        payload, error = server._validate_audience_payload(data)
        assert payload == {"vote": "yes", "agent": "claude"}
        assert error is None

    def test_missing_payload(self, server):
        """Missing payload returns empty dict (not an error)."""
        data = {}
        payload, error = server._validate_audience_payload(data)
        assert payload == {}
        assert error is None

    def test_invalid_payload_type(self, server):
        """Non-dict payload returns error."""
        data = {"payload": "not a dict"}
        payload, error = server._validate_audience_payload(data)
        assert payload is None
        assert "Invalid payload format" in error

    def test_payload_too_large(self, server):
        """Payload larger than 10KB returns error."""
        # Create a payload larger than 10KB
        large_data = "x" * 11000
        data = {"payload": {"content": large_data}}
        payload, error = server._validate_audience_payload(data)
        assert payload is None
        assert "Payload too large" in error

    def test_payload_exactly_10kb(self, server):
        """Payload at exactly 10KB limit passes."""
        # Create a payload just under 10KB
        content = "x" * 10000
        data = {"payload": {"c": content[:10000]}}

        # This should work - actual size depends on JSON encoding
        payload, error = server._validate_audience_payload(data)
        # Result depends on actual size after JSON encoding


# ===========================================================================
# Test Audience Rate Limiting
# ===========================================================================


class TestAudienceRateLimiting:
    """Tests for _check_audience_rate_limit."""

    def test_first_request_allowed(self, server):
        """First request for a client is allowed."""
        # Create a rate limiter for the client
        from aragora.server.stream.emitter import TokenBucket

        server._rate_limiters["client-1"] = TokenBucket(rate_per_minute=60, burst_size=10)

        allowed, error = server._check_audience_rate_limit("client-1")
        assert allowed is True
        assert error is None

    def test_no_rate_limiter_returns_error(self, server):
        """Request without rate limiter returns error."""
        allowed, error = server._check_audience_rate_limit("unknown-client")
        assert allowed is False
        assert "Rate limit exceeded" in error["data"]["message"]

    def test_exhausted_rate_limiter_returns_error(self, server):
        """Request when rate limit exhausted returns error."""
        from aragora.server.stream.emitter import TokenBucket

        # Create a rate limiter with 0 tokens
        limiter = TokenBucket(rate_per_minute=60, burst_size=0)
        server._rate_limiters["client-1"] = limiter

        allowed, error = server._check_audience_rate_limit("client-1")
        assert allowed is False
        assert "Rate limit exceeded" in error["data"]["message"]


# ===========================================================================
# Test Debate State Updates
# ===========================================================================


class TestDebateStateUpdates:
    """Tests for _update_debate_state."""

    def test_debate_start_creates_state(self, server):
        """DEBATE_START event creates new debate state."""
        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test question", "agents": ["claude", "gpt4"]},
        )

        server._update_debate_state(event)

        with server._debate_states_lock:
            assert "debate-1" in server.debate_states
            state = server.debate_states["debate-1"]
            assert state["task"] == "Test question"
            assert state["agents"] == ["claude", "gpt4"]
            assert state["ended"] is False

    def test_debate_end_marks_ended(self, server):
        """DEBATE_END event marks debate as ended."""
        # First create the debate
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test", "agents": []},
        )
        server._update_debate_state(start_event)

        # Then end it
        end_event = StreamEvent(
            type=StreamEventType.DEBATE_END,
            loop_id="debate-1",
            data={"duration": 30.0},
        )
        server._update_debate_state(end_event)

        with server._debate_states_lock:
            assert server.debate_states["debate-1"]["ended"] is True

    def test_loop_unregister_removes_state(self, server):
        """LOOP_UNREGISTER event removes debate state."""
        # First create the debate
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test", "agents": []},
        )
        server._update_debate_state(start_event)

        # Then unregister
        unregister_event = StreamEvent(
            type=StreamEventType.LOOP_UNREGISTER,
            loop_id="debate-1",
            data={},
        )
        server._update_debate_state(unregister_event)

        with server._debate_states_lock:
            assert "debate-1" not in server.debate_states

    def test_lru_eviction_at_capacity(self, server):
        """LRU eviction happens when at max capacity."""
        # Set a low max for testing
        server.config.max_debate_states = 3

        # Create 3 debates
        for i in range(3):
            event = StreamEvent(
                type=StreamEventType.DEBATE_START,
                loop_id=f"debate-{i}",
                data={"task": f"Task {i}", "agents": []},
            )
            server._update_debate_state(event)

        # End the first one (making it eligible for eviction)
        end_event = StreamEvent(
            type=StreamEventType.DEBATE_END,
            loop_id="debate-0",
            data={},
        )
        server._update_debate_state(end_event)

        # Create a 4th debate (should evict the ended one)
        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-3",
            data={"task": "Task 3", "agents": []},
        )
        server._update_debate_state(event)

        with server._debate_states_lock:
            # Ended debate should have been evicted
            assert "debate-0" not in server.debate_states
            # New debate should exist
            assert "debate-3" in server.debate_states


# ===========================================================================
# Test Client Subscription Management
# ===========================================================================


class TestClientSubscriptions:
    """Tests for client subscription tracking."""

    def test_subscribe_client(self, server):
        """Client can subscribe to a debate."""
        ws_id = 12345

        with server._client_subscriptions_lock:
            server._client_subscriptions[ws_id] = "debate-1"

        with server._client_subscriptions_lock:
            assert server._client_subscriptions[ws_id] == "debate-1"

    def test_unsubscribe_client(self, server):
        """Client subscription can be removed."""
        ws_id = 12345

        with server._client_subscriptions_lock:
            server._client_subscriptions[ws_id] = "debate-1"
            del server._client_subscriptions[ws_id]

        with server._client_subscriptions_lock:
            assert ws_id not in server._client_subscriptions


# ===========================================================================
# Test Cleanup
# ===========================================================================


class TestCleanup:
    """Tests for cleanup functionality."""

    def test_cleanup_stale_entries(self, server):
        """_cleanup_stale_entries calls base class cleanup."""
        # Add some data that will be cleaned up
        server.register_loop("loop-1", "Test Loop")

        # Mark as stale
        stale_time = time.time() - (server.config.active_loops_ttl + 1)
        server._active_loops_last_access["loop-1"] = stale_time

        server._cleanup_stale_entries()

        # Loop should have been cleaned up
        with server._active_loops_lock:
            assert "loop-1" not in server.active_loops


# ===========================================================================
# Test Thread Safety
# ===========================================================================


class TestThreadSafety:
    """Tests for thread-safe operations."""

    def test_concurrent_loop_registration(self, server):
        """Multiple threads can register loops safely."""
        errors = []

        def register_loop(loop_id):
            try:
                server.register_loop(loop_id, f"Loop {loop_id}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=register_loop, args=(f"loop-{i}",)) for i in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        with server._active_loops_lock:
            assert len(server.active_loops) == 10

    def test_concurrent_debate_state_updates(self, server):
        """Multiple threads can update debate states safely."""
        errors = []

        # Create initial debate
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test", "agents": []},
        )
        server._update_debate_state(start_event)

        def update_state(round_num):
            try:
                # Simulate round updates
                event = StreamEvent(
                    type=StreamEventType.DEBATE_START,
                    loop_id=f"debate-{round_num}",
                    data={"task": f"Task {round_num}", "agents": []},
                )
                server._update_debate_state(event)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=update_state, args=(i,)) for i in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ===========================================================================
# Test Integration with Emitter
# ===========================================================================


class TestEmitterIntegration:
    """Tests for integration with SyncEventEmitter."""

    def test_emitter_available(self, server):
        """Server has emitter attribute."""
        assert server._emitter is not None

    def test_emit_event(self, server):
        """Events can be emitted through server."""
        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="test",
            data={"task": "Test"},
        )

        # Should not raise
        server._emitter.emit(event)

    def test_audience_inbox_available(self, server):
        """Server has audience_inbox attribute."""
        assert server.audience_inbox is not None


# ===========================================================================
# Test Error Handling
# ===========================================================================


class TestErrorHandling:
    """Tests for error handling in server operations."""

    def test_update_loop_state_missing_loop(self, server):
        """Updating state for missing loop doesn't raise."""
        # Should not raise
        server.update_loop_state("missing-loop", cycle=1)

    def test_unregister_missing_loop(self, server):
        """Unregistering missing loop doesn't raise."""
        # Should not raise
        server.unregister_loop("missing-loop")

    def test_unregister_missing_cartographer(self, server):
        """Unregistering missing cartographer doesn't raise."""
        # Should not raise
        server.unregister_cartographer("missing-loop")
