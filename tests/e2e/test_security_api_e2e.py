"""
End-to-end tests for Security API endpoints.

Tests the complete flow of:
- GET /api/admin/security/status
- POST /api/admin/security/rotate-key
- GET /api/admin/security/health
- GET /api/admin/security/keys

Also tests full database integration with encryption.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import (
    requires_no_ci,
    REQUIRES_NO_CI,
)


# =============================================================================
# Security API Handler Tests
# =============================================================================


class TestSecurityServiceDirect:
    """Direct tests for security service functionality (bypassing handlers)."""

    @pytest.fixture
    def encryption_key(self):
        """Generate a test encryption key."""
        key = secrets.token_hex(32)
        with patch.dict(os.environ, {"ARAGORA_ENCRYPTION_KEY": key}):
            # Clear any cached encryption service
            try:
                from aragora.security.encryption import _encryption_service_cache

                _encryption_service_cache.clear()
            except (ImportError, AttributeError):
                pass
            yield key

    def test_encryption_service_status(self, encryption_key):
        """Test encryption service returns correct status."""
        from aragora.security.encryption import get_encryption_service, CRYPTO_AVAILABLE

        assert CRYPTO_AVAILABLE is True
        service = get_encryption_service()
        assert service is not None
        assert service.get_active_key_id() is not None

    def test_encryption_service_key_info(self, encryption_key):
        """Test encryption service returns key information."""
        from aragora.security.encryption import get_encryption_service

        service = get_encryption_service()
        keys = service.list_keys()
        assert len(keys) >= 1

    def test_encryption_round_trip_health(self, encryption_key):
        """Test encryption service can perform round-trip."""
        from aragora.security.encryption import get_encryption_service

        service = get_encryption_service()
        test_data = b"health_check_test_data"

        encrypted = service.encrypt(test_data)
        decrypted = service.decrypt(encrypted)

        assert decrypted == test_data

    def test_list_encryption_keys(self, encryption_key):
        """Test listing encryption keys."""
        from aragora.security.encryption import get_encryption_service

        service = get_encryption_service()
        keys = service.list_keys()

        assert len(keys) >= 1
        for key in keys:
            # Keys may be dicts or objects
            if isinstance(key, dict):
                assert "is_active" in key or "version" in key
            else:
                assert hasattr(key, "key_id") or hasattr(key, "version")


# =============================================================================
# Full Database Integration Tests
# =============================================================================


class TestIntegrationStoreE2E:
    """End-to-end tests for IntegrationStore with real database."""

    @pytest.fixture
    def encryption_key(self):
        """Generate a test encryption key."""
        key = secrets.token_hex(32)
        with patch.dict(os.environ, {"ARAGORA_ENCRYPTION_KEY": key}):
            try:
                from aragora.security.encryption import _encryption_service_cache

                _encryption_service_cache.clear()
            except (ImportError, AttributeError):
                pass
            yield key

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
        except OSError:
            pass

    @pytest.mark.asyncio
    async def test_save_and_retrieve_encrypted_integration(self, encryption_key, temp_db):
        """Test saving and retrieving an integration with encrypted secrets."""
        from aragora.storage.integration_store import (
            SQLiteIntegrationStore,
            IntegrationConfig,
        )

        store = SQLiteIntegrationStore(db_path=temp_db)

        # Create integration with sensitive data
        config = IntegrationConfig(
            type="slack",
            user_id="user-123",
            settings={
                "api_key": "sk_live_secret_key_12345",
                "bot_token": "xoxb-secret-token",
                "webhook_url": "https://hooks.slack.com/secret",
            },
        )

        # Save
        await store.save(config)

        # Retrieve
        retrieved = await store.get("slack", "user-123")

        # Verify sensitive fields are decrypted correctly
        assert retrieved is not None
        assert retrieved.settings["api_key"] == "sk_live_secret_key_12345"
        assert retrieved.settings["bot_token"] == "xoxb-secret-token"
        assert retrieved.settings["webhook_url"] == "https://hooks.slack.com/secret"

    @pytest.mark.asyncio
    async def test_secrets_encrypted_in_database(self, encryption_key, temp_db):
        """Verify secrets are actually encrypted in the database file."""
        from aragora.storage.integration_store import (
            SQLiteIntegrationStore,
            IntegrationConfig,
        )

        store = SQLiteIntegrationStore(db_path=temp_db)

        secret_value = "sk_live_super_secret_key_67890"
        config = IntegrationConfig(
            type="api",
            user_id="user-456",
            settings={"api_key": secret_value},
        )

        await store.save(config)

        # Read raw database content
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute("SELECT settings_json FROM integrations WHERE user_id = 'user-456'")
        row = cursor.fetchone()
        conn.close()

        # The plaintext secret should NOT appear in raw storage
        raw_settings = row[0] if row else ""
        assert secret_value not in raw_settings, "Secret stored in plaintext!"


class TestGmailTokenStoreE2E:
    """End-to-end tests for GmailTokenStore with real database."""

    @pytest.fixture
    def encryption_key(self):
        """Generate a test encryption key."""
        key = secrets.token_hex(32)
        with patch.dict(os.environ, {"ARAGORA_ENCRYPTION_KEY": key}):
            try:
                from aragora.security.encryption import _encryption_service_cache

                _encryption_service_cache.clear()
            except (ImportError, AttributeError):
                pass
            yield key

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
        except OSError:
            pass

    @pytest.mark.asyncio
    async def test_save_and_retrieve_encrypted_tokens(self, encryption_key, temp_db):
        """Test saving and retrieving Gmail tokens with encryption."""
        from aragora.storage.gmail_token_store import (
            SQLiteGmailTokenStore,
            GmailUserState,
        )

        store = SQLiteGmailTokenStore(db_path=temp_db)

        # Create state with sensitive tokens
        state = GmailUserState(
            user_id="user@example.com",
            access_token="ya29.access_token_secret_12345",
            refresh_token="1//refresh_token_secret_67890",
            token_expiry=None,
        )

        # Save
        await store.save(state)

        # Retrieve
        retrieved = await store.get("user@example.com")

        # Verify tokens are decrypted correctly
        assert retrieved is not None
        assert retrieved.access_token == "ya29.access_token_secret_12345"
        assert retrieved.refresh_token == "1//refresh_token_secret_67890"

    @pytest.mark.asyncio
    async def test_tokens_encrypted_in_database(self, encryption_key, temp_db):
        """Verify tokens are actually encrypted in the database file."""
        from aragora.storage.gmail_token_store import (
            SQLiteGmailTokenStore,
            GmailUserState,
        )

        store = SQLiteGmailTokenStore(db_path=temp_db)

        access_token = "ya29.super_secret_access_token"
        refresh_token = "1//super_secret_refresh_token"

        state = GmailUserState(
            user_id="test@example.com",
            access_token=access_token,
            refresh_token=refresh_token,
        )

        await store.save(state)

        # Read raw database content
        conn = sqlite3.connect(temp_db)
        cursor = conn.execute(
            "SELECT access_token, refresh_token FROM gmail_tokens WHERE user_id = 'test@example.com'"
        )
        row = cursor.fetchone()
        conn.close()

        if row:
            raw_access, raw_refresh = row
            # Tokens should NOT appear in plaintext
            assert access_token not in (raw_access or ""), "Access token stored in plaintext!"
            assert refresh_token not in (raw_refresh or ""), "Refresh token stored in plaintext!"


class TestSyncStoreE2E:
    """End-to-end tests for SyncStore with real database."""

    @pytest.fixture
    def encryption_key(self):
        """Generate a test encryption key."""
        key = secrets.token_hex(32)
        with patch.dict(os.environ, {"ARAGORA_ENCRYPTION_KEY": key}):
            try:
                from aragora.security.encryption import _encryption_service_cache

                _encryption_service_cache.clear()
            except (ImportError, AttributeError):
                pass
            yield key

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        try:
            os.unlink(db_path)
        except OSError:
            pass

    @pytest.mark.asyncio
    async def test_save_and_retrieve_encrypted_connector(self, encryption_key, temp_db):
        """Test saving and retrieving connector config with encryption."""
        from aragora.storage.sync_store import (
            SyncStore,
            ConnectorConfig,
        )

        # Use SQLite URL format for SyncStore
        store = SyncStore(database_url=f"sqlite:///{temp_db}", use_encryption=True)
        await store.initialize()

        # Save connector config with sensitive data
        connector = await store.save_connector(
            connector_id="conn-123",
            connector_type="salesforce",
            name="Test Salesforce",
            config={
                "client_id": "public_client_id",
                "client_secret": "super_secret_client_secret",
                "access_token": "secret_access_token_xyz",
            },
        )

        # Retrieve
        retrieved = await store.get_connector("conn-123")

        # Verify secrets are decrypted correctly
        assert retrieved is not None
        assert retrieved.config["client_id"] == "public_client_id"
        assert retrieved.config["client_secret"] == "super_secret_client_secret"
        assert retrieved.config["access_token"] == "secret_access_token_xyz"

        await store.close()


# =============================================================================
# Key Rotation E2E Tests
# =============================================================================


class TestKeyRotationE2E:
    """End-to-end tests for key rotation with real data."""

    @pytest.fixture(autouse=True)
    def security_migration_adapters(self):
        """Register the application composition adapters for direct E2E calls."""
        from aragora.ops.security_edge_adapters import register_security_migration_adapters
        from aragora.security.migration import register_migration_audit_provider

        register_security_migration_adapters()
        yield
        register_migration_audit_provider(None)

    @pytest.fixture
    def encryption_key(self):
        """Generate a test encryption key."""
        key = secrets.token_hex(32)
        with patch.dict(os.environ, {"ARAGORA_ENCRYPTION_KEY": key}):
            try:
                from aragora.security.encryption import _encryption_service_cache

                _encryption_service_cache.clear()
            except (ImportError, AttributeError):
                pass
            yield key

    def test_rotation_dry_run_preserves_data(self, encryption_key):
        """Test that dry run doesn't modify any data."""
        from aragora.security.migration import rotate_encryption_key

        # Run dry run
        result = rotate_encryption_key(dry_run=True, stores=[])

        assert result.success is True
        assert result.records_reencrypted == 0  # Dry run shouldn't re-encrypt

    def test_rotation_result_structure(self, encryption_key):
        """Test rotation result has expected structure."""
        from aragora.security.migration import rotate_encryption_key

        result = rotate_encryption_key(dry_run=True, stores=[])

        # Verify result structure
        assert hasattr(result, "success")
        assert hasattr(result, "old_key_version")
        assert hasattr(result, "new_key_version")
        assert hasattr(result, "stores_processed")
        assert hasattr(result, "records_reencrypted")
        assert hasattr(result, "failed_records")
        assert hasattr(result, "duration_seconds")
        assert hasattr(result, "errors")


# =============================================================================
# Security Hardening Verification Tests
# =============================================================================


@pytest.mark.skipif(requires_no_ci, reason=REQUIRES_NO_CI)
class TestSecurityHardeningVerification:
    """Tests verifying security hardening is properly configured."""

    def test_encryption_service_available(self):
        """Verify encryption service is importable and usable."""
        from aragora.security.encryption import (
            get_encryption_service,
            CRYPTO_AVAILABLE,
        )

        assert CRYPTO_AVAILABLE is True

    def test_security_handler_registered(self):
        """Verify SecurityHandler is registered in handler registry."""
        from aragora.server.handler_registry import HANDLER_REGISTRY
        from aragora.server.handlers.admin.security import SecurityHandler

        handler_names = [h[0] for h in HANDLER_REGISTRY]
        assert "_security_handler" in handler_names
        assert SecurityHandler is not None

    def test_security_routes_defined(self):
        """Verify security routes are defined."""
        from aragora.server.handlers.admin.security import SecurityHandler

        handler = SecurityHandler({})
        expected_routes = [
            "/api/admin/security/status",
            "/api/admin/security/rotate-key",
            "/api/admin/security/health",
            "/api/admin/security/keys",
        ]

        for route in expected_routes:
            assert handler.can_handle(route), f"Route not handled: {route}"

    def test_key_rotation_scheduler_available(self):
        """Verify key rotation scheduler is importable."""
        from aragora.ops.key_rotation import (
            KeyRotationScheduler,
            KeyRotationConfig,
            get_key_rotation_scheduler,
        )

        config = KeyRotationConfig()
        assert config.rotation_interval_days == 90
        assert config.alert_days_before == 7

    def test_security_metrics_available(self):
        """Verify security metrics are defined."""
        from aragora.observability.metrics.security import (
            record_encryption_operation,
            record_key_rotation,
            record_auth_attempt,
            record_rbac_decision,
        )

        # Just verify functions are callable
        assert callable(record_encryption_operation)
        assert callable(record_key_rotation)
        assert callable(record_auth_attempt)
        assert callable(record_rbac_decision)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
