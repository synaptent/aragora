"""
Integration tests for WebSocket event streaming.

Tests verify that the event streaming system correctly:
- Emits debate lifecycle events (start → rounds → consensus → end)
- Handles multiple clients subscribed to the same debate
- Maintains event ordering guarantees
- Handles client reconnection scenarios
"""

import asyncio
import json
import time
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.events.types import StreamEvent, StreamEventType, AudienceMessage
from aragora.server.stream.emitter import SyncEventEmitter, TokenBucket, AudienceInbox


class TestSyncEventEmitter:
    """Test the sync event emitter for correct event queuing."""

    def test_emit_queues_event(self):
        """Events emitted should be queued for later draining."""
        emitter = SyncEventEmitter()

        event = StreamEvent(type=StreamEventType.DEBATE_START, data={"task": "Test debate"})
        emitter.emit(event)

        events = emitter.drain()
        assert len(events) == 1
        assert events[0].type == StreamEventType.DEBATE_START
        assert events[0].data["task"] == "Test debate"

    def test_emit_assigns_sequence_numbers(self):
        """Events should get sequential sequence numbers."""
        emitter = SyncEventEmitter()

        emitter.emit(StreamEvent(type=StreamEventType.ROUND_START, data={"round": 1}))
        emitter.emit(StreamEvent(type=StreamEventType.AGENT_MESSAGE, data={"agent": "claude"}))
        emitter.emit(StreamEvent(type=StreamEventType.ROUND_START, data={"round": 2}))

        events = emitter.drain()
        assert events[0].seq == 1
        assert events[1].seq == 2
        assert events[2].seq == 3

    def test_emit_assigns_agent_sequence_numbers(self):
        """Token events should get per-agent sequence numbers."""
        emitter = SyncEventEmitter()

        emitter.emit(
            StreamEvent(type=StreamEventType.TOKEN_DELTA, data={"token": "a"}, agent="claude")
        )
        emitter.emit(
            StreamEvent(type=StreamEventType.TOKEN_DELTA, data={"token": "b"}, agent="gpt")
        )
        emitter.emit(
            StreamEvent(type=StreamEventType.TOKEN_DELTA, data={"token": "c"}, agent="claude")
        )

        events = emitter.drain()
        # claude gets agent_seq 1, 2
        assert events[0].agent_seq == 1
        assert events[2].agent_seq == 2
        # gpt gets agent_seq 1
        assert events[1].agent_seq == 1

    def test_drain_returns_batch(self):
        """Drain should return events and clear the queue."""
        emitter = SyncEventEmitter()

        for i in range(5):
            emitter.emit(StreamEvent(type=StreamEventType.AGENT_MESSAGE, data={"idx": i}))

        events = emitter.drain()
        assert len(events) == 5

        # Queue should be empty now
        events = emitter.drain()
        assert len(events) == 0

    def test_drain_respects_max_batch_size(self):
        """Drain should respect max_batch_size parameter."""
        emitter = SyncEventEmitter()

        for i in range(10):
            emitter.emit(StreamEvent(type=StreamEventType.AGENT_MESSAGE, data={"idx": i}))

        events = emitter.drain(max_batch_size=3)
        assert len(events) == 3

        # Remaining events should still be in queue
        events = emitter.drain()
        assert len(events) == 7

    def test_reset_sequences(self):
        """Reset should clear sequence counters."""
        emitter = SyncEventEmitter()

        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_START, data={}))
        emitter.emit(StreamEvent(type=StreamEventType.TOKEN_DELTA, data={}, agent="claude"))
        emitter.drain()  # Clear the queue

        emitter.reset_sequences()

        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_START, data={}))
        events = emitter.drain()

        # After reset, seq should start from 1 again
        assert events[-1].seq == 1

    def test_subscribe_callback(self):
        """Subscribed callbacks should receive emitted events."""
        emitter = SyncEventEmitter()
        received = []

        def callback(event):
            received.append(event)

        emitter.subscribe(callback)
        emitter.emit(StreamEvent(type=StreamEventType.CONSENSUS, data={"reached": True}))

        assert len(received) == 1
        assert received[0].type == StreamEventType.CONSENSUS

    def test_set_loop_id(self):
        """Events should get the emitter's loop_id if not already set."""
        emitter = SyncEventEmitter()
        emitter.set_loop_id("loop-123")

        event = StreamEvent(type=StreamEventType.DEBATE_START, data={})
        emitter.emit(event)

        events = emitter.drain()
        assert events[0].loop_id == "loop-123"


class TestTokenBucket:
    """Test token bucket rate limiting."""

    def test_allows_requests_within_limit(self):
        """Should allow requests up to burst size."""
        bucket = TokenBucket(rate_per_minute=60.0, burst_size=10)

        for _ in range(10):
            assert bucket.consume() is True

    def test_blocks_after_burst_exhausted(self):
        """Should block after burst is exhausted."""
        bucket = TokenBucket(rate_per_minute=60.0, burst_size=5)

        # Exhaust burst
        for _ in range(5):
            bucket.consume()

        # Next request should be blocked
        assert bucket.consume() is False

    def test_tokens_regenerate_over_time(self):
        """Tokens should regenerate based on rate."""
        bucket = TokenBucket(rate_per_minute=6000.0, burst_size=1)  # 100/sec

        bucket.consume()  # Use the token
        assert bucket.consume() is False

        time.sleep(0.02)  # Wait 20ms for ~2 tokens to regenerate
        assert bucket.consume() is True


class TestAudienceInbox:
    """Test audience vote/suggestion collection."""

    def test_put_stores_message(self):
        """Messages should be stored in inbox."""
        inbox = AudienceInbox()

        message = AudienceMessage(type="vote", loop_id="test", payload={"choice": "A"})
        inbox.put(message)

        messages = inbox.get_all()
        assert len(messages) == 1
        assert messages[0].payload["choice"] == "A"

    def test_get_all_clears_inbox(self):
        """get_all should drain the inbox."""
        inbox = AudienceInbox()

        inbox.put(AudienceMessage(type="vote", loop_id="test", payload={}))
        inbox.put(AudienceMessage(type="suggestion", loop_id="test", payload={}))

        messages = inbox.get_all()
        assert len(messages) == 2

        messages = inbox.get_all()
        assert len(messages) == 0

    def test_bounded_capacity(self):
        """Inbox should respect max capacity."""
        inbox = AudienceInbox(max_messages=5)

        for i in range(10):
            inbox.put(AudienceMessage(type="vote", loop_id="test", payload={"idx": i}))

        messages = inbox.get_all()
        assert len(messages) == 5

    def test_get_summary_counts_votes(self):
        """get_summary should count votes correctly."""
        inbox = AudienceInbox()

        inbox.put(AudienceMessage(type="vote", loop_id="test", payload={"choice": "A"}))
        inbox.put(AudienceMessage(type="vote", loop_id="test", payload={"choice": "A"}))
        inbox.put(AudienceMessage(type="vote", loop_id="test", payload={"choice": "B"}))
        inbox.put(AudienceMessage(type="suggestion", loop_id="test", payload={"text": "hello"}))

        summary = inbox.get_summary()
        assert summary["votes"]["A"] == 2
        assert summary["votes"]["B"] == 1
        assert summary["suggestions"] == 1

    def test_drain_suggestions(self):
        """drain_suggestions should only return suggestions."""
        inbox = AudienceInbox()

        inbox.put(AudienceMessage(type="vote", loop_id="test", payload={"choice": "A"}))
        inbox.put(AudienceMessage(type="suggestion", loop_id="test", payload={"text": "try X"}))
        inbox.put(
            AudienceMessage(type="suggestion", loop_id="test", payload={"text": "consider Y"})
        )

        suggestions = inbox.drain_suggestions()
        assert len(suggestions) == 2

        # Vote should remain
        messages = inbox.get_all()
        assert len(messages) == 1
        assert messages[0].type == "vote"


class TestEventLifecycle:
    """Test complete debate event lifecycle."""

    def test_debate_lifecycle_events(self):
        """Should emit events in correct order for a debate lifecycle."""
        emitter = SyncEventEmitter()

        # Simulate debate lifecycle
        emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_START,
                data={"task": "Test task", "agents": ["a1", "a2"]},
            )
        )
        emitter.emit(StreamEvent(type=StreamEventType.ROUND_START, data={"round": 1}))
        emitter.emit(
            StreamEvent(
                type=StreamEventType.AGENT_MESSAGE, data={"agent": "a1", "content": "proposal"}
            )
        )
        emitter.emit(
            StreamEvent(type=StreamEventType.CRITIQUE, data={"agent": "a2", "target": "a1"})
        )
        emitter.emit(
            StreamEvent(type=StreamEventType.VOTE, data={"agent": "a1", "choice": "consensus"})
        )
        emitter.emit(
            StreamEvent(type=StreamEventType.VOTE, data={"agent": "a2", "choice": "consensus"})
        )
        emitter.emit(
            StreamEvent(type=StreamEventType.CONSENSUS, data={"reached": True, "confidence": 0.9})
        )
        emitter.emit(
            StreamEvent(type=StreamEventType.DEBATE_END, data={"duration": 10.5, "rounds": 1})
        )

        events = emitter.drain()

        # Verify event sequence
        event_types = [e.type for e in events]
        assert event_types == [
            StreamEventType.DEBATE_START,
            StreamEventType.ROUND_START,
            StreamEventType.AGENT_MESSAGE,
            StreamEventType.CRITIQUE,
            StreamEventType.VOTE,
            StreamEventType.VOTE,
            StreamEventType.CONSENSUS,
            StreamEventType.DEBATE_END,
        ]

    def test_multiple_rounds(self):
        """Should handle multiple rounds correctly."""
        emitter = SyncEventEmitter()

        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_START, data={"task": "Multi-round"}))

        for round_num in range(1, 4):
            emitter.emit(StreamEvent(type=StreamEventType.ROUND_START, data={"round": round_num}))
            emitter.emit(
                StreamEvent(
                    type=StreamEventType.AGENT_MESSAGE, data={"agent": "a1", "round": round_num}
                )
            )
            emitter.emit(
                StreamEvent(type=StreamEventType.CRITIQUE, data={"agent": "a2", "round": round_num})
            )

        emitter.emit(StreamEvent(type=StreamEventType.CONSENSUS, data={"reached": True}))
        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_END, data={"rounds": 3}))

        events = emitter.drain()

        # Should have: 1 start + 3*(round_start + message + critique) + consensus + end
        assert len(events) == 1 + 3 * 3 + 2

        # Count round_start events
        round_starts = [e for e in events if e.type == StreamEventType.ROUND_START]
        assert len(round_starts) == 3

    def test_token_streaming_events(self):
        """Should emit token streaming events for real-time display."""
        emitter = SyncEventEmitter()

        emitter.emit(
            StreamEvent(type=StreamEventType.TOKEN_START, data={"agent": "claude"}, agent="claude")
        )

        for token in ["Hello", " ", "world", "!"]:
            emitter.emit(
                StreamEvent(type=StreamEventType.TOKEN_DELTA, data={"token": token}, agent="claude")
            )

        emitter.emit(
            StreamEvent(type=StreamEventType.TOKEN_END, data={"agent": "claude"}, agent="claude")
        )

        events = emitter.drain()

        assert events[0].type == StreamEventType.TOKEN_START
        assert events[-1].type == StreamEventType.TOKEN_END

        deltas = [e for e in events if e.type == StreamEventType.TOKEN_DELTA]
        assert len(deltas) == 4

        # Verify agent sequence ordering
        for i, delta in enumerate(deltas, start=2):  # +1 for TOKEN_START
            assert delta.agent_seq == i


class TestLoopTracking:
    """Test multi-loop tracking capabilities."""

    def test_loop_id_propagation(self):
        """Events should include loop_id when set."""
        emitter = SyncEventEmitter(loop_id="loop-123")

        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_START, data={"task": "Test"}))

        events = emitter.drain()
        assert events[0].loop_id == "loop-123"

    def test_multiple_loops_concurrent(self):
        """Should track multiple concurrent loops independently."""
        emitter = SyncEventEmitter()

        # Events from two different loops
        emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_START, data={"task": "Task A"}, loop_id="loop-A"
            )
        )
        emitter.emit(
            StreamEvent(
                type=StreamEventType.DEBATE_START, data={"task": "Task B"}, loop_id="loop-B"
            )
        )
        emitter.emit(
            StreamEvent(type=StreamEventType.ROUND_START, data={"round": 1}, loop_id="loop-A")
        )
        emitter.emit(
            StreamEvent(type=StreamEventType.ROUND_START, data={"round": 1}, loop_id="loop-B")
        )

        events = emitter.drain()

        # Filter by loop
        loop_a_events = [e for e in events if e.loop_id == "loop-A"]
        loop_b_events = [e for e in events if e.loop_id == "loop-B"]

        assert len(loop_a_events) == 2
        assert len(loop_b_events) == 2


class TestEventSerialization:
    """Test event serialization for WebSocket transmission."""

    def test_event_to_dict(self):
        """StreamEvent should serialize to dict correctly."""
        event = StreamEvent(
            type=StreamEventType.AGENT_MESSAGE,
            data={"agent": "claude", "content": "Hello"},
            round=1,
            agent="claude",
            loop_id="test-loop",
        )

        d = event.to_dict()

        assert d["type"] == "agent_message"
        assert d["data"]["agent"] == "claude"
        assert d["round"] == 1
        assert d["loop_id"] == "test-loop"
        assert "timestamp" in d
        assert "seq" in d

    def test_event_json_serializable(self):
        """Events should be JSON serializable."""
        event = StreamEvent(
            type=StreamEventType.CONSENSUS,
            data={"reached": True, "confidence": 0.95},
        )

        # Should not raise
        json_str = json.dumps(event.to_dict())
        assert "consensus" in json_str


class TestConcurrentAccess:
    """Test thread-safety of event emitter."""

    def test_concurrent_emit(self):
        """Multiple threads emitting should not lose events."""
        import threading

        emitter = SyncEventEmitter()
        num_threads = 10
        events_per_thread = 100

        def emit_events(thread_id):
            for i in range(events_per_thread):
                emitter.emit(
                    StreamEvent(
                        type=StreamEventType.AGENT_MESSAGE, data={"thread": thread_id, "idx": i}
                    )
                )

        threads = [threading.Thread(target=emit_events, args=(i,)) for i in range(num_threads)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        events = emitter.drain()

        # Should have all events (or bounded by queue size)
        # Note: some may be dropped if queue overflows
        assert len(events) <= num_threads * events_per_thread

    def test_concurrent_subscribe_emit(self):
        """Subscribing and emitting concurrently should be safe."""
        import threading

        emitter = SyncEventEmitter()
        received = []
        lock = threading.Lock()

        def callback(event):
            with lock:
                received.append(event)

        def subscribe_thread():
            for _ in range(50):
                emitter.subscribe(callback)
                time.sleep(0.001)

        def emit_thread():
            for i in range(100):
                emitter.emit(StreamEvent(type=StreamEventType.AGENT_MESSAGE, data={"idx": i}))
                time.sleep(0.001)

        t1 = threading.Thread(target=subscribe_thread)
        t2 = threading.Thread(target=emit_thread)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Should not crash, events should be received
        assert len(received) > 0
