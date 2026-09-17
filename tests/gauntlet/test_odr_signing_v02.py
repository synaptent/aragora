"""ODR v0.2 signature entries (spec §6): the DOCUMENT's ``odr_version`` picks the
signed message (``0.1`` = 32 raw digest bytes, ``0.2`` = ``JCS({odr_digest,
odr_signature_input, protected})``), no fallback; every case runs BOTH verifiers."""

from __future__ import annotations

import base64
import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_ARAGORA_VERIFY_SRC = _ROOT / "aragora-verify" / "src"
if str(_ARAGORA_VERIFY_SRC) not in sys.path:
    sys.path.insert(0, str(_ARAGORA_VERIFY_SRC))

from cryptography.exceptions import InvalidSignature  # noqa: E402

from aragora.gauntlet import odr_jcs, odr_verify  # noqa: E402
from aragora.gauntlet.odr_export import (  # noqa: E402
    load_odr_schema,
    odr_content_digest,
    sign_odr_if_configured,
)
from aragora.gauntlet.odr_signing import (  # noqa: E402
    ODR_SIGNATURE_ROLES,
    OdrSigningError,
    compute_key_id,
    generate_signing_key,
    sign_odr_receipt,
)
from aragora_verify import jcs as standalone_jcs  # noqa: E402
from aragora_verify import load_public_key as load_standalone_key  # noqa: E402
from aragora_verify import verify as verify_standalone  # noqa: E402
from aragora_verify.schema import load_bundled_schema  # noqa: E402

from tests.gauntlet.odr_parity_fixtures import valid_odr  # noqa: E402
from tests.gauntlet.odr_test_keys import odr_test_key  # noqa: E402

_EXAMPLES = _ROOT / "docs" / "specs" / "examples"
_T0, _T1 = "2026-09-05T00:00:00+00:00", "2027-09-05T00:00:00+00:00"
_DELETE = object()
_KEY = odr_test_key()
_PUB = _KEY.public_key()


def _v02() -> dict[str, Any]:
    doc = valid_odr()
    doc.update(odr_version="0.2", profile="https://aragora.ai/specs/open-decision-receipt/v0.2")
    return doc


def _signed_v02(**kwargs: Any) -> dict[str, Any]:
    return sign_odr_receipt(_v02(), _KEY, issuer="aragora", **kwargs)


def _check(result: Any, name: str) -> Any:
    return next(c for c in result.checks if c.name == name)


def _both(doc: dict[str, Any], public_key: Any = _PUB) -> tuple[Any, Any]:
    return (
        odr_verify.verify_odr_document(copy.deepcopy(doc), public_key=public_key),
        verify_standalone(copy.deepcopy(doc), public_key=public_key),
    )


def _assert_signature_fail_digest_pass(doc: dict[str, Any]) -> None:
    for result in _both(doc):
        assert result.ok is False
        assert _check(result, "canonical_digest").status == "pass"
        assert _check(result, "signature").status == "fail"


def _unauthenticated(result: Any) -> list[str]:
    return [w for w in result.warnings if "unauthenticated signature metadata" in w]


# --- signer: 0.2 entry shape and construction ------------------------------


def test_v02_entry_carries_signer_committed_metadata() -> None:
    (entry,) = _signed_v02()["signatures"]
    assert set(entry) == {"alg", "key_id", "issuer", "role", "signed_at", "signature"}
    assert (entry["alg"], entry["key_id"]) == ("Ed25519", compute_key_id(_PUB))
    assert (entry["issuer"], entry["role"]) == ("aragora", "emitter")
    # RFC 3339 with an explicit timezone, never a naive local time.
    assert datetime.fromisoformat(entry["signed_at"].replace("Z", "+00:00")).tzinfo is not None
    assert len(base64.b64decode(entry["signature"], validate=True)) == 64


def test_v02_construction_pinned_under_both_jcs_implementations() -> None:
    signed = _signed_v02()
    entry = signed["signatures"][0]
    signature = base64.b64decode(entry["signature"])
    digest = odr_content_digest(signed)
    protected = {k: v for k, v in entry.items() if k != "signature"}
    payload = {"odr_digest": digest, "odr_signature_input": "0.2", "protected": protected}
    message = odr_jcs.jcs_canonicalize(payload)
    assert message == standalone_jcs.jcs_canonicalize(payload)
    _PUB.verify(signature, message)  # construction ok
    with pytest.raises(InvalidSignature):  # the 0.1 message is never accepted for 0.2
        _PUB.verify(signature, bytes.fromhex(digest))
    for helper in (odr_jcs.odr_signature_message, standalone_jcs.odr_signature_message):
        assert helper(digest, "0.2", protected) == message
        assert helper(digest, "0.1", protected) == bytes.fromhex(digest)


def test_v02_signed_document_verifies_in_both_verifiers() -> None:
    for extra in ({}, {"role": "reviewer", "signed_at": _T0, "expires_at": _T1}):
        signed = _signed_v02(**extra)
        assert {k: signed["signatures"][0][k] for k in extra} == extra
        for result in _both(signed):
            assert result.ok is True, result.checks
            assert _check(result, "signature").status == "pass"
            assert _unauthenticated(result) == []


@pytest.mark.parametrize(
    "with_expiry,member,value",
    [
        pytest.param(False, "issuer", "mallory", id="issuer_changed"),
        pytest.param(False, "role", "notary", id="role_changed"),
        pytest.param(False, "signed_at", "2000-01-01T00:00:00+00:00", id="signed_at_changed"),
        pytest.param(False, "expires_at", "2099-01-01T00:00:00Z", id="expires_at_added"),
        pytest.param(False, "key_id", "ed25519-deadbeefdeadbeef", id="key_id_relabelled"),
        pytest.param(False, "issuer", _DELETE, id="issuer_stripped"),
        pytest.param(False, "signed_at", _DELETE, id="signed_at_stripped"),
        pytest.param(True, "expires_at", _DELETE, id="expires_at_stripped"),
    ],
)
def test_v02_metadata_tamper_fails_signature_but_not_digest(
    with_expiry: bool, member: str, value: Any
) -> None:
    signed = _signed_v02(signed_at=_T0, expires_at=_T1) if with_expiry else _signed_v02()
    if value is _DELETE:
        del signed["signatures"][0][member]
    else:
        signed["signatures"][0][member] = value
    _assert_signature_fail_digest_pass(signed)


def test_v02_entry_over_v01_message_fails_in_both_verifiers() -> None:
    """VAL-ODR-031.3: no fallback — a 0.2 entry made over the 32 raw digest bytes fails."""
    doc = _v02()
    legacy_signature = _KEY.sign(bytes.fromhex(odr_content_digest(doc)))
    entry = {"alg": "Ed25519", "key_id": compute_key_id(_PUB), "issuer": "aragora"}
    entry.update(
        role="emitter", signed_at=_T0, signature=base64.b64encode(legacy_signature).decode()
    )
    doc["signatures"] = [entry]
    _assert_signature_fail_digest_pass(doc)


# --- signer: argument validation -------------------------------------------


@pytest.mark.parametrize(
    "override,match",
    [
        ({"issuer": None}, "issuer"),
        ({"issuer": ""}, "issuer"),
        ({"role": "auditor"}, "role"),
        ({"expires_at": "2026-09-04T23:59:59+00:00"}, "later than signed_at"),
        ({"expires_at": _T0}, "later than signed_at"),
        ({"expires_at": "not-a-timestamp"}, "expires_at"),
        ({"expires_at": "2027-09-05T00:00:00"}, "timezone"),
        ({"signed_at": "2026-09-05T00:00:00", "expires_at": _T1}, "timezone"),
    ],
)
def test_v02_signer_rejects_invalid_metadata(override: dict[str, Any], match: str) -> None:
    with pytest.raises(OdrSigningError, match=match):
        sign_odr_receipt(_v02(), _KEY, **{"issuer": "aragora", "signed_at": _T0, **override})


@pytest.mark.parametrize("member", ["issuer", "role", "signed_at", "expires_at"])
def test_metadata_kwargs_on_v01_document_raise(member: str) -> None:
    values: dict[str, Any] = {
        "issuer": "x",
        "role": "reviewer",
        "signed_at": _T0,
        "expires_at": _T1,
    }
    with pytest.raises(OdrSigningError, match="0.2"):
        sign_odr_receipt(valid_odr(), _KEY, **{member: values[member]})


def test_append_mode_accepts_existing_v02_metadata_entry() -> None:
    other = generate_signing_key()
    twice = sign_odr_receipt(_signed_v02(), other, issuer="reviewer-bot", role="reviewer")
    assert [e["issuer"] for e in twice["signatures"]] == ["aragora", "reviewer-bot"]
    for public_key in (_PUB, other.public_key()):
        for result in _both(twice, public_key):
            assert result.ok is True, result.checks
            assert _check(result, "signature").status == "pass"


# --- v0.1 unchanged ----------------------------------------------------------


def test_v01_and_non_odr_payloads_keep_three_member_entry_over_raw_digest() -> None:
    # Non-ODR payloads (e.g. the disagreement-atlas manifest) reuse the signer
    # and keep the legacy construction.
    for doc in (valid_odr(), {"manifest": "x", "signatures": []}):
        signed = sign_odr_receipt(doc, _KEY)
        (entry,) = signed["signatures"]
        assert set(entry) == {"alg", "key_id", "signature"}
        _PUB.verify(base64.b64decode(entry["signature"]), bytes.fromhex(odr_content_digest(signed)))
    for result in _both(sign_odr_receipt(valid_odr(), _KEY)):
        assert result.ok is True
        assert _check(result, "signature").status == "pass"
        assert _unauthenticated(result) == []


@pytest.mark.parametrize(
    "version,extra,expected",
    [
        ("0.1", {"issuer": "aragora"}, 1),
        ("0.1", {"issuer": "aragora", "role": "emitter", "expires_at": "2099-01-01T00:00:00Z"}, 1),
        ("0.1", {"signed_at": "2026-06-14T00:00:01Z"}, 0),
        ("0.2", {}, 0),
    ],
    ids=["v01_issuer", "v01_all_members", "v01_signed_at_alone", "v02_metadata"],
)
def test_unauthenticated_metadata_warning_only_on_v01_documents(
    version: str, extra: dict[str, str], expected: int
) -> None:
    signed = _signed_v02() if version == "0.2" else sign_odr_receipt(valid_odr(), _KEY)
    signed["signatures"][0].update(extra)
    for result in _both(signed):
        assert result.ok is True and _check(result, "signature").status == "pass"
        assert len(_unauthenticated(result)) == expected, result.warnings
        assert all("issuer" in w for w in _unauthenticated(result))
    # The warning is about the document version, not the key: same without one.
    for result in _both(signed, None):
        assert len(_unauthenticated(result)) == expected, result.warnings


def test_committed_examples_keep_outcomes_with_no_unauthenticated_warning() -> None:
    pem = (_EXAMPLES / "example-signed.pubkey.pem").read_bytes()
    for path in sorted(_EXAMPLES.glob("*.odr.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        signed = bool(doc.get("signatures"))
        in_repo_key = odr_verify.load_public_key(pem) if signed else None
        standalone_key = load_standalone_key(pem) if signed else None
        for result in (
            odr_verify.verify_odr_document(copy.deepcopy(doc), public_key=in_repo_key),
            verify_standalone(doc, public_key=standalone_key),
        ):
            assert result.ok is True and _unauthenticated(result) == [], path.name
            assert (_check(result, "signature").status == "pass") is signed, path.name


# --- producer wiring: sign_odr_if_configured ---------------------------------


def test_sign_odr_if_configured_supplies_issuer_and_role_on_v02_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ARAGORA_ODR_SIGNING_ISSUER", raising=False)
    signed = sign_odr_if_configured(_v02(), key_loader=odr_test_key)
    (entry,) = signed["signatures"]
    assert set(entry) == {"alg", "key_id", "issuer", "role", "signed_at", "signature"}
    assert (entry["issuer"], entry["role"]) == ("aragora", "emitter")
    assert all(result.ok for result in _both(signed))
    v01_entry = sign_odr_if_configured(valid_odr(), key_loader=odr_test_key)["signatures"][0]
    assert set(v01_entry) == {"alg", "key_id", "signature"}
    for env_value, issuer in (("acme-ci", "acme-ci"), ("", "aragora")):  # empty means unset
        monkeypatch.setenv("ARAGORA_ODR_SIGNING_ISSUER", env_value)
        entry = sign_odr_if_configured(_v02(), key_loader=odr_test_key)["signatures"][0]
        assert entry["issuer"] == issuer


# --- schema copies and hand-written validators -------------------------------


def test_both_schema_copies_define_the_metadata_members_identically() -> None:
    in_tree = (_ROOT / "aragora" / "gauntlet" / "odr_schema.json").read_bytes()
    assert in_tree == (_ARAGORA_VERIFY_SRC / "aragora_verify" / "odr_schema.json").read_bytes()
    assert ODR_SIGNATURE_ROLES == ("emitter", "reviewer", "attestor", "notary")
    for schema in (load_odr_schema(), load_bundled_schema()):
        items = schema["properties"]["signatures"]["items"]
        props = items["properties"]
        assert props["issuer"] == {"type": "string", "minLength": 1}
        assert props["role"] == {"type": "string", "enum": list(ODR_SIGNATURE_ROLES)}
        assert props["signed_at"] == props["expires_at"] == {"type": "string"}
        assert items["required"] == ["alg", "key_id", "signature"]
        assert items["additionalProperties"] is False


@pytest.mark.parametrize(
    "member,value",
    [("issuer", ""), ("issuer", 7), ("role", "auditor"), ("expires_at", 5), ("note", "x")],
    ids=["empty_issuer", "non_string_issuer", "undefined_role", "non_string_expiry", "unknown"],
)
def test_both_validators_reject_malformed_metadata(member: str, value: Any) -> None:
    signed = _signed_v02()
    signed["signatures"][0][member] = value
    for result in _both(signed):
        assert result.ok is False
        check = _check(result, "schema_conformance")
        assert check.status == "fail" and f"signatures[0].{member}" in check.detail
