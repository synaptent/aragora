"""The dependency-free walker types every member ``odr_schema.json`` types.

This engine never imports ``jsonschema``, and a default ``pip install aragora-verify``
resolves ``cryptography`` alone, so anything the walkers leave untyped is unenforced for
almost every install. Every mutant below is rejected by the bundled schema under
``jsonschema.Draft202012Validator`` and must be rejected with no JSON Schema engine.
"""

from __future__ import annotations

from typing import Any

import pytest

from aragora.gauntlet.odr_verify import FAIL, verify_odr_document
from tests.gauntlet.odr_parity_fixtures import valid_odr

# One mutant per member whose type the schema states: (path, value).
SCHEMA_TYPED_MEMBERS = [
    ("attestation.attested_at", 5),
    ("claim.statement", 5),
    ("confidence.calibration", "x"),
    ("confidence.calibration.provenance_ref", "x"),
    ("confidence.calibration.status", "x"),
    ("quorum.independence", {}),
    ("quorum.independence.disclosed", "x"),
    ("quorum.independence.distinct_model_families", "x"),
    ("quorum.independence.model_families", "x"),
    ("source", "x"),
    ("source.artifact_hash", 5),
    ("source.receipt_id", 5),
    ("source.schema", 5),
    ("source.schema_version", 5),
    ("source.system", 5),
    ("subject.digest.alg", 5),
    ("subject.summary", 5),
]


def conformant_doc() -> dict[str, Any]:
    """``valid_odr`` extended with every optional block the mutants reach into."""
    doc = valid_odr()
    doc["attestation"] = {
        "disposition": "human_attested",
        "attestor": {"id": "rm-1", "name": "P. Natarajan", "role": "release manager"},
        "attested_at": "2026-07-01T09:05:00+00:00",
    }
    doc["confidence"]["calibration"] = {
        "status": "present",
        "provenance_ref": {"type": "aragora.settlement_metadata", "receipt_id": "rcpt-1"},
    }
    doc["source"] = {
        "system": "aragora",
        "schema": "aragora.gauntlet.DecisionReceipt",
        "schema_version": "1.1",
        "receipt_id": "rcpt-1",
        "artifact_hash": "fe" * 32,
    }
    return doc


def assign(doc: dict[str, Any], path: str, value: Any) -> None:
    *parents, leaf = path.split(".")
    cursor: Any = doc
    for part in parents:
        cursor = cursor[part]
    cursor[leaf] = value


def test_document_using_every_typed_block_still_verifies() -> None:
    result = verify_odr_document(conformant_doc())
    assert result.ok is True, [(c.name, c.detail) for c in result.checks if c.status == FAIL]


@pytest.mark.parametrize(
    ("path", "value"), SCHEMA_TYPED_MEMBERS, ids=[p for p, _ in SCHEMA_TYPED_MEMBERS]
)
def test_schema_typed_member_fails_schema_conformance(path: str, value: Any) -> None:
    doc = conformant_doc()
    assign(doc, path, value)

    result = verify_odr_document(doc)

    assert result.ok is False
    failed = [c for c in result.checks if c.status == FAIL]
    assert [c.name for c in failed] == ["schema_conformance"]
    named = [item.partition(":")[0] for item in failed[0].detail.split("; ")]
    assert any(path == name or path.startswith(f"{name}.") for name in named), failed[0].detail


def test_absent_marker_is_not_typed_as_the_present_branch() -> None:
    # Each of these members is a oneOf whose second branch is the absent marker;
    # routing a strict marker to the present branch would reject valid receipts.
    doc = conformant_doc()
    doc["claim"]["statement"] = {"status": "absent", "reason": "no statement recorded"}
    doc["subject"]["digest"] = {"status": "absent", "reason": "no artifact digest recorded"}
    doc["confidence"]["calibration"] = {"status": "absent", "reason": "no calibration record"}

    result = verify_odr_document(doc)

    assert result.ok is True, [(c.name, c.detail) for c in result.checks if c.status == FAIL]
