"""
Tests for the notification retry queue.

Covers enqueue/dequeue round-trips, exponential backoff calculation,
max-attempt discarding, thread safety, and queue capacity eviction.
"""

from __future__ import annotations

import threading
import time

import pytest

from aragora.notifications.retry_queue import (
    NotificationRetryQueue,
    RetryEntry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    entry_id: str = "r-1",
    notification_id: str = "n-100",
    channel: str = "slack",
    recipient: str = "#alerts",
    attempt: int = 0,
    max_attempts: int = 5,
    next_retry_at: float = 0.0,
    created_at: float | None = None,
    last_error: str = "",
) -> RetryEntry:
    return RetryEntry(
        id=entry_id,
        notification_id=notification_id,
        channel=channel,
        recipient=recipient,
        payload={"title": "Test", "message": "body"},
        attempt=attempt,
        max_attempts=max_attempts,
        next_retry_at=next_retry_at,
        created_at=created_at if created_at is not None else time.time(),
        last_error=last_error,
    )


# ===========================================================================
# Enqueue / dequeue round-trip
# ===========================================================================


class TestEnqueueDequeue:
    """Basic enqueue then dequeue_ready semantics."""

    def test_round_trip(self):
        """Enqueued entry is returned by dequeue_ready when time has passed."""
        queue = NotificationRetryQueue()
        entry = _make_entry(next_retry_at=0.0)
        queue.enqueue(entry)

        ready = queue.dequeue_ready(now=1.0)
        assert len(ready) == 1
        assert ready[0].id == "r-1"
        # Entry removed after dequeue
        assert queue.pending_count() == 0

    def test_not_ready_yet(self):
        """Entries whose next_retry_at is in the future are NOT returned."""
        queue = NotificationRetryQueue()
        entry = _make_entry(next_retry_at=100.0)
        queue.enqueue(entry)

        ready = queue.dequeue_ready(now=50.0)
        assert len(ready) == 0
        assert queue.pending_count() == 1

    def test_multiple_entries_mixed_readiness(self):
        """Only ready entries are dequeued; future entries stay."""
        queue = NotificationRetryQueue()
        queue.enqueue(_make_entry(entry_id="r-1", next_retry_at=10.0))
        queue.enqueue(_make_entry(entry_id="r-2", next_retry_at=20.0))
        queue.enqueue(_make_entry(entry_id="r-3", next_retry_at=30.0))

        ready = queue.dequeue_ready(now=25.0)
        ready_ids = {e.id for e in ready}
        assert ready_ids == {"r-1", "r-2"}
        assert queue.pending_count() == 1


# ===========================================================================
# Exponential backoff
# ===========================================================================


class TestExponentialBackoff:
    """Verify the backoff progression with a 30 s cap."""

    @pytest.mark.parametrize(
        ("attempt", "expected"),
        [
            (0, 1),
            (1, 2),
            (2, 4),
            (3, 8),
            (4, 16),
            (5, 30),  # capped
            (6, 30),  # still capped
            (10, 30),
        ],
    )
    def test_backoff_values(self, attempt: int, expected: float):
        assert NotificationRetryQueue.compute_backoff(attempt) == expected


# ===========================================================================
# Max attempts exhaustion
# ===========================================================================


class TestMaxAttempts:
    """Entry is discarded (dead-lettered) after max_attempts failures."""

    def test_discarded_after_max_attempts(self):
        queue = NotificationRetryQueue()
        entry = _make_entry(attempt=4, max_attempts=5)
        queue.enqueue(entry)

        # Dequeue and fail — attempt becomes 5 which == max_attempts
        ready = queue.dequeue_ready(now=time.time() + 1)
        assert len(ready) == 1
        queue.mark_failed(ready[0], "still broken")

        # Entry should NOT be re-enqueued
        assert queue.pending_count() == 0

    def test_not_discarded_before_max(self):
        queue = NotificationRetryQueue()
        entry = _make_entry(attempt=2, max_attempts=5)
        queue.enqueue(entry)

        ready = queue.dequeue_ready(now=time.time() + 1)
        assert len(ready) == 1
        queue.mark_failed(ready[0], "temporary error")

        # attempt is now 3, still below max 5 — re-enqueued
        assert queue.pending_count() == 1


# ===========================================================================
# mark_success
# ===========================================================================


class TestMarkSuccess:
    """mark_success removes the entry from the queue."""

    def test_removes_entry(self):
        queue = NotificationRetryQueue()
        entry = _make_entry(entry_id="r-99")
        queue.enqueue(entry)
        assert queue.pending_count() == 1

        queue.mark_success("r-99")
        assert queue.pending_count() == 0

    def test_noop_for_unknown_id(self):
        """Calling mark_success with an unknown id does not raise."""
        queue = NotificationRetryQueue()
        queue.mark_success("nonexistent")  # should not raise


# ===========================================================================
# mark_failed
# ===========================================================================


class TestMarkFailed:
    """mark_failed increments attempt and updates next_retry_at."""

    def test_increments_attempt(self):
        queue = NotificationRetryQueue()
        entry = _make_entry(attempt=1, max_attempts=5)

        before = time.time()
        queue.mark_failed(entry, "timeout")
        after = time.time()

        assert entry.attempt == 2
        assert entry.last_error == "timeout"
        # next_retry_at should be roughly now + backoff(2) = now + 4
        expected_backoff = NotificationRetryQueue.compute_backoff(2)
        assert entry.next_retry_at >= before + expected_backoff - 0.1
        assert entry.next_retry_at <= after + expected_backoff + 0.1
        # Re-enqueued
        assert queue.pending_count() == 1

    def test_error_string_preserved(self):
        queue = NotificationRetryQueue()
        entry = _make_entry(attempt=0, max_attempts=3)
        queue.mark_failed(entry, "connection refused")
        assert entry.last_error == "connection refused"


# ===========================================================================
# pending_count and get_pending
# ===========================================================================


class TestPendingInspection:
    """pending_count and get_pending for observability."""

    def test_pending_count(self):
        queue = NotificationRetryQueue()
        assert queue.pending_count() == 0

        queue.enqueue(_make_entry(entry_id="a"))
        queue.enqueue(_make_entry(entry_id="b"))
        assert queue.pending_count() == 2

    def test_get_pending_sorted(self):
        queue = NotificationRetryQueue()
        queue.enqueue(_make_entry(entry_id="late", next_retry_at=100.0))
        queue.enqueue(_make_entry(entry_id="early", next_retry_at=10.0))
        queue.enqueue(_make_entry(entry_id="mid", next_retry_at=50.0))

        pending = queue.get_pending(limit=2)
        assert len(pending) == 2
        assert pending[0].id == "early"
        assert pending[1].id == "mid"

    def test_get_pending_limit(self):
        queue = NotificationRetryQueue()
        for i in range(10):
            queue.enqueue(_make_entry(entry_id=f"r-{i}"))
        assert len(queue.get_pending(limit=3)) == 3


# ===========================================================================
# Thread safety
# ===========================================================================


class TestThreadSafety:
    """Concurrent enqueue from multiple threads must not lose entries."""

    def test_concurrent_enqueue(self):
        queue = NotificationRetryQueue(max_size=5000)
        num_threads = 8
        entries_per_thread = 100
        barrier = threading.Barrier(num_threads)

        def _worker(thread_idx: int) -> None:
            barrier.wait()
            for i in range(entries_per_thread):
                entry = _make_entry(
                    entry_id=f"t{thread_idx}-{i}",
                    notification_id=f"n-{thread_idx}-{i}",
                )
                queue.enqueue(entry)

        threads = [threading.Thread(target=_worker, args=(t,)) for t in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert queue.pending_count() == num_threads * entries_per_thread

    def test_concurrent_enqueue_and_dequeue(self):
        """Interleaved enqueue + dequeue_ready must not raise."""
        queue = NotificationRetryQueue(max_size=5000)
        errors: list[str] = []

        def _enqueuer() -> None:
            try:
                for i in range(200):
                    queue.enqueue(_make_entry(entry_id=f"eq-{i}", next_retry_at=0.0))
            except Exception as exc:  # noqa: BLE001 — test harness
                errors.append(str(exc))

        def _dequeuer() -> None:
            try:
                for _ in range(200):
                    queue.dequeue_ready(now=time.time() + 1)
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

        t1 = threading.Thread(target=_enqueuer)
        t2 = threading.Thread(target=_dequeuer)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert errors == [], f"Unexpected errors during concurrent access: {errors}"


# ===========================================================================
# Queue capacity / eviction
# ===========================================================================


class TestCapacity:
    """Queue enforces max_size by evicting the oldest entry."""

    def test_eviction_on_overflow(self):
        queue = NotificationRetryQueue(max_size=3)
        queue.enqueue(_make_entry(entry_id="a", created_at=1.0))
        queue.enqueue(_make_entry(entry_id="b", created_at=2.0))
        queue.enqueue(_make_entry(entry_id="c", created_at=3.0))

        # Adding a 4th should evict "a" (oldest)
        queue.enqueue(_make_entry(entry_id="d", created_at=4.0))

        assert queue.pending_count() == 3
        ids = {e.id for e in queue.get_pending(limit=10)}
        assert "a" not in ids
        assert ids == {"b", "c", "d"}

    def test_update_existing_entry_does_not_evict(self):
        """Re-enqueuing with the same id should update, not grow the queue."""
        queue = NotificationRetryQueue(max_size=2)
        queue.enqueue(_make_entry(entry_id="x", created_at=1.0))
        queue.enqueue(_make_entry(entry_id="y", created_at=2.0))

        # Update x — should replace, not evict
        queue.enqueue(_make_entry(entry_id="x", created_at=3.0, last_error="updated"))
        assert queue.pending_count() == 2

        pending = {e.id: e for e in queue.get_pending(limit=10)}
        assert pending["x"].created_at == 3.0
