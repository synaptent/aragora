"""
Tests for WebSocket broadcasting and client management utilities.

Tests cover:
- ClientManager: Client tracking, LRU eviction, rate limiter management
- DebateStateCache: State updates from events, TTL cleanup
- LoopRegistry: Loop registration, state updates, LRU eviction
- WebSocketBroadcaster: Broadcasting, batching, event grouping
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.stream.broadcaster import (
    BroadcasterConfig,
    ClientManager,
    DebateStateCache,
    LoopRegistry,
    WebSocketBroadcaster,
)
from aragora.events.types import StreamEvent, StreamEventType


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def config():
    """Create a test configuration with lower limits for faster testing."""
    return BroadcasterConfig(
        max_active_loops=5,
        active_loops_ttl=60,
        max_debate_states=5,
        debate_states_ttl=60,
        rate_limiter_ttl=60,
        cleanup_interval=2,
        max_client_ids=5,
    )


@pytest.fixture
def client_manager(config):
    """Create a ClientManager with test config."""
    return ClientManager(config)


@pytest.fixture
def debate_state_cache(config):
    """Create a DebateStateCache with test config."""
    return DebateStateCache(config)


@pytest.fixture
def loop_registry(config):
    """Create a LoopRegistry with test config."""
    return LoopRegistry(config)


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket for testing."""
    ws = MagicMock()
    ws.send = AsyncMock()
    return ws


# ===========================================================================
# Test BroadcasterConfig
# ===========================================================================


class TestBroadcasterConfig:
    """Tests for BroadcasterConfig dataclass."""

    def test_default_values(self):
        """Config has reasonable default values."""
        config = BroadcasterConfig()
        assert config.max_active_loops == 1000
        assert config.active_loops_ttl == 86400
        assert config.max_debate_states == 500
        assert config.debate_states_ttl == 3600
        assert config.rate_limit_per_minute == 60.0

    def test_custom_values(self):
        """Config accepts custom values."""
        config = BroadcasterConfig(
            max_active_loops=10,
            rate_limit_per_minute=120.0,
        )
        assert config.max_active_loops == 10
        assert config.rate_limit_per_minute == 120.0


# ===========================================================================
# Test ClientManager
# ===========================================================================


class TestClientManager:
    """Tests for ClientManager class."""

    def test_add_client_returns_secure_id(self, client_manager, mock_websocket):
        """add_client returns a cryptographically secure ID."""
        client_id = client_manager.add_client(mock_websocket)
        assert client_id is not None
        assert len(client_id) >= 16  # Base64 encoding of 16 bytes
        assert mock_websocket in client_manager.clients

    def test_add_client_same_websocket_returns_same_id(self, client_manager, mock_websocket):
        """Adding the same websocket returns the same client ID."""
        client_id1 = client_manager.add_client(mock_websocket)
        client_id2 = client_manager.add_client(mock_websocket)
        assert client_id1 == client_id2

    def test_remove_client(self, client_manager, mock_websocket):
        """remove_client removes the client and its ID."""
        client_manager.add_client(mock_websocket)
        assert mock_websocket in client_manager.clients

        client_manager.remove_client(mock_websocket)
        assert mock_websocket not in client_manager.clients
        assert client_manager.get_client_id(mock_websocket) is None

    def test_get_client_id(self, client_manager, mock_websocket):
        """get_client_id returns the ID for a tracked websocket."""
        client_id = client_manager.add_client(mock_websocket)
        assert client_manager.get_client_id(mock_websocket) == client_id

    def test_get_client_id_unknown(self, client_manager, mock_websocket):
        """get_client_id returns None for unknown websocket."""
        assert client_manager.get_client_id(mock_websocket) is None

    def test_lru_eviction_at_capacity(self, client_manager):
        """Oldest client ID is evicted when at capacity."""
        websockets = [MagicMock() for _ in range(6)]  # Capacity is 5
        client_ids = []

        for ws in websockets:
            client_ids.append(client_manager.add_client(ws))

        # First websocket's ID should have been evicted (LRU)
        assert client_manager.get_client_id(websockets[0]) is None
        # Most recent should still be tracked
        assert client_manager.get_client_id(websockets[5]) is not None

    def test_get_rate_limiter(self, client_manager, mock_websocket):
        """get_rate_limiter returns a TokenBucket for the client."""
        client_id = client_manager.add_client(mock_websocket)
        limiter = client_manager.get_rate_limiter(client_id)
        assert limiter is not None
        # Same limiter should be returned on subsequent calls
        assert client_manager.get_rate_limiter(client_id) is limiter

    def test_rate_limiter_cleanup(self, client_manager):
        """Stale rate limiters are cleaned up."""
        # Add rate limiters
        for i in range(3):
            client_manager.get_rate_limiter(f"client-{i}")

        # Manually mark all as stale
        stale_time = time.time() - (client_manager.config.rate_limiter_ttl + 1)
        for key in client_manager._rate_limiter_last_access:
            client_manager._rate_limiter_last_access[key] = stale_time

        # Trigger cleanup
        client_manager._cleanup_stale_rate_limiters()

        assert len(client_manager._rate_limiters) == 0

    def test_client_count(self, client_manager):
        """client_count returns number of connected clients."""
        assert client_manager.client_count == 0

        for i in range(3):
            ws = MagicMock()
            client_manager.add_client(ws)

        assert client_manager.client_count == 3

    def test_cleanup(self, client_manager):
        """cleanup clears all tracked resources."""
        for i in range(3):
            ws = MagicMock()
            client_id = client_manager.add_client(ws)
            client_manager.get_rate_limiter(client_id)

        client_manager.cleanup()

        assert client_manager.client_count == 0
        assert len(client_manager._rate_limiters) == 0

    def test_context_manager(self, config):
        """ClientManager works as context manager."""
        with ClientManager(config) as manager:
            ws = MagicMock()
            manager.add_client(ws)
            assert manager.client_count == 1

        # Cleanup should have been called
        assert manager.client_count == 0


# ===========================================================================
# Test DebateStateCache
# ===========================================================================


class TestDebateStateCache:
    """Tests for DebateStateCache class."""

    def test_debate_start_event(self, debate_state_cache):
        """DEBATE_START event initializes state."""
        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test task", "agents": ["claude", "gpt4"]},
        )

        debate_state_cache.update_from_event(event)

        state = debate_state_cache.get_state("debate-1")
        assert state is not None
        assert state["task"] == "Test task"
        assert state["agents"] == ["claude", "gpt4"]
        assert state["messages"] == []
        assert state["consensus_reached"] is False
        assert state["ended"] is False

    def test_agent_message_event(self, debate_state_cache):
        """AGENT_MESSAGE event adds to messages."""
        # First create the debate
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test", "agents": ["claude"]},
        )
        debate_state_cache.update_from_event(start_event)

        # Then add a message
        msg_event = StreamEvent(
            type=StreamEventType.AGENT_MESSAGE,
            loop_id="debate-1",
            agent="claude",
            round=1,
            data={"content": "Test response", "role": "proposer"},
        )
        debate_state_cache.update_from_event(msg_event)

        state = debate_state_cache.get_state("debate-1")
        assert len(state["messages"]) == 1
        assert state["messages"][0]["agent"] == "claude"
        assert state["messages"][0]["content"] == "Test response"

    def test_agent_message_caps_at_1000(self, debate_state_cache):
        """Messages are capped at 1000."""
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test", "agents": ["claude"]},
        )
        debate_state_cache.update_from_event(start_event)

        # Add 1005 messages
        for i in range(1005):
            msg_event = StreamEvent(
                type=StreamEventType.AGENT_MESSAGE,
                loop_id="debate-1",
                agent="claude",
                round=1,
                data={"content": f"Message {i}"},
            )
            debate_state_cache.update_from_event(msg_event)

        state = debate_state_cache.get_state("debate-1")
        assert len(state["messages"]) == 1000
        # First messages should have been discarded
        assert "Message 5" in state["messages"][0]["content"]

    def test_round_start_event(self, debate_state_cache):
        """ROUND_START event updates round count."""
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test", "agents": ["claude"]},
        )
        debate_state_cache.update_from_event(start_event)

        round_event = StreamEvent(
            type=StreamEventType.ROUND_START,
            loop_id="debate-1",
            round=3,
            data={},
        )
        debate_state_cache.update_from_event(round_event)

        state = debate_state_cache.get_state("debate-1")
        assert state["rounds"] == 3

    def test_consensus_event(self, debate_state_cache):
        """CONSENSUS event updates consensus info."""
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test", "agents": ["claude"]},
        )
        debate_state_cache.update_from_event(start_event)

        consensus_event = StreamEvent(
            type=StreamEventType.CONSENSUS,
            loop_id="debate-1",
            data={"reached": True, "confidence": 0.95, "answer": "42"},
        )
        debate_state_cache.update_from_event(consensus_event)

        state = debate_state_cache.get_state("debate-1")
        assert state["consensus_reached"] is True
        assert state["consensus_confidence"] == 0.95
        assert state["consensus_answer"] == "42"

    def test_debate_end_event(self, debate_state_cache):
        """DEBATE_END event marks debate as ended."""
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test", "agents": ["claude"]},
        )
        debate_state_cache.update_from_event(start_event)

        end_event = StreamEvent(
            type=StreamEventType.DEBATE_END,
            loop_id="debate-1",
            data={"duration": 45.5},
        )
        debate_state_cache.update_from_event(end_event)

        state = debate_state_cache.get_state("debate-1")
        assert state["ended"] is True
        assert state["duration"] == 45.5

    def test_loop_unregister_event(self, debate_state_cache):
        """LOOP_UNREGISTER event removes state."""
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test", "agents": ["claude"]},
        )
        debate_state_cache.update_from_event(start_event)

        assert debate_state_cache.get_state("debate-1") is not None

        unregister_event = StreamEvent(
            type=StreamEventType.LOOP_UNREGISTER,
            loop_id="debate-1",
            data={},
        )
        debate_state_cache.update_from_event(unregister_event)

        assert debate_state_cache.get_state("debate-1") is None

    def test_get_state_returns_copy(self, debate_state_cache):
        """get_state returns a copy, not the original dict."""
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test", "agents": ["claude"]},
        )
        debate_state_cache.update_from_event(start_event)

        state1 = debate_state_cache.get_state("debate-1")
        state1["task"] = "Modified"

        state2 = debate_state_cache.get_state("debate-1")
        assert state2["task"] == "Test"  # Original unmodified

    def test_get_state_unknown_returns_none(self, debate_state_cache):
        """get_state returns None for unknown debate."""
        assert debate_state_cache.get_state("nonexistent") is None

    def test_lru_eviction_prefers_ended_debates(self, debate_state_cache):
        """LRU eviction prefers removing ended debates."""
        # Fill cache (capacity is 5)
        for i in range(5):
            event = StreamEvent(
                type=StreamEventType.DEBATE_START,
                loop_id=f"debate-{i}",
                data={"task": f"Task {i}", "agents": []},
            )
            debate_state_cache.update_from_event(event)

        # End the first one
        end_event = StreamEvent(
            type=StreamEventType.DEBATE_END,
            loop_id="debate-0",
            data={"duration": 10.0},
        )
        debate_state_cache.update_from_event(end_event)

        # Add a 6th debate (should evict the ended one)
        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-5",
            data={"task": "Task 5", "agents": []},
        )
        debate_state_cache.update_from_event(event)

        # Ended debate should have been evicted
        assert debate_state_cache.get_state("debate-0") is None
        # New debate should exist
        assert debate_state_cache.get_state("debate-5") is not None

    def test_cleanup_stale(self, debate_state_cache):
        """cleanup_stale removes old ended debates."""
        # Create and end a debate
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test", "agents": []},
        )
        debate_state_cache.update_from_event(start_event)

        end_event = StreamEvent(
            type=StreamEventType.DEBATE_END,
            loop_id="debate-1",
            data={"duration": 10.0},
        )
        debate_state_cache.update_from_event(end_event)

        # Mark as stale
        stale_time = time.time() - (debate_state_cache.config.debate_states_ttl + 1)
        debate_state_cache._last_access["debate-1"] = stale_time

        removed = debate_state_cache.cleanup_stale()
        assert removed == 1
        assert debate_state_cache.get_state("debate-1") is None

    def test_set_tts_callback(self, debate_state_cache):
        """TTS callback can be set."""
        callback = AsyncMock()
        debate_state_cache.set_tts_callback(callback)
        assert debate_state_cache._tts_callback is callback

    def test_context_manager(self, config):
        """DebateStateCache works as context manager."""
        with DebateStateCache(config) as cache:
            event = StreamEvent(
                type=StreamEventType.DEBATE_START,
                loop_id="debate-1",
                data={"task": "Test", "agents": []},
            )
            cache.update_from_event(event)
            assert cache.get_state("debate-1") is not None

        # Cleanup should have been called
        assert len(cache.debate_states) == 0


# ===========================================================================
# Test LoopRegistry
# ===========================================================================


class TestLoopRegistry:
    """Tests for LoopRegistry class."""

    def test_register_loop(self, loop_registry):
        """register creates a new LoopInstance."""
        instance = loop_registry.register("loop-1", "Test Loop", "/path")

        assert instance.loop_id == "loop-1"
        assert instance.name == "Test Loop"
        assert instance.path == "/path"
        assert loop_registry.count == 1

    def test_register_lru_eviction(self, loop_registry):
        """LRU eviction when at capacity."""
        # Fill capacity (5)
        for i in range(5):
            loop_registry.register(f"loop-{i}", f"Loop {i}")

        # Make loop-0 the oldest by accessing others
        time.sleep(0.01)
        for i in range(1, 5):
            loop_registry.get(f"loop-{i}")

        # Add one more (should evict loop-0)
        loop_registry.register("loop-5", "Loop 5")

        assert loop_registry.get("loop-0") is None
        assert loop_registry.get("loop-5") is not None
        assert loop_registry.count == 5

    def test_unregister(self, loop_registry):
        """unregister removes a loop."""
        loop_registry.register("loop-1", "Test Loop")
        assert loop_registry.count == 1

        result = loop_registry.unregister("loop-1")
        assert result is True
        assert loop_registry.count == 0

    def test_unregister_nonexistent(self, loop_registry):
        """unregister returns False for unknown loop."""
        result = loop_registry.unregister("nonexistent")
        assert result is False

    def test_update_state(self, loop_registry):
        """update_state modifies loop properties."""
        loop_registry.register("loop-1", "Test Loop")

        result = loop_registry.update_state("loop-1", cycle=5, phase="debate")
        assert result is True

        instance = loop_registry.get("loop-1")
        assert instance.cycle == 5
        assert instance.phase == "debate"

    def test_update_state_partial(self, loop_registry):
        """update_state can update just one property."""
        loop_registry.register("loop-1", "Test Loop")
        original_phase = loop_registry.get("loop-1").phase
        loop_registry.update_state("loop-1", cycle=3)

        instance = loop_registry.get("loop-1")
        assert instance.cycle == 3
        assert instance.phase == original_phase  # Phase unchanged

    def test_update_state_nonexistent(self, loop_registry):
        """update_state returns False for unknown loop."""
        result = loop_registry.update_state("nonexistent", cycle=1)
        assert result is False

    def test_get_list(self, loop_registry):
        """get_list returns list of loop dicts."""
        loop_registry.register("loop-1", "Loop 1")
        loop_registry.register("loop-2", "Loop 2")
        loop_registry.update_state("loop-1", cycle=2, phase="design")

        loops = loop_registry.get_list()
        assert len(loops) == 2

        loop1 = next(lp for lp in loops if lp["loop_id"] == "loop-1")
        assert loop1["name"] == "Loop 1"
        assert loop1["cycle"] == 2
        assert loop1["phase"] == "design"

    def test_get(self, loop_registry):
        """get returns LoopInstance for known loop."""
        loop_registry.register("loop-1", "Test Loop")
        instance = loop_registry.get("loop-1")
        assert instance is not None
        assert instance.loop_id == "loop-1"

    def test_get_unknown(self, loop_registry):
        """get returns None for unknown loop."""
        assert loop_registry.get("nonexistent") is None

    def test_cleanup_stale(self, loop_registry):
        """cleanup_stale removes old loops."""
        loop_registry.register("loop-1", "Test Loop")

        # Mark as stale
        stale_time = time.time() - (loop_registry.config.active_loops_ttl + 1)
        loop_registry._last_access["loop-1"] = stale_time

        removed = loop_registry.cleanup_stale()
        assert removed == 1
        assert loop_registry.count == 0

    def test_context_manager(self, config):
        """LoopRegistry works as context manager."""
        with LoopRegistry(config) as registry:
            registry.register("loop-1", "Test Loop")
            assert registry.count == 1

        # Cleanup should have been called
        assert registry.count == 0


# ===========================================================================
# Test WebSocketBroadcaster
# ===========================================================================


class TestWebSocketBroadcaster:
    """Tests for WebSocketBroadcaster class."""

    @pytest.fixture
    def broadcaster(self, config):
        """Create a WebSocketBroadcaster with test config."""
        return WebSocketBroadcaster(config=config)

    def test_initialization(self, broadcaster):
        """Broadcaster initializes all components."""
        assert broadcaster.client_manager is not None
        assert broadcaster.debate_state_cache is not None
        assert broadcaster.loop_registry is not None
        assert broadcaster.audience_inbox is not None

    def test_emitter_property(self, broadcaster):
        """emitter property returns the event emitter."""
        emitter = broadcaster.emitter
        assert emitter is not None

    def test_clients_property(self, broadcaster):
        """clients property returns connected clients set."""
        assert broadcaster.clients == set()

        ws = MagicMock()
        broadcaster.client_manager.add_client(ws)
        assert ws in broadcaster.clients

    @pytest.mark.asyncio
    async def test_broadcast(self, broadcaster):
        """broadcast sends event to all subscribed clients."""
        ws1 = MagicMock()
        ws1.send = AsyncMock()
        ws1._bound_loop_id = "test"
        ws2 = MagicMock()
        ws2.send = AsyncMock()
        ws2._bound_loop_id = "test"

        broadcaster.client_manager.add_client(ws1)
        broadcaster.client_manager.add_client(ws2)

        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="test",
            data={"task": "Test"},
        )

        await broadcaster.broadcast(event)

        ws1.send.assert_called_once()
        ws2.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_broadcast_removes_disconnected(self, broadcaster):
        """broadcast removes clients that fail to send."""
        ws1 = MagicMock()
        ws1.send = AsyncMock()
        ws1._bound_loop_id = "test"
        ws2 = MagicMock()
        ws2.send = AsyncMock(side_effect=ConnectionError("Disconnected"))
        ws2._bound_loop_id = "test"

        broadcaster.client_manager.add_client(ws1)
        broadcaster.client_manager.add_client(ws2)

        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="test",
            data={"task": "Test"},
        )

        await broadcaster.broadcast(event)

        # ws2 should have been removed
        assert ws1 in broadcaster.clients
        assert ws2 not in broadcaster.clients

    @pytest.mark.asyncio
    async def test_broadcast_no_clients(self, broadcaster):
        """broadcast does nothing with no clients."""
        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="test",
            data={"task": "Test"},
        )

        # Should not raise
        await broadcaster.broadcast(event)

    @pytest.mark.asyncio
    async def test_broadcast_batch(self, broadcaster):
        """broadcast_batch sends multiple events as JSON array."""
        ws = MagicMock()
        ws.send = AsyncMock()
        ws._bound_loop_id = "test"
        broadcaster.client_manager.add_client(ws)

        events = [
            StreamEvent(type=StreamEventType.DEBATE_START, loop_id="test", data={}),
            StreamEvent(type=StreamEventType.ROUND_START, loop_id="test", round=1, data={}),
        ]

        await broadcaster.broadcast_batch(events)

        ws.send.assert_called_once()
        # Should be a JSON array
        call_arg = ws.send.call_args[0][0]
        import json

        parsed = json.loads(call_arg)
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    @pytest.mark.asyncio
    async def test_broadcast_batch_empty(self, broadcaster):
        """broadcast_batch does nothing with empty list."""
        ws = MagicMock()
        ws.send = AsyncMock()
        broadcaster.client_manager.add_client(ws)

        await broadcaster.broadcast_batch([])

        ws.send.assert_not_called()

    def test_group_events_by_agent(self, broadcaster):
        """_group_events_by_agent groups TOKEN_DELTA by agent."""
        events = [
            StreamEvent(
                type=StreamEventType.TOKEN_DELTA,
                loop_id="test",
                agent="claude",
                data={"token": "A"},
                agent_seq=1,
            ),
            StreamEvent(
                type=StreamEventType.TOKEN_DELTA,
                loop_id="test",
                agent="gpt4",
                data={"token": "X"},
                agent_seq=1,
            ),
            StreamEvent(
                type=StreamEventType.TOKEN_DELTA,
                loop_id="test",
                agent="claude",
                data={"token": "B"},
                agent_seq=2,
            ),
            StreamEvent(
                type=StreamEventType.TOKEN_DELTA,
                loop_id="test",
                agent="gpt4",
                data={"token": "Y"},
                agent_seq=2,
            ),
        ]

        grouped = broadcaster._group_events_by_agent(events)

        # Should be grouped by agent
        # Claude's tokens should be together, GPT4's tokens should be together
        claude_indices = [i for i, e in enumerate(grouped) if e.agent == "claude"]
        gpt4_indices = [i for i, e in enumerate(grouped) if e.agent == "gpt4"]

        # Check that each agent's tokens are contiguous
        assert claude_indices == [0, 1] or claude_indices == [2, 3]
        assert gpt4_indices == [0, 1] or gpt4_indices == [2, 3]

    def test_group_events_non_token_flushes(self, broadcaster):
        """Non-token events flush buffered tokens."""
        events = [
            StreamEvent(
                type=StreamEventType.TOKEN_DELTA,
                loop_id="test",
                agent="claude",
                data={"token": "A"},
                agent_seq=1,
            ),
            StreamEvent(type=StreamEventType.ROUND_START, loop_id="test", round=1, data={}),
            StreamEvent(
                type=StreamEventType.TOKEN_DELTA,
                loop_id="test",
                agent="claude",
                data={"token": "B"},
                agent_seq=2,
            ),
        ]

        grouped = broadcaster._group_events_by_agent(events)

        # Order should be: token A, round_start, token B
        assert grouped[0].type == StreamEventType.TOKEN_DELTA
        assert grouped[1].type == StreamEventType.ROUND_START
        assert grouped[2].type == StreamEventType.TOKEN_DELTA

    def test_stop(self, broadcaster):
        """stop sets _running to False."""
        broadcaster._running = True
        broadcaster.stop()
        assert broadcaster._running is False

    def test_cleanup_all(self, broadcaster):
        """cleanup_all runs cleanup on all components."""
        # Add some data
        ws = MagicMock()
        broadcaster.client_manager.add_client(ws)
        broadcaster.loop_registry.register("loop-1", "Test")

        # Mark loop as stale for cleanup
        stale_time = time.time() - (broadcaster.config.active_loops_ttl + 1)
        broadcaster.loop_registry._last_access["loop-1"] = stale_time

        result = broadcaster.cleanup_all()
        assert "loops" in result
        assert result["loops"] == 1

    def test_cleanup(self, broadcaster):
        """cleanup clears all resources."""
        ws = MagicMock()
        broadcaster.client_manager.add_client(ws)
        broadcaster.loop_registry.register("loop-1", "Test")
        broadcaster._running = True

        broadcaster.cleanup()

        assert broadcaster._running is False
        assert broadcaster.client_manager.client_count == 0
        assert broadcaster.loop_registry.count == 0

    def test_context_manager(self, config):
        """WebSocketBroadcaster works as context manager."""
        with WebSocketBroadcaster(config=config) as broadcaster:
            ws = MagicMock()
            broadcaster.client_manager.add_client(ws)
            assert broadcaster.client_manager.client_count == 1

        # Cleanup should have been called
        assert broadcaster.client_manager.client_count == 0

    @pytest.mark.asyncio
    async def test_async_context_manager(self, config):
        """WebSocketBroadcaster works as async context manager."""
        async with WebSocketBroadcaster(config=config) as broadcaster:
            ws = MagicMock()
            broadcaster.client_manager.add_client(ws)
            assert broadcaster.client_manager.client_count == 1

        # Cleanup should have been called
        assert broadcaster.client_manager.client_count == 0

    def test_emitter_subscription(self, broadcaster):
        """Broadcaster subscribes to emitter for state updates."""
        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="test",
            data={"task": "Test task", "agents": ["claude"]},
        )

        # Emit through the emitter
        broadcaster.emitter.emit(event)

        # Debate state cache should have been updated
        state = broadcaster.debate_state_cache.get_state("test")
        assert state is not None
        assert state["task"] == "Test task"


# ===========================================================================
# Test Integration Scenarios
# ===========================================================================


class TestBroadcasterIntegration:
    """Integration tests for broadcaster components working together."""

    @pytest.mark.asyncio
    async def test_full_debate_lifecycle(self, config):
        """Test a complete debate from start to end."""
        broadcaster = WebSocketBroadcaster(config=config)

        # Add a client
        ws = MagicMock()
        ws.send = AsyncMock()
        ws._bound_loop_id = "debate-1"
        broadcaster.client_manager.add_client(ws)

        # Start debate
        start_event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="debate-1",
            data={"task": "Test question", "agents": ["claude", "gpt4"]},
        )
        broadcaster.emitter.emit(start_event)
        await broadcaster.broadcast(start_event)

        # Add messages
        for i in range(3):
            msg_event = StreamEvent(
                type=StreamEventType.AGENT_MESSAGE,
                loop_id="debate-1",
                agent="claude" if i % 2 == 0 else "gpt4",
                round=1,
                data={"content": f"Response {i}", "role": "proposer"},
            )
            broadcaster.emitter.emit(msg_event)
            await broadcaster.broadcast(msg_event)

        # End debate
        end_event = StreamEvent(
            type=StreamEventType.DEBATE_END,
            loop_id="debate-1",
            data={"duration": 30.0},
        )
        broadcaster.emitter.emit(end_event)
        await broadcaster.broadcast(end_event)

        # Verify state
        state = broadcaster.debate_state_cache.get_state("debate-1")
        assert state is not None
        assert state["ended"] is True
        assert len(state["messages"]) == 3

        # Verify broadcasts
        assert ws.send.call_count == 5  # start + 3 messages + end

        broadcaster.cleanup()

    @pytest.mark.asyncio
    async def test_client_disconnect_during_broadcast(self, config):
        """Test graceful handling of client disconnect."""
        broadcaster = WebSocketBroadcaster(config=config)

        # Add multiple clients
        good_ws = MagicMock()
        good_ws.send = AsyncMock()
        good_ws._bound_loop_id = "test"
        bad_ws = MagicMock()
        bad_ws.send = AsyncMock(side_effect=ConnectionResetError())
        bad_ws._bound_loop_id = "test"

        broadcaster.client_manager.add_client(good_ws)
        broadcaster.client_manager.add_client(bad_ws)

        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            loop_id="test",
            data={"task": "Test"},
        )

        await broadcaster.broadcast(event)

        # Bad client should be removed, good client should remain
        assert good_ws in broadcaster.clients
        assert bad_ws not in broadcaster.clients

        broadcaster.cleanup()

    def test_rate_limiting_across_components(self, config):
        """Test rate limiting works correctly."""
        broadcaster = WebSocketBroadcaster(config=config)

        # Add client and get rate limiter
        ws = MagicMock()
        client_id = broadcaster.client_manager.add_client(ws)
        limiter = broadcaster.client_manager.get_rate_limiter(client_id)

        # Consume all tokens
        for _ in range(config.rate_limit_burst):
            limiter.consume()

        # Next consume should fail
        assert limiter.consume() is False

        broadcaster.cleanup()
