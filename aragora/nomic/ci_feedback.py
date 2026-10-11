"""CI Feedback Loop for Nomic branches.

Collects CI results from GitHub Actions and feeds them back
into the Nomic Loop's verification and planning phases.

Uses the ``gh`` CLI for GitHub API access, gracefully degrading
when ``gh`` is not available (same pattern as GitHubConnector).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CITestFailure:
    """A single test failure from CI."""

    test_name: str
    error_message: str
    file_path: str = ""


@dataclass
class CITestSummary:
    """Summary of CI test results."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    failure_details: list[CITestFailure] = field(default_factory=list)


@dataclass
class CIResult:
    """Result from a CI workflow run."""

    workflow_run_id: int
    branch: str
    commit_sha: str
    conclusion: str  # success, failure, cancelled, etc.
    test_summary: CITestSummary | None = None
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0


class CIResultCollector:
    """Collects CI results from GitHub Actions via the gh CLI.

    Gracefully degrades when ``gh`` is not installed or not authenticated.
    """

    def __init__(self, repo_owner: str = "", repo_name: str = ""):
        self._repo_owner = repo_owner
        self._repo_name = repo_name
        if not repo_owner or not repo_name:
            self._auto_detect_repo()

    def _auto_detect_repo(self) -> None:
        """Auto-detect repo owner/name from gh CLI."""
        if not self._gh_available():
            return
        try:
            result = subprocess.run(
                ["gh", "repo", "view", "--json", "owner,name"],  # fixed command
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                self._repo_owner = data.get("owner", {}).get("login", "")
                self._repo_name = data.get("name", "")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            pass

    @staticmethod
    def _gh_available() -> bool:
        """Check if the gh CLI is available on PATH."""
        return shutil.which("gh") is not None

    @property
    def repo_slug(self) -> str:
        """Return owner/name slug."""
        return f"{self._repo_owner}/{self._repo_name}"

    def poll_for_result(
        self,
        branch: str,
        sha: str,
        timeout: float = 600,
        poll_interval: float = 30,
    ) -> CIResult | None:
        """Poll GitHub Actions for a completed run on the given branch/sha.

        Args:
            branch: Branch name
            sha: Commit SHA to match
            timeout: Maximum seconds to wait
            poll_interval: Seconds between polls

        Returns:
            CIResult if a completed run is found, None on timeout or error
        """
        if not self._gh_available() or not self._repo_owner:
            logger.debug("gh CLI not available or repo not detected, skipping CI poll")
            return None

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self._fetch_run(branch, sha)
            if result is not None:
                return result
            time.sleep(poll_interval)

        logger.warning("CI poll timed out after %.0fs for %s@%s", timeout, branch, sha[:8])
        return None

    def get_latest_result(self, branch: str) -> CIResult | None:
        """Get the latest CI result for a branch (non-blocking).

        Returns:
            CIResult or None if unavailable
        """
        if not self._gh_available() or not self._repo_owner:
            return None

        try:
            result = subprocess.run(  # subprocess with fixed args, no shell
                [  # fixed command
                    "gh",
                    "api",
                    f"repos/{self.repo_slug}/actions/runs",
                    "-q",
                    ".workflow_runs[0]",
                    "--jq",
                    ".",
                    "-f",
                    f"branch={branch}",
                    "-f",
                    "per_page=1",
                    "-f",
                    "status=completed",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None

            run_data = json.loads(result.stdout)
            return self._parse_run_to_result(run_data)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            logger.debug("Failed to fetch latest CI result: %s", e)
            return None

    def _fetch_run(self, branch: str, sha: str) -> CIResult | None:
        """Fetch a specific run matching branch and sha."""
        try:
            result = subprocess.run(  # subprocess with fixed args, no shell
                [  # fixed command
                    "gh",
                    "api",
                    f"repos/{self.repo_slug}/actions/runs",
                    "-f",
                    f"branch={branch}",
                    "-f",
                    f"head_sha={sha}",
                    "-f",
                    "per_page=1",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return None

            data = json.loads(result.stdout)
            runs = data.get("workflow_runs", [])
            if not runs:
                return None

            run = runs[0]
            if run.get("status") != "completed":
                return None

            return self._parse_run_to_result(run)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            logger.debug("Failed to fetch CI run: %s", e)
            return None

    def _parse_run_to_result(self, run_data: dict[str, Any]) -> CIResult:
        """Parse a GitHub Actions run JSON object into a CIResult."""
        started = run_data.get("run_started_at", "")
        completed = run_data.get("updated_at", "")

        # Calculate duration if timestamps available
        duration = 0.0
        if started and completed:
            try:
                from datetime import datetime, timezone

                fmt = "%Y-%m-%dT%H:%M:%SZ"
                start_dt = datetime.strptime(started, fmt).replace(tzinfo=timezone.utc)
                end_dt = datetime.strptime(completed, fmt).replace(tzinfo=timezone.utc)
                duration = (end_dt - start_dt).total_seconds()
            except (ValueError, TypeError):
                pass

        return CIResult(
            workflow_run_id=run_data.get("id", 0),
            branch=run_data.get("head_branch", ""),
            commit_sha=run_data.get("head_sha", ""),
            conclusion=run_data.get("conclusion", "unknown"),
            started_at=started,
            completed_at=completed,
            duration_seconds=duration,
        )

    @staticmethod
    def to_feedback_error(result: CIResult) -> dict[str, Any]:
        """Convert a CIResult to a format suitable for FeedbackLoop.analyze_failure().

        Returns:
            Dict with ``type`` and ``message`` keys for the feedback loop
        """
        failures: list[str] = []
        if result.test_summary:
            for f in result.test_summary.failure_details:
                failures.append(f"{f.test_name}: {f.error_message}")

        return {
            "type": "ci_failure",
            "message": f"CI {result.conclusion} for {result.branch}@{result.commit_sha[:8]}",
            "ci_failures": failures,
            "workflow_run_id": result.workflow_run_id,
            "conclusion": result.conclusion,
        }


__all__ = [
    "CITestFailure",
    "CITestSummary",
    "CIResult",
    "CIResultCollector",
]
