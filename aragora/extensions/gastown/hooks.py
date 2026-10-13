"""
Hook Runner - Git Worktree Persistence.

Manages git hooks for persistent storage of agent state.
Enables disaster recovery and session persistence via worktrees.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
import hashlib
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aragora.nomic.stores.paths import resolve_store_dir
from aragora.worktree.lifecycle import WorktreeLifecycleService
from .models import Hook, HookType

logger = logging.getLogger(__name__)


class HookRunner:
    """
    Manages git hooks for persistent state storage.

    Hooks store agent state in git worktrees, enabling persistence
    across sessions and disaster recovery via commits.
    """

    def __init__(
        self,
        storage_path: str | Path | None = None,
        auto_commit: bool = True,
    ) -> None:
        """
        Initialize the hook runner.

        Args:
            storage_path: Path for hook metadata storage
            auto_commit: Auto-commit state changes
        """
        base_path = Path(storage_path) if storage_path else resolve_store_dir()
        self._storage_path = base_path
        self._state_path = self._storage_path / "hooks.json"
        self._auto_commit = auto_commit
        self._hooks: dict[str, Hook] = {}
        self._lock = asyncio.Lock()

        self._storage_path.mkdir(parents=True, exist_ok=True)
        self._load_state()

    def _hook_to_dict(self, hook: Hook) -> dict[str, Any]:
        data = asdict(hook)
        data["type"] = hook.type.value
        data["created_at"] = hook.created_at.isoformat()
        data["updated_at"] = hook.updated_at.isoformat()
        data["last_triggered"] = hook.last_triggered.isoformat() if hook.last_triggered else None
        return data

    def _hook_from_dict(self, data: dict[str, Any]) -> Hook:
        payload = dict(data)
        payload["type"] = HookType(payload["type"])
        created_at = payload.get("created_at")
        updated_at = payload.get("updated_at")
        last_triggered = payload.get("last_triggered")
        if isinstance(created_at, str):
            payload["created_at"] = datetime.fromisoformat(created_at)
        if isinstance(updated_at, str):
            payload["updated_at"] = datetime.fromisoformat(updated_at)
        if isinstance(last_triggered, str):
            payload["last_triggered"] = datetime.fromisoformat(last_triggered)
        return Hook(**payload)

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            payload = json.loads(self._state_path.read_text())
        except json.JSONDecodeError:
            logger.warning("Gastown hook state is corrupted; ignoring %s", self._state_path)
            return
        for hook_data in payload.get("hooks", []):
            try:
                hook = self._hook_from_dict(hook_data)
            except (KeyError, TypeError, ValueError):
                continue
            self._hooks[hook.id] = hook

    def _save_state(self) -> None:
        payload = {"hooks": [self._hook_to_dict(h) for h in self._hooks.values()]}
        self._state_path.write_text(json.dumps(payload, indent=2))

    async def create_hook(
        self,
        rig_id: str,
        hook_type: HookType,
        path: str,
        content: str = "",
        enabled: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> Hook:
        """
        Create a new git hook.

        Args:
            rig_id: Parent rig ID
            hook_type: Type of git hook
            path: Path to hook script
            content: Hook script content
            enabled: Whether hook is enabled
            metadata: Additional metadata

        Returns:
            Created hook
        """
        async with self._lock:
            hook_id = str(uuid.uuid4())

            hook = Hook(
                id=hook_id,
                rig_id=rig_id,
                type=hook_type,
                path=path,
                content=content,
                enabled=enabled,
                metadata=metadata or {},
            )

            self._hooks[hook_id] = hook
            self._save_state()

            # Write hook script if content provided
            if content:
                await self._write_hook_script(path, content)

            logger.info("Created %s hook (%s)", hook_type.value, hook_id)
            return hook

    async def get_hook(self, hook_id: str) -> Hook | None:
        """Get a hook by ID."""
        return self._hooks.get(hook_id)

    async def list_hooks(
        self,
        rig_id: str | None = None,
        hook_type: HookType | None = None,
        enabled: bool | None = None,
    ) -> list[Hook]:
        """List hooks with optional filters."""
        hooks = list(self._hooks.values())

        if rig_id:
            hooks = [h for h in hooks if h.rig_id == rig_id]
        if hook_type:
            hooks = [h for h in hooks if h.type == hook_type]
        if enabled is not None:
            hooks = [h for h in hooks if h.enabled == enabled]

        return hooks

    async def update_hook(
        self,
        hook_id: str,
        content: str | None = None,
        enabled: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Hook | None:
        """Update a hook."""
        async with self._lock:
            hook = self._hooks.get(hook_id)
            if not hook:
                return None

            if content is not None:
                hook.content = content
                await self._write_hook_script(hook.path, content)

            if enabled is not None:
                hook.enabled = enabled

            if metadata is not None:
                hook.metadata.update(metadata)

            hook.updated_at = datetime.now(timezone.utc)
            self._save_state()
            return hook

    async def delete_hook(self, hook_id: str) -> bool:
        """Delete a hook."""
        async with self._lock:
            hook = self._hooks.get(hook_id)
            if not hook:
                return False

            # Remove hook script
            hook_path = Path(hook.path)
            if hook_path.exists():
                hook_path.unlink()

            del self._hooks[hook_id]
            self._save_state()
            logger.info("Deleted hook %s", hook_id)
            return True

    async def trigger_hook(
        self,
        hook_id: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Trigger a hook execution.

        Args:
            hook_id: Hook to trigger
            context: Execution context

        Returns:
            Execution result
        """
        async with self._lock:
            hook = self._hooks.get(hook_id)
            if not hook:
                return {"success": False, "error": "Hook not found"}

            if not hook.enabled:
                return {"success": False, "error": "Hook is disabled"}

            hook.last_triggered = datetime.now(timezone.utc)
            hook.trigger_count += 1
            hook.updated_at = datetime.now(timezone.utc)
            self._save_state()

        # Execute hook script
        result = await self._execute_hook(hook, context or {})

        logger.debug("Triggered hook %s: %s", hook_id, result.get("success"))
        return result

    async def _write_hook_script(self, path: str, content: str) -> None:
        """Write hook script to disk."""
        hook_path = Path(path)
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        hook_path.write_text(content)
        # Make executable
        os.chmod(hook_path, 0o755)  # nosec B103 - Git hooks must be executable

    async def _execute_hook(
        self,
        hook: Hook,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a hook script."""
        hook_path = Path(hook.path)
        if not hook_path.exists():
            return {"success": False, "error": f"Hook script not found: {hook.path}"}

        try:
            # Set up environment with context
            env = os.environ.copy()
            for key, value in context.items():
                env[f"HOOK_{key.upper()}"] = str(value)

            # Run hook script
            result = await asyncio.to_thread(
                subprocess.run,
                [str(hook_path)],
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
            )

            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Hook execution timed out"}
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            logger.warning("Hook execution failed: %s", e)
            return {"success": False, "error": "Hook execution failed"}

    async def persist_state(
        self,
        rig_id: str,
        state: dict[str, Any],
        message: str = "Auto-persist state",
    ) -> dict[str, Any]:
        """
        Persist agent state to git worktree.

        Args:
            rig_id: Rig to persist state for
            state: State data to persist
            message: Commit message

        Returns:
            Persistence result
        """
        if not self._storage_path:
            return {"success": False, "error": "No storage path configured"}

        state_path = self._storage_path / rig_id / "state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)

        import json

        state_json = json.dumps(state, indent=2, default=str)
        state_path.write_text(state_json)

        # Compute hash for integrity
        state_hash = hashlib.sha256(state_json.encode()).hexdigest()[:12]

        result = {
            "success": True,
            "path": str(state_path),
            "hash": state_hash,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Auto-commit if enabled and in a git repo
        if self._auto_commit:
            commit_result = await self._git_commit(state_path, message)
            result["committed"] = commit_result.get("success", False)

        logger.debug("Persisted state for rig %s: %s", rig_id, state_hash)
        return result

    async def restore_state(self, rig_id: str) -> dict[str, Any] | None:
        """
        Restore agent state from git worktree.

        Args:
            rig_id: Rig to restore state for

        Returns:
            Restored state or None if not found
        """
        if not self._storage_path:
            return None

        state_path = self._storage_path / rig_id / "state.json"
        if not state_path.exists():
            return None

        import json

        state = json.loads(state_path.read_text())
        logger.debug("Restored state for rig %s", rig_id)
        return state

    async def _git_commit(
        self,
        path: Path,
        message: str,
    ) -> dict[str, Any]:
        """Commit a file to git."""
        try:
            repo_dir = path.parent

            # Check if in a git repo
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "rev-parse", "--git-dir"],
                capture_output=True,
                cwd=repo_dir,
            )
            if result.returncode != 0:
                return {"success": False, "error": "Not a git repository"}

            # Stage the file
            await asyncio.to_thread(
                subprocess.run,
                ["git", "add", str(path)],
                capture_output=True,
                cwd=repo_dir,
            )

            # Commit
            result = await asyncio.to_thread(
                subprocess.run,
                ["git", "commit", "-m", message],
                capture_output=True,
                text=True,
                cwd=repo_dir,
            )

            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            logger.warning("Git commit failed: %s", e)
            return {"success": False, "error": "Git commit failed"}

    async def create_worktree(
        self,
        repo_path: str,
        worktree_path: str,
        branch: str,
    ) -> dict[str, Any]:
        """
        Create a git worktree.

        Args:
            repo_path: Path to main repository
            worktree_path: Path for the worktree
            branch: Branch name for worktree

        Returns:
            Creation result
        """
        try:
            repo = Path(repo_path)
            worktree = Path(worktree_path)

            if worktree.exists():
                return {"success": False, "error": "Worktree path already exists"}

            lifecycle = WorktreeLifecycleService(repo_root=repo)
            result = await asyncio.to_thread(
                lifecycle.create_worktree,
                worktree_path=worktree,
                ref=branch,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": result.stderr or "Failed to create worktree",
                }

            logger.info("Created worktree at %s", worktree_path)
            return {
                "success": True,
                "worktree_path": str(worktree),
                "branch": branch,
            }

        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            logger.warning("Worktree creation failed: %s", e)
            return {"success": False, "error": "Worktree creation failed"}

    async def remove_worktree(self, worktree_path: str) -> dict[str, Any]:
        """Remove a git worktree."""
        try:
            worktree = Path(worktree_path)

            if not worktree.exists():
                return {"success": False, "error": "Worktree does not exist"}

            lifecycle = WorktreeLifecycleService(repo_root=Path.cwd())
            result = await asyncio.to_thread(
                lifecycle.remove_worktree,
                worktree_path=worktree,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": result.stderr or "Failed to remove worktree",
                }

            logger.info("Removed worktree at %s", worktree_path)
            return {"success": True}

        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            logger.warning("Worktree removal failed: %s", e)
            return {"success": False, "error": "Worktree removal failed"}

    async def get_stats(self) -> dict[str, Any]:
        """Get hook runner statistics."""
        async with self._lock:
            by_type: dict[str, int] = {}
            total_triggers = 0
            enabled_count = 0

            for hook in self._hooks.values():
                hook_type = hook.type.value
                by_type[hook_type] = by_type.get(hook_type, 0) + 1
                total_triggers += hook.trigger_count
                if hook.enabled:
                    enabled_count += 1

            return {
                "hooks_total": len(self._hooks),
                "hooks_enabled": enabled_count,
                "hooks_by_type": by_type,
                "total_triggers": total_triggers,
            }
