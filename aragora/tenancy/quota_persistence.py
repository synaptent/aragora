"""
Redis-backed Quota Persistence.

Provides distributed quota tracking via Redis with in-memory fallback,
enabling consistent quota enforcement across multiple server instances.

Features:
- Atomic increment/decrement operations via Lua scripts
- Automatic TTL based on quota period
- In-memory fallback when Redis unavailable
- Cross-instance quota sharing

Usage:
    from aragora.tenancy.quota_persistence import (
        QuotaPersistence,
        get_quota_persistence,
    )

    persistence = get_quota_persistence()

    # Increment usage atomically
    new_count = await persistence.increment(
        tenant_id="tenant-123",
        resource="api_requests",
        amount=1,
        period="minute",
    )

    # Check current usage
    usage = await persistence.get_usage(
        tenant_id="tenant-123",
        resource="api_requests",
        period="minute",
    )
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Configuration
REDIS_KEY_PREFIX = os.environ.get("ARAGORA_QUOTA_KEY_PREFIX", "aragora:quota")
ENABLE_REDIS_QUOTAS = os.environ.get("ARAGORA_QUOTA_REDIS_ENABLED", "true").lower() == "true"


class QuotaPeriod(str, Enum):
    """Time period for quota limits (mirrors quotas.py)."""

    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    UNLIMITED = "unlimited"

    @property
    def ttl_seconds(self) -> int:
        """Get TTL for this period (with buffer)."""
        ttls = {
            QuotaPeriod.MINUTE: 120,  # 2 minutes
            QuotaPeriod.HOUR: 7200,  # 2 hours
            QuotaPeriod.DAY: 172800,  # 2 days
            QuotaPeriod.WEEK: 1209600,  # 2 weeks
            QuotaPeriod.MONTH: 5184000,  # 60 days
            QuotaPeriod.UNLIMITED: 0,  # No expiry
        }
        return ttls.get(self, 86400)


@dataclass
class QuotaUsage:
    """Current quota usage."""

    tenant_id: str
    resource: str
    period: QuotaPeriod
    count: int
    period_key: str
    expires_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "tenant_id": self.tenant_id,
            "resource": self.resource,
            "period": self.period.value,
            "count": self.count,
            "period_key": self.period_key,
            "expires_at": self.expires_at,
        }


def _get_period_key(period: QuotaPeriod) -> str:
    """Get a key for the current period."""
    now = datetime.now()
    if period == QuotaPeriod.MINUTE:
        return now.strftime("%Y%m%d%H%M")
    if period == QuotaPeriod.HOUR:
        return now.strftime("%Y%m%d%H")
    if period == QuotaPeriod.DAY:
        return now.strftime("%Y%m%d")
    if period == QuotaPeriod.WEEK:
        return f"{now.year}W{now.isocalendar()[1]:02d}"
    if period == QuotaPeriod.MONTH:
        return now.strftime("%Y%m")
    return "unlimited"


def _build_redis_key(tenant_id: str, resource: str, period: QuotaPeriod) -> str:
    """Build Redis key for quota tracking."""
    period_key = _get_period_key(period)
    return f"{REDIS_KEY_PREFIX}:{tenant_id}:{resource}:{period.value}:{period_key}"


# Lua script for atomic increment with TTL
LUA_INCREMENT = """
local key = KEYS[1]
local amount = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

local current = redis.call('INCRBY', key, amount)

-- Set TTL only if this is a new key (current == amount)
if current == amount and ttl > 0 then
    redis.call('EXPIRE', key, ttl)
end

return current
"""

# Lua script for decrement (floor at 0)
LUA_DECREMENT = """
local key = KEYS[1]
local amount = tonumber(ARGV[1])

local current = tonumber(redis.call('GET', key) or 0)
local new_value = math.max(0, current - amount)
redis.call('SET', key, new_value, 'KEEPTTL')

return new_value
"""


class QuotaPersistence:
    """Redis-backed quota persistence with in-memory fallback.

    Provides distributed quota tracking that survives server restarts
    and enables consistent enforcement across multiple instances.
    """

    def __init__(self, redis_client: Any | None = None):
        """Initialize quota persistence.

        Args:
            redis_client: Redis client (async). If None, attempts to get global client.
        """
        self._redis = redis_client
        self._redis_checked = False
        self._redis_scripts: dict[str, Any] = {}

        # In-memory fallback (stores both count:int and period_key:str)
        self._memory: dict[str, dict[str, Any]] = defaultdict(dict)
        self._memory_expiry: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def _get_redis(self) -> Any | None:
        """Get Redis client (lazy initialization)."""
        if not ENABLE_REDIS_QUOTAS:
            return None

        if self._redis_checked:
            return self._redis

        try:
            # Try to get async redis client
            from aragora.utils.redis_config import get_async_redis_client

            self._redis = await get_async_redis_client()
            if self._redis:
                # Register Lua scripts
                await self._register_scripts()
                logger.debug("QuotaPersistence: using Redis backend")
            else:
                logger.debug("QuotaPersistence: using in-memory fallback (Redis unavailable)")
        except ImportError:
            logger.debug("QuotaPersistence: using in-memory fallback (redis_config not available)")
        except (ConnectionError, OSError, RuntimeError) as e:
            logger.warning("QuotaPersistence: Redis init failed, using fallback: %s", e)

        self._redis_checked = True
        return self._redis

    async def _register_scripts(self) -> None:
        """Register Lua scripts with Redis."""
        if self._redis:
            try:
                self._redis_scripts["increment"] = self._redis.register_script(LUA_INCREMENT)
                self._redis_scripts["decrement"] = self._redis.register_script(LUA_DECREMENT)
            except (ConnectionError, OSError, RuntimeError) as e:
                logger.warning("Failed to register Lua scripts: %s", e)

    async def increment(
        self,
        tenant_id: str,
        resource: str,
        amount: int = 1,
        period: QuotaPeriod | str = QuotaPeriod.MINUTE,
    ) -> int:
        """Atomically increment quota usage.

        Args:
            tenant_id: Tenant identifier
            resource: Resource name (e.g., "api_requests")
            amount: Amount to increment
            period: Quota period

        Returns:
            New usage count after increment
        """
        if isinstance(period, str):
            period = QuotaPeriod(period)

        redis = await self._get_redis()

        if redis:
            try:
                key = _build_redis_key(tenant_id, resource, period)
                ttl = period.ttl_seconds

                if "increment" in self._redis_scripts:
                    return await self._redis_scripts["increment"](keys=[key], args=[amount, ttl])
                else:
                    # Fallback without Lua script
                    new_count = await redis.incrby(key, amount)
                    if new_count == amount and ttl > 0:
                        await redis.expire(key, ttl)
                    return new_count
            except (ConnectionError, OSError, TypeError, ValueError) as e:
                logger.warning("Redis increment failed, using fallback: %s", e)

        # In-memory fallback
        return await self._memory_increment(tenant_id, resource, amount, period)

    async def decrement(
        self,
        tenant_id: str,
        resource: str,
        amount: int = 1,
        period: QuotaPeriod | str = QuotaPeriod.MINUTE,
    ) -> int:
        """Atomically decrement quota usage (floors at 0).

        Args:
            tenant_id: Tenant identifier
            resource: Resource name
            amount: Amount to decrement
            period: Quota period

        Returns:
            New usage count after decrement
        """
        if isinstance(period, str):
            period = QuotaPeriod(period)

        redis = await self._get_redis()

        if redis:
            try:
                key = _build_redis_key(tenant_id, resource, period)

                if "decrement" in self._redis_scripts:
                    return await self._redis_scripts["decrement"](keys=[key], args=[amount])
                else:
                    # Fallback without Lua script
                    current = int(await redis.get(key) or 0)
                    new_val = max(0, current - amount)
                    await redis.set(key, new_val, keepttl=True)
                    return new_val
            except (ConnectionError, OSError, TypeError, ValueError) as e:
                logger.warning("Redis decrement failed, using fallback: %s", e)

        # In-memory fallback
        return await self._memory_decrement(tenant_id, resource, amount, period)

    async def get_usage(
        self,
        tenant_id: str,
        resource: str,
        period: QuotaPeriod | str = QuotaPeriod.MINUTE,
    ) -> QuotaUsage:
        """Get current quota usage.

        Args:
            tenant_id: Tenant identifier
            resource: Resource name
            period: Quota period

        Returns:
            Current usage information
        """
        if isinstance(period, str):
            period = QuotaPeriod(period)

        period_key = _get_period_key(period)
        redis = await self._get_redis()
        count = 0
        expires_at = None

        if redis:
            try:
                key = _build_redis_key(tenant_id, resource, period)
                count = int(await redis.get(key) or 0)
                ttl = await redis.ttl(key)
                if ttl > 0:
                    expires_at = time.time() + ttl
            except (ConnectionError, OSError, TypeError, ValueError) as e:
                logger.warning("Redis get_usage failed, using fallback: %s", e)
                count = await self._memory_get(tenant_id, resource, period)
        else:
            count = await self._memory_get(tenant_id, resource, period)

        return QuotaUsage(
            tenant_id=tenant_id,
            resource=resource,
            period=period,
            count=count,
            period_key=period_key,
            expires_at=expires_at,
        )

    async def set_usage(
        self,
        tenant_id: str,
        resource: str,
        count: int,
        period: QuotaPeriod | str = QuotaPeriod.MINUTE,
    ) -> None:
        """Set quota usage to a specific value.

        Args:
            tenant_id: Tenant identifier
            resource: Resource name
            count: New usage count
            period: Quota period
        """
        if isinstance(period, str):
            period = QuotaPeriod(period)

        redis = await self._get_redis()

        if redis:
            try:
                key = _build_redis_key(tenant_id, resource, period)
                ttl = period.ttl_seconds
                if ttl > 0:
                    await redis.setex(key, ttl, count)
                else:
                    await redis.set(key, count)
                return
            except (ConnectionError, OSError, TypeError, ValueError) as e:
                logger.warning("Redis set_usage failed, using fallback: %s", e)

        # In-memory fallback
        await self._memory_set(tenant_id, resource, count, period)

    async def reset_usage(
        self,
        tenant_id: str,
        resource: str | None = None,
        period: QuotaPeriod | str | None = None,
    ) -> int:
        """Reset quota usage for a tenant.

        Args:
            tenant_id: Tenant identifier
            resource: Optional resource filter (None = all)
            period: Optional period filter (None = all)

        Returns:
            Number of keys reset
        """
        if isinstance(period, str):
            period = QuotaPeriod(period)

        redis = await self._get_redis()
        reset_count = 0

        if redis:
            try:
                # Build pattern for matching keys
                pattern_parts = [REDIS_KEY_PREFIX, tenant_id]
                if resource:
                    pattern_parts.append(resource)
                else:
                    pattern_parts.append("*")
                if period:
                    pattern_parts.append(period.value)
                else:
                    pattern_parts.append("*")
                pattern_parts.append("*")
                pattern = ":".join(pattern_parts)

                # Use SCAN to find and delete matching keys
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(cursor, match=pattern, count=100)
                    if keys:
                        await redis.delete(*keys)
                        reset_count += len(keys)
                    if cursor == 0:
                        break
            except (ConnectionError, OSError, TypeError, ValueError) as e:
                logger.warning("Redis reset_usage failed: %s", e)

        # Also reset in-memory
        async with self._lock:
            keys_to_delete = []
            for key in self._memory.keys():
                parts = key.split(":")
                if len(parts) >= 2 and parts[0] == tenant_id:
                    if resource and parts[1] != resource:
                        continue
                    if period and len(parts) >= 3 and parts[2] != period.value:
                        continue
                    keys_to_delete.append(key)

            for key in keys_to_delete:
                del self._memory[key]
                reset_count += 1

        return reset_count

    async def get_all_usage(self, tenant_id: str) -> list[QuotaUsage]:
        """Get all quota usage for a tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            List of all usage records
        """
        usages: list[QuotaUsage] = []
        redis = await self._get_redis()

        if redis:
            try:
                pattern = f"{REDIS_KEY_PREFIX}:{tenant_id}:*"
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(cursor, match=pattern, count=100)
                    for key in keys:
                        # Parse key: prefix:tenant:resource:period:period_key
                        parts = key.split(":")
                        if len(parts) >= 5:
                            resource = parts[2]
                            period = QuotaPeriod(parts[3])
                            period_key = parts[4]
                            count = int(await redis.get(key) or 0)
                            ttl = await redis.ttl(key)
                            usages.append(
                                QuotaUsage(
                                    tenant_id=tenant_id,
                                    resource=resource,
                                    period=period,
                                    count=count,
                                    period_key=period_key,
                                    expires_at=time.time() + ttl if ttl > 0 else None,
                                )
                            )
                    if cursor == 0:
                        break
            except (ConnectionError, OSError, TypeError, ValueError) as e:
                logger.warning("Redis get_all_usage failed: %s", e)

        return usages

    # -------------------------------------------------------------------------
    # In-memory fallback methods
    # -------------------------------------------------------------------------

    async def _memory_increment(
        self, tenant_id: str, resource: str, amount: int, period: QuotaPeriod
    ) -> int:
        """In-memory increment with expiry tracking."""
        key = f"{tenant_id}:{resource}:{period.value}"
        period_key = _get_period_key(period)
        full_key = f"{key}:{period_key}"

        async with self._lock:
            # Check if we need to reset (new period)
            stored_period = self._memory.get(key, {}).get("period_key")
            if stored_period != period_key:
                self._memory[key] = {"count": 0, "period_key": period_key}

            self._memory[key]["count"] = self._memory[key].get("count", 0) + amount

            # Set expiry
            if period.ttl_seconds > 0:
                self._memory_expiry[full_key] = time.time() + period.ttl_seconds

            return self._memory[key]["count"]

    async def _memory_decrement(
        self, tenant_id: str, resource: str, amount: int, period: QuotaPeriod
    ) -> int:
        """In-memory decrement."""
        key = f"{tenant_id}:{resource}:{period.value}"

        async with self._lock:
            current = self._memory[key].get("count", 0)
            new_val = max(0, current - amount)
            self._memory[key]["count"] = new_val
            return new_val

    async def _memory_get(self, tenant_id: str, resource: str, period: QuotaPeriod) -> int:
        """In-memory get."""
        key = f"{tenant_id}:{resource}:{period.value}"
        period_key = _get_period_key(period)

        async with self._lock:
            data = self._memory.get(key, {})
            if data.get("period_key") != period_key:
                return 0
            return data.get("count", 0)

    async def _memory_set(
        self, tenant_id: str, resource: str, count: int, period: QuotaPeriod
    ) -> None:
        """In-memory set."""
        key = f"{tenant_id}:{resource}:{period.value}"
        period_key = _get_period_key(period)

        async with self._lock:
            self._memory[key] = {"count": count, "period_key": period_key}

    @property
    def is_using_redis(self) -> bool:
        """Check if Redis is being used."""
        return self._redis is not None


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

_persistence: QuotaPersistence | None = None
_lock = asyncio.Lock()


async def get_quota_persistence() -> QuotaPersistence:
    """Get or create the global quota persistence instance."""
    global _persistence
    if _persistence is None:
        async with _lock:
            if _persistence is None:
                _persistence = QuotaPersistence()
    return _persistence


def reset_quota_persistence() -> None:
    """Reset the global quota persistence (for testing)."""
    global _persistence
    _persistence = None


__all__ = [
    "QuotaPersistence",
    "QuotaPeriod",
    "QuotaUsage",
    "get_quota_persistence",
    "reset_quota_persistence",
]
