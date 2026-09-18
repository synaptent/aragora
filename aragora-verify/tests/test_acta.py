"""ACTA-02 projections in the standalone verifier: module parity, checks, CLI.

``aragora_verify.acta`` is a verbatim copy of
``aragora/gauntlet/odr_acta_projection.py`` so a stranger can verify a
projection with nothing but this package and ``cryptography``.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from _fixtures import valid_odr
from aragora_verify import compute_key_id, odr_content_digest
from aragora_verify.acta import (
    ACTA_CHAIN_SCOPE,
    ACTA_PAYLOAD_TYPE,
    ACTA_SIGNATURE_ALG,
    GENESIS_PREVIOUS_RECEIPT_HASH,
    acta_envelope_hash,
    project_to_acta,
    verify_acta_projection,
)
from aragora_verify.cli import main
from aragora_verify.jcs import jcs_canonicalize, odr_signature_message

_COPY = Path(__file__).resolve().parents[1] / "src" / "aragora_verify" / "acta.py"
_IN_TREE = Path(__file__).resolve().parents[2] / "aragora" / "gauntlet" / "odr_acta_projection.py"

_PUBKEY_PEM = "pubkey.pem"


def _key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def _signed_v02_odr(private_key: Ed25519PrivateKey) -> dict[str, Any]:
    """A v0.2 ODR document signed with the §6 v0.2 construction."""
    doc = valid_odr("0.2")
    doc["profile"] = "https://aragora.ai/specs/open-decision-receipt/v0.2"
    entry = {
        "alg": "Ed25519",
        "key_id": compute_key_id(private_key.public_key()),
        "issuer": "aragora",
        "role": "emitter",
        "signed_at": "2026-06-14T00:00:01Z",
    }
    message = odr_signature_message(odr_content_digest(doc), doc["odr_version"], entry)
    signed = copy.deepcopy(doc)
    signed["signatures"] = [
        {**entry, "signature": base64.b64encode(private_key.sign(message)).decode("ascii")}
    ]
    return signed


@pytest.fixture
def private_key() -> Ed25519PrivateKey:
    return _key()


@pytest.fixture
def odr(private_key: Ed25519PrivateKey) -> dict[str, Any]:
    return _signed_v02_odr(private_key)


@pytest.fixture
def pubkey_file(tmp_path: Path, private_key: Ed25519PrivateKey) -> Path:
    from cryptography.hazmat.primitives import serialization

    path = tmp_path / _PUBKEY_PEM
    path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    return path


@pytest.fixture
def projection(tmp_path: Path, odr: dict[str, Any], private_key: Ed25519PrivateKey):
    """Write an ODR document and its genesis projection; return both paths."""
    kid = compute_key_id(private_key.public_key())
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)
    odr_path = tmp_path / "receipt.odr.json"
    acta_path = tmp_path / "receipt.acta.json"
    odr_path.write_bytes(jcs_canonicalize(odr))
    acta_path.write_bytes(jcs_canonicalize(envelope))
    return odr_path, acta_path


# ---------------------------------------------------------------------------
# The two copies must not drift
# ---------------------------------------------------------------------------


def test_bundled_acta_module_exists() -> None:
    assert _COPY.is_file(), _COPY


def test_bundled_acta_module_is_byte_identical_to_the_in_tree_copy() -> None:
    if not _IN_TREE.is_file():
        pytest.skip(f"in-tree module not present at {_IN_TREE} (standalone checkout)")
    assert _COPY.read_bytes() == _IN_TREE.read_bytes(), (
        f"{_COPY} and {_IN_TREE} have drifted; the ACTA projection module is "
        "duplicated verbatim so the standalone verifier needs no aragora install"
    )


def test_bundled_acta_module_does_not_import_aragora() -> None:
    source = _COPY.read_text(encoding="utf-8")
    assert "import aragora" not in source
    assert "from aragora" not in source


# ---------------------------------------------------------------------------
# Projection and verification
# ---------------------------------------------------------------------------


def test_projection_binds_the_whole_signed_document(odr, private_key):
    kid = compute_key_id(private_key.public_key())
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)

    canonical = jcs_canonicalize(odr)
    payload = envelope["payload"]
    assert set(envelope) == {"payload", "signature"}
    assert payload["type"] == ACTA_PAYLOAD_TYPE
    assert payload["chain_scope"] == ACTA_CHAIN_SCOPE
    assert payload["issuer_id"] == kid == envelope["signature"]["kid"]
    assert envelope["signature"]["alg"] == ACTA_SIGNATURE_ALG
    assert payload["payload_digest"]["hash"] == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert payload["payload_digest"]["size"] == len(canonical)
    assert payload["odr"] == odr
    assert payload["previousReceiptHash"] == GENESIS_PREVIOUS_RECEIPT_HASH
    private_key.public_key().verify(
        bytes.fromhex(envelope["signature"]["sig"]), jcs_canonicalize(payload)
    )


def test_verify_accepts_a_projection_and_a_lone_non_genesis_link(odr, private_key):
    kid = compute_key_id(private_key.public_key())
    first = project_to_acta(odr, private_key=private_key, kid=kid)
    second = project_to_acta(
        odr, private_key=private_key, kid=kid, previous_receipt_hash=acta_envelope_hash(first)
    )

    assert verify_acta_projection(first, private_key.public_key()).ok is True
    assert verify_acta_projection(second, private_key.public_key()).ok is True
    assert verify_acta_projection(second, private_key.public_key(), previous_envelope=first).ok


def test_verify_rejects_a_broken_binding(odr, private_key):
    kid = compute_key_id(private_key.public_key())
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)
    envelope["payload"]["odr"]["claim"]["verdict"] = "FAIL"

    result = verify_acta_projection(envelope, private_key.public_key())

    assert result.ok is False
    assert any("acta_binding" in reason for reason in result.reasons)
    assert result.to_dict()["ok"] is False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_verifies_the_pair(projection, pubkey_file, capsys):
    odr_path, acta_path = projection

    exit_code = main([str(odr_path), "--acta", str(acta_path), "--pubkey", str(pubkey_file)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "acta_binding" in out
    assert "=> VERIFIED" in out


def test_cli_auto_detects_an_envelope_passed_alone(projection, pubkey_file, capsys):
    _, acta_path = projection

    exit_code = main([str(acta_path), "--pubkey", str(pubkey_file)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "acta_signature" in out


def test_cli_reports_projection_checks_in_json(projection, pubkey_file, capsys):
    odr_path, acta_path = projection

    exit_code = main(
        [str(odr_path), "--acta", str(acta_path), "--pubkey", str(pubkey_file), "--json"]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    names = [check["name"] for check in payload["checks"]]
    assert {"acta_envelope", "acta_binding", "acta_signature", "acta_chain"} <= set(names)
    assert payload["ok"] is True


def test_cli_fails_a_broken_binding(projection, pubkey_file, tmp_path, capsys):
    odr_path, acta_path = projection
    envelope = json.loads(acta_path.read_text())
    envelope["payload"]["odr"]["claim"]["verdict"] = "FAIL"
    broken = tmp_path / "broken.acta.json"
    broken.write_text(json.dumps(envelope))

    exit_code = main([str(odr_path), "--acta", str(broken), "--pubkey", str(pubkey_file)])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "acta_binding" in out
    assert "FAIL" in out


def test_cli_fails_when_the_projection_carries_a_different_receipt(
    projection, pubkey_file, tmp_path, capsys
):
    odr_path, acta_path = projection
    other = json.loads(odr_path.read_text())
    other["receipt_id"] = "rcpt-0002"
    other_path = tmp_path / "other.odr.json"
    other_path.write_text(json.dumps(other))

    exit_code = main([str(other_path), "--acta", str(acta_path), "--pubkey", str(pubkey_file)])

    assert exit_code == 1
    assert "acta_receipt" in capsys.readouterr().out


def test_cli_reports_a_missing_projection_file_as_usage(projection, pubkey_file, tmp_path, capsys):
    odr_path, _ = projection

    exit_code = main(
        [str(odr_path), "--acta", str(tmp_path / "nope.acta.json"), "--pubkey", str(pubkey_file)]
    )

    assert exit_code == 2
    assert "not found" in capsys.readouterr().err


def test_cli_help_lists_the_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0
    assert "--acta" in capsys.readouterr().out
