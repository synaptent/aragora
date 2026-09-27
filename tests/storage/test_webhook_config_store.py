"""
Tests for WebhookConfigStore - durable webhook configuration storage.

Tests cover:
- WebhookConfig dataclass (serialization, event matching, from_row)
- Encryption helpers (_encrypt_secret, _decrypt_secret)
- EncryptionError exception
- InMemoryWebhookConfigStore (full CRUD, delivery tracking, filtering)
- SQLiteWebhookConfigStore (persistence, filtering, delivery, edge cases)
- RedisWebhookConfigStore (cache hit/miss, invalidation, fallback)
- Factory function get_webhook_config_store (backend selection, singleton)
- WEBHOOK_EVENTS set validation
"""

import json
import os
import time
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock, AsyncMock

from aragora.storage.webhook_config_store import (
    WebhookConfig,
    WebhookConfigStoreBackend,
    InMemoryWebhookConfigStore,
    PostgresWebhookConfigStore,
    SQLiteWebhookConfigStore,
    RedisWebhookConfigStore,
    get_webhook_config_store,
    set_webhook_config_store,
    reset_webhook_config_store,
    WEBHOOK_EVENTS,
    EncryptionError,
    _encrypt_secret,
    _decrypt_secret,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def in_memory_store():
    """Create fresh in-memory store for testing."""
    return InMemoryWebhookConfigStore()


@pytest.fixture
def sqlite_store(tmp_path):
    """Create fresh SQLite store for testing."""
    db_path = tmp_path / "test_webhooks.db"
    store = SQLiteWebhookConfigStore(db_path)
    yield store
    store.close()


@pytest.fixture
def redis_store(tmp_path):
    """Create fresh Redis store (falls back to SQLite) for testing."""
    db_path = tmp_path / "test_webhooks_redis.db"
    store = RedisWebhookConfigStore(db_path, redis_url="redis://nonexistent:6379")
    yield store
    store.close()


@pytest.fixture(autouse=True)
def reset_global_store():
    """Reset global store between tests."""
    reset_webhook_config_store()
    yield
    reset_webhook_config_store()


@pytest.fixture(autouse=True)
def webhook_store_test_env(monkeypatch):
    """Stabilize encryption/secrets behavior for webhook store unit tests."""
    monkeypatch.setenv("ARAGORA_ENV", "development")
    monkeypatch.setenv("ARAGORA_ENCRYPTION_REQUIRED", "false")
    monkeypatch.setenv("ARAGORA_SECRETS_STRICT", "false")
    monkeypatch.setenv("ARAGORA_ENCRYPTION_KEY", "0" * 64)

    # Clear cached encryption service so each test sees patched env values.
    from aragora.security import encryption as encryption_module

    encryption_module._encryption_service = None  # type: ignore[attr-defined]
    yield
    encryption_module._encryption_service = None  # type: ignore[attr-defined]


# =============================================================================
# EncryptionError Tests
# =============================================================================


class TestEncryptionError:
    """Tests for EncryptionError exception class."""

    def test_encryption_error_attributes(self):
        """Test EncryptionError stores operation, reason, and store."""
        err = EncryptionError("encrypt", "key not found", "webhook_config_store")
        assert err.operation == "encrypt"
        assert err.reason == "key not found"
        assert err.store == "webhook_config_store"

    def test_encryption_error_message(self):
        """Test EncryptionError formats a helpful message."""
        err = EncryptionError("decrypt", "invalid ciphertext", "test_store")
        assert "decrypt" in str(err)
        assert "invalid ciphertext" in str(err)
        assert "test_store" in str(err)
        assert "ARAGORA_ENCRYPTION_REQUIRED" in str(err)

    def test_encryption_error_default_store(self):
        """Test EncryptionError with default empty store."""
        err = EncryptionError("encrypt", "some reason")
        assert err.store == ""

    def test_encryption_error_is_exception(self):
        """Test EncryptionError is an Exception subclass."""
        err = EncryptionError("encrypt", "test")
        assert isinstance(err, Exception)

    def test_encryption_error_can_be_raised(self):
        """Test EncryptionError can be raised and caught."""
        with pytest.raises(EncryptionError) as exc_info:
            raise EncryptionError("encrypt", "missing key", "store_name")
        assert exc_info.value.operation == "encrypt"


# =============================================================================
# Encryption Helper Tests
# =============================================================================


class TestEncryptionHelpers:
    """Tests for _encrypt_secret and _decrypt_secret helpers."""

    def test_encrypt_empty_secret(self):
        """Test that encrypting empty string returns empty string."""
        assert _encrypt_secret("") == ""

    def test_decrypt_empty_secret(self):
        """Test that decrypting empty string returns empty string."""
        assert _decrypt_secret("") == ""

    @patch("aragora.storage.webhook_config_store.CRYPTO_AVAILABLE", False)
    @patch("aragora.storage.webhook_config_store.is_encryption_required", return_value=False)
    def test_encrypt_without_crypto_not_required(self, mock_req):
        """Test encrypt returns plaintext when crypto unavailable and not required."""
        result = _encrypt_secret("my-secret")
        assert result == "my-secret"

    @patch("aragora.storage.webhook_config_store.CRYPTO_AVAILABLE", False)
    @patch("aragora.storage.webhook_config_store.is_encryption_required", return_value=True)
    def test_encrypt_without_crypto_required_raises(self, mock_req):
        """Test encrypt raises EncryptionError when crypto unavailable but required."""
        with pytest.raises(EncryptionError) as exc_info:
            _encrypt_secret("my-secret")
        assert exc_info.value.operation == "encrypt"
        assert "cryptography library not available" in exc_info.value.reason

    @patch("aragora.storage.webhook_config_store.CRYPTO_AVAILABLE", True)
    @patch("aragora.storage.webhook_config_store.get_encryption_service", return_value=None)
    @patch("aragora.storage.webhook_config_store.is_encryption_required", return_value=False)
    def test_encrypt_no_service_not_required(self, mock_req, mock_svc):
        """Test encrypt returns plaintext when service unavailable and not required."""
        result = _encrypt_secret("my-secret")
        assert result == "my-secret"

    @patch("aragora.storage.webhook_config_store.CRYPTO_AVAILABLE", True)
    @patch("aragora.storage.webhook_config_store.get_encryption_service", return_value=None)
    @patch("aragora.storage.webhook_config_store.is_encryption_required", return_value=True)
    def test_encrypt_no_service_required_raises(self, mock_req, mock_svc):
        """Test encrypt raises EncryptionError when service unavailable but required."""
        with pytest.raises(EncryptionError) as exc_info:
            _encrypt_secret("my-secret")
        assert exc_info.value.reason == "encryption service not available"

    @patch("aragora.storage.webhook_config_store.CRYPTO_AVAILABLE", True)
    @patch("aragora.storage.webhook_config_store.is_encryption_required", return_value=False)
    def test_encrypt_service_exception_logs_warning(self, mock_req):
        """Test encrypt falls back to plaintext on service exception when not required."""
        mock_service = MagicMock()
        mock_service.encrypt.side_effect = RuntimeError("encryption failure")
        with patch(
            "aragora.storage.webhook_config_store.get_encryption_service", return_value=mock_service
        ):
            result = _encrypt_secret("my-secret")
            assert result == "my-secret"

    @patch("aragora.storage.webhook_config_store.CRYPTO_AVAILABLE", True)
    @patch("aragora.storage.webhook_config_store.is_encryption_required", return_value=True)
    def test_encrypt_service_exception_required_raises(self, mock_req):
        """Test encrypt raises EncryptionError on service exception when required."""
        mock_service = MagicMock()
        mock_service.encrypt.side_effect = RuntimeError("encryption failure")
        with patch(
            "aragora.storage.webhook_config_store.get_encryption_service", return_value=mock_service
        ):
            with pytest.raises(EncryptionError) as exc_info:
                _encrypt_secret("my-secret")
            assert "encryption failure" in exc_info.value.reason

    @patch("aragora.storage.webhook_config_store.CRYPTO_AVAILABLE", True)
    def test_encrypt_success(self):
        """Test successful encryption through the service."""
        mock_encrypted = MagicMock()
        mock_encrypted.to_base64.return_value = "AAAAencrypted_base64"
        mock_service = MagicMock()
        mock_service.encrypt.return_value = mock_encrypted
        with patch(
            "aragora.storage.webhook_config_store.get_encryption_service", return_value=mock_service
        ):
            result = _encrypt_secret("my-secret")
            assert result == "AAAAencrypted_base64"
            mock_service.encrypt.assert_called_once_with("my-secret")

    @patch("aragora.storage.webhook_config_store.CRYPTO_AVAILABLE", False)
    def test_decrypt_without_crypto(self):
        """Test decrypt returns input when crypto unavailable."""
        result = _decrypt_secret("some-encrypted-data")
        assert result == "some-encrypted-data"

    @patch("aragora.storage.webhook_config_store.CRYPTO_AVAILABLE", True)
    def test_decrypt_legacy_short_secret(self):
        """Test decrypt returns short secrets as-is (legacy unencrypted)."""
        # Legacy secrets are short base64 strings (< 50 chars)
        result = _decrypt_secret("abc123legacysecret")
        assert result == "abc123legacysecret"

    @patch("aragora.storage.webhook_config_store.CRYPTO_AVAILABLE", True)
    def test_decrypt_non_prefixed_secret(self):
        """Test decrypt returns secrets not starting with AAAA as-is."""
        long_secret = "B" * 60  # Long but doesn't start with AAAA
        result = _decrypt_secret(long_secret)
        assert result == long_secret

    @patch("aragora.storage.webhook_config_store.CRYPTO_AVAILABLE", True)
    def test_decrypt_success(self):
        """Test successful decryption through the service."""
        mock_service = MagicMock()
        mock_service.decrypt_string.return_value = "decrypted-secret"
        encrypted = "AAAA" + "x" * 60  # Looks like encrypted data
        with patch(
            "aragora.storage.webhook_config_store.get_encryption_service", return_value=mock_service
        ):
            result = _decrypt_secret(encrypted)
            assert result == "decrypted-secret"

    @patch("aragora.storage.webhook_config_store.CRYPTO_AVAILABLE", True)
    def test_decrypt_failure_returns_original(self):
        """Test decrypt returns original on failure (graceful degradation)."""
        mock_service = MagicMock()
        mock_service.decrypt_string.side_effect = ValueError("bad ciphertext")
        encrypted = "AAAA" + "x" * 60
        with patch(
            "aragora.storage.webhook_config_store.get_encryption_service", return_value=mock_service
        ):
            result = _decrypt_secret(encrypted)
            assert result == encrypted

    @patch("aragora.storage.webhook_config_store.CRYPTO_AVAILABLE", True)
    @patch("aragora.storage.webhook_config_store.get_encryption_service", return_value=None)
    def test_decrypt_no_service_returns_original(self, mock_svc):
        """Test decrypt returns original when service unavailable."""
        encrypted = "AAAA" + "x" * 60
        result = _decrypt_secret(encrypted)
        assert result == encrypted


# =============================================================================
# WebhookConfig Model Tests
# =============================================================================


class TestWebhookConfig:
    """Tests for WebhookConfig dataclass."""

    def test_create_minimal_config(self):
        """Test creating a config with minimal required fields."""
        config = WebhookConfig(
            id="test-id",
            url="https://example.com/webhook",
            events=["debate_end"],
            secret="test-secret",
        )
        assert config.id == "test-id"
        assert config.url == "https://example.com/webhook"
        assert config.events == ["debate_end"]
        assert config.secret == "test-secret"
        assert config.active is True
        assert config.name is None
        assert config.description is None
        assert config.last_delivery_at is None
        assert config.last_delivery_status is None
        assert config.delivery_count == 0
        assert config.failure_count == 0
        assert config.user_id is None
        assert config.workspace_id is None

    def test_create_full_config(self):
        """Test creating a config with all fields."""
        now = time.time()
        config = WebhookConfig(
            id="full-id",
            url="https://example.com/webhook",
            events=["debate_end", "consensus"],
            secret="secret-value",
            active=False,
            created_at=now,
            updated_at=now,
            name="My Webhook",
            description="A test webhook",
            last_delivery_at=now - 60,
            last_delivery_status=200,
            delivery_count=10,
            failure_count=2,
            user_id="user-1",
            workspace_id="ws-1",
        )
        assert config.active is False
        assert config.name == "My Webhook"
        assert config.description == "A test webhook"
        assert config.delivery_count == 10
        assert config.failure_count == 2
        assert config.user_id == "user-1"
        assert config.workspace_id == "ws-1"

    def test_to_dict_excludes_secret(self):
        """Test to_dict excludes secret by default."""
        config = WebhookConfig(
            id="test-id",
            url="https://example.com",
            events=["debate_end"],
            secret="secret-value",
        )
        result = config.to_dict()
        assert "secret" not in result
        assert result["id"] == "test-id"
        assert result["url"] == "https://example.com"
        assert result["events"] == ["debate_end"]

    def test_to_dict_includes_secret(self):
        """Test to_dict can include secret when requested."""
        config = WebhookConfig(
            id="test-id",
            url="https://example.com",
            events=["debate_end"],
            secret="secret-value",
        )
        result = config.to_dict(include_secret=True)
        assert result["secret"] == "secret-value"

    def test_to_dict_contains_all_fields(self):
        """Test to_dict includes all non-secret fields."""
        config = WebhookConfig(
            id="test-id",
            url="https://example.com",
            events=["debate_end"],
            secret="secret-value",
            name="Test",
            user_id="user-1",
            workspace_id="ws-1",
        )
        result = config.to_dict()
        assert result["name"] == "Test"
        assert result["user_id"] == "user-1"
        assert result["workspace_id"] == "ws-1"
        assert result["active"] is True
        assert result["delivery_count"] == 0
        assert result["failure_count"] == 0

    def test_matches_event_active(self):
        """Test matches_event for active webhook."""
        config = WebhookConfig(
            id="test-id",
            url="https://example.com",
            events=["debate_start", "debate_end"],
            secret="secret",
            active=True,
        )
        assert config.matches_event("debate_start") is True
        assert config.matches_event("debate_end") is True
        assert config.matches_event("vote") is False

    def test_matches_event_inactive(self):
        """Test matches_event returns False for inactive webhook."""
        config = WebhookConfig(
            id="test-id",
            url="https://example.com",
            events=["debate_start"],
            secret="secret",
            active=False,
        )
        assert config.matches_event("debate_start") is False

    def test_matches_event_wildcard(self):
        """Test matches_event with wildcard subscription."""
        config = WebhookConfig(
            id="test-id",
            url="https://example.com",
            events=["*"],
            secret="secret",
            active=True,
        )
        assert config.matches_event("debate_start") is True
        assert config.matches_event("vote") is True
        assert config.matches_event("invalid_event") is False  # Not in WEBHOOK_EVENTS

    def test_matches_event_wildcard_covers_all_known_events(self):
        """Test that wildcard matches all events in WEBHOOK_EVENTS."""
        config = WebhookConfig(
            id="test-id",
            url="https://example.com",
            events=["*"],
            secret="secret",
            active=True,
        )
        for event in WEBHOOK_EVENTS:
            assert config.matches_event(event) is True, f"Wildcard should match {event}"

    def test_matches_event_empty_events_list(self):
        """Test matches_event with empty events list."""
        config = WebhookConfig(
            id="test-id",
            url="https://example.com",
            events=[],
            secret="secret",
            active=True,
        )
        assert config.matches_event("debate_start") is False

    def test_to_json_roundtrip(self):
        """Test JSON serialization roundtrip."""
        config = WebhookConfig(
            id="test-id",
            url="https://example.com",
            events=["debate_end"],
            secret="secret",
            name="Test",
            user_id="user-1",
        )
        json_str = config.to_json()
        restored = WebhookConfig.from_json(json_str)
        assert restored.id == config.id
        assert restored.url == config.url
        assert restored.events == config.events
        assert restored.name == config.name
        assert restored.user_id == config.user_id

    def test_to_json_preserves_all_fields(self):
        """Test that to_json preserves all fields including delivery tracking."""
        config = WebhookConfig(
            id="test-id",
            url="https://example.com",
            events=["debate_end"],
            secret="secret",
            delivery_count=5,
            failure_count=2,
            last_delivery_status=200,
            workspace_id="ws-1",
        )
        json_str = config.to_json()
        restored = WebhookConfig.from_json(json_str)
        assert restored.delivery_count == 5
        assert restored.failure_count == 2
        assert restored.last_delivery_status == 200
        assert restored.workspace_id == "ws-1"

    def test_from_row(self):
        """Test creating WebhookConfig from database row tuple."""
        now = time.time()
        row = (
            "row-id",  # id
            "https://example.com/hook",  # url
            '["debate_end", "vote"]',  # events_json
            "plain-secret",  # secret (no encryption prefix)
            1,  # active
            now,  # created_at
            now,  # updated_at
            "Row Hook",  # name
            "A row-based hook",  # description
            now - 100,  # last_delivery_at
            200,  # last_delivery_status
            5,  # delivery_count
            1,  # failure_count
            "user-row",  # user_id
            "ws-row",  # workspace_id
        )
        config = WebhookConfig.from_row(row)
        assert config.id == "row-id"
        assert config.url == "https://example.com/hook"
        assert config.events == ["debate_end", "vote"]
        assert config.active is True
        assert config.name == "Row Hook"
        assert config.description == "A row-based hook"
        assert config.delivery_count == 5
        assert config.failure_count == 1
        assert config.user_id == "user-row"
        assert config.workspace_id == "ws-row"

    def test_from_row_with_native_events_sequence(self):
        """Test from_row accepts already-decoded event sequences."""
        now = time.time()
        row = (
            "row-id",
            "https://example.com/hook",
            ["debate_end", "vote"],
            "plain-secret",
            1,
            now,
            now,
            "Row Hook",
            "A row-based hook",
            None,
            None,
            0,
            0,
            None,
            None,
        )
        config = WebhookConfig.from_row(row)
        assert config.events == ["debate_end", "vote"]

    def test_from_row_with_null_optional_fields(self):
        """Test from_row handles NULL values for optional fields."""
        now = time.time()
        row = (
            "row-id",
            "https://example.com",
            '["debate_end"]',
            "",  # empty secret
            0,  # inactive
            now,
            now,
            None,  # name
            None,  # description
            None,  # last_delivery_at
            None,  # last_delivery_status
            0,  # delivery_count
            0,  # failure_count
            None,  # user_id
            None,  # workspace_id
        )
        config = WebhookConfig.from_row(row)
        assert config.active is False
        assert config.name is None
        assert config.description is None
        assert config.last_delivery_at is None
        assert config.last_delivery_status is None
        assert config.user_id is None
        assert config.workspace_id is None

    def test_from_row_with_empty_events(self):
        """Test from_row handles empty events JSON."""
        now = time.time()
        row = (
            "row-id",
            "https://example.com",
            "",
            "secret",
            1,
            now,
            now,
            None,
            None,
            None,
            None,
            0,
            0,
            None,
            None,
        )
        config = WebhookConfig.from_row(row)
        assert config.events == []

    def test_from_row_with_none_timestamps(self):
        """Test from_row defaults to current time when timestamps are None."""
        before = time.time()
        row = (
            "row-id",
            "https://example.com",
            '["debate_end"]',
            "secret",
            1,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
        config = WebhookConfig.from_row(row)
        after = time.time()
        assert before <= config.created_at <= after
        assert before <= config.updated_at <= after


# =============================================================================
# InMemoryWebhookConfigStore Tests
# =============================================================================


class TestInMemoryWebhookConfigStore:
    """Tests for InMemoryWebhookConfigStore."""

    def test_register_webhook(self, in_memory_store):
        """Test registering a new webhook."""
        webhook = in_memory_store.register(
            url="https://example.com/hook",
            events=["debate_end"],
            name="Test Hook",
        )
        assert webhook.id is not None
        assert webhook.url == "https://example.com/hook"
        assert webhook.events == ["debate_end"]
        assert webhook.name == "Test Hook"
        assert webhook.secret is not None
        assert len(webhook.secret) > 20  # Should be a secure token

    def test_register_with_all_params(self, in_memory_store):
        """Test registering a webhook with all optional parameters."""
        webhook = in_memory_store.register(
            url="https://example.com/hook",
            events=["debate_end", "consensus"],
            name="Full Hook",
            description="A fully configured webhook",
            user_id="user-123",
            workspace_id="ws-456",
        )
        assert webhook.description == "A fully configured webhook"
        assert webhook.user_id == "user-123"
        assert webhook.workspace_id == "ws-456"
        assert webhook.active is True
        assert webhook.delivery_count == 0
        assert webhook.failure_count == 0

    def test_register_generates_unique_ids(self, in_memory_store):
        """Test that each registration generates a unique ID."""
        w1 = in_memory_store.register(url="https://a.com", events=["debate_end"])
        w2 = in_memory_store.register(url="https://b.com", events=["vote"])
        assert w1.id != w2.id

    def test_register_generates_unique_secrets(self, in_memory_store):
        """Test that each registration generates a unique secret."""
        w1 = in_memory_store.register(url="https://a.com", events=["debate_end"])
        w2 = in_memory_store.register(url="https://b.com", events=["vote"])
        assert w1.secret != w2.secret

    def test_get_webhook(self, in_memory_store):
        """Test retrieving a webhook by ID."""
        created = in_memory_store.register(
            url="https://example.com/hook",
            events=["debate_end"],
        )
        retrieved = in_memory_store.get(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.url == created.url

    def test_get_nonexistent_webhook(self, in_memory_store):
        """Test retrieving a nonexistent webhook."""
        result = in_memory_store.get("nonexistent-id")
        assert result is None

    def test_list_webhooks(self, in_memory_store):
        """Test listing all webhooks."""
        in_memory_store.register(url="https://a.com", events=["debate_end"])
        in_memory_store.register(url="https://b.com", events=["vote"])
        webhooks = in_memory_store.list()
        assert len(webhooks) == 2

    def test_list_webhooks_by_user(self, in_memory_store):
        """Test listing webhooks filtered by user."""
        in_memory_store.register(url="https://a.com", events=["debate_end"], user_id="user-1")
        in_memory_store.register(url="https://b.com", events=["vote"], user_id="user-2")
        webhooks = in_memory_store.list(user_id="user-1")
        assert len(webhooks) == 1
        assert webhooks[0].user_id == "user-1"

    def test_list_webhooks_by_workspace(self, in_memory_store):
        """Test listing webhooks filtered by workspace."""
        in_memory_store.register(url="https://a.com", events=["debate_end"], workspace_id="ws-1")
        in_memory_store.register(url="https://b.com", events=["vote"], workspace_id="ws-2")
        in_memory_store.register(url="https://c.com", events=["consensus"], workspace_id="ws-1")
        webhooks = in_memory_store.list(workspace_id="ws-1")
        assert len(webhooks) == 2
        for w in webhooks:
            assert w.workspace_id == "ws-1"

    def test_list_webhooks_active_only(self, in_memory_store):
        """Test listing only active webhooks."""
        w1 = in_memory_store.register(url="https://a.com", events=["debate_end"])
        in_memory_store.register(url="https://b.com", events=["vote"])
        in_memory_store.update(w1.id, active=False)
        webhooks = in_memory_store.list(active_only=True)
        assert len(webhooks) == 1
        assert webhooks[0].active is True

    def test_list_empty_store(self, in_memory_store):
        """Test listing webhooks from empty store."""
        webhooks = in_memory_store.list()
        assert webhooks == []

    def test_list_sorted_by_created_at_descending(self, in_memory_store):
        """Test that list returns webhooks sorted by created_at descending."""
        w1 = in_memory_store.register(url="https://first.com", events=["debate_end"])
        time.sleep(0.01)  # Ensure different timestamps
        w2 = in_memory_store.register(url="https://second.com", events=["vote"])
        webhooks = in_memory_store.list()
        assert webhooks[0].url == "https://second.com"
        assert webhooks[1].url == "https://first.com"

    def test_list_combined_filters(self, in_memory_store):
        """Test listing with user_id and active_only combined."""
        in_memory_store.register(
            url="https://a.com",
            events=["debate_end"],
            user_id="user-1",
        )
        w2 = in_memory_store.register(
            url="https://b.com",
            events=["vote"],
            user_id="user-1",
        )
        in_memory_store.update(w2.id, active=False)
        in_memory_store.register(
            url="https://c.com",
            events=["consensus"],
            user_id="user-2",
        )
        webhooks = in_memory_store.list(user_id="user-1", active_only=True)
        assert len(webhooks) == 1
        assert webhooks[0].url == "https://a.com"

    def test_delete_webhook(self, in_memory_store):
        """Test deleting a webhook."""
        webhook = in_memory_store.register(url="https://a.com", events=["debate_end"])
        result = in_memory_store.delete(webhook.id)
        assert result is True
        assert in_memory_store.get(webhook.id) is None

    def test_delete_nonexistent_webhook(self, in_memory_store):
        """Test deleting a nonexistent webhook."""
        result = in_memory_store.delete("nonexistent-id")
        assert result is False

    def test_update_webhook(self, in_memory_store):
        """Test updating a webhook."""
        webhook = in_memory_store.register(
            url="https://old.com",
            events=["debate_end"],
            name="Old Name",
        )
        updated = in_memory_store.update(
            webhook.id,
            url="https://new.com",
            name="New Name",
        )
        assert updated.url == "https://new.com"
        assert updated.name == "New Name"
        assert updated.updated_at > webhook.created_at

    def test_update_webhook_partial(self, in_memory_store):
        """Test partial update of webhook."""
        webhook = in_memory_store.register(
            url="https://example.com",
            events=["debate_end"],
            name="Original Name",
        )
        updated = in_memory_store.update(webhook.id, name="New Name")
        assert updated.url == "https://example.com"  # Unchanged
        assert updated.name == "New Name"

    def test_update_webhook_events(self, in_memory_store):
        """Test updating webhook events list."""
        webhook = in_memory_store.register(
            url="https://example.com",
            events=["debate_end"],
        )
        updated = in_memory_store.update(webhook.id, events=["debate_start", "vote", "consensus"])
        assert updated.events == ["debate_start", "vote", "consensus"]
        assert updated.url == "https://example.com"  # Unchanged

    def test_update_webhook_active_state(self, in_memory_store):
        """Test toggling webhook active state."""
        webhook = in_memory_store.register(url="https://example.com", events=["debate_end"])
        assert webhook.active is True

        deactivated = in_memory_store.update(webhook.id, active=False)
        assert deactivated.active is False

        reactivated = in_memory_store.update(webhook.id, active=True)
        assert reactivated.active is True

    def test_update_webhook_description(self, in_memory_store):
        """Test updating webhook description."""
        webhook = in_memory_store.register(url="https://example.com", events=["debate_end"])
        updated = in_memory_store.update(webhook.id, description="New description")
        assert updated.description == "New description"

    def test_update_nonexistent_webhook(self, in_memory_store):
        """Test updating a nonexistent webhook returns None."""
        result = in_memory_store.update("nonexistent-id", url="https://new.com")
        assert result is None

    def test_record_delivery_success(self, in_memory_store):
        """Test recording successful delivery."""
        webhook = in_memory_store.register(url="https://a.com", events=["debate_end"])
        in_memory_store.record_delivery(webhook.id, 200, success=True)
        updated = in_memory_store.get(webhook.id)
        assert updated.last_delivery_status == 200
        assert updated.delivery_count == 1
        assert updated.failure_count == 0
        assert updated.last_delivery_at is not None

    def test_record_delivery_failure(self, in_memory_store):
        """Test recording failed delivery."""
        webhook = in_memory_store.register(url="https://a.com", events=["debate_end"])
        in_memory_store.record_delivery(webhook.id, 500, success=False)
        updated = in_memory_store.get(webhook.id)
        assert updated.last_delivery_status == 500
        assert updated.delivery_count == 1
        assert updated.failure_count == 1

    def test_record_multiple_deliveries(self, in_memory_store):
        """Test recording multiple deliveries tracks cumulative counts."""
        webhook = in_memory_store.register(url="https://a.com", events=["debate_end"])
        in_memory_store.record_delivery(webhook.id, 200, success=True)
        in_memory_store.record_delivery(webhook.id, 200, success=True)
        in_memory_store.record_delivery(webhook.id, 500, success=False)
        in_memory_store.record_delivery(webhook.id, 200, success=True)
        in_memory_store.record_delivery(webhook.id, 502, success=False)

        updated = in_memory_store.get(webhook.id)
        assert updated.delivery_count == 5
        assert updated.failure_count == 2

    def test_record_delivery_nonexistent_webhook(self, in_memory_store):
        """Test recording delivery for nonexistent webhook is a no-op."""
        # Should not raise
        in_memory_store.record_delivery("nonexistent-id", 200, success=True)

    def test_get_for_event(self, in_memory_store):
        """Test getting webhooks for a specific event."""
        in_memory_store.register(url="https://a.com", events=["debate_end", "vote"])
        in_memory_store.register(url="https://b.com", events=["consensus"])
        webhooks = in_memory_store.get_for_event("debate_end")
        assert len(webhooks) == 1
        assert "debate_end" in webhooks[0].events

    def test_get_for_event_multiple_matches(self, in_memory_store):
        """Test get_for_event returns all matching webhooks."""
        in_memory_store.register(url="https://a.com", events=["debate_end"])
        in_memory_store.register(url="https://b.com", events=["debate_end", "vote"])
        in_memory_store.register(url="https://c.com", events=["consensus"])
        webhooks = in_memory_store.get_for_event("debate_end")
        assert len(webhooks) == 2

    def test_get_for_event_excludes_inactive(self, in_memory_store):
        """Test get_for_event excludes inactive webhooks."""
        w1 = in_memory_store.register(url="https://a.com", events=["debate_end"])
        in_memory_store.register(url="https://b.com", events=["debate_end"])
        in_memory_store.update(w1.id, active=False)
        webhooks = in_memory_store.get_for_event("debate_end")
        assert len(webhooks) == 1
        assert webhooks[0].url == "https://b.com"

    def test_get_for_event_wildcard(self, in_memory_store):
        """Test get_for_event includes wildcard subscriptions."""
        in_memory_store.register(url="https://a.com", events=["*"])
        in_memory_store.register(url="https://b.com", events=["debate_end"])
        webhooks = in_memory_store.get_for_event("debate_end")
        assert len(webhooks) == 2

    def test_get_for_event_no_matches(self, in_memory_store):
        """Test get_for_event returns empty list when no matches."""
        in_memory_store.register(url="https://a.com", events=["debate_end"])
        webhooks = in_memory_store.get_for_event("consensus")
        assert webhooks == []

    def test_clear(self, in_memory_store):
        """Test clearing all webhooks."""
        in_memory_store.register(url="https://a.com", events=["debate_end"])
        in_memory_store.register(url="https://b.com", events=["vote"])
        in_memory_store.clear()
        assert len(in_memory_store.list()) == 0


# =============================================================================
# SQLiteWebhookConfigStore Tests
# =============================================================================


class TestSQLiteWebhookConfigStore:
    """Tests for SQLiteWebhookConfigStore."""

    def test_register_and_get(self, sqlite_store):
        """Test registering and retrieving a webhook."""
        webhook = sqlite_store.register(
            url="https://example.com/hook",
            events=["debate_end"],
            name="Test Hook",
        )
        assert webhook.id is not None
        retrieved = sqlite_store.get(webhook.id)
        assert retrieved is not None
        assert retrieved.url == "https://example.com/hook"
        assert retrieved.name == "Test Hook"

    def test_register_with_all_params(self, sqlite_store):
        """Test registering with all optional parameters."""
        webhook = sqlite_store.register(
            url="https://example.com/hook",
            events=["debate_end", "vote"],
            name="Full Hook",
            description="Test description",
            user_id="user-1",
            workspace_id="ws-1",
        )
        retrieved = sqlite_store.get(webhook.id)
        assert retrieved.description == "Test description"
        assert retrieved.user_id == "user-1"
        assert retrieved.workspace_id == "ws-1"
        assert retrieved.events == ["debate_end", "vote"]

    def test_persistence(self, tmp_path):
        """Test that data persists across store instances."""
        db_path = tmp_path / "persist_test.db"

        # Create and register
        store1 = SQLiteWebhookConfigStore(db_path)
        webhook = store1.register(url="https://a.com", events=["debate_end"])
        webhook_id = webhook.id
        store1.close()

        # Open new instance and verify data persists
        store2 = SQLiteWebhookConfigStore(db_path)
        retrieved = store2.get(webhook_id)
        assert retrieved is not None
        assert retrieved.url == "https://a.com"
        store2.close()

    def test_get_nonexistent(self, sqlite_store):
        """Test get returns None for nonexistent webhook."""
        result = sqlite_store.get("nonexistent-id")
        assert result is None

    def test_list_webhooks(self, sqlite_store):
        """Test listing all webhooks."""
        sqlite_store.register(url="https://a.com", events=["debate_end"])
        sqlite_store.register(url="https://b.com", events=["vote"])
        webhooks = sqlite_store.list()
        assert len(webhooks) == 2

    def test_list_by_user(self, sqlite_store):
        """Test listing webhooks by user."""
        sqlite_store.register(url="https://a.com", events=["debate_end"], user_id="user-1")
        sqlite_store.register(url="https://b.com", events=["vote"], user_id="user-2")
        webhooks = sqlite_store.list(user_id="user-1")
        assert len(webhooks) == 1
        assert webhooks[0].user_id == "user-1"

    def test_list_by_workspace(self, sqlite_store):
        """Test listing webhooks by workspace."""
        sqlite_store.register(url="https://a.com", events=["debate_end"], workspace_id="ws-1")
        sqlite_store.register(url="https://b.com", events=["vote"], workspace_id="ws-2")
        sqlite_store.register(url="https://c.com", events=["consensus"], workspace_id="ws-1")
        webhooks = sqlite_store.list(workspace_id="ws-1")
        assert len(webhooks) == 2

    def test_list_active_only(self, sqlite_store):
        """Test listing only active webhooks."""
        w1 = sqlite_store.register(url="https://a.com", events=["debate_end"])
        sqlite_store.register(url="https://b.com", events=["vote"])
        sqlite_store.update(w1.id, active=False)
        webhooks = sqlite_store.list(active_only=True)
        assert len(webhooks) == 1
        assert webhooks[0].active is True

    def test_list_ordered_by_created_at_desc(self, sqlite_store):
        """Test list returns results ordered by created_at descending."""
        sqlite_store.register(url="https://first.com", events=["debate_end"])
        time.sleep(0.01)
        sqlite_store.register(url="https://second.com", events=["vote"])
        webhooks = sqlite_store.list()
        assert webhooks[0].url == "https://second.com"
        assert webhooks[1].url == "https://first.com"

    def test_list_combined_filters(self, sqlite_store):
        """Test listing with user_id, workspace_id, and active_only."""
        sqlite_store.register(
            url="https://a.com",
            events=["debate_end"],
            user_id="user-1",
            workspace_id="ws-1",
        )
        w2 = sqlite_store.register(
            url="https://b.com",
            events=["vote"],
            user_id="user-1",
            workspace_id="ws-1",
        )
        sqlite_store.update(w2.id, active=False)
        sqlite_store.register(
            url="https://c.com",
            events=["consensus"],
            user_id="user-1",
            workspace_id="ws-2",
        )
        webhooks = sqlite_store.list(user_id="user-1", workspace_id="ws-1", active_only=True)
        assert len(webhooks) == 1
        assert webhooks[0].url == "https://a.com"

    def test_delete_webhook(self, sqlite_store):
        """Test deleting a webhook."""
        webhook = sqlite_store.register(url="https://a.com", events=["debate_end"])
        result = sqlite_store.delete(webhook.id)
        assert result is True
        assert sqlite_store.get(webhook.id) is None

    def test_delete_nonexistent(self, sqlite_store):
        """Test deleting a nonexistent webhook returns False."""
        result = sqlite_store.delete("nonexistent-id")
        assert result is False

    def test_update_webhook(self, sqlite_store):
        """Test updating a webhook."""
        webhook = sqlite_store.register(url="https://old.com", events=["debate_end"])
        updated = sqlite_store.update(webhook.id, url="https://new.com")
        assert updated.url == "https://new.com"
        # Verify persistence
        retrieved = sqlite_store.get(webhook.id)
        assert retrieved.url == "https://new.com"

    def test_update_webhook_events(self, sqlite_store):
        """Test updating webhook events."""
        webhook = sqlite_store.register(url="https://example.com", events=["debate_end"])
        updated = sqlite_store.update(webhook.id, events=["vote", "consensus"])
        assert updated.events == ["vote", "consensus"]
        # Verify persistence
        retrieved = sqlite_store.get(webhook.id)
        assert retrieved.events == ["vote", "consensus"]

    def test_update_webhook_active(self, sqlite_store):
        """Test updating webhook active state."""
        webhook = sqlite_store.register(url="https://example.com", events=["debate_end"])
        updated = sqlite_store.update(webhook.id, active=False)
        assert updated.active is False
        # Verify persistence
        retrieved = sqlite_store.get(webhook.id)
        assert retrieved.active is False

    def test_update_webhook_name_and_description(self, sqlite_store):
        """Test updating webhook name and description."""
        webhook = sqlite_store.register(url="https://example.com", events=["debate_end"])
        updated = sqlite_store.update(webhook.id, name="Updated Name", description="Updated desc")
        assert updated.name == "Updated Name"
        assert updated.description == "Updated desc"

    def test_update_nonexistent(self, sqlite_store):
        """Test updating a nonexistent webhook returns None."""
        result = sqlite_store.update("nonexistent-id", url="https://new.com")
        assert result is None

    def test_update_sets_updated_at(self, sqlite_store):
        """Test that update changes the updated_at timestamp."""
        webhook = sqlite_store.register(url="https://example.com", events=["debate_end"])
        original_updated_at = webhook.updated_at
        time.sleep(0.01)
        updated = sqlite_store.update(webhook.id, name="Changed")
        assert updated.updated_at > original_updated_at

    def test_update_keeps_returned_revision_in_sync_with_durable_row(self, sqlite_store):
        """Returned updated_at should match the durable revision used by Redis validation."""
        webhook = sqlite_store.register(url="https://example.com", events=["debate_end"])
        revised_at = webhook.updated_at + 10

        with patch(
            "aragora.storage.webhook_config_store.time.time",
            side_effect=[revised_at, revised_at + 1],
        ):
            updated = sqlite_store.update(webhook.id, name="Changed")

        assert updated is not None
        assert updated.updated_at == revised_at
        assert sqlite_store.get_cache_revision(webhook.id) == revised_at

    def test_update_returns_none_when_row_is_deleted_before_write(self, sqlite_store):
        """A concurrent delete must not surface a phantom successful SQLite update."""
        original = WebhookConfig(
            id="webhook-123",
            url="https://example.com/hook",
            events=["debate_end"],
            secret="secret",
            updated_at=100.0,
        )
        cursor = MagicMock()
        cursor.rowcount = 0
        conn = MagicMock()
        conn.execute.return_value = cursor

        with (
            patch.object(sqlite_store, "get", return_value=original),
            patch.object(sqlite_store, "_get_conn", return_value=conn),
            patch("aragora.storage.webhook_config_store.time.time", return_value=200.0),
        ):
            updated = sqlite_store.update("webhook-123", url="https://example.com/new")

        assert updated is None
        query, params = conn.execute.call_args.args
        assert "updated_at = ?" in query
        assert params == ["https://example.com/new", 200.0, "webhook-123"]

    def test_record_delivery_success(self, sqlite_store):
        """Test recording successful delivery."""
        webhook = sqlite_store.register(url="https://a.com", events=["debate_end"])
        sqlite_store.record_delivery(webhook.id, 200, success=True)
        updated = sqlite_store.get(webhook.id)
        assert updated.last_delivery_status == 200
        assert updated.delivery_count == 1
        assert updated.failure_count == 0

    def test_record_delivery_updates_revision(self, sqlite_store):
        """Delivery metadata updates must advance the durable cache revision."""
        webhook = sqlite_store.register(url="https://a.com", events=["debate_end"])
        revised_at = webhook.updated_at + 10

        with patch("aragora.storage.webhook_config_store.time.time", return_value=revised_at):
            sqlite_store.record_delivery(webhook.id, 200, success=True)

        updated = sqlite_store.get(webhook.id)
        assert updated.updated_at == revised_at
        assert sqlite_store.get_cache_revision(webhook.id) == revised_at

    def test_record_delivery_failure(self, sqlite_store):
        """Test recording failed delivery."""
        webhook = sqlite_store.register(url="https://a.com", events=["debate_end"])
        sqlite_store.record_delivery(webhook.id, 500, success=False)
        updated = sqlite_store.get(webhook.id)
        assert updated.last_delivery_status == 500
        assert updated.delivery_count == 1
        assert updated.failure_count == 1

    def test_record_multiple_deliveries(self, sqlite_store):
        """Test recording multiple deliveries tracks cumulative counts."""
        webhook = sqlite_store.register(url="https://a.com", events=["debate_end"])
        sqlite_store.record_delivery(webhook.id, 200, success=True)
        sqlite_store.record_delivery(webhook.id, 200, success=True)
        sqlite_store.record_delivery(webhook.id, 500, success=False)
        sqlite_store.record_delivery(webhook.id, 200, success=True)

        updated = sqlite_store.get(webhook.id)
        assert updated.delivery_count == 4
        assert updated.failure_count == 1
        assert updated.last_delivery_at is not None

    def test_get_for_event(self, sqlite_store):
        """Test getting webhooks for an event."""
        sqlite_store.register(url="https://a.com", events=["debate_end"])
        sqlite_store.register(url="https://b.com", events=["vote"])
        webhooks = sqlite_store.get_for_event("debate_end")
        assert len(webhooks) == 1

    def test_get_for_event_excludes_inactive(self, sqlite_store):
        """Test get_for_event excludes inactive webhooks."""
        w1 = sqlite_store.register(url="https://a.com", events=["debate_end"])
        sqlite_store.register(url="https://b.com", events=["debate_end"])
        sqlite_store.update(w1.id, active=False)
        webhooks = sqlite_store.get_for_event("debate_end")
        assert len(webhooks) == 1
        assert webhooks[0].url == "https://b.com"

    def test_get_for_event_wildcard(self, sqlite_store):
        """Test get_for_event includes wildcard subscriptions."""
        sqlite_store.register(url="https://a.com", events=["*"])
        sqlite_store.register(url="https://b.com", events=["debate_end"])
        webhooks = sqlite_store.get_for_event("debate_end")
        assert len(webhooks) == 2

    def test_close_and_reopen(self, tmp_path):
        """Test that closing and reopening works correctly."""
        db_path = tmp_path / "close_test.db"
        store = SQLiteWebhookConfigStore(db_path)
        webhook = store.register(url="https://example.com", events=["debate_end"])
        store.close()

        # Reopen and verify
        store2 = SQLiteWebhookConfigStore(db_path)
        retrieved = store2.get(webhook.id)
        assert retrieved is not None
        store2.close()

    def test_creates_parent_directories(self, tmp_path):
        """Test that the store creates parent directories if needed."""
        db_path = tmp_path / "nested" / "dirs" / "webhooks.db"
        store = SQLiteWebhookConfigStore(db_path)
        webhook = store.register(url="https://example.com", events=["debate_end"])
        assert store.get(webhook.id) is not None
        store.close()


# =============================================================================
# RedisWebhookConfigStore Tests (with SQLite fallback)
# =============================================================================


class TestRedisWebhookConfigStore:
    """Tests for RedisWebhookConfigStore (falls back to SQLite when Redis unavailable)."""

    def test_fallback_to_sqlite(self, redis_store):
        """Test that store works when Redis is unavailable (using SQLite fallback)."""
        webhook = redis_store.register(
            url="https://example.com/hook",
            events=["debate_end"],
        )
        assert webhook.id is not None
        retrieved = redis_store.get(webhook.id)
        assert retrieved is not None
        assert retrieved.url == "https://example.com/hook"

    def test_list_uses_sqlite(self, redis_store):
        """Test that list operations use SQLite backend."""
        redis_store.register(url="https://a.com", events=["debate_end"])
        redis_store.register(url="https://b.com", events=["vote"])
        webhooks = redis_store.list()
        assert len(webhooks) == 2

    def test_delete(self, redis_store):
        """Test deleting a webhook."""
        webhook = redis_store.register(url="https://a.com", events=["debate_end"])
        result = redis_store.delete(webhook.id)
        assert result is True
        assert redis_store.get(webhook.id) is None

    def test_update(self, redis_store):
        """Test updating a webhook through Redis store."""
        webhook = redis_store.register(url="https://old.com", events=["debate_end"])
        updated = redis_store.update(webhook.id, url="https://new.com")
        assert updated is not None
        assert updated.url == "https://new.com"

    def test_record_delivery(self, redis_store):
        """Test recording delivery through Redis store."""
        webhook = redis_store.register(url="https://a.com", events=["debate_end"])
        redis_store.record_delivery(webhook.id, 200, success=True)
        updated = redis_store.get(webhook.id)
        assert updated.delivery_count == 1

    def test_get_for_event(self, redis_store):
        """Test get_for_event through Redis store."""
        redis_store.register(url="https://a.com", events=["debate_end"])
        redis_store.register(url="https://b.com", events=["vote"])
        webhooks = redis_store.get_for_event("debate_end")
        assert len(webhooks) == 1

    def test_redis_key_format(self, redis_store):
        """Test Redis key format is correct."""
        key = redis_store._redis_key("test-id-123")
        assert key == "aragora:webhook_configs:test-id-123"

    def test_redis_ttl_value(self):
        """Test Redis TTL is set to 24 hours."""
        assert RedisWebhookConfigStore.REDIS_TTL == 86400

    def test_redis_prefix(self):
        """Test Redis prefix is correct."""
        assert RedisWebhookConfigStore.REDIS_PREFIX == "aragora:webhook_configs"

    def test_with_mocked_redis_register(self, tmp_path):
        """Test register caches to Redis when available."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store.register(url="https://example.com", events=["debate_end"])

        # Verify Redis was called with setex
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == f"aragora:webhook_configs:{webhook.id}"
        assert call_args[0][1] == 86400  # TTL
        store.close()

    def test_with_mocked_redis_register_encrypts_cached_secret(self, tmp_path):
        """Redis cache entries should not store decrypted webhook secrets."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        with patch(
            "aragora.storage.webhook_config_store._encrypt_secret",
            return_value="ENCRYPTED-SECRET",
        ) as mock_encrypt:
            webhook = store.register(url="https://example.com", events=["debate_end"])

        payload = json.loads(mock_redis.setex.call_args[0][2])
        assert payload["id"] == webhook.id
        assert payload["secret"] == "ENCRYPTED-SECRET"
        assert any(call.args == (webhook.secret,) for call in mock_encrypt.call_args_list)
        store.close()

    def test_with_mocked_redis_get_cache_hit(self, tmp_path):
        """Test get returns from Redis cache when available."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        # Create a webhook in SQLite first
        webhook = store._sqlite.register(url="https://example.com", events=["debate_end"])

        # Set up Redis to return the cached value
        mock_redis.get.return_value = webhook.to_json()

        retrieved = store.get(webhook.id)
        assert retrieved is not None
        assert retrieved.url == "https://example.com"
        mock_redis.get.assert_called_once()
        store.close()

    def test_with_mocked_redis_get_cache_hit_decrypts_cached_secret(self, tmp_path):
        """Redis cache hits should decrypt cached secrets before returning them."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store._sqlite.register(url="https://example.com", events=["debate_end"])
        payload = webhook.to_dict(include_secret=True)
        payload["secret"] = "ENCRYPTED-SECRET"
        mock_redis.get.return_value = json.dumps(payload)

        with patch(
            "aragora.storage.webhook_config_store._decrypt_secret",
            return_value=webhook.secret,
        ) as mock_decrypt:
            retrieved = store.get(webhook.id)

        assert retrieved is not None
        assert retrieved.secret == webhook.secret
        mock_decrypt.assert_called_once_with("ENCRYPTED-SECRET")
        store.close()

    def test_with_mocked_redis_get_cache_hit_bypasses_deleted_sqlite_row(self, tmp_path):
        """A stale Redis hit must not resurrect a webhook deleted by another instance."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store._sqlite.register(url="https://example.com", events=["debate_end"])
        mock_redis.get.return_value = webhook.to_json()
        assert store._sqlite.delete(webhook.id) is True

        retrieved = store.get(webhook.id)

        assert retrieved is None
        mock_redis.get.assert_called_once_with(f"aragora:webhook_configs:{webhook.id}")
        mock_redis.delete.assert_called_once_with(f"aragora:webhook_configs:{webhook.id}")
        store.close()

    def test_with_mocked_redis_get_cache_hit_refreshes_stale_delivery_state(self, tmp_path):
        """A stale Redis hit must refresh from SQLite when delivery metadata changed elsewhere."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store._sqlite.register(url="https://example.com", events=["debate_end"])
        mock_redis.get.return_value = webhook.to_json()
        store._sqlite.record_delivery(webhook.id, 500, success=False)

        retrieved = store.get(webhook.id)

        assert retrieved is not None
        assert retrieved.last_delivery_status == 500
        assert retrieved.delivery_count == 1
        assert retrieved.failure_count == 1
        mock_redis.get.assert_called_once_with(f"aragora:webhook_configs:{webhook.id}")
        mock_redis.setex.assert_called_once()
        store.close()

    def test_with_mocked_redis_get_rejects_boolean_cached_revision(self, tmp_path):
        """Boolean cache revisions must not satisfy the durable revision trust gate."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store._sqlite.register(url="https://example.com", events=["debate_end"])

        cached_payload = webhook.to_dict(include_secret=True)
        cached_payload["url"] = "https://stale.example.com"
        cached_payload["updated_at"] = True
        mock_redis.get.return_value = json.dumps(cached_payload)

        with patch.object(store._sqlite, "get_cache_revision", return_value=1.0):
            retrieved = store.get(webhook.id)

        assert retrieved is not None
        assert retrieved.url == "https://example.com"
        mock_redis.get.assert_called_once_with(f"aragora:webhook_configs:{webhook.id}")
        mock_redis.setex.assert_called_once()
        store.close()

    def test_with_mocked_redis_get_rejects_nonboolean_cached_active_flag(self, tmp_path):
        """Malformed cached activity flags must not override SQLite truth."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store._sqlite.register(url="https://example.com", events=["debate_end"])
        inactive = store._sqlite.update(webhook.id, active=False)
        assert inactive is not None

        cached_payload = inactive.to_dict(include_secret=True)
        cached_payload["active"] = "false"
        mock_redis.get.return_value = json.dumps(cached_payload)

        retrieved = store.get(webhook.id)

        assert retrieved is not None
        assert retrieved.active is False
        mock_redis.get.assert_called_once_with(f"aragora:webhook_configs:{webhook.id}")
        mock_redis.setex.assert_called_once()
        store.close()

    def test_with_mocked_redis_get_cache_miss(self, tmp_path):
        """Test get falls back to SQLite on cache miss and populates cache."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        # Create a webhook in SQLite
        webhook = store._sqlite.register(url="https://example.com", events=["debate_end"])

        # Redis returns None (cache miss)
        mock_redis.get.return_value = None

        retrieved = store.get(webhook.id)
        assert retrieved is not None
        assert retrieved.url == "https://example.com"

        # Should populate Redis cache
        mock_redis.setex.assert_called_once()
        store.close()

    def test_with_mocked_redis_get_redis_error(self, tmp_path):
        """Test get falls back to SQLite on Redis error."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        # Create a webhook in SQLite
        webhook = store._sqlite.register(url="https://example.com", events=["debate_end"])

        # Redis raises an error
        mock_redis.get.side_effect = ConnectionError("Redis down")

        retrieved = store.get(webhook.id)
        assert retrieved is not None
        assert retrieved.url == "https://example.com"
        store.close()

    def test_with_mocked_redis_delete_invalidates_cache(self, tmp_path):
        """Test delete removes from Redis cache."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store._sqlite.register(url="https://example.com", events=["debate_end"])
        store.delete(webhook.id)

        mock_redis.delete.assert_called_with(f"aragora:webhook_configs:{webhook.id}")
        store.close()

    def test_with_mocked_redis_delete_failure_bypasses_stale_cache(self, tmp_path):
        """A failed Redis invalidation must not resurrect a deleted webhook on later reads."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store.register(url="https://example.com", events=["debate_end"])
        stale_payload = webhook.to_json()

        mock_redis.delete.side_effect = ConnectionError("Redis down")
        assert store.delete(webhook.id) is True

        mock_redis.delete.side_effect = None
        mock_redis.reset_mock()
        mock_redis.get.return_value = stale_payload

        retrieved = store.get(webhook.id)

        assert retrieved is None
        mock_redis.get.assert_not_called()
        mock_redis.delete.assert_called_once_with(f"aragora:webhook_configs:{webhook.id}")
        store.close()

    def test_with_mocked_redis_update_refreshes_cache(self, tmp_path):
        """Test update refreshes the Redis cache."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store._sqlite.register(url="https://old.com", events=["debate_end"])
        store.update(webhook.id, url="https://new.com")

        # Redis cache should be updated
        mock_redis.setex.assert_called_once()
        store.close()

    def test_with_mocked_redis_update_keeps_cached_revision_trusted(self, tmp_path):
        """An updated cache entry should be immediately reusable without SQLite repair."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store._sqlite.register(url="https://old.com", events=["debate_end"])
        revised_at = webhook.updated_at + 10

        with patch(
            "aragora.storage.webhook_config_store.time.time",
            side_effect=[revised_at, revised_at + 1],
        ):
            updated = store.update(webhook.id, url="https://new.com")

        assert updated is not None
        cached_payload = mock_redis.setex.call_args[0][2]
        mock_redis.reset_mock()
        mock_redis.get.return_value = cached_payload

        retrieved = store.get(webhook.id)

        assert retrieved is not None
        assert retrieved.url == "https://new.com"
        mock_redis.get.assert_called_once_with(f"aragora:webhook_configs:{webhook.id}")
        mock_redis.setex.assert_not_called()
        store.close()

    def test_with_mocked_redis_update_failure_bypasses_stale_cache(self, tmp_path):
        """A failed Redis refresh must not let an older cached payload override SQLite truth."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store.register(url="https://old.com", events=["debate_end"])
        stale_payload = webhook.to_json()

        mock_redis.reset_mock()
        mock_redis.setex.side_effect = ConnectionError("Redis down")

        updated = store.update(webhook.id, url="https://new.com")
        assert updated is not None
        assert updated.url == "https://new.com"

        mock_redis.setex.side_effect = None
        mock_redis.reset_mock()
        mock_redis.get.return_value = stale_payload

        retrieved = store.get(webhook.id)

        assert retrieved is not None
        assert retrieved.url == "https://new.com"
        mock_redis.get.assert_not_called()
        mock_redis.setex.assert_called_once()
        store.close()

    def test_with_mocked_redis_update_miss_clears_stale_cache(self, tmp_path):
        """An update miss must clear stale Redis payloads for webhooks deleted elsewhere."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store.register(url="https://example.com", events=["debate_end"])
        stale_payload = webhook.to_json()

        # Simulate the webhook being deleted out-of-band in durable storage.
        assert store._sqlite.delete(webhook.id) is True

        mock_redis.reset_mock()
        updated = store.update(webhook.id, url="https://new.com")

        assert updated is None
        mock_redis.delete.assert_called_once_with(f"aragora:webhook_configs:{webhook.id}")

        mock_redis.reset_mock()
        mock_redis.get.return_value = stale_payload
        retrieved = store.get(webhook.id)

        assert retrieved is None
        mock_redis.get.assert_not_called()
        mock_redis.delete.assert_called_once_with(f"aragora:webhook_configs:{webhook.id}")
        store.close()

    def test_with_mocked_redis_record_delivery_invalidates(self, tmp_path):
        """Test record_delivery invalidates the Redis cache."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store._sqlite.register(url="https://example.com", events=["debate_end"])
        store.record_delivery(webhook.id, 200, success=True)

        # Redis cache should be invalidated (deleted)
        mock_redis.delete.assert_called_with(f"aragora:webhook_configs:{webhook.id}")
        store.close()

    def test_redis_connection_failure_graceful(self, tmp_path):
        """Test graceful handling when Redis connection fails during init."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path, redis_url="redis://nonexistent:9999")

        # The store should work via SQLite fallback
        webhook = store.register(url="https://example.com", events=["debate_end"])
        assert webhook.id is not None
        retrieved = store.get(webhook.id)
        assert retrieved is not None
        store.close()

    def test_redis_cache_failure_on_delete_graceful(self, tmp_path):
        """Test graceful handling when Redis delete fails."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.delete.side_effect = ConnectionError("Redis down")
        store._redis = mock_redis
        store._redis_checked = True

        webhook = store._sqlite.register(url="https://example.com", events=["debate_end"])

        # Should not raise even though Redis fails
        result = store.delete(webhook.id)
        assert result is True
        store.close()

    def test_redis_cache_failure_on_register_graceful(self, tmp_path):
        """Test graceful handling when Redis cache update fails on register."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        mock_redis.setex.side_effect = ConnectionError("Redis down")
        store._redis = mock_redis
        store._redis_checked = True

        # Should succeed despite Redis failure
        webhook = store.register(url="https://example.com", events=["debate_end"])
        assert webhook.id is not None
        store.close()

    def test_close(self, tmp_path):
        """Test closing the Redis store."""
        db_path = tmp_path / "test.db"
        store = RedisWebhookConfigStore(db_path)

        mock_redis = MagicMock()
        store._redis = mock_redis

        store.close()
        mock_redis.close.assert_called_once()


# =============================================================================
# PostgresWebhookConfigStore Sync Wrapper Tests
# =============================================================================


class TestPostgresWebhookConfigStoreSyncWrappers:
    """Tests for Postgres sync wrappers bridging through run_async()."""

    @pytest.fixture
    def postgres_store(self):
        """Create a Postgres store with a mocked pool."""
        return PostgresWebhookConfigStore(MagicMock())

    @pytest.mark.parametrize(
        ("method_name", "args", "kwargs"),
        [
            ("register", ("https://example.com/hook", ["debate_end"]), {}),
            ("get", ("webhook-123",), {}),
            ("list", (), {"user_id": "user-123", "workspace_id": "ws-123", "active_only": True}),
            ("delete", ("webhook-123",), {}),
            ("update", ("webhook-123",), {"url": "https://example.com/new"}),
            ("get_for_event", ("debate_end",), {}),
        ],
    )
    def test_sync_wrappers_delegate_via_run_async(
        self,
        postgres_store,
        method_name: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> None:
        """Sync wrappers should use the shared async bridge instead of run_until_complete()."""
        sentinel = object()

        def _capture(coro, timeout: float = 30.0):
            assert timeout == 30.0
            coro.close()
            return sentinel

        with patch(
            "aragora.storage.webhook_config_store.run_async", side_effect=_capture
        ) as mock_run:
            result = getattr(postgres_store, method_name)(*args, **kwargs)

        assert result is sentinel
        mock_run.assert_called_once()

    def test_record_delivery_delegates_via_run_async(self, postgres_store) -> None:
        """record_delivery should also bridge via run_async()."""

        def _capture(coro, timeout: float = 30.0):
            assert timeout == 30.0
            coro.close()
            return object()

        with patch(
            "aragora.storage.webhook_config_store.run_async", side_effect=_capture
        ) as mock_run:
            result = postgres_store.record_delivery("webhook-123", 200, success=True)

        assert result is None
        mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_record_delivery_async_updates_revision_timestamp(self) -> None:
        """Postgres delivery updates should advance updated_at like SQLite does."""
        conn = AsyncMock()
        acquire_cm = AsyncMock()
        acquire_cm.__aenter__.return_value = conn
        acquire_cm.__aexit__.return_value = False
        pool = MagicMock()
        pool.acquire.return_value = acquire_cm
        store = PostgresWebhookConfigStore(pool)

        await store.record_delivery_async("webhook-123", 200, success=True)

        query = conn.execute.await_args.args[0]
        assert "updated_at = NOW()" in query

        conn.reset_mock()
        await store.record_delivery_async("webhook-123", 500, success=False)

        query = conn.execute.await_args.args[0]
        assert "updated_at = NOW()" in query

    @pytest.mark.asyncio
    async def test_update_async_returns_durable_revision_timestamp(self) -> None:
        """Returned updated_at should match the durable revision written to Postgres."""
        conn = AsyncMock()
        conn.execute.return_value = "UPDATE 1"
        acquire_cm = AsyncMock()
        acquire_cm.__aenter__.return_value = conn
        acquire_cm.__aexit__.return_value = False
        pool = MagicMock()
        pool.acquire.return_value = acquire_cm
        store = PostgresWebhookConfigStore(pool)

        original = WebhookConfig(
            id="webhook-123",
            url="https://example.com/hook",
            events=["debate_end"],
            secret="secret",
            updated_at=100.0,
        )
        revised_at = 200.0
        durable = WebhookConfig(
            id="webhook-123",
            url="https://example.com/new",
            events=["debate_end"],
            secret="secret",
            updated_at=revised_at,
        )
        get_async = AsyncMock(side_effect=[original, durable])

        with (
            patch.object(store, "get_async", get_async),
            patch("aragora.storage.webhook_config_store.time.time", return_value=revised_at),
        ):
            updated = await store.update_async("webhook-123", url="https://example.com/new")

        assert updated is not None
        assert updated.url == "https://example.com/new"
        assert updated.updated_at == revised_at
        assert get_async.await_count == 2
        query, *params = conn.execute.await_args.args
        assert "updated_at = to_timestamp($2)" in query
        assert params == ["https://example.com/new", revised_at, "webhook-123"]

    @pytest.mark.asyncio
    async def test_update_async_returns_durable_boolean_state_after_postgres_coercion(self) -> None:
        """Returned active flag should reflect durable Postgres truth, not the input payload type."""
        conn = AsyncMock()
        conn.execute.return_value = "UPDATE 1"
        acquire_cm = AsyncMock()
        acquire_cm.__aenter__.return_value = conn
        acquire_cm.__aexit__.return_value = False
        pool = MagicMock()
        pool.acquire.return_value = acquire_cm
        store = PostgresWebhookConfigStore(pool)

        original = WebhookConfig(
            id="webhook-123",
            url="https://example.com/hook",
            events=["debate_end"],
            secret="secret",
            active=True,
            updated_at=100.0,
        )
        revised_at = 200.0
        durable = WebhookConfig(
            id="webhook-123",
            url="https://example.com/hook",
            events=["debate_end"],
            secret="secret",
            active=False,
            updated_at=revised_at,
        )
        get_async = AsyncMock(side_effect=[original, durable])

        with (
            patch.object(store, "get_async", get_async),
            patch("aragora.storage.webhook_config_store.time.time", return_value=revised_at),
        ):
            updated = await store.update_async("webhook-123", active="false")

        assert updated is not None
        assert updated.active is False
        assert updated.updated_at == revised_at
        assert get_async.await_count == 2
        query, *params = conn.execute.await_args.args
        assert "active = $1" in query
        assert params == ["false", revised_at, "webhook-123"]

    @pytest.mark.asyncio
    async def test_update_async_returns_none_when_row_is_deleted_before_write(self) -> None:
        """A concurrent delete must not surface a phantom successful Postgres update."""
        conn = AsyncMock()
        conn.execute.return_value = "UPDATE 0"
        acquire_cm = AsyncMock()
        acquire_cm.__aenter__.return_value = conn
        acquire_cm.__aexit__.return_value = False
        pool = MagicMock()
        pool.acquire.return_value = acquire_cm
        store = PostgresWebhookConfigStore(pool)

        original = WebhookConfig(
            id="webhook-123",
            url="https://example.com/hook",
            events=["debate_end"],
            secret="secret",
            updated_at=100.0,
        )
        revised_at = 200.0

        with (
            patch.object(store, "get_async", AsyncMock(return_value=original)),
            patch("aragora.storage.webhook_config_store.time.time", return_value=revised_at),
        ):
            updated = await store.update_async("webhook-123", url="https://example.com/new")

        assert updated is None
        query, *params = conn.execute.await_args.args
        assert "updated_at = to_timestamp($2)" in query
        assert params == ["https://example.com/new", revised_at, "webhook-123"]

    def test_row_to_config_accepts_native_jsonb_sequence(self, postgres_store) -> None:
        """Postgres JSONB rows may already be decoded into Python sequences."""
        now = time.time()
        row = {
            "id": "webhook-123",
            "url": "https://example.com/hook",
            "events_json": ["debate_end", "vote"],
            "secret": "plain-secret",
            "active": True,
            "created_at": now,
            "updated_at": now,
            "name": "Example Hook",
            "description": "Example description",
            "last_delivery_at": None,
            "last_delivery_status": None,
            "delivery_count": 0,
            "failure_count": 0,
            "user_id": "user-123",
            "workspace_id": "ws-123",
        }

        config = postgres_store._row_to_config(row)

        assert config.id == "webhook-123"
        assert config.events == ["debate_end", "vote"]
        assert config.user_id == "user-123"
        assert config.workspace_id == "ws-123"


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestGetWebhookConfigStore:
    """Tests for get_webhook_config_store factory function."""

    def test_default_is_sqlite(self, tmp_path):
        """Test that default backend is SQLite."""
        with patch.dict(os.environ, {"ARAGORA_DATA_DIR": str(tmp_path)}, clear=False):
            reset_webhook_config_store()
            store = get_webhook_config_store()
            assert isinstance(store, SQLiteWebhookConfigStore)

    def test_memory_backend(self, tmp_path):
        """Test in-memory backend selection."""
        with patch.dict(
            os.environ,
            {"ARAGORA_WEBHOOK_CONFIG_STORE_BACKEND": "memory", "ARAGORA_DATA_DIR": str(tmp_path)},
            clear=False,
        ):
            reset_webhook_config_store()
            store = get_webhook_config_store()
            assert isinstance(store, InMemoryWebhookConfigStore)

    def test_redis_backend(self, tmp_path):
        """Test Redis backend selection via environment variable."""
        with patch.dict(
            os.environ,
            {
                "ARAGORA_WEBHOOK_CONFIG_STORE_BACKEND": "redis",
                "ARAGORA_DATA_DIR": str(tmp_path),
            },
            clear=False,
        ):
            reset_webhook_config_store()
            store = get_webhook_config_store()
            assert isinstance(store, RedisWebhookConfigStore)

    def test_singleton_behavior(self, tmp_path):
        """Test that factory returns singleton."""
        with patch.dict(os.environ, {"ARAGORA_DATA_DIR": str(tmp_path)}, clear=False):
            reset_webhook_config_store()
            store1 = get_webhook_config_store()
            store2 = get_webhook_config_store()
            assert store1 is store2

    def test_set_webhook_config_store(self):
        """Test setting a custom store."""
        custom_store = InMemoryWebhookConfigStore()
        set_webhook_config_store(custom_store)
        assert get_webhook_config_store() is custom_store

    def test_reset_webhook_config_store(self, tmp_path):
        """Test that reset clears the singleton."""
        with patch.dict(os.environ, {"ARAGORA_DATA_DIR": str(tmp_path)}, clear=False):
            store1 = get_webhook_config_store()
            reset_webhook_config_store()
            store2 = get_webhook_config_store()
            assert store1 is not store2

    def test_set_store_overrides_factory(self, tmp_path):
        """Test that set_webhook_config_store overrides factory selection."""
        with patch.dict(os.environ, {"ARAGORA_DATA_DIR": str(tmp_path)}, clear=False):
            reset_webhook_config_store()
            # First call creates a SQLite store
            default_store = get_webhook_config_store()
            assert isinstance(default_store, SQLiteWebhookConfigStore)

            # Override with custom store
            custom_store = InMemoryWebhookConfigStore()
            set_webhook_config_store(custom_store)
            assert get_webhook_config_store() is custom_store
            assert not isinstance(get_webhook_config_store(), SQLiteWebhookConfigStore)

    def test_set_webhook_config_store_closes_previous_store(self):
        """Replacing global store closes previous instance."""
        first = InMemoryWebhookConfigStore()
        second = InMemoryWebhookConfigStore()
        first.close = MagicMock()  # type: ignore[method-assign]
        second.close = MagicMock()  # type: ignore[method-assign]

        set_webhook_config_store(first)
        set_webhook_config_store(second)

        first.close.assert_called_once()
        second.close.assert_not_called()
        reset_webhook_config_store()
        second.close.assert_called_once()


# =============================================================================
# WEBHOOK_EVENTS Tests
# =============================================================================


class TestWebhookEvents:
    """Tests for WEBHOOK_EVENTS set."""

    def test_events_not_empty(self):
        """Test that WEBHOOK_EVENTS is not empty."""
        assert len(WEBHOOK_EVENTS) > 0

    def test_contains_core_events(self):
        """Test that core events are present."""
        assert "debate_start" in WEBHOOK_EVENTS
        assert "debate_end" in WEBHOOK_EVENTS
        assert "consensus" in WEBHOOK_EVENTS
        assert "vote" in WEBHOOK_EVENTS
        assert "agent_message" in WEBHOOK_EVENTS
        assert "round_start" in WEBHOOK_EVENTS

    def test_contains_knowledge_events(self):
        """Test that knowledge-related events are present."""
        assert "knowledge_indexed" in WEBHOOK_EVENTS
        assert "knowledge_queried" in WEBHOOK_EVENTS
        assert "mound_updated" in WEBHOOK_EVENTS

    def test_contains_gauntlet_events(self):
        """Test that gauntlet-related events are present."""
        assert "gauntlet_complete" in WEBHOOK_EVENTS
        assert "gauntlet_verdict" in WEBHOOK_EVENTS
        assert "receipt_ready" in WEBHOOK_EVENTS
        assert "receipt_exported" in WEBHOOK_EVENTS

    def test_contains_agent_events(self):
        """Test that agent-related events are present."""
        assert "agent_elo_updated" in WEBHOOK_EVENTS
        assert "agent_calibration_changed" in WEBHOOK_EVENTS
        assert "agent_fallback_triggered" in WEBHOOK_EVENTS

    def test_contains_verification_events(self):
        """Test that verification-related events are present."""
        assert "claim_verification_result" in WEBHOOK_EVENTS
        assert "formal_verification_result" in WEBHOOK_EVENTS

    def test_all_events_are_strings(self):
        """Test that all events are strings."""
        for event in WEBHOOK_EVENTS:
            assert isinstance(event, str)
            assert len(event) > 0

    def test_all_events_are_snake_case(self):
        """Test that all events follow snake_case convention."""
        for event in WEBHOOK_EVENTS:
            assert event == event.lower(), f"Event {event} should be lowercase"
            assert " " not in event, f"Event {event} should not contain spaces"

    def test_is_a_set(self):
        """Test that WEBHOOK_EVENTS is a set (no duplicates)."""
        assert isinstance(WEBHOOK_EVENTS, set)

    def test_event_count(self):
        """Test that we have a reasonable number of events."""
        # At least 20 events defined in the source
        assert len(WEBHOOK_EVENTS) >= 20


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestWebhookConfigStoreIntegration:
    """Integration-style tests covering multi-step workflows."""

    def test_full_lifecycle(self, in_memory_store):
        """Test complete webhook lifecycle: register, use, update, delete."""
        # Register
        webhook = in_memory_store.register(
            url="https://example.com/hook",
            events=["debate_end", "consensus"],
            name="Lifecycle Test",
            user_id="user-1",
        )
        assert webhook.active is True

        # Use (record deliveries)
        in_memory_store.record_delivery(webhook.id, 200, success=True)
        in_memory_store.record_delivery(webhook.id, 500, success=False)
        in_memory_store.record_delivery(webhook.id, 200, success=True)

        # Verify delivery tracking
        w = in_memory_store.get(webhook.id)
        assert w.delivery_count == 3
        assert w.failure_count == 1

        # Update
        in_memory_store.update(webhook.id, events=["debate_end"], name="Updated Hook")
        w = in_memory_store.get(webhook.id)
        assert w.events == ["debate_end"]
        assert w.name == "Updated Hook"

        # Deactivate
        in_memory_store.update(webhook.id, active=False)
        assert in_memory_store.get_for_event("debate_end") == []

        # Reactivate
        in_memory_store.update(webhook.id, active=True)
        assert len(in_memory_store.get_for_event("debate_end")) == 1

        # Delete
        assert in_memory_store.delete(webhook.id) is True
        assert in_memory_store.get(webhook.id) is None

    def test_multi_tenant_isolation(self, sqlite_store):
        """Test that webhooks from different tenants are properly isolated."""
        # Register webhooks for different users and workspaces
        sqlite_store.register(
            url="https://tenant1.com/hook",
            events=["debate_end"],
            user_id="user-1",
            workspace_id="ws-alpha",
        )
        sqlite_store.register(
            url="https://tenant2.com/hook",
            events=["debate_end"],
            user_id="user-2",
            workspace_id="ws-beta",
        )
        sqlite_store.register(
            url="https://tenant1-extra.com/hook",
            events=["vote"],
            user_id="user-1",
            workspace_id="ws-alpha",
        )

        # User filtering
        user1_hooks = sqlite_store.list(user_id="user-1")
        assert len(user1_hooks) == 2

        # Workspace filtering
        alpha_hooks = sqlite_store.list(workspace_id="ws-alpha")
        assert len(alpha_hooks) == 2

        # Combined filtering
        user2_beta = sqlite_store.list(user_id="user-2", workspace_id="ws-beta")
        assert len(user2_beta) == 1
        assert user2_beta[0].url == "https://tenant2.com/hook"

        # All webhooks
        all_hooks = sqlite_store.list()
        assert len(all_hooks) == 3

    def test_event_routing(self, in_memory_store):
        """Test that events route to correct webhooks."""
        in_memory_store.register(url="https://debates.com", events=["debate_start", "debate_end"])
        in_memory_store.register(url="https://votes.com", events=["vote", "consensus"])
        in_memory_store.register(url="https://all.com", events=["*"])

        debate_hooks = in_memory_store.get_for_event("debate_start")
        assert len(debate_hooks) == 2  # debates.com + all.com

        vote_hooks = in_memory_store.get_for_event("vote")
        assert len(vote_hooks) == 2  # votes.com + all.com

        knowledge_hooks = in_memory_store.get_for_event("knowledge_indexed")
        assert len(knowledge_hooks) == 1  # all.com only
