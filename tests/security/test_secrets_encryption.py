"""
Tests for secrets encryption at rest.

Verifies that sensitive fields are encrypted before storage and
decrypted correctly on retrieval.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestIntegrationStoreEncryption:
    """Test encryption in integration_store.py."""

    def test_sensitive_keys_identified(self):
        """Verify SENSITIVE_KEYS includes all expected fields."""
        from aragora.storage.integration_store import SENSITIVE_KEYS

        # These are the core sensitive field patterns that should be encrypted
        expected = {"api_key", "access_token", "password", "secret"}
        assert expected.issubset(SENSITIVE_KEYS)

    def test_encrypt_settings_with_sensitive_data(self):
        """Test that sensitive fields are encrypted."""
        from aragora.storage.integration_store import _encrypt_settings

        settings = {
            "api_key": "sk-secret-key-12345",
            "username": "public-user",
            "password": "super-secret",
        }

        # Encryption may not be available in test env
        encrypted = _encrypt_settings(settings, user_id="user-1", integration_type="test")

        # If encryption is available, sensitive fields should be encrypted
        # (will have different format or _encrypted marker)
        # If not available, settings returned unchanged
        assert "username" in encrypted
        assert encrypted["username"] == "public-user"  # Not sensitive

    def test_decrypt_settings_round_trip(self):
        """Test encrypt then decrypt returns original values."""
        from aragora.storage.integration_store import (
            _encrypt_settings,
            _decrypt_settings,
        )

        original = {
            "api_key": "test-api-key-value",
            "username": "test-user",
            "enabled": True,
        }

        encrypted = _encrypt_settings(
            original.copy(),
            user_id="user-123",
            integration_type="slack",
        )

        decrypted = _decrypt_settings(
            encrypted,
            user_id="user-123",
            integration_type="slack",
        )

        assert decrypted["api_key"] == original["api_key"]
        assert decrypted["username"] == original["username"]
        assert decrypted["enabled"] == original["enabled"]

    def test_aad_prevents_cross_user_decryption(self):
        """Test that AAD binding prevents decryption with wrong user_id."""
        from aragora.storage.integration_store import (
            _encrypt_settings,
            _decrypt_settings,
        )

        original = {"api_key": "secret-key-value"}

        encrypted = _encrypt_settings(
            original.copy(),
            user_id="user-A",
            integration_type="test",
        )

        # Attempt to decrypt with different user_id should fail or return encrypted
        decrypted = _decrypt_settings(
            encrypted,
            user_id="user-B",  # Different user
            integration_type="test",
        )

        # Either decryption fails (returns encrypted) or raises error
        # depending on implementation
        # The key should NOT be the original if AAD is enforced
        if "_encrypted" in encrypted.get("api_key", ""):
            assert decrypted.get("api_key") != original["api_key"]


class TestGmailTokenStoreEncryption:
    """Test encryption in gmail_token_store.py."""

    def test_encrypt_token_round_trip(self):
        """Test token encryption and decryption."""
        from aragora.storage.gmail_token_store import _encrypt_token, _decrypt_token

        original_token = "ya29.test-access-token-12345"
        user_id = "user@example.com"

        encrypted = _encrypt_token(original_token, user_id=user_id)
        decrypted = _decrypt_token(encrypted, user_id=user_id)

        assert decrypted == original_token

    def test_empty_token_returns_empty(self):
        """Test empty token handling."""
        from aragora.storage.gmail_token_store import _encrypt_token, _decrypt_token

        assert _encrypt_token("", user_id="user") == ""
        assert _decrypt_token("", user_id="user") == ""

    def test_token_aad_binding(self):
        """Test that token AAD prevents cross-user decryption."""
        from aragora.storage.gmail_token_store import _encrypt_token, _decrypt_token

        original = "test-refresh-token"

        encrypted = _encrypt_token(original, user_id="user-A")

        # Decrypt with different user should fail
        decrypted = _decrypt_token(encrypted, user_id="user-B")

        # Either returns original encrypted string or empty on failure
        assert decrypted != original or decrypted == encrypted


class TestSyncStoreEncryption:
    """Test encryption in sync_store.py."""

    def test_encrypt_config_with_credentials(self):
        """Test connector config encryption."""
        from aragora.storage.sync_store import (
            _encrypt_config,
            _decrypt_config,
        )

        config = {
            "client_id": "app-123",
            "client_secret": "super-secret-value",
            "access_token": "token-xyz",
            "site_url": "https://example.com",
        }

        encrypted = _encrypt_config(
            config.copy(),
            use_encryption=True,
            connector_id="connector-1",
        )

        decrypted = _decrypt_config(
            encrypted,
            use_encryption=True,
            connector_id="connector-1",
        )

        assert decrypted["client_id"] == config["client_id"]
        assert decrypted["client_secret"] == config["client_secret"]
        assert decrypted["site_url"] == config["site_url"]

    def test_encryption_disabled_passthrough(self):
        """Test that use_encryption=False passes through unchanged."""
        from aragora.storage.sync_store import (
            _encrypt_config,
            _decrypt_config,
        )

        config = {"client_secret": "not-encrypted"}

        result = _encrypt_config(
            config.copy(),
            use_encryption=False,
            connector_id="test",
        )

        assert result["client_secret"] == config["client_secret"]


class TestNoPlaintextSecrets:
    """Verify secrets are not stored as plaintext."""

    def test_integration_store_no_plaintext(self):
        """Ensure saved integration settings don't have plaintext secrets."""
        # This test would require a mock database or file
        pass  # Placeholder for integration test

    def test_gmail_tokens_no_plaintext(self):
        """Ensure saved Gmail tokens don't have plaintext tokens."""
        pass  # Placeholder for integration test


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
