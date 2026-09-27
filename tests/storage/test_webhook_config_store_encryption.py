"""Encryption-service contract tests for the webhook configuration store.

The store reaches the encryption provider through narrow protocols. These tests
cover the provider being available, unavailable, and malformed, plus the
encrypt and decrypt paths, including legacy plaintext secrets.
"""

from __future__ import annotations

import logging
import typing

import pytest

from aragora.security import encryption as encryption_module
from aragora.storage import webhook_config_store as wcs

STORE_LOGGER = "aragora.storage.webhook_config_store"
CIPHERTEXT = "AAAA" + "x" * 60


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


@pytest.mark.skipif(not encryption_module.CRYPTO_AVAILABLE, reason="cryptography not installed")
class TestEncryptionAvailable:
    @pytest.fixture(autouse=True)
    def development_key(self, monkeypatch):
        monkeypatch.setenv("ARAGORA_ENV", "development")
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

    @pytest.mark.parametrize(
        "stored",
        [
            pytest.param("short-legacy-secret", id="short"),
            pytest.param("B" * 60, id="no-ciphertext-prefix"),
            pytest.param("AAAA" + "x" * 45, id="prefixed-but-49-chars"),
        ],
    )
    def test_decrypt_keeps_legacy_plaintext(self, provider, stored):
        service = _StubService()
        provider(service)
        assert wcs._decrypt_secret(stored) == stored
        assert service.decrypted == []
