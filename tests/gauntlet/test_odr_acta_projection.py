"""ACTA-02 envelope projection of an ODR document (architecture §2.4).

Covers the envelope shape, the ``payload_digest`` binding over the ENTIRE ODR
(``signatures`` included, so it equals ``odr_digest`` only for an unsigned
document), the Ed25519 signature over ``JCS(payload)``, and the chain link.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aragora.gauntlet.odr_acta_projection import (
    ACTA_CHAIN_SCOPE,
    ACTA_PAYLOAD_TYPE,
    ACTA_SIGNATURE_ALG,
    GENESIS_PREVIOUS_RECEIPT_HASH,
    acta_envelope_hash,
    ed25519_key_id,
    project_to_acta,
    verify_acta_projection,
)
from aragora.gauntlet.odr_export import odr_content_digest
from aragora.gauntlet.odr_jcs import jcs_canonicalize
from aragora.gauntlet.odr_signing import compute_key_id, sign_odr_receipt
from tests.gauntlet.odr_test_keys import odr_test_key

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def private_key() -> Ed25519PrivateKey:
    return odr_test_key()


@pytest.fixture
def kid(private_key: Ed25519PrivateKey) -> str:
    return compute_key_id(private_key.public_key())


@pytest.fixture
def unsigned_odr() -> dict:
    doc = json.loads((ROOT / "docs/specs/examples/example-approved-clean.odr.json").read_text())
    doc["odr_version"] = "0.2"
    doc["profile"] = "https://aragora.ai/specs/open-decision-receipt/v0.2"
    doc["signatures"] = []
    return doc


@pytest.fixture
def odr(unsigned_odr: dict, private_key: Ed25519PrivateKey) -> dict:
    return sign_odr_receipt(unsigned_odr, private_key, issuer="aragora", role="emitter")


def test_envelope_has_exactly_payload_and_signature(odr, private_key, kid):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)

    assert set(envelope) == {"payload", "signature"}
    assert set(envelope["signature"]) == {"alg", "kid", "sig"}
    assert envelope["signature"]["alg"] == ACTA_SIGNATURE_ALG == "EdDSA"
    assert envelope["signature"]["kid"] == kid
    assert set(envelope["payload"]) == {
        "type",
        "issued_at",
        "issuer_id",
        "chain_scope",
        "previousReceiptHash",
        "payload_digest",
        "odr",
    }


def test_payload_members_carry_the_pinned_values(odr, private_key, kid):
    payload = project_to_acta(odr, private_key=private_key, kid=kid)["payload"]

    assert payload["type"] == ACTA_PAYLOAD_TYPE == "aragora:decision"
    assert payload["chain_scope"] == ACTA_CHAIN_SCOPE == "acta-02"
    assert payload["issuer_id"] == kid
    assert payload["issued_at"].endswith("Z")
    assert payload["odr"] == odr
    assert set(payload["payload_digest"]) <= {"hash", "size", "preview"}
    assert {"hash", "size"} <= set(payload["payload_digest"])
    assert isinstance(payload["payload_digest"]["size"], int)


def test_payload_digest_covers_the_entire_signed_odr(odr, private_key, kid):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)
    canonical = jcs_canonicalize(odr)

    digest = envelope["payload"]["payload_digest"]
    assert digest["hash"] == "sha256:" + hashlib.sha256(canonical).hexdigest()
    assert digest["size"] == len(canonical)
    # The ODR is signed, so the projection digest differs from odr_digest,
    # which excludes `signatures`.
    assert digest["hash"][len("sha256:") :] != odr_content_digest(odr)


def test_payload_digest_equals_odr_digest_only_without_signatures(unsigned_odr, private_key, kid):
    bare = {k: v for k, v in unsigned_odr.items() if k != "signatures"}

    without = project_to_acta(bare, private_key=private_key, kid=kid)
    with_empty = project_to_acta(unsigned_odr, private_key=private_key, kid=kid)

    assert unsigned_odr["signatures"] == []
    assert odr_content_digest(bare) == odr_content_digest(unsigned_odr)
    assert _digest_hex(without) == odr_content_digest(bare)
    # An empty `signatures` array is still a member of the projected document,
    # so it moves payload_digest while odr_digest keeps ignoring it.
    assert _digest_hex(with_empty) != odr_content_digest(unsigned_odr)


def _digest_hex(envelope: dict) -> str:
    return envelope["payload"]["payload_digest"]["hash"][len("sha256:") :]


def test_kid_equals_the_odr_signature_key_id_of_the_same_key(odr, private_key, kid):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)

    assert envelope["signature"]["kid"] == odr["signatures"][0]["key_id"]
    assert kid.startswith("ed25519-")
    assert len(kid) == len("ed25519-") + 16


def test_signature_is_ed25519_hex_over_jcs_payload(odr, private_key, kid):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)

    signature = bytes.fromhex(envelope["signature"]["sig"])
    private_key.public_key().verify(signature, jcs_canonicalize(envelope["payload"]))


def test_genesis_previous_receipt_hash_is_all_zero(odr, private_key, kid):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)

    assert envelope["payload"]["previousReceiptHash"] == GENESIS_PREVIOUS_RECEIPT_HASH
    assert envelope["payload"]["previousReceiptHash"] == "0" * 64


def test_chain_link_is_sha256_of_jcs_of_the_previous_envelope(odr, private_key, kid):
    first = project_to_acta(odr, private_key=private_key, kid=kid)
    link = acta_envelope_hash(first)
    second = project_to_acta(odr, private_key=private_key, kid=kid, previous_receipt_hash=link)

    assert link == hashlib.sha256(jcs_canonicalize(first)).hexdigest()
    assert second["payload"]["previousReceiptHash"] == link


def test_projection_does_not_mutate_its_input(odr, private_key, kid):
    before = copy.deepcopy(odr)
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)

    assert odr == before
    envelope["payload"]["odr"]["receipt_id"] = "mutated"
    assert odr["receipt_id"] != "mutated"


def test_issued_at_can_be_pinned_for_deterministic_vectors(odr, private_key, kid):
    envelope = project_to_acta(
        odr, private_key=private_key, kid=kid, issued_at="2026-06-14T00:00:00Z"
    )
    twin = project_to_acta(odr, private_key=private_key, kid=kid, issued_at="2026-06-14T00:00:00Z")

    assert envelope["payload"]["issued_at"] == "2026-06-14T00:00:00Z"
    assert envelope == twin


@pytest.mark.parametrize("bad", ["", "0" * 63, "0" * 65, "F" * 64, "zz" + "0" * 62, 0])
def test_projection_rejects_a_malformed_previous_receipt_hash(odr, private_key, kid, bad):
    with pytest.raises(ValueError):
        project_to_acta(odr, private_key=private_key, kid=kid, previous_receipt_hash=bad)


def test_projection_rejects_a_non_mapping_document(private_key, kid):
    with pytest.raises(TypeError):
        project_to_acta(["not", "a", "document"], private_key=private_key, kid=kid)


def test_verify_accepts_a_genesis_envelope(odr, private_key, kid):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)

    result = verify_acta_projection(envelope, private_key.public_key())

    assert result.ok is True
    assert result.reasons == []
    assert [c.name for c in result.checks] == [
        "acta_envelope",
        "acta_binding",
        "acta_signature",
        "acta_chain",
    ]


def test_verify_accepts_a_lone_non_genesis_link_without_its_predecessor(odr, private_key, kid):
    first = project_to_acta(odr, private_key=private_key, kid=kid)
    third = project_to_acta(
        odr, private_key=private_key, kid=kid, previous_receipt_hash=acta_envelope_hash(first)
    )

    assert verify_acta_projection(third, private_key.public_key()).ok is True


def test_verify_checks_the_link_only_when_a_predecessor_is_supplied(odr, private_key, kid):
    first = project_to_acta(odr, private_key=private_key, kid=kid)
    second = project_to_acta(
        odr, private_key=private_key, kid=kid, previous_receipt_hash=acta_envelope_hash(first)
    )

    assert verify_acta_projection(second, private_key.public_key(), previous_envelope=first).ok
    broken = verify_acta_projection(second, private_key.public_key(), previous_envelope=second)
    assert broken.ok is False
    assert any("acta_chain" in reason for reason in broken.reasons)


def test_verify_fails_a_broken_binding_with_a_named_reason(odr, private_key, kid):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)
    envelope["payload"]["odr"]["claim"]["statement"] = "tampered after projection"

    result = verify_acta_projection(envelope, private_key.public_key())

    assert result.ok is False
    assert any("acta_binding" in reason for reason in result.reasons)


def test_verify_fails_a_tampered_signature(odr, private_key, kid):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)
    envelope["signature"]["sig"] = "00" * 64

    result = verify_acta_projection(envelope, private_key.public_key())

    assert result.ok is False
    assert any("acta_signature" in reason for reason in result.reasons)


def test_verify_fails_a_wrong_key(odr, private_key, kid):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)
    other = Ed25519PrivateKey.generate()

    result = verify_acta_projection(envelope, other.public_key())

    assert result.ok is False
    assert any("acta_signature" in reason for reason in result.reasons)


def test_verify_skips_the_signature_without_a_key(odr, private_key, kid):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)

    result = verify_acta_projection(envelope, None)

    assert result.ok is True
    assert [c.status for c in result.checks if c.name == "acta_signature"] == ["skip"]


def test_an_unkeyed_verdict_reports_that_authenticity_was_never_checked(odr, private_key, kid):
    """`ok` alone must not read as "authentic" to a direct caller."""
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)

    unkeyed = verify_acta_projection(envelope, None)
    keyed = verify_acta_projection(envelope, private_key.public_key())

    assert unkeyed.authenticity_unverified is True
    assert unkeyed.to_dict()["authenticity_unverified"] is True
    assert keyed.authenticity_unverified is False
    assert keyed.to_dict()["authenticity_unverified"] is False


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda e: e.pop("signature"), id="missing_signature"),
        pytest.param(lambda e: e.update(extra=1), id="extra_top_level_member"),
        pytest.param(lambda e: e["payload"].pop("odr"), id="missing_odr"),
        pytest.param(lambda e: e["payload"].update(type="acme:other"), id="wrong_type"),
        pytest.param(lambda e: e["payload"].update(chain_scope="acta-01"), id="wrong_chain_scope"),
        pytest.param(
            lambda e: e["payload"].update(issuer_id="ed25519-0000"), id="issuer_kid_split"
        ),
        pytest.param(lambda e: e["signature"].update(alg="Ed25519"), id="wrong_alg"),
        pytest.param(lambda e: e["signature"].update(sig="not-hex"), id="non_hex_signature"),
        pytest.param(
            lambda e: e["payload"].update(previousReceiptHash="F" * 64), id="uppercase_link"
        ),
    ],
)
def test_verify_fails_a_malformed_envelope(odr, private_key, kid, mutate):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)
    mutate(envelope)

    result = verify_acta_projection(envelope, private_key.public_key())

    assert result.ok is False
    assert result.reasons


def test_verify_fails_when_the_declared_size_disagrees(odr, private_key, kid):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)
    envelope["payload"]["payload_digest"]["size"] += 1

    result = verify_acta_projection(envelope, None)

    assert result.ok is False
    assert any("acta_binding" in reason for reason in result.reasons)


def test_verify_fails_an_envelope_relabelled_with_another_kid(odr, private_key, kid):
    """A valid signer must not be able to claim another issuer's identity."""
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)
    other_kid = compute_key_id(Ed25519PrivateKey.generate().public_key())
    envelope["payload"]["issuer_id"] = other_kid
    envelope["signature"]["kid"] = other_kid
    envelope["signature"]["sig"] = private_key.sign(jcs_canonicalize(envelope["payload"])).hex()

    result = verify_acta_projection(envelope, private_key.public_key())

    assert result.ok is False
    assert any("signer-label tampering" in reason for reason in result.reasons)


def test_ed25519_key_id_matches_compute_key_id(private_key):
    public_key = private_key.public_key()

    assert ed25519_key_id(public_key) == compute_key_id(public_key)


def test_ed25519_key_id_is_none_for_a_non_key_object():
    assert ed25519_key_id(object()) is None


@pytest.mark.parametrize(
    "issued_at",
    [
        pytest.param("soon", id="not_a_timestamp"),
        pytest.param("2026-99-99T99:99:99Z", id="impossible_calendar_values"),
        pytest.param("2026-02-30T00:00:00Z", id="day_that_does_not_exist"),
        pytest.param("2026-06-14T24:00:00Z", id="hour_out_of_range"),
        pytest.param("2026-06-14T00:00:00+99:00", id="offset_out_of_range"),
        pytest.param("2026-06-14 00:00:00Z", id="space_instead_of_t"),
        pytest.param("2026-06-14T00:00:00", id="no_offset"),
    ],
)
def test_verify_rejects_an_issued_at_that_is_not_a_real_rfc3339_instant(
    odr, private_key, kid, issued_at
):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)
    envelope["payload"]["issued_at"] = issued_at
    envelope["signature"]["sig"] = private_key.sign(jcs_canonicalize(envelope["payload"])).hex()

    result = verify_acta_projection(envelope, private_key.public_key())

    assert result.ok is False
    assert any("issued_at" in reason for reason in result.reasons)


@pytest.mark.parametrize(
    "issued_at",
    ["2026-06-14T00:00:00Z", "2026-06-14T00:00:00.123456Z", "2024-02-29T23:59:60+02:00"],
)
def test_verify_accepts_real_rfc3339_instants(odr, private_key, kid, issued_at):
    envelope = project_to_acta(odr, private_key=private_key, kid=kid)
    envelope["payload"]["issued_at"] = issued_at
    envelope["signature"]["sig"] = private_key.sign(jcs_canonicalize(envelope["payload"])).hex()

    assert verify_acta_projection(envelope, private_key.public_key()).ok is True


def test_a_lone_non_genesis_link_is_reported_as_skipped_not_passed(odr, private_key, kid):
    first = project_to_acta(odr, private_key=private_key, kid=kid)
    second = project_to_acta(
        odr, private_key=private_key, kid=kid, previous_receipt_hash=acta_envelope_hash(first)
    )

    result = verify_acta_projection(second, private_key.public_key())

    assert result.ok is True
    assert [c.status for c in result.checks if c.name == "acta_chain"] == ["skip"]
    assert [c.status for c in result.checks if c.name == "acta_chain"] != ["pass"]


def test_project_rejects_an_issued_at_the_verifier_would_reject(odr, private_key, kid):
    """Producer and consumer share one definition of a usable timestamp."""
    with pytest.raises(ValueError, match="issued_at"):
        project_to_acta(odr, private_key=private_key, kid=kid, issued_at="not-a-timestamp")


def test_project_rejects_a_naive_datetime_rather_than_calling_it_utc(odr, private_key, kid):
    from datetime import datetime

    with pytest.raises(ValueError, match="timezone-aware"):
        project_to_acta(
            odr, private_key=private_key, kid=kid, issued_at=datetime(2026, 6, 14, 12, 0, 0)
        )
