"""
Control Plane Distributed Policy Cache (Redis-backed).

Provides fast lookups for frequently evaluated policy decisions.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from types import ModuleType
from typing import Any

from aragora.observability import get_logger
from aragora.exceptions import REDIS_CONNECTION_ERRORS

_REDIS_AND_JSON_ERRORS: tuple[type[Exception], ...] = (
    *REDIS_CONNECTION_ERRORS,
    json.JSONDecodeError,
)
_REDIS_AND_TYPE_ERRORS: tuple[type[Exception], ...] = (*REDIS_CONNECTION_ERRORS, TypeError)

from .types import (
    EnforcementLevel,
    PolicyDecision,
    PolicyEvaluationResult,
)

logger = get_logger(__name__)

# Pre-declare optional import with module type annotation
aioredis: ModuleType | None = None

# Redis availability check (optional - for distributed cache)
try:
    aioredis = importlib.import_module("redis.asyncio")

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class RedisPolicyCache:
    """
    Redis-backed cache for policy evaluation results.

    Provides fast lookups for frequently evaluated policy decisions,
    reducing repeated policy evaluation overhead in distributed deployments.

    Cache keys are based on the evaluation context hash (task_type + agent + region + workspace).
    Cache entries expire after a configurable TTL.

    Usage:
        cache = RedisPolicyCache(redis_url="redis://localhost:6379")
        await cache.connect()

        # Check cache before evaluation
        cached = await cache.get(task_type="debate", agent_id="claude", region="us-east-1")
        if cached:
            return cached

        # Evaluate and cache result
        result = policy_manager.evaluate_task_dispatch(...)
        await cache.set(result, task_type="debate", agent_id="claude", region="us-east-1")
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "aragora:policy_cache:",
        ttl_seconds: int = 300,
        enabled: bool = True,
    ):
        """
        Initialize the policy cache.

        Args:
            redis_url: Redis connection URL
            key_prefix: Prefix for cache keys
            ttl_seconds: Time-to-live for cache entries
            enabled: Whether caching is enabled
        """
        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._ttl_seconds = ttl_seconds
        self._enabled = enabled
        self._redis: Any | None = None
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "errors": 0,
        }

    async def connect(self) -> bool:
        """
        Connect to Redis.

        Returns:
            True if connected successfully, False otherwise
        """
        # Check REDIS_AVAILABLE from the package level for patchability
        import aragora.control_plane.policy as _policy_pkg

        redis_available = getattr(_policy_pkg, "REDIS_AVAILABLE", REDIS_AVAILABLE)
        if not self._enabled or not redis_available:
            logger.debug("Policy cache disabled or Redis not available")
            return False

        try:
            self._redis = aioredis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info("policy_cache_connected", redis_url=self._redis_url)
            return True
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("policy_cache_connection_failed", error=str(e))
            self._redis = None
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    def _make_cache_key(
        self,
        task_type: str,
        agent_id: str,
        region: str,
        workspace: str | None = None,
        policy_version: str | None = None,
    ) -> str:
        """Generate a cache key from evaluation context."""
        components = [
            task_type,
            agent_id,
            region,
            workspace or "_default_",
            policy_version or "_current_",
        ]
        key_data = ":".join(components)
        key_hash = hashlib.sha256(key_data.encode()).hexdigest()[:16]
        return f"{self._key_prefix}{key_hash}"

    async def get(
        self,
        task_type: str,
        agent_id: str,
        region: str,
        workspace: str | None = None,
        policy_version: str | None = None,
    ) -> PolicyEvaluationResult | None:
        """
        Get cached evaluation result.

        Args:
            task_type: Task type from evaluation
            agent_id: Agent ID from evaluation
            region: Region from evaluation
            workspace: Workspace from evaluation
            policy_version: Version hash of current policies (for invalidation)

        Returns:
            Cached PolicyEvaluationResult if found and valid, None otherwise
        """
        if not self._redis:
            return None

        try:
            key = self._make_cache_key(task_type, agent_id, region, workspace, policy_version)
            data = await self._redis.get(key)

            if data:
                self._stats["hits"] += 1
                cached_dict = json.loads(data)
                return PolicyEvaluationResult(
                    decision=PolicyDecision(cached_dict["decision"]),
                    allowed=cached_dict["allowed"],
                    policy_id=cached_dict["policy_id"],
                    policy_name=cached_dict["policy_name"],
                    reason=cached_dict["reason"],
                    enforcement_level=EnforcementLevel(cached_dict["enforcement_level"]),
                    task_type=cached_dict.get("task_type"),
                    agent_id=cached_dict.get("agent_id"),
                    region=cached_dict.get("region"),
                    sla_violation=cached_dict.get("sla_violation"),
                )

            self._stats["misses"] += 1
            return None

        except _REDIS_AND_JSON_ERRORS as e:  # type: ignore[misc]
            self._stats["errors"] += 1
            logger.debug("policy_cache_get_error", error=str(e))
            return None

    async def set(
        self,
        result: PolicyEvaluationResult,
        task_type: str,
        agent_id: str,
        region: str,
        workspace: str | None = None,
        policy_version: str | None = None,
    ) -> bool:
        """
        Cache an evaluation result.

        Args:
            result: The evaluation result to cache
            task_type: Task type from evaluation
            agent_id: Agent ID from evaluation
            region: Region from evaluation
            workspace: Workspace from evaluation
            policy_version: Version hash of current policies

        Returns:
            True if cached successfully, False otherwise
        """
        if not self._redis:
            return False

        try:
            key = self._make_cache_key(task_type, agent_id, region, workspace, policy_version)
            data = json.dumps(result.to_dict())
            await self._redis.setex(key, self._ttl_seconds, data)
            self._stats["sets"] += 1
            return True

        except _REDIS_AND_TYPE_ERRORS as e:  # type: ignore[misc]
            self._stats["errors"] += 1
            logger.debug("policy_cache_set_error", error=str(e))
            return False

    async def invalidate_all(self) -> int:
        """
        Invalidate all cached policy results.

        Call this after policy changes to ensure fresh evaluations.

        Returns:
            Number of keys deleted
        """
        if not self._redis:
            return 0

        try:
            pattern = f"{self._key_prefix}*"
            deleted = 0
            async for key in self._redis.scan_iter(match=pattern):
                await self._redis.delete(key)
                deleted += 1
            logger.info("policy_cache_invalidated", deleted=deleted)
            return deleted
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("policy_cache_invalidate_error", error=str(e))
            return 0

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = self._stats["hits"] + self._stats["misses"]
        hit_rate = self._stats["hits"] / total if total > 0 else 0.0
        return {
            **self._stats,
            "hit_rate": hit_rate,
            "connected": self._redis is not None,
        }
