#!/usr/bin/env python3
"""Build and verify canonical Contract Drift historical-backfill capsules."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NoReturn, Protocol
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import check_contract_drift_ratchet as ratchet
from scripts import generate_contract_drift_inventory as inventory_mod

PAYLOAD_SCHEMA = "contract-drift-historical-backfill-successor-v2"
MANIFEST_SCHEMA = "contract-drift-historical-backfill-manifest-v2"
RECEIPT_SCHEMA = "contract-drift-historical-backfill-receipt-v1"
ATTESTATION_SCHEMA = "contract-drift-historical-backfill-attestation-v1"
RULE_SUITE_SCHEMA = "contract-drift-historical-backfill-rule-suite-v1"
CAPSULE_SCHEMA_PATH = "scripts/schemas/contract-drift-historical-backfill-capsule-v2.schema.json"
CANONICAL_SERIALIZATION = (
    "UTF-8; no BOM; object keys sorted; compact separators comma/colon; "
    "declared array orders; exactly one terminal LF"
)
REQUIRED_CONTEXT_NAMES = (
    "lint",
    "typecheck",
    "sdk-parity",
    "Generate & Validate",
    "TypeScript SDK Type Check",
    "aragora-merge-quorum",
)
EXPECTED_GITHUB_ACTIONS_APP_ID = 15368
RECEIPT_JOB_NAME = "contract-drift-main-receipt"
MAX_GITHUB_PAGES = 100
EXPECTED_ASSET_NAMES = ("manifest.json", "payload.json", "checksums.txt")
PR_9320_BASE_SHA = "14d1ef53e23c5466c0491ed93f72752944c78cd4"
PR_9320_HEAD_SHA = "aba6b14c94eca3a9c825b1a303ea67684d5f8daa"
PR_9320_MERGE_SHA = "0b28f68b9f4d204ae14814169093723ea84c1364"
PR_9320_FIRST_PARENT_SHA = "e448b840dad03ee28accd218c14a27fa8b87c7b4"
PR_9320_HEAD_TREE_SHA = "e5c6c3d07a918cf43fffed6d4a9f472bc10a674a"
PR_9320_MERGE_TREE_SHA = "79c1c374eed261c42468dc526d837e726e73425a"
PR_9320_FIRST_PARENT_PATCH_BYTE_LENGTH = 6054
PR_9320_FIRST_PARENT_PATCH_SHA256 = (
    "7c53f6c8b9bd17847cdb4ecc5dfa1c7aa1699105faabc47439a4437709a175b4"
)
PR_9320_SUPERSEDED_RELEASE_API_ID = 363450207
PR_9320_SUPERSEDED_RELEASE_TAG = "backfill-0b28f68b9f4d204ae14814169093723ea84c1364"
VALID_METHODS = frozenset(
    {
        "CONNECT",
        "DELETE",
        "GET",
        "HEAD",
        "OPTIONS",
        "PATCH",
        "POST",
        "PUT",
        "TRACE",
    }
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
WORKFLOW_PATH = ".github/workflows/contract-drift-governance.yml"
ATTESTATION_WORKFLOW_PATH = ".github/workflows/contract-drift-boundary.yml"

PAYLOAD_FIELDS = frozenset(
    {
        "attestation",
        "authority",
        "canonical_serialization",
        "capsule_schema",
        "disposition",
        "historical_pull_request",
        "projection",
        "receipt",
        "release",
        "repository",
        "rule_suite",
        "schema",
        "supersedes",
    }
)
HISTORICAL_PR_FIELDS = frozenset(
    {
        "actor",
        "base_sha",
        "changed_files",
        "first_parent_patch_byte_length",
        "first_parent_patch_sha256",
        "first_parent_sha",
        "head_sha",
        "head_tree_sha",
        "merge_sha",
        "merge_tree_sha",
        "merged_at",
        "pr",
    }
)
CHANGED_FILE_FIELDS = frozenset({"additions", "deletions", "path"})
AUTHORITY_FIELDS = frozenset(
    {
        "active_inventory_sha256",
        "analyzer_bundle_sha256",
        "authority_manifest_sha256",
        "category_counts_sha256",
        "dependency_manifest_sha256",
        "inventory_sha256",
        "operation_projection_record_digest_set_sha256",
        "operation_projection_schema_sha256",
        "original_record_id_set_sha256",
        "public_symbol_sha256",
        "route_boundary_sha256",
        "sdk_original_record_id_set_sha256",
        "sdk_provenance_record_digest_set_sha256",
        "core_original_record_id_set_sha256",
        "extended_original_record_id_set_sha256",
        "source_sha",
    }
)
PROJECTION_FIELDS = frozenset(
    {
        "edge_count",
        "max_edges",
        "membership_count",
        "multi_edge_originals",
        "record_digest_set_sha256",
        "records",
    }
)
PROJECTION_RECORD_FIELDS = frozenset(
    {
        "category",
        "exact_historical_literal_record",
        "operation_edges",
        "original_record_id",
        "projection_status",
        "record_sha256",
        "schema",
        "sdk_language",
    }
)
PROJECTION_EDGE_FIELDS = frozenset(
    {"evidence", "method", "normalized_operation", "normalized_path"}
)
RECEIPT_FIELDS = frozenset(
    {
        "artifact_name",
        "base_sha",
        "check_run_id",
        "conclusion",
        "first_parent_sha",
        "head_sha",
        "job_id",
        "merge_sha",
        "required_contexts",
        "run_attempt",
        "schema",
        "source_sha",
        "workflow_name",
        "workflow_path",
        "workflow_run_id",
    }
)
CONTEXT_FIELDS = frozenset(
    {
        "app_id",
        "check_run_id",
        "conclusion",
        "job_id",
        "name",
        "run_attempt",
        "workflow_run_id",
    }
)
RELEASE_FIELDS = frozenset(
    {
        "asset_names",
        "exact_full_sha_tag",
        "immutable",
        "release_api_id",
        "tag_name",
        "tag_target_sha",
        "verified",
    }
)
ATTESTATION_FIELDS = frozenset(
    {
        "predicate_type",
        "repository",
        "schema",
        "signer_san_regexp",
        "source_digest",
        "subject_asset_names",
        "verified",
        "workflow",
        "workflow_path",
    }
)
ATTESTATION_EVIDENCE_FIELDS = frozenset(
    {
        "predicate_type",
        "repository",
        "schema",
        "signer_san_regexp",
        "source_digest",
        "subject_sha256s",
        "verified",
        "workflow",
        "workflow_path",
    }
)
RULE_SUITE_FIELDS = frozenset(
    {
        "after_sha",
        "id",
        "ref",
        "repository_id",
        "repository_name",
        "result",
        "schema",
    }
)
MOVEMENT_FIELDS = frozenset(
    {
        "main_sha_after",
        "main_sha_before",
        "newest_run_attempt_after",
        "newest_run_attempt_before",
        "newest_workflow_run_id_after",
        "newest_workflow_run_id_before",
    }
)
SUPERSEDES_FIELDS = frozenset({"reason", "release_api_id", "status", "tag_name"})
MANIFEST_FIELDS = frozenset(
    {
        "asset_names",
        "first_parent_sha",
        "merge_sha",
        "payload_byte_length",
        "payload_sha256",
        "pr",
        "release_api_id",
        "schema",
        "tag_name",
    }
)


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fail(message: str) -> NoReturn:
    raise ValueError(message)


def _require_exact_fields(value: Any, expected: frozenset[str], *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        _fail(f"{label} fields are incomplete or noncanonical")
    return value


def _require_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        _fail(f"{label} must be a nonempty string")
    return value


def _require_positive_int(value: Any, *, label: str, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{label} must be an integer")
    if value < 0 if allow_zero else value <= 0:
        _fail(f"{label} is outside the allowed range")
    return value


def _require_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        _fail(f"{label} is not a lowercase full commit SHA")
    return value


def _require_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} is not a lowercase SHA-256")
    return value


def _parse_canonical_json(raw: bytes, *, label: str) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf"):
        _fail(f"{label} has a UTF-8 BOM")
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n") or b"\n" in raw[:-1]:
        _fail(f"{label} must have exactly one terminal LF")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=ratchet._duplicate_key_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        _fail(f"{label} is not duplicate-free UTF-8 JSON: {exc}")
    if not isinstance(value, dict) or raw != _canonical_json_bytes(value):
        _fail(f"{label} is not canonical compact sorted-key JSON")
    return value


def _git_text(repo_root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        check=True,
        env=_git_env(),
        text=True,
    ).stdout.strip()


def _git_env() -> dict[str, str]:
    # Ambient GIT_* variables (GIT_CONFIG_COUNT/GIT_CONFIG_PARAMETERS
    # command-scope config, identity/date overrides, object-store redirection)
    # bypass the two config pins below and make fixed-ref output
    # session-dependent, so drop them all before pinning.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "LC_ALL": "C",
        }
    )
    return env


def _git_bytes(repo_root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        check=True,
        env=_git_env(),
    ).stdout


def _resolve_commit(repo_root: Path, value: str, *, label: str) -> str:
    _require_sha(value, label=label)
    try:
        resolved = _git_text(repo_root, "rev-parse", "--verify", f"{value}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        _fail(f"{label} is unavailable: {value}")
    if resolved != value:
        _fail(f"{label} does not resolve to itself")
    return resolved


def _load_json_path(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=ratchet._duplicate_key_object
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        _fail(f"{label} is unavailable or malformed: {exc}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


class ApiReader(Protocol):
    def get_json(self, endpoint: str) -> dict[str, Any]: ...


class GhApiReader:
    """Authenticated read-only GitHub transport backed by ``gh api``."""

    def __init__(self, *, timeout_seconds: int = 60):
        self.timeout_seconds = timeout_seconds

    def get_json(self, endpoint: str) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                [
                    "gh",
                    "api",
                    "--method",
                    "GET",
                    "-H",
                    "Accept: application/vnd.github+json",
                    endpoint,
                ],
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            _fail(f"authenticated GitHub GET timed out: {endpoint}")
        if proc.returncode != 0:
            error = proc.stderr.decode("utf-8", errors="replace").strip()
            _fail(f"authenticated GitHub GET failed for {endpoint}: {error}")
        try:
            payload = json.loads(
                proc.stdout,
                object_pairs_hook=ratchet._duplicate_key_object,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            _fail(f"authenticated GitHub response is malformed for {endpoint}: {exc}")
        if not isinstance(payload, dict):
            _fail(f"authenticated GitHub response is not an object: {endpoint}")
        return payload


def _github_collection(
    reader: ApiReader,
    endpoint: str,
    *,
    collection_key: str,
    identity: Callable[[dict[str, Any]], Any],
    label: str,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    reported_total: int | None = None
    for page in range(1, MAX_GITHUB_PAGES + 1):
        separator = "&" if "?" in endpoint else "?"
        page_endpoint = f"{endpoint}{separator}per_page=100&page={page}"
        payload = reader.get_json(page_endpoint)
        page_records = payload.get(collection_key)
        if not isinstance(page_records, list) or not all(
            isinstance(record, dict) for record in page_records
        ):
            _fail(f"{label} page is malformed")
        total = _require_positive_int(
            payload.get("total_count"),
            label=f"{label} total_count",
            allow_zero=True,
        )
        if reported_total is None:
            reported_total = total
        elif reported_total != total:
            _fail(f"{label} total_count moved between pages")
        existing = {identity(record) for record in records}
        page_identities = [identity(record) for record in page_records]
        if (
            any(item is None for item in page_identities)
            or len(page_identities) != len(set(page_identities))
            or existing.intersection(page_identities)
        ):
            _fail(f"{label} pagination returned duplicate or missing identities")
        records.extend(page_records)
        if len(page_records) < 100:
            break
    else:
        _fail(f"{label} pagination did not terminate")
    if reported_total != len(records):
        _fail(f"{label} records do not reconcile to total_count")
    return records


def _require_github_run(
    reader: ApiReader,
    *,
    repository: str,
    workflow_run_id: int,
    run_attempt: int,
    head_sha: str,
    label: str,
    require_dispatch: bool,
) -> dict[str, Any]:
    run = reader.get_json(f"repos/{repository}/actions/runs/{workflow_run_id}")
    repo = run.get("repository")
    repository_name = repo.get("full_name") if isinstance(repo, dict) else None
    if (
        run.get("id") != workflow_run_id
        or run.get("run_attempt") != run_attempt
        or run.get("head_sha") != head_sha
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or repository_name != repository
    ):
        _fail(f"{label} run is not a completed success for the exact repository/source SHA")
    if require_dispatch and (
        run.get("event") != "workflow_dispatch" or run.get("path") != WORKFLOW_PATH
    ):
        _fail(f"{label} run is not the exact historical workflow dispatch")
    return run


def _require_github_job_check(
    reader: ApiReader,
    *,
    repository: str,
    workflow_run_id: int,
    run_attempt: int,
    head_sha: str,
    expected_name: str,
    label: str,
    expected_job_id: int | None = None,
) -> dict[str, Any]:
    endpoint = f"repos/{repository}/actions/runs/{workflow_run_id}/attempts/{run_attempt}/jobs"
    jobs = _github_collection(
        reader,
        endpoint,
        collection_key="jobs",
        identity=lambda job: job.get("id"),
        label=f"{label} jobs",
    )
    matching = [job for job in jobs if job.get("name") == expected_name]
    if len(matching) != 1:
        _fail(f"{label} attempt does not contain exactly one expected job")
    job = matching[0]
    if expected_job_id is not None and job.get("id") != expected_job_id:
        _fail(f"{label} job ID does not match the completed producer identity")
    if (
        job.get("run_attempt") != run_attempt
        or job.get("head_sha") != head_sha
        or job.get("status") != "completed"
        or job.get("conclusion") != "success"
    ):
        _fail(f"{label} job is not a completed success for the exact attempt/source SHA")
    job_id = _require_positive_int(job.get("id"), label=f"{label} job ID")
    check_url = _require_string(
        job.get("check_url") or job.get("check_run_url"),
        label=f"{label} check URL",
    )
    parsed = urlparse(check_url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "api.github.com"
        or not parsed.path.startswith(f"/repos/{repository}/check-runs/")
    ):
        _fail(f"{label} check URL is bound to another repository")
    check = reader.get_json(check_url)
    app = check.get("app")
    app_id = app.get("id") if isinstance(app, dict) else None
    if app_id != EXPECTED_GITHUB_ACTIONS_APP_ID:
        _fail(f"{label} check is not authenticated by the GitHub Actions app")
    details_url = _require_string(check.get("details_url"), label=f"{label} details URL")
    if (
        check.get("name") != expected_name
        or check.get("head_sha") != head_sha
        or check.get("status") != "completed"
        or check.get("conclusion") != "success"
        or f"/actions/runs/{workflow_run_id}/job/{job_id}" not in details_url
    ):
        _fail(f"{label} check is not a completed success for the exact job/run/source SHA")
    return {
        "app_id": app_id,
        "check_run_id": _require_positive_int(
            check.get("id"),
            label=f"{label} check-run ID",
        ),
        "conclusion": "success",
        "job_id": job_id,
        "name": expected_name,
        "run_attempt": run_attempt,
        "workflow_run_id": workflow_run_id,
    }


def _require_github_run_artifact(
    reader: ApiReader,
    *,
    repository: str,
    workflow_run_id: int,
    artifact_id: int,
    head_sha: str,
) -> None:
    artifacts = _github_collection(
        reader,
        f"repos/{repository}/actions/runs/{workflow_run_id}/artifacts",
        collection_key="artifacts",
        identity=lambda artifact: artifact.get("id"),
        label="historical receipt artifacts",
    )
    matching = [artifact for artifact in artifacts if artifact.get("id") == artifact_id]
    if len(matching) != 1:
        _fail("historical receipt artifact is not bound to the completed producer run")
    artifact = matching[0]
    workflow_run = artifact.get("workflow_run")
    if (
        artifact.get("expired") is not False
        or artifact.get("name") != f"contract-drift-main-receipt-analyzer-{head_sha}"
        or not isinstance(workflow_run, dict)
        or workflow_run.get("id") != workflow_run_id
        or workflow_run.get("head_sha") != head_sha
    ):
        _fail("historical receipt artifact identity contradicts the completed producer run")


def build_historical_receipt_envelope(
    *,
    analyzer_result: Mapping[str, Any],
    repository: str,
    workflow_run_id: int,
    run_attempt: int,
    job_id: int,
    artifact_id: int,
    reader: ApiReader,
) -> dict[str, Any]:
    if REPOSITORY_RE.fullmatch(repository) is None:
        _fail("historical receipt repository is malformed")
    if analyzer_result.get("status") != "pass" or analyzer_result.get("passing") is not True:
        _fail("historical receipt analyzer did not pass")
    execution = analyzer_result.get("execution")
    if not isinstance(execution, dict):
        _fail("historical receipt analyzer execution is missing")
    source_sha = _require_sha(execution.get("source_sha"), label="receipt source SHA")
    base_sha = _require_sha(execution.get("base_sha"), label="receipt base SHA")
    head_sha = _require_sha(execution.get("head_sha"), label="receipt head SHA")
    merge_sha = _require_sha(execution.get("merge_sha"), label="receipt merge SHA")
    first_parent_sha = _require_sha(
        execution.get("first_parent_sha"),
        label="receipt first-parent SHA",
    )
    if analyzer_result.get("source_sha") != source_sha:
        _fail("historical receipt analyzer source SHA is contradictory")

    workflow_run_id = _require_positive_int(
        workflow_run_id,
        label="historical receipt workflow run ID",
    )
    run_attempt = _require_positive_int(
        run_attempt,
        label="historical receipt run attempt",
    )
    job_id = _require_positive_int(
        job_id,
        label="historical receipt producer job ID",
    )
    artifact_id = _require_positive_int(
        artifact_id,
        label="historical receipt analyzer artifact ID",
    )
    _require_github_run(
        reader,
        repository=repository,
        workflow_run_id=workflow_run_id,
        run_attempt=run_attempt,
        head_sha=source_sha,
        label="historical receipt",
        require_dispatch=True,
    )
    _require_github_run_artifact(
        reader,
        repository=repository,
        workflow_run_id=workflow_run_id,
        artifact_id=artifact_id,
        head_sha=source_sha,
    )
    receipt_job = _require_github_job_check(
        reader,
        repository=repository,
        workflow_run_id=workflow_run_id,
        run_attempt=run_attempt,
        head_sha=source_sha,
        expected_name=RECEIPT_JOB_NAME,
        label="historical receipt",
        expected_job_id=job_id,
    )

    contexts: list[dict[str, Any]] = []
    for context in _historical_context_bindings():
        context_run_id = _require_positive_int(
            context.get("workflow_run_id"),
            label=f"historical context {context.get('name')} workflow run ID",
        )
        context_attempt = _require_positive_int(
            context.get("run_attempt"),
            label=f"historical context {context.get('name')} run attempt",
        )
        context_name = _require_string(
            context.get("name"),
            label="historical context name",
        )
        _require_github_run(
            reader,
            repository=repository,
            workflow_run_id=context_run_id,
            run_attempt=context_attempt,
            head_sha=head_sha,
            label=f"historical context {context_name}",
            require_dispatch=False,
        )
        authenticated = _require_github_job_check(
            reader,
            repository=repository,
            workflow_run_id=context_run_id,
            run_attempt=context_attempt,
            head_sha=head_sha,
            expected_name=context_name,
            label=f"historical context {context_name}",
        )
        if authenticated != context:
            _fail(f"historical context {context_name} identity moved")
        contexts.append(authenticated)

    receipt = {
        "artifact_name": f"contract-drift-main-receipt-{merge_sha}",
        "base_sha": base_sha,
        "check_run_id": receipt_job["check_run_id"],
        "conclusion": "success",
        "first_parent_sha": first_parent_sha,
        "head_sha": head_sha,
        "job_id": receipt_job["job_id"],
        "merge_sha": merge_sha,
        "required_contexts": contexts,
        "run_attempt": run_attempt,
        "schema": RECEIPT_SCHEMA,
        "source_sha": source_sha,
        "workflow_name": "Contract Drift Governance",
        "workflow_path": WORKFLOW_PATH,
        "workflow_run_id": workflow_run_id,
    }
    return _validate_receipt(
        receipt,
        authority_source_sha=source_sha,
        base_sha=base_sha,
        head_sha=head_sha,
        merge_sha=merge_sha,
        first_parent_sha=first_parent_sha,
    )


def _historical_context_bindings() -> list[dict[str, Any]]:
    return [
        {
            "app_id": EXPECTED_GITHUB_ACTIONS_APP_ID,
            "check_run_id": 87709243174,
            "conclusion": "success",
            "job_id": 87709243174,
            "name": "lint",
            "run_attempt": 1,
            "workflow_run_id": 29524359563,
        },
        {
            "app_id": EXPECTED_GITHUB_ACTIONS_APP_ID,
            "check_run_id": 87709180560,
            "conclusion": "success",
            "job_id": 87709180560,
            "name": "typecheck",
            "run_attempt": 1,
            "workflow_run_id": 29524359563,
        },
        {
            "app_id": EXPECTED_GITHUB_ACTIONS_APP_ID,
            "check_run_id": 87709276751,
            "conclusion": "success",
            "job_id": 87709276751,
            "name": "sdk-parity",
            "run_attempt": 1,
            "workflow_run_id": 29524359665,
        },
        {
            "app_id": EXPECTED_GITHUB_ACTIONS_APP_ID,
            "check_run_id": 87709726971,
            "conclusion": "success",
            "job_id": 87709726971,
            "name": "Generate & Validate",
            "run_attempt": 1,
            "workflow_run_id": 29524359572,
        },
        {
            "app_id": EXPECTED_GITHUB_ACTIONS_APP_ID,
            "check_run_id": 87709013895,
            "conclusion": "success",
            "job_id": 87709013895,
            "name": "TypeScript SDK Type Check",
            "run_attempt": 1,
            "workflow_run_id": 29524359727,
        },
        {
            "app_id": EXPECTED_GITHUB_ACTIONS_APP_ID,
            "check_run_id": 87728267780,
            "conclusion": "success",
            "job_id": 87728267780,
            "name": "aragora-merge-quorum",
            "run_attempt": 3,
            "workflow_run_id": 29524359568,
        },
    ]


def _load_inventory_at_ref(repo_root: Path, source_sha: str) -> dict[str, Any]:
    try:
        raw = _git_bytes(
            repo_root,
            "show",
            f"{source_sha}:{inventory_mod.DEFAULT_INVENTORY}",
        )
        value = json.loads(raw, object_pairs_hook=ratchet._duplicate_key_object)
    except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError) as exc:
        _fail(f"accepted authority inventory is unavailable at {source_sha}: {exc}")
    if not isinstance(value, dict):
        _fail("accepted authority inventory is malformed")
    return value


def _load_authority_manifest(repo_root: Path, source_sha: str) -> dict[str, Any]:
    inventory_script = REPO_ROOT / "scripts/generate_contract_drift_inventory.py"
    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            str(inventory_script),
            "--repo-root",
            str(repo_root),
            "--authority-manifest",
            "--ref",
            source_sha,
        ],
        cwd=repo_root,
        capture_output=True,
        # The generator shells out to git without scrubbing, so its whole
        # child tree must inherit the pinned git environment or the manifest
        # digest embedded in the payload absorbs session git config.
        env=_git_env(),
    )
    if proc.returncode != 0:
        _fail(
            "exact-ref authority manifest generation failed: "
            + proc.stdout.decode("utf-8", errors="replace").strip()
        )
    try:
        value = json.loads(proc.stdout, object_pairs_hook=ratchet._duplicate_key_object)
    except (json.JSONDecodeError, ValueError) as exc:
        _fail(f"exact-ref authority manifest is malformed: {exc}")
    if not isinstance(value, dict):
        _fail("exact-ref authority manifest must be an object")
    return value


def _authority_summary(
    *,
    authority_manifest: dict[str, Any],
    accepted_authority: dict[str, Any],
    source_sha: str,
) -> dict[str, Any]:
    repo_files = authority_manifest.get("repo_files")
    inventory = authority_manifest.get("inventory")
    if not isinstance(repo_files, list) or not all(isinstance(item, dict) for item in repo_files):
        _fail("authority manifest repository closure is malformed")
    if not isinstance(inventory, dict):
        _fail("authority manifest inventory binding is malformed")
    summary = ratchet._authority_summary(authority_manifest)
    canonical = accepted_authority.get("canonical_artifacts")
    cohort = canonical.get("original_cohort") if isinstance(canonical, dict) else None
    provenance = canonical.get("sdk_provenance") if isinstance(canonical, dict) else None
    if not isinstance(cohort, dict) or not isinstance(provenance, dict):
        _fail("accepted authority canonical artifacts are malformed")
    projection = cohort.get("operation_projection")
    category_counts = cohort.get("counts", {}).get("by_category")
    if not isinstance(projection, dict) or not isinstance(category_counts, dict):
        _fail("accepted authority projection or category counts are malformed")
    projection_descriptor = {
        "one_to_many_rule": projection.get("one_to_many_rule"),
        "record_digest_encoding": projection.get("record_digest_encoding"),
        "schema": projection.get("schema"),
        "schema_version": 1,
    }
    if (
        not isinstance(projection_descriptor["one_to_many_rule"], str)
        or not projection_descriptor["one_to_many_rule"]
        or not isinstance(projection_descriptor["record_digest_encoding"], str)
        or not projection_descriptor["record_digest_encoding"]
        or projection_descriptor["schema"] != "cdg-operation-projection-v1"
    ):
        _fail("accepted authority operation projection schema is malformed")
    partition = provenance.get("partition")
    if not isinstance(partition, dict):
        _fail("accepted authority SDK partition is malformed")
    return {
        "active_inventory_sha256": _require_sha256(
            accepted_authority.get("active_inventory_sha256"),
            label="active inventory digest",
        ),
        "analyzer_bundle_sha256": _canonical_digest(accepted_authority.get("analyzer_bundle")),
        "authority_manifest_sha256": _require_sha256(
            summary.get("authority_manifest_sha256"),
            label="authority manifest digest",
        ),
        "category_counts_sha256": _canonical_digest(
            {
                "counts": category_counts,
                "schema": "cdg-original-category-counts-v1",
            }
        ),
        "dependency_manifest_sha256": _require_sha256(
            summary.get("dependency_manifest_sha256"),
            label="dependency manifest digest",
        ),
        "inventory_sha256": _require_sha256(
            summary.get("inventory_sha256"),
            label="inventory digest",
        ),
        "operation_projection_record_digest_set_sha256": _require_sha256(
            projection.get("record_digest_set_sha256"),
            label="operation projection digest",
        ),
        "operation_projection_schema_sha256": _canonical_digest(projection_descriptor),
        "original_record_id_set_sha256": _require_sha256(
            cohort.get("original_record_id_set", {}).get("sha256"),
            label="original record ID-set digest",
        ),
        "public_symbol_sha256": _require_sha256(
            summary.get("public_symbol_sha256"),
            label="public-symbol digest",
        ),
        "route_boundary_sha256": _require_sha256(
            summary.get("route_boundary_sha256"),
            label="route-boundary digest",
        ),
        "sdk_original_record_id_set_sha256": _require_sha256(
            partition.get("sdk_original_record_id_set_sha256"),
            label="SDK original record ID-set digest",
        ),
        "sdk_provenance_record_digest_set_sha256": _require_sha256(
            provenance.get("record_digest_set_sha256"),
            label="SDK provenance digest",
        ),
        "core_original_record_id_set_sha256": _require_sha256(
            partition.get("core_original_record_id_set_sha256"),
            label="core original record ID-set digest",
        ),
        "extended_original_record_id_set_sha256": _require_sha256(
            partition.get("extended_original_record_id_set_sha256"),
            label="extended original record ID-set digest",
        ),
        "source_sha": source_sha,
    }


def _validate_contexts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        _fail("receipt required contexts must be an array")
    contexts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        context = _require_exact_fields(
            item,
            CONTEXT_FIELDS,
            label=f"receipt required context {index}",
        )
        name = _require_string(context.get("name"), label=f"receipt context {index} name")
        if name in seen:
            _fail(f"receipt required context is duplicated: {name}")
        seen.add(name)
        if context.get("conclusion") != "success":
            _fail(f"receipt required context is not successful: {name}")
        for field in ("workflow_run_id", "run_attempt", "job_id", "check_run_id", "app_id"):
            _require_positive_int(
                context.get(field),
                label=f"receipt context {name} {field}",
            )
        contexts.append(context)
    if tuple(context["name"] for context in contexts) != REQUIRED_CONTEXT_NAMES:
        _fail("receipt required contexts are incomplete, reordered, or noncanonical")
    return contexts


def _validate_receipt(
    value: Any,
    *,
    authority_source_sha: str,
    base_sha: str,
    head_sha: str,
    merge_sha: str,
    first_parent_sha: str,
) -> dict[str, Any]:
    receipt = _require_exact_fields(value, RECEIPT_FIELDS, label="historical backfill receipt")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        _fail("historical backfill receipt schema mismatch")
    if receipt.get("workflow_name") != "Contract Drift Governance":
        _fail("historical backfill receipt workflow name mismatch")
    if receipt.get("workflow_path") != WORKFLOW_PATH:
        _fail("historical backfill receipt workflow path mismatch")
    if receipt.get("artifact_name") != f"contract-drift-main-receipt-{merge_sha}":
        _fail("historical backfill receipt artifact name mismatch")
    if receipt.get("conclusion") != "success":
        _fail("historical backfill receipt did not succeed")
    if receipt.get("source_sha") != authority_source_sha:
        _fail("historical backfill receipt source SHA mismatch")
    if receipt.get("merge_sha") != merge_sha:
        _fail("historical backfill receipt merge SHA mismatch")
    if receipt.get("base_sha") != base_sha:
        _fail("historical backfill receipt base SHA mismatch")
    if receipt.get("head_sha") != head_sha:
        _fail("historical backfill receipt head SHA mismatch")
    if receipt.get("first_parent_sha") != first_parent_sha:
        _fail("historical backfill receipt first-parent SHA mismatch")
    for field in ("workflow_run_id", "run_attempt", "job_id", "check_run_id"):
        _require_positive_int(receipt.get(field), label=f"historical receipt {field}")
    _validate_contexts(receipt.get("required_contexts"))
    return receipt


def _validate_projection(value: Any) -> dict[str, Any]:
    projection = _require_exact_fields(value, PROJECTION_FIELDS, label="operation projection")
    records = projection.get("records")
    if not isinstance(records, list) or not records:
        _fail("operation projection records are missing")
    record_ids: set[str] = set()
    edge_count = 0
    multi_edge = 0
    max_edges = 0
    digests: list[str] = []
    for index, item in enumerate(records):
        record = _require_exact_fields(
            item,
            PROJECTION_RECORD_FIELDS,
            label=f"operation projection record {index}",
        )
        original_id = _require_string(
            record.get("original_record_id"),
            label=f"operation projection record {index} original_record_id",
        )
        if original_id in record_ids:
            _fail("operation projection original record ID is duplicated")
        record_ids.add(original_id)
        if not original_id.startswith("cdg1:") or SHA256_RE.fullmatch(original_id[5:]) is None:
            _fail("operation projection original record ID is malformed")
        _require_string(
            record.get("category"), label=f"operation projection record {index} category"
        )
        if record.get("schema") != "cdg-operation-projection-record-v1":
            _fail("operation projection record schema mismatch")
        if record.get("projection_status") not in {"resolved", "unresolved"}:
            _fail("operation projection record status mismatch")
        if not isinstance(record.get("exact_historical_literal_record"), str):
            _fail("operation projection exact historical literal is missing")
        sdk_language = record.get("sdk_language")
        if not isinstance(sdk_language, list) or not all(
            isinstance(language, str) and language for language in sdk_language
        ):
            _fail("operation projection SDK language is malformed")
        edges = record.get("operation_edges")
        if not isinstance(edges, list) or not edges:
            _fail(f"operation projection record {index} has no method-specific edges")
        seen_edges: set[tuple[str, str]] = set()
        for edge_index, raw_edge in enumerate(edges):
            edge = _require_exact_fields(
                raw_edge,
                PROJECTION_EDGE_FIELDS,
                label=f"operation projection edge {index}:{edge_index}",
            )
            method = edge.get("method")
            path = edge.get("normalized_path")
            if method not in VALID_METHODS:
                _fail("operation projection edge method is invalid")
            if not isinstance(path, str) or not path.startswith("/"):
                _fail("operation projection edge path is invalid")
            if edge.get("normalized_operation") != f"{method} {path}":
                _fail("operation projection normalized operation mismatch")
            evidence = edge.get("evidence")
            if (
                not isinstance(evidence, list)
                or not evidence
                or not all(isinstance(item, (str, dict)) for item in evidence)
            ):
                _fail("operation projection edge evidence is missing")
            key = (method, path)
            if key in seen_edges:
                _fail("operation projection edge is duplicated")
            seen_edges.add(key)
        reconstructed = _canonical_digest(
            {key: val for key, val in record.items() if key != "record_sha256"}
        )
        if record.get("record_sha256") != reconstructed:
            _fail(f"operation projection record {index} digest mismatch")
        digests.append(reconstructed)
        size = len(edges)
        edge_count += size
        multi_edge += int(size > 1)
        max_edges = max(max_edges, size)
    digest = ratchet._digest_set(
        "cdg-operation-projection-record-digest-set-v1",
        digests,
        "record_sha256_values",
    )
    if projection.get("record_digest_set_sha256") != digest:
        _fail("operation projection record-digest set mismatch")
    if projection.get("membership_count") != len(records):
        _fail("operation projection membership count mismatch")
    if projection.get("edge_count") != edge_count:
        _fail("operation projection edge count mismatch")
    if projection.get("multi_edge_originals") != multi_edge:
        _fail("operation projection multi-edge count mismatch")
    if projection.get("max_edges") != max_edges:
        _fail("operation projection maximum edge count mismatch")
    return projection


def _validate_attestation(value: Any, *, repository: str, source_sha: str) -> dict[str, Any]:
    attestation = _require_exact_fields(
        value,
        ATTESTATION_FIELDS,
        label="historical backfill attestation",
    )
    if attestation.get("schema") != ATTESTATION_SCHEMA:
        _fail("historical backfill attestation schema mismatch")
    if attestation.get("verified") is not True:
        _fail("historical backfill attestation is absent or unverified")
    if attestation.get("workflow") != "actions/attest@v4":
        _fail("historical backfill attestation workflow mismatch")
    if attestation.get("workflow_path") != ATTESTATION_WORKFLOW_PATH:
        _fail("historical backfill attestation signer workflow mismatch")
    if attestation.get("predicate_type") != ratchet.RELEASE_ATTESTATION_PREDICATE_TYPE:
        _fail("historical backfill attestation predicate mismatch")
    if attestation.get("signer_san_regexp") != ratchet.RELEASE_ATTESTATION_SIGNER_SAN_REGEXP:
        _fail("historical backfill attestation signer mismatch")
    if attestation.get("repository") != repository:
        _fail("historical backfill attestation repository mismatch")
    if attestation.get("source_digest") != source_sha:
        _fail("historical backfill attestation source digest mismatch")
    if attestation.get("subject_asset_names") != list(EXPECTED_ASSET_NAMES):
        _fail("historical backfill attestation subject names are incomplete")
    return attestation


def _validate_rule_suite(
    value: Any,
    *,
    repository: str,
    source_sha: str,
) -> dict[str, Any]:
    record = _require_exact_fields(value, RULE_SUITE_FIELDS, label="historical rule suite")
    if record.get("schema") != RULE_SUITE_SCHEMA:
        _fail("historical rule-suite schema mismatch")
    if record.get("repository_name") != repository:
        _fail("historical rule-suite repository mismatch")
    _require_positive_int(record.get("repository_id"), label="historical rule-suite repository_id")
    _require_positive_int(record.get("id"), label="historical rule-suite id")
    if record.get("ref") != "refs/heads/main":
        _fail("historical rule-suite ref mismatch")
    if record.get("after_sha") != source_sha:
        _fail("historical rule-suite after SHA mismatch")
    if record.get("result") != "pass":
        _fail("historical rule suite did not pass")
    return record


def validate_payload(payload: Any) -> dict[str, Any]:
    document = _require_exact_fields(payload, PAYLOAD_FIELDS, label="historical backfill payload")
    if document.get("schema") != PAYLOAD_SCHEMA:
        _fail("historical backfill payload schema mismatch")
    if document.get("capsule_schema") != CAPSULE_SCHEMA_PATH:
        _fail("historical backfill capsule schema path mismatch")
    if document.get("canonical_serialization") != CANONICAL_SERIALIZATION:
        _fail("historical backfill canonical serialization mismatch")
    repository = _require_string(document.get("repository"), label="historical backfill repository")
    if REPOSITORY_RE.fullmatch(repository) is None:
        _fail("historical backfill repository identity is malformed")

    historical = _require_exact_fields(
        document.get("historical_pull_request"),
        HISTORICAL_PR_FIELDS,
        label="historical pull request",
    )
    _require_positive_int(historical.get("pr"), label="historical pull request number")
    base_sha = _require_sha(historical.get("base_sha"), label="historical base SHA")
    head_sha = _require_sha(historical.get("head_sha"), label="historical head SHA")
    merge_sha = _require_sha(historical.get("merge_sha"), label="historical merge SHA")
    first_parent_sha = _require_sha(
        historical.get("first_parent_sha"),
        label="historical first-parent SHA",
    )
    if (
        historical.get("pr") != 9320
        or base_sha != PR_9320_BASE_SHA
        or head_sha != PR_9320_HEAD_SHA
        or merge_sha != PR_9320_MERGE_SHA
        or first_parent_sha != PR_9320_FIRST_PARENT_SHA
    ):
        _fail("historical pull request does not match the frozen PR #9320 exact pair")
    head_tree_sha = _require_sha(historical.get("head_tree_sha"), label="historical head tree SHA")
    merge_tree_sha = _require_sha(
        historical.get("merge_tree_sha"),
        label="historical merge tree SHA",
    )
    _require_string(historical.get("actor"), label="historical merge actor")
    _require_string(historical.get("merged_at"), label="historical merged_at")
    patch_byte_length = _require_positive_int(
        historical.get("first_parent_patch_byte_length"),
        label="historical first-parent patch byte length",
    )
    patch_sha256 = _require_sha256(
        historical.get("first_parent_patch_sha256"),
        label="historical first-parent patch digest",
    )
    # The --verify-dir chain reaches this validator with no git access, so the
    # derived historical values are bound to the frozen PR #9320 constants here;
    # build_payload independently recomputes the same four values from immutable
    # git before any capsule bytes are written.
    if head_tree_sha != PR_9320_HEAD_TREE_SHA:
        _fail("historical head tree does not match the frozen PR #9320 evidence")
    if merge_tree_sha != PR_9320_MERGE_TREE_SHA:
        _fail("historical merge tree does not match the frozen PR #9320 evidence")
    if patch_byte_length != PR_9320_FIRST_PARENT_PATCH_BYTE_LENGTH:
        _fail(
            "historical first-parent patch byte length does not match the frozen PR #9320 evidence"
        )
    if patch_sha256 != PR_9320_FIRST_PARENT_PATCH_SHA256:
        _fail("historical first-parent patch digest does not match the frozen PR #9320 evidence")
    changed_files = historical.get("changed_files")
    if not isinstance(changed_files, list) or not changed_files:
        _fail("historical changed-file list is missing")
    paths: list[str] = []
    for index, item in enumerate(changed_files):
        record = _require_exact_fields(
            item,
            CHANGED_FILE_FIELDS,
            label=f"historical changed file {index}",
        )
        path = _require_string(record.get("path"), label=f"historical changed file {index} path")
        if path in paths:
            _fail("historical changed-file path is duplicated")
        paths.append(path)
        _require_positive_int(
            record.get("additions"),
            label=f"historical changed file {path} additions",
            allow_zero=True,
        )
        _require_positive_int(
            record.get("deletions"),
            label=f"historical changed file {path} deletions",
            allow_zero=True,
        )
    if paths != sorted(paths):
        _fail("historical changed-file list is not sorted")
    if len({base_sha, head_sha, merge_sha, first_parent_sha}) < 4:
        _fail("historical pull request commit identities collapsed")

    authority = _require_exact_fields(
        document.get("authority"),
        AUTHORITY_FIELDS,
        label="historical authority bindings",
    )
    for field in AUTHORITY_FIELDS:
        if field == "source_sha":
            _require_sha(authority.get(field), label=f"historical authority {field}")
        else:
            _require_sha256(authority.get(field), label=f"historical authority {field}")

    projection = _validate_projection(document.get("projection"))
    if authority.get("operation_projection_record_digest_set_sha256") != projection.get(
        "record_digest_set_sha256"
    ):
        _fail("historical authority and projection digests disagree")

    receipt = _validate_receipt(
        document.get("receipt"),
        authority_source_sha=authority["source_sha"],
        base_sha=base_sha,
        head_sha=head_sha,
        merge_sha=merge_sha,
        first_parent_sha=first_parent_sha,
    )

    disposition = document.get("disposition")
    if disposition != {
        "authoritative_for_future_admission": False,
        "precedential": False,
        "status": "historical_nonconforming",
    }:
        _fail("historical backfill disposition is widened or malformed")

    release = _require_exact_fields(
        document.get("release"),
        RELEASE_FIELDS,
        label="historical successor release",
    )
    if release.get("asset_names") != list(EXPECTED_ASSET_NAMES):
        _fail("historical successor release asset names are incomplete")
    _require_positive_int(release.get("release_api_id"), label="historical release_api_id")
    if release.get("immutable") is not True or release.get("verified") is not True:
        _fail("historical successor release is not verified immutable")
    expected_tag = f"backfill-v2-{merge_sha}"
    if (
        release.get("tag_name") != expected_tag
        or release.get("tag_target_sha") != authority["source_sha"]
        or release.get("exact_full_sha_tag") != merge_sha
    ):
        _fail("historical successor release tag binding mismatch")

    _validate_attestation(
        document.get("attestation"),
        repository=repository,
        source_sha=authority["source_sha"],
    )
    # The repository's rule-suite ledger postdates the historical squash merge, so
    # no passing record for merge_sha can exist; the rule-suite plane binds the
    # implementation push identity, symmetric with the attestation plane.
    _validate_rule_suite(
        document.get("rule_suite"),
        repository=repository,
        source_sha=authority["source_sha"],
    )

    supersedes = _require_exact_fields(
        document.get("supersedes"),
        SUPERSEDES_FIELDS,
        label="historical superseded release",
    )
    _require_positive_int(
        supersedes.get("release_api_id"),
        label="superseded historical release_api_id",
    )
    if supersedes.get("release_api_id") != PR_9320_SUPERSEDED_RELEASE_API_ID:
        _fail("superseded historical release_api_id does not match the frozen old release")
    if supersedes.get("release_api_id") == release.get("release_api_id"):
        _fail("successor release reuses the superseded release API ID")
    if supersedes.get("status") != "superseded_historical_evidence":
        _fail("superseded historical release status mismatch")
    _require_string(supersedes.get("tag_name"), label="superseded historical tag")
    if supersedes.get("tag_name") != PR_9320_SUPERSEDED_RELEASE_TAG:
        _fail("superseded historical tag does not match the frozen old release")
    _require_string(supersedes.get("reason"), label="superseded historical reason")
    return document


def validate_manifest(
    manifest: Any,
    *,
    payload_bytes: bytes,
    payload: dict[str, Any],
) -> dict[str, Any]:
    document = _require_exact_fields(
        manifest,
        MANIFEST_FIELDS,
        label="historical backfill manifest",
    )
    if document.get("schema") != MANIFEST_SCHEMA:
        _fail("historical backfill manifest schema mismatch")
    historical = payload["historical_pull_request"]
    release = payload["release"]
    if (
        document.get("pr") != historical["pr"]
        or document.get("first_parent_sha") != historical["first_parent_sha"]
        or document.get("merge_sha") != historical["merge_sha"]
        or document.get("payload_byte_length") != len(payload_bytes)
        or document.get("payload_sha256") != _sha256(payload_bytes)
        or document.get("release_api_id") != release["release_api_id"]
        or document.get("tag_name") != release["tag_name"]
        or document.get("asset_names") != list(EXPECTED_ASSET_NAMES)
    ):
        _fail("historical backfill manifest binding mismatch")
    return document


def validate_checksums(
    checksums: bytes,
    *,
    manifest_bytes: bytes,
    payload_bytes: bytes,
) -> None:
    expected = (
        f"{_sha256(manifest_bytes)}  manifest.json\n{_sha256(payload_bytes)}  payload.json\n"
    ).encode("ascii")
    if checksums != expected:
        _fail("historical backfill checksum asset is incomplete or noncanonical")


def validate_capsule_bytes(
    *,
    manifest_bytes: bytes,
    payload_bytes: bytes,
    checksums_bytes: bytes,
) -> dict[str, Any]:
    payload = validate_payload(
        _parse_canonical_json(payload_bytes, label="historical backfill payload")
    )
    validate_manifest(
        _parse_canonical_json(manifest_bytes, label="historical backfill manifest"),
        payload_bytes=payload_bytes,
        payload=payload,
    )
    validate_checksums(
        checksums_bytes,
        manifest_bytes=manifest_bytes,
        payload_bytes=payload_bytes,
    )
    return payload


def validate_external_attestation(
    evidence: Any,
    *,
    payload: dict[str, Any],
    assets: dict[str, bytes],
) -> dict[str, Any]:
    record = _require_exact_fields(
        evidence,
        ATTESTATION_EVIDENCE_FIELDS,
        label="historical backfill attestation evidence",
    )
    claim = payload["attestation"]
    if record.get("schema") != "contract-drift-historical-backfill-attestation-evidence-v1":
        _fail("historical backfill attestation evidence schema mismatch")
    for field in (
        "predicate_type",
        "repository",
        "signer_san_regexp",
        "source_digest",
        "verified",
        "workflow",
        "workflow_path",
    ):
        if record.get(field) != claim.get(field):
            _fail(f"historical backfill attestation evidence {field} mismatch")
    if record.get("verified") is not True:
        _fail("historical backfill attestation evidence is unverified")
    subject_sha256s = record.get("subject_sha256s")
    if not isinstance(subject_sha256s, dict) or set(subject_sha256s) != set(EXPECTED_ASSET_NAMES):
        _fail("historical backfill attestation evidence subject set is incomplete")
    observed = {name: _sha256(assets[name]) for name in EXPECTED_ASSET_NAMES}
    if subject_sha256s != observed:
        _fail("historical backfill attestation subjects do not match exact asset bytes")
    return record


def build_external_attestation_evidence(
    *,
    payload: dict[str, Any],
    assets: dict[str, bytes],
) -> dict[str, Any]:
    claim = payload["attestation"]
    evidence = {
        "predicate_type": claim["predicate_type"],
        "repository": claim["repository"],
        "schema": "contract-drift-historical-backfill-attestation-evidence-v1",
        "signer_san_regexp": claim["signer_san_regexp"],
        "source_digest": claim["source_digest"],
        "subject_sha256s": {name: _sha256(assets[name]) for name in EXPECTED_ASSET_NAMES},
        "verified": claim["verified"],
        "workflow": claim["workflow"],
        "workflow_path": claim["workflow_path"],
    }
    return validate_external_attestation(
        evidence,
        payload=payload,
        assets=assets,
    )


def validate_movement_snapshot(value: Any) -> dict[str, Any]:
    snapshot = _require_exact_fields(
        value,
        MOVEMENT_FIELDS,
        label="historical backfill movement snapshot",
    )
    before_sha = _require_sha(
        snapshot.get("main_sha_before"),
        label="historical movement main SHA before",
    )
    after_sha = _require_sha(
        snapshot.get("main_sha_after"),
        label="historical movement main SHA after",
    )
    for field in (
        "newest_workflow_run_id_before",
        "newest_workflow_run_id_after",
        "newest_run_attempt_before",
        "newest_run_attempt_after",
    ):
        _require_positive_int(snapshot.get(field), label=f"historical movement {field}")
    if before_sha != after_sha:
        _fail("historical backfill main moved during verification")
    if (
        snapshot["newest_workflow_run_id_before"],
        snapshot["newest_run_attempt_before"],
    ) != (
        snapshot["newest_workflow_run_id_after"],
        snapshot["newest_run_attempt_after"],
    ):
        _fail("historical backfill newest receipt execution moved during verification")
    return snapshot


def build_payload(
    *,
    repo_root: Path,
    input_document: dict[str, Any],
    authority_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_sha = _resolve_commit(
        repo_root,
        _require_string(
            input_document.get("authority_source_sha"),
            label="authority_source_sha",
        ),
        label="authority source SHA",
    )
    historical = _require_exact_fields(
        input_document.get("historical_pull_request"),
        HISTORICAL_PR_FIELDS,
        label="historical pull request input",
    )
    for field in ("base_sha", "head_sha", "merge_sha", "first_parent_sha"):
        _resolve_commit(repo_root, historical[field], label=f"historical {field}")
    merge_sha = historical["merge_sha"]
    first_parent_sha = historical["first_parent_sha"]
    base_sha = historical["base_sha"]
    head_sha = historical["head_sha"]
    if _git_text(repo_root, "rev-parse", f"{merge_sha}^1") != first_parent_sha:
        _fail("historical merge first parent does not match input")
    for ancestor, descendant, label in (
        (base_sha, head_sha, "historical base is not an ancestor of the PR head"),
        (
            base_sha,
            first_parent_sha,
            "historical base is not an ancestor of the merge first parent",
        ),
        (base_sha, merge_sha, "historical base is not an ancestor of the squash merge"),
    ):
        ancestry = subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", ancestor, descendant],
            capture_output=True,
            env=_git_env(),
        )
        if ancestry.returncode != 0:
            _fail(label)
    if (
        _git_text(repo_root, "rev-parse", f"{historical['head_sha']}^{{tree}}")
        != historical["head_tree_sha"]
    ):
        _fail("historical head tree does not match input")
    if _git_text(repo_root, "rev-parse", f"{merge_sha}^{{tree}}") != historical["merge_tree_sha"]:
        _fail("historical merge tree does not match input")
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
    head_patch = _git_bytes(repo_root, *patch_args, f"{base_sha}^{{tree}}", f"{head_sha}^{{tree}}")
    patch = _git_bytes(
        repo_root,
        *patch_args,
        f"{first_parent_sha}^{{tree}}",
        f"{merge_sha}^{{tree}}",
    )
    if head_patch != patch:
        _fail("historical base/head patch differs from first-parent/merge patch")
    if (
        len(patch) != historical["first_parent_patch_byte_length"]
        or _sha256(patch) != historical["first_parent_patch_sha256"]
    ):
        _fail("historical first-parent patch binding mismatch")
    observed_paths = sorted(
        ratchet._first_parent_semantic_delta(
            repo_root,
            first_parent_sha=first_parent_sha,
            merge_sha=merge_sha,
            pr=historical["pr"],
            operation_log=[],
        )
    )
    head_paths = sorted(
        ratchet._first_parent_semantic_delta(
            repo_root,
            first_parent_sha=base_sha,
            merge_sha=head_sha,
            pr=historical["pr"],
            operation_log=[],
        )
    )
    if head_paths != observed_paths:
        _fail("historical base/head paths differ from first-parent/merge paths")
    if observed_paths != [item["path"] for item in historical["changed_files"]]:
        _fail("historical changed-file set contradicts immutable git")

    inventory = _load_inventory_at_ref(repo_root, source_sha)
    accepted_authority = inventory.get("accepted_authority")
    if not isinstance(accepted_authority, dict):
        _fail("authority source has no accepted authority")
    ratchet.validate_accepted_authority(
        accepted_authority,
        repo_root=repo_root,
        live_ref=source_sha,
        residue_ref=_git_text(repo_root, "rev-parse", f"{source_sha}^1"),
    )
    authority_manifest = authority_manifest or _load_authority_manifest(repo_root, source_sha)
    if authority_manifest.get("ref") != source_sha:
        _fail("authority manifest exact-ref mismatch")
    authority = _authority_summary(
        authority_manifest=authority_manifest,
        accepted_authority=accepted_authority,
        source_sha=source_sha,
    )

    cohort = accepted_authority["canonical_artifacts"]["original_cohort"]
    projection = cohort["operation_projection"]
    projection_records = copy.deepcopy(projection["records"])
    projection_payload = {
        "edge_count": sum(len(record["operation_edges"]) for record in projection_records),
        "max_edges": max(len(record["operation_edges"]) for record in projection_records),
        "membership_count": len(projection_records),
        "multi_edge_originals": sum(
            len(record["operation_edges"]) > 1 for record in projection_records
        ),
        "record_digest_set_sha256": projection["record_digest_set_sha256"],
        "records": projection_records,
    }

    payload = {
        "attestation": copy.deepcopy(input_document.get("attestation")),
        "authority": authority,
        "canonical_serialization": CANONICAL_SERIALIZATION,
        "capsule_schema": CAPSULE_SCHEMA_PATH,
        "disposition": copy.deepcopy(input_document.get("disposition")),
        "historical_pull_request": copy.deepcopy(historical),
        "projection": projection_payload,
        "receipt": copy.deepcopy(input_document.get("receipt")),
        "release": copy.deepcopy(input_document.get("release")),
        "repository": input_document.get("repository"),
        "rule_suite": copy.deepcopy(input_document.get("rule_suite")),
        "schema": PAYLOAD_SCHEMA,
        "supersedes": copy.deepcopy(input_document.get("supersedes")),
    }
    return validate_payload(payload)


def build_capsule_bytes(payload: dict[str, Any]) -> dict[str, bytes]:
    payload_bytes = _canonical_json_bytes(validate_payload(copy.deepcopy(payload)))
    historical = payload["historical_pull_request"]
    release = payload["release"]
    manifest = {
        "asset_names": list(EXPECTED_ASSET_NAMES),
        "first_parent_sha": historical["first_parent_sha"],
        "merge_sha": historical["merge_sha"],
        "payload_byte_length": len(payload_bytes),
        "payload_sha256": _sha256(payload_bytes),
        "pr": historical["pr"],
        "release_api_id": release["release_api_id"],
        "schema": MANIFEST_SCHEMA,
        "tag_name": release["tag_name"],
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    checksums_bytes = (
        f"{_sha256(manifest_bytes)}  manifest.json\n{_sha256(payload_bytes)}  payload.json\n"
    ).encode("ascii")
    validate_capsule_bytes(
        manifest_bytes=manifest_bytes,
        payload_bytes=payload_bytes,
        checksums_bytes=checksums_bytes,
    )
    return {
        "checksums.txt": checksums_bytes,
        "manifest.json": manifest_bytes,
        "payload.json": payload_bytes,
    }


def write_capsule(output_dir: Path, assets: dict[str, bytes]) -> None:
    output_dir.mkdir(parents=True, exist_ok=False)
    for name in EXPECTED_ASSET_NAMES:
        path = output_dir / name
        path.write_bytes(assets[name])


def _verify_directory(path: Path) -> dict[str, Any]:
    entries = sorted(path.iterdir(), key=lambda item: item.name)
    if [item.name for item in entries] != sorted(EXPECTED_ASSET_NAMES) or not all(
        item.is_file() and not item.is_symlink() for item in entries
    ):
        _fail("historical backfill directory must contain the exact three regular files")
    payload = validate_capsule_bytes(
        manifest_bytes=(path / "manifest.json").read_bytes(),
        payload_bytes=(path / "payload.json").read_bytes(),
        checksums_bytes=(path / "checksums.txt").read_bytes(),
    )
    return {
        "asset_sha256s": {
            name: _sha256((path / name).read_bytes()) for name in EXPECTED_ASSET_NAMES
        },
        "merge_sha": payload["historical_pull_request"]["merge_sha"],
        "pr": payload["historical_pull_request"]["pr"],
        "release_api_id": payload["release"]["release_api_id"],
        "status": "pass",
        "tag_name": payload["release"]["tag_name"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--authority-manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--verify-dir", type=Path)
    parser.add_argument("--build-receipt-envelope", action="store_true")
    parser.add_argument("--analyzer-result", type=Path)
    parser.add_argument("--output-receipt", type=Path)
    parser.add_argument("--repository")
    parser.add_argument("--workflow-run-id", type=int)
    parser.add_argument("--run-attempt", type=int)
    parser.add_argument("--job-id", type=int)
    parser.add_argument("--artifact-id", type=int)
    parser.add_argument("--github-api", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        if args.build_receipt_envelope:
            if any(
                value is not None
                for value in (
                    args.input,
                    args.authority_manifest,
                    args.output_dir,
                    args.verify_dir,
                )
            ):
                _fail("--build-receipt-envelope cannot be combined with capsule build inputs")
            required = {
                "--analyzer-result": args.analyzer_result,
                "--output-receipt": args.output_receipt,
                "--repository": args.repository,
                "--run-attempt": args.run_attempt,
                "--job-id": args.job_id,
                "--artifact-id": args.artifact_id,
                "--workflow-run-id": args.workflow_run_id,
            }
            missing = [flag for flag, value in required.items() if value is None]
            if missing:
                _fail("receipt-envelope build requires " + ", ".join(missing))
            if not args.github_api:
                _fail("receipt-envelope build requires authenticated --github-api discovery")
            analyzer_result = _load_json_path(
                args.analyzer_result,
                label="historical receipt analyzer result",
            )
            receipt = build_historical_receipt_envelope(
                analyzer_result=analyzer_result,
                repository=args.repository,
                workflow_run_id=args.workflow_run_id,
                run_attempt=args.run_attempt,
                job_id=args.job_id,
                artifact_id=args.artifact_id,
                reader=GhApiReader(),
            )
            receipt_bytes = _canonical_json_bytes(receipt)
            args.output_receipt.write_bytes(receipt_bytes)
            result = {
                "artifact_name": receipt["artifact_name"],
                "byte_length": len(receipt_bytes),
                "run_attempt": receipt["run_attempt"],
                "sha256": _sha256(receipt_bytes),
                "source_sha": receipt["source_sha"],
                "status": "pass",
                "workflow_run_id": receipt["workflow_run_id"],
            }
        elif args.verify_dir is not None:
            if (
                args.input is not None
                or args.output_dir is not None
                or args.authority_manifest is not None
            ):
                _fail("--verify-dir cannot be combined with build inputs")
            result = _verify_directory(args.verify_dir)
        else:
            if args.input is None or args.output_dir is None:
                _fail("building requires --input and --output-dir")
            input_document = _load_json_path(args.input, label="historical backfill input")
            authority_manifest = (
                _load_json_path(args.authority_manifest, label="authority manifest")
                if args.authority_manifest is not None
                else None
            )
            payload = build_payload(
                repo_root=args.repo_root.resolve(),
                input_document=input_document,
                authority_manifest=authority_manifest,
            )
            assets = build_capsule_bytes(payload)
            write_capsule(args.output_dir, assets)
            result = {
                "asset_sha256s": {name: _sha256(raw) for name, raw in assets.items()},
                "merge_sha": payload["historical_pull_request"]["merge_sha"],
                "pr": payload["historical_pull_request"]["pr"],
                "release_api_id": payload["release"]["release_api_id"],
                "status": "pass",
                "tag_name": payload["release"]["tag_name"],
            }
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        result = {
            "error": str(exc),
            "error_code": "historical_backfill_invalid",
            "status": "fail",
        }
        print(
            json.dumps(result, sort_keys=True, separators=(",", ":"))
            if args.json
            else f"FAIL (closed): {exc}",
            file=sys.stdout if args.json else sys.stderr,
        )
        return 1

    print(
        json.dumps(result, sort_keys=True, separators=(",", ":"))
        if args.json
        else f"Historical backfill capsule: {result['status'].upper()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
