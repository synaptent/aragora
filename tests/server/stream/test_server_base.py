"""
Tests for ServerBase class.

Comprehensive test coverage for the base server functionality:
- Server initialization and configuration
- Rate limiting with TTL-based cleanup
- Debate state caching and eviction
- Active loops tracking
- Client ID management (LRU eviction)
- WebSocket authentication state management
- Cleanup operations
- Context manager support (sync and async)
- Thread safety

These tests verify the foundational server capabilities that all streaming servers inherit.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.stream.server_base import (
    ServerBase,
    ServerConfig,
    WS_TOKEN_REVALIDATION_INTERVAL,
)
from aragora.server.stream.emitter import SyncEventEmitter, TokenBucket
from aragora.server.stream.state_manager import LoopInstance
from aragora.events.types import StreamEvent, StreamEventType


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def server_config() -> ServerConfig:
    """Create a ServerConfig with default values."""
    return ServerConfig()


@pytest.fixture
def custom_config() -> ServerConfig:
    """Create a ServerConfig with custom values for testing."""
    return ServerConfig(
        rate_limiter_ttl=60.0,  # 1 minute for faster tests
        rate_limiter_cleanup_interval=5,  # Frequent cleanup
        debate_states_ttl=60.0,
        max_debate_states=10,
        active_loops_ttl=60.0,
        max_active_loops=10,
        max_client_ids=10,
    )


@pytest.fixture
def emitter() -> SyncEventEmitter:
    """Create a SyncEventEmitter instance."""
    return SyncEventEmitter()


@pytest.fixture
def server_base(emitter) -> ServerBase:
    """Create a ServerBase instance with default config."""
    return ServerBase(emitter=emitter)


@pytest.fixture
def server_base_custom(custom_config, emitter) -> ServerBase:
    """Create a ServerBase instance with custom config."""
    return ServerBase(emitter=emitter, config=custom_config)


@pytest.fixture
def loop_instance() -> LoopInstance:
    """Create a sample LoopInstance."""
    return LoopInstance(
        loop_id="test-loop-1",
        name="Test Loop",
        started_at=time.time(),
        cycle=1,
        phase="running",
        path="/test",
    )


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket connection."""
    ws = MagicMock()
    ws.id = id(ws)  # Use id() as we would with real WebSockets
    return ws


# ===========================================================================
# Test ServerConfig
# ===========================================================================


class TestServerConfig:
    """Tests for ServerConfig dataclass."""

    def test_default_values(self):
        """ServerConfig has expected default values."""
        config = ServerConfig()

        assert config.rate_limiter_ttl == 3600.0
        assert config.rate_limiter_cleanup_interval == 100
        assert config.debate_states_ttl == 3600.0
        assert config.max_debate_states == 500
        assert config.active_loops_ttl == 86400.0
        assert config.max_active_loops == 1000
        assert config.max_client_ids == 10000

    def test_custom_values(self, custom_config):
        """ServerConfig accepts custom values."""
        assert custom_config.rate_limiter_ttl == 60.0
        assert custom_config.rate_limiter_cleanup_interval == 5
        assert custom_config.debate_states_ttl == 60.0
        assert custom_config.max_debate_states == 10
        assert custom_config.active_loops_ttl == 60.0
        assert custom_config.max_active_loops == 10
        assert custom_config.max_client_ids == 10


# ===========================================================================
# Test ServerBase Initialization
# ===========================================================================


class TestServerBaseInitialization:
    """Tests for ServerBase initialization."""

    def test_initialization_with_defaults(self):
        """ServerBase initializes with default config and new emitter."""
        server = ServerBase()

        assert server._config is not None
        assert isinstance(server._emitter, SyncEventEmitter)
        assert server._running is False
        assert len(server.clients) == 0

    def test_initialization_with_custom_emitter(self, emitter):
        """ServerBase uses provided emitter."""
        server = ServerBase(emitter=emitter)

        assert server._emitter is emitter

    def test_initialization_with_custom_config(self, custom_config):
        """ServerBase uses provided config."""
        server = ServerBase(config=custom_config)

        assert server._config is custom_config
        assert server._config.max_debate_states == 10

    def test_emitter_property(self, server_base, emitter):
        """emitter property returns the event emitter."""
        assert server_base.emitter is emitter

    def test_config_property(self, server_base):
        """config property returns the server configuration."""
        assert isinstance(server_base.config, ServerConfig)

    def test_emitter_subscription(self, server_base):
        """ServerBase subscribes to emitter for state updates."""
        # Emit an event and verify state is updated
        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="test-loop",
            data={"task": "Test task", "agents": ["claude"]},
        )
        server_base.emitter.emit(event)

        # State should be created
        state = server_base.get_debate_state("test-loop")
        assert state is not None
        assert state["task"] == "Test task"


# ===========================================================================
# Test Rate Limiting
# ===========================================================================


class TestRateLimiting:
    """Tests for rate limiter management."""

    def test_get_rate_limiter_creates_new(self, server_base):
        """get_rate_limiter creates new limiter for unknown client."""
        limiter = server_base.get_rate_limiter("client-1")

        assert isinstance(limiter, TokenBucket)
        assert limiter.rate_per_minute == 10.0
        assert limiter.burst_size == 30

    def test_get_rate_limiter_returns_existing(self, server_base):
        """get_rate_limiter returns same limiter for known client."""
        limiter1 = server_base.get_rate_limiter("client-1")
        limiter2 = server_base.get_rate_limiter("client-1")

        assert limiter1 is limiter2

    def test_get_rate_limiter_custom_params(self, server_base):
        """get_rate_limiter accepts custom rate and capacity."""
        limiter = server_base.get_rate_limiter("client-custom", rate=20.0, capacity=50.0)

        assert limiter.rate_per_minute == 20.0
        assert limiter.burst_size == 50

    def test_cleanup_rate_limiters_removes_stale(self, server_base_custom):
        """cleanup_rate_limiters removes stale entries."""
        # Create a rate limiter
        server_base_custom.get_rate_limiter("stale-client")

        # Artificially age the entry
        with server_base_custom._rate_limiters_lock:
            server_base_custom._rate_limiter_last_access["stale-client"] = (
                time.time() - 3700  # Older than TTL
            )

        # Run cleanup
        removed = server_base_custom.cleanup_rate_limiters()

        assert removed == 1
        assert "stale-client" not in server_base_custom._rate_limiters

    def test_automatic_cleanup_on_access(self, server_base_custom):
        """Rate limiters are cleaned up periodically on access."""
        # Create stale entry
        server_base_custom.get_rate_limiter("stale-client")
        with server_base_custom._rate_limiters_lock:
            server_base_custom._rate_limiter_last_access["stale-client"] = time.time() - 3700

        # Access enough times to trigger cleanup (cleanup_interval=5)
        for i in range(6):
            server_base_custom.get_rate_limiter(f"client-{i}")

        # Stale entry should have been cleaned up
        assert "stale-client" not in server_base_custom._rate_limiters

    def test_rate_limiter_thread_safety(self, server_base):
        """Rate limiter operations are thread-safe."""
        results = []

        def get_limiters():
            for i in range(50):
                limiter = server_base.get_rate_limiter(f"client-{i % 10}")
                results.append(limiter is not None)

        threads = [threading.Thread(target=get_limiters) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results)


# ===========================================================================
# Test Debate State Caching
# ===========================================================================


class TestDebateStateCaching:
    """Tests for debate state caching."""

    def test_get_debate_state_returns_none_for_unknown(self, server_base):
        """get_debate_state returns None for unknown loop."""
        state = server_base.get_debate_state("unknown-loop")
        assert state is None

    def test_set_and_get_debate_state(self, server_base):
        """set_debate_state stores state that can be retrieved."""
        state = {"loop_id": "test-loop", "status": "running"}
        server_base.set_debate_state("test-loop", state)

        retrieved = server_base.get_debate_state("test-loop")
        assert retrieved == state

    def test_debate_state_eviction_on_max(self, server_base_custom):
        """Oldest debate state is evicted when max is reached."""
        # Fill up to max (10)
        for i in range(10):
            server_base_custom.set_debate_state(f"loop-{i}", {"id": i})
            time.sleep(0.01)  # Ensure different timestamps

        # Add one more - should evict oldest
        server_base_custom.set_debate_state("loop-new", {"id": "new"})

        # Oldest (loop-0) should be gone
        assert server_base_custom.get_debate_state("loop-0") is None
        assert server_base_custom.get_debate_state("loop-new") is not None

    def test_cleanup_debate_states_removes_stale(self, server_base_custom):
        """cleanup_debate_states removes entries older than TTL."""
        server_base_custom.set_debate_state("stale-loop", {"status": "old"})

        # Artificially age the entry
        with server_base_custom._debate_states_lock:
            server_base_custom._debate_states_last_access["stale-loop"] = time.time() - 3700

        removed = server_base_custom.cleanup_debate_states()

        assert removed == 1
        assert server_base_custom.get_debate_state("stale-loop") is None

    def test_update_debate_state_from_events(self, server_base):
        """_update_debate_state processes various event types."""
        # Debate start event
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="event-loop",
            data={"task": "Test", "agents": ["claude", "gpt4"]},
        )
        server_base._update_debate_state(start_event)

        state = server_base.get_debate_state("event-loop")
        assert state["task"] == "Test"
        assert state["agents"] == ["claude", "gpt4"]
        assert state["status"] == "running"

    def test_update_debate_state_round_start(self, server_base):
        """_update_debate_state handles round_start events."""
        # Initialize state first
        server_base.set_debate_state(
            "event-loop",
            {
                "loop_id": "event-loop",
                "status": "running",
                "rounds": [],
                "messages": [],
                "current_round": 0,
            },
        )

        round_event = StreamEvent(
            type=StreamEventType.ROUND_START,
            loop_id="event-loop",
            round=2,
            data={},
        )
        server_base._update_debate_state(round_event)

        state = server_base.get_debate_state("event-loop")
        assert state["current_round"] == 2

    def test_update_debate_state_agent_message(self, server_base):
        """_update_debate_state handles agent_message events."""
        server_base.set_debate_state(
            "event-loop",
            {
                "loop_id": "event-loop",
                "status": "running",
                "rounds": [],
                "messages": [],
                "current_round": 1,
            },
        )

        msg_event = StreamEvent(
            type=StreamEventType.AGENT_MESSAGE,
            loop_id="event-loop",
            agent="claude",
            round=1,
            data={"content": "Hello world", "role": "proposer"},
        )
        server_base._update_debate_state(msg_event)

        state = server_base.get_debate_state("event-loop")
        assert len(state["messages"]) == 1
        assert state["messages"][0]["agent"] == "claude"
        assert state["messages"][0]["content"] == "Hello world"

    def test_update_debate_state_synthesis(self, server_base):
        """_update_debate_state handles synthesis events."""
        server_base.set_debate_state(
            "event-loop",
            {
                "loop_id": "event-loop",
                "status": "running",
                "rounds": [],
                "messages": [],
                "current_round": 3,
            },
        )

        synthesis_event = StreamEvent(
            type=StreamEventType.SYNTHESIS,
            loop_id="event-loop",
            agent="synthesis-agent",
            round=3,
            data={"content": "Final synthesis result"},
        )
        server_base._update_debate_state(synthesis_event)

        state = server_base.get_debate_state("event-loop")
        assert state["synthesis"] == "Final synthesis result"
        assert any(m["role"] == "synthesis" for m in state["messages"])

    def test_update_debate_state_consensus(self, server_base):
        """_update_debate_state handles consensus events."""
        server_base.set_debate_state(
            "event-loop",
            {
                "loop_id": "event-loop",
                "status": "running",
                "rounds": [],
                "messages": [],
                "current_round": 2,
            },
        )

        consensus_event = StreamEvent(
            type=StreamEventType.CONSENSUS,
            loop_id="event-loop",
            data={"result": "Agreement reached"},
        )
        server_base._update_debate_state(consensus_event)

        state = server_base.get_debate_state("event-loop")
        assert state["status"] == "completed"
        assert state["result"] == "Agreement reached"

    def test_update_debate_state_error(self, server_base):
        """_update_debate_state handles error events."""
        server_base.set_debate_state(
            "event-loop",
            {
                "loop_id": "event-loop",
                "status": "running",
                "rounds": [],
                "messages": [],
                "current_round": 1,
            },
        )

        error_event = StreamEvent(
            type=StreamEventType.ERROR,
            loop_id="event-loop",
            data={"error": "Something went wrong"},
        )
        server_base._update_debate_state(error_event)

        state = server_base.get_debate_state("event-loop")
        assert state["status"] == "error"
        assert state["error"] == "Something went wrong"

    def test_update_debate_state_dict_compatibility(self, server_base):
        """_update_debate_state handles dict events for backwards compatibility."""
        dict_event = {
            "type": "debate_start",
            "loop_id": "dict-loop",
            "data": {"task": "Dict event test"},
        }
        server_base._update_debate_state(dict_event)

        state = server_base.get_debate_state("dict-loop")
        assert state is not None
        assert state["task"] == "Dict event test"

    def test_update_debate_state_ignores_empty_loop_id(self, server_base):
        """_update_debate_state ignores events without loop_id."""
        initial_count = len(server_base.debate_states)

        empty_event = StreamEvent(
            type=StreamEventType.HEARTBEAT,
            loop_id="",
            data={},
        )
        server_base._update_debate_state(empty_event)

        assert len(server_base.debate_states) == initial_count


# ===========================================================================
# Test Active Loops Tracking
# ===========================================================================


class TestActiveLoopsTracking:
    """Tests for active loops management."""

    def test_get_active_loop_returns_none_for_unknown(self, server_base):
        """get_active_loop returns None for unknown loop."""
        loop = server_base.get_active_loop("unknown")
        assert loop is None

    def test_set_and_get_active_loop(self, server_base, loop_instance):
        """set_active_loop stores loop that can be retrieved."""
        server_base.set_active_loop("test-loop-1", loop_instance)

        retrieved = server_base.get_active_loop("test-loop-1")
        assert retrieved is loop_instance

    def test_remove_active_loop(self, server_base, loop_instance):
        """remove_active_loop removes and returns the loop."""
        server_base.set_active_loop("test-loop-1", loop_instance)

        removed = server_base.remove_active_loop("test-loop-1")
        assert removed is loop_instance
        assert server_base.get_active_loop("test-loop-1") is None

    def test_remove_active_loop_unknown_returns_none(self, server_base):
        """remove_active_loop returns None for unknown loop."""
        result = server_base.remove_active_loop("unknown")
        assert result is None

    def test_active_loop_eviction_on_max(self, server_base_custom):
        """Oldest active loop is evicted when max is reached."""
        # Fill up to max (10)
        for i in range(10):
            loop = LoopInstance(
                loop_id=f"loop-{i}",
                name=f"Loop {i}",
                started_at=time.time(),
            )
            server_base_custom.set_active_loop(f"loop-{i}", loop)
            time.sleep(0.01)  # Ensure different timestamps

        # Add one more - should evict oldest
        new_loop = LoopInstance(loop_id="loop-new", name="New", started_at=time.time())
        server_base_custom.set_active_loop("loop-new", new_loop)

        # Oldest (loop-0) should be gone
        assert server_base_custom.get_active_loop("loop-0") is None
        assert server_base_custom.get_active_loop("loop-new") is not None

    def test_cleanup_active_loops_removes_stale(self, server_base_custom, loop_instance):
        """cleanup_active_loops removes entries older than TTL."""
        server_base_custom.set_active_loop("stale-loop", loop_instance)

        # Artificially age the entry
        with server_base_custom._active_loops_lock:
            server_base_custom._active_loops_last_access["stale-loop"] = time.time() - 90000

        removed = server_base_custom.cleanup_active_loops()

        assert removed == 1
        assert server_base_custom.get_active_loop("stale-loop") is None


# ===========================================================================
# Test Client ID Management
# ===========================================================================


class TestClientIDManagement:
    """Tests for client ID management with LRU eviction."""

    def test_get_client_id_returns_none_for_unknown(self, server_base):
        """get_client_id returns None for unknown ws_id."""
        result = server_base.get_client_id(12345)
        assert result is None

    def test_set_and_get_client_id(self, server_base):
        """set_client_id stores ID that can be retrieved."""
        server_base.set_client_id(12345, "secure-client-id")

        result = server_base.get_client_id(12345)
        assert result == "secure-client-id"

    def test_remove_client_id(self, server_base):
        """remove_client_id removes and returns the ID."""
        server_base.set_client_id(12345, "secure-client-id")

        removed = server_base.remove_client_id(12345)
        assert removed == "secure-client-id"
        assert server_base.get_client_id(12345) is None

    def test_remove_client_id_unknown_returns_none(self, server_base):
        """remove_client_id returns None for unknown ws_id."""
        result = server_base.remove_client_id(99999)
        assert result is None

    def test_lru_eviction_on_max(self, server_base_custom):
        """Oldest client IDs are evicted with LRU when max is reached."""
        # Fill up to max (10)
        for i in range(10):
            server_base_custom.set_client_id(i, f"client-{i}")

        # Add one more - should evict oldest (0)
        server_base_custom.set_client_id(100, "client-100")

        # Oldest should be gone
        assert server_base_custom.get_client_id(0) is None
        assert server_base_custom.get_client_id(100) == "client-100"

    def test_lru_update_on_set(self, server_base_custom):
        """set_client_id moves entry to end (most recently used)."""
        # Add entries
        for i in range(5):
            server_base_custom.set_client_id(i, f"client-{i}")

        # Access entry 0 by setting it again
        server_base_custom.set_client_id(0, "client-0-updated")

        # Fill to max - entry 0 should NOT be evicted (it's most recent)
        for i in range(10, 16):
            server_base_custom.set_client_id(i, f"client-{i}")

        # Entry 0 should still exist (was moved to end)
        assert server_base_custom.get_client_id(0) == "client-0-updated"
        # Entry 1 should be gone (oldest)
        assert server_base_custom.get_client_id(1) is None


# ===========================================================================
# Test WebSocket Authentication
# ===========================================================================


class TestWebSocketAuthentication:
    """Tests for WebSocket authentication state management."""

    def test_set_and_get_ws_auth_state(self, server_base):
        """set_ws_auth_state stores state that can be retrieved."""
        server_base.set_ws_auth_state(
            ws_id=12345,
            authenticated=True,
            token="test-token",
            ip_address="192.168.1.1",
        )

        state = server_base.get_ws_auth_state(12345)
        assert state is not None
        assert state["authenticated"] is True
        assert state["token"] == "test-token"
        assert state["ip_address"] == "192.168.1.1"
        assert "last_validated" in state
        assert "created_at" in state

    def test_get_ws_auth_state_unknown_returns_none(self, server_base):
        """get_ws_auth_state returns None for unknown ws_id."""
        result = server_base.get_ws_auth_state(99999)
        assert result is None

    def test_is_ws_authenticated_true(self, server_base):
        """is_ws_authenticated returns True for authenticated connection."""
        server_base.set_ws_auth_state(12345, authenticated=True)

        assert server_base.is_ws_authenticated(12345) is True

    def test_is_ws_authenticated_false(self, server_base):
        """is_ws_authenticated returns False for unauthenticated connection."""
        server_base.set_ws_auth_state(12345, authenticated=False)

        assert server_base.is_ws_authenticated(12345) is False

    def test_is_ws_authenticated_unknown(self, server_base):
        """is_ws_authenticated returns False for unknown ws_id."""
        assert server_base.is_ws_authenticated(99999) is False

    def test_should_revalidate_ws_token_false_when_recent(self, server_base):
        """should_revalidate_ws_token returns False when recently validated."""
        server_base.set_ws_auth_state(12345, authenticated=True, token="token")

        assert server_base.should_revalidate_ws_token(12345) is False

    def test_should_revalidate_ws_token_true_when_old(self, server_base):
        """should_revalidate_ws_token returns True when validation is old."""
        server_base.set_ws_auth_state(12345, authenticated=True, token="token")

        # Artificially age the validation
        with server_base._ws_auth_lock:
            server_base._ws_auth_states[12345]["last_validated"] = (
                time.time() - WS_TOKEN_REVALIDATION_INTERVAL - 10
            )

        assert server_base.should_revalidate_ws_token(12345) is True

    def test_should_revalidate_ws_token_false_when_unauthenticated(self, server_base):
        """should_revalidate_ws_token returns False for unauthenticated connections."""
        server_base.set_ws_auth_state(12345, authenticated=False)

        assert server_base.should_revalidate_ws_token(12345) is False

    def test_mark_ws_token_validated(self, server_base):
        """mark_ws_token_validated updates last_validated timestamp."""
        server_base.set_ws_auth_state(12345, authenticated=True)

        # Age the validation
        with server_base._ws_auth_lock:
            old_time = time.time() - 1000
            server_base._ws_auth_states[12345]["last_validated"] = old_time

        server_base.mark_ws_token_validated(12345)

        state = server_base.get_ws_auth_state(12345)
        assert state["last_validated"] > old_time

    def test_revoke_ws_auth_success(self, server_base):
        """revoke_ws_auth sets authenticated to False."""
        server_base.set_ws_auth_state(12345, authenticated=True)

        result = server_base.revoke_ws_auth(12345, reason="Token expired")

        assert result is True
        assert server_base.is_ws_authenticated(12345) is False
        state = server_base.get_ws_auth_state(12345)
        assert "revoked_at" in state
        assert state["revoke_reason"] == "Token expired"

    def test_revoke_ws_auth_unknown(self, server_base):
        """revoke_ws_auth returns False for unknown ws_id."""
        result = server_base.revoke_ws_auth(99999)
        assert result is False

    def test_remove_ws_auth_state(self, server_base):
        """remove_ws_auth_state removes and returns the state."""
        server_base.set_ws_auth_state(12345, authenticated=True)

        removed = server_base.remove_ws_auth_state(12345)
        assert removed is not None
        assert removed["authenticated"] is True
        assert server_base.get_ws_auth_state(12345) is None

    def test_get_ws_token(self, server_base):
        """get_ws_token returns stored token."""
        server_base.set_ws_auth_state(12345, authenticated=True, token="my-secret-token")

        token = server_base.get_ws_token(12345)
        assert token == "my-secret-token"

    def test_get_ws_token_none_when_no_token(self, server_base):
        """get_ws_token returns None when no token stored."""
        server_base.set_ws_auth_state(12345, authenticated=True, token=None)

        assert server_base.get_ws_token(12345) is None

    def test_cleanup_ws_auth_states(self, server_base, mock_websocket):
        """cleanup_ws_auth_states removes orphaned auth states."""
        # Add client to server
        server_base.clients.add(mock_websocket)
        ws_id = id(mock_websocket)
        server_base.set_ws_auth_state(ws_id, authenticated=True)

        # Also add orphaned auth state
        server_base.set_ws_auth_state(99999, authenticated=True)

        removed = server_base.cleanup_ws_auth_states()

        assert removed == 1
        assert server_base.get_ws_auth_state(ws_id) is not None
        assert server_base.get_ws_auth_state(99999) is None


# ===========================================================================
# Test Cleanup All and Stats
# ===========================================================================


class TestCleanupAndStats:
    """Tests for cleanup_all and get_stats methods."""

    def test_cleanup_all(self, server_base, loop_instance):
        """cleanup_all runs all cleanup operations and returns counts."""
        # Add some data to clean up
        server_base.get_rate_limiter("client-1")
        server_base.set_debate_state("loop-1", {"status": "running"})
        server_base.set_active_loop("loop-1", loop_instance)
        server_base.set_ws_auth_state(12345, authenticated=True)

        # Age all entries
        old_time = time.time() - 100000
        with server_base._rate_limiters_lock:
            server_base._rate_limiter_last_access["client-1"] = old_time
        with server_base._debate_states_lock:
            server_base._debate_states_last_access["loop-1"] = old_time
        with server_base._active_loops_lock:
            server_base._active_loops_last_access["loop-1"] = old_time

        result = server_base.cleanup_all()

        assert "rate_limiters" in result
        assert "debate_states" in result
        assert "active_loops" in result
        assert "auth_states" in result

    def test_get_stats(self, server_base, mock_websocket):
        """get_stats returns current server statistics."""
        # Add some data
        server_base.clients.add(mock_websocket)
        server_base.get_rate_limiter("client-1")
        server_base.set_debate_state("loop-1", {"status": "running"})
        server_base.set_client_id(1, "client-id")
        server_base.set_ws_auth_state(id(mock_websocket), authenticated=True)

        stats = server_base.get_stats()

        assert stats["clients"] == 1
        assert stats["rate_limiters"] == 1
        assert stats["debate_states"] == 1
        assert stats["client_ids"] == 1
        assert stats["auth_states"] == 1
        assert stats["authenticated_clients"] == 1
        assert stats["running"] is False

    def test_get_stats_authenticated_count(self, server_base):
        """get_stats correctly counts authenticated clients."""
        server_base.set_ws_auth_state(1, authenticated=True)
        server_base.set_ws_auth_state(2, authenticated=True)
        server_base.set_ws_auth_state(3, authenticated=False)

        stats = server_base.get_stats()

        assert stats["auth_states"] == 3
        assert stats["authenticated_clients"] == 2


# ===========================================================================
# Test Context Manager Support
# ===========================================================================


class TestContextManagerSupport:
    """Tests for sync and async context manager support."""

    def test_sync_context_manager_enter(self):
        """Sync context manager sets running to True on enter."""
        server = ServerBase()

        with server as s:
            assert s is server
            assert s._running is True

    def test_sync_context_manager_exit(self):
        """Sync context manager cleans up resources on exit."""
        server = ServerBase()
        server.set_debate_state("loop-1", {"status": "running"})
        server.get_rate_limiter("client-1")

        with server:
            pass

        assert server._running is False
        assert len(server.debate_states) == 0
        assert len(server._rate_limiters) == 0

    @pytest.mark.asyncio
    async def test_async_context_manager_enter(self):
        """Async context manager sets running to True on enter."""
        server = ServerBase()

        async with server as s:
            assert s is server
            assert s._running is True

    @pytest.mark.asyncio
    async def test_async_context_manager_exit(self):
        """Async context manager cleans up resources on exit."""
        server = ServerBase()
        server.set_debate_state("loop-1", {"status": "running"})
        server.get_rate_limiter("client-1")
        server.set_client_id(1, "client-id")

        async with server:
            pass

        assert server._running is False
        assert len(server.debate_states) == 0
        assert len(server._rate_limiters) == 0
        assert len(server._client_ids) == 0

    def test_cleanup_resources(self):
        """_cleanup_resources clears all tracked state."""
        server = ServerBase()

        # Add various data
        server.get_rate_limiter("client-1")
        server.set_debate_state("loop-1", {"status": "running"})
        server.set_active_loop(
            "loop-1", LoopInstance(loop_id="loop-1", name="Test", started_at=time.time())
        )
        server.set_client_id(1, "client-id")
        server.set_ws_auth_state(1, authenticated=True)
        server.clients.add(MagicMock())

        server._cleanup_resources()

        assert len(server._rate_limiters) == 0
        assert len(server._rate_limiter_last_access) == 0
        assert len(server.debate_states) == 0
        assert len(server._debate_states_last_access) == 0
        assert len(server.active_loops) == 0
        assert len(server._active_loops_last_access) == 0
        assert len(server._ws_auth_states) == 0
        assert len(server._client_ids) == 0
        assert len(server.clients) == 0


# ===========================================================================
# Test Thread Safety
# ===========================================================================


class TestThreadSafety:
    """Tests for thread safety of ServerBase operations."""

    def test_concurrent_debate_state_operations(self, server_base):
        """Debate state operations are thread-safe."""
        errors = []

        def modify_states():
            try:
                for i in range(50):
                    loop_id = f"loop-{i % 10}"
                    server_base.set_debate_state(loop_id, {"i": i})
                    server_base.get_debate_state(loop_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=modify_states) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_active_loop_operations(self, server_base):
        """Active loop operations are thread-safe."""
        errors = []

        def modify_loops():
            try:
                for i in range(50):
                    loop_id = f"loop-{i % 10}"
                    loop = LoopInstance(loop_id=loop_id, name="Test", started_at=time.time())
                    server_base.set_active_loop(loop_id, loop)
                    server_base.get_active_loop(loop_id)
                    if i % 5 == 0:
                        server_base.remove_active_loop(loop_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=modify_loops) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_ws_auth_operations(self, server_base):
        """WebSocket auth operations are thread-safe."""
        errors = []

        def modify_auth():
            try:
                for i in range(50):
                    ws_id = i % 10
                    server_base.set_ws_auth_state(ws_id, authenticated=True, token=f"token-{i}")
                    server_base.get_ws_auth_state(ws_id)
                    server_base.is_ws_authenticated(ws_id)
                    if i % 5 == 0:
                        server_base.mark_ws_token_validated(ws_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=modify_auth) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ===========================================================================
# Test Constants
# ===========================================================================


class TestConstants:
    """Tests for module-level constants."""

    def test_ws_token_revalidation_interval(self):
        """WS_TOKEN_REVALIDATION_INTERVAL has expected value."""
        assert WS_TOKEN_REVALIDATION_INTERVAL == 300.0  # 5 minutes
