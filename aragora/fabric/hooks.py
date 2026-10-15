"""
GUPP Hook Persistence - Git worktree-backed per-agent work queues.

Implements Gastown's core persistence principle: "If there is work on your
Hook, YOU MUST RUN IT" (GUPP). Each agent has a pinned work item (hook)
backed by a git worktree so that work survives agent crashes and restarts.

Key concepts:
- Hook: A pinned work item assigned to an agent, persisted as JSONL in a
  git worktree directory.
- GUPP: On startup or patrol, scan all hooks. Any hook with pending work
  MUST be resumed by the assigned agent (or re-assigned).
- Crash recovery: If an agent dies, its hook persists on disk. The next
  patrol cycle detects it and triggers re-assignment.

Usage:
    from aragora.fabric.hooks import HookManager

    hooks = HookManager(workspace_root="/path/to/workspace")
    hook = await hooks.create_hook("agent-1", work_item)
    pending = await hooks.check_pending_hooks()
    await hooks.complete_hook(hook.hook_id, result={"output": "done"})
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# JSONL file name within each hook directory
HOOK_STATE_FILE = "hook_state.jsonl"
HOOK_RESULT_FILE = "hook_result.json"
HOOKS_DIR_NAME = ".aragora_hooks"


class HookStatus(Enum):
    """Hook lifecycle status."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


@dataclass
class Hook:
    """A pinned work item for an agent, backed by a git worktree."""

    hook_id: str
    agent_id: str
    workspace_id: str
    status: HookStatus = HookStatus.PENDING
    work_item: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    assigned_at: float | None = None
    completed_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    git_worktree_path: str | None = None
    retry_count: int = 0
    max_retries: int = 3

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Hook:
        """Deserialize from dictionary."""
        data = dict(data)
        if isinstance(data.get("status"), str):
            data["status"] = HookStatus(data["status"])
        return cls(**data)


@dataclass
class HookManagerConfig:
    """Configuration for the HookManager."""

    workspace_root: str = "."
    hooks_dir: str = HOOKS_DIR_NAME
    use_git_worktrees: bool = True
    max_retries: int = 3
    patrol_interval_seconds: float = 60.0
    stale_threshold_seconds: float = 300.0


class HookManager:
    """
    Manages GUPP hooks -- per-agent persistent work queues.

    Each hook is stored as a JSONL file in a directory under the workspace
    root. If git worktrees are enabled, each hook gets its own worktree
    for isolated file operations.

    Features:
    - Create/assign hooks to agents
    - Persist hook state to disk (JSONL)
    - GUPP patrol: scan for abandoned hooks
    - Resume or re-assign abandoned hooks
    - Complete hooks and store results
    - Git worktree isolation per hook
    """

    def __init__(self, config: HookManagerConfig | None = None) -> None:
        self._config = config or HookManagerConfig()
        self._hooks: dict[str, Hook] = {}
        self._hooks_dir = Path(self._config.workspace_root) / self._config.hooks_dir
        self._hooks_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # Hook CRUD
    # =========================================================================

    async def create_hook(
        self,
        agent_id: str,
        work_item: dict[str, Any],
        workspace_id: str = "default",
        hook_id: str | None = None,
    ) -> Hook:
        """
        Create a new hook for an agent.

        Args:
            agent_id: Agent to assign the hook to.
            work_item: Work item payload.
            workspace_id: Workspace this hook belongs to.
            hook_id: Optional custom hook ID (auto-generated if None).

        Returns:
            The created Hook.
        """
        if hook_id is None:
            hook_id = f"hk-{_short_id()}"

        now = time.time()
        hook = Hook(
            hook_id=hook_id,
            agent_id=agent_id,
            workspace_id=workspace_id,
            status=HookStatus.ASSIGNED,
            work_item=work_item,
            created_at=now,
            updated_at=now,
            assigned_at=now,
            max_retries=self._config.max_retries,
        )

        # Create hook directory and persist state
        hook_dir = self._hook_dir(hook_id)
        hook_dir.mkdir(parents=True, exist_ok=True)

        # Optionally create a git worktree
        if self._config.use_git_worktrees:
            worktree_path = self._create_worktree(hook_id)
            if worktree_path:
                hook.git_worktree_path = str(worktree_path)

        self._hooks[hook_id] = hook
        self._persist_hook(hook)

        logger.info("Created hook %s for agent %s", hook_id, agent_id)
        return hook

    async def get_hook(self, hook_id: str) -> Hook | None:
        """Get a hook by ID."""
        if hook_id in self._hooks:
            return self._hooks[hook_id]
        # Try loading from disk
        return self._load_hook(hook_id)

    async def list_hooks(
        self,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        status: HookStatus | None = None,
    ) -> list[Hook]:
        """List hooks with optional filters."""
        # Ensure all on-disk hooks are loaded
        self._load_all_hooks()

        results = []
        for hook in self._hooks.values():
            if agent_id and hook.agent_id != agent_id:
                continue
            if workspace_id and hook.workspace_id != workspace_id:
                continue
            if status and hook.status != status:
                continue
            results.append(hook)
        return results

    # =========================================================================
    # GUPP: Check and resume pending hooks
    # =========================================================================

    async def check_pending_hooks(self) -> list[Hook]:
        """
        GUPP patrol: scan all hooks and return those that need attention.

        Returns hooks that are in ASSIGNED or RUNNING state -- the agent
        MUST resume these.
        """
        self._load_all_hooks()

        pending = []
        for hook in self._hooks.values():
            if hook.status in (HookStatus.ASSIGNED, HookStatus.RUNNING):
                pending.append(hook)

        if pending:
            logger.info("GUPP patrol found %s pending hooks", len(pending))

        return pending

    async def check_stale_hooks(self) -> list[Hook]:
        """
        Find hooks that have been in ASSIGNED/RUNNING state too long.

        These are candidates for re-assignment or abandonment.
        """
        now = time.time()
        threshold = self._config.stale_threshold_seconds
        stale = []

        for hook in self._hooks.values():
            if hook.status not in (HookStatus.ASSIGNED, HookStatus.RUNNING):
                continue
            if now - hook.updated_at > threshold:
                stale.append(hook)

        if stale:
            logger.warning("Found %s stale hooks", len(stale))

        return stale

    async def resume_hook(self, hook_id: str) -> Hook | None:
        """
        Mark a hook as RUNNING (agent is actively working on it).

        Returns the updated hook, or None if not found.
        """
        hook = self._hooks.get(hook_id)
        if not hook:
            hook = self._load_hook(hook_id)
        if not hook:
            return None

        hook.status = HookStatus.RUNNING
        hook.updated_at = time.time()
        self._persist_hook(hook)

        logger.info("Resumed hook %s for agent %s", hook_id, hook.agent_id)
        return hook

    async def reassign_hook(self, hook_id: str, new_agent_id: str) -> Hook | None:
        """
        Re-assign a hook to a different agent.

        Used when the original agent has crashed or is unavailable.
        """
        hook = self._hooks.get(hook_id)
        if not hook:
            hook = self._load_hook(hook_id)
        if not hook:
            return None

        old_agent = hook.agent_id
        hook.agent_id = new_agent_id
        hook.status = HookStatus.ASSIGNED
        hook.updated_at = time.time()
        hook.assigned_at = time.time()
        hook.retry_count += 1
        self._persist_hook(hook)

        logger.info("Re-assigned hook %s from %s to %s", hook_id, old_agent, new_agent_id)
        return hook

    # =========================================================================
    # Hook completion
    # =========================================================================

    async def complete_hook(
        self,
        hook_id: str,
        result: dict[str, Any] | None = None,
    ) -> Hook | None:
        """
        Mark a hook as completed with an optional result.

        Args:
            hook_id: Hook to complete.
            result: Work result to store.

        Returns:
            The updated hook, or None if not found.
        """
        hook = self._hooks.get(hook_id)
        if not hook:
            hook = self._load_hook(hook_id)
        if not hook:
            return None

        hook.status = HookStatus.COMPLETED
        hook.completed_at = time.time()
        hook.updated_at = time.time()
        hook.result = result
        self._persist_hook(hook)

        # Write result to separate file for easy consumption
        if result:
            result_path = self._hook_dir(hook_id) / HOOK_RESULT_FILE
            result_path.write_text(json.dumps(result, indent=2, default=str))

        logger.info("Completed hook %s for agent %s", hook_id, hook.agent_id)
        return hook

    async def fail_hook(
        self,
        hook_id: str,
        error: str,
    ) -> Hook | None:
        """
        Mark a hook as failed.

        If retries remain, re-sets status to ASSIGNED for retry.
        """
        hook = self._hooks.get(hook_id)
        if not hook:
            hook = self._load_hook(hook_id)
        if not hook:
            return None

        hook.error = error
        hook.updated_at = time.time()

        if hook.retry_count < hook.max_retries:
            hook.status = HookStatus.ASSIGNED
            hook.retry_count += 1
            logger.warning(
                "Hook %s failed (retry %s/%s): %s",
                hook_id,
                hook.retry_count,
                hook.max_retries,
                error,
            )
        else:
            hook.status = HookStatus.FAILED
            hook.completed_at = time.time()
            logger.error("Hook %s permanently failed: %s", hook_id, error)

        self._persist_hook(hook)
        return hook

    async def abandon_hook(
        self,
        hook_id: str,
        reason: str = "",
    ) -> Hook | None:
        """Mark a hook as abandoned (will not be retried)."""
        hook = self._hooks.get(hook_id)
        if not hook:
            hook = self._load_hook(hook_id)
        if not hook:
            return None

        hook.status = HookStatus.ABANDONED
        hook.error = reason or "Abandoned"
        hook.completed_at = time.time()
        hook.updated_at = time.time()
        self._persist_hook(hook)

        logger.info("Abandoned hook %s: %s", hook_id, reason)
        return hook

    # =========================================================================
    # Cleanup
    # =========================================================================

    async def cleanup_completed(self, max_age_seconds: float = 86400.0) -> int:
        """
        Remove completed/failed/abandoned hooks older than max_age_seconds.

        Returns the number of hooks cleaned up.
        """
        now = time.time()
        to_remove = []

        for hook_id, hook in self._hooks.items():
            if hook.status not in (
                HookStatus.COMPLETED,
                HookStatus.FAILED,
                HookStatus.ABANDONED,
            ):
                continue
            if hook.completed_at and now - hook.completed_at > max_age_seconds:
                to_remove.append(hook_id)

        for hook_id in to_remove:
            del self._hooks[hook_id]
            self._remove_hook_dir(hook_id)

        if to_remove:
            logger.info("Cleaned up %s completed hooks", len(to_remove))

        return len(to_remove)

    # =========================================================================
    # Stats
    # =========================================================================

    async def get_stats(self) -> dict[str, Any]:
        """Get hook manager statistics."""
        self._load_all_hooks()

        by_status: dict[str, int] = {}
        for hook in self._hooks.values():
            key = hook.status.value
            by_status[key] = by_status.get(key, 0) + 1

        return {
            "total_hooks": len(self._hooks),
            "by_status": by_status,
            "hooks_dir": str(self._hooks_dir),
            "use_git_worktrees": self._config.use_git_worktrees,
        }

    # =========================================================================
    # Internal: persistence
    # =========================================================================

    def _hook_dir(self, hook_id: str) -> Path:
        """Get the directory for a hook."""
        # Prevent path traversal
        safe_id = hook_id.replace("/", "_").replace("..", "_")
        return self._hooks_dir / safe_id

    def _persist_hook(self, hook: Hook) -> None:
        """Write hook state to disk as JSONL."""
        hook_dir = self._hook_dir(hook.hook_id)
        hook_dir.mkdir(parents=True, exist_ok=True)
        state_path = hook_dir / HOOK_STATE_FILE

        # Append to JSONL (preserves history)
        line = json.dumps(hook.to_dict(), default=str)
        with open(state_path, "a") as f:
            f.write(line + "\n")

    def _load_hook(self, hook_id: str) -> Hook | None:
        """Load the latest hook state from disk."""
        hook_dir = self._hook_dir(hook_id)
        state_path = hook_dir / HOOK_STATE_FILE

        if not state_path.exists():
            return None

        try:
            # Read last line of JSONL
            lines = state_path.read_text().strip().split("\n")
            if not lines or not lines[-1].strip():
                return None
            data = json.loads(lines[-1])
            hook = Hook.from_dict(data)
            self._hooks[hook_id] = hook
            return hook
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("Failed to load hook %s: %s", hook_id, e)
            return None

    def _load_all_hooks(self) -> None:
        """Load all hooks from disk into memory."""
        if not self._hooks_dir.exists():
            return

        for entry in self._hooks_dir.iterdir():
            if entry.is_dir() and entry.name not in self._hooks:
                hook_id = entry.name
                self._load_hook(hook_id)

    def _remove_hook_dir(self, hook_id: str) -> None:
        """Remove a hook directory from disk."""
        hook_dir = self._hook_dir(hook_id)

        # If it has a worktree, remove it first
        hook = self._hooks.get(hook_id)
        if hook and hook.git_worktree_path:
            self._remove_worktree(hook_id)

        if hook_dir.exists():
            import shutil

            shutil.rmtree(hook_dir, ignore_errors=True)

    # =========================================================================
    # Internal: git worktrees
    # =========================================================================

    def _create_worktree(self, hook_id: str) -> Path | None:
        """Create a git worktree for a hook."""
        worktree_path = self._hook_dir(hook_id) / "worktree"
        branch_name = f"hook/{hook_id}"

        try:
            # Check if we're in a git repo
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],  # fixed command
                cwd=self._config.workspace_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                logger.debug("Not in a git repo, skipping worktree creation")
                return None

            # Create worktree with a new branch
            subprocess.run(  # subprocess with fixed args, no shell
                ["git", "worktree", "add", "-b", branch_name, str(worktree_path)],  # fixed command
                cwd=self._config.workspace_root,
                capture_output=True,
                text=True,
                timeout=30,
            )

            logger.debug("Created git worktree at %s", worktree_path)
            return worktree_path

        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.warning("Failed to create git worktree for hook %s: %s", hook_id, e)
            return None

    def _remove_worktree(self, hook_id: str) -> None:
        """Remove a git worktree for a hook."""
        worktree_path = self._hook_dir(hook_id) / "worktree"

        try:
            subprocess.run(  # subprocess with fixed args, no shell
                ["git", "worktree", "remove", "--force", str(worktree_path)],  # fixed command
                cwd=self._config.workspace_root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            logger.debug("Removed git worktree at %s", worktree_path)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.warning("Failed to remove git worktree for hook %s: %s", hook_id, e)


def _short_id() -> str:
    """Generate a short random ID (5 chars, Gastown bead convention)."""
    import hashlib

    return hashlib.sha256(str(time.time()).encode()).hexdigest()[:5]
