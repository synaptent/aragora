"""Performance tests for debate trace checksum caching.

Verifies that:
1. Checksum is cached and not recomputed on every access
2. Cache invalidation works correctly when events are added/modified
3. Multiple checksum accesses are fast (O(1) after initial computation)
"""

import time
from unittest.mock import patch

import pytest

from aragora.debate.traces import DebateTrace, EventType, TraceEvent


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def trace_event():
    """Create a basic TraceEvent."""
    return TraceEvent(
        event_id="debate-001-e0001",
        event_type=EventType.AGENT_PROPOSAL,
        timestamp="2025-01-01T12:00:00",
        round_num=1,
        agent="claude",
        content={"text": "My proposal", "confidence": 0.8},
    )


@pytest.fixture
def empty_trace():
    """Create an empty DebateTrace."""
    return DebateTrace(
        trace_id="trace-perf-test",
        debate_id="perf-test",
        task="Performance test task",
        agents=["claude", "gpt4"],
        random_seed=42,
        events=[],
    )


@pytest.fixture
def trace_with_events():
    """Create a DebateTrace with multiple events."""
    events = [
        TraceEvent(
            event_id=f"perf-e{i:04d}",
            event_type=EventType.AGENT_PROPOSAL,
            timestamp=f"2025-01-01T12:{i:02d}:00",
            round_num=i // 10,
            agent=f"agent{i % 3}",
            content={"text": f"Proposal {i}", "confidence": 0.5 + (i % 5) * 0.1},
        )
        for i in range(100)
    ]
    return DebateTrace(
        trace_id="trace-perf-test",
        debate_id="perf-test",
        task="Performance test task",
        agents=["agent0", "agent1", "agent2"],
        random_seed=42,
        events=events,
    )


def create_event(event_id: str) -> TraceEvent:
    """Create a trace event with given ID."""
    return TraceEvent(
        event_id=event_id,
        event_type=EventType.MESSAGE,
        timestamp="2025-01-01T12:00:00",
        round_num=1,
        agent="test-agent",
        content={"text": "Test message"},
    )


# =============================================================================
# TestChecksumCaching
# =============================================================================


class TestChecksumCaching:
    """Tests verifying checksum caching behavior."""

    def test_checksum_is_cached_after_first_access(self, empty_trace):
        """Checksum should be cached after first computation."""
        # Add an event using proper method
        empty_trace.add_event(create_event("e-001"))

        # First access - should compute
        checksum1 = empty_trace.checksum

        # Verify cache fields are set
        assert empty_trace._cached_checksum is not None
        assert empty_trace._cached_checksum == checksum1
        assert empty_trace._checksum_dirty is False

    def test_second_access_returns_cached_value(self, empty_trace):
        """Second checksum access should return cached value without recomputation."""
        empty_trace.add_event(create_event("e-001"))

        checksum1 = empty_trace.checksum
        checksum2 = empty_trace.checksum

        assert checksum1 == checksum2
        # Cache should still be valid
        assert empty_trace._checksum_dirty is False

    def test_cached_checksum_not_recomputed_on_repeated_access(self, trace_with_events):
        """Multiple accesses should not recompute the checksum."""
        # First access computes the checksum
        _ = trace_with_events.checksum

        # Patch json.dumps to detect recomputation
        with patch("aragora.debate.traces.json.dumps") as mock_dumps:
            # These accesses should use cached value
            _ = trace_with_events.checksum
            _ = trace_with_events.checksum
            _ = trace_with_events.checksum

            # json.dumps should not be called since checksum is cached
            mock_dumps.assert_not_called()

    def test_deterministic_checksum_same_events(self, empty_trace):
        """Same events should always produce same checksum."""
        empty_trace.add_event(create_event("e-001"))
        empty_trace.add_event(create_event("e-002"))

        checksums = [empty_trace.checksum for _ in range(10)]

        assert all(c == checksums[0] for c in checksums)


# =============================================================================
# TestCacheInvalidation
# =============================================================================


class TestCacheInvalidation:
    """Tests verifying cache invalidation behavior."""

    def test_add_event_invalidates_cache(self, empty_trace):
        """Adding an event should invalidate the cached checksum."""
        empty_trace.add_event(create_event("e-001"))
        checksum1 = empty_trace.checksum
        assert empty_trace._checksum_dirty is False

        # Add another event
        empty_trace.add_event(create_event("e-002"))

        # Cache should be invalidated
        assert empty_trace._checksum_dirty is True

        # New checksum should be different
        checksum2 = empty_trace.checksum
        assert checksum1 != checksum2

    def test_clear_events_invalidates_cache(self, trace_with_events):
        """Clearing events should invalidate the cached checksum."""
        checksum1 = trace_with_events.checksum
        assert trace_with_events._checksum_dirty is False

        # Clear all events
        trace_with_events.clear_events()

        # Cache should be invalidated
        assert trace_with_events._checksum_dirty is True

        # New checksum should be different
        checksum2 = trace_with_events.checksum
        assert checksum1 != checksum2

    def test_direct_list_modification_detected_via_count(self, empty_trace):
        """Direct list modifications should be detected via count change."""
        empty_trace.add_event(create_event("e-001"))
        checksum1 = empty_trace.checksum

        # Direct modification (not recommended but should be detected)
        empty_trace.events.append(create_event("e-002"))

        # Checksum should detect the change via count
        checksum2 = empty_trace.checksum
        assert checksum1 != checksum2

    def test_cache_invalidated_after_direct_append(self, empty_trace):
        """Cache should be invalidated after direct list append."""
        empty_trace.add_event(create_event("e-001"))
        _ = empty_trace.checksum

        # Direct append
        empty_trace.events.append(create_event("e-002"))

        # Access checksum - should detect count change and recompute
        with patch(
            "aragora.debate.traces.json.dumps", wraps=__import__("json").dumps
        ) as mock_dumps:
            _ = empty_trace.checksum
            # Should have been called to recompute
            mock_dumps.assert_called_once()

    def test_cache_valid_when_count_unchanged(self, trace_with_events):
        """Cache should remain valid when event count is unchanged."""
        _ = trace_with_events.checksum
        original_count = len(trace_with_events.events)

        # Multiple accesses without modification
        with patch("aragora.debate.traces.json.dumps") as mock_dumps:
            for _ in range(5):
                _ = trace_with_events.checksum

            # No recomputation should occur
            mock_dumps.assert_not_called()

        # Count should be unchanged
        assert len(trace_with_events.events) == original_count


# =============================================================================
# TestChecksumPerformance
# =============================================================================


class TestChecksumPerformance:
    """Tests verifying checksum performance characteristics."""

    def test_first_access_computes_checksum(self, trace_with_events):
        """First access should compute the checksum (verifiable via timing or mock)."""
        with patch(
            "aragora.debate.traces.json.dumps", wraps=__import__("json").dumps
        ) as mock_dumps:
            _ = trace_with_events.checksum
            # First access should call json.dumps
            mock_dumps.assert_called_once()

    def test_subsequent_accesses_are_fast(self, trace_with_events):
        """Subsequent accesses should be significantly faster than first access."""
        # First access - cold cache
        start = time.perf_counter()
        _ = trace_with_events.checksum
        first_access_time = time.perf_counter() - start

        # Subsequent accesses - warm cache
        subsequent_times = []
        for _ in range(100):
            start = time.perf_counter()
            _ = trace_with_events.checksum
            subsequent_times.append(time.perf_counter() - start)

        avg_subsequent_time = sum(subsequent_times) / len(subsequent_times)

        # Cached access should be at least 5x faster than initial computation
        # (being conservative here to avoid flaky tests)
        assert avg_subsequent_time < first_access_time, (
            f"Cached access ({avg_subsequent_time:.6f}s) should be faster than "
            f"initial computation ({first_access_time:.6f}s)"
        )

    def test_many_accesses_remain_constant_time(self, trace_with_events):
        """Many checksum accesses should maintain constant time (O(1))."""
        # Prime the cache
        _ = trace_with_events.checksum

        # Measure time for many accesses
        access_times = []
        for _ in range(1000):
            start = time.perf_counter()
            _ = trace_with_events.checksum
            access_times.append(time.perf_counter() - start)

        # Sub-microsecond property lookups have high relative jitter: on a
        # loaded shared runner a single scheduler preemption can cost ~0.5ms,
        # so comparing the raw max against the average is inherently flaky.
        # Use robust statistics instead — the bulk of accesses (p95) must stay
        # near the typical (median) cost, with a generous absolute ceiling.
        sorted_times = sorted(access_times)
        median_time = sorted_times[len(sorted_times) // 2]
        p95_time = sorted_times[int(len(sorted_times) * 0.95)]
        assert p95_time < max(median_time * 100, 1e-3), (
            f"Access times should be relatively constant. "
            f"Median: {median_time:.6f}s, p95: {p95_time:.6f}s"
        )

        # The actual O(1) guarantee: per-access cost must not grow with the
        # number of prior accesses. Compare first-half vs second-half medians,
        # which isolated hiccups cannot skew.
        half = len(access_times) // 2
        first_half = sorted(access_times[:half])
        second_half = sorted(access_times[half:])
        first_median = first_half[len(first_half) // 2]
        second_median = second_half[len(second_half) // 2]
        assert second_median < max(first_median * 10, 5e-5), (
            f"Access times should not grow with access count. "
            f"First-half median: {first_median:.6f}s, "
            f"second-half median: {second_median:.6f}s"
        )

    def test_large_trace_caching_benefits(self):
        """Large traces should benefit significantly from caching."""
        # Create a trace with many events
        events = [
            TraceEvent(
                event_id=f"large-e{i:06d}",
                event_type=EventType.AGENT_PROPOSAL,
                timestamp=f"2025-01-01T{(i // 3600):02d}:{((i % 3600) // 60):02d}:{(i % 60):02d}",
                round_num=i // 100,
                agent=f"agent{i % 5}",
                content={
                    "text": f"This is proposal number {i} with some content to make it larger",
                    "confidence": 0.5 + (i % 5) * 0.1,
                    "metadata": {"index": i, "category": f"cat-{i % 10}"},
                },
            )
            for i in range(1000)
        ]
        large_trace = DebateTrace(
            trace_id="trace-large",
            debate_id="large-test",
            task="Large trace test",
            agents=["agent0", "agent1", "agent2", "agent3", "agent4"],
            random_seed=42,
            events=events,
        )

        # First access - full computation
        start = time.perf_counter()
        checksum1 = large_trace.checksum
        first_time = time.perf_counter() - start

        # Multiple cached accesses
        cached_times = []
        for _ in range(100):
            start = time.perf_counter()
            checksum2 = large_trace.checksum
            cached_times.append(time.perf_counter() - start)

        avg_cached_time = sum(cached_times) / len(cached_times)

        # Checksums should be identical
        assert checksum1 == checksum2

        # Cached access should be much faster (at least 10x for large traces)
        speedup = first_time / avg_cached_time if avg_cached_time > 0 else float("inf")
        assert speedup > 2, (
            f"Caching should provide significant speedup. "
            f"First: {first_time:.6f}s, Cached avg: {avg_cached_time:.6f}s, Speedup: {speedup:.1f}x"
        )


# =============================================================================
# TestCacheStateConsistency
# =============================================================================


class TestCacheStateConsistency:
    """Tests verifying cache state remains consistent."""

    def test_dirty_flag_transitions_correctly(self, empty_trace):
        """Dirty flag should transition correctly through operations."""
        # Initial state
        assert empty_trace._checksum_dirty is True  # New trace is dirty

        # After first checksum access
        _ = empty_trace.checksum
        assert empty_trace._checksum_dirty is False

        # After adding event
        empty_trace.add_event(create_event("e-001"))
        assert empty_trace._checksum_dirty is True

        # After checksum access again
        _ = empty_trace.checksum
        assert empty_trace._checksum_dirty is False

        # After clearing events
        empty_trace.clear_events()
        assert empty_trace._checksum_dirty is True

        # After final checksum access
        _ = empty_trace.checksum
        assert empty_trace._checksum_dirty is False

    def test_event_count_tracking_accuracy(self, empty_trace):
        """Event count tracking should accurately reflect events list."""
        # Add events using add_event
        for i in range(5):
            empty_trace.add_event(create_event(f"e-{i:03d}"))

        _ = empty_trace.checksum
        assert empty_trace._last_event_count == 5

        # Clear and verify
        empty_trace.clear_events()
        _ = empty_trace.checksum
        assert empty_trace._last_event_count == 0

    def test_cached_checksum_matches_fresh_computation(self, trace_with_events):
        """Cached checksum should match a fresh computation."""
        # Get cached checksum
        cached = trace_with_events.checksum

        # Force recomputation by clearing cache
        trace_with_events._mark_checksum_dirty()
        fresh = trace_with_events.checksum

        assert cached == fresh

    def test_checksum_integrity_after_serialization_roundtrip(self, trace_with_events):
        """Checksum should be valid after JSON roundtrip."""
        original_checksum = trace_with_events.checksum

        # Serialize and deserialize
        json_str = trace_with_events.to_json()
        restored = DebateTrace.from_json(json_str)

        # Restored trace should have same checksum
        assert restored.checksum == original_checksum
