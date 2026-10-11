"""
Token Revocation Middleware.

Provides token revocation support for API authentication.
Maintains a store of revoked tokens with TTL-based cleanup.

Features:
- In-memory store for single-instance deployments
- Redis backend for distributed deployments
- TTL-based automatic cleanup
- Thread-safe operations

Usage:
    from aragora.server.middleware.token_revocation import (
        revoke_token,
        is_token_revoked,
        get_revocation_store,
    )

    # Revoke a token
    revoke_token("user-token-123", reason="logout")

    # Check if token is revoked
    if is_token_revoked("user-token-123"):
        return error_response("Token has been revoked", 401)
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from aragora.exceptions import REDIS_CONNECTION_ERRORS

logger = logging.getLogger(__name__)


@dataclass
class RevocationEntry:
    """Entry in the revocation store."""

    token_hash: str  # SHA-256 hash of token (don't store raw tokens)
    revoked_at: datetime
    expires_at: datetime  # When to auto-cleanup this entry
    reason: str = ""
    revoked_by: str = ""  # User/system that revoked
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        """Check if this entry has expired and can be cleaned up."""
        return datetime.now(timezone.utc) > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "token_hash": self.token_hash,
            "revoked_at": self.revoked_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "reason": self.reason,
            "revoked_by": self.revoked_by,
            "metadata": self.metadata,
        }


class RevocationStore(Protocol):
    """Protocol for token revocation stores."""

    def add(self, entry: RevocationEntry) -> None:
        """Add a revocation entry."""
        ...

    def contains(self, token_hash: str) -> bool:
        """Check if a token hash is revoked."""
        ...

    def remove(self, token_hash: str) -> bool:
        """Remove a revocation entry."""
        ...

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        ...

    def count(self) -> int:
        """Get total number of revoked tokens."""
        ...


class InMemoryRevocationStore:
    """
    In-memory token revocation store.

    Suitable for single-instance deployments.
    Thread-safe with periodic cleanup.
    """

    def __init__(self, cleanup_interval: float = 300.0):
        """
        Initialize the in-memory store.

        Args:
            cleanup_interval: Seconds between automatic cleanup runs
        """
        self._store: dict[str, RevocationEntry] = {}
        self._lock = threading.Lock()
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()

    def add(self, entry: RevocationEntry) -> None:
        """Add a revocation entry."""
        with self._lock:
            self._store[entry.token_hash] = entry
            self._maybe_cleanup()
        logger.debug("token_revoked hash=%s... reason=%s", entry.token_hash[:8], entry.reason)

    def contains(self, token_hash: str) -> bool:
        """Check if a token hash is revoked."""
        with self._lock:
            entry = self._store.get(token_hash)
            if entry is None:
                return False
            # Check if entry has expired
            if entry.is_expired():
                del self._store[token_hash]
                return False
            return True

    def remove(self, token_hash: str) -> bool:
        """Remove a revocation entry (un-revoke)."""
        with self._lock:
            if token_hash in self._store:
                del self._store[token_hash]
                return True
            return False

    def cleanup_expired(self) -> int:
        """Remove expired entries."""
        with self._lock:
            now = datetime.now(timezone.utc)
            expired = [h for h, e in self._store.items() if e.expires_at < now]
            for h in expired:
                del self._store[h]
            self._last_cleanup = time.time()
            if expired:
                logger.debug("token_revocation_cleanup removed=%s", len(expired))
            return len(expired)

    def count(self) -> int:
        """Get total number of revoked tokens."""
        with self._lock:
            return len(self._store)

    def _maybe_cleanup(self) -> None:
        """Run cleanup if interval has passed."""
        if time.time() - self._last_cleanup > self._cleanup_interval:
            # Run cleanup in a separate thread to avoid blocking
            threading.Thread(target=self.cleanup_expired, daemon=True).start()


class RedisRevocationStore:
    """
    Redis-backed token revocation store.

    Suitable for distributed deployments with multiple instances.
    Uses Redis SET with TTL for automatic expiration.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        key_prefix: str = "aragora:revoked:",
    ):
        """
        Initialize the Redis store.

        Args:
            redis_url: Redis connection URL (defaults to REDIS_URL env var)
            key_prefix: Prefix for Redis keys
        """
        self._redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self._key_prefix = key_prefix
        self._client: Any | None = None

    def _get_client(self) -> Any:
        """Get or create Redis client."""
        if self._client is None:
            try:
                import redis

                self._client = redis.from_url(self._redis_url)
            except ImportError:
                logger.debug("redis package not installed, falling back to in-memory")
                raise
        return self._client

    def _key(self, token_hash: str) -> str:
        """Get Redis key for a token hash."""
        return f"{self._key_prefix}{token_hash}"

    def add(self, entry: RevocationEntry) -> None:
        """Add a revocation entry with TTL."""
        try:
            client = self._get_client()
            ttl_seconds = int((entry.expires_at - datetime.now(timezone.utc)).total_seconds())
            if ttl_seconds > 0:
                import json

                client.setex(
                    self._key(entry.token_hash),
                    ttl_seconds,
                    json.dumps(entry.to_dict()),
                )
                logger.debug(
                    "token_revoked_redis hash=%s... ttl=%ss reason=%s",
                    entry.token_hash[:8],
                    ttl_seconds,
                    entry.reason,
                )
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("Redis revocation store error: %s", e)
            raise

    def contains(self, token_hash: str) -> bool:
        """Check if a token hash is revoked."""
        try:
            client = self._get_client()
            return client.exists(self._key(token_hash)) > 0
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("Redis revocation check error: %s", e)
            return False

    def remove(self, token_hash: str) -> bool:
        """Remove a revocation entry."""
        try:
            client = self._get_client()
            return client.delete(self._key(token_hash)) > 0
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("Redis revocation remove error: %s", e)
            return False

    def cleanup_expired(self) -> int:
        """Redis handles TTL expiration automatically."""
        return 0

    def count(self) -> int:
        """Get approximate count of revoked tokens."""
        try:
            client = self._get_client()
            # Use SCAN to count keys matching prefix
            count = 0
            cursor = 0
            while True:
                cursor, keys = client.scan(cursor, match=f"{self._key_prefix}*", count=100)
                count += len(keys)
                if cursor == 0:
                    break
            return count
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("Redis count error: %s", e)
            return 0


# Global store instance
_revocation_store: RevocationStore | None = None
_store_lock = threading.Lock()


def get_revocation_store() -> RevocationStore:
    """
    Get the global revocation store.

    Uses Redis if REDIS_URL is set, otherwise in-memory.

    Raises:
        DistributedStateError: If distributed state is required but Redis unavailable.
    """
    global _revocation_store
    if _revocation_store is None:
        with _store_lock:
            if _revocation_store is None:
                redis_url = os.environ.get("REDIS_URL")
                if redis_url:
                    try:
                        _revocation_store = RedisRevocationStore(redis_url)
                        logger.info("token_revocation using Redis store")
                    except ImportError:
                        # Check if distributed state is required
                        from aragora.config.distributed import is_distributed_state_required
                        from aragora.control_plane.leader import DistributedStateError

                        if is_distributed_state_required():
                            raise DistributedStateError(
                                "token_revocation",
                                "Redis not available for distributed token revocation",
                            )
                        _revocation_store = InMemoryRevocationStore()
                        logger.warning(
                            "token_revocation using in-memory store (redis not available). "
                            "Token revocations will not be shared across instances."
                        )
                else:
                    # No Redis URL - check if distributed state is required
                    from aragora.config.distributed import is_distributed_state_required
                    from aragora.control_plane.leader import DistributedStateError

                    if is_distributed_state_required():
                        raise DistributedStateError(
                            "token_revocation",
                            "REDIS_URL not configured for distributed token revocation",
                        )
                    _revocation_store = InMemoryRevocationStore()
                    logger.debug("token_revocation using in-memory store")
    return _revocation_store


def hash_token(token: str) -> str:
    """
    Hash a token for storage.

    Never store raw tokens - always hash them.

    Args:
        token: Raw token string

    Returns:
        SHA-256 hash of the token
    """
    return hashlib.sha256(token.encode()).hexdigest()


def revoke_token(
    token: str,
    reason: str = "",
    revoked_by: str = "system",
    ttl_seconds: int = 86400,  # 24 hours default
    metadata: dict[str, Any] | None = None,
) -> RevocationEntry:
    """
    Revoke a token.

    Args:
        token: Token to revoke
        reason: Reason for revocation (logout, security, etc.)
        revoked_by: User/system that initiated revocation
        ttl_seconds: How long to keep the revocation entry
        metadata: Additional context

    Returns:
        The revocation entry created
    """
    now = datetime.now(timezone.utc)
    entry = RevocationEntry(
        token_hash=hash_token(token),
        revoked_at=now,
        expires_at=datetime.fromtimestamp(now.timestamp() + ttl_seconds, tz=timezone.utc),
        reason=reason,
        revoked_by=revoked_by,
        metadata=metadata or {},
    )

    store = get_revocation_store()
    store.add(entry)

    logger.info(
        "token_revoked reason=%s revoked_by=%s ttl=%ss hash=%s...",
        reason,
        revoked_by,
        ttl_seconds,
        entry.token_hash[:8],
    )

    # Log audit event for security tracking
    try:
        from aragora.server.middleware.audit_logger import audit_token_revoked

        audit_token_revoked(
            token_hash=entry.token_hash,
            revoked_by=revoked_by,
            reason=reason,
        )
    except ImportError:
        pass  # Audit logger not available

    return entry


def is_token_revoked(token: str) -> bool:
    """
    Check if a token has been revoked.

    Args:
        token: Token to check

    Returns:
        True if token is revoked, False otherwise
    """
    store = get_revocation_store()
    return store.contains(hash_token(token))


def unrevoke_token(token: str) -> bool:
    """
    Un-revoke a token (remove from revocation list).

    Use with caution - only for administrative purposes.

    Args:
        token: Token to un-revoke

    Returns:
        True if token was revoked and is now un-revoked
    """
    store = get_revocation_store()
    result = store.remove(hash_token(token))
    if result:
        logger.warning("token_unrevoked hash=%s...", hash_token(token)[:8])
    return result


def get_revocation_stats() -> dict[str, Any]:
    """
    Get statistics about the revocation store.

    Returns:
        Dictionary with store statistics
    """
    store = get_revocation_store()
    store_type = "redis" if isinstance(store, RedisRevocationStore) else "memory"
    return {
        "store_type": store_type,
        "revoked_count": store.count(),
    }


__all__ = [
    "RevocationEntry",
    "RevocationStore",
    "InMemoryRevocationStore",
    "RedisRevocationStore",
    "get_revocation_store",
    "hash_token",
    "revoke_token",
    "is_token_revoked",
    "unrevoke_token",
    "get_revocation_stats",
]
