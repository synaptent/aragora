#!/usr/bin/env python3
"""Phase 3 of cleanup plan: reconcile automation outbox handoffs against
existing receipts and merged PR state.

Many .aragora/automation-outbox/*.json files are stale: their PR has merged,
or a terminal receipt was written, but the outbox file was never archived.
Each stale entry blocks the corresponding branch from being categorised as
cleanup-eligible by the audit script (because unresolved_outbox_handoff_branches
returns it as protected).

This script:
  1. Reads every outbox file
  2. For each, checks: matching receipt exists? superseded handoff? matching PR merged?
  3. Archives satisfied outbox files to .aragora/automation-outbox-archive/
     and writes a synthetic receipt if needed (so future audits stay correct)
  4. Reports counts before/after

Read-only by default (--dry-run); pass --apply to actually move files.
Dry-run reports are printed to stdout; pass --write-report or --out to persist
a JSON report.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from audit_codex_branch_backlog import (  # noqa: E402
    open_pr_heads,
    run_git,
)
from github_cli_health import check_github_cli_health  # noqa: E402
from identify_lane_owner import build_worktree_reference_preservation_proof  # noqa: E402

UTC = timezone.utc
DEFAULT_OUTBOX_DIR = Path(".aragora/automation-outbox")
DEFAULT_RECEIPT_DIR = Path(".aragora/automation-receipts")
DEFAULT_ARCHIVE_DIR = Path(".aragora/automation-outbox-archive")

# Bounded terminal-archive policy for the existing_issue deadlock:
# the publisher refuses to open a duplicate PR because a GitHub issue already
# tracks the task (receipt reason "existing_issue"), while the reconciler
# refuses to archive PR-intent handoffs satisfied only by an issue receipt.
# Neither side ever clears the handoff. The escape valve below archives such
# handoffs with an explicit terminal receipt, but only when ALL gates hold:
# verified issue state, minimum item age, and a per-pass archive cap.
DEFAULT_EXISTING_ISSUE_MIN_AGE_DAYS = 3.0
DEFAULT_EXISTING_ISSUE_ARCHIVE_CAP = 20
TERMINAL_DISPOSITION_EXISTING_ISSUE = "superseded_by_existing_issue"
SHA_RE = re.compile(r"[0-9a-fA-F]{40}")
LOCAL_WORK_MARKER_KEYS = (
    "uncommitted_changes",
    "has_uncommitted_changes",
    "uncommitted",
    "unpushed_commits",
    "local_changes",
    "local_work",
    "dirty",
)


def _mute_stdout_after_broken_pipe() -> None:
    close = getattr(sys.stdout, "close", None)
    if callable(close):
        try:
            close()
        except OSError:
            pass
    sys.stdout = open(os.devnull, "w", encoding="utf-8")


def _emit_output(output: str) -> None:
    try:
        sys.stdout.write(output)
        sys.stdout.write("\n")
        sys.stdout.flush()
    except BrokenPipeError:
        _mute_stdout_after_broken_pipe()


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _list_json(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(p for p in path.iterdir() if p.is_file() and p.suffix == ".json")


def _resolve_outbox_file_filter(outbox_dir: Path, value: Path) -> Path:
    expanded = value.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (outbox_dir / expanded).resolve()


def _state_default_path(state_root: Path, default_relative: Path) -> Path:
    expanded = state_root.expanduser()
    if default_relative.parts[:1] == (".aragora",) and expanded.name == ".aragora":
        return expanded.joinpath(*default_relative.parts[1:])
    return expanded / default_relative


def _resolve_path(repo_root: Path, value: Path | None, default: Path) -> Path:
    if value is None:
        return default.resolve()
    expanded = value.expanduser()
    if expanded.is_absolute():
        return expanded.resolve()
    return (repo_root / expanded).resolve()


def _normalize_base_ref(value: str) -> str:
    text = str(value or "").strip()
    for prefix in ("refs/remotes/origin/", "refs/heads/", "origin/"):
        if text.startswith(prefix):
            return text.removeprefix(prefix)
    return text


def _ref_has_landed_on_main(root: Path, base: str, ref: str) -> bool:
    """Return True if ref or a patch-equivalent commit is on the selected base."""
    proc = run_git(["rev-parse", "--verify", ref], root, timeout=15)
    if proc.returncode != 0:
        return False
    proc = run_git(["merge-base", "--is-ancestor", ref, base], root, timeout=15)
    if proc.returncode == 0:
        return True
    proc = run_git(["cherry", base, ref], root, timeout=120)
    if proc.returncode != 0:
        return False
    statuses = [line.split(" ", 1)[0] for line in proc.stdout.splitlines() if line.strip()]
    return bool(statuses) and all(status == "-" for status in statuses)


def _branch_has_landed_on_main(root: Path, base: str, branch: str) -> bool:
    """Return True if the branch's HEAD or a patch-equivalent commit is on main."""
    return _ref_has_landed_on_main(root, base, branch)


def _terminal_receipt_keys(receipt_dir: Path) -> set[str]:
    """Return idempotency keys whose receipts are in a terminal state."""
    return set(_terminal_receipts_by_key(receipt_dir))


def _terminal_receipts_by_key(receipt_dir: Path) -> dict[str, dict[str, Any]]:
    """Return terminal receipts keyed by idempotency key."""
    receipts: dict[str, dict[str, Any]] = {}
    for path in _list_json(receipt_dir):
        payload = _load_json(path)
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "").strip().lower()
        if status in ("published", "already_satisfied", "completed", "skipped"):
            key = str(payload.get("idempotency_key") or path.stem).strip()
            if key:
                receipts[key] = payload
    return receipts


def _mapping_from_action(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not (text.startswith("{") and text.endswith("}")):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, Mapping):
        return parsed

    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None
    if isinstance(parsed, Mapping):
        return parsed
    return None


def _local_evidence_mappings(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _branch_from_payload(payload: dict[str, Any]) -> str:
    """Extract a branch from outbox payloads with historical shape drift."""
    for local_evidence in _local_evidence_mappings(payload.get("local_evidence")):
        branch = str(local_evidence.get("branch") or "").strip()
        if branch:
            return branch

    branch = str(payload.get("branch") or "").strip()
    if branch:
        return branch

    requested_action = _mapping_from_action(payload.get("requested_action"))
    if requested_action is not None:
        return str(requested_action.get("branch") or "").strip()
    return ""


NON_HANDOFF_REPORT_DISPOSITION = "non_handoff_report"


def _has_requested_action_contract(payload: Mapping[str, Any]) -> bool:
    requested_action = payload.get("requested_action")
    if isinstance(requested_action, str):
        return bool(requested_action.strip())
    if _mapping_from_action(requested_action) is not None:
        return True
    return False


def _looks_like_non_handoff_report(payload: Mapping[str, Any]) -> bool:
    preservation_markers = {
        "branch",
        "constraints",
        "desired_head",
        "desired_head_sha",
        "commit",
        "head",
        "head_sha",
        "local_evidence",
        "requested_action",
        "worktree",
        "worktree_path",
    }
    if any(key in payload for key in preservation_markers):
        return False

    report_markers = {
        "candidate_notes",
        "cycle_dir",
        "main_required_check_state",
        "required_contexts",
        "rows",
        "verified_8992",
    }
    report_identity_markers = {
        "candidate_notes",
        "cycle_dir",
        "main_required_check_state",
        "verified_8992",
    }
    return sum(1 for key in report_markers if key in payload) >= 2 and any(
        key in payload for key in report_identity_markers
    )


def _non_handoff_report_terminal_info(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return terminal metadata for branchless report artifacts, if recognized."""
    idem = str(payload.get("idempotency_key") or "").strip()
    if not idem:
        return None
    if _branch_from_payload(dict(payload)):
        return None
    if _has_requested_action_contract(payload):
        return None
    if not _looks_like_non_handoff_report(payload):
        return None
    return {
        "archived_by": "scripts/reconcile_automation_outbox.py",
        "disposition": NON_HANDOFF_REPORT_DISPOSITION,
        "idempotency_key": idem,
        "reason": (
            "branchless conductor report artifact is not an automation handoff; "
            "archived through supported non-handoff report path"
        ),
    }


def _head_from_payload(payload: dict[str, Any]) -> str:
    """Extract the branch head SHA from outbox payloads when present."""
    for local_evidence in _local_evidence_mappings(payload.get("local_evidence")):
        head = str(
            local_evidence.get("head_sha")
            or local_evidence.get("head")
            or local_evidence.get("commit")
            or ""
        ).strip()
        if head:
            return head

    for key in ("head_sha", "head", "commit"):
        head = str(payload.get(key) or "").strip()
        if head:
            return head
    return ""


def _desired_head_from_payload(payload: dict[str, Any]) -> str:
    """Extract the requested branch head SHA from outbox payloads when present."""
    for local_evidence in _local_evidence_mappings(payload.get("local_evidence")):
        head = str(
            local_evidence.get("desired_head_sha")
            or local_evidence.get("head_sha")
            or local_evidence.get("head")
            or local_evidence.get("commit")
            or ""
        ).strip()
        if head:
            return head

    for key in ("desired_head_sha", "head_sha", "head", "commit"):
        head = str(payload.get(key) or "").strip()
        if head:
            return head

    requested_action = _mapping_from_action(payload.get("requested_action"))
    if requested_action is not None:
        for key in ("desired_head_sha", "head_sha", "head", "commit"):
            head = str(requested_action.get(key) or "").strip()
            if head:
                return head
    return ""


def _copy_local_work_markers(record: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key in LOCAL_WORK_MARKER_KEYS:
        if source.get(key):
            record[key] = source.get(key)


def _has_local_work_marker(record: Mapping[str, Any]) -> bool:
    return any(bool(record.get(key)) for key in LOCAL_WORK_MARKER_KEYS)


def _lane_records_from_payload(payload: Mapping[str, Any], branch: str) -> list[dict[str, Any]]:
    """Build lane-like records for every local evidence reference.

    Older handoffs may contain multiple local_evidence records. Treating only
    the last worktree as authoritative can hide still-active local work, so the
    merged-PR proof path must prove every referenced worktree/head independently.
    """

    desired_head = _desired_head_from_payload(dict(payload))
    common: dict[str, Any] = {"branch": branch}
    if desired_head:
        common["desired_head_sha"] = desired_head
        common["head_sha"] = desired_head
    _copy_local_work_markers(common, payload)

    lane = payload.get("lane")
    if isinstance(lane, Mapping):
        lane_id = str(lane.get("lane_id") or lane.get("lane") or "").strip()
        if lane_id:
            common["lane_id"] = lane_id

    records: list[dict[str, Any]] = []
    for local_evidence in _local_evidence_mappings(payload.get("local_evidence")):
        record = dict(common)
        local_branch = str(local_evidence.get("branch") or "").strip()
        if local_branch:
            record["branch"] = local_branch
        local_head = str(
            local_evidence.get("desired_head_sha")
            or local_evidence.get("head_sha")
            or local_evidence.get("head")
            or local_evidence.get("commit")
            or ""
        ).strip()
        if local_head:
            record["desired_head_sha"] = local_head
            record["head_sha"] = local_head
        worktree = str(local_evidence.get("worktree") or "").strip()
        if worktree:
            record["worktree"] = worktree
        _copy_local_work_markers(record, local_evidence)
        records.append(record)

    worktree = str(payload.get("worktree") or "").strip()
    if worktree and not any(record.get("worktree") == worktree for record in records):
        record = dict(common)
        record["worktree"] = worktree
        _copy_local_work_markers(record, payload)
        records.append(record)

    if not records:
        records.append(dict(common))
    return records


def _lane_record_from_payload(payload: Mapping[str, Any], branch: str) -> dict[str, Any]:
    """Build the first minimal lane-like record needed by legacy callers."""
    return _lane_records_from_payload(payload, branch)[0]


def _requested_base_from_payload(payload: Mapping[str, Any]) -> str:
    requested_action = _mapping_from_action(payload.get("requested_action"))
    if requested_action is not None:
        for key in ("base", "base_ref", "base_ref_name", "target_base"):
            base = str(requested_action.get(key) or "").strip()
            if base:
                return base
    for key in ("base", "base_ref", "base_ref_name", "target_base"):
        base = str(payload.get(key) or "").strip()
        if base:
            return base
    return ""


def _upstream_base_matches(upstream: Mapping[str, Any], expected_base: str) -> bool:
    expected = _normalize_base_ref(expected_base)
    for key in ("base_ref", "base_ref_name", "baseRefName", "base"):
        actual = upstream.get(key)
        if isinstance(actual, Mapping):
            actual = actual.get("ref")
        actual_ref = _normalize_base_ref(str(actual or "").strip())
        if actual_ref:
            return actual_ref == expected
    return False


def _desired_head_landed_on_base(root: Path, base: str, branch: str, desired_head: str) -> bool:
    branch_head = _git_ref_head(root, branch) if branch else ""
    if (
        branch_head
        and _heads_match(desired_head, branch_head)
        and _ref_has_landed_on_main(root, base, branch)
    ):
        return True
    return bool(desired_head) and _ref_has_landed_on_main(root, base, desired_head)


def _merged_pr_commit_preservation_proof(
    *,
    root: Path,
    state_root: Path,
    payload: dict[str, Any],
    branch: str,
    repo_name: str,
    base: str,
) -> Mapping[str, Any] | None:
    """Return proof that an outbox head is already preserved by a merged PR.

    This intentionally accepts only the merged-PR commit-list proof. A remote
    branch at the exact desired head still represents unpublished PR-intent work,
    so it must keep protecting the outbox handoff. The merged PR must also target
    the reconciler base, and the desired head must be present or patch-equivalent
    on that base now; historical PR membership alone is not enough after reverts.
    """

    if not _is_pr_publication_request(payload):
        return None
    expected_base = _requested_base_from_payload(payload) or base
    records = _lane_records_from_payload(payload, branch)
    if not records:
        return None

    proofs: list[Mapping[str, Any]] = []
    desired_heads: set[str] = set()
    worktree_paths: list[str] = []
    common_upstream: Mapping[str, Any] | None = None

    for record in records:
        desired_head = str(record.get("desired_head_sha") or "").strip()
        if not desired_head:
            return None
        record_branch = str(record.get("branch") or branch).strip()
        desired_heads.add(desired_head)

        if not record.get("worktree"):
            if _has_local_work_marker(record):
                return None
            if not _desired_head_landed_on_base(root, base, record_branch, desired_head):
                return None
            proof = {
                "available": True,
                "branch": record_branch,
                "desired_head_sha": desired_head,
                "upstream_preservation": {
                    "proven": True,
                    "method": "current_base_contains_desired_head",
                    "base": base,
                },
            }
            proofs.append(proof)
            continue

        worktree_paths.append(str(record.get("worktree") or ""))
        try:
            proof = build_worktree_reference_preservation_proof(
                record,
                repo_root=root,
                state_root=state_root,
            )
        except Exception:
            return None
        if not isinstance(proof, Mapping):
            return None

        upstream = proof.get("upstream_preservation")
        if proof.get("available") is not True:
            if proof.get("reason") != "upstream_preservation_unproven":
                return None
            if not _preservation_proof_has_absent_worktree(proof):
                return None
            upstream = _merged_pr_commit_list_preservation(root, repo_name, desired_head)
            if upstream.get("proven") is not True:
                return None
            proof = {
                **dict(proof),
                "available": True,
                "upstream_preservation": upstream,
                "upstream_preservation_fallback": "direct_paginated_merged_pr_lookup",
            }
        elif not isinstance(upstream, Mapping) or not (
            upstream.get("method") == "merged_pr_commit_list" and upstream.get("proven") is True
        ):
            if not _preservation_proof_has_absent_worktree(proof):
                return None
            upstream = _merged_pr_commit_list_preservation(root, repo_name, desired_head)
            if upstream.get("proven") is not True:
                return None
            proof = {
                **dict(proof),
                "upstream_preservation": upstream,
                "upstream_preservation_fallback": {
                    "from": dict(proof.get("upstream_preservation") or {}),
                    "method": "direct_paginated_merged_pr_lookup",
                },
            }
        if not isinstance(upstream, Mapping):
            return None
        if not _upstream_base_matches(upstream, expected_base):
            return None
        if common_upstream is None:
            common_upstream = upstream
        proofs.append(proof)

    if common_upstream is None:
        common_upstream = {
            "proven": True,
            "method": "current_base_contains_desired_head",
            "base": base,
        }
    if len(proofs) == 1:
        single = dict(proofs[0])
        single["upstream_preservation"] = dict(common_upstream)
        return single
    return {
        "available": True,
        "branch": branch,
        "desired_head_sha": sorted(desired_heads)[0] if len(desired_heads) == 1 else None,
        "desired_head_shas": sorted(desired_heads),
        "worktree_paths": worktree_paths,
        "worktree_proofs": proofs,
        "upstream_preservation": dict(common_upstream),
    }


def _remote_branch_exact_preservation_proof(
    *,
    root: Path,
    state_root: Path,
    payload: dict[str, Any],
    branch: str,
) -> Mapping[str, Any] | None:
    """Return proof that a missing local ref is preserved by exact remote branch."""

    if not _is_pr_publication_request(payload):
        return None
    records = _lane_records_from_payload(payload, branch)
    if not records:
        return None

    proofs: list[Mapping[str, Any]] = []
    desired_heads: set[str] = set()
    worktree_paths: list[str] = []
    for record in records:
        desired_head = str(record.get("desired_head_sha") or "").strip()
        if not desired_head:
            return None
        record_branch = str(record.get("branch") or branch).strip()
        if not record_branch:
            return None
        desired_heads.add(desired_head)
        if _has_local_work_marker(record):
            return None

        if not record.get("worktree"):
            remote = _live_remote_branch_head(root, record_branch)
            remote_head = str(remote.get("head_sha") or "").strip()
            if remote.get("status") != "exists" or not _heads_equal(desired_head, remote_head):
                return None
            proofs.append(
                {
                    "available": True,
                    "branch": record_branch,
                    "desired_head_sha": desired_head,
                    "upstream_preservation": {
                        "proven": True,
                        "method": "remote_branch_exact_head",
                        "remote_ref": remote.get("remote_ref"),
                        "remote_head_sha": remote_head,
                        "source": "git_ls_remote",
                    },
                }
            )
            continue

        worktree_paths.append(str(record.get("worktree") or ""))
        try:
            proof = build_worktree_reference_preservation_proof(
                record,
                repo_root=root,
                state_root=state_root,
            )
        except Exception:
            return None
        if not isinstance(proof, Mapping):
            return None
        upstream = proof.get("upstream_preservation")
        if not isinstance(upstream, Mapping):
            return None
        if proof.get("available") is not True:
            return None
        if upstream.get("method") != "remote_branch_exact_head":
            return None
        if upstream.get("proven") is not True:
            return None
        if not _preservation_proof_has_absent_worktree(proof):
            return None
        proof_desired_head = str(proof.get("desired_head_sha") or "").strip()
        if not proof_desired_head or not _heads_equal(desired_head, proof_desired_head):
            return None
        remote_head = str(upstream.get("remote_head_sha") or "").strip()
        if not remote_head or not _heads_equal(desired_head, remote_head):
            return None
        proofs.append(proof)

    if not proofs:
        return None
    if len(proofs) == 1:
        return proofs[0]
    return {
        "available": True,
        "branch": branch,
        "desired_head_sha": sorted(desired_heads)[0] if len(desired_heads) == 1 else None,
        "desired_head_shas": sorted(desired_heads),
        "worktree_paths": worktree_paths,
        "worktree_proofs": proofs,
        "upstream_preservation": {
            "proven": True,
            "method": "remote_branch_exact_head",
        },
    }


def _preservation_proof_has_absent_worktree(proof: Mapping[str, Any]) -> bool:
    inspections = proof.get("worktree_inspections")
    if not isinstance(inspections, Sequence) or isinstance(inspections, (str, bytes, bytearray)):
        return False
    return bool(inspections) and all(
        isinstance(item, Mapping) and item.get("absent_noop") is True for item in inspections
    )


def _remote_branch_preservation_lookup_failed_reason(
    *,
    root: Path,
    state_root: Path,
    payload: dict[str, Any],
    branch: str,
) -> str | None:
    """Return a fail-closed reason when remote preservation truth is unavailable."""

    if not _is_pr_publication_request(payload):
        return None
    records = _lane_records_from_payload(payload, branch)
    if not records:
        return None

    for record in records:
        desired_head = str(record.get("desired_head_sha") or "").strip()
        record_branch = str(record.get("branch") or branch).strip()
        if not desired_head or not record_branch or _has_local_work_marker(record):
            return None

        if not record.get("worktree"):
            remote = _live_remote_branch_head(root, record_branch)
            if remote.get("status") == "lookup_failed":
                reason = str(remote.get("reason") or "remote branch lookup failed").strip()
                return (
                    f"branch no longer exists locally, but live remote branch state for "
                    f"{record_branch} is unavailable: {reason}"
                )
            continue

        try:
            proof = build_worktree_reference_preservation_proof(
                record,
                repo_root=root,
                state_root=state_root,
            )
        except Exception as exc:
            return (
                f"branch no longer exists locally, but remote preservation proof for "
                f"{record_branch} failed: {exc}"
            )
        if not isinstance(proof, Mapping):
            continue
        if proof.get("reason") == "remote_branch_lookup_failed":
            remote = proof.get("remote")
            reason = ""
            if isinstance(remote, Mapping):
                reason = str(remote.get("reason") or "").strip()
            detail = f": {reason}" if reason else ""
            return (
                f"branch no longer exists locally, but live remote branch state for "
                f"{record_branch} is unavailable{detail}"
            )

    return None


def _gh_api_paginated_items(root: Path, endpoint: str) -> list[Mapping[str, Any]] | None:
    try:
        proc = subprocess.run(
            ["gh", "api", "--paginate", "--slurp", endpoint],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        pages = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    if not isinstance(pages, list):
        return None
    items: list[Mapping[str, Any]] = []
    for page in pages:
        if isinstance(page, list):
            items.extend(item for item in page if isinstance(item, Mapping))
        elif isinstance(page, Mapping):
            items.append(page)
    return items


def _pull_base_ref(pull: Mapping[str, Any]) -> str:
    base = pull.get("base")
    if isinstance(base, Mapping):
        ref = str(base.get("ref") or "").strip()
        if ref:
            return ref
    for key in ("baseRefName", "base_ref_name", "base_ref"):
        ref = str(pull.get(key) or "").strip()
        if ref:
            return ref
    return ""


def _merged_pr_commit_list_preservation(
    root: Path,
    repo_name: str,
    desired_head: str,
) -> Mapping[str, Any]:
    if not desired_head:
        return {
            "proven": False,
            "method": "merged_pr_commit_list",
            "reason": "desired_head_unavailable",
        }
    pulls = _gh_api_paginated_items(root, f"repos/{repo_name}/commits/{desired_head}/pulls")
    if pulls is None:
        return {
            "proven": False,
            "method": "merged_pr_commit_list",
            "reason": "commit_pulls_unavailable",
        }
    for pull in pulls:
        if not pull.get("merged_at"):
            continue
        number = pull.get("number")
        if not isinstance(number, int):
            continue
        commits = _gh_api_paginated_items(
            root,
            f"repos/{repo_name}/pulls/{number}/commits?per_page=100",
        )
        if commits is None:
            continue
        if any(item.get("sha") == desired_head for item in commits):
            return {
                "proven": True,
                "method": "merged_pr_commit_list",
                "pr_number": number,
                "repo": repo_name,
                "source": "gh_api_paginated",
                "base_ref": _pull_base_ref(pull) or None,
            }
    return {
        "proven": False,
        "method": "merged_pr_commit_list",
        "reason": "no_merged_pr_commit_contains_desired_head",
    }


def _requested_action_type(payload: Mapping[str, Any]) -> str:
    requested_action = payload.get("requested_action")
    requested_action_mapping = _mapping_from_action(requested_action)
    if requested_action_mapping is not None:
        return str(requested_action_mapping.get("type") or "").strip().lower()
    if isinstance(requested_action, str):
        return requested_action.strip().lower()
    return ""


def _is_pr_publication_request(payload: Mapping[str, Any]) -> bool:
    return _requested_action_type(payload) in {
        "open_pr",
        "open_pull_request",
        "open_or_update_pr",
        "open_or_update_pull_request",
        "push_branch_and_open_pr",
        "push_branch_and_open_pull_request",
        "push_branch_and_open_or_update_pr",
        "push_branch_and_open_or_update_pull_request",
    }


def _receipt_has_pr_reference(receipt: Mapping[str, Any]) -> bool:
    for key in (
        "created_pr_url",
        "existing_pr_url",
        "pr_url",
        "pull_request_url",
        "created_pull_request_url",
        "existing_pull_request_url",
    ):
        if str(receipt.get(key) or "").strip():
            return True
    return False


def _pr_number_from_value(value: Any) -> int | None:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return None
    if text.isdigit():
        return int(text)
    marker = "/pull/"
    if marker not in text:
        return None
    candidate = text.rsplit(marker, 1)[1].split("/", 1)[0]
    return int(candidate) if candidate.isdigit() else None


def _target_pr_number_from_receipt(receipt: Mapping[str, Any]) -> int | None:
    for key in ("target_pr", "pr_number", "pull_request_number"):
        number = _pr_number_from_value(receipt.get(key))
        if number is not None:
            return number
    for key in (
        "created_pr_url",
        "existing_pr_url",
        "pr_url",
        "pull_request_url",
        "created_pull_request_url",
        "existing_pull_request_url",
    ):
        number = _pr_number_from_value(receipt.get(key))
        if number is not None:
            return number
    return None


def _target_pr_state(
    root: Path,
    repo_name: str,
    receipt: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    number = _target_pr_number_from_receipt(receipt)
    if number is None:
        return None
    repo = str(receipt.get("repo") or repo_name).strip() or repo_name
    try:
        proc = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "number,state,headRefOid",
            ],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, Mapping) else None


def _merged_target_pr_receipt_resolution(
    root: Path,
    repo_name: str,
    payload: dict[str, Any],
    receipt: Mapping[str, Any],
) -> tuple[bool, str | None]:
    """Resolve target-PR receipts whose referenced PR is already merged.

    Returns (handled, keep_reason). When handled is True and keep_reason is None,
    the receipt satisfies the handoff without needing any branch ref checks.
    """

    status = str(receipt.get("status") or "").strip().lower()
    reason = str(receipt.get("reason") or "").strip().lower()
    if status != "already_satisfied" or reason not in {"target_open_pr", "existing_pr"}:
        return False, None
    receipt_label = f"{reason} receipt"

    desired_head = _desired_head_from_payload(payload)
    if not desired_head:
        return False, None

    target_pr_state = _target_pr_state(root, repo_name, receipt)
    if str((target_pr_state or {}).get("state") or "").strip().upper() != "MERGED":
        return False, None

    target_pr_head = str((target_pr_state or {}).get("headRefOid") or "").strip()
    target_pr_number = str((target_pr_state or {}).get("number") or "").strip()
    if _heads_match(desired_head, target_pr_head):
        return True, None
    return True, (
        f"{receipt_label} points to merged PR #{target_pr_number} at "
        f"{target_pr_head[:12] or 'unknown'}, not desired head {desired_head[:12]}"
    )


def _receipt_has_issue_reference(receipt: Mapping[str, Any]) -> bool:
    for key in (
        "created_issue_url",
        "existing_issue_url",
        "issue_url",
    ):
        if str(receipt.get(key) or "").strip():
            return True
    return False


def _issue_only_pr_receipt_keep_reason(
    payload: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> str | None:
    """Return why an issue-only receipt cannot satisfy a PR-intended handoff."""

    if not _is_pr_publication_request(payload):
        return None

    status = str(receipt.get("status") or "").strip().lower()
    if status not in {"already_satisfied", "published"} or _receipt_has_pr_reference(receipt):
        return None

    reason = str(receipt.get("reason") or "").strip().lower()
    if reason in {"published", "existing_issue", "created_issue"} or _receipt_has_issue_reference(
        receipt
    ):
        return "PR-intended handoff has issue-only receipt; keep until a PR receipt exists"
    return None


def _issue_url_from_receipt(receipt: Mapping[str, Any]) -> str:
    for key in ("existing_issue_url", "created_issue_url", "issue_url"):
        url = str(receipt.get(key) or "").strip()
        if url:
            return url
    return ""


def _issue_number_from_url(url: str) -> int | None:
    text = str(url or "").strip().rstrip("/")
    marker = "/issues/"
    if marker not in text:
        return None
    candidate = text.rsplit(marker, 1)[1].split("/", 1)[0]
    return int(candidate) if candidate.isdigit() else None


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _outbox_item_age_days(path: Path, payload: Mapping[str, Any], now: datetime) -> float | None:
    """Age of an outbox handoff, preferring payload timestamps over file mtime."""
    for key in ("created_at", "updated_at"):
        timestamp = _parse_timestamp(payload.get(key))
        if timestamp is not None:
            return (now - timestamp).total_seconds() / 86400.0
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    return (now - datetime.fromtimestamp(mtime, tz=UTC)).total_seconds() / 86400.0


class _IssueStateChecker:
    """Verify linked GitHub issue state via gh, with caching and a failure circuit.

    After MAX_CONSECUTIVE_FAILURES consecutive gh errors the checker stops
    issuing new calls and reports issues as unverifiable, so a GitHub outage
    cannot turn one reconcile pass into hundreds of 20s timeouts.
    """

    MAX_CONSECUTIVE_FAILURES = 3

    def __init__(self, root: Path, default_repo: str) -> None:
        self._root = root
        self._default_repo = default_repo
        self._cache: dict[tuple[str, int], tuple[Mapping[str, Any] | None, str | None]] = {}
        self._consecutive_failures = 0

    def state(
        self, issue_url: str, receipt: Mapping[str, Any]
    ) -> tuple[Mapping[str, Any] | None, str | None]:
        """Return (issue_state, error). issue_state is None when unverifiable."""
        number = _issue_number_from_url(issue_url)
        if number is None:
            return None, f"could not parse issue number from {issue_url!r}"
        repo = str(receipt.get("repo") or self._default_repo).strip() or self._default_repo
        cache_key = (repo, number)
        if cache_key in self._cache:
            return self._cache[cache_key]
        if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            return None, "issue state lookups disabled after repeated gh failures"
        result = self._fetch(repo, number)
        if result[0] is None:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0
        self._cache[cache_key] = result
        return result

    def _fetch(self, repo: str, number: int) -> tuple[Mapping[str, Any] | None, str | None]:
        try:
            proc = subprocess.run(
                [
                    "gh",
                    "issue",
                    "view",
                    str(number),
                    "--repo",
                    repo,
                    "--json",
                    "number,state,stateReason,url",
                ],
                cwd=self._root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"gh issue view failed ({exc.__class__.__name__})"
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip().splitlines()
            return None, f"gh issue view exited {proc.returncode}: {detail[0] if detail else ''}"
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return None, "gh issue view returned unparseable JSON"
        if not isinstance(payload, Mapping):
            return None, "gh issue view returned non-mapping JSON"
        return payload, None


def _existing_issue_terminal_candidate(
    *,
    path: Path,
    payload: Mapping[str, Any],
    receipt: Mapping[str, Any],
    min_age_days: float,
    cap: int,
    archived_so_far: int,
    issue_checker: _IssueStateChecker,
    now: datetime | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Evaluate the bounded existing_issue terminal-archive escape valve.

    Returns (terminal_info, gate_detail):
      (info, None)    -- ALL gates hold; archive with this terminal receipt.
      (None, detail)  -- in scope but a gate blocked it; keep, annotated.
      (None, None)    -- out of scope; the normal issue-only keep applies.
    """
    if not _is_pr_publication_request(payload):
        return None, None
    status = str(receipt.get("status") or "").strip().lower()
    reason = str(receipt.get("reason") or "").strip().lower()
    if status != "already_satisfied" or reason != "existing_issue":
        return None, None
    if _receipt_has_pr_reference(receipt):
        return None, None
    issue_url = _issue_url_from_receipt(receipt)
    if not issue_url:
        return None, None

    now_value = now or datetime.now(UTC)
    age_days = _outbox_item_age_days(path, payload, now_value)
    if age_days is None:
        return None, "terminal-archive gate: item age unknown"
    if age_days < min_age_days:
        return None, (f"terminal-archive gate: item age {age_days:.1f}d < min {min_age_days:.1f}d")
    if archived_so_far >= cap:
        return None, f"terminal-archive gate: per-pass archive cap {cap} reached"

    issue_state, error = issue_checker.state(issue_url, receipt)
    if issue_state is None:
        return None, f"terminal-archive gate: issue state unverified ({error})"
    state = str(issue_state.get("state") or "").strip().upper()
    state_reason = str(issue_state.get("stateReason") or "").strip().upper()
    if state != "OPEN" and not (state == "CLOSED" and state_reason == "COMPLETED"):
        return None, (
            f"terminal-archive gate: issue {issue_url} is "
            f"{state or 'UNKNOWN'}/{state_reason or 'unknown'}, not open or closed-completed"
        )

    terminal_info: dict[str, Any] = {
        "disposition": TERMINAL_DISPOSITION_EXISTING_ISSUE,
        "issue_url": str(issue_state.get("url") or issue_url),
        "issue_number": issue_state.get("number"),
        "issue_state": state,
        "issue_state_reason": state_reason or None,
        "issue_state_checked_at": now_value.isoformat(),
        "decision_evidence": {
            "publisher_decision": "existing_issue",
            "receipt_status": status,
            "receipt_reason": reason,
            "receipt_recorded_at": receipt.get("recorded_at"),
            "receipt_idempotency_key": receipt.get("idempotency_key"),
        },
        "item_age_days": round(age_days, 2),
        "min_age_days": min_age_days,
        "per_pass_archive_cap": cap,
        "archived_by": "scripts/reconcile_automation_outbox.py",
    }
    return terminal_info, None


def _archive_with_terminal_disposition(
    path: Path,
    archive_dir: Path,
    payload: Mapping[str, Any],
    terminal_info: Mapping[str, Any],
) -> Path:
    """Archive an outbox handoff with an explicit terminal receipt embedded.

    The archived copy is written first (with terminal_disposition populated)
    and only then is the live outbox file removed, so a failure can never
    delete a handoff without its terminal receipt landing in the archive.
    """
    archived = {key: value for key, value in payload.items() if key != "__source_file"}
    archived["terminal_disposition"] = dict(terminal_info)
    destination = archive_dir / path.name
    destination.write_text(json.dumps(archived, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.unlink()
    return destination


def _archive_with_preservation_proof(
    path: Path,
    archive_dir: Path,
    payload: Mapping[str, Any],
    proof: Mapping[str, Any],
    reason: str,
) -> Path:
    archived = {key: value for key, value in payload.items() if key != "__source_file"}
    archived["terminal_disposition"] = {
        "archived_by": "scripts/reconcile_automation_outbox.py",
        "reason": reason,
        "preservation_proof": dict(proof),
    }
    destination = archive_dir / path.name
    destination.write_text(json.dumps(archived, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.unlink()
    return destination


def _heads_match(expected: str, actual: str) -> bool:
    expected_value = expected.strip().lower()
    actual_value = actual.strip().lower()
    if len(expected_value) < 7 or len(actual_value) < 7:
        return False
    return actual_value.startswith(expected_value) or expected_value.startswith(actual_value)


def _heads_equal(expected: str, actual: str) -> bool:
    return expected.strip().lower() == actual.strip().lower()


def _git_ref_head(root: Path, ref: str) -> str:
    proc = run_git(["rev-parse", "--verify", ref], root, timeout=10)
    if proc.returncode != 0:
        return ""
    lines = proc.stdout.strip().splitlines()
    return lines[0].strip() if lines else ""


def _live_remote_branch_head(root: Path, branch: str) -> Mapping[str, Any]:
    remote_branch = _normalize_base_ref(branch)
    if not remote_branch:
        return {"status": "missing_branch_name"}
    remote_ref = f"refs/heads/{remote_branch}"
    try:
        proc = run_git(["ls-remote", "origin", remote_ref], root, timeout=30)
    except Exception as exc:
        return {"status": "lookup_failed", "remote_ref": remote_ref, "reason": str(exc)}
    if proc.returncode != 0:
        return {
            "status": "lookup_failed",
            "remote_ref": remote_ref,
            "reason": proc.stderr.strip(),
        }
    lines = proc.stdout.strip().splitlines()
    if not lines:
        return {"status": "missing", "remote_ref": remote_ref}
    parts = lines[0].split()
    if not parts:
        return {
            "status": "lookup_failed",
            "remote_ref": remote_ref,
            "reason": "unexpected ls-remote output",
        }
    head = parts[0].strip()
    if not SHA_RE.fullmatch(head):
        return {
            "status": "lookup_failed",
            "remote_ref": remote_ref,
            "reason": "unexpected ls-remote output",
        }
    return {"status": "exists", "remote_ref": remote_ref, "head_sha": head}


def _receipt_handoff_keep_reason(
    root: Path,
    repo_name: str,
    payload: dict[str, Any],
    receipt: Mapping[str, Any],
    branch: str,
) -> str | None:
    """Return why a terminal receipt is not enough to archive this handoff."""

    status = str(receipt.get("status") or "").strip().lower()
    reason = str(receipt.get("reason") or "").strip().lower()
    if status != "already_satisfied" or reason not in {"target_open_pr", "existing_pr"}:
        return None

    desired_head = _desired_head_from_payload(payload)
    if not desired_head:
        return None
    receipt_label = f"{reason} receipt"

    handled, keep_reason = _merged_target_pr_receipt_resolution(root, repo_name, payload, receipt)
    if handled:
        return keep_reason

    remote_ref = f"refs/remotes/origin/{branch}"
    remote_head = _git_ref_head(root, remote_ref)
    if remote_head and _heads_match(desired_head, remote_head):
        return None

    local_head = _git_ref_head(root, branch)
    if local_head and _heads_match(desired_head, local_head):
        short_desired = desired_head[:12]
        if remote_head:
            return (
                f"{receipt_label} exists, but origin/{branch} is "
                f"{remote_head[:12]}, not desired head {short_desired}"
            )
        return (
            f"{receipt_label} exists, but origin/{branch} is unavailable "
            f"and local desired head {short_desired} still needs publication"
        )
    return None


def _superseded_targets(
    outbox_payloads: Sequence[tuple[Path, dict[str, Any]]],
) -> dict[tuple[str, str], dict[str, str]]:
    """Map explicitly superseded branch heads to the active handoff replacing them."""
    targets: dict[tuple[str, str], dict[str, str]] = {}
    for path, payload in outbox_payloads:
        superseder_key = str(payload.get("idempotency_key") or path.stem).strip()
        superseder_branch = _branch_from_payload(payload)
        for local_evidence in _local_evidence_mappings(payload.get("local_evidence")):
            branch = str(
                local_evidence.get("supersedes_branch") or local_evidence.get("source_branch") or ""
            ).strip()
            head = str(
                local_evidence.get("supersedes_head_sha")
                or local_evidence.get("source_head_sha")
                or ""
            ).strip()
            if not branch or not head:
                continue
            targets[(branch, head)] = {
                "branch": superseder_branch,
                "idempotency_key": superseder_key,
                "path": str(path),
            }
    return targets


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _superseded_outbox_keys(
    outbox_payloads: Sequence[tuple[Path, dict[str, Any]]],
) -> dict[str, dict[str, str]]:
    """Map explicitly superseded outbox idempotency keys to their replacement handoff."""
    targets: dict[str, dict[str, str]] = {}
    for path, payload in outbox_payloads:
        superseder_key = str(payload.get("idempotency_key") or path.stem).strip()
        superseder_branch = _branch_from_payload(payload)
        for local_evidence in _local_evidence_mappings(payload.get("local_evidence")):
            keys = _string_list(local_evidence.get("supersedes_outbox_keys"))
            source_candidates = local_evidence.get("source_candidates")
            if isinstance(source_candidates, Sequence) and not isinstance(
                source_candidates, (str, bytes, bytearray)
            ):
                for candidate in source_candidates:
                    if isinstance(candidate, Mapping):
                        keys.append(str(candidate.get("idempotency_key") or "").strip())
            for key in keys:
                if not key or key == superseder_key:
                    continue
                targets[key] = {
                    "branch": superseder_branch,
                    "idempotency_key": superseder_key,
                    "path": str(path),
                }
    return targets


def _write_synthetic_receipt(
    *,
    receipt_dir: Path,
    outbox_payload: dict[str, Any],
    reason: str,
    pr_number: int | None,
    apply: bool,
) -> Path:
    receipt_dir.mkdir(parents=True, exist_ok=True)
    key = str(outbox_payload.get("idempotency_key") or "").strip()
    if not key:
        raise ValueError("outbox payload missing idempotency_key")
    path = receipt_dir / f"{key}.json"
    body = {
        "created_issue_url": None,
        "existing_issue_url": None,
        "existing_pr_url": (
            f"https://github.com/{outbox_payload.get('repo', 'synaptent/aragora')}/pull/{pr_number}"
            if pr_number is not None
            else None
        ),
        "idempotency_key": key,
        "reason": reason,
        "recorded_at": datetime.now(UTC).isoformat(),
        "repo": outbox_payload.get("repo", "synaptent/aragora"),
        "source_file": str(outbox_payload.get("__source_file", "")),
        "status": "already_satisfied",
        "task": outbox_payload.get("task", ""),
        "synthetic": True,
        "synthetic_reason": reason,
    }
    if apply:
        path.write_text(json.dumps(body, indent=2, sort_keys=True))
    return path


def _github_open_pr_state(root: Path, repo_name: str) -> tuple[dict[str, int], bool, str]:
    """Return open PR heads when GitHub is healthy enough to trust."""

    try:
        health = check_github_cli_health(root)
    except Exception as exc:
        return {}, False, f"GitHub health check failed ({exc})"

    if not health.ready:
        detail = f"GitHub unavailable [{health.mode}] {health.error}".strip()
        return {}, False, detail

    try:
        open_prs = open_pr_heads(root, repo_name, "")
    except Exception as exc:
        return {}, False, f"open PR fetch failed ({exc})"
    if not isinstance(open_prs, dict):
        return {}, False, "open PR fetch returned no usable data"
    return open_prs, True, f"{len(open_prs)} open PRs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        default=".",
        help=(
            "Repository root or disposable worktree used for git checks. "
            "Outbox/receipt state defaults to this path's .aragora/ subdirectory "
            "(default: current working directory)."
        ),
    )
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--repo-name", default="synaptent/aragora")
    parser.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help=(
            "Checkout or .aragora directory that owns shared automation state. "
            "Explicit --outbox-dir/--receipt-dir/--archive-dir override it."
        ),
    )
    parser.add_argument(
        "--outbox-dir",
        type=Path,
        default=None,
        help="Directory containing JSON automation outbox handoffs.",
    )
    parser.add_argument(
        "--receipt-dir",
        type=Path,
        default=None,
        help="Directory containing JSON automation publisher receipts.",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=None,
        help=(
            "Directory for archived satisfied outbox handoffs. Defaults beside "
            "the selected automation outbox."
        ),
    )
    parser.add_argument(
        "--idempotency-key",
        action="append",
        default=[],
        help=(
            "Only reconcile the outbox handoff with this idempotency key. "
            "Repeat to target multiple handoffs."
        ),
    )
    parser.add_argument(
        "--outbox-file",
        action="append",
        type=Path,
        default=[],
        help=(
            "Only reconcile this outbox JSON file. Relative paths resolve inside "
            "the selected outbox directory; repeat to target multiple handoffs."
        ),
    )
    parser.add_argument(
        "--existing-issue-min-age-days",
        type=float,
        default=DEFAULT_EXISTING_ISSUE_MIN_AGE_DAYS,
        help=(
            "Minimum handoff age (days) before an open-PR handoff whose publisher "
            "decision was existing_issue may be archived with a terminal receipt "
            f"(default: {DEFAULT_EXISTING_ISSUE_MIN_AGE_DAYS})."
        ),
    )
    parser.add_argument(
        "--existing-issue-archive-cap",
        type=int,
        default=DEFAULT_EXISTING_ISSUE_ARCHIVE_CAP,
        help=(
            "Maximum existing_issue terminal archives per reconcile pass "
            f"(default: {DEFAULT_EXISTING_ISSUE_ARCHIVE_CAP})."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Move satisfied outbox files (default is dry-run)",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicitly use the default read-only dry-run mode",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a machine-readable reconciliation result instead of human text",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="With --json, omit per-handoff action details and print only compact counts.",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help=(
            "Persist a JSON reconciliation report during dry-run. Apply mode always writes "
            "the report."
        ),
    )
    parser.add_argument(
        "--out",
        "--report-path",
        dest="report_path",
        type=Path,
        default=None,
        help=(
            "Explicit JSON report path. Relative paths are resolved from --repo. "
            "Implies --write-report for dry-runs and overrides the default apply report path."
        ),
    )
    args = parser.parse_args(argv)

    root = Path(args.repo).resolve()
    state_root = Path(args.state_root).expanduser().resolve() if args.state_root else root
    outbox_default = _state_default_path(state_root, DEFAULT_OUTBOX_DIR)
    receipt_default = _state_default_path(state_root, DEFAULT_RECEIPT_DIR)
    outbox_dir = _resolve_path(root, args.outbox_dir, outbox_default)
    receipt_dir = _resolve_path(root, args.receipt_dir, receipt_default)
    archive_default = (
        outbox_dir.with_name("automation-outbox-archive")
        if args.outbox_dir is not None
        else _state_default_path(state_root, DEFAULT_ARCHIVE_DIR)
    )
    archive_dir = _resolve_path(root, args.archive_dir, archive_default)

    def emit(message: str = "") -> None:
        if not args.json:
            _emit_output(message)

    emit(f"state_root: {state_root}")
    emit(f"outbox_dir: {outbox_dir}")
    emit(f"receipt_dir: {receipt_dir}")
    emit(f"archive_dir: {archive_dir} {'(will create)' if not archive_dir.exists() else ''}")
    emit(f"mode: {'APPLY' if args.apply else 'DRY-RUN'}\n")

    if args.apply:
        archive_dir.mkdir(parents=True, exist_ok=True)

    emit("loading existing terminal receipt keys...")
    receipt_payloads_by_key = _terminal_receipts_by_key(receipt_dir)
    receipt_keys = set(receipt_payloads_by_key)
    emit(f"  {len(receipt_keys)} terminal receipt keys")

    emit("loading outbox files...")
    all_outbox_files = _list_json(outbox_dir)
    emit(f"  {len(all_outbox_files)} outbox files\n")

    parsed_outbox_payloads: dict[Path, dict[str, Any]] = {}
    for path in all_outbox_files:
        payload = _load_json(path)
        if isinstance(payload, dict):
            parsed_outbox_payloads[path] = payload
    parsed_outbox_items = list(parsed_outbox_payloads.items())
    superseded_targets = _superseded_targets(parsed_outbox_items)
    superseded_keys = _superseded_outbox_keys(parsed_outbox_items)

    target_keys = {str(key).strip() for key in args.idempotency_key if str(key).strip()}
    target_files = {_resolve_outbox_file_filter(outbox_dir, path) for path in args.outbox_file}
    if target_keys or target_files:
        outbox_files = []
        matched_keys: set[str] = set()
        matched_files: set[Path] = set()
        for path in all_outbox_files:
            resolved_path = path.resolve()
            payload = parsed_outbox_payloads.get(path)
            idempotency_key = str((payload or {}).get("idempotency_key") or path.stem).strip()
            if idempotency_key in target_keys or resolved_path in target_files:
                outbox_files.append(path)
                if idempotency_key in target_keys:
                    matched_keys.add(idempotency_key)
                if resolved_path in target_files:
                    matched_files.add(resolved_path)

        missing_keys = sorted(target_keys - matched_keys)
        missing_files = sorted(str(path) for path in target_files - matched_files)
        if missing_keys or missing_files:
            payload = {
                "applied": False,
                "dry_run": not args.apply,
                "error": "target outbox handoff not found",
                "missing_idempotency_keys": missing_keys,
                "missing_outbox_files": missing_files,
                "outbox_count": 0,
                "outbox_dir": str(outbox_dir),
                "repo": str(root),
                "state_root": str(state_root),
                "total_outbox_count": len(all_outbox_files),
            }
            if args.json:
                _emit_output(json.dumps(payload, indent=2, sort_keys=True))
            else:
                for key in missing_keys:
                    emit(f"ERROR: no outbox handoff found for idempotency key {key}")
                for missing_file in missing_files:
                    emit(f"ERROR: no outbox handoff found at {missing_file}")
            return 2
    else:
        outbox_files = all_outbox_files

    open_prs_cache: dict[str, int] | None = None
    open_pr_state_available = False

    def load_open_pr_state() -> tuple[dict[str, int], bool]:
        nonlocal open_prs_cache, open_pr_state_available
        if open_prs_cache is None:
            emit("loading open PR state from GitHub (one bulk call)...")
            open_prs_cache, open_pr_state_available, message = _github_open_pr_state(
                root, args.repo_name
            )
            if open_pr_state_available:
                emit(f"  {message}\n")
            else:
                emit(f"  WARN: {message}; preserving ambiguous handoffs without open-PR truth\n")
        return open_prs_cache, open_pr_state_available

    counts = {
        "satisfied_by_existing_receipt": 0,
        "archived_superseded_by_existing_issue": 0,
        "blocked_receipt_pr_head_mismatch": 0,
        "blocked_receipt_issue_only": 0,
        "satisfied_by_superseded_handoff": 0,
        "satisfied_by_landed_on_main": 0,
        "satisfied_by_open_pr_merged": 0,  # placeholder; we only know open PRs
        "satisfied_by_merged_pr_commit_proof": 0,
        "still_protecting_active_work": 0,
        "missing_branch": 0,
        "blocked_missing_branch_open_pr_unknown": 0,
        "blocked_missing_branch_remote_unknown": 0,
        "non_handoff_report": 0,
        "skipped_unparseable": 0,
    }

    issue_checker = _IssueStateChecker(root, args.repo_name)
    existing_issue_archived = 0

    actions: list[dict[str, Any]] = []
    for path in outbox_files:
        payload = parsed_outbox_payloads.get(path)
        if payload is None:
            counts["skipped_unparseable"] += 1
            continue
        payload["__source_file"] = str(path)
        idem = str(payload.get("idempotency_key") or "").strip()
        branch = _branch_from_payload(payload)

        if not idem or not branch:
            terminal_info = _non_handoff_report_terminal_info(payload)
            if terminal_info is not None:
                counts["non_handoff_report"] += 1
                actions.append(
                    {
                        "path": str(path),
                        "branch": "",
                        "decision": "archive_report",
                        "reason": terminal_info["reason"],
                        "terminal_disposition": terminal_info,
                        "synthetic_receipt": False,
                    }
                )
                if args.apply:
                    _archive_with_terminal_disposition(path, archive_dir, payload, terminal_info)
                continue
            counts["skipped_unparseable"] += 1
            continue

        receipt = receipt_payloads_by_key.get(idem)
        if receipt is not None:
            issue_only_keep_reason = _issue_only_pr_receipt_keep_reason(payload, receipt)
            if issue_only_keep_reason is not None:
                terminal_info, gate_detail = _existing_issue_terminal_candidate(
                    path=path,
                    payload=payload,
                    receipt=receipt,
                    min_age_days=args.existing_issue_min_age_days,
                    cap=args.existing_issue_archive_cap,
                    archived_so_far=existing_issue_archived,
                    issue_checker=issue_checker,
                )
                if terminal_info is not None:
                    existing_issue_archived += 1
                    counts["archived_superseded_by_existing_issue"] += 1
                    actions.append(
                        {
                            "path": str(path),
                            "branch": branch,
                            "decision": "archive",
                            "reason": (
                                "superseded by existing issue "
                                f"{terminal_info['issue_url']} (terminal receipt)"
                            ),
                            "terminal_disposition": terminal_info,
                            "synthetic_receipt": False,
                        }
                    )
                    if args.apply:
                        _archive_with_terminal_disposition(
                            path, archive_dir, payload, terminal_info
                        )
                    continue
                merged_pr_proof = _merged_pr_commit_preservation_proof(
                    root=root,
                    state_root=state_root,
                    payload=payload,
                    branch=branch,
                    repo_name=args.repo_name,
                    base=args.base,
                )
                if merged_pr_proof is not None:
                    upstream = merged_pr_proof.get("upstream_preservation") or {}
                    pr_number = upstream.get("pr_number") if isinstance(upstream, Mapping) else None
                    reason = "desired head preserved by merged PR commit list" + (
                        f" (PR #{pr_number})" if pr_number is not None else ""
                    )
                    counts["satisfied_by_merged_pr_commit_proof"] += 1
                    actions.append(
                        {
                            "path": str(path),
                            "branch": branch,
                            "decision": "archive",
                            "reason": reason,
                            "preservation_proof": merged_pr_proof,
                            "synthetic_receipt": False,
                        }
                    )
                    if args.apply:
                        _archive_with_preservation_proof(
                            path, archive_dir, payload, merged_pr_proof, reason
                        )
                    continue
                issue_only_kept_reason = (
                    issue_only_keep_reason
                    if gate_detail is None
                    else f"{issue_only_keep_reason} ({gate_detail})"
                )
                counts["blocked_receipt_issue_only"] += 1
                counts["still_protecting_active_work"] += 1
                actions.append(
                    {
                        "path": str(path),
                        "branch": branch,
                        "decision": "keep",
                        "reason": issue_only_kept_reason,
                        "synthetic_receipt": False,
                    }
                )
                continue
            target_pr_handled, target_pr_keep_reason = _merged_target_pr_receipt_resolution(
                root, args.repo_name, payload, receipt
            )
            if target_pr_handled:
                if target_pr_keep_reason is not None:
                    counts["blocked_receipt_pr_head_mismatch"] += 1
                    counts["still_protecting_active_work"] += 1
                    actions.append(
                        {
                            "path": str(path),
                            "branch": branch,
                            "decision": "keep",
                            "reason": target_pr_keep_reason,
                            "synthetic_receipt": False,
                        }
                    )
                    continue
                counts["satisfied_by_existing_receipt"] += 1
                actions.append(
                    {
                        "path": str(path),
                        "branch": branch,
                        "decision": "archive",
                        "reason": "matching receipt exists",
                        "synthetic_receipt": False,
                    }
                )
                if args.apply:
                    shutil.move(str(path), str(archive_dir / path.name))
                continue
            if str(receipt.get("reason") or "").strip().lower() == "existing_pr":
                keep_reason = _receipt_handoff_keep_reason(
                    root, args.repo_name, payload, receipt, branch
                )
                if keep_reason is not None:
                    counts["blocked_receipt_pr_head_mismatch"] += 1
                    counts["still_protecting_active_work"] += 1
                    actions.append(
                        {
                            "path": str(path),
                            "branch": branch,
                            "decision": "keep",
                            "reason": keep_reason,
                            "synthetic_receipt": False,
                        }
                    )
                    continue
                counts["satisfied_by_existing_receipt"] += 1
                actions.append(
                    {
                        "path": str(path),
                        "branch": branch,
                        "decision": "archive",
                        "reason": "matching receipt exists",
                        "synthetic_receipt": False,
                    }
                )
                if args.apply:
                    shutil.move(str(path), str(archive_dir / path.name))
                continue
            if _branch_has_landed_on_main(root, args.base, branch):
                counts["satisfied_by_landed_on_main"] += 1
                actions.append(
                    {
                        "path": str(path),
                        "branch": branch,
                        "decision": "archive",
                        "reason": "branch work landed on main (merge or patch-equivalent)",
                        "synthetic_receipt": False,
                    }
                )
                if args.apply:
                    shutil.move(str(path), str(archive_dir / path.name))
                continue
            keep_reason = _receipt_handoff_keep_reason(
                root, args.repo_name, payload, receipt, branch
            )
            if keep_reason is not None:
                counts["blocked_receipt_pr_head_mismatch"] += 1
                counts["still_protecting_active_work"] += 1
                actions.append(
                    {
                        "path": str(path),
                        "branch": branch,
                        "decision": "keep",
                        "reason": keep_reason,
                        "synthetic_receipt": False,
                    }
                )
                continue
            counts["satisfied_by_existing_receipt"] += 1
            actions.append(
                {
                    "path": str(path),
                    "branch": branch,
                    "decision": "archive",
                    "reason": "matching receipt exists",
                    "synthetic_receipt": False,
                }
            )
            if args.apply:
                shutil.move(str(path), str(archive_dir / path.name))
            continue

        key_superseder = superseded_keys.get(idem)
        if key_superseder is not None and key_superseder["idempotency_key"] != idem:
            reason = f"superseded by active handoff {key_superseder['idempotency_key']}"
            counts["satisfied_by_superseded_handoff"] += 1
            actions.append(
                {
                    "path": str(path),
                    "branch": branch,
                    "decision": "archive",
                    "reason": reason,
                    "superseded_by": key_superseder,
                    "synthetic_receipt": True,
                }
            )
            if args.apply:
                _write_synthetic_receipt(
                    receipt_dir=receipt_dir,
                    outbox_payload=payload,
                    reason=reason,
                    pr_number=None,
                    apply=True,
                )
                shutil.move(str(path), str(archive_dir / path.name))
            continue

        head = _head_from_payload(payload)
        superseder = superseded_targets.get((branch, head)) if head else None
        if superseder is not None and superseder["idempotency_key"] != idem:
            reason = f"superseded by active handoff {superseder['idempotency_key']}"
            counts["satisfied_by_superseded_handoff"] += 1
            actions.append(
                {
                    "path": str(path),
                    "branch": branch,
                    "decision": "archive",
                    "reason": reason,
                    "superseded_by": superseder,
                    "synthetic_receipt": True,
                }
            )
            if args.apply:
                _write_synthetic_receipt(
                    receipt_dir=receipt_dir,
                    outbox_payload=payload,
                    reason=reason,
                    pr_number=None,
                    apply=True,
                )
                shutil.move(str(path), str(archive_dir / path.name))
            continue

        try:
            ref_proc = run_git(["rev-parse", "--verify", branch], root, timeout=10)
        except Exception:
            ref_proc = None
        if ref_proc is None or ref_proc.returncode != 0:
            open_prs, open_pr_state_available = load_open_pr_state()
            if branch in open_prs:
                counts["still_protecting_active_work"] += 1
                actions.append(
                    {
                        "path": str(path),
                        "branch": branch,
                        "decision": "keep",
                        "reason": f"branch missing locally but has open PR #{open_prs[branch]}",
                        "synthetic_receipt": False,
                    }
                )
                continue
            if not open_pr_state_available:
                counts["blocked_missing_branch_open_pr_unknown"] += 1
                actions.append(
                    {
                        "path": str(path),
                        "branch": branch,
                        "decision": "keep",
                        "reason": (
                            "branch no longer exists locally, but open PR state is unavailable"
                        ),
                        "synthetic_receipt": False,
                    }
                )
                continue

            merged_pr_proof = _merged_pr_commit_preservation_proof(
                root=root,
                state_root=state_root,
                payload=payload,
                branch=branch,
                repo_name=args.repo_name,
                base=args.base,
            )
            if merged_pr_proof is not None:
                upstream = merged_pr_proof.get("upstream_preservation") or {}
                pr_number = upstream.get("pr_number") if isinstance(upstream, Mapping) else None
                reason = "desired head preserved by merged PR commit list" + (
                    f" (PR #{pr_number})" if pr_number is not None else ""
                )
                counts["satisfied_by_merged_pr_commit_proof"] += 1
                actions.append(
                    {
                        "path": str(path),
                        "branch": branch,
                        "decision": "archive",
                        "reason": reason,
                        "preservation_proof": merged_pr_proof,
                        "synthetic_receipt": True,
                    }
                )
                if args.apply:
                    _write_synthetic_receipt(
                        receipt_dir=receipt_dir,
                        outbox_payload=payload,
                        reason=reason,
                        pr_number=int(pr_number) if isinstance(pr_number, int) else None,
                        apply=True,
                    )
                    _archive_with_preservation_proof(
                        path, archive_dir, payload, merged_pr_proof, reason
                    )
                continue

            remote_branch_proof = _remote_branch_exact_preservation_proof(
                root=root,
                state_root=state_root,
                payload=payload,
                branch=branch,
            )
            if remote_branch_proof is not None:
                counts["still_protecting_active_work"] += 1
                actions.append(
                    {
                        "path": str(path),
                        "branch": branch,
                        "decision": "keep",
                        "reason": (
                            "desired head preserved by exact remote branch; "
                            "local ref unavailable — actively protecting"
                        ),
                        "preservation_proof": remote_branch_proof,
                        "synthetic_receipt": False,
                    }
                )
                continue

            remote_lookup_failure_reason = _remote_branch_preservation_lookup_failed_reason(
                root=root,
                state_root=state_root,
                payload=payload,
                branch=branch,
            )
            if remote_lookup_failure_reason is not None:
                counts["blocked_missing_branch_remote_unknown"] += 1
                counts["still_protecting_active_work"] += 1
                actions.append(
                    {
                        "path": str(path),
                        "branch": branch,
                        "decision": "keep",
                        "reason": remote_lookup_failure_reason,
                        "synthetic_receipt": False,
                    }
                )
                continue

            counts["missing_branch"] += 1
            actions.append(
                {
                    "path": str(path),
                    "branch": branch,
                    "decision": "archive",
                    "reason": "branch no longer exists",
                    "synthetic_receipt": True,
                }
            )
            if args.apply:
                _write_synthetic_receipt(
                    receipt_dir=receipt_dir,
                    outbox_payload=payload,
                    reason="branch no longer exists locally",
                    pr_number=None,
                    apply=True,
                )
                shutil.move(str(path), str(archive_dir / path.name))
            continue

        if _branch_has_landed_on_main(root, args.base, branch):
            counts["satisfied_by_landed_on_main"] += 1
            actions.append(
                {
                    "path": str(path),
                    "branch": branch,
                    "decision": "archive",
                    "reason": "branch work landed on main (merge or patch-equivalent)",
                    "synthetic_receipt": True,
                }
            )
            if args.apply:
                _write_synthetic_receipt(
                    receipt_dir=receipt_dir,
                    outbox_payload=payload,
                    reason="branch work landed on main (merge or patch-equivalent)",
                    pr_number=None,
                    apply=True,
                )
                shutil.move(str(path), str(archive_dir / path.name))
            continue

        open_prs, open_pr_state_available = load_open_pr_state()
        if branch in open_prs:
            counts["still_protecting_active_work"] += 1
            actions.append(
                {
                    "path": str(path),
                    "branch": branch,
                    "decision": "keep",
                    "reason": f"branch has open PR #{open_prs[branch]}",
                    "synthetic_receipt": False,
                }
            )
            continue

        merged_pr_proof = _merged_pr_commit_preservation_proof(
            root=root,
            state_root=state_root,
            payload=payload,
            branch=branch,
            repo_name=args.repo_name,
            base=args.base,
        )
        if merged_pr_proof is not None:
            upstream = merged_pr_proof.get("upstream_preservation") or {}
            pr_number = upstream.get("pr_number") if isinstance(upstream, Mapping) else None
            reason = "desired head preserved by merged PR commit list" + (
                f" (PR #{pr_number})" if pr_number is not None else ""
            )
            counts["satisfied_by_merged_pr_commit_proof"] += 1
            actions.append(
                {
                    "path": str(path),
                    "branch": branch,
                    "decision": "archive",
                    "reason": reason,
                    "preservation_proof": merged_pr_proof,
                    "synthetic_receipt": True,
                }
            )
            if args.apply:
                _write_synthetic_receipt(
                    receipt_dir=receipt_dir,
                    outbox_payload=payload,
                    reason=reason,
                    pr_number=int(pr_number) if isinstance(pr_number, int) else None,
                    apply=True,
                )
                _archive_with_preservation_proof(
                    path, archive_dir, payload, merged_pr_proof, reason
                )
            continue

        reason = (
            "branch has unique commits not on main, no open PR — actively protecting"
            if open_pr_state_available
            else (
                "branch has unique commits not on main, open PR state is unavailable "
                "— actively protecting"
            )
        )
        counts["still_protecting_active_work"] += 1
        actions.append(
            {
                "path": str(path),
                "branch": branch,
                "decision": "keep",
                "reason": reason,
                "synthetic_receipt": False,
            }
        )

    emit("\n--- summary ---")
    for k, v in counts.items():
        emit(f"  {k:>40}: {v}")
    archived = sum(1 for a in actions if a["decision"] in {"archive", "archive_report"})
    kept = sum(1 for a in actions if a["decision"] == "keep")
    reason_counts: dict[str, int] = {}
    for action in actions:
        reason = str(action.get("reason") or "unknown").strip() or "unknown"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    emit(f"\n  total: {archived} archived, {kept} kept")

    should_write_report = args.apply or args.write_report or args.report_path is not None
    report_path: Path | None = None
    if should_write_report:
        if args.report_path is not None:
            out = root / args.report_path
        else:
            state_dir = root / ".aragora" / "cleanup-state"
            out = (
                state_dir
                / f"outbox-reconciliation-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
            )
        out.parent.mkdir(parents=True, exist_ok=True)
        report_path = out
        out.write_text(
            json.dumps(
                {"counts": counts, "actions": actions, "applied": args.apply},
                indent=2,
                sort_keys=True,
            )
        )
        emit(f"\n  report: {out}")
    else:
        emit("\n  report: not written in dry-run; pass --write-report to persist one.")
    if not args.apply:
        emit("\n  DRY-RUN — re-run with --apply to actually archive files.")
    if args.json:
        payload = {
            "actions": actions,
            "applied": args.apply,
            "archive_dir": str(archive_dir),
            "archived": archived,
            "base": args.base,
            "counts": counts,
            "dry_run": not args.apply,
            "existing_issue_policy": {
                "archive_cap": args.existing_issue_archive_cap,
                "archived_this_pass": existing_issue_archived,
                "min_age_days": args.existing_issue_min_age_days,
                "terminal_disposition": TERMINAL_DISPOSITION_EXISTING_ISSUE,
            },
            "kept": kept,
            "outbox_count": len(outbox_files),
            "outbox_dir": str(outbox_dir),
            "reason_counts": reason_counts,
            "receipt_dir": str(receipt_dir),
            "repo": str(root),
            "repo_name": args.repo_name,
            "report": str(report_path) if report_path is not None else None,
            "state_root": str(state_root),
            "target": {
                "idempotency_keys": sorted(target_keys),
                "outbox_files": sorted(str(path) for path in target_files),
            },
            "terminal_receipt_count": len(receipt_keys),
            "total_outbox_count": len(all_outbox_files),
        }
        if args.summary_only:
            payload["action_count"] = len(actions)
            payload["actions_omitted"] = True
            payload.pop("actions", None)
        _emit_output(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
