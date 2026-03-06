"""
Notification retry queue with exponential backoff.

Provides reliable delivery for failed notifications by queuing them for
automatic retry with capped exponential backoff.  The implementation is
fully in-memory and thread-safe (no Redis required).

Usage:
    from aragora.notifications.retry_queue import (
        NotificationRetryQueue,
        RetryEntry,
    )

    queue = NotificationRetryQueue(max_size=1000)

    # Enqueue a failed delivery
    queue.enqueue(RetryEntry(
        id="r-1",
        notification_id="n-456",
        channel="slack",
        recipient="#alerts",
        payload={"title": "Critical Finding", "message": "..."},
        last_error="Connection refused",
    ))

    # Later, drain ready entries
    for entry in queue.dequeue_ready():
        result = await provider.send(...)
        if result.success:
            queue.mark_success(entry.id)
        else:
            queue.mark_failed(entry, str(result.error))
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "RetryEntry",
    "NotificationRetryQueue",
]

# Maximum backoff in seconds (30 s cap)
_MAX_BACKOFF_SECONDS = 30


@dataclass
class RetryEntry:
    """A notification delivery that failed and is queued for retry."""

    id: str
    notification_id: str
    channel: str
    recipient: str
    payload: dict[str, Any]
    attempt: int = 0
    max_attempts: int = 5
    next_retry_at: float = 0.0
    created_at: float = field(default_factory=time.time)
    last_error: str = ""


class NotificationRetryQueue:
    """Thread-safe in-memory retry queue with exponential backoff.

    Entries are held in a dict keyed by ``entry.id`` for O(1) lookup on
    mark_success / mark_failed.  ``dequeue_ready`` performs a linear scan
    which is acceptable for the expected queue sizes (capped at *max_size*).
    """

    def __init__(self, max_size: int = 1000) -> None:
        self._max_size = max_size
        self._lock = threading.Lock()
        self._entries: dict[str, RetryEntry] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, entry: RetryEntry) -> None:
        """Add a failed notification for retry.

        If the queue is already at capacity the oldest entry (by
        ``created_at``) is evicted to make room.
        """
        with self._lock:
            if len(self._entries) >= self._max_size and entry.id not in self._entries:
                self._evict_oldest()
            self._entries[entry.id] = entry
            logger.debug(
                "Enqueued retry %s for notification %s (attempt %d)",
                entry.id,
                entry.notification_id,
                entry.attempt,
            )

    def dequeue_ready(self, now: float | None = None) -> list[RetryEntry]:
        """Return all entries whose ``next_retry_at <= now``.

        Returned entries are **removed** from the queue; the caller is
        responsible for calling :meth:`mark_success` or :meth:`mark_failed`
        to re-enqueue failures.
        """
        if now is None:
            now = time.time()
        ready: list[RetryEntry] = []
        with self._lock:
            ids_to_remove: list[str] = []
            for entry_id, entry in self._entries.items():
                if entry.next_retry_at <= now:
                    ready.append(entry)
                    ids_to_remove.append(entry_id)
            for entry_id in ids_to_remove:
                del self._entries[entry_id]
        return ready

    def mark_success(self, entry_id: str) -> None:
        """Remove an entry after successful delivery."""
        with self._lock:
            removed = self._entries.pop(entry_id, None)
        if removed is not None:
            logger.debug("Retry %s succeeded, removed from queue", entry_id)

    def mark_failed(self, entry: RetryEntry, error: str) -> None:
        """Record a failed retry attempt.

        Increments the attempt counter and computes the next backoff time.
        If the entry has reached ``max_attempts`` it is discarded and a
        warning is logged.
        """
        entry.attempt += 1
        entry.last_error = error

        if entry.attempt >= entry.max_attempts:
            logger.warning(
                "Notification %s exhausted %d retry attempts; discarding (last error: %s)",
                entry.notification_id,
                entry.max_attempts,
                error,
            )
            # Do NOT re-enqueue — entry is dead-lettered.
            return

        entry.next_retry_at = time.time() + self.compute_backoff(entry.attempt)
        self.enqueue(entry)
        logger.debug(
            "Retry %s failed (attempt %d/%d), next retry at %.1f",
            entry.id,
            entry.attempt,
            entry.max_attempts,
            entry.next_retry_at,
        )

    def pending_count(self) -> int:
        """Return the number of entries currently in the queue."""
        with self._lock:
            return len(self._entries)

    def get_pending(self, limit: int = 50) -> list[RetryEntry]:
        """Return up to *limit* pending entries (sorted by next_retry_at)."""
        with self._lock:
            entries = sorted(self._entries.values(), key=lambda e: e.next_retry_at)
            return entries[:limit]

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def compute_backoff(attempt: int) -> float:
        """Exponential backoff: 1 s, 2 s, 4 s, 8 s, 16 s, 30 s, 30 s, ...

        Cap is ``_MAX_BACKOFF_SECONDS`` (30 s).
        """
        return min(2**attempt, _MAX_BACKOFF_SECONDS)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evict_oldest(self) -> None:
        """Remove the entry with the smallest ``created_at``."""
        if not self._entries:
            return
        oldest_id = min(self._entries, key=lambda k: self._entries[k].created_at)
        evicted = self._entries.pop(oldest_id)
        logger.debug(
            "Evicted oldest retry entry %s (notification %s) to stay within max_size",
            evicted.id,
            evicted.notification_id,
        )
