#!/usr/bin/env python3
"""Enforce execution-gate policy versioning and change-control metadata."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


POST_DEBATE_CONFIG_PATH = Path("aragora/debate/post_debate_coordinator.py")
POLICY_PATH = Path("security/policies/execution_gate_defaults_policy.json")

TRACKED_FIELDS: tuple[str, ...] = (
    "enforce_execution_safety_gate",
    "execution_gate_require_verified_signed_receipt",
    "execution_gate_enforce_receipt_signer_allowlist",
    "execution_gate_allowed_receipt_signer_keys",
    "execution_gate_require_signed_receipt_timestamp",
    "execution_gate_receipt_max_age_seconds",
    "execution_gate_receipt_max_future_skew_seconds",
    "execution_gate_min_provider_diversity",
    "execution_gate_min_model_family_diversity",
    "execution_gate_block_on_context_taint",
    "execution_gate_block_on_high_severity_dissent",
    "execution_gate_high_severity_dissent_threshold",
)


@dataclass(frozen=True)
class Violation:
    path: str
    message: str


def _literal_value(node: ast.AST) -> Any | None:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def _extract_post_debate_defaults(source_text: str) -> dict[str, Any]:
    module = ast.parse(source_text)
    for node in module.body:
        if not isinstance(node, ast.ClassDef) or node.name != "PostDebateConfig":
            continue
        defaults: dict[str, Any] = {}
        for entry in node.body:
            if isinstance(entry, ast.AnnAssign) and isinstance(entry.target, ast.Name):
                if entry.value is None:
                    continue
                defaults[entry.target.id] = _literal_value(entry.value)
        return defaults
    return {}


def canonicalize_json(data: Any) -> str:
    """Canonical JSON string for deterministic checksum/signature generation."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def normalize_policy_value(value: Any) -> Any:
    """Normalize Python literals to JSON-compatible comparison form."""
    if isinstance(value, tuple):
        return [normalize_policy_value(entry) for entry in value]
    if isinstance(value, list):
        return [normalize_policy_value(entry) for entry in value]
    if isinstance(value, dict):
        return {str(key): normalize_policy_value(entry) for key, entry in value.items()}
    return value


def compute_defaults_checksum(defaults: dict[str, Any]) -> str:
    payload = canonicalize_json(normalize_policy_value(defaults)).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def compute_approval_signature(
    policy_id: str,
    version: str,
    defaults_checksum: str,
    approval: dict[str, Any],
) -> str:
    payload = canonicalize_json(
        {
            "policy_id": policy_id,
            "version": version,
            "defaults_checksum": defaults_checksum,
            "approval": approval,
        }
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def validate_policy_document(
    policy: dict[str, Any],
    source_defaults: dict[str, Any],
) -> list[str]:
    errors: list[str] = []

    policy_id = str(policy.get("policy_id") or "").strip()
    version = str(policy.get("version") or "").strip()
    defaults = policy.get("defaults")
    approval = policy.get("approval")
    defaults_checksum = str(policy.get("defaults_checksum") or "").strip()
    approval_signature = str(policy.get("approval_signature") or "").strip()

    if not policy_id:
        errors.append("missing `policy_id`")
    if not version:
        errors.append("missing `version`")
    if not isinstance(defaults, dict):
        errors.append("missing or invalid `defaults` section")
    if not isinstance(approval, dict):
        errors.append("missing or invalid `approval` section")

    if isinstance(approval, dict):
        approved_by = approval.get("approved_by")
        if not isinstance(approved_by, list) or not approved_by:
            errors.append("`approval.approved_by` must be a non-empty list")
        if not str(approval.get("approved_at") or "").strip():
            errors.append("missing `approval.approved_at`")
        if not str(approval.get("change_ticket") or "").strip():
            errors.append("missing `approval.change_ticket`")

    if not defaults_checksum:
        errors.append("missing `defaults_checksum`")
    if not approval_signature:
        errors.append("missing `approval_signature`")

    if not isinstance(defaults, dict):
        return errors

    expected_defaults = normalize_policy_value(
        {key: source_defaults[key] for key in TRACKED_FIELDS if key in source_defaults}
    )
    missing_defaults = sorted(set(TRACKED_FIELDS) - set(defaults))
    extra_defaults = sorted(set(defaults) - set(TRACKED_FIELDS))
    if missing_defaults:
        errors.append(f"`defaults` missing tracked keys: {', '.join(missing_defaults)}")
    if extra_defaults:
        errors.append(f"`defaults` contains untracked keys: {', '.join(extra_defaults)}")

    if defaults != expected_defaults:
        errors.append("`defaults` do not match PostDebateConfig execution-gate baselines")

    expected_checksum = compute_defaults_checksum(defaults)
    if defaults_checksum != expected_checksum:
        errors.append(
            f"`defaults_checksum` mismatch (expected {expected_checksum}, found {defaults_checksum})"
        )

    if isinstance(approval, dict) and policy_id and version and defaults_checksum:
        expected_signature = compute_approval_signature(
            policy_id=policy_id,
            version=version,
            defaults_checksum=defaults_checksum,
            approval=approval,
        )
        if approval_signature != expected_signature:
            errors.append(
                "`approval_signature` mismatch "
                f"(expected {expected_signature}, found {approval_signature})"
            )

    return errors


def check_repo(repo_root: Path) -> list[Violation]:
    violations: list[Violation] = []

    source_path = repo_root / POST_DEBATE_CONFIG_PATH
    if not source_path.exists():
        return [
            Violation(
                path=str(POST_DEBATE_CONFIG_PATH),
                message="missing PostDebateConfig source file",
            )
        ]

    policy_path = repo_root / POLICY_PATH
    if not policy_path.exists():
        return [
            Violation(
                path=str(POLICY_PATH),
                message="missing execution-gate policy document",
            )
        ]

    source_text = source_path.read_text(encoding="utf-8")
    source_defaults = _extract_post_debate_defaults(source_text)
    if not source_defaults:
        violations.append(
            Violation(
                path=str(POST_DEBATE_CONFIG_PATH),
                message="failed to parse PostDebateConfig defaults",
            )
        )
        return violations

    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [
            Violation(
                path=str(POLICY_PATH),
                message=f"invalid JSON: {exc}",
            )
        ]

    errors = validate_policy_document(policy, source_defaults)
    violations.extend(Violation(path=str(POLICY_PATH), message=error) for error in errors)
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate execution-gate policy versioning/change-control metadata",
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root to check",
    )
    args = parser.parse_args()

    violations = check_repo(Path(args.repo_root).resolve())
    if not violations:
        print("Execution gate policy control check passed")
        return 0

    print("Execution gate policy control violations detected:")
    for violation in violations:
        print(f"- {violation.path}: {violation.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
