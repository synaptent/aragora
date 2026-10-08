"""Encryption-service contract tests for the webhook configuration store.

The store reaches the encryption provider through narrow protocols. These tests
cover the provider being available, unavailable, and malformed, plus the
encrypt and decrypt paths, including legacy plaintext secrets.
"""

from __future__ import annotations

import base64
import logging
import sqlite3
import typing

import pytest

from aragora.security import encryption as encryption_module
from aragora.storage import webhook_config_store as wcs

STORE_LOGGER = "aragora.storage.webhook_config_store"
# Same serialization as EncryptionService.encrypt(...).to_base64(); it starts with
# "AQ" (format byte 0x01), not "AAAA".
CIPHERTEXT = encryption_module.EncryptedData(
    ciphertext=bytes(range(48)),
    nonce=bytes(12),
    key_id="master",
    key_version=1,
    algorithm=encryption_module.EncryptionAlgorithm.AES_256_GCM,
).to_base64()
LEGACY_PLAINTEXT_SECRETS = [
    pytest.param("short-legacy-secret", id="short"),
    pytest.param("B" * 60, id="long-non-base64-header"),
    pytest.param("AAAA" + "x" * 45, id="prefixed-49-chars"),
    pytest.param("AAAA" + "x" * 60, id="prefixed-64-chars"),
    pytest.param("AQ" + "A" * 62, id="format-byte-without-header"),
]


class _StubEncrypted:
    def __init__(self, encoded: str) -> None:
        self.encoded = encoded

    def to_base64(self) -> str:
        return self.encoded


class _StubService:
    def __init__(self) -> None:
        self.encrypted: list[str] = []
        self.decrypted: list[str] = []

    def encrypt(self, plaintext: str) -> _StubEncrypted:
        self.encrypted.append(plaintext)
        return _StubEncrypted("AAAA-encoded-" + plaintext)

    def decrypt_string(self, encrypted: str) -> str:
        self.decrypted.append(encrypted)
        return "decrypted-secret"


class _NoBase64Service:
    def encrypt(self, plaintext: str) -> object:
        return object()


class _WrongSignatureService:
    def encrypt(self) -> _StubEncrypted:
        return _StubEncrypted("unused")


class _FailingDecryptService:
    def decrypt_string(self, encrypted: str) -> str:
        raise ValueError("bad ciphertext")


def _unexpected_provider_call() -> None:
    raise AssertionError("the encryption provider must not be consulted")


@pytest.fixture
def provider(monkeypatch):
    """Install an encryption provider (or ``None``) behind the store."""

    def _install(service: object) -> None:
        monkeypatch.setattr(wcs, "CRYPTO_AVAILABLE", True)
        monkeypatch.setattr(wcs, "get_encryption_service", lambda: service)

    return _install


@pytest.fixture
def required(monkeypatch):
    """Set whether encryption is required for the current test."""

    def _set(value: bool) -> None:
        monkeypatch.setattr(wcs, "is_encryption_required", lambda: value)

    return _set


class TestEncryptionServiceContract:
    def test_get_encryption_service_returns_protocol_or_none(self):
        hints = typing.get_type_hints(wcs.get_encryption_service)
        assert set(typing.get_args(hints["return"])) == {
            wcs._SecretEncryptionService,
            type(None),
        }

    def test_protocols_declare_the_methods_the_store_calls(self):
        assert callable(wcs._SecretEncryptionService.encrypt)
        assert callable(wcs._SecretEncryptionService.decrypt_string)
        assert callable(wcs._EncryptedSecret.to_base64)


class TestEncryptionAvailable:
    @pytest.fixture(autouse=True)
    def development_key(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENV", "development")
        monkeypatch.delenv("ARAGORA_SECRETS_STRICT", raising=False)
        monkeypatch.setenv("ARAGORA_ENCRYPTION_KEY", "0" * 64)
        monkeypatch.setattr(encryption_module, "_encryption_service", None)

    def test_default_provider_returns_a_working_service(self):
        service = wcs.get_encryption_service()
        assert service is not None
        encoded = service.encrypt("whsec-default").to_base64()
        assert isinstance(encoded, str)
        assert service.decrypt_string(encoded) == "whsec-default"

    def test_encrypt_secret_uses_the_real_service(self, required):
        required(True)
        stored = wcs._encrypt_secret("whsec-real")
        assert stored != "whsec-real"
        assert encryption_module.get_encryption_service().decrypt_string(stored) == "whsec-real"


class TestEncryptionUnavailable:
    def test_missing_service_fails_closed_when_required(self, provider, required):
        provider(None)
        required(True)
        with pytest.raises(wcs.EncryptionError) as exc_info:
            wcs._encrypt_secret("whsec-test")
        assert exc_info.value.operation == "encrypt"
        assert exc_info.value.reason == "encryption service not available"

    def test_missing_service_stores_plaintext_with_warning(self, provider, required, caplog):
        provider(None)
        required(False)
        with caplog.at_level(logging.WARNING, logger=STORE_LOGGER):
            assert wcs._encrypt_secret("whsec-test") == "whsec-test"
        assert any(
            "storing unencrypted" in r.getMessage()
            and "encryption service not available" in r.getMessage()
            for r in caplog.records
        )

    def test_missing_service_returns_ciphertext_unchanged(self, provider):
        provider(None)
        assert wcs._decrypt_secret(CIPHERTEXT) == CIPHERTEXT

    def test_provider_error_fails_closed_when_required(self, monkeypatch, required):
        def _raise() -> None:
            raise wcs.EncryptionError("init", "ARAGORA_ENCRYPTION_KEY missing", "encryption")

        monkeypatch.setattr(wcs, "CRYPTO_AVAILABLE", True)
        monkeypatch.setattr(wcs, "get_encryption_service", _raise)
        required(True)
        with pytest.raises(wcs.EncryptionError) as exc_info:
            wcs._encrypt_secret("whsec-test")
        assert exc_info.value.operation == "encrypt"
        assert isinstance(exc_info.value.__cause__, wcs.EncryptionError)

    def test_provider_error_stores_plaintext_with_warning(self, monkeypatch, required, caplog):
        def _raise() -> None:
            raise OSError("key store unreachable")

        monkeypatch.setattr(wcs, "CRYPTO_AVAILABLE", True)
        monkeypatch.setattr(wcs, "get_encryption_service", _raise)
        required(False)
        with caplog.at_level(logging.WARNING, logger=STORE_LOGGER):
            assert wcs._encrypt_secret("whsec-test") == "whsec-test"
        assert any("key store unreachable" in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("is_required", [True, False])
    def test_missing_crypto_library_skips_the_provider(self, monkeypatch, required, is_required):
        monkeypatch.setattr(wcs, "CRYPTO_AVAILABLE", False)
        monkeypatch.setattr(wcs, "get_encryption_service", _unexpected_provider_call)
        required(is_required)
        if is_required:
            with pytest.raises(wcs.EncryptionError, match="cryptography library not available"):
                wcs._encrypt_secret("whsec-test")
        else:
            assert wcs._encrypt_secret("whsec-test") == "whsec-test"
        assert wcs._decrypt_secret(CIPHERTEXT) == CIPHERTEXT


MALFORMED_ENCRYPT_PROVIDERS = [
    pytest.param(object(), id="no-encrypt-method"),
    pytest.param(_NoBase64Service(), id="result-without-to-base64"),
    pytest.param(_WrongSignatureService(), id="encrypt-wrong-signature"),
]


class TestMalformedProvider:
    @pytest.mark.parametrize("service", MALFORMED_ENCRYPT_PROVIDERS)
    def test_encrypt_fails_closed_when_required(self, provider, required, service):
        provider(service)
        required(True)
        with pytest.raises(wcs.EncryptionError) as exc_info:
            wcs._encrypt_secret("whsec-test")
        assert exc_info.value.operation == "encrypt"

    @pytest.mark.parametrize("service", MALFORMED_ENCRYPT_PROVIDERS)
    def test_encrypt_stores_plaintext_with_warning(self, provider, required, caplog, service):
        provider(service)
        required(False)
        with caplog.at_level(logging.WARNING, logger=STORE_LOGGER):
            assert wcs._encrypt_secret("whsec-test") == "whsec-test"
        assert any("storing unencrypted" in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize(
        "service",
        [
            pytest.param(object(), id="no-decrypt-method"),
            pytest.param(_FailingDecryptService(), id="decrypt-raises"),
        ],
    )
    def test_decrypt_returns_stored_value(self, provider, service):
        provider(service)
        assert wcs._decrypt_secret(CIPHERTEXT) == CIPHERTEXT


class TestEncryptDecrypt:
    def test_encrypt_stores_the_service_base64(self, provider, required):
        service = _StubService()
        provider(service)
        required(True)
        assert wcs._encrypt_secret("whsec-test") == "AAAA-encoded-whsec-test"
        assert service.encrypted == ["whsec-test"]

    def test_encrypt_empty_secret_skips_the_provider(self, monkeypatch):
        monkeypatch.setattr(wcs, "get_encryption_service", _unexpected_provider_call)
        assert wcs._encrypt_secret("") == ""

    def test_decrypt_routes_ciphertext_through_the_service(self, provider):
        service = _StubService()
        provider(service)
        assert wcs._decrypt_secret(CIPHERTEXT) == "decrypted-secret"
        assert service.decrypted == [CIPHERTEXT]

    @pytest.mark.parametrize("stored", LEGACY_PLAINTEXT_SECRETS)
    def test_decrypt_keeps_legacy_plaintext(self, provider, stored):
        service = _StubService()
        provider(service)
        assert wcs._decrypt_secret(stored) == stored
        assert service.decrypted == []


class TestRealEncryptionRoundTrip:
    """Secrets encrypted by the real EncryptionService must read back as plaintext."""

    @pytest.fixture(autouse=True)
    def development_key(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENV", "development")
        monkeypatch.delenv("ARAGORA_SECRETS_STRICT", raising=False)
        monkeypatch.setenv("ARAGORA_ENCRYPTION_KEY", "0" * 64)
        monkeypatch.setattr(encryption_module, "_encryption_service", None)

    @staticmethod
    def _stored_secret(db_path, webhook_id: str) -> str:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT secret FROM webhook_configs WHERE id = ?", (webhook_id,)
            ).fetchone()
        finally:
            conn.close()
        return row[0]

    @staticmethod
    def _set_stored_secret(db_path, webhook_id: str, secret: str) -> None:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("UPDATE webhook_configs SET secret = ? WHERE id = ?", (secret, webhook_id))
            conn.commit()
        finally:
            conn.close()

    def test_decrypt_secret_returns_the_plaintext(self):
        stored = encryption_module.get_encryption_service().encrypt("whsec-real").to_base64()
        assert wcs._decrypt_secret(stored) == "whsec-real"

    def test_sqlite_store_reload_returns_the_registered_secret(self, tmp_path):
        db_path = tmp_path / "webhooks.db"
        store = wcs.SQLiteWebhookConfigStore(db_path)
        registered = store.register(url="https://example.com/hook", events=["debate_end"])
        store.close()

        stored = self._stored_secret(db_path, registered.id)
        assert stored != registered.secret
        assert encryption_module.get_encryption_service().decrypt_string(stored) == (
            registered.secret
        )

        reopened = wcs.SQLiteWebhookConfigStore(db_path)
        try:
            reloaded = reopened.get(registered.id)
            assert reloaded is not None
            assert reloaded.secret == registered.secret
            assert [w.secret for w in reopened.get_for_event("debate_end")] == [registered.secret]
        finally:
            reopened.close()

    def test_sqlite_update_keeps_a_single_encryption_layer(self, tmp_path):
        db_path = tmp_path / "webhooks.db"
        store = wcs.SQLiteWebhookConfigStore(db_path)
        try:
            registered = store.register(url="https://example.com/hook", events=["debate_end"])
            stored_before = self._stored_secret(db_path, registered.id)
            assert store.update(registered.id, name="renamed") is not None
            assert self._stored_secret(db_path, registered.id) == stored_before
            reloaded = store.get(registered.id)
            assert reloaded is not None
            assert reloaded.secret == registered.secret
        finally:
            store.close()

    @pytest.mark.parametrize("legacy", LEGACY_PLAINTEXT_SECRETS)
    def test_sqlite_store_returns_legacy_plaintext_unchanged(self, tmp_path, legacy):
        db_path = tmp_path / "webhooks.db"
        store = wcs.SQLiteWebhookConfigStore(db_path)
        registered = store.register(url="https://example.com/hook", events=["debate_end"])
        store.close()
        self._set_stored_secret(db_path, registered.id, legacy)

        reopened = wcs.SQLiteWebhookConfigStore(db_path)
        try:
            reloaded = reopened.get(registered.id)
            assert reloaded is not None
            assert reloaded.secret == legacy
        finally:
            reopened.close()

    def test_redis_cache_payload_round_trips_the_secret(self):
        webhook = wcs.WebhookConfig(
            id="wh-cache",
            url="https://example.com/hook",
            events=["debate_end"],
            secret="whsec-cache",
        )
        payload = wcs.RedisWebhookConfigStore._serialize_for_cache(webhook)
        assert "whsec-cache" not in payload
        restored = wcs.RedisWebhookConfigStore._deserialize_from_cache(payload)
        assert restored.secret == "whsec-cache"

    def test_tampered_ciphertext_returns_stored_value_with_debug_log(self, caplog):
        stored = encryption_module.get_encryption_service().encrypt("whsec-real").to_base64()
        raw = bytearray(base64.b64decode(stored))
        raw[-1] ^= 0x01
        tampered = base64.b64encode(bytes(raw)).decode("ascii")

        with caplog.at_level(logging.DEBUG, logger=STORE_LOGGER):
            assert wcs._decrypt_secret(tampered) == tampered
        assert any("Secret decryption failed" in r.getMessage() for r in caplog.records)

    def test_truncated_ciphertext_returns_stored_value(self):
        stored = encryption_module.get_encryption_service().encrypt("whsec-real").to_base64()
        truncated = stored[:-8]
        assert wcs._decrypt_secret(truncated) == truncated
