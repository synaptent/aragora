"""
Account Lockout System for brute-force prevention.

Provides a LockoutTracker class that tracks failed login attempts by both
email and IP address, implementing exponential backoff lockouts.

Supports Redis backend for distributed deployments with automatic fallback
to in-memory storage for single-instance deployments.

Usage:
    from aragora.auth.lockout import get_lockout_tracker, LockoutTracker

    tracker = get_lockout_tracker()

    # Check if locked before login attempt
    if tracker.is_locked(email=email, ip=client_ip):
        remaining = tracker.get_remaining_time(email=email, ip=client_ip)
        return error(f"Locked for {remaining} seconds")

    # On failed login
    tracker.record_failure(email=email, ip=client_ip)

    # On successful login
    tracker.reset(email=email, ip=client_ip)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class RedisClientProtocol(Protocol):
    """Protocol for Redis client operations we use."""

    def ping(self) -> Any: ...
    def get(self, key: str) -> str | None: ...
    def setex(self, key: str, ttl: int, value: str) -> Any: ...
    def delete(self, key: str) -> Any: ...


logger = logging.getLogger(__name__)


@dataclass
class LockoutEntry:
    """Represents a lockout tracking entry."""

    failed_attempts: int = 0
    lockout_until: float | None = None  # Unix timestamp
    last_attempt: float | None = None  # Unix timestamp

    def is_locked(self) -> bool:
        """Check if this entry is currently locked."""
        if self.lockout_until is None:
            return False
        return time.time() < self.lockout_until

    def get_remaining_seconds(self) -> int:
        """Get remaining lockout time in seconds."""
        if self.lockout_until is None:
            return 0
        remaining = self.lockout_until - time.time()
        return max(0, int(remaining))


class LockoutBackend(ABC):
    """Abstract base class for lockout storage backends."""

    @abstractmethod
    def get_entry(self, key: str) -> LockoutEntry | None:
        """Get lockout entry for a key."""
        pass

    @abstractmethod
    def set_entry(self, key: str, entry: LockoutEntry, ttl_seconds: int) -> None:
        """Set lockout entry with TTL."""
        pass

    @abstractmethod
    def delete_entry(self, key: str) -> None:
        """Delete a lockout entry."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the backend is available."""
        pass


class InMemoryLockoutBackend(LockoutBackend):
    """
    In-memory lockout storage backend.

    Thread-safe implementation for single-instance deployments.
    Entries automatically expire based on TTL.
    """

    def __init__(self) -> None:
        self._store: dict[str, tuple[LockoutEntry, float]] = {}  # key -> (entry, expires_at)
        self._lock = threading.Lock()

    def get_entry(self, key: str) -> LockoutEntry | None:
        """Get lockout entry, returning None if expired."""
        with self._lock:
            data = self._store.get(key)
            if data is None:
                return None
            entry, expires_at = data
            if time.time() > expires_at:
                del self._store[key]
                return None
            return entry

    def set_entry(self, key: str, entry: LockoutEntry, ttl_seconds: int) -> None:
        """Set lockout entry with TTL."""
        expires_at = time.time() + ttl_seconds
        with self._lock:
            self._store[key] = (entry, expires_at)

    def delete_entry(self, key: str) -> None:
        """Delete a lockout entry."""
        with self._lock:
            self._store.pop(key, None)

    def is_available(self) -> bool:
        """In-memory backend is always available."""
        return True

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns number of entries removed."""
        removed = 0
        now = time.time()
        with self._lock:
            expired_keys = [k for k, (_, exp) in self._store.items() if now > exp]
            for key in expired_keys:
                del self._store[key]
                removed += 1
        return removed


class RedisLockoutBackend(LockoutBackend):
    """
    Redis-backed lockout storage for distributed deployments.

    Requires redis-py library. Falls back gracefully if Redis is unavailable.
    """

    def __init__(
        self,
        redis_url: str | None = None,
        key_prefix: str = "aragora:lockout:",
    ) -> None:
        """
        Initialize Redis backend.

        Args:
            redis_url: Redis connection URL. If None, uses REDIS_URL env var.
            key_prefix: Prefix for all lockout keys in Redis.
        """
        self._redis_url = redis_url or os.getenv("REDIS_URL")
        self._key_prefix = key_prefix
        self._client: RedisClientProtocol | None = None
        self._available = False

        if self._redis_url:
            self._init_client()

    def _init_client(self) -> None:
        """Initialize Redis client."""
        redis_url = self._redis_url
        if redis_url is None:
            return

        try:
            import redis

            client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            # Test connection
            client.ping()
            self._client = client
            self._available = True
            logger.info("Redis lockout backend connected")
        except ImportError:
            logger.warning("redis-py not installed, Redis backend unavailable")
            self._available = False
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Redis connection failed: %s", e)
            self._available = False

    def _make_key(self, key: str) -> str:
        """Create full Redis key with prefix."""
        return f"{self._key_prefix}{key}"

    def get_entry(self, key: str) -> LockoutEntry | None:
        """Get lockout entry from Redis."""
        if not self._available or self._client is None:
            return None

        try:
            import json

            data = self._client.get(self._make_key(key))
            if data is None:
                return None

            parsed = json.loads(data)
            return LockoutEntry(
                failed_attempts=parsed.get("failed_attempts", 0),
                lockout_until=parsed.get("lockout_until"),
                last_attempt=parsed.get("last_attempt"),
            )
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning("Redis get failed - data error: %s", e)
            return None
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Redis get failed - connection error: %s", e)
            return None

    def set_entry(self, key: str, entry: LockoutEntry, ttl_seconds: int) -> None:
        """Set lockout entry in Redis with TTL."""
        if not self._available or self._client is None:
            return

        try:
            import json

            data = json.dumps(
                {
                    "failed_attempts": entry.failed_attempts,
                    "lockout_until": entry.lockout_until,
                    "last_attempt": entry.last_attempt,
                }
            )
            self._client.setex(self._make_key(key), ttl_seconds, data)
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Redis set failed: %s", e)

    def delete_entry(self, key: str) -> None:
        """Delete lockout entry from Redis."""
        if not self._available or self._client is None:
            return

        try:
            self._client.delete(self._make_key(key))
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Redis delete failed: %s", e)

    def is_available(self) -> bool:
        """Check if Redis is available."""
        if not self._client:
            return False

        try:
            self._client.ping()
            return True
        except (ConnectionError, TimeoutError, OSError, AttributeError, RuntimeError) as e:
            # Expected Redis connection issues or client misconfiguration
            logger.debug("Redis ping failed: %s", e)
            self._available = False
            return False


class LockoutTracker:
    """
    Tracks failed login attempts and enforces account lockouts.

    Implements exponential backoff lockout policy:
    - 5 failed attempts: 1 minute lockout
    - 10 failed attempts: 15 minute lockout
    - 15+ failed attempts: 1 hour lockout

    Tracks both by email (account-based) and IP address (network-based).
    A lockout on either dimension blocks login attempts.
    """

    # Lockout thresholds (attempts)
    THRESHOLD_1 = 5  # First lockout threshold
    THRESHOLD_2 = 10  # Second lockout threshold
    THRESHOLD_3 = 15  # Third lockout threshold

    # Lockout durations in seconds
    DURATION_1 = 60  # 1 minute
    DURATION_2 = 15 * 60  # 15 minutes
    DURATION_3 = 60 * 60  # 1 hour

    # Maximum TTL for entries (cleanup after this time)
    MAX_TTL = 24 * 60 * 60  # 24 hours

    def __init__(
        self,
        redis_url: str | None = None,
        use_redis: bool = True,
    ) -> None:
        """
        Initialize lockout tracker.

        Args:
            redis_url: Optional Redis URL for distributed storage.
            use_redis: Whether to attempt Redis connection. If False or
                      Redis unavailable, uses in-memory storage.
        """
        self._memory_backend = InMemoryLockoutBackend()
        self._redis_backend: RedisLockoutBackend | None = None

        if use_redis:
            self._redis_backend = RedisLockoutBackend(redis_url)
            if not self._redis_backend.is_available():
                _env = os.environ.get("ARAGORA_ENV", "production").lower()
                if _env not in ("development", "dev", "test", "local"):
                    logger.critical(
                        "SECURITY: Redis unavailable in %s — using in-memory lockout storage. "
                        "Lockout state will be LOST on restart and NOT shared across instances. "
                        "This allows lockout bypass via server restart or multi-instance routing. "
                        "Configure REDIS_URL to enable distributed lockout tracking.",
                        _env,
                    )
                else:
                    logger.info("Redis unavailable, using in-memory lockout storage")
                self._redis_backend = None

    @property
    def _backend(self) -> LockoutBackend:
        """Get the active backend (Redis if available, else memory)."""
        if self._redis_backend and self._redis_backend.is_available():
            return self._redis_backend
        return self._memory_backend

    def _email_key(self, email: str) -> str:
        """Generate key for email-based tracking."""
        return f"email:{email.lower()}"

    def _ip_key(self, ip: str) -> str:
        """Generate key for IP-based tracking."""
        return f"ip:{ip}"

    def _calculate_lockout_duration(self, attempts: int) -> int | None:
        """
        Calculate lockout duration based on failed attempts.

        Returns duration in seconds, or None if no lockout needed.
        """
        if attempts >= self.THRESHOLD_3:
            return self.DURATION_3
        elif attempts >= self.THRESHOLD_2:
            return self.DURATION_2
        elif attempts >= self.THRESHOLD_1:
            return self.DURATION_1
        return None

    def record_failure(
        self,
        email: str | None = None,
        ip: str | None = None,
    ) -> tuple[int, int | None]:
        """
        Record a failed login attempt.

        Args:
            email: User email address
            ip: Client IP address

        Returns:
            Tuple of (total_attempts, lockout_seconds_if_locked)
            lockout_seconds is None if not locked, otherwise the duration.
        """
        now = time.time()
        max_attempts = 0
        lockout_duration: int | None = None

        for key in [
            self._email_key(email) if email else None,
            self._ip_key(ip) if ip else None,
        ]:
            if key is None:
                continue

            entry = self._backend.get_entry(key) or LockoutEntry()
            entry.failed_attempts += 1
            entry.last_attempt = now

            # Calculate if lockout is needed
            duration = self._calculate_lockout_duration(entry.failed_attempts)
            if duration:
                entry.lockout_until = now + duration
                if lockout_duration is None or duration > lockout_duration:
                    lockout_duration = duration
                logger.warning(
                    "Lockout triggered: key=%s, attempts=%s, duration=%ss",
                    key,
                    entry.failed_attempts,
                    duration,
                )

            # Store with TTL
            ttl = max(duration or 0, self.MAX_TTL)
            self._backend.set_entry(key, entry, ttl)

            max_attempts = max(max_attempts, entry.failed_attempts)

        return max_attempts, lockout_duration

    def is_locked(
        self,
        email: str | None = None,
        ip: str | None = None,
    ) -> bool:
        """
        Check if login is locked for the given email or IP.

        Returns True if either the email OR IP is currently locked.

        Args:
            email: User email address
            ip: Client IP address

        Returns:
            True if locked, False otherwise.
        """
        for key in [
            self._email_key(email) if email else None,
            self._ip_key(ip) if ip else None,
        ]:
            if key is None:
                continue

            entry = self._backend.get_entry(key)
            if entry and entry.is_locked():
                return True

        return False

    def get_remaining_time(
        self,
        email: str | None = None,
        ip: str | None = None,
    ) -> int:
        """
        Get remaining lockout time in seconds.

        Returns the maximum remaining time across email and IP.

        Args:
            email: User email address
            ip: Client IP address

        Returns:
            Remaining lockout seconds (0 if not locked).
        """
        max_remaining = 0

        for key in [
            self._email_key(email) if email else None,
            self._ip_key(ip) if ip else None,
        ]:
            if key is None:
                continue

            entry = self._backend.get_entry(key)
            if entry:
                remaining = entry.get_remaining_seconds()
                max_remaining = max(max_remaining, remaining)

        return max_remaining

    def reset(
        self,
        email: str | None = None,
        ip: str | None = None,
    ) -> None:
        """
        Reset lockout state after successful login.

        Clears both failed attempts counter and any active lockout.

        Args:
            email: User email address
            ip: Client IP address
        """
        for key in [
            self._email_key(email) if email else None,
            self._ip_key(ip) if ip else None,
        ]:
            if key is None:
                continue

            self._backend.delete_entry(key)
            logger.debug("Lockout reset: key=%s", key)

    def get_info(
        self,
        email: str | None = None,
        ip: str | None = None,
    ) -> dict:
        """
        Get detailed lockout information.

        Args:
            email: User email address
            ip: Client IP address

        Returns:
            Dict with lockout details for both email and IP.
        """
        info: dict = {
            "is_locked": self.is_locked(email=email, ip=ip),
            "remaining_seconds": self.get_remaining_time(email=email, ip=ip),
        }

        if email:
            email_entry = self._backend.get_entry(self._email_key(email))
            info["email"] = {
                "failed_attempts": email_entry.failed_attempts if email_entry else 0,
                "is_locked": email_entry.is_locked() if email_entry else False,
                "remaining_seconds": email_entry.get_remaining_seconds() if email_entry else 0,
                "lockout_until": (
                    datetime.fromtimestamp(email_entry.lockout_until).isoformat()
                    if email_entry and email_entry.lockout_until
                    else None
                ),
            }

        if ip:
            ip_entry = self._backend.get_entry(self._ip_key(ip))
            info["ip"] = {
                "failed_attempts": ip_entry.failed_attempts if ip_entry else 0,
                "is_locked": ip_entry.is_locked() if ip_entry else False,
                "remaining_seconds": ip_entry.get_remaining_seconds() if ip_entry else 0,
                "lockout_until": (
                    datetime.fromtimestamp(ip_entry.lockout_until).isoformat()
                    if ip_entry and ip_entry.lockout_until
                    else None
                ),
            }

        return info

    def admin_unlock(
        self,
        email: str | None = None,
        ip: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        """
        Admin-initiated unlock of an account or IP.

        This resets the lockout without requiring successful login.
        Should only be called by admin endpoints.

        Args:
            email: User email to unlock
            ip: IP address to unlock
            user_id: User ID (for logging purposes)

        Returns:
            True if any lockout was cleared.
        """
        cleared = False

        for key in [
            self._email_key(email) if email else None,
            self._ip_key(ip) if ip else None,
        ]:
            if key is None:
                continue

            entry = self._backend.get_entry(key)
            if entry:
                self._backend.delete_entry(key)
                cleared = True
                logger.info("Admin unlock: key=%s, user_id=%s", key, user_id)

        return cleared

    @property
    def backend_type(self) -> str:
        """Return the current backend type."""
        if self._redis_backend and self._redis_backend.is_available():
            return "redis"
        return "memory"


# Global lockout tracker instance
_lockout_tracker: LockoutTracker | None = None
_tracker_lock = threading.Lock()


def get_lockout_tracker(
    redis_url: str | None = None,
    use_redis: bool = True,
) -> LockoutTracker:
    """
    Get or create the global LockoutTracker instance.

    Args:
        redis_url: Optional Redis URL (only used on first call)
        use_redis: Whether to use Redis (only used on first call)

    Returns:
        The global LockoutTracker instance.
    """
    global _lockout_tracker

    if _lockout_tracker is not None:
        return _lockout_tracker

    with _tracker_lock:
        if _lockout_tracker is None:
            _lockout_tracker = LockoutTracker(redis_url=redis_url, use_redis=use_redis)

    return _lockout_tracker


def reset_lockout_tracker() -> None:
    """Reset the global lockout tracker (for testing)."""
    global _lockout_tracker
    with _tracker_lock:
        _lockout_tracker = None


__all__ = [
    "LockoutTracker",
    "LockoutEntry",
    "LockoutBackend",
    "InMemoryLockoutBackend",
    "RedisLockoutBackend",
    "get_lockout_tracker",
    "reset_lockout_tracker",
]
