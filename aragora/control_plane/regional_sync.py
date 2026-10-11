"""
Regional Synchronization for Multi-Region Control Plane.

Provides cross-region state synchronization with:
- Event-driven sync via Redis pub/sub
- Regional event bus for broadcasting changes
- Conflict-free state updates using timestamps
- Regional health monitoring

Usage:
    from aragora.control_plane.regional_sync import (
        RegionalEventBus,
        RegionalSyncConfig,
        RegionalStateManager,
    )

    # Create regional event bus
    config = RegionalSyncConfig(
        local_region="us-west-2",
        sync_regions=["us-east-1", "eu-west-1"],
    )
    event_bus = RegionalEventBus(redis_url="redis://localhost:6379", config=config)
    await event_bus.connect()

    # Publish state change
    await event_bus.publish_agent_update(agent_id, agent_state)

    # Subscribe to remote changes
    await event_bus.subscribe(handler_callback)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, cast
from collections.abc import Awaitable, Callable, Coroutine

# Observability
from aragora.observability import get_logger
from aragora.resilience.regional_events import RegionalEvent, RegionalEventType

logger = get_logger(__name__)


@dataclass
class RegionalSyncConfig:
    """Configuration for regional synchronization."""

    # Local region identifier
    local_region: str = field(default_factory=lambda: os.environ.get("ARAGORA_REGION", "default"))

    # Regions to sync with (empty = all regions via broadcast)
    sync_regions: list[str] = field(default_factory=list)

    # Redis channel prefix for regional events
    channel_prefix: str = "aragora:regional:"

    # How often to publish heartbeats (seconds)
    heartbeat_interval: float = 10.0

    # How long before a region is considered unhealthy (seconds)
    region_timeout: float = 30.0

    # Maximum events to buffer locally when disconnected
    max_event_buffer: int = 1000

    # Whether to sync agent heartbeats (high volume)
    sync_heartbeats: bool = False

    # Conflict resolution strategy
    conflict_strategy: str = "last_write_wins"  # or "merge", "source_priority"

    def get_global_channel(self) -> str:
        """Get the global broadcast channel name."""
        return f"{self.channel_prefix}global"

    def get_region_channel(self, region_id: str) -> str:
        """Get region-specific channel name."""
        return f"{self.channel_prefix}region:{region_id}"


# Type alias for event handlers
RegionalEventHandler = Callable[[RegionalEvent], Coroutine[Any, Any, None]]


class RegionalEventBus:
    """
    Event bus for cross-region state synchronization.

    Uses Redis pub/sub for broadcasting events to all regions.
    Supports both global broadcast and region-specific channels.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        config: RegionalSyncConfig | None = None,
    ):
        """
        Initialize the regional event bus.

        Args:
            redis_url: Redis connection URL
            config: Regional sync configuration
        """
        self._redis_url = redis_url
        self._config = config or RegionalSyncConfig()
        self._redis: Any | None = None
        self._pubsub: Any | None = None
        self._connected = False
        self._running = False

        # Event handlers
        self._handlers: dict[RegionalEventType, list[RegionalEventHandler]] = {}
        self._global_handlers: list[RegionalEventHandler] = []

        # Event buffer for offline operation
        self._event_buffer: list[RegionalEvent] = []

        # Last seen timestamps per region (for health monitoring)
        self._region_last_seen: dict[str, float] = {}

        # Background tasks
        self._listener_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

    @property
    def local_region(self) -> str:
        """Get the local region identifier."""
        return self._config.local_region

    @property
    def is_connected(self) -> bool:
        """Check if connected to Redis."""
        return self._connected

    async def connect(self) -> bool:
        """
        Connect to Redis and start listening for events.

        Returns:
            True if connected successfully
        """
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await cast(Awaitable[bool], self._redis.ping())
            self._connected = True

            # Create pubsub connection
            self._pubsub = self._redis.pubsub()

            # Subscribe to global channel and local region channel
            await self._pubsub.subscribe(self._config.get_global_channel())
            await self._pubsub.subscribe(self._config.get_region_channel(self._config.local_region))

            logger.info("RegionalEventBus connected to Redis, region=%s", self._config.local_region)

            # Start background tasks
            self._running = True
            self._listener_task = asyncio.create_task(self._listen_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # Announce region joined
            await self.publish(
                RegionalEvent(
                    event_type=RegionalEventType.REGION_JOINED,
                    source_region=self._config.local_region,
                    entity_id=self._config.local_region,
                    data={"timestamp": datetime.now(timezone.utc).isoformat()},
                )
            )

            # Flush buffered events
            await self._flush_buffer()

            return True

        except ImportError:
            logger.warning("redis package not installed, regional sync disabled")
            return False
        except (OSError, ConnectionError, TimeoutError) as e:
            logger.error("Failed to connect RegionalEventBus: %s", e)
            return False
        except Exception as e:  # noqa: BLE001 - redis.exceptions.ConnectionError inherits directly from Exception, not builtin ConnectionError
            error_name = type(e).__name__
            if (
                "ConnectionError" in error_name
                or "TimeoutError" in error_name
                or "RedisError" in error_name
            ):
                logger.error("Failed to connect RegionalEventBus: %s", e)
                return False
            raise

    async def close(self) -> None:
        """Close connections and stop background tasks."""
        self._running = False

        # Announce region leaving
        if self._connected:
            try:
                await self.publish(
                    RegionalEvent(
                        event_type=RegionalEventType.REGION_LEFT,
                        source_region=self._config.local_region,
                        entity_id=self._config.local_region,
                    )
                )
            except asyncio.CancelledError:
                # Re-raise cancellation for proper shutdown
                raise
            except (ConnectionError, TimeoutError, OSError) as e:
                # Connection issues during shutdown are expected
                logger.debug("Could not announce region leaving: %s", e)

        # Cancel background tasks
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass  # noqa: ASYNC100 - expected: CancelledError is the normal outcome after explicit .cancel()

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass  # noqa: ASYNC100 - expected: CancelledError is the normal outcome after explicit .cancel()

        # Close pubsub
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()

        # Close Redis
        if self._redis:
            await self._redis.close()

        self._connected = False
        logger.info("RegionalEventBus disconnected")

    def subscribe(
        self,
        event_type: RegionalEventType | None = None,
        handler: RegionalEventHandler | None = None,
    ) -> None:
        """
        Subscribe to regional events.

        Args:
            event_type: Specific event type to subscribe to (None for all)
            handler: Async handler function
        """
        if handler is None:
            return

        if event_type is None:
            self._global_handlers.append(handler)
        else:
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(handler)

    def unsubscribe(
        self,
        event_type: RegionalEventType | None = None,
        handler: RegionalEventHandler | None = None,
    ) -> None:
        """Unsubscribe a handler from events."""
        if handler is None:
            return

        if event_type is None:
            if handler in self._global_handlers:
                self._global_handlers.remove(handler)
        else:
            if event_type in self._handlers and handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)

    async def publish(
        self,
        event: RegionalEvent,
        target_region: str | None = None,
    ) -> bool:
        """
        Publish an event to other regions.

        Args:
            event: Event to publish
            target_region: Specific region to send to (None = broadcast)

        Returns:
            True if published (or buffered)
        """
        # Don't sync heartbeats unless configured
        if (
            event.event_type == RegionalEventType.AGENT_HEARTBEAT
            and not self._config.sync_heartbeats
        ):
            return True

        if not self._connected:
            # Buffer event for later
            if len(self._event_buffer) < self._config.max_event_buffer:
                self._event_buffer.append(event)
                return True
            else:
                logger.warning("Event buffer full, dropping event")
                return False

        try:
            channel = (
                self._config.get_region_channel(target_region)
                if target_region
                else self._config.get_global_channel()
            )
            await self._redis.publish(channel, json.dumps(event.to_dict()))  # type: ignore[union-attr]
            return True

        except (OSError, ConnectionError, RuntimeError) as e:
            logger.warning("Failed to publish regional event: %s", e)
            # Buffer on failure
            if len(self._event_buffer) < self._config.max_event_buffer:
                self._event_buffer.append(event)
            return False

    async def publish_agent_update(
        self,
        agent_id: str,
        agent_data: dict[str, Any],
        event_type: RegionalEventType = RegionalEventType.AGENT_UPDATED,
    ) -> bool:
        """Convenience method to publish agent state update."""
        event = RegionalEvent(
            event_type=event_type,
            source_region=self._config.local_region,
            entity_id=agent_id,
            data=agent_data,
        )
        return await self.publish(event)

    async def publish_task_update(
        self,
        task_id: str,
        task_data: dict[str, Any],
        event_type: RegionalEventType = RegionalEventType.TASK_SUBMITTED,
    ) -> bool:
        """Convenience method to publish task state update."""
        event = RegionalEvent(
            event_type=event_type,
            source_region=self._config.local_region,
            entity_id=task_id,
            data=task_data,
        )
        return await self.publish(event)

    def get_healthy_regions(self) -> list[str]:
        """Get list of regions that have sent heartbeats recently."""
        now = time.time()
        timeout = self._config.region_timeout
        return [
            region
            for region, last_seen in self._region_last_seen.items()
            if (now - last_seen) < timeout
        ]

    def get_region_health(self) -> dict[str, dict[str, Any]]:
        """Get health status for all known regions."""
        now = time.time()
        timeout = self._config.region_timeout
        result = {}

        for region, last_seen in self._region_last_seen.items():
            age = now - last_seen
            result[region] = {
                "last_seen": last_seen,
                "last_seen_ago_seconds": age,
                "healthy": age < timeout,
                "status": "healthy" if age < timeout else "unhealthy",
            }

        return result

    async def _listen_loop(self) -> None:
        """Background task to listen for events from other regions."""
        while self._running:
            try:
                message = await self._pubsub.get_message(  # type: ignore[union-attr]
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    await self._handle_message(message["data"])

            except asyncio.CancelledError:
                break
            except (OSError, ConnectionError, RuntimeError) as e:
                logger.warning("Error in regional event listener: %s", e)
                await asyncio.sleep(1.0)

    async def _handle_message(self, data: str) -> None:
        """Handle an incoming message from Redis."""
        try:
            event_dict = json.loads(data)
            event = RegionalEvent.from_dict(event_dict)

            # Ignore events from self
            if event.source_region == self._config.local_region:
                return

            # Update region health tracking
            self._region_last_seen[event.source_region] = time.time()

            # Call handlers
            await self._dispatch_event(event)

        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON in regional event: %s", e)
        except (RuntimeError, ValueError, KeyError) as e:
            logger.warning("Error handling regional event: %s", e)

    async def _dispatch_event(self, event: RegionalEvent) -> None:
        """Dispatch event to registered handlers."""
        # Call type-specific handlers
        if event.event_type in self._handlers:
            for handler in self._handlers[event.event_type]:
                try:
                    await handler(event)
                except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided event handler callback
                    logger.error("Error in regional event handler: %s", e)

        # Call global handlers
        for handler in self._global_handlers:
            try:
                await handler(event)
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided event handler callback
                logger.error("Error in global regional event handler: %s", e)

    async def _heartbeat_loop(self) -> None:
        """Background task to send periodic region heartbeats."""
        while self._running:
            try:
                await self.publish(
                    RegionalEvent(
                        event_type=RegionalEventType.REGION_HEALTH,
                        source_region=self._config.local_region,
                        entity_id=self._config.local_region,
                        data={
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "status": "healthy",
                        },
                    )
                )
                await asyncio.sleep(self._config.heartbeat_interval)

            except asyncio.CancelledError:
                break
            except (OSError, ConnectionError, RuntimeError) as e:
                logger.warning("Error sending region heartbeat: %s", e)
                await asyncio.sleep(self._config.heartbeat_interval)

    async def _flush_buffer(self) -> None:
        """Flush buffered events after reconnection."""
        if not self._event_buffer:
            return

        logger.info("Flushing %s buffered regional events", len(self._event_buffer))
        events = self._event_buffer.copy()
        self._event_buffer.clear()

        for event in events:
            await self.publish(event)


@dataclass
class RegionHealth:
    """Health status of a region."""

    region_id: str
    last_seen: float
    healthy: bool
    agent_count: int = 0
    task_count: int = 0
    leader_id: str | None = None


class RegionalStateManager:
    """
    Manages state synchronization across regions.

    Integrates with SharedControlPlaneState to keep agent and task
    state synchronized across multiple regional deployments.
    """

    def __init__(
        self,
        event_bus: RegionalEventBus,
        state_store: Any | None = None,  # SharedControlPlaneState
    ):
        """
        Initialize the regional state manager.

        Args:
            event_bus: Regional event bus for cross-region communication
            state_store: Shared control plane state store
        """
        self._event_bus = event_bus
        self._state_store = state_store

        # Track entity versions for conflict detection
        self._entity_versions: dict[str, float] = {}

        # Register event handlers
        self._register_handlers()

    def _register_handlers(self) -> None:
        """Register handlers for regional events."""
        # Agent events
        self._event_bus.subscribe(RegionalEventType.AGENT_REGISTERED, self._handle_agent_registered)
        self._event_bus.subscribe(RegionalEventType.AGENT_UPDATED, self._handle_agent_updated)
        self._event_bus.subscribe(
            RegionalEventType.AGENT_UNREGISTERED, self._handle_agent_unregistered
        )

        # Task events
        self._event_bus.subscribe(RegionalEventType.TASK_SUBMITTED, self._handle_task_submitted)
        self._event_bus.subscribe(RegionalEventType.TASK_COMPLETED, self._handle_task_completed)

    async def _handle_agent_registered(self, event: RegionalEvent) -> None:
        """Handle agent registration from another region."""
        if self._state_store is None:
            return

        # Check if this is newer than our version
        if not self._is_newer(event.entity_id, event.timestamp):
            return

        self._entity_versions[event.entity_id] = event.timestamp
        logger.debug("Syncing agent %s from region %s", event.entity_id, event.source_region)

        # Update local state
        # Note: This would call state_store methods when integrated

    async def _handle_agent_updated(self, event: RegionalEvent) -> None:
        """Handle agent update from another region."""
        if not self._is_newer(event.entity_id, event.timestamp):
            return

        self._entity_versions[event.entity_id] = event.timestamp
        logger.debug("Syncing agent update %s from region %s", event.entity_id, event.source_region)

    async def _handle_agent_unregistered(self, event: RegionalEvent) -> None:
        """Handle agent unregistration from another region."""
        if not self._is_newer(event.entity_id, event.timestamp):
            return

        self._entity_versions[event.entity_id] = event.timestamp
        logger.debug(
            "Syncing agent removal %s from region %s", event.entity_id, event.source_region
        )

    async def _handle_task_submitted(self, event: RegionalEvent) -> None:
        """Handle task submission from another region."""
        if not self._is_newer(event.entity_id, event.timestamp):
            return

        self._entity_versions[event.entity_id] = event.timestamp
        logger.debug("Syncing task %s from region %s", event.entity_id, event.source_region)

    async def _handle_task_completed(self, event: RegionalEvent) -> None:
        """Handle task completion from another region."""
        if not self._is_newer(event.entity_id, event.timestamp):
            return

        self._entity_versions[event.entity_id] = event.timestamp
        logger.debug(
            "Syncing task completion %s from region %s", event.entity_id, event.source_region
        )

    def _is_newer(self, entity_id: str, timestamp: float) -> bool:
        """Check if an event timestamp is newer than our version."""
        current = self._entity_versions.get(entity_id, 0.0)
        return timestamp > current

    async def sync_task_state(
        self,
        task_id: str,
        task_data: dict[str, Any],
        event_type: RegionalEventType = RegionalEventType.TASK_SUBMITTED,
        target_region: str | None = None,
    ) -> bool:
        """
        Synchronize task state to other regions.

        Args:
            task_id: Task identifier
            task_data: Task state data to sync
            event_type: Type of task event
            target_region: Specific region to sync to (None = broadcast)

        Returns:
            True if sync initiated successfully
        """
        # Update local version tracking
        self._entity_versions[task_id] = time.time()

        # Publish via event bus
        return await self._event_bus.publish_task_update(
            task_id=task_id,
            task_data=task_data,
            event_type=event_type,
        )

    async def sync_agent_state(
        self,
        agent_id: str,
        agent_data: dict[str, Any],
        event_type: RegionalEventType = RegionalEventType.AGENT_UPDATED,
    ) -> bool:
        """
        Synchronize agent state to other regions.

        Args:
            agent_id: Agent identifier
            agent_data: Agent state data to sync
            event_type: Type of agent event

        Returns:
            True if sync initiated successfully
        """
        # Update local version tracking
        self._entity_versions[agent_id] = time.time()

        # Publish via event bus
        return await self._event_bus.publish_agent_update(
            agent_id=agent_id,
            agent_data=agent_data,
            event_type=event_type,
        )

    async def request_full_sync(self, target_region: str) -> bool:
        """
        Request full state sync from a specific region.

        Used during region startup or after network partition recovery.

        Args:
            target_region: Region to request sync from

        Returns:
            True if request sent successfully
        """
        event = RegionalEvent(
            event_type=RegionalEventType.REGION_JOINED,
            source_region=self._event_bus.local_region,
            entity_id=self._event_bus.local_region,
            data={
                "request_type": "full_sync",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        return await self._event_bus.publish(event, target_region=target_region)

    def get_sync_status(self) -> dict[str, Any]:
        """Get synchronization status and metrics."""
        return {
            "local_region": self._event_bus.local_region,
            "entities_tracked": len(self._entity_versions),
            "healthy_regions": self._event_bus.get_healthy_regions(),
            "region_health": self._event_bus.get_region_health(),
            "is_connected": self._event_bus.is_connected,
        }


# Module-level singleton
_regional_event_bus: RegionalEventBus | None = None


def get_regional_event_bus() -> RegionalEventBus | None:
    """Get the global regional event bus instance."""
    return _regional_event_bus


def set_regional_event_bus(bus: RegionalEventBus) -> None:
    """Set the global regional event bus instance."""
    global _regional_event_bus
    _regional_event_bus = bus


async def init_regional_sync(
    redis_url: str = "redis://localhost:6379",
    config: RegionalSyncConfig | None = None,
) -> RegionalEventBus | None:
    """
    Initialize regional synchronization.

    Args:
        redis_url: Redis connection URL
        config: Regional sync configuration

    Returns:
        RegionalEventBus if connected, None otherwise
    """
    bus = RegionalEventBus(redis_url=redis_url, config=config)
    if await bus.connect():
        set_regional_event_bus(bus)
        return bus
    return None
