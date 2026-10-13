"""Scope Guard for multi-agent track boundaries.

Enforces track-scoped file ownership to prevent cross-track conflicts
when multiple agents work in parallel worktrees.

Reads track assignments from docs/AGENT_ASSIGNMENTS.md and validates
that file modifications stay within the track's declared scope.

Can be used as:
- A pre-commit hook (`python -m aragora.nomic.scope_guard --hook`)
- A CI check (`python -m aragora.nomic.scope_guard --ci`)
- A library call from the coordinate CLI

Usage:
    from aragora.nomic.scope_guard import ScopeGuard, TrackScope

    guard = ScopeGuard()
    violations = guard.check_files(["aragora/debate/orchestrator.py"], track="sme")
    if violations:
        print(f"Scope violation: {violations}")
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TrackScope:
    """Defines the file ownership scope for a development track."""

    name: str
    allowed_paths: list[str] = field(default_factory=list)
    denied_paths: list[str] = field(default_factory=list)
    description: str = ""


@dataclass
class ScopeViolation:
    """A file modification that crosses track boundaries."""

    file_path: str
    track: str
    violation_type: str  # "outside_scope" | "protected_file" | "cross_track"
    message: str
    severity: str = "warn"  # "warn" | "block"


# Default track scopes (matches AGENT_ASSIGNMENTS.md and the plan)
DEFAULT_TRACK_SCOPES: dict[str, TrackScope] = {
    "sme-track": TrackScope(
        name="sme-track",
        allowed_paths=[
            "aragora/live/",
            "docs/",
            "aragora/audience/",
            "aragora/server/handlers/",
        ],
        denied_paths=[
            "aragora/debate/",
            "aragora/nomic/",
            "aragora/agents/",
        ],
        description="SME user-facing features",
    ),
    "developer-track": TrackScope(
        name="developer-track",
        allowed_paths=[
            "sdk/",
            "aragora/mcp/",
            "aragora/integrations/",
            "docs/",
            "tests/sdk/",
        ],
        denied_paths=[
            "aragora/server/handlers/",
            "aragora/debate/",
        ],
        description="SDK and API development",
    ),
    "qa-track": TrackScope(
        name="qa-track",
        allowed_paths=[
            "tests/",
            ".github/workflows/",
            "aragora/live/e2e/",
        ],
        denied_paths=[],  # QA can read anything but only write tests
        description="Quality assurance and testing",
    ),
    "security-track": TrackScope(
        name="security-track",
        allowed_paths=[
            "aragora/security/",
            "aragora/rbac/",
            "aragora/auth/",
            "aragora/audit/",
        ],
        denied_paths=[
            "aragora/live/",
            "sdk/",
        ],
        description="Security hardening",
    ),
    "core-track": TrackScope(
        name="core-track",
        allowed_paths=[
            "aragora/debate/",
            "aragora/nomic/",
            "aragora/memory/",
            "aragora/agents/",
            "aragora/reasoning/",
        ],
        denied_paths=[
            "aragora/live/",
            "deploy/",
        ],
        description="Core debate and nomic engine",
    ),
    "infra-track": TrackScope(
        name="infra-track",
        allowed_paths=[
            "deploy/",
            "docker/",
            "Dockerfile",
            ".github/workflows/",
            "scripts/",
        ],
        denied_paths=[
            "aragora/debate/",
            "aragora/agents/",
            "aragora/live/src/",
        ],
        description="Infrastructure and deployment",
    ),
}

# Protected files that require explicit approval regardless of track
PROTECTED_FILES = [
    "CLAUDE.md",
    "aragora/__init__.py",
    ".env",
    ".env.local",
    "scripts/nomic_loop.py",
    "aragora/debate/orchestrator.py",
]


class ScopeGuard:
    """Enforces track-scoped file ownership boundaries."""

    def __init__(
        self,
        repo_path: Path | None = None,
        scopes: dict[str, TrackScope] | None = None,
        mode: str = "warn",  # "warn" | "block"
    ):
        self.repo_path = repo_path or Path.cwd()
        self.scopes = scopes or DEFAULT_TRACK_SCOPES
        self.mode = mode

    def detect_track_from_branch(self, branch: str | None = None) -> str | None:
        """Detect the track from the current or specified branch name."""
        if branch is None:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # fixed command
                capture_output=True,
                text=True,
                cwd=self.repo_path,
                check=False,
            )
            if result.returncode != 0:
                return None
            branch = result.stdout.strip()

        # Extract track from branch patterns like dev/core-track, work/security-20240215
        for prefix in ("dev/", "work/", "sprint/"):
            if branch.startswith(prefix):
                track_part = branch[len(prefix) :]
                # Match against known track names
                for track_name in self.scopes:
                    # Check exact match or prefix match
                    clean = track_name.replace("-track", "")
                    if track_part.startswith(track_name) or track_part.startswith(clean):
                        return track_name
                break

        return None

    def get_changed_files(self, base_branch: str = "main") -> list[str]:
        """Get files changed in current branch relative to base."""
        result = subprocess.run(  # subprocess with fixed args, no shell
            ["git", "diff", "--name-only", f"{base_branch}...HEAD"],  # fixed command
            capture_output=True,
            text=True,
            cwd=self.repo_path,
            check=False,
        )
        if result.returncode != 0:
            # Fallback: staged + unstaged changes
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],  # fixed command
                capture_output=True,
                text=True,
                cwd=self.repo_path,
                check=False,
            )
        if result.returncode != 0:
            return []
        return [f for f in result.stdout.strip().split("\n") if f]

    def check_files(
        self,
        files: list[str],
        track: str,
    ) -> list[ScopeViolation]:
        """Check if files are within the track's allowed scope.

        Args:
            files: List of file paths (relative to repo root)
            track: Track name (e.g., "core-track")

        Returns:
            List of scope violations found
        """
        violations: list[ScopeViolation] = []
        scope = self.scopes.get(track)

        if scope is None:
            logger.warning("Unknown track: %s", track)
            return violations

        for file_path in files:
            # Check protected files
            if any(file_path == pf or file_path.endswith(f"/{pf}") for pf in PROTECTED_FILES):
                violations.append(
                    ScopeViolation(
                        file_path=file_path,
                        track=track,
                        violation_type="protected_file",
                        message=f"Protected file requires explicit approval: {file_path}",
                        severity="block",
                    )
                )
                continue

            # Check denied paths
            denied_match = False
            if scope.denied_paths:
                for denied in scope.denied_paths:
                    if file_path.startswith(denied):
                        violations.append(
                            ScopeViolation(
                                file_path=file_path,
                                track=track,
                                violation_type="outside_scope",
                                message=(
                                    f"File {file_path} is in denied path {denied} for track {track}"
                                ),
                                severity=self.mode,
                            )
                        )
                        denied_match = True
                        break

            if denied_match:
                continue

            # Check allowed paths (only if there are explicit allowed paths)
            if scope.allowed_paths:
                in_scope = any(file_path.startswith(allowed) for allowed in scope.allowed_paths)
                if not in_scope:
                    violations.append(
                        ScopeViolation(
                            file_path=file_path,
                            track=track,
                            violation_type="outside_scope",
                            message=(
                                f"File {file_path} is outside allowed paths "
                                f"for track {track}: {scope.allowed_paths}"
                            ),
                            severity=self.mode,
                        )
                    )

        return violations

    def check_cross_track_overlaps(
        self,
        worktree_files: dict[str, list[str]],
    ) -> list[ScopeViolation]:
        """Check for files modified by multiple tracks.

        Args:
            worktree_files: Mapping of track -> list of changed files

        Returns:
            List of cross-track violations
        """
        file_owners: dict[str, list[str]] = {}
        for track, files in worktree_files.items():
            for f in files:
                if f not in file_owners:
                    file_owners[f] = []
                file_owners[f].append(track)

        violations: list[ScopeViolation] = []
        for file_path, tracks in file_owners.items():
            if len(tracks) > 1:
                violations.append(
                    ScopeViolation(
                        file_path=file_path,
                        track=", ".join(tracks),
                        violation_type="cross_track",
                        message=(
                            f"File {file_path} modified by multiple tracks: {', '.join(tracks)}"
                        ),
                        severity="block" if len(tracks) > 2 else "warn",
                    )
                )

        return violations

    def run_check(self, base_branch: str = "main") -> list[ScopeViolation]:
        """Run a full scope check on the current branch.

        Detects the track from the branch name and checks all changed files.
        """
        track = self.detect_track_from_branch()
        if track is None:
            logger.info("Could not detect track from branch name")
            return []

        files = self.get_changed_files(base_branch)
        if not files:
            return []

        return self.check_files(files, track)


def main() -> int:
    """CLI entry point for scope guard."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Scope guard — enforce track file ownership boundaries"
    )
    parser.add_argument(
        "--hook",
        action="store_true",
        help="Run as a pre-commit hook",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="Run as a CI check (exit 1 on block-severity violations)",
    )
    parser.add_argument(
        "--track",
        type=str,
        default=None,
        help="Override track detection (e.g., --track core-track)",
    )
    parser.add_argument(
        "--base-branch",
        default="main",
        help="Base branch to compare against (default: main)",
    )
    parser.add_argument(
        "--mode",
        choices=["warn", "block"],
        default="warn",
        help="Violation severity mode (default: warn)",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Specific files to check (default: auto-detect from git)",
    )
    args = parser.parse_args()

    guard = ScopeGuard(mode=args.mode)

    # Determine track
    track = args.track or guard.detect_track_from_branch()
    if track is None:
        if args.ci or args.hook:
            # In CI/hook mode, skip if we can't detect the track
            print("scope-guard: Could not detect track from branch name. Skipping.")
            return 0
        print("Error: Could not detect track. Use --track to specify.")
        return 1

    # Determine files
    files = args.files or guard.get_changed_files(args.base_branch)
    if not files:
        print(f"scope-guard: No changed files for track {track}.")
        return 0

    # Check
    violations = guard.check_files(files, track)

    if not violations:
        print(f"scope-guard: All {len(files)} files are within {track} scope.")
        return 0

    # Report violations
    block_count = 0
    warn_count = 0
    for v in violations:
        icon = "BLOCK" if v.severity == "block" else "WARN"
        if v.severity == "block":
            block_count += 1
        else:
            warn_count += 1
        print(f"  [{icon}] {v.message}")

    print(f"\nScope check: {warn_count} warnings, {block_count} blocks")

    if args.ci and block_count > 0:
        return 1
    if args.hook and block_count > 0:
        print("Commit blocked by scope guard. Use --no-verify to bypass.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = [
    "ScopeGuard",
    "ScopeViolation",
    "TrackScope",
    "DEFAULT_TRACK_SCOPES",
    "PROTECTED_FILES",
]
