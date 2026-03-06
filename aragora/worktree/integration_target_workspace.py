"""Dedicated integration target workspace for fleet merges."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from aragora.worktree.autopilot import resolve_repo_root


def _sanitize_path_component(value: str) -> str:
    """Normalize a path component for filesystem-safe branch directories."""
    sanitized = value.replace("\\", "-").replace("/", "-").strip()
    return sanitized or "default"


@dataclass
class FleetIntegrationTargetWorkspace:
    """Manage a dedicated clone used for fleet merge validation/execution."""

    repo_root: Path
    target_branch: str = "main"
    workspace_path: Path | None = None

    def __post_init__(self) -> None:
        self.repo_root = resolve_repo_root(self.repo_root)
        if self.workspace_path is None:
            self.workspace_path = (
                self._git_common_dir()
                / "aragora"
                / "integration-targets"
                / _sanitize_path_component(self.target_branch)
            )

    def _git_common_dir(self) -> Path:
        result = self._run_git("rev-parse", "--git-common-dir")
        common_dir = Path(result.stdout.strip())
        if common_dir.is_absolute():
            return common_dir.resolve()
        return (self.repo_root / common_dir).resolve()

    def _run_git(
        self,
        *args: str,
        cwd: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 -- fixed git command arguments
            ["git", *args],
            cwd=cwd or self.repo_root,
            capture_output=True,
            text=True,
            check=check,
        )

    def _ensure_clone(self) -> None:
        if self.workspace_path is None:
            raise RuntimeError("integration workspace path is not configured")
        if (self.workspace_path / ".git").exists():
            return
        self.workspace_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_git("clone", "--shared", str(self.repo_root), str(self.workspace_path))

    def _ensure_identity(self) -> None:
        if self.workspace_path is None:
            raise RuntimeError("integration workspace path is not configured")

        fallbacks = {
            "user.name": "Aragora Fleet Integrator",
            "user.email": "fleet@aragora.local",
        }
        for key, fallback in fallbacks.items():
            clone_value = self._run_git(
                "config", "--get", key, cwd=self.workspace_path, check=False
            ).stdout.strip()
            if clone_value:
                continue

            source_value = self._run_git("config", "--get", key, check=False).stdout.strip()
            effective_value = source_value or fallback
            self._run_git("config", key, effective_value, cwd=self.workspace_path)

    def ensure_ready(self, source_branch: str) -> Path:
        """Ensure the integration workspace is ready to validate a source branch."""
        if self.workspace_path is None:
            raise RuntimeError("integration workspace path is not configured")

        self._ensure_clone()
        self._run_git(
            "remote",
            "set-url",
            "origin",
            str(self.repo_root),
            cwd=self.workspace_path,
            check=False,
        )
        self._run_git("fetch", "origin", self.target_branch, cwd=self.workspace_path)
        self._run_git(
            "checkout",
            "-B",
            self.target_branch,
            f"origin/{self.target_branch}",
            cwd=self.workspace_path,
        )
        self._ensure_identity()

        if source_branch != self.target_branch:
            fetch_result = self._run_git(
                "fetch",
                "origin",
                f"{source_branch}:{source_branch}",
                cwd=self.workspace_path,
                check=False,
            )
            if fetch_result.returncode != 0:
                message = (fetch_result.stderr or fetch_result.stdout).strip()
                raise RuntimeError(
                    f"Failed to materialize source branch {source_branch}: {message}"
                )

        return self.workspace_path


__all__ = ["FleetIntegrationTargetWorkspace"]
