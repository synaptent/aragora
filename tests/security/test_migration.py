"""
Tests for encryption migration utilities.

Tests automatic detection, migration, and startup migration functionality.
"""

import ast
import asyncio
import logging
import sqlite3
import sys
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import aragora.security.migration as migration_module
import aragora.utils.async_utils as async_utils
from aragora.security.migration import (
    MigrationResult,
    EncryptionMigrator,
    register_migration_audit_provider,
    is_field_encrypted,
    needs_migration,
    migrate_integration_store,
    migrate_gmail_token_store,
    migrate_sync_store,
    StartupMigrationConfig,
    get_startup_migration_config,
    run_startup_migration,
    rotate_encryption_key,
)


@pytest.fixture(autouse=True)
def reset_migration_providers():
    """Keep security migration provider registration isolated per test."""
    register_migration_audit_provider(None)
    yield
    register_migration_audit_provider(None)


class _LoopAffineSyncStore:
    """SyncStore fake that, like a real database connection, only works on its creation loop."""

    def __init__(self, backend: "_FakeSyncBackend", kwargs: dict[str, Any]) -> None:
        self._backend = backend
        self.kwargs = kwargs
        self.loop: asyncio.AbstractEventLoop | None = None
        self.closed = False
        self.calls: list[tuple[str, asyncio.AbstractEventLoop]] = []

    def _enter(self, name: str) -> None:
        loop = asyncio.get_running_loop()
        self.calls.append((name, loop))
        if self.loop is None or self.closed:
            raise RuntimeError(f"{name} called on an uninitialized or closed store")
        if loop is not self.loop:
            raise RuntimeError(f"{name} ran on a different event loop than initialize()")

    @property
    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]

    @property
    def call_loops(self) -> set[asyncio.AbstractEventLoop]:
        return {loop for _, loop in self.calls}

    async def initialize(self) -> None:
        if self._backend.init_error is not None:
            raise self._backend.init_error
        self.loop = asyncio.get_running_loop()
        self.calls.append(("initialize", self.loop))

    async def list_connectors(self) -> list[SimpleNamespace]:
        self._enter("list_connectors")
        if self._backend.list_error is not None:
            raise self._backend.list_error
        return list(self._backend.connectors)

    async def save_connector(
        self,
        connector_id: str,
        connector_type: str,
        name: str,
        config: dict[str, Any],
    ) -> SimpleNamespace:
        self._enter("save_connector")
        delay = self._backend.save_delays.get(connector_id)
        if delay:
            await asyncio.sleep(delay)
        error = self._backend.save_errors.get(connector_id)
        if error is not None:
            raise error
        self._backend.saved.append((connector_id, connector_type, name, dict(config)))
        return SimpleNamespace(
            id=connector_id, connector_type=connector_type, name=name, config=config
        )

    async def close(self) -> None:
        if self.loop is not None:
            self._enter("close")
        self.closed = True


class _FakeSyncBackend:
    """Stand-in for aragora.storage.sync_store, including the process-wide get_sync_store()."""

    def __init__(self) -> None:
        self.connectors: list[SimpleNamespace] = []
        self.init_error: Exception | None = None
        self.list_error: Exception | None = None
        self.save_errors: dict[str, Exception] = {}
        self.save_delays: dict[str, float] = {}
        self.saved: list[tuple[str, str, str, dict[str, Any]]] = []
        self.stores: list[_LoopAffineSyncStore] = []
        self.process_store: _LoopAffineSyncStore | None = None
        self.get_sync_store_calls = 0

    def add_connector(self, connector_id: str, config: dict[str, Any]) -> None:
        self.connectors.append(
            SimpleNamespace(
                id=connector_id,
                connector_type="github",
                name=f"GitHub {connector_id}",
                config=dict(config),
            )
        )

    def create_store(self, *args: Any, **kwargs: Any) -> _LoopAffineSyncStore:
        store = _LoopAffineSyncStore(self, kwargs)
        self.stores.append(store)
        return store

    async def get_sync_store(self) -> _LoopAffineSyncStore:
        self.get_sync_store_calls += 1
        if self.process_store is None:
            store = self.create_store()
            await store.initialize()
            self.process_store = store
        return self.process_store

    @property
    def private_stores(self) -> list[_LoopAffineSyncStore]:
        return [store for store in self.stores if store is not self.process_store]

    def only_private_store(self) -> _LoopAffineSyncStore:
        assert self.get_sync_store_calls == 0
        assert self.process_store is None
        assert len(self.private_stores) == 1
        store = self.private_stores[0]
        assert store.kwargs == {"recover_jobs_on_init": False}
        assert store.closed is True
        assert len(store.call_loops) <= 1
        if store.loop is not None:
            assert store.call_loops == {store.loop}
            assert store.call_names[0] == "initialize"
            assert store.call_names[-1] == "close"
            assert store.loop.is_closed()
        return store


@pytest.fixture
def sync_backend(monkeypatch):
    """Loop-affine sync store module, with no shared pool loop registered."""
    backend = _FakeSyncBackend()
    module = ModuleType("aragora.storage.sync_store")
    module.SyncStore = backend.create_store
    module.get_sync_store = backend.get_sync_store
    monkeypatch.setitem(sys.modules, "aragora.storage.sync_store", module)
    monkeypatch.setattr(async_utils, "_pool_event_loop_provider", None)
    return backend


@pytest.fixture
def shared_pool_loop(sync_backend, monkeypatch):
    """A running loop registered as the shared pool loop, as in a Postgres server process."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, name="test-shared-pool-loop", daemon=True)
    thread.start()
    monkeypatch.setattr(async_utils, "_pool_event_loop_provider", lambda: loop)
    asyncio.run_coroutine_threadsafe(sync_backend.get_sync_store(), loop).result(timeout=5)
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


def _assert_used_shared_store(backend: _FakeSyncBackend, loop: asyncio.AbstractEventLoop) -> None:
    assert backend.private_stores == []
    store = backend.process_store
    assert store is not None
    assert store.loop is loop
    assert store.call_loops == {loop}
    assert store.closed is False
    assert "close" not in store.call_names


def _prepare_live_rotation(service: MagicMock) -> None:
    service._keys = {"default": MagicMock(version=1)}
    service._active_key_id = "default"
    service.rotate_key.return_value = MagicMock(key_id="default", version=2)


class TestMigrationResult:
    """Tests for MigrationResult dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        result = MigrationResult(store_name="test_store")

        assert result.store_name == "test_store"
        assert result.total_records == 0
        assert result.migrated_records == 0
        assert result.already_encrypted == 0
        assert result.failed_records == 0
        assert result.errors == []
        assert result.completed_at is None
        assert result.duration_seconds == 0.0

    def test_success_property_no_failures(self):
        """Test success is True when no failures."""
        result = MigrationResult(
            store_name="test",
            total_records=10,
            migrated_records=8,
            already_encrypted=2,
            failed_records=0,
        )
        assert result.success is True

    def test_success_property_with_failures(self):
        """Test success is False when there are failures."""
        result = MigrationResult(
            store_name="test",
            total_records=10,
            migrated_records=7,
            failed_records=3,
        )
        assert result.success is False

    def test_to_dict(self):
        """Test conversion to dictionary."""
        now = datetime.now(timezone.utc)
        result = MigrationResult(
            store_name="test_store",
            total_records=10,
            migrated_records=5,
            already_encrypted=3,
            failed_records=2,
            errors=["Error 1", "Error 2"],
            started_at=now,
            completed_at=now,
            duration_seconds=1.5,
        )

        data = result.to_dict()

        assert data["store_name"] == "test_store"
        assert data["total_records"] == 10
        assert data["migrated_records"] == 5
        assert data["already_encrypted"] == 3
        assert data["failed_records"] == 2
        assert data["errors"] == ["Error 1", "Error 2"]
        assert data["duration_seconds"] == 1.5
        assert data["success"] is False

    def test_to_dict_truncates_errors(self):
        """Test that to_dict truncates error list to 10 items."""
        result = MigrationResult(
            store_name="test",
            errors=[f"Error {i}" for i in range(20)],
        )

        data = result.to_dict()
        assert len(data["errors"]) == 10


class TestFieldEncryptionDetection:
    """Tests for is_field_encrypted and needs_migration."""

    def test_is_field_encrypted_dict_with_marker(self):
        """Test detection of encrypted dict field."""
        value = {"_encrypted": True, "ciphertext": "abc123", "nonce": "xyz"}
        assert is_field_encrypted(value) is True

    def test_is_field_encrypted_dict_without_marker(self):
        """Test detection of unencrypted dict field."""
        value = {"api_key": "secret123"}
        assert is_field_encrypted(value) is False

    def test_is_field_encrypted_string(self):
        """Test that string values are not encrypted."""
        assert is_field_encrypted("secret123") is False

    def test_is_field_encrypted_none(self):
        """Test that None values are not encrypted."""
        assert is_field_encrypted(None) is False

    def test_needs_migration_plaintext_fields(self):
        """Test detection of records needing migration."""
        record = {
            "id": "123",
            "name": "Test",
            "api_key": "secret_value",
        }
        sensitive_fields = ["api_key", "api_secret"]

        assert needs_migration(record, sensitive_fields) is True

    def test_needs_migration_already_encrypted(self):
        """Test that already encrypted records don't need migration."""
        record = {
            "id": "123",
            "name": "Test",
            "api_key": {"_encrypted": True, "ciphertext": "abc"},
        }
        sensitive_fields = ["api_key"]

        assert needs_migration(record, sensitive_fields) is False

    def test_needs_migration_no_sensitive_fields(self):
        """Test records without sensitive fields don't need migration."""
        record = {
            "id": "123",
            "name": "Test",
        }
        sensitive_fields = ["api_key", "api_secret"]

        assert needs_migration(record, sensitive_fields) is False

    def test_needs_migration_null_sensitive_field(self):
        """Test that null sensitive fields don't trigger migration."""
        record = {
            "id": "123",
            "api_key": None,
        }
        sensitive_fields = ["api_key"]

        assert needs_migration(record, sensitive_fields) is False


class TestEncryptionMigrator:
    """Tests for EncryptionMigrator class."""

    def test_init_defaults(self):
        """Test default initialization."""
        migrator = EncryptionMigrator()

        assert migrator._encryption_service is None
        assert migrator._batch_size == 100
        assert migrator._dry_run is False

    def test_init_custom_values(self):
        """Test custom initialization."""
        mock_service = MagicMock()
        migrator = EncryptionMigrator(
            encryption_service=mock_service,
            batch_size=50,
            dry_run=True,
        )

        assert migrator._encryption_service is mock_service
        assert migrator._batch_size == 50
        assert migrator._dry_run is True

    def test_get_encryption_service_lazy_load(self):
        """Test lazy loading of encryption service."""
        migrator = EncryptionMigrator()

        with patch("aragora.security.encryption.get_encryption_service") as mock_get:
            mock_service = MagicMock()
            mock_get.return_value = mock_service

            service = migrator._get_encryption_service()

            assert service is mock_service
            mock_get.assert_called_once()

            # Second call should use cached service
            service2 = migrator._get_encryption_service()
            assert service2 is mock_service
            mock_get.assert_called_once()  # Still only one call

    def test_migrate_record(self):
        """Test single record migration."""
        mock_service = MagicMock()
        mock_service.encrypt_fields.return_value = {
            "id": "123",
            "api_key": {"_encrypted": True, "ciphertext": "encrypted"},
        }

        migrator = EncryptionMigrator(encryption_service=mock_service)

        record = {"id": "123", "api_key": "secret"}
        result = migrator.migrate_record(record, ["api_key"], record_id="123")

        mock_service.encrypt_fields.assert_called_once_with(
            record, ["api_key"], associated_data="123"
        )
        assert result["api_key"]["_encrypted"] is True

    def test_migrate_store_success(self):
        """Test successful store migration."""
        mock_service = MagicMock()
        mock_service.encrypt_fields.return_value = {
            "id": "1",
            "api_key": {"_encrypted": True, "ciphertext": "enc"},
        }

        migrator = EncryptionMigrator(encryption_service=mock_service)

        records = [
            {"id": "1", "api_key": "secret1"},
            {"id": "2", "api_key": {"_encrypted": True, "ciphertext": "already"}},
            {"id": "3", "api_key": "secret3"},
        ]

        def list_fn():
            return records

        def save_fn(record_id, record):
            return True

        result = migrator.migrate_store(
            store_name="test_store",
            list_fn=list_fn,
            save_fn=save_fn,
            sensitive_fields=["api_key"],
            id_field="id",
        )

        assert result.store_name == "test_store"
        assert result.total_records == 3
        assert result.migrated_records == 2
        assert result.already_encrypted == 1
        assert result.failed_records == 0
        assert result.success is True

    def test_migrate_store_dry_run(self):
        """Test dry run mode doesn't save."""
        mock_service = MagicMock()
        migrator = EncryptionMigrator(encryption_service=mock_service, dry_run=True)

        records = [{"id": "1", "api_key": "secret"}]
        save_called = []

        def list_fn():
            return records

        def save_fn(record_id, record):
            save_called.append(record_id)
            return True

        result = migrator.migrate_store(
            store_name="test_store",
            list_fn=list_fn,
            save_fn=save_fn,
            sensitive_fields=["api_key"],
        )

        assert result.migrated_records == 1
        assert len(save_called) == 0  # Save should not be called
        mock_service.encrypt_fields.assert_not_called()

    def test_migrate_store_save_failure(self):
        """Test handling of save failures."""
        mock_service = MagicMock()
        mock_service.encrypt_fields.return_value = {"id": "1", "api_key": {"_encrypted": True}}

        migrator = EncryptionMigrator(encryption_service=mock_service)

        records = [{"id": "1", "api_key": "secret"}]

        def list_fn():
            return records

        def save_fn(record_id, record):
            return False  # Simulate save failure

        result = migrator.migrate_store(
            store_name="test_store",
            list_fn=list_fn,
            save_fn=save_fn,
            sensitive_fields=["api_key"],
        )

        assert result.failed_records == 1
        assert result.migrated_records == 0
        assert result.success is False
        assert len(result.errors) == 1

    def test_migrate_store_encryption_error(self):
        """Test handling of encryption errors."""
        mock_service = MagicMock()
        mock_service.encrypt_fields.side_effect = RuntimeError("Encryption failed")

        migrator = EncryptionMigrator(encryption_service=mock_service)

        records = [{"id": "1", "api_key": "secret"}]

        def list_fn():
            return records

        def save_fn(record_id, record):
            return True

        result = migrator.migrate_store(
            store_name="test_store",
            list_fn=list_fn,
            save_fn=save_fn,
            sensitive_fields=["api_key"],
        )

        assert result.failed_records == 1
        assert result.success is False


class TestStoreMigrations:
    """Tests for store-specific migration functions."""

    def test_migrate_integration_store_dry_run_uses_async_backend(self):
        """Dry-run should bridge the async integration store and count plaintext secrets."""
        mock_store = MagicMock()
        mock_store.list_all = AsyncMock(
            return_value=[
                MagicMock(
                    type="slack",
                    user_id="user-123",
                    settings={"api_key": "secret-value"},
                )
            ]
        )
        mock_store.save = AsyncMock(return_value=None)

        with patch(
            "aragora.storage.integration_store.get_integration_store",
            return_value=mock_store,
        ):
            result = migrate_integration_store(dry_run=True)

        assert result.store_name == "integration_store"
        assert result.total_records == 1
        assert result.migrated_records == 1
        assert result.failed_records == 0
        mock_store.list_all.assert_awaited_once()
        mock_store.save.assert_not_awaited()

    def test_migrate_integration_store_saves_async_backend_records(self):
        """Non-dry-run migration should await the async save path and treat None as success."""
        config = MagicMock(
            type="teams",
            user_id="user-456",
            settings={"refresh_token": "secret-token"},
        )
        mock_store = MagicMock()
        mock_store.list_all = AsyncMock(return_value=[config])
        mock_store.save = AsyncMock(return_value=None)

        with patch(
            "aragora.storage.integration_store.get_integration_store",
            return_value=mock_store,
        ):
            result = migrate_integration_store(dry_run=False)

        assert result.store_name == "integration_store"
        assert result.total_records == 1
        assert result.migrated_records == 1
        assert result.failed_records == 0
        mock_store.list_all.assert_awaited_once()
        mock_store.save.assert_awaited_once_with(config)

    def test_migrate_integration_store_import_error(self):
        """Test graceful handling of import error."""
        with patch(
            "aragora.storage.integration_store.get_integration_store",
            side_effect=ImportError("Not found"),
        ):
            result = migrate_integration_store()

            assert result.store_name == "integration_store"
            assert len(result.errors) > 0

    def test_migrate_gmail_token_store_import_error(self):
        """Test graceful handling of import error."""
        with patch(
            "aragora.storage.gmail_token_store.get_gmail_token_store",
            side_effect=ImportError("Not found"),
        ):
            result = migrate_gmail_token_store()

            assert result.store_name == "gmail_token_store"
            assert len(result.errors) > 0

    def test_migrate_sync_store_empty(self, sync_backend):
        """Test migration with empty sync store."""
        result = migrate_sync_store(dry_run=True)

        assert result.store_name == "sync_store"
        # Should complete successfully even with empty store
        assert result.failed_records == 0
        assert result.errors == []
        assert sync_backend.only_private_store().call_names == [
            "initialize",
            "list_connectors",
            "close",
        ]

    def test_unavailable_sync_store_preserves_best_effort_result(self, sync_backend):
        """An unavailable storage implementation preserves the best-effort result."""
        sync_backend.init_error = RuntimeError("unavailable")

        result = migrate_sync_store(dry_run=True)

        assert result.store_name == "sync_store"
        assert result.errors == ["Sync store not available"]
        assert result.success is True
        assert sync_backend.only_private_store().call_names == []

    def test_unimportable_sync_store_preserves_best_effort_result(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "aragora.storage.sync_store", None)

        result = migrate_sync_store(dry_run=False)

        assert result.errors == ["Sync store not available"]
        assert result.success is True


class TestMigrationAuditProvider:
    """Tests for injected key-rotation audit emission."""

    @pytest.fixture
    def encryption_service(self):
        service = MagicMock()
        service._keys = {}
        service._active_key_id = None
        return service

    def test_dry_run_emits_registered_audit_event(self, encryption_service):
        audit = MagicMock()
        register_migration_audit_provider(audit)

        with patch(
            "aragora.security.encryption.get_encryption_service",
            return_value=encryption_service,
        ):
            result = rotate_encryption_key(dry_run=True, stores=[])

        assert result.success is True
        audit.assert_called_once_with(
            event_type="key_rotation",
            actor_id="system",
            reason="dry_run_key_rotation",
        )

    def test_dry_run_missing_audit_provider_warns(self, encryption_service, caplog):
        with patch(
            "aragora.security.encryption.get_encryption_service",
            return_value=encryption_service,
        ):
            result = rotate_encryption_key(dry_run=True, stores=[])

        assert result.success is True
        assert "Migration audit provider not registered" in caplog.text

    def test_dry_run_audit_import_failure_is_logged(self, encryption_service, caplog):
        register_migration_audit_provider(
            MagicMock(side_effect=ImportError("audit backend unavailable"))
        )

        with caplog.at_level(logging.WARNING, logger="aragora.security.migration"):
            with patch(
                "aragora.security.encryption.get_encryption_service",
                return_value=encryption_service,
            ):
                result = rotate_encryption_key(dry_run=True, stores=[])

        assert result.success is True
        assert "dry-run key rotation event was not emitted" in caplog.text
        assert "audit backend unavailable" in caplog.text

    def test_live_audit_import_failure_remains_best_effort(self, encryption_service):
        old_key = MagicMock(version=1)
        new_key = MagicMock(key_id="default", version=2)
        encryption_service._keys = {"default": old_key}
        encryption_service._active_key_id = "default"
        encryption_service.rotate_key.return_value = new_key
        register_migration_audit_provider(MagicMock(side_effect=ImportError("unavailable")))

        with patch(
            "aragora.security.encryption.get_encryption_service",
            return_value=encryption_service,
        ):
            result = rotate_encryption_key(dry_run=False, stores=["unknown"])

        assert result.success is True
        assert result.old_key_version == 1
        assert result.new_key_version == 2
        assert result.errors == []

    def test_live_audit_import_failure_is_logged(self, encryption_service, caplog):
        encryption_service._keys = {"default": MagicMock(version=1)}
        encryption_service._active_key_id = "default"
        encryption_service.rotate_key.return_value = MagicMock(key_id="default", version=2)
        register_migration_audit_provider(
            MagicMock(side_effect=ImportError("audit backend unavailable"))
        )

        with caplog.at_level(logging.WARNING, logger="aragora.security.migration"):
            with patch(
                "aragora.security.encryption.get_encryption_service",
                return_value=encryption_service,
            ):
                result = rotate_encryption_key(dry_run=False, stores=["unknown"])

        assert result.success is True
        assert result.new_key_version == 2
        assert "key rotation event was not emitted" in caplog.text
        assert "audit backend unavailable" in caplog.text

    def test_live_missing_audit_provider_warns(self, encryption_service, caplog):
        encryption_service._keys = {"default": MagicMock(version=1)}
        encryption_service._active_key_id = "default"
        encryption_service.rotate_key.return_value = MagicMock(key_id="default", version=2)

        with caplog.at_level(logging.WARNING, logger="aragora.security.migration"):
            with patch(
                "aragora.security.encryption.get_encryption_service",
                return_value=encryption_service,
            ):
                result = rotate_encryption_key(dry_run=False, stores=["unknown"])

        assert result.success is True
        assert result.new_key_version == 2
        assert "Migration audit provider not registered" in caplog.text

    def test_missing_provider_warning_names_event_and_registration_path(
        self, encryption_service, caplog
    ):
        with caplog.at_level(logging.WARNING, logger="aragora.security.migration"):
            with patch(
                "aragora.security.encryption.get_encryption_service",
                return_value=encryption_service,
            ):
                rotate_encryption_key(dry_run=True, stores=[])

        warnings = [
            record
            for record in caplog.records
            if record.name == "aragora.security.migration" and record.levelno == logging.WARNING
        ]
        assert len(warnings) == 1
        message = warnings[0].getMessage()
        assert "'key_rotation'" in message
        assert "register_security_migration_adapters()" in message
        assert "register_migration_audit_provider()" in message

    def test_registered_provider_is_readable(self):
        provider = MagicMock()
        assert migration_module.get_migration_audit_provider() is None

        register_migration_audit_provider(provider)
        assert migration_module.get_migration_audit_provider() is provider

        register_migration_audit_provider(None)
        assert migration_module.get_migration_audit_provider() is None

    def _rotate_sync(self, encryption_service, **kwargs):
        _prepare_live_rotation(encryption_service)
        kwargs.setdefault("stores", ["sync"])
        with patch(
            "aragora.security.encryption.get_encryption_service",
            return_value=encryption_service,
        ):
            return rotate_encryption_key(dry_run=False, **kwargs)

    def test_live_sync_rotation_resolves_unregistered_storage_store(
        self, encryption_service, sync_backend
    ):
        sync_backend.add_connector("connector-1", {"api_key": "decrypted-secret"})

        result = self._rotate_sync(encryption_service)

        assert result.success is True
        assert result.stores_processed == 1
        assert result.records_reencrypted == 1
        assert sync_backend.saved == [
            ("connector-1", "github", "GitHub connector-1", {"api_key": "decrypted-secret"})
        ]
        assert sync_backend.only_private_store().call_names == [
            "initialize",
            "list_connectors",
            "save_connector",
            "close",
        ]

    def test_optional_store_absence_remains_best_effort(self, encryption_service, sync_backend):
        with (
            patch("aragora.security.migration._get_integration_store_config", return_value=None),
            patch("aragora.security.migration._get_gmail_store_config", return_value=None),
        ):
            result = self._rotate_sync(encryption_service, stores=None)

        assert result.success is True
        assert result.stores_processed == 1
        assert result.failed_records == 0
        assert result.errors == []
        assert sync_backend.only_private_store().call_names == [
            "initialize",
            "list_connectors",
            "close",
        ]

    def test_live_sync_rotation_fails_closed_when_storage_resolution_fails(
        self, encryption_service, sync_backend
    ):
        sync_backend.init_error = RuntimeError("sync store unavailable")

        result = self._rotate_sync(encryption_service)

        assert result.success is False
        assert result.stores_processed == 0
        assert result.failed_records == 1
        assert result.errors == ["Store sync re-encryption failed"]
        assert sync_backend.only_private_store().call_names == []

    def test_live_sync_rotation_fails_closed_when_storage_is_unimportable(
        self, encryption_service, monkeypatch
    ):
        monkeypatch.setitem(sys.modules, "aragora.storage.sync_store", None)

        result = self._rotate_sync(encryption_service)

        assert result.success is False
        assert result.failed_records == 1
        assert result.errors == ["Store sync re-encryption failed"]

    def test_live_sync_rotation_fails_closed_when_connector_list_fails(
        self, encryption_service, sync_backend
    ):
        sync_backend.list_error = RuntimeError("credential=secret-value")

        result = self._rotate_sync(encryption_service)

        assert result.success is False
        assert result.stores_processed == 1
        assert result.failed_records >= 1
        assert result.errors == ["Re-encryption failed due to an internal error"]
        assert "secret-value" not in " ".join(result.errors)
        assert sync_backend.only_private_store().call_names == [
            "initialize",
            "list_connectors",
            "close",
        ]

    def test_live_sync_rotation_fails_closed_when_connector_save_fails(
        self, encryption_service, sync_backend
    ):
        sync_backend.add_connector("connector-1", {"api_key": "decrypted-secret"})
        sync_backend.save_errors["connector-1"] = RuntimeError("write failed")

        result = self._rotate_sync(encryption_service)

        assert result.success is False
        assert result.stores_processed == 1
        assert result.failed_records == 1
        assert result.errors == ["Error re-encrypting record: connector-1"]
        assert sync_backend.only_private_store().call_names.count("save_connector") == 1

    def test_live_sync_rotation_counts_each_failed_record_on_one_loop(
        self, encryption_service, sync_backend
    ):
        for connector_id in ("connector-1", "connector-2", "connector-3"):
            sync_backend.add_connector(connector_id, {"token": f"{connector_id}-secret"})
        sync_backend.save_errors["connector-2"] = RuntimeError("write failed")

        result = self._rotate_sync(encryption_service)

        assert result.success is False
        assert result.records_reencrypted == 2
        assert result.failed_records == 1
        assert result.errors == ["Error re-encrypting record: connector-2"]
        assert [saved[0] for saved in sync_backend.saved] == ["connector-1", "connector-3"]
        assert sync_backend.only_private_store().call_names.count("save_connector") == 3

    def test_live_sync_rotation_save_timeout_fails_closed_and_closes_store(
        self, encryption_service, sync_backend, monkeypatch
    ):
        monkeypatch.setattr(migration_module, "_SYNC_STORE_CALL_TIMEOUT", 1.0)
        sync_backend.add_connector("connector-1", {"api_key": "slow-secret"})
        sync_backend.add_connector("connector-2", {"api_key": "fast-secret"})
        sync_backend.save_delays["connector-1"] = 60.0

        result = self._rotate_sync(encryption_service)

        assert result.success is False
        assert result.failed_records == 1
        assert result.errors == ["Error re-encrypting record: connector-1"]
        assert [saved[0] for saved in sync_backend.saved] == ["connector-2"]
        sync_backend.only_private_store()

    def test_live_sync_rotation_keeps_shared_pool_store_on_its_loop(
        self, encryption_service, sync_backend, shared_pool_loop
    ):
        sync_backend.add_connector("connector-1", {"api_key": "decrypted-secret"})

        result = self._rotate_sync(encryption_service)

        assert result.success is True
        assert result.records_reencrypted == 1
        assert [saved[0] for saved in sync_backend.saved] == ["connector-1"]
        _assert_used_shared_store(sync_backend, shared_pool_loop)


class TestMigrationAuditComposition:
    """The ops adapter routes key-rotation events to the unified audit log."""

    @pytest.fixture
    def encryption_service(self):
        service = MagicMock()
        service._keys = {}
        service._active_key_id = None
        return service

    def test_adapter_emits_unified_dry_run_event(self, encryption_service):
        from aragora.ops.security_edge_adapters import register_security_migration_adapters

        register_security_migration_adapters()

        with (
            patch("aragora.audit.unified.audit_security") as audit_security,
            patch(
                "aragora.security.encryption.get_encryption_service",
                return_value=encryption_service,
            ),
        ):
            result = rotate_encryption_key(dry_run=True, stores=[])

        assert result.success is True
        audit_security.assert_called_once_with(
            event_type="key_rotation",
            actor_id="system",
            reason="dry_run_key_rotation",
        )

    def test_adapter_emits_unified_live_event(self, encryption_service):
        from aragora.ops.security_edge_adapters import register_security_migration_adapters

        encryption_service._keys = {"default": MagicMock(version=1)}
        encryption_service._active_key_id = "default"
        encryption_service.rotate_key.return_value = MagicMock(key_id="default", version=2)
        register_security_migration_adapters()

        with (
            patch("aragora.audit.unified.audit_security") as audit_security,
            patch(
                "aragora.security.encryption.get_encryption_service",
                return_value=encryption_service,
            ),
        ):
            result = rotate_encryption_key(dry_run=False, stores=["unknown"])

        assert result.success is True
        audit_security.assert_called_once_with(
            event_type="key_rotation",
            actor_id="system",
            old_version=1,
            new_version=2,
        )

    def test_migration_module_does_not_import_audit_or_ops(self):
        source = Path(migration_module.__file__).read_text(encoding="utf-8")
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        assert {
            name for name in imported if name.startswith(("aragora.audit", "aragora.ops"))
        } == set()

    def test_migration_module_does_not_import_connectors_or_server(self):
        source = Path(migration_module.__file__).read_text(encoding="utf-8")
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)

        assert {
            name
            for name in imported
            if name.startswith(("aragora.connectors", "aragora.server", "aragora.storage.pool"))
        } == set()


class TestDirectSyncMigration:
    """Direct sync migration resolves and awaits the storage implementation."""

    def test_migrate_sync_store_resaves_plaintext_connector(self, sync_backend):
        sync_backend.add_connector("connector-1", {"api_key": "plaintext-secret"})

        result = migrate_sync_store(dry_run=False)

        assert result.success is True
        assert result.total_records == 1
        assert result.migrated_records == 1
        assert sync_backend.saved == [
            ("connector-1", "github", "GitHub connector-1", {"api_key": "plaintext-secret"})
        ]
        assert sync_backend.only_private_store().call_names == [
            "initialize",
            "list_connectors",
            "save_connector",
            "close",
        ]

    def test_migrate_sync_store_dry_run_counts_without_saving(self, sync_backend):
        sync_backend.add_connector("connector-1", {"api_key": "plaintext-secret"})

        result = migrate_sync_store(dry_run=True)

        assert result.success is True
        assert result.migrated_records == 1
        assert sync_backend.saved == []
        assert "save_connector" not in sync_backend.only_private_store().call_names

    def test_migrate_sync_store_counts_failed_record_and_continues(self, sync_backend):
        sync_backend.add_connector("connector-1", {"api_key": "first-secret"})
        sync_backend.add_connector("connector-2", {"api_key": "second-secret"})
        sync_backend.save_errors["connector-1"] = RuntimeError("write failed")

        result = migrate_sync_store(dry_run=False)

        assert result.success is False
        assert result.total_records == 2
        assert result.migrated_records == 1
        assert result.failed_records == 1
        assert result.errors == ["Error migrating record: connector-1"]
        assert [saved[0] for saved in sync_backend.saved] == ["connector-2"]
        assert sync_backend.only_private_store().call_names.count("save_connector") == 2

    def test_migrate_sync_store_ignores_process_store_bound_to_another_loop(self, sync_backend):
        sync_backend.add_connector("connector-1", {"api_key": "plaintext-secret"})
        process_store = asyncio.run(sync_backend.get_sync_store())
        sync_backend.get_sync_store_calls = 0

        result = migrate_sync_store(dry_run=False)

        assert result.success is True
        assert result.migrated_records == 1
        assert process_store.call_names == ["initialize"]
        assert sync_backend.get_sync_store_calls == 0
        private_stores = sync_backend.private_stores
        assert len(private_stores) == 1
        assert private_stores[0].closed is True
        assert len(private_stores[0].call_loops) == 1

    def test_migrate_sync_store_called_inside_a_running_loop(self, sync_backend):
        sync_backend.add_connector("connector-1", {"api_key": "plaintext-secret"})

        async def call_from_async_handler():
            return migrate_sync_store(dry_run=False), asyncio.get_running_loop()

        result, caller_loop = asyncio.run(call_from_async_handler())

        assert result.success is True
        assert result.migrated_records == 1
        assert sync_backend.only_private_store().loop is not caller_loop

    def test_migrate_sync_store_real_sqlite_leaves_live_jobs_running(self, tmp_path, monkeypatch):
        from aragora.storage.sync_store import SyncStore

        db_path = tmp_path / "connectors.db"
        monkeypatch.setenv("ARAGORA_SYNC_DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setattr(async_utils, "_pool_event_loop_provider", None)

        async def seed_live_owner() -> None:
            owner = SyncStore(use_encryption=False)
            await owner.initialize()
            await owner.save_connector("connector-1", "github", "GitHub", {"api_key": "plain"})
            await owner.record_sync_start("connector-1")
            await owner.close()

        asyncio.run(seed_live_owner())

        result = migrate_sync_store(dry_run=True)

        assert result.errors == []
        assert result.total_records == 1
        assert result.migrated_records == 1
        with closing(sqlite3.connect(db_path)) as conn:
            statuses = [row[0] for row in conn.execute("SELECT status FROM sync_jobs")]
        assert statuses == ["running"]

    def test_migrate_sync_store_keeps_shared_pool_store_on_its_loop(
        self, sync_backend, shared_pool_loop
    ):
        sync_backend.add_connector("connector-1", {"api_key": "plaintext-secret"})

        result = migrate_sync_store(dry_run=False)

        assert result.success is True
        assert result.migrated_records == 1
        assert [saved[0] for saved in sync_backend.saved] == ["connector-1"]
        _assert_used_shared_store(sync_backend, shared_pool_loop)

    def test_migrate_sync_store_closes_private_loop_when_thread_start_fails(
        self, sync_backend, monkeypatch
    ):
        sync_backend.add_connector("connector-1", {"api_key": "plaintext-secret"})
        loops: list[asyncio.AbstractEventLoop] = []

        class _UnstartableThread(threading.Thread):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                loops.append(kwargs["args"][0])

            def start(self) -> None:
                raise RuntimeError("can't start new thread")

        monkeypatch.setattr(
            migration_module, "threading", SimpleNamespace(Thread=_UnstartableThread)
        )

        result = migrate_sync_store(dry_run=False)

        assert result.errors == ["Sync store not available"]
        assert sync_backend.stores == []
        assert len(loops) == 1
        assert loops[0].is_closed()

    def test_closed_shared_pool_session_refuses_new_calls(self, sync_backend, shared_pool_loop):
        session = migration_module._SyncStoreSession()
        session.close()

        with pytest.raises(RuntimeError, match="session is closed"):
            session.run(session.store.list_connectors())
        _assert_used_shared_store(sync_backend, shared_pool_loop)


class TestStartupMigrationConfig:
    """Tests for startup migration configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = StartupMigrationConfig()

        assert config.enabled is False
        assert config.dry_run is False
        assert config.stores == ["integration", "gmail", "sync"]
        assert config.fail_on_error is False

    def test_get_config_from_env_enabled(self):
        """Test config loading with migration enabled."""
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_MIGRATE_ON_STARTUP": "true",
                "ARAGORA_MIGRATION_DRY_RUN": "1",
                "ARAGORA_MIGRATION_STORES": "integration,sync",
                "ARAGORA_MIGRATION_FAIL_ON_ERROR": "yes",
            },
        ):
            config = get_startup_migration_config()

            assert config.enabled is True
            assert config.dry_run is True
            assert config.stores == ["integration", "sync"]
            assert config.fail_on_error is True

    def test_get_config_from_env_disabled(self):
        """Test config loading with migration disabled."""
        with patch.dict(
            "os.environ",
            {
                "ARAGORA_MIGRATE_ON_STARTUP": "false",
            },
            clear=True,
        ):
            config = get_startup_migration_config()

            assert config.enabled is False


class TestRunStartupMigration:
    """Tests for run_startup_migration function."""

    def test_disabled_returns_empty(self):
        """Test that disabled migration returns empty list."""
        config = StartupMigrationConfig(enabled=False)

        results = run_startup_migration(config)

        assert results == []

    def test_enabled_runs_migrations(self):
        """Test that enabled migration runs store migrations."""
        config = StartupMigrationConfig(
            enabled=True,
            dry_run=True,
            stores=["integration"],
        )

        mock_result = MigrationResult(store_name="integration_store", migrated_records=5)

        with patch(
            "aragora.security.migration.migrate_integration_store", return_value=mock_result
        ) as mock_migrate:
            results = run_startup_migration(config)

            assert len(results) == 1
            assert results[0].store_name == "integration_store"
            mock_migrate.assert_called_once_with(dry_run=True)

    def test_unknown_store_skipped(self):
        """Test that unknown store names are skipped."""
        config = StartupMigrationConfig(
            enabled=True,
            stores=["unknown_store"],
        )

        results = run_startup_migration(config)

        assert len(results) == 0

    def test_fail_on_error_raises(self):
        """Test that fail_on_error causes exception on failure."""
        config = StartupMigrationConfig(
            enabled=True,
            stores=["integration"],
            fail_on_error=True,
        )

        mock_result = MigrationResult(
            store_name="integration_store",
            failed_records=5,
            errors=["Something went wrong"],
        )

        with patch(
            "aragora.security.migration.migrate_integration_store", return_value=mock_result
        ):
            with pytest.raises(RuntimeError) as exc_info:
                run_startup_migration(config)

            assert "Migration failed for integration" in str(exc_info.value)

    def test_fail_on_error_false_continues(self):
        """Test that fail_on_error=False continues after failure."""
        config = StartupMigrationConfig(
            enabled=True,
            stores=["integration", "sync"],
            fail_on_error=False,
        )

        failed_result = MigrationResult(
            store_name="integration_store",
            failed_records=5,
        )
        success_result = MigrationResult(
            store_name="sync_store",
            migrated_records=3,
        )

        with patch(
            "aragora.security.migration.migrate_integration_store", return_value=failed_result
        ):
            with patch(
                "aragora.security.migration.migrate_sync_store", return_value=success_result
            ):
                results = run_startup_migration(config)

                assert len(results) == 2
                assert results[0].success is False
                assert results[1].success is True

    def test_migration_exception_with_fail_on_error(self):
        """Test exception handling with fail_on_error=True."""
        config = StartupMigrationConfig(
            enabled=True,
            stores=["integration"],
            fail_on_error=True,
        )

        with patch(
            "aragora.security.migration.migrate_integration_store",
            side_effect=RuntimeError("DB error"),
        ):
            with pytest.raises(Exception) as exc_info:
                run_startup_migration(config)

            assert "DB error" in str(exc_info.value)

    def test_migration_exception_without_fail_on_error(self):
        """Test exception handling with fail_on_error=False."""
        config = StartupMigrationConfig(
            enabled=True,
            stores=["integration", "sync"],
            fail_on_error=False,
        )

        success_result = MigrationResult(store_name="sync_store")

        with patch(
            "aragora.security.migration.migrate_integration_store",
            side_effect=RuntimeError("DB error"),
        ):
            with patch(
                "aragora.security.migration.migrate_sync_store", return_value=success_result
            ):
                results = run_startup_migration(config)

                # Should have one result for sync store
                assert len(results) == 1
                assert results[0].store_name == "sync_store"

    def test_all_stores_run(self):
        """Test that all configured stores are migrated."""
        config = StartupMigrationConfig(
            enabled=True,
            stores=["integration", "gmail", "sync"],
        )

        results_map = {
            "integration": MigrationResult(store_name="integration_store"),
            "gmail": MigrationResult(store_name="gmail_token_store"),
            "sync": MigrationResult(store_name="sync_store"),
        }

        with patch(
            "aragora.security.migration.migrate_integration_store",
            return_value=results_map["integration"],
        ):
            with patch(
                "aragora.security.migration.migrate_gmail_token_store",
                return_value=results_map["gmail"],
            ):
                with patch(
                    "aragora.security.migration.migrate_sync_store",
                    return_value=results_map["sync"],
                ):
                    results = run_startup_migration(config)

                    assert len(results) == 3
                    store_names = {r.store_name for r in results}
                    assert store_names == {"integration_store", "gmail_token_store", "sync_store"}
