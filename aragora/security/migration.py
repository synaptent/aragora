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

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, cast
from collections.abc import Callable

logger = logging.getLogger(__name__)

MigrationAuditProvider = Callable[..., Any]

_migration_audit_provider: MigrationAuditProvider | None = None


def register_migration_audit_provider(provider: MigrationAuditProvider | None) -> None:
    """Register the higher-layer security audit provider."""
    global _migration_audit_provider
    _migration_audit_provider = provider


def _audit_security(**kwargs: Any) -> Any:
    """Emit a security audit event through the registered provider."""
    if _migration_audit_provider is None:
        logger.warning("Migration audit provider not registered; security event was not emitted")
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
            result.failed_records = result.total_records
            logger.error("Migration failed for %s: %s", store_name, e)

        return result


# Store-specific migration functions


def migrate_integration_store(dry_run: bool = False) -> MigrationResult:
    """Migrate integration store secrets."""
    try:
        from aragora.storage.integration_store import get_integration_store
        from aragora.utils.async_utils import run_async

        store = get_integration_store()
        result = MigrationResult(store_name="integration_store")

        sensitive_fields = [
            "api_key",
            "api_secret",
            "access_token",
            "refresh_token",
            "password",
            "secret",
            "credentials",
            "token",
        ]

        configs = list(run_async(store.list_all()))
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
            except (KeyError, ValueError, TypeError, RuntimeError, OSError) as e:
                result.failed_records += 1
                result.errors.append(f"Error migrating record: {record_id}")
                logger.warning("Failed to migrate record %s: %s", record_id, e)

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
    except ImportError as e:
        logger.warning("Integration store not available: %s", e)
        return MigrationResult(
            store_name="integration_store", errors=["Integration store not available"]
        )


def migrate_gmail_token_store(dry_run: bool = False) -> MigrationResult:
    """Migrate Gmail token store secrets."""
    try:
        from aragora.storage.gmail_token_store import get_gmail_token_store

        store = get_gmail_token_store()
        migrator = EncryptionMigrator(dry_run=dry_run)

        sensitive_fields = ["access_token", "refresh_token"]

        def list_all():
            # GmailTokenStore may not have list_all, get states instead
            if hasattr(store, "list_all"):
                return list(store.list_all())
            return []

        def save(user_id, record):
            return store.save_state(user_id, record)

        return migrator.migrate_store(
            store_name="gmail_token_store",
            list_fn=list_all,
            save_fn=save,
            sensitive_fields=sensitive_fields,
            id_field="user_id",
        )
    except ImportError as e:
        logger.warning("Gmail token store not available: %s", e)
        return MigrationResult(
            store_name="gmail_token_store", errors=["Gmail token store not available"]
        )


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

    try:
        from aragora.storage.sync_store import get_sync_store
        from aragora.utils.async_utils import run_async

        store = run_async(get_sync_store())
        connectors = run_async(store.list_connectors())
        result.total_records = len(connectors)

        for connector in connectors:
            try:
                if not needs_migration(connector.config, sensitive_fields):
                    result.already_encrypted += 1
                    continue

                if not dry_run:
                    run_async(
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

    if dry_run:
        logger.info(
            "[DRY RUN] Would rotate key %s from v%s to v%s",
            old_key_id,
            old_version,
            old_version + 1,
        )
        # Audit log would go here
        _audit_security(
            event_type="key_rotation",
            actor_id="system",
            reason="dry_run_key_rotation",
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
        except ImportError:
            pass

        # Re-encrypt stores
        stores_to_process = stores or ["integration", "gmail", "sync"]
        store_configs = {
            "integration": _get_integration_store_config,
            "gmail": _get_gmail_store_config,
            "sync": _get_sync_store_config,
        }

        for store_name in stores_to_process:
            config_fn = store_configs.get(store_name)
            if not config_fn:
                logger.warning("Unknown store for key rotation: %s", store_name)
                continue
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

            except (ImportError, RuntimeError, ValueError, TypeError, OSError) as e:
                result.errors.append(f"Store {store_name} re-encryption failed")
                if store_name == "sync":
                    result.failed_records += 1
                logger.error("Key rotation failed for store %s: %s", store_name, e)

        result.completed_at = datetime.now(timezone.utc)
        result.duration_seconds = (result.completed_at - result.started_at).total_seconds()

        logger.info(
            "Key rotation complete: %s stores, %s records re-encrypted, %s failures",
            result.stores_processed,
            result.records_reencrypted,
            result.failed_records,
        )

    except (RuntimeError, ValueError, TypeError, OSError, ImportError, AttributeError) as e:
        result.errors.append("Key rotation failed due to an internal error")
        logger.error("Key rotation failed: %s", e)

    return result


def _get_integration_store_config() -> dict[str, Any] | None:
    """Get configuration for integration store re-encryption."""
    try:
        from aragora.storage.integration_store import get_integration_store

        store = get_integration_store()

        return {
            "list_fn": lambda: list(cast(Any, store).list_all()),
            "save_fn": lambda id, record: cast(Any, store).save(record),
            "sensitive_fields": [
                "api_key",
                "api_secret",
                "access_token",
                "refresh_token",
                "password",
                "secret",
                "credentials",
                "token",
            ],
            "id_field": "integration_id",
        }
    except ImportError:
        return None


def _get_gmail_store_config() -> dict[str, Any] | None:
    """Get configuration for Gmail store re-encryption."""
    try:
        from aragora.storage.gmail_token_store import get_gmail_token_store

        store = get_gmail_token_store()

        return {
            "list_fn": lambda: list(cast(Any, store).list_all())
            if hasattr(store, "list_all")
            else [],
            "save_fn": lambda id, record: cast(Any, store).save_state(id, record),
            "sensitive_fields": ["access_token", "refresh_token"],
            "id_field": "user_id",
        }
    except ImportError:
        return None


def _get_sync_store_config() -> dict[str, Any] | None:
    """Get configuration for sync store re-encryption."""
    try:
        from aragora.storage.sync_store import get_sync_store
        from aragora.utils.async_utils import run_async

        store = run_async(get_sync_store())
        connectors_by_id: dict[str, Any] = {}

        def list_connectors() -> list[dict[str, Any]]:
            connectors = run_async(store.list_connectors())
            connectors_by_id.clear()
            records: list[dict[str, Any]] = []
            for connector in connectors:
                connectors_by_id[connector.id] = connector
                records.append({**connector.config, "__sync_connector_id__": connector.id})
            return records

        def save_connector(connector_id: str, record: dict[str, Any]) -> bool:
            connector = connectors_by_id[connector_id]
            config = {key: value for key, value in record.items() if key != "__sync_connector_id__"}
            run_async(
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
