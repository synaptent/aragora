"""
Tests for event emitter and audience participation classes.

Tests cover:
- normalize_intensity: Input validation and clamping
- TokenBucket: Rate limiting with burst and refill
- AudienceInbox: Thread-safe message queuing and summarization
- SyncEventEmitter: Thread-safe event emission and sequencing

These are critical classes that bridge synchronous Arena code with async WebSocket
broadcasts, so tests focus on thread-safety, edge cases, and correctness.
"""

import queue
import threading
import time
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.stream.emitter import (
    AudienceInbox,
    SyncEventEmitter,
    TokenBucket,
    normalize_intensity,
    set_global_emitter,
)
from aragora.events.types import (
    AudienceMessage,
    StreamEvent,
    StreamEventType,
)
from aragora.storage import receipt_signing
from aragora.storage.receipt_signing import SignatureMetadata, SignedReceipt


# ===========================================================================
# Test Fixtures
# ===========================================================================


def test_receipt_verification_observer_broadcasts_receipt_id():
    """Server stream composition registers canonical receipt telemetry."""
    emitter = MagicMock()
    signed_receipt = SignedReceipt(
        receipt_data={"receipt_id": "receipt-123"},
        signature="signature",
        signature_metadata=SignatureMetadata(
            algorithm="HMAC-SHA256",
            timestamp="2026-07-12T12:00:00+00:00",
            key_id="key-123",
        ),
    )
    set_global_emitter(emitter)
    try:
        observer = receipt_signing._receipt_verification_observer
        assert observer is not None
        observer(signed_receipt, True)
    finally:
        set_global_emitter(None)

    event = emitter.emit.call_args.args[0]
    assert event.type is StreamEventType.RECEIPT_VERIFIED
    assert event.data == {"receipt_id": "receipt-123", "valid": True}


@pytest.fixture
def token_bucket() -> TokenBucket:
    """Create a token bucket with 60 tokens/min and burst of 10."""
    return TokenBucket(rate_per_minute=60.0, burst_size=10)


@pytest.fixture
def audience_inbox() -> AudienceInbox:
    """Create an audience inbox with default settings."""
    return AudienceInbox()


@pytest.fixture
def small_inbox() -> AudienceInbox:
    """Create a small audience inbox for overflow testing."""
    return AudienceInbox(max_messages=5)


@pytest.fixture
def emitter() -> SyncEventEmitter:
    """Create a SyncEventEmitter with default settings."""
    return SyncEventEmitter()


@pytest.fixture
def emitter_with_loop_id() -> SyncEventEmitter:
    """Create a SyncEventEmitter with a preset loop_id."""
    emitter = SyncEventEmitter(loop_id="test-loop-123")
    return emitter


@pytest.fixture
def vote_message() -> AudienceMessage:
    """Create a sample vote message."""
    return AudienceMessage(
        type="vote",
        loop_id="loop-1",
        payload={"choice": "option_a", "intensity": 7},
        user_id="user-1",
    )


@pytest.fixture
def suggestion_message() -> AudienceMessage:
    """Create a sample suggestion message."""
    return AudienceMessage(
        type="suggestion",
        loop_id="loop-1",
        payload={"text": "Consider environmental impact"},
        user_id="user-2",
    )


@pytest.fixture
def stream_event() -> StreamEvent:
    """Create a sample stream event."""
    return StreamEvent(
        type=StreamEventType.DEBATE_START,
        data={"task": "Test debate task", "agents": ["claude", "gpt4"]},
    )


# ===========================================================================
# Test normalize_intensity
# ===========================================================================


class TestNormalizeIntensity:
    """Tests for normalize_intensity function."""

    def test_none_returns_default(self):
        """None value returns default intensity."""
        assert normalize_intensity(None) == 5
        assert normalize_intensity(None, default=3) == 3

    def test_valid_integer(self):
        """Valid integer values are returned as-is."""
        assert normalize_intensity(7) == 7
        assert normalize_intensity(1) == 1
        assert normalize_intensity(10) == 10

    def test_valid_float_truncated(self):
        """Float values are truncated to integers."""
        assert normalize_intensity(7.8) == 7
        assert normalize_intensity(3.2) == 3

    def test_string_integer(self):
        """String integers are parsed correctly."""
        assert normalize_intensity("5") == 5
        assert normalize_intensity("10") == 10

    def test_string_float(self):
        """String floats are parsed and truncated."""
        assert normalize_intensity("7.5") == 7
        assert normalize_intensity("3.9") == 3

    def test_invalid_string_returns_default(self):
        """Invalid strings return default."""
        assert normalize_intensity("invalid") == 5
        assert normalize_intensity("abc", default=7) == 7

    def test_clamp_below_minimum(self):
        """Values below minimum are clamped."""
        assert normalize_intensity(0) == 1
        assert normalize_intensity(-5) == 1
        assert normalize_intensity(0, min_val=3) == 3

    def test_clamp_above_maximum(self):
        """Values above maximum are clamped."""
        assert normalize_intensity(15) == 10
        assert normalize_intensity(100) == 10
        assert normalize_intensity(15, max_val=8) == 8

    def test_custom_min_max(self):
        """Custom min/max values work correctly."""
        assert normalize_intensity(3, min_val=5, max_val=20) == 5
        assert normalize_intensity(25, min_val=5, max_val=20) == 20
        assert normalize_intensity(10, min_val=5, max_val=20) == 10

    def test_type_error_returns_default(self):
        """TypeError on conversion returns default."""
        assert normalize_intensity(object()) == 5
        assert normalize_intensity([], default=3) == 3


# ===========================================================================
# Test TokenBucket
# ===========================================================================


class TestTokenBucket:
    """Tests for TokenBucket rate limiter."""

    def test_initialization(self, token_bucket):
        """TokenBucket initializes with full bucket."""
        assert token_bucket.rate_per_minute == 60.0
        assert token_bucket.burst_size == 10
        assert token_bucket.tokens == 10.0  # Starts full

    def test_consume_success(self, token_bucket):
        """Consuming available tokens succeeds."""
        assert token_bucket.consume() is True
        assert token_bucket.tokens < 10

    def test_consume_multiple(self, token_bucket):
        """Consuming multiple tokens at once works."""
        assert token_bucket.consume(5) is True
        assert token_bucket.tokens < 6  # 10 - 5 + some refill

    def test_consume_all_then_fail(self, token_bucket):
        """Consuming all tokens then trying again fails."""
        # Consume all 10 tokens
        for _ in range(10):
            token_bucket.consume()

        # Next consume should fail (minimal refill time)
        assert token_bucket.consume() is False

    def test_refill_over_time(self):
        """Tokens refill over time based on rate."""
        # High rate for faster testing
        bucket = TokenBucket(rate_per_minute=6000.0, burst_size=5)

        # Consume all tokens
        for _ in range(5):
            bucket.consume()

        # Wait for refill (100 tokens/second at 6000/min)
        time.sleep(0.05)  # Should refill ~5 tokens

        # Should be able to consume again
        assert bucket.consume() is True

    def test_refill_caps_at_burst_size(self):
        """Refill doesn't exceed burst_size."""
        bucket = TokenBucket(rate_per_minute=60000.0, burst_size=5)

        # Wait longer than needed to fill
        time.sleep(0.1)
        bucket.consume()  # Trigger refill calculation

        # Tokens should not exceed burst_size
        assert bucket.tokens <= 5

    def test_thread_safety(self, token_bucket):
        """TokenBucket is thread-safe for concurrent access."""
        results = []

        def consume_tokens():
            for _ in range(5):
                results.append(token_bucket.consume())
                time.sleep(0.001)

        threads = [threading.Thread(target=consume_tokens) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Total successful consumes should be <= burst_size + refill
        successful = sum(1 for r in results if r)
        assert successful <= 15  # 10 initial + some refill

    def test_consume_zero_tokens(self, token_bucket):
        """Consuming zero tokens always succeeds."""
        assert token_bucket.consume(0) is True
        # Can do this repeatedly
        for _ in range(100):
            assert token_bucket.consume(0) is True


# ===========================================================================
# Test AudienceInbox
# ===========================================================================


class TestAudienceInbox:
    """Tests for AudienceInbox thread-safe queue."""

    def test_put_and_get_all(self, audience_inbox, vote_message):
        """put() adds message, get_all() retrieves and clears."""
        audience_inbox.put(vote_message)
        messages = audience_inbox.get_all()

        assert len(messages) == 1
        assert messages[0] == vote_message

        # Queue should be empty now
        assert audience_inbox.get_all() == []

    def test_multiple_messages(self, audience_inbox, vote_message, suggestion_message):
        """Multiple messages can be added and retrieved."""
        audience_inbox.put(vote_message)
        audience_inbox.put(suggestion_message)

        messages = audience_inbox.get_all()
        assert len(messages) == 2

    def test_overflow_drops_oldest(self, small_inbox):
        """When at capacity, oldest messages are dropped."""
        # Add 7 messages to inbox with max_messages=5
        for i in range(7):
            msg = AudienceMessage(
                type="vote",
                loop_id="loop-1",
                payload={"choice": f"option_{i}", "intensity": 5},
            )
            small_inbox.put(msg)

        messages = small_inbox.get_all()
        assert len(messages) == 5
        # Oldest (0, 1) should be dropped, we should have 2-6
        assert messages[0].payload["choice"] == "option_2"
        assert messages[-1].payload["choice"] == "option_6"

    def test_overflow_count_tracking(self, small_inbox):
        """Overflow count is tracked correctly."""
        for i in range(10):
            msg = AudienceMessage(
                type="vote",
                loop_id="loop-1",
                payload={"choice": f"option_{i}"},
            )
            small_inbox.put(msg)

        # Should have dropped 5 messages
        assert small_inbox._overflow_count == 5

    def test_get_summary_empty(self, audience_inbox):
        """Empty inbox returns zero counts."""
        summary = audience_inbox.get_summary()
        assert summary["votes"] == {}
        assert summary["suggestions"] == 0
        assert summary["total"] == 0

    def test_get_summary_votes(self, audience_inbox):
        """get_summary correctly counts votes."""
        # Add multiple votes
        for choice in ["a", "a", "b", "a"]:
            msg = AudienceMessage(
                type="vote",
                loop_id="loop-1",
                payload={"choice": choice, "intensity": 5},
            )
            audience_inbox.put(msg)

        summary = audience_inbox.get_summary()
        assert summary["votes"]["a"] == 3
        assert summary["votes"]["b"] == 1
        assert summary["suggestions"] == 0
        assert summary["total"] == 4

    def test_get_summary_suggestions(self, audience_inbox, suggestion_message):
        """get_summary correctly counts suggestions."""
        audience_inbox.put(suggestion_message)
        audience_inbox.put(suggestion_message)

        summary = audience_inbox.get_summary()
        assert summary["suggestions"] == 2

    def test_get_summary_weighted_votes(self, audience_inbox):
        """get_summary calculates weighted votes by intensity."""
        # High intensity vote
        audience_inbox.put(
            AudienceMessage(
                type="vote",
                loop_id="loop-1",
                payload={"choice": "a", "intensity": 10},
            )
        )
        # Low intensity vote
        audience_inbox.put(
            AudienceMessage(
                type="vote",
                loop_id="loop-1",
                payload={"choice": "a", "intensity": 1},
            )
        )

        summary = audience_inbox.get_summary()
        # Weighted votes should reflect intensity differences
        # Intensity 10 = 2.0 weight, intensity 1 = 0.5 weight
        assert summary["weighted_votes"]["a"] == 2.5

    def test_get_summary_histograms(self, audience_inbox):
        """get_summary builds intensity histograms per choice."""
        audience_inbox.put(
            AudienceMessage(
                type="vote",
                loop_id="loop-1",
                payload={"choice": "a", "intensity": 5},
            )
        )
        audience_inbox.put(
            AudienceMessage(
                type="vote",
                loop_id="loop-1",
                payload={"choice": "a", "intensity": 5},
            )
        )
        audience_inbox.put(
            AudienceMessage(
                type="vote",
                loop_id="loop-1",
                payload={"choice": "a", "intensity": 8},
            )
        )

        summary = audience_inbox.get_summary()
        assert summary["histograms"]["a"][5] == 2
        assert summary["histograms"]["a"][8] == 1

    def test_get_summary_conviction_distribution(self, audience_inbox):
        """get_summary tracks global conviction distribution."""
        for intensity in [3, 5, 5, 7, 10]:
            audience_inbox.put(
                AudienceMessage(
                    type="vote",
                    loop_id="loop-1",
                    payload={"choice": "a", "intensity": intensity},
                )
            )

        summary = audience_inbox.get_summary()
        dist = summary["conviction_distribution"]
        assert dist[3] == 1
        assert dist[5] == 2
        assert dist[7] == 1
        assert dist[10] == 1

    def test_get_summary_loop_id_filter(self, audience_inbox):
        """get_summary filters by loop_id when provided."""
        audience_inbox.put(
            AudienceMessage(
                type="vote",
                loop_id="loop-1",
                payload={"choice": "a", "intensity": 5},
            )
        )
        audience_inbox.put(
            AudienceMessage(
                type="vote",
                loop_id="loop-2",
                payload={"choice": "b", "intensity": 5},
            )
        )

        summary = audience_inbox.get_summary(loop_id="loop-1")
        assert "a" in summary["votes"]
        assert "b" not in summary["votes"]

    def test_get_summary_does_not_drain(self, audience_inbox, vote_message):
        """get_summary does not remove messages from inbox."""
        audience_inbox.put(vote_message)

        # Call summary multiple times
        audience_inbox.get_summary()
        audience_inbox.get_summary()

        # Messages should still be there
        messages = audience_inbox.get_all()
        assert len(messages) == 1

    def test_drain_suggestions(self, audience_inbox, vote_message, suggestion_message):
        """drain_suggestions removes only suggestion messages."""
        audience_inbox.put(vote_message)
        audience_inbox.put(suggestion_message)
        audience_inbox.put(vote_message)

        suggestions = audience_inbox.drain_suggestions()
        assert len(suggestions) == 1
        assert suggestions[0]["text"] == "Consider environmental impact"

        # Votes should remain
        remaining = audience_inbox.get_all()
        assert len(remaining) == 2
        assert all(m.type == "vote" for m in remaining)

    def test_drain_suggestions_loop_id_filter(self, audience_inbox):
        """drain_suggestions filters by loop_id."""
        audience_inbox.put(
            AudienceMessage(
                type="suggestion",
                loop_id="loop-1",
                payload={"text": "Suggestion 1"},
            )
        )
        audience_inbox.put(
            AudienceMessage(
                type="suggestion",
                loop_id="loop-2",
                payload={"text": "Suggestion 2"},
            )
        )

        suggestions = audience_inbox.drain_suggestions(loop_id="loop-1")
        assert len(suggestions) == 1
        assert suggestions[0]["text"] == "Suggestion 1"

        # loop-2 suggestion should remain
        remaining = audience_inbox.get_all()
        assert len(remaining) == 1
        assert remaining[0].loop_id == "loop-2"

    def test_peek_suggestions_does_not_drain(self, audience_inbox, suggestion_message):
        """peek_suggestions returns suggestions without removing them."""
        audience_inbox.put(suggestion_message)

        suggestions = audience_inbox.peek_suggestions()
        assert len(suggestions) == 1
        assert suggestions[0]["text"] == "Consider environmental impact"

        remaining = audience_inbox.get_all()
        assert len(remaining) == 1
        assert remaining[0].type == "suggestion"

    def test_thread_safety_put(self, audience_inbox):
        """AudienceInbox.put() is thread-safe."""

        def add_messages():
            for i in range(100):
                msg = AudienceMessage(
                    type="vote",
                    loop_id="loop-1",
                    payload={"choice": f"option_{i}"},
                )
                audience_inbox.put(msg)

        threads = [threading.Thread(target=add_messages) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have all messages (up to max)
        messages = audience_inbox.get_all()
        assert len(messages) <= AudienceInbox.MAX_MESSAGES

    def test_missing_choice_in_vote(self, audience_inbox):
        """Vote without choice defaults to 'unknown'."""
        audience_inbox.put(
            AudienceMessage(
                type="vote",
                loop_id="loop-1",
                payload={"intensity": 5},  # No choice
            )
        )

        summary = audience_inbox.get_summary()
        assert summary["votes"]["unknown"] == 1


# ===========================================================================
# Test SyncEventEmitter
# ===========================================================================


class TestSyncEventEmitter:
    """Tests for SyncEventEmitter thread-safe event queue."""

    def test_initialization(self, emitter):
        """SyncEventEmitter initializes with empty queue."""
        events = emitter.drain()
        assert events == []

    def test_initialization_with_loop_id(self, emitter_with_loop_id):
        """SyncEventEmitter can be initialized with loop_id."""
        assert emitter_with_loop_id._loop_id == "test-loop-123"

    def test_set_loop_id(self, emitter):
        """set_loop_id updates the default loop_id."""
        emitter.set_loop_id("new-loop-456")
        assert emitter._loop_id == "new-loop-456"

    def test_emit_basic(self, emitter, stream_event):
        """emit() adds event to queue."""
        emitter.emit(stream_event)
        events = emitter.drain()

        assert len(events) == 1
        assert events[0].type == StreamEventType.DEBATE_START

    def test_emit_assigns_loop_id(self, emitter_with_loop_id):
        """emit() assigns loop_id to events without one."""
        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            data={"task": "Test"},
        )
        emitter_with_loop_id.emit(event)

        events = emitter_with_loop_id.drain()
        assert events[0].loop_id == "test-loop-123"

    def test_emit_preserves_existing_loop_id(self, emitter_with_loop_id):
        """emit() does not override existing loop_id."""
        event = StreamEvent(
            type=StreamEventType.DEBATE_START,
            data={"task": "Test"},
            loop_id="existing-loop",
        )
        emitter_with_loop_id.emit(event)

        events = emitter_with_loop_id.drain()
        assert events[0].loop_id == "existing-loop"

    def test_emit_assigns_sequence_numbers(self, emitter):
        """emit() assigns global and agent sequence numbers."""
        event1 = StreamEvent(
            type=StreamEventType.AGENT_MESSAGE,
            data={"content": "Hello"},
            agent="claude",
        )
        event2 = StreamEvent(
            type=StreamEventType.AGENT_MESSAGE,
            data={"content": "World"},
            agent="claude",
        )

        emitter.emit(event1)
        emitter.emit(event2)

        events = emitter.drain()
        assert events[0].seq == 1
        assert events[0].agent_seq == 1
        assert events[1].seq == 2
        assert events[1].agent_seq == 2

    def test_emit_per_agent_sequences(self, emitter):
        """emit() tracks separate sequences per agent."""
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_MESSAGE,
                data={},
                agent="claude",
            )
        )
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_MESSAGE,
                data={},
                agent="gpt4",
            )
        )
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_MESSAGE,
                data={},
                agent="claude",
            )
        )

        events = emitter.drain()
        # Global seq should be 1, 2, 3
        assert events[0].seq == 1
        assert events[1].seq == 2
        assert events[2].seq == 3
        # Agent seq should be 1, 1, 2 (claude, gpt4, claude)
        assert events[0].agent_seq == 1  # claude's first
        assert events[1].agent_seq == 1  # gpt4's first
        assert events[2].agent_seq == 2  # claude's second

    def test_reset_sequences(self, emitter):
        """reset_sequences() clears all sequence counters."""
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_MESSAGE,
                data={},
                agent="claude",
            )
        )
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_MESSAGE,
                data={},
                agent="gpt4",
            )
        )

        emitter.reset_sequences()

        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_MESSAGE,
                data={},
                agent="claude",
            )
        )

        events = emitter.drain()
        # After reset, sequence should restart at 1
        assert events[-1].seq == 1
        assert events[-1].agent_seq == 1

    def test_drain_batch_limit(self, emitter):
        """drain() respects max_batch_size."""
        for i in range(50):
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.HEARTBEAT,
                    data={"i": i},
                )
            )

        # Drain with limit
        events = emitter.drain(max_batch_size=20)
        assert len(events) == 20

        # Remaining events still in queue
        remaining = emitter.drain(max_batch_size=100)
        assert len(remaining) == 30

    def test_drain_non_blocking(self, emitter):
        """drain() returns immediately when queue is empty."""
        start = time.time()
        events = emitter.drain()
        elapsed = time.time() - start

        assert events == []
        assert elapsed < 0.1  # Should not block

    def test_subscribe_callback(self, emitter):
        """subscribe() registers callback for immediate notification."""
        received_events = []

        def callback(event: StreamEvent):
            received_events.append(event)

        emitter.subscribe(callback)
        emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={"task": "Test"},
            )
        )

        # Callback should have been called synchronously
        assert len(received_events) == 1

    def test_subscribe_multiple_callbacks(self, emitter):
        """Multiple subscribers all receive events."""
        results1 = []
        results2 = []

        emitter.subscribe(lambda e: results1.append(e))
        emitter.subscribe(lambda e: results2.append(e))

        emitter.emit(StreamEvent(type=StreamEventType.HEARTBEAT, data={}))

        assert len(results1) == 1
        assert len(results2) == 1

    def test_subscribe_error_handling(self, emitter):
        """Subscriber errors don't prevent other subscribers."""
        results = []

        def bad_callback(event):
            raise ValueError("Test error")

        def good_callback(event):
            results.append(event)

        emitter.subscribe(bad_callback)
        emitter.subscribe(good_callback)

        # Should not raise, and good_callback should still run
        emitter.emit(StreamEvent(type=StreamEventType.HEARTBEAT, data={}))
        assert len(results) == 1

    def test_queue_overflow_drops_oldest(self, emitter):
        """Queue overflow drops oldest events."""
        # Override MAX_QUEUE_SIZE for testing
        original_max = emitter.MAX_QUEUE_SIZE
        emitter.MAX_QUEUE_SIZE = 10

        try:
            for i in range(15):
                emitter.emit(
                    StreamEvent(
                        type=StreamEventType.HEARTBEAT,
                        data={"i": i},
                    )
                )

            events = emitter.drain()
            # Should have latest 10 events (5-14)
            assert len(events) == 10
            assert events[0].data["i"] == 5
            assert events[-1].data["i"] == 14
        finally:
            emitter.MAX_QUEUE_SIZE = original_max

    def test_overflow_count_tracking(self, emitter):
        """Overflow count is tracked."""
        original_max = emitter.MAX_QUEUE_SIZE
        emitter.MAX_QUEUE_SIZE = 5

        try:
            for i in range(10):
                emitter.emit(
                    StreamEvent(
                        type=StreamEventType.HEARTBEAT,
                        data={},
                    )
                )

            assert emitter._overflow_count == 5
        finally:
            emitter.MAX_QUEUE_SIZE = original_max

    def test_thread_safety_emit(self, emitter):
        """emit() is thread-safe for concurrent calls."""

        def emit_events():
            for i in range(100):
                emitter.emit(
                    StreamEvent(
                        type=StreamEventType.HEARTBEAT,
                        data={"thread": threading.current_thread().name, "i": i},
                    )
                )

        threads = [threading.Thread(target=emit_events) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        events = emitter.drain(max_batch_size=1000)
        # All events should have sequential global seq numbers
        seqs = [e.seq for e in events]
        assert seqs == sorted(seqs)  # Monotonically increasing

    def test_token_event_without_task_id_logs_warning(self, emitter, caplog):
        """TOKEN events without task_id log a warning."""
        event = StreamEvent(
            type=StreamEventType.TOKEN_DELTA,
            data={"token": "hello"},
            agent="claude",
            task_id="",  # Empty task_id
        )

        with caplog.at_level("WARNING"):
            emitter.emit(event)

        # Warning should have been logged
        assert any("empty task_id" in record.message.lower() for record in caplog.records)


# ===========================================================================
# Test SyncEventEmitter.broadcast_event with TelemetryConfig
# ===========================================================================


class TestSyncEventEmitterBroadcast:
    """Tests for broadcast_event with telemetry configuration."""

    @pytest.fixture
    def mock_telemetry_config(self):
        """Create a mock TelemetryConfig."""
        config = MagicMock()
        config.is_silent.return_value = False
        config.is_diagnostic.return_value = False
        config.should_redact.return_value = False
        return config

    def test_broadcast_event_basic(self, emitter):
        """broadcast_event emits event without telemetry controls."""
        result = emitter.broadcast_event(
            event_type=StreamEventType.DEBATE_START,
            data={"task": "Test"},
            agent="claude",
            round_num=1,
        )

        assert result is True
        events = emitter.drain()
        assert len(events) == 1
        assert events[0].type == StreamEventType.DEBATE_START

    def test_broadcast_event_silent_mode(self, emitter, mock_telemetry_config):
        """broadcast_event suppresses events in silent mode."""
        mock_telemetry_config.is_silent.return_value = True

        with patch("aragora.debate.telemetry_config.TelemetryConfig.get_instance") as mock_get:
            mock_get.return_value = mock_telemetry_config

            result = emitter.broadcast_event(
                event_type=StreamEventType.TELEMETRY_THOUGHT,
                data={"thought": "I think..."},
            )

        assert result is False
        events = emitter.drain()
        assert len(events) == 0

    def test_broadcast_event_diagnostic_mode_telemetry_event(self, emitter, mock_telemetry_config):
        """broadcast_event logs but doesn't broadcast telemetry events in diagnostic mode."""
        mock_telemetry_config.is_silent.return_value = False
        mock_telemetry_config.is_diagnostic.return_value = True

        with patch("aragora.debate.telemetry_config.TelemetryConfig.get_instance") as mock_get:
            mock_get.return_value = mock_telemetry_config

            result = emitter.broadcast_event(
                event_type=StreamEventType.TELEMETRY_THOUGHT,
                data={"thought": "Test thought"},
            )

        assert result is False
        events = emitter.drain()
        assert len(events) == 0

    def test_broadcast_event_controlled_mode_with_redaction(self, emitter, mock_telemetry_config):
        """broadcast_event applies redaction in controlled mode."""
        mock_telemetry_config.is_silent.return_value = False
        mock_telemetry_config.is_diagnostic.return_value = False
        mock_telemetry_config.should_redact.return_value = True

        def redactor(data: dict) -> dict:
            return {"thought": "[REDACTED]"}

        with patch("aragora.debate.telemetry_config.TelemetryConfig.get_instance") as mock_get:
            mock_get.return_value = mock_telemetry_config

            result = emitter.broadcast_event(
                event_type=StreamEventType.TELEMETRY_THOUGHT,
                data={"thought": "Secret thought"},
                agent="claude",
                redactor=redactor,
            )

        assert result is True
        events = emitter.drain()
        # Should have redaction notification + redacted event
        assert len(events) == 2
        # First should be redaction notification
        redaction_event = events[0]
        assert redaction_event.type == StreamEventType.TELEMETRY_REDACTION

    def test_broadcast_event_redactor_failure_suppresses(self, emitter, mock_telemetry_config):
        """broadcast_event suppresses event on redaction failure for security."""
        mock_telemetry_config.is_silent.return_value = False
        mock_telemetry_config.is_diagnostic.return_value = False
        mock_telemetry_config.should_redact.return_value = True

        def bad_redactor(data: dict) -> dict:
            raise ValueError("Redaction failed")

        with patch("aragora.debate.telemetry_config.TelemetryConfig.get_instance") as mock_get:
            mock_get.return_value = mock_telemetry_config

            result = emitter.broadcast_event(
                event_type=StreamEventType.TELEMETRY_THOUGHT,
                data={"thought": "Secret"},
                redactor=bad_redactor,
            )

        assert result is False
        events = emitter.drain()
        assert len(events) == 0

    def test_broadcast_event_spectacle_mode_no_redaction(self, emitter, mock_telemetry_config):
        """broadcast_event doesn't redact in spectacle mode."""
        mock_telemetry_config.is_silent.return_value = False
        mock_telemetry_config.is_diagnostic.return_value = False
        mock_telemetry_config.should_redact.return_value = False

        def redactor(data: dict) -> dict:
            return {"thought": "[REDACTED]"}

        with patch("aragora.debate.telemetry_config.TelemetryConfig.get_instance") as mock_get:
            mock_get.return_value = mock_telemetry_config

            result = emitter.broadcast_event(
                event_type=StreamEventType.TELEMETRY_THOUGHT,
                data={"thought": "Full transparency"},
                redactor=redactor,
            )

        assert result is True
        events = emitter.drain()
        assert len(events) == 1
        assert events[0].data["thought"] == "Full transparency"

    def test_broadcast_event_non_telemetry_always_emits(self, emitter, mock_telemetry_config):
        """Non-telemetry events are always emitted (except in silent mode)."""
        mock_telemetry_config.is_silent.return_value = False
        mock_telemetry_config.is_diagnostic.return_value = True

        with patch("aragora.debate.telemetry_config.TelemetryConfig.get_instance") as mock_get:
            mock_get.return_value = mock_telemetry_config

            result = emitter.broadcast_event(
                event_type=StreamEventType.DEBATE_START,  # Not a telemetry_ event
                data={"task": "Test"},
            )

        assert result is True
        events = emitter.drain()
        assert len(events) == 1

    def test_broadcast_event_import_error_fallback(self, emitter):
        """broadcast_event emits without telemetry controls when TelemetryConfig unavailable."""
        # Mock the import inside broadcast_event to raise ImportError
        import sys

        # Temporarily remove the module from cache if present
        telemetry_module = "aragora.debate.telemetry_config"
        original_module = sys.modules.get(telemetry_module)

        try:
            # Remove the module from cache
            if telemetry_module in sys.modules:
                del sys.modules[telemetry_module]

            # Create a mock that raises ImportError when imported
            with patch.dict(sys.modules, {telemetry_module: None}):
                # The import inside broadcast_event will fail
                result = emitter.broadcast_event(
                    event_type=StreamEventType.DEBATE_START,
                    data={"task": "Test"},
                )

            # Should still succeed with fallback behavior
            assert result is True
        finally:
            # Restore original module
            if original_module is not None:
                sys.modules[telemetry_module] = original_module

    def test_broadcast_event_error_handling(self, emitter):
        """broadcast_event handles exceptions gracefully."""
        # Create an event type that will trigger an error
        with patch.object(emitter, "emit", side_effect=RuntimeError("Test error")):
            result = emitter.broadcast_event(
                event_type=StreamEventType.DEBATE_START,
                data={"task": "Test"},
            )

        assert result is False


# ===========================================================================
# Test Integration Scenarios
# ===========================================================================


class TestEmitterIntegration:
    """Integration tests for emitter components working together."""

    def test_debate_lifecycle_events(self, emitter):
        """Test emitting a complete debate lifecycle."""
        emitter.set_loop_id("debate-1")

        # Start debate
        emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={"task": "Should we use Python or Rust?", "agents": ["claude", "gpt4"]},
            )
        )

        # Round 1
        emitter.emit(
            StreamEvent(
                type=StreamEventType.ROUND_START,
                data={},
                round=1,
            )
        )

        # Agent messages
        for agent in ["claude", "gpt4"]:
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.AGENT_MESSAGE,
                    data={"content": f"{agent}'s argument"},
                    agent=agent,
                    round=1,
                )
            )

        # Consensus
        emitter.emit(
            StreamEvent(
                type=StreamEventType.CONSENSUS,
                data={"reached": True, "answer": "Use both!"},
            )
        )

        # End
        emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_END,
                data={"duration": 30.5},
            )
        )

        events = emitter.drain()
        assert len(events) == 6

        # All should have loop_id
        for event in events:
            assert event.loop_id == "debate-1"

        # Check sequence numbers
        for i, event in enumerate(events, 1):
            assert event.seq == i

    def test_concurrent_agent_token_streams(self, emitter):
        """Test concurrent token streams from multiple agents."""
        emitter.set_loop_id("stream-test")

        def stream_tokens(agent: str, tokens: list[str], task_id: str):
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.TOKEN_START,
                    data={},
                    agent=agent,
                    task_id=task_id,
                )
            )
            for token in tokens:
                emitter.emit(
                    StreamEvent(
                        type=StreamEventType.TOKEN_DELTA,
                        data={"token": token},
                        agent=agent,
                        task_id=task_id,
                    )
                )
                time.sleep(0.001)
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.TOKEN_END,
                    data={},
                    agent=agent,
                    task_id=task_id,
                )
            )

        # Start concurrent streams
        t1 = threading.Thread(
            target=stream_tokens, args=("claude", ["Hello", " ", "world"], "task-1")
        )
        t2 = threading.Thread(target=stream_tokens, args=("gpt4", ["Hi", " ", "there"], "task-2"))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        events = emitter.drain()

        # Each agent should have sequential agent_seq
        claude_events = [e for e in events if e.agent == "claude"]
        gpt4_events = [e for e in events if e.agent == "gpt4"]

        assert len(claude_events) == 5  # START + 3 DELTA + END
        assert len(gpt4_events) == 5

        # Agent sequences should be sequential within each agent
        claude_seqs = [e.agent_seq for e in claude_events]
        gpt4_seqs = [e.agent_seq for e in gpt4_events]

        assert claude_seqs == sorted(claude_seqs)
        assert gpt4_seqs == sorted(gpt4_seqs)

    def test_audience_interaction_during_debate(self, emitter, audience_inbox):
        """Test audience votes and suggestions during a debate."""
        emitter.set_loop_id("interactive-debate")

        # Simulate debate progress
        emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={"task": "Best programming language?"},
            )
        )

        # Audience votes come in
        for i in range(10):
            choice = ["python", "rust", "go"][i % 3]
            audience_inbox.put(
                AudienceMessage(
                    type="vote",
                    loop_id="interactive-debate",
                    payload={"choice": choice, "intensity": (i % 10) + 1},
                )
            )

        # Add a suggestion
        audience_inbox.put(
            AudienceMessage(
                type="suggestion",
                loop_id="interactive-debate",
                payload={"text": "Consider developer experience"},
            )
        )

        # Get summary
        summary = audience_inbox.get_summary(loop_id="interactive-debate")

        assert sum(summary["votes"].values()) == 10
        assert summary["suggestions"] == 1

        # Drain suggestions for arena to process
        suggestions = audience_inbox.drain_suggestions(loop_id="interactive-debate")
        assert len(suggestions) == 1

        # Emit audience summary event
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AUDIENCE_SUMMARY,
                data=summary,
            )
        )

        events = emitter.drain()
        audience_event = next(e for e in events if e.type == StreamEventType.AUDIENCE_SUMMARY)
        assert "python" in audience_event.data["votes"]
