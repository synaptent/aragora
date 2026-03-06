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
                    item["status"] = "waiting_conflict"
                    item["conflicts"] = list(exc.conflicts)
                except RuntimeError as exc:
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
                item["status"] = "dispatched"
                item["pid"] = worker.pid
                launched.append(worker)
            except (FileNotFoundError, RuntimeError, OSError) as exc:
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
        """Collect only workers that have already finished."""
        record = self.store.get_supervisor_run(run_id)
        if record is None:
            raise KeyError(f"Unknown supervisor run: {run_id}")

        work_orders = [dict(item) for item in record.get("work_orders", [])]
        dispatched_ids = [
            str(item.get("work_order_id", "")).strip()
            for item in work_orders
            if str(item.get("status", "")) == "dispatched"
        ]
        finished = await self.launcher.collect_finished(work_order_ids=dispatched_ids)
        if not finished:
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
                item["receipt_id"] = receipt.receipt_id
                item["confidence"] = receipt.confidence
            item["status"] = "completed"
            item["review_status"] = "pending_heterogeneous_review"
            return

        if lease_id:
            self.store.release_lease(lease_id, status=LeaseStatus.RELEASED)
        item["status"] = "timed_out" if result.exit_code == -1 else "failed"
        item["exit_code"] = result.exit_code
        if result.stderr.strip():
            item["blockers"] = [result.stderr.strip()]

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
