"""Merge-gate state and replay predicates for dev-coordination work orders.

Builds the merge-gate state of a work order and decides when a failed merge
gate should be replayed (docs-only, missing-required, narrow-pytest, targeted
or environment-blocked verification), reconciled, or reclassified as a stale
branch. Split out of :mod:`aragora.nomic.dev_coordination.core`, which
re-imports every name here, so ``core._merge_gate_state_for_work_order``, the
package-level attribute fallthrough and the ``aragora.nomic.dev_receipts``
aliases keep resolving to these objects.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

from aragora.nomic.dev_coordination.utils import _normalize_claim
from aragora.nomic.dev_coordination.work_order_overlap import (
    _optional_text,
    _work_order_has_concrete_deliverable,
)
from aragora.nomic.dev_coordination_verification import (
    _TEST_FILE_PATTERN,
    _canonical_verification_command,
    _extract_tests_value,
    _inferred_expected_tests_for_work_order,
    _is_overbroad_pytest_command,
    _pytest_command_targets,
    _verification_command_covers_expected,
)

_DOCS_ONLY_GENERATE_CAPABILITY_MATRIX_COMMANDS = (
    "python3 scripts/generate_capability_matrix.py",
    "python3 scripts/generate_capability_matrix.py --out docs-site/docs/contributing/capability-matrix.md",
)


def _is_docs_only_path(path: Any) -> bool:
    normalized = str(path or "").strip().removeprefix("./")
    if not normalized:
        return False
    return normalized.startswith("docs/") or normalized.endswith((".md", ".mdx", ".rst", ".txt"))


def _merge_gate_state_for_work_order(work_order: dict[str, Any]) -> dict[str, Any]:
    expected_checks = _inferred_expected_tests_for_work_order(work_order)
    verification_results = [
        dict(entry)
        for entry in work_order.get("verification_results", [])
        if isinstance(entry, dict) and str(entry.get("command", "")).strip()
    ]
    missing_checks = [
        command
        for command in expected_checks
        if not any(
            _verification_command_covers_expected(entry.get("command", ""), command)
            for entry in verification_results
        )
    ]
    failed_checks = [
        dict(entry)
        for entry in verification_results
        if any(
            _verification_command_covers_expected(entry.get("command", ""), command)
            for command in expected_checks
        )
        and not bool(entry.get("passed", False))
    ]
    deferred_dependency_ids = [
        str(dep).strip()
        for dep in (
            dict(work_order.get("metadata") or {}).get("deferred_verification_to_dependency_ids")
            or []
        )
        if str(dep).strip()
    ]

    if deferred_dependency_ids:
        return {
            "enabled": True,
            "expected_checks": expected_checks,
            "verification_results": verification_results,
            "verification_missing_reason": None,
            "checks_passed": True,
            "human_approval_required": True,
            "merge_eligible": True,
            "blocked_reasons": [],
            "verification_deferred_to_dependency_ids": deferred_dependency_ids,
        }

    blocked_reasons: list[str] = []
    verification_missing_reason: str | None = None
    if not expected_checks:
        candidates = [
            str(path).strip()
            for path in work_order.get("changed_paths", []) or work_order.get("file_scope", [])
            if str(path).strip()
        ]
        if candidates and all(_is_docs_only_path(path) for path in candidates):
            return {
                "enabled": True,
                "expected_checks": expected_checks,
                "verification_results": verification_results,
                "verification_missing_reason": None,
                "checks_passed": True,
                "human_approval_required": True,
                "merge_eligible": True,
                "blocked_reasons": [],
            }
        verification_missing_reason = "missing_verification_plan"
        blocked_reasons.append(
            "merge gate blocked: missing verification plan or verification command"
        )
    if missing_checks:
        blocked_reasons.append(
            "merge gate blocked: required verification did not run: "
            + ", ".join(missing_checks[:3])
        )
    if failed_checks:
        first = failed_checks[0]
        reason = (
            "merge gate blocked: verification failed: "
            f"{first.get('command', '')} (exit {first.get('exit_code', -1)})"
        )
        stderr = str(first.get("stderr", "")).strip()
        if stderr:
            reason = f"{reason} - {stderr.splitlines()[0][:200]}"
        blocked_reasons.append(reason)

    checks_passed = not blocked_reasons
    return {
        "enabled": True,
        "expected_checks": expected_checks,
        "verification_results": verification_results,
        "verification_missing_reason": verification_missing_reason,
        "checks_passed": checks_passed,
        "human_approval_required": True,
        "merge_eligible": checks_passed,
        "blocked_reasons": blocked_reasons,
    }


def _work_order_should_replay_missing_verification(work_order: dict[str, Any]) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested"}:
        return False
    if _optional_text(work_order.get("failure_reason")).lower() != "merge_gate_failed":
        return False
    if not _work_order_has_concrete_deliverable(work_order):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    expected_tests = [
        str(item).strip() for item in work_order.get("expected_tests", []) if str(item).strip()
    ]
    if not expected_tests:
        return False
    verification_results = [
        dict(entry)
        for entry in work_order.get("verification_results", [])
        if isinstance(entry, dict) and str(entry.get("command", "")).strip()
    ]
    if verification_results:
        return False
    tests_run = [str(item).strip() for item in work_order.get("tests_run", []) if str(item).strip()]
    return not tests_run


def _verification_result_looks_environment_blocked(result: dict[str, Any]) -> bool:
    if not isinstance(result, dict):
        return False
    if bool(result.get("passed", False)):
        return False
    haystack = "\n".join(
        str(result.get(key, "")).lower()
        for key in ("stdout", "stderr")
        if str(result.get(key, "")).strip()
    )
    return any(
        marker in haystack
        for marker in (
            "no module named 'aragora_debate'",
            "no module named 'pydantic_settings'",
            "cannot find module 'next/jest'",
            "jest: command not found",
            "cannot find module 'react'",
            "react/jsx-runtime",
            "cannot execute binary file",
        )
    )


def _docs_only_verification_script_path(command: Any) -> str:
    normalized = _canonical_verification_command(command)
    if not normalized:
        return ""
    try:
        tokens = shlex.split(normalized)
    except ValueError:
        return ""
    if not tokens:
        return ""
    interpreter = Path(tokens[0]).name
    if len(tokens) < 2 or not interpreter.startswith("python"):
        return ""
    return tokens[1]


def _is_docs_only_verification_command(command: Any) -> bool:
    script = _docs_only_verification_script_path(command)
    return script in {
        "scripts/reconcile_status_docs.py",
        "scripts/check_capability_matrix_sync.py",
        "scripts/check_version_alignment.py",
        "scripts/generate_capability_matrix.py",
    }


def _docs_only_merge_gate_needs_capability_matrix_generation(
    work_order: dict[str, Any],
    commands: list[str],
) -> bool:
    if any(
        _docs_only_verification_script_path(command)
        in {
            "scripts/reconcile_status_docs.py",
            "scripts/check_capability_matrix_sync.py",
        }
        for command in commands
        if str(command).strip()
    ):
        return True
    haystacks = [str(work_order.get("dispatch_error", "")).lower()]
    for entry in work_order.get("verification_results", []):
        if not isinstance(entry, dict):
            continue
        haystacks.extend(
            str(entry.get(field, "")).lower() for field in ("stdout", "stderr") if entry.get(field)
        )
    combined = "\n".join(haystacks)
    return any(
        marker in combined
        for marker in (
            "capability matrix files are out of date",
            "capability_matrix.md",
            "generate_capability_matrix.py",
        )
    )


def _docs_only_replay_commands_for_work_order(work_order: dict[str, Any]) -> list[str] | None:
    commands: list[str] = []
    seen: set[str] = set()

    def _append(command: Any) -> None:
        text = str(command).strip()
        canonical = _canonical_verification_command(text)
        if not text or not canonical or canonical in seen:
            return
        seen.add(canonical)
        commands.append(text)

    for source in (
        work_order.get("expected_tests", []),
        work_order.get("tests_run", []),
    ):
        for entry in source:
            if _is_docs_only_verification_command(entry):
                _append(entry)
    for entry in work_order.get("verification_results", []):
        if not isinstance(entry, dict):
            continue
        command = entry.get("command", "")
        if _is_docs_only_verification_command(command):
            _append(command)

    if not commands:
        return None

    if _docs_only_merge_gate_needs_capability_matrix_generation(work_order, commands):
        generated: list[str] = []
        for command in _DOCS_ONLY_GENERATE_CAPABILITY_MATRIX_COMMANDS:
            canonical = _canonical_verification_command(command)
            if canonical in seen:
                continue
            seen.add(canonical)
            generated.append(command)
        commands = generated + commands

    return commands


def _work_order_should_replay_docs_only_merge_gate_failure(work_order: dict[str, Any]) -> bool:
    if not _work_order_should_reconcile_merge_gate_failure(work_order):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    candidates = [
        str(path).strip()
        for path in work_order.get("changed_paths", []) or work_order.get("file_scope", [])
        if str(path).strip()
    ]
    if not candidates or not all(_is_docs_only_path(path) for path in candidates):
        return False
    return _docs_only_replay_commands_for_work_order(work_order) is not None


def _missing_required_replay_commands_for_work_order(
    work_order: dict[str, Any],
) -> list[str] | None:
    if not _work_order_should_reconcile_merge_gate_failure(work_order):
        return None
    if not _optional_text(work_order.get("receipt_id")):
        return None

    merge_gate = _merge_gate_state_for_work_order(work_order)
    expected_checks = [
        str(command).strip()
        for command in merge_gate.get("expected_checks", [])
        if str(command).strip()
    ]
    verification_results = [
        dict(entry)
        for entry in work_order.get("verification_results", [])
        if isinstance(entry, dict) and str(entry.get("command", "")).strip()
    ]
    if not expected_checks:
        return None

    missing_checks = [
        command
        for command in expected_checks
        if not any(
            _verification_command_covers_expected(entry.get("command", ""), command)
            for entry in verification_results
        )
    ]
    failed_checks = [
        dict(entry)
        for entry in verification_results
        if any(
            _verification_command_covers_expected(entry.get("command", ""), command)
            for command in expected_checks
        )
        and not bool(entry.get("passed", False))
    ]
    if failed_checks or not missing_checks:
        return None
    return missing_checks


def _work_order_should_replay_missing_required_merge_gate_failure(
    work_order: dict[str, Any],
) -> bool:
    return _missing_required_replay_commands_for_work_order(work_order) is not None


def _narrow_pytest_replay_commands_for_work_order(work_order: dict[str, Any]) -> list[str] | None:
    commands: list[str] = []
    seen: set[str] = set()

    def _append(command: Any) -> None:
        text = str(command).strip()
        canonical = _canonical_verification_command(text)
        if not text or not canonical or canonical in seen:
            return
        if not _pytest_command_targets(text) or _is_overbroad_pytest_command(text):
            return
        seen.add(canonical)
        commands.append(text)

    for source in (
        work_order.get("expected_tests", []),
        work_order.get("tests_run", []),
    ):
        for entry in source:
            _append(entry)
    for entry in work_order.get("verification_results", []):
        if not isinstance(entry, dict):
            continue
        _append(entry.get("command", ""))

    return commands or None


def _work_order_should_replay_narrow_pytest_merge_gate_failure(work_order: dict[str, Any]) -> bool:
    if not _work_order_should_reconcile_merge_gate_failure(work_order):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    return _narrow_pytest_replay_commands_for_work_order(work_order) is not None


def _work_order_should_replay_environment_blocked_verification(work_order: dict[str, Any]) -> bool:
    if not _work_order_should_reconcile_merge_gate_failure(work_order):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    verification_results = [
        dict(entry)
        for entry in work_order.get("verification_results", [])
        if isinstance(entry, dict) and str(entry.get("command", "")).strip()
    ]
    return any(
        _verification_result_looks_environment_blocked(entry) for entry in verification_results
    )


def _targeted_replay_expected_tests_for_work_order(work_order: dict[str, Any]) -> list[str]:
    targeted: list[str] = []
    seen: set[str] = set()

    def _append(command: str) -> None:
        display = str(command).strip()
        normalized = _canonical_verification_command(display)
        if (
            not display
            or not normalized
            or normalized in seen
            or _is_overbroad_pytest_command(normalized)
        ):
            return
        seen.add(normalized)
        targeted.append(display)

    success_criteria = work_order.get("success_criteria")
    if isinstance(success_criteria, dict):
        for entry in _extract_tests_value(success_criteria.get("tests")):
            _append(entry)

    metadata = work_order.get("metadata")
    if isinstance(metadata, dict):
        for entry in metadata.get("acceptance_criteria", []):
            text = str(entry).strip()
            if text.startswith("python -m pytest") or text.startswith("pytest"):
                _append(text)
            for match in _TEST_FILE_PATTERN.findall(text):
                _append(f"python -m pytest {match} -q")

    for entry in work_order.get("tests_run", []):
        _append(str(entry))

    for entry in work_order.get("verification_results", []):
        if isinstance(entry, dict):
            _append(str(entry.get("command", "")))

    for path in work_order.get("file_scope", []):
        normalized = str(path).strip()
        if normalized.startswith("tests/") and normalized.endswith(".py"):
            _append(f"python -m pytest {normalized} -q")

    for path in work_order.get("changed_paths", []):
        normalized = str(path).strip()
        if normalized.startswith("tests/") and normalized.endswith(".py"):
            _append(f"python -m pytest {normalized} -q")

    return targeted


def _work_order_should_replay_targeted_merge_gate_failure(work_order: dict[str, Any]) -> bool:
    if not _work_order_should_reconcile_merge_gate_failure(work_order):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    current_expected = [
        _canonical_verification_command(command)
        for command in work_order.get("expected_tests", [])
        if str(command).strip()
    ]
    if not any(_is_overbroad_pytest_command(command) for command in current_expected):
        return False
    targeted = _targeted_replay_expected_tests_for_work_order(work_order)
    if not targeted:
        return False
    return set(targeted) != {command for command in current_expected if command}


def _mainline_verification_commands_for_work_order(work_order: dict[str, Any]) -> list[str]:
    targeted = _targeted_replay_expected_tests_for_work_order(work_order)
    if targeted:
        return list(targeted)

    commands: list[str] = []
    seen: set[str] = set()
    for entry in work_order.get("expected_tests", []):
        display = str(entry).strip()
        normalized = _canonical_verification_command(display)
        if not display or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        commands.append(display)
    return commands


def _mainline_candidate_repo_paths_for_work_order(work_order: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()

    def _append(raw: Any) -> None:
        text = str(raw or "").strip()
        if not text:
            return
        target = text.split("::", 1)[0].strip()
        normalized = _normalize_claim(target)
        if not normalized or any(token in normalized for token in ("*", "?", "[", "]", "{", "}")):
            return
        if normalized in seen:
            return
        seen.add(normalized)
        paths.append(normalized)

    for entry in work_order.get("file_scope", []) or []:
        _append(entry)
    for entry in work_order.get("changed_paths", []) or []:
        _append(entry)
    for command in _mainline_verification_commands_for_work_order(work_order):
        for target in _pytest_command_targets(command):
            _append(target)
    return paths


def _mainline_missing_repo_paths_for_work_order(
    work_order: dict[str, Any],
    *,
    repo_root: Path,
) -> list[str]:
    root = repo_root.resolve()
    missing: list[str] = []
    for candidate in _mainline_candidate_repo_paths_for_work_order(work_order):
        resolved = (root / candidate).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        if not resolved.exists():
            missing.append(candidate)
    return missing


def _work_order_should_reclassify_branch_stale_verification_target_missing(
    work_order: dict[str, Any],
    *,
    repo_root: Path,
) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested"}:
        return False
    if _optional_text(work_order.get("failure_reason")).lower() != "verification_target_missing":
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    if not _work_order_has_concrete_deliverable(work_order):
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and (
        bool(metadata.get("mainline_verification_passed"))
        or bool(metadata.get("mainline_verification_target_missing"))
    ):
        return False
    candidate_paths = _mainline_candidate_repo_paths_for_work_order(work_order)
    if not candidate_paths:
        return False
    missing_paths = _mainline_missing_repo_paths_for_work_order(work_order, repo_root=repo_root)
    return bool(missing_paths) and len(missing_paths) == len(candidate_paths)


def _work_order_should_reclassify_branch_stale_merge_gate_failure(
    work_order: dict[str, Any],
) -> bool:
    if not _work_order_should_reconcile_merge_gate_failure(work_order):
        return False
    if not _optional_text(work_order.get("receipt_id")):
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and bool(metadata.get("mainline_verification_passed")):
        return False
    return bool(_mainline_verification_commands_for_work_order(work_order))


def _work_order_should_reconcile_merge_gate_failure(work_order: dict[str, Any]) -> bool:
    if not isinstance(work_order, dict):
        return False
    status = _optional_text(work_order.get("status")).lower()
    if status not in {"needs_human", "changes_requested"}:
        return False
    if _optional_text(work_order.get("failure_reason")).lower() != "merge_gate_failed":
        return False
    if not _work_order_has_concrete_deliverable(work_order):
        return False
    verification_results = [
        dict(entry)
        for entry in work_order.get("verification_results", [])
        if isinstance(entry, dict) and str(entry.get("command", "")).strip()
    ]
    return bool(verification_results)
