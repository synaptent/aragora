"""
Redis Pub/Sub for cross-instance debate event propagation.

Enables WebSocket event broadcasting across multiple server instances,
supporting horizontal scaling of the debate platform.

When Redis is available:
- Events are published to Redis channels for cross-instance delivery
- Each instance subscribes to relevant channels and broadcasts locally

When Redis is unavailable:
- Falls back to local-only event delivery (single instance)
- No cross-instance propagation

Usage:
    from aragora.server.pubsub import get_pubsub, PubSubEvent

    pubsub = get_pubsub()

    # Publish an event (async)
    await pubsub.publish("debate:123", {"type": "vote", "agent": "claude"})

    # Subscribe to events (async)
    async def handler(event: PubSubEvent):
        print(f"Received: {event.data}")

    await pubsub.subscribe("debate:*", handler)
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable, Coroutine

from aragora.utils.redis_config import get_redis_client, is_redis_available

logger = logging.getLogger(__name__)

# Type alias for event handlers
EventHandler = Callable[["PubSubEvent"], Coroutine[Any, Any, None]]


@dataclass
class PubSubEvent:
    """Event received from pub/sub channel."""

    channel: str
    data: dict[str, Any]
    pattern: str | None = None


@dataclass
class RedisPubSub:
    """Redis-based pub/sub for cross-instance event propagation.

    Provides async publish/subscribe interface for debate events.
    Falls back gracefully when Redis is unavailable.
    """

    # Channel prefix for debate events
    channel_prefix: str = "aragora:events:"

    # Internal state
    _pubsub: Any = field(default=None, repr=False)
    _handlers: dict[str, list[EventHandler]] = field(default_factory=dict, repr=False)
    _listener_task: asyncio.Task | None = field(default=None, repr=False)
    _running: bool = field(default=False, repr=False)

    @property
    def is_available(self) -> bool:
        """Check if Redis pub/sub is available."""
        return is_redis_available()

    async def publish(self, channel: str, data: dict[str, Any]) -> bool:
        """Publish event to channel.

        Args:
            channel: Channel name (e.g., "debate:123")
            data: Event data to publish

        Returns:
            True if published successfully, False otherwise
        """
        if not self.is_available:
            logger.debug("Redis unavailable, skipping publish to %s", channel)
            return False

        try:
            client = get_redis_client()
            if not client:
                return False

            full_channel = f"{self.channel_prefix}{channel}"
            message = json.dumps(data)

            # Use run_in_executor for sync Redis client
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: client.publish(full_channel, message))

            logger.debug("Published to %s", full_channel)
            return True

        except (ConnectionError, OSError, json.JSONDecodeError) as e:
            logger.warning("Pub/sub publish failed: %s", e)
            return False

    async def subscribe(
        self,
        pattern: str,
        handler: EventHandler,
    ) -> bool:
        """Subscribe to channel pattern.

        Args:
            pattern: Channel pattern (e.g., "debate:*" for all debates)
            handler: Async callback for received events

        Returns:
            True if subscribed successfully, False otherwise
        """
        full_pattern = f"{self.channel_prefix}{pattern}"

        # Register handler
        if full_pattern not in self._handlers:
            self._handlers[full_pattern] = []
        self._handlers[full_pattern].append(handler)

        if not self.is_available:
            logger.debug("Redis unavailable, handler registered locally for %s", pattern)
            return False

        try:
            await self._ensure_pubsub()
            if not self._pubsub:
                return False

            # Subscribe to pattern
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, lambda: self._pubsub.psubscribe(full_pattern))

            logger.info("Subscribed to pattern: %s", full_pattern)
            return True

        except (ConnectionError, OSError) as e:
            logger.warning("Pub/sub subscribe failed: %s", e)
            return False

    async def unsubscribe(self, pattern: str) -> None:
        """Unsubscribe from channel pattern.

        Args:
            pattern: Channel pattern to unsubscribe from
        """
        full_pattern = f"{self.channel_prefix}{pattern}"

        # Remove handlers
        if full_pattern in self._handlers:
            del self._handlers[full_pattern]

        if self._pubsub:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: self._pubsub.punsubscribe(full_pattern))
            except (ConnectionError, OSError) as e:
                logger.debug("Unsubscribe failed: %s", e)

    async def start_listener(self) -> None:
        """Start background listener for pub/sub messages.

        Should be called once during server startup.
        """
        if self._running:
            return

        if not self.is_available:
            logger.info("Redis unavailable, pub/sub listener disabled")
            return

        self._running = True
        self._listener_task = asyncio.create_task(self._listen_loop())
        logger.info("Pub/sub listener started")

    async def stop_listener(self) -> None:
        """Stop background listener.

        Should be called during server shutdown.
        """
        self._running = False

        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

        if self._pubsub:
            try:
                self._pubsub.close()
            except (ConnectionError, OSError) as e:
                logger.debug("Error closing pubsub connection: %s", type(e).__name__)
            self._pubsub = None

        logger.info("Pub/sub listener stopped")

    async def _ensure_pubsub(self) -> None:
        """Ensure pub/sub connection is established."""
        if self._pubsub is not None:
            return

        client = get_redis_client()
        if not client:
            return

        try:
            self._pubsub = client.pubsub()
        except (ConnectionError, OSError) as e:
            logger.warning("Failed to create pub/sub: %s", e)

    async def _listen_loop(self) -> None:
        """Background loop listening for pub/sub messages."""
        await self._ensure_pubsub()

        if not self._pubsub:
            logger.debug("Pub/sub not available, listener exiting")
            return

        while self._running:
            try:
                # Get message with timeout
                loop = asyncio.get_running_loop()
                message = await loop.run_in_executor(
                    None, lambda: self._pubsub.get_message(timeout=1.0)
                )

                if message and message["type"] == "pmessage":
                    await self._handle_message(message)

            except asyncio.CancelledError:
                break
            except (ConnectionError, OSError) as e:
                logger.warning("Pub/sub listen error: %s", e)
                await asyncio.sleep(1.0)

    async def _handle_message(self, message: dict) -> None:
        """Handle received pub/sub message."""
        try:
            channel = message.get("channel", "")
            pattern = message.get("pattern", "")
            data_str = message.get("data", "{}")

            # Decode if bytes
            if isinstance(channel, bytes):
                channel = channel.decode()
            if isinstance(pattern, bytes):
                pattern = pattern.decode()
            if isinstance(data_str, bytes):
                data_str = data_str.decode()

            data = json.loads(data_str)

            event = PubSubEvent(
                channel=channel,
                data=data,
                pattern=pattern,
            )

            # Dispatch to handlers
            if pattern in self._handlers:
                for handler in self._handlers[pattern]:
                    try:
                        await handler(event)
                    except Exception as e:  # noqa: BLE001 - Isolate individual handler failures from listener loop
                        logger.warning("Handler error: %s", e)

        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON in pub/sub message: %s", e)
        except (KeyError, TypeError, UnicodeDecodeError) as e:
            logger.warning("Error handling pub/sub message: %s", e)

    async def publish_debate_event(
        self,
        debate_id: str,
        event_type: str,
        data: dict[str, Any],
    ) -> bool:
        """Convenience method to publish debate events.

        Args:
            debate_id: The debate ID
            event_type: Event type (e.g., "vote", "message")
            data: Event data

        Returns:
            True if published successfully
        """
        return await self.publish(
            f"debate:{debate_id}",
            {"type": event_type, "debate_id": debate_id, **data},
        )


# Module-level singleton with thread-safe initialization
_pubsub: RedisPubSub | None = None
_pubsub_lock = threading.Lock()


def get_pubsub() -> RedisPubSub:
    """Get shared RedisPubSub instance.

    Returns:
        Singleton RedisPubSub instance
    """
    global _pubsub
    if _pubsub is None:
        with _pubsub_lock:
            if _pubsub is None:
                _pubsub = RedisPubSub()
    return _pubsub


def reset_pubsub() -> None:
    """Reset pub/sub state for testing."""
    global _pubsub
    with _pubsub_lock:
        _pubsub = None


__all__ = [
    "PubSubEvent",
    "RedisPubSub",
    "EventHandler",
    "get_pubsub",
    "reset_pubsub",
]
