"""
Event Bus for Aragora Debates.

Centralized event emission and subscription system for debate events.
Extracted from Arena to enable cleaner event handling and testing.

Usage:
    from aragora.debate.event_bus import EventBus, DebateEvent

    # Create event bus
    bus = EventBus()

    # Subscribe to events
    async def handler(event: DebateEvent):
        print(f"Received: {event.event_type}")

    bus.subscribe("debate_start", handler)

    # Emit events
    await bus.emit("debate_start", debate_id="123", task="Design a rate limiter")
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from collections.abc import Callable, Coroutine

from aragora.observability.middleware.tracing import get_span_id, get_trace_id

logger = logging.getLogger(__name__)


@dataclass
class DebateEvent:
    """Represents a debate event with distributed tracing support."""

    event_type: str
    debate_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = field(default_factory=dict)
    # Distributed tracing fields for correlation across services
    correlation_id: str | None = field(default=None)
    span_id: str | None = field(default=None)

    def __post_init__(self) -> None:
        """Auto-populate correlation_id from current trace context if not provided."""
        if self.correlation_id is None:
            self.correlation_id = get_trace_id()
        if self.span_id is None:
            self.span_id = get_span_id()

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary for serialization."""
        result = {
            "event_type": self.event_type,
            "debate_id": self.debate_id,
            "timestamp": self.timestamp.isoformat(),
            **self.data,
        }
        # Include tracing fields if present
        if self.correlation_id:
            result["correlation_id"] = self.correlation_id
        if self.span_id:
            result["span_id"] = self.span_id
        return result


# Type alias for event handlers
EventHandler = Callable[[DebateEvent], Coroutine[Any, Any, None]]
SyncEventHandler = Callable[[DebateEvent], None]


class EventBus:
    """
    Centralized event bus for debate events.

    Features:
    - Async event emission
    - Multiple subscribers per event type
    - User event queuing (thread-safe)
    - Event bridge integration for WebSocket streaming
    - Health event broadcasting
    """

    def __init__(
        self,
        event_bridge: Any | None = None,  # EventEmitterBridge
        audience_manager: Any | None = None,  # AudienceManager
        immune_system: Any | None = None,  # TransparentImmuneSystem
        spectator: Any | None = None,  # SpectatorStream
    ):
        """
        Initialize the event bus.

        Args:
            event_bridge: Optional EventEmitterBridge for external notifications
            audience_manager: Optional AudienceManager for user participation
            immune_system: Optional TransparentImmuneSystem for health events
            spectator: Optional SpectatorStream for WebSocket broadcasting
        """
        self._event_bridge = event_bridge
        self._audience_manager = audience_manager
        self._immune_system = immune_system
        self._spectator = spectator

        # Event subscribers
        self._async_handlers: dict[str, list[EventHandler]] = {}
        self._sync_handlers: dict[str, list[SyncEventHandler]] = {}

        # User event queue (thread-safe for external input, bounded to prevent OOM)
        self._user_event_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=5000)
        self._user_event_lock = threading.Lock()

        # Metrics
        self._events_emitted: int = 0
        self._events_by_type: dict[str, int] = {}

    # =========================================================================
    # Subscription Management
    # =========================================================================

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """
        Subscribe an async handler to an event type.

        Args:
            event_type: Type of event to subscribe to
            handler: Async handler function
        """
        if event_type not in self._async_handlers:
            self._async_handlers[event_type] = []
        self._async_handlers[event_type].append(handler)
        logger.debug("Subscribed async handler to '%s'", event_type)

    def subscribe_sync(self, event_type: str, handler: SyncEventHandler) -> None:
        """
        Subscribe a sync handler to an event type.

        Args:
            event_type: Type of event to subscribe to
            handler: Sync handler function
        """
        if event_type not in self._sync_handlers:
            self._sync_handlers[event_type] = []
        self._sync_handlers[event_type].append(handler)
        logger.debug("Subscribed sync handler to '%s'", event_type)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> bool:
        """
        Unsubscribe an async handler from an event type.

        Args:
            event_type: Type of event to unsubscribe from
            handler: Handler function to remove

        Returns:
            True if handler was found and removed
        """
        if event_type in self._async_handlers:
            try:
                self._async_handlers[event_type].remove(handler)
                return True
            except ValueError as e:
                logger.debug(
                    "Failed to remove async handler for event type '%s': %s", event_type, e
                )
                # Handler was not in list, likely already removed
        return False

    def unsubscribe_sync(self, event_type: str, handler: SyncEventHandler) -> bool:
        """
        Unsubscribe a sync handler from an event type.

        Args:
            event_type: Type of event to unsubscribe from
            handler: Handler function to remove

        Returns:
            True if handler was found and removed
        """
        if event_type in self._sync_handlers:
            try:
                self._sync_handlers[event_type].remove(handler)
                return True
            except ValueError as e:
                logger.debug("Failed to remove sync handler for event type '%s': %s", event_type, e)
                # Handler was not in list, likely already removed
        return False

    def clear_handlers(self, event_type: str | None = None) -> int:
        """
        Clear all handlers, optionally for a specific event type.

        Args:
            event_type: If provided, only clear handlers for this event type.
                       If None, clear all handlers.

        Returns:
            Number of handlers removed
        """
        removed = 0
        if event_type is not None:
            if event_type in self._async_handlers:
                removed += len(self._async_handlers[event_type])
                del self._async_handlers[event_type]
            if event_type in self._sync_handlers:
                removed += len(self._sync_handlers[event_type])
                del self._sync_handlers[event_type]
        else:
            for async_handlers in self._async_handlers.values():
                removed += len(async_handlers)
            for sync_handlers in self._sync_handlers.values():
                removed += len(sync_handlers)
            self._async_handlers.clear()
            self._sync_handlers.clear()
        return removed

    def cleanup(self) -> None:
        """Clean up all event bus resources.

        Should be called when the event bus is no longer needed to prevent
        memory leaks from accumulated handlers.
        """
        self.clear_handlers()
        self._events_emitted = 0
        self._events_by_type.clear()
        # Clear user event queue
        while not self._user_event_queue.empty():
            try:
                self._user_event_queue.get_nowait()
            except queue.Empty:
                break
        logger.debug("EventBus resources cleaned up")

    # =========================================================================
    # Event Emission
    # =========================================================================

    async def emit(
        self,
        event_type: str,
        debate_id: str = "",
        correlation_id: str | None = None,
        **data: Any,
    ) -> None:
        """
        Emit an event to all subscribers.

        Args:
            event_type: Type of event
            debate_id: ID of the debate
            correlation_id: Optional correlation ID for distributed tracing
                           (auto-populated from trace context if not provided)
            **data: Additional event data
        """
        event = DebateEvent(
            event_type=event_type,
            debate_id=debate_id,
            correlation_id=correlation_id,
            data=data,
        )

        # Update metrics
        self._events_emitted += 1
        self._events_by_type[event_type] = self._events_by_type.get(event_type, 0) + 1

        # Notify event bridge (WebSocket streaming)
        if self._event_bridge is not None:
            try:
                event_data = event.to_dict()
                event_data.pop("event_type", None)  # Already passed as first arg
                self._event_bridge.notify(event_type, **event_data)
            except (RuntimeError, AttributeError, TypeError, ValueError, OSError) as e:
                logger.warning("Event bridge notification failed: %s", e)

        # Notify spectator stream
        if self._spectator is not None:
            try:
                self._spectator.emit(event_type, event.to_dict())
            except (RuntimeError, AttributeError, TypeError, ValueError, OSError) as e:
                logger.warning("Spectator notification failed: %s", e)

        # Call sync handlers
        for handler in self._sync_handlers.get(event_type, []):
            try:
                handler(event)
            except Exception as e:  # noqa: BLE001 - handler isolation: user-provided handlers may raise anything
                logger.warning("Sync handler error for '%s': %s", event_type, e)

        # Call async handlers
        async_handlers = self._async_handlers.get(event_type, [])
        if async_handlers:
            await asyncio.gather(
                *[self._safe_call_handler(handler, event) for handler in async_handlers],
                return_exceptions=True,
            )

        logger.debug("Emitted event '%s' for debate '%s'", event_type, debate_id)

    async def _safe_call_handler(
        self,
        handler: EventHandler,
        event: DebateEvent,
    ) -> None:
        """Safely call an async handler with error handling."""
        try:
            await handler(event)
        except Exception as e:  # noqa: BLE001 - handler isolation: user-provided handlers may raise anything
            logger.warning("Async handler error for '%s': %s", event.event_type, e)

    def emit_sync(
        self,
        event_type: str,
        debate_id: str = "",
        correlation_id: str | None = None,
        **data: Any,
    ) -> None:
        """
        Emit an event synchronously (for non-async contexts).

        Only notifies sync handlers and event bridge.

        Args:
            event_type: Type of event
            debate_id: ID of the debate
            correlation_id: Optional correlation ID for distributed tracing
                           (auto-populated from trace context if not provided)
            **data: Additional event data
        """
        event = DebateEvent(
            event_type=event_type,
            debate_id=debate_id,
            correlation_id=correlation_id,
            data=data,
        )

        # Update metrics
        self._events_emitted += 1
        self._events_by_type[event_type] = self._events_by_type.get(event_type, 0) + 1

        # Notify event bridge
        if self._event_bridge is not None:
            try:
                event_data = event.to_dict()
                event_data.pop("event_type", None)  # Already passed as first arg
                self._event_bridge.notify(event_type, **event_data)
            except (RuntimeError, AttributeError, TypeError, ValueError, OSError) as e:
                logger.warning("Event bridge notification failed: %s", e)

        # Call sync handlers only
        for handler in self._sync_handlers.get(event_type, []):
            try:
                handler(event)
            except Exception as e:  # noqa: BLE001 - handler isolation: user-provided handlers may raise anything
                logger.warning("Sync handler error for '%s': %s", event_type, e)

    # =========================================================================
    # Specialized Event Methods (extracted from Arena)
    # =========================================================================

    async def notify_spectator(
        self,
        event_type: str,
        debate_id: str,
        **data: Any,
    ) -> None:
        """
        Notify spectators of a debate event.

        Extracted from Arena._notify_spectator().

        Args:
            event_type: Type of event
            debate_id: ID of the debate
            **data: Event data
        """
        await self.emit(event_type, debate_id=debate_id, **data)

    async def emit_moment_event(
        self,
        debate_id: str,
        moment_type: str,
        description: str,
        agent: str | None = None,
        round_num: int | None = None,
        significance: float = 0.5,
        **extra: Any,
    ) -> None:
        """
        Emit a significant moment event.

        Extracted from Arena._emit_moment_event().

        Args:
            debate_id: ID of the debate
            moment_type: Type of moment (e.g., "breakthrough", "consensus")
            description: Human-readable description
            agent: Optional agent name involved
            round_num: Optional round number
            significance: Significance score (0-1)
            **extra: Additional data
        """
        await self.emit(
            "moment",
            debate_id=debate_id,
            moment_type=moment_type,
            description=description,
            agent=agent,
            round_num=round_num,
            significance=significance,
            **extra,
        )

    async def broadcast_health_event(
        self,
        debate_id: str,
        health_status: dict[str, Any],
    ) -> None:
        """
        Broadcast immune system health status.

        Extracted from Arena._broadcast_health_event().

        Args:
            debate_id: ID of the debate
            health_status: Health metrics from immune system
        """
        if self._immune_system is None:
            return

        await self.emit(
            "health_update",
            debate_id=debate_id,
            health=health_status,
            timestamp=time.time(),
        )

    # =========================================================================
    # User Event Queue (Thread-Safe)
    # =========================================================================

    # Lock timeout to prevent deadlocks (1 second)
    LOCK_TIMEOUT = 1.0

    def queue_user_event(self, event: dict[str, Any]) -> None:
        """
        Queue a user participation event (thread-safe with timeout).

        Extracted from Arena._handle_user_event().

        Args:
            event: User event data (vote, suggestion, etc.)
        """
        acquired = self._user_event_lock.acquire(timeout=self.LOCK_TIMEOUT)
        if not acquired:
            logger.warning(
                "[event_bus] Lock timeout in queue_user_event, dropping event: %s",
                event.get("type", "unknown"),
            )
            return
        try:
            self._user_event_queue.put(event)
        finally:
            self._user_event_lock.release()
        logger.debug("Queued user event: %s", event.get("type", "unknown"))

    async def drain_user_events(self, debate_id: str) -> list[dict[str, Any]]:
        """
        Process all queued user events (with timeout protection).

        Extracted from Arena._drain_user_events().

        Args:
            debate_id: ID of the debate

        Returns:
            List of processed events
        """
        events: list[dict[str, Any]] = []
        acquired = self._user_event_lock.acquire(timeout=self.LOCK_TIMEOUT)
        if not acquired:
            logger.warning("[event_bus] Lock timeout in drain_user_events, returning empty")
            return events
        try:
            while not self._user_event_queue.empty():
                try:
                    event = self._user_event_queue.get_nowait()
                    events.append(event)
                except queue.Empty:
                    break
        finally:
            self._user_event_lock.release()

        # Process events through audience manager if available
        if self._audience_manager is not None and events:
            for event in events:
                try:
                    await self._process_user_event(event, debate_id)
                except (RuntimeError, ValueError, TypeError, AttributeError, KeyError) as e:
                    logger.warning("Failed to process user event: %s", e)

        return events

    async def _process_user_event(
        self,
        event: dict[str, Any],
        debate_id: str,
    ) -> None:
        """Process a single user event."""
        event_type = event.get("type", "")

        if event_type == "vote" and self._audience_manager:
            await self._audience_manager.record_vote(
                debate_id=debate_id,
                user_id=event.get("user_id", "anonymous"),
                vote=event.get("vote"),
            )
        elif event_type == "suggestion" and self._audience_manager:
            await self._audience_manager.add_suggestion(
                debate_id=debate_id,
                user_id=event.get("user_id", "anonymous"),
                content=event.get("content", ""),
            )

    # =========================================================================
    # Metrics
    # =========================================================================

    def get_metrics(self) -> dict[str, Any]:
        """
        Get event bus metrics.

        Returns:
            Dictionary with event statistics
        """
        return {
            "total_events_emitted": self._events_emitted,
            "events_by_type": self._events_by_type.copy(),
            "async_subscribers": {k: len(v) for k, v in self._async_handlers.items()},
            "sync_subscribers": {k: len(v) for k, v in self._sync_handlers.items()},
            "pending_user_events": self._user_event_queue.qsize(),
        }

    def reset_metrics(self) -> None:
        """Reset event metrics."""
        self._events_emitted = 0
        self._events_by_type.clear()

    # Context manager support for proper cleanup
    def __enter__(self) -> EventBus:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context manager - cleanup all resources."""
        self.cleanup()


# Singleton instance for global access (optional pattern)
_default_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the default event bus instance."""
    global _default_bus
    if _default_bus is None:
        _default_bus = EventBus()
    return _default_bus


def set_event_bus(bus: EventBus) -> None:
    """Set the default event bus instance."""
    global _default_bus
    _default_bus = bus


__all__ = [
    "EventBus",
    "DebateEvent",
    "EventHandler",
    "SyncEventHandler",
    "get_event_bus",
    "set_event_bus",
]
