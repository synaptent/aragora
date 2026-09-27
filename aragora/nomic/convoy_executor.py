"""
Gastown-style convoy executor for Nomic ImplementPhase.

Bridges ImplementPlan tasks to Beads + Convoys + HookQueues, then
executes tasks with Claude/Codex while using additional agents for
cross-check review.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from collections.abc import Callable

from aragora.implement.executor import HybridExecutor
from aragora.implement.types import ImplementTask, TaskResult
from aragora.nomic.agent_roles import AgentHierarchy, AgentRole
from aragora.nomic.beads import Bead, BeadPriority, BeadStatus, BeadStore, BeadType
from aragora.nomic.convoy_coordinator import AssignmentStatus, ConvoyCoordinator
from aragora.nomic.convoys import ConvoyManager, ConvoyPriority
from aragora.nomic.hook_queue import HookQueue
from aragora.nomic.stores.paths import (
    resolve_bead_and_convoy_dirs,
    should_use_canonical_store,
)
from aragora.stores import get_canonical_workspace_stores
from aragora.stores.canonical import WorkspaceStores

logger = logging.getLogger(__name__)


@dataclass
class ReviewResult:
    approved: bool
    notes: str


class GastownConvoyExecutor:
    """Execute ImplementPlan tasks via Gastown-style convoys and beads."""

    def __init__(
        self,
        repo_path: Path,
        implementers: list[Any],
        reviewers: list[Any] | None = None,
        bead_dir: Path | None = None,
        convoy_dir: Path | None = None,
        allow_parallel: bool | None = None,
        max_parallel: int | None = None,
        enable_tests: bool | None = None,
        test_command: str | None = None,
        test_timeout: int | None = None,
        log_fn: Callable[[str], None] | None = None,
        stream_emit_fn: Callable[..., None] | None = None,
    ) -> None:
        self.repo_path = Path(repo_path)
        self.implementers = [a for a in implementers if a is not None]
        self.reviewers = [a for a in (reviewers or []) if a is not None]
        self._log = log_fn or (lambda msg: logger.info(msg))
        self._stream_emit = stream_emit_fn or (lambda *args, **kwargs: None)

        if allow_parallel is None:
            allow_parallel = os.environ.get("NOMIC_CONVOY_PARALLEL_TASKS", "0") == "1"
        if max_parallel is None:
            max_parallel = int(os.environ.get("NOMIC_CONVOY_MAX_PARALLEL", "2"))
        if enable_tests is None:
            enable_tests = os.environ.get("NOMIC_CONVOY_TESTS", "0") == "1"
        if test_command is None:
            test_command = os.environ.get("NOMIC_CONVOY_TEST_COMMAND", "")
        if test_timeout is None:
            test_timeout = int(os.environ.get("NOMIC_CONVOY_TEST_TIMEOUT", "600"))

        self._allow_parallel = allow_parallel
        self._max_parallel = max_parallel
        self._enable_tests = enable_tests
        self._test_command = test_command
        self._test_timeout = test_timeout
        self._test_lock = asyncio.Lock()

        use_canonical_store = should_use_canonical_store(default=True)
        if bead_dir is None and use_canonical_store:
            resolved_bead_dir, resolved_convoy_dir = resolve_bead_and_convoy_dirs(
                workspace_root=self.repo_path
            )
            self.bead_dir = Path(resolved_bead_dir)
            self.convoy_dir = Path(convoy_dir or resolved_convoy_dir)
        else:
            base_dir = bead_dir or (self.repo_path / ".nomic" / "convoys")
            self.bead_dir = Path(base_dir)
            self.convoy_dir = Path(convoy_dir or base_dir)

        self._canonical_stores: WorkspaceStores = get_canonical_workspace_stores(
            bead_dir=str(self.bead_dir),
            convoy_dir=str(self.convoy_dir),
            git_enabled=True,
            auto_commit=False,
        )
        self.bead_store: BeadStore | None = None
        self.convoy_manager: ConvoyManager | None = None
        self.hierarchy = AgentHierarchy(self.repo_path / ".nomic" / "agents")
        self.coordinator: ConvoyCoordinator | None = None
        self._executor = HybridExecutor(self.repo_path)
        self._hook_queues: dict[str, HookQueue] = {}
        self._initialized = False

    async def _register_agents(self) -> None:
        for agent in self.implementers:
            try:
                await self.hierarchy.register_agent(agent.name, AgentRole.CREW)
            except (RuntimeError, OSError, ValueError) as e:
                logger.debug(
                    "Failed to register implementer agent %s: %s: %s",
                    agent.name,
                    type(e).__name__,
                    e,
                )
                continue
        for agent in self.reviewers:
            if any(a.name == agent.name for a in self.implementers):
                continue
            try:
                await self.hierarchy.register_agent(agent.name, AgentRole.WITNESS)
            except (RuntimeError, OSError, ValueError) as e:
                logger.debug(
                    "Failed to register reviewer agent %s: %s: %s", agent.name, type(e).__name__, e
                )
                continue

    async def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        if self.bead_store is None:
            self.bead_store = await self._canonical_stores.bead_store()
        if self.convoy_manager is None:
            self.convoy_manager = await self._canonical_stores.convoy_manager()
        await self.bead_store.initialize()
        await self.convoy_manager.initialize()
        await self.hierarchy.initialize()
        await self._register_agents()
        if self.coordinator is None:
            self.coordinator = ConvoyCoordinator(
                convoy_manager=self.convoy_manager,
                hierarchy=self.hierarchy,
                bead_store=self.bead_store,
            )
        await self.coordinator.initialize()
        for agent in self.implementers:
            queue = HookQueue(
                agent_id=getattr(agent, "name", str(agent)), bead_store=self.bead_store
            )
            await queue.initialize()
            self._hook_queues[queue.agent_id] = queue
        self._initialized = True

    async def execute_plan(
        self,
        tasks: list[ImplementTask],
        completed: set[str],
        on_task_complete=None,
        stop_on_failure: bool = False,
    ) -> list[TaskResult]:
        await self._ensure_initialized()
        bead_store = self.bead_store
        convoy_manager = self.convoy_manager
        coordinator = self.coordinator
        if bead_store is None or convoy_manager is None or coordinator is None:
            raise RuntimeError("Convoy executor components failed to initialize")
        if not self.implementers:
            raise RuntimeError("No implementer agents available for convoy execution")

        # Create beads for tasks
        convoy_id = f"nomic-{uuid.uuid4().hex[:8]}"
        bead_ids: dict[str, str] = {}
        for task in tasks:
            bead = Bead.create(
                bead_type=BeadType.TASK,
                title=task.id,
                description=task.description,
                priority=BeadPriority.NORMAL,
                metadata={"task_id": task.id, "files": task.files, "complexity": task.complexity},
            )
            bead.id = f"{convoy_id}-{task.id}"
            # Preserve dependencies using bead IDs
            bead.dependencies = []
            bead_ids[task.id] = bead.id
            try:
                await bead_store.create(bead)
            except ValueError:
                # Already exists; ignore
                pass

        # Map dependencies to bead IDs
        for task in tasks:
            stored_bead = await bead_store.get(bead_ids[task.id])
            if stored_bead:
                stored_bead.dependencies = [bead_ids[d] for d in task.dependencies if d in bead_ids]
                await bead_store.update(stored_bead)

        # Create convoy
        convoy = await convoy_manager.create_convoy(
            title="Nomic Implement Plan",
            description=f"{len(tasks)} tasks",
            bead_ids=[bead_ids[t.id] for t in tasks],
            priority=ConvoyPriority.HIGH,
            metadata={"convoy_id": convoy_id},
            convoy_id=convoy_id,
        )

        # Distribute beads to implementers
        assignments = await coordinator.distribute_convoy(
            convoy_id=convoy.id,
            agent_ids=[a.name for a in self.implementers],
        )
        if assignments:
            self._log(
                f"  [convoy] Assigned {len(assignments)} beads across {len(self.implementers)} agents"
            )

        # Push to hooks
        for assignment in assignments or []:
            hook = self._hook_queues.get(assignment.agent_id)
            if hook:
                await hook.push(assignment.bead_id, priority=assignment.priority)

        # Execute tasks respecting dependencies
        results: list[TaskResult] = []
        pending = {task.id: task for task in tasks if task.id not in completed}
        completion_lock = asyncio.Lock()

        async def run_task(task: ImplementTask) -> TaskResult:
            bead_id = bead_ids[task.id]
            assignment = await coordinator.get_assignment(bead_id)
            agent = self._select_agent_for_assignment(assignment.agent_id if assignment else None)

            await coordinator.update_assignment_status(bead_id, AssignmentStatus.ACTIVE)
            await bead_store.claim(bead_id, agent.name)
            await bead_store.update_status(bead_id, BeadStatus.RUNNING)

            result = await self._execute_task_with_agent(task, agent)
            review = await self._review_task(task, agent, result.diff)

            if result.success and review.approved:
                tests_ok, test_notes = await self._run_task_tests(task)
                if not tests_ok:
                    result = TaskResult(
                        task_id=task.id,
                        success=False,
                        diff=result.diff,
                        error=f"tests_failed: {test_notes}"[:800],
                        model_used=result.model_used,
                        duration_seconds=result.duration_seconds,
                    )
                else:
                    async with completion_lock:
                        completed.add(task.id)
                    await bead_store.update_status(bead_id, BeadStatus.COMPLETED)
                    await coordinator.update_assignment_status(bead_id, AssignmentStatus.COMPLETED)
                    hook = self._hook_queues.get(agent.name)
                    if hook:
                        await hook.complete(bead_id)
                    if on_task_complete:
                        on_task_complete(task.id, result)

            if not result.success or not review.approved:
                reason = result.error or review.notes or "review_blocked"
                result = TaskResult(
                    task_id=task.id,
                    success=False,
                    diff=result.diff,
                    error=reason,
                    model_used=result.model_used,
                    duration_seconds=result.duration_seconds,
                )
                await bead_store.update_status(bead_id, BeadStatus.FAILED)
                await coordinator.update_assignment_status(
                    bead_id, AssignmentStatus.FAILED, error_message=reason
                )
                hook = self._hook_queues.get(agent.name)
                if hook:
                    await hook.fail(bead_id, reason)

            return result

        while pending:
            ready = [
                task
                for task in pending.values()
                if all(dep in completed for dep in task.dependencies)
            ]
            if not ready:
                for task in list(pending.values()):
                    results.append(
                        TaskResult(
                            task_id=task.id,
                            success=False,
                            error="dependencies_unmet",
                        )
                    )
                break

            if not self._allow_parallel or self._max_parallel <= 1 or len(ready) == 1:
                task = ready[0]
                pending.pop(task.id, None)
                result = await run_task(task)
                results.append(result)
                if stop_on_failure and not result.success:
                    break
                continue

            batch: list[ImplementTask] = []
            used_files: set[str] = set()
            for task in ready:
                task_files = set(task.files or [])
                if not task_files:
                    if not batch:
                        batch = [task]
                    break
                if used_files & task_files:
                    continue
                batch.append(task)
                used_files.update(task_files)
                if len(batch) >= self._max_parallel:
                    break

            if not batch:
                batch = [ready[0]]

            for task in batch:
                pending.pop(task.id, None)

            batch_results = await asyncio.gather(
                *[run_task(task) for task in batch],
                return_exceptions=True,
            )
            for batch_result in batch_results:
                if isinstance(batch_result, BaseException):
                    results.append(
                        TaskResult(
                            task_id="unknown",
                            success=False,
                            error=str(batch_result),
                        )
                    )
                else:
                    results.append(batch_result)
                if (
                    stop_on_failure
                    and not isinstance(batch_result, BaseException)
                    and not batch_result.success
                ):
                    return results

        return results

    def _select_agent_for_assignment(self, agent_id: str | None) -> Any:
        if agent_id:
            for agent in self.implementers:
                if agent.name == agent_id:
                    return agent
        return self.implementers[0]

    async def _execute_task_with_agent(self, task: ImplementTask, agent: Any) -> TaskResult:
        # Use HybridExecutor to leverage its prompt and timeout logic.
        use_codex = self._is_codex_agent(agent)
        return await self._executor.execute_task(task, attempt=1, use_fallback=use_codex)

    async def _review_task(self, task: ImplementTask, implementer: Any, diff: str) -> ReviewResult:
        if not diff.strip():
            return ReviewResult(approved=True, notes="no_diff")

        reviewers = [r for r in self.reviewers if r.name != implementer.name]
        if not reviewers:
            # Fallback to codex review if configured
            try:
                codex_review = await self._executor.review_with_codex(diff)
                approved = bool(codex_review.get("approved", True))
                notes = "codex_review" if approved else "codex_blocked"
                return ReviewResult(approved=approved, notes=notes)
            except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:
                return ReviewResult(approved=True, notes=f"review_skipped:{e}")

        prompt = f"""Review the following code changes for correctness and safety.

## Task
{task.id}: {task.description}

## Diff
```
{diff[:10000]}
```

Respond with one of:
- APPROVE: <short reason>
- BLOCKER: <short reason>

Be concise. If unsure, choose APPROVE and note uncertainty.
"""

        async def review_with(agent: Any) -> str:
            try:
                return await agent.generate(prompt, context=[])
            except (RuntimeError, OSError, ConnectionError, TimeoutError) as e:
                return f"BLOCKER: review failed ({e})"

        review_tasks = [review_with(r) for r in reviewers[:2]]
        responses = await asyncio.gather(*review_tasks, return_exceptions=True)

        blocker_reasons = []
        for resp in responses:
            if isinstance(resp, Exception):
                blocker_reasons.append(str(resp))
                continue
            text = str(resp).strip().lower()
            if text.startswith("blocker"):
                blocker_reasons.append(str(resp))

        if blocker_reasons:
            return ReviewResult(approved=False, notes="; ".join(blocker_reasons)[:500])

        return ReviewResult(approved=True, notes="approved")

    async def _run_task_tests(self, task: ImplementTask) -> tuple[bool, str]:
        """Run tests for a task if enabled."""
        if not self._enable_tests:
            return True, "tests_disabled"

        command, use_shell = self._get_test_command(task)
        if not command:
            return True, "no_tests_selected"

        async with self._test_lock:
            try:
                # cast subprocess.run to Any to avoid overload resolution issues
                # with the shell parameter being a runtime value
                run_func = cast(Any, subprocess.run)
                result = await asyncio.to_thread(
                    lambda: run_func(
                        command,
                        cwd=self.repo_path,
                        capture_output=True,
                        text=True,
                        timeout=self._test_timeout,
                        shell=use_shell,
                    )
                )
            except subprocess.TimeoutExpired:
                return False, "test_timeout"
            except (OSError, subprocess.SubprocessError) as exc:
                return False, f"test_error: {exc}"

        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output[-2000:]

    def _get_test_command(self, task: ImplementTask) -> tuple[object | None, bool]:
        if self._test_command:
            return self._test_command, True

        test_files = [f for f in (task.files or []) if self._is_test_file(f)]
        if not test_files:
            return None, False

        return ["pytest", *test_files], False

    @staticmethod
    def _is_test_file(path: str) -> bool:
        normalized = path.replace("\\", "/")
        if normalized.startswith("tests/"):
            return True
        if "/tests/" in normalized:
            return True
        basename = normalized.rsplit("/", 1)[-1]
        return basename.startswith("test_") or basename.endswith("_test.py")

    @staticmethod
    def _is_codex_agent(agent: Any) -> bool:
        # Works with AirlockProxy by inspecting wrapped_agent
        wrapped = getattr(agent, "wrapped_agent", agent)
        name = getattr(wrapped, "name", "").lower()
        cls_name = wrapped.__class__.__name__.lower()
        return "codex" in name or "codex" in cls_name


__all__ = ["GastownConvoyExecutor"]
