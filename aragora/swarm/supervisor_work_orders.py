"""Work-order scope helpers and explicit-spec work orders for ``SwarmSupervisor``.

The module-level helpers backfill and narrow a work order's file scope (explicit spec
paths, docs-only scopes) and recognise non-actionable or umbrella explicit-spec items.
``SwarmSupervisor`` (``aragora.swarm.supervisor``) inherits the mixin, which turns a spec's
explicit work orders into bounded work orders with default tests and a risk level.
``aragora.swarm.supervisor`` re-exports every module-level name here. Import the
supervisor from ``aragora.swarm.supervisor``.
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.docs_only import (
    canonical_docs_container_scope,
    infer_docs_safe_hints,
    is_docs_safe_path,
    is_docs_safe_top_level_file,
)
from aragora.nomic.approval import ApprovalLevel, ApprovalPolicy
from aragora.nomic.pipeline_bridge import BoundedWorkOrder
from aragora.swarm.spec import SwarmSpec
from aragora.swarm.supervisor_duplicates import _path_in_scope

# Log under the supervisor's name so existing log routing and filters keep matching.
logger = logging.getLogger("aragora.swarm.supervisor")

_TRUTHY_BOOL_STRINGS = {"1", "true", "yes", "y", "on"}
_FALSY_BOOL_STRINGS = {"0", "false", "no", "n", "off"}


def _is_concrete_repo_path(path: str) -> bool:
    return SwarmSpec.is_concrete_repo_path_hint(path)


def _strict_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUTHY_BOOL_STRINGS:
            return True
        if normalized in _FALSY_BOOL_STRINGS:
            return False
    return default


def _docs_only_scope_supports_hint(path: str, original_scope: list[str]) -> bool:
    if any(_path_in_scope(path, scope) or _path_in_scope(scope, path) for scope in original_scope):
        return True
    if not is_docs_safe_top_level_file(path):
        return False
    return any(canonical_docs_container_scope(scope) == "docs" for scope in original_scope)


def _narrow_scope_to_explicit_paths(
    item: BoundedWorkOrder,
    spec: SwarmSpec,
) -> BoundedWorkOrder:
    """Replace broad container scopes with explicit file paths named in task text."""
    if not item.file_scope:
        return item
    inference_text = " ".join(
        filter(
            None,
            [
                spec.refined_goal or "",
                spec.raw_goal or "",
                item.title or "",
                item.description or "",
            ],
        )
    )
    explicit_paths = [
        path
        for path in SwarmSpec.infer_file_scope_hints(inference_text)
        if _is_concrete_repo_path(path)
    ]
    if not explicit_paths:
        return item

    original_scope = [str(path).strip() for path in item.file_scope if str(path).strip()]
    if not original_scope:
        return item

    narrowed_scope: list[str] = []
    replaced = False
    for scope in original_scope:
        contains_explicit = any(_path_in_scope(path, scope) for path in explicit_paths)
        if contains_explicit and scope not in explicit_paths and not _is_concrete_repo_path(scope):
            replaced = True
            continue
        narrowed_scope.append(scope)
    if not replaced:
        return item

    item.file_scope = list(dict.fromkeys(narrowed_scope + explicit_paths))
    logger.info(
        "Narrowed broad file_scope on work order %s using explicit path hints: %s -> %s",
        item.work_order_id,
        original_scope,
        item.file_scope,
    )
    return item


def _narrow_docs_only_scope(
    item: BoundedWorkOrder,
    spec: SwarmSpec,
) -> BoundedWorkOrder:
    constraints = [str(value).strip() for value in spec.constraints if str(value).strip()]
    if not any("documentation only" in value.lower() for value in constraints):
        return item

    original_scope = [str(path).strip() for path in item.file_scope if str(path).strip()]
    if not original_scope:
        return item

    inference_text = " ".join(
        filter(
            None,
            [
                spec.refined_goal or "",
                spec.raw_goal or "",
                item.title or "",
                item.description or "",
                *list(spec.acceptance_criteria),
                *constraints,
            ],
        )
    )
    doc_hints: list[str] = []
    for path in infer_docs_safe_hints(inference_text):
        clean = path.strip().removeprefix("./").rstrip("/")
        if _docs_only_scope_supports_hint(clean, original_scope):
            doc_hints.append(clean)
    if any(
        is_docs_safe_path(hint) and canonical_docs_container_scope(hint) is None
        for hint in doc_hints
    ):
        doc_hints = [hint for hint in doc_hints if canonical_docs_container_scope(hint) is None]
    narrowed_scope = list(dict.fromkeys(doc_hints))
    if not narrowed_scope:
        narrowed_scope = list(
            dict.fromkeys(
                scope
                for scope in (canonical_docs_container_scope(path) for path in original_scope)
                if scope is not None
            )
        )
    if not narrowed_scope or tuple(narrowed_scope) == tuple(original_scope):
        return item

    item.file_scope = narrowed_scope
    logger.info(
        "Narrowed docs-only file_scope on work order %s: %s -> %s",
        item.work_order_id,
        original_scope,
        item.file_scope,
    )
    return item


_NON_ACTIONABLE_EXPLICIT_SPEC_TITLES = {
    "validation changes",
    "acceptance criteria changes",
    "stop conditions changes",
    "scope changes",
    "goal changes",
    "context changes",
    "source issue context changes",
}


def _looks_like_non_actionable_explicit_spec_work_order(
    item: BoundedWorkOrder,
    spec: SwarmSpec,
) -> bool:
    title = " ".join(str(item.title or "").strip().lower().split())
    description = " ".join(str(item.description or "").strip().lower().split())
    if title not in _NON_ACTIONABLE_EXPLICIT_SPEC_TITLES and not description.startswith("## "):
        return False
    if any(
        _is_concrete_repo_path(path)
        for path in (
            *SwarmSpec.infer_file_scope_hints(item.title or ""),
            *SwarmSpec.infer_file_scope_hints(item.description or ""),
        )
    ):
        return False
    expected_tests = [str(test).strip() for test in item.expected_tests if str(test).strip()]
    if expected_tests:
        return False
    success_tests = item.success_criteria.get("tests")
    if isinstance(success_tests, str) and success_tests.strip():
        return False
    if isinstance(success_tests, list) and any(str(test).strip() for test in success_tests):
        return False
    scope_key = {path.strip() for path in item.file_scope if path.strip()}
    spec_scope = {path.strip() for path in spec.file_scope_hints if path.strip()}
    if scope_key and spec_scope and scope_key != spec_scope:
        return False
    return True


def _looks_like_umbrella_explicit_spec_work_order(
    item: BoundedWorkOrder,
    spec: SwarmSpec,
    siblings: list[BoundedWorkOrder],
) -> bool:
    normalized_title = " ".join(str(item.title or "").strip().lower().split())
    normalized_description = " ".join(str(item.description or "").strip().lower().split())
    normalized_goals = {
        " ".join(str(value or "").strip().lower().split())
        for value in (spec.refined_goal, spec.raw_goal)
        if str(value or "").strip()
    }
    if not normalized_goals:
        return False
    if normalized_title not in normalized_goals and normalized_description not in normalized_goals:
        return False
    item_scope = {path.strip() for path in item.file_scope if path.strip()}
    for sibling in siblings:
        if sibling is item:
            continue
        sibling_scope = {path.strip() for path in sibling.file_scope if path.strip()}
        if item_scope != sibling_scope:
            continue
        sibling_title = " ".join(str(sibling.title or "").strip().lower().split())
        if sibling_title and sibling_title != normalized_title:
            return True
    return False


def _ensure_work_order_scope(
    item: BoundedWorkOrder,
    spec: SwarmSpec,
) -> BoundedWorkOrder:
    """Ensure a work order has non-empty file_scope through a 3-tier fallback.

    1. If the work order already has ``file_scope`` entries, merge in spec hints
       (preserving deduplication) so the worker can touch any file the project
       declares.
    2. If the work order has empty ``file_scope`` but the spec carries
       ``file_scope_hints``, backfill them directly.
    3. If both are empty, attempt keyword-based inference from the work order
       title and description via ``SwarmSpec.infer_file_scope_hints()``.

    A warning is logged when scope remains empty after all attempts — this is
    advisory, not blocking, to maintain backward compatibility.

    Returns the (mutated) work order for convenience.
    """
    spec_hints = list(spec.file_scope_hints) if spec.file_scope_hints else []

    if item.file_scope and spec_hints:
        # Merge: keep work order scope, append any new spec hints
        merged = list(dict.fromkeys(item.file_scope + spec_hints))
        if set(merged) != set(item.file_scope):
            logger.info(
                "Merged spec hints into work order %s file_scope: %s -> %s",
                item.work_order_id,
                item.file_scope,
                merged,
            )
        item.file_scope = merged
    elif not item.file_scope and spec_hints:
        # Backfill from spec hints
        item.file_scope = list(spec_hints)
        logger.info(
            "Backfilled empty file_scope on work order %s from spec hints: %s",
            item.work_order_id,
            spec_hints,
        )
    elif not item.file_scope and not spec_hints:
        # Last resort: infer from task title + description
        inference_text = " ".join(filter(None, [item.title or "", item.description or ""]))
        inferred = SwarmSpec.infer_file_scope_hints(inference_text)
        if inferred:
            item.file_scope = inferred
            logger.info(
                "Inferred file_scope on work order %s from title/description: %s",
                item.work_order_id,
                inferred,
            )
        else:
            logger.warning(
                "Work order %s has empty file_scope after all inference attempts "
                "(spec hints empty, keyword inference found nothing). "
                "Scope enforcement will be open for this work order.",
                item.work_order_id,
            )

    item = _narrow_scope_to_explicit_paths(item, spec)
    return _narrow_docs_only_scope(item, spec)


class SwarmSupervisorWorkOrderMixin:
    """Explicit-spec work-order construction inherited by ``SwarmSupervisor``."""

    approval_policy: ApprovalPolicy

    def _explicit_work_orders_from_spec(self, spec: SwarmSpec) -> list[BoundedWorkOrder]:
        if not spec.work_orders:
            return []

        work_orders: list[BoundedWorkOrder] = []
        pipeline_id_by_work_order: dict[str, str] = {}
        normalized_payloads = [
            dict(payload) for payload in spec.work_orders if isinstance(payload, dict)
        ]
        explicit_ids: list[str] = []

        for index, payload in enumerate(normalized_payloads, start=1):
            work_order_id = str(payload.get("work_order_id", "")).strip() or f"work-{index}"
            explicit_ids.append(work_order_id)
            pipeline_id_by_work_order[work_order_id] = (
                str(payload.get("pipeline_task_id", "")).strip() or f"task-{index}"
            )

        for index, payload in enumerate(normalized_payloads, start=1):
            work_order_id = explicit_ids[index - 1]
            pipeline_task_id = pipeline_id_by_work_order[work_order_id]
            target_agent = str(payload.get("target_agent", "")).strip()
            reviewer_agent = str(payload.get("reviewer_agent", "")).strip()
            if not target_agent:
                target_agent = "codex" if (index - 1) % 2 == 0 else "claude"
            if not reviewer_agent:
                reviewer_agent = "claude" if target_agent == "codex" else "codex"

            success_criteria = dict(payload.get("success_criteria") or {})
            expected_tests = [
                str(item).strip() for item in payload.get("expected_tests", []) if str(item).strip()
            ]
            if expected_tests and "tests" not in success_criteria:
                success_criteria["tests"] = list(expected_tests)

            estimated_complexity = (
                str(payload.get("estimated_complexity", "medium")).strip() or "medium"
            )
            risk_level = str(payload.get("risk_level", "")).strip() or self._risk_level_for_scope(
                [str(item) for item in payload.get("file_scope", []) if str(item).strip()]
            )

            dependency_ids = [
                str(dep).strip() for dep in payload.get("dependency_ids", []) if str(dep).strip()
            ]
            if not dependency_ids:
                dependency_ids = [
                    pipeline_id_by_work_order.get(str(dep).strip(), str(dep).strip())
                    for dep in payload.get("dependencies", [])
                    if str(dep).strip()
                ]

            work_orders.append(
                BoundedWorkOrder(
                    work_order_id=work_order_id,
                    pipeline_task_id=pipeline_task_id,
                    title=str(payload.get("title", "")).strip() or work_order_id,
                    description=str(payload.get("description", "")).strip()
                    or str(payload.get("title", "")).strip()
                    or spec.refined_goal
                    or spec.raw_goal,
                    file_scope=[
                        normalized
                        for item in payload.get("file_scope", [])
                        if (normalized := SwarmSpec.sanitize_file_scope_entry(item))
                    ],
                    dependency_ids=dependency_ids,
                    success_criteria=success_criteria,
                    expected_tests=expected_tests,
                    estimated_complexity=estimated_complexity,
                    risk_level=risk_level,
                    target_agent=target_agent,
                    reviewer_agent=reviewer_agent,
                    approval_required=_coerce_bool(
                        payload.get("approval_required"),
                        default=True,
                    ),
                    mission_id=str(payload.get("mission_id", "")).strip() or spec.mission_id,
                    stage_id=str(payload.get("stage_id", "")).strip() or spec.stage_id,
                    assertion_ids=[
                        str(item).strip()
                        for item in payload.get("assertion_ids", [])
                        if str(item).strip()
                    ]
                    or list(spec.assertion_ids),
                    roadmap_refs=[
                        str(item).strip()
                        for item in payload.get("roadmap_refs", [])
                        if str(item).strip()
                    ]
                    or list(spec.roadmap_refs),
                    evidence_expectations=[
                        str(item).strip()
                        for item in payload.get("evidence_expectations", [])
                        if str(item).strip()
                    ]
                    or list(spec.evidence_expectations),
                    gate_expectations=dict(payload.get("gate_expectations") or {})
                    or dict(spec.gate_expectations),
                    mission_context_policies=dict(payload.get("mission_context_policies") or {})
                    or dict(spec.mission_context_policies),
                    metadata={
                        **dict(payload.get("metadata") or {}),
                        "source": "explicit_spec_work_order",
                    },
                )
            )

        # Merge spec.file_scope_hints into explicit work orders so scope
        # enforcement is never bypassed when the upstream planner leaves
        # file_scope empty on individual work orders (fixes #884).
        spec_hints = list(spec.file_scope_hints) if spec.file_scope_hints else []
        for item in work_orders:
            if spec_hints:
                if not item.file_scope:
                    item.file_scope = list(spec_hints)
                    logger.info(
                        "Backfilled empty file_scope on explicit work order %s from spec hints: %s",
                        item.work_order_id,
                        spec_hints,
                    )
                else:
                    merged = list(dict.fromkeys(item.file_scope + list(spec_hints)))
                    if set(merged) != set(item.file_scope):
                        logger.info(
                            "Merged spec hints into explicit work order %s file_scope: %s -> %s",
                            item.work_order_id,
                            item.file_scope,
                            merged,
                        )
                    item.file_scope = merged
            _narrow_scope_to_explicit_paths(item, spec)
            item.expected_tests = self._default_tests(item, spec)
            item.risk_level = str(item.risk_level).strip() or self._risk_level_for_scope(
                item.file_scope
            )
            item.metadata = {
                **dict(item.metadata),
                "acceptance_criteria": list(spec.acceptance_criteria),
                "constraints": list(spec.constraints),
            }

        filtered_work_orders = [
            item
            for item in work_orders
            if not _looks_like_non_actionable_explicit_spec_work_order(item, spec)
        ]
        filtered_work_orders = [
            item
            for item in filtered_work_orders
            if not _looks_like_umbrella_explicit_spec_work_order(item, spec, filtered_work_orders)
        ]
        if filtered_work_orders:
            dropped = len(work_orders) - len(filtered_work_orders)
            if dropped:
                logger.info(
                    "Dropped %d non-actionable explicit spec work orders from %d total payloads",
                    dropped,
                    len(work_orders),
                )
            work_orders = filtered_work_orders

        return work_orders

    @staticmethod
    def _tests_from_acceptance(acceptance_criteria: list[str]) -> list[str]:
        tests: list[str] = []
        for item in acceptance_criteria:
            text = str(item).strip()
            if text.startswith("python -m pytest") or text.startswith("pytest"):
                tests.append(text)
        return tests

    def _default_tests(self, work_order: BoundedWorkOrder, spec: SwarmSpec) -> list[str]:
        tests = [str(item) for item in work_order.expected_tests if str(item).strip()]
        if tests:
            return tests
        for path in work_order.file_scope:
            if path.startswith("tests/") and path.endswith(".py"):
                tests.append(f"python -m pytest {path} -q")
        if tests:
            return tests
        return self._tests_from_acceptance(spec.acceptance_criteria)

    def _risk_level_for_scope(self, file_scope: list[str]) -> str:
        if not file_scope:
            return "review"
        level = ApprovalLevel.INFO
        for path in file_scope:
            next_level = self.approval_policy.get_approval_level(path)
            if next_level == ApprovalLevel.CRITICAL:
                return "critical"
            if next_level == ApprovalLevel.REVIEW:
                level = ApprovalLevel.REVIEW
        return "review" if level == ApprovalLevel.REVIEW else "info"
