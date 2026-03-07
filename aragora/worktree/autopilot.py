"""Canonical Python interface for codex worktree autopilot operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys

AUTOPILOT_ACTIONS = ("ensure", "reconcile", "cleanup", "maintain", "status")
AUTOPILOT_STRATEGIES = ("merge", "rebase", "ff-only", "none")


@dataclass(slots=True)
class AutopilotRequest:
    """Normalized request schema for autopilot actions."""

    action: str = "status"
    managed_dir: str = ".worktrees/codex-auto"
    base_branch: str = "main"
    agent: str = "codex"
    session_id: str | None = None
    force_new: bool = False
    strategy: str = "ff-only"
    reconcile: bool = False
    reconcile_all: bool = False
    path: str | None = None
    ttl_hours: int = 24
    force_unmerged: bool = False
    delete_branches: bool | None = None
    json_output: bool = False
    print_path: bool = False


def resolve_repo_root(path: Path) -> Path:
    """Resolve a repository root from any path inside the repo."""
    proc = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],  # noqa: S607 -- fixed command
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip()).resolve()
    return path.resolve()


def autopilot_script_path(repo_root: Path) -> Path:
    return repo_root / "scripts" / "codex_worktree_autopilot.py"


def build_autopilot_command(
    *,
    repo_root: Path,
    request: AutopilotRequest,
    python_executable: str | None = None,
) -> list[str]:
    """Build argv for an autopilot request."""
    if request.action not in AUTOPILOT_ACTIONS:
        raise ValueError(f"Unsupported autopilot action: {request.action}")
    if request.strategy not in AUTOPILOT_STRATEGIES:
        raise ValueError(f"Unsupported autopilot strategy: {request.strategy}")

    script_path = autopilot_script_path(repo_root)
    cmd = [
        python_executable or sys.executable,
        str(script_path),
        "--repo",
        str(repo_root),
        "--managed-dir",
        request.managed_dir,
        request.action,
    ]

    if request.action == "ensure":
        cmd.extend(
            [
                "--agent",
                request.agent,
                "--base",
                request.base_branch,
                "--strategy",
                request.strategy,
            ]
        )
        if request.session_id:
            cmd.extend(["--session-id", request.session_id])
        if request.force_new:
            cmd.append("--force-new")
        if request.reconcile:
            cmd.append("--reconcile")
        if request.print_path:
            cmd.append("--print-path")
        if request.json_output:
            cmd.append("--json")

    elif request.action == "reconcile":
        cmd.extend(
            [
                "--base",
                request.base_branch,
                "--strategy",
                request.strategy,
                "--ttl-hours",
                str(request.ttl_hours),
            ]
        )
        if request.reconcile_all:
            cmd.append("--all")
        if request.path:
            cmd.extend(["--path", request.path])
        if request.json_output:
            cmd.append("--json")

    elif request.action == "cleanup":
        cmd.extend(["--base", request.base_branch, "--ttl-hours", str(request.ttl_hours)])
        if request.force_unmerged:
            cmd.append("--force-unmerged")
        if request.delete_branches is True:
            cmd.append("--delete-branches")
        elif request.delete_branches is False:
            cmd.append("--no-delete-branches")
        if request.json_output:
            cmd.append("--json")

    elif request.action == "maintain":
        cmd.extend(
            [
                "--base",
                request.base_branch,
                "--strategy",
                request.strategy,
                "--ttl-hours",
                str(request.ttl_hours),
            ]
        )
        if request.force_unmerged:
            cmd.append("--force-unmerged")
        if request.delete_branches is True:
            cmd.append("--delete-branches")
        elif request.delete_branches is False:
            cmd.append("--no-delete-branches")
        if request.json_output:
            cmd.append("--json")

    elif request.action == "status":
        cmd.extend(["--ttl-hours", str(request.ttl_hours)])
        if request.json_output:
            cmd.append("--json")

    return cmd


def run_autopilot(
    *,
    repo_root: Path,
    request: AutopilotRequest,
    python_executable: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an autopilot request and return the subprocess result."""
    script_path = autopilot_script_path(repo_root)
    if not script_path.exists():
        raise FileNotFoundError(str(script_path))

    cmd = build_autopilot_command(
        repo_root=repo_root,
        request=request,
        python_executable=python_executable,
    )
    return subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
