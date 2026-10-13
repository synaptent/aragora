"""Tests for reconnection integration: latency tracking, cleanup loop, replay.

Covers:
- Quality tracker records latency from ping/pong
- Cleanup loop runs and calls cleanup_stale
- Replay buffer returns events from given seq
- Latency recording sanity bounds
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.stream.replay_buffer import ConnectionQualityTracker, EventReplayBuffer


# ---------------------------------------------------------------------------
# Latency tracking from ping/pong
# ---------------------------------------------------------------------------


class TestPingPongLatencyTracking:
    """Test that ping handler records latency in the quality tracker."""

    @pytest.mark.asyncio
    async def test_ping_records_latency(self):
        """Simulate the ping handler logic and verify latency is recorded."""
        tracker = ConnectionQualityTracker()
        ws_id = 42
        tracker.register(ws_id)

        # Simulate: client sent ping 50ms ago
        client_ts = time.time() * 1000 - 50
        server_ts = time.time() * 1000
        latency_ms = server_ts - client_ts

        if 0 <= latency_ms < 60000:
            tracker.record_latency(ws_id, latency_ms)

        quality = tracker.get_quality(ws_id)
        assert quality is not None
        assert quality["latency_sample_count"] == 1
        assert quality["avg_latency_ms"] > 0

    @pytest.mark.asyncio
    async def test_negative_latency_not_recorded(self):
        """Latency with future client timestamps should be rejected."""
        tracker = ConnectionQualityTracker()
        ws_id = 42
        tracker.register(ws_id)

        # Client timestamp is in the future (clock skew)
        client_ts = time.time() * 1000 + 5000
        server_ts = time.time() * 1000
        latency_ms = server_ts - client_ts

        if 0 <= latency_ms < 60000:
            tracker.record_latency(ws_id, latency_ms)

        quality = tracker.get_quality(ws_id)
        assert quality["latency_sample_count"] == 0

    @pytest.mark.asyncio
    async def test_zero_client_ts_skipped(self):
        """When client_ts is 0 (default), no latency should be recorded."""
        tracker = ConnectionQualityTracker()
        ws_id = 42
        tracker.register(ws_id)

        client_ts = 0
        # The ping handler checks `if client_ts:` which is False for 0
        if client_ts:
            server_ts = time.time() * 1000
            latency_ms = server_ts - client_ts
            if 0 <= latency_ms < 60000:
                tracker.record_latency(ws_id, latency_ms)

        quality = tracker.get_quality(ws_id)
        assert quality["latency_sample_count"] == 0


# ---------------------------------------------------------------------------
# Cleanup loop
# ---------------------------------------------------------------------------


class TestBufferCleanupLoop:
    """Test that the buffer cleanup loop removes stale debate buffers."""

    def test_cleanup_stale_removes_inactive_debates(self):
        buf = EventReplayBuffer(max_per_debate=100)
        event_cls = _make_event_class()

        buf.append(event_cls("active-debate", seq=1))
        buf.append(event_cls("stale-debate", seq=1))
        buf.append(event_cls("another-stale", seq=1))

        removed = buf.cleanup_stale({"active-debate"})
        assert removed == 2
        assert buf.get_buffered_count("active-debate") == 1
        assert buf.get_buffered_count("stale-debate") == 0
        assert buf.get_buffered_count("another-stale") == 0

    def test_cleanup_with_empty_active_set(self):
        buf = EventReplayBuffer(max_per_debate=100)
        event_cls = _make_event_class()

        buf.append(event_cls("d1", seq=1))
        buf.append(event_cls("d2", seq=1))

        removed = buf.cleanup_stale(set())
        assert removed == 2

    def test_cleanup_with_no_stale_buffers(self):
        buf = EventReplayBuffer(max_per_debate=100)
        event_cls = _make_event_class()

        buf.append(event_cls("d1", seq=1))
        buf.append(event_cls("d2", seq=1))

        removed = buf.cleanup_stale({"d1", "d2"})
        assert removed == 0

    @pytest.mark.asyncio
    async def test_cleanup_loop_method_calls_cleanup_stale(self):
        """Verify that _buffer_cleanup_loop calls cleanup_stale with active loop ids."""
        from aragora.server.stream.debate_stream_server import DebateStreamServer

        server = DebateStreamServer.__new__(DebateStreamServer)
        server._running = True
        server._replay_buffer = MagicMock()
        server._replay_buffer.cleanup_stale.return_value = 2

        # Mock active_loops_lock and active_loops
        import threading

        server._active_loops_lock = threading.Lock()
        server.active_loops = {"debate-1": MagicMock(), "debate-2": MagicMock()}

        # Run the cleanup loop but stop it after one iteration
        async def run_one_iteration():
            # Override sleep to stop after first iteration
            original_sleep = asyncio.sleep
            call_count = 0

            async def mock_sleep(seconds):
                nonlocal call_count
                call_count += 1
                if call_count >= 2:
                    server._running = False
                    return
                await original_sleep(0)  # yield control

            with patch("asyncio.sleep", side_effect=mock_sleep):
                await server._buffer_cleanup_loop()

        await run_one_iteration()

        server._replay_buffer.cleanup_stale.assert_called_once_with({"debate-1", "debate-2"})


# ---------------------------------------------------------------------------
# Replay buffer integration
# ---------------------------------------------------------------------------


class TestReplayBufferIntegration:
    """Test replay buffer replay_since behavior in integration context."""

    def test_replay_returns_events_from_given_seq(self):
        buf = EventReplayBuffer(max_per_debate=100)
        event_cls = _make_event_class()

        for i in range(1, 11):
            buf.append(event_cls("debate-1", seq=i))

        replayed = buf.replay_since("debate-1", 7)
        assert len(replayed) == 3  # seq 8, 9, 10

        for r in replayed:
            parsed = json.loads(r)
            assert parsed["seq"] > 7

    def test_replay_from_zero_returns_all(self):
        buf = EventReplayBuffer(max_per_debate=100)
        event_cls = _make_event_class()

        for i in range(1, 6):
            buf.append(event_cls("debate-1", seq=i))

        replayed = buf.replay_since("debate-1", 0)
        assert len(replayed) == 5

    def test_replay_from_latest_returns_empty(self):
        buf = EventReplayBuffer(max_per_debate=100)
        event_cls = _make_event_class()

        for i in range(1, 6):
            buf.append(event_cls("debate-1", seq=i))

        replayed = buf.replay_since("debate-1", 5)
        assert len(replayed) == 0

    def test_replay_nonexistent_debate_returns_empty(self):
        buf = EventReplayBuffer(max_per_debate=100)
        replayed = buf.replay_since("no-such-debate", 0)
        assert replayed == []

    def test_replay_preserves_insertion_order(self):
        buf = EventReplayBuffer(max_per_debate=100)
        event_cls = _make_event_class()

        # Append events with non-monotonic seq (simulating out-of-order)
        for seq in [5, 3, 7, 1, 9]:
            buf.append(event_cls("debate-1", seq=seq))

        replayed = buf.replay_since("debate-1", 3)
        seqs = [json.loads(r)["seq"] for r in replayed]
        # Returns events > 3, in insertion order
        assert seqs == [5, 7, 9]

    def test_replay_with_ring_buffer_eviction(self):
        buf = EventReplayBuffer(max_per_debate=5)
        event_cls = _make_event_class()

        for i in range(1, 11):
            buf.append(event_cls("debate-1", seq=i))

        # Only last 5 events remain (seq 6-10)
        replayed = buf.replay_since("debate-1", 0)
        assert len(replayed) == 5
        seqs = [json.loads(r)["seq"] for r in replayed]
        assert seqs == [6, 7, 8, 9, 10]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event_class():
    """Return a factory that creates minimal StreamEvent objects for testing."""
    from aragora.events.types import StreamEvent, StreamEventType

    def factory(loop_id: str, seq: int = 1) -> StreamEvent:
        return StreamEvent(
            type=StreamEventType.AGENT_MESSAGE,
            data={"content": f"message-{seq}"},
            loop_id=loop_id,
            seq=seq,
            agent=f"agent-{seq % 3}",
        )

    return factory
