"""
Persistent delivery tracking for the notification system.

Provides a DeliveryLogEntry dataclass and an abstract DeliveryLogStore
interface with an in-memory default implementation.  Designed to be
swapped for a database-backed store without changing caller code.

Usage:
    from aragora.notifications.delivery_log import (
        DeliveryLogEntry,
        DeliveryLogStore,
        InMemoryDeliveryLogStore,
        get_delivery_log_store,
    )

    store = get_delivery_log_store()
    await store.log(entry)
    entries = await store.get_by_notification(notification_id)
    analytics = await store.get_analytics(since=time.time() - 3600)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

__all__ = [
    "DeliveryLogEntry",
    "DeliveryLogStore",
    "InMemoryDeliveryLogStore",
    "get_delivery_log_store",
    "set_delivery_log_store",
]


@dataclass
class DeliveryLogEntry:
    """A single delivery attempt record."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    notification_id: str = ""
    channel: str = ""  # slack, email, webhook, in_app
    recipient: str = ""
    status: str = "sent"  # sent, delivered, failed, retried, bounced
    timestamp: float = field(default_factory=time.time)
    external_id: str = ""  # message ID from provider
    error: str = ""
    retry_count: int = 0
    latency_ms: float = 0.0


class DeliveryLogStore(ABC):
    """Abstract interface for delivery log persistence."""

    @abstractmethod
    async def log(self, entry: DeliveryLogEntry) -> None:
        """Record a delivery log entry."""
        ...

    @abstractmethod
    async def get_by_notification(self, notification_id: str) -> list[DeliveryLogEntry]:
        """Retrieve all delivery entries for a given notification."""
        ...

    @abstractmethod
    async def get_analytics(self, since: float | None = None) -> dict:
        """Return aggregate analytics over delivery entries.

        Returns a dict with keys: ``success_count``, ``failure_count``,
        ``avg_latency_ms``, ``by_channel``.
        """
        ...

    @abstractmethod
    async def get_recent(self, limit: int = 50) -> list[DeliveryLogEntry]:
        """Return the most recent delivery entries (newest first)."""
        ...


class InMemoryDeliveryLogStore(DeliveryLogStore):
    """In-memory delivery log store.

    Keeps up to ``max_entries`` entries. Suitable for development and
    testing; swap for a database-backed store in production.
    """

    def __init__(self, max_entries: int = 10_000) -> None:
        self._entries: list[DeliveryLogEntry] = []
        self._max_entries = max_entries
        self._lock = threading.Lock()

    async def log(self, entry: DeliveryLogEntry) -> None:
        with self._lock:
            self._entries.append(entry)
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries :]

    async def get_by_notification(self, notification_id: str) -> list[DeliveryLogEntry]:
        with self._lock:
            return [e for e in self._entries if e.notification_id == notification_id]

    async def get_analytics(self, since: float | None = None) -> dict:
        with self._lock:
            entries = self._entries
            if since is not None:
                entries = [e for e in entries if e.timestamp >= since]

        success_count = 0
        failure_count = 0
        total_latency = 0.0
        by_channel: dict[str, dict[str, int]] = {}

        for entry in entries:
            is_success = entry.status in ("sent", "delivered")
            if is_success:
                success_count += 1
            else:
                failure_count += 1
            total_latency += entry.latency_ms

            ch = by_channel.setdefault(entry.channel, {"success": 0, "failure": 0})
            if is_success:
                ch["success"] += 1
            else:
                ch["failure"] += 1

        total = success_count + failure_count
        avg_latency_ms = (total_latency / total) if total > 0 else 0.0

        return {
            "success_count": success_count,
            "failure_count": failure_count,
            "avg_latency_ms": avg_latency_ms,
            "by_channel": by_channel,
        }

    async def get_recent(self, limit: int = 50) -> list[DeliveryLogEntry]:
        with self._lock:
            return list(reversed(self._entries[-limit:]))


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_delivery_log_store: DeliveryLogStore | None = None
_store_lock = threading.Lock()


def get_delivery_log_store() -> DeliveryLogStore:
    """Get the global delivery log store (creates InMemoryDeliveryLogStore on first call)."""
    global _delivery_log_store
    if _delivery_log_store is None:
        with _store_lock:
            if _delivery_log_store is None:
                _delivery_log_store = InMemoryDeliveryLogStore()
    return _delivery_log_store


def set_delivery_log_store(store: DeliveryLogStore) -> None:
    """Replace the global delivery log store (e.g. with a database-backed one)."""
    global _delivery_log_store
    with _store_lock:
        _delivery_log_store = store
