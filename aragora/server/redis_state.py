"""
Redis-backed state management for horizontal scaling.

Provides distributed state management for WebSocket servers running
across multiple instances. Enables:
- Shared debate state across server instances
- Pub/Sub for real-time event broadcasting
- Session affinity fallback when Redis unavailable

Usage:
    from aragora.server.redis_state import get_redis_state_manager

    state = get_redis_state_manager()
    await state.register_debate("debate-123", {...})

    # Subscribe to cross-instance events
    async for event in state.subscribe("debate:*"):
        print(f"Event: {event}")

Environment Variables:
    ARAGORA_REDIS_URL: Redis connection URL (default: redis://localhost:6379)
    ARAGORA_STATE_BACKEND: "redis" or "memory" (default: "memory")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from collections.abc import AsyncGenerator, Callable

from aragora.exceptions import REDIS_CONNECTION_ERRORS

logger = logging.getLogger(__name__)

# Redis configuration
REDIS_URL = os.environ.get("ARAGORA_REDIS_URL", "redis://localhost:6379")
STATE_BACKEND = os.environ.get("ARAGORA_STATE_BACKEND", "memory").lower()
DEBATE_TTL_SECONDS = 86400  # 24 hours
INSTANCE_ID = os.environ.get("ARAGORA_INSTANCE_ID", f"instance-{os.getpid()}")

# Optional aioredis/redis import
aioredis: Any
try:
    import redis.asyncio as _aioredis

    aioredis = _aioredis
    REDIS_AVAILABLE = True
except ImportError:
    aioredis = None
    REDIS_AVAILABLE = False
    logger.debug("aioredis not available, Redis state backend disabled")


@dataclass
class DebateState:
    """State for an active debate (Redis-serializable)."""

    debate_id: str
    task: str
    agents: list[str]
    start_time: float
    status: str = "running"
    current_round: int = 0
    total_rounds: int = 3
    messages: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    instance_id: str = ""  # Which server instance owns this debate

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "debate_id": self.debate_id,
            "task": self.task,
            "agents": self.agents,
            "start_time": self.start_time,
            "status": self.status,
            "current_round": self.current_round,
            "total_rounds": self.total_rounds,
            "message_count": len(self.messages),
            "elapsed_seconds": time.time() - self.start_time,
            "instance_id": self.instance_id,
        }

    def to_json(self) -> str:
        """Serialize to JSON for Redis storage."""
        data = asdict(self)
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> DebateState:
        """Deserialize from JSON."""
        data = json.loads(json_str)
        return cls(**data)


class RedisStateManager:
    """
    Redis-backed distributed state manager.

    Provides the same interface as the in-memory StateManager but
    stores state in Redis for cross-instance sharing.

    Key Patterns:
        aragora:debate:{debate_id} - Debate state (JSON)
        aragora:debates:active - Set of active debate IDs
        aragora:events - Pub/Sub channel for events
    """

    KEY_PREFIX = "aragora"
    DEBATE_PREFIX = f"{KEY_PREFIX}:debate"
    ACTIVE_DEBATES_KEY = f"{KEY_PREFIX}:debates:active"
    EVENTS_CHANNEL = f"{KEY_PREFIX}:events"

    def __init__(self, redis_url: str = REDIS_URL):
        """Initialize Redis state manager.

        Args:
            redis_url: Redis connection URL
        """
        self._redis_url = redis_url
        self._redis: Any | None = None
        self._pubsub: Any | None = None
        self._instance_id = INSTANCE_ID
        self._server_start_time = time.time()
        self._shutdown_callbacks: list[Callable] = []
        self._connected = False

    async def connect(self) -> bool:
        """Connect to Redis.

        Returns:
            True if connected, False otherwise
        """
        if not REDIS_AVAILABLE or aioredis is None:
            logger.debug("Redis not available (aioredis not installed)")
            return False

        try:
            self._redis = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            # Test connection
            await self._require_redis().ping()
            self._connected = True
            logger.info("Connected to Redis at %s", self._redis_url)
            return True
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("Failed to connect to Redis: %s", e)
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._pubsub:
            await self._pubsub.unsubscribe()
            await self._pubsub.close()
            self._pubsub = None

        if self._redis:
            await self._redis.close()
            self._redis = None

        self._connected = False
        logger.info("Disconnected from Redis")

    @property
    def is_connected(self) -> bool:
        """Check if connected to Redis."""
        return self._connected and self._redis is not None

    def _require_redis(self) -> Any:
        """Return the connected Redis client or fail closed."""
        client = self._redis
        if client is None:
            raise RuntimeError("Redis client not available")
        return client

    @property
    def server_start_time(self) -> float:
        """Get server start timestamp."""
        return self._server_start_time

    @property
    def uptime_seconds(self) -> float:
        """Get server uptime in seconds."""
        return time.time() - self._server_start_time

    # ==================== Debate Management ====================

    async def register_debate(
        self,
        debate_id: str,
        task: str,
        agents: list[str],
        total_rounds: int = 3,
        metadata: dict | None = None,
    ) -> DebateState:
        """Register a new active debate.

        Args:
            debate_id: Unique debate identifier
            task: The debate task/topic
            agents: List of participating agent names
            total_rounds: Total number of debate rounds
            metadata: Optional additional metadata

        Returns:
            The created DebateState
        """
        state = DebateState(
            debate_id=debate_id,
            task=task,
            agents=agents,
            start_time=time.time(),
            total_rounds=total_rounds,
            metadata=metadata or {},
            instance_id=self._instance_id,
        )

        if self.is_connected:
            redis = self._require_redis()
            key = f"{self.DEBATE_PREFIX}:{debate_id}"
            await redis.setex(key, DEBATE_TTL_SECONDS, state.to_json())
            await redis.sadd(self.ACTIVE_DEBATES_KEY, debate_id)

            # Publish event
            await self._publish_event(
                "debate_registered",
                {
                    "debate_id": debate_id,
                    "task": task,
                    "instance_id": self._instance_id,
                },
            )

            logger.debug("Registered debate %s in Redis", debate_id)

        return state

    async def unregister_debate(self, debate_id: str) -> DebateState | None:
        """Unregister a debate when it completes.

        Args:
            debate_id: Debate identifier to remove

        Returns:
            The removed DebateState, or None if not found
        """
        state = await self.get_debate(debate_id)

        if self.is_connected:
            redis = self._require_redis()
            key = f"{self.DEBATE_PREFIX}:{debate_id}"
            await redis.delete(key)
            await redis.srem(self.ACTIVE_DEBATES_KEY, debate_id)

            # Publish event
            await self._publish_event(
                "debate_unregistered",
                {
                    "debate_id": debate_id,
                    "instance_id": self._instance_id,
                },
            )

            logger.debug("Unregistered debate %s from Redis", debate_id)

        return state

    async def get_debate(self, debate_id: str) -> DebateState | None:
        """Get a debate's state by ID."""
        if not self.is_connected:
            return None

        key = f"{self.DEBATE_PREFIX}:{debate_id}"
        data = await self._require_redis().get(key)

        if data:
            return DebateState.from_json(data)
        return None

    async def get_active_debates(self) -> dict[str, DebateState]:
        """Get all active debates."""
        if not self.is_connected:
            return {}

        # Get all active debate IDs
        debate_ids = await self._require_redis().smembers(self.ACTIVE_DEBATES_KEY)
        if not debate_ids:
            return {}

        # Fetch all debate states
        debates = {}
        for debate_id in debate_ids:
            state = await self.get_debate(debate_id)
            if state:
                debates[debate_id] = state

        return debates

    async def get_active_debate_count(self) -> int:
        """Get count of active debates."""
        if not self.is_connected:
            return 0
        return await self._require_redis().scard(self.ACTIVE_DEBATES_KEY)

    async def update_debate_status(
        self,
        debate_id: str,
        status: str | None = None,
        current_round: int | None = None,
    ) -> bool:
        """Update a debate's status.

        Args:
            debate_id: Debate to update
            status: New status (e.g., "running", "completed", "failed")
            current_round: Current round number

        Returns:
            True if update succeeded, False if debate not found
        """
        state = await self.get_debate(debate_id)
        if state is None:
            return False

        if status is not None:
            state.status = status
        if current_round is not None:
            state.current_round = current_round

        # Save updated state
        if self.is_connected:
            key = f"{self.DEBATE_PREFIX}:{debate_id}"
            await self._require_redis().setex(key, DEBATE_TTL_SECONDS, state.to_json())

            # Publish event
            await self._publish_event(
                "debate_updated",
                {
                    "debate_id": debate_id,
                    "status": status,
                    "current_round": current_round,
                    "instance_id": self._instance_id,
                },
            )

        return True

    async def add_debate_message(self, debate_id: str, message: Any) -> bool:
        """Add a message to a debate's history.

        Args:
            debate_id: Debate to update
            message: Message to add

        Returns:
            True if update succeeded, False if debate not found
        """
        state = await self.get_debate(debate_id)
        if state is None:
            return False

        state.messages.append(message)

        # Save updated state
        if self.is_connected:
            key = f"{self.DEBATE_PREFIX}:{debate_id}"
            await self._require_redis().setex(key, DEBATE_TTL_SECONDS, state.to_json())

            # Publish event for real-time broadcast
            await self._publish_event(
                "debate_message",
                {
                    "debate_id": debate_id,
                    "message": message if isinstance(message, dict) else str(message),
                    "instance_id": self._instance_id,
                },
            )

        return True

    # ==================== Pub/Sub ====================

    async def _publish_event(self, event_type: str, data: dict) -> None:
        """Publish an event to the events channel."""
        if not self.is_connected:
            return

        event = {
            "type": event_type,
            "data": data,
            "timestamp": time.time(),
            "instance_id": self._instance_id,
        }
        await self._require_redis().publish(self.EVENTS_CHANNEL, json.dumps(event))

    async def subscribe(self, pattern: str = "*") -> AsyncGenerator[dict, None]:
        """Subscribe to events matching a pattern.

        Args:
            pattern: Event pattern to subscribe to (e.g., "debate:*")

        Yields:
            Event dictionaries
        """
        if not self.is_connected:
            return

        pubsub = self._require_redis().pubsub()
        self._pubsub = pubsub
        await pubsub.subscribe(self.EVENTS_CHANNEL)

        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        event = json.loads(message["data"])
                        # Filter by pattern if specified
                        if pattern == "*" or event.get("type", "").startswith(pattern.rstrip("*")):
                            yield event
                    except json.JSONDecodeError:
                        logger.warning("Invalid event JSON: %s", message["data"])
        finally:
            await pubsub.unsubscribe()

    # ==================== Health & Metrics ====================

    async def health_check(self) -> dict:
        """Perform health check on Redis connection."""
        result = {
            "backend": "redis",
            "connected": self.is_connected,
            "instance_id": self._instance_id,
            "uptime_seconds": self.uptime_seconds,
        }

        if self.is_connected:
            try:
                start = time.time()
                await self._require_redis().ping()
                result["ping_ms"] = (time.time() - start) * 1000
                result["active_debates"] = await self.get_active_debate_count()
            except REDIS_CONNECTION_ERRORS as e:
                logger.warning("Redis state health check failed: %s", e)
                result["error"] = "Redis health check failed"
                result["connected"] = False

        return result


# Singleton instance and lock for async-safe access
_redis_state_manager: RedisStateManager | None = None
_redis_state_lock: asyncio.Lock | None = None


def _get_redis_state_lock() -> asyncio.Lock:
    """Get or create the asyncio lock (lazy initialization)."""
    global _redis_state_lock
    if _redis_state_lock is None:
        _redis_state_lock = asyncio.Lock()
    return _redis_state_lock


async def get_redis_state_manager(
    redis_url: str | None = None,
    auto_connect: bool = True,
) -> RedisStateManager:
    """Get or create the global Redis state manager.

    Args:
        redis_url: Optional Redis URL override
        auto_connect: Whether to automatically connect

    Returns:
        RedisStateManager instance
    """
    global _redis_state_manager

    # Fast path: return existing instance without lock
    if _redis_state_manager is not None:
        return _redis_state_manager

    # Slow path: acquire lock and create instance
    async with _get_redis_state_lock():
        # Double-check after acquiring lock
        if _redis_state_manager is None:
            _redis_state_manager = RedisStateManager(redis_url or REDIS_URL)

            if auto_connect:
                await _redis_state_manager.connect()

    return _redis_state_manager


async def reset_redis_state_manager() -> None:
    """Reset the global Redis state manager (for testing)."""
    global _redis_state_manager

    async with _get_redis_state_lock():
        if _redis_state_manager is not None:
            await _redis_state_manager.disconnect()
            _redis_state_manager = None


def is_redis_state_enabled() -> bool:
    """Check if Redis state backend is enabled via environment."""
    return STATE_BACKEND == "redis" and REDIS_AVAILABLE


__all__ = [
    "DebateState",
    "RedisStateManager",
    "get_redis_state_manager",
    "reset_redis_state_manager",
    "is_redis_state_enabled",
    "REDIS_AVAILABLE",
]
