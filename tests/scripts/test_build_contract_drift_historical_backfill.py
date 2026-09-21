from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import build_contract_drift_historical_backfill as backfill
from tests.scripts._contract_drift_historical_git import ensure_pr_9320_head

ROOT = Path(__file__).resolve().parents[2]
SOURCE_SHA = "ee989c889e51f911f1cf5dd5fe667417613bbeb6"
PR_BASE_SHA = "14d1ef53e23c5466c0491ed93f72752944c78cd4"
HEAD_SHA = "aba6b14c94eca3a9c825b1a303ea67684d5f8daa"
MERGE_SHA = "0b28f68b9f4d204ae14814169093723ea84c1364"
FIRST_PARENT_SHA = "e448b840dad03ee28accd218c14a27fa8b87c7b4"
HEAD_TREE_SHA = "e5c6c3d07a918cf43fffed6d4a9f472bc10a674a"
MERGE_TREE_SHA = "79c1c374eed261c42468dc526d837e726e73425a"
PATCH_SHA256 = "7c53f6c8b9bd17847cdb4ecc5dfa1c7aa1699105faabc47439a4437709a175b4"
IMPLEMENTATION_PUSH_SHA = "057407297d7c7991bddb4cf16185ee3626100dd2"
IMPLEMENTATION_RULE_SUITE_ID = 3821290531
OLD_RELEASE_ID = 363450207
SYNTHETIC_RELEASE_ID = 990000001
SYNTHETIC_RULE_SUITE_ID = 990000002
SYNTHETIC_RECEIPT_RUN_ID = 990000003
SYNTHETIC_RECEIPT_JOB_ID = 990000004
SYNTHETIC_RECEIPT_ARTIFACT_ID = 990000005
APP_ID = 15368
EXPECTED_PATHS = [
    "aragora/server/handlers/social/__init__.py",
    "aragora/server/handlers/social/sharing.py",
    "tests/handlers/social/test_sharing.py",
]


def _git_text(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def _authority() -> dict[str, Any]:
    raw = subprocess.check_output(
        [
            "git",
            "-C",
            str(ROOT),
            "show",
            f"{SOURCE_SHA}:scripts/baselines/contract_drift_inventory.json",
        ]
    )
    return json.loads(raw)["accepted_authority"]


def _authority_manifest() -> dict[str, Any]:
    return json.loads(
        subprocess.check_output(
            [
                "python3",
                "-B",
                "scripts/generate_contract_drift_inventory.py",
                "--authority-manifest",
                "--ref",
                SOURCE_SHA,
            ],
            cwd=ROOT,
            env=backfill._git_env(),
        )
    )


def _contexts() -> list[dict[str, Any]]:
    return [
        {
            "app_id": APP_ID,
            "check_run_id": 87709243174,
            "conclusion": "success",
            "job_id": 87709243174,
            "name": "lint",
            "run_attempt": 1,
            "workflow_run_id": 29524359563,
        },
        {
            "app_id": APP_ID,
            "check_run_id": 87709180560,
            "conclusion": "success",
            "job_id": 87709180560,
            "name": "typecheck",
            "run_attempt": 1,
            "workflow_run_id": 29524359563,
        },
        {
            "app_id": APP_ID,
            "check_run_id": 87709276751,
            "conclusion": "success",
            "job_id": 87709276751,
            "name": "sdk-parity",
            "run_attempt": 1,
            "workflow_run_id": 29524359665,
        },
        {
            "app_id": APP_ID,
            "check_run_id": 87709726971,
            "conclusion": "success",
            "job_id": 87709726971,
            "name": "Generate & Validate",
            "run_attempt": 1,
            "workflow_run_id": 29524359572,
        },
        {
            "app_id": APP_ID,
            "check_run_id": 87709013895,
            "conclusion": "success",
            "job_id": 87709013895,
            "name": "TypeScript SDK Type Check",
            "run_attempt": 1,
            "workflow_run_id": 29524359727,
        },
        {
            "app_id": APP_ID,
            "check_run_id": 87728267780,
            "conclusion": "success",
            "job_id": 87728267780,
            "name": "aragora-merge-quorum",
            "run_attempt": 3,
            "workflow_run_id": 29524359568,
        },
    ]


def _input_document() -> dict[str, Any]:
    return {
        "attestation": {
            "predicate_type": backfill.ratchet.RELEASE_ATTESTATION_PREDICATE_TYPE,
            "repository": "synaptent/aragora",
            "schema": backfill.ATTESTATION_SCHEMA,
            "signer_san_regexp": backfill.ratchet.RELEASE_ATTESTATION_SIGNER_SAN_REGEXP,
            "source_digest": SOURCE_SHA,
            "subject_asset_names": list(backfill.EXPECTED_ASSET_NAMES),
            "verified": True,
            "workflow": "actions/attest@v4",
            "workflow_path": backfill.ATTESTATION_WORKFLOW_PATH,
        },
        "authority_source_sha": SOURCE_SHA,
        "disposition": {
            "authoritative_for_future_admission": False,
            "precedential": False,
            "status": "historical_nonconforming",
        },
        "historical_pull_request": {
            "actor": "scarmani",
            "base_sha": PR_BASE_SHA,
            "changed_files": [
                {
                    "additions": 3,
                    "deletions": 1,
                    "path": "aragora/server/handlers/social/__init__.py",
                },
                {
                    "additions": 23,
                    "deletions": 0,
                    "path": "aragora/server/handlers/social/sharing.py",
                },
                {
                    "additions": 89,
                    "deletions": 2,
                    "path": "tests/handlers/social/test_sharing.py",
                },
            ],
            "first_parent_patch_byte_length": 6054,
            "first_parent_patch_sha256": PATCH_SHA256,
            "first_parent_sha": FIRST_PARENT_SHA,
            "head_sha": HEAD_SHA,
            "head_tree_sha": HEAD_TREE_SHA,
            "merge_sha": MERGE_SHA,
            "merge_tree_sha": MERGE_TREE_SHA,
            "merged_at": "2026-07-16T20:00:49Z",
            "pr": 9320,
        },
        "receipt": {
            "artifact_name": f"contract-drift-main-receipt-{MERGE_SHA}",
            "base_sha": PR_BASE_SHA,
            "check_run_id": SYNTHETIC_RECEIPT_JOB_ID,
            "conclusion": "success",
            "first_parent_sha": FIRST_PARENT_SHA,
            "head_sha": HEAD_SHA,
            "job_id": SYNTHETIC_RECEIPT_JOB_ID,
            "merge_sha": MERGE_SHA,
            "required_contexts": _contexts(),
            "run_attempt": 1,
            "schema": backfill.RECEIPT_SCHEMA,
            "source_sha": SOURCE_SHA,
            "workflow_name": "Contract Drift Governance",
            "workflow_path": backfill.WORKFLOW_PATH,
            "workflow_run_id": SYNTHETIC_RECEIPT_RUN_ID,
        },
        "release": {
            "asset_names": list(backfill.EXPECTED_ASSET_NAMES),
            "exact_full_sha_tag": MERGE_SHA,
            "immutable": True,
            "release_api_id": SYNTHETIC_RELEASE_ID,
            "tag_name": f"backfill-v2-{MERGE_SHA}",
            "tag_target_sha": SOURCE_SHA,
            "verified": True,
        },
        "repository": "synaptent/aragora",
        "rule_suite": {
            "after_sha": SOURCE_SHA,
            "id": SYNTHETIC_RULE_SUITE_ID,
            "ref": "refs/heads/main",
            "repository_id": 1126097105,
            "repository_name": "synaptent/aragora",
            "result": "pass",
            "schema": backfill.RULE_SUITE_SCHEMA,
        },
        "supersedes": {
            "reason": (
                "Immutable release 363450207 is retained as superseded historical "
                "evidence because its receipt and attestation planes were incomplete."
            ),
            "release_api_id": OLD_RELEASE_ID,
            "status": "superseded_historical_evidence",
            "tag_name": f"backfill-{MERGE_SHA}",
        },
    }


@pytest.fixture(scope="module")
def payload() -> dict[str, Any]:
    return backfill.build_payload(
        repo_root=ROOT,
        input_document=_input_document(),
        authority_manifest=_authority_manifest(),
    )


@pytest.fixture(scope="module")
def assets(payload: dict[str, Any]) -> dict[str, bytes]:
    return backfill.build_capsule_bytes(payload)


def test_fixture_builds_byte_identically_twice(
    payload: dict[str, Any],
    assets: dict[str, bytes],
) -> None:
    second = backfill.build_capsule_bytes(copy.deepcopy(payload))
    assert assets == second
    assert list(assets) == ["checksums.txt", "manifest.json", "payload.json"]
    assert all(raw for raw in assets.values())
    assert OLD_RELEASE_ID not in {payload["release"]["release_api_id"]}
    assert payload["supersedes"]["release_api_id"] == OLD_RELEASE_ID


def test_fixture_binds_all_semantic_planes(payload: dict[str, Any]) -> None:
    authority = _authority()
    projection = payload["projection"]
    assert projection["membership_count"] == 655
    assert projection["edge_count"] == 666
    assert projection["multi_edge_originals"] == 9
    assert projection["max_edges"] == 4
    assert (
        projection["records"]
        == (authority["canonical_artifacts"]["original_cohort"]["operation_projection"]["records"])
    )
    assert payload["authority"]["original_record_id_set_sha256"] == (
        "c1235670c183b1887ba3fe4280fa0320f9fd6f4a85b8f346d4332ac2aebbe269"
    )
    assert payload["authority"]["operation_projection_record_digest_set_sha256"] == (
        "2d6790a6f825c53047639d9433f40e3e10b5bfc9e357bcd161f6b341134775e5"
    )
    assert payload["authority"]["operation_projection_schema_sha256"] == (
        "26bb802de06dcda62be8dc0b8f67b7ee9243af0692e712340771835a76e5b5ce"
    )
    assert payload["authority"]["sdk_provenance_record_digest_set_sha256"] == (
        "0d30ce3b083344f19949da12ae2d92952757af0aea800b3f99d447458b6eeba0"
    )
    assert payload["authority"]["sdk_original_record_id_set_sha256"] == (
        "51a963079136a92a86485b56f6cef42aafc7749bfad146ce5fb37293524c5762"
    )
    assert payload["authority"]["core_original_record_id_set_sha256"] == (
        "b3a1755f027c998d507f13f3ba9093f769cea8720d44bfac12be6beccd626787"
    )
    assert payload["authority"]["extended_original_record_id_set_sha256"] == (
        "bb1fc41548778022dab3041bc05fc40a4da239a1bd4ad8b1ccbcd1007d90b252"
    )
    assert payload["receipt"]["base_sha"] == PR_BASE_SHA
    assert payload["receipt"]["head_sha"] == HEAD_SHA
    assert payload["receipt"]["source_sha"] == SOURCE_SHA
    assert payload["receipt"]["merge_sha"] == MERGE_SHA
    assert payload["release"]["tag_name"] == f"backfill-v2-{MERGE_SHA}"
    assert payload["release"]["exact_full_sha_tag"] == MERGE_SHA
    assert payload["release"]["tag_target_sha"] == SOURCE_SHA
    assert payload["attestation"]["source_digest"] == SOURCE_SHA
    assert payload["rule_suite"]["after_sha"] == SOURCE_SHA
    assert (
        payload["historical_pull_request"]["changed_files"]
        == _input_document()["historical_pull_request"]["changed_files"]
    )


@pytest.mark.parametrize(
    "path",
    [
        *((field,) for field in sorted(backfill.PAYLOAD_FIELDS)),
        *(("historical_pull_request", field) for field in sorted(backfill.HISTORICAL_PR_FIELDS)),
        *(
            ("historical_pull_request", "changed_files", "0", field)
            for field in sorted(backfill.CHANGED_FILE_FIELDS)
        ),
        *(("authority", field) for field in sorted(backfill.AUTHORITY_FIELDS)),
        *(("projection", field) for field in sorted(backfill.PROJECTION_FIELDS)),
        *(
            ("projection", "records", "0", field)
            for field in sorted(backfill.PROJECTION_RECORD_FIELDS)
        ),
        *(
            ("projection", "records", "0", "operation_edges", "0", field)
            for field in sorted(backfill.PROJECTION_EDGE_FIELDS)
        ),
        *(("receipt", field) for field in sorted(backfill.RECEIPT_FIELDS)),
        *(
            ("receipt", "required_contexts", "0", field)
            for field in sorted(backfill.CONTEXT_FIELDS)
        ),
        *(("release", field) for field in sorted(backfill.RELEASE_FIELDS)),
        *(("attestation", field) for field in sorted(backfill.ATTESTATION_FIELDS)),
        *(("rule_suite", field) for field in sorted(backfill.RULE_SUITE_FIELDS)),
        *(("supersedes", field) for field in sorted(backfill.SUPERSEDES_FIELDS)),
    ],
)
def test_every_required_payload_field_is_fail_closed(
    payload: dict[str, Any],
    path: tuple[str, ...],
) -> None:
    candidate = copy.deepcopy(payload)
    normalized = tuple(int(item) if item.isdigit() else item for item in path)
    current: Any = candidate
    for key in normalized[:-1]:
        current = current[key]
    del current[normalized[-1]]
    with pytest.raises(ValueError):
        backfill.validate_payload(candidate)


def test_failed_receipt_and_missing_attestation_fail_closed(payload: dict[str, Any]) -> None:
    failed = copy.deepcopy(payload)
    failed["receipt"]["conclusion"] = "failure"
    with pytest.raises(ValueError, match="did not succeed"):
        backfill.validate_payload(failed)

    missing = copy.deepcopy(payload)
    del missing["attestation"]
    with pytest.raises(ValueError, match="fields are incomplete"):
        backfill.validate_payload(missing)

    wrong_base = copy.deepcopy(payload)
    wrong_base["receipt"]["base_sha"] = FIRST_PARENT_SHA
    with pytest.raises(ValueError, match="receipt base SHA mismatch"):
        backfill.validate_payload(wrong_base)

    wrong_head = copy.deepcopy(payload)
    wrong_head["receipt"]["head_sha"] = MERGE_SHA
    with pytest.raises(ValueError, match="receipt head SHA mismatch"):
        backfill.validate_payload(wrong_head)

    wrong_source = copy.deepcopy(payload)
    wrong_source["receipt"]["source_sha"] = MERGE_SHA
    with pytest.raises(ValueError, match="receipt source SHA mismatch"):
        backfill.validate_payload(wrong_source)

    wrong_merge = copy.deepcopy(payload)
    wrong_merge["receipt"]["merge_sha"] = SOURCE_SHA
    with pytest.raises(ValueError, match="receipt merge SHA mismatch"):
        backfill.validate_payload(wrong_merge)

    wrong_tag_target = copy.deepcopy(payload)
    wrong_tag_target["release"]["tag_target_sha"] = MERGE_SHA
    with pytest.raises(ValueError, match="release tag binding mismatch"):
        backfill.validate_payload(wrong_tag_target)

    wrong_pair = copy.deepcopy(payload)
    wrong_pair["historical_pull_request"]["base_sha"] = FIRST_PARENT_SHA
    wrong_pair["receipt"]["base_sha"] = FIRST_PARENT_SHA
    with pytest.raises(ValueError, match="frozen PR #9320 exact pair"):
        backfill.validate_payload(wrong_pair)


def test_supersedes_wrong_identity_fails_closed(payload: dict[str, Any]) -> None:
    wrong_id = copy.deepcopy(payload)
    wrong_id["supersedes"]["release_api_id"] = OLD_RELEASE_ID + 1
    with pytest.raises(ValueError, match="frozen old release"):
        backfill.validate_payload(wrong_id)

    wrong_tag = copy.deepcopy(payload)
    wrong_tag["supersedes"]["tag_name"] = f"backfill-{HEAD_SHA}"
    with pytest.raises(ValueError, match="frozen old release"):
        backfill.validate_payload(wrong_tag)

    successor_tag = copy.deepcopy(payload)
    successor_tag["supersedes"]["tag_name"] = f"backfill-v2-{MERGE_SHA}"
    with pytest.raises(ValueError, match="frozen old release"):
        backfill.validate_payload(successor_tag)


def test_supersedes_missing_identity_fails_closed(payload: dict[str, Any]) -> None:
    for field in ("release_api_id", "tag_name"):
        omitted = copy.deepcopy(payload)
        del omitted["supersedes"][field]
        with pytest.raises(ValueError, match="incomplete or noncanonical"):
            backfill.validate_payload(omitted)

    for field, degenerate in (("release_api_id", None), ("tag_name", None), ("tag_name", "")):
        broken = copy.deepcopy(payload)
        broken["supersedes"][field] = degenerate
        with pytest.raises(ValueError):
            backfill.validate_payload(broken)


def test_supersedes_correct_frozen_identity_passes(payload: dict[str, Any]) -> None:
    assert backfill.PR_9320_SUPERSEDED_RELEASE_API_ID == OLD_RELEASE_ID
    assert backfill.PR_9320_SUPERSEDED_RELEASE_TAG == f"backfill-{MERGE_SHA}"
    validated = backfill.validate_payload(copy.deepcopy(payload))
    assert validated["supersedes"]["release_api_id"] == OLD_RELEASE_ID
    assert validated["supersedes"]["tag_name"] == f"backfill-{MERGE_SHA}"


def test_schema_supersedes_region_pins_frozen_identity() -> None:
    schema = json.loads((ROOT / backfill.CAPSULE_SCHEMA_PATH).read_text(encoding="utf-8"))
    supersedes = schema["properties"]["supersedes"]
    assert supersedes["additionalProperties"] is False
    assert set(supersedes["required"]) == set(supersedes["properties"])
    assert supersedes["properties"]["release_api_id"]["const"] == OLD_RELEASE_ID
    assert supersedes["properties"]["tag_name"]["const"] == f"backfill-{MERGE_SHA}"
    assert supersedes["properties"]["status"]["const"] == "superseded_historical_evidence"


def test_schema_supersedes_region_rejects_wrong_identity(payload: dict[str, Any]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / backfill.CAPSULE_SCHEMA_PATH).read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema["properties"]["supersedes"])
    assert not list(validator.iter_errors(copy.deepcopy(payload["supersedes"])))

    wrong_id = copy.deepcopy(payload["supersedes"])
    wrong_id["release_api_id"] = OLD_RELEASE_ID + 1
    assert list(validator.iter_errors(wrong_id))

    wrong_tag = copy.deepcopy(payload["supersedes"])
    wrong_tag["tag_name"] = f"backfill-v2-{MERGE_SHA}"
    assert list(validator.iter_errors(wrong_tag))

    missing_id = copy.deepcopy(payload["supersedes"])
    del missing_id["release_api_id"]
    assert list(validator.iter_errors(missing_id))


def _write_self_consistent_capsule(
    tmp_path: Path,
    payload: dict[str, Any],
    **overrides: Any,
) -> Path:
    # Assemble the three asset byte streams directly, bypassing build/validate,
    # so the directory is internally consistent (manifest and checksums match
    # the tampered payload bytes) while carrying false historical evidence —
    # the exact capsule shape --verify-dir must reject without git access.
    document = copy.deepcopy(payload)
    document["historical_pull_request"].update(overrides)
    payload_bytes = backfill._canonical_json_bytes(document)
    historical = document["historical_pull_request"]
    release = document["release"]
    manifest_bytes = backfill._canonical_json_bytes(
        {
            "asset_names": list(backfill.EXPECTED_ASSET_NAMES),
            "first_parent_sha": historical["first_parent_sha"],
            "merge_sha": historical["merge_sha"],
            "payload_byte_length": len(payload_bytes),
            "payload_sha256": backfill._sha256(payload_bytes),
            "pr": historical["pr"],
            "release_api_id": release["release_api_id"],
            "schema": backfill.MANIFEST_SCHEMA,
            "tag_name": release["tag_name"],
        }
    )
    checksums_bytes = (
        f"{backfill._sha256(manifest_bytes)}  manifest.json\n"
        f"{backfill._sha256(payload_bytes)}  payload.json\n"
    ).encode("ascii")
    capsule_dir = tmp_path / "capsule"
    capsule_dir.mkdir()
    (capsule_dir / "manifest.json").write_bytes(manifest_bytes)
    (capsule_dir / "payload.json").write_bytes(payload_bytes)
    (capsule_dir / "checksums.txt").write_bytes(checksums_bytes)
    return capsule_dir


def test_verify_dir_rejects_wrong_head_tree_sha(payload: dict[str, Any], tmp_path: Path) -> None:
    capsule_dir = _write_self_consistent_capsule(tmp_path, payload, head_tree_sha=MERGE_TREE_SHA)
    with pytest.raises(ValueError, match="frozen PR #9320 evidence"):
        backfill._verify_directory(capsule_dir)


def test_verify_dir_rejects_wrong_merge_tree_sha(payload: dict[str, Any], tmp_path: Path) -> None:
    capsule_dir = _write_self_consistent_capsule(tmp_path, payload, merge_tree_sha=HEAD_TREE_SHA)
    with pytest.raises(ValueError, match="frozen PR #9320 evidence"):
        backfill._verify_directory(capsule_dir)


def test_verify_dir_rejects_wrong_first_parent_patch_byte_length(
    payload: dict[str, Any], tmp_path: Path
) -> None:
    capsule_dir = _write_self_consistent_capsule(
        tmp_path, payload, first_parent_patch_byte_length=6055
    )
    with pytest.raises(ValueError, match="frozen PR #9320 evidence"):
        backfill._verify_directory(capsule_dir)


def test_verify_dir_rejects_wrong_first_parent_patch_sha256(
    payload: dict[str, Any], tmp_path: Path
) -> None:
    capsule_dir = _write_self_consistent_capsule(
        tmp_path, payload, first_parent_patch_sha256=backfill._sha256(b"tampered")
    )
    with pytest.raises(ValueError, match="frozen PR #9320 evidence"):
        backfill._verify_directory(capsule_dir)


def test_verify_dir_accepts_canonical_frozen_value_fixture(
    payload: dict[str, Any],
    assets: dict[str, bytes],
    tmp_path: Path,
) -> None:
    assert backfill.PR_9320_HEAD_TREE_SHA == HEAD_TREE_SHA
    assert backfill.PR_9320_MERGE_TREE_SHA == MERGE_TREE_SHA
    assert backfill.PR_9320_FIRST_PARENT_PATCH_BYTE_LENGTH == 6054
    assert backfill.PR_9320_FIRST_PARENT_PATCH_SHA256 == PATCH_SHA256
    historical = payload["historical_pull_request"]
    # build_payload recomputed these four values against immutable git before
    # validating, so equality with the frozen constants is git-grounded here,
    # not self-referential.
    assert historical["head_tree_sha"] == backfill.PR_9320_HEAD_TREE_SHA
    assert historical["merge_tree_sha"] == backfill.PR_9320_MERGE_TREE_SHA
    assert (
        historical["first_parent_patch_byte_length"]
        == backfill.PR_9320_FIRST_PARENT_PATCH_BYTE_LENGTH
    )
    assert historical["first_parent_patch_sha256"] == backfill.PR_9320_FIRST_PARENT_PATCH_SHA256
    capsule_dir = tmp_path / "capsule"
    backfill.write_capsule(capsule_dir, assets)
    result = backfill._verify_directory(capsule_dir)
    assert result["status"] == "pass"
    assert result["pr"] == 9320


def test_schema_historical_region_pins_frozen_derived_evidence() -> None:
    schema = json.loads((ROOT / backfill.CAPSULE_SCHEMA_PATH).read_text(encoding="utf-8"))
    historical = schema["properties"]["historical_pull_request"]
    assert historical["additionalProperties"] is False
    assert set(historical["required"]) == set(historical["properties"])
    assert historical["properties"]["head_tree_sha"]["const"] == HEAD_TREE_SHA
    assert historical["properties"]["merge_tree_sha"]["const"] == MERGE_TREE_SHA
    assert historical["properties"]["first_parent_patch_byte_length"]["const"] == 6054
    assert historical["properties"]["first_parent_patch_sha256"]["const"] == PATCH_SHA256


def test_schema_historical_region_rejects_wrong_derived_evidence(
    payload: dict[str, Any],
) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / backfill.CAPSULE_SCHEMA_PATH).read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema["properties"]["historical_pull_request"])
    assert not list(validator.iter_errors(copy.deepcopy(payload["historical_pull_request"])))

    for field, wrong in (
        ("head_tree_sha", MERGE_TREE_SHA),
        ("merge_tree_sha", HEAD_TREE_SHA),
        ("first_parent_patch_byte_length", 6055),
        ("first_parent_patch_sha256", backfill._sha256(b"tampered")),
    ):
        tampered = copy.deepcopy(payload["historical_pull_request"])
        tampered[field] = wrong
        assert list(validator.iter_errors(tampered)), field


def test_real_exact_pair_receipt_source_identity_feeds_builder() -> None:
    result = backfill.ratchet.build_accepted_result(
        mode="receipt",
        repo_root=ROOT,
        inventory_path=ROOT / backfill.inventory_mod.DEFAULT_INVENTORY,
        source_sha=SOURCE_SHA,
        historical_base_sha=PR_BASE_SHA,
        historical_head_sha=HEAD_SHA,
        historical_merge_sha=MERGE_SHA,
        historical_first_parent_sha=FIRST_PARENT_SHA,
    )
    assert result["status"] == "pass"
    assert result["source_sha"] == SOURCE_SHA
    assert result["execution"]["source_sha"] == SOURCE_SHA
    assert result["execution"]["merge_sha"] == MERGE_SHA

    input_document = _input_document()
    input_document["receipt"]["source_sha"] = result["source_sha"]
    built = backfill.build_payload(
        repo_root=ROOT,
        input_document=input_document,
        authority_manifest=_authority_manifest(),
    )
    assert built["receipt"]["source_sha"] == SOURCE_SHA
    assert built["receipt"]["merge_sha"] == MERGE_SHA


class _ReceiptApiFixture:
    def __init__(
        self,
        *,
        artifact_id: int = SYNTHETIC_RECEIPT_ARTIFACT_ID,
        receipt_lifecycle: str = "completed",
    ) -> None:
        self.responses: dict[str, dict[str, Any]] = {}
        if receipt_lifecycle not in {"completed", "in_progress"}:
            raise AssertionError(f"unsupported receipt lifecycle: {receipt_lifecycle}")
        receipt_status = receipt_lifecycle
        receipt_conclusion = "success" if receipt_lifecycle == "completed" else None
        receipt_run = {
            "conclusion": receipt_conclusion,
            "event": "workflow_dispatch",
            "head_sha": SOURCE_SHA,
            "id": SYNTHETIC_RECEIPT_RUN_ID,
            "path": backfill.WORKFLOW_PATH,
            "repository": {"full_name": "synaptent/aragora"},
            "run_attempt": 1,
            "status": receipt_status,
        }
        receipt_job = {
            "check_url": (
                "https://api.github.com/repos/synaptent/aragora/check-runs/"
                f"{SYNTHETIC_RECEIPT_JOB_ID}"
            ),
            "conclusion": receipt_conclusion,
            "head_sha": SOURCE_SHA,
            "id": SYNTHETIC_RECEIPT_JOB_ID,
            "name": "contract-drift-main-receipt",
            "run_attempt": 1,
            "status": receipt_status,
        }
        self.responses[f"repos/synaptent/aragora/actions/runs/{SYNTHETIC_RECEIPT_RUN_ID}"] = (
            receipt_run
        )
        self.responses[
            f"repos/synaptent/aragora/actions/runs/{SYNTHETIC_RECEIPT_RUN_ID}/artifacts"
            "?per_page=100&page=1"
        ] = {
            "artifacts": [
                {
                    "expired": False,
                    "id": artifact_id,
                    "name": f"contract-drift-main-receipt-analyzer-{SOURCE_SHA}",
                    "workflow_run": {
                        "head_sha": SOURCE_SHA,
                        "id": SYNTHETIC_RECEIPT_RUN_ID,
                    },
                }
            ],
            "total_count": 1,
        }
        self.responses[
            "repos/synaptent/aragora/actions/runs/"
            f"{SYNTHETIC_RECEIPT_RUN_ID}/attempts/1/jobs?per_page=100&page=1"
        ] = {"jobs": [receipt_job], "total_count": 1}
        self.responses[
            f"https://api.github.com/repos/synaptent/aragora/check-runs/{SYNTHETIC_RECEIPT_JOB_ID}"
        ] = {
            "app": {"id": APP_ID},
            "conclusion": receipt_conclusion,
            "details_url": (
                "https://github.com/synaptent/aragora/actions/runs/"
                f"{SYNTHETIC_RECEIPT_RUN_ID}/job/{SYNTHETIC_RECEIPT_JOB_ID}"
            ),
            "head_sha": SOURCE_SHA,
            "id": SYNTHETIC_RECEIPT_JOB_ID,
            "name": "contract-drift-main-receipt",
            "status": receipt_status,
        }
        for context in _contexts():
            run_id = context["workflow_run_id"]
            check_id = context["check_run_id"]
            job_id = context["job_id"]
            attempt = context["run_attempt"]
            check_url = f"https://api.github.com/repos/synaptent/aragora/check-runs/{check_id}"
            self.responses[f"repos/synaptent/aragora/actions/runs/{run_id}"] = {
                "conclusion": "success",
                "head_sha": HEAD_SHA,
                "id": run_id,
                "repository": {"full_name": "synaptent/aragora"},
                "run_attempt": attempt,
                "status": "completed",
            }
            self.responses[
                "repos/synaptent/aragora/actions/runs/"
                f"{run_id}/attempts/{attempt}/jobs?per_page=100&page=1"
            ] = self.responses.get(
                "repos/synaptent/aragora/actions/runs/"
                f"{run_id}/attempts/{attempt}/jobs?per_page=100&page=1",
                {"jobs": [], "total_count": 0},
            )
            jobs_payload = self.responses[
                "repos/synaptent/aragora/actions/runs/"
                f"{run_id}/attempts/{attempt}/jobs?per_page=100&page=1"
            ]
            jobs_payload["jobs"].append(
                {
                    "check_url": check_url,
                    "conclusion": "success",
                    "head_sha": HEAD_SHA,
                    "id": job_id,
                    "name": context["name"],
                    "run_attempt": attempt,
                    "status": "completed",
                }
            )
            jobs_payload["total_count"] = len(jobs_payload["jobs"])
            self.responses[check_url] = {
                "app": {"id": APP_ID},
                "conclusion": "success",
                "details_url": (
                    f"https://github.com/synaptent/aragora/actions/runs/{run_id}/job/{job_id}"
                ),
                "head_sha": HEAD_SHA,
                "id": check_id,
                "name": context["name"],
                "status": "completed",
            }

    def get_json(self, endpoint: str) -> dict[str, Any]:
        try:
            return copy.deepcopy(self.responses[endpoint])
        except KeyError as exc:
            raise AssertionError(f"unexpected endpoint: {endpoint}") from exc


def _historical_analyzer_result() -> dict[str, Any]:
    result = backfill.ratchet.build_accepted_result(
        mode="receipt",
        repo_root=ROOT,
        inventory_path=ROOT / backfill.inventory_mod.DEFAULT_INVENTORY,
        source_sha=SOURCE_SHA,
        historical_base_sha=PR_BASE_SHA,
        historical_head_sha=HEAD_SHA,
        historical_merge_sha=MERGE_SHA,
        historical_first_parent_sha=FIRST_PARENT_SHA,
    )
    assert result["status"] == "pass"
    return result


def test_receipt_envelope_is_canonical_and_feeds_builder_directly() -> None:
    receipt = backfill.build_historical_receipt_envelope(
        analyzer_result=_historical_analyzer_result(),
        repository="synaptent/aragora",
        workflow_run_id=SYNTHETIC_RECEIPT_RUN_ID,
        run_attempt=1,
        job_id=SYNTHETIC_RECEIPT_JOB_ID,
        artifact_id=SYNTHETIC_RECEIPT_ARTIFACT_ID,
        reader=_ReceiptApiFixture(),
    )
    assert receipt == _input_document()["receipt"]
    raw = backfill._canonical_json_bytes(receipt)
    assert backfill._parse_canonical_json(raw, label="historical receipt") == receipt

    input_document = _input_document()
    input_document["receipt"] = receipt
    built = backfill.build_payload(
        repo_root=ROOT,
        input_document=input_document,
        authority_manifest=_authority_manifest(),
    )
    assert built["receipt"] == receipt


def test_receipt_envelope_rejects_the_still_running_producer_lifecycle() -> None:
    with pytest.raises(ValueError, match="completed success"):
        backfill.build_historical_receipt_envelope(
            analyzer_result=_historical_analyzer_result(),
            repository="synaptent/aragora",
            workflow_run_id=SYNTHETIC_RECEIPT_RUN_ID,
            run_attempt=1,
            job_id=SYNTHETIC_RECEIPT_JOB_ID,
            artifact_id=SYNTHETIC_RECEIPT_ARTIFACT_ID,
            reader=_ReceiptApiFixture(receipt_lifecycle="in_progress"),
        )


def test_receipt_envelope_rejects_a_moved_producer_job_id() -> None:
    with pytest.raises(ValueError, match="job ID"):
        backfill.build_historical_receipt_envelope(
            analyzer_result=_historical_analyzer_result(),
            repository="synaptent/aragora",
            workflow_run_id=SYNTHETIC_RECEIPT_RUN_ID,
            run_attempt=1,
            job_id=SYNTHETIC_RECEIPT_JOB_ID + 1,
            artifact_id=SYNTHETIC_RECEIPT_ARTIFACT_ID,
            reader=_ReceiptApiFixture(),
        )


def test_receipt_envelope_rejects_an_artifact_outside_the_producer_run() -> None:
    with pytest.raises(ValueError, match="artifact"):
        backfill.build_historical_receipt_envelope(
            analyzer_result=_historical_analyzer_result(),
            repository="synaptent/aragora",
            workflow_run_id=SYNTHETIC_RECEIPT_RUN_ID,
            run_attempt=1,
            job_id=SYNTHETIC_RECEIPT_JOB_ID,
            artifact_id=SYNTHETIC_RECEIPT_ARTIFACT_ID + 1,
            reader=_ReceiptApiFixture(),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda fixture: fixture.responses.__setitem__(
                f"repos/synaptent/aragora/actions/runs/{SYNTHETIC_RECEIPT_RUN_ID}",
                {
                    **fixture.responses[
                        f"repos/synaptent/aragora/actions/runs/{SYNTHETIC_RECEIPT_RUN_ID}"
                    ],
                    "head_sha": MERGE_SHA,
                },
            ),
            "source SHA",
        ),
        (
            lambda fixture: fixture.responses[
                "https://api.github.com/repos/synaptent/aragora/check-runs/"
                f"{SYNTHETIC_RECEIPT_JOB_ID}"
            ]["app"].__setitem__("id", 99999),
            "GitHub Actions app",
        ),
        (
            lambda fixture: fixture.responses[
                "https://api.github.com/repos/synaptent/aragora/check-runs/87709243174"
            ].__setitem__("conclusion", "failure"),
            "completed success",
        ),
    ],
)
def test_receipt_envelope_rejects_malformed_authenticated_identity(
    mutation,
    message: str,
) -> None:
    fixture = _ReceiptApiFixture()
    mutation(fixture)
    with pytest.raises(ValueError, match=message):
        backfill.build_historical_receipt_envelope(
            analyzer_result=_historical_analyzer_result(),
            repository="synaptent/aragora",
            workflow_run_id=SYNTHETIC_RECEIPT_RUN_ID,
            run_attempt=1,
            job_id=SYNTHETIC_RECEIPT_JOB_ID,
            artifact_id=SYNTHETIC_RECEIPT_ARTIFACT_ID,
            reader=fixture,
        )


def test_tampered_assets_fail_closed(
    payload: dict[str, Any],
    assets: dict[str, bytes],
) -> None:
    with pytest.raises(ValueError, match="terminal LF"):
        backfill.validate_capsule_bytes(
            manifest_bytes=assets["manifest.json"],
            payload_bytes=assets["payload.json"] + b" ",
            checksums_bytes=assets["checksums.txt"],
        )
    with pytest.raises(ValueError, match="manifest binding"):
        tampered_manifest = json.loads(assets["manifest.json"])
        tampered_manifest["pr"] = 1
        backfill.validate_capsule_bytes(
            manifest_bytes=backfill._canonical_json_bytes(tampered_manifest),
            payload_bytes=assets["payload.json"],
            checksums_bytes=assets["checksums.txt"],
        )
    with pytest.raises(ValueError, match="checksum asset"):
        backfill.validate_capsule_bytes(
            manifest_bytes=assets["manifest.json"],
            payload_bytes=assets["payload.json"],
            checksums_bytes=b"0" * len(assets["checksums.txt"]),
        )


def test_attestation_subject_signer_and_repository_are_fail_closed(
    payload: dict[str, Any],
    assets: dict[str, bytes],
) -> None:
    evidence = backfill.build_external_attestation_evidence(
        payload=payload,
        assets=assets,
    )
    wrong_subject = copy.deepcopy(evidence)
    wrong_subject["subject_sha256s"]["payload.json"] = "0" * 64
    with pytest.raises(ValueError, match="exact asset bytes"):
        backfill.validate_external_attestation(
            wrong_subject,
            payload=payload,
            assets=assets,
        )
    for field, value in (
        ("signer_san_regexp", "^https://example.invalid$"),
        ("repository", "other/repository"),
        ("source_digest", MERGE_SHA),
    ):
        mismatch = copy.deepcopy(evidence)
        mismatch[field] = value
        with pytest.raises(ValueError, match=f"{field} mismatch"):
            backfill.validate_external_attestation(
                mismatch,
                payload=payload,
                assets=assets,
            )


def test_rule_suite_and_projection_edges_are_fail_closed(payload: dict[str, Any]) -> None:
    failed_rule = copy.deepcopy(payload)
    failed_rule["rule_suite"]["result"] = "fail"
    with pytest.raises(ValueError, match="did not pass"):
        backfill.validate_payload(failed_rule)

    missing_edge = copy.deepcopy(payload)
    missing_edge["projection"]["records"][0]["operation_edges"].clear()
    with pytest.raises(ValueError, match="no method-specific edges"):
        backfill.validate_payload(missing_edge)


def test_rule_suite_after_sha_bound_to_historical_merge_fails_closed(
    payload: dict[str, Any],
) -> None:
    # The repository's rule-suite ledger began after the 2026-07-16 historical
    # squash merge, so no passing record with after_sha == merge_sha ever
    # existed or can exist; a payload claiming one must be rejected.
    candidate = copy.deepcopy(payload)
    candidate["rule_suite"]["after_sha"] = MERGE_SHA
    with pytest.raises(ValueError, match="rule-suite after SHA mismatch"):
        backfill.validate_payload(candidate)


def test_rule_suite_after_sha_bound_to_implementation_source_validates(
    payload: dict[str, Any],
) -> None:
    candidate = copy.deepcopy(payload)
    candidate["rule_suite"]["after_sha"] = SOURCE_SHA
    validated = backfill.validate_payload(candidate)
    assert validated["rule_suite"]["after_sha"] == validated["authority"]["source_sha"]


def test_live_rule_suite_record_requires_normalized_repository_name() -> None:
    # Field values from the live passing record for the merged implementation
    # push (rule-suite ID 3821290531). The raw rule-suites API returns the bare
    # repository name ("aragora"), so input construction must normalize it to
    # the owner/name form before validation; raw persisted bytes stay bare.
    record = {
        "after_sha": IMPLEMENTATION_PUSH_SHA,
        "id": IMPLEMENTATION_RULE_SUITE_ID,
        "ref": "refs/heads/main",
        "repository_id": 1126097105,
        "repository_name": "synaptent/aragora",
        "result": "pass",
        "schema": backfill.RULE_SUITE_SCHEMA,
    }
    validated = backfill._validate_rule_suite(
        dict(record),
        repository="synaptent/aragora",
        source_sha=IMPLEMENTATION_PUSH_SHA,
    )
    assert validated == record

    bare = {**record, "repository_name": "aragora"}
    with pytest.raises(ValueError, match="rule-suite repository mismatch"):
        backfill._validate_rule_suite(
            bare,
            repository="synaptent/aragora",
            source_sha=IMPLEMENTATION_PUSH_SHA,
        )

    before_push = {**record, "after_sha": "80671081ec1558aaf63460f39980b43601a7c44d"}
    with pytest.raises(ValueError, match="rule-suite after SHA mismatch"):
        backfill._validate_rule_suite(
            before_push,
            repository="synaptent/aragora",
            source_sha=IMPLEMENTATION_PUSH_SHA,
        )


def test_movement_is_fail_closed() -> None:
    stable = {
        "main_sha_after": SOURCE_SHA,
        "main_sha_before": SOURCE_SHA,
        "newest_run_attempt_after": 1,
        "newest_run_attempt_before": 1,
        "newest_workflow_run_id_after": SYNTHETIC_RECEIPT_RUN_ID,
        "newest_workflow_run_id_before": SYNTHETIC_RECEIPT_RUN_ID,
    }
    assert backfill.validate_movement_snapshot(stable) == stable
    moved_main = {**stable, "main_sha_after": "f" * 40}
    with pytest.raises(ValueError, match="main moved"):
        backfill.validate_movement_snapshot(moved_main)
    moved_run = {**stable, "newest_run_attempt_after": 2}
    with pytest.raises(ValueError, match="execution moved"):
        backfill.validate_movement_snapshot(moved_run)


def test_historical_git_fixture_is_exact() -> None:
    assert ensure_pr_9320_head(ROOT) == HEAD_SHA
    assert _git_text("rev-parse", f"{MERGE_SHA}^1") == FIRST_PARENT_SHA
    assert (
        subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", PR_BASE_SHA, HEAD_SHA]
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", PR_BASE_SHA, FIRST_PARENT_SHA]
        ).returncode
        == 0
    )
    assert _git_text("rev-parse", f"{HEAD_SHA}^{{tree}}") == HEAD_TREE_SHA
    assert _git_text("rev-parse", f"{MERGE_SHA}^{{tree}}") == MERGE_TREE_SHA
    assert _git_text("diff", "--name-only", FIRST_PARENT_SHA, MERGE_SHA).splitlines() == (
        EXPECTED_PATHS
    )
    patch_args = (
        "-c",
        "diff.noprefix=false",
        "-c",
        "diff.mnemonicPrefix=false",
        "-c",
        "diff.algorithm=myers",
        "-c",
        "diff.context=3",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--no-color",
        "--no-indent-heuristic",
        "--full-index",
        "--unified=3",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "-O/dev/null",
    )
    head_patch = backfill._git_bytes(
        ROOT,
        *patch_args,
        f"{PR_BASE_SHA}^{{tree}}",
        f"{HEAD_SHA}^{{tree}}",
    )
    merge_patch = backfill._git_bytes(
        ROOT,
        *patch_args,
        f"{FIRST_PARENT_SHA}^{{tree}}",
        f"{MERGE_SHA}^{{tree}}",
    )
    assert head_patch == merge_patch
    assert len(merge_patch) == 6054
    assert backfill._sha256(merge_patch) == PATCH_SHA256


def test_builder_patch_binding_ignores_hostile_git_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    global_config = tmp_path / "hostile-gitconfig"
    global_config.write_text(
        "[diff]\n"
        "\tnoprefix = true\n"
        "\talgorithm = histogram\n"
        "\tcontext = 19\n"
        "[core]\n"
        "\tabbrev = 40\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.delenv("GIT_CONFIG_NOSYSTEM", raising=False)
    payload = backfill.build_payload(
        repo_root=ROOT,
        input_document=_input_document(),
        authority_manifest=_authority_manifest(),
    )
    historical = payload["historical_pull_request"]
    assert historical["first_parent_patch_byte_length"] == 6054
    assert historical["first_parent_patch_sha256"] == PATCH_SHA256


def test_builder_isolates_every_git_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []
    real_run = subprocess.run
    authority_manifest = _authority_manifest()

    def recording_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        if (
            argv
            and Path(argv[0]).name == "git"
            and argv[1:3] == ["-C", str(ROOT)]
            and "env" in kwargs
        ):
            calls.append((argv, kwargs["env"]))
        return real_run(argv, **kwargs)

    monkeypatch.setattr(backfill.subprocess, "run", recording_run)
    backfill.build_payload(
        repo_root=ROOT,
        input_document=_input_document(),
        authority_manifest=authority_manifest,
    )
    assert calls
    for argv, env in calls:
        assert Path(argv[0]).name == "git"
        assert env["GIT_CONFIG_GLOBAL"] == os.devnull
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert env["GIT_NO_REPLACE_OBJECTS"] == "1"
        assert env["LC_ALL"] == "C"


def test_builder_payload_bytes_are_environment_independent(
    assets: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # core.autocrlf reaches `git archive` inside the authority-manifest
    # generator when the ambient git environment leaks into that subprocess,
    # which is exactly the channel that made fixed-ref rebuilds session-
    # dependent; the rebuild below must stay byte-identical anyway.
    hostile_home = tmp_path / "hostile-home"
    hostile_home.mkdir()
    (hostile_home / ".gitconfig").write_text(
        "[core]\n"
        "\tautocrlf = true\n"
        "\tquotepath = false\n"
        "[diff]\n"
        "\talgorithm = histogram\n"
        "[log]\n"
        "\tshowSignature = true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(hostile_home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("GIT_CONFIG_GLOBAL", raising=False)
    monkeypatch.delenv("GIT_CONFIG_NOSYSTEM", raising=False)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Hostile Session")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "hostile@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Hostile Session")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "hostile@example.invalid")
    rebuilt = backfill.build_payload(
        repo_root=ROOT,
        input_document=_input_document(),
    )
    assert backfill.build_capsule_bytes(rebuilt) == assets


def test_builder_cli_is_supported_from_outside_the_repository(tmp_path: Path) -> None:
    env = {
        "HOME": os.environ.get("HOME", ""),
        "PATH": os.environ["PATH"],
        "PYTHONNOUSERSITE": "1",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-B",
            str(ROOT / "scripts/build_contract_drift_historical_backfill.py"),
            "--help",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "--verify-dir" in result.stdout
    assert "--build-receipt-envelope" in result.stdout


def test_verify_directory_rejects_rogue_subdirectories(
    tmp_path: Path,
    assets: dict[str, bytes],
) -> None:
    output = tmp_path / "capsule"
    backfill.write_capsule(output, assets)
    (output / "rogue").mkdir()
    with pytest.raises(ValueError, match="exact three regular files"):
        backfill._verify_directory(output)
