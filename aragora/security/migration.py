"""
Encryption Migration Utilities.

Provides tools for migrating plaintext secrets to encrypted format
and running migrations on application startup.

Features:
- Automatic detection of plaintext vs encrypted fields
- Background migration for existing records
- Startup migration option
- Migration progress tracking and reporting
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import logging
import os
import sqlite3
import struct
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypeVar
from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)

T = TypeVar("T")

_SYNC_STORE_CALL_TIMEOUT = 30.0
_SYNC_STORE_LOOP_GRACE = 5.0

MigrationAuditProvider = Callable[..., Any]

_migration_audit_provider: MigrationAuditProvider | None = None

_MISSING_PROVIDER_REMEDY = (
    "call aragora.ops.security_edge_adapters.register_security_migration_adapters() "
    "or register_migration_audit_provider() before rotating keys"
)


def register_migration_audit_provider(provider: MigrationAuditProvider | None) -> None:
    """Register the provider that emits key-rotation security audit events.

    This module must not import the audit layer, so the composition root
    supplies the provider. Server startup and the ``aragora security`` CLI
    commands call
    ``aragora.ops.security_edge_adapters.register_security_migration_adapters()``,
    which routes events to ``aragora.audit.unified.audit_security``. Embedded
    callers of :func:`rotate_encryption_key` must do the same, or pass their own
    callable here. The provider receives keyword arguments only
    (``event_type``, ``actor_id`` and event-specific fields). Pass ``None`` to
    unregister.
    """
    global _migration_audit_provider
    _migration_audit_provider = provider


def get_migration_audit_provider() -> MigrationAuditProvider | None:
    """Return the registered migration audit provider, or ``None`` if none is set."""
    return _migration_audit_provider


def _audit_security(**kwargs: Any) -> Any:
    """Emit a security audit event through the registered provider."""
    if _migration_audit_provider is None:
        logger.warning(
            "Migration audit provider not registered; security event %r was not emitted (%s)",
            kwargs.get("event_type"),
            _MISSING_PROVIDER_REMEDY,
        )
        return None
    return _migration_audit_provider(**kwargs)


@dataclass
class MigrationResult:
    """Result of a migration operation."""

    store_name: str
    total_records: int = 0
    migrated_records: int = 0
    already_encrypted: int = 0
    failed_records: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    duration_seconds: float = 0.0

    @property
    def success(self) -> bool:
        """Check if migration was successful."""
        return self.failed_records == 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "store_name": self.store_name,
            "total_records": self.total_records,
            "migrated_records": self.migrated_records,
            "already_encrypted": self.already_encrypted,
            "failed_records": self.failed_records,
            "errors": self.errors[:10],  # Limit error details
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
        }


def is_field_encrypted(value: Any) -> bool:
    """Check if a field value is already encrypted."""
    if isinstance(value, dict):
        return value.get("_encrypted") is True
    return False


def needs_migration(record: dict[str, Any], sensitive_fields: list[str]) -> bool:
    """Check if a record has plaintext sensitive fields that need migration."""
    for field_name in sensitive_fields:
        if field_name in record:
            value = record[field_name]
            if value is not None and not is_field_encrypted(value):
                return True
    return False


class EncryptionMigrator:
    """
    Handles migration of plaintext data to encrypted format.

    This migrator works with any store that implements a basic interface:
    - list_all() -> list[Dict] or similar
    - save(record) or update(id, record)
    """

    def __init__(
        self,
        encryption_service: Any | None = None,
        batch_size: int = 100,
        dry_run: bool = False,
    ):
        """
        Initialize the migrator.

        Args:
            encryption_service: Encryption service instance (uses global if not provided)
            batch_size: Number of records to process in each batch
            dry_run: If True, report what would be migrated without making changes
        """
        self._encryption_service = encryption_service
        self._batch_size = batch_size
        self._dry_run = dry_run

    def _get_encryption_service(self):
        """Get encryption service lazily."""
        if self._encryption_service is None:
            from aragora.security.encryption import get_encryption_service

            self._encryption_service = get_encryption_service()
        return self._encryption_service

    def migrate_record(
        self,
        record: dict[str, Any],
        sensitive_fields: list[str],
        record_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Migrate a single record's sensitive fields to encrypted format.

        Args:
            record: The record to migrate
            sensitive_fields: Fields that should be encrypted
            record_id: Optional record ID for associated data

        Returns:
            Migrated record with encrypted fields
        """
        service = self._get_encryption_service()
        return service.encrypt_fields(record, sensitive_fields, associated_data=record_id)

    def migrate_store(
        self,
        store_name: str,
        list_fn: Callable[[], list[dict[str, Any]]],
        save_fn: Callable[[str, dict[str, Any]], bool],
        sensitive_fields: list[str],
        id_field: str = "id",
    ) -> MigrationResult:
        """
        Migrate all records in a store.

        Args:
            store_name: Name of the store (for logging/reporting)
            list_fn: Function that returns all records
            save_fn: Function that saves a record (id, record) -> success
            sensitive_fields: Fields that should be encrypted
            id_field: Name of the ID field in records

        Returns:
            MigrationResult with statistics
        """
        result = MigrationResult(store_name=store_name)

        try:
            records = list_fn()
            result.total_records = len(records)

            logger.info("Starting migration for %s: %s records", store_name, result.total_records)

            for record in records:
                record_id = record.get(id_field, "unknown")

                try:
                    if not needs_migration(record, sensitive_fields):
                        result.already_encrypted += 1
                        continue

                    if self._dry_run:
                        result.migrated_records += 1
                        logger.debug("[DRY RUN] Would migrate record: %s", record_id)
                        continue

                    # Migrate the record
                    migrated = self.migrate_record(
                        record, sensitive_fields, record_id=str(record_id)
                    )

                    # Save back
                    if save_fn(record_id, migrated):
                        result.migrated_records += 1
                        logger.debug("Migrated record: %s", record_id)
                    else:
                        result.failed_records += 1
                        result.errors.append(f"Failed to save record: {record_id}")

                except (KeyError, ValueError, TypeError, RuntimeError, OSError) as e:
                    result.failed_records += 1
                    result.errors.append(f"Error migrating record: {record_id}")
                    logger.warning("Failed to migrate record %s: %s", record_id, e)

            result.completed_at = datetime.now(timezone.utc)
            result.duration_seconds = (result.completed_at - result.started_at).total_seconds()

            logger.info(
                "Migration complete for %s: %s migrated, %s already encrypted, %s failed",
                store_name,
                result.migrated_records,
                result.already_encrypted,
                result.failed_records,
            )

        except (TypeError, RuntimeError, OSError, ValueError) as e:
            result.errors.append("Migration failed due to an internal error")
            result.failed_records = max(1, result.total_records)
            logger.error("Migration failed for %s: %s", store_name, e)

        return result


# Store-specific migration functions

_INTEGRATION_RECORD_ID_FIELD = "__integration_record_id__"

# Integration backends cap list_all() at 1000 rows unless given a limit and
# cannot page, so they are asked for one row past this bound to detect a store
# too large to process in a single pass.
_INTEGRATION_LIST_LIMIT = 1_000_000


class _StoreListingError(RuntimeError):
    """A store could not list its records; the cause is logged, never reported."""


def _list_store_records(store: Any, store_name: str, limit: int | None = None) -> list[Any]:
    """Await ``store.list_all()``, turning every non-import failure into a listing error.

    With ``limit``, a store holding more than ``limit`` records is a listing
    error rather than a silently partial list. ImportError propagates so
    callers keep their optional-dependency handling.
    """
    from aragora.utils.async_utils import run_async

    try:
        if limit is None:
            records = list(run_async(store.list_all()))
        else:
            records = list(run_async(store.list_all(limit=limit + 1)))
    except ImportError:
        raise
    except Exception as e:  # noqa: BLE001 - driver errors (sqlite3, asyncpg) are not builtins
        # Driver messages can carry DSNs or file paths, so only the type is logged.
        logger.error("Listing records failed for %s: %s", store_name, type(e).__name__)
        raise _StoreListingError(f"Listing records failed for {store_name}") from e
    if limit is not None and len(records) > limit:
        logger.error("Listing records for %s exceeded the %d-record bound", store_name, limit)
        raise _StoreListingError(f"Listing records exceeded the bound for {store_name}")
    return records


def _finish_migration(result: MigrationResult) -> MigrationResult:
    result.completed_at = datetime.now(timezone.utc)
    result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
    logger.info(
        "Migration complete for %s: %s migrated, %s already encrypted, %s failed",
        result.store_name,
        result.migrated_records,
        result.already_encrypted,
        result.failed_records,
    )
    return result


def _listing_failed(result: MigrationResult) -> MigrationResult:
    result.errors.append("Migration failed due to an internal error")
    result.failed_records = max(1, result.total_records)
    return _finish_migration(result)


def _is_undecrypted_token(token: Any) -> bool:
    """Return True when a Gmail store handed back a token it could not decrypt.

    Gmail backends return the stored ciphertext unchanged when decryption fails,
    and saving it again would encrypt the ciphertext a second time.
    """
    if not isinstance(token, str) or not token:
        return False
    from aragora.security.encryption import EncryptedData

    try:
        data = EncryptedData.from_bytes(base64.b64decode(token, validate=True))
    except (ValueError, struct.error):
        return False
    # An AES-GCM ciphertext always carries a nonce and at least the 16-byte tag.
    return bool(data.nonce) and len(data.ciphertext) >= 16


def migrate_integration_store(dry_run: bool = False) -> MigrationResult:
    """Migrate integration store secrets."""
    try:
        from aragora.storage.integration_models import EncryptionError
        from aragora.storage.integration_store import SENSITIVE_KEYS, get_integration_store
        from aragora.utils.async_utils import run_async

        store = get_integration_store()
        result = MigrationResult(store_name="integration_store")

        # Exactly the keys the store encrypts on save, so every plaintext one is re-saved.
        sensitive_fields = sorted(SENSITIVE_KEYS)

        try:
            configs = _list_store_records(store, result.store_name, limit=_INTEGRATION_LIST_LIMIT)
        except _StoreListingError:
            return _listing_failed(result)
        result.total_records = len(configs)

        logger.info(
            "Starting migration for %s: %s records",
            result.store_name,
            result.total_records,
        )

        for config in configs:
            integration_type = str(getattr(config, "type", "") or "unknown")
            user_id = str(getattr(config, "user_id", "") or "default")
            record_id = f"{user_id}:{integration_type}"

            try:
                settings = getattr(config, "settings", {})
                if isinstance(settings, dict) and any(
                    is_field_encrypted(settings.get(name)) for name in sensitive_fields
                ):
                    # The store returns settings it could not decrypt unchanged. Such a record
                    # is not cleanly encrypted, and saving it would encrypt that ciphertext again.
                    raise ValueError("Store returned a setting it could not decrypt")
                if not isinstance(settings, dict) or not needs_migration(
                    settings, sensitive_fields
                ):
                    result.already_encrypted += 1
                    continue

                if dry_run:
                    result.migrated_records += 1
                    logger.debug("[DRY RUN] Would migrate record: %s", record_id)
                    continue

                run_async(store.save(config))
                result.migrated_records += 1
                logger.debug("Migrated record: %s", record_id)
            except (KeyError, ValueError, TypeError, RuntimeError, OSError, EncryptionError) as e:
                result.failed_records += 1
                result.errors.append(f"Error migrating record: {record_id}")
                logger.warning("Failed to migrate record %s: %s", record_id, type(e).__name__)

        return _finish_migration(result)
    except ImportError as e:
        logger.warning("Integration store not available: %s", e)
        return MigrationResult(
            store_name="integration_store", errors=["Integration store not available"]
        )


def migrate_gmail_token_store(dry_run: bool = False) -> MigrationResult:
    """Re-save Gmail OAuth tokens so the store encrypts them with the active key.

    Gmail backends decrypt tokens in ``list_all()`` and encrypt them in
    ``save()``, so re-saving a user's state migrates plaintext tokens and tokens
    under older key versions alike. A dry run lists and counts without saving.
    """
    try:
        from aragora.storage.gmail_token_store import (
            ENCRYPTED_FIELDS,
            EncryptionError,
            get_gmail_token_store,
        )
        from aragora.utils.async_utils import run_async

        store = get_gmail_token_store()
        result = MigrationResult(store_name="gmail_token_store")

        try:
            states = _list_store_records(store, result.store_name)
        except _StoreListingError:
            return _listing_failed(result)
        result.total_records = len(states)

        logger.info(
            "Starting migration for %s: %s records",
            result.store_name,
            result.total_records,
        )

        for state in states:
            user_id = str(getattr(state, "user_id", "") or "unknown")
            try:
                tokens = [getattr(state, name) for name in ENCRYPTED_FIELDS]
                if not any(tokens):
                    result.already_encrypted += 1
                    continue
                if any(_is_undecrypted_token(token) for token in tokens):
                    raise ValueError("Store returned a token it could not decrypt")

                if dry_run:
                    logger.debug("[DRY RUN] Would migrate record: %s", user_id)
                else:
                    run_async(store.save(state))
                result.migrated_records += 1
            except (
                AttributeError,
                KeyError,
                ValueError,
                TypeError,
                RuntimeError,
                OSError,
                sqlite3.Error,
                EncryptionError,
            ) as e:
                result.failed_records += 1
                result.errors.append(f"Error migrating record: {user_id}")
                logger.warning("Failed to migrate record %s: %s", user_id, type(e).__name__)

        return _finish_migration(result)
    except ImportError as e:
        logger.warning("Gmail token store not available: %s", e)
        return MigrationResult(
            store_name="gmail_token_store", errors=["Gmail token store not available"]
        )


def _run_private_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    finally:
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            loop.close()


class _SyncStoreSession:
    """A sync store plus the one event loop that every call on it runs on.

    Database connections belong to the loop that opened them, so a store must
    never be opened on one temporary loop and used from another. When the shared
    pool loop is running, the process-wide store lives there and calls are
    dispatched to it. Otherwise a private store is opened on a private loop
    thread and closed together with that loop.
    """

    def __init__(self) -> None:
        from aragora.utils.async_utils import get_pool_event_loop

        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._closed = False
        self.store: Any = None

        pool_loop = get_pool_event_loop()
        if pool_loop is not None and pool_loop.is_running():
            from aragora.storage.sync_store import get_sync_store

            self.store = self.run(get_sync_store())
            return

        from aragora.storage.sync_store import SyncStore

        loop = asyncio.new_event_loop()
        self._loop = loop
        self._thread = threading.Thread(
            target=_run_private_loop,
            args=(loop,),
            name="security-migration-sync-store",
            daemon=True,
        )
        try:
            self._thread.start()
        except BaseException:
            self._closed = True
            loop.close()
            raise
        try:
            # Job recovery belongs to the process that runs the jobs; a store
            # opened only to re-save connectors must not interrupt live syncs.
            self.store = SyncStore(recover_jobs_on_init=False)
            self.run(self.store.initialize())
        except BaseException:
            self.close()
            raise

    def run(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run ``coro`` on this session's loop and return its result."""
        if self._closed:
            coro.close()
            raise RuntimeError("Sync store session is closed")
        if self._loop is None:
            from aragora.utils.async_utils import run_async

            return run_async(coro, timeout=_SYNC_STORE_CALL_TIMEOUT)
        future = asyncio.run_coroutine_threadsafe(
            asyncio.wait_for(coro, timeout=_SYNC_STORE_CALL_TIMEOUT), self._loop
        )
        try:
            return future.result(timeout=_SYNC_STORE_CALL_TIMEOUT + _SYNC_STORE_LOOP_GRACE)
        except (asyncio.TimeoutError, concurrent.futures.TimeoutError) as e:
            # Normalise to the builtin, which is an OSError on every supported
            # Python, so per-record handlers count a private-loop timeout as a
            # failed record. Shared-pool calls keep run_async's timeout type.
            future.cancel()
            raise TimeoutError(
                f"Sync store call timed out after {_SYNC_STORE_CALL_TIMEOUT:.1f}s"
            ) from e

    def close(self) -> None:
        """Close a private store and its loop. The shared process-wide store stays open."""
        loop, thread = self._loop, self._thread
        if self._closed or loop is None or thread is None:
            self._closed = True
            return
        try:
            if self.store is not None:
                self.run(self.store.close())
        except Exception as e:  # noqa: BLE001 - driver errors (sqlite3, asyncpg) are not builtins
            logger.warning("Failed to close migration sync store: %s", e)
        finally:
            self._closed = True
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=_SYNC_STORE_CALL_TIMEOUT)
            if thread.is_alive():
                logger.warning("Migration sync store loop did not stop within the timeout")


def migrate_sync_store(dry_run: bool = False) -> MigrationResult:
    """Migrate connector sync store secrets."""
    result = MigrationResult(store_name="sync_store")
    sensitive_fields = [
        "api_key",
        "api_secret",
        "token",
        "password",
        "auth_token",
        "secret",
    ]

    session: _SyncStoreSession | None = None
    try:
        session = _SyncStoreSession()
        store = session.store
        connectors = session.run(store.list_connectors())
        result.total_records = len(connectors)

        for connector in connectors:
            try:
                if not needs_migration(connector.config, sensitive_fields):
                    result.already_encrypted += 1
                    continue

                if not dry_run:
                    session.run(
                        store.save_connector(
                            connector.id,
                            connector.connector_type,
                            connector.name,
                            connector.config,
                        )
                    )
                result.migrated_records += 1
            except (KeyError, ValueError, TypeError, RuntimeError, OSError) as e:
                result.failed_records += 1
                result.errors.append(f"Error migrating record: {connector.id}")
                logger.warning("Failed to migrate sync connector %s: %s", connector.id, e)
    except (ImportError, RuntimeError, ValueError, TypeError, OSError) as e:
        logger.warning("Sync store not available: %s", e)
        result.errors.append("Sync store not available")
    finally:
        if session is not None:
            session.close()

    result.completed_at = datetime.now(timezone.utc)
    result.duration_seconds = (result.completed_at - result.started_at).total_seconds()
    return result


@dataclass
class StartupMigrationConfig:
    """Configuration for startup migration."""

    enabled: bool = False
    dry_run: bool = False
    stores: list[str] = field(default_factory=lambda: ["integration", "gmail", "sync"])
    fail_on_error: bool = False


def get_startup_migration_config() -> StartupMigrationConfig:
    """Get startup migration config from environment."""
    return StartupMigrationConfig(
        enabled=os.environ.get("ARAGORA_MIGRATE_ON_STARTUP", "").lower()
        in (
            "true",
            "1",
            "yes",
        ),
        dry_run=os.environ.get("ARAGORA_MIGRATION_DRY_RUN", "").lower()
        in (
            "true",
            "1",
            "yes",
        ),
        stores=os.environ.get("ARAGORA_MIGRATION_STORES", "integration,gmail,sync").split(","),
        fail_on_error=os.environ.get("ARAGORA_MIGRATION_FAIL_ON_ERROR", "").lower()
        in (
            "true",
            "1",
            "yes",
        ),
    )


def run_startup_migration(
    config: StartupMigrationConfig | None = None,
) -> list[MigrationResult]:
    """
    Run encryption migration on startup.

    This function can be called during application initialization to
    migrate any plaintext secrets to encrypted format.

    Args:
        config: Migration configuration (uses env vars if not provided)

    Returns:
        List of migration results for each store

    Environment Variables:
        ARAGORA_MIGRATE_ON_STARTUP: Set to "true" to enable
        ARAGORA_MIGRATION_DRY_RUN: Set to "true" for dry run mode
        ARAGORA_MIGRATION_STORES: Comma-separated list of stores to migrate
        ARAGORA_MIGRATION_FAIL_ON_ERROR: Set to "true" to fail on errors
    """
    if config is None:
        config = get_startup_migration_config()

    if not config.enabled:
        logger.debug("Startup migration disabled")
        return []

    logger.info("Running startup migration (dry_run=%s, stores=%s)", config.dry_run, config.stores)

    results = []

    store_migrations = {
        "integration": migrate_integration_store,
        "gmail": migrate_gmail_token_store,
        "sync": migrate_sync_store,
    }

    for store_name in config.stores:
        store_name = store_name.strip()
        migrate_fn = store_migrations.get(store_name)

        if migrate_fn is None:
            logger.warning("Unknown store for migration: %s", store_name)
            continue

        try:
            result = migrate_fn(dry_run=config.dry_run)
            results.append(result)

            if not result.success and config.fail_on_error:
                raise RuntimeError(f"Migration failed for {store_name}: {result.errors}")

        except (RuntimeError, OSError, ValueError, KeyError, TypeError) as e:
            logger.error("Migration error for %s: %s", store_name, e)
            if config.fail_on_error:
                raise

    logger.info("Startup migration complete: %s stores processed", len(results))
    return results


# =============================================================================
# Key Rotation Workflow
# =============================================================================


@dataclass
class KeyRotationResult:
    """Result of a key rotation operation."""

    old_key_id: str
    new_key_id: str
    old_key_version: int
    new_key_version: int
    stores_processed: int = 0
    records_reencrypted: int = 0
    failed_records: int = 0
    errors: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    duration_seconds: float = 0.0

    @property
    def success(self) -> bool:
        """Check if rotation was successful."""
        return self.failed_records == 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "old_key_id": self.old_key_id,
            "new_key_id": self.new_key_id,
            "old_key_version": self.old_key_version,
            "new_key_version": self.new_key_version,
            "stores_processed": self.stores_processed,
            "records_reencrypted": self.records_reencrypted,
            "failed_records": self.failed_records,
            "errors": self.errors[:10],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
        }


def rotate_and_reencrypt_store(
    store_name: str,
    list_fn: Callable[[], list[dict[str, Any]]],
    save_fn: Callable[[str, dict[str, Any]], bool],
    sensitive_fields: list[str],
    id_field: str = "id",
    encryption_service: Any | None = None,
    force_resave: bool = False,
) -> MigrationResult:
    """
    Re-encrypt all records in a store with the current active key.

    Use this after rotating the encryption key to update all records
    to use the new key.

    Args:
        store_name: Name of the store
        list_fn: Function that returns all records
        save_fn: Function that saves a record (id, record) -> success
        sensitive_fields: Fields that are encrypted
        id_field: Name of the ID field in records
        encryption_service: Encryption service (uses global if not provided)
        force_resave: Re-save plaintext records so the store encrypts them with the active key

    Returns:
        MigrationResult with statistics
    """
    from aragora.security.encryption import get_encryption_service

    service = encryption_service or get_encryption_service()
    result = MigrationResult(store_name=store_name)

    try:
        records = list_fn()
        result.total_records = len(records)

        logger.info(
            "Starting key rotation re-encryption for %s: %s records",
            store_name,
            result.total_records,
        )

        for record in records:
            record_id = record.get(id_field, "unknown")

            try:
                # Check if record has encrypted fields
                has_encrypted = any(is_field_encrypted(record.get(f)) for f in sensitive_fields)

                if force_resave:
                    if has_encrypted:
                        raise RuntimeError("Store returned an encrypted record")
                    if save_fn(record_id, record):
                        result.migrated_records += 1
                    else:
                        result.failed_records += 1
                        result.errors.append(f"Failed to save record: {record_id}")
                    continue

                if not has_encrypted:
                    # Record has no encrypted fields, skip
                    result.already_encrypted += 1
                    continue

                # Re-encrypt: decrypt with any valid key, encrypt with active key
                reencrypted = {}
                for key, value in record.items():
                    if key in sensitive_fields and is_field_encrypted(value):
                        # Decrypt and re-encrypt
                        try:
                            plaintext = service.decrypt(value, associated_data=str(record_id))
                            encrypted = service.encrypt(
                                plaintext,
                                associated_data=str(record_id),
                            )
                            reencrypted[key] = encrypted.to_base64()
                        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
                            logger.warning("Failed to re-encrypt field %s: %s", key, e)
                            reencrypted[key] = value  # Keep original
                    else:
                        reencrypted[key] = value

                # Save back
                if save_fn(record_id, reencrypted):
                    result.migrated_records += 1
                    logger.debug("Re-encrypted record: %s", record_id)
                else:
                    result.failed_records += 1
                    result.errors.append(f"Failed to save record: {record_id}")

            except (KeyError, ValueError, TypeError, RuntimeError, OSError) as e:
                result.failed_records += 1
                result.errors.append(f"Error re-encrypting record: {record_id}")
                logger.warning("Failed to re-encrypt record %s: %s", record_id, e)

        result.completed_at = datetime.now(timezone.utc)
        result.duration_seconds = (result.completed_at - result.started_at).total_seconds()

        logger.info(
            "Key rotation re-encryption complete for %s: %s re-encrypted, %s skipped, %s failed",
            store_name,
            result.migrated_records,
            result.already_encrypted,
            result.failed_records,
        )

    except (TypeError, RuntimeError, OSError, ValueError) as e:
        result.errors.append("Re-encryption failed due to an internal error")
        result.failed_records = max(1, result.total_records)
        logger.error("Key rotation re-encryption failed for %s: %s", store_name, e)

    return result


def rotate_encryption_key(
    stores: list[str] | None = None,
    dry_run: bool = False,
) -> KeyRotationResult:
    """
    Rotate the encryption key and re-encrypt all data.

    This function:
    1. Rotates the active encryption key (old key remains valid during overlap)
    2. Re-encrypts all records in specified stores with the new key
    3. Returns a summary of the rotation operation

    Args:
        stores: List of stores to re-encrypt (default: all)
        dry_run: If True, only show what would be done

    Returns:
        KeyRotationResult with statistics

    Audit:
        Emits a ``key_rotation`` security event through the provider set with
        :func:`register_migration_audit_provider`. Without a provider the event
        is dropped and a warning is logged, so embedded callers must register
        one before calling this function.

    Environment Variables:
        ARAGORA_KEY_ROTATION_OVERLAP_DAYS: Days to keep old key valid (default: 7)
    """
    from aragora.security.encryption import get_encryption_service

    service = get_encryption_service()

    # Get current key info
    active_key_id = service._active_key_id
    old_key = service._keys.get(active_key_id) if active_key_id else None
    old_key_id = active_key_id or "default"
    old_version = old_key.version if old_key else 0

    result = KeyRotationResult(
        old_key_id=old_key_id,
        new_key_id=old_key_id,  # Will be same ID, different version
        old_key_version=old_version,
        new_key_version=old_version + 1,
    )

    store_configs = {
        "integration": _get_integration_store_config,
        "gmail": _get_gmail_store_config,
        "sync": _get_sync_store_config,
    }
    stores_to_process = stores or list(store_configs)
    unknown_stores = [
        name for name in stores_to_process if not isinstance(name, str) or name not in store_configs
    ]
    if unknown_stores:
        # Reject before rotating so a mistyped name cannot rotate the key and skip its store.
        result.new_key_version = old_version
        result.failed_records += len(unknown_stores)
        for name in unknown_stores:
            label = name if isinstance(name, str) else type(name).__name__
            result.errors.append(f"Unknown store for key rotation: {label[:64]}")
        logger.warning("Key rotation rejected; unknown stores: %s", unknown_stores)
        return result

    if dry_run:
        logger.info(
            "[DRY RUN] Would rotate key %s from v%s to v%s",
            old_key_id,
            old_version,
            old_version + 1,
        )
        try:
            _audit_security(
                event_type="key_rotation",
                actor_id="system",
                reason="dry_run_key_rotation",
            )
        except ImportError as e:
            logger.warning(
                "Migration audit provider could not load its audit backend; "
                "dry-run key rotation event was not emitted: %s",
                e,
            )
        return result

    try:
        # Rotate the key
        new_key = service.rotate_key(old_key_id)
        result.new_key_id = new_key.key_id
        result.new_key_version = new_key.version

        logger.info(
            "Rotated encryption key: %s v%s -> v%s", old_key_id, old_version, new_key.version
        )

        # Audit log key rotation
        try:
            _audit_security(
                event_type="key_rotation",
                actor_id="system",
                old_version=old_version,
                new_version=new_key.version,
            )
        except ImportError as e:
            logger.warning(
                "Migration audit provider could not load its audit backend; "
                "key rotation event was not emitted: %s",
                e,
            )

        for store_name in stores_to_process:
            config_fn = store_configs[store_name]
            config: dict[str, Any] | None = None
            try:
                config = config_fn()
                if config is None:
                    if store_name == "sync":
                        result.failed_records += 1
                        result.errors.append("Store sync re-encryption failed")
                    continue

                store_result = rotate_and_reencrypt_store(
                    store_name=store_name,
                    list_fn=config["list_fn"],
                    save_fn=config["save_fn"],
                    sensitive_fields=config["sensitive_fields"],
                    id_field=config["id_field"],
                    encryption_service=service,
                    force_resave=config.get("force_resave", False),
                )

                result.stores_processed += 1
                result.records_reencrypted += store_result.migrated_records
                result.failed_records += store_result.failed_records
                result.errors.extend(store_result.errors)

            except (ImportError, RuntimeError, ValueError, TypeError, OSError, sqlite3.Error) as e:
                result.errors.append(f"Store {store_name} re-encryption failed")
                result.failed_records += 1
                logger.error("Key rotation failed for store %s: %s", store_name, e)
            finally:
                close_fn = config.get("close_fn") if config else None
                if close_fn is not None:
                    close_fn()

        result.completed_at = datetime.now(timezone.utc)
        result.duration_seconds = (result.completed_at - result.started_at).total_seconds()

        logger.info(
            "Key rotation complete: %s stores, %s records re-encrypted, %s failures",
            result.stores_processed,
            result.records_reencrypted,
            result.failed_records,
        )

    except (
        RuntimeError,
        ValueError,
        TypeError,
        OSError,
        ImportError,
        AttributeError,
        sqlite3.Error,
    ) as e:
        result.errors.append("Key rotation failed due to an internal error")
        result.failed_records += 1
        logger.error("Key rotation failed: %s", e)

    return result


def _get_integration_store_config() -> dict[str, Any] | None:
    """Get configuration for integration store re-encryption.

    The store decrypts settings when listing and encrypts them with the active
    key when saving, so each listed config is re-saved as it was read.
    """
    try:
        from aragora.storage.integration_models import EncryptionError
        from aragora.storage.integration_store import SENSITIVE_KEYS, get_integration_store
        from aragora.utils.async_utils import run_async

        store = get_integration_store()
        configs_by_id: dict[str, Any] = {}

        def list_configs() -> list[dict[str, Any]]:
            configs = _list_store_records(store, "integration_store", limit=_INTEGRATION_LIST_LIMIT)
            configs_by_id.clear()
            records: list[dict[str, Any]] = []
            for config in configs:
                record_id = f"{config.user_id or 'default'}:{config.type}"
                configs_by_id[record_id] = config
                settings = config.settings or {}
                records.append({**settings, _INTEGRATION_RECORD_ID_FIELD: record_id})
            return records

        def save_config(record_id: str, _record: dict[str, Any]) -> bool:
            try:
                run_async(store.save(configs_by_id[record_id]))
            except EncryptionError as e:
                # Counted per record by the caller; only the type is passed on, as for Gmail.
                raise RuntimeError(f"Saving settings failed: {type(e).__name__}") from e
            return True

        return {
            "list_fn": list_configs,
            "save_fn": save_config,
            # Every key the store encrypts, so a setting it failed to decrypt
            # fails the record instead of being encrypted a second time.
            "sensitive_fields": sorted(SENSITIVE_KEYS),
            "id_field": _INTEGRATION_RECORD_ID_FIELD,
            "force_resave": True,
        }
    except ImportError:
        return None


def _get_gmail_store_config() -> dict[str, Any] | None:
    """Get configuration for Gmail store re-encryption.

    The store decrypts tokens when listing and encrypts them with the active
    key when saving, so each listed user state is re-saved as it was read.
    """
    try:
        from aragora.storage.gmail_token_store import (
            ENCRYPTED_FIELDS,
            EncryptionError,
            get_gmail_token_store,
        )
        from aragora.utils.async_utils import run_async

        store = get_gmail_token_store()
        states_by_user: dict[str, Any] = {}

        def list_states() -> list[dict[str, Any]]:
            states = _list_store_records(store, "gmail_token_store")
            states_by_user.clear()
            records: list[dict[str, Any]] = []
            for state in states:
                states_by_user[state.user_id] = state
                tokens = {name: getattr(state, name) for name in ENCRYPTED_FIELDS}
                records.append({**tokens, "user_id": state.user_id})
            return records

        def save_state(user_id: str, record: dict[str, Any]) -> bool:
            if any(_is_undecrypted_token(record.get(name)) for name in ENCRYPTED_FIELDS):
                raise RuntimeError("Store returned a token it could not decrypt")
            try:
                run_async(store.save(states_by_user[user_id]))
            except EncryptionError as e:
                # Counted as a per-record failure by the caller; the store's message
                # can carry key or path detail, so only the type is passed on.
                raise RuntimeError(f"Saving tokens failed: {type(e).__name__}") from e
            return True

        return {
            "list_fn": list_states,
            "save_fn": save_state,
            "sensitive_fields": list(ENCRYPTED_FIELDS),
            "id_field": "user_id",
            "force_resave": True,
        }
    except ImportError:
        return None


def _get_sync_store_config() -> dict[str, Any] | None:
    """Get configuration for sync store re-encryption.

    The returned ``close_fn`` must be called once the store has been processed.
    """
    try:
        session = _SyncStoreSession()
        store = session.store
        connectors_by_id: dict[str, Any] = {}

        def list_connectors() -> list[dict[str, Any]]:
            connectors = session.run(store.list_connectors())
            connectors_by_id.clear()
            records: list[dict[str, Any]] = []
            for connector in connectors:
                connectors_by_id[connector.id] = connector
                records.append({**connector.config, "__sync_connector_id__": connector.id})
            return records

        def save_connector(connector_id: str, record: dict[str, Any]) -> bool:
            connector = connectors_by_id[connector_id]
            config = {key: value for key, value in record.items() if key != "__sync_connector_id__"}
            session.run(
                store.save_connector(
                    connector.id,
                    connector.connector_type,
                    connector.name,
                    config,
                )
            )
            return True

        return {
            "list_fn": list_connectors,
            "save_fn": save_connector,
            "close_fn": session.close,
            "sensitive_fields": [
                "api_key",
                "api_secret",
                "token",
                "password",
                "auth_token",
                "secret",
            ],
            "id_field": "__sync_connector_id__",
            "force_resave": True,
        }
    except ImportError:
        return None


__all__ = [
    "EncryptionMigrator",
    "MigrationResult",
    "KeyRotationResult",
    "StartupMigrationConfig",
    "get_migration_audit_provider",
    "register_migration_audit_provider",
    "is_field_encrypted",
    "needs_migration",
    "migrate_integration_store",
    "migrate_gmail_token_store",
    "migrate_sync_store",
    "run_startup_migration",
    "get_startup_migration_config",
    "rotate_encryption_key",
    "rotate_and_reencrypt_store",
]
