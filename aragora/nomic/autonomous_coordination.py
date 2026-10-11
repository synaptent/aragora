"""Branch, convoy/bead and Agent Fabric helpers, inherited by ``AutonomousOrchestrator``.

Creates and merges per-track worktree branches, tracks the orchestration as a convoy
of beads, and registers, bills, notifies and retires agents through the Agent Fabric.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

# Runtime import, not a TYPE_CHECKING one: typing.get_type_hints() on the
# orchestrator methods below evaluates their annotations here.
from aragora.nomic.types import AgentAssignment
from aragora.observability import get_logger

# The facade's logger name, so log filters and caplog assertions keyed on
# "aragora.nomic.autonomous_orchestrator" still see records from these methods.
logger = get_logger("aragora.nomic.autonomous_orchestrator")


class AutonomousCoordinationMixin:
    """Branch, convoy and Agent Fabric helpers of ``AutonomousOrchestrator``."""

    # Set by AutonomousOrchestrator.__init__.
    aragora_path: Path
    branch_coordinator: Any
    enable_convoy_tracking: bool
    workspace_manager: Any
    agent_fabric: Any
    _orchestration_id: str | None
    _convoy_id: str | None
    _bead_ids: dict[str, str]

    async def _create_branches_for_assignments(
        self,
        assignments: list[AgentAssignment],
    ) -> None:
        """Create worktree branches for each unique track in the assignments.

        Groups assignments by track and creates one branch per track so
        multiple assignments targeting the same track share a worktree.
        """
        if self.branch_coordinator is None:
            return

        from aragora.nomic.meta_planner import Track as MetaTrack

        seen_tracks: set[str] = set()
        for assignment in assignments:
            track_value = assignment.track.value
            if track_value in seen_tracks:
                continue
            seen_tracks.add(track_value)

            # Map orchestrator Track to meta_planner Track
            try:
                meta_track = MetaTrack(track_value)
            except ValueError:
                meta_track = MetaTrack.DEVELOPER

            await self.branch_coordinator.create_track_branch(
                track=meta_track,
                goal=assignment.subtask.description[:60],
            )
            logger.info(
                "worktree_created",
                track=track_value,
                subtask_id=assignment.subtask.id,
            )

    async def _merge_and_cleanup(
        self,
        assignments: list[AgentAssignment],
    ) -> None:
        """Merge completed branches back to base and cleanup worktrees."""
        if self.branch_coordinator is None:
            return

        completed_tracks: set[str] = set()
        failed_tracks: set[str] = set()
        for assignment in assignments:
            if assignment.status == "completed":
                completed_tracks.add(assignment.track.value)
            elif assignment.status == "failed":
                failed_tracks.add(assignment.track.value)

        # Merge branches where all assignments in the track completed
        for branch, wt_path in dict(
            getattr(self.branch_coordinator, "_worktree_paths", {})
        ).items():
            # Check if any track in this branch completed and none failed
            track_value = None
            for t in completed_tracks:
                if t in branch:
                    track_value = t
                    break

            if track_value and track_value not in failed_tracks:
                # Scope guard: warn about cross-track file modifications before merging
                try:
                    from aragora.nomic.scope_guard import ScopeGuard

                    guard = ScopeGuard(repo_path=self.aragora_path, mode="warn")
                    track_name = f"{track_value}-track"
                    changed = guard.get_changed_files(
                        base_branch=self.branch_coordinator.config.base_branch
                    )
                    if changed:
                        violations = guard.check_files(changed, track=track_name)
                        if violations:
                            for v in violations[:5]:
                                logger.info("scope_violation branch=%s %s", branch, v.message)
                except (ImportError, OSError, ValueError) as e:
                    logger.debug("scope_guard_skipped: %s", e)

                # CI feedback: check latest CI result for the branch before merging
                try:
                    from aragora.nomic.ci_feedback import CIResultCollector

                    ci_collector = CIResultCollector()
                    ci_result = ci_collector.get_latest_result(branch)
                    if ci_result is not None:
                        if ci_result.conclusion == "success":
                            logger.info("ci_check_passed branch=%s", branch)
                        else:
                            logger.warning(
                                "ci_check_failed branch=%s conclusion=%s",
                                branch,
                                ci_result.conclusion,
                            )
                            # Don't block merge on CI — just warn
                except (ImportError, OSError, RuntimeError) as e:
                    logger.debug("ci_check_skipped: %s", e)

                # Use safe_merge_with_gate for test-gated merges when available
                if hasattr(self.branch_coordinator, "safe_merge_with_gate"):
                    merge_result = await self.branch_coordinator.safe_merge_with_gate(
                        branch,
                        auto_revert=True,
                    )
                else:
                    merge_result = await self.branch_coordinator.safe_merge(branch)
                if merge_result.success:
                    logger.info(
                        "branch_merged",
                        branch=branch,
                        commit_sha=merge_result.commit_sha,
                    )
                else:
                    logger.warning(
                        "branch_merge_failed",
                        branch=branch,
                        error=merge_result.error,
                    )

        # Cleanup all worktrees
        if hasattr(self.branch_coordinator, "cleanup_all_worktrees"):
            removed = self.branch_coordinator.cleanup_all_worktrees()
        elif hasattr(self.branch_coordinator, "cleanup_worktrees"):
            removed = self.branch_coordinator.cleanup_worktrees()
        else:
            removed = 0
        if removed:
            logger.info("worktrees_cleaned", count=removed)

    async def _create_convoy_for_goal(
        self,
        goal: str,
        assignments: list[AgentAssignment],
    ) -> None:
        """Create a convoy and beads for tracking the orchestration lifecycle."""
        if not self.enable_convoy_tracking or self.workspace_manager is None:
            return

        try:
            # Create a rig for this orchestration
            rig = await self.workspace_manager.create_rig(
                name=f"orch-{self._orchestration_id}",
            )

            # Create bead specs from assignments
            bead_specs = [
                {
                    "title": a.subtask.title,
                    "description": a.subtask.description,
                    "payload": {
                        "subtask_id": a.subtask.id,
                        "track": a.track.value,
                        "agent_type": a.agent_type,
                    },
                }
                for a in assignments
            ]

            convoy = await self.workspace_manager.create_convoy(
                rig_id=rig.rig_id,
                name=f"Goal: {goal[:50]}",
                description=goal,
                bead_specs=bead_specs,
            )

            self._convoy_id = convoy.convoy_id
            await self.workspace_manager.start_convoy(convoy.convoy_id)

            # Map subtask IDs to bead IDs for status updates
            beads = await self.workspace_manager._bead_manager.list_beads(
                convoy_id=convoy.convoy_id,
            )
            for bead in beads:
                subtask_id = bead.payload.get("subtask_id", "")
                if subtask_id:
                    self._bead_ids[subtask_id] = bead.bead_id

            logger.info(
                "convoy_created",
                convoy_id=convoy.convoy_id,
                bead_count=len(beads),
            )

        except (RuntimeError, OSError, ValueError, ConnectionError, asyncio.TimeoutError) as e:
            logger.warning("Failed to create convoy: %s", e)

    async def _update_bead_status(
        self,
        subtask_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        """Update bead status for a subtask."""
        if not self.enable_convoy_tracking or self.workspace_manager is None:
            return

        bead_id = self._bead_ids.get(subtask_id)
        if not bead_id:
            return

        try:
            if status == "running":
                await self.workspace_manager._bead_manager.start_bead(bead_id)
            elif status == "done":
                await self.workspace_manager.complete_bead(bead_id)
            elif status == "failed":
                await self.workspace_manager.fail_bead(bead_id, error or "Unknown error")
        except (RuntimeError, OSError, ValueError, ConnectionError, asyncio.TimeoutError) as e:
            logger.debug("Failed to update bead %s: %s", bead_id, e)

    async def _complete_convoy(
        self,
        success: bool,
        error: str | None = None,
    ) -> None:
        """Mark the convoy as completed or failed."""
        if not self.enable_convoy_tracking or self.workspace_manager is None:
            return
        if not self._convoy_id:
            return

        try:
            if success:
                await self.workspace_manager.complete_convoy(self._convoy_id)
            else:
                tracker = self.workspace_manager._convoy_tracker
                await tracker.fail_convoy(self._convoy_id, error or "Orchestration failed")
        except (RuntimeError, OSError, ValueError, ConnectionError, asyncio.TimeoutError) as e:
            logger.debug("Failed to complete convoy: %s", e)

    async def _fabric_register_agent(self, assignment: AgentAssignment) -> str | None:
        """Register an agent with the Fabric for lifecycle management.

        Returns the Fabric agent_id if registered, None otherwise.
        """
        if not self.agent_fabric:
            return None

        try:
            from aragora.fabric.models import AgentConfig as FabricAgentConfig

            config = FabricAgentConfig(
                id=f"{assignment.agent_type}-{assignment.subtask.id[:8]}",
                model=assignment.agent_type,
                tools=["code", "test", "lint"],
                max_concurrent_tasks=1,
            )
            handle = await self.agent_fabric.spawn(config)
            fabric_id = handle.agent_id if hasattr(handle, "agent_id") else str(handle)
            logger.debug(
                "[fabric] Spawned agent %s for subtask %s",
                fabric_id,
                assignment.subtask.id,
            )
            return fabric_id
        except (ImportError, TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[fabric] Agent registration failed: %s", e)
            return None

    async def _fabric_track_usage(
        self,
        assignment: AgentAssignment,
        cost_usd: float = 0.0,
        tokens: int = 0,
    ) -> None:
        """Track usage in Fabric's BudgetManager for cost enforcement."""
        if not self.agent_fabric:
            return

        try:
            from aragora.fabric.models import Usage

            agent_id = f"{assignment.agent_type}-{assignment.subtask.id[:8]}"
            usage = Usage(
                agent_id=agent_id,
                tokens_input=tokens,
                cost_usd=cost_usd,
                task_id=f"subtask:{assignment.subtask.id}",
            )
            await self.agent_fabric.track_usage(usage)
        except (ImportError, TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[fabric] Usage tracking failed: %s", e)

    async def _fabric_complete_task(
        self,
        assignment: AgentAssignment,
        success: bool,
    ) -> None:
        """Notify Fabric that a task completed (for scheduler cleanup)."""
        if not self.agent_fabric:
            return

        try:
            task_id = f"task-{assignment.subtask.id}"
            error = None if success else "Task failed"
            await self.agent_fabric.complete_task(task_id, result=None, error=error)
            # Terminate the agent after task completion
            agent_id = f"{assignment.agent_type}-{assignment.subtask.id[:8]}"
            await self.agent_fabric.terminate(agent_id, graceful=True)
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[fabric] Task completion notification failed: %s", e)

    async def _fabric_notify_agents(
        self,
        message: str,
        exclude_agent: str | None = None,
    ) -> None:
        """Broadcast a message to all active agents via Fabric's NudgeRouter."""
        if not self.agent_fabric:
            return

        try:
            from aragora.fabric.nudge import NudgeRouter  # noqa: F401

            router = getattr(self.agent_fabric, "_nudge_router", None)
            if router:
                await router.broadcast(
                    sender="orchestrator",
                    content=message,
                    exclude=[exclude_agent] if exclude_agent else None,
                )
        except (ImportError, TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[fabric] Agent notification failed: %s", e)

    async def get_fabric_stats(self) -> dict[str, Any] | None:
        """Get Fabric orchestration statistics for dashboard display."""
        if not self.agent_fabric:
            return None

        try:
            return await self.agent_fabric.get_fabric_stats()
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            logger.debug("[fabric] Stats retrieval failed: %s", e)
            return None
