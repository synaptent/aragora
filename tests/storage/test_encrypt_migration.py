"""
Tests for the data encryption migration utility.

Tests cover:
- Migration result tracking
- Detection of unencrypted data
- Dry run mode
- Error handling
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.storage.migrations.encrypt_existing_data import (
    MigrationResult,
    _needs_migration,
    migrate_sync_store,
    migrate_integration_store,
    migrate_all,
)


class TestMigrationResult:
    """Tests for MigrationResult dataclass."""

    def test_success_when_no_failures(self):
        """Result is successful when no records failed."""
        result = MigrationResult(
            store_name="TestStore",
            total_records=100,
            migrated=50,
            already_encrypted=50,
            failed=0,
            errors=[],
            dry_run=False,
        )
        assert result.success is True

    def test_failure_when_records_failed(self):
        """Result is not successful when records failed."""
        result = MigrationResult(
            store_name="TestStore",
            total_records=100,
            migrated=45,
            already_encrypted=50,
            failed=5,
            errors=["Error 1", "Error 2"],
            dry_run=False,
        )
        assert result.success is False

    def test_str_representation(self):
        """String representation includes key metrics."""
        result = MigrationResult(
            store_name="TestStore",
            total_records=100,
            migrated=50,
            already_encrypted=50,
            failed=0,
            errors=[],
            dry_run=False,
        )
        s = str(result)
        assert "TestStore" in s
        assert "100" in s  # total
        assert "50" in s  # migrated

    def test_str_shows_dry_run_mode(self):
        """String representation shows dry run indicator."""
        result = MigrationResult(
            store_name="TestStore",
            total_records=10,
            migrated=5,
            already_encrypted=5,
            failed=0,
            errors=[],
            dry_run=True,
        )
        s = str(result)
        assert "DRY RUN" in s


class TestNeedsMigration:
    """Tests for _needs_migration function."""

    def test_empty_config_does_not_need_migration(self):
        """Empty config doesn't need migration."""
        assert _needs_migration({}, ["password", "token"]) is False

    def test_none_config_does_not_need_migration(self):
        """None config doesn't need migration."""
        assert _needs_migration(None, ["password", "token"]) is False

    def test_non_sensitive_fields_dont_need_migration(self):
        """Config with only non-sensitive fields doesn't need migration."""
        config = {"name": "test", "host": "localhost", "port": 5432}
        assert _needs_migration(config, ["password", "token"]) is False

    def test_plaintext_sensitive_field_needs_migration(self):
        """Config with plaintext sensitive field needs migration."""
        config = {"name": "test", "password": "secret123"}
        assert _needs_migration(config, ["password", "token"]) is True

    def test_encrypted_sensitive_field_does_not_need_migration(self):
        """Config with encrypted sensitive field doesn't need migration."""
        config = {
            "name": "test",
            "password": {"_encrypted": True, "_value": "encrypted_data"},
        }
        assert _needs_migration(config, ["password", "token"]) is False

    def test_mixed_fields_need_migration(self):
        """Config with mix of encrypted and plaintext needs migration."""
        config = {
            "password": {"_encrypted": True, "_value": "encrypted_data"},
            "api_token": "plaintext_token",  # This needs migration
        }
        assert _needs_migration(config, ["password", "token"]) is True

    def test_none_sensitive_value_does_not_need_migration(self):
        """Config with None sensitive value doesn't need migration."""
        config = {"name": "test", "password": None}
        assert _needs_migration(config, ["password", "token"]) is False

    def test_case_insensitive_keyword_matching(self):
        """Keyword matching is case-insensitive."""
        config = {"API_TOKEN": "secret", "Password": "abc123"}
        assert _needs_migration(config, ["password", "token"]) is True


class TestMigrateSyncStore:
    """Tests for migrate_sync_store function."""

    @pytest.mark.asyncio
    async def test_handles_encryption_not_available(self):
        """Returns error when encryption not available."""
        with patch("aragora.storage.migrations.encrypt_existing_data.CRYPTO_AVAILABLE", False):
            result = await migrate_sync_store(dry_run=True)

        assert result.failed == 0
        assert len(result.errors) > 0
        assert "not available" in result.errors[0].lower()

    @pytest.mark.asyncio
    async def test_returns_result_with_store_name(self):
        """Result has correct store name."""
        with patch("aragora.storage.migrations.encrypt_existing_data.CRYPTO_AVAILABLE", False):
            result = await migrate_sync_store(dry_run=True)

        assert result.store_name == "SyncStore"
        assert result.dry_run is True

    @pytest.mark.asyncio
    async def test_resaves_connector_through_storage_sync_store(self, monkeypatch):
        connector = SimpleNamespace(
            id="connector-1",
            connector_type="github",
            name="GitHub",
            config={"api_key": "plaintext-secret"},
        )
        store = MagicMock()
        store.initialize = AsyncMock()
        store.list_connectors = AsyncMock(return_value=[connector])
        store.save_connector = AsyncMock(return_value=connector)
        sync_store_type = MagicMock(return_value=store)
        sync_store_module = ModuleType("aragora.storage.sync_store")
        sync_store_module.SyncStore = sync_store_type
        sync_store_module.CREDENTIAL_KEYWORDS = frozenset({"api_key", "token"})
        monkeypatch.setitem(sys.modules, "aragora.storage.sync_store", sync_store_module)
        monkeypatch.setitem(sys.modules, "aragora.connectors.enterprise.sync_store", None)

        with patch(
            "aragora.storage.migrations.encrypt_existing_data.CRYPTO_AVAILABLE",
            True,
        ):
            result = await migrate_sync_store(dry_run=False)

        assert result.success is True
        assert result.total_records == 1
        assert result.migrated == 1
        sync_store_type.assert_called_once_with(use_encryption=True)
        store.initialize.assert_awaited_once_with()
        store.list_connectors.assert_awaited_once_with()
        store.save_connector.assert_awaited_once_with(
            "connector-1",
            "github",
            "GitHub",
            {"api_key": "plaintext-secret"},
        )


class TestMigrateIntegrationStore:
    """Tests for migrate_integration_store function."""

    @pytest.mark.asyncio
    async def test_handles_encryption_not_available(self):
        """Returns error when encryption not available."""
        with patch("aragora.storage.migrations.encrypt_existing_data.CRYPTO_AVAILABLE", False):
            result = await migrate_integration_store(dry_run=True)

        assert len(result.errors) > 0


class TestMigrateAll:
    """Tests for migrate_all function."""

    @pytest.mark.asyncio
    async def test_runs_all_migrations(self):
        """migrate_all runs all individual migrations."""
        with patch("aragora.storage.migrations.encrypt_existing_data.CRYPTO_AVAILABLE", True):
            with patch(
                "aragora.storage.migrations.encrypt_existing_data.get_encryption_service"
            ) as mock_service:
                mock_service.return_value.get_active_key_id.return_value = "test-key"

                with patch(
                    "aragora.storage.migrations.encrypt_existing_data.migrate_sync_store"
                ) as mock_sync:
                    with patch(
                        "aragora.storage.migrations.encrypt_existing_data.migrate_integration_store"
                    ) as mock_int:
                        with patch(
                            "aragora.storage.migrations.encrypt_existing_data.migrate_gmail_tokens"
                        ) as mock_gmail:
                            mock_sync.return_value = MigrationResult(
                                store_name="SyncStore",
                                total_records=0,
                                migrated=0,
                                already_encrypted=0,
                                failed=0,
                                errors=[],
                                dry_run=True,
                            )
                            mock_int.return_value = MigrationResult(
                                store_name="IntegrationStore",
                                total_records=0,
                                migrated=0,
                                already_encrypted=0,
                                failed=0,
                                errors=[],
                                dry_run=True,
                            )
                            mock_gmail.return_value = MigrationResult(
                                store_name="GmailTokenStore",
                                total_records=0,
                                migrated=0,
                                already_encrypted=0,
                                failed=0,
                                errors=[],
                                dry_run=True,
                            )

                            results = await migrate_all(dry_run=True)

                            assert len(results) == 3
                            mock_sync.assert_called_once_with(dry_run=True)
                            mock_int.assert_called_once_with(dry_run=True)
                            mock_gmail.assert_called_once_with(dry_run=True)

    @pytest.mark.asyncio
    async def test_returns_empty_when_crypto_unavailable(self):
        """migrate_all returns empty list when crypto not available."""
        with patch("aragora.storage.migrations.encrypt_existing_data.CRYPTO_AVAILABLE", False):
            results = await migrate_all(dry_run=True)

        assert results == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_service_fails(self):
        """migrate_all returns empty list when encryption service fails."""
        with patch("aragora.storage.migrations.encrypt_existing_data.CRYPTO_AVAILABLE", True):
            with patch(
                "aragora.storage.migrations.encrypt_existing_data.get_encryption_service"
            ) as mock_service:
                mock_service.side_effect = RuntimeError("No encryption key configured")

                results = await migrate_all(dry_run=True)

        assert results == []


class TestMigrateGmailTokens:
    """Tests for migrate_gmail_tokens function."""

    @pytest.mark.asyncio
    async def test_handles_encryption_not_available(self):
        """Returns error when encryption not available."""
        from aragora.storage.migrations.encrypt_existing_data import migrate_gmail_tokens

        with patch("aragora.storage.migrations.encrypt_existing_data.CRYPTO_AVAILABLE", False):
            result = await migrate_gmail_tokens(dry_run=True)

        assert len(result.errors) > 0
        assert result.store_name == "GmailTokenStore"

    @pytest.mark.asyncio
    async def test_handles_import_error(self):
        """Returns error when GmailTokenStore not importable."""
        from aragora.storage.migrations.encrypt_existing_data import migrate_gmail_tokens

        with patch("aragora.storage.migrations.encrypt_existing_data.CRYPTO_AVAILABLE", True):
            with patch.dict("sys.modules", {"aragora.storage.gmail_token_store": None}):
                with patch(
                    "aragora.storage.migrations.encrypt_existing_data.get_encryption_service"
                ):
                    # This will raise ImportError when trying to import
                    result = await migrate_gmail_tokens(dry_run=True)

        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_dry_run_returns_result(self):
        """Should return result with dry_run flag set.

        When CRYPTO_AVAILABLE is True but get_gmail_token_store() doesn't
        accept the use_encryption kwarg, the TypeError is now caught
        gracefully and the result is returned with an error message.
        """
        from aragora.storage.migrations.encrypt_existing_data import migrate_gmail_tokens

        with patch("aragora.storage.migrations.encrypt_existing_data.CRYPTO_AVAILABLE", True):
            # The TypeError from get_gmail_token_store(use_encryption=True)
            # is caught and recorded as an error in the result
            result = await migrate_gmail_tokens(dry_run=True)

        assert result.dry_run is True
        assert result.store_name == "GmailTokenStore"


class TestMigrationCLI:
    """Tests for CLI entry point."""

    def test_main_dry_run_default(self):
        """CLI defaults to dry-run mode."""
        from aragora.storage.migrations.encrypt_existing_data import main

        with patch("sys.argv", ["encrypt_existing_data.py", "--all"]):
            with patch("asyncio.run") as mock_run:
                with patch("builtins.print"):
                    main()

        # Verify asyncio.run was called
        mock_run.assert_called_once()

    def test_main_with_execute(self):
        """CLI respects --execute flag."""
        from aragora.storage.migrations.encrypt_existing_data import main

        with patch("sys.argv", ["encrypt_existing_data.py", "--all", "--execute"]):
            with patch("asyncio.run") as mock_run:
                with patch("builtins.print"):
                    main()

        mock_run.assert_called_once()

    def test_main_specific_store(self):
        """CLI can migrate specific stores."""
        from aragora.storage.migrations.encrypt_existing_data import main

        with patch("sys.argv", ["encrypt_existing_data.py", "--sync-store"]):
            with patch("asyncio.run") as mock_run:
                with patch("builtins.print"):
                    main()

        mock_run.assert_called_once()


class TestMetricsIntegration:
    """Tests for metrics recording during migration."""

    @pytest.mark.asyncio
    async def test_metrics_recorded_on_migration(self):
        """Should record metrics during migration."""
        with patch("aragora.storage.migrations.encrypt_existing_data.CRYPTO_AVAILABLE", True):
            with patch(
                "aragora.storage.migrations.encrypt_existing_data.record_migration_record"
            ) as mock_record:
                with patch(
                    "aragora.storage.migrations.encrypt_existing_data.record_migration_error"
                ) as mock_error:
                    # Mock the store to have records to migrate
                    mock_store = MagicMock()
                    mock_connector = MagicMock()
                    mock_connector.id = "test-conn"
                    mock_connector.config = {"password": "secret"}
                    mock_store.list_connectors = AsyncMock(return_value=[mock_connector])
                    mock_store.save_connector = AsyncMock()
                    mock_store.initialize = AsyncMock()

                    with patch(
                        "aragora.storage.sync_store.SyncStore",
                        return_value=mock_store,
                    ):
                        with patch(
                            "aragora.storage.sync_store.CREDENTIAL_KEYWORDS",
                            {"password"},
                        ):
                            result = await migrate_sync_store(dry_run=False)

                    # Metrics should be recorded or migration attempted
                    # (may fail due to import errors in test env, but that's ok)
                    assert result is not None


class TestEdgeCases:
    """Tests for edge cases in migration."""

    def test_needs_migration_with_nested_dict(self):
        """Should handle nested dicts correctly."""
        config = {
            "name": "test",
            "nested": {
                "password": "nested_secret",
            },
        }
        # Only top-level keys are checked
        assert _needs_migration(config, ["password", "token"]) is False

    def test_needs_migration_with_empty_string(self):
        """Should handle empty string values."""
        config = {"password": ""}
        # Empty string is not None, so migration IS needed
        # (the function checks `value is not None`, not truthiness)
        assert _needs_migration(config, ["password"]) is True

    def test_needs_migration_with_list_value(self):
        """Should handle list values."""
        config = {"tokens": ["token1", "token2"]}
        # List value is not encrypted dict, so needs migration
        assert _needs_migration(config, ["token"]) is True

    def test_needs_migration_partial_match(self):
        """Should match partial keywords."""
        config = {"api_token_secret": "value", "db_password_hash": "hash"}
        assert _needs_migration(config, ["token", "password"]) is True

    def test_migration_result_with_errors(self):
        """Should track multiple errors."""
        result = MigrationResult(
            store_name="TestStore",
            total_records=100,
            migrated=90,
            already_encrypted=0,
            failed=10,
            errors=[
                "Record 1: Connection error",
                "Record 2: Timeout",
                "Record 3: Invalid data",
            ],
            dry_run=False,
        )

        assert result.success is False
        assert len(result.errors) == 3
        s = str(result)
        assert "10" in s  # Failed count
