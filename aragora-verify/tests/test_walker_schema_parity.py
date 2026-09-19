"""The dependency-free walker types every member ``odr_schema.json`` types.

A default ``pip install aragora-verify`` resolves ``cryptography`` alone, so the walker in
:mod:`aragora_verify.schema` is the only structural check almost every install runs. The
``walker_only`` fixture neutralises the optional ``jsonschema`` extra so these tests
measure that walker and nothing else.
"""

from __future__ import annotations

from typing import Any

import pytest

from aragora_verify import schema, verify
from aragora_verify.verifier import FAIL

from _fixtures import valid_odr

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
    ("subject.digest.alg", 5),
    ("subject.summary", 5),
    ("quorum.independence.distinct_model_families", -1),  # schema minimum: 0
] + [
    (f"source.{m}", 5)
    for m in ("artifact_hash", "receipt_id", "schema", "schema_version", "system")
]

# A marker is only the absent branch of its oneOf when it matches $defs/absent.
MALFORMED_MARKERS = [
    {"status": "absent"},
    {"status": "absent", "reason": 5},
    {"status": "absent", "reason": ""},
]


@pytest.fixture
def walker_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(schema, "_jsonschema_errors", lambda doc: [])


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


def test_document_using_every_typed_block_still_verifies(walker_only) -> None:
    result = verify(conformant_doc())
    assert result.ok is True, [(c.name, c.detail) for c in result.checks if c.status == FAIL]


@pytest.mark.parametrize(
    ("path", "value"), SCHEMA_TYPED_MEMBERS, ids=[p for p, _ in SCHEMA_TYPED_MEMBERS]
)
def test_schema_typed_member_fails_without_the_extra(path: str, value: Any, walker_only) -> None:
    doc = conformant_doc()
    assign(doc, path, value)

    errors = schema.validate_structure(doc)
    result = verify(doc)

    named = [error.partition(":")[0] for error in errors]
    assert any(path == n or path.startswith(f"{n}.") or n.startswith(f"{path}.") for n in named), (
        errors
    )
    assert result.ok is False
    assert sorted({c.name for c in result.checks if c.status == FAIL}) == ["schema_conformance"]


@pytest.mark.parametrize("marker", MALFORMED_MARKERS, ids=["none", "typed", "empty"])
def test_malformed_absent_marker_is_rejected(marker: dict[str, Any], walker_only) -> None:
    doc = conformant_doc()
    doc["claim"]["statement"] = marker
    assert schema.validate_structure(doc) != []
    assert verify(doc).ok is False


def test_absent_marker_is_not_typed_as_the_present_branch(walker_only) -> None:
    # Each of these members is a oneOf whose second branch is the absent marker;
    # routing a strict marker to the present branch would reject valid receipts.
    doc = conformant_doc()
    doc["claim"]["statement"] = {"status": "absent", "reason": "no statement recorded"}
    doc["subject"]["digest"] = {"status": "absent", "reason": "no artifact digest recorded"}
    doc["confidence"]["calibration"] = {"status": "absent", "reason": "no calibration record"}

    result = verify(doc)

    assert result.ok is True, [(c.name, c.detail) for c in result.checks if c.status == FAIL]
