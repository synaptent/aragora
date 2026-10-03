"""Schema 1.3 evidence-linked DecisionReceipt tests."""

from __future__ import annotations

import copy
import json
from argparse import Namespace
from pathlib import Path

import pytest

from aragora.cli.commands.verify import (
    _inline_artifact_hash,
    _inline_decision_payload_hash,
    _verify_receipt,
    cmd_verify,
)
from aragora.gauntlet.receipt_models import (
    DecisionReceipt,
    compute_decision_payload_hash,
    compute_receipt_artifact_hash,
)


def evidence(evidence_id: str, path: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "path": path,
        "blob_id": "a" * 40,
        "sha256": "b" * 64,
        "size_bytes": 42,
        "line_count": 3,
        "role": "roadmap",
        "uri": f"repo://example/project@{'c' * 40}/{path}#L1-L3",
        "http_permalink": f"https://github.com/example/project/blob/{'c' * 40}/{path}#L1-L3",
    }


def receipt(**overrides) -> DecisionReceipt:
    values = {
        "receipt_id": "receipt-evidence-1",
        "gauntlet_id": "debate-evidence-1",
        "timestamp": "2026-08-14T12:00:00+00:00",
        "input_summary": "Choose repository improvements",
        "input_hash": "d" * 64,
        "risk_summary": {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0},
        "attacks_attempted": 0,
        "attacks_successful": 0,
        "probes_run": 2,
        "vulnerabilities_found": 0,
        "verdict": "PASS",
        "confidence": 0.8,
        "robustness_score": 0.8,
    }
    values.update(overrides)
    return DecisionReceipt(**values)


def assert_cli_rejects(
    data: dict[str, object],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(data), encoding="utf-8")

    exit_code = cmd_verify(
        Namespace(receipt_path=str(receipt_path), output_format="json", verbose=False)
    )
    result = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert result["valid"] is False


def test_schema_13_round_trip_and_markdown_links() -> None:
    original = receipt(
        evidence_references=[evidence("ev-z", "src/app.py"), evidence("ev-a", "ROADMAP.md")],
        decision_payload={
            "goals": [
                {
                    "rank": 1,
                    "title": "Improve planning",
                    "criterion_scores": {"impact": 0.9},
                    "evidence_refs": ["ev-a"],
                }
            ]
        },
    )

    assert original.schema_version == "1.3"
    assert [item["evidence_id"] for item in original.evidence_references] == ["ev-a", "ev-z"]
    assert original.decision_payload_hash == compute_decision_payload_hash(
        original.decision_payload, original.evidence_references
    )
    assert original.verify_integrity()

    restored = DecisionReceipt.from_dict(json.loads(original.to_json()))
    assert restored.to_dict() == original.to_dict()
    assert restored.verify_integrity()
    markdown = restored.to_markdown()
    assert "## Decision Evidence" in markdown
    assert "Decision Payload Hash" in markdown
    assert "ROADMAP.md" in markdown
    assert "https://github.com/example/project/blob/" in markdown


def test_evidence_order_is_canonical() -> None:
    refs = [evidence("ev-a", "a.py"), evidence("ev-b", "b.py")]
    first = receipt(evidence_references=refs, decision_payload={"goals": [{"title": "Goal"}]})
    second = receipt(
        evidence_references=list(reversed(refs)),
        decision_payload={"goals": [{"title": "Goal"}]},
    )

    assert first.decision_payload_hash == second.decision_payload_hash
    assert first.artifact_hash == second.artifact_hash


def test_decision_payload_tampering_is_detected() -> None:
    original = receipt(
        evidence_references=[evidence("ev-a", "ROADMAP.md")],
        decision_payload={"goals": [{"title": "Original", "evidence_refs": ["ev-a"]}]},
    )
    original.decision_payload["goals"][0]["title"] = "Tampered"

    assert not original.verify_integrity()
    result = _verify_receipt(original.to_dict())
    assert result["valid"] is False
    assert "decision_payload_hash mismatch" in str(result["checks"])


def test_evidence_tampering_is_detected() -> None:
    original = receipt(
        evidence_references=[evidence("ev-a", "ROADMAP.md")],
        decision_payload={"goals": [{"title": "Original", "evidence_refs": ["ev-a"]}]},
    )
    original.evidence_references[0]["path"] = "OTHER.md"

    assert not original.verify_integrity()
    result = _verify_receipt(original.to_dict())
    assert result["valid"] is False
    assert "mismatch" in str(result["checks"])


def test_cli_inline_hashes_match_canonical_recipe() -> None:
    original = receipt(
        evidence_references=[evidence("ev-a", "ROADMAP.md")],
        decision_payload={"goals": [{"title": "Goal"}]},
    )
    data = original.to_dict()

    assert _inline_decision_payload_hash(data) == original.decision_payload_hash
    assert _inline_artifact_hash(data) == compute_receipt_artifact_hash(data)
    assert _verify_receipt(data)["valid"] is True


def test_removed_decision_hash_is_preserved_and_rejected_by_object_and_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = receipt(
        evidence_references=[evidence("ev-a", "ROADMAP.md")],
        decision_payload={"goals": [{"title": "Goal"}]},
    )
    data = original.to_dict()
    del data["decision_payload_hash"]

    restored = DecisionReceipt.from_dict(data)

    assert restored.schema_version == "1.3"
    assert restored.decision_payload_hash is None
    assert not restored.verify_integrity()
    assert_cli_rejects(data, tmp_path, capsys)


def test_schema_downgrade_is_preserved_and_rejected_by_object_and_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = receipt(
        evidence_references=[evidence("ev-a", "ROADMAP.md")],
        decision_payload={"goals": [{"title": "Goal"}]},
    )
    data = original.to_dict()
    data["schema_version"] = "1.2"

    restored = DecisionReceipt.from_dict(data)

    assert restored.schema_version == "1.2"
    assert restored.decision_payload_hash == original.decision_payload_hash
    assert not restored.verify_integrity()
    assert_cli_rejects(data, tmp_path, capsys)


def test_legacy_receipts_remain_byte_and_hash_compatible() -> None:
    legacy = receipt(schema_version="1.1")
    data = legacy.to_dict()
    assert legacy.schema_version == "1.1"
    assert "evidence_references" not in data
    assert "decision_payload" not in data
    assert "decision_payload_hash" not in data
    assert legacy.verify_integrity()

    schema_10 = copy.deepcopy(data)
    schema_10["schema_version"] = "1.0"
    schema_10["artifact_hash"] = compute_receipt_artifact_hash(schema_10)
    assert DecisionReceipt.from_dict(schema_10).verify_integrity()

    schema_12 = copy.deepcopy(data)
    schema_12["schema_version"] = "1.2"
    schema_12["cruxes"] = {"items": [{"claim": "A"}]}
    schema_12["artifact_hash"] = compute_receipt_artifact_hash(schema_12)
    assert DecisionReceipt.from_dict(schema_12).verify_integrity()
