#!/usr/bin/env python3
"""Guard execution safety gate defaults against policy regressions."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Violation:
    path: str
    message: str


POST_DEBATE_CONFIG_PATH = Path("aragora/debate/post_debate_coordinator.py")
ORCHESTRATOR_RUNNER_PATH = Path("aragora/debate/orchestrator_runner.py")

REQUIRED_TRUE_FIELDS: set[str] = {
    "enforce_execution_safety_gate",
    "execution_gate_require_verified_signed_receipt",
    "execution_gate_require_signed_receipt_timestamp",
    "execution_gate_block_on_context_taint",
    "execution_gate_block_on_high_severity_dissent",
}

MINIMUM_FIELDS: dict[str, float] = {
    "execution_gate_receipt_max_age_seconds": 300,
    "execution_gate_receipt_max_future_skew_seconds": 0,
    "execution_gate_min_provider_diversity": 2,
    "execution_gate_min_model_family_diversity": 2,
}

MAXIMUM_FIELDS: dict[str, float] = {
    "execution_gate_receipt_max_age_seconds": 86400,
    "execution_gate_receipt_max_future_skew_seconds": 300,
    "execution_gate_high_severity_dissent_threshold": 0.7,
}

ORCHESTRATOR_EXPECTED_GETATTRS: dict[str, str] = {
    "require_verified_signed_receipt": "execution_gate_require_verified_signed_receipt",
    "require_receipt_signer_allowlist": "execution_gate_enforce_receipt_signer_allowlist",
    "allowed_receipt_signer_keys": "execution_gate_allowed_receipt_signer_keys",
    "require_signed_receipt_timestamp": "execution_gate_require_signed_receipt_timestamp",
    "receipt_max_age_seconds": "execution_gate_receipt_max_age_seconds",
    "receipt_max_future_skew_seconds": "execution_gate_receipt_max_future_skew_seconds",
    "min_provider_diversity": "execution_gate_min_provider_diversity",
    "min_model_family_diversity": "execution_gate_min_model_family_diversity",
    "block_on_context_taint": "execution_gate_block_on_context_taint",
    "block_on_high_severity_dissent": "execution_gate_block_on_high_severity_dissent",
    "high_severity_dissent_threshold": "execution_gate_high_severity_dissent_threshold",
}


def _literal_value(node: ast.AST) -> Any | None:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return None


def _validate_field_value(field: str, value: Any) -> str | None:
    if field in REQUIRED_TRUE_FIELDS and value is not True:
        return f"`{field}` must default to True (found {value!r})"

    if field in MINIMUM_FIELDS:
        minimum = MINIMUM_FIELDS[field]
        if not isinstance(value, (int, float)):
            return f"`{field}` must be numeric (found {type(value).__name__})"
        if float(value) < minimum:
            return f"`{field}` must be >= {minimum} (found {value!r})"

    if field in MAXIMUM_FIELDS:
        maximum = MAXIMUM_FIELDS[field]
        if not isinstance(value, (int, float)):
            return f"`{field}` must be numeric (found {type(value).__name__})"
        if float(value) > maximum:
            return f"`{field}` must be <= {maximum} (found {value!r})"

    return None


def _find_post_debate_config_defaults(module: ast.Module) -> dict[str, Any]:
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


def find_post_debate_default_violations(source_text: str) -> list[str]:
    try:
        module = ast.parse(source_text)
    except SyntaxError as exc:
        return [f"invalid python syntax: {exc}"]

    defaults = _find_post_debate_config_defaults(module)
    if not defaults:
        return ["missing `PostDebateConfig` class or literal defaults"]

    violations: list[str] = []
    tracked_fields = REQUIRED_TRUE_FIELDS | set(MINIMUM_FIELDS) | set(MAXIMUM_FIELDS)
    for field in sorted(tracked_fields):
        if field not in defaults:
            violations.append(f"missing default for `{field}` in `PostDebateConfig`")
            continue

        value = defaults[field]
        if value is None:
            violations.append(f"default for `{field}` must be a literal value")
            continue

        error = _validate_field_value(field, value)
        if error:
            violations.append(error)
    return violations


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _extract_execution_safety_policy_call(module: ast.Module) -> ast.Call | None:
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        if _call_name(node.func) != "ExecutionSafetyPolicy":
            continue
        if {kw.arg for kw in node.keywords if kw.arg}.issuperset(ORCHESTRATOR_EXPECTED_GETATTRS):
            return node
    return None


def _parse_getattr_call(node: ast.AST) -> tuple[str | None, Any | None, str | None]:
    if not isinstance(node, ast.Call) or _call_name(node.func) != "getattr":
        return None, None, "must use getattr(..., <field>, <fallback>)"
    if len(node.args) < 3:
        return None, None, "getattr must include explicit fallback argument"

    field_node = node.args[1]
    field_name = _literal_value(field_node)
    if not isinstance(field_name, str):
        return None, None, "getattr field selector must be a string literal"

    fallback_value = _literal_value(node.args[2])
    if fallback_value is None:
        return field_name, None, "getattr fallback must be a literal value"

    return field_name, fallback_value, None


def find_orchestrator_runner_default_violations(source_text: str) -> list[str]:
    try:
        module = ast.parse(source_text)
    except SyntaxError as exc:
        return [f"invalid python syntax: {exc}"]

    call = _extract_execution_safety_policy_call(module)
    if call is None:
        return ["missing `ExecutionSafetyPolicy(...)` call with required execution-gate fields"]

    keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg}
    violations: list[str] = []
    for policy_arg, expected_field in ORCHESTRATOR_EXPECTED_GETATTRS.items():
        node = keywords.get(policy_arg)
        if node is None:
            violations.append(f"missing `{policy_arg}` argument in `ExecutionSafetyPolicy(...)`")
            continue

        field_name, fallback_value, error = _parse_getattr_call(node)
        if error:
            violations.append(f"`{policy_arg}` {error}")
            continue

        if field_name != expected_field:
            violations.append(
                f"`{policy_arg}` must read `{expected_field}` via getattr (found {field_name!r})"
            )
            continue

        validation_error = _validate_field_value(expected_field, fallback_value)
        if validation_error:
            violations.append(
                f"`{policy_arg}` fallback weakens baseline policy: {validation_error}"
            )
    return violations


def check_repo(repo_root: Path) -> list[Violation]:
    violations: list[Violation] = []

    post_debate_file = repo_root / POST_DEBATE_CONFIG_PATH
    if not post_debate_file.exists():
        violations.append(
            Violation(
                path=str(POST_DEBATE_CONFIG_PATH),
                message="missing post-debate coordinator file",
            )
        )
    else:
        text = post_debate_file.read_text(encoding="utf-8")
        violations.extend(
            Violation(path=str(POST_DEBATE_CONFIG_PATH), message=msg)
            for msg in find_post_debate_default_violations(text)
        )

    orchestrator_file = repo_root / ORCHESTRATOR_RUNNER_PATH
    if not orchestrator_file.exists():
        violations.append(
            Violation(
                path=str(ORCHESTRATOR_RUNNER_PATH),
                message="missing orchestrator runner file",
            )
        )
    else:
        text = orchestrator_file.read_text(encoding="utf-8")
        violations.extend(
            Violation(path=str(ORCHESTRATOR_RUNNER_PATH), message=msg)
            for msg in find_orchestrator_runner_default_violations(text)
        )

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enforce secure execution safety gate defaults and fallback guards."
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Repository root to check",
    )
    args = parser.parse_args()

    violations = check_repo(Path(args.repo_root).resolve())
    if not violations:
        print("Execution gate defaults check passed")
        return 0

    print("Execution gate defaults policy violations detected:")
    for violation in violations:
        print(f"- {violation.path}: {violation.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
