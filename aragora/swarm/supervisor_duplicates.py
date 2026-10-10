"""Duplicate-work suppression for ``SwarmSupervisor`` work orders.

``SwarmSupervisor`` (``aragora.swarm.supervisor``) inherits these helpers: they discard a
new work order that duplicates an open developer task (same tranche lane, or same goal
with an overlapping file scope) and collapse over-decomposed work orders that all claim
the spec's file scope into one. ``_path_in_scope`` and ``_parse_iso_timestamp`` moved here
with them, and ``aragora.swarm.supervisor`` re-exports both. Import the supervisor from
``aragora.swarm.supervisor``.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aragora.nomic.pipeline_bridge import BoundedWorkOrder

if TYPE_CHECKING:
    from aragora.nomic.dev_coordination import DevCoordinationStore
    from aragora.swarm.spec import SwarmSpec

UTC = timezone.utc
# Log under the supervisor's name so existing log routing and filters keep matching.
logger = logging.getLogger("aragora.swarm.supervisor")
DEFAULT_RECEIPTLESS_DUPLICATE_STALE_SECONDS = 1800.0


def _path_in_scope(path: str, scope_pattern: str) -> bool:
    """Check if a file path falls within a scope pattern.

    Delegates to the coordination layer's proven ``_path_matches_glob`` which
    supports exact paths, directory prefixes, ``/**`` recursive globs, and
    ``PurePosixPath.match()`` for standard glob patterns like ``*.json`` or
    ``**/*.ts``.
    """
    from aragora.nomic.dev_coordination import _path_matches_glob

    clean_path = path.strip().removeprefix("./").rstrip("/")
    clean_scope = scope_pattern.strip().removeprefix("./").rstrip("/")
    if not clean_path or not clean_scope:
        return False
    return _path_matches_glob(clean_path, clean_scope)


def _parse_iso_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text or text.lower() == "none":
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class SwarmSupervisorDuplicateWorkMixin:
    """Duplicate-work suppression helpers inherited by ``SwarmSupervisor``."""

    store: DevCoordinationStore

    @staticmethod
    def _normalized_scope_signature(paths: list[str]) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in paths:
            path = str(raw).strip()
            if not path or path in seen:
                continue
            seen.add(path)
            normalized.append(path)
        return tuple(sorted(normalized))

    @staticmethod
    def _normalized_goal_signature(value: Any) -> str:
        text = str(value or "").strip()
        for paragraph in re.split(r"\n\s*\n", text):
            candidate = " ".join(paragraph.split()).strip()
            if not candidate:
                continue
            lower = candidate.lower()
            if lower.startswith(
                (
                    "## ",
                    "validation",
                    "allowed write scope",
                    "verification commands",
                    "source issue context",
                    "acceptance criteria",
                    "context",
                    "goal",
                )
            ):
                continue
            first_sentence = re.split(r"(?<=[.!?])\s+", candidate, maxsplit=1)[0]
            normalized = " ".join(first_sentence.split()).strip().lower()
            if normalized:
                return normalized
        return " ".join(text.split()).strip().lower()

    @staticmethod
    def _task_has_concrete_deliverable(task: Any) -> bool:
        metadata = getattr(task, "metadata", {}) or {}
        commit_shas = [
            str(item).strip() for item in (metadata.get("commit_shas") or []) if str(item).strip()
        ]
        pr_url = str(metadata.get("pr_url") or "").strip()
        adopted_pr = str(metadata.get("adopted_pr") or "").strip()
        return bool(getattr(task, "receipt_id", None) or commit_shas or pr_url or adopted_pr)

    def _duplicate_open_work_order_group_key(
        self,
        goal: str,
        file_scope: list[str],
        metadata: dict[str, Any] | None,
    ) -> tuple[str, str, tuple[str, ...]] | None:
        scope = self._normalized_scope_signature(file_scope)
        payload = dict(metadata or {})
        tranche_lane_id = str(payload.get("tranche_lane_id") or "").strip()
        if tranche_lane_id:
            return ("tranche_lane_id", tranche_lane_id, scope)
        goal_key = self._normalized_goal_signature(goal)
        if not goal_key:
            return None
        return ("goal", goal_key, scope)

    @staticmethod
    def _scope_signature_contains(
        container: tuple[str, ...],
        containee: tuple[str, ...],
    ) -> bool:
        if not container or not containee:
            return False
        return all(
            any(_path_in_scope(path, scope_pattern) for scope_pattern in container)
            for path in containee
        )

    @staticmethod
    def _work_order_candidate_text(goal: str, item: dict[str, Any]) -> str:
        parts = [
            str(goal or "").strip(),
            str(item.get("title", "") or "").strip(),
            str(item.get("description", "") or "").strip(),
        ]
        return " ".join(part for part in parts if part).lower()

    @staticmethod
    def _duplicate_candidate_is_current_batch_dependency(
        item: dict[str, Any],
        candidate: dict[str, Any],
    ) -> bool:
        if not candidate.get("from_current_batch"):
            return False
        dependency_ids = {
            str(dep).strip() for dep in item.get("dependency_ids", []) if str(dep).strip()
        }
        if not dependency_ids:
            return False
        for candidate_id in (
            str(candidate.get("pipeline_task_id", "")).strip(),
            str(candidate.get("work_order_id", "")).strip(),
            str(candidate.get("task_key", "")).strip(),
        ):
            if candidate_id and candidate_id in dependency_ids:
                return True
        return False

    @staticmethod
    def _duplicate_candidate_has_stale_reaped_dependency(
        work_order: dict[str, Any],
        run_work_orders: list[dict[str, Any]],
    ) -> bool:
        dependency_ids = {
            str(dep).strip() for dep in work_order.get("dependency_ids", []) if str(dep).strip()
        }
        if not dependency_ids:
            return False

        stale_failure_reasons = {"stale_lease_reaped", "expired_lease_reaped"}
        dependency_lookup: dict[str, dict[str, Any]] = {}
        for candidate in run_work_orders:
            if not isinstance(candidate, dict):
                continue
            for key in ("pipeline_task_id", "work_order_id", "task_key"):
                candidate_id = str(candidate.get(key, "")).strip()
                if candidate_id:
                    dependency_lookup[candidate_id] = candidate

        for dependency_id in dependency_ids:
            dependency = dependency_lookup.get(dependency_id)
            if not isinstance(dependency, dict):
                continue
            if str(dependency.get("status", "")).strip().lower() != "needs_human":
                continue
            failure_reason = str(dependency.get("failure_reason", "")).strip().lower()
            if failure_reason in stale_failure_reasons:
                return True
        return False

    @staticmethod
    def _duplicate_candidate_receiptless_failure_is_stale(
        work_order: dict[str, Any],
        *,
        run_record: dict[str, Any],
        stale_threshold_seconds: float = DEFAULT_RECEIPTLESS_DUPLICATE_STALE_SECONDS,
    ) -> bool:
        anchor = None
        for value in (
            work_order.get("last_observed_at"),
            work_order.get("last_progress_at"),
            work_order.get("completed_at"),
            work_order.get("dispatched_at"),
            work_order.get("leased_at"),
            work_order.get("started_at"),
            run_record.get("updated_at"),
            run_record.get("created_at"),
        ):
            anchor = _parse_iso_timestamp(value)
            if anchor is not None:
                break
        if anchor is None:
            return False
        return (datetime.now(UTC) - anchor).total_seconds() >= float(stale_threshold_seconds)

    def _duplicate_candidate_should_block(
        self,
        task: Any,
        *,
        run_cache: dict[str, dict[str, Any] | None],
    ) -> bool:
        stale_failure_reasons = {"stale_lease_reaped", "expired_lease_reaped"}
        metadata = getattr(task, "metadata", {}) or {}
        status = str(getattr(task, "status", "")).strip().lower()
        failure_reason = str(metadata.get("failure_reason") or "").strip().lower()
        if status == "needs_human" and failure_reason in stale_failure_reasons:
            return False

        run_id = str(getattr(task, "run_id", "")).strip()
        task_id = str(getattr(task, "task_id", "")).strip()
        if status != "queued" and failure_reason != "worker_exited_without_receipt":
            return True
        if not run_id or not task_id:
            return True

        record = run_cache.get(run_id)
        if record is None:
            record = self.store.get_supervisor_run(run_id)
            run_cache[run_id] = record
        if not isinstance(record, dict):
            return True

        work_order = next(
            (
                item
                for item in record.get("work_orders", [])
                if isinstance(item, dict) and str(item.get("work_order_id", "")).strip() == task_id
            ),
            None,
        )
        if not isinstance(work_order, dict):
            return True
        if status == "needs_human" and failure_reason == "worker_exited_without_receipt":
            return not self._duplicate_candidate_receiptless_failure_is_stale(
                work_order,
                run_record=record,
            )
        if status != "queued":
            return True
        if self._duplicate_candidate_has_stale_reaped_dependency(
            work_order,
            [item for item in record.get("work_orders", []) if isinstance(item, dict)],
        ):
            return False
        return True

    @staticmethod
    def _looks_like_broad_explicit_pytest_umbrella(*, source: str, text: str) -> bool:
        if source.strip() != "explicit_spec_work_order":
            return False
        if "pytest" not in text:
            return False
        return any(
            marker in text
            for marker in (
                "comprehensive pytest",
                "thorough pytest",
                "cover every",
                "internal helper",
                "helper function",
            )
        )

    @staticmethod
    def _looks_like_specific_pytest_child(text: str) -> bool:
        if "pytest" not in text:
            return False
        return any(
            marker in text
            for marker in (
                "write one pytest test",
                "one pytest test",
                "single pytest test",
            )
        )

    def _suppress_duplicate_open_work_orders(
        self,
        goal: str,
        work_orders: list[dict[str, Any]],
    ) -> None:
        try:
            self.store.rehabilitate_dependency_deferred_missing_verification_plan_work_orders()
            self.store.archive_failed_no_deliverable_work_orders(grace_period_hours=0.0)
            self.store.archive_clean_exit_no_deliverable_work_orders(grace_period_hours=0.0)
            self.store.archive_terminal_dependency_failure_work_orders()
        except Exception:  # noqa: BLE001 - store upkeep is best-effort; suppression proceeds without it
            logger.debug(
                "duplicate suppression pre-maintenance skipped",
                exc_info=True,
            )
        active_duplicate_statuses = {
            "queued",
            "leased",
            "dispatched",
            "active",
            "waiting_conflict",
            "dispatch_failed",
            "needs_human",
            "timed_out",
            "failed",
        }
        goal_key = self._normalized_goal_signature(goal)
        existing_by_group: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
        existing_overlap_candidates: list[dict[str, Any]] = []
        run_cache: dict[str, dict[str, Any] | None] = {}
        for task in self.store.list_developer_tasks(open_only=True, limit=1000):
            if str(getattr(task, "status", "")).strip().lower() not in active_duplicate_statuses:
                continue
            if self._task_has_concrete_deliverable(task):
                continue
            if not self._duplicate_candidate_should_block(task, run_cache=run_cache):
                continue
            task_goal = self._normalized_goal_signature(str(getattr(task, "goal", "") or ""))
            task_metadata = getattr(task, "metadata", {}) or {}
            task_scope = self._normalized_scope_signature(
                list(getattr(task, "allowed_paths", []) or [])
            )
            task_lane = str(task_metadata.get("tranche_lane_id") or "").strip()
            task_key = str(getattr(task, "task_key", "")).strip()
            task_title = str(getattr(task, "title", "") or "").strip()
            task_source = str(task_metadata.get("source") or "").strip()
            group_key = self._duplicate_open_work_order_group_key(
                str(getattr(task, "goal", "") or ""),
                list(getattr(task, "allowed_paths", []) or []),
                task_metadata,
            )
            if not group_key or group_key in existing_by_group:
                if task_scope and task_key and task_goal:
                    existing_overlap_candidates.append(
                        {
                            "task_key": task_key,
                            "goal_key": task_goal,
                            "lane": task_lane,
                            "scope": task_scope,
                            "source": task_source,
                            "pipeline_task_id": str(
                                getattr(task, "pipeline_task_id", "") or ""
                            ).strip(),
                            "work_order_id": str(getattr(task, "work_order_id", "") or "").strip()
                            or task_key,
                            "from_current_batch": False,
                            "text": " ".join(
                                part
                                for part in (
                                    str(getattr(task, "goal", "") or "").strip(),
                                    task_title,
                                )
                                if part
                            ).lower(),
                        }
                    )
                continue
            existing_by_group[group_key] = {
                "task_key": task_key,
                "pipeline_task_id": str(getattr(task, "pipeline_task_id", "") or "").strip(),
                "work_order_id": str(getattr(task, "work_order_id", "") or "").strip() or task_key,
                "from_current_batch": False,
            }
            if task_scope and task_key and task_goal:
                existing_overlap_candidates.append(
                    {
                        "task_key": task_key,
                        "goal_key": task_goal,
                        "lane": task_lane,
                        "scope": task_scope,
                        "source": task_source,
                        "pipeline_task_id": str(
                            getattr(task, "pipeline_task_id", "") or ""
                        ).strip(),
                        "work_order_id": str(getattr(task, "work_order_id", "") or "").strip()
                        or task_key,
                        "from_current_batch": False,
                        "text": " ".join(
                            part
                            for part in (
                                str(getattr(task, "goal", "") or "").strip(),
                                task_title,
                            )
                            if part
                        ).lower(),
                    }
                )

        if not existing_by_group and not existing_overlap_candidates:
            return

        now = datetime.now(UTC).isoformat()
        for item in work_orders:
            if str(item.get("status", "")).strip().lower() == "discarded":
                continue
            item_scope = self._normalized_scope_signature(
                [str(path) for path in item.get("file_scope", []) if str(path).strip()]
            )
            item_lane = str((item.get("metadata") or {}).get("tranche_lane_id") or "").strip()
            item_text = self._work_order_candidate_text(goal, item)
            item_is_specific_pytest_child = self._looks_like_specific_pytest_child(item_text)
            group_key = self._duplicate_open_work_order_group_key(
                goal,
                [str(path) for path in item.get("file_scope", []) if str(path).strip()],
                dict(item.get("metadata") or {}),
            )
            canonical_candidate = existing_by_group.get(group_key) if group_key else None
            canonical_task_key = (
                str(canonical_candidate["task_key"])
                if canonical_candidate
                and not self._duplicate_candidate_is_current_batch_dependency(
                    item, canonical_candidate
                )
                else None
            )
            if not canonical_task_key and item_scope:
                for existing in existing_overlap_candidates:
                    if self._duplicate_candidate_is_current_batch_dependency(item, existing):
                        continue
                    same_lane = bool(
                        item_lane and existing["lane"] and item_lane == existing["lane"]
                    )
                    same_goal = bool(goal_key and existing["goal_key"] == goal_key)
                    if (
                        item_is_specific_pytest_child
                        and item_scope == existing["scope"]
                        and self._looks_like_broad_explicit_pytest_umbrella(
                            source=str(existing["source"]),
                            text=str(existing["text"]),
                        )
                    ):
                        canonical_task_key = str(existing["task_key"])
                        break
                    if not same_lane and not same_goal:
                        continue
                    if self._scope_signature_contains(existing["scope"], item_scope) or (
                        self._scope_signature_contains(item_scope, existing["scope"])
                    ):
                        canonical_task_key = str(existing["task_key"])
                        break
            if not group_key or not canonical_task_key:
                if group_key:
                    existing_by_group.setdefault(
                        group_key,
                        {
                            "task_key": str(item.get("work_order_id", "")).strip(),
                            "pipeline_task_id": str(item.get("pipeline_task_id", "")).strip(),
                            "work_order_id": str(item.get("work_order_id", "")).strip(),
                            "from_current_batch": True,
                        },
                    )
                if item_scope and goal_key:
                    existing_overlap_candidates.append(
                        {
                            "task_key": str(item.get("work_order_id", "")).strip(),
                            "goal_key": goal_key,
                            "lane": item_lane,
                            "scope": item_scope,
                            "source": str((item.get("metadata") or {}).get("source") or ""),
                            "pipeline_task_id": str(item.get("pipeline_task_id", "")).strip(),
                            "work_order_id": str(item.get("work_order_id", "")).strip(),
                            "from_current_batch": True,
                            "text": item_text,
                        }
                    )
                continue
            metadata = dict(item.get("metadata") or {})
            metadata.update(
                {
                    "archived_due_to": "duplicate_open_work_order",
                    "archived_at": now,
                    "archive_reason": "duplicate_open_work_order",
                    "canonical_task_key": canonical_task_key,
                    "previous_status": str(item.get("status") or "queued").strip() or "queued",
                }
            )
            item["metadata"] = metadata
            item["status"] = "discarded"

    def _collapse_redundant_work_orders(
        self,
        work_orders: list[BoundedWorkOrder],
        spec: SwarmSpec,
    ) -> list[BoundedWorkOrder]:
        """Collapse decomposition noise when every lane targets the same bounded scope.

        Boss-loop issue bodies can sometimes be over-decomposed into multiple
        phase-style work orders ("CLI Changes", "Tests Changes", etc.) that all
        claim the same file scope. Those lanes cannot make independent forward
        progress because lease enforcement serializes identical scopes anyway.
        Converting them back into one bounded work order preserves the file
        contract while avoiding waiting_conflict fan-out.
        """

        if len(work_orders) <= 1:
            return work_orders

        spec_scope = self._normalized_scope_signature(list(spec.file_scope_hints))
        if not spec_scope:
            return work_orders

        order_scopes = {
            self._normalized_scope_signature(list(item.file_scope)) for item in work_orders
        }
        if order_scopes != {spec_scope}:
            return work_orders

        tests: list[str] = []
        seen_tests: set[str] = set()
        for item in work_orders:
            for test in item.expected_tests:
                normalized = str(test).strip()
                if not normalized or normalized in seen_tests:
                    continue
                seen_tests.add(normalized)
                tests.append(normalized)

        first = work_orders[0]
        collapsed = BoundedWorkOrder(
            work_order_id=first.work_order_id,
            pipeline_task_id=first.pipeline_task_id,
            title=first.title,
            description=spec.refined_goal or spec.raw_goal or first.description,
            file_scope=list(spec_scope),
            dependency_ids=[],
            success_criteria={
                **dict(first.success_criteria),
                "tests": tests or list(first.success_criteria.get("tests", [])),
            },
            expected_tests=tests or list(first.expected_tests),
            estimated_complexity=first.estimated_complexity,
            risk_level=first.risk_level,
            target_agent=first.target_agent,
            reviewer_agent=first.reviewer_agent,
            approval_required=True,
            mission_id=first.mission_id or spec.mission_id,
            stage_id=first.stage_id or spec.stage_id,
            assertion_ids=list(first.assertion_ids or spec.assertion_ids),
            roadmap_refs=list(first.roadmap_refs or spec.roadmap_refs),
            evidence_expectations=list(first.evidence_expectations or spec.evidence_expectations),
            gate_expectations=dict(first.gate_expectations or spec.gate_expectations),
            mission_context_policies=dict(
                first.mission_context_policies or spec.mission_context_policies
            ),
            metadata={
                **dict(first.metadata),
                "collapsed_redundant_work_orders": [item.work_order_id for item in work_orders],
                "source": "collapsed_decomposition",
            },
        )
        logger.info(
            "Collapsed %d redundant work orders with identical scope %s into %s",
            len(work_orders),
            list(spec_scope),
            collapsed.work_order_id,
        )
        return [collapsed]
