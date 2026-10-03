"""
Integration tests for encryption service and field-level encryption.

Tests the full encryption lifecycle including:
- Key management and rotation
- Field-level encryption/decryption
- Store integration (IntegrationStore, WebhookConfigStore, etc.)
- Error handling and edge cases
"""

import os
import pytest
from unittest.mock import patch, MagicMock

# Keys used for env var isolation
_ENV_KEYS = ("ARAGORA_ENCRYPTION_KEY", "ARAGORA_ENCRYPTION_REQUIRED", "ARAGORA_ENV")
_TEST_ENCRYPTION_KEY = "a" * 64  # 32-byte hex key


@pytest.fixture(autouse=True)
def _isolate_encryption_state():
    """Reset encryption singleton and environment before/after every test.

    This fixture guarantees full isolation so tests are not affected by
    global state left behind by other test modules (e.g. ARAGORA_ENV set
    to 'production', a stale _encryption_service singleton, or a cached
    SecretManager that remembers keys from earlier tests).
    """
    import aragora.security.encryption as enc_module
    from aragora.config.secrets import reset_secret_manager

    # -- Save state --
    saved_env: dict[str, str | None] = {}
    for key in _ENV_KEYS:
        saved_env[key] = os.environ.get(key)

    saved_singleton = enc_module._encryption_service

    # -- Set clean state for the test --
    os.environ["ARAGORA_ENCRYPTION_KEY"] = _TEST_ENCRYPTION_KEY
    # Ensure not in production mode and encryption is not required
    os.environ.pop("ARAGORA_ENCRYPTION_REQUIRED", None)
    os.environ.pop("ARAGORA_ENV", None)
    enc_module._encryption_service = None
    # Reset the SecretManager so it re-reads env vars fresh
    reset_secret_manager()

    yield

    # -- Restore state --
    enc_module._encryption_service = saved_singleton
    reset_secret_manager()
    for key in _ENV_KEYS:
        if saved_env[key] is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = saved_env[key]


class TestEncryptionServiceLifecycle:
    """Test encryption service initialization and key management."""

    def test_service_initializes_with_env_key(self):
        """Service should initialize with ARAGORA_ENCRYPTION_KEY."""
        from aragora.security.encryption import get_encryption_service

        service = get_encryption_service()
        assert service is not None
        assert service.get_active_key_id() == "master"

    def test_service_generates_ephemeral_key_without_env(self):
        """Service should generate ephemeral key when no env key set."""
        import aragora.security.encryption as enc_module
        from aragora.config.secrets import reset_secret_manager

        # Remove env key so the service creates an ephemeral one
        os.environ.pop("ARAGORA_ENCRYPTION_KEY", None)
        enc_module._encryption_service = None
        reset_secret_manager()  # Clear cached key from SecretManager

        from aragora.security.encryption import get_encryption_service

        service = get_encryption_service()
        assert service is not None
        # Should have generated a default key
        assert service.get_active_key_id() == "default"

    def test_key_rotation(self):
        """Key rotation should create new version while keeping old for decryption."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        key1 = service.generate_key("test_key")
        assert key1.version == 1

        # Encrypt with key1
        encrypted = service.encrypt("secret data")
        assert encrypted.key_version == 1

        # Rotate key
        key2 = service.rotate_key("test_key")
        assert key2.version == 2

        # Should still decrypt old data
        decrypted = service.decrypt(encrypted)
        assert decrypted == b"secret data"

        # New encryptions should use key2
        encrypted2 = service.encrypt("new secret")
        assert encrypted2.key_version == 2

    def test_encryption_with_associated_data(self):
        """AAD should prevent ciphertext from being used with wrong context."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test")

        # Encrypt with AAD
        encrypted = service.encrypt("secret", associated_data="user_123")

        # Decrypt with correct AAD
        decrypted = service.decrypt(encrypted, associated_data="user_123")
        assert decrypted == b"secret"

        # Decrypt with wrong AAD should fail
        with pytest.raises(Exception):  # cryptography raises InvalidTag
            service.decrypt(encrypted, associated_data="user_456")


class TestFieldLevelEncryption:
    """Test field-level encryption for storage records."""

    def test_encrypt_fields_marks_encrypted(self):
        """Encrypted fields should be marked with _encrypted flag."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test")

        record = {
            "name": "My Integration",
            "api_key": "sk-secret-key-123",
            "enabled": True,
        }

        encrypted = service.encrypt_fields(record, ["api_key"])

        assert encrypted["name"] == "My Integration"
        assert encrypted["enabled"] is True
        assert isinstance(encrypted["api_key"], dict)
        assert encrypted["api_key"]["_encrypted"] is True
        assert "_value" in encrypted["api_key"]

    def test_decrypt_fields_restores_values(self):
        """Decrypted fields should restore original values."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test")

        original = {
            "name": "Test",
            "api_key": "sk-secret-123",
            "password": "hunter2",
        }

        encrypted = service.encrypt_fields(original.copy(), ["api_key", "password"])
        decrypted = service.decrypt_fields(encrypted, ["api_key", "password"])

        assert decrypted == original

    def test_encrypt_fields_with_aad(self):
        """Field encryption with AAD should bind to record ID."""
        from aragora.security.encryption import EncryptionService

        service = EncryptionService()
        service.generate_key("test")

        record = {"api_key": "secret"}
        encrypted = service.encrypt_fields(record, ["api_key"], associated_data="rec_123")

        # Should decrypt with correct AAD
        decrypted = service.decrypt_fields(encrypted, ["api_key"], associated_data="rec_123")
        assert decrypted["api_key"] == "secret"

        # Should fail with wrong AAD
        with pytest.raises(Exception):
            service.decrypt_fields(encrypted, ["api_key"], associated_data="rec_456")


class TestEncryptedFieldsUtility:
    """Test the encrypted_fields utility module."""

    def test_sensitive_fields_constant(self):
        """SENSITIVE_FIELDS should contain expected field names."""
        from aragora.storage.encrypted_fields import SENSITIVE_FIELDS

        expected = {
            "access_token",
            "refresh_token",
            "api_key",
            "secret",
            "password",
            "auth_token",
            "bot_token",
            "webhook_url",
        }
        for field in expected:
            assert field in SENSITIVE_FIELDS

    def test_encrypt_sensitive_auto_detects_fields(self):
        """encrypt_sensitive should auto-detect sensitive fields."""
        from aragora.storage.encrypted_fields import encrypt_sensitive

        data = {
            "name": "test",
            "api_key": "sk-123",
            "access_token": "token-abc",
            "normal_field": "visible",
        }

        result = encrypt_sensitive(data)

        # Non-sensitive fields unchanged
        assert result["name"] == "test"
        assert result["normal_field"] == "visible"

        # Sensitive fields encrypted
        assert isinstance(result["api_key"], dict)
        assert result["api_key"]["_encrypted"] is True
        assert isinstance(result["access_token"], dict)
        assert result["access_token"]["_encrypted"] is True

    def test_decrypt_sensitive_restores_values(self):
        """decrypt_sensitive should restore original values."""
        from aragora.storage.encrypted_fields import encrypt_sensitive, decrypt_sensitive

        original = {
            "name": "test",
            "api_key": "sk-secret-key",
            "password": "hunter2",
        }

        encrypted = encrypt_sensitive(original.copy())
        decrypted = decrypt_sensitive(encrypted)

        assert decrypted == original

    def test_handles_none_values(self):
        """None values should not be encrypted."""
        from aragora.storage.encrypted_fields import encrypt_sensitive

        data = {"api_key": None, "name": "test"}
        result = encrypt_sensitive(data)

        assert result["api_key"] is None
        assert result["name"] == "test"

    def test_handles_empty_data(self):
        """Empty data should return empty."""
        from aragora.storage.encrypted_fields import encrypt_sensitive, decrypt_sensitive

        assert encrypt_sensitive({}) == {}
        assert encrypt_sensitive(None) is None
        assert decrypt_sensitive({}) == {}
        assert decrypt_sensitive(None) is None

    def test_is_field_encrypted_helper(self):
        """is_field_encrypted should detect encrypted fields."""
        from aragora.storage.encrypted_fields import (
            encrypt_sensitive,
            is_field_encrypted,
        )

        data = {"api_key": "secret", "name": "test"}
        encrypted = encrypt_sensitive(data)

        assert is_field_encrypted(encrypted, "api_key") is True
        assert is_field_encrypted(encrypted, "name") is False
        assert is_field_encrypted(encrypted, "nonexistent") is False

    def test_get_encrypted_field_names_helper(self):
        """get_encrypted_field_names should list encrypted fields."""
        from aragora.storage.encrypted_fields import (
            encrypt_sensitive,
            get_encrypted_field_names,
        )

        data = {"api_key": "secret", "password": "pass", "name": "test"}
        encrypted = encrypt_sensitive(data)

        names = get_encrypted_field_names(encrypted)
        assert "api_key" in names
        assert "password" in names
        assert "name" not in names


class TestEncryptionEdgeCases:
    """Test edge cases and error handling."""

    def test_unicode_data(self):
        """Unicode data should encrypt/decrypt correctly."""
        from aragora.storage.encrypted_fields import encrypt_sensitive, decrypt_sensitive

        data = {"api_key": "密钥123🔐"}
        encrypted = encrypt_sensitive(data)
        decrypted = decrypt_sensitive(encrypted)

        assert decrypted["api_key"] == "密钥123🔐"

    def test_special_characters(self):
        """Special characters should encrypt/decrypt correctly."""
        from aragora.storage.encrypted_fields import encrypt_sensitive, decrypt_sensitive

        data = {"api_key": "!@#$%^&*()_+-=[]{}|;':\",./<>?"}
        encrypted = encrypt_sensitive(data)
        decrypted = decrypt_sensitive(encrypted)

        assert decrypted["api_key"] == "!@#$%^&*()_+-=[]{}|;':\",./<>?"

    def test_large_data(self):
        """Large data should encrypt/decrypt correctly."""
        from aragora.storage.encrypted_fields import encrypt_sensitive, decrypt_sensitive

        # 1MB of data
        large_secret = "x" * (1024 * 1024)
        data = {"api_key": large_secret}

        encrypted = encrypt_sensitive(data)
        decrypted = decrypt_sensitive(encrypted)

        assert decrypted["api_key"] == large_secret

    def test_mixed_encrypted_unencrypted(self):
        """Mix of encrypted and unencrypted fields should work."""
        from aragora.storage.encrypted_fields import encrypt_sensitive, decrypt_sensitive

        # Partially encrypted data (simulating legacy + new)
        data = {"api_key": "secret"}
        encrypted = encrypt_sensitive(data)
        encrypted["plaintext_field"] = "visible"
        encrypted["password"] = "unencrypted_legacy"

        decrypted = decrypt_sensitive(encrypted)

        assert decrypted["api_key"] == "secret"
        assert decrypted["plaintext_field"] == "visible"
        assert decrypted["password"] == "unencrypted_legacy"  # Not encrypted, returned as-is


class TestEncryptionAvailability:
    """Test encryption availability checks."""

    def test_is_encryption_available(self):
        """is_encryption_available should return True when cryptography installed."""
        from aragora.storage.encrypted_fields import is_encryption_available

        assert is_encryption_available() is True

    def test_is_encryption_configured(self):
        """is_encryption_configured should check for env key."""
        from aragora.storage.encrypted_fields import is_encryption_configured

        # The autouse fixture sets ARAGORA_ENCRYPTION_KEY for us
        assert is_encryption_configured() is True

    def test_graceful_degradation_without_crypto(self):
        """Should degrade gracefully if cryptography unavailable."""
        from aragora.storage.encrypted_fields import encrypt_sensitive

        # Mock CRYPTO_AVAILABLE = False
        with patch("aragora.storage.encrypted_fields.is_encryption_available", return_value=False):
            data = {"api_key": "secret"}
            result = encrypt_sensitive(data)

            # Should return data unchanged
            assert result["api_key"] == "secret"


class TestEncryptionEnforcement:
    """Test encryption enforcement with ARAGORA_ENCRYPTION_REQUIRED flag."""

    def test_encryption_required_flag_default_false(self):
        """ENCRYPTION_REQUIRED should default to False."""
        import aragora.security.encryption as enc_module

        # The autouse fixture clears ARAGORA_ENCRYPTION_REQUIRED and ARAGORA_ENV
        assert enc_module.is_encryption_required() is False

    def test_encryption_required_raises_when_crypto_unavailable(self):
        """Should raise EncryptionError when encryption required but unavailable."""
        from aragora.storage.integration_store import _encrypt_settings
        from aragora.security.encryption import EncryptionError

        settings = {"api_key": "secret-key", "name": "test"}

        # Mock crypto unavailable + encryption required
        with patch("aragora.storage.integration_models.CRYPTO_AVAILABLE", False):
            with patch(
                "aragora.storage.integration_models.is_encryption_required", return_value=True
            ):
                with pytest.raises(EncryptionError) as exc_info:
                    _encrypt_settings(settings, "user1", "slack")

                assert "cryptography library not available" in str(exc_info.value)
                assert "integration_store" in str(exc_info.value)

    def test_encryption_required_raises_on_service_error(self):
        """Should raise EncryptionError when encryption fails and required."""
        from aragora.storage.integration_store import _encrypt_settings
        from aragora.security.encryption import EncryptionError

        settings = {"api_key": "secret-key", "name": "test"}

        # Mock encryption service failure + encryption required
        with patch("aragora.storage.integration_models.get_encryption_service") as mock_svc:
            mock_svc.side_effect = RuntimeError("Key not found")
            with patch(
                "aragora.storage.integration_models.is_encryption_required", return_value=True
            ):
                with pytest.raises(EncryptionError) as exc_info:
                    _encrypt_settings(settings, "user1", "slack")

                assert "Key not found" in str(exc_info.value)

    def test_encryption_not_required_returns_plaintext_on_failure(self):
        """Should return plaintext when encryption fails and not required."""
        from aragora.storage.integration_store import _encrypt_settings

        settings = {"api_key": "secret-key", "name": "test"}

        # Mock encryption service failure + encryption NOT required (default)
        with patch("aragora.storage.integration_models.get_encryption_service") as mock_svc:
            mock_svc.side_effect = RuntimeError("Key not found")
            with patch(
                "aragora.storage.integration_models.is_encryption_required", return_value=False
            ):
                result = _encrypt_settings(settings, "user1", "slack")

                # Should return original plaintext data
                assert result["api_key"] == "secret-key"

    def test_gmail_token_store_encryption_enforcement(self):
        """GmailTokenStore should enforce encryption when required."""
        from aragora.storage.gmail_token_store import _encrypt_token
        from aragora.security.encryption import EncryptionError

        token = "ya29.access_token_here"

        # Mock crypto unavailable + encryption required
        with patch("aragora.storage.gmail_token_store.CRYPTO_AVAILABLE", False):
            with patch(
                "aragora.storage.gmail_token_store.is_encryption_required", return_value=True
            ):
                with pytest.raises(EncryptionError) as exc_info:
                    _encrypt_token(token, "user123")

                assert "gmail_token_store" in str(exc_info.value)

    def test_sync_store_encryption_enforcement(self):
        """SyncStore should enforce encryption when required."""
        from aragora.storage.sync_store import _encrypt_config
        from aragora.security.encryption import EncryptionError

        config = {"api_key": "secret", "endpoint": "https://api.example.com"}

        # Mock crypto unavailable + encryption required
        with patch("aragora.storage.sync_store.CRYPTO_AVAILABLE", False):
            with patch("aragora.storage.sync_store.is_encryption_required", return_value=True):
                with pytest.raises(EncryptionError) as exc_info:
                    _encrypt_config(config, use_encryption=True, connector_id="salesforce")

                assert "sync_store" in str(exc_info.value)

    def test_encryption_error_has_helpful_message(self):
        """EncryptionError should include helpful remediation message."""
        from aragora.security.encryption import EncryptionError

        error = EncryptionError("encrypt", "test reason", "test_store")
        message = str(error)

        assert "ARAGORA_ENCRYPTION_REQUIRED=false" in message
        assert "test reason" in message
        assert "test_store" in message
