"""Merge-gate failure replay and reconciliation for dev-coordination work orders.

Each function takes a ``DevCoordinationStore`` as ``self``. The store methods in
``aragora.nomic.dev_coordination.core`` import them lazily from
``aragora.nomic.dev_receipts``, which re-exports every function here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Imported from its leaf module rather than through ``_dev``: mypy cannot infer
# the type of this alias when it resolves the dev_coordination import cycle.
from .dev_coordination_verification import _canonical_verification_command

if TYPE_CHECKING:
    from .dev_coordination import core as _dev
else:
    # Same routing as ``dev_receipts``: ``core`` reaches these functions through
    # function-local imports, so a runtime edge into ``core`` would make the two
    # modules mutually dependent.
    from . import dev_coordination as _dev

_backfill_work_order_blocker_metadata = _dev._backfill_work_order_blocker_metadata
_default_blocking_question_for_reason = _dev._default_blocking_question_for_reason
_docs_only_replay_commands_for_work_order = _dev._docs_only_replay_commands_for_work_order
_find_work_order = _dev._find_work_order
_mainline_missing_repo_paths_for_work_order = _dev._mainline_missing_repo_paths_for_work_order
_mainline_verification_commands_for_work_order = _dev._mainline_verification_commands_for_work_order
_merge_gate_replay_matches_task_keys = _dev._merge_gate_replay_matches_task_keys
_merge_gate_state_for_work_order = _dev._merge_gate_state_for_work_order
_missing_required_replay_commands_for_work_order = (
    _dev._missing_required_replay_commands_for_work_order
)
_narrow_pytest_replay_commands_for_work_order = _dev._narrow_pytest_replay_commands_for_work_order
_optional_text = _dev._optional_text
_targeted_replay_expected_tests_for_work_order = _dev._targeted_replay_expected_tests_for_work_order
_utcnow = _dev._utcnow
_work_order_identifier = _dev._work_order_identifier
_work_order_should_reclassify_branch_stale_merge_gate_failure = (
    _dev._work_order_should_reclassify_branch_stale_merge_gate_failure
)
_work_order_should_reclassify_branch_stale_verification_target_missing = (
    _dev._work_order_should_reclassify_branch_stale_verification_target_missing
)
_work_order_should_reclassify_deliverable_changes_requested = (
    _dev._work_order_should_reclassify_deliverable_changes_requested
)
_work_order_should_reconcile_merge_gate_failure = (
    _dev._work_order_should_reconcile_merge_gate_failure
)
_work_order_should_replay_docs_only_merge_gate_failure = (
    _dev._work_order_should_replay_docs_only_merge_gate_failure
)
_work_order_should_replay_environment_blocked_verification = (
    _dev._work_order_should_replay_environment_blocked_verification
)
_work_order_should_replay_missing_required_merge_gate_failure = (
    _dev._work_order_should_replay_missing_required_merge_gate_failure
)
_work_order_should_replay_missing_verification = _dev._work_order_should_replay_missing_verification
_work_order_should_replay_narrow_pytest_merge_gate_failure = (
    _dev._work_order_should_replay_narrow_pytest_merge_gate_failure
)
_work_order_should_replay_targeted_merge_gate_failure = (
    _dev._work_order_should_replay_targeted_merge_gate_failure
)


def _replay_merge_gate_failures(
    self,
    *,
    should_replay: Any,
    metadata_flag: str,
    prepare_commands: Any | None = None,
    merge_existing_results: bool = False,
    task_keys: list[str] | None = None,
    limit: int | None = None,
    timeout: float = 900.0,
) -> int:
    normalized_task_keys = {
        str(task_key).strip() for task_key in (task_keys or []) if str(task_key).strip()
    }
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        candidate_ids: list[tuple[str, str]] = []
        attempted = 0
        for row in rows:
            if isinstance(limit, int) and limit > 0 and attempted >= limit:
                break
            record = self._supervisor_run_from_row(row)
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                if isinstance(limit, int) and limit > 0 and attempted >= limit:
                    break
                if not _merge_gate_replay_matches_task_keys(
                    record["run_id"], item, normalized_task_keys
                ):
                    continue
                if not should_replay(item):
                    continue
                work_order_id = _work_order_identifier(item)
                if not work_order_id:
                    continue
                candidate_ids.append((record["run_id"], work_order_id))
                attempted += 1
    finally:
        conn.close()

    replayed = 0
    for run_id, work_order_id in candidate_ids:
        record = self.get_supervisor_run(run_id)
        if not record:
            continue
        item = _find_work_order(record, work_order_id)
        if item is None or not _merge_gate_replay_matches_task_keys(
            run_id, item, normalized_task_keys
        ):
            continue
        if not should_replay(item):
            continue

        commands = [
            str(command).strip()
            for command in item.get("expected_tests", [])
            if str(command).strip()
        ]
        if prepare_commands is not None:
            prepared_commands = prepare_commands(item)
            if prepared_commands is None:
                continue
            commands = [
                str(command).strip() for command in prepared_commands if str(command).strip()
            ]
        if not commands:
            continue

        worktree_path, cleanup_path = self._resolve_verification_worktree(item)
        if not worktree_path:
            continue
        try:
            verification_results = self._run_verification_commands_sync(
                worktree_path,
                commands,
                timeout=timeout,
            )
        finally:
            self._cleanup_verification_worktree(cleanup_path)
        if not verification_results:
            continue

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM supervisor_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                continue
            record = self._supervisor_run_from_row(row)
            item = _find_work_order(record, work_order_id)
            if item is None or not _merge_gate_replay_matches_task_keys(
                run_id, item, normalized_task_keys
            ):
                continue
            if not should_replay(item):
                continue
            if prepare_commands is not None and prepare_commands(item) is None:
                continue

            existing_results = [
                dict(entry)
                for entry in item.get("verification_results", [])
                if isinstance(entry, dict) and str(entry.get("command", "")).strip()
            ]
            existing_tests_run = [
                str(command).strip()
                for command in item.get("tests_run", [])
                if str(command).strip()
            ]
            effective_results = [dict(entry) for entry in verification_results]
            effective_tests_run = [
                str(entry.get("command", "")).strip()
                for entry in effective_results
                if str(entry.get("command", "")).strip()
            ]
            if merge_existing_results:
                seen_commands = {
                    _canonical_verification_command(entry.get("command", ""))
                    for entry in effective_results
                    if _canonical_verification_command(entry.get("command", ""))
                }
                for entry in existing_results:
                    canonical = _canonical_verification_command(entry.get("command", ""))
                    if canonical and canonical not in seen_commands:
                        effective_results.append(dict(entry))
                        seen_commands.add(canonical)
                seen_tests = {
                    _canonical_verification_command(command)
                    for command in effective_tests_run
                    if _canonical_verification_command(command)
                }
                for command in existing_tests_run:
                    canonical = _canonical_verification_command(command)
                    if canonical and canonical not in seen_tests:
                        effective_tests_run.append(command)
                        seen_tests.add(canonical)

            item["tests_run"] = effective_tests_run
            item["verification_results"] = [dict(entry) for entry in effective_results]
            item["merge_gate"] = _merge_gate_state_for_work_order(item)
            metadata = dict(item.get("metadata") or {})
            metadata[metadata_flag] = True
            metadata[f"{metadata_flag}_at"] = _utcnow().isoformat()
            item["metadata"] = metadata
            receipt_id = _optional_text(item.get("receipt_id"))
            if receipt_id:
                self._update_completion_receipt_verification_locked(
                    conn,
                    receipt_id=receipt_id,
                    verification_results=effective_results,
                    replayed_at=metadata[f"{metadata_flag}_at"],
                )
            if item["merge_gate"]["checks_passed"]:
                item["status"] = "completed"
                item["review_status"] = "pending_heterogeneous_review"
                item["worker_outcome"] = "completed"
                item["blockers"] = []
                for key in (
                    "failure_reason",
                    "blocking_question",
                    "blocker",
                    "dispatch_error",
                ):
                    item.pop(key, None)
            else:
                item["status"] = "needs_human"
                item["review_status"] = "changes_requested"
                item["worker_outcome"] = "merge_gate_failed"
                item["failure_reason"] = "merge_gate_failed"
                item["dispatch_error"] = (
                    item["merge_gate"]["blocked_reasons"][0]
                    if item["merge_gate"]["blocked_reasons"]
                    else "merge gate blocked"
                )
                item["blockers"] = list(item["merge_gate"]["blocked_reasons"])
                _backfill_work_order_blocker_metadata(item)
                if _work_order_should_reclassify_deliverable_changes_requested(item):
                    item["status"] = "changes_requested"

            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = _utcnow().isoformat()
            self._persist_supervisor_run(conn, record)
            conn.commit()
            replayed += 1
        finally:
            conn.close()
    return replayed


def replay_missing_verification_for_merge_gate_failures(
    self,
    *,
    task_keys: list[str] | None = None,
    limit: int | None = None,
    timeout: float = 900.0,
) -> int:
    return self._replay_merge_gate_failures(
        should_replay=_work_order_should_replay_missing_verification,
        metadata_flag="verification_replayed",
        task_keys=task_keys,
        limit=limit,
        timeout=timeout,
    )


def replay_environment_blocked_merge_gate_failures(
    self,
    *,
    task_keys: list[str] | None = None,
    limit: int | None = None,
    timeout: float = 900.0,
) -> int:
    return self._replay_merge_gate_failures(
        should_replay=_work_order_should_replay_environment_blocked_verification,
        metadata_flag="verification_environment_replayed",
        task_keys=task_keys,
        limit=limit,
        timeout=timeout,
    )


def replay_docs_only_merge_gate_failures(
    self,
    *,
    task_keys: list[str] | None = None,
    limit: int | None = None,
    timeout: float = 900.0,
) -> int:
    return self._replay_merge_gate_failures(
        should_replay=_work_order_should_replay_docs_only_merge_gate_failure,
        metadata_flag="verification_docs_replayed",
        prepare_commands=_docs_only_replay_commands_for_work_order,
        task_keys=task_keys,
        limit=limit,
        timeout=timeout,
    )


def replay_missing_required_merge_gate_failures(
    self,
    *,
    task_keys: list[str] | None = None,
    limit: int | None = None,
    timeout: float = 900.0,
) -> int:
    return self._replay_merge_gate_failures(
        should_replay=_work_order_should_replay_missing_required_merge_gate_failure,
        metadata_flag="verification_missing_required_replayed",
        prepare_commands=_missing_required_replay_commands_for_work_order,
        merge_existing_results=True,
        task_keys=task_keys,
        limit=limit,
        timeout=timeout,
    )


def replay_narrow_pytest_merge_gate_failures(
    self,
    *,
    task_keys: list[str] | None = None,
    limit: int | None = None,
    timeout: float = 900.0,
) -> int:
    return self._replay_merge_gate_failures(
        should_replay=_work_order_should_replay_narrow_pytest_merge_gate_failure,
        metadata_flag="verification_narrow_pytest_replayed",
        prepare_commands=_narrow_pytest_replay_commands_for_work_order,
        task_keys=task_keys,
        limit=limit,
        timeout=timeout,
    )


def replay_targeted_merge_gate_failures(
    self,
    *,
    task_keys: list[str] | None = None,
    limit: int | None = None,
    timeout: float = 900.0,
) -> int:
    def _prepare(item: dict[str, Any]) -> list[str] | None:
        targeted_commands = _targeted_replay_expected_tests_for_work_order(item)
        if not targeted_commands:
            return None
        previous_expected = [
            str(command).strip()
            for command in item.get("expected_tests", [])
            if str(command).strip()
        ]
        metadata = dict(item.get("metadata") or {})
        if previous_expected and not metadata.get("verification_targeted_previous_expected_tests"):
            metadata["verification_targeted_previous_expected_tests"] = list(previous_expected)
        item["metadata"] = metadata
        item["expected_tests"] = list(targeted_commands)
        success_criteria = dict(item.get("success_criteria") or {})
        success_criteria["tests"] = (
            targeted_commands[0] if len(targeted_commands) == 1 else list(targeted_commands)
        )
        item["success_criteria"] = success_criteria
        item["tests_run"] = []
        item["verification_results"] = []
        return targeted_commands

    return self._replay_merge_gate_failures(
        should_replay=_work_order_should_replay_targeted_merge_gate_failure,
        metadata_flag="verification_targeted_replayed",
        prepare_commands=_prepare,
        task_keys=task_keys,
        limit=limit,
        timeout=timeout,
    )


def reclassify_branch_stale_merge_gate_failures(
    self,
    *,
    limit: int | None = None,
    timeout: float = 900.0,
    task_keys: list[str] | None = None,
) -> int:
    requested_task_keys = {str(item).strip() for item in (task_keys or []) if str(item).strip()}

    def _task_key_for(record: dict[str, Any], item: dict[str, Any], work_order_id: str) -> str:
        metadata = item.get("metadata")
        if isinstance(metadata, dict):
            task_key = _optional_text(metadata.get("task_key"))
            if task_key:
                return task_key
        task_key = _optional_text(item.get("task_key"))
        if task_key:
            return task_key
        if record.get("run_id") and work_order_id:
            return f"{record['run_id']}:{work_order_id}"
        return ""

    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        candidate_ids: list[tuple[str, str]] = []
        attempted = 0
        for row in rows:
            if isinstance(limit, int) and limit > 0 and attempted >= limit:
                break
            record = self._supervisor_run_from_row(row)
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                if isinstance(limit, int) and limit > 0 and attempted >= limit:
                    break
                if not (
                    _work_order_should_reclassify_branch_stale_merge_gate_failure(item)
                    or _work_order_should_reclassify_branch_stale_verification_target_missing(
                        item, repo_root=self.repo_root
                    )
                ):
                    continue
                work_order_id = _work_order_identifier(item)
                if not work_order_id:
                    continue
                task_key = _task_key_for(record, item, work_order_id)
                if requested_task_keys and task_key not in requested_task_keys:
                    continue
                candidate_ids.append((record["run_id"], work_order_id))
                attempted += 1
    finally:
        conn.close()

    reclassified = 0
    for run_id, work_order_id in candidate_ids:
        record = self.get_supervisor_run(run_id)
        if not record:
            continue
        item = _find_work_order(record, work_order_id)
        is_missing_target = False
        if item is None:
            continue
        if _work_order_should_reclassify_branch_stale_merge_gate_failure(item):
            pass
        elif _work_order_should_reclassify_branch_stale_verification_target_missing(
            item, repo_root=self.repo_root
        ):
            is_missing_target = True
        else:
            continue
        task_key = _task_key_for(record, item, work_order_id)
        if requested_task_keys and task_key not in requested_task_keys:
            continue
        target_ref = _optional_text(record.get("target_branch")) or "main"
        commands = _mainline_verification_commands_for_work_order(item)
        verification_results: list[dict[str, Any]] = []
        missing_paths: list[str] = []
        if is_missing_target:
            missing_paths = _mainline_missing_repo_paths_for_work_order(
                item, repo_root=self.repo_root
            )
            if not missing_paths:
                continue
        else:
            if not commands:
                continue
            worktree_path, cleanup_path = self._resolve_verification_worktree(
                {"branch": target_ref}
            )
            if not worktree_path and target_ref != "main":
                target_ref = "main"
                worktree_path, cleanup_path = self._resolve_verification_worktree(
                    {"branch": target_ref}
                )
            if not worktree_path:
                continue
            try:
                verification_results = self._run_verification_commands_sync(
                    worktree_path,
                    commands,
                    timeout=timeout,
                )
            finally:
                self._cleanup_verification_worktree(cleanup_path)
            if not verification_results or not all(
                bool(entry.get("passed", False)) for entry in verification_results
            ):
                continue

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM supervisor_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                continue
            refreshed_record = self._supervisor_run_from_row(row)
            refreshed_item = _find_work_order(refreshed_record, work_order_id)
            refreshed_is_missing_target = False
            if refreshed_item is None:
                continue
            if _work_order_should_reclassify_branch_stale_merge_gate_failure(refreshed_item):
                pass
            elif _work_order_should_reclassify_branch_stale_verification_target_missing(
                refreshed_item, repo_root=self.repo_root
            ):
                refreshed_is_missing_target = True
            else:
                continue
            refreshed_task_key = _task_key_for(refreshed_record, refreshed_item, work_order_id)
            if requested_task_keys and refreshed_task_key not in requested_task_keys:
                continue

            checked_at = _utcnow().isoformat()
            metadata = dict(refreshed_item.get("metadata") or {})
            metadata["mainline_verification_checked_at"] = checked_at
            if refreshed_is_missing_target:
                metadata["mainline_verification_target_missing"] = True
                metadata["mainline_missing_paths"] = list(missing_paths)
                metadata["mainline_verification_commands"] = list(commands)
            else:
                metadata["mainline_verification_passed"] = True
                metadata["mainline_verification_commands"] = list(commands)
                metadata["mainline_verification_results"] = [
                    dict(entry) for entry in verification_results
                ]
            refreshed_item["metadata"] = metadata
            refreshed_item["status"] = "changes_requested"
            refreshed_item["review_status"] = "changes_requested"
            refreshed_item["worker_outcome"] = "branch_snapshot_stale"
            refreshed_item["failure_reason"] = "branch_snapshot_stale"
            refreshed_item["blocking_question"] = _default_blocking_question_for_reason(
                "branch_snapshot_stale"
            )
            if refreshed_is_missing_target:
                refreshed_item["dispatch_error"] = (
                    "branch snapshot stale: referenced verification targets no longer exist "
                    f"on {target_ref}"
                )
            else:
                refreshed_item["dispatch_error"] = (
                    f"branch snapshot stale: merge-gate verification now passes on {target_ref}"
                )
            refreshed_item["blockers"] = ["branch_snapshot_stale"]
            refreshed_item["blocker"] = {
                "reason": "branch_snapshot_stale",
                "question": refreshed_item["blocking_question"],
            }

            refreshed_record["status"] = self._derive_supervisor_run_status(
                refreshed_record["work_orders"]
            )
            refreshed_record["updated_at"] = checked_at
            self._persist_supervisor_run(conn, refreshed_record)
            conn.commit()
            reclassified += 1
        finally:
            conn.close()

    return reclassified


def reconcile_merge_gate_failed_work_orders(self) -> int:
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM supervisor_runs ORDER BY updated_at DESC").fetchall()
        reconciled = 0
        for row in rows:
            record = self._supervisor_run_from_row(row)
            changed = False
            for item in record["work_orders"]:
                if not isinstance(item, dict):
                    continue
                if not _work_order_should_reconcile_merge_gate_failure(item):
                    continue
                item["merge_gate"] = _merge_gate_state_for_work_order(item)
                metadata = dict(item.get("metadata") or {})
                metadata["merge_gate_reconciled"] = True
                metadata["merge_gate_reconciled_at"] = _utcnow().isoformat()
                item["metadata"] = metadata
                if item["merge_gate"]["checks_passed"]:
                    item["status"] = "completed"
                    item["review_status"] = "pending_heterogeneous_review"
                    item["worker_outcome"] = "completed"
                    item["blockers"] = []
                    for key in (
                        "failure_reason",
                        "blocking_question",
                        "blocker",
                        "dispatch_error",
                    ):
                        item.pop(key, None)
                else:
                    item["status"] = "needs_human"
                    item["review_status"] = "changes_requested"
                    item["worker_outcome"] = "merge_gate_failed"
                    item["failure_reason"] = "merge_gate_failed"
                    item["dispatch_error"] = (
                        item["merge_gate"]["blocked_reasons"][0]
                        if item["merge_gate"]["blocked_reasons"]
                        else "merge gate blocked"
                    )
                    item["blockers"] = list(item["merge_gate"]["blocked_reasons"])
                    _backfill_work_order_blocker_metadata(item)
                changed = True
                reconciled += 1
            if not changed:
                continue
            record["status"] = self._derive_supervisor_run_status(record["work_orders"])
            record["updated_at"] = _utcnow().isoformat()
            self._persist_supervisor_run(conn, record)
        conn.commit()
    finally:
        conn.close()
    return reconciled
