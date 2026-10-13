"""
Shared compatibility utilities and constants for checkpoint stores.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any
from collections.abc import Callable

# Type aliases for optional dependencies
_RedisClientGetter = Callable[[], Any]
_PoolType = Any  # asyncpg.Pool when available

logger = logging.getLogger(__name__)

# =============================================================================
# Hardening Constants
# =============================================================================

# Default connection timeout for database operations (seconds)
DEFAULT_CONNECTION_TIMEOUT = 10.0

# Default operation timeout for Redis/PostgreSQL commands (seconds)
DEFAULT_OPERATION_TIMEOUT = 30.0

# Maximum entries in checkpoint cache (for LRU eviction)
MAX_CHECKPOINT_CACHE_SIZE = 100

# Python 3.11+ asyncio.timeout compatibility
if sys.version_info >= (3, 11):
    _asyncio_timeout = asyncio.timeout
else:
    # Fallback for Python 3.10 and earlier - use contextlib version or simple wrapper
    try:
        from async_timeout import timeout as _asyncio_timeout
    except ImportError:
        # Simple fallback that doesn't provide true timeout context manager
        # but allows the code to run - actual timeout handled by wait_for
        from contextlib import asynccontextmanager
        from collections.abc import AsyncIterator

        @asynccontextmanager
        async def _asyncio_timeout(delay: float) -> AsyncIterator[None]:
            """No-op timeout context manager for Python < 3.11."""
            yield


# Optional Redis import - graceful degradation
_get_redis_client: _RedisClientGetter | None = None
REDIS_AVAILABLE = False

try:
    from aragora.utils.redis_config import get_redis_client as _redis_getter

    _get_redis_client = _redis_getter
    REDIS_AVAILABLE = True
except ImportError:
    logger.debug("Redis not available for checkpoint store")

# Optional asyncpg import - graceful degradation
_asyncpg_module: Any | None = None
ASYNCPG_AVAILABLE = False

try:
    import asyncpg as _asyncpg

    _asyncpg_module = _asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    logger.debug("asyncpg not available for checkpoint store")
