"""
Webhook Configuration Storage.

Provides persistent storage for webhook configurations (URLs, events, secrets).
Survives server restarts and supports multi-instance deployments.

Backends:
- InMemoryWebhookConfigStore: Fast, single-instance only (for testing)
- SQLiteWebhookConfigStore: Persisted, single-instance (default)
- RedisWebhookConfigStore: Distributed, multi-instance (with SQLite fallback)

Usage:
    from aragora.storage.webhook_config_store import get_webhook_config_store

    store = get_webhook_config_store()
    webhook = await store.register(url="https://...", events=["debate_end"])
    webhook = await store.get(webhook_id)
"""

from __future__ import annotations

import atexit
import contextvars
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from asyncpg import Pool

from aragora.config import resolve_db_path
from aragora.utils.async_utils import run_async

# Pre-declare encryption names for optional import fallback
EncryptionError: type[Exception]

# redis.exceptions.ConnectionError does NOT inherit from builtins.ConnectionError
# (it inherits from redis.RedisError -> Exception), so we need to catch it explicitly.
_RedisError: type[Exception] = OSError  # overwritten below if redis is available
try:
    from redis.exceptions import RedisError

    _RedisError = RedisError
except ImportError:
    pass  # _RedisError stays as OSError fallback

logger = logging.getLogger(__name__)

# Alias to avoid shadowing by `list()` methods inside store classes
_list = list

# Try to import encryption service
try:
    from aragora.security.encryption import (
        get_encryption_service as _get_encryption_service,
        CRYPTO_AVAILABLE,
        is_encryption_required as _is_encryption_required,
        EncryptionError as _EncryptionError,
    )

    def get_encryption_service() -> Any | None:
        return _get_encryption_service()

    def is_encryption_required() -> bool:
        return _is_encryption_required()

    EncryptionError = _EncryptionError

except ImportError:
    CRYPTO_AVAILABLE = False

    def get_encryption_service() -> Any | None:
        """Fallback when security module unavailable."""
        return None

    def is_encryption_required() -> bool:
        """Fallback when security module unavailable - still check env vars."""
        if os.environ.get("ARAGORA_ENCRYPTION_REQUIRED", "").lower() in ("true", "1", "yes"):
            return True
        if os.environ.get("ARAGORA_ENV") == "production":
            return True
        return False

    # Fallback class when security module is unavailable; pre-declared above
    class _EncryptionErrorFallback(Exception):
        """Fallback exception when security module unavailable."""

        def __init__(self, operation: str, reason: str, store: str = ""):
            self.operation = operation
            self.reason = reason
            self.store = store
            super().__init__(
                f"Encryption {operation} failed in {store}: {reason}. "
                f"Set ARAGORA_ENCRYPTION_REQUIRED=false to allow plaintext fallback."
            )

    EncryptionError = _EncryptionErrorFallback


def _encrypt_secret(secret: str) -> str:
    """Encrypt webhook secret before storage.

    SECURITY: Fails if encryption is required but unavailable.
    """
    if not secret:
        return secret

    if not CRYPTO_AVAILABLE:
        if is_encryption_required():
            raise EncryptionError(
                "encrypt",
                "cryptography library not available",
                "webhook_config_store",
            )
        return secret

    try:
        service = cast(Any, get_encryption_service())
        encrypted = service.encrypt(secret)
        return encrypted.to_base64()
    except (EncryptionError, ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
        if is_encryption_required():
            raise EncryptionError(
                "encrypt",
                str(e),
                "webhook_config_store",
            ) from e
        logger.warning("Secret encryption failed, storing unencrypted: %s", e)
        return secret


def _decrypt_secret(encrypted_secret: str) -> str:
    """Decrypt webhook secret, handling legacy unencrypted data."""
    if not CRYPTO_AVAILABLE or not encrypted_secret:
        return encrypted_secret

    # Check if it looks like encrypted data (base64 with specific structure)
    # Legacy secrets are 43-char base64 (32 bytes urlsafe)
    if len(encrypted_secret) < 50 or not encrypted_secret.startswith("AAAA"):
        # Likely legacy unencrypted secret
        return encrypted_secret

    try:
        service = cast(Any, get_encryption_service())
        return service.decrypt_string(encrypted_secret)
    except (EncryptionError, ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
        logger.debug("Secret decryption failed (may be legacy unencrypted): %s", e)
        return encrypted_secret  # Return as-is if decryption fails


def _deserialize_events(value: Any) -> list[str]:
    """Normalize stored event payloads from JSON strings or native sequences."""
    if value is None:
        return []
    payload = value
    if isinstance(payload, str):
        payload = json.loads(payload) if payload else []
    elif isinstance(payload, bytes):
        payload = json.loads(payload.decode("utf-8")) if payload else []
    if isinstance(payload, (list, tuple, set)):
        return [str(item) for item in payload]
    logger.debug("Unexpected webhook events payload type: %s", type(payload).__name__)
    return []


# Events that can trigger webhooks
WEBHOOK_EVENTS: set[str] = {
    "debate_start",
    "debate_end",
    "consensus",
    "round_start",
    "agent_message",
    "vote",
    "insight_extracted",
    "memory_stored",
    "memory_retrieved",
    "claim_verification_result",
    "formal_verification_result",
    "gauntlet_complete",
    "gauntlet_verdict",
    "receipt_ready",
    "receipt_exported",
    "graph_branch_created",
    "graph_branch_merged",
    "genesis_evolution",
    "breakpoint",
    "breakpoint_resolved",
    "agent_elo_updated",
    "knowledge_indexed",
    "knowledge_queried",
    "mound_updated",
    "calibration_update",
    "evidence_found",
    "agent_calibration_changed",
    "agent_fallback_triggered",
    "explanation_ready",
}


@dataclass
class WebhookConfig:
    """Configuration for a registered webhook."""

    id: str
    url: str
    events: list[str]
    secret: str
    active: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Optional metadata
    name: str | None = None
    description: str | None = None

    # Delivery tracking
    last_delivery_at: float | None = None
    last_delivery_status: int | None = None
    delivery_count: int = 0
    failure_count: int = 0

    # Owner (for multi-tenant)
    user_id: str | None = None
    workspace_id: str | None = None

    def to_dict(self, include_secret: bool = False) -> dict:
        """Convert to dict, optionally excluding secret."""
        result = asdict(self)
        if not include_secret:
            result.pop("secret", None)
        return result

    def to_json(self) -> str:
        """Serialize to JSON for storage."""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, json_str: str) -> WebhookConfig:
        """Deserialize from JSON."""
        data = json.loads(json_str)
        return cls(**data)

    @classmethod
    def from_row(cls, row: tuple) -> WebhookConfig:
        """Create from database row."""
        return cls(
            id=row[0],
            url=row[1],
            events=_deserialize_events(row[2]),
            secret=_decrypt_secret(row[3] or ""),
            active=bool(row[4]),
            created_at=row[5] or time.time(),
            updated_at=row[6] or time.time(),
            name=row[7],
            description=row[8],
            last_delivery_at=row[9],
            last_delivery_status=row[10],
            delivery_count=row[11] or 0,
            failure_count=row[12] or 0,
            user_id=row[13],
            workspace_id=row[14],
        )

    def matches_event(self, event_type: str) -> bool:
        """Check if this webhook should receive the given event."""
        if not self.active:
            return False
        if "*" in self.events:
            return event_type in WEBHOOK_EVENTS
        return event_type in self.events


class WebhookConfigStoreBackend(ABC):
    """Abstract base for webhook configuration storage backends."""

    @abstractmethod
    def register(
        self,
        url: str,
        events: _list[str],
        name: str | None = None,
        description: str | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> WebhookConfig:
        """Register a new webhook."""
        pass

    @abstractmethod
    def get(self, webhook_id: str) -> WebhookConfig | None:
        """Get webhook by ID."""
        pass

    @abstractmethod
    def list(
        self,
        user_id: str | None = None,
        workspace_id: str | None = None,
        active_only: bool = False,
    ) -> _list[WebhookConfig]:
        """List webhooks with optional filtering."""
        pass

    @abstractmethod
    def delete(self, webhook_id: str) -> bool:
        """Delete webhook by ID."""
        pass

    @abstractmethod
    def update(
        self,
        webhook_id: str,
        url: str | None = None,
        events: _list[str] | None = None,
        active: bool | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> WebhookConfig | None:
        """Update webhook configuration."""
        pass

    @abstractmethod
    def record_delivery(
        self,
        webhook_id: str,
        status_code: int,
        success: bool = True,
    ) -> None:
        """Record webhook delivery attempt."""
        pass

    @abstractmethod
    def get_for_event(self, event_type: str) -> _list[WebhookConfig]:
        """Get all active webhooks that should receive the given event."""
        pass

    def close(self) -> None:
        """Close connections (optional to implement)."""
        pass


class InMemoryWebhookConfigStore(WebhookConfigStoreBackend):
    """
    Thread-safe in-memory webhook config store.

    Fast but not shared across restarts. Suitable for development/testing.
    """

    def __init__(self) -> None:
        self._webhooks: dict[str, WebhookConfig] = {}
        self._lock = threading.RLock()

    def register(
        self,
        url: str,
        events: _list[str],
        name: str | None = None,
        description: str | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> WebhookConfig:
        webhook_id = str(uuid.uuid4())
        secret = secrets.token_urlsafe(32)

        webhook = WebhookConfig(
            id=webhook_id,
            url=url,
            events=events,
            secret=secret,
            name=name,
            description=description,
            user_id=user_id,
            workspace_id=workspace_id,
        )

        with self._lock:
            self._webhooks[webhook_id] = webhook

        logger.info("Registered webhook %s for events: %s", webhook_id, events)
        return webhook

    def get(self, webhook_id: str) -> WebhookConfig | None:
        with self._lock:
            return self._webhooks.get(webhook_id)

    def list(
        self,
        user_id: str | None = None,
        workspace_id: str | None = None,
        active_only: bool = False,
    ) -> _list[WebhookConfig]:
        with self._lock:
            webhooks = list(self._webhooks.values())

        if user_id:
            webhooks = [w for w in webhooks if w.user_id == user_id]
        if workspace_id:
            webhooks = [w for w in webhooks if w.workspace_id == workspace_id]
        if active_only:
            webhooks = [w for w in webhooks if w.active]

        return sorted(webhooks, key=lambda w: w.created_at, reverse=True)

    def delete(self, webhook_id: str) -> bool:
        with self._lock:
            if webhook_id in self._webhooks:
                del self._webhooks[webhook_id]
                logger.info("Deleted webhook %s", webhook_id)
                return True
            return False

    def update(
        self,
        webhook_id: str,
        url: str | None = None,
        events: _list[str] | None = None,
        active: bool | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> WebhookConfig | None:
        with self._lock:
            webhook = self._webhooks.get(webhook_id)
            if not webhook:
                return None

            if url is not None:
                webhook.url = url
            if events is not None:
                webhook.events = events
            if active is not None:
                webhook.active = active
            if name is not None:
                webhook.name = name
            if description is not None:
                webhook.description = description

            webhook.updated_at = time.time()
            return webhook

    def record_delivery(
        self,
        webhook_id: str,
        status_code: int,
        success: bool = True,
    ) -> None:
        with self._lock:
            webhook = self._webhooks.get(webhook_id)
            if webhook:
                webhook.last_delivery_at = time.time()
                webhook.last_delivery_status = status_code
                webhook.delivery_count += 1
                if not success:
                    webhook.failure_count += 1

    def get_for_event(self, event_type: str) -> _list[WebhookConfig]:
        with self._lock:
            return [w for w in self._webhooks.values() if w.matches_event(event_type)]

    def clear(self) -> None:
        """Clear all entries (for testing)."""
        with self._lock:
            self._webhooks.clear()


class SQLiteWebhookConfigStore(WebhookConfigStoreBackend):
    """
    SQLite-backed webhook config store.

    Persisted to disk, survives restarts. Suitable for single-instance
    production deployments.

    Raises:
        DistributedStateError: In production if PostgreSQL is not available
    """

    def __init__(self, db_path: Path | str):
        # SECURITY: Check production guards for SQLite usage
        try:
            from aragora.storage.production_guards import (
                require_distributed_store,
                StorageMode,
            )

            require_distributed_store(
                "webhook_config_store",
                StorageMode.SQLITE,
                "Webhook config store using SQLite - use PostgreSQL for multi-instance deployments",
            )
        except ImportError:
            pass  # Guards not available, allow SQLite

        self.db_path = Path(resolve_db_path(db_path))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # ContextVar for per-async-context connection (async-safe replacement for threading.local)
        self._conn_var: contextvars.ContextVar[sqlite3.Connection | None] = contextvars.ContextVar(
            f"webhookconfigstore_conn_{id(self)}", default=None
        )
        # Track all connections for proper cleanup
        self._connections: set[sqlite3.Connection] = set()
        self._connections_lock = threading.Lock()
        self._init_schema()
        logger.info("SQLiteWebhookConfigStore initialized: %s", self.db_path)

    def _get_conn(self) -> sqlite3.Connection:
        """Get per-context database connection (async-safe)."""
        conn = self._conn_var.get()
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._conn_var.set(conn)
            with self._connections_lock:
                self._connections.add(conn)
        return conn

    def _init_schema(self) -> None:
        """Initialize database schema."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS webhook_configs (
                id TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                events_json TEXT NOT NULL,
                secret TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                name TEXT,
                description TEXT,
                last_delivery_at REAL,
                last_delivery_status INTEGER,
                delivery_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                user_id TEXT,
                workspace_id TEXT
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_webhook_configs_user ON webhook_configs(user_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_webhook_configs_workspace ON webhook_configs(workspace_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_webhook_configs_active ON webhook_configs(active)"
        )
        conn.commit()
        conn.close()

    def register(
        self,
        url: str,
        events: _list[str],
        name: str | None = None,
        description: str | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> WebhookConfig:
        webhook_id = str(uuid.uuid4())
        secret = secrets.token_urlsafe(32)
        now = time.time()

        webhook = WebhookConfig(
            id=webhook_id,
            url=url,
            events=events,
            secret=secret,
            name=name,
            description=description,
            user_id=user_id,
            workspace_id=workspace_id,
            created_at=now,
            updated_at=now,
        )

        conn = self._get_conn()
        conn.execute(
            """INSERT INTO webhook_configs
               (id, url, events_json, secret, active, created_at, updated_at,
                name, description, last_delivery_at, last_delivery_status,
                delivery_count, failure_count, user_id, workspace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                webhook.id,
                webhook.url,
                json.dumps(webhook.events),
                _encrypt_secret(webhook.secret),
                int(webhook.active),
                webhook.created_at,
                webhook.updated_at,
                webhook.name,
                webhook.description,
                webhook.last_delivery_at,
                webhook.last_delivery_status,
                webhook.delivery_count,
                webhook.failure_count,
                webhook.user_id,
                webhook.workspace_id,
            ),
        )
        conn.commit()
        logger.info("Registered webhook %s for events: %s", webhook_id, events)
        return webhook

    def get(self, webhook_id: str) -> WebhookConfig | None:
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT id, url, events_json, secret, active, created_at, updated_at,
                      name, description, last_delivery_at, last_delivery_status,
                      delivery_count, failure_count, user_id, workspace_id
               FROM webhook_configs WHERE id = ?""",
            (webhook_id,),
        )
        row = cursor.fetchone()
        if row:
            return WebhookConfig.from_row(row)
        return None

    def get_cache_revision(self, webhook_id: str) -> float | None:
        """Return the durable row revision used to validate Redis cache hits."""
        conn = self._get_conn()
        cursor = conn.execute(
            "SELECT updated_at FROM webhook_configs WHERE id = ?",
            (webhook_id,),
        )
        row = cursor.fetchone()
        if row:
            return float(row[0])
        return None

    def list(
        self,
        user_id: str | None = None,
        workspace_id: str | None = None,
        active_only: bool = False,
    ) -> _list[WebhookConfig]:
        conn = self._get_conn()

        query = """SELECT id, url, events_json, secret, active, created_at, updated_at,
                          name, description, last_delivery_at, last_delivery_status,
                          delivery_count, failure_count, user_id, workspace_id
                   FROM webhook_configs WHERE 1=1"""
        params: _list[Any] = []

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if workspace_id:
            query += " AND workspace_id = ?"
            params.append(workspace_id)
        if active_only:
            query += " AND active = 1"

        query += " ORDER BY created_at DESC"

        cursor = conn.execute(query, params)
        return [WebhookConfig.from_row(row) for row in cursor.fetchall()]

    def delete(self, webhook_id: str) -> bool:
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM webhook_configs WHERE id = ?", (webhook_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            logger.info("Deleted webhook %s", webhook_id)
        return deleted

    def update(
        self,
        webhook_id: str,
        url: str | None = None,
        events: _list[str] | None = None,
        active: bool | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> WebhookConfig | None:
        webhook = self.get(webhook_id)
        if not webhook:
            return None

        updates: _list[str] = []
        params: _list[Any] = []

        if url is not None:
            updates.append("url = ?")
            params.append(url)
            webhook.url = url
        if events is not None:
            updates.append("events_json = ?")
            params.append(json.dumps(events))
            webhook.events = events
        if active is not None:
            updates.append("active = ?")
            params.append(int(active))
            webhook.active = active
        if name is not None:
            updates.append("name = ?")
            params.append(name)
            webhook.name = name
        if description is not None:
            updates.append("description = ?")
            params.append(description)
            webhook.description = description

        if updates:
            now = time.time()
            updates.append("updated_at = ?")
            params.append(now)
            params.append(webhook_id)

            conn = self._get_conn()
            cursor = conn.execute(
                f"UPDATE webhook_configs SET {', '.join(updates)} WHERE id = ?",  # noqa: S608 -- dynamic clause from internal state
                params,
            )
            conn.commit()
            if cursor.rowcount <= 0:
                return None
            webhook.updated_at = now

        return webhook

    def record_delivery(
        self,
        webhook_id: str,
        status_code: int,
        success: bool = True,
    ) -> None:
        conn = self._get_conn()
        now = time.time()
        if success:
            conn.execute(
                """UPDATE webhook_configs SET
                   last_delivery_at = ?, last_delivery_status = ?,
                   delivery_count = delivery_count + 1,
                   updated_at = ?
                   WHERE id = ?""",
                (now, status_code, now, webhook_id),
            )
        else:
            conn.execute(
                """UPDATE webhook_configs SET
                   last_delivery_at = ?, last_delivery_status = ?,
                   delivery_count = delivery_count + 1, failure_count = failure_count + 1,
                   updated_at = ?
                   WHERE id = ?""",
                (now, status_code, now, webhook_id),
            )
        conn.commit()

    def get_for_event(self, event_type: str) -> _list[WebhookConfig]:
        conn = self._get_conn()
        cursor = conn.execute(
            """SELECT id, url, events_json, secret, active, created_at, updated_at,
                      name, description, last_delivery_at, last_delivery_status,
                      delivery_count, failure_count, user_id, workspace_id
               FROM webhook_configs WHERE active = 1"""
        )
        webhooks = [WebhookConfig.from_row(row) for row in cursor.fetchall()]
        return [w for w in webhooks if w.matches_event(event_type)]

    def close(self) -> None:
        """Close all database connections."""
        with self._connections_lock:
            for conn in self._connections:
                try:
                    conn.close()
                except sqlite3.Error as e:
                    logger.debug("Error closing connection: %s", e)
            self._connections.clear()


class RedisWebhookConfigStore(WebhookConfigStoreBackend):
    """
    Redis-backed webhook config store with SQLite fallback.

    Uses Redis for fast distributed access, with SQLite as durable storage.
    This enables multi-instance deployments while ensuring persistence.
    """

    REDIS_PREFIX = "aragora:webhook_configs"
    REDIS_TTL = 86400  # 24 hours

    def __init__(self, db_path: Path | str, redis_url: str | None = None):
        self._sqlite = SQLiteWebhookConfigStore(db_path)
        self._redis: Any | None = None
        self._redis_url = redis_url or os.environ.get("ARAGORA_REDIS_URL", "redis://localhost:6379")
        self._redis_checked = False
        self._dirty_ids: set[str] = set()
        logger.info("RedisWebhookConfigStore initialized with SQLite fallback")

    def _get_redis(self) -> Any | None:
        """Get Redis client (lazy initialization)."""
        if self._redis_checked:
            return self._redis

        try:
            import redis

            self._redis = redis.from_url(self._redis_url, encoding="utf-8", decode_responses=True)
            self._redis.ping()
            self._redis_checked = True
            logger.info("Redis connected for webhook config store")
        except (ImportError, _RedisError, ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.debug("Redis not available, using SQLite only: %s", e)
            self._redis = None
            self._redis_checked = True

        return self._redis

    def _redis_key(self, webhook_id: str) -> str:
        return f"{self.REDIS_PREFIX}:{webhook_id}"

    def _mark_dirty(self, webhook_id: str) -> None:
        self._dirty_ids.add(webhook_id)

    def _clear_dirty(self, webhook_id: str) -> None:
        self._dirty_ids.discard(webhook_id)

    @staticmethod
    def _serialize_for_cache(webhook: WebhookConfig) -> str:
        """Serialize cache entries without storing decrypted secrets in Redis."""
        payload = webhook.to_dict(include_secret=True)
        secret = str(payload.get("secret") or "").strip()
        if secret:
            payload["secret"] = _encrypt_secret(secret)
        return json.dumps(payload)

    @staticmethod
    def _deserialize_from_cache(payload: str) -> WebhookConfig:
        """Deserialize cache entries, decrypting cached secrets when present."""
        data = json.loads(payload)
        if data.get("active") is not True and data.get("active") is not False:
            raise ValueError("cached webhook active flag must be boolean")
        secret = str(data.get("secret") or "").strip()
        if secret:
            data["secret"] = _decrypt_secret(secret)
        return WebhookConfig(**data)

    @staticmethod
    def _trusted_cache_revision(value: Any) -> float | None:
        """Return a revision usable for cache trust decisions.

        Cache payloads are untyped JSON. Reject booleans explicitly because
        `True == 1.0` and `False == 0.0`, which can accidentally satisfy the
        durable revision equality check.
        """
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        return None

    def register(
        self,
        url: str,
        events: _list[str],
        name: str | None = None,
        description: str | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> WebhookConfig:
        # Always save to SQLite (durable)
        webhook = self._sqlite.register(
            url=url,
            events=events,
            name=name,
            description=description,
            user_id=user_id,
            workspace_id=workspace_id,
        )

        # Update Redis cache
        redis = self._get_redis()
        if redis:
            try:
                redis.setex(
                    self._redis_key(webhook.id), self.REDIS_TTL, self._serialize_for_cache(webhook)
                )
            except (_RedisError, ConnectionError, TimeoutError, OSError, ValueError) as e:
                logger.debug("Redis cache update failed: %s", e)

        return webhook

    def get(self, webhook_id: str) -> WebhookConfig | None:
        redis = self._get_redis()

        # Try Redis first
        if redis is not None and webhook_id not in self._dirty_ids:
            try:
                data = redis.get(self._redis_key(webhook_id))
                if data:
                    cached_webhook = self._deserialize_from_cache(data)
                    durable_revision = self._sqlite.get_cache_revision(webhook_id)
                    cached_revision = self._trusted_cache_revision(cached_webhook.updated_at)
                    if (
                        durable_revision is not None
                        and cached_revision is not None
                        and cached_revision == durable_revision
                    ):
                        return cached_webhook
            except (
                _RedisError,
                ConnectionError,
                TimeoutError,
                OSError,
                ValueError,
                TypeError,
                KeyError,
                json.JSONDecodeError,
            ) as e:
                logger.debug("Redis get failed, falling back to SQLite: %s", e)

        # Fall back to SQLite
        webhook = self._sqlite.get(webhook_id)

        # Repair or clear Redis cache from authoritative durable state.
        if redis:
            try:
                if webhook is None:
                    redis.delete(self._redis_key(webhook_id))
                else:
                    redis.setex(
                        self._redis_key(webhook_id),
                        self.REDIS_TTL,
                        self._serialize_for_cache(webhook),
                    )
                self._clear_dirty(webhook_id)
            except (_RedisError, ConnectionError, TimeoutError) as e:
                logger.debug("Redis cache repair failed (connection issue): %s", e)
                self._mark_dirty(webhook_id)
            except (_RedisError, ConnectionError, TimeoutError, OSError, ValueError) as e:
                logger.debug("Redis cache repair failed: %s", e)
                self._mark_dirty(webhook_id)

        return webhook

    def list(
        self,
        user_id: str | None = None,
        workspace_id: str | None = None,
        active_only: bool = False,
    ) -> _list[WebhookConfig]:
        # Always use SQLite for list operations (authoritative)
        return self._sqlite.list(
            user_id=user_id, workspace_id=workspace_id, active_only=active_only
        )

    def delete(self, webhook_id: str) -> bool:
        redis = self._get_redis()
        if redis:
            try:
                redis.delete(self._redis_key(webhook_id))
                self._clear_dirty(webhook_id)
            except (_RedisError, ConnectionError, TimeoutError) as e:
                logger.debug("Redis cache delete failed (connection issue): %s", e)
                self._mark_dirty(webhook_id)
            except (_RedisError, ConnectionError, TimeoutError, OSError, ValueError) as e:
                logger.debug("Redis cache delete failed: %s", e)
                self._mark_dirty(webhook_id)

        return self._sqlite.delete(webhook_id)

    def update(
        self,
        webhook_id: str,
        url: str | None = None,
        events: _list[str] | None = None,
        active: bool | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> WebhookConfig | None:
        webhook = self._sqlite.update(
            webhook_id=webhook_id,
            url=url,
            events=events,
            active=active,
            name=name,
            description=description,
        )

        if webhook is None:
            # SQLite is authoritative. If the webhook no longer exists, clear
            # any stale Redis payload so later reads cannot resurrect it.
            # Mark the ID dirty even if delete succeeds so the next read uses
            # SQLite truth before trusting Redis again.
            redis = self._get_redis()
            if redis:
                try:
                    redis.delete(self._redis_key(webhook_id))
                    self._mark_dirty(webhook_id)
                except (_RedisError, ConnectionError, TimeoutError, OSError, ValueError) as e:
                    logger.debug("Redis cache delete on update miss failed: %s", e)
                    self._mark_dirty(webhook_id)
            return None

        # Update Redis cache
        redis = self._get_redis()
        if redis:
            try:
                redis.setex(
                    self._redis_key(webhook_id),
                    self.REDIS_TTL,
                    self._serialize_for_cache(webhook),
                )
                self._clear_dirty(webhook_id)
            except (_RedisError, ConnectionError, TimeoutError, OSError, ValueError) as e:
                logger.debug("Redis cache update failed: %s", e)
                self._mark_dirty(webhook_id)

        return webhook

    def record_delivery(
        self,
        webhook_id: str,
        status_code: int,
        success: bool = True,
    ) -> None:
        self._sqlite.record_delivery(webhook_id, status_code, success)

        # Invalidate Redis cache (next get will refresh)
        redis = self._get_redis()
        if redis:
            try:
                redis.delete(self._redis_key(webhook_id))
                self._clear_dirty(webhook_id)
            except (_RedisError, ConnectionError, TimeoutError, OSError, ValueError) as e:
                logger.debug("Redis cache invalidation failed: %s", e)
                self._mark_dirty(webhook_id)

    def get_for_event(self, event_type: str) -> _list[WebhookConfig]:
        return self._sqlite.get_for_event(event_type)

    def close(self) -> None:
        self._sqlite.close()
        if self._redis:
            self._redis.close()


class PostgresWebhookConfigStore(WebhookConfigStoreBackend):
    """
    PostgreSQL-backed webhook config store.

    Async implementation for production multi-instance deployments
    with horizontal scaling and concurrent writes.
    """

    SCHEMA_NAME = "webhook_configs"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS webhook_configs (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            events_json JSONB NOT NULL,
            secret TEXT NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            name TEXT,
            description TEXT,
            last_delivery_at TIMESTAMPTZ,
            last_delivery_status INTEGER,
            delivery_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            user_id TEXT,
            workspace_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_webhook_configs_user ON webhook_configs(user_id);
        CREATE INDEX IF NOT EXISTS idx_webhook_configs_workspace ON webhook_configs(workspace_id);
        CREATE INDEX IF NOT EXISTS idx_webhook_configs_active ON webhook_configs(active);
    """

    def __init__(self, pool: Pool):
        self._pool = pool
        self._initialized = False
        logger.info("PostgresWebhookConfigStore initialized")

    async def initialize(self) -> None:
        """Initialize database schema."""
        if self._initialized:
            return

        async with self._pool.acquire() as conn:
            await conn.execute(self.INITIAL_SCHEMA)

        self._initialized = True
        logger.debug("[%s] Schema initialized", self.SCHEMA_NAME)

    def register(
        self,
        url: str,
        events: _list[str],
        name: str | None = None,
        description: str | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> WebhookConfig:
        """Register a new webhook (sync wrapper for async)."""
        return run_async(self.register_async(url, events, name, description, user_id, workspace_id))

    async def register_async(
        self,
        url: str,
        events: _list[str],
        name: str | None = None,
        description: str | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> WebhookConfig:
        """Register a new webhook asynchronously."""
        webhook_id = str(uuid.uuid4())
        secret = secrets.token_urlsafe(32)
        now = time.time()

        webhook = WebhookConfig(
            id=webhook_id,
            url=url,
            events=events,
            secret=secret,
            name=name,
            description=description,
            user_id=user_id,
            workspace_id=workspace_id,
            created_at=now,
            updated_at=now,
        )

        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO webhook_configs
                   (id, url, events_json, secret, active, created_at, updated_at,
                    name, description, last_delivery_at, last_delivery_status,
                    delivery_count, failure_count, user_id, workspace_id)
                   VALUES ($1, $2, $3, $4, $5, to_timestamp($6), to_timestamp($7),
                           $8, $9, $10, $11, $12, $13, $14, $15)""",
                webhook.id,
                webhook.url,
                json.dumps(webhook.events),
                _encrypt_secret(webhook.secret),
                webhook.active,
                webhook.created_at,
                webhook.updated_at,
                webhook.name,
                webhook.description,
                None,  # last_delivery_at
                None,  # last_delivery_status
                0,  # delivery_count
                0,  # failure_count
                webhook.user_id,
                webhook.workspace_id,
            )

        logger.info("Registered webhook %s for events: %s", webhook_id, events)
        return webhook

    def get(self, webhook_id: str) -> WebhookConfig | None:
        """Get webhook by ID (sync wrapper for async)."""
        return run_async(self.get_async(webhook_id))

    async def get_async(self, webhook_id: str) -> WebhookConfig | None:
        """Get webhook by ID asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id, url, events_json, secret, active,
                          EXTRACT(EPOCH FROM created_at) as created_at,
                          EXTRACT(EPOCH FROM updated_at) as updated_at,
                          name, description,
                          EXTRACT(EPOCH FROM last_delivery_at) as last_delivery_at,
                          last_delivery_status, delivery_count, failure_count,
                          user_id, workspace_id
                   FROM webhook_configs WHERE id = $1""",
                webhook_id,
            )
            if row:
                return self._row_to_config(row)
            return None

    def _row_to_config(self, row: Any) -> WebhookConfig:
        """Convert database row to WebhookConfig."""
        return WebhookConfig(
            id=row["id"],
            url=row["url"],
            events=_deserialize_events(row["events_json"]),
            secret=_decrypt_secret(row["secret"] or ""),
            active=bool(row["active"]),
            created_at=row["created_at"] or time.time(),
            updated_at=row["updated_at"] or time.time(),
            name=row["name"],
            description=row["description"],
            last_delivery_at=row["last_delivery_at"],
            last_delivery_status=row["last_delivery_status"],
            delivery_count=row["delivery_count"] or 0,
            failure_count=row["failure_count"] or 0,
            user_id=row["user_id"],
            workspace_id=row["workspace_id"],
        )

    def list(
        self,
        user_id: str | None = None,
        workspace_id: str | None = None,
        active_only: bool = False,
    ) -> _list[WebhookConfig]:
        """List webhooks (sync wrapper for async)."""
        return run_async(self.list_async(user_id, workspace_id, active_only))

    async def list_async(
        self,
        user_id: str | None = None,
        workspace_id: str | None = None,
        active_only: bool = False,
    ) -> _list[WebhookConfig]:
        """List webhooks asynchronously."""
        query = """SELECT id, url, events_json, secret, active,
                          EXTRACT(EPOCH FROM created_at) as created_at,
                          EXTRACT(EPOCH FROM updated_at) as updated_at,
                          name, description,
                          EXTRACT(EPOCH FROM last_delivery_at) as last_delivery_at,
                          last_delivery_status, delivery_count, failure_count,
                          user_id, workspace_id
                   FROM webhook_configs WHERE 1=1"""
        params: _list[Any] = []
        param_idx = 1

        if user_id:
            query += f" AND user_id = ${param_idx}"
            params.append(user_id)
            param_idx += 1
        if workspace_id:
            query += f" AND workspace_id = ${param_idx}"
            params.append(workspace_id)
            param_idx += 1
        if active_only:
            query += " AND active = TRUE"

        query += " ORDER BY created_at DESC"

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_config(row) for row in rows]

    def delete(self, webhook_id: str) -> bool:
        """Delete webhook (sync wrapper for async)."""
        return run_async(self.delete_async(webhook_id))

    async def delete_async(self, webhook_id: str) -> bool:
        """Delete webhook asynchronously."""
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM webhook_configs WHERE id = $1", webhook_id)
            deleted = result != "DELETE 0"
            if deleted:
                logger.info("Deleted webhook %s", webhook_id)
            return deleted

    def update(
        self,
        webhook_id: str,
        url: str | None = None,
        events: _list[str] | None = None,
        active: bool | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> WebhookConfig | None:
        """Update webhook (sync wrapper for async)."""
        return run_async(self.update_async(webhook_id, url, events, active, name, description))

    async def update_async(
        self,
        webhook_id: str,
        url: str | None = None,
        events: _list[str] | None = None,
        active: bool | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> WebhookConfig | None:
        """Update webhook asynchronously."""
        webhook = await self.get_async(webhook_id)
        if not webhook:
            return None

        updates: _list[str] = []
        params: _list[Any] = []
        param_idx = 1

        if url is not None:
            updates.append(f"url = ${param_idx}")
            params.append(url)
            param_idx += 1
            webhook.url = url
        if events is not None:
            updates.append(f"events_json = ${param_idx}")
            params.append(json.dumps(events))
            param_idx += 1
            webhook.events = events
        if active is not None:
            updates.append(f"active = ${param_idx}")
            params.append(active)
            param_idx += 1
            webhook.active = active
        if name is not None:
            updates.append(f"name = ${param_idx}")
            params.append(name)
            param_idx += 1
            webhook.name = name
        if description is not None:
            updates.append(f"description = ${param_idx}")
            params.append(description)
            param_idx += 1
            webhook.description = description

        if updates:
            updated_at = time.time()
            updates.append(f"updated_at = to_timestamp(${param_idx})")
            params.append(updated_at)
            param_idx += 1
            params.append(webhook_id)

            async with self._pool.acquire() as conn:
                result = await conn.execute(
                    f"UPDATE webhook_configs SET {', '.join(updates)} WHERE id = ${param_idx}",  # noqa: S608 -- dynamic clause from internal state
                    *params,
                )
            if result == "UPDATE 0":
                return None
            durable = await self.get_async(webhook_id)
            if durable is None:
                return None
            return durable

        return webhook

    def record_delivery(
        self,
        webhook_id: str,
        status_code: int,
        success: bool = True,
    ) -> None:
        """Record delivery (sync wrapper for async)."""
        run_async(self.record_delivery_async(webhook_id, status_code, success))

    async def record_delivery_async(
        self,
        webhook_id: str,
        status_code: int,
        success: bool = True,
    ) -> None:
        """Record delivery asynchronously."""
        async with self._pool.acquire() as conn:
            if success:
                await conn.execute(
                    """UPDATE webhook_configs SET
                       last_delivery_at = NOW(), last_delivery_status = $1,
                       delivery_count = delivery_count + 1,
                       updated_at = NOW()
                       WHERE id = $2""",
                    status_code,
                    webhook_id,
                )
            else:
                await conn.execute(
                    """UPDATE webhook_configs SET
                       last_delivery_at = NOW(), last_delivery_status = $1,
                       delivery_count = delivery_count + 1, failure_count = failure_count + 1,
                       updated_at = NOW()
                       WHERE id = $2""",
                    status_code,
                    webhook_id,
                )

    def get_for_event(self, event_type: str) -> _list[WebhookConfig]:
        """Get webhooks for event (sync wrapper for async)."""
        return run_async(self.get_for_event_async(event_type))

    async def get_for_event_async(self, event_type: str) -> _list[WebhookConfig]:
        """Get webhooks for event asynchronously."""
        webhooks = await self.list_async(active_only=True)
        return [w for w in webhooks if w.matches_event(event_type)]

    def close(self) -> None:
        """Close is a no-op for pool-based stores (pool managed externally)."""
        pass


# =============================================================================
# Global Store Factory
# =============================================================================

_webhook_config_store: WebhookConfigStoreBackend | None = None


def get_webhook_config_store() -> WebhookConfigStoreBackend:
    """
    Get or create the webhook config store.

    Backend selection (in preference order):
    1. Supabase PostgreSQL (if SUPABASE_URL + SUPABASE_DB_PASSWORD configured)
    2. Self-hosted PostgreSQL (if DATABASE_URL or ARAGORA_POSTGRES_DSN configured)
    3. Redis (if ARAGORA_WEBHOOK_CONFIG_STORE_BACKEND=redis)
    4. SQLite (fallback, with production warning)

    Override via:
    - ARAGORA_WEBHOOK_CONFIG_STORE_BACKEND: "memory", "sqlite", "postgres", "supabase", or "redis"
    - ARAGORA_DB_BACKEND: Global override

    Returns:
        Configured WebhookConfigStoreBackend instance
    """
    global _webhook_config_store
    if _webhook_config_store is not None:
        return _webhook_config_store

    # Check store-specific backend for Redis (not handled by create_persistent_store)
    backend_type = os.environ.get("ARAGORA_WEBHOOK_CONFIG_STORE_BACKEND", "").lower()
    fallback_db_path = Path(resolve_db_path("webhook_configs.db"))
    if backend_type == "redis":
        logger.info("Using Redis webhook config store with SQLite fallback")
        _webhook_config_store = RedisWebhookConfigStore(fallback_db_path)
        return _webhook_config_store

    # Use unified factory for memory/sqlite/postgres/supabase
    from aragora.storage.connection_factory import create_persistent_store

    _webhook_config_store = create_persistent_store(
        store_name="webhook_config",
        sqlite_class=SQLiteWebhookConfigStore,
        postgres_class=PostgresWebhookConfigStore,
        db_filename="webhook_configs.db",
        memory_class=InMemoryWebhookConfigStore,
    )

    return _webhook_config_store


def set_webhook_config_store(store: WebhookConfigStoreBackend) -> None:
    """
    Set custom webhook config store.

    Useful for testing or custom deployments.
    """
    global _webhook_config_store
    previous = _webhook_config_store
    _webhook_config_store = store
    if previous is not None and previous is not store:
        try:
            previous.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to close previous webhook config store: %s", exc)
    logger.debug("Webhook config store backend set: %s", type(store).__name__)


def reset_webhook_config_store() -> None:
    """Reset the global webhook config store (for testing)."""
    global _webhook_config_store
    previous = _webhook_config_store
    _webhook_config_store = None
    if previous is not None:
        try:
            previous.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to close webhook config store during reset: %s", exc)


atexit.register(reset_webhook_config_store)


__all__ = [
    "WebhookConfig",
    "WebhookConfigStoreBackend",
    "InMemoryWebhookConfigStore",
    "SQLiteWebhookConfigStore",
    "RedisWebhookConfigStore",
    "PostgresWebhookConfigStore",
    "get_webhook_config_store",
    "set_webhook_config_store",
    "reset_webhook_config_store",
    "WEBHOOK_EVENTS",
]
