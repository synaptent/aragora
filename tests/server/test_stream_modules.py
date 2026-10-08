"""
Tests for server/stream submodules: events, emitter, state_manager.

These modules handle WebSocket streaming, audience participation,
and debate state tracking with thread-safety and TTL-based cleanup.
"""

import json
import threading
import time
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest

from aragora.events.types import (
    StreamEventType,
    StreamEvent,
    AudienceMessage,
)
from aragora.server.stream.emitter import (
    TokenBucket,
    AudienceInbox,
    SyncEventEmitter,
    normalize_intensity,
)
from aragora.server.stream.state_manager import (
    BoundedDebateDict,
    LoopInstance,
    DebateStateManager,
    get_active_debates,
    get_active_debates_lock,
    cleanup_stale_debates,
    increment_cleanup_counter,
)


# =============================================================================
# Tests for events.py
# =============================================================================


class TestStreamEventType:
    """Tests for StreamEventType enum."""

    def test_debate_events_exist(self):
        """All core debate events should be defined."""
        assert StreamEventType.DEBATE_START.value == "debate_start"
        assert StreamEventType.ROUND_START.value == "round_start"
        assert StreamEventType.AGENT_MESSAGE.value == "agent_message"
        assert StreamEventType.CRITIQUE.value == "critique"
        assert StreamEventType.VOTE.value == "vote"
        assert StreamEventType.CONSENSUS.value == "consensus"
        assert StreamEventType.DEBATE_END.value == "debate_end"

    def test_token_streaming_events_exist(self):
        """Token streaming events should be defined."""
        assert StreamEventType.TOKEN_START.value == "token_start"
        assert StreamEventType.TOKEN_DELTA.value == "token_delta"
        assert StreamEventType.TOKEN_END.value == "token_end"

    def test_nomic_loop_events_exist(self):
        """Nomic loop events should be defined."""
        assert StreamEventType.CYCLE_START.value == "cycle_start"
        assert StreamEventType.CYCLE_END.value == "cycle_end"
        assert StreamEventType.PHASE_START.value == "phase_start"
        assert StreamEventType.PHASE_END.value == "phase_end"

    def test_audience_events_exist(self):
        """Audience participation events should be defined."""
        assert StreamEventType.USER_VOTE.value == "user_vote"
        assert StreamEventType.USER_SUGGESTION.value == "user_suggestion"
        assert StreamEventType.AUDIENCE_SUMMARY.value == "audience_summary"

    def test_telemetry_events_exist(self):
        """Telemetry events should be defined."""
        assert StreamEventType.TELEMETRY_THOUGHT.value == "telemetry_thought"
        assert StreamEventType.TELEMETRY_CAPABILITY.value == "telemetry_capability"
        assert StreamEventType.TELEMETRY_REDACTION.value == "telemetry_redaction"


class TestStreamEvent:
    """Tests for StreamEvent dataclass."""

    def test_creation_with_defaults(self):
        """StreamEvent should have sensible defaults."""
        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            data={"topic": "Test topic"},
        )
        assert event.type == StreamEventType.DEBATE_START
        assert event.data == {"topic": "Test topic"}
        assert event.round == 0
        assert event.agent == ""
        assert event.loop_id == ""
        assert event.seq == 0
        assert event.agent_seq == 0
        assert event.timestamp > 0

    def test_creation_with_all_fields(self):
        """StreamEvent should accept all fields."""
        ts = time.time()
        event = StreamEvent(
            type=StreamEventType.AGENT_MESSAGE,
            data={"content": "Hello"},
            timestamp=ts,
            round=2,
            agent="claude",
            loop_id="loop-123",
            seq=42,
            agent_seq=5,
        )
        assert event.timestamp == ts
        assert event.round == 2
        assert event.agent == "claude"
        assert event.loop_id == "loop-123"
        assert event.seq == 42
        assert event.agent_seq == 5

    def test_to_dict(self):
        """to_dict should return proper dictionary representation."""
        event = StreamEvent(
            type=StreamEventType.VOTE,
            data={"choice": "option1"},
            round=3,
            agent="gemini",
            seq=10,
            agent_seq=2,
        )
        result = event.to_dict()

        assert result["type"] == "vote"
        assert result["data"] == {"choice": "option1"}
        assert result["round"] == 3
        assert result["agent"] == "gemini"
        assert result["seq"] == 10
        assert result["agent_seq"] == 2
        assert "timestamp" in result

    def test_to_dict_includes_loop_id_when_set(self):
        """to_dict should include loop_id only when set."""
        event_without_loop = StreamEvent(
            type=StreamEventType.CONSENSUS,
            data={},
        )
        assert "loop_id" not in event_without_loop.to_dict()

        event_with_loop = StreamEvent(
            type=StreamEventType.CONSENSUS,
            data={},
            loop_id="loop-456",
        )
        assert event_with_loop.to_dict()["loop_id"] == "loop-456"

    def test_to_json(self):
        """to_json should return valid JSON string."""
        event = StreamEvent(
            type=StreamEventType.ERROR,
            data={"message": "Test error"},
        )
        json_str = event.to_json()
        parsed = json.loads(json_str)

        assert parsed["type"] == "error"
        assert parsed["data"]["message"] == "Test error"


class TestAudienceMessage:
    """Tests for AudienceMessage dataclass."""

    def test_creation_with_defaults(self):
        """AudienceMessage should have sensible defaults."""
        msg = AudienceMessage(
            type="vote",
            loop_id="loop-123",
            payload={"choice": "option1"},
        )
        assert msg.type == "vote"
        assert msg.loop_id == "loop-123"
        assert msg.payload == {"choice": "option1"}
        assert msg.user_id == ""
        assert msg.timestamp > 0

    def test_creation_with_user_id(self):
        """AudienceMessage should accept user_id."""
        msg = AudienceMessage(
            type="suggestion",
            loop_id="loop-456",
            payload={"text": "Consider X"},
            user_id="user-789",
        )
        assert msg.user_id == "user-789"


# =============================================================================
# Tests for emitter.py
# =============================================================================


class TestNormalizeIntensity:
    """Tests for normalize_intensity utility function."""

    def test_valid_integer(self):
        """Should return integer values unchanged if in range."""
        assert normalize_intensity(5) == 5
        assert normalize_intensity(1) == 1
        assert normalize_intensity(10) == 10

    def test_clamping_low(self):
        """Should clamp values below minimum."""
        assert normalize_intensity(0) == 1
        assert normalize_intensity(-5) == 1

    def test_clamping_high(self):
        """Should clamp values above maximum."""
        assert normalize_intensity(11) == 10
        assert normalize_intensity(100) == 10

    def test_none_returns_default(self):
        """None should return default value."""
        assert normalize_intensity(None) == 5
        assert normalize_intensity(None, default=7) == 7

    def test_string_conversion(self):
        """Should convert string to int."""
        assert normalize_intensity("7") == 7
        assert normalize_intensity("3.9") == 3  # Truncates

    def test_invalid_string_returns_default(self):
        """Invalid strings should return default."""
        assert normalize_intensity("invalid") == 5
        assert normalize_intensity("") == 5

    def test_custom_range(self):
        """Should respect custom min/max values."""
        assert normalize_intensity(5, min_val=1, max_val=5) == 5
        assert normalize_intensity(10, min_val=1, max_val=5) == 5
        assert normalize_intensity(0, min_val=1, max_val=5) == 1


class TestTokenBucket:
    """Tests for TokenBucket rate limiter."""

    def test_initial_burst_capacity(self):
        """Bucket should start with full burst capacity."""
        bucket = TokenBucket(rate_per_minute=60, burst_size=10)
        # Should be able to consume burst_size tokens immediately
        for _ in range(10):
            assert bucket.consume() is True
        # Next should fail (no time for refill)
        assert bucket.consume() is False

    def test_refill_over_time(self):
        """Bucket should refill tokens over time."""
        bucket = TokenBucket(rate_per_minute=600, burst_size=5)
        # Consume all tokens
        for _ in range(5):
            bucket.consume()
        assert bucket.consume() is False

        # Manually advance time (simulate 0.1 minutes = 6 seconds)
        bucket.last_refill = time.monotonic() - 6
        # At 600/min = 10/sec, 6 seconds should refill ~60 tokens (capped at 5)
        assert bucket.consume() is True

    def test_multi_token_consume(self):
        """Should support consuming multiple tokens at once."""
        bucket = TokenBucket(rate_per_minute=60, burst_size=10)
        assert bucket.consume(tokens=5) is True
        assert bucket.consume(tokens=5) is True
        assert bucket.consume(tokens=1) is False

    def test_thread_safety(self):
        """Bucket should be thread-safe under concurrent access."""
        bucket = TokenBucket(rate_per_minute=1000, burst_size=100)
        consumed = []
        lock = threading.Lock()

        def worker():
            for _ in range(20):
                result = bucket.consume()
                with lock:
                    consumed.append(result)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have exactly 100 successful consumes
        assert consumed.count(True) == 100
        assert consumed.count(False) == 100


class TestAudienceInbox:
    """Tests for AudienceInbox message queue."""

    def test_put_and_get_all(self):
        """Should store and retrieve all messages."""
        inbox = AudienceInbox()
        msg1 = AudienceMessage(type="vote", loop_id="loop1", payload={"choice": "A"})
        msg2 = AudienceMessage(type="suggestion", loop_id="loop1", payload={"text": "X"})

        inbox.put(msg1)
        inbox.put(msg2)

        messages = inbox.get_all()
        assert len(messages) == 2
        assert messages[0] == msg1
        assert messages[1] == msg2

    def test_get_all_drains_inbox(self):
        """get_all should empty the inbox."""
        inbox = AudienceInbox()
        inbox.put(AudienceMessage(type="vote", loop_id="loop1", payload={}))
        inbox.put(AudienceMessage(type="vote", loop_id="loop1", payload={}))

        _ = inbox.get_all()
        assert len(inbox.get_all()) == 0

    def test_get_summary_vote_counts(self):
        """Should count votes by choice."""
        inbox = AudienceInbox()
        inbox.put(
            AudienceMessage(type="vote", loop_id="loop1", payload={"choice": "A", "intensity": 5})
        )
        inbox.put(
            AudienceMessage(type="vote", loop_id="loop1", payload={"choice": "A", "intensity": 8})
        )
        inbox.put(
            AudienceMessage(type="vote", loop_id="loop1", payload={"choice": "B", "intensity": 3})
        )

        summary = inbox.get_summary()
        assert summary["votes"] == {"A": 2, "B": 1}
        assert summary["suggestions"] == 0
        assert summary["total"] == 3

    def test_get_summary_weighted_votes(self):
        """Should calculate weighted votes based on intensity."""
        inbox = AudienceInbox()
        # High intensity vote (10 -> weight 2.0)
        inbox.put(
            AudienceMessage(type="vote", loop_id="loop1", payload={"choice": "A", "intensity": 10})
        )
        # Low intensity vote (1 -> weight 0.5)
        inbox.put(
            AudienceMessage(type="vote", loop_id="loop1", payload={"choice": "B", "intensity": 1})
        )

        summary = inbox.get_summary()
        assert summary["weighted_votes"]["A"] == pytest.approx(2.0, rel=0.1)
        assert summary["weighted_votes"]["B"] == pytest.approx(0.5, rel=0.1)

    def test_get_summary_histograms(self):
        """Should build per-choice intensity histograms."""
        inbox = AudienceInbox()
        inbox.put(
            AudienceMessage(type="vote", loop_id="loop1", payload={"choice": "A", "intensity": 5})
        )
        inbox.put(
            AudienceMessage(type="vote", loop_id="loop1", payload={"choice": "A", "intensity": 5})
        )
        inbox.put(
            AudienceMessage(type="vote", loop_id="loop1", payload={"choice": "A", "intensity": 10})
        )

        summary = inbox.get_summary()
        assert summary["histograms"]["A"][5] == 2
        assert summary["histograms"]["A"][10] == 1

    def test_get_summary_conviction_distribution(self):
        """Should track global conviction distribution."""
        inbox = AudienceInbox()
        inbox.put(
            AudienceMessage(type="vote", loop_id="loop1", payload={"choice": "A", "intensity": 5})
        )
        inbox.put(
            AudienceMessage(type="vote", loop_id="loop1", payload={"choice": "B", "intensity": 5})
        )
        inbox.put(
            AudienceMessage(type="vote", loop_id="loop1", payload={"choice": "A", "intensity": 10})
        )

        summary = inbox.get_summary()
        assert summary["conviction_distribution"][5] == 2
        assert summary["conviction_distribution"][10] == 1

    def test_get_summary_filter_by_loop_id(self):
        """Should filter messages by loop_id when provided."""
        inbox = AudienceInbox()
        inbox.put(AudienceMessage(type="vote", loop_id="loop1", payload={"choice": "A"}))
        inbox.put(AudienceMessage(type="vote", loop_id="loop2", payload={"choice": "B"}))

        summary_loop1 = inbox.get_summary(loop_id="loop1")
        assert summary_loop1["votes"] == {"A": 1}

        summary_loop2 = inbox.get_summary(loop_id="loop2")
        assert summary_loop2["votes"] == {"B": 1}

    def test_thread_safety(self):
        """Inbox should be thread-safe under concurrent access."""
        inbox = AudienceInbox()
        lock = threading.Lock()
        total_added = [0]

        def producer(count):
            for i in range(count):
                inbox.put(AudienceMessage(type="vote", loop_id="loop1", payload={"i": i}))
                with lock:
                    total_added[0] += 1

        threads = [threading.Thread(target=producer, args=(50,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        messages = inbox.get_all()
        assert len(messages) == 500


class TestSyncEventEmitter:
    """Tests for SyncEventEmitter bridging sync/async code."""

    def test_emit_queues_event(self):
        """emit() should queue events for later drain()."""
        emitter = SyncEventEmitter()
        event = StreamEvent(type=StreamEventType.DEBATE_START, data={"topic": "Test"})

        emitter.emit(event)

        events = emitter.drain()
        assert len(events) == 1
        assert events[0].type == StreamEventType.DEBATE_START

    def test_drain_empties_queue(self):
        """drain() should empty the queue."""
        emitter = SyncEventEmitter()
        emitter.emit(StreamEvent(type=StreamEventType.VOTE, data={}))

        _ = emitter.drain()
        assert len(emitter.drain()) == 0

    def test_sequence_numbers_assigned(self):
        """emit() should assign global sequence numbers."""
        emitter = SyncEventEmitter()
        event1 = StreamEvent(type=StreamEventType.DEBATE_START, data={})
        event2 = StreamEvent(type=StreamEventType.ROUND_START, data={})

        emitter.emit(event1)
        emitter.emit(event2)

        events = emitter.drain()
        assert events[0].seq == 1
        assert events[1].seq == 2

    def test_agent_sequence_numbers(self):
        """emit() should assign per-agent sequence numbers."""
        emitter = SyncEventEmitter()
        e1 = StreamEvent(type=StreamEventType.TOKEN_DELTA, data={}, agent="claude")
        e2 = StreamEvent(type=StreamEventType.TOKEN_DELTA, data={}, agent="gemini")
        e3 = StreamEvent(type=StreamEventType.TOKEN_DELTA, data={}, agent="claude")

        emitter.emit(e1)
        emitter.emit(e2)
        emitter.emit(e3)

        events = emitter.drain()
        # claude: seq 1, 2
        assert events[0].agent_seq == 1
        assert events[2].agent_seq == 2
        # gemini: seq 1
        assert events[1].agent_seq == 1

    def test_loop_id_attached(self):
        """Events should have loop_id attached when set."""
        emitter = SyncEventEmitter(loop_id="loop-123")
        event = StreamEvent(type=StreamEventType.VOTE, data={})

        emitter.emit(event)

        events = emitter.drain()
        assert events[0].loop_id == "loop-123"

    def test_set_loop_id(self):
        """set_loop_id should change the loop_id for future events."""
        emitter = SyncEventEmitter()
        emitter.set_loop_id("new-loop")

        event = StreamEvent(type=StreamEventType.VOTE, data={})
        emitter.emit(event)

        events = emitter.drain()
        assert events[0].loop_id == "new-loop"

    def test_reset_sequences(self):
        """reset_sequences should reset all counters."""
        emitter = SyncEventEmitter()
        emitter.emit(StreamEvent(type=StreamEventType.VOTE, data={}, agent="claude"))
        emitter.drain()

        emitter.reset_sequences()

        event = StreamEvent(type=StreamEventType.VOTE, data={}, agent="claude")
        emitter.emit(event)
        events = emitter.drain()
        assert events[0].seq == 1
        assert events[0].agent_seq == 1

    def test_subscriber_callback(self):
        """Subscribers should receive events immediately."""
        emitter = SyncEventEmitter()
        received = []

        def callback(event):
            received.append(event)

        emitter.subscribe(callback)
        event = StreamEvent(type=StreamEventType.CONSENSUS, data={})
        emitter.emit(event)

        assert len(received) == 1
        assert received[0].type == StreamEventType.CONSENSUS

    def test_subscriber_exception_does_not_break_emit(self):
        """Subscriber exceptions should not break event emission."""
        emitter = SyncEventEmitter()

        def bad_callback(event):
            raise RuntimeError("Callback error")

        emitter.subscribe(bad_callback)
        event = StreamEvent(type=StreamEventType.VOTE, data={})

        # Should not raise
        emitter.emit(event)

        # Event should still be queued
        events = emitter.drain()
        assert len(events) == 1

    def test_drain_batch_size(self):
        """drain() should respect max_batch_size."""
        emitter = SyncEventEmitter()
        for i in range(10):
            emitter.emit(StreamEvent(type=StreamEventType.VOTE, data={"i": i}))

        batch = emitter.drain(max_batch_size=3)
        assert len(batch) == 3

        # Remaining events still in queue
        remaining = emitter.drain()
        assert len(remaining) == 7

    def test_queue_overflow_protection(self):
        """Queue should drop oldest events when full."""
        emitter = SyncEventEmitter()
        # Reduce max size for testing
        emitter.MAX_QUEUE_SIZE = 10

        # Fill queue beyond capacity
        for i in range(15):
            emitter.emit(StreamEvent(type=StreamEventType.VOTE, data={"i": i}))

        events = emitter.drain()
        # Should have dropped 5 oldest events
        assert len(events) == 10
        assert emitter._overflow_count == 5

    def test_thread_safety(self):
        """Emitter should be thread-safe under concurrent access."""
        emitter = SyncEventEmitter()

        def producer(count):
            for i in range(count):
                emitter.emit(StreamEvent(type=StreamEventType.VOTE, data={"i": i}))

        threads = [threading.Thread(target=producer, args=(50,)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Drain all events (may need multiple batches)
        events = emitter.drain(max_batch_size=1000)
        assert len(events) == 500
        # All sequence numbers should be unique
        seqs = [e.seq for e in events]
        assert len(set(seqs)) == 500


# =============================================================================
# Tests for state_manager.py
# =============================================================================


class TestBoundedDebateDict:
    """Tests for BoundedDebateDict with eviction."""

    def test_normal_dict_operations(self):
        """Should behave like a normal OrderedDict."""
        d = BoundedDebateDict(maxsize=10)
        d["key1"] = {"status": "active"}
        d["key2"] = {"status": "completed"}

        assert d["key1"] == {"status": "active"}
        assert len(d) == 2

    def test_eviction_when_full(self):
        """Should evict oldest entries when at capacity."""
        d = BoundedDebateDict(maxsize=3)
        d["a"] = 1
        d["b"] = 2
        d["c"] = 3
        d["d"] = 4  # Should evict "a"

        assert "a" not in d
        assert "b" in d
        assert "d" in d
        assert len(d) == 3

    def test_update_existing_key_no_eviction(self):
        """Updating existing key should not trigger eviction."""
        d = BoundedDebateDict(maxsize=3)
        d["a"] = 1
        d["b"] = 2
        d["c"] = 3
        d["b"] = 200  # Update existing

        assert len(d) == 3
        assert d["b"] == 200
        assert "a" in d  # "a" should not be evicted

    def test_eviction_order(self):
        """Should evict in FIFO order."""
        d = BoundedDebateDict(maxsize=2)
        d["first"] = 1
        d["second"] = 2
        d["third"] = 3  # Evicts "first"
        d["fourth"] = 4  # Evicts "second"

        assert list(d.keys()) == ["third", "fourth"]


class TestLoopInstance:
    """Tests for LoopInstance dataclass."""

    def test_creation(self):
        """Should create with required fields."""
        instance = LoopInstance(
            loop_id="loop-123",
            name="Test Loop",
            started_at=time.time(),
        )
        assert instance.loop_id == "loop-123"
        assert instance.name == "Test Loop"
        assert instance.cycle == 0
        assert instance.phase == "starting"
        assert instance.path == ""


class TestDebateStateManager:
    """Tests for DebateStateManager state tracking."""

    def test_register_loop(self):
        """Should register new loop instances."""
        manager = DebateStateManager()
        instance = manager.register_loop("loop-123", "Test Loop", "/path")

        assert instance.loop_id == "loop-123"
        assert instance.name == "Test Loop"
        assert instance.path == "/path"
        assert "loop-123" in manager.active_loops

    def test_unregister_loop(self):
        """Should unregister loop instances."""
        manager = DebateStateManager()
        manager.register_loop("loop-123", "Test Loop")

        result = manager.unregister_loop("loop-123")
        assert result is True
        assert "loop-123" not in manager.active_loops

    def test_unregister_nonexistent_loop(self):
        """Should return False for nonexistent loop."""
        manager = DebateStateManager()
        result = manager.unregister_loop("nonexistent")
        assert result is False

    def test_update_loop_state(self):
        """Should update loop cycle and phase."""
        manager = DebateStateManager()
        manager.register_loop("loop-123", "Test Loop")

        manager.update_loop_state("loop-123", cycle=2, phase="debate")

        loop = manager.active_loops["loop-123"]
        assert loop.cycle == 2
        assert loop.phase == "debate"

    def test_get_loop_list(self):
        """Should return list of active loops as dicts."""
        manager = DebateStateManager()
        manager.register_loop("loop-1", "Loop One", "/path1")
        manager.register_loop("loop-2", "Loop Two", "/path2")

        loop_list = manager.get_loop_list()
        assert len(loop_list) == 2

        ids = [loop["loop_id"] for loop in loop_list]
        assert "loop-1" in ids
        assert "loop-2" in ids

    def test_max_active_loops_eviction(self):
        """Should evict oldest loops when at capacity."""
        manager = DebateStateManager()
        manager._MAX_ACTIVE_LOOPS = 3

        manager.register_loop("loop-1", "Loop 1")
        time.sleep(0.01)
        manager.register_loop("loop-2", "Loop 2")
        time.sleep(0.01)
        manager.register_loop("loop-3", "Loop 3")
        time.sleep(0.01)
        manager.register_loop("loop-4", "Loop 4")  # Evicts loop-1

        assert "loop-1" not in manager.active_loops
        assert len(manager.active_loops) == 3

    def test_debate_state_get_set(self):
        """Should get/set cached debate states."""
        manager = DebateStateManager()
        manager.set_debate_state("loop-123", {"status": "active", "round": 2})

        state = manager.get_debate_state("loop-123")
        assert state["status"] == "active"
        assert state["round"] == 2

    def test_debate_state_returns_none_for_missing(self):
        """Should return None for nonexistent states."""
        manager = DebateStateManager()
        assert manager.get_debate_state("nonexistent") is None

    def test_remove_debate_state(self):
        """Should remove cached debate states."""
        manager = DebateStateManager()
        manager.set_debate_state("loop-123", {"status": "active"})
        manager.remove_debate_state("loop-123")

        assert manager.get_debate_state("loop-123") is None

    def test_max_debate_states_eviction(self):
        """Should evict oldest ended states when at capacity."""
        manager = DebateStateManager()
        manager._MAX_DEBATE_STATES = 3

        manager.set_debate_state("s1", {"ended": True})
        time.sleep(0.01)
        manager.set_debate_state("s2", {"ended": True})
        time.sleep(0.01)
        manager.set_debate_state("s3", {"ended": False})  # Active, not evictable
        time.sleep(0.01)
        manager.set_debate_state("s4", {"ended": True})  # Should evict s1

        assert "s1" not in manager.debate_states
        assert "s2" in manager.debate_states
        assert "s3" in manager.debate_states  # Active protected
        assert "s4" in manager.debate_states

    def test_cleanup_stale_entries(self):
        """Should clean up stale entries based on TTL."""
        manager = DebateStateManager()
        manager._ACTIVE_LOOPS_TTL = 0.01  # Very short TTL for testing
        manager._DEBATE_STATES_TTL = 0.01

        manager.register_loop("old-loop", "Old Loop")
        manager.set_debate_state("old-state", {"ended": True})

        time.sleep(0.02)  # Wait for TTL to expire

        cleaned = manager.cleanup_stale_entries()
        assert cleaned >= 2
        assert "old-loop" not in manager.active_loops
        assert "old-state" not in manager.debate_states

    def test_should_cleanup_periodic(self):
        """should_cleanup should return True every N accesses."""
        manager = DebateStateManager()
        manager._CLEANUP_INTERVAL = 5

        for _ in range(4):
            assert manager.should_cleanup() is False
        assert manager.should_cleanup() is True
        assert manager.should_cleanup() is False

    def test_thread_safety(self):
        """Manager should be thread-safe under concurrent access."""
        manager = DebateStateManager()
        errors = []

        def worker(i):
            try:
                loop_id = f"loop-{i}"
                manager.register_loop(loop_id, f"Loop {i}")
                manager.update_loop_state(loop_id, cycle=i, phase="debate")
                manager.set_debate_state(loop_id, {"round": i})
                _ = manager.get_loop_list()
                _ = manager.get_debate_state(loop_id)
                manager.unregister_loop(loop_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestGlobalStateAccessors:
    """Tests for global state accessor functions."""

    def test_get_active_debates_returns_bounded_dict(self):
        """Should return the global BoundedDebateDict."""
        debates = get_active_debates()
        assert isinstance(debates, BoundedDebateDict)

    def test_get_active_debates_lock_returns_lock(self):
        """Should return a threading.Lock."""
        lock = get_active_debates_lock()
        assert isinstance(lock, type(threading.Lock()))

    def test_increment_cleanup_counter(self):
        """Should return True every 100 calls."""
        # Reset counter by calling until it returns True
        while not increment_cleanup_counter():
            pass

        # Now count to 99
        for _ in range(99):
            assert increment_cleanup_counter() is False
        assert increment_cleanup_counter() is True
