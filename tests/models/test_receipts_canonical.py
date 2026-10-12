"""The canonical receipt helpers keep their behaviour and identity after the move."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from aragora.models.receipts import canonical, gauntlet

OLD_PATH_NAMES = sorted(
    set(canonical.__all__)
    | {"_canonical_decision_value", "_clamp_receipt_confidence", "_normalize_receipt_boolean"}
)

BASE = {
    "receipt_id": "r-1",
    "gauntlet_id": "g-1",
    "input_hash": "abc",
    "risk_summary": {"high": 1},
    "verdict": "PASS",
    "confidence": 0.75,
}
EVIDENCE = [{"evidence_id": "e2", "path": "b"}, {"evidence_id": "e1", "path": "a"}]


@pytest.mark.parametrize("name", OLD_PATH_NAMES)
def test_old_paths_resolve_to_the_canonical_objects(name: str) -> None:
    import aragora.gauntlet.receipt_models as old

    assert getattr(gauntlet, name) is getattr(canonical, name)
    assert getattr(old, name) is getattr(canonical, name)


# Expected digests were computed with the pre-move implementation on main.
@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (BASE, "8b0c59bfff4d4aabd2ddb97b6ef25b7379e9c2b506d9107646b3c13a2635ee30"),
        (
            {**BASE, "cruxes": {"items": [{"claim": "x"}]}, "schema_version": "1.2"},
            "e9121aa6e1290a079712636827b05caa77ac8357aeddc056c171b51204216aa7",
        ),
        (
            {
                **BASE,
                "schema_version": "1.3",
                "decision_payload_hash": "dp",
                "evidence_references": EVIDENCE,
            },
            "9798847270e822bae0a4d58c7775ac3c5c2a476f79cd5e87017fc13830ab15b6",
        ),
    ],
)
def test_artifact_hash_recipe_is_unchanged(data: dict, expected: str) -> None:
    assert canonical.compute_receipt_artifact_hash(data) == expected


def test_decision_payload_hash_is_unchanged() -> None:
    digest = canonical.compute_decision_payload_hash({"goals": {"b": 2, "a": [1, {3}]}}, EVIDENCE)
    assert digest == "0dc0b86af8eee441348c15b00d4b2dc802e493725b8d2b25f2614929d08e6c5d"


def test_execution_linkage_normalization_is_unchanged() -> None:
    linkage = canonical.canonicalize_execution_outcome_linkage(
        {"receipt_id": " r-9 ", "consensus_proof": {"reached": "yes", "confidence": 3}}
    )
    assert linkage["receipt_id"] == linkage["debate_id"] == linkage["gauntlet_id"] == "r-9"
    assert linkage["consensus_proof"] == {"reached": True, "confidence": 1.0}
    assert linkage["receipt"] == {"id": "r-9", "confidence": 1.0, "consensus_reached": True}


def test_schema_version_selection_is_unchanged() -> None:
    assert canonical.receipt_schema_version(None) == canonical.RECEIPT_SCHEMA_VERSION == "1.1"
    assert canonical.receipt_schema_version({"items": [1]}) == "1.2"
    assert canonical.receipt_schema_version(None, EVIDENCE[:1]) == "1.3"


def test_receipt_hash_matches_the_canonical_recipe() -> None:
    receipt = gauntlet.DecisionReceipt(
        receipt_id="r-1",
        gauntlet_id="g-1",
        timestamp="2026-01-01T00:00:00+00:00",
        input_summary="input",
        input_hash="abc",
        risk_summary={"high": 1},
        attacks_attempted=0,
        attacks_successful=0,
        probes_run=0,
        vulnerabilities_found=0,
        verdict="PASS",
        confidence=0.75,
        robustness_score=1.0,
    )
    assert receipt.artifact_hash == canonical.compute_receipt_artifact_hash(receipt.to_dict())
    assert receipt.verify_integrity()


def test_canonical_imports_only_the_standard_library() -> None:
    code = (
        "import sys\n"
        "before = set(sys.modules)\n"
        "import aragora.models.receipts.canonical\n"
        "print(' '.join(sorted(m for m in set(sys.modules) - before if m.startswith('aragora'))))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=Path(canonical.__file__).resolve().parents[3],
    )
    assert completed.returncode == 0, completed.stderr
    loaded = set(completed.stdout.split())
    assert "aragora.models.receipts.canonical" in loaded
    assert all(
        name == "aragora"
        or name.startswith(("aragora.models", "aragora.core_types", "aragora.__version__"))
        for name in loaded
    ), sorted(loaded)
