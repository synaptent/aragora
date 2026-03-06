"""Worker launcher for supervised swarm runs.

Spawns Claude Code or Codex CLI processes in provisioned worktrees,
reusing the managed-session wrapper so worktree locks/logs stay coherent.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any

logger = logging.getLogger(__name__)

UTC = timezone.utc


@dataclass(slots=True)
class WorkerProcess:
    """Tracks a running worker subprocess."""

    work_order_id: str
    agent: str
    worktree_path: str
    branch: str
    pid: int | None = None
    session_id: str = ""
    lease_id: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at: str | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    diff: str = ""
    initial_head: str = ""
    head_sha: str = ""
    commit_shas: list[str] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)

    @property
    def is_running(self) -> bool:
        return self.exit_code is None and self.pid is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "agent": self.agent,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "pid": self.pid,
            "session_id": self.session_id,
            "lease_id": self.lease_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "exit_code": self.exit_code,
            "head_sha": self.head_sha,
            "commit_shas": list(self.commit_shas),
            "changed_paths": list(self.changed_paths),
        }


@dataclass(slots=True)
class LaunchConfig:
    """Configuration for worker launches."""

    claude_path: str = "claude"
    codex_path: str = "codex"
    timeout_seconds: float = 600.0
    claude_model: str | None = None
    codex_model: str | None = None
    auto_commit: bool = True
    use_managed_session_script: bool = True
    base_branch: str = "main"


class WorkerLauncher:
    """Launch and monitor Claude Code / Codex worker processes."""

    def __init__(self, config: LaunchConfig | None = None) -> None:
        self.config = config or LaunchConfig()
        self._workers: dict[str, WorkerProcess] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    async def launch(
        self,
        work_order: dict[str, Any],
        *,
        worktree_path: str,
        branch: str = "main",
    ) -> WorkerProcess:
        """Launch a worker process for a work order."""
        work_order_id = str(work_order.get("work_order_id", "unknown"))
        agent = str(work_order.get("target_agent", "claude")).strip() or "claude"
        prompt = self._build_prompt(work_order)
        session_id = str(work_order.get("owner_session_id", "")).strip()
        lease_id = str(work_order.get("lease_id", "")).strip()

        cmd = self._build_command(
            agent,
            prompt,
            worktree_path,
            session_id=session_id,
        )
        if not cmd:
            raise RuntimeError(f"Cannot build launch command for agent={agent}")

        self._validate_launch_command(cmd, agent)
        initial_head = await self._git_output(worktree_path, "rev-parse", "HEAD")

        logger.info(
            "Launching %s worker for %s in %s",
            agent,
            work_order_id,
            worktree_path,
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        worker = WorkerProcess(
            work_order_id=work_order_id,
            agent=agent,
            worktree_path=worktree_path,
            branch=branch,
            pid=proc.pid,
            session_id=session_id,
            lease_id=lease_id,
            initial_head=initial_head,
            tests_run=[
                str(item) for item in work_order.get("expected_tests", []) if str(item).strip()
            ],
            command=list(cmd),
        )
        self._workers[work_order_id] = worker
        self._processes[work_order_id] = proc
        return worker

    async def wait(
        self,
        work_order_id: str,
        *,
        timeout: float | None = None,
    ) -> WorkerProcess:
        """Wait for a worker to complete and collect results."""
        worker = self._workers.get(work_order_id)
        proc = self._processes.get(work_order_id)
        if worker is None or proc is None:
            raise KeyError(f"No running worker for {work_order_id}")

        effective_timeout = timeout or self.config.timeout_seconds

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=effective_timeout,
            )
            worker.exit_code = proc.returncode
            worker.stdout = stdout_bytes.decode(errors="replace")
            worker.stderr = stderr_bytes.decode(errors="replace")
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            worker.exit_code = -1
            worker.stderr = f"Timed out after {effective_timeout}s"
            logger.warning("Worker %s timed out", work_order_id)

        worker.completed_at = datetime.now(UTC).isoformat()
        worker.diff = await self._collect_diff(worker.worktree_path)

        if self.config.auto_commit and worker.diff and worker.exit_code == 0:
            await self._auto_commit(worker)

        worker.head_sha = await self._git_output(worker.worktree_path, "rev-parse", "HEAD")
        worker.commit_shas = await self._collect_commit_shas(
            worker.worktree_path,
            initial_head=worker.initial_head,
            head_sha=worker.head_sha,
        )
        worker.changed_paths = await self._collect_changed_paths(
            worker.worktree_path,
            initial_head=worker.initial_head,
            head_sha=worker.head_sha,
        )

        logger.info(
            "Worker %s completed: exit=%s commits=%d changed_paths=%d",
            work_order_id,
            worker.exit_code,
            len(worker.commit_shas),
            len(worker.changed_paths),
        )

        self._processes.pop(work_order_id, None)
        return worker

    async def collect_finished(
        self,
        *,
        work_order_ids: list[str] | None = None,
        poll_timeout: float = 0.01,
    ) -> list[WorkerProcess]:
        """Collect only workers that have already finished."""
        completed: list[WorkerProcess] = []
        ids = work_order_ids or list(self._processes.keys())
        for work_order_id in ids:
            proc = self._processes.get(work_order_id)
            if proc is None:
                continue
            finished = proc.returncode is not None
            if not finished:
                try:
                    await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=poll_timeout)
                    finished = True
                except asyncio.TimeoutError:
                    finished = False
            if finished:
                completed.append(await self.wait(work_order_id, timeout=max(poll_timeout, 0.1)))
        return completed

    async def launch_and_wait(
        self,
        work_order: dict[str, Any],
        *,
        worktree_path: str,
        branch: str = "main",
    ) -> WorkerProcess:
        """Launch a worker and wait for it to complete."""
        worker = await self.launch(
            work_order,
            worktree_path=worktree_path,
            branch=branch,
        )
        return await self.wait(worker.work_order_id)

    def get_worker(self, work_order_id: str) -> WorkerProcess | None:
        return self._workers.get(work_order_id)

    def active_workers(self) -> list[WorkerProcess]:
        return [w for w in self._workers.values() if w.is_running]

    def _build_command(
        self,
        agent: str,
        prompt: str,
        worktree_path: str,
        *,
        session_id: str = "",
    ) -> list[str]:
        """Build the launch command for the given agent type."""
        inner = self._build_agent_command(agent, prompt)
        if not self.config.use_managed_session_script:
            return inner

        session_script = Path(worktree_path).resolve() / "scripts" / "codex_session.sh"
        managed_dir = str(Path(worktree_path).resolve().parent)
        cmd = [
            "bash",
            str(session_script),
            "--agent",
            agent,
            "--base",
            self.config.base_branch,
            "--managed-dir",
            managed_dir,
            "--no-maintain",
            "--no-reconcile",
        ]
        if session_id:
            cmd.extend(["--session-id", session_id])
        cmd.append("--")
        cmd.extend(inner)
        return cmd

    def _build_agent_command(self, agent: str, prompt: str) -> list[str]:
        if agent == "claude":
            cmd = [self.config.claude_path, "-p", prompt, "--yes"]
            if self.config.claude_model:
                cmd.extend(["--model", self.config.claude_model])
            return cmd

        if agent == "codex":
            cmd = [self.config.codex_path, "exec", prompt, "--full-auto"]
            if self.config.codex_model:
                cmd.extend(["--model", self.config.codex_model])
            return cmd

        logger.warning("Unknown agent %r, falling back to claude", agent)
        return [self.config.claude_path, "-p", prompt, "--yes"]

    def _validate_launch_command(self, cmd: list[str], agent: str) -> None:
        if not cmd:
            raise RuntimeError("Empty launch command")
        if self.config.use_managed_session_script:
            inner_cli = self.config.claude_path if agent == "claude" else self.config.codex_path
            if agent not in {"claude", "codex"}:
                inner_cli = self.config.claude_path
            if not shutil.which(inner_cli):
                raise FileNotFoundError(f"{inner_cli} CLI not found on PATH")
            session_script = Path(cmd[1]) if len(cmd) > 1 else None
            if session_script is None or not session_script.exists():
                raise FileNotFoundError(f"session script not found: {session_script}")
            return

        cli_path = cmd[0]
        if not shutil.which(cli_path):
            raise FileNotFoundError(f"{cli_path} CLI not found on PATH")

    @staticmethod
    def _build_prompt(work_order: dict[str, Any]) -> str:
        """Build the task prompt from a work order dict."""
        parts: list[str] = []

        title = str(work_order.get("title", "")).strip()
        if title:
            parts.append(f"# Task: {title}")

        description = str(work_order.get("description", "")).strip()
        if description:
            parts.append(description)

        file_scope = work_order.get("file_scope", [])
        if file_scope:
            scope_list = ", ".join(str(f) for f in file_scope)
            parts.append(f"Files in scope: {scope_list}")

        expected_tests = work_order.get("expected_tests", [])
        if expected_tests:
            tests_text = "\n".join(f"  - {t}" for t in expected_tests)
            parts.append(f"Run these tests to verify:\n{tests_text}")

        metadata = work_order.get("metadata", {})
        acceptance = metadata.get("acceptance_criteria", [])
        if acceptance:
            criteria_text = "\n".join(f"  - {c}" for c in acceptance)
            parts.append(f"Acceptance criteria:\n{criteria_text}")

        constraints = metadata.get("constraints", [])
        if constraints:
            constraints_text = "\n".join(f"  - {c}" for c in constraints)
            parts.append(f"Constraints:\n{constraints_text}")

        parts.append(
            "After completing the task, run the tests listed above to verify "
            "your changes work correctly. Commit your changes with a descriptive message."
        )

        return "\n\n".join(parts)

    @staticmethod
    async def _git_output(worktree_path: str, *args: str) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                *args,
                cwd=worktree_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                return ""
            return stdout.decode(errors="replace").strip()
        except (asyncio.TimeoutError, FileNotFoundError, OSError):
            return ""

    @classmethod
    async def _collect_diff(cls, worktree_path: str) -> str:
        return await cls._git_output(worktree_path, "diff", "HEAD")

    @classmethod
    async def _collect_commit_shas(
        cls,
        worktree_path: str,
        *,
        initial_head: str,
        head_sha: str,
    ) -> list[str]:
        if not initial_head or not head_sha or initial_head == head_sha:
            return []
        output = await cls._git_output(
            worktree_path, "rev-list", "--reverse", f"{initial_head}..{head_sha}"
        )
        return [line.strip() for line in output.splitlines() if line.strip()]

    @classmethod
    async def _collect_changed_paths(
        cls,
        worktree_path: str,
        *,
        initial_head: str,
        head_sha: str,
    ) -> list[str]:
        changed: set[str] = set()
        if initial_head and head_sha and initial_head != head_sha:
            diff_names = await cls._git_output(
                worktree_path,
                "diff",
                "--name-only",
                f"{initial_head}..{head_sha}",
            )
            changed.update(line.strip() for line in diff_names.splitlines() if line.strip())

        status_output = await cls._git_output(worktree_path, "status", "--porcelain")
        for line in status_output.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].strip()
            if " -> " in path:
                path = path.split(" -> ")[-1].strip()
            if path:
                changed.add(path)
        return sorted(changed)

    @staticmethod
    async def _auto_commit(worker: WorkerProcess) -> None:
        """Auto-commit changes in the worktree if any."""
        try:
            add_proc = await asyncio.create_subprocess_exec(
                "git",
                "add",
                "-A",
                cwd=worker.worktree_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(add_proc.communicate(), timeout=10)

            msg = f"feat(swarm): {worker.agent} completed {worker.work_order_id}"
            commit_proc = await asyncio.create_subprocess_exec(
                "git",
                "commit",
                "-m",
                msg,
                "--allow-empty",
                cwd=worker.worktree_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(commit_proc.communicate(), timeout=10)
        except (asyncio.TimeoutError, FileNotFoundError, OSError) as exc:
            logger.warning("Auto-commit failed for %s: %s", worker.work_order_id, exc)
