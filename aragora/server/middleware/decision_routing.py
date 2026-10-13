"""
Decision Routing Middleware.

Provides unified routing of incoming requests through the DecisionRouter,
ensuring consistent handling across all channels (Slack, Teams, Discord,
Telegram, WhatsApp, Email, Web, API).

Features:
- Unified deduplication across channels
- Response caching at router level
- Origin tracking for bidirectional routing
- Consistent error handling

Usage:
    from aragora.server.middleware.decision_routing import (
        route_decision,
        get_decision_router,
        DecisionRoutingMiddleware,
    )

    # As a decorator
    @route_decision(channel="slack")
    async def handle_slack_message(request):
        ...

    # As middleware
    middleware = DecisionRoutingMiddleware(router)
    result = await middleware.process(request)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Literal, TypeVar, cast
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Type variables
F = TypeVar("F", bound=Callable[..., Any])

# Deduplication window (5 seconds)
DEDUPE_WINDOW_SECONDS = 5.0

# Response cache TTL (1 hour)
CACHE_TTL_SECONDS = 3600.0


@dataclass
class RoutingContext:
    """Context for a routed request."""

    channel: str  # slack, teams, discord, telegram, whatsapp, email, web, api
    channel_id: str  # Channel/chat ID
    user_id: str  # User who sent the request
    request_id: str  # Unique request ID
    message_id: str | None = None  # Original message ID
    thread_id: str | None = None  # Thread ID if threaded
    workspace_id: str | None = None  # Workspace/org ID
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "channel_id": self.channel_id,
            "user_id": self.user_id,
            "request_id": self.request_id,
            "message_id": self.message_id,
            "thread_id": self.thread_id,
            "workspace_id": self.workspace_id,
            "metadata": self.metadata,
        }


class RequestDeduplicator:
    """
    Deduplicates identical requests across all channels.

    Uses content hashing to detect duplicate requests within a time window.
    This prevents double-processing when the same message is received
    multiple times (e.g., webhook retries, multi-device delivery).
    """

    def __init__(self, window_seconds: float = DEDUPE_WINDOW_SECONDS):
        self._window_seconds = window_seconds
        self._seen: dict[str, float] = {}  # hash -> timestamp
        self._in_flight: dict[str, asyncio.Future] = {}  # hash -> future
        self._lock = asyncio.Lock()

    def _compute_hash(self, content: str, user_id: str, channel: str) -> str:
        """Compute a deduplication hash."""
        data = f"{channel}:{user_id}:{content}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]

    async def check_and_mark(
        self,
        content: str,
        user_id: str,
        channel: str,
    ) -> tuple[bool, asyncio.Future | None]:
        """
        Check if this request is a duplicate.

        Returns:
            Tuple of (is_duplicate, optional_future_to_await)
            If is_duplicate is True and future is not None, await the future
            to get the result of the in-flight request.
        """
        request_hash = self._compute_hash(content, user_id, channel)
        now = time.time()

        async with self._lock:
            # Clean up old entries
            expired = [h for h, ts in self._seen.items() if now - ts > self._window_seconds]
            for h in expired:
                del self._seen[h]
                self._in_flight.pop(h, None)

            # Check if already seen
            if request_hash in self._seen:
                logger.debug("Duplicate request detected: %s...", request_hash[:8])
                # Return the in-flight future if available
                return True, self._in_flight.get(request_hash)

            # Mark as seen and create in-flight future
            self._seen[request_hash] = now
            self._in_flight[request_hash] = asyncio.get_running_loop().create_future()
            return False, None

    async def complete(
        self,
        content: str,
        user_id: str,
        channel: str,
        result: Any,
    ) -> None:
        """Mark a request as complete and resolve any waiting duplicates."""
        request_hash = self._compute_hash(content, user_id, channel)

        async with self._lock:
            future = self._in_flight.get(request_hash)
            if future and not future.done():
                future.set_result(result)

    async def fail(
        self,
        content: str,
        user_id: str,
        channel: str,
        error: Exception,
    ) -> None:
        """Mark a request as failed."""
        request_hash = self._compute_hash(content, user_id, channel)

        async with self._lock:
            future = self._in_flight.get(request_hash)
            if future and not future.done():
                future.set_exception(error)
            # Remove from seen so retries work
            self._seen.pop(request_hash, None)
            self._in_flight.pop(request_hash, None)


@dataclass
class CacheEntry:
    """A cache entry with metadata for invalidation."""

    result: Any
    timestamp: float
    workspace_id: str | None = None
    policy_version: str | None = None
    agent_versions: dict[str, str] | None = None
    tags: list[str] = field(default_factory=list)

    def matches_tag(self, tag: str) -> bool:
        """Check if entry has a specific tag."""
        return tag in self.tags

    def matches_workspace(self, workspace_id: str) -> bool:
        """Check if entry belongs to a workspace."""
        return self.workspace_id == workspace_id


class ResponseCache:
    """
    Caches responses for identical queries with support for invalidation.

    Features:
    - Content + context hashing for cache keys
    - Tagged entries for selective invalidation
    - Workspace-scoped invalidation
    - Policy version tracking
    - Cache statistics and monitoring
    """

    def __init__(self, ttl_seconds: float = CACHE_TTL_SECONDS, max_size: int = 1000):
        self._ttl_seconds = ttl_seconds
        self._max_size = max_size
        self._cache: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

        # Statistics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._invalidations = 0

        # Current policy version (updated on governance changes)
        self._policy_version: str | None = None

    def _compute_hash(self, content: str, context: dict[str, Any] | None = None) -> str:
        """Compute a cache key hash."""
        ctx_str = json.dumps(context, sort_keys=True) if context else ""
        data = f"{content}:{ctx_str}"
        return hashlib.sha256(data.encode()).hexdigest()[:32]

    async def get(
        self,
        content: str,
        context: dict[str, Any] | None = None,
    ) -> Any | None:
        """Get a cached response if available."""
        cache_key = self._compute_hash(content, context)
        now = time.time()

        async with self._lock:
            if cache_key in self._cache:
                entry = self._cache[cache_key]

                # Check TTL
                if now - entry.timestamp >= self._ttl_seconds:
                    del self._cache[cache_key]
                    self._misses += 1
                    return None

                # Check policy version (invalidate if policy changed)
                if self._policy_version and entry.policy_version != self._policy_version:
                    del self._cache[cache_key]
                    self._invalidations += 1
                    self._misses += 1
                    logger.debug("Cache invalidated due to policy change: %s...", cache_key[:8])
                    return None

                self._hits += 1
                logger.debug("Cache hit for: %s...", cache_key[:8])
                return entry.result

            self._misses += 1
            return None

    async def set(
        self,
        content: str,
        result: Any,
        context: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        agent_versions: dict[str, str] | None = None,
    ) -> None:
        """
        Cache a response with metadata.

        Args:
            content: The query content
            result: The result to cache
            context: Context dict (channel, workspace_id, etc.)
            tags: Optional tags for selective invalidation
            agent_versions: Optional dict of agent name -> version
        """
        cache_key = self._compute_hash(content, context)
        now = time.time()

        workspace_id = context.get("workspace_id") if context else None

        entry = CacheEntry(
            result=result,
            timestamp=now,
            workspace_id=workspace_id,
            policy_version=self._policy_version,
            agent_versions=agent_versions,
            tags=tags or [],
        )

        async with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self._max_size and cache_key not in self._cache:
                oldest_key = min(self._cache, key=lambda k: self._cache[k].timestamp)
                del self._cache[oldest_key]
                self._evictions += 1

            self._cache[cache_key] = entry

    async def clear(self) -> int:
        """Clear the entire cache. Returns number of entries cleared."""
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._invalidations += count
            return count

    async def invalidate_by_workspace(self, workspace_id: str) -> int:
        """
        Invalidate all cache entries for a specific workspace.

        Args:
            workspace_id: The workspace to invalidate

        Returns:
            Number of entries invalidated
        """
        async with self._lock:
            keys_to_remove = [
                k for k, v in self._cache.items() if v.matches_workspace(workspace_id)
            ]
            for key in keys_to_remove:
                del self._cache[key]

            self._invalidations += len(keys_to_remove)
            logger.info(
                "Invalidated %s cache entries for workspace %s", len(keys_to_remove), workspace_id
            )
            return len(keys_to_remove)

    async def invalidate_by_tag(self, tag: str) -> int:
        """
        Invalidate all cache entries with a specific tag.

        Args:
            tag: The tag to match

        Returns:
            Number of entries invalidated
        """
        async with self._lock:
            keys_to_remove = [k for k, v in self._cache.items() if v.matches_tag(tag)]
            for key in keys_to_remove:
                del self._cache[key]

            self._invalidations += len(keys_to_remove)
            logger.info("Invalidated %s cache entries with tag '%s'", len(keys_to_remove), tag)
            return len(keys_to_remove)

    async def invalidate_by_agent_version(self, agent_name: str, old_version: str) -> int:
        """
        Invalidate cache entries using a specific agent version.

        Useful when an agent is upgraded and old cached results should be discarded.

        Args:
            agent_name: Name of the agent
            old_version: The old version to invalidate

        Returns:
            Number of entries invalidated
        """
        async with self._lock:
            keys_to_remove = []
            for key, entry in self._cache.items():
                if entry.agent_versions:
                    if entry.agent_versions.get(agent_name) == old_version:
                        keys_to_remove.append(key)

            for key in keys_to_remove:
                del self._cache[key]

            self._invalidations += len(keys_to_remove)
            logger.info(
                "Invalidated %s cache entries for agent %s version %s",
                len(keys_to_remove),
                agent_name,
                old_version,
            )
            return len(keys_to_remove)

    def set_policy_version(self, version: str) -> None:
        """
        Update the current policy version.

        This will cause cache entries with old policy versions to be
        invalidated on next access (lazy invalidation).

        Args:
            version: New policy version string
        """
        old_version = self._policy_version
        self._policy_version = version
        logger.info("Policy version updated: %s -> %s", old_version, version)

    async def get_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dict with cache stats including hits, misses, hit rate, etc.
        """
        async with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0

            # Count entries by workspace
            workspace_counts: dict[str, int] = {}
            for entry in self._cache.values():
                ws = entry.workspace_id or "none"
                workspace_counts[ws] = workspace_counts.get(ws, 0) + 1

            return {
                "size": len(self._cache),
                "max_size": self._max_size,
                "ttl_seconds": self._ttl_seconds,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 4),
                "evictions": self._evictions,
                "invalidations": self._invalidations,
                "policy_version": self._policy_version,
                "entries_by_workspace": workspace_counts,
            }


class DecisionRoutingMiddleware:
    """
    Middleware that routes requests through DecisionRouter.

    Provides:
    - Unified entry point for all channels
    - Request deduplication
    - Response caching
    - Origin tracking for bidirectional routing
    - Metrics and tracing
    """

    def __init__(
        self,
        enable_deduplication: bool = True,
        enable_caching: bool = True,
        dedupe_window: float = DEDUPE_WINDOW_SECONDS,
        cache_ttl: float = CACHE_TTL_SECONDS,
    ):
        self._enable_deduplication = enable_deduplication
        self._enable_caching = enable_caching
        self._deduplicator = RequestDeduplicator(dedupe_window) if enable_deduplication else None
        self._cache = ResponseCache(cache_ttl) if enable_caching else None
        self._router = None  # Lazy loaded
        self._unified_router = None  # Lazy loaded

    def _get_router(self):
        """Get or create the DecisionRouter."""
        if self._router is None:
            try:
                from aragora.core.decision import DecisionRouter

                self._router = DecisionRouter()
            except ImportError:
                logger.debug("DecisionRouter not available")
        return self._router

    def _get_unified_router(self):
        """Get or create the UnifiedDecisionRouter."""
        if self._unified_router is None:
            try:
                from aragora.routing.unified_router import UnifiedDecisionRouter

                self._unified_router = UnifiedDecisionRouter()
            except ImportError:
                logger.debug("UnifiedDecisionRouter not available")
        return self._unified_router

    async def process(
        self,
        content: str,
        context: RoutingContext,
        decision_type: str = "debate",
        **kwargs,
    ) -> dict[str, Any]:
        """
        Process a request through the routing middleware.

        Args:
            content: The request content/question
            context: Routing context with channel info
            decision_type: Type of decision (debate, workflow, gauntlet, quick)
            **kwargs: Additional arguments for the router

        Returns:
            Response dictionary with result and metadata
        """
        start_time = time.time()

        # Check cache first
        if self._cache:
            cache_context = {
                "channel": context.channel,
                "workspace_id": context.workspace_id,
            }
            cached = await self._cache.get(content, cache_context)
            if cached:
                logger.info("Serving cached response for %s", context.request_id)
                return {
                    "success": True,
                    "cached": True,
                    "result": cached,
                    "request_id": context.request_id,
                }

        # Check for duplicate in-flight request
        if self._deduplicator:
            is_duplicate, future = await self._deduplicator.check_and_mark(
                content, context.user_id, context.channel
            )
            if is_duplicate:
                if future:
                    logger.info("Waiting for in-flight duplicate: %s", context.request_id)
                    try:
                        result = await asyncio.wait_for(future, timeout=300.0)
                        return {
                            "success": True,
                            "deduplicated": True,
                            "result": result,
                            "request_id": context.request_id,
                        }
                    except asyncio.TimeoutError:
                        logger.warning("Timeout waiting for duplicate: %s", context.request_id)
                else:
                    return {
                        "success": False,
                        "error": "Duplicate request detected",
                        "request_id": context.request_id,
                    }

        try:
            # Register origin for bidirectional routing
            await self._register_origin(content, context)

            # Route through DecisionRouter if available
            router = self._get_router()
            if router:
                result = await self._route_via_decision_router(
                    content, context, decision_type, **kwargs
                )
            else:
                # Fallback: direct debate
                result = await self._fallback_route(content, context, **kwargs)

            duration = time.time() - start_time

            # Cache successful results
            if self._cache and result.get("success"):
                cache_context = {
                    "channel": context.channel,
                    "workspace_id": context.workspace_id,
                }
                await self._cache.set(content, result.get("answer"), cache_context)

            # Complete deduplication
            if self._deduplicator:
                await self._deduplicator.complete(
                    content, context.user_id, context.channel, result.get("answer")
                )

            logger.info(
                "Routed request %s via %s in %.2fs", context.request_id, context.channel, duration
            )

            return {
                "success": True,
                "result": result,
                "request_id": context.request_id,
                "duration_seconds": duration,
            }

        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError) as e:
            logger.error("Routing error for %s: %s", context.request_id, e)

            if self._deduplicator:
                await self._deduplicator.fail(content, context.user_id, context.channel, e)

            return {
                "success": False,
                "error": "Decision routing failed",
                "request_id": context.request_id,
            }
        except Exception as e:  # noqa: BLE001 - Top-level request handler: catch-all after specific catches prevents unhandled 500s
            logger.error("Unexpected routing error for %s: %s", context.request_id, e)

            if self._deduplicator:
                await self._deduplicator.fail(content, context.user_id, context.channel, e)

            return {
                "success": False,
                "error": "Internal routing error",
                "request_id": context.request_id,
            }

    async def _register_origin(self, content: str, context: RoutingContext) -> None:
        """Register the origin for bidirectional routing."""
        try:
            from aragora.server.debate_origin import register_debate_origin

            register_debate_origin(
                debate_id=context.request_id,
                platform=context.channel,
                channel_id=context.channel_id,
                user_id=context.user_id,
                thread_id=context.thread_id,
                message_id=context.message_id,
                metadata={
                    "workspace_id": context.workspace_id,
                    "content_preview": content[:100] if content else "",
                    **context.metadata,
                },
            )
        except ImportError:
            logger.debug("debate_origin not available for origin registration")
        except (OSError, RuntimeError, ValueError, TypeError) as e:
            logger.warning("Failed to register origin: %s", e)

    async def _route_via_decision_router(
        self,
        content: str,
        context: RoutingContext,
        decision_type: str,
        **kwargs,
    ) -> dict[str, Any]:
        """Route via the full DecisionRouter."""
        from aragora.core.decision import (
            DecisionRequest,
            DecisionType,
            InputSource,
            RequestContext,
        )

        # Map channel to input source
        source_map = {
            "slack": InputSource.SLACK,
            "teams": InputSource.TEAMS,
            "discord": InputSource.DISCORD,
            "telegram": InputSource.TELEGRAM,
            "whatsapp": InputSource.WHATSAPP,
            "email": InputSource.EMAIL,
            "gmail": InputSource.GMAIL,
            "web": InputSource.HTTP_API,
            "api": InputSource.HTTP_API,
            "websocket": InputSource.WEBSOCKET,
            "cli": InputSource.CLI,
        }
        source = source_map.get(context.channel.lower(), InputSource.HTTP_API)

        # Map decision type
        type_map = {
            "auto": DecisionType.AUTO,
            "debate": DecisionType.DEBATE,
            "workflow": DecisionType.WORKFLOW,
            "gauntlet": DecisionType.GAUNTLET,
            "quick": DecisionType.QUICK,
        }
        dtype = type_map.get(decision_type.lower(), DecisionType.DEBATE)

        # Build context - channel_id and thread_id go in metadata
        request_metadata = {
            **context.metadata,
            "channel_id": context.channel_id,
            "thread_id": context.thread_id,
        }
        request_context = RequestContext(
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            metadata=request_metadata,
        )

        # Build request
        request = DecisionRequest(
            request_id=context.request_id,
            content=content,
            decision_type=dtype,
            source=source,
            context=request_context,
        )

        # Route
        if dtype == DecisionType.AUTO:
            router = self._get_unified_router()
        else:
            router = self._get_router()
        if router is None:
            return {
                "success": False,
                "error": "Decision router not available",
                "request_id": context.request_id,
            }
        result = await router.route(request)

        return {
            "success": result.success,
            "answer": result.answer,
            "confidence": result.confidence,
            "consensus_reached": result.consensus_reached,
            "reasoning": result.reasoning,
            "duration_seconds": result.duration_seconds,
            "error": result.error,
        }

    async def _fallback_route(
        self,
        content: str,
        context: RoutingContext,
        **kwargs,
    ) -> dict[str, Any]:
        """Fallback routing when DecisionRouter is not available."""
        try:
            from aragora.config.settings import DebateSettings
            from aragora.debate import Arena, Environment, DebateProtocol

            env = Environment(task=content)
            defaults = DebateSettings()
            consensus_type = cast(
                Literal[
                    "majority",
                    "unanimous",
                    "judge",
                    "none",
                    "weighted",
                    "supermajority",
                    "any",
                    "byzantine",
                ],
                defaults.default_consensus,
            )
            protocol = DebateProtocol(
                rounds=defaults.default_rounds,
                consensus=consensus_type,
            )

            # Run with default agents
            arena = Arena(env, protocol=protocol)
            result = await arena.run()

            return {
                "success": True,
                "answer": result.get("consensus", {}).get("answer", ""),
                "confidence": result.get("consensus", {}).get("confidence", 0.0),
                "consensus_reached": result.get("consensus_reached", False),
            }

        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError, ImportError) as e:
            logger.error("Fallback routing failed: %s", e)
            return {
                "success": False,
                "error": "Fallback routing failed",
            }


# Global middleware instance
_middleware: DecisionRoutingMiddleware | None = None
_middleware_lock = asyncio.Lock()


async def get_decision_middleware() -> DecisionRoutingMiddleware:
    """Get or create the global DecisionRoutingMiddleware."""
    global _middleware
    if _middleware is None:
        async with _middleware_lock:
            if _middleware is None:
                _middleware = DecisionRoutingMiddleware()
    return _middleware


def route_decision(
    channel: str,
    decision_type: str = "debate",
    enable_caching: bool = True,
) -> Callable[[F], F]:
    """
    Decorator to route handler results through DecisionRouter.

    Args:
        channel: Channel name (slack, teams, discord, etc.)
        decision_type: Type of decision (debate, workflow, gauntlet, quick)
        enable_caching: Whether to cache responses

    Usage:
        @route_decision(channel="slack")
        async def handle_slack_message(content, user_id, channel_id):
            return {"content": content, "user_id": user_id}
    """

    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract content and context from handler result
            handler_result = await func(*args, **kwargs)

            if not isinstance(handler_result, dict):
                return handler_result

            # Get middleware
            middleware = await get_decision_middleware()

            # Build routing context
            context = RoutingContext(
                channel=channel,
                channel_id=handler_result.get("channel_id", ""),
                user_id=handler_result.get("user_id", ""),
                request_id=handler_result.get("request_id", f"{channel}-{time.time()}"),
                message_id=handler_result.get("message_id"),
                thread_id=handler_result.get("thread_id"),
                workspace_id=handler_result.get("workspace_id"),
                metadata=handler_result.get("metadata", {}),
            )

            content = handler_result.get("content", "")

            # Route through middleware
            result = await middleware.process(
                content=content,
                context=context,
                decision_type=decision_type,
            )

            return result

        return cast(F, wrapper)

    return decorator


def reset_decision_middleware() -> None:
    """Reset the global middleware (for testing)."""
    global _middleware
    _middleware = None


async def invalidate_cache_for_workspace(workspace_id: str) -> int:
    """
    Invalidate all cached decisions for a workspace.

    Call this when workspace policies or configurations change.

    Args:
        workspace_id: The workspace ID to invalidate

    Returns:
        Number of entries invalidated
    """
    middleware = await get_decision_middleware()
    if middleware._cache:
        return await middleware._cache.invalidate_by_workspace(workspace_id)
    return 0


async def invalidate_cache_for_policy_change(new_policy_version: str) -> None:
    """
    Mark all cached decisions as stale due to policy change.

    This performs lazy invalidation - entries are invalidated on next access.

    Args:
        new_policy_version: The new policy version string
    """
    middleware = await get_decision_middleware()
    if middleware._cache:
        middleware._cache.set_policy_version(new_policy_version)


async def invalidate_cache_for_agent_upgrade(agent_name: str, old_version: str) -> int:
    """
    Invalidate cached decisions that used a specific agent version.

    Call this when an agent is upgraded to ensure fresh results.

    Args:
        agent_name: Name of the upgraded agent
        old_version: The old version being replaced

    Returns:
        Number of entries invalidated
    """
    middleware = await get_decision_middleware()
    if middleware._cache:
        return await middleware._cache.invalidate_by_agent_version(agent_name, old_version)
    return 0


async def get_cache_stats() -> dict[str, Any]:
    """
    Get cache statistics for monitoring.

    Returns:
        Dict with cache stats including hits, misses, hit rate, etc.
    """
    middleware = await get_decision_middleware()
    if middleware._cache:
        return await middleware._cache.get_stats()
    return {"enabled": False}


__all__ = [
    "RoutingContext",
    "CacheEntry",
    "RequestDeduplicator",
    "ResponseCache",
    "DecisionRoutingMiddleware",
    "get_decision_middleware",
    "route_decision",
    "reset_decision_middleware",
    # Cache invalidation
    "invalidate_cache_for_workspace",
    "invalidate_cache_for_policy_change",
    "invalidate_cache_for_agent_upgrade",
    "get_cache_stats",
]
