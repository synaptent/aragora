"""
Minimal Dependency Mode Configuration.

Provides configuration for running Aragora with minimal dependencies:
- SQLite instead of PostgreSQL
- In-memory caching instead of Redis
- No external message queues

Usage:
    # Set environment variable before starting
    ARAGORA_MODE=minimal aragora serve --api-port 8080 --ws-port 8765

    # Or in code
    from aragora.config.minimal import apply_minimal_mode
    apply_minimal_mode()
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from aragora.config import resolve_db_path

logger = logging.getLogger(__name__)

# Environment variable to enable minimal mode
MINIMAL_MODE_ENV = "ARAGORA_MODE"
MINIMAL_MODE_VALUE = "minimal"


@dataclass
class MinimalModeConfig:
    """Configuration for minimal dependency mode."""

    # Database
    db_backend: str = "sqlite"
    db_path: str = "aragora.db"

    # Cache
    cache_backend: str = "memory"
    cache_max_size: int = 10000

    # Disable external services
    redis_enabled: bool = False
    postgres_enabled: bool = False
    kafka_enabled: bool = False
    rabbitmq_enabled: bool = False

    # Simplified features
    enable_embeddings: bool = True  # Can use local embeddings
    enable_metrics: bool = True
    enable_tracing: bool = False  # Skip distributed tracing


def is_minimal_mode() -> bool:
    """Check if minimal mode is enabled."""
    return os.environ.get(MINIMAL_MODE_ENV, "").lower() == MINIMAL_MODE_VALUE


def get_minimal_config() -> MinimalModeConfig:
    """Get minimal mode configuration."""
    return MinimalModeConfig()


def apply_minimal_mode(config: MinimalModeConfig | None = None) -> dict[str, Any]:
    """Apply minimal mode environment variables.

    This function sets environment variables to configure Aragora for
    minimal dependencies. Call before importing other Aragora modules.

    Args:
        config: Optional custom configuration

    Returns:
        Dictionary of applied environment variables
    """
    if config is None:
        config = get_minimal_config()

    applied: dict[str, Any] = {}

    # Database configuration
    os.environ.setdefault("ARAGORA_DB_BACKEND", config.db_backend)
    applied["ARAGORA_DB_BACKEND"] = config.db_backend

    if config.db_backend == "sqlite":
        # Use SQLite file path
        resolved_db_path = resolve_db_path(config.db_path)
        os.environ.setdefault("ARAGORA_DB_PATH", resolved_db_path)
        applied["ARAGORA_DB_PATH"] = resolved_db_path

    # Disable Redis
    if not config.redis_enabled:
        os.environ.setdefault("ARAGORA_REDIS_URL", "")
        applied["ARAGORA_REDIS_URL"] = ""

    # Disable PostgreSQL URL
    if not config.postgres_enabled:
        # Don't override if DATABASE_URL was explicitly set
        if "DATABASE_URL" not in os.environ:
            os.environ.setdefault("ARAGORA_DB_MODE", "legacy")
            applied["ARAGORA_DB_MODE"] = "legacy"

    # Disable streaming connectors
    if not config.kafka_enabled:
        os.environ.setdefault("ARAGORA_KAFKA_ENABLED", "false")
        applied["ARAGORA_KAFKA_ENABLED"] = "false"

    if not config.rabbitmq_enabled:
        os.environ.setdefault("ARAGORA_RABBITMQ_ENABLED", "false")
        applied["ARAGORA_RABBITMQ_ENABLED"] = "false"

    # Tracing
    if not config.enable_tracing:
        os.environ.setdefault("ARAGORA_TRACING_ENABLED", "false")
        applied["ARAGORA_TRACING_ENABLED"] = "false"

    logger.info("Applied minimal mode configuration: %s", applied)
    return applied


def check_minimal_requirements() -> dict[str, bool]:
    """Check if minimal requirements are met.

    Returns:
        Dictionary mapping requirement to availability status
    """
    requirements = {}

    import importlib.util

    # Python standard library (always available)
    requirements["sqlite3"] = importlib.util.find_spec("sqlite3") is not None

    # Minimal mode should treat direct providers and funded fallback routes
    # consistently so local/dogfood validation matches runtime behavior.
    requirements["anthropic_key"] = bool(os.environ.get("ANTHROPIC_API_KEY"))
    requirements["openai_key"] = bool(os.environ.get("OPENAI_API_KEY"))
    requirements["openrouter_key"] = bool(os.environ.get("OPENROUTER_API_KEY"))
    requirements["mistral_key"] = bool(os.environ.get("MISTRAL_API_KEY"))
    requirements["gemini_key"] = bool(
        os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    )
    requirements["xai_key"] = bool(os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY"))
    requirements["has_ai_provider"] = any(
        requirements[key]
        for key in (
            "anthropic_key",
            "openai_key",
            "openrouter_key",
            "mistral_key",
            "gemini_key",
            "xai_key",
        )
    )

    # Optional dependencies
    requirements["httpx"] = importlib.util.find_spec("httpx") is not None
    requirements["pydantic"] = importlib.util.find_spec("pydantic") is not None

    return requirements


def get_minimal_startup_message() -> str:
    """Get startup message for minimal mode."""
    return """
============================================================
  Aragora - Minimal Mode
============================================================

Running with minimal dependencies:
  - Database: SQLite (local file)
  - Cache: In-memory (no Redis)
  - Queue: In-process (no Kafka/RabbitMQ)

This mode is suitable for:
  - Local development
  - Small deployments
  - Testing and evaluation

For production with high availability, consider:
  - PostgreSQL for database
  - Redis for caching/sessions
  - Proper backup strategy

============================================================
"""


class InMemoryCache:
    """Simple in-memory cache for minimal mode.

    Thread-safe LRU-style cache with TTL support.
    """

    def __init__(self, max_size: int = 10000):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._max_size = max_size
        import threading

        self._lock = threading.RLock()

    def get(self, key: str) -> Any | None:
        """Get value from cache."""
        import time

        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if expiry == 0 or time.time() < expiry:
                    return value
                # Expired
                del self._cache[key]
            return None

    def set(self, key: str, value: Any, ttl: int = 0) -> None:
        """Set value in cache with optional TTL (seconds)."""
        import time

        with self._lock:
            # Evict oldest entries if at capacity
            if len(self._cache) >= self._max_size:
                # Simple eviction: remove first 10%
                to_remove = list(self._cache.keys())[: self._max_size // 10]
                for k in to_remove:
                    del self._cache[k]

            expiry = time.time() + ttl if ttl > 0 else 0
            self._cache[key] = (value, expiry)

    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)


# Global cache instance for minimal mode
_minimal_cache: InMemoryCache | None = None


def get_minimal_cache() -> InMemoryCache:
    """Get the global minimal mode cache instance."""
    global _minimal_cache
    if _minimal_cache is None:
        config = get_minimal_config()
        _minimal_cache = InMemoryCache(max_size=config.cache_max_size)
    return _minimal_cache


# Auto-apply minimal mode if environment variable is set
if is_minimal_mode():
    apply_minimal_mode()
