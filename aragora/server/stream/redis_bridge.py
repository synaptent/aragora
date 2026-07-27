"""
Redis Pub/Sub Bridge for WebSocket Broadcasting.

Enables cross-instance event broadcasting for horizontally scaled deployments.
Events published on one server instance are relayed to all other instances.

Usage:
    from aragora.server.stream.redis_bridge import RedisBroadcastBridge

    # Initialize bridge
    bridge = RedisBroadcastBridge(broadcaster)
    await bridge.connect()

    # Bridge will automatically relay events between instances

    # Publish events that should be broadcast to all instances
    await bridge.publish_to_all("debate_message", {"debate_id": "...", ...})

    # Cleanup
    await bridge.disconnect()

Environment Variables:
    ARAGORA_REDIS_URL: Redis connection URL
    ARAGORA_INSTANCE_ID: Unique instance identifier
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import time
from typing import Any

from aragora.exceptions import REDIS_CONNECTION_ERRORS

logger = logging.getLogger(__name__)

# Configuration
REDIS_URL = os.environ.get("ARAGORA_REDIS_URL", "redis://localhost:6379")
INSTANCE_ID = os.environ.get("ARAGORA_INSTANCE_ID", f"instance-{os.getpid()}")

# Optional redis import
try:
    aioredis: Any = importlib.import_module("redis.asyncio")

    REDIS_AVAILABLE = True
except ImportError:
    aioredis = None
    REDIS_AVAILABLE = False


class RedisBroadcastBridge:
    """
    Bridge between local WebSocket broadcaster and Redis Pub/Sub.

    Listens for events from other instances and relays them to local clients.
    Publishes local events for other instances to receive.
    """

    CHANNEL_PREFIX = "aragora:broadcast"
    DEBATE_CHANNEL = f"{CHANNEL_PREFIX}:debates"
    LOOP_CHANNEL = f"{CHANNEL_PREFIX}:loops"
    GLOBAL_CHANNEL = f"{CHANNEL_PREFIX}:global"

    def __init__(
        self,
        broadcaster: Any,
        redis_url: str = REDIS_URL,
        instance_id: str = INSTANCE_ID,
    ):
        """Initialize the Redis bridge.

        Args:
            broadcaster: Local broadcaster instance to relay events to
            redis_url: Redis connection URL
            instance_id: Unique identifier for this server instance
        """
        self._broadcaster = broadcaster
        self._redis_url = redis_url
        self._instance_id = instance_id
        self._redis: Any | None = None
        self._pubsub: Any | None = None
        self._listener_task: asyncio.Task | None = None
        self._connected = False
        self._running = False

    async def connect(self) -> bool:
        """Connect to Redis and start listening for events.

        Returns:
            True if connected successfully
        """
        if not REDIS_AVAILABLE:
            logger.debug("Redis not available for broadcast bridge")
            return False

        try:
            self._redis = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis.ping()
            self._connected = True

            # Start listener
            self._running = True
            self._listener_task = asyncio.create_task(self._listen_loop())

            logger.info("Redis broadcast bridge connected (instance=%s)", self._instance_id)
            return True

        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("Failed to connect Redis bridge: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from Redis and stop listening."""
        self._running = False

        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
            self._listener_task = None

        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
            self._pubsub = None

        if self._redis:
            await self._redis.close()
            self._redis = None

        self._connected = False
        logger.info("Redis broadcast bridge disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if connected to Redis."""
        return self._connected

    async def _listen_loop(self) -> None:
        """Listen for events from other instances."""
        if not self._redis:
            return

        self._pubsub = self._redis.pubsub()
        await self._pubsub.subscribe(
            self.DEBATE_CHANNEL,
            self.LOOP_CHANNEL,
            self.GLOBAL_CHANNEL,
        )

        logger.debug("Redis bridge listening for events")

        try:
            async for message in self._pubsub.listen():
                if not self._running:
                    break

                if message["type"] != "message":
                    continue

                try:
                    await self._handle_message(message)
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.warning("Error handling Redis message: %s", e)

        except asyncio.CancelledError:
            logger.debug("Redis bridge listener cancelled")
        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Redis bridge listener error: %s", e)

    async def _handle_message(self, message: dict) -> None:
        """Handle an incoming Redis message.

        Args:
            message: Redis pub/sub message
        """
        try:
            data = json.loads(message["data"])
        except json.JSONDecodeError:
            logger.warning("Invalid JSON in Redis message: %s", message["data"])
            return

        # Ignore messages from this instance
        if data.get("instance_id") == self._instance_id:
            return

        event_type = data.get("type")
        payload = data.get("payload", {})
        channel = message["channel"]

        logger.debug(
            "Received cross-instance event: %s from %s", event_type, data.get("instance_id")
        )

        # Relay to local broadcaster
        await self._relay_to_local(channel, event_type, payload)

    async def _relay_to_local(self, channel: str, event_type: str, payload: dict) -> None:
        """Relay a remote event to local WebSocket clients.

        Args:
            channel: Redis channel the event came from
            event_type: Type of event
            payload: Event payload
        """
        if not self._broadcaster:
            return

        # Map Redis channel to broadcast method
        if channel == self.DEBATE_CHANNEL:
            debate_id = payload.get("debate_id")
            if debate_id and hasattr(self._broadcaster, "broadcast_to_debate"):
                await self._broadcaster.broadcast_to_debate(
                    debate_id,
                    {"type": event_type, **payload},
                )
        elif channel == self.LOOP_CHANNEL:
            loop_id = payload.get("loop_id")
            if loop_id and hasattr(self._broadcaster, "broadcast_to_loop"):
                await self._broadcaster.broadcast_to_loop(
                    loop_id,
                    {"type": event_type, **payload},
                )
        elif channel == self.GLOBAL_CHANNEL:
            if hasattr(self._broadcaster, "broadcast_to_all"):
                await self._broadcaster.broadcast_to_all(
                    {"type": event_type, **payload},
                )

    async def publish_debate_event(self, debate_id: str, event_type: str, payload: dict) -> None:
        """Publish a debate event to all instances.

        Args:
            debate_id: Debate identifier
            event_type: Event type (e.g., "message", "vote", "consensus")
            payload: Event payload
        """
        await self._publish(
            self.DEBATE_CHANNEL,
            event_type,
            {"debate_id": debate_id, **payload},
        )

    async def publish_loop_event(self, loop_id: str, event_type: str, payload: dict) -> None:
        """Publish a loop event to all instances.

        Args:
            loop_id: Loop identifier
            event_type: Event type
            payload: Event payload
        """
        await self._publish(
            self.LOOP_CHANNEL,
            event_type,
            {"loop_id": loop_id, **payload},
        )

    async def publish_global_event(self, event_type: str, payload: dict) -> None:
        """Publish a global event to all instances.

        Args:
            event_type: Event type
            payload: Event payload
        """
        await self._publish(self.GLOBAL_CHANNEL, event_type, payload)

    async def _publish(self, channel: str, event_type: str, payload: dict) -> None:
        """Publish an event to a Redis channel.

        Args:
            channel: Redis channel to publish to
            event_type: Event type
            payload: Event payload
        """
        if not self._connected or not self._redis:
            return

        message = {
            "type": event_type,
            "payload": payload,
            "instance_id": self._instance_id,
            "timestamp": time.time(),
        }

        try:
            await self._redis.publish(channel, json.dumps(message))
            logger.debug("Published event to %s: %s", channel, event_type)
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("Failed to publish Redis event: %s", e)

    async def health_check(self) -> dict:
        """Perform health check.

        Returns:
            Health status dict
        """
        result = {
            "connected": self._connected,
            "instance_id": self._instance_id,
            "listener_running": self._listener_task is not None and not self._listener_task.done(),
        }

        if self._connected and self._redis:
            try:
                start = time.time()
                await self._redis.ping()
                result["ping_ms"] = (time.time() - start) * 1000
            except REDIS_CONNECTION_ERRORS as e:
                logger.warning("Redis bridge health check failed: %s", e)
                result["error"] = "Redis health check failed"
                result["connected"] = False

        return result


# Singleton bridge instance
_bridge: RedisBroadcastBridge | None = None


async def get_broadcast_bridge(
    broadcaster: Any = None,
    redis_url: str | None = None,
) -> RedisBroadcastBridge:
    """Get or create the global broadcast bridge.

    Args:
        broadcaster: Broadcaster instance (required on first call)
        redis_url: Optional Redis URL override

    Returns:
        RedisBroadcastBridge instance
    """
    global _bridge

    if _bridge is None:
        if broadcaster is None:
            raise ValueError("broadcaster required for first initialization")
        _bridge = RedisBroadcastBridge(
            broadcaster,
            redis_url=redis_url or REDIS_URL,
        )
        await _bridge.connect()

    return _bridge


async def reset_broadcast_bridge() -> None:
    """Reset the global broadcast bridge (for testing)."""
    global _bridge

    if _bridge is not None:
        await _bridge.disconnect()
        _bridge = None


__all__ = [
    "RedisBroadcastBridge",
    "get_broadcast_bridge",
    "reset_broadcast_bridge",
    "REDIS_AVAILABLE",
]
