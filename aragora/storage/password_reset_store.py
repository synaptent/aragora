"""
Password Reset Token Storage.

Provides secure storage for password reset tokens with:
- Cryptographically secure token generation
- Automatic expiration (default 1 hour)
- Rate limiting support (tracks attempts per email)
- Multiple backend support (in-memory, SQLite, PostgreSQL)

Usage:
    store = get_password_reset_store()

    # Generate and store a reset token
    token = store.create_token("user@example.com")

    # Validate a token (returns email if valid)
    email = store.validate_token(token)

    # Consume token after password reset
    store.consume_token(token)
"""

from __future__ import annotations

import contextvars
import hashlib
import logging
import os
import secrets
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from aragora.config import resolve_db_path
from aragora.storage.connection_factory import is_postgres_backend

if TYPE_CHECKING:
    from asyncpg import Pool


from aragora.utils.async_utils import run_async

logger = logging.getLogger(__name__)

# Token configuration
DEFAULT_TOKEN_BYTES = 32  # 256 bits of entropy
DEFAULT_TTL_SECONDS = 3600  # 1 hour
MAX_ATTEMPTS_PER_EMAIL = 3  # Max reset requests per email per hour
ATTEMPT_WINDOW_SECONDS = 3600  # 1 hour window for rate limiting


@dataclass
class ResetTokenData:
    """Data associated with a password reset token."""

    email: str
    token_hash: str
    created_at: datetime
    expires_at: datetime
    used: bool = False

    @property
    def is_expired(self) -> bool:
        """Check if token has expired."""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_valid(self) -> bool:
        """Check if token is valid (not expired and not used)."""
        return not self.is_expired and not self.used


class PasswordResetBackend(ABC):
    """Abstract base for password reset token storage."""

    @abstractmethod
    def store_token(self, email: str, token_hash: str, expires_at: float) -> None:
        """Store a password reset token."""
        pass

    @abstractmethod
    def get_token_data(self, token_hash: str) -> ResetTokenData | None:
        """Get token data by hash."""
        pass

    @abstractmethod
    def mark_used(self, token_hash: str) -> bool:
        """Mark a token as used. Returns True if successful."""
        pass

    @abstractmethod
    def delete_token(self, token_hash: str) -> bool:
        """Delete a token. Returns True if deleted."""
        pass

    @abstractmethod
    def count_recent_requests(self, email: str, window_seconds: int) -> int:
        """Count recent reset requests for an email (for rate limiting)."""
        pass

    @abstractmethod
    def cleanup_expired(self) -> int:
        """Remove expired tokens. Returns count of removed tokens."""
        pass

    @abstractmethod
    def delete_tokens_for_email(self, email: str) -> int:
        """Delete all tokens for an email. Returns count of deleted tokens."""
        pass


class InMemoryPasswordResetStore(PasswordResetBackend):
    """In-memory password reset token store for development."""

    def __init__(self) -> None:
        self._tokens: dict[str, ResetTokenData] = {}
        self._lock = threading.Lock()

    def store_token(self, email: str, token_hash: str, expires_at: float) -> None:
        with self._lock:
            self._tokens[token_hash] = ResetTokenData(
                email=email.lower(),
                token_hash=token_hash,
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
            )

    def get_token_data(self, token_hash: str) -> ResetTokenData | None:
        with self._lock:
            return self._tokens.get(token_hash)

    def mark_used(self, token_hash: str) -> bool:
        with self._lock:
            if token_hash in self._tokens:
                self._tokens[token_hash].used = True
                return True
            return False

    def delete_token(self, token_hash: str) -> bool:
        with self._lock:
            if token_hash in self._tokens:
                del self._tokens[token_hash]
                return True
            return False

    def count_recent_requests(self, email: str, window_seconds: int) -> int:
        with self._lock:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
            email_lower = email.lower()
            return sum(
                1
                for data in self._tokens.values()
                if data.email == email_lower and data.created_at > cutoff
            )

    def cleanup_expired(self) -> int:
        with self._lock:
            now = datetime.now(timezone.utc)
            expired = [h for h, d in self._tokens.items() if d.expires_at < now]
            for h in expired:
                del self._tokens[h]
            return len(expired)

    def delete_tokens_for_email(self, email: str) -> int:
        with self._lock:
            email_lower = email.lower()
            to_delete = [h for h, d in self._tokens.items() if d.email == email_lower]
            for h in to_delete:
                del self._tokens[h]
            return len(to_delete)


class SQLitePasswordResetStore(PasswordResetBackend):
    """SQLite-backed password reset token store for single-instance production."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(resolve_db_path(db_path))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # ContextVar for per-async-context connection (async-safe replacement for threading.local)
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            f"passwordresetstore_conn_{id(self)}", default=None
        )
        # Track all connections for proper cleanup
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.Lock()
        self._init_schema()
        logger.info("SQLitePasswordResetStore initialized: %s", self.db_path)

    def _get_conn(self) -> sqlite3.Connection:
        conn = self._conn_var.get()
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            self._conn_var.set(conn)
            with self._connections_lock:
                self._connections.add(conn)
        return conn

    def close(self) -> None:
        """Close all database connections."""
        with self._connections_lock:
            for conn in self._connections:
                try:
                    conn.close()
                except (OSError, RuntimeError, ValueError) as e:
                    logger.debug("Error closing connection: %s", e)
            self._connections.clear()

    def _init_schema(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                token_hash TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reset_email ON password_reset_tokens(email)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reset_expires ON password_reset_tokens(expires_at)"
        )
        conn.commit()
        conn.close()

    def store_token(self, email: str, token_hash: str, expires_at: float) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO password_reset_tokens
               (token_hash, email, created_at, expires_at, used)
               VALUES (?, ?, ?, ?, 0)""",
            (token_hash, email.lower(), time.time(), expires_at),
        )
        conn.commit()

    def get_token_data(self, token_hash: str) -> ResetTokenData | None:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM password_reset_tokens WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        if not row:
            return None
        return ResetTokenData(
            email=row["email"],
            token_hash=row["token_hash"],
            created_at=datetime.fromtimestamp(row["created_at"], tz=timezone.utc),
            expires_at=datetime.fromtimestamp(row["expires_at"], tz=timezone.utc),
            used=bool(row["used"]),
        )

    def mark_used(self, token_hash: str) -> bool:
        conn = self._get_conn()
        cursor = conn.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE token_hash = ?",
            (token_hash,),
        )
        conn.commit()
        return cursor.rowcount > 0

    def delete_token(self, token_hash: str) -> bool:
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM password_reset_tokens WHERE token_hash = ?", (token_hash,)
        )
        conn.commit()
        return cursor.rowcount > 0

    def count_recent_requests(self, email: str, window_seconds: int) -> int:
        conn = self._get_conn()
        cutoff = time.time() - window_seconds
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM password_reset_tokens WHERE email = ? AND created_at > ?",
            (email.lower(), cutoff),
        ).fetchone()
        return row["cnt"] if row else 0

    def cleanup_expired(self) -> int:
        conn = self._get_conn()
        cursor = conn.execute(
            "DELETE FROM password_reset_tokens WHERE expires_at < ?", (time.time(),)
        )
        conn.commit()
        return cursor.rowcount

    def delete_tokens_for_email(self, email: str) -> int:
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM password_reset_tokens WHERE email = ?", (email.lower(),))
        conn.commit()
        return cursor.rowcount


class PostgresPasswordResetStore(PasswordResetBackend):
    """PostgreSQL-backed password reset token store for multi-instance production."""

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token_hash TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ NOT NULL,
            used BOOLEAN NOT NULL DEFAULT FALSE
        );
        CREATE INDEX IF NOT EXISTS idx_reset_email ON password_reset_tokens(email);
        CREATE INDEX IF NOT EXISTS idx_reset_expires ON password_reset_tokens(expires_at);
    """

    def __init__(self, pool: Pool) -> None:
        self._pool = pool
        self._initialized = False
        logger.info("PostgresPasswordResetStore initialized")

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(self.INITIAL_SCHEMA)
        self._initialized = True

    def store_token(self, email: str, token_hash: str, expires_at: float) -> None:
        run_async(self._store_token_async(email, token_hash, expires_at))

    async def _store_token_async(self, email: str, token_hash: str, expires_at: float) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO password_reset_tokens (token_hash, email, expires_at)
                   VALUES ($1, $2, to_timestamp($3))
                   ON CONFLICT (token_hash) DO UPDATE SET
                       email = $2, expires_at = to_timestamp($3), used = FALSE""",
                token_hash,
                email.lower(),
                expires_at,
            )

    def get_token_data(self, token_hash: str) -> ResetTokenData | None:
        return run_async(self._get_token_data_async(token_hash))

    async def _get_token_data_async(self, token_hash: str) -> ResetTokenData | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM password_reset_tokens WHERE token_hash = $1", token_hash
            )
            if not row:
                return None
            return ResetTokenData(
                email=row["email"],
                token_hash=row["token_hash"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                used=row["used"],
            )

    def mark_used(self, token_hash: str) -> bool:
        return run_async(self._mark_used_async(token_hash))

    async def _mark_used_async(self, token_hash: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "UPDATE password_reset_tokens SET used = TRUE WHERE token_hash = $1",
                token_hash,
            )
            return result.endswith("1")

    def delete_token(self, token_hash: str) -> bool:
        return run_async(self._delete_token_async(token_hash))

    async def _delete_token_async(self, token_hash: str) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM password_reset_tokens WHERE token_hash = $1", token_hash
            )
            return result.endswith("1")

    def count_recent_requests(self, email: str, window_seconds: int) -> int:
        return run_async(self._count_recent_requests_async(email, window_seconds))

    async def _count_recent_requests_async(self, email: str, window_seconds: int) -> int:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT COUNT(*) as cnt FROM password_reset_tokens
                   WHERE email = $1 AND created_at > NOW() - INTERVAL '%s seconds'""",
                email.lower(),
                window_seconds,
            )
            return row["cnt"] if row else 0

    def cleanup_expired(self) -> int:
        return run_async(self._cleanup_expired_async())

    async def _cleanup_expired_async(self) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM password_reset_tokens WHERE expires_at < NOW()"
            )
            try:
                return int(result.split()[1])
            except (IndexError, ValueError):
                return 0

    def delete_tokens_for_email(self, email: str) -> int:
        return run_async(self._delete_tokens_for_email_async(email))

    async def _delete_tokens_for_email_async(self, email: str) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM password_reset_tokens WHERE email = $1", email.lower()
            )
            try:
                return int(result.split()[1])
            except (IndexError, ValueError):
                return 0


class PasswordResetStore:
    """
    High-level password reset token manager.

    Provides secure token generation, validation, and rate limiting.
    Delegates storage to a pluggable backend.
    """

    def __init__(
        self,
        backend: PasswordResetBackend,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_attempts: int = MAX_ATTEMPTS_PER_EMAIL,
        attempt_window: int = ATTEMPT_WINDOW_SECONDS,
    ) -> None:
        self._backend = backend
        self._ttl_seconds = ttl_seconds
        self._max_attempts = max_attempts
        self._attempt_window = attempt_window

    def create_token(self, email: str) -> tuple[str | None, str | None]:
        """
        Create a password reset token for the given email.

        Returns:
            Tuple of (token, error_message).
            On success: (token_string, None)
            On rate limit: (None, error_message)
        """
        email = email.lower().strip()

        # Check rate limit
        recent = self._backend.count_recent_requests(email, self._attempt_window)
        if recent >= self._max_attempts:
            logger.warning("Password reset rate limit exceeded for: %s", email)
            return None, "Too many reset requests. Please try again later."

        # Generate secure token
        token = secrets.token_urlsafe(DEFAULT_TOKEN_BYTES)
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        # Calculate expiration
        expires_at = time.time() + self._ttl_seconds

        # Store token hash (never store plaintext token)
        self._backend.store_token(email, token_hash, expires_at)

        logger.info("Password reset token created for: %s", email)
        return token, None

    def validate_token(self, token: str) -> tuple[str | None, str | None]:
        """
        Validate a password reset token.

        Returns:
            Tuple of (email, error_message).
            On success: (email_address, None)
            On failure: (None, error_message)
        """
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        data = self._backend.get_token_data(token_hash)

        if not data:
            return None, "Invalid or expired reset token"

        if data.is_expired:
            self._backend.delete_token(token_hash)
            return None, "Reset token has expired"

        if data.used:
            return None, "Reset token has already been used"

        return data.email, None

    def consume_token(self, token: str) -> bool:
        """
        Mark a token as used and delete it.

        Should be called after successfully resetting the password.
        Returns True if token was consumed, False if not found.
        """
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        # Mark as used first (prevents race conditions)
        self._backend.mark_used(token_hash)

        # Delete the token
        deleted = self._backend.delete_token(token_hash)

        if deleted:
            logger.info("Password reset token consumed")
        return deleted

    def invalidate_tokens_for_email(self, email: str) -> int:
        """
        Invalidate all reset tokens for an email address.

        Call this after a successful password reset to prevent
        replay attacks with other valid tokens.
        """
        count = self._backend.delete_tokens_for_email(email)
        if count > 0:
            logger.info("Invalidated %s reset token(s) for: %s", count, email)
        return count

    def cleanup(self) -> int:
        """Remove expired tokens. Returns count of removed tokens."""
        return self._backend.cleanup_expired()


# Global store instance
_password_reset_store: PasswordResetStore | None = None
_password_reset_store_lock = threading.Lock()  # Protects singleton initialization


def get_password_reset_store() -> PasswordResetStore:
    """
    Get or create the global password reset store.

    Uses environment variables to configure backend:
    - ARAGORA_PASSWORD_RESET_BACKEND: "memory", "sqlite", or "postgres"
    - ARAGORA_DB_BACKEND: Global database backend (fallback)
    - ARAGORA_DATA_DIR: Directory for SQLite database
    """
    global _password_reset_store
    # Fast path: return existing instance without lock
    if _password_reset_store is not None:
        return _password_reset_store

    # Slow path: acquire lock for initialization
    with _password_reset_store_lock:
        # Double-check after acquiring lock (another thread may have initialized)
        if _password_reset_store is not None:
            return _password_reset_store

    backend_type = os.environ.get("ARAGORA_PASSWORD_RESET_BACKEND")
    if not backend_type:
        backend_type = os.environ.get("ARAGORA_DB_BACKEND", "auto")
    backend_type = backend_type.lower()

    # SQLite fallback path for non-Postgres backends
    fallback_db_path = Path(resolve_db_path("password_reset.db"))

    backend: PasswordResetBackend
    if backend_type == "memory":
        backend = InMemoryPasswordResetStore()
    elif is_postgres_backend(backend_type):
        # Try to get PostgreSQL pool
        try:
            from aragora.storage.connection_factory import get_postgres_pool

            pool = get_postgres_pool()
            if pool:
                backend = PostgresPasswordResetStore(pool)
            else:
                logger.warning("PostgreSQL pool not available, falling back to SQLite")
                backend = SQLitePasswordResetStore(fallback_db_path)
        except ImportError:
            logger.warning("PostgreSQL support not available, falling back to SQLite")
            backend = SQLitePasswordResetStore(fallback_db_path)
    else:
        # Default to SQLite for persistence
        backend = SQLitePasswordResetStore(fallback_db_path)

    _password_reset_store = PasswordResetStore(backend)
    return _password_reset_store


def set_password_reset_store(store: PasswordResetStore) -> None:
    """Set custom password reset store (for testing)."""
    global _password_reset_store
    _password_reset_store = store


__all__ = [
    "PasswordResetStore",
    "PasswordResetBackend",
    "InMemoryPasswordResetStore",
    "SQLitePasswordResetStore",
    "PostgresPasswordResetStore",
    "ResetTokenData",
    "get_password_reset_store",
    "set_password_reset_store",
    "DEFAULT_TTL_SECONDS",
    "MAX_ATTEMPTS_PER_EMAIL",
]
