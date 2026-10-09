"""
Resilience Patterns for Email Connectors.

Provides production-ready resilience patterns for email sync:
- Exponential backoff retry for transient failures
- Circuit breaker for API protection
- OAuth token persistence with refresh
- Rate limiting protection
- Timeout enforcement

Usage:
    from aragora.connectors.email.resilience import (
        ResilientEmailClient,
        OAuthTokenStore,
        EmailCircuitBreaker,
    )

    # Create resilient client
    client = ResilientEmailClient(
        provider="gmail",
        token_store=OAuthTokenStore(storage_path="tokens.db"),
    )

    # Make resilient API calls
    result = await client.execute(
        lambda: gmail_api.get_message(msg_id),
        operation="get_message",
    )
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, TypeVar
from collections.abc import Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")

# =============================================================================
# Configuration
# =============================================================================


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple = (
        ConnectionError,
        TimeoutError,
        asyncio.TimeoutError,
    )
    retryable_status_codes: tuple = (429, 500, 502, 503, 504)


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    failure_threshold: int = 5
    recovery_timeout_seconds: float = 60.0
    half_open_max_calls: int = 3
    success_threshold: int = 2


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""

    requests_per_minute: int = 60
    burst_size: int = 10
    window_seconds: float = 60.0


# =============================================================================
# Circuit Breaker
# =============================================================================


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing recovery


class EmailCircuitBreaker:
    """
    Circuit breaker for email API calls.

    Prevents cascading failures by stopping calls when failure rate is high.
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ):
        """Initialize circuit breaker."""
        self.name = name
        self.config = config or CircuitBreakerConfig()

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        return self._state

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (blocking calls)."""
        return self._state == CircuitState.OPEN

    async def can_execute(self) -> bool:
        """Check if a call can be executed."""
        async with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                # Check if recovery timeout has elapsed
                if self._last_failure_time:
                    elapsed = time.time() - self._last_failure_time
                    if elapsed >= self.config.recovery_timeout_seconds:
                        self._state = CircuitState.HALF_OPEN
                        self._half_open_calls = 1  # Count this call
                        logger.info("[CircuitBreaker:%s] Transitioning to HALF_OPEN", self.name)
                        return True
                return False

            if self._state == CircuitState.HALF_OPEN:
                # Allow limited calls in half-open state
                if self._half_open_calls < self.config.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False

            return False

    async def record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("[CircuitBreaker:%s] Circuit CLOSED after recovery", self.name)
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = 0

    async def record_failure(self, error: Exception) -> None:
        """Record a failed call."""
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open reopens the circuit
                self._state = CircuitState.OPEN
                self._success_count = 0
                logger.warning(
                    "[CircuitBreaker:%s] Circuit OPEN after half-open failure: %s", self.name, error
                )

            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.config.failure_threshold:
                    self._state = CircuitState.OPEN
                    logger.warning(
                        "[CircuitBreaker:%s] Circuit OPEN after %s failures: %s",
                        self.name,
                        self._failure_count,
                        error,
                    )

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure_time": self._last_failure_time,
        }


# =============================================================================
# Retry with Exponential Backoff
# =============================================================================


class RetryExecutor:
    """Executes operations with retry and exponential backoff."""

    def __init__(self, config: RetryConfig | None = None):
        """Initialize retry executor."""
        self.config = config or RetryConfig()

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for next retry with exponential backoff and jitter."""
        import random

        delay = self.config.initial_delay_seconds * (self.config.exponential_base**attempt)
        delay = min(delay, self.config.max_delay_seconds)

        if self.config.jitter:
            delay *= 0.5 + random.random()  # noqa: S311 -- retry jitter

        return delay

    def _is_retryable(self, error: Exception) -> bool:
        """Check if error is retryable."""
        # Check exception type
        if isinstance(error, self.config.retryable_exceptions):
            return True

        # Check HTTP status code if available
        if hasattr(error, "response") and hasattr(error.response, "status_code"):
            return error.response.status_code in self.config.retryable_status_codes

        # Check for rate limiting indicators
        error_str = str(error).lower()
        if "rate limit" in error_str or "429" in error_str or "too many" in error_str:
            return True

        return False

    async def execute(
        self,
        operation: Callable[[], T],
        operation_name: str = "operation",
    ) -> T:
        """
        Execute operation with retry.

        Args:
            operation: Async callable to execute
            operation_name: Name for logging

        Returns:
            Result of the operation

        Raises:
            Last exception if all retries fail
        """
        last_error: Exception | None = None

        for attempt in range(self.config.max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(operation):
                    return await operation()
                else:
                    return operation()

            except (
                OSError,
                ConnectionError,
                TimeoutError,
                asyncio.TimeoutError,
                RuntimeError,
            ) as e:
                last_error = e

                if not self._is_retryable(e):
                    logger.warning("[Retry] Non-retryable error in %s: %s", operation_name, e)
                    raise

                if attempt >= self.config.max_retries:
                    logger.error(
                        "[Retry] All %s retries exhausted for %s: %s",
                        self.config.max_retries,
                        operation_name,
                        e,
                    )
                    raise

                delay = self._calculate_delay(attempt)
                logger.warning(
                    "[Retry] Attempt %s/%s for %s failed: %s. Retrying in %.1fs",
                    attempt + 1,
                    self.config.max_retries,
                    operation_name,
                    e,
                    delay,
                )
                await asyncio.sleep(delay)

        # Should never reach here, but just in case
        if last_error:
            raise last_error
        raise RuntimeError(f"Retry loop exited unexpectedly for {operation_name}")


# =============================================================================
# OAuth Token Store
# =============================================================================


@dataclass
class OAuthToken:
    """OAuth token with metadata."""

    access_token: str
    refresh_token: str
    expires_at: datetime
    token_type: str = "Bearer"  # noqa: S105 -- OAuth2 token type
    scope: str = ""
    provider: str = ""  # "gmail" or "outlook"
    tenant_id: str = ""
    user_id: str = ""

    @property
    def is_expired(self) -> bool:
        """Check if token is expired (with 5 minute buffer)."""
        return datetime.now(timezone.utc) >= (self.expires_at - timedelta(minutes=5))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
            "token_type": self.token_type,
            "scope": self.scope,
            "provider": self.provider,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OAuthToken:
        """Create from dictionary."""
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.fromisoformat(data["expires_at"]),
            token_type=data.get("token_type", "Bearer"),
            scope=data.get("scope", ""),
            provider=data.get("provider", ""),
            tenant_id=data.get("tenant_id", ""),
            user_id=data.get("user_id", ""),
        )


class OAuthTokenStore:
    """
    Persistent storage for OAuth tokens.

    Supports SQLite for local storage with encryption for sensitive data.
    Context-safe for async and multi-worker deployments.
    """

    _conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
        "oauth_token_conn", default=None
    )

    def __init__(
        self,
        storage_path: str | None = None,
        encryption_key: str | None = None,
    ):
        """
        Initialize token store.

        Args:
            storage_path: Path to SQLite database (None for in-memory)
            encryption_key: Optional key for token encryption
        """
        self._storage_path = storage_path or ":memory:"
        self._encryption_key = encryption_key or os.environ.get("ARAGORA_ENCRYPTION_KEY")
        self._connections: list[sqlite3.Connection] = []
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Get context-local connection."""
        conn = self._conn_var.get()
        if conn is None:
            conn = sqlite3.connect(self._storage_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._conn_var.set(conn)
            self._connections.append(conn)
        return conn

    def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                token_key TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                access_token_encrypted TEXT NOT NULL,
                refresh_token_encrypted TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                token_type TEXT DEFAULT 'Bearer',
                scope TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tokens_provider ON oauth_tokens(provider, tenant_id, user_id);
            CREATE INDEX IF NOT EXISTS idx_tokens_expiry ON oauth_tokens(expires_at);
            """)
        conn.commit()

    def _encrypt(self, plaintext: str) -> str:
        """Encrypt sensitive data."""
        if not self._encryption_key:
            raise RuntimeError(
                "Encryption key required for OAuth token storage. "
                "Set ARAGORA_ENCRYPTION_KEY environment variable or pass "
                "encryption_key to OAuthTokenStore constructor."
            )

        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            import base64

            # Derive key from encryption key
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"aragora_oauth_salt",  # Static salt is OK here
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(self._encryption_key.encode()))
            fernet = Fernet(key)
            return fernet.encrypt(plaintext.encode()).decode()

        except ImportError:
            raise RuntimeError(
                "cryptography package required for OAuth token encryption. "
                "Install with: pip install cryptography"
            )

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt sensitive data."""
        if not self._encryption_key:
            raise RuntimeError(
                "Encryption key required for OAuth token storage. "
                "Set ARAGORA_ENCRYPTION_KEY environment variable or pass "
                "encryption_key to OAuthTokenStore constructor."
            )

        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
            import base64

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"aragora_oauth_salt",
                iterations=100000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(self._encryption_key.encode()))
            fernet = Fernet(key)
            return fernet.decrypt(ciphertext.encode()).decode()

        except ImportError:
            raise RuntimeError(
                "cryptography package required for OAuth token encryption. "
                "Install with: pip install cryptography"
            )

    def _token_key(self, provider: str, tenant_id: str, user_id: str) -> str:
        """Generate unique key for a token."""
        return hashlib.sha256(f"{provider}:{tenant_id}:{user_id}".encode()).hexdigest()

    async def store_token(self, token: OAuthToken) -> None:
        """Store an OAuth token."""
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()
        key = self._token_key(token.provider, token.tenant_id, token.user_id)

        conn.execute(
            """
            INSERT OR REPLACE INTO oauth_tokens (
                token_key, provider, tenant_id, user_id,
                access_token_encrypted, refresh_token_encrypted,
                expires_at, token_type, scope, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key,
                token.provider,
                token.tenant_id,
                token.user_id,
                self._encrypt(token.access_token),
                self._encrypt(token.refresh_token),
                token.expires_at.isoformat(),
                token.token_type,
                token.scope,
                now,
                now,
            ),
        )
        conn.commit()
        logger.debug(
            "[TokenStore] Stored token for %s/%s/%s", token.provider, token.tenant_id, token.user_id
        )

    async def get_token(
        self,
        provider: str,
        tenant_id: str,
        user_id: str,
    ) -> OAuthToken | None:
        """Retrieve an OAuth token."""
        conn = self._get_conn()
        key = self._token_key(provider, tenant_id, user_id)

        row = conn.execute(
            "SELECT * FROM oauth_tokens WHERE token_key = ?",
            (key,),
        ).fetchone()

        if not row:
            return None

        return OAuthToken(
            access_token=self._decrypt(row["access_token_encrypted"]),
            refresh_token=self._decrypt(row["refresh_token_encrypted"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            token_type=row["token_type"],
            scope=row["scope"] or "",
            provider=row["provider"],
            tenant_id=row["tenant_id"],
            user_id=row["user_id"],
        )

    async def delete_token(
        self,
        provider: str,
        tenant_id: str,
        user_id: str,
    ) -> bool:
        """Delete an OAuth token."""
        conn = self._get_conn()
        key = self._token_key(provider, tenant_id, user_id)

        cursor = conn.execute("DELETE FROM oauth_tokens WHERE token_key = ?", (key,))
        conn.commit()

        deleted = cursor.rowcount > 0
        if deleted:
            logger.debug("[TokenStore] Deleted token for %s/%s/%s", provider, tenant_id, user_id)
        return deleted

    async def get_expiring_tokens(
        self,
        within_minutes: int = 60,
    ) -> list[OAuthToken]:
        """Get tokens expiring soon (for proactive refresh)."""
        conn = self._get_conn()
        cutoff = (datetime.now(timezone.utc) + timedelta(minutes=within_minutes)).isoformat()

        rows = conn.execute(
            "SELECT * FROM oauth_tokens WHERE expires_at <= ?",
            (cutoff,),
        ).fetchall()

        tokens = []
        for row in rows:
            tokens.append(
                OAuthToken(
                    access_token=self._decrypt(row["access_token_encrypted"]),
                    refresh_token=self._decrypt(row["refresh_token_encrypted"]),
                    expires_at=datetime.fromisoformat(row["expires_at"]),
                    token_type=row["token_type"],
                    scope=row["scope"] or "",
                    provider=row["provider"],
                    tenant_id=row["tenant_id"],
                    user_id=row["user_id"],
                )
            )

        return tokens


# =============================================================================
# Resilient Email Client
# =============================================================================


class ResilientEmailClient:
    """
    Resilient wrapper for email API operations.

    Combines circuit breaker, retry, token management, and rate limiting
    for production-grade email sync.
    """

    def __init__(
        self,
        provider: str,
        tenant_id: str = "",
        user_id: str = "",
        token_store: OAuthTokenStore | None = None,
        retry_config: RetryConfig | None = None,
        circuit_breaker_config: CircuitBreakerConfig | None = None,
        rate_limit_config: RateLimitConfig | None = None,
    ):
        """
        Initialize resilient email client.

        Args:
            provider: Email provider ("gmail" or "outlook")
            tenant_id: Tenant identifier
            user_id: User identifier
            token_store: OAuth token persistence
            retry_config: Retry configuration
            circuit_breaker_config: Circuit breaker configuration
            rate_limit_config: Rate limiting configuration
        """
        self.provider = provider
        self.tenant_id = tenant_id
        self.user_id = user_id

        self._token_store = token_store
        self._retry = RetryExecutor(retry_config)
        self._circuit_breaker = EmailCircuitBreaker(
            name=f"{provider}_{tenant_id}_{user_id}",
            config=circuit_breaker_config,
        )
        self._rate_limit_config = rate_limit_config or RateLimitConfig()

        # Rate limiting state
        self._request_times: list[float] = []
        self._rate_lock = asyncio.Lock()

    async def _check_rate_limit(self) -> None:
        """Check and enforce rate limits."""
        async with self._rate_lock:
            now = time.time()
            window_start = now - self._rate_limit_config.window_seconds

            # Remove old requests
            self._request_times = [t for t in self._request_times if t > window_start]

            # Check if we're over the limit
            if len(self._request_times) >= self._rate_limit_config.requests_per_minute:
                # Calculate wait time
                oldest_in_window = min(self._request_times)
                wait_time = (oldest_in_window + self._rate_limit_config.window_seconds) - now
                if wait_time > 0:
                    logger.warning("[RateLimit] Waiting %.1fs for rate limit", wait_time)
                    await asyncio.sleep(wait_time)

            self._request_times.append(time.time())

    async def get_valid_token(self) -> OAuthToken | None:
        """Get a valid (non-expired) access token."""
        if not self._token_store:
            return None

        token = await self._token_store.get_token(self.provider, self.tenant_id, self.user_id)

        if not token:
            return None

        if token.is_expired:
            # Token needs refresh
            logger.info("[ResilientClient] Token expired, refresh needed")
            # Note: Actual refresh should be done by the caller with provider-specific logic
            return None

        return token

    async def execute(
        self,
        operation: Callable[[], T],
        operation_name: str = "api_call",
        timeout_seconds: float = 30.0,
    ) -> T:
        """
        Execute an operation with full resilience patterns.

        Args:
            operation: Async callable to execute
            operation_name: Name for logging
            timeout_seconds: Timeout for the operation

        Returns:
            Result of the operation

        Raises:
            CircuitBreakerOpenError: If circuit is open
            Exception: If operation fails after all retries
        """
        # Check circuit breaker
        if not await self._circuit_breaker.can_execute():
            raise CircuitBreakerOpenError(f"Circuit breaker open for {self._circuit_breaker.name}")

        # Check rate limit
        await self._check_rate_limit()

        try:
            # Execute with retry and timeout
            result = await asyncio.wait_for(
                self._retry.execute(operation, operation_name),
                timeout=timeout_seconds,
            )
            await self._circuit_breaker.record_success()
            return result

        except (OSError, ConnectionError, TimeoutError, asyncio.TimeoutError, RuntimeError) as e:
            await self._circuit_breaker.record_failure(e)
            raise

    def get_stats(self) -> dict[str, Any]:
        """Get client statistics."""
        return {
            "provider": self.provider,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "circuit_breaker": self._circuit_breaker.get_stats(),
            "requests_in_window": len(self._request_times),
        }


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open and blocking calls."""

    pass


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Config
    "RetryConfig",
    "CircuitBreakerConfig",
    "RateLimitConfig",
    # Circuit Breaker
    "CircuitState",
    "EmailCircuitBreaker",
    "CircuitBreakerOpenError",
    # Retry
    "RetryExecutor",
    # OAuth
    "OAuthToken",
    "OAuthTokenStore",
    # Client
    "ResilientEmailClient",
]
