"""Fleet merge-queue worker backed by existing merge engines.

The worker turns FleetCoordinationStore's merge queue into an actual
integration lane. It does not invent a new merge implementation; instead it:

- claims queued work via FleetCoordinationStore
- validates mergeability using GitReconciler + BranchCoordinator dry-runs
- optionally performs the merge via BranchCoordinator
- persists queue lifecycle state back to FleetCoordinationStore
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aragora.coordination.reconciler import GitReconciler
from aragora.nomic.branch_coordinator import (
    BranchCoordinator,
    BranchCoordinatorConfig,
)
from aragora.worktree.fleet import FleetCoordinationStore
from aragora.worktree.integration_target_workspace import (
    FleetIntegrationTargetWorkspace,
)


@dataclass
class FleetIntegrationWorkerConfig:
    """Configuration for processing fleet merge queue items."""

    target_branch: str = "main"
    execute_with_test_gate: bool = False
    use_dedicated_integration_workspace: bool = True
    integration_workspace_path: Path | None = None


@dataclass
class FleetIntegrationOutcome:
    """Result of processing one fleet merge queue item."""

    queue_item_id: str | None
    branch: str | None
    queue_status: str
    action: str
    dry_run_success: bool = False
    merge_commit_sha: str | None = None
    conflicts: list[str] = field(default_factory=list)
    conflict_details: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "queue_item_id": self.queue_item_id,
            "branch": self.branch,
            "queue_status": self.queue_status,
            "action": self.action,
            "dry_run_success": self.dry_run_success,
            "merge_commit_sha": self.merge_commit_sha,
            "conflicts": list(self.conflicts),
            "conflict_details": [dict(item) for item in self.conflict_details],
            "error": self.error,
            "metadata": dict(self.metadata),
        }


class FleetIntegrationWorker:
    """Process FleetCoordinationStore merge queue items."""

    def __init__(
        self,
        repo_path: Path | None = None,
        *,
        config: FleetIntegrationWorkerConfig | None = None,
        fleet_store: FleetCoordinationStore | None = None,
        branch_coordinator: BranchCoordinator | None = None,
        reconciler: GitReconciler | None = None,
        integration_workspace: FleetIntegrationTargetWorkspace | None = None,
    ) -> None:
        self.repo_path = (repo_path or Path.cwd()).resolve()
        self.config = config or FleetIntegrationWorkerConfig()
        self.fleet_store = fleet_store or FleetCoordinationStore(self.repo_path)
        self.branch_coordinator = branch_coordinator
        self.reconciler = reconciler
        self.integration_workspace = integration_workspace

    @staticmethod
    def _is_checkout_constraint(error: str | None) -> bool:
        """Return True when merge execution is blocked by target checkout ownership."""
        if not error:
            return False
        lowered = error.lower()
        return "failed to checkout target branch" in lowered and "already checked out" in lowered

    def _merge_engines(self, source_branch: str) -> tuple[BranchCoordinator, GitReconciler, Path]:
        """Resolve merge engines, optionally via a dedicated integration workspace."""
        if self.branch_coordinator is not None and self.reconciler is not None:
            return self.branch_coordinator, self.reconciler, self.repo_path

        engine_repo_path = self.repo_path
        if self.config.use_dedicated_integration_workspace:
            workspace = self.integration_workspace or FleetIntegrationTargetWorkspace(
                repo_root=self.repo_path,
                target_branch=self.config.target_branch,
                workspace_path=self.config.integration_workspace_path,
            )
            self.integration_workspace = workspace
            engine_repo_path = workspace.ensure_ready(source_branch=source_branch)

        if self.branch_coordinator is None:
            self.branch_coordinator = BranchCoordinator(
                repo_path=engine_repo_path,
                config=BranchCoordinatorConfig(
                    base_branch=self.config.target_branch,
                    use_worktrees=True,
                ),
            )
        if self.reconciler is None:
            self.reconciler = GitReconciler(repo_path=engine_repo_path)

        return self.branch_coordinator, self.reconciler, engine_repo_path

    async def process_next(
        self,
        *,
        worker_session_id: str,
        execute: bool = False,
    ) -> FleetIntegrationOutcome:
        """Claim and process the next queued merge item."""
        item = self.fleet_store.claim_next_merge(
            worker_session_id=worker_session_id,
            from_status="queued",
            to_status="validating",
        )
        if item is None:
            return FleetIntegrationOutcome(
                queue_item_id=None,
                branch=None,
                queue_status="idle",
                action="no_work",
            )

        item_id = str(item.get("id", ""))
        branch = str(item.get("branch", ""))
        metadata = dict(item.get("metadata") or {})
        branch_coordinator, reconciler, engine_repo_path = self._merge_engines(source_branch=branch)
        changed_files = reconciler.get_changed_files(branch, self.config.target_branch)
        commits_ahead = reconciler.get_commits_ahead(branch, self.config.target_branch)

        conflict_infos = reconciler.detect_conflicts(branch, self.config.target_branch)
        conflict_details = [
            {
                "file_path": info.file_path,
                "category": info.category.value,
                "description": info.description,
                "auto_resolvable": info.auto_resolvable,
            }
            for info in conflict_infos
        ]

        validation_metadata = {
            **metadata,
            "validated_by": worker_session_id,
            "reconciler_conflicts": conflict_details,
            "changed_files": changed_files,
            "commits_ahead": commits_ahead,
            "integration_workspace_path": str(engine_repo_path),
        }

        if conflict_details:
            updated = self.fleet_store.update_merge_queue_item(
                item_id=item_id,
                status="blocked",
                metadata=validation_metadata | {"validation_error": "merge conflicts detected"},
            )
            return FleetIntegrationOutcome(
                queue_item_id=item_id,
                branch=branch,
                queue_status=str(updated.get("status", "blocked")),
                action="blocked",
                dry_run_success=False,
                conflicts=[detail["file_path"] for detail in conflict_details],
                conflict_details=conflict_details,
                error="merge conflicts detected",
                metadata=dict(updated.get("metadata") or {}),
            )

        dry_run = await branch_coordinator.safe_merge(
            branch,
            self.config.target_branch,
            dry_run=True,
        )
        validation_metadata |= {
            "dry_run_success": dry_run.success,
            "dry_run_conflicts": list(dry_run.conflicts),
        }

        if not dry_run.success:
            status = "needs_human" if self._is_checkout_constraint(dry_run.error) else "blocked"
            action = "needs_human" if status == "needs_human" else "blocked"
            updated = self.fleet_store.update_merge_queue_item(
                item_id=item_id,
                status=status,
                metadata=validation_metadata
                | {"validation_error": dry_run.error or "dry-run merge failed"},
            )
            return FleetIntegrationOutcome(
                queue_item_id=item_id,
                branch=branch,
                queue_status=str(updated.get("status", status)),
                action=action,
                dry_run_success=False,
                conflicts=list(dry_run.conflicts),
                error=dry_run.error,
                metadata=dict(updated.get("metadata") or {}),
            )

        if not execute:
            updated = self.fleet_store.update_merge_queue_item(
                item_id=item_id,
                status="needs_human",
                metadata=validation_metadata | {"validated_only": True},
            )
            return FleetIntegrationOutcome(
                queue_item_id=item_id,
                branch=branch,
                queue_status=str(updated.get("status", "needs_human")),
                action="validated",
                dry_run_success=True,
                metadata=dict(updated.get("metadata") or {}),
            )

        self.fleet_store.update_merge_queue_item(
            item_id=item_id,
            status="integrating",
            metadata=validation_metadata | {"executed_by": worker_session_id},
        )

        if self.config.execute_with_test_gate:
            merge_result = await branch_coordinator.safe_merge_with_gate(
                branch,
                target=self.config.target_branch,
            )
        else:
            merge_result = await branch_coordinator.safe_merge(
                branch,
                self.config.target_branch,
                dry_run=False,
            )

        if merge_result.success:
            updated = self.fleet_store.update_merge_queue_item(
                item_id=item_id,
                status="merged",
                metadata=validation_metadata
                | {
                    "executed_by": worker_session_id,
                    "merge_commit_sha": merge_result.commit_sha,
                },
            )
            return FleetIntegrationOutcome(
                queue_item_id=item_id,
                branch=branch,
                queue_status=str(updated.get("status", "merged")),
                action="merged",
                dry_run_success=True,
                merge_commit_sha=merge_result.commit_sha,
                metadata=dict(updated.get("metadata") or {}),
            )

        fail_status = (
            "needs_human"
            if self._is_checkout_constraint(merge_result.error)
            else ("blocked" if merge_result.conflicts else "failed")
        )
        updated = self.fleet_store.update_merge_queue_item(
            item_id=item_id,
            status=fail_status,
            metadata=validation_metadata
            | {
                "executed_by": worker_session_id,
                "merge_error": merge_result.error,
                "merge_conflicts": list(merge_result.conflicts),
            },
        )
        return FleetIntegrationOutcome(
            queue_item_id=item_id,
            branch=branch,
            queue_status=str(updated.get("status", fail_status)),
            action="needs_human" if fail_status == "needs_human" else "failed",
            dry_run_success=True,
            conflicts=list(merge_result.conflicts),
            error=merge_result.error,
            metadata=dict(updated.get("metadata") or {}),
        )


__all__ = [
    "FleetIntegrationOutcome",
    "FleetIntegrationWorker",
    "FleetIntegrationWorkerConfig",
]
