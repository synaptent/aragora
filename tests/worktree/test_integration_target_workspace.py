"""Tests for the dedicated fleet integration target workspace."""

from __future__ import annotations

import subprocess
from pathlib import Path

from aragora.worktree.integration_target_workspace import FleetIntegrationTargetWorkspace


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed command arguments in tests
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(cwd, "git", *args)


def _make_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "checkout", "-b", "feature/test")
    (repo / "feature.py").write_text("VALUE = 1\n")
    _git(repo, "add", "feature.py")
    _git(repo, "commit", "-m", "feature")
    _git(repo, "checkout", "main")
    return repo


def test_ensure_ready_clones_repo_and_materializes_source_branch(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path)
    workspace = FleetIntegrationTargetWorkspace(repo_root=repo, target_branch="main")

    clone_path = workspace.ensure_ready(source_branch="feature/test")

    assert clone_path.exists()
    current_branch = _git(clone_path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert current_branch == "main"
    source_branch_exists = _git(clone_path, "show-ref", "--verify", "refs/heads/feature/test")
    assert source_branch_exists.returncode == 0


def test_ensure_ready_defaults_workspace_under_git_common_dir(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path)
    workspace = FleetIntegrationTargetWorkspace(repo_root=repo, target_branch="main")

    clone_path = workspace.ensure_ready(source_branch="feature/test")
    common_dir = _git(repo, "rev-parse", "--git-common-dir").stdout.strip()
    common_dir_path = (repo / common_dir).resolve()

    assert str(clone_path).startswith(str(common_dir_path))
