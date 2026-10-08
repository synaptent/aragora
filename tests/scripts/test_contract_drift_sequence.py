"""VAL-CDG-017 historical backfill and route-truth sequence regressions.

The tests deliberately use checked-in records and immutable local Git objects,
not live GitHub API calls. The later ``route_truth`` sealer owns live capsule
re-authentication; this file pins the facts it must rediscover.

Successor-capsule planes are asserted from the checked-in canonical bytes of
immutable release 377250950 under
``tests/fixtures/contract_drift_pr9320_successor_capsule/``. The bytes are
authenticated against the pinned publication digests and re-validated through
the successor builder's fail-closed capsule validation before any plane is
read, so an absent, tampered, unattested, or rule-suite-failing capsule can
never satisfy these tests.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict

import pytest

from scripts import build_contract_drift_historical_backfill as backfill


class AssetBinding(TypedDict):
    byte_length: int
    sha256: str


class PatchBinding(TypedDict):
    byte_length: int
    sha256: str


class CorrectiveCapsuleBinding(TypedDict):
    end_sha: str
    release_id: int
    tag: str


class SequenceEntry(TypedDict):
    fulfills: tuple[str, ...]
    merge_sha: str
    pr: int
    role: str


ROOT = Path(__file__).resolve().parents[2]
BACKFILL_RECORD = ROOT / "docs/audits/2026-08-01-pr9320-historical-first-parent-backfill.md"
AUTHORITY_INVENTORY = ROOT / "scripts/baselines/contract_drift_inventory.json"
SUCCESSOR_CAPSULE_DIR = ROOT / "tests/fixtures/contract_drift_pr9320_successor_capsule"

PR_9320 = 9320
PR_9320_BASE = "14d1ef53e23c5466c0491ed93f72752944c78cd4"
PR_9320_HEAD = "aba6b14c94eca3a9c825b1a303ea67684d5f8daa"
PR_9320_OLD_HEAD = "73cf6d4831c2cb032f31108dada6251f45571748"
PR_9320_MERGE = "0b28f68b9f4d204ae14814169093723ea84c1364"
PR_9320_FIRST_PARENT = "e448b840dad03ee28accd218c14a27fa8b87c7b4"
PR_9320_MERGED_AT = "2026-07-16T20:00:49Z"
PR_9320_ACTOR = "scarmani"
PR_9320_HEAD_TREE = "e5c6c3d07a918cf43fffed6d4a9f472bc10a674a"
PR_9320_MERGE_TREE = "79c1c374eed261c42468dc526d837e726e73425a"

AUTHORITY_SOURCE_SHA = "fe97dc28cd5eb69eb05f1c634f406c021e92358c"
SUCCESSOR_RELEASE_ID = 377250950
SUCCESSOR_TAG = f"backfill-v2-{PR_9320_MERGE}"
SUPERSEDED_RELEASE_ID = 363450207
SUPERSEDED_TAG = f"backfill-{PR_9320_MERGE}"
SUCCESSOR_ASSET_NAMES = ["manifest.json", "payload.json", "checksums.txt"]
SUCCESSOR_ASSETS: dict[str, AssetBinding] = {
    "manifest.json": {
        "byte_length": 457,
        "sha256": "d4fc15a63da2bbc9e3d6380033431d0e829265c692e04de2fbadea9745afb259",
    },
    "payload.json": {
        "byte_length": 1122045,
        "sha256": "0c2f40b475c32ab489da1d91d0e1cc0c0b6cc0cc626d4044aa70cd6b4c237311",
    },
    "checksums.txt": {
        "byte_length": 159,
        "sha256": "9f0990298f6e51d8d6af77d57fdfa25d5605d4f6fcbfc64f96480af753fcdef2",
    },
}
RECEIPT_RUN_ID = 32986224895
RECEIPT_JOB_ID = 98232786669
RULE_SUITE_ID = 3824028173
SUCCESSOR_ACTIVE_INVENTORY_SHA256 = (
    "9be3c35b6701703a6bdce23eaf1840b104fd12376c8b4de128e6af6958ed7de2"
)
ORIGINAL_RECORD_ID_SET_SHA256 = "c1235670c183b1887ba3fe4280fa0320f9fd6f4a85b8f346d4332ac2aebbe269"
PROVENANCE_DIGEST_SET_SHA256 = "0d30ce3b083344f19949da12ae2d92952757af0aea800b3f99d447458b6eeba0"
PROJECTION_DIGEST_SET_SHA256 = "2d6790a6f825c53047639d9433f40e3e10b5bfc9e357bcd161f6b341134775e5"
FIRST_PARENT_PATCH: PatchBinding = {
    "byte_length": 6054,
    "sha256": "7c53f6c8b9bd17847cdb4ecc5dfa1c7aa1699105faabc47439a4437709a175b4",
}
# Byte-exact reproduction of the successor builder's pinned patch invocation;
# any flag drift breaks equality with the payload's first-parent patch digest.
SUCCESSOR_PATCH_ARGS = (
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
SEMANTIC_PATHS = [
    "aragora/server/handlers/social/__init__.py",
    "aragora/server/handlers/social/sharing.py",
    "tests/handlers/social/test_sharing.py",
]
ROUTE_CATEGORIES = frozenset(
    {"routes_missing_in_spec", "routes_orphaned_in_spec", "sdk_missing_from_both"}
)
RUNTIME_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"}
)
HISTORICAL_FACT = {
    "actor": PR_9320_ACTOR,
    "head_sha": PR_9320_HEAD,
    "merge_sha": PR_9320_MERGE,
    "merged_at": PR_9320_MERGED_AT,
    "pr": PR_9320,
}
CORRECTIVE_CAPSULE: CorrectiveCapsuleBinding = {
    "end_sha": "3aa420631c4e906ee4c12bf4fde06282c1f21489",
    "release_id": 364632369,
    "tag": "cdg-corrective_bootstrap-3aa420631c4e906ee4c12bf4fde06282c1f21489",
}
CONSTANTS_MERGE = "ee686e9d116c704ede146a6ec69dfe013b6c32be"
MATCHER_MERGE = "e8a0d165242737d3226b6d3360aa9e8ec014fd75"
STAGE1_MERGE = "9482fc2dffdb6425d2405389c13f46d5954ac467"
STAGE2_MERGE = "d20d22335e3459050f5c0e433120db309f503d13"
CORRECTIVE_MERGE = "d3e45fafe6dd04508882935c813f6896abc859d7"
BACKFILL_RECORDING_MERGE = "486b24fbb131d27b90853c1d64dd949834427e1f"
BACKFILL_CAPSULE_BINDING_MERGE = "4b36750a2ea3433e42a06927c79056b3bd5a9e3d"
ROUTE_CORE_MERGE = "9148ba293404e8d46c4c588d4169d32fb11e29b0"
OPENAPI_REARM_MERGE = "56af53b778f6d8ec80f81edc4f8ed6651d4410b7"
SEQUENCE: list[SequenceEntry] = [
    {
        "fulfills": (),
        "merge_sha": CONSTANTS_MERGE,
        "pr": 9406,
        "role": "constants",
    },
    {
        "fulfills": (),
        "merge_sha": MATCHER_MERGE,
        "pr": 9413,
        "role": "matcher",
    },
    {
        "fulfills": (),
        "merge_sha": STAGE1_MERGE,
        "pr": 9429,
        "role": "stage1",
    },
    {
        "fulfills": ("VAL-CDG-001",),
        "merge_sha": STAGE2_MERGE,
        "pr": 9449,
        "role": "stage2",
    },
    {
        "fulfills": (),
        "merge_sha": CORRECTIVE_MERGE,
        "pr": 9645,
        "role": "corrective",
    },
    {
        "fulfills": (),
        "merge_sha": BACKFILL_CAPSULE_BINDING_MERGE,
        "pr": 9692,
        "role": "backfill",
    },
    {
        "fulfills": ("VAL-CDG-011",),
        "merge_sha": ROUTE_CORE_MERGE,
        "pr": 9717,
        "role": "route_core",
    },
    {
        "fulfills": ("VAL-CDG-012",),
        "merge_sha": OPENAPI_REARM_MERGE,
        "pr": 9719,
        "role": "openapi_rearm",
    },
]


@lru_cache
def _record_text() -> str:
    return BACKFILL_RECORD.read_text(encoding="utf-8")


@lru_cache
def _authority() -> dict:
    inventory = json.loads(AUTHORITY_INVENTORY.read_text(encoding="utf-8"))
    return inventory["accepted_authority"]


@lru_cache
def _capsule_bytes() -> dict[str, bytes]:
    """Checked-in successor capsule bytes, authenticated against the pins."""
    contents: dict[str, bytes] = {}
    for name, binding in SUCCESSOR_ASSETS.items():
        raw = (SUCCESSOR_CAPSULE_DIR / name).read_bytes()
        assert len(raw) == binding["byte_length"]
        assert _sha256(raw) == binding["sha256"]
        contents[name] = raw
    return contents


@lru_cache
def _capsule_payload() -> dict[str, Any]:
    """Successor payload parsed via the builder's fail-closed capsule validation."""
    raw = _capsule_bytes()
    return backfill.validate_capsule_bytes(
        manifest_bytes=raw["manifest.json"],
        payload_bytes=raw["payload.json"],
        checksums_bytes=raw["checksums.txt"],
    )


def _canonical_json_bytes(value: object, *, terminal_lf: bool) -> bytes:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return raw + (b"\n" if terminal_lf else b"")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", "-c", "core.pager=cat", *args],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout


def _hermetic_git_bytes(*args: str) -> bytes:
    # Mirrors the successor builder's hermetic git environment so recomputed
    # patch bytes are comparable with the payload's pinned digest.
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "LC_ALL": "C",
    }
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True,
        check=True,
        env=env,
    ).stdout


def _git_text(*args: str) -> str:
    return _git_bytes(*args).decode().strip()


def _all_commits_present(*shas: str) -> bool:
    return all(
        subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
        for sha in shas
    )


def _first_parent_positions(*shas: str) -> dict[str, int] | None:
    """First-parent chain positions, or None when any pin sits off the chain.

    Backported or cherry-picked pins can exist as objects without being
    first-parent ancestors of HEAD; returning None instead of raising keeps
    chronology checks from producing ``list.index`` ValueErrors on such clones.
    """
    if not _all_commits_present(*shas):
        return None
    first_parent = _git_text("rev-list", "--first-parent", "--reverse", "HEAD").splitlines()
    lookup = {sha: position for position, sha in enumerate(first_parent)}
    if any(sha not in lookup for sha in shas):
        return None
    return {sha: lookup[sha] for sha in shas}


def _assert_recorded(*needles: str) -> None:
    text = _record_text()
    for needle in needles:
        assert needle in text


def test_pr_9320_is_exact_historical_nonconforming_head_and_merge() -> None:
    historical = _authority()["transition"]["historical_nonconforming"]
    matches = [fact for fact in historical if fact["pr"] == PR_9320]
    assert matches == [HISTORICAL_FACT]

    payload = _capsule_payload()
    pull_request = payload["historical_pull_request"]
    assert pull_request["pr"] == PR_9320
    assert pull_request["base_sha"] == PR_9320_BASE
    assert pull_request["head_sha"] == PR_9320_HEAD
    assert pull_request["merge_sha"] == PR_9320_MERGE
    assert pull_request["first_parent_sha"] == PR_9320_FIRST_PARENT
    assert pull_request["merged_at"] == PR_9320_MERGED_AT
    assert pull_request["actor"] == PR_9320_ACTOR
    assert pull_request["head_tree_sha"] == PR_9320_HEAD_TREE
    assert pull_request["merge_tree_sha"] == PR_9320_MERGE_TREE
    assert payload["disposition"]["status"] == "historical_nonconforming"

    # Full clones recompute from immutable Git objects. Shallow CI clones retain
    # the always-on capsule-byte and checked-in authority assertions above.
    if _all_commits_present(PR_9320_MERGE, PR_9320_HEAD):
        merge_fields = _git_text(
            "show",
            "-s",
            "--format=%H|%P|%T|%s",
            PR_9320_MERGE,
        ).split("|")
        assert merge_fields == [
            PR_9320_MERGE,
            PR_9320_FIRST_PARENT,
            PR_9320_MERGE_TREE,
            "fix(sharing): warn on legacy share model access (#9320)",
        ]
        assert _git_text("show", "-s", "--format=%T", PR_9320_HEAD) == PR_9320_HEAD_TREE


def test_pr_9320_requires_first_parent_historical_backfill_not_future_admission() -> None:
    payload = _capsule_payload()
    assert payload["schema"] == "contract-drift-historical-backfill-successor-v2"
    assert payload["historical_pull_request"]["first_parent_sha"] == PR_9320_FIRST_PARENT
    assert payload["release"]["exact_full_sha_tag"] == PR_9320_MERGE
    assert payload["release"]["tag_name"] == SUCCESSOR_TAG
    assert payload["supersedes"]["tag_name"] == SUPERSEDED_TAG
    assert payload["disposition"]["authoritative_for_future_admission"] is False
    if _all_commits_present(PR_9320_MERGE, PR_9320_FIRST_PARENT):
        assert _git_text("show", "-s", "--format=%P", PR_9320_MERGE) == PR_9320_FIRST_PARENT
    _assert_recorded(
        "required historical first-parent receipt/backfill",
        "pre-merge admission evidence (`contract-drift-pr-delta` never ran for this PR)",
        "forward immutable-boundary, chronology, settlement, or capsule proof",
        "historical_backfill",
        "future admission",
    )


def test_pr_9320_historical_record_cannot_supply_authority_chronology_no_admin_or_forward_capsule_proof() -> (
    None
):
    assert set(HISTORICAL_FACT) == {"actor", "head_sha", "merge_sha", "merged_at", "pr"}
    forbidden_authority = {
        "accepted_authority",
        "admission",
        "admin",
        "authority",
        "boundary",
        "capsule",
        "chronology",
        "post_settlement_quorum",
        "settlement",
    }
    assert not (set(HISTORICAL_FACT) & forbidden_authority)
    assert _capsule_payload()["disposition"] == {
        "authoritative_for_future_admission": False,
        "precedential": False,
        "status": "historical_nonconforming",
    }
    _assert_recorded(
        "accepted authority or an authority transition",
        "forward proof of no-admin merge behavior",
        "forward immutable-boundary, chronology, settlement, or capsule proof",
    )


def test_pr_9320_old_delegations_are_consumed_or_void() -> None:
    _assert_recorded(
        PR_9320_OLD_HEAD,
        "every delegation bound to it remain",
        "consumed or void",
    )
    assert PR_9320_OLD_HEAD != PR_9320_HEAD
    assert _capsule_payload()["historical_pull_request"]["head_sha"] == PR_9320_HEAD
    if _all_commits_present(PR_9320_HEAD, PR_9320_OLD_HEAD):
        assert PR_9320_OLD_HEAD in _git_text("show", "-s", "--format=%P", PR_9320_HEAD).split()


def test_pr_9320_backfill_payload_binds_canonical_artifacts_cohort_provenance_and_projection_edges() -> (
    None
):
    payload = _capsule_payload()
    authority_plane = payload["authority"]
    assert authority_plane["source_sha"] == AUTHORITY_SOURCE_SHA
    assert authority_plane["original_record_id_set_sha256"] == ORIGINAL_RECORD_ID_SET_SHA256
    assert authority_plane["sdk_provenance_record_digest_set_sha256"] == (
        PROVENANCE_DIGEST_SET_SHA256
    )
    assert authority_plane["operation_projection_record_digest_set_sha256"] == (
        PROJECTION_DIGEST_SET_SHA256
    )

    projection = payload["projection"]
    assert projection["membership_count"] == 655
    assert projection["edge_count"] == 666
    assert projection["multi_edge_originals"] == 9
    assert projection["max_edges"] == 4
    assert projection["record_digest_set_sha256"] == PROJECTION_DIGEST_SET_SHA256
    records = projection["records"]
    assert len(records) == 655
    assert sum(len(record["operation_edges"]) for record in records) == 666
    for record in records:
        assert record["operation_edges"]
        for edge in record["operation_edges"]:
            assert edge["method"] in RUNTIME_METHODS
            assert edge["normalized_path"]
            assert edge["normalized_operation"]
    route_edge_counts = sorted(
        len(record["operation_edges"])
        for record in records
        if record["category"] in ROUTE_CATEGORIES
    )
    assert route_edge_counts == [1] * 48 + [2] * 8 + [4]

    authority = _authority()
    bindings = {entry["path"]: entry for entry in authority["canonical_artifact_bindings"]}
    artifacts = authority["canonical_artifacts"]
    for key, path in (
        ("original_cohort", "library/contract-drift-original-cohort-v1.json"),
        ("sdk_provenance", "library/contract-drift-sdk-provenance-v1.json"),
    ):
        raw = _canonical_json_bytes(artifacts[key], terminal_lf=True)
        assert len(raw) == bindings[path]["byte_length"]
        assert _sha256(raw) == bindings[path]["sha256"]

    cohort = artifacts["original_cohort"]
    assert cohort["counts"]["records"] == 655
    assert cohort["counts"]["method_bearing_sdk_records"] == 598
    assert cohort["counts"]["method_null_route_parity_records"] == 57
    assert cohort["original_record_id_set"]["sha256"] == ORIGINAL_RECORD_ID_SET_SHA256
    route_ids_from_cohort = {
        record["original_record_id"]
        for record in cohort["original_records"]
        if record["method"] is None
    }
    route_ids_from_payload = {
        record["original_record_id"] for record in records if record["category"] in ROUTE_CATEGORIES
    }
    assert route_ids_from_payload == route_ids_from_cohort
    provenance = artifacts["sdk_provenance"]
    assert provenance["counts"]["records"] == 598
    assert provenance["partition"]["intersection_count"] == 0
    assert provenance["partition"]["union_count"] == 598


def test_pr_9320_backfill_payload_binds_semantic_run_attempt_job_and_check_digests() -> None:
    payload = _capsule_payload()
    receipt = payload["receipt"]
    assert receipt["schema"] == "contract-drift-historical-backfill-receipt-v1"
    assert receipt["workflow_run_id"] == RECEIPT_RUN_ID
    assert receipt["run_attempt"] == 1
    assert receipt["job_id"] == RECEIPT_JOB_ID
    assert receipt["check_run_id"] == RECEIPT_JOB_ID
    assert receipt["conclusion"] == "success"
    assert receipt["workflow_path"] == ".github/workflows/contract-drift-governance.yml"
    assert receipt["source_sha"] == AUTHORITY_SOURCE_SHA
    assert receipt["artifact_name"] == f"contract-drift-main-receipt-{PR_9320_MERGE}"
    assert receipt["base_sha"] == PR_9320_BASE
    assert receipt["head_sha"] == PR_9320_HEAD
    assert receipt["merge_sha"] == PR_9320_MERGE
    assert receipt["first_parent_sha"] == PR_9320_FIRST_PARENT
    contexts = [
        (
            context["name"],
            context["workflow_run_id"],
            context["run_attempt"],
            context["job_id"],
            context["check_run_id"],
            context["conclusion"],
            context["app_id"],
        )
        for context in receipt["required_contexts"]
    ]
    assert contexts == [
        ("lint", 29524359563, 1, 87709243174, 87709243174, "success", 15368),
        ("typecheck", 29524359563, 1, 87709180560, 87709180560, "success", 15368),
        ("sdk-parity", 29524359665, 1, 87709276751, 87709276751, "success", 15368),
        ("Generate & Validate", 29524359572, 1, 87709726971, 87709726971, "success", 15368),
        (
            "TypeScript SDK Type Check",
            29524359727,
            1,
            87709013895,
            87709013895,
            "success",
            15368,
        ),
        ("aragora-merge-quorum", 29524359568, 3, 87728267780, 87728267780, "success", 15368),
    ]
    pull_request = payload["historical_pull_request"]
    assert pull_request["first_parent_patch_byte_length"] == FIRST_PARENT_PATCH["byte_length"]
    assert pull_request["first_parent_patch_sha256"] == FIRST_PARENT_PATCH["sha256"]
    assert payload["authority"]["active_inventory_sha256"] == SUCCESSOR_ACTIVE_INVENTORY_SHA256

    active_inventory = _authority()["active_inventory"]
    assert (
        _sha256(_canonical_json_bytes(active_inventory, terminal_lf=False))
        == (_authority()["active_inventory_sha256"])
    )


def test_pr_9320_backfill_release_capsule_binds_manifest_payload_checksums_attestation_and_rule_suite() -> (
    None
):
    raw = _capsule_bytes()
    payload = _capsule_payload()

    manifest = json.loads(raw["manifest.json"])
    assert manifest == {
        "asset_names": SUCCESSOR_ASSET_NAMES,
        "first_parent_sha": PR_9320_FIRST_PARENT,
        "merge_sha": PR_9320_MERGE,
        "payload_byte_length": len(raw["payload.json"]),
        "payload_sha256": _sha256(raw["payload.json"]),
        "pr": PR_9320,
        "release_api_id": SUCCESSOR_RELEASE_ID,
        "schema": "contract-drift-historical-backfill-manifest-v2",
        "tag_name": SUCCESSOR_TAG,
    }
    expected_checksums = (
        f"{_sha256(raw['manifest.json'])}  manifest.json\n"
        f"{_sha256(raw['payload.json'])}  payload.json\n"
    ).encode()
    assert raw["checksums.txt"] == expected_checksums

    assert payload["attestation"] == {
        "predicate_type": "https://in-toto.io/attestation/release/v0.2",
        "repository": "synaptent/aragora",
        "schema": "contract-drift-historical-backfill-attestation-v1",
        "signer_san_regexp": "^https://dotcom\\.releases\\.github\\.com$",
        "source_digest": AUTHORITY_SOURCE_SHA,
        "subject_asset_names": SUCCESSOR_ASSET_NAMES,
        "verified": True,
        "workflow": "actions/attest@v4",
        "workflow_path": ".github/workflows/contract-drift-boundary.yml",
    }
    assert payload["rule_suite"] == {
        "after_sha": AUTHORITY_SOURCE_SHA,
        "id": RULE_SUITE_ID,
        "ref": "refs/heads/main",
        "repository_id": 1126097105,
        "repository_name": "synaptent/aragora",
        "result": "pass",
        "schema": "contract-drift-historical-backfill-rule-suite-v1",
    }
    assert payload["release"] == {
        "asset_names": SUCCESSOR_ASSET_NAMES,
        "exact_full_sha_tag": PR_9320_MERGE,
        "immutable": True,
        "release_api_id": SUCCESSOR_RELEASE_ID,
        "tag_name": SUCCESSOR_TAG,
        "tag_target_sha": AUTHORITY_SOURCE_SHA,
        "verified": True,
    }

    # A capsule without successful attestation or a passing rule suite must
    # fail closed; it can never read as passing.
    unverified = copy.deepcopy(payload)
    unverified["attestation"]["verified"] = False
    with pytest.raises(ValueError, match="attestation is absent or unverified"):
        backfill.validate_payload(unverified)
    absent = copy.deepcopy(payload)
    del absent["attestation"]
    with pytest.raises(ValueError, match="fields are incomplete"):
        backfill.validate_payload(absent)
    failed_suite = copy.deepcopy(payload)
    failed_suite["rule_suite"]["result"] = "fail"
    with pytest.raises(ValueError, match="rule suite did not pass"):
        backfill.validate_payload(failed_suite)


def test_pr_9320_backfill_is_durable_after_actions_artifact_expiration() -> None:
    raw = _capsule_bytes()
    payload = _capsule_payload()
    release = payload["release"]
    assert list(raw) == SUCCESSOR_ASSET_NAMES
    assert release["asset_names"] == SUCCESSOR_ASSET_NAMES
    for name, binding in SUCCESSOR_ASSETS.items():
        assert len(raw[name]) == binding["byte_length"]
        assert _sha256(raw[name]) == binding["sha256"]
    assert release["immutable"] is True
    assert release["verified"] is True
    assert release["release_api_id"] == SUCCESSOR_RELEASE_ID
    assert release["release_api_id"] > 0
    assert release["tag_target_sha"] == AUTHORITY_SOURCE_SHA
    supersedes = payload["supersedes"]
    assert supersedes["release_api_id"] == SUPERSEDED_RELEASE_ID
    assert supersedes["status"] == "superseded_historical_evidence"
    assert supersedes["tag_name"] == SUPERSEDED_TAG
    manifest = json.loads(raw["manifest.json"])
    assert not any("artifact" in key for key in manifest)
    assert payload["receipt"]["artifact_name"].startswith("contract-drift-main-receipt-")


def test_pr_9320_backfill_recomputes_first_parent_to_squash_semantics() -> None:
    pull_request = _capsule_payload()["historical_pull_request"]
    assert pull_request["head_tree_sha"] == PR_9320_HEAD_TREE
    assert pull_request["merge_tree_sha"] == PR_9320_MERGE_TREE
    assert pull_request["head_tree_sha"] != pull_request["merge_tree_sha"]
    assert pull_request["first_parent_patch_byte_length"] == FIRST_PARENT_PATCH["byte_length"]
    assert pull_request["first_parent_patch_sha256"] == FIRST_PARENT_PATCH["sha256"]
    changed_paths = [entry["path"] for entry in pull_request["changed_files"]]
    assert changed_paths == SEMANTIC_PATHS
    assert not any(
        path.startswith(("scripts/baselines/", "scripts/check_contract_drift"))
        for path in changed_paths
    )
    if _all_commits_present(PR_9320_MERGE, PR_9320_FIRST_PARENT):
        assert _git_text("show", "-s", "--format=%P", PR_9320_MERGE) == PR_9320_FIRST_PARENT
        patch = _hermetic_git_bytes(
            *SUCCESSOR_PATCH_ARGS,
            f"{PR_9320_FIRST_PARENT}^{{tree}}",
            f"{PR_9320_MERGE}^{{tree}}",
        )
        assert len(patch) == FIRST_PARENT_PATCH["byte_length"]
        assert _sha256(patch) == FIRST_PARENT_PATCH["sha256"]
        recomputed_paths = (
            _hermetic_git_bytes(
                "diff",
                "--name-only",
                "--no-renames",
                f"{PR_9320_FIRST_PARENT}^{{tree}}",
                f"{PR_9320_MERGE}^{{tree}}",
            )
            .decode()
            .splitlines()
        )
        assert recomputed_paths == changed_paths


def test_pr_9320_cannot_be_reopened_resettled_or_remerged() -> None:
    matching_facts = [
        fact
        for fact in _authority()["transition"]["historical_nonconforming"]
        if fact["pr"] == PR_9320
    ]
    assert matching_facts == [HISTORICAL_FACT]
    disposition = _capsule_payload()["disposition"]
    assert disposition["precedential"] is False
    assert disposition["authoritative_for_future_admission"] is False
    _assert_recorded(
        "must never be reopened, resettled, remerged, edited",
        "cannot supply",
        "sole accepted disposition remains `historical_nonconforming`",
    )
    assert "state" not in HISTORICAL_FACT
    assert "settlement_id" not in HISTORICAL_FACT


def test_constants_matcher_stage1_stage2_corrective_backfill_route_openapi_order_is_exact() -> None:
    assert [entry["role"] for entry in SEQUENCE] == [
        "constants",
        "matcher",
        "stage1",
        "stage2",
        "corrective",
        "backfill",
        "route_core",
        "openapi_rearm",
    ]
    payload = _capsule_payload()
    assert payload["release"]["release_api_id"] == SUCCESSOR_RELEASE_ID
    assert payload["supersedes"]["release_api_id"] == SUPERSEDED_RELEASE_ID
    assert SUCCESSOR_RELEASE_ID != SUPERSEDED_RELEASE_ID
    assert CORRECTIVE_CAPSULE["release_id"] not in {SUCCESSOR_RELEASE_ID, SUPERSEDED_RELEASE_ID}
    assert payload["release"]["tag_name"].endswith(PR_9320_MERGE)
    assert CORRECTIVE_CAPSULE["tag"].endswith(CORRECTIVE_CAPSULE["end_sha"])

    chronological_shas = [entry["merge_sha"] for entry in SEQUENCE]
    positions = _first_parent_positions(
        *chronological_shas,
        BACKFILL_RECORDING_MERGE,
        CORRECTIVE_CAPSULE["end_sha"],
        AUTHORITY_SOURCE_SHA,
    )
    if positions is not None:
        ordered_positions = [positions[sha] for sha in chronological_shas]
        assert ordered_positions == sorted(ordered_positions)
        assert len(set(ordered_positions)) == len(SEQUENCE)

        assert positions[CORRECTIVE_MERGE] < positions[BACKFILL_RECORDING_MERGE]
        assert positions[BACKFILL_RECORDING_MERGE] < positions[BACKFILL_CAPSULE_BINDING_MERGE]
        assert positions[BACKFILL_CAPSULE_BINDING_MERGE] < positions[ROUTE_CORE_MERGE]
        assert positions[ROUTE_CORE_MERGE] < positions[OPENAPI_REARM_MERGE]

        assert positions[CORRECTIVE_MERGE] < positions[CORRECTIVE_CAPSULE["end_sha"]]
        assert positions[CORRECTIVE_CAPSULE["end_sha"]] < positions[ROUTE_CORE_MERGE]
        assert positions[OPENAPI_REARM_MERGE] < positions[AUTHORITY_SOURCE_SHA]


def test_stage1_has_no_fulfills_and_stage2_is_sole_val_cdg_001_owner() -> None:
    by_role = {entry["role"]: entry for entry in SEQUENCE}
    assert by_role["stage1"]["fulfills"] == ()
    assert by_role["stage2"]["fulfills"] == ("VAL-CDG-001",)
    assert [entry["role"] for entry in SEQUENCE if "VAL-CDG-001" in entry["fulfills"]] == ["stage2"]

    if _all_commits_present(STAGE1_MERGE, STAGE2_MERGE):
        stage1_paths = set(
            _git_text("diff-tree", "--no-commit-id", "--name-only", "-r", STAGE1_MERGE).splitlines()
        )
        stage2_paths = set(
            _git_text("diff-tree", "--no-commit-id", "--name-only", "-r", STAGE2_MERGE).splitlines()
        )
        assert "scripts/generate_contract_drift_inventory.py" in stage1_paths
        assert "scripts/check_contract_drift_ratchet.py" not in stage1_paths
        assert stage2_paths == {
            "scripts/check_contract_drift_ratchet.py",
            "tests/scripts/test_check_contract_drift_ratchet.py",
        }
        assert _git_text("show", "-s", "--format=%s", STAGE1_MERGE).endswith("(#9429)")
        assert _git_text("show", "-s", "--format=%s", STAGE2_MERGE).endswith("(#9449)")


def test_route_core_and_openapi_rearm_are_separate_prs() -> None:
    by_role = {entry["role"]: entry for entry in SEQUENCE}
    route = by_role["route_core"]
    rearm = by_role["openapi_rearm"]
    assert route["pr"] == 9717
    assert rearm["pr"] == 9719
    assert route["pr"] != rearm["pr"]
    assert route["merge_sha"] != rearm["merge_sha"]
    if _all_commits_present(route["merge_sha"], rearm["merge_sha"]):
        assert set(
            _git_text(
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                route["merge_sha"],
            ).splitlines()
        ) == {
            "scripts/validate_openapi_routes.py",
            "tests/scripts/test_validate_openapi_routes.py",
        }
        assert set(
            _git_text(
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                rearm["merge_sha"],
            ).splitlines()
        ) == {
            ".github/workflows/openapi.yml",
            "tests/scripts/test_openapi_workflow_contract.py",
        }


def test_route_core_merges_before_openapi_rearm() -> None:
    roles = [entry["role"] for entry in SEQUENCE]
    assert roles.index("route_core") < roles.index("openapi_rearm")
    if _all_commits_present(ROUTE_CORE_MERGE, OPENAPI_REARM_MERGE):
        ancestry = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ROUTE_CORE_MERGE, OPENAPI_REARM_MERGE],
            cwd=ROOT,
            check=False,
        )
        assert ancestry.returncode == 0
        assert _git_text("show", "-s", "--format=%s", ROUTE_CORE_MERGE).endswith("(#9717)")
        assert _git_text("show", "-s", "--format=%s", OPENAPI_REARM_MERGE).endswith("(#9719)")
    positions = _first_parent_positions(ROUTE_CORE_MERGE, OPENAPI_REARM_MERGE)
    if positions is not None:
        assert positions[ROUTE_CORE_MERGE] < positions[OPENAPI_REARM_MERGE]


def test_openapi_rearm_requires_method_aware_route_core() -> None:
    workflow = (ROOT / ".github/workflows/openapi.yml").read_text(encoding="utf-8")
    assert "Method-aware operation plane (VAL-CDG-011/012)" in workflow
    assert 'EXEC_SHA="$(git rev-parse HEAD)"' in workflow
    assert "scripts/validate_openapi_routes.py \\" in workflow
    assert '--ref "${EXEC_SHA}"' in workflow
    assert 'if plane.get("ref") != sys.argv[1]:' in workflow
    assert "method-aware plane ref" in workflow

    route_core_source = (ROOT / "scripts/validate_openapi_routes.py").read_text(encoding="utf-8")
    assert '"--ref"' in route_core_source
    assert '"served_operations"' in route_core_source
    assert '"operation_projection"' in route_core_source
    if _all_commits_present(ROUTE_CORE_MERGE, OPENAPI_REARM_MERGE):
        assert (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", ROUTE_CORE_MERGE, OPENAPI_REARM_MERGE],
                cwd=ROOT,
                check=False,
            ).returncode
            == 0
        )
