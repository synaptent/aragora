"""Tests for stream event emitter module.

Tests the TokenBucket, AudienceInbox, and SyncEventEmitter classes
used for streaming events in the Aragora server.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from aragora.events.types import AudienceMessage, StreamEvent, StreamEventType


class TestNormalizeIntensity:
    """Test normalize_intensity function."""

    def test_normalize_valid_int(self):
        """Test normalizing valid integer."""
        from aragora.server.stream.emitter import normalize_intensity

        assert normalize_intensity(5) == 5
        assert normalize_intensity(1) == 1
        assert normalize_intensity(10) == 10

    def test_normalize_valid_string(self):
        """Test normalizing string number."""
        from aragora.server.stream.emitter import normalize_intensity

        assert normalize_intensity("5") == 5
        assert normalize_intensity("7.5") == 7

    def test_normalize_clamps_values(self):
        """Test that values are clamped to range."""
        from aragora.server.stream.emitter import normalize_intensity

        assert normalize_intensity(0) == 1  # Below min
        assert normalize_intensity(-5) == 1  # Negative
        assert normalize_intensity(15) == 10  # Above max

    def test_normalize_none_returns_default(self):
        """Test None returns default value."""
        from aragora.server.stream.emitter import normalize_intensity

        assert normalize_intensity(None) == 5
        assert normalize_intensity(None, default=7) == 7

    def test_normalize_invalid_returns_default(self):
        """Test invalid values return default."""
        from aragora.server.stream.emitter import normalize_intensity

        assert normalize_intensity("not a number") == 5
        assert normalize_intensity({}) == 5
        assert normalize_intensity([]) == 5


class TestTokenBucket:
    """Test TokenBucket rate limiter."""

    def test_initial_full_bucket(self):
        """Test bucket starts full."""
        from aragora.server.stream.emitter import TokenBucket

        bucket = TokenBucket(rate_per_minute=10, burst_size=5)

        # Should be able to consume burst_size tokens immediately
        for _ in range(5):
            assert bucket.consume(1) is True

        # 6th should fail
        assert bucket.consume(1) is False

    def test_token_refill(self):
        """Test tokens refill over time."""
        from aragora.server.stream.emitter import TokenBucket

        bucket = TokenBucket(rate_per_minute=600, burst_size=1)  # 10 per second

        # Consume the one available token
        assert bucket.consume(1) is True
        assert bucket.consume(1) is False

        # Wait for refill
        time.sleep(0.2)  # Should refill ~2 tokens

        assert bucket.consume(1) is True

    def test_burst_capacity(self):
        """Test burst capacity limits."""
        from aragora.server.stream.emitter import TokenBucket

        bucket = TokenBucket(rate_per_minute=60, burst_size=3)

        # Should allow burst of 3
        assert bucket.consume(1) is True
        assert bucket.consume(1) is True
        assert bucket.consume(1) is True
        assert bucket.consume(1) is False

    def test_multiple_token_consumption(self):
        """Test consuming multiple tokens at once."""
        from aragora.server.stream.emitter import TokenBucket

        bucket = TokenBucket(rate_per_minute=60, burst_size=5)

        assert bucket.consume(3) is True  # 5 - 3 = 2 remaining
        assert bucket.consume(3) is False  # Not enough
        assert bucket.consume(2) is True  # 2 - 2 = 0 remaining


class TestAudienceInbox:
    """Test AudienceInbox class."""

    def test_put_and_get_all(self):
        """Test basic put and get_all operations."""
        from aragora.server.stream.emitter import AudienceInbox

        inbox = AudienceInbox(max_messages=100)

        msg1 = AudienceMessage(type="vote", loop_id="loop_001", payload={"choice": "A"})
        msg2 = AudienceMessage(type="vote", loop_id="loop_001", payload={"choice": "B"})

        inbox.put(msg1)
        inbox.put(msg2)

        messages = inbox.get_all()
        assert len(messages) == 2
        assert messages[0].payload["choice"] == "A"
        assert messages[1].payload["choice"] == "B"

        # Inbox should be empty now
        assert inbox.get_all() == []

    def test_max_messages_limit(self):
        """Test inbox respects max_messages limit."""
        from aragora.server.stream.emitter import AudienceInbox

        inbox = AudienceInbox(max_messages=3)

        for i in range(5):
            msg = AudienceMessage(type="vote", loop_id="loop_001", payload={"i": i})
            inbox.put(msg)

        messages = inbox.get_all()
        assert len(messages) == 3
        # Should have kept most recent
        assert messages[0].payload["i"] == 2
        assert messages[1].payload["i"] == 3
        assert messages[2].payload["i"] == 4

    def test_get_summary_votes(self):
        """Test get_summary counts votes correctly."""
        from aragora.server.stream.emitter import AudienceInbox

        inbox = AudienceInbox()

        # Add some votes
        for _ in range(3):
            inbox.put(
                AudienceMessage(
                    type="vote",
                    loop_id="loop_001",
                    payload={"choice": "A", "intensity": 5},
                )
            )
        for _ in range(2):
            inbox.put(
                AudienceMessage(
                    type="vote",
                    loop_id="loop_001",
                    payload={"choice": "B", "intensity": 8},
                )
            )

        summary = inbox.get_summary()

        assert summary["votes"]["A"] == 3
        assert summary["votes"]["B"] == 2
        assert summary["total"] == 5

    def test_get_summary_suggestions(self):
        """Test get_summary counts suggestions."""
        from aragora.server.stream.emitter import AudienceInbox

        inbox = AudienceInbox()

        inbox.put(
            AudienceMessage(
                type="suggestion",
                loop_id="loop_001",
                payload={"text": "Suggestion 1"},
            )
        )
        inbox.put(
            AudienceMessage(
                type="suggestion",
                loop_id="loop_001",
                payload={"text": "Suggestion 2"},
            )
        )

        summary = inbox.get_summary()
        assert summary["suggestions"] == 2

    def test_get_summary_loop_filter(self):
        """Test get_summary filters by loop_id."""
        from aragora.server.stream.emitter import AudienceInbox

        inbox = AudienceInbox()

        inbox.put(
            AudienceMessage(
                type="vote",
                loop_id="loop_001",
                payload={"choice": "A"},
            )
        )
        inbox.put(
            AudienceMessage(
                type="vote",
                loop_id="loop_002",
                payload={"choice": "B"},
            )
        )

        summary = inbox.get_summary(loop_id="loop_001")
        assert summary["votes"]["A"] == 1
        assert "B" not in summary["votes"]

    def test_get_summary_histograms(self):
        """Test get_summary includes intensity histograms."""
        from aragora.server.stream.emitter import AudienceInbox

        inbox = AudienceInbox()

        inbox.put(
            AudienceMessage(
                type="vote",
                loop_id="loop_001",
                payload={"choice": "A", "intensity": 5},
            )
        )
        inbox.put(
            AudienceMessage(
                type="vote",
                loop_id="loop_001",
                payload={"choice": "A", "intensity": 10},
            )
        )

        summary = inbox.get_summary()

        assert "histograms" in summary
        assert summary["histograms"]["A"][5] == 1
        assert summary["histograms"]["A"][10] == 1

    def test_drain_suggestions(self):
        """Test drain_suggestions removes only suggestions."""
        from aragora.server.stream.emitter import AudienceInbox

        inbox = AudienceInbox()

        inbox.put(
            AudienceMessage(
                type="vote",
                loop_id="loop_001",
                payload={"choice": "A"},
            )
        )
        inbox.put(
            AudienceMessage(
                type="suggestion",
                loop_id="loop_001",
                payload={"text": "Test suggestion"},
            )
        )

        suggestions = inbox.drain_suggestions()

        assert len(suggestions) == 1
        assert suggestions[0]["text"] == "Test suggestion"

        # Vote should still be there
        messages = inbox.get_all()
        assert len(messages) == 1
        assert messages[0].type == "vote"

    def test_drain_suggestions_loop_filter(self):
        """Test drain_suggestions respects loop_id filter."""
        from aragora.server.stream.emitter import AudienceInbox

        inbox = AudienceInbox()

        inbox.put(
            AudienceMessage(
                type="suggestion",
                loop_id="loop_001",
                payload={"text": "Loop 1"},
            )
        )
        inbox.put(
            AudienceMessage(
                type="suggestion",
                loop_id="loop_002",
                payload={"text": "Loop 2"},
            )
        )

        suggestions = inbox.drain_suggestions(loop_id="loop_001")

        assert len(suggestions) == 1
        assert suggestions[0]["text"] == "Loop 1"

        # Loop 2 suggestion should still be there
        remaining = inbox.get_all()
        assert len(remaining) == 1
        assert remaining[0].payload["text"] == "Loop 2"


class TestSyncEventEmitter:
    """Test SyncEventEmitter class."""

    def test_emit_and_drain(self):
        """Test basic emit and drain."""
        from aragora.server.stream.emitter import SyncEventEmitter

        emitter = SyncEventEmitter(loop_id="loop_001")

        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            data={"topic": "Test"},
        )
        emitter.emit(event)

        events = emitter.drain()
        assert len(events) == 1
        assert events[0].type == StreamEventType.DEBATE_START
        assert events[0].loop_id == "loop_001"

    def test_emit_sync_adapts_legacy_trickster_event(self):
        """Legacy debate emissions are converted without crashing the stream path."""
        from aragora.server.stream.emitter import SyncEventEmitter

        emitter = SyncEventEmitter()

        emitter.emit_sync(
            event_type="trickster_intervention",
            debate_id="debate-123",
            correlation_id="correlation-456",
            agent="trickster",
            round=2,
            challenge="Surface independent evidence",
        )

        events = emitter.drain()
        assert len(events) == 1
        event = events[0]
        assert event.type == StreamEventType.TRICKSTER_INTERVENTION
        assert event.loop_id == "debate-123"
        assert event.correlation_id == "correlation-456"
        assert event.agent == "trickster"
        assert event.round == 2
        assert event.data == {
            "agent": "trickster",
            "round": 2,
            "challenge": "Surface independent evidence",
        }

    def test_emit_sync_supports_early_termination_event(self):
        from aragora.server.stream.emitter import SyncEventEmitter

        emitter = SyncEventEmitter()

        emitter.emit_sync(
            event_type="debate_early_terminated",
            debate_id="debate-123",
            round_num=1,
            total_rounds=3,
        )

        [event] = emitter.drain()
        assert event.type == StreamEventType.DEBATE_EARLY_TERMINATED
        assert event.round == 1
        assert event.data == {"round_num": 1, "total_rounds": 3}

    def test_emit_sync_drops_unknown_event_type_with_warning(self, caplog):
        from aragora.server.stream.emitter import SyncEventEmitter

        emitter = SyncEventEmitter()

        with caplog.at_level("WARNING"):
            emitter.emit_sync(event_type="not_registered", debate_id="debate-123")

        assert emitter.drain() == []
        assert "Unknown event type 'not_registered'; event dropped" in caplog.text

    def test_sequence_numbers(self):
        """Test sequence numbers are assigned."""
        from aragora.server.stream.emitter import SyncEventEmitter

        emitter = SyncEventEmitter()

        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_START, data={}))
        emitter.emit(StreamEvent(type=StreamEventType.ROUND_START, data={}))
        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_END, data={}))

        events = emitter.drain()

        assert events[0].seq == 1
        assert events[1].seq == 2
        assert events[2].seq == 3

    def test_agent_sequence_numbers(self):
        """Test per-agent sequence numbers."""
        from aragora.server.stream.emitter import SyncEventEmitter

        emitter = SyncEventEmitter()

        emitter.emit(StreamEvent(type=StreamEventType.AGENT_MESSAGE, data={}, agent="claude"))
        emitter.emit(StreamEvent(type=StreamEventType.AGENT_MESSAGE, data={}, agent="gpt-4"))
        emitter.emit(StreamEvent(type=StreamEventType.AGENT_MESSAGE, data={}, agent="claude"))

        events = emitter.drain()

        assert events[0].agent_seq == 1  # claude #1
        assert events[1].agent_seq == 1  # gpt-4 #1
        assert events[2].agent_seq == 2  # claude #2

    def test_reset_sequences(self):
        """Test sequence reset."""
        from aragora.server.stream.emitter import SyncEventEmitter

        emitter = SyncEventEmitter()

        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_START, data={}))
        emitter.drain()

        emitter.reset_sequences()

        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_START, data={}))
        events = emitter.drain()

        assert events[0].seq == 1

    def test_set_loop_id(self):
        """Test setting loop_id."""
        from aragora.server.stream.emitter import SyncEventEmitter

        emitter = SyncEventEmitter()
        emitter.set_loop_id("loop_002")

        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_START, data={}))
        events = emitter.drain()

        assert events[0].loop_id == "loop_002"

    def test_subscriber_callback(self):
        """Test subscriber receives events."""
        from aragora.server.stream.emitter import SyncEventEmitter

        emitter = SyncEventEmitter()
        received = []

        def callback(event: StreamEvent):
            received.append(event)

        emitter.subscribe(callback)

        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_START, data={}))

        assert len(received) == 1
        assert received[0].type == StreamEventType.DEBATE_START

    def test_drain_batch_limit(self):
        """Test drain respects max_batch_size."""
        from aragora.server.stream.emitter import SyncEventEmitter

        emitter = SyncEventEmitter()

        for i in range(10):
            emitter.emit(StreamEvent(type=StreamEventType.HEARTBEAT, data={"i": i}))

        events = emitter.drain(max_batch_size=5)
        assert len(events) == 5

        # Remaining events
        events = emitter.drain(max_batch_size=10)
        assert len(events) == 5

    def test_queue_overflow_protection(self):
        """Test queue size limit prevents memory exhaustion."""
        from aragora.server.stream.emitter import SyncEventEmitter

        emitter = SyncEventEmitter()
        original_max = emitter.MAX_QUEUE_SIZE

        # Set a low max for testing
        emitter.MAX_QUEUE_SIZE = 10

        try:
            for i in range(20):
                emitter.emit(StreamEvent(type=StreamEventType.HEARTBEAT, data={"i": i}))

            events = emitter.drain(max_batch_size=100)

            # Should have limited to max
            assert len(events) <= 10
        finally:
            emitter.MAX_QUEUE_SIZE = original_max


class TestSyncEventEmitterConcurrency:
    """Test thread-safety of SyncEventEmitter."""

    def test_concurrent_emit(self):
        """Test concurrent emit is thread-safe."""
        from aragora.server.stream.emitter import SyncEventEmitter

        emitter = SyncEventEmitter()
        errors = []

        def emit_events(count: int):
            try:
                for i in range(count):
                    emitter.emit(StreamEvent(type=StreamEventType.HEARTBEAT, data={"i": i}))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=emit_events, args=(100,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

        # Verify sequence numbers are unique
        events = emitter.drain(max_batch_size=1000)
        seqs = [e.seq for e in events]
        assert len(seqs) == len(set(seqs))  # All unique


class TestStreamEvent:
    """Test StreamEvent dataclass."""

    def test_event_creation(self):
        """Test creating a StreamEvent."""
        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            data={"topic": "Test"},
            round=1,
            agent="claude",
        )

        assert event.type == StreamEventType.DEBATE_START
        assert event.data == {"topic": "Test"}
        assert event.round == 1
        assert event.agent == "claude"
        assert event.timestamp > 0

    def test_to_dict(self):
        """Test StreamEvent serialization."""
        event = StreamEvent(
            type=StreamEventType.AGENT_MESSAGE,
            data={"content": "Hello"},
            round=2,
            agent="gpt-4",
            loop_id="loop_001",
            seq=5,
            agent_seq=3,
        )

        d = event.to_dict()

        assert d["type"] == "agent_message"
        assert d["data"] == {"content": "Hello"}
        assert d["round"] == 2
        assert d["agent"] == "gpt-4"
        assert d["loop_id"] == "loop_001"
        assert d["seq"] == 5
        assert d["agent_seq"] == 3

    def test_to_json(self):
        """Test StreamEvent JSON serialization."""
        import json

        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            data={"topic": "Test"},
        )

        json_str = event.to_json()
        parsed = json.loads(json_str)

        assert parsed["type"] == "debate_start"
        assert parsed["data"]["topic"] == "Test"


class TestAudienceMessage:
    """Test AudienceMessage dataclass."""

    def test_message_creation(self):
        """Test creating an AudienceMessage."""
        msg = AudienceMessage(
            type="vote",
            loop_id="loop_001",
            payload={"choice": "A", "intensity": 7},
            user_id="user_123",
        )

        assert msg.type == "vote"
        assert msg.loop_id == "loop_001"
        assert msg.payload["choice"] == "A"
        assert msg.user_id == "user_123"
        assert msg.timestamp > 0

    def test_default_timestamp(self):
        """Test automatic timestamp generation."""
        before = time.time()
        msg = AudienceMessage(type="suggestion", loop_id="loop_001", payload={})
        after = time.time()

        assert before <= msg.timestamp <= after
