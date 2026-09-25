from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CLAIMS_DIR = REPO_ROOT / "docs" / "status" / "claims"
SCHEMA_PATH = CLAIMS_DIR / "executable_claim_manifest.schema.json"
CLAIM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")

REQUIRED_CLAIM_FIELDS = {
    "claim_id",
    "statement",
    "owner",
    "scope",
    "confidence",
    "evidence",
    "freshness_sla_hours",
    "verification",
    "failure",
    "receipts",
}


def _load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_schema_documents_required_claim_contract() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    claim_required = set(schema["$defs"]["claim"]["required"])

    assert schema["properties"]["schema_version"]["const"] == 1
    assert REQUIRED_CLAIM_FIELDS <= claim_required
    assert "report_only" in schema["$defs"]["failure"]["properties"]["allowed_action"]["enum"]
    assert (
        "propose_bounded_issue"
        in schema["$defs"]["failure"]["properties"]["allowed_action"]["enum"]
    )
    truth_status = schema["$defs"]["truth_status"]
    assert set(truth_status["properties"]["state"]["enum"]) == {
        "live",
        "unsupported",
        "aspirational",
    }


def test_time_aware_manifests_declare_honest_truth_status() -> None:
    for name in ("proof_first_claims.yaml", "outsider_verifiable_claims.yaml"):
        manifest = _load_manifest(CLAIMS_DIR / name)
        for claim in manifest["claims"]:
            truth_status = claim["truth_status"]
            assert truth_status["state"] in {"live", "unsupported", "aspirational"}
            if truth_status["state"] == "live":
                assert truth_status["last_verified_at"].endswith("Z")
            else:
                assert "last_verified_at" not in truth_status


def test_all_manifests_remain_valid_under_backward_compatible_schema() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    for path in sorted(CLAIMS_DIR.glob("*.yaml")):
        validator.validate(_load_manifest(path))


def test_initial_proof_first_manifest_has_three_grounded_claims() -> None:
    manifest = _load_manifest(CLAIMS_DIR / "proof_first_claims.yaml")

    assert manifest["schema_version"] == 1
    assert manifest["manifest_id"] == "proof_first_claims"
    claims = manifest["claims"]
    assert len(claims) >= 3

    claim_ids = [claim["claim_id"] for claim in claims]
    assert len(claim_ids) == len(set(claim_ids))
    assert {
        "b0.benchmark_truth.complete_current_corpus",
        "tw03.rescue_productization.no_repeated_unlinked_classes",
        "docs.proof_first_queue_policy.current",
    } <= set(claim_ids)


def test_claim_examples_satisfy_minimum_contract() -> None:
    manifest = _load_manifest(CLAIMS_DIR / "proof_first_claims.yaml")

    for claim in manifest["claims"]:
        assert REQUIRED_CLAIM_FIELDS <= set(claim)
        assert CLAIM_ID_RE.match(claim["claim_id"])
        assert claim["statement"].strip()
        assert claim["owner"].strip()
        assert claim["scope"].strip()
        assert claim["confidence"] in {"low", "medium", "high"}
        assert isinstance(claim["freshness_sla_hours"], int)
        assert claim["freshness_sla_hours"] > 0

        evidence = claim["evidence"]
        assert isinstance(evidence, list)
        assert evidence
        for item in evidence:
            assert set(item) & {"path", "workflow", "issue", "pull_request", "url", "note"}
            if "path" in item:
                assert (REPO_ROOT / item["path"]).exists(), item["path"]

        verification = claim["verification"]
        assert verification["kind"] in {"command", "workflow", "manual"}
        assert verification["command"].strip()
        assert "expected_result" in verification

        failure = claim["failure"]
        assert failure["severity"] in {"info", "warning", "blocking"}
        assert failure["allowed_action"] in {
            "report_only",
            "rerun_workflow",
            "propose_bounded_issue",
        }
        assert failure["allowed_action"] != "boss_ready"

        receipts = claim["receipts"]
        assert isinstance(receipts, list)
        assert receipts
        for receipt in receipts:
            assert receipt["type"].strip()
            if "path" in receipt:
                assert (REPO_ROOT / receipt["path"]).exists(), receipt["path"]
