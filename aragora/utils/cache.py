"""
General-purpose caching utilities for Aragora.

Provides LRU caching with TTL expiry that can be used throughout the codebase,
not just in HTTP handlers.

Usage:
    from aragora.utils.cache import lru_cache_with_ttl, cached_property_ttl

    class MyService:
        @lru_cache_with_ttl(ttl_seconds=300, maxsize=100)
        def get_expensive_data(self, key: str) -> dict:
            # Expensive operation
            ...

        @cached_property_ttl(ttl_seconds=600)
        def config(self) -> dict:
            # Computed once, cached for 10 minutes
            ...
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Generic, Protocol, TypeVar, cast
from collections.abc import Awaitable, Callable

from aragora.config import (
    CACHE_TTL_AGENT_FLIPS,
    CACHE_TTL_AGENT_H2H,
    CACHE_TTL_AGENT_PROFILE,
    CACHE_TTL_AGENT_REPUTATION,
    CACHE_TTL_ALL_REPUTATIONS,
    CACHE_TTL_ANALYTICS,
    CACHE_TTL_ANALYTICS_DEBATES,
    CACHE_TTL_ANALYTICS_MEMORY,
    CACHE_TTL_ANALYTICS_RANKING,
    CACHE_TTL_ARCHIVE_STATS,
    CACHE_TTL_CALIBRATION_LB,
    CACHE_TTL_CONSENSUS,
    CACHE_TTL_CONSENSUS_SETTLED,
    CACHE_TTL_CONSENSUS_SIMILAR,
    CACHE_TTL_CONSENSUS_STATS,
    CACHE_TTL_CONTRARIAN_VIEWS,
    CACHE_TTL_CRITIQUE_PATTERNS,
    CACHE_TTL_CRITIQUE_STATS,
    CACHE_TTL_DASHBOARD_DEBATES,
    CACHE_TTL_EMBEDDINGS,
    CACHE_TTL_FLIPS_RECENT,
    CACHE_TTL_FLIPS_SUMMARY,
    CACHE_TTL_LB_INTROSPECTION,
    CACHE_TTL_LB_MATCHES,
    CACHE_TTL_LB_RANKINGS,
    CACHE_TTL_LB_REPUTATION,
    CACHE_TTL_LB_STATS,
    CACHE_TTL_LB_TEAMS,
    CACHE_TTL_LEADERBOARD,
    CACHE_TTL_LEARNING_EVOLUTION,
    CACHE_TTL_META_LEARNING,
    CACHE_TTL_METHOD,
    CACHE_TTL_QUERY,
    CACHE_TTL_RECENT_DISSENTS,
    CACHE_TTL_RECENT_MATCHES,
    CACHE_TTL_REPLAYS_LIST,
    CACHE_TTL_RISK_WARNINGS,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)


class CachedCallable(Protocol[T_co]):
    """Protocol for callable with cache attributes attached."""

    cache: TTLCache[Any]
    cache_key_prefix: str

    def __call__(self, *args: Any, **kwargs: Any) -> T_co: ...


class TTLCache(Generic[T]):
    """
    Thread-safe LRU cache with TTL expiry.

    Generic version that can store any type T.
    """

    def __init__(self, maxsize: int = 128, ttl_seconds: float = 300.0):
        self._cache: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._maxsize = maxsize
        self._ttl_seconds = ttl_seconds
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> T | None:
        """Get a value from cache if not expired."""
        with self._lock:
            if key in self._cache:
                cached_time, value = self._cache[key]
                if time.time() - cached_time < self._ttl_seconds:
                    # Move to end (most recently used)
                    self._cache.move_to_end(key)
                    self._hits += 1
                    return value
                else:
                    # Expired
                    del self._cache[key]
            self._misses += 1
            return None

    def set(self, key: str, value: T) -> None:
        """Store a value in cache."""
        with self._lock:
            # Remove oldest entries if at capacity
            while len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)

            self._cache[key] = (time.time(), value)

    def invalidate(self, key: str) -> bool:
        """Invalidate a specific key."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> int:
        """Clear all entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count

    def clear_prefix(self, prefix: str) -> int:
        """Clear entries with keys starting with prefix."""
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.startswith(prefix)]
            for k in keys_to_remove:
                del self._cache[k]
            return len(keys_to_remove)

    @property
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "size": len(self._cache),
                "maxsize": self._maxsize,
                "ttl_seconds": self._ttl_seconds,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self._hits / total if total > 0 else 0.0,
            }

    def __len__(self) -> int:
        """Return the number of cached items."""
        with self._lock:
            return len(self._cache)

    def __getitem__(self, key: str) -> T:
        """Get item by key, raises KeyError if not found or expired."""
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __contains__(self, key: str) -> bool:
        """Check if key is in cache and not expired."""
        return self.get(key) is not None

    def __iter__(self):
        """Iterate over cache keys (returns snapshot to avoid lock during iteration)."""
        with self._lock:
            return iter(list(self._cache.keys()))

    def keys(self) -> list[str]:
        """Return a copy of all keys in the cache."""
        with self._lock:
            return list(self._cache.keys())

    def items(self) -> list[tuple[str, T]]:
        """Return a copy of all (key, value) pairs, filtering expired entries."""
        with self._lock:
            now = time.time()
            return [
                (k, v)
                for k, (cached_time, v) in self._cache.items()
                if now - cached_time < self._ttl_seconds
            ]


# Global cache instances for different purposes
_method_cache = TTLCache[Any](maxsize=1000, ttl_seconds=CACHE_TTL_METHOD)
_query_cache = TTLCache[Any](maxsize=500, ttl_seconds=CACHE_TTL_QUERY)

CacheRegistrationHook = Callable[[TTLCache[Any], TTLCache[Any]], None]
_cache_registration_hook: CacheRegistrationHook | None = None


def register_cache_registration_hook(hook: CacheRegistrationHook | None) -> None:
    """Register a higher-layer observer for the two foundation cache instances."""
    global _cache_registration_hook
    _cache_registration_hook = hook
    _register_caches_with_service_registry()


def _register_caches_with_service_registry() -> None:
    """Notify the registered higher-layer cache observer, if any."""
    if _cache_registration_hook is None:
        return

    try:
        _cache_registration_hook(_method_cache, _query_cache)
    except ImportError:
        pass


def get_method_cache() -> TTLCache[Any]:
    """Get the global method cache, registering with ServiceRegistry if available."""
    _register_caches_with_service_registry()
    return _method_cache


def get_query_cache() -> TTLCache[Any]:
    """Get the global query cache, registering with ServiceRegistry if available."""
    _register_caches_with_service_registry()
    return _query_cache


def lru_cache_with_ttl(
    ttl_seconds: float = 300.0,
    maxsize: int = 128,
    key_prefix: str = "",
    cache: TTLCache | None = None,
):
    """
    Decorator for caching function/method results with LRU eviction and TTL expiry.

    Args:
        ttl_seconds: How long to cache results (default 5 minutes)
        maxsize: Maximum number of cached results (default 128)
        key_prefix: Optional prefix for cache keys
        cache: Optional custom cache instance (uses global cache if not provided)

    Example:
        @lru_cache_with_ttl(ttl_seconds=300)
        def get_user(user_id: str) -> User:
            return db.query(User).filter_by(id=user_id).first()

        @lru_cache_with_ttl(ttl_seconds=60, key_prefix="leaderboard")
        def get_leaderboard(self, limit: int = 20) -> list[dict]:
            ...
    """
    # Create dedicated cache if maxsize differs from global
    if cache is None:
        if maxsize != 128:
            cache = TTLCache(maxsize=maxsize, ttl_seconds=ttl_seconds)
        else:
            cache = _method_cache

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Build cache key
            # Skip 'self' for methods by checking if first arg is an object
            skip_first = (
                args
                and hasattr(args[0], "__class__")
                and not isinstance(args[0], (str, int, float, bool, list, dict, tuple))
            )
            cache_args = args[1:] if skip_first else args

            # Create hashable key
            key_parts = [key_prefix or func.__name__]
            key_parts.append(str(cache_args))
            if kwargs:
                key_parts.append(str(sorted(kwargs.items())))
            cache_key = ":".join(key_parts)

            # Try to get from cache
            cached = cache.get(cache_key)
            if cached is not None:
                return cached

            # Compute and cache result
            result = func(*args, **kwargs)
            cache.set(cache_key, result)
            return result

        # Attach cache reference for manual invalidation
        setattr(wrapper, "cache", cache)
        setattr(wrapper, "cache_key_prefix", key_prefix or func.__name__)

        return cast(Callable[..., T], wrapper)

    return decorator


def cached_property_ttl(ttl_seconds: float = 300.0):
    """
    Decorator for cached properties with TTL expiry.

    Similar to @property but caches the result for the specified duration.
    Each instance gets its own cached value.

    Example:
        class MyClass:
            @cached_property_ttl(ttl_seconds=60)
            def expensive_computation(self) -> dict:
                return self._compute_expensive_thing()
    """

    def decorator(func: Callable[[Any], T]) -> property:
        attr_name = f"_cached_{func.__name__}"
        time_attr = f"_cached_{func.__name__}_time"

        @wraps(func)
        def getter(self) -> T:
            now = time.time()
            cached_time = getattr(self, time_attr, 0)

            if now - cached_time < ttl_seconds:
                cached_value = getattr(self, attr_name, None)
                if cached_value is not None:
                    return cached_value

            # Compute new value
            value = func(self)
            setattr(self, attr_name, value)
            setattr(self, time_attr, now)
            return value

        return property(getter)

    return decorator


def invalidate_method_cache(prefix: str) -> int:
    """Invalidate entries in the global method cache by prefix."""
    return _method_cache.clear_prefix(prefix)


def get_cache_stats() -> dict[str, Any]:
    """Get statistics for global caches."""
    # Register with service registry on first stats call
    _register_caches_with_service_registry()

    return {
        "method_cache": _method_cache.stats,
        "query_cache": _query_cache.stats,
    }


def clear_all_caches() -> dict[str, int]:
    """Clear all global caches."""
    return {
        "method_cache": _method_cache.clear(),
        "query_cache": _query_cache.clear(),
    }


# =============================================================================
# Handler-style cache utilities (for use by memory and other modules)
# =============================================================================

# Global bounded cache for handler-style caching
_handler_cache: TTLCache[Any] = TTLCache(maxsize=1000, ttl_seconds=60.0)


def ttl_cache(ttl_seconds: float = 60.0, key_prefix: str = "", skip_first: bool = True):
    """
    Decorator for caching function results with TTL expiry.

    This is the handler-style cache decorator that can be used by both
    server handlers and other modules like memory.

    Args:
        ttl_seconds: How long to cache results (default 60s)
        key_prefix: Prefix for cache key to namespace different functions
        skip_first: If True, skip first arg (self) when building cache key for methods.
                   Default is True since most usage is on class methods.
                   Set to False when decorating standalone functions.

    Usage:
        @ttl_cache(ttl_seconds=300, key_prefix="leaderboard")
        def _get_leaderboard(self, limit: int):
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # Skip 'self' when building cache key for methods
            cache_args = args[1:] if skip_first and args else args
            # Build cache key from function name, args and kwargs
            cache_key = f"{key_prefix}:{func.__name__}:{cache_args}:{sorted(kwargs.items())}"

            # Check cache
            cached = _handler_cache.get(cache_key)
            if cached is not None:
                logger.debug("Cache hit for %s", cache_key)
                return cached

            # Cache miss - compute and store
            result = func(*args, **kwargs)
            _handler_cache.set(cache_key, result)
            logger.debug("Cache miss, stored %s", cache_key)
            return result

        return wrapper

    return decorator


def async_ttl_cache(ttl_seconds: float = 60.0, key_prefix: str = "", skip_first: bool = True):
    """
    Async decorator for caching coroutine results with TTL expiry.

    Same as ttl_cache but works with async functions.

    Args:
        ttl_seconds: How long to cache results (default 60s)
        key_prefix: Prefix for cache key to namespace different functions
        skip_first: If True, skip first arg (self) when building cache key for methods.
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            # Skip 'self' when building cache key for methods
            cache_args = args[1:] if skip_first and args else args
            cache_key = f"{key_prefix}:{func.__name__}:{cache_args}:{sorted(kwargs.items())}"

            # Check cache
            cached = _handler_cache.get(cache_key)
            if cached is not None:
                logger.debug("Cache hit for %s", cache_key)
                return cached

            # Cache miss - compute and store
            result = await func(*args, **kwargs)
            _handler_cache.set(cache_key, result)
            logger.debug("Cache miss, stored %s", cache_key)
            return result

        return cast(Callable[..., Awaitable[T]], wrapper)

    return decorator


# Maps data sources to cache prefixes that should be invalidated
CACHE_INVALIDATION_MAP: dict[str, list[str]] = {
    # Memory module events
    "memory": ["analytics_memory", "critique_patterns", "critique_stats"],
    # Debate events
    "debates": ["dashboard_debates", "analytics_debates", "replays_list", "consensus_stats"],
    # Consensus events
    "consensus": ["consensus_stats", "consensus_settled", "consensus_similar"],
    # ELO/ranking events
    "elo": ["leaderboard", "lb_rankings", "agents_list", "agent_profile"],
    # Agent events
    "agent": ["agent_profile", "agents_list"],
    # Analytics dashboard events (see aragora.server.handlers.analytics.cache)
    "analytics_dashboard": [
        "analytics_dashboard_summary",
        "analytics_dashboard_trends",
        "analytics_dashboard_agents",
        "analytics_dashboard_remediation",
        "analytics_dashboard_cost",
        "analytics_dashboard_tokens",
        "analytics_dashboard_deliberations",
    ],
    # Cost/billing events
    "billing": ["analytics_dashboard_cost", "analytics_dashboard_tokens"],
}


def invalidate_cache(data_source: str) -> int:
    """Invalidate cache entries associated with a data source.

    This function clears all cache prefixes registered for a given data source.
    Can be used by memory modules, server handlers, or any other code that
    needs to invalidate related caches.

    Args:
        data_source: Name of the data source (e.g., "memory", "debates", "consensus")

    Returns:
        Total number of cache entries invalidated
    """
    prefixes = CACHE_INVALIDATION_MAP.get(data_source, [data_source])
    total_cleared = 0

    for prefix in prefixes:
        cleared = _handler_cache.clear_prefix(prefix)
        total_cleared += cleared
        if cleared > 0:
            logger.debug("Cache invalidation: cleared %s entries with prefix '%s'", cleared, prefix)

    if total_cleared > 0:
        logger.info("Cache invalidated: source=%s, entries_cleared=%s", data_source, total_cleared)

    return total_cleared


def get_handler_cache() -> TTLCache[Any]:
    """Get the global handler cache instance."""
    return _handler_cache


# =============================================================================
# Unified CacheManager with TTL Presets
# =============================================================================


class CachePreset:
    """Named cache preset with preconfigured TTL and maxsize."""

    def __init__(
        self,
        name: str,
        ttl_seconds: float,
        maxsize: int = 128,
        description: str = "",
    ):
        self.name = name
        self.ttl_seconds = ttl_seconds
        self.maxsize = maxsize
        self.description = description
        self._cache: TTLCache[Any] | None = None

    @property
    def cache(self) -> TTLCache[Any]:
        """Lazily create the cache on first access."""
        if self._cache is None:
            self._cache = TTLCache(maxsize=self.maxsize, ttl_seconds=self.ttl_seconds)
        return self._cache

    def get(self, key: str) -> Any | None:
        """Get value from cache."""
        return self.cache.get(key)

    def set(self, key: str, value: Any) -> None:
        """Set value in cache."""
        self.cache.set(key, value)

    def invalidate(self, key: str) -> bool:
        """Invalidate a specific key."""
        return self.cache.invalidate(key)

    def clear(self) -> int:
        """Clear all entries."""
        return self.cache.clear()

    def clear_prefix(self, prefix: str) -> int:
        """Clear entries with matching prefix."""
        return self.cache.clear_prefix(prefix)

    @property
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        if self._cache is None:
            return {
                "name": self.name,
                "size": 0,
                "maxsize": self.maxsize,
                "ttl_seconds": self.ttl_seconds,
                "hits": 0,
                "misses": 0,
                "hit_rate": 0.0,
                "initialized": False,
            }
        stats = self._cache.stats
        stats["name"] = self.name
        stats["initialized"] = True
        return stats


class CacheManager:
    """
    Unified cache manager with domain-specific presets.

    Provides named cache presets configured from centralized TTL constants,
    with a registry for observability and coordinated invalidation.

    Usage:
        manager = CacheManager.get_instance()

        # Get a domain-specific cache
        agent_cache = manager.get_preset("agent_profile")
        agent_cache.set("agent:claude", profile_data)
        profile = agent_cache.get("agent:claude")

        # Use decorator with preset
        @manager.cached("consensus")
        def get_consensus_data(debate_id: str) -> dict:
            ...

        # Get all stats for monitoring
        all_stats = manager.get_all_stats()
    """

    _instance: CacheManager | None = None
    _lock = threading.Lock()

    # Domain-grouped preset configurations
    PRESET_CONFIGS: dict[str, tuple[float, int, str]] = {
        # Agent data (TTL, maxsize, description)
        "agent_profile": (CACHE_TTL_AGENT_PROFILE, 200, "Agent profile data"),
        "agent_h2h": (CACHE_TTL_AGENT_H2H, 500, "Agent head-to-head records"),
        "agent_flips": (CACHE_TTL_AGENT_FLIPS, 200, "Agent position flips"),
        "agent_reputation": (CACHE_TTL_AGENT_REPUTATION, 200, "Agent reputation scores"),
        "all_reputations": (CACHE_TTL_ALL_REPUTATIONS, 50, "All agent reputations"),
        # Leaderboard & rankings
        "leaderboard": (CACHE_TTL_LEADERBOARD, 50, "Main leaderboard"),
        "lb_rankings": (CACHE_TTL_LB_RANKINGS, 100, "Leaderboard rankings"),
        "lb_matches": (CACHE_TTL_LB_MATCHES, 200, "Leaderboard matches"),
        "lb_reputation": (CACHE_TTL_LB_REPUTATION, 100, "Leaderboard reputation"),
        "lb_teams": (CACHE_TTL_LB_TEAMS, 50, "Leaderboard teams"),
        "lb_stats": (CACHE_TTL_LB_STATS, 50, "Leaderboard statistics"),
        "lb_introspection": (CACHE_TTL_LB_INTROSPECTION, 100, "Leaderboard introspection"),
        "calibration_lb": (CACHE_TTL_CALIBRATION_LB, 50, "Calibration leaderboard"),
        "recent_matches": (CACHE_TTL_RECENT_MATCHES, 100, "Recent match history"),
        "flips_recent": (CACHE_TTL_FLIPS_RECENT, 100, "Recent position flips"),
        "flips_summary": (CACHE_TTL_FLIPS_SUMMARY, 50, "Flip statistics summary"),
        # Analytics
        "analytics": (CACHE_TTL_ANALYTICS, 100, "General analytics"),
        "analytics_ranking": (CACHE_TTL_ANALYTICS_RANKING, 100, "Ranking analytics"),
        "analytics_debates": (CACHE_TTL_ANALYTICS_DEBATES, 100, "Debate analytics"),
        "analytics_memory": (CACHE_TTL_ANALYTICS_MEMORY, 50, "Memory analytics"),
        "archive_stats": (CACHE_TTL_ARCHIVE_STATS, 50, "Archive statistics"),
        # Consensus
        "consensus": (CACHE_TTL_CONSENSUS, 200, "Consensus data"),
        "consensus_similar": (CACHE_TTL_CONSENSUS_SIMILAR, 200, "Similar consensus"),
        "consensus_settled": (CACHE_TTL_CONSENSUS_SETTLED, 100, "Settled consensus"),
        "consensus_stats": (CACHE_TTL_CONSENSUS_STATS, 50, "Consensus statistics"),
        "recent_dissents": (CACHE_TTL_RECENT_DISSENTS, 100, "Recent dissent records"),
        "contrarian_views": (CACHE_TTL_CONTRARIAN_VIEWS, 100, "Contrarian view data"),
        "risk_warnings": (CACHE_TTL_RISK_WARNINGS, 100, "Risk warning data"),
        # Memory & learning
        "replays_list": (CACHE_TTL_REPLAYS_LIST, 50, "Replay list data"),
        "learning_evolution": (CACHE_TTL_LEARNING_EVOLUTION, 100, "Learning evolution"),
        "meta_learning": (CACHE_TTL_META_LEARNING, 100, "Meta-learning patterns"),
        "critique_patterns": (CACHE_TTL_CRITIQUE_PATTERNS, 100, "Critique patterns"),
        "critique_stats": (CACHE_TTL_CRITIQUE_STATS, 50, "Critique statistics"),
        # Dashboard
        "dashboard_debates": (CACHE_TTL_DASHBOARD_DEBATES, 50, "Dashboard debate list"),
        # Embeddings & vectors
        "embeddings": (CACHE_TTL_EMBEDDINGS, 1000, "Vector embeddings"),
        # Generic
        "method": (CACHE_TTL_METHOD, 1000, "Method-level caching"),
        "query": (CACHE_TTL_QUERY, 500, "Query result caching"),
    }

    # Domain groupings for bulk invalidation
    DOMAIN_PRESETS: dict[str, list[str]] = {
        "agent": [
            "agent_profile",
            "agent_h2h",
            "agent_flips",
            "agent_reputation",
            "all_reputations",
        ],
        "leaderboard": [
            "leaderboard",
            "lb_rankings",
            "lb_matches",
            "lb_reputation",
            "lb_teams",
            "lb_stats",
            "lb_introspection",
            "calibration_lb",
            "recent_matches",
            "flips_recent",
            "flips_summary",
        ],
        "analytics": [
            "analytics",
            "analytics_ranking",
            "analytics_debates",
            "analytics_memory",
            "archive_stats",
        ],
        "consensus": [
            "consensus",
            "consensus_similar",
            "consensus_settled",
            "consensus_stats",
            "recent_dissents",
            "contrarian_views",
            "risk_warnings",
        ],
        "memory": [
            "replays_list",
            "learning_evolution",
            "meta_learning",
            "critique_patterns",
            "critique_stats",
        ],
        "dashboard": ["dashboard_debates"],
        "embeddings": ["embeddings"],
    }

    def __init__(self):
        self._presets: dict[str, CachePreset] = {}
        self._initialized = False
        self._init_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> CacheManager:
        """Get the singleton instance of CacheManager."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _ensure_initialized(self) -> None:
        """Initialize presets lazily on first access."""
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            for name, (ttl, maxsize, desc) in self.PRESET_CONFIGS.items():
                self._presets[name] = CachePreset(name, ttl, maxsize, desc)
            self._initialized = True
            logger.debug("CacheManager initialized with %s presets", len(self._presets))

    def get_preset(self, name: str) -> CachePreset:
        """
        Get a named cache preset.

        Args:
            name: Preset name (e.g., "agent_profile", "consensus", "embeddings")

        Returns:
            CachePreset with preconfigured TTL and maxsize

        Raises:
            KeyError: If preset name is not recognized
        """
        self._ensure_initialized()
        if name not in self._presets:
            available = ", ".join(sorted(self._presets.keys()))
            raise KeyError(f"Unknown cache preset '{name}'. Available: {available}")
        return self._presets[name]

    def get_or_create_preset(
        self,
        name: str,
        ttl_seconds: float = 300.0,
        maxsize: int = 128,
        description: str = "",
    ) -> CachePreset:
        """
        Get existing preset or create a new one.

        Useful for custom presets not in the default configuration.
        """
        self._ensure_initialized()
        if name not in self._presets:
            self._presets[name] = CachePreset(name, ttl_seconds, maxsize, description)
            logger.debug("Created custom cache preset: %s", name)
        return self._presets[name]

    def invalidate_domain(self, domain: str) -> dict[str, int]:
        """
        Invalidate all caches in a domain.

        Args:
            domain: Domain name (e.g., "agent", "consensus", "analytics")

        Returns:
            Dict mapping preset names to number of entries cleared
        """
        self._ensure_initialized()
        preset_names = self.DOMAIN_PRESETS.get(domain, [domain])
        results = {}

        for name in preset_names:
            if name in self._presets:
                cleared = self._presets[name].clear()
                results[name] = cleared
                if cleared > 0:
                    logger.debug("Invalidated %s entries from %s cache", cleared, name)

        total = sum(results.values())
        if total > 0:
            logger.info("Domain '%s' invalidation: %s total entries cleared", domain, total)

        return results

    def invalidate_all(self) -> dict[str, int]:
        """Clear all caches and return counts."""
        self._ensure_initialized()
        results = {}
        for name, preset in self._presets.items():
            results[name] = preset.clear()
        total = sum(results.values())
        logger.info("All caches invalidated: %s entries cleared", total)
        return results

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Get statistics for all presets."""
        self._ensure_initialized()
        return {name: preset.stats for name, preset in self._presets.items()}

    def get_domain_stats(self, domain: str) -> dict[str, dict[str, Any]]:
        """Get statistics for all presets in a domain."""
        self._ensure_initialized()
        preset_names = self.DOMAIN_PRESETS.get(domain, [])
        return {name: self._presets[name].stats for name in preset_names if name in self._presets}

    def get_summary_stats(self) -> dict[str, Any]:
        """Get summary statistics across all caches."""
        self._ensure_initialized()
        all_stats = self.get_all_stats()

        total_size = 0
        total_maxsize = 0
        total_hits = 0
        total_misses = 0
        initialized_count = 0

        for stats in all_stats.values():
            total_size += stats.get("size", 0)
            total_maxsize += stats.get("maxsize", 0)
            total_hits += stats.get("hits", 0)
            total_misses += stats.get("misses", 0)
            if stats.get("initialized", False):
                initialized_count += 1

        total_requests = total_hits + total_misses
        return {
            "preset_count": len(self._presets),
            "initialized_count": initialized_count,
            "total_size": total_size,
            "total_maxsize": total_maxsize,
            "total_hits": total_hits,
            "total_misses": total_misses,
            "overall_hit_rate": total_hits / total_requests if total_requests > 0 else 0.0,
        }

    def cached(
        self,
        preset_name: str,
        key_prefix: str = "",
        skip_first: bool = True,
    ):
        """
        Decorator for caching function results using a named preset.

        Args:
            preset_name: Name of the cache preset to use
            key_prefix: Optional prefix for cache keys
            skip_first: If True, skip first arg (self) when building cache key

        Example:
            manager = CacheManager.get_instance()

            @manager.cached("consensus")
            def get_consensus(self, debate_id: str) -> dict:
                ...
        """
        preset = self.get_preset(preset_name)

        def decorator(func: Callable[..., T]) -> Callable[..., T]:
            @wraps(func)
            def wrapper(*args, **kwargs) -> T:
                cache_args = args[1:] if skip_first and args else args
                cache_key = f"{key_prefix}:{func.__name__}:{cache_args}:{sorted(kwargs.items())}"

                cached_value = preset.get(cache_key)
                if cached_value is not None:
                    return cached_value

                result = func(*args, **kwargs)
                preset.set(cache_key, result)
                return result

            return wrapper

        return decorator

    def async_cached(
        self,
        preset_name: str,
        key_prefix: str = "",
        skip_first: bool = True,
    ):
        """
        Async decorator for caching coroutine results using a named preset.

        Args:
            preset_name: Name of the cache preset to use
            key_prefix: Optional prefix for cache keys
            skip_first: If True, skip first arg (self) when building cache key
        """
        preset = self.get_preset(preset_name)

        def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
            @wraps(func)
            async def wrapper(*args, **kwargs) -> T:
                cache_args = args[1:] if skip_first and args else args
                cache_key = f"{key_prefix}:{func.__name__}:{cache_args}:{sorted(kwargs.items())}"

                cached_value = preset.get(cache_key)
                if cached_value is not None:
                    return cached_value

                result = await func(*args, **kwargs)
                preset.set(cache_key, result)
                return result

            return cast(Callable[..., Awaitable[T]], wrapper)

        return decorator

    def list_presets(self) -> list[str]:
        """List all available preset names."""
        self._ensure_initialized()
        return sorted(self._presets.keys())

    def list_domains(self) -> list[str]:
        """List all available domain names."""
        return sorted(self.DOMAIN_PRESETS.keys())


# Convenience function for getting the global CacheManager
def get_cache_manager() -> CacheManager:
    """Get the global CacheManager singleton."""
    return CacheManager.get_instance()
