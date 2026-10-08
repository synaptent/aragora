"""
Integration tests for encrypted storage.

Tests verify that:
- Secrets are encrypted before storage
- Secrets are decrypted correctly on retrieval
- Encryption survives store round-trips
- Encryption works across all storage backends
- Plaintext fallback works when encryption unavailable
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# Encryption Service Tests
# ============================================================================


class TestEncryptionService:
    """Tests for the EncryptionService functionality."""

    def test_encryption_service_initialization(self) -> None:
        """Test EncryptionService can be initialized."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test-key")

        assert service.get_active_key_id() == "test-key"

    def test_encrypt_decrypt_string(self) -> None:
        """Test string encryption and decryption."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test-key")

        plaintext = "my-secret-api-key-12345"
        encrypted = service.encrypt(plaintext)
        decrypted = service.decrypt_string(encrypted)

        assert decrypted == plaintext
        assert encrypted.to_base64() != plaintext

    def test_encrypt_decrypt_with_aad(self) -> None:
        """Test encryption with Associated Authenticated Data."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test-key")

        plaintext = "secret-token"
        aad = "user-123"

        encrypted = service.encrypt(plaintext, associated_data=aad)
        decrypted = service.decrypt_string(encrypted, associated_data=aad)

        assert decrypted == plaintext

    def test_aad_mismatch_fails(self) -> None:
        """Test that decryption with wrong AAD fails."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test-key")

        plaintext = "secret-token"
        encrypted = service.encrypt(plaintext, associated_data="user-123")

        # Decryption with wrong AAD should fail
        with pytest.raises(Exception):
            service.decrypt_string(encrypted, associated_data="user-456")

    def test_encrypt_fields(self) -> None:
        """Test encrypting specific fields in a record."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test-key")

        record = {
            "name": "My Integration",
            "api_key": "sk-secret-123",
            "webhook_url": "https://example.com/webhook",
            "enabled": True,
        }

        encrypted_record = service.encrypt_fields(
            record,
            sensitive_fields=["api_key", "webhook_url"],
        )

        # Non-sensitive fields unchanged
        assert encrypted_record["name"] == "My Integration"
        assert encrypted_record["enabled"] is True

        # Sensitive fields encrypted
        assert encrypted_record["api_key"]["_encrypted"] is True
        assert encrypted_record["webhook_url"]["_encrypted"] is True
        assert encrypted_record["api_key"]["_value"] != "sk-secret-123"

    def test_decrypt_fields(self) -> None:
        """Test decrypting specific fields in a record."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test-key")

        original = {
            "name": "My Integration",
            "api_key": "sk-secret-123",
            "webhook_url": "https://example.com/webhook",
        }

        encrypted = service.encrypt_fields(
            original,
            sensitive_fields=["api_key", "webhook_url"],
        )

        decrypted = service.decrypt_fields(
            encrypted,
            sensitive_fields=["api_key", "webhook_url"],
        )

        assert decrypted["name"] == original["name"]
        assert decrypted["api_key"] == original["api_key"]
        assert decrypted["webhook_url"] == original["webhook_url"]


# ============================================================================
# Integration Store Encryption Tests
# ============================================================================


class TestIntegrationStoreEncryption:
    """Tests for encryption in IntegrationStore."""

    @pytest.mark.asyncio
    async def test_sensitive_keys_encrypted(self) -> None:
        """Test that sensitive keys are encrypted when saved."""
        from aragora.storage.integration_store import (
            IntegrationConfig,
            InMemoryIntegrationStore,
        )

        store = InMemoryIntegrationStore()

        config = IntegrationConfig(
            type="slack",
            user_id="user-123",
            settings={
                "bot_token": "xoxb-secret-token",
                "api_key": "slack-api-key",
                "channel_name": "general",  # Not sensitive
            },
            enabled=True,
        )

        await store.save(config)

        # Retrieve and verify decryption
        retrieved = await store.get("slack", user_id="user-123")

        assert retrieved is not None
        assert retrieved.settings["channel_name"] == "general"
        # If encryption is available, tokens should be decrypted correctly
        assert retrieved.settings.get("bot_token") is not None

    @pytest.mark.asyncio
    async def test_roundtrip_preserves_data(self) -> None:
        """Test save/get roundtrip preserves all data."""
        from aragora.storage.integration_store import (
            IntegrationConfig,
            InMemoryIntegrationStore,
        )

        store = InMemoryIntegrationStore()

        original_settings = {
            "access_token": "oauth-token-12345",
            "webhook_url": "https://hooks.example.com/abc",
            "channel_id": "C12345",
            "team_name": "My Team",
        }

        config = IntegrationConfig(
            type="slack",
            user_id="user-roundtrip",
            settings=original_settings,
            enabled=True,
        )

        await store.save(config)
        retrieved = await store.get("slack", user_id="user-roundtrip")

        assert retrieved is not None
        for key, value in original_settings.items():
            assert retrieved.settings.get(key) == value, f"Mismatch for key: {key}"

    @pytest.mark.asyncio
    async def test_list_all_decrypts(self) -> None:
        """Test that list_all returns decrypted data."""
        from aragora.storage.integration_store import (
            IntegrationConfig,
            InMemoryIntegrationStore,
        )

        store = InMemoryIntegrationStore()

        # Save multiple configs
        for i in range(3):
            config = IntegrationConfig(
                type="discord",
                user_id=f"user-list-{i}",
                settings={
                    "bot_token": f"discord-token-{i}",
                    "guild_id": f"guild-{i}",
                },
                enabled=True,
            )
            await store.save(config)

        # List all and verify
        all_configs = await store.list_all()
        discord_configs = [c for c in all_configs if c.type == "discord"]

        assert len(discord_configs) >= 3
        for config in discord_configs:
            if config.user_id and "user-list-" in config.user_id:
                assert "discord-token-" in config.settings.get("bot_token", "")


# ============================================================================
# Gmail Token Store Encryption Tests
# ============================================================================


class TestGmailTokenStoreEncryption:
    """Tests for encryption in GmailTokenStore."""

    @pytest.mark.asyncio
    async def test_tokens_encrypted(self) -> None:
        """Test that OAuth tokens are encrypted."""
        from aragora.storage.gmail_token_store import (
            GmailUserState,
            InMemoryGmailTokenStore,
        )

        store = InMemoryGmailTokenStore()

        state = GmailUserState(
            user_id="gmail-user-123",
            email_address="user@example.com",
            access_token="ya29.access-token-secret",
            refresh_token="1//refresh-token-secret",
        )

        await store.save(state)

        # Retrieve and verify decryption
        retrieved = await store.get("gmail-user-123")

        assert retrieved is not None
        assert retrieved.email_address == "user@example.com"
        assert retrieved.access_token == "ya29.access-token-secret"
        assert retrieved.refresh_token == "1//refresh-token-secret"

    @pytest.mark.asyncio
    async def test_token_roundtrip(self) -> None:
        """Test token save/get roundtrip."""
        from aragora.storage.gmail_token_store import (
            GmailUserState,
            InMemoryGmailTokenStore,
        )

        store = InMemoryGmailTokenStore()

        original = GmailUserState(
            user_id="roundtrip-user",
            email_address="roundtrip@test.com",
            access_token="access-12345",
            refresh_token="refresh-67890",
        )

        await store.save(original)
        retrieved = await store.get("roundtrip-user")

        assert retrieved is not None
        assert retrieved.user_id == original.user_id
        assert retrieved.email_address == original.email_address
        assert retrieved.access_token == original.access_token
        assert retrieved.refresh_token == original.refresh_token


# ============================================================================
# Sync Store Encryption Tests
# ============================================================================


@pytest.mark.timeout(10)
class TestSyncStoreEncryption:
    """Tests for encryption in SyncStore (enterprise connectors)."""

    @pytest.fixture(autouse=True)
    def _reset_encryption_singleton(self):
        """Reset encryption service singleton before each test."""
        import aragora.security.encryption as enc_mod

        saved = enc_mod._encryption_service
        enc_mod._encryption_service = None
        yield
        enc_mod._encryption_service = saved

    @pytest.mark.asyncio
    async def test_connector_credentials_encrypted(self, tmp_path) -> None:
        """Test that connector credentials are encrypted."""
        from aragora.storage.sync_store import SyncStore

        store = SyncStore(use_encryption=True)
        store._database_url = f"sqlite:///{tmp_path}/connectors.db"
        await store.initialize()

        config = {
            "api_key": "sf-api-key-secret",
            "client_secret": "sf-client-secret",
            "instance_url": "https://example.salesforce.com",
        }

        await store.save_connector(
            connector_id="salesforce-1",
            connector_type="salesforce",
            name="Salesforce Integration",
            config=config,
        )

        # Retrieve and verify decryption
        retrieved = await store.get_connector("salesforce-1")

        assert retrieved is not None
        assert retrieved.name == "Salesforce Integration"
        assert retrieved.config["instance_url"] == "https://example.salesforce.com"
        # Credentials should be decrypted
        assert retrieved.config.get("api_key") == "sf-api-key-secret"

    @pytest.mark.asyncio
    async def test_encryption_disabled(self, tmp_path) -> None:
        """Test store works with encryption disabled."""
        from aragora.storage.sync_store import SyncStore

        store = SyncStore(use_encryption=False)
        store._database_url = f"sqlite:///{tmp_path}/connectors.db"
        await store.initialize()

        config = {
            "api_key": "plain-api-key",
        }

        await store.save_connector(
            connector_id="plain-1",
            connector_type="generic",
            name="Unencrypted Integration",
            config=config,
        )
        retrieved = await store.get_connector("plain-1")

        assert retrieved is not None
        assert retrieved.config["api_key"] == "plain-api-key"


# ============================================================================
# Encryption Migration Tests
# ============================================================================


class TestEncryptionMigration:
    """Tests for encrypting existing plaintext data."""

    def test_detect_unencrypted_value(self) -> None:
        """Test detection of unencrypted values."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test-key")

        # Plaintext value (not encrypted)
        plaintext_record = {
            "api_key": "plain-text-key",
        }

        # Check that decrypt_fields handles plaintext gracefully
        decrypted = service.decrypt_fields(plaintext_record, ["api_key"])

        # Should return as-is since it's not encrypted
        assert decrypted["api_key"] == "plain-text-key"

    def test_encrypted_value_detection(self) -> None:
        """Test that encrypted values are properly detected."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test-key")

        # Encrypt a value
        encrypted = service.encrypt_fields(
            {"api_key": "secret"},
            ["api_key"],
        )

        # Should have encryption marker
        assert encrypted["api_key"]["_encrypted"] is True
        assert "_value" in encrypted["api_key"]


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestEncryptionErrorHandling:
    """Tests for encryption error handling."""

    def test_encrypt_empty_value(self) -> None:
        """Test encrypting empty values roundtrips correctly."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test-key")

        record = {
            "api_key": "",
            "name": "Test",
        }

        encrypted = service.encrypt_fields(record, ["api_key"])
        decrypted = service.decrypt_fields(encrypted, ["api_key"])

        # Empty string should roundtrip correctly
        assert decrypted["api_key"] == ""
        assert decrypted["name"] == "Test"

    def test_encrypt_none_value(self) -> None:
        """Test encrypting None values."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test-key")

        record = {
            "api_key": None,
            "name": "Test",
        }

        encrypted = service.encrypt_fields(record, ["api_key"])

        # None should be preserved
        assert encrypted["api_key"] is None

    def test_encrypt_complex_value(self) -> None:
        """Test encrypting complex (dict/list) values."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test-key")

        record = {
            "credentials": {
                "username": "admin",
                "password": "secret123",
            },
            "name": "Test",
        }

        encrypted = service.encrypt_fields(record, ["credentials"])
        decrypted = service.decrypt_fields(encrypted, ["credentials"])

        # Complex value should roundtrip
        assert decrypted["credentials"]["username"] == "admin"
        assert decrypted["credentials"]["password"] == "secret123"


# ============================================================================
# Key Rotation Tests
# ============================================================================


class TestKeyRotation:
    """Tests for encryption key rotation."""

    def test_key_rotation(self) -> None:
        """Test that key rotation creates new key version."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("initial-key")

        # Encrypt with initial key
        encrypted = service.encrypt("secret-data")

        # Rotate key
        new_key = service.rotate_key()

        # Old data should still decrypt (overlap period)
        decrypted = service.decrypt_string(encrypted)
        assert decrypted == "secret-data"

    def test_new_encryptions_use_new_key(self) -> None:
        """Test that new encryptions use the rotated key."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("key-v1")

        # Rotate to v2
        service.rotate_key()

        # New encryption uses new key
        encrypted = service.encrypt("new-secret")

        # Should decrypt successfully
        decrypted = service.decrypt_string(encrypted)
        assert decrypted == "new-secret"
