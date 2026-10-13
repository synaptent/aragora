"""
Batched Webhook Dispatcher.

Provides intelligent batching of webhook notifications for high-volume scenarios.
Instead of sending individual webhooks for each event, this batches events of
the same type within a configurable window.

Features:
- Configurable batch window (default: 5 seconds)
- Maximum batch size limit
- Priority events bypass batching
- Thread-safe batching
- Automatic flush on shutdown

Usage:
    from aragora.events.batch_dispatcher import get_batch_dispatcher

    dispatcher = get_batch_dispatcher()

    # Queue an event for batched delivery
    dispatcher.queue_event("slo_violation", {"operation": "km_query", ...})

    # High-priority events can bypass batching
    dispatcher.queue_event("slo_violation", data, priority=True)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Batch window in seconds
BATCH_WINDOW = float(os.environ.get("ARAGORA_WEBHOOK_BATCH_WINDOW", "5.0"))

# Maximum events per batch
MAX_BATCH_SIZE = int(os.environ.get("ARAGORA_WEBHOOK_MAX_BATCH_SIZE", "100"))

# Event types that should bypass batching (always send immediately)
PRIORITY_EVENT_TYPES = frozenset(
    os.environ.get(
        "ARAGORA_WEBHOOK_PRIORITY_EVENTS",
        "slo_violation,debate_end,consensus,gauntlet_verdict",
    ).split(",")
)

# =============================================================================
# Batch Data Structures
# =============================================================================


@dataclass
class BatchedEvent:
    """A single event in a batch."""

    event_type: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


@dataclass
class EventBatch:
    """A batch of events to be delivered together."""

    event_type: str
    events: list[BatchedEvent] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def add(self, event: BatchedEvent) -> None:
        """Add an event to the batch."""
        self.events.append(event)

    def is_full(self, max_size: int = MAX_BATCH_SIZE) -> bool:
        """Check if batch has reached maximum size."""
        return len(self.events) >= max_size

    def is_expired(self, window: float = BATCH_WINDOW) -> bool:
        """Check if batch window has expired."""
        return time.time() - self.created_at >= window

    def to_payload(self) -> dict[str, Any]:
        """Convert batch to webhook payload."""
        return {
            "event": f"{self.event_type}_batch",
            "batch_size": len(self.events),
            "window_start": self.created_at,
            "window_end": time.time(),
            "events": [
                {
                    "data": e.data,
                    "timestamp": e.timestamp,
                }
                for e in self.events
            ],
            # Summary stats for quick overview
            "summary": self._generate_summary(),
        }

    def _generate_summary(self) -> dict[str, Any]:
        """Generate summary statistics for the batch."""
        if not self.events:
            return {}

        # Count by operation (for SLO events)
        by_operation: defaultdict[str, int] = defaultdict(int)
        by_severity: defaultdict[str, int] = defaultdict(int)

        for event in self.events:
            if "operation" in event.data:
                by_operation[event.data["operation"]] += 1
            if "severity" in event.data:
                by_severity[event.data["severity"]] += 1

        return {
            "count": len(self.events),
            "by_operation": dict(by_operation) if by_operation else None,
            "by_severity": dict(by_severity) if by_severity else None,
            "first_event_at": self.events[0].timestamp,
            "last_event_at": self.events[-1].timestamp,
        }


# =============================================================================
# Batch Dispatcher
# =============================================================================


class BatchWebhookDispatcher:
    """
    Webhook dispatcher with intelligent batching.

    Events are queued and batched by type. Batches are flushed when:
    - Batch window expires (default: 5 seconds)
    - Batch reaches maximum size
    - Priority event is queued
    - Shutdown is requested
    """

    def __init__(
        self,
        batch_window: float = BATCH_WINDOW,
        max_batch_size: int = MAX_BATCH_SIZE,
        priority_events: frozenset = PRIORITY_EVENT_TYPES,
    ):
        self.batch_window = batch_window
        self.max_batch_size = max_batch_size
        self.priority_events = priority_events

        # Event batches by type
        self._batches: dict[str, EventBatch] = {}
        self._lock = threading.Lock()

        # Delivery callback
        self._deliver_callback: Callable[[str, dict], None] | None = None

        # Background flush thread
        self._shutdown = False
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            daemon=True,
            name="webhook-batch-flush",
        )
        self._flush_thread.start()

        # Stats
        self._events_queued = 0
        self._batches_sent = 0
        self._priority_sent = 0

    def set_delivery_callback(self, callback: Callable[[str, dict], None]) -> None:
        """
        Set the callback for delivering batched events.

        Args:
            callback: Function that takes (event_type, payload) and delivers
        """
        self._deliver_callback = callback

    def queue_event(
        self,
        event_type: str,
        data: dict[str, Any],
        priority: bool = False,
    ) -> None:
        """
        Queue an event for batched delivery.

        Args:
            event_type: Type of event (e.g., "slo_violation")
            data: Event data
            priority: If True, bypasses batching and sends immediately
        """
        if self._shutdown:
            return

        event = BatchedEvent(event_type=event_type, data=data)

        # Priority events bypass batching
        if priority or event_type in self.priority_events:
            self._deliver_immediate(event)
            return

        with self._lock:
            self._events_queued += 1

            # Get or create batch for this event type
            if event_type not in self._batches:
                self._batches[event_type] = EventBatch(event_type=event_type)

            batch = self._batches[event_type]
            batch.add(event)

            # Flush if batch is full
            if batch.is_full(self.max_batch_size):
                self._flush_batch(event_type)

    def _deliver_immediate(self, event: BatchedEvent) -> None:
        """Deliver a single event immediately (no batching)."""
        if not self._deliver_callback:
            return

        self._priority_sent += 1

        payload = {
            "event": event.event_type,
            "timestamp": event.timestamp,
            "data": event.data,
            "batched": False,
        }

        try:
            self._deliver_callback(event.event_type, payload)
        except (OSError, ConnectionError, RuntimeError, ValueError, TypeError) as e:
            logger.error("Failed to deliver priority event: %s", e)

    def _flush_batch(self, event_type: str) -> None:
        """Flush a batch for delivery. Must hold lock."""
        if event_type not in self._batches:
            return

        batch = self._batches.pop(event_type)
        if not batch.events:
            return

        self._batches_sent += 1

        if self._deliver_callback:
            # Import tracing lazily to avoid circular imports
            trace_webhook_batch: Callable[..., Any] | None
            try:
                from aragora.observability.tracing import (
                    trace_webhook_batch as _trace_webhook_batch,
                )
            except ImportError:
                trace_webhook_batch = None
            else:
                trace_webhook_batch = _trace_webhook_batch

            payload = batch.to_payload()
            batch_size = len(batch.events)

            if trace_webhook_batch:
                with trace_webhook_batch(event_type, batch_size) as span:
                    try:
                        self._deliver_callback(event_type, payload)
                        span.set_attribute("webhook.batch_success", True)
                    except (OSError, ConnectionError, RuntimeError, ValueError, TypeError) as e:
                        span.set_attribute("webhook.batch_success", False)
                        span.set_attribute("webhook.error", str(e)[:200])
                        logger.error("Failed to deliver batch for %s: %s", event_type, e)
            else:
                try:
                    self._deliver_callback(event_type, payload)
                except (OSError, ConnectionError, RuntimeError, ValueError, TypeError) as e:
                    logger.error("Failed to deliver batch for %s: %s", event_type, e)

    def _flush_loop(self) -> None:
        """Background thread that flushes expired batches."""
        while not self._shutdown:
            time.sleep(min(self.batch_window / 2, 1.0))

            if self._shutdown:
                break

            with self._lock:
                expired = [
                    event_type
                    for event_type, batch in self._batches.items()
                    if batch.is_expired(self.batch_window)
                ]

                for event_type in expired:
                    self._flush_batch(event_type)

    def flush_all(self) -> None:
        """Flush all pending batches immediately."""
        with self._lock:
            for event_type in list(self._batches.keys()):
                self._flush_batch(event_type)

    def get_stats(self) -> dict[str, Any]:
        """Get dispatcher statistics."""
        with self._lock:
            pending_events = sum(len(b.events) for b in self._batches.values())

            return {
                "events_queued": self._events_queued,
                "batches_sent": self._batches_sent,
                "priority_sent": self._priority_sent,
                "pending_batches": len(self._batches),
                "pending_events": pending_events,
                "batch_window": self.batch_window,
                "max_batch_size": self.max_batch_size,
            }

    def shutdown(self, flush: bool = True) -> None:
        """
        Shutdown the dispatcher.

        Args:
            flush: If True, flush all pending batches before shutdown
        """
        self._shutdown = True

        if flush:
            self.flush_all()

        self._flush_thread.join(timeout=5.0)
        logger.info("Batch webhook dispatcher shutdown")


# =============================================================================
# Global Dispatcher
# =============================================================================

_batch_dispatcher: BatchWebhookDispatcher | None = None


def get_batch_dispatcher() -> BatchWebhookDispatcher:
    """Get or create the global batch dispatcher."""
    global _batch_dispatcher

    if _batch_dispatcher is None:
        _batch_dispatcher = BatchWebhookDispatcher()

        # Wire up to the standard dispatcher
        try:
            from aragora.events.dispatcher import dispatch_event

            _batch_dispatcher.set_delivery_callback(
                lambda event_type, payload: dispatch_event(
                    payload.get("event", event_type), payload
                )
            )
        except ImportError:
            logger.warning("Could not wire batch dispatcher to event dispatcher")

    return _batch_dispatcher


def queue_batched_event(
    event_type: str,
    data: dict[str, Any],
    priority: bool = False,
) -> None:
    """
    Queue an event for batched webhook delivery.

    Convenience function using the global batch dispatcher.

    Args:
        event_type: Event type
        data: Event data
        priority: If True, sends immediately
    """
    dispatcher = get_batch_dispatcher()
    dispatcher.queue_event(event_type, data, priority)


def shutdown_batch_dispatcher(flush: bool = True) -> None:
    """Shutdown the global batch dispatcher."""
    global _batch_dispatcher

    if _batch_dispatcher is not None:
        _batch_dispatcher.shutdown(flush=flush)
        _batch_dispatcher = None


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "BatchWebhookDispatcher",
    "EventBatch",
    "BatchedEvent",
    "get_batch_dispatcher",
    "queue_batched_event",
    "shutdown_batch_dispatcher",
]
