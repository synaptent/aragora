"""Focused fail-closed tests for provider-neutral ODR key custody."""

from __future__ import annotations

import base64

import pytest

from aragora.gauntlet.odr_signing import (
    SIGNING_KEY_SECRET_ENV,
    OdrSigningError,
    load_signing_key_from_secrets,
)


def test_one_line_encoded_key_is_rejected_without_reflection(monkeypatch) -> None:
    encoded_key = base64.b64encode(b"-----BEGIN PRIVATE KEY-----raw-material").decode()
    monkeypatch.setenv(SIGNING_KEY_SECRET_ENV, encoded_key)
    monkeypatch.delenv("ARAGORA_SECRETS_DIR", raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "true")

    with pytest.raises(OdrSigningError, match="appears to contain raw key material") as exc:
        load_signing_key_from_secrets()

    assert encoded_key not in str(exc.value)


def test_long_path_style_secret_identifier_is_not_key_material(monkeypatch) -> None:
    from aragora.gauntlet.odr_signing import _secret_id_contains_key_material

    secret_id = "aragora/production/odr-signing-key-rotation-2026-08-29-primary"
    assert _secret_id_contains_key_material(secret_id) is False


def test_explicit_argument_bypasses_mounted_default(monkeypatch) -> None:
    import aragora.gauntlet.odr_signing as signing

    monkeypatch.setattr(
        signing,
        "_load_pem_secret_from_aws",
        lambda secret_id, explicitly_named: (
            "aws-pem" if secret_id == "explicit-id" and explicitly_named else None
        ),
    )
    monkeypatch.setattr(signing, "_load_pem_from_mounted_custody", lambda: "mounted-pem")
    monkeypatch.setattr(signing, "load_private_key_from_pem", lambda pem: pem)

    assert load_signing_key_from_secrets(secret_name="explicit-id") == "aws-pem"


def test_explicit_secret_identifier_is_redacted_on_failure(monkeypatch) -> None:
    from aragora.config.secrets import SecretManager, SecretsConfig

    secret_id = "production/odr-signing-key"

    class FailingClient:
        def get_secret_value(self, *, SecretId: str):
            assert SecretId == secret_id
            raise RuntimeError("backend unavailable")

    monkeypatch.setattr(
        SecretsConfig,
        "from_env",
        classmethod(lambda cls: cls(use_aws=True, aws_regions=["us-east-1"])),
    )
    monkeypatch.setattr(SecretManager, "_get_aws_client", lambda self, region: FailingClient())
    monkeypatch.setenv(SIGNING_KEY_SECRET_ENV, secret_id)

    with pytest.raises(OdrSigningError) as exc:
        load_signing_key_from_secrets()

    assert secret_id not in str(exc.value)
    assert "<redacted-secret-id>" in str(exc.value)
