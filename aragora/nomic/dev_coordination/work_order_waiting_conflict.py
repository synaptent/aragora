"""Waiting-conflict predicates for dev-coordination work orders.

Decides when a work order parked in ``waiting_conflict`` is superseded and can
be archived, when its scope can be narrowed from explicit or docs-only path
hints so it can be rehabilitated, how duplicate and containing work orders are
ranked, and which sibling work orders still block it. Split out of
:mod:`aragora.nomic.dev_coordination.core`, which re-imports every name here,
so ``core._blocking_waiting_conflict_siblings``, the package-level attribute
fallthrough and the ``aragora.nomic.dev_receipts`` aliases keep resolving to
these objects.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from aragora.docs_only import (
    canonical_docs_container_scope,
    infer_docs_safe_hints,
    is_docs_safe_path,
    is_docs_safe_top_level_file,
)
from aragora.nomic.dev_coordination.models import LeaseStatus
from aragora.nomic.dev_coordination.utils import _normalize_claim, _parse_dt, _utcnow
from aragora.nomic.dev_coordination.work_order_overlap import (
    _canonical_scope_pattern,
    _collapse_scope_patterns,
    _developer_task_updated_at,
    _optional_text,
    _path_matches_glob,
    _work_order_has_concrete_deliverable,
    _work_order_scope_contains,
    _work_order_scope_patterns,
    _work_orders_overlap_by_scope,
)


def _work_order_identifier(work_order: dict[str, Any]) -> str:
    return (
        str(work_order.get("work_order_id", "")).strip()
        or str(work_order.get("task_id", "")).strip()
        or str(work_order.get("id", "")).strip()
    )


def _work_order_should_archive_superseded_waiting_conflict(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    cutoff: datetime,
    lease_status: str | None,
) -> bool:
    if _optional_text(work_order.get("status")).lower() != "waiting_conflict":
        return False
    if _optional_text(lease_status).lower() == LeaseStatus.ACTIVE.value:
        return False
    metadata = work_order.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    if _optional_text(work_order.get("receipt_id")) or _work_order_has_concrete_deliverable(
        work_order
    ):
        return False
    if not _work_order_scope_patterns(work_order):
        return False
    updated_at = _parse_dt(_waiting_conflict_staleness_anchor(work_order, run))
    return updated_at <= cutoff


def _work_order_should_rehabilitate_narrowed_waiting_conflict(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    cutoff: datetime,
    lease_status: str | None,
) -> bool:
    if not _work_order_should_archive_superseded_waiting_conflict(
        work_order,
        run=run,
        cutoff=cutoff,
        lease_status=lease_status,
    ):
        return False
    return bool(
        _narrow_waiting_conflict_scope_from_explicit_paths(
            work_order,
            run=run,
            repo_root=None,
        )
    )


def _waiting_conflict_staleness_anchor(work_order: dict[str, Any], run: dict[str, Any]) -> str:
    for value in (
        *(
            work_order.get(key)
            for key in (
                "last_observed_at",
                "last_progress_at",
                "completed_at",
                "dispatched_at",
                "leased_at",
                "started_at",
            )
        ),
        run.get("created_at"),
        run.get("updated_at"),
        _utcnow().isoformat(),
    ):
        text = str(value or "").strip()
        if text and text.lower() != "none":
            return text
    return _utcnow().isoformat()


def _duplicate_branch_deliverable_priority(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> tuple[int, int, int, str]:
    commit_shas = [
        str(item).strip() for item in work_order.get("commit_shas", []) if str(item).strip()
    ]
    return (
        1 if _optional_text(work_order.get("receipt_id")) else 0,
        len(commit_shas),
        1 if _optional_text(work_order.get("head_sha")) else 0,
        _developer_task_updated_at(work_order, run),
    )


def _duplicate_waiting_conflict_priority(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> tuple[int, str, str]:
    return (
        -len(_work_order_scope_patterns(work_order)),
        _waiting_conflict_staleness_anchor(work_order, run),
        _optional_text(work_order.get("work_order_id"), work_order.get("task_id")),
    )


def _containing_waiting_conflict_priority(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> tuple[int, int, str]:
    patterns = _work_order_scope_patterns(work_order)
    return (
        len(patterns),
        -sum(len(pattern) for pattern in patterns),
        _optional_text(work_order.get("work_order_id"), work_order.get("task_id")),
    )


def _is_concrete_repo_path_hint(path: str, *, repo_root: Path | None) -> bool:
    clean = _normalize_claim(path)
    if not clean or any(token in clean for token in ("*", "?", "[", "]", "{", "}")):
        return False
    name = clean.rsplit("/", 1)[-1]
    if repo_root is not None:
        candidate = (repo_root / clean).resolve()
        try:
            candidate.relative_to(repo_root.resolve())
        except ValueError:
            return False
        if candidate.is_file():
            return True
    return "." in name


def _waiting_conflict_inference_text(work_order: dict[str, Any], run: dict[str, Any]) -> str:
    spec = run.get("spec")
    metadata = work_order.get("metadata")
    spec_acceptance = spec.get("acceptance_criteria") if isinstance(spec, dict) else []
    spec_constraints = spec.get("constraints") if isinstance(spec, dict) else []
    metadata_acceptance = metadata.get("acceptance_criteria") if isinstance(metadata, dict) else []
    metadata_constraints = metadata.get("constraints") if isinstance(metadata, dict) else []
    parts = [
        run.get("goal"),
        spec.get("raw_goal") if isinstance(spec, dict) else None,
        spec.get("refined_goal") if isinstance(spec, dict) else None,
        work_order.get("title"),
        work_order.get("description"),
        metadata.get("description") if isinstance(metadata, dict) else None,
    ]
    if isinstance(spec_acceptance, list):
        parts.extend(spec_acceptance)
    if isinstance(spec_constraints, list):
        parts.extend(spec_constraints)
    if isinstance(metadata_acceptance, list):
        parts.extend(metadata_acceptance)
    if isinstance(metadata_constraints, list):
        parts.extend(metadata_constraints)
    return " ".join(str(part).strip() for part in parts if str(part or "").strip())


def _explicit_scope_paths_for_waiting_conflict(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    repo_root: Path | None,
) -> list[str]:
    from aragora.swarm.spec import SwarmSpec

    original_scope = [
        _canonical_scope_pattern(str(path))
        for path in work_order.get("file_scope", []) or []
        if _canonical_scope_pattern(str(path))
    ]
    if not original_scope:
        return []
    explicit_paths: list[str] = []
    for path in SwarmSpec.infer_file_scope_hints(_waiting_conflict_inference_text(work_order, run)):
        clean = _normalize_claim(path)
        if not _is_concrete_repo_path_hint(clean, repo_root=repo_root):
            continue
        if not any(_path_matches_glob(clean, scope) for scope in original_scope):
            continue
        if clean not in explicit_paths:
            explicit_paths.append(clean)
    return explicit_paths


def _docs_only_scope_hints_for_waiting_conflict(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
) -> list[str]:
    metadata = work_order.get("metadata") or {}
    constraints = metadata.get("constraints") if isinstance(metadata, dict) else []
    if not isinstance(constraints, list) or not any(
        "documentation only" in str(item).strip().lower() for item in constraints
    ):
        spec = run.get("spec")
        spec_constraints = spec.get("constraints") if isinstance(spec, dict) else []
        if not isinstance(spec_constraints, list) or not any(
            "documentation only" in str(item).strip().lower() for item in spec_constraints
        ):
            return []

    original_scope = [
        _canonical_scope_pattern(str(path))
        for path in work_order.get("file_scope", []) or []
        if _canonical_scope_pattern(str(path))
    ]
    if not original_scope:
        return []

    def _scope_supports_docs_only_hint(path: str) -> bool:
        if any(
            scope == path or path.startswith(f"{scope}/") or scope.startswith(f"{path}/")
            for scope in original_scope
        ):
            return True
        if not is_docs_safe_top_level_file(path):
            return False
        return any(canonical_docs_container_scope(scope) == "docs" for scope in original_scope)

    doc_hints: list[str] = []
    for path in infer_docs_safe_hints(_waiting_conflict_inference_text(work_order, run)):
        clean = _canonical_scope_pattern(path)
        if _scope_supports_docs_only_hint(clean):
            doc_hints.append(clean)
    if any(
        is_docs_safe_path(hint) and canonical_docs_container_scope(hint) is None
        for hint in doc_hints
    ):
        doc_hints = [hint for hint in doc_hints if canonical_docs_container_scope(hint) is None]
    collapsed = _collapse_scope_patterns(doc_hints)
    if collapsed:
        return collapsed
    return list(
        dict.fromkeys(
            scope
            for scope in (canonical_docs_container_scope(path) for path in original_scope)
            if scope is not None
        )
    )


def _narrow_waiting_conflict_scope_from_explicit_paths(
    work_order: dict[str, Any],
    *,
    run: dict[str, Any],
    repo_root: Path | None,
) -> list[str]:
    original_scope = [
        _canonical_scope_pattern(str(path))
        for path in work_order.get("file_scope", []) or []
        if _canonical_scope_pattern(str(path))
    ]
    if not original_scope:
        return []
    explicit_paths = _explicit_scope_paths_for_waiting_conflict(
        work_order,
        run=run,
        repo_root=repo_root,
    )
    if explicit_paths:
        narrowed_scope: list[str] = []
        replaced = False
        for scope in original_scope:
            contains_explicit = any(_path_matches_glob(path, scope) for path in explicit_paths)
            if (
                contains_explicit
                and scope not in explicit_paths
                and not _is_concrete_repo_path_hint(
                    scope,
                    repo_root=repo_root,
                )
            ):
                replaced = True
                continue
            narrowed_scope.append(scope)
        if replaced:
            return _collapse_scope_patterns(narrowed_scope + explicit_paths)

    docs_only_scope = _docs_only_scope_hints_for_waiting_conflict(work_order, run=run)
    if docs_only_scope and tuple(docs_only_scope) != tuple(original_scope):
        return docs_only_scope
    return []


def _waiting_conflict_sibling_can_be_ignored(
    candidate: dict[str, Any],
    sibling: dict[str, Any],
) -> bool:
    if _optional_text(sibling.get("status")).lower() != "waiting_conflict":
        return False
    metadata = sibling.get("metadata")
    if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
        return False
    if _optional_text(sibling.get("receipt_id")) or _work_order_has_concrete_deliverable(sibling):
        return False
    return _work_order_scope_contains(sibling, candidate) and not _work_order_scope_contains(
        candidate,
        sibling,
    )


def _blocking_waiting_conflict_siblings(
    candidate: dict[str, Any],
    *,
    run: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    run_id = _optional_text(run.get("run_id"))
    work_order_id = _work_order_identifier(candidate)
    conflicts: list[dict[str, Any]] = []
    for sibling_record in records:
        sibling_run_id = _optional_text(sibling_record.get("run_id"))
        for sibling in sibling_record.get("work_orders", []):
            if not isinstance(sibling, dict):
                continue
            if sibling is candidate and sibling_run_id == run_id:
                continue
            if (
                work_order_id
                and sibling_run_id == run_id
                and _work_order_identifier(sibling) == work_order_id
            ):
                continue
            status = _optional_text(sibling.get("status")).lower()
            if status in {"discarded", "superseded", "merged"}:
                continue
            metadata = sibling.get("metadata")
            if isinstance(metadata, dict) and _optional_text(metadata.get("archived_due_to")):
                continue
            if not _work_orders_overlap_by_scope(candidate, sibling):
                continue
            if _waiting_conflict_sibling_can_be_ignored(candidate, sibling):
                continue
            conflicts.append(
                {
                    "source": "work_order",
                    "run_id": sibling_run_id or None,
                    "work_order_id": _work_order_identifier(sibling) or None,
                    "status": status or None,
                    "title": _optional_text(sibling.get("title")) or None,
                    "allowed_globs": _work_order_scope_patterns(sibling),
                }
            )
    return conflicts
