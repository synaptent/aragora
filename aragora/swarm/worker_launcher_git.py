"""Git working-tree inspection for ``WorkerLauncher``.

``WorkerLauncher`` (``aragora.swarm.worker_launcher``) inherits these helpers: dirty-tree
checks, diffs, commit SHAs and changed paths, each in an async and a sync form. Import
the launcher from ``aragora.swarm.worker_launcher``.
"""

from __future__ import annotations

import asyncio
import subprocess

from aragora.swarm.worker_process import is_ignored_changed_path


class WorkerLauncherGitMixin:
    """Git inspection helpers inherited by ``WorkerLauncher``."""

    @staticmethod
    def _strip_session_artifacts(paths: set[str]) -> list[str]:
        """Normalize changed paths by removing harness/runtime-owned artifacts."""
        return sorted(path for path in paths if not is_ignored_changed_path(path))

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
            return stdout.decode(errors="replace").rstrip()
        except (asyncio.TimeoutError, FileNotFoundError, OSError):
            return ""

    @staticmethod
    def _git_output_sync(worktree_path: str, *args: str) -> str:
        try:
            proc = subprocess.run(
                ["git", *args],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ""
        if proc.returncode != 0:
            return ""
        return proc.stdout.rstrip()

    @classmethod
    async def _has_working_tree_changes(cls, worktree_path: str) -> bool:
        """Check for real (non-artifact) working-tree changes via git status.

        This is a robust fallback for ``_collect_diff`` which relies on
        ``git diff HEAD`` — that command can return empty on timeout, error,
        or when only binary files changed.  ``git status --porcelain`` is
        cheaper and more reliable for a yes/no dirty-tree check.
        """
        # Expand untracked directories into file paths so docs-only tasks that
        # create new trees still qualify as concrete deliverables.
        status = await cls._git_output(
            worktree_path,
            "status",
            "--porcelain",
            "--untracked-files=all",
        )
        for line in status.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].strip()
            if path and not is_ignored_changed_path(path):
                return True
        return False

    @classmethod
    def _has_working_tree_changes_sync(cls, worktree_path: str) -> bool:
        status = cls._git_output_sync(
            worktree_path,
            "status",
            "--porcelain",
            "--untracked-files=all",
        )
        for line in status.splitlines():
            if len(line) < 4:
                continue
            path = line[3:].strip()
            if path and not is_ignored_changed_path(path):
                return True
        return False

    @classmethod
    async def _collect_diff(cls, worktree_path: str) -> str:
        return await cls._git_output(worktree_path, "diff", "HEAD")

    @classmethod
    def _collect_diff_sync(cls, worktree_path: str) -> str:
        return cls._git_output_sync(worktree_path, "diff", "HEAD")

    @classmethod
    async def _collect_commit_shas(
        cls,
        worktree_path: str,
        *,
        initial_head: str,
        head_sha: str,
    ) -> list[str]:
        if not head_sha:
            return []

        # Primary path: compare initial_head to current HEAD
        if initial_head and initial_head != head_sha:
            output = await cls._git_output(
                worktree_path, "rev-list", "--reverse", f"{initial_head}..{head_sha}"
            )
            shas = [line.strip() for line in output.splitlines() if line.strip()]
            if shas:
                return shas

        # Fail closed when initial_head is missing or unchanged. Falling back
        # to origin/main can misattribute pre-existing branch commits to the
        # current worker when the lane starts from stale or non-main history.
        return []

    @classmethod
    def _collect_commit_shas_sync(
        cls,
        worktree_path: str,
        *,
        initial_head: str,
        head_sha: str,
    ) -> list[str]:
        if not head_sha:
            return []

        if initial_head and initial_head != head_sha:
            output = cls._git_output_sync(
                worktree_path, "rev-list", "--reverse", f"{initial_head}..{head_sha}"
            )
            shas = [line.strip() for line in output.splitlines() if line.strip()]
            if shas:
                return shas

        # Fail closed when initial_head is missing or unchanged. Falling back
        # to origin/main can misattribute pre-existing branch commits to the
        # current worker when the lane starts from stale or non-main history.
        return []

    @classmethod
    async def _collect_changed_paths(
        cls,
        worktree_path: str,
        *,
        initial_head: str,
        head_sha: str,
    ) -> list[str]:
        changed: set[str] = set()
        diff_range = ""
        if initial_head and head_sha and initial_head != head_sha:
            diff_range = f"{initial_head}..{head_sha}"
        if diff_range:
            diff_names = await cls._git_output(
                worktree_path,
                "diff",
                "--name-only",
                diff_range,
            )
            changed.update(line.strip() for line in diff_names.splitlines() if line.strip())

        # _git_output() strips the whole output, which can eat the leading
        # space from porcelain status lines like " M docs/file.py".  Parse
        # robustly: skip the first two status characters if the line matches
        # the XY+space pattern, otherwise fall back to lstrip-after-status.
        status_output = await cls._git_output(
            worktree_path,
            "status",
            "--porcelain",
            "--untracked-files=all",
        )
        for line in status_output.splitlines():
            if not line or len(line) < 2:
                continue
            # Porcelain v1: XY<space>PATH  (3 chars prefix when both X,Y present)
            # After .strip(), a leading-space status " M" becomes "M" — only
            # 2 chars before the path.  Detect by checking whether position 2
            # is a space (full prefix) or part of the path (stripped prefix).
            if len(line) > 2 and line[2] == " ":
                path = line[3:].strip()
            else:
                # Stripped leading space: "M docs/..." or "?? docs/..."
                # Find the first space after the status chars.
                first_space = line.find(" ")
                if first_space < 0:
                    continue
                path = line[first_space + 1 :].strip()
            if " -> " in path:
                path = path.split(" -> ")[-1].strip()
            if path:
                changed.add(path)
        # Strip session artifacts — these are harness metadata, not deliverables
        return cls._strip_session_artifacts(changed)

    @classmethod
    def _collect_changed_paths_sync(
        cls,
        worktree_path: str,
        *,
        initial_head: str,
        head_sha: str,
    ) -> list[str]:
        changed: set[str] = set()
        diff_range = ""
        if initial_head and head_sha and initial_head != head_sha:
            diff_range = f"{initial_head}..{head_sha}"
        if diff_range:
            diff_names = cls._git_output_sync(
                worktree_path,
                "diff",
                "--name-only",
                diff_range,
            )
            changed.update(line.strip() for line in diff_names.splitlines() if line.strip())

        status_output = cls._git_output_sync(
            worktree_path,
            "status",
            "--porcelain",
            "--untracked-files=all",
        )
        for line in status_output.splitlines():
            if not line or len(line) < 2:
                continue
            if len(line) > 2 and line[2] == " ":
                path = line[3:].strip()
            else:
                first_space = line.find(" ")
                if first_space < 0:
                    continue
                path = line[first_space + 1 :].strip()
            if " -> " in path:
                path = path.split(" -> ")[-1].strip()
            if path:
                changed.add(path)
        return cls._strip_session_artifacts(changed)
