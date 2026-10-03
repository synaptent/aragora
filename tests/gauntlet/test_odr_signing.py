"""Tests for ODR Ed25519 detached signing (ODR-2, issue #8225).

Two layers:
  1. Self-contained unit tests of the signer's contract (no cross-package
     dependency) — sign, manual Ed25519 verify over the raw digest, tamper
     detection, key_id formula, no-mutation, replace/append modes.
  2. A true round-trip against the SHIPPED verifier (``aragora_verify``),
     hard-failing when that package is not importable, proving producer and
     consumer are compatible — the whole point of #8225 (the verifier landed
     first via #8388).
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
from pathlib import Path

import pytest

from aragora.gauntlet.odr_export import odr_content_digest
from aragora.gauntlet.odr_signing import (
    DEFAULT_SIGNING_KEY_SECRET,
    ODR_SIGNATURE_ALG,
    SIGNING_KEY_SECRET_ENV,
    OdrSigningError,
    OdrSigningUnconfiguredError,
    compute_key_id,
    generate_signing_key,
    load_private_key_from_pem,
    load_signing_key_from_secrets,
    public_key_pem,
    sign_odr_receipt,
)

cryptography = pytest.importorskip("cryptography")
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PublicKey,
)


def _valid_odr() -> dict:
    """A schema-conformant unsigned ODR v0.1 doc (mirrors aragora-verify fixture)."""
    return {
        "odr_version": "0.1",
        "profile": "https://aragora.ai/specs/open-decision-receipt/v0.1",
        "receipt_id": "rcpt-0001",
        "issued_at": "2026-06-14T00:00:00Z",
        "subject": {
            "identifier": "5f1b14e4b5e113dc978d60d1f6bd21b5a478c744",
            "digest": {"status": "present", "alg": "sha-256", "value": "deadbeef"},
            "summary": "PR #8360",
        },
        "claim": {"verdict": "PASS", "statement": "merge PR #8360"},
        "reasoning": {"status": "present", "summary": "all required checks green"},
        "quorum": {
            "status": "present",
            "method": "majority",
            "reached": True,
            "supporting_agents": ["claude", "grok"],
            "participants": [
                {"agent": "claude", "model_family": "anthropic", "model_id": "claude-opus-4-8"},
                {"agent": "grok", "model_family": "xai", "model_id": "grok-4"},
            ],
            "independence": {
                "disclosed": True,
                "distinct_model_families": 2,
                "model_families": ["anthropic", "xai"],
            },
            "dissent": {"present": False, "dissenting_agents": [], "views": []},
        },
        "confidence": {
            "status": "present",
            "value": 0.9,
            "scale": "unit_interval",
            "calibration": {"status": "absent", "reason": "no calibration record"},
        },
        "cruxes": {"status": "absent", "reason": "no crux set supplied"},
        "attestation": {"disposition": "autonomous"},
        "routing": {"status": "reserved"},
        "signatures": [],
    }


def _pub_raw(public_key: Ed25519PublicKey) -> bytes:
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


# ----------------------------------------------------------------------------
# Contract unit tests (self-contained)
# ----------------------------------------------------------------------------


def test_signature_entry_shape() -> None:
    key = generate_signing_key()
    signed = sign_odr_receipt(_valid_odr(), key)
    assert len(signed["signatures"]) == 1
    entry = signed["signatures"][0]
    assert set(entry) == {"alg", "key_id", "signature"}
    assert entry["alg"] == ODR_SIGNATURE_ALG == "Ed25519"
    assert entry["key_id"].startswith("ed25519-")
    # raw 64-byte Ed25519 signature, base64-encoded
    assert len(base64.b64decode(entry["signature"])) == 64


def test_signs_the_raw_digest_message() -> None:
    key = generate_signing_key()
    signed = sign_odr_receipt(_valid_odr(), key)
    # The verifier checks the signature over bytes.fromhex(digest), not the
    # canonical bytes and not the hex string. Confirm that exact contract.
    message = bytes.fromhex(odr_content_digest(signed))
    sig = base64.b64decode(signed["signatures"][0]["signature"])
    key.public_key().verify(sig, message)  # raises InvalidSignature on mismatch


def test_key_id_matches_verifier_formula() -> None:
    key = generate_signing_key()
    expected = "ed25519-" + hashlib.sha256(_pub_raw(key.public_key())).hexdigest()[:16]
    assert compute_key_id(key.public_key()) == expected
    assert sign_odr_receipt(_valid_odr(), key)["signatures"][0]["key_id"] == expected


def test_input_is_not_mutated() -> None:
    key = generate_signing_key()
    original = _valid_odr()
    sign_odr_receipt(original, key)
    assert original["signatures"] == []


def test_signed_receipt_is_deep_copied_from_input() -> None:
    key = generate_signing_key()
    original = _valid_odr()
    signed = sign_odr_receipt(original, key)

    original["claim"]["statement"] = "mutated after signing"
    original["subject"]["digest"]["value"] = "cafebabe"

    assert signed["claim"]["statement"] == "merge PR #8360"
    assert signed["subject"]["digest"]["value"] == "deadbeef"
    sig = base64.b64decode(signed["signatures"][0]["signature"])
    key.public_key().verify(sig, bytes.fromhex(odr_content_digest(signed)))


def test_tampering_invalidates_signature() -> None:
    key = generate_signing_key()
    signed = sign_odr_receipt(_valid_odr(), key)
    tampered = dict(signed)
    tampered["claim"] = {"verdict": "PASS", "statement": "merge a DIFFERENT PR"}
    sig = base64.b64decode(tampered["signatures"][0]["signature"])
    from cryptography.exceptions import InvalidSignature

    with pytest.raises(InvalidSignature):
        key.public_key().verify(sig, bytes.fromhex(odr_content_digest(tampered)))


def test_append_mode_preserves_prior_signature() -> None:
    k1, k2 = generate_signing_key(), generate_signing_key()
    once = sign_odr_receipt(_valid_odr(), k1)
    twice = sign_odr_receipt(once, k2)
    assert len(twice["signatures"]) == 2
    msg = bytes.fromhex(odr_content_digest(twice))
    # both signatures still verify (digest excludes the signatures array)
    k1.public_key().verify(base64.b64decode(twice["signatures"][0]["signature"]), msg)
    k2.public_key().verify(base64.b64decode(twice["signatures"][1]["signature"]), msg)


def test_replace_mode_drops_prior_signatures() -> None:
    k1, k2 = generate_signing_key(), generate_signing_key()
    once = sign_odr_receipt(_valid_odr(), k1)
    replaced = sign_odr_receipt(once, k2, replace=True)
    assert len(replaced["signatures"]) == 1
    assert replaced["signatures"][0]["key_id"] == compute_key_id(k2.public_key())


def test_append_mode_rejects_invalid_existing_signatures() -> None:
    key = generate_signing_key()
    odr = _valid_odr()
    odr["signatures"] = [{"alg": "Ed25519", "key_id": "ed25519-old"}]

    with pytest.raises(OdrSigningError, match="existing signatures\\[0\\]"):
        sign_odr_receipt(odr, key)


def test_replace_mode_drops_invalid_existing_signatures() -> None:
    key = generate_signing_key()
    odr = _valid_odr()
    odr["signatures"] = [{"alg": "Ed25519", "key_id": "ed25519-old"}]

    signed = sign_odr_receipt(odr, key, replace=True)

    assert len(signed["signatures"]) == 1
    assert signed["signatures"][0]["key_id"] == compute_key_id(key.public_key())


def test_pem_round_trip() -> None:
    key = generate_signing_key()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    reloaded = load_private_key_from_pem(pem)
    assert compute_key_id(reloaded.public_key()) == compute_key_id(key.public_key())


def test_rejects_non_ed25519_pem() -> None:
    from cryptography.hazmat.primitives.asymmetric import rsa

    rsa_pem = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )
    with pytest.raises(OdrSigningError):
        load_private_key_from_pem(rsa_pem)


def test_public_key_pem_is_publishable_spki() -> None:
    key = generate_signing_key()
    pem = public_key_pem(key)
    assert "BEGIN PUBLIC KEY" in pem
    loaded = serialization.load_pem_public_key(pem.encode())
    assert isinstance(loaded, Ed25519PublicKey)


def test_load_signing_key_from_standalone_aws_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from aragora.config.secrets import SecretManager, SecretsConfig

    key = generate_signing_key()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    class DummyClient:
        def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
            assert SecretId == DEFAULT_SIGNING_KEY_SECRET
            return {"SecretString": pem}

    monkeypatch.setattr(
        SecretsConfig,
        "from_env",
        classmethod(
            lambda cls: cls(
                use_aws=True,
                aws_region="us-east-1",
                aws_regions=["us-east-1"],
            )
        ),
    )
    monkeypatch.setattr(SecretManager, "_get_aws_client", lambda self, region: DummyClient())

    loaded = load_signing_key_from_secrets()
    assert compute_key_id(loaded.public_key()) == compute_key_id(key.public_key())


def test_load_signing_key_from_binary_aws_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from aragora.config.secrets import SecretManager, SecretsConfig

    key = generate_signing_key()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    class DummyClient:
        def get_secret_value(self, *, SecretId: str) -> dict[str, bytes]:
            assert SecretId == DEFAULT_SIGNING_KEY_SECRET
            return {"SecretBinary": pem}

    monkeypatch.setattr(
        SecretsConfig,
        "from_env",
        classmethod(
            lambda cls: cls(
                use_aws=True,
                aws_region="us-east-1",
                aws_regions=["us-east-1"],
            )
        ),
    )
    monkeypatch.setattr(SecretManager, "_get_aws_client", lambda self, region: DummyClient())

    loaded = load_signing_key_from_secrets()
    assert compute_key_id(loaded.public_key()) == compute_key_id(key.public_key())


def test_empty_aws_region_falls_through_to_next_region(monkeypatch: pytest.MonkeyPatch) -> None:
    from aragora.config.secrets import SecretManager, SecretsConfig

    key = generate_signing_key()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    class DummyClient:
        def __init__(self, region: str) -> None:
            self.region = region

        def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
            assert SecretId == DEFAULT_SIGNING_KEY_SECRET
            if self.region == "us-east-1":
                return {"SecretString": ""}
            return {"SecretString": pem}

    monkeypatch.setattr(
        SecretsConfig,
        "from_env",
        classmethod(
            lambda cls: cls(
                use_aws=True,
                aws_region="us-east-1",
                aws_regions=["us-east-1", "us-west-2"],
            )
        ),
    )
    monkeypatch.setattr(
        SecretManager,
        "_get_aws_client",
        lambda self, region: DummyClient(region),
    )

    loaded = load_signing_key_from_secrets()
    assert compute_key_id(loaded.public_key()) == compute_key_id(key.public_key())


def test_load_signing_key_rejects_raw_env_pem_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from aragora.config.secrets import SecretManager, SecretsConfig

    key = generate_signing_key()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    class UnexpectedClient:
        def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
            raise AssertionError("raw PEM must be rejected before any AWS request")

    monkeypatch.setattr(
        SecretsConfig,
        "from_env",
        classmethod(
            lambda cls: cls(
                use_aws=True,
                aws_region="us-east-1",
                aws_regions=["us-east-1"],
            )
        ),
    )
    monkeypatch.setattr(SecretManager, "_get_aws_client", lambda self, region: UnexpectedClient())
    monkeypatch.setenv(SIGNING_KEY_SECRET_ENV, pem)

    with pytest.raises(OdrSigningError, match="appears to contain raw key material") as exc:
        load_signing_key_from_secrets()

    assert "BEGIN PRIVATE KEY" not in str(exc.value)


def test_load_signing_key_requires_aws_secret_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aragora.config.secrets import SecretsConfig

    monkeypatch.setattr(
        SecretsConfig,
        "from_env",
        classmethod(lambda cls: cls(use_aws=False)),
    )

    with pytest.raises(OdrSigningError, match="AWS Secrets Manager is not enabled"):
        load_signing_key_from_secrets()


def _not_found_client():
    from aragora.config.secrets import ClientError

    class NotFoundClient:
        def get_secret_value(self, *, SecretId: str) -> dict[str, str]:
            raise ClientError(
                {"Error": {"Code": "ResourceNotFoundException"}},
                "GetSecretValue",
            )

    return NotFoundClient()


def _aws_enabled_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from aragora.config.secrets import SecretsConfig

    monkeypatch.setattr(
        SecretsConfig,
        "from_env",
        classmethod(
            lambda cls: cls(
                use_aws=True,
                aws_region="us-east-1",
                aws_regions=["us-east-1"],
            )
        ),
    )


def test_default_secret_not_found_is_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The DEFAULT secret missing everywhere = key never provisioned (expected)."""
    from aragora.config.secrets import SecretManager

    _aws_enabled_config(monkeypatch)
    monkeypatch.setattr(SecretManager, "_get_aws_client", lambda self, region: _not_found_client())
    monkeypatch.delenv(SIGNING_KEY_SECRET_ENV, raising=False)

    with pytest.raises(OdrSigningUnconfiguredError, match="not provisioned yet"):
        load_signing_key_from_secrets()


def test_explicitly_named_secret_not_found_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator-named secret that is missing is a typo/deletion, never
    'unconfigured' — it must fail closed."""
    from aragora.config.secrets import SecretManager

    _aws_enabled_config(monkeypatch)
    monkeypatch.setattr(SecretManager, "_get_aws_client", lambda self, region: _not_found_client())
    monkeypatch.setenv(SIGNING_KEY_SECRET_ENV, "aragora/typoed-secret-name")

    with pytest.raises(OdrSigningError) as exc:
        load_signing_key_from_secrets()
    assert not isinstance(exc.value, OdrSigningUnconfiguredError)


def test_secrets_manager_disabled_is_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from aragora.config.secrets import SecretsConfig

    monkeypatch.setattr(
        SecretsConfig,
        "from_env",
        classmethod(lambda cls: cls(use_aws=False)),
    )
    monkeypatch.delenv(SIGNING_KEY_SECRET_ENV, raising=False)

    with pytest.raises(OdrSigningUnconfiguredError, match="AWS Secrets Manager is not enabled"):
        load_signing_key_from_secrets()


def test_secrets_manager_disabled_with_explicit_secret_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicitly named signing secret means signing is INTENDED: a
    disabled secrets backend is then a misconfiguration, not 'unconfigured'."""
    from aragora.config.secrets import SecretsConfig

    monkeypatch.setattr(
        SecretsConfig,
        "from_env",
        classmethod(lambda cls: cls(use_aws=False)),
    )
    monkeypatch.setenv(SIGNING_KEY_SECRET_ENV, "aragora/explicit-signing-key")

    with pytest.raises(OdrSigningError) as exc:
        load_signing_key_from_secrets()
    assert not isinstance(exc.value, OdrSigningUnconfiguredError)


def test_sign_odr_receipt_wraps_digest_errors() -> None:
    key = generate_signing_key()
    malformed = _valid_odr()
    malformed["claim"] = {"verdict": "PASS", "statement": {"not", "json"}}

    with pytest.raises(OdrSigningError, match="could not compute ODR content digest"):
        sign_odr_receipt(malformed, key)


# ----------------------------------------------------------------------------
# True round-trip against the SHIPPED verifier (skip if not installed)
# ----------------------------------------------------------------------------


def _load_real_verifier():
    try:
        from aragora_verify.verifier import verify  # noqa: PLC0415

        return verify
    except ModuleNotFoundError:
        # The verifier ships as a separate package under aragora-verify/src;
        # add it to the path for the in-repo round-trip.
        src = Path(__file__).resolve().parents[2] / "aragora-verify" / "src"
        if src.is_dir():
            sys.path.insert(0, str(src))
            try:
                from aragora_verify.verifier import verify  # noqa: PLC0415

                return verify
            except Exception:  # pragma: no cover - environment-dependent
                return None
    return None


def test_round_trip_against_shipped_verifier() -> None:
    verify = _load_real_verifier()
    if verify is None:
        raise AssertionError("aragora_verify must be importable for the ODR signing contract test")

    key = generate_signing_key()
    signed = sign_odr_receipt(_valid_odr(), key)

    result = verify(signed, public_key=key.public_key())
    sig_check = next((c for c in result.checks if c.name == "signature"), None)
    assert sig_check is not None and sig_check.status == "pass", (
        sig_check.detail if sig_check else "no signature check"
    )
    assert result.ok is True

    # And a wrong key must FAIL the signature check.
    other = generate_signing_key()
    bad = verify(signed, public_key=other.public_key())
    bad_sig = next((c for c in bad.checks if c.name == "signature"), None)
    assert bad_sig is not None and bad_sig.status == "fail"
