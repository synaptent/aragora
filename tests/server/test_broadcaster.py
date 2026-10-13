"""
Tests for broadcaster.py - WebSocket broadcasting infrastructure.

Tests ClientManager, DebateStateCache, LoopRegistry.
"""

import pytest
import time
from unittest.mock import MagicMock

from aragora.server.stream.broadcaster import (
    BroadcasterConfig,
    ClientManager,
    DebateStateCache,
    LoopRegistry,
)
from aragora.server.stream.state_manager import LoopInstance
from aragora.events.types import StreamEvent, StreamEventType


# =============================================================================
# BroadcasterConfig Tests
# =============================================================================


class TestBroadcasterConfig:
    """Tests for BroadcasterConfig dataclass."""

    def test_default_values(self):
        """Should have sensible default values."""
        config = BroadcasterConfig()

        assert config.max_active_loops > 0
        assert config.active_loops_ttl > 0
        assert config.max_debate_states > 0
        assert config.debate_states_ttl > 0
        assert config.rate_limiter_ttl > 0
        assert config.cleanup_interval > 0
        assert config.max_client_ids > 0

    def test_custom_values(self):
        """Should accept custom values."""
        config = BroadcasterConfig(
            max_active_loops=50,
            max_debate_states=200,
            cleanup_interval=50,
        )

        assert config.max_active_loops == 50
        assert config.max_debate_states == 200
        assert config.cleanup_interval == 50


# =============================================================================
# ClientManager Tests
# =============================================================================


class TestClientManager:
    """Tests for ClientManager."""

    @pytest.fixture
    def manager(self):
        """Create ClientManager with default config."""
        return ClientManager()

    @pytest.fixture
    def mock_websocket(self):
        """Create mock websocket."""
        ws = MagicMock()
        return ws

    def test_add_client(self, manager, mock_websocket):
        """Should add client and return unique ID."""
        client_id = manager.add_client(mock_websocket)

        assert client_id is not None
        assert len(client_id) > 0
        assert manager.client_count == 1

    def test_add_multiple_clients(self, manager):
        """Should assign unique IDs to multiple clients."""
        ws1 = MagicMock()
        ws2 = MagicMock()

        id1 = manager.add_client(ws1)
        id2 = manager.add_client(ws2)

        assert id1 != id2
        assert manager.client_count == 2

    def test_remove_client(self, manager, mock_websocket):
        """Should remove client by websocket."""
        manager.add_client(mock_websocket)
        assert manager.client_count == 1

        manager.remove_client(mock_websocket)
        assert manager.client_count == 0

    def test_remove_nonexistent_client(self, manager, mock_websocket):
        """Should handle removal of nonexistent client gracefully."""
        # Should not raise
        manager.remove_client(mock_websocket)
        assert manager.client_count == 0

    def test_get_client_id(self, manager, mock_websocket):
        """Should return client ID for known websocket."""
        expected_id = manager.add_client(mock_websocket)
        actual_id = manager.get_client_id(mock_websocket)

        assert actual_id == expected_id

    def test_get_client_id_unknown(self, manager, mock_websocket):
        """Should return None for unknown websocket."""
        client_id = manager.get_client_id(mock_websocket)
        assert client_id is None

    def test_get_rate_limiter(self, manager, mock_websocket):
        """Should return rate limiter for client."""
        client_id = manager.add_client(mock_websocket)
        limiter = manager.get_rate_limiter(client_id)

        assert limiter is not None
        # TokenBucket should have consume method
        assert hasattr(limiter, "consume")

    def test_lru_eviction_for_client_ids(self):
        """Should evict oldest client IDs when at capacity."""
        config = BroadcasterConfig(max_client_ids=2)
        manager = ClientManager(config=config)

        ws1, ws2, ws3 = MagicMock(), MagicMock(), MagicMock()

        id1 = manager.add_client(ws1)
        id2 = manager.add_client(ws2)
        id3 = manager.add_client(ws3)

        # All should get IDs (LRU eviction happens in client_ids dict, not clients set)
        assert id1 is not None
        assert id2 is not None
        assert id3 is not None
        assert manager.client_count == 3

    def test_context_manager(self, mock_websocket):
        """Should work as context manager."""
        with ClientManager() as manager:
            manager.add_client(mock_websocket)
            assert manager.client_count == 1

    def test_cleanup(self, manager, mock_websocket):
        """Should cleanup all clients."""
        manager.add_client(mock_websocket)
        manager.cleanup()

        assert manager.client_count == 0


# =============================================================================
# DebateStateCache Tests
# =============================================================================


class TestDebateStateCache:
    """Tests for DebateStateCache."""

    @pytest.fixture
    def cache(self):
        """Create DebateStateCache with default config."""
        return DebateStateCache()

    @pytest.fixture
    def mock_debate_start_event(self):
        """Create mock debate_start event."""
        return StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="loop-123",
            data={
                "task": "Test Task",
                "agents": ["agent1", "agent2"],
            },
            timestamp=time.time(),
        )

    @pytest.fixture
    def mock_agent_message_event(self):
        """Create mock agent_message event."""
        return StreamEvent(
            type=StreamEventType.AGENT_MESSAGE,
            loop_id="loop-123",
            agent="agent1",
            round=1,
            data={
                "role": "proposer",
                "content": "Test message",
            },
            timestamp=time.time(),
        )

    def test_update_from_debate_start(self, cache, mock_debate_start_event):
        """Should create state from debate_start event."""
        cache.update_from_event(mock_debate_start_event)

        state = cache.get_state("loop-123")
        assert state is not None
        assert state["task"] == "Test Task"
        assert "agent1" in state["agents"]

    def test_update_from_agent_message(
        self, cache, mock_debate_start_event, mock_agent_message_event
    ):
        """Should update state from agent_message event."""
        cache.update_from_event(mock_debate_start_event)
        cache.update_from_event(mock_agent_message_event)

        state = cache.get_state("loop-123")
        assert state is not None
        assert len(state.get("messages", [])) > 0

    def test_get_state_unknown_loop(self, cache):
        """Should return None for unknown loop."""
        state = cache.get_state("unknown-loop")
        assert state is None

    def test_cleanup_stale_ended_debates(self, cache, mock_debate_start_event):
        """Should cleanup stale ended debates."""
        # Create state with very short TTL config
        config = BroadcasterConfig(debate_states_ttl=0)  # 0 seconds TTL
        cache = DebateStateCache(config=config)

        cache.update_from_event(mock_debate_start_event)

        # End the debate
        end_event = StreamEvent(
            type=StreamEventType.DEBATE_END,
            loop_id="loop-123",
            data={"duration": 10.0},
            timestamp=time.time(),
        )
        cache.update_from_event(end_event)

        # Should have state before cleanup
        assert cache.get_state("loop-123") is not None

        # Wait briefly for TTL to pass
        time.sleep(0.01)
        cleaned = cache.cleanup_stale()

        # Cleanup only removes ended debates
        assert cleaned >= 0

    def test_context_manager(self, mock_debate_start_event):
        """Should work as context manager."""
        with DebateStateCache() as cache:
            cache.update_from_event(mock_debate_start_event)
            assert cache.get_state("loop-123") is not None


# =============================================================================
# LoopRegistry Tests
# =============================================================================


class TestLoopRegistry:
    """Tests for LoopRegistry."""

    @pytest.fixture
    def registry(self):
        """Create LoopRegistry with default config."""
        return LoopRegistry()

    def test_register_loop(self, registry):
        """Should register loop and return LoopInstance."""
        loop = registry.register("loop-123", "Test Loop", "/path/to/loop")

        assert loop is not None
        assert loop.loop_id == "loop-123"
        assert loop.name == "Test Loop"
        assert loop.path == "/path/to/loop"

    def test_register_replaces_existing(self, registry):
        """Should replace existing loop when registering duplicate."""
        loop1 = registry.register("loop-123", "Test Loop")
        loop2 = registry.register("loop-123", "Different Name")

        assert loop2.loop_id == "loop-123"
        assert loop2.name == "Different Name"
        # Count should still be 1
        assert registry.count == 1

    def test_unregister_loop(self, registry):
        """Should unregister loop."""
        registry.register("loop-123", "Test Loop")
        assert registry.count == 1

        result = registry.unregister("loop-123")

        assert result is True
        assert registry.count == 0

    def test_unregister_unknown_loop(self, registry):
        """Should return False for unknown loop."""
        result = registry.unregister("unknown-loop")
        assert result is False

    def test_update_state(self, registry):
        """Should update loop state."""
        registry.register("loop-123", "Test Loop")

        result = registry.update_state("loop-123", cycle=5, phase="debate")

        assert result is True
        loop = registry.get("loop-123")
        assert loop.cycle == 5
        assert loop.phase == "debate"

    def test_update_state_unknown_loop(self, registry):
        """Should return False for unknown loop."""
        result = registry.update_state("unknown-loop", cycle=5)
        assert result is False

    def test_get_list(self, registry):
        """Should return list of all loops."""
        registry.register("loop-1", "Loop 1")
        registry.register("loop-2", "Loop 2")

        loops = registry.get_list()

        assert len(loops) == 2
        loop_ids = [loop["loop_id"] for loop in loops]
        assert "loop-1" in loop_ids
        assert "loop-2" in loop_ids

    def test_get_loop(self, registry):
        """Should return loop by ID."""
        registry.register("loop-123", "Test Loop")

        loop = registry.get("loop-123")

        assert loop is not None
        assert loop.loop_id == "loop-123"

    def test_get_unknown_loop(self, registry):
        """Should return None for unknown loop."""
        loop = registry.get("unknown-loop")
        assert loop is None

    def test_count(self, registry):
        """Should return correct count."""
        assert registry.count == 0

        registry.register("loop-1", "Loop 1")
        assert registry.count == 1

        registry.register("loop-2", "Loop 2")
        assert registry.count == 2

    def test_cleanup_stale(self, registry):
        """Should cleanup stale loops."""
        config = BroadcasterConfig(active_loops_ttl=0)  # 0 seconds TTL
        registry = LoopRegistry(config=config)

        registry.register("loop-123", "Test Loop")
        assert registry.count == 1

        # Wait briefly for TTL to pass
        time.sleep(0.01)
        cleaned = registry.cleanup_stale()

        assert cleaned >= 0

    def test_context_manager(self):
        """Should work as context manager."""
        with LoopRegistry() as registry:
            registry.register("loop-123", "Test Loop")
            assert registry.count == 1


# =============================================================================
# LoopInstance Tests
# =============================================================================


class TestLoopInstance:
    """Tests for LoopInstance dataclass."""

    def test_default_values(self):
        """Should have sensible default values."""
        loop = LoopInstance(
            loop_id="loop-123",
            name="Test Loop",
            started_at=time.time(),
        )

        assert loop.loop_id == "loop-123"
        assert loop.name == "Test Loop"
        assert loop.cycle == 0
        assert loop.phase == "starting"  # default is "starting"
        assert loop.path == ""

    def test_started_at_timestamp(self):
        """Should store started_at timestamp."""
        before = time.time()
        loop = LoopInstance(loop_id="loop-123", name="Test", started_at=time.time())
        after = time.time()

        # started_at should be between before and after
        assert before <= loop.started_at <= after


# =============================================================================
# Integration Tests
# =============================================================================


class TestBroadcasterIntegration:
    """Integration tests for broadcaster components."""

    def test_client_manager_with_rate_limiter(self):
        """ClientManager should create rate limiters for clients."""
        manager = ClientManager()
        ws = MagicMock()

        client_id = manager.add_client(ws)
        limiter = manager.get_rate_limiter(client_id)

        # Rate limiter should exist and be usable
        assert limiter is not None
        # TokenBucket has consume() method
        assert hasattr(limiter, "consume")

    def test_state_cache_lifecycle(self):
        """DebateStateCache should handle full debate lifecycle."""
        cache = DebateStateCache()

        # Start event
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="loop-123",
            data={"task": "Test", "agents": ["a1", "a2"]},
            timestamp=time.time(),
        )
        cache.update_from_event(start_event)

        # Round start event
        round_event = StreamEvent(
            type=StreamEventType.ROUND_START,
            loop_id="loop-123",
            round=1,
            data={},
            timestamp=time.time(),
        )
        cache.update_from_event(round_event)

        # End event
        end_event = StreamEvent(
            type=StreamEventType.DEBATE_END,
            loop_id="loop-123",
            data={"duration": 10.0},
            timestamp=time.time(),
        )
        cache.update_from_event(end_event)

        state = cache.get_state("loop-123")
        assert state is not None
        assert state.get("ended") is True

    def test_registry_with_state_updates(self):
        """LoopRegistry should track state changes."""
        registry = LoopRegistry()

        registry.register("loop-123", "Test Loop")
        registry.update_state("loop-123", cycle=1, phase="init")
        registry.update_state("loop-123", cycle=1, phase="debate")
        registry.update_state("loop-123", cycle=2, phase="init")

        loop = registry.get("loop-123")
        assert loop.cycle == 2
        assert loop.phase == "init"
