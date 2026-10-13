"""Worktree Auditor.

Validates worktree configuration, health, and isolation. Checks that
default paths exist, permissions are correct, disk space is sufficient,
and no shared state leaks between worktrees.

Usage:
    from aragora.nomic.worktree_auditor import WorktreeAuditor, AuditorConfig

    auditor = WorktreeAuditor(repo_path=Path("."))
    report = auditor.audit()
    for finding in report.findings:
        print(f"[{finding.severity}] {finding.message}")

    # Get status of all worktrees
    statuses = auditor.get_status()

    # Validate isolation between worktrees
    isolation_ok = auditor.validate_isolation()
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AuditorConfig:
    """Configuration for WorktreeAuditor."""

    # Minimum free disk space in bytes (default: 500 MB)
    min_disk_space_bytes: int = 500 * 1024 * 1024
    # Expected permissions for worktree directories (octal)
    expected_dir_permissions: int = 0o755
    # Files that should NOT be shared between worktrees (isolation check)
    isolation_files: list[str] = field(
        default_factory=lambda: [
            ".env",
            ".aragora_beads",
            ".aragora_events",
            "node_modules",
        ]
    )
    # Git lock files that indicate active operations
    git_lock_files: list[str] = field(
        default_factory=lambda: [
            ".git/index.lock",
            ".git/HEAD.lock",
            ".git/refs/heads",
        ]
    )
    # Default worktree base directory name
    worktree_base_dir: str = ".worktrees"


@dataclass
class AuditFinding:
    """A single audit finding."""

    severity: str  # info | warning | error | critical
    category: str  # path | permission | disk | isolation | config | git
    message: str
    path: str | None = None
    recommendation: str = ""


@dataclass
class AuditReport:
    """Complete audit report."""

    timestamp: str
    repo_path: str
    worktree_count: int
    findings: list[AuditFinding]
    healthy: bool
    summary: str

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity in ("error", "critical"))

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")


@dataclass
class WorktreeStatus:
    """Status of a single worktree."""

    branch_name: str
    worktree_path: str
    status: str  # healthy | stalled | abandoned | missing | error
    has_uncommitted_changes: bool = False
    has_lock_files: bool = False
    disk_usage_bytes: int = 0
    last_commit_timestamp: str | None = None
    error: str | None = None


class WorktreeAuditor:
    """Validates worktree configuration, health, and isolation.

    Performs comprehensive checks on git worktrees to ensure they are
    properly configured, have correct permissions, sufficient disk space,
    and maintain proper isolation from each other.
    """

    def __init__(
        self,
        repo_path: Path | None = None,
        config: AuditorConfig | None = None,
    ):
        self.repo_path = repo_path or Path.cwd()
        self.config = config or AuditorConfig()
        self._worktree_dir = self.repo_path / self.config.worktree_base_dir

    def _run_git(
        self,
        *args: str,
        cwd: Path | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess:
        """Run a git command."""
        cmd = ["git"] + list(args)
        return subprocess.run(  # subprocess with fixed args, no shell
            cmd,
            cwd=cwd or self.repo_path,
            capture_output=True,
            text=True,
            check=check,
        )

    def _list_git_worktrees(self) -> list[dict[str, str]]:
        """Parse git worktree list --porcelain into structured data."""
        result = self._run_git("worktree", "list", "--porcelain")
        if result.returncode != 0:
            return []

        worktrees: list[dict[str, str]] = []
        current: dict[str, str] = {}

        for line in result.stdout.split("\n"):
            line = line.strip()
            if line.startswith("worktree "):
                if current:
                    worktrees.append(current)
                current = {"path": line[len("worktree ") :]}
            elif line.startswith("branch refs/heads/"):
                current["branch"] = line[len("branch refs/heads/") :]
            elif line.startswith("HEAD "):
                current["head"] = line[len("HEAD ") :]
            elif line == "bare":
                current["bare"] = "true"
            elif line == "detached":
                current["detached"] = "true"
            elif line == "" and current:
                worktrees.append(current)
                current = {}

        if current:
            worktrees.append(current)

        return worktrees

    def audit(self) -> AuditReport:
        """Run a comprehensive worktree audit.

        Checks:
        1. Default worktree directory exists and has correct permissions
        2. Each worktree directory exists and is accessible
        3. Disk space is sufficient
        4. Git configuration is valid
        5. No orphaned lock files
        6. Worktree isolation is intact

        Returns:
            AuditReport with findings and overall health status.
        """
        findings: list[AuditFinding] = []

        # 1. Check worktree base directory
        findings.extend(self._check_base_directory())

        # 2. Check disk space
        findings.extend(self._check_disk_space())

        # 3. Check git configuration
        findings.extend(self._check_git_config())

        # 4. Check individual worktrees
        worktrees = self._list_git_worktrees()
        for wt in worktrees:
            # Skip the main worktree (the repo itself)
            wt_path = wt.get("path", "")
            if wt_path == str(self.repo_path):
                continue
            findings.extend(self._check_worktree(wt))

        # 5. Check isolation
        findings.extend(self._check_isolation())

        # Count non-main worktrees
        worktree_count = max(0, len(worktrees) - 1)

        healthy = all(f.severity not in ("error", "critical") for f in findings)

        error_count = sum(1 for f in findings if f.severity in ("error", "critical"))
        warn_count = sum(1 for f in findings if f.severity == "warning")
        summary_parts = [f"{worktree_count} worktrees audited"]
        if error_count:
            summary_parts.append(f"{error_count} errors")
        if warn_count:
            summary_parts.append(f"{warn_count} warnings")
        if healthy:
            summary_parts.append("all healthy")

        return AuditReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            repo_path=str(self.repo_path),
            worktree_count=worktree_count,
            findings=findings,
            healthy=healthy,
            summary=", ".join(summary_parts),
        )

    def _check_base_directory(self) -> list[AuditFinding]:
        """Check that the worktree base directory exists with correct permissions."""
        findings: list[AuditFinding] = []

        if not self._worktree_dir.exists():
            findings.append(
                AuditFinding(
                    severity="info",
                    category="path",
                    message=f"Worktree directory does not exist: {self._worktree_dir}",
                    path=str(self._worktree_dir),
                    recommendation=(
                        "Directory will be created automatically when first worktree is added."
                    ),
                )
            )
            return findings

        if not self._worktree_dir.is_dir():
            findings.append(
                AuditFinding(
                    severity="critical",
                    category="path",
                    message=f"Worktree path exists but is not a directory: {self._worktree_dir}",
                    path=str(self._worktree_dir),
                    recommendation="Remove the file and let the system recreate the directory.",
                )
            )
            return findings

        # Check permissions
        try:
            stat = self._worktree_dir.stat()
            mode = stat.st_mode & 0o777
            if mode & 0o700 != 0o700:
                findings.append(
                    AuditFinding(
                        severity="error",
                        category="permission",
                        message=(
                            f"Worktree directory has restrictive permissions: "
                            f"{oct(mode)} (expected at least 0o700)"
                        ),
                        path=str(self._worktree_dir),
                        recommendation=f"chmod 755 {self._worktree_dir}",
                    )
                )
            else:
                findings.append(
                    AuditFinding(
                        severity="info",
                        category="permission",
                        message=f"Worktree directory permissions: {oct(mode)}",
                        path=str(self._worktree_dir),
                    )
                )
        except OSError as e:
            findings.append(
                AuditFinding(
                    severity="error",
                    category="permission",
                    message=f"Cannot stat worktree directory: {e}",
                    path=str(self._worktree_dir),
                )
            )

        return findings

    def _check_disk_space(self) -> list[AuditFinding]:
        """Check that sufficient disk space is available."""
        findings: list[AuditFinding] = []

        try:
            usage = shutil.disk_usage(self.repo_path)
            free_gb = usage.free / (1024**3)
            min_gb = self.config.min_disk_space_bytes / (1024**3)

            if usage.free < self.config.min_disk_space_bytes:
                findings.append(
                    AuditFinding(
                        severity="error",
                        category="disk",
                        message=(
                            f"Insufficient disk space: {free_gb:.1f} GB free "
                            f"(minimum: {min_gb:.1f} GB)"
                        ),
                        path=str(self.repo_path),
                        recommendation="Free up disk space before creating new worktrees.",
                    )
                )
            else:
                findings.append(
                    AuditFinding(
                        severity="info",
                        category="disk",
                        message=f"Disk space: {free_gb:.1f} GB free",
                        path=str(self.repo_path),
                    )
                )
        except OSError as e:
            findings.append(
                AuditFinding(
                    severity="warning",
                    category="disk",
                    message=f"Cannot check disk space: {e}",
                    path=str(self.repo_path),
                )
            )

        return findings

    def _check_git_config(self) -> list[AuditFinding]:
        """Check git configuration for worktree support."""
        findings: list[AuditFinding] = []

        # Verify this is a git repo
        result = self._run_git("rev-parse", "--git-dir")
        if result.returncode != 0:
            findings.append(
                AuditFinding(
                    severity="critical",
                    category="git",
                    message="Not a git repository",
                    path=str(self.repo_path),
                    recommendation="Initialize a git repository with 'git init'.",
                )
            )
            return findings

        # Check git version supports worktrees (2.5+)
        result = self._run_git("--version")
        if result.returncode == 0:
            version_str = result.stdout.strip()
            findings.append(
                AuditFinding(
                    severity="info",
                    category="git",
                    message=f"Git version: {version_str}",
                )
            )

        # Check for stale worktree entries
        result = self._run_git("worktree", "list", "--porcelain")
        if result.returncode == 0:
            stale_count = 0
            for wt in self._list_git_worktrees():
                wt_path = wt.get("path", "")
                if wt_path and wt_path != str(self.repo_path):
                    if not Path(wt_path).exists():
                        stale_count += 1
                        findings.append(
                            AuditFinding(
                                severity="warning",
                                category="git",
                                message=f"Stale worktree entry: {wt_path}",
                                path=wt_path,
                                recommendation="Run 'git worktree prune' to clean up.",
                            )
                        )
            if stale_count > 0:
                findings.append(
                    AuditFinding(
                        severity="warning",
                        category="git",
                        message=f"{stale_count} stale worktree entries found",
                        recommendation="git worktree prune",
                    )
                )

        return findings

    def _check_worktree(self, wt_info: dict[str, str]) -> list[AuditFinding]:
        """Check a single worktree for health issues."""
        findings: list[AuditFinding] = []
        wt_path = Path(wt_info.get("path", ""))
        branch = wt_info.get("branch", "detached")

        if not wt_path.exists():
            findings.append(
                AuditFinding(
                    severity="error",
                    category="path",
                    message=f"Worktree directory missing: {wt_path} (branch: {branch})",
                    path=str(wt_path),
                    recommendation="Remove with 'git worktree remove' and recreate.",
                )
            )
            return findings

        # Check for lock files
        git_dir = wt_path / ".git"
        if git_dir.is_file():
            # .git is a file in worktrees, pointing to the main repo
            findings.append(
                AuditFinding(
                    severity="info",
                    category="git",
                    message=f"Worktree git link valid: {branch}",
                    path=str(wt_path),
                )
            )
        elif git_dir.is_dir():
            findings.append(
                AuditFinding(
                    severity="warning",
                    category="git",
                    message=f"Worktree has full .git directory (expected file link): {branch}",
                    path=str(wt_path),
                    recommendation="This may indicate a corrupted worktree.",
                )
            )

        # Check for uncommitted changes
        result = self._run_git("status", "--porcelain", cwd=wt_path)
        if result.returncode == 0 and result.stdout.strip():
            change_count = len(result.stdout.strip().split("\n"))
            findings.append(
                AuditFinding(
                    severity="warning",
                    category="git",
                    message=f"Worktree has {change_count} uncommitted changes: {branch}",
                    path=str(wt_path),
                    recommendation="Commit or stash changes before cleanup.",
                )
            )

        return findings

    def _check_isolation(self) -> list[AuditFinding]:
        """Check that worktrees maintain proper isolation."""
        findings: list[AuditFinding] = []

        worktrees = self._list_git_worktrees()
        wt_paths = [
            Path(wt["path"])
            for wt in worktrees
            if wt.get("path") and wt["path"] != str(self.repo_path)
        ]

        if len(wt_paths) < 2:
            # Not enough worktrees to check isolation
            return findings

        # Check that isolation files are not symlinked between worktrees
        for wt_path in wt_paths:
            if not wt_path.exists():
                continue
            for iso_file in self.config.isolation_files:
                target = wt_path / iso_file
                if target.is_symlink():
                    link_target = os.readlink(target)
                    # Check if the symlink points to another worktree
                    for other_wt in wt_paths:
                        if other_wt == wt_path:
                            continue
                        if str(other_wt) in str(link_target):
                            findings.append(
                                AuditFinding(
                                    severity="error",
                                    category="isolation",
                                    message=(
                                        f"Isolation violation: {iso_file} in {wt_path.name} "
                                        f"is symlinked to {other_wt.name}"
                                    ),
                                    path=str(target),
                                    recommendation=(
                                        "Remove the symlink and create an independent copy."
                                    ),
                                )
                            )

        # Check for shared PID files or lock files
        for wt_path in wt_paths:
            if not wt_path.exists():
                continue
            lock_candidates = list(wt_path.glob("*.lock")) + list(wt_path.glob(".*.lock"))
            for lock_file in lock_candidates:
                findings.append(
                    AuditFinding(
                        severity="warning",
                        category="isolation",
                        message=f"Lock file found in worktree: {lock_file.name}",
                        path=str(lock_file),
                        recommendation="Verify the lock owner is still active.",
                    )
                )

        return findings

    def get_status(self) -> list[WorktreeStatus]:
        """Get status of all worktrees.

        Returns:
            List of WorktreeStatus objects for each non-main worktree.
        """
        statuses: list[WorktreeStatus] = []
        worktrees = self._list_git_worktrees()

        for wt in worktrees:
            wt_path_str = wt.get("path", "")
            if not wt_path_str or wt_path_str == str(self.repo_path):
                continue

            wt_path = Path(wt_path_str)
            branch = wt.get("branch", "detached")

            if not wt_path.exists():
                statuses.append(
                    WorktreeStatus(
                        branch_name=branch,
                        worktree_path=wt_path_str,
                        status="missing",
                        error="Directory does not exist",
                    )
                )
                continue

            # Check for uncommitted changes
            has_changes = False
            result = self._run_git("status", "--porcelain", cwd=wt_path)
            if result.returncode == 0 and result.stdout.strip():
                has_changes = True

            # Check for lock files
            has_locks = False
            git_dir = wt_path / ".git"
            if git_dir.is_file():
                # Read the gitdir from the file to find lock files
                try:
                    gitdir_content = git_dir.read_text().strip()
                    if gitdir_content.startswith("gitdir:"):
                        actual_git_dir = Path(gitdir_content[len("gitdir:") :].strip())
                        if not actual_git_dir.is_absolute():
                            actual_git_dir = wt_path / actual_git_dir
                        if (actual_git_dir / "index.lock").exists():
                            has_locks = True
                except (OSError, ValueError):
                    pass

            # Get last commit timestamp
            last_commit_ts = None
            result = self._run_git("log", "-1", "--format=%aI", cwd=wt_path)
            if result.returncode == 0 and result.stdout.strip():
                last_commit_ts = result.stdout.strip()

            # Determine overall status
            status = "healthy"
            if has_locks:
                status = "stalled"

            statuses.append(
                WorktreeStatus(
                    branch_name=branch,
                    worktree_path=wt_path_str,
                    status=status,
                    has_uncommitted_changes=has_changes,
                    has_lock_files=has_locks,
                    last_commit_timestamp=last_commit_ts,
                )
            )

        return statuses

    def validate_isolation(self) -> bool:
        """Validate that no shared state leaks between worktrees.

        A convenience method that runs isolation checks and returns
        True if no isolation violations are found.

        Returns:
            True if all worktrees are properly isolated.
        """
        findings = self._check_isolation()
        violations = [f for f in findings if f.severity in ("error", "critical")]
        if violations:
            for v in violations:
                logger.warning(
                    "worktree_isolation_violation: %s (path=%s)",
                    v.message,
                    v.path,
                )
        return len(violations) == 0


__all__ = [
    "WorktreeAuditor",
    "AuditorConfig",
    "AuditFinding",
    "AuditReport",
    "WorktreeStatus",
]
