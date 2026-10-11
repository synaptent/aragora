"""Debate origin registration, lookup, and lifecycle management.

Manages the in-memory origin store with persistent backends (SQLite,
PostgreSQL, Redis) for durable debate origin tracking.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import sys
import time
from typing import Any
from collections.abc import Callable, Coroutine

from .models import DebateOrigin
from .stores import (
    ORIGIN_TTL_SECONDS,
    _get_sqlite_store as _stores_get_sqlite_store,
    _get_postgres_store as _stores_get_postgres_store,
    _get_postgres_store_sync as _stores_get_postgres_store_sync,
)
from .sessions import _create_and_link_session

from aragora.config.distributed import is_distributed_state_required
from aragora.control_plane.leader import DistributedStateError

logger = logging.getLogger(__name__)

# In-memory store with optional Redis backend
_origin_store: dict[str, DebateOrigin] = {}


def _get_pkg():
    """Get the package module to support test patching via __init__."""
    return sys.modules.get("aragora.server.debate_origin")


def _get_sqlite_store():
    """Wrapper that respects patches on the package namespace."""
    pkg = _get_pkg()
    if pkg is not None and hasattr(pkg, "_get_sqlite_store"):
        fn = getattr(pkg, "_get_sqlite_store")
        # Avoid infinite recursion if the package re-exported us
        if fn is not _get_sqlite_store:
            return fn()
    return _stores_get_sqlite_store()


async def _get_postgres_store():
    """Wrapper that respects patches on the package namespace."""
    pkg = _get_pkg()
    if pkg is not None and hasattr(pkg, "_get_postgres_store"):
        fn = getattr(pkg, "_get_postgres_store")
        if fn is not _get_postgres_store:
            return await fn()
    return await _stores_get_postgres_store()


def _get_postgres_store_sync():
    """Wrapper that respects patches on the package namespace."""
    pkg = _get_pkg()
    if pkg is not None and hasattr(pkg, "_get_postgres_store_sync"):
        fn = getattr(pkg, "_get_postgres_store_sync")
        if fn is not _get_postgres_store_sync:
            return fn()
    return _stores_get_postgres_store_sync()


def _get_persistence_loop() -> asyncio.AbstractEventLoop | None:
    """Return the persistent server loop when one is available."""
    try:
        from aragora.server.unified_server import get_main_event_loop

        main_loop = get_main_event_loop()
        if main_loop is not None and main_loop.is_running():
            return main_loop
    except ImportError:
        pass

    try:
        from aragora.utils.async_utils import get_pool_event_loop

        pool_loop = get_pool_event_loop()
        if pool_loop is not None and pool_loop.is_running():
            return pool_loop
    except ImportError:
        pass

    return None


def _handle_persistence_task_result(task: asyncio.Task[Any], task_name: str) -> None:
    """Log background persistence failures without crashing the caller."""
    if task.cancelled():
        logger.debug("Persistence task %s was cancelled", task_name)
        return
    exc = task.exception()
    if exc:
        logger.warning("Persistence task %s failed: %s", task_name, exc, exc_info=exc)


def _handle_persistence_future_result(future: Any, task_name: str) -> None:
    """Log threadsafe persistence failures without crashing the caller."""
    try:
        exc = future.exception()
    except Exception as err:  # noqa: BLE001 - concurrent futures vary by backend
        logger.warning("Persistence task %s failed: %s", task_name, err, exc_info=err)
        return
    if exc:
        logger.warning("Persistence task %s failed: %s", task_name, exc, exc_info=exc)


def _schedule_persistence_task(
    coro_factory: Callable[[], Coroutine[Any, Any, Any]],
    sync_fallback: Callable[[], None],
    task_name: str,
) -> None:
    """Dispatch persistence work to the durable server loop when possible.

    Temporary handler loops disappear as soon as the sync HTTP request returns,
    so raw ``asyncio.create_task(...)`` on the current loop can silently drop
    origin persistence. When no durable loop is available, fall back to the
    existing synchronous write path instead of spawning a doomed task.
    """
    main_loop = _get_persistence_loop()
    if main_loop is None:
        sync_fallback()
        return

    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        current = None

    coro = coro_factory()
    if current is main_loop:
        task = main_loop.create_task(coro, name=task_name)
        task.add_done_callback(lambda t: _handle_persistence_task_result(t, task_name))
        return

    future = asyncio.run_coroutine_threadsafe(coro, main_loop)
    future.add_done_callback(lambda f: _handle_persistence_future_result(f, task_name))


def _store_origin_redis(origin: DebateOrigin) -> None:
    """Store origin in Redis."""
    import json as _json

    try:
        import redis

        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
        key = f"debate_origin:{origin.debate_id}"
        r.setex(key, ORIGIN_TTL_SECONDS, _json.dumps(origin.to_dict()))
    except ImportError:
        raise
    except (OSError, ConnectionError, TimeoutError, ValueError) as e:
        logger.debug("Redis store failed: %s", e)
        raise


def _load_origin_redis(debate_id: str) -> DebateOrigin | None:
    """Load origin from Redis."""
    import json as _json

    try:
        import redis

        r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))
        key = f"debate_origin:{debate_id}"
        data = r.get(key)
        if data:
            return DebateOrigin.from_dict(_json.loads(data))
        return None
    except ImportError:
        raise
    except (OSError, ConnectionError, TimeoutError, ValueError, json.JSONDecodeError) as e:
        logger.debug("Redis load failed: %s", e)
        raise


def _resolve_store_origin_redis():
    """Get _store_origin_redis, respecting patches on the package namespace."""
    pkg = _get_pkg()
    if pkg is not None and hasattr(pkg, "_store_origin_redis"):
        fn = getattr(pkg, "_store_origin_redis")
        if fn is not _store_origin_redis:
            return fn
    return _store_origin_redis


def _resolve_load_origin_redis():
    """Get _load_origin_redis, respecting patches on the package namespace."""
    pkg = _get_pkg()
    if pkg is not None and hasattr(pkg, "_load_origin_redis"):
        fn = getattr(pkg, "_load_origin_redis")
        if fn is not _load_origin_redis:
            return fn
    return _load_origin_redis


def _should_use_redis() -> bool:
    """Return True if Redis should be used for debate origin storage."""
    if is_distributed_state_required():
        return True
    return bool(os.environ.get("REDIS_URL") or os.environ.get("ARAGORA_REDIS_URL"))


def register_debate_origin(
    debate_id: str,
    platform: str,
    channel_id: str,
    user_id: str,
    thread_id: str | None = None,
    message_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str | None = None,
    create_session: bool = False,
) -> DebateOrigin:
    """Register the origin of a debate for result routing.

    Args:
        debate_id: Unique debate identifier
        platform: Platform name (telegram, whatsapp, slack, discord, etc.)
        channel_id: Channel/chat ID on the platform
        user_id: User ID who initiated the debate
        thread_id: Optional thread ID for threaded conversations
        message_id: Optional message ID that started the debate
        metadata: Optional additional metadata (username, etc.)
        session_id: Optional existing session ID to link
        create_session: If True and no session_id, create a new session

    Returns:
        DebateOrigin instance
    """
    # Handle session creation/linking
    linked_session_id = session_id
    if create_session and not session_id:
        try:
            from aragora.connectors.debate_session import get_debate_session_manager

            manager = get_debate_session_manager()
            # Try to create session synchronously
            try:
                # Check if we're in an async context
                loop = asyncio.get_running_loop()
                # In async context, schedule tasks
                asyncio.create_task(
                    _create_and_link_session(manager, platform, user_id, metadata, debate_id)
                )
            except RuntimeError:
                # No running event loop - create one for sync execution
                try:
                    loop = asyncio.new_event_loop()
                    try:
                        session = loop.run_until_complete(
                            manager.create_session(platform, user_id, metadata)
                        )
                        linked_session_id = session.session_id
                        # Link debate to session
                        loop.run_until_complete(manager.link_debate(session.session_id, debate_id))
                    finally:
                        loop.close()
                except RuntimeError:
                    pass
        except ImportError:
            logger.debug("Session management not available")
        except (RuntimeError, OSError, ValueError) as e:
            logger.debug("Session creation failed: %s", e)
    elif session_id:
        # Link existing session to debate
        try:
            from aragora.connectors.debate_session import get_debate_session_manager

            manager = get_debate_session_manager()
            try:
                # Check if we're in an async context
                asyncio.get_running_loop()
                asyncio.create_task(manager.link_debate(session_id, debate_id))
            except RuntimeError:
                # No running event loop - create one for sync execution
                try:
                    loop = asyncio.new_event_loop()
                    try:
                        loop.run_until_complete(manager.link_debate(session_id, debate_id))
                    finally:
                        loop.close()
                except RuntimeError:
                    pass
        except ImportError:
            pass
        except (RuntimeError, OSError, ValueError) as e:
            logger.debug("Session linking failed: %s", e)

    origin = DebateOrigin(
        debate_id=debate_id,
        platform=platform,
        channel_id=channel_id,
        user_id=user_id,
        thread_id=thread_id,
        message_id=message_id,
        session_id=linked_session_id,
        metadata=metadata or {},
    )

    _origin_store[debate_id] = origin

    # Try PostgreSQL first if configured
    pg_store = _get_postgres_store_sync()
    if pg_store:

        def _save_postgres_sync() -> None:
            try:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(pg_store.save(origin))
                finally:
                    loop.close()
            except OSError as e:
                logger.warning("PostgreSQL origin storage failed: %s", e)

        _schedule_persistence_task(
            lambda: pg_store.save(origin),
            _save_postgres_sync,
            task_name=f"debate-origin-save:{debate_id}",
        )
    else:

        def _save_sqlite_sync() -> None:
            try:
                _get_sqlite_store().save(origin)
            except (sqlite3.Error, OSError, RuntimeError, ValueError, Exception) as e:
                logger.warning("SQLite origin storage failed: %s", e)

        _schedule_persistence_task(
            lambda: _get_sqlite_store().save_async(origin),
            _save_sqlite_sync,
            task_name=f"debate-origin-save:{debate_id}",
        )

    # Persist to Redis for distributed deployments
    redis_success = False
    if _should_use_redis():
        store_redis_fn = _resolve_store_origin_redis()
        try:
            store_redis_fn(origin)
            redis_success = True
        except ImportError:
            if is_distributed_state_required():
                raise DistributedStateError(
                    "debate_origin",
                    "Redis library not installed (pip install redis)",
                )
            logger.debug("Redis not available, using SQLite/PostgreSQL only")
        except (OSError, ConnectionError, TimeoutError, ValueError) as e:
            if is_distributed_state_required():
                raise DistributedStateError(
                    "debate_origin",
                    f"Redis connection failed: {e}",
                )
            logger.debug("Redis origin storage not available: %s", e)
        except Exception as e:  # noqa: BLE001 - redis.exceptions.ConnectionError doesn't inherit builtins.ConnectionError
            if is_distributed_state_required():
                raise DistributedStateError(
                    "debate_origin",
                    f"Redis error: {e}",
                )
            logger.debug("Redis origin storage not available: %s", e)

    logger.info(
        "Registered debate origin: %s from %s:%s (redis=%s)",
        debate_id,
        platform,
        channel_id,
        redis_success,
    )
    return origin


def get_debate_origin(debate_id: str) -> DebateOrigin | None:
    """Get the origin of a debate.

    Args:
        debate_id: Debate identifier

    Returns:
        DebateOrigin if found, None otherwise
    """
    # Check in-memory first
    origin = _origin_store.get(debate_id)
    if origin:
        return origin

    # Try Redis
    if _should_use_redis():
        load_redis_fn = _resolve_load_origin_redis()
        try:
            origin = load_redis_fn(debate_id)
            if origin:
                _origin_store[debate_id] = origin  # Cache locally
                return origin
        except (
            ImportError,
            OSError,
            ConnectionError,
            TimeoutError,
            ValueError,
            json.JSONDecodeError,
        ) as e:
            logger.debug("Redis origin lookup not available: %s", e)
        except Exception as e:  # noqa: BLE001 - redis.exceptions.ConnectionError doesn't inherit builtins.ConnectionError
            logger.debug("Redis origin lookup not available: %s", e)

    # Try PostgreSQL if configured
    pg_store = _get_postgres_store_sync()
    if pg_store:
        try:
            # Check if we're in an async context - if so, can't block
            asyncio.get_running_loop()
            # In async context, caller should use get_debate_origin_async instead
        except RuntimeError:
            # No running event loop - create one for sync execution
            try:
                loop = asyncio.new_event_loop()
                try:
                    origin = loop.run_until_complete(pg_store.get(debate_id))
                    if origin:
                        _origin_store[debate_id] = origin  # Cache locally
                        return origin
                finally:
                    loop.close()
            except OSError as e:
                logger.debug("PostgreSQL origin lookup failed: %s", e)
    else:
        # Try SQLite fallback (sync - caller should use get_debate_origin_async if possible)
        try:
            origin = _get_sqlite_store().get(debate_id)
            if origin:
                _origin_store[debate_id] = origin  # Cache locally
                return origin
        except (sqlite3.OperationalError, json.JSONDecodeError) as e:
            logger.debug("SQLite origin lookup failed: %s", e)

    return None


async def get_debate_origin_async(debate_id: str) -> DebateOrigin | None:
    """Async version of get_debate_origin that doesn't block event loop.

    Prefer this in async contexts to avoid blocking the event loop
    with synchronous SQLite operations.

    Args:
        debate_id: Debate identifier

    Returns:
        DebateOrigin if found, None otherwise
    """
    # Check in-memory first
    origin = _origin_store.get(debate_id)
    if origin:
        return origin

    # Try Redis
    if _should_use_redis():
        load_redis_fn = _resolve_load_origin_redis()
        try:
            origin = load_redis_fn(debate_id)
            if origin:
                _origin_store[debate_id] = origin  # Cache locally
                return origin
        except (
            ImportError,
            OSError,
            ConnectionError,
            TimeoutError,
            ValueError,
            json.JSONDecodeError,
        ) as e:
            logger.debug("Redis origin lookup not available: %s", e)

    # Try PostgreSQL if configured
    pg_store = await _get_postgres_store()
    if pg_store:
        try:
            origin = await pg_store.get(debate_id)
            if origin:
                _origin_store[debate_id] = origin  # Cache locally
                return origin
        except OSError as e:
            logger.debug("PostgreSQL origin lookup failed: %s", e)
    else:
        # Try SQLite fallback with async method
        try:
            origin = await _get_sqlite_store().get_async(debate_id)
            if origin:
                _origin_store[debate_id] = origin  # Cache locally
                return origin
        except (sqlite3.OperationalError, json.JSONDecodeError) as e:
            logger.debug("SQLite origin lookup failed: %s", e)

    return None


def mark_result_sent(debate_id: str) -> None:
    """Mark that the result has been sent for a debate."""
    origin = get_debate_origin(debate_id)
    if origin:
        origin.result_sent = True
        origin.result_sent_at = time.time()

        # Update PostgreSQL if configured
        pg_store = _get_postgres_store_sync()
        if pg_store:

            def _save_postgres_sync() -> None:
                try:
                    loop = asyncio.new_event_loop()
                    try:
                        loop.run_until_complete(pg_store.save(origin))
                    finally:
                        loop.close()
                except OSError as e:
                    logger.debug("PostgreSQL update failed: %s", e)

            _schedule_persistence_task(
                lambda: pg_store.save(origin),
                _save_postgres_sync,
                task_name=f"debate-origin-mark-sent:{debate_id}",
            )
        else:

            def _save_sqlite_sync() -> None:
                try:
                    _get_sqlite_store().save(origin)
                except sqlite3.OperationalError as e:
                    logger.debug("SQLite update failed: %s", e)

            _schedule_persistence_task(
                lambda: _get_sqlite_store().save_async(origin),
                _save_sqlite_sync,
                task_name=f"debate-origin-mark-sent:{debate_id}",
            )

        # Update Redis if available
        if _should_use_redis():
            store_redis_fn = _resolve_store_origin_redis()
            try:
                store_redis_fn(origin)
            except (ImportError, OSError, ConnectionError, TimeoutError, ValueError) as e:
                # Catch Redis errors (connection, timeout, etc.)
                logger.debug("Redis update skipped: %s", e)
            except Exception as e:  # noqa: BLE001 - redis.exceptions.ConnectionError doesn't inherit builtins.ConnectionError
                logger.debug("Redis update skipped: %s", e)


def cleanup_expired_origins() -> int:
    """Remove expired origin records from in-memory store and persistent storage.

    This function cleans up expired debate origins from:
    1. In-memory cache
    2. PostgreSQL database (if configured)
    3. SQLite database (fallback persistent storage)

    Should be called periodically (e.g., hourly) to prevent unbounded growth.

    Returns:
        Total count of expired records removed
    """
    total_cleaned = 0
    now = time.time()

    # Clean up in-memory store
    expired = [k for k, v in _origin_store.items() if now - v.created_at > ORIGIN_TTL_SECONDS]

    for k in expired:
        del _origin_store[k]

    if expired:
        logger.info("Cleaned up %s expired debate origins from memory", len(expired))
        total_cleaned += len(expired)

    # Clean up PostgreSQL if configured
    pg_store = _get_postgres_store_sync()
    if pg_store:
        try:
            # Check if we're in an async context - if so, can't block
            asyncio.get_running_loop()
            # In async context, caller should use an async cleanup method
        except RuntimeError:
            # No running event loop - create one for sync execution
            try:
                loop = asyncio.new_event_loop()
                try:
                    pg_cleaned = loop.run_until_complete(
                        pg_store.cleanup_expired(ORIGIN_TTL_SECONDS)
                    )
                    if pg_cleaned > 0:
                        logger.info(
                            "Cleaned up %s expired debate origins from PostgreSQL", pg_cleaned
                        )
                        total_cleaned += pg_cleaned
                finally:
                    loop.close()
            except OSError as e:
                logger.warning("PostgreSQL cleanup failed: %s", e)
    else:
        # Clean up SQLite store (fallback)
        try:
            sqlite_cleaned = _get_sqlite_store().cleanup_expired(ORIGIN_TTL_SECONDS)
            if sqlite_cleaned > 0:
                logger.info("Cleaned up %s expired debate origins from SQLite", sqlite_cleaned)
                total_cleaned += sqlite_cleaned
        except sqlite3.OperationalError as e:
            logger.warning("SQLite cleanup failed: %s", e)

    return total_cleaned
