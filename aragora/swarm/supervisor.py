"""Supervisor-driven Codex/Claude swarm orchestration.

Builds bounded work orders from a SwarmSpec, provisions managed worktrees for
Codex/Claude execution targets, claims bounded leases, and persists a
SupervisorRun in the existing development coordination store.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from aragora.nomic.approval import ApprovalLevel, ApprovalPolicy
from aragora.nomic.dev_coordination import (
    DevCoordinationStore,
    FileScopeViolationError,
    LeaseConflictError,
    LeaseStatus,
)
from aragora.nomic.pipeline_bridge import BoundedWorkOrder, NomicPipelineBridge
from aragora.nomic.task_decomposer import SubTask, TaskDecomposer
from aragora.swarm.spec import SwarmSpec
from aragora.swarm.worker_launcher import WorkerLauncher, WorkerProcess
from aragora.worktree.lifecycle import WorktreeLifecycleService

UTC = timezone.utc


class SupervisorRunStatus(str, Enum):
    """Lifecycle state for a supervised swarm run."""

    PLANNED = "planned"
    ACTIVE = "active"
    NEEDS_HUMAN = "needs_human"
    COMPLETED = "completed"


@dataclass(slots=True)
class SwarmApprovalPolicy:
    """Explicit human-gating policy for supervised swarm runs."""

    require_merge_approval: bool = True
    require_external_action_approval: bool = True
    protected_patterns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "require_merge_approval": self.require_merge_approval,
            "require_external_action_approval": self.require_external_action_approval,
            "protected_patterns": list(self.protected_patterns),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SwarmApprovalPolicy:
        payload = dict(data or {})
        return cls(
            require_merge_approval=bool(payload.get("require_merge_approval", True)),
            require_external_action_approval=bool(
                payload.get("require_external_action_approval", True)
            ),
            protected_patterns=[
                str(item) for item in payload.get("protected_patterns", []) if str(item).strip()
            ],
        )


@dataclass(slots=True)
class SupervisorRun:
    """Top-level artifact for one supervised swarm execution."""

    run_id: str
    goal: str
    target_branch: str
    status: str
    supervisor_agents: dict[str, Any]
    approval_policy: SwarmApprovalPolicy
    spec: SwarmSpec
    work_orders: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "goal": self.goal,
            "target_branch": self.target_branch,
            "status": self.status,
            "supervisor_agents": dict(self.supervisor_agents),
            "approval_policy": self.approval_policy.to_dict(),
            "spec": self.spec.to_dict(),
            "work_orders": [dict(item) for item in self.work_orders],
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> SupervisorRun:
        return cls(
            run_id=str(record.get("run_id", "")),
            goal=str(record.get("goal", "")),
            target_branch=str(record.get("target_branch", "main")),
            status=str(record.get("status", SupervisorRunStatus.PLANNED.value)),
            supervisor_agents=dict(record.get("supervisor_agents") or {}),
            approval_policy=SwarmApprovalPolicy.from_dict(record.get("approval_policy")),
            spec=SwarmSpec.from_dict(dict(record.get("spec") or {})),
            work_orders=[dict(item) for item in record.get("work_orders", [])],
            metadata=dict(record.get("metadata") or {}),
            created_at=str(record.get("created_at", datetime.now(UTC).isoformat())),
            updated_at=str(record.get("updated_at", datetime.now(UTC).isoformat())),
        )


class SwarmSupervisor:
    """Coordinate a bounded Codex/Claude worker pool using existing primitives."""

    def __init__(
        self,
        repo_root: Path | None = None,
        *,
        store: DevCoordinationStore | None = None,
        lifecycle: WorktreeLifecycleService | None = None,
        bridge: NomicPipelineBridge | None = None,
        decomposer: TaskDecomposer | None = None,
        approval_policy: ApprovalPolicy | None = None,
        launcher: WorkerLauncher | None = None,
    ) -> None:
        self.repo_root = (repo_root or Path.cwd()).resolve()
        self.store = store or DevCoordinationStore(repo_root=self.repo_root)
        self.lifecycle = lifecycle or WorktreeLifecycleService(repo_root=self.repo_root)
        self.bridge = bridge or NomicPipelineBridge(repo_path=self.repo_root)
        self.decomposer = decomposer or TaskDecomposer()
        self.approval_policy = approval_policy or ApprovalPolicy()
        self.launcher = launcher or WorkerLauncher()

    def start_run(
        self,
        *,
        spec: SwarmSpec,
        target_branch: str = "main",
        max_concurrency: int = 8,
        managed_dir_pattern: str = ".worktrees/{agent}-auto",
        approval_policy: SwarmApprovalPolicy | None = None,
        refresh_scaling: bool = True,
    ) -> SupervisorRun:
        goal = spec.refined_goal or spec.raw_goal
        policy = approval_policy or SwarmApprovalPolicy()
        work_orders = [item.to_dict() for item in self._build_supervised_work_orders(spec)]
        for item in work_orders:
            item.setdefault("status", "queued")
            item.setdefault("lease_id", None)
            item.setdefault("receipt_id", None)
            item.setdefault("review_status", "pending")

        record = self.store.create_supervisor_run(
            goal=goal,
            target_branch=target_branch,
            supervisor_agents={"planner": "codex", "judge": "claude"},
            approval_policy=policy.to_dict(),
            spec=spec.to_dict(),
            work_orders=work_orders,
            status=SupervisorRunStatus.PLANNED.value,
            metadata={
                "max_concurrency": min(max(1, int(max_concurrency)), 8),
                "managed_dir_pattern": managed_dir_pattern,
            },
        )
        run = SupervisorRun.from_record(record)
        if refresh_scaling:
            return self.refresh_run(run.run_id)
        return run

    def refresh_run(self, run_id: str) -> SupervisorRun:
        record = self.store.get_supervisor_run(run_id)
        if record is None:
            raise KeyError(f"Unknown supervisor run: {run_id}")

        max_concurrency = min(max(1, int(record.get("metadata", {}).get("max_concurrency", 8))), 8)
        managed_dir_pattern = str(
            record.get("metadata", {}).get("managed_dir_pattern", ".worktrees/{agent}-auto")
        )
        work_orders = [dict(item) for item in record.get("work_orders", [])]
        active_count = sum(1 for item in work_orders if str(item.get("status", "")) == "leased")

        if active_count < max_concurrency:
            for item in work_orders:
                if active_count >= max_concurrency:
                    break
                if str(item.get("status", "queued")) not in {"queued", "waiting_conflict"}:
                    continue
                try:
                    self._lease_work_order(
                        run_id=run_id,
                        target_branch=str(record.get("target_branch", "main")),
                        work_order=item,
                        managed_dir_pattern=managed_dir_pattern,
                        approval_policy=SwarmApprovalPolicy.from_dict(
                            record.get("approval_policy")
                        ),
                    )
                    active_count += 1
                except LeaseConflictError as exc:
                    released = self._release_orphaned_conflict_leases(exc.conflicts)
                    if released:
                        try:
                            self._lease_work_order(
                                run_id=run_id,
                                target_branch=str(record.get("target_branch", "main")),
                                work_order=item,
                                managed_dir_pattern=managed_dir_pattern,
                                approval_policy=SwarmApprovalPolicy.from_dict(
                                    record.get("approval_policy")
                                ),
                            )
                            active_count += 1
                            continue
                        except LeaseConflictError as retry_exc:
                            exc = retry_exc
                    item["status"] = "waiting_conflict"
                    item["conflicts"] = list(exc.conflicts)
                except RuntimeError as exc:
                    if self._is_resource_constraint_error(exc):
                        item["status"] = "waiting_resource"
                        item["resource_error"] = str(exc)
                    else:
                        item["status"] = "needs_human"
                        item["dispatch_error"] = str(exc)
                    break

        refreshed = self.store.update_supervisor_run(
            run_id,
            status=self._derive_status(work_orders),
            work_orders=work_orders,
        )
        return SupervisorRun.from_record(refreshed)

    def status_summary(
        self,
        *,
        run_id: str | None = None,
        limit: int = 20,
        refresh_scaling: bool = False,
    ) -> dict[str, Any]:
        records = (
            [self.store.get_supervisor_run(run_id)]
            if run_id
            else self.store.list_supervisor_runs(limit=limit)
        )
        runs: list[SupervisorRun] = []
        for record in records:
            if not record:
                continue
            current = (
                self.refresh_run(record["run_id"])
                if refresh_scaling
                else SupervisorRun.from_record(record)
            )
            runs.append(current)
        coordination = self.store.status_summary()
        return {
            "runs": [run.to_dict() for run in runs],
            "counts": {
                "runs": len(runs),
                "queued_work_orders": sum(
                    1
                    for run in runs
                    for item in run.work_orders
                    if str(item.get("status", "")) == "queued"
                ),
                "leased_work_orders": sum(
                    1
                    for run in runs
                    for item in run.work_orders
                    if str(item.get("status", "")) == "leased"
                ),
                "completed_work_orders": sum(
                    1
                    for run in runs
                    for item in run.work_orders
                    if str(item.get("status", "")) == "completed"
                ),
            },
            "coordination": coordination,
        }

    async def dispatch_workers(self, run_id: str) -> list[WorkerProcess]:
        """Launch worker processes for all leased work orders in a run.

        Call this after start_run() to actually spawn the CLI processes.
        Only launches workers for orders in 'leased' status that have a
        worktree_path assigned.

        Returns:
            List of WorkerProcess objects for launched workers.
        """
        record = self.store.get_supervisor_run(run_id)
        if record is None:
            raise KeyError(f"Unknown supervisor run: {run_id}")

        work_orders = [dict(item) for item in record.get("work_orders", [])]
        launched: list[WorkerProcess] = []

        for item in work_orders:
            if str(item.get("status", "")) != "leased":
                continue
            worktree_path = str(item.get("worktree_path", "")).strip()
            branch = str(item.get("branch", "main")).strip()
            if not worktree_path:
                continue

            try:
                worker = await self.launcher.launch(
                    item,
                    worktree_path=worktree_path,
                    branch=branch,
                )
                dispatch_time = datetime.now(UTC).isoformat()
                item["status"] = "dispatched"
                item["pid"] = worker.pid
                item["initial_head"] = worker.initial_head
                item["dispatched_at"] = dispatch_time
                item["last_observed_at"] = dispatch_time
                item["last_progress_at"] = dispatch_time
                item["progress_fingerprint"] = {
                    "head_sha": worker.initial_head,
                    "changed_paths": [],
                    "diff_lines": 0,
                }
                launched.append(worker)
            except (FileNotFoundError, RuntimeError, OSError) as exc:
                fallback_requeued = self._requeue_after_dispatch_error(item, exc)
                if not fallback_requeued:
                    item["status"] = "dispatch_failed"
                    item["dispatch_error"] = str(exc)
                import logging

                logging.getLogger(__name__).warning(
                    "Failed to dispatch %s: %s",
                    item.get("work_order_id"),
                    exc,
                )

        self.store.update_supervisor_run(
            run_id,
            status=self._derive_status(work_orders),
            work_orders=work_orders,
        )
        return launched

    async def collect_results(
        self,
        run_id: str,
        *,
        timeout: float | None = None,
    ) -> list[WorkerProcess]:
        """Wait for all dispatched workers to complete and update the run.

        Returns:
            List of completed WorkerProcess objects.
        """
        record = self.store.get_supervisor_run(run_id)
        if record is None:
            raise KeyError(f"Unknown supervisor run: {run_id}")

        work_orders = [dict(item) for item in record.get("work_orders", [])]
        completed: list[WorkerProcess] = []

        for item in work_orders:
            if str(item.get("status", "")) != "dispatched":
                continue
            work_order_id = str(item.get("work_order_id", ""))
            worker = self.launcher.get_worker(work_order_id)
            if worker is None:
                continue

            result = await self.launcher.wait(work_order_id, timeout=timeout)
            self._apply_worker_result(item, result)
            completed.append(result)

        self.store.update_supervisor_run(
            run_id,
            status=self._derive_status(work_orders),
            work_orders=work_orders,
        )
        return completed

    async def collect_finished_results(self, run_id: str) -> list[WorkerProcess]:
        """Collect only workers that have already finished.

        Tries in-memory process collection first (same-process workers).
        Falls back to detached PID-based collection for workers spawned
        by a previous process (e.g. --dispatch-only mode).
        """
        record = self.store.get_supervisor_run(run_id)
        if record is None:
            raise KeyError(f"Unknown supervisor run: {run_id}")

        work_orders = [dict(item) for item in record.get("work_orders", [])]
        dispatched_ids = [
            str(item.get("work_order_id", "")).strip()
            for item in work_orders
            if str(item.get("status", "")) == "dispatched"
        ]

        # Try in-memory collection first (same process that launched workers)
        finished = await self.launcher.collect_finished(work_order_ids=dispatched_ids)
        changed = False

        # Fall back to detached collection for workers not in memory
        # (parent process restarted, or --dispatch-only mode)
        finished_ids = {w.work_order_id for w in finished}
        for item in work_orders:
            woid = str(item.get("work_order_id", "")).strip()
            if str(item.get("status", "")) != "dispatched":
                continue
            if woid in finished_ids:
                continue
            worktree_path = str(item.get("worktree_path", "")).strip()
            if not worktree_path:
                continue
            result = await WorkerLauncher.collect_detached_result(
                work_order_id=woid,
                agent=str(item.get("target_agent", "codex")),
                worktree_path=worktree_path,
                branch=str(item.get("branch", "main")),
                pid=item.get("pid"),
                initial_head=str(item.get("initial_head", "")),
                auto_commit=self.launcher.config.auto_commit,
            )
            if result is not None:
                finished.append(result)
                finished_ids.add(woid)
                continue

            progress = await self.launcher.snapshot_progress(item)
            observed_at = datetime.now(UTC).isoformat()
            item["last_observed_at"] = observed_at
            progress_fingerprint = self._progress_fingerprint(progress)
            if progress_fingerprint != self._progress_fingerprint(item.get("progress_fingerprint")):
                item["progress_fingerprint"] = progress_fingerprint
                item["last_progress_at"] = observed_at
                if progress_fingerprint["head_sha"]:
                    item["head_sha"] = progress_fingerprint["head_sha"]
                item["changed_paths"] = list(progress_fingerprint["changed_paths"])
                item["diff_lines"] = int(progress_fingerprint["diff_lines"])
                changed = True
                continue

            if not bool(progress.get("pid_alive")):
                self._mark_needs_human(
                    item,
                    "worker process exited without receipt or exit marker",
                )
                changed = True
                continue

            if self._exceeded_no_progress_timeout(item):
                self._mark_needs_human(
                    item,
                    (
                        "worker exceeded no-progress timeout "
                        f"({int(self._no_progress_timeout_seconds())}s)"
                    ),
                )
                changed = True

        if not finished and not changed:
            return []

        finished_by_id = {worker.work_order_id: worker for worker in finished}
        for item in work_orders:
            worker = finished_by_id.get(str(item.get("work_order_id", "")).strip())
            if worker is None:
                continue
            self._apply_worker_result(item, worker)

        self.store.update_supervisor_run(
            run_id,
            status=self._derive_status(work_orders),
            work_orders=work_orders,
        )
        return finished

    def _build_supervised_work_orders(self, spec: SwarmSpec) -> list[BoundedWorkOrder]:
        explicit = self._explicit_work_orders_from_spec(spec)
        if explicit:
            return explicit

        goal = spec.refined_goal or spec.raw_goal
        decomposition = self.decomposer.analyze(self._task_prompt(spec))
        subtasks = list(decomposition.subtasks)
        if not subtasks:
            subtasks = [
                SubTask(
                    id=f"work-{uuid.uuid4().hex[:8]}",
                    title=goal[:80] or "Swarm task",
                    description=goal,
                    file_scope=list(spec.file_scope_hints),
                    success_criteria={
                        "tests": self._tests_from_acceptance(spec.acceptance_criteria),
                        "acceptance_criteria": list(spec.acceptance_criteria),
                    },
                )
            ]
        work_orders = self.bridge.build_work_orders(subtasks)
        for item in work_orders:
            item.expected_tests = self._default_tests(item, spec)
            item.risk_level = self._risk_level_for_scope(item.file_scope)
            item.approval_required = item.approval_required or item.risk_level in {
                "critical",
                "review",
            }
            item.metadata = {
                **dict(item.metadata),
                "acceptance_criteria": list(spec.acceptance_criteria),
                "constraints": list(spec.constraints),
            }
        return work_orders

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
                        str(item).strip()
                        for item in payload.get("file_scope", [])
                        if str(item).strip()
                    ],
                    dependency_ids=dependency_ids,
                    success_criteria=success_criteria,
                    expected_tests=expected_tests,
                    estimated_complexity=estimated_complexity,
                    risk_level=risk_level,
                    target_agent=target_agent,
                    reviewer_agent=reviewer_agent,
                    approval_required=bool(payload.get("approval_required", False)),
                    metadata={
                        **dict(payload.get("metadata") or {}),
                        "source": "explicit_spec_work_order",
                    },
                )
            )

        for item in work_orders:
            item.expected_tests = self._default_tests(item, spec)
            item.risk_level = str(item.risk_level).strip() or self._risk_level_for_scope(
                item.file_scope
            )
            item.approval_required = item.approval_required or item.risk_level in {
                "critical",
                "review",
            }
            item.metadata = {
                **dict(item.metadata),
                "acceptance_criteria": list(spec.acceptance_criteria),
                "constraints": list(spec.constraints),
            }

        return work_orders

    def _lease_work_order(
        self,
        *,
        run_id: str,
        target_branch: str,
        work_order: dict[str, Any],
        managed_dir_pattern: str,
        approval_policy: SwarmApprovalPolicy,
    ) -> None:
        target_agent = str(work_order.get("target_agent", "codex")).strip() or "codex"
        managed_dir = self._managed_dir_for_agent(managed_dir_pattern, target_agent)
        session_key = f"swarm-{run_id[:8]}-{str(work_order.get('work_order_id', 'task'))[:8]}"
        session = self.lifecycle.ensure_managed_worktree(
            managed_dir=managed_dir,
            base_branch=target_branch,
            agent=target_agent,
            session_id=session_key,
            reconcile=True,
            strategy="ff-only",
        )
        file_scope = [str(item) for item in work_order.get("file_scope", []) if str(item).strip()]
        claimed_paths = [item for item in file_scope if not self._looks_like_glob(item)]
        allowed_globs = [item for item in file_scope if self._looks_like_glob(item)]
        if not allowed_globs and not claimed_paths and file_scope:
            claimed_paths = list(file_scope)

        lease = self.store.claim_lease(
            task_id=str(work_order.get("work_order_id", "")),
            title=str(work_order.get("title", "") or work_order.get("work_order_id", "task")),
            owner_agent=target_agent,
            owner_session_id=session.session_id,
            branch=session.branch,
            worktree_path=str(session.path),
            allowed_globs=allowed_globs,
            claimed_paths=claimed_paths,
            expected_tests=[str(item) for item in work_order.get("expected_tests", [])],
            metadata={
                "supervisor_run_id": run_id,
                "work_order_id": str(work_order.get("work_order_id", "")),
                "reviewer_agent": str(work_order.get("reviewer_agent", "")),
                "risk_level": str(work_order.get("risk_level", "review")),
                "approval_required": bool(work_order.get("approval_required", False))
                or approval_policy.require_merge_approval,
            },
        )
        work_order.update(
            {
                "status": "leased",
                "lease_id": lease.lease_id,
                "owner_session_id": session.session_id,
                "branch": session.branch,
                "worktree_path": str(session.path),
                "target_agent": target_agent,
                "approval_required": bool(work_order.get("approval_required", False))
                or approval_policy.require_merge_approval,
            }
        )

    def _apply_worker_result(self, item: dict[str, Any], result: WorkerProcess) -> None:
        item["completed_at"] = result.completed_at
        item["diff_lines"] = result.diff.count("\n")
        item["changed_paths"] = list(result.changed_paths)
        item["tests_run"] = list(result.tests_run)
        item["commit_shas"] = list(result.commit_shas)
        item["head_sha"] = result.head_sha
        item.pop("pid", None)

        lease_id = str(item.get("lease_id", "")).strip()
        if result.exit_code == 0:
            receipt_id = str(item.get("receipt_id", "")).strip()
            if lease_id and not receipt_id:
                try:
                    receipt = self.store.record_completion(
                        lease_id=lease_id,
                        owner_agent=str(item.get("target_agent", result.agent)),
                        owner_session_id=str(item.get("owner_session_id", result.session_id)),
                        branch=str(item.get("branch", result.branch)),
                        worktree_path=str(item.get("worktree_path", result.worktree_path)),
                        commit_shas=list(result.commit_shas),
                        changed_paths=list(result.changed_paths),
                        tests_run=list(result.tests_run),
                        assumptions=[],
                        blockers=[],
                        confidence=self._completion_confidence(item, result),
                    )
                except FileScopeViolationError as exc:
                    self._mark_needs_human(
                        item,
                        "worker completion violated file-scope ownership; narrow or split the lane",
                    )
                    item["review_status"] = "changes_requested"
                    item["scope_violation"] = {
                        "violations": list(exc.violations),
                        "changed_paths": list(result.changed_paths),
                    }
                    item["exit_code"] = result.exit_code
                    return
                item["receipt_id"] = receipt.receipt_id
                item["confidence"] = receipt.confidence
            item["status"] = "completed"
            item["review_status"] = "pending_heterogeneous_review"
            return

        if self._requeue_after_worker_failure(item, result):
            return

        if lease_id:
            self.store.release_lease(lease_id, status=LeaseStatus.RELEASED)
        item["status"] = "timed_out" if result.exit_code == -1 else "failed"
        item["exit_code"] = result.exit_code
        if result.stderr.strip():
            item["blockers"] = [result.stderr.strip()]

    def _requeue_after_dispatch_error(self, item: dict[str, Any], exc: Exception) -> bool:
        message = str(exc).strip()
        lowered = message.lower()
        if "cli not found" not in lowered and "not found" not in lowered:
            return False
        return self._requeue_with_fallback(
            item,
            reason="agent_unavailable",
            detail=message,
        )

    def _requeue_after_worker_failure(
        self,
        item: dict[str, Any],
        result: WorkerProcess,
    ) -> bool:
        combined = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        lowered = combined.lower()
        capacity_patterns = (
            "credit balance is too low",
            "insufficient credit",
            "insufficient balance",
            "out of credits",
            "quota exceeded",
            "usage limit reached",
            "rate limit exceeded",
            "billing",
            "payment required",
        )
        if not any(pattern in lowered for pattern in capacity_patterns):
            return False
        return self._requeue_with_fallback(
            item,
            reason="agent_capacity",
            detail=combined or f"{result.agent} worker failed",
        )

    def _requeue_with_fallback(
        self,
        item: dict[str, Any],
        *,
        reason: str,
        detail: str,
    ) -> bool:
        current_agent = str(item.get("target_agent", "")).strip().lower()
        fallback_agent = self._alternate_agent(current_agent)
        if not fallback_agent:
            return False

        metadata = dict(item.get("metadata") or {})
        attempted_agents = [
            str(agent).strip().lower()
            for agent in metadata.get("attempted_agents", [])
            if str(agent).strip()
        ]
        if current_agent and current_agent not in attempted_agents:
            attempted_agents.append(current_agent)
        if fallback_agent in attempted_agents:
            return False

        fallback_history = list(metadata.get("fallback_history", []))
        fallback_history.append(
            {
                "from_agent": current_agent,
                "to_agent": fallback_agent,
                "reason": reason,
                "detail": detail[:500],
                "at": datetime.now(UTC).isoformat(),
            }
        )
        metadata.update(
            {
                "requested_target_agent": metadata.get("requested_target_agent", current_agent),
                "requested_reviewer_agent": metadata.get(
                    "requested_reviewer_agent",
                    str(item.get("reviewer_agent", "")).strip().lower(),
                ),
                "attempted_agents": attempted_agents,
                "fallback_history": fallback_history,
                "last_failure_reason": reason,
                "last_failure_detail": detail[:1000],
                "reuse_existing_worktree": True,
            }
        )

        item.update(
            {
                "status": "leased",
                "target_agent": fallback_agent,
                "reviewer_agent": self._alternate_agent(fallback_agent)
                or str(item.get("reviewer_agent", "")),
                "metadata": metadata,
                "review_status": "pending",
                "receipt_id": None,
                "dispatch_error": None,
                "exit_code": None,
                "completed_at": None,
            }
        )
        item.pop("pid", None)
        item.pop("blockers", None)
        item.pop("dispatched_at", None)
        item.pop("last_observed_at", None)
        item.pop("last_progress_at", None)
        item.pop("progress_fingerprint", None)
        return True

    def _release_orphaned_conflict_leases(self, conflicts: list[dict[str, Any]]) -> int:
        released = 0
        for conflict in conflicts:
            if str(conflict.get("source", "lease")).strip() not in {"lease", ""}:
                continue
            lease_id = str(conflict.get("lease_id", "")).strip()
            worktree_path = str(conflict.get("worktree_path", "")).strip()
            if not lease_id or not worktree_path:
                continue
            if Path(worktree_path).exists():
                continue
            self.store.release_lease(lease_id, status=LeaseStatus.RELEASED)
            released += 1
        return released

    @staticmethod
    def _is_resource_constraint_error(exc: Exception) -> bool:
        lowered = str(exc).lower()
        return "no space left on device" in lowered or "disk full" in lowered

    @staticmethod
    def _alternate_agent(agent: str | None) -> str | None:
        value = str(agent or "").strip().lower()
        if value == "claude":
            return "codex"
        if value == "codex":
            return "claude"
        return None

    @staticmethod
    def _completion_confidence(item: dict[str, Any], result: WorkerProcess) -> float:
        expected_tests = [str(test) for test in item.get("expected_tests", []) if str(test).strip()]
        if result.exit_code != 0:
            return 0.0
        if expected_tests:
            return 0.8 if result.tests_run else 0.65
        if result.commit_shas or result.changed_paths:
            return 0.6
        return 0.4

    @staticmethod
    def _progress_fingerprint(source: Any) -> dict[str, Any]:
        payload = dict(source or {})
        return {
            "head_sha": str(payload.get("head_sha", "")).strip(),
            "changed_paths": sorted(
                str(path).strip() for path in payload.get("changed_paths", []) if str(path).strip()
            ),
            "diff_lines": int(payload.get("diff_lines", 0) or 0),
        }

    def _no_progress_timeout_seconds(self) -> float:
        raw = getattr(self.launcher.config, "no_progress_timeout_seconds", 120.0)
        try:
            return max(1.0, float(raw))
        except (TypeError, ValueError):
            return 120.0

    def _exceeded_no_progress_timeout(self, item: dict[str, Any]) -> bool:
        since = self._parse_timestamp(item.get("last_progress_at")) or self._parse_timestamp(
            item.get("dispatched_at")
        )
        if since is None:
            return False
        elapsed = (datetime.now(UTC) - since).total_seconds()
        return elapsed >= self._no_progress_timeout_seconds()

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    @staticmethod
    def _mark_needs_human(item: dict[str, Any], reason: str) -> None:
        item["status"] = "needs_human"
        item["dispatch_error"] = reason
        blockers = [str(value).strip() for value in item.get("blockers", []) if str(value).strip()]
        if reason not in blockers:
            blockers.append(reason)
        item["blockers"] = blockers
        item.pop("pid", None)

    @staticmethod
    def _derive_status(work_orders: list[dict[str, Any]]) -> str:
        statuses = {str(item.get("status", "")).strip() for item in work_orders if item}
        if not statuses:
            return SupervisorRunStatus.PLANNED.value
        terminal = {"merged", "discarded", "salvage", "completed", "failed", "timed_out"}
        if statuses <= terminal:
            return SupervisorRunStatus.COMPLETED.value
        if "needs_human" in statuses or "changes_requested" in statuses:
            return SupervisorRunStatus.NEEDS_HUMAN.value
        if "dispatch_failed" in statuses:
            return SupervisorRunStatus.NEEDS_HUMAN.value
        return SupervisorRunStatus.ACTIVE.value

    @staticmethod
    def _managed_dir_for_agent(pattern: str, agent: str) -> str:
        if "{agent}" in pattern:
            return pattern.format(agent=agent)
        cleaned = pattern.rstrip("/")
        if cleaned.endswith("-auto"):
            return cleaned.replace("codex-auto", f"{agent}-auto")
        return f"{cleaned}/{agent}-auto"

    @staticmethod
    def _looks_like_glob(path: str) -> bool:
        return any(token in path for token in ("*", "?", "["))

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

    @staticmethod
    def _task_prompt(spec: SwarmSpec) -> str:
        parts = [spec.refined_goal or spec.raw_goal]
        if spec.file_scope_hints:
            parts.append("File scope hints: " + ", ".join(spec.file_scope_hints))
        if spec.constraints:
            parts.append("Constraints: " + "; ".join(spec.constraints))
        if spec.acceptance_criteria:
            parts.append("Acceptance: " + "; ".join(spec.acceptance_criteria))
        return "\n".join(part for part in parts if part)
