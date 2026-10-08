"""Dependency-free validator covers the oversight attestation members (#8230).

The bundled JSON schema gained optional ``execution_identity`` / ``observed``
/ ``mechanism`` attestation members; the default validator (used by installs
without the optional ``jsonschema`` extra) must reject the same malformed
shapes the schema rejects and accept well-formed blocks.
"""

from __future__ import annotations

from aragora_verify.schema import validate_structure

from _fixtures import valid_odr


def _attested(odr: dict) -> dict:
    odr = dict(odr)
    odr["attestation"] = {
        "disposition": "human_attested",
        "attestor": {"id": "scarmani", "role": "oversight"},
        "attested_at": "2026-07-17T12:00:00+00:00",
        "execution_identity": {"id": "an0mium"},
        "observed": {"head_sha": "b" * 40, "evidence_digest": "sha256:" + "a" * 64},
        "mechanism": {
            "type": "settlement_status",
            "context": "aragora/human-settlement",
            "ref": "https://api.github.com/repos/o/r/statuses/abc",
        },
    }
    return odr


def test_well_formed_oversight_block_accepted() -> None:
    errors = validate_structure(_attested(valid_odr()))
    assert errors == []


def test_malformed_mechanism_rejected() -> None:
    odr = _attested(valid_odr())
    odr["attestation"]["mechanism"] = {"context": "missing-type"}
    errors = validate_structure(odr)
    assert any("mechanism.type" in e for e in errors)


def test_non_object_members_rejected() -> None:
    odr = _attested(valid_odr())
    odr["attestation"]["observed"] = "not-an-object"
    odr["attestation"]["execution_identity"] = 42
    errors = validate_structure(odr)
    assert any("observed: must be an object" in e for e in errors)
    assert any("execution_identity: must be an object" in e for e in errors)


def test_non_string_observed_fields_rejected() -> None:
    odr = _attested(valid_odr())
    odr["attestation"]["observed"] = {"head_sha": 123}
    errors = validate_structure(odr)
    assert any("observed.head_sha: must be a string" in e for e in errors)


def test_self_attested_block_rejected() -> None:
    odr = _attested(valid_odr())
    odr["attestation"]["execution_identity"] = {"id": "Scarmani"}
    errors = validate_structure(odr)
    assert any("must differ" in e for e in errors)


def test_non_string_attestor_fields_rejected() -> None:
    odr = _attested(valid_odr())
    odr["attestation"]["attestor"] = {"id": 123, "role": ["oversight"]}
    errors = validate_structure(odr)
    assert any("attestor.id: must be a string" in e for e in errors)
    assert any("attestor.role: must be a string" in e for e in errors)
