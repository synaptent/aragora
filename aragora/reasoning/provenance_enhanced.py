"""
Enhanced Evidence Provenance Chain.

Extends the base provenance system with:
- Staleness detection and re-validation triggers
- Git integration for code evidence
- URL/web content verification with caching
- Automatic provenance validation
- Living document support (consensus proofs that flag stale evidence)

This ensures debate conclusions remain valid as underlying evidence changes.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

from aragora.reasoning.provenance import (
    ProvenanceManager,
    ProvenanceRecord,
    SourceType,
)


class StalenessStatus(Enum):
    """Status of evidence freshness."""

    FRESH = "fresh"  # Evidence still valid
    STALE = "stale"  # Evidence has changed
    UNKNOWN = "unknown"  # Cannot determine
    ERROR = "error"  # Failed to check
    EXPIRED = "expired"  # Time-based expiration


@dataclass
class GitSourceInfo:
    """Git-specific source information for code evidence."""

    repo_path: str
    file_path: str
    line_start: int
    line_end: int
    commit_sha: str
    branch: str = "main"
    commit_timestamp: str | None = None
    commit_author: str | None = None
    commit_message: str | None = None

    @property
    def ref(self) -> str:
        """Git reference string."""
        return f"{self.file_path}:{self.line_start}-{self.line_end}@{self.commit_sha[:8]}"

    def to_dict(self) -> dict:
        return {
            "repo_path": self.repo_path,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "commit_sha": self.commit_sha,
            "branch": self.branch,
            "commit_timestamp": self.commit_timestamp,
            "commit_author": self.commit_author,
            "commit_message": self.commit_message,
            "ref": self.ref,
        }


@dataclass
class WebSourceInfo:
    """Web-specific source information for URL evidence."""

    url: str
    fetch_timestamp: str
    content_hash: str
    http_status: int = 200
    content_type: str = "text/html"
    last_modified: str | None = None
    etag: str | None = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "fetch_timestamp": self.fetch_timestamp,
            "content_hash": self.content_hash,
            "http_status": self.http_status,
            "content_type": self.content_type,
            "last_modified": self.last_modified,
            "etag": self.etag,
        }


@dataclass
class StalenessCheck:
    """Result of checking evidence staleness."""

    evidence_id: str
    status: StalenessStatus
    checked_at: str
    reason: str

    # Change details (if stale)
    original_hash: str | None = None
    current_hash: str | None = None
    change_summary: str | None = None

    # For git sources
    commits_behind: int = 0
    changed_lines: list[tuple[int, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "status": self.status.value,
            "checked_at": self.checked_at,
            "reason": self.reason,
            "original_hash": self.original_hash,
            "current_hash": self.current_hash,
            "change_summary": self.change_summary,
            "commits_behind": self.commits_behind,
            "changed_lines": self.changed_lines,
        }


@dataclass
class RevalidationTrigger:
    """Trigger for re-debate based on stale evidence."""

    trigger_id: str
    claim_id: str
    evidence_ids: list[str]
    staleness_checks: list[StalenessCheck]
    severity: str  # "info", "warning", "critical"
    recommendation: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "trigger_id": self.trigger_id,
            "claim_id": self.claim_id,
            "evidence_ids": self.evidence_ids,
            "staleness_checks": [sc.to_dict() for sc in self.staleness_checks],
            "severity": self.severity,
            "recommendation": self.recommendation,
            "created_at": self.created_at,
        }


class GitProvenanceTracker:
    """Tracks provenance for code evidence via git."""

    def __init__(self, repo_path: str | None = None):
        self.repo_path = repo_path or os.getcwd()

    def _run_git(self, args: list[str]) -> tuple[bool, str]:
        """Run a git command and return (success, output).

        Returns stdout on success, stderr on failure for better diagnostics.
        """
        try:
            result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                ["git"] + args,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
            if result.returncode != 0:
                return (
                    False,
                    result.stderr.strip() or f"git command failed (exit {result.returncode})",
                )
            return True, result.stdout.strip()
        except subprocess.TimeoutExpired:
            return False, "git command timed out after 30s"
        except (OSError, subprocess.SubprocessError) as e:
            return False, str(e)

    def get_current_commit(self) -> str | None:
        """Get current HEAD commit SHA."""
        success, output = self._run_git(["rev-parse", "HEAD"])
        return output if success else None

    def get_file_at_commit(
        self,
        file_path: str,
        commit_sha: str,
    ) -> str | None:
        """Get file content at a specific commit."""
        success, output = self._run_git(["show", f"{commit_sha}:{file_path}"])
        return output if success else None

    def get_blame(
        self,
        file_path: str,
        line_start: int,
        line_end: int,
    ) -> list[dict]:
        """Get git blame for specific lines."""
        success, output = self._run_git(
            ["blame", "-L", f"{line_start},{line_end}", "--porcelain", file_path]
        )

        if not success:
            return []

        blame_info: list[dict] = []
        lines = output.split("\n")
        current_commit = None

        for line in lines:
            if re.match(r"^[0-9a-f]{40}", line):
                parts = line.split()
                current_commit = {
                    "sha": parts[0],
                    "original_line": int(parts[1]),
                    "final_line": int(parts[2]),
                }
            elif line.startswith("author "):
                if current_commit:
                    current_commit["author"] = line[7:]
            elif line.startswith("author-time "):
                if current_commit:
                    current_commit["timestamp"] = line[12:]
            elif line.startswith("\t"):
                if current_commit:
                    current_commit["content"] = line[1:]
                    blame_info.append(current_commit)
                    current_commit = None

        return blame_info

    def record_code_evidence(
        self,
        file_path: str,
        line_start: int,
        line_end: int,
        content: str,
    ) -> GitSourceInfo:
        """Record evidence from code with full git provenance."""
        commit = self.get_current_commit() or "unknown"

        # Get commit details
        success, commit_info = self._run_git(["log", "-1", "--format=%H|%an|%ad|%s", commit])

        commit_timestamp = None
        commit_author = None
        commit_message = None

        if success and "|" in commit_info:
            parts = commit_info.split("|", 3)
            commit_author = parts[1] if len(parts) > 1 else None
            commit_timestamp = parts[2] if len(parts) > 2 else None
            commit_message = parts[3] if len(parts) > 3 else None

        # Get current branch
        success, branch = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        branch = branch if success else "unknown"

        return GitSourceInfo(
            repo_path=self.repo_path,
            file_path=file_path,
            line_start=line_start,
            line_end=line_end,
            commit_sha=commit,
            branch=branch,
            commit_timestamp=commit_timestamp,
            commit_author=commit_author,
            commit_message=commit_message,
        )

    def check_staleness(
        self,
        source_info: GitSourceInfo,
    ) -> StalenessCheck:
        """Check if code evidence has become stale."""
        evidence_id = source_info.ref

        # Get original content at recorded commit
        original = self.get_file_at_commit(
            source_info.file_path,
            source_info.commit_sha,
        )

        if original is None:
            return StalenessCheck(
                evidence_id=evidence_id,
                status=StalenessStatus.ERROR,
                checked_at=datetime.now().isoformat(),
                reason=f"Cannot retrieve file at commit {source_info.commit_sha[:8]}",
            )

        # Get current content
        current_commit = self.get_current_commit()
        current = self.get_file_at_commit(
            source_info.file_path,
            current_commit or "HEAD",
        )

        if current is None:
            return StalenessCheck(
                evidence_id=evidence_id,
                status=StalenessStatus.UNKNOWN,
                checked_at=datetime.now().isoformat(),
                reason="File no longer exists",
            )

        # Extract relevant lines
        original_lines = original.split("\n")[source_info.line_start - 1 : source_info.line_end]
        current_lines = current.split("\n")[source_info.line_start - 1 : source_info.line_end]

        original_hash = hashlib.sha256("\n".join(original_lines).encode()).hexdigest()
        current_hash = hashlib.sha256("\n".join(current_lines).encode()).hexdigest()

        if original_hash == current_hash:
            return StalenessCheck(
                evidence_id=evidence_id,
                status=StalenessStatus.FRESH,
                checked_at=datetime.now().isoformat(),
                reason="Code unchanged",
                original_hash=original_hash[:16],
                current_hash=current_hash[:16],
            )

        # Find changed lines
        changed_lines = []
        for i, (orig, curr) in enumerate(zip(original_lines, current_lines)):
            if orig != curr:
                changed_lines.append((source_info.line_start + i, curr))

        # Count commits between original and current
        success, log = self._run_git(
            ["rev-list", "--count", f"{source_info.commit_sha}..HEAD", "--", source_info.file_path]
        )
        commits_behind = int(log) if success and log.isdigit() else 0

        return StalenessCheck(
            evidence_id=evidence_id,
            status=StalenessStatus.STALE,
            checked_at=datetime.now().isoformat(),
            reason=f"Code changed in {commits_behind} commits",
            original_hash=original_hash[:16],
            current_hash=current_hash[:16],
            change_summary=f"{len(changed_lines)} lines modified",
            commits_behind=commits_behind,
            changed_lines=changed_lines,
        )


class WebProvenanceTracker:
    """Tracks provenance for web-based evidence."""

    def __init__(self, cache_dir: str | None = None):
        self.cache_dir = Path(cache_dir) if cache_dir else Path(".web_cache")
        self.cache_dir.mkdir(exist_ok=True)

    async def record_url_evidence(
        self,
        url: str,
        content: str,
    ) -> WebSourceInfo:
        """Record evidence from a URL with provenance."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        return WebSourceInfo(
            url=url,
            fetch_timestamp=datetime.now().isoformat(),
            content_hash=content_hash,
        )

    async def check_staleness(
        self,
        source_info: WebSourceInfo,
        timeout: float = 30.0,
    ) -> StalenessCheck:
        """Check if web evidence has become stale."""
        try:
            from aragora.observability.http_client_pool import get_http_pool

            pool = get_http_pool()
            async with pool.get_session("web_provenance") as client:
                response = await client.get(source_info.url, timeout=timeout)
                if response.status_code != 200:
                    return StalenessCheck(
                        evidence_id=source_info.url,
                        status=StalenessStatus.ERROR,
                        checked_at=datetime.now().isoformat(),
                        reason=f"HTTP {response.status_code}",
                    )

                content = response.text
                current_hash = hashlib.sha256(content.encode()).hexdigest()

                if current_hash == source_info.content_hash:
                    return StalenessCheck(
                        evidence_id=source_info.url,
                        status=StalenessStatus.FRESH,
                        checked_at=datetime.now().isoformat(),
                        reason="Content unchanged",
                        original_hash=source_info.content_hash[:16],
                        current_hash=current_hash[:16],
                    )
                else:
                    return StalenessCheck(
                        evidence_id=source_info.url,
                        status=StalenessStatus.STALE,
                        checked_at=datetime.now().isoformat(),
                        reason="Content has changed",
                        original_hash=source_info.content_hash[:16],
                        current_hash=current_hash[:16],
                    )

        except ImportError:
            # http pool not available, use basic check
            return StalenessCheck(
                evidence_id=source_info.url,
                status=StalenessStatus.UNKNOWN,
                checked_at=datetime.now().isoformat(),
                reason="http pool not available for web checking",
            )
        except (OSError, ValueError) as e:
            return StalenessCheck(
                evidence_id=source_info.url,
                status=StalenessStatus.ERROR,
                checked_at=datetime.now().isoformat(),
                reason=str(e),
            )


class EnhancedProvenanceManager(ProvenanceManager):
    """
    Enhanced provenance manager with staleness detection and verification.

    Extends ProvenanceManager with:
    - Git integration for code evidence
    - Web content verification
    - Automatic staleness checking
    - Re-debate triggers
    """

    def __init__(
        self,
        debate_id: str | None = None,
        repo_path: str | None = None,
        staleness_threshold_hours: float = 24.0,
    ):
        super().__init__(debate_id)
        self.git_tracker = GitProvenanceTracker(repo_path)
        self.web_tracker = WebProvenanceTracker()
        self.staleness_threshold = timedelta(hours=staleness_threshold_hours)

        # Extended state
        self.git_sources: dict[str, GitSourceInfo] = {}
        self.web_sources: dict[str, WebSourceInfo] = {}
        self.staleness_checks: dict[str, StalenessCheck] = {}
        self.triggers: list[RevalidationTrigger] = []

    def record_code_evidence(
        self,
        file_path: str,
        line_start: int,
        line_end: int,
        content: str,
        claim_id: str | None = None,
    ) -> ProvenanceRecord:
        """Record code evidence with git provenance."""
        # Get git info
        git_info = self.git_tracker.record_code_evidence(file_path, line_start, line_end, content)

        # Create provenance record
        record = self.record_evidence(
            content=content,
            source_type=SourceType.CODE_ANALYSIS,
            source_id=git_info.ref,
            content_type="code",
            metadata={"git": git_info.to_dict()},
        )

        self.git_sources[record.id] = git_info

        # Create citation if claim provided
        if claim_id:
            self.cite_evidence(
                claim_id=claim_id,
                evidence_id=record.id,
                citation_text=f"Code at {git_info.ref}",
            )

        return record

    async def record_web_evidence(
        self,
        url: str,
        content: str,
        claim_id: str | None = None,
    ) -> ProvenanceRecord:
        """Record web evidence with URL provenance."""
        web_info = await self.web_tracker.record_url_evidence(url, content)

        record = self.record_evidence(
            content=content,
            source_type=SourceType.WEB_SEARCH,
            source_id=url,
            content_type="web",
            metadata={"web": web_info.to_dict()},
        )

        self.web_sources[record.id] = web_info

        if claim_id:
            self.cite_evidence(
                claim_id=claim_id,
                evidence_id=record.id,
                citation_text=f"Retrieved from {url}",
            )

        return record

    async def check_all_staleness(self) -> list[StalenessCheck]:
        """Check staleness of all evidence."""
        checks = []

        # Check git sources
        for record_id, git_info in self.git_sources.items():
            check = self.git_tracker.check_staleness(git_info)
            self.staleness_checks[record_id] = check
            checks.append(check)

        # Check web sources
        for record_id, web_info in self.web_sources.items():
            check = await self.web_tracker.check_staleness(web_info)
            self.staleness_checks[record_id] = check
            checks.append(check)

        return checks

    def check_claim_evidence_staleness(
        self,
        claim_id: str,
    ) -> list[StalenessCheck]:
        """Check staleness of all evidence supporting a claim."""
        citations = self.graph.get_claim_evidence(claim_id)
        checks = []

        for citation in citations:
            if citation.evidence_id in self.staleness_checks:
                checks.append(self.staleness_checks[citation.evidence_id])
            elif citation.evidence_id in self.git_sources:
                check = self.git_tracker.check_staleness(self.git_sources[citation.evidence_id])
                self.staleness_checks[citation.evidence_id] = check
                checks.append(check)

        return checks

    def generate_revalidation_triggers(
        self,
        claim_ids: list[str] | None = None,
    ) -> list[RevalidationTrigger]:
        """Generate triggers for claims with stale evidence."""
        triggers: list[RevalidationTrigger] = []

        # Get all claims if not specified
        if claim_ids is None:
            claim_ids = list(self.graph.claim_citations.keys())

        for claim_id in claim_ids:
            stale_checks = [
                check
                for check in self.check_claim_evidence_staleness(claim_id)
                if check.status == StalenessStatus.STALE
            ]

            if stale_checks:
                # Determine severity
                if any(c.commits_behind > 10 for c in stale_checks):
                    severity = "critical"
                elif any(c.commits_behind > 3 for c in stale_checks):
                    severity = "warning"
                else:
                    severity = "info"

                trigger = RevalidationTrigger(
                    trigger_id=f"trigger-{len(triggers):04d}",
                    claim_id=claim_id,
                    evidence_ids=[c.evidence_id for c in stale_checks],
                    staleness_checks=stale_checks,
                    severity=severity,
                    recommendation=self._generate_recommendation(stale_checks),
                )
                triggers.append(trigger)
                self.triggers.append(trigger)

        return triggers

    def _generate_recommendation(self, checks: list[StalenessCheck]) -> str:
        """Generate a recommendation based on staleness checks."""
        total_changes = sum(c.commits_behind for c in checks)
        stale_count = len(checks)

        if total_changes > 20:
            return (
                f"Critical: {stale_count} evidence sources have changed significantly "
                f"({total_changes} total commits). Re-debate strongly recommended."
            )
        elif total_changes > 5:
            return (
                f"Warning: {stale_count} evidence sources have been modified. "
                f"Review changes and consider re-validation."
            )
        else:
            return (
                f"Info: Minor changes detected in {stale_count} evidence sources. "
                f"Review for relevance."
            )

    def get_living_document_status(self) -> dict:
        """
        Get status of the debate as a "living document".

        Returns information about evidence freshness and
        recommendations for re-validation.
        """
        all_checks = list(self.staleness_checks.values())

        fresh_count = sum(1 for c in all_checks if c.status == StalenessStatus.FRESH)
        stale_count = sum(1 for c in all_checks if c.status == StalenessStatus.STALE)
        unknown_count = sum(1 for c in all_checks if c.status == StalenessStatus.UNKNOWN)
        error_count = sum(1 for c in all_checks if c.status == StalenessStatus.ERROR)

        total = len(all_checks)
        freshness_ratio = fresh_count / total if total > 0 else 1.0

        # Determine overall status
        if stale_count == 0 and error_count == 0:
            overall_status = "healthy"
            overall_message = "All evidence is fresh and verified"
        elif stale_count > total * 0.3:
            overall_status = "stale"
            overall_message = f"{stale_count}/{total} evidence sources have changed"
        elif stale_count > 0:
            overall_status = "warning"
            overall_message = f"{stale_count} evidence sources need review"
        else:
            overall_status = "unknown"
            overall_message = f"Unable to verify {unknown_count + error_count} sources"

        return {
            "debate_id": self.debate_id,
            "checked_at": datetime.now().isoformat(),
            "overall_status": overall_status,
            "overall_message": overall_message,
            "freshness_ratio": freshness_ratio,
            "counts": {
                "total": total,
                "fresh": fresh_count,
                "stale": stale_count,
                "unknown": unknown_count,
                "error": error_count,
            },
            "triggers": [t.to_dict() for t in self.triggers],
            "recommendation": (
                "Consider re-running debate" if stale_count > 0 else "No action needed"
            ),
        }

    def export_enhanced(self) -> dict:
        """Export enhanced provenance data."""
        base_export = self.export()

        base_export.update(
            {
                "git_sources": {k: v.to_dict() for k, v in self.git_sources.items()},
                "web_sources": {k: v.to_dict() for k, v in self.web_sources.items()},
                "staleness_checks": {k: v.to_dict() for k, v in self.staleness_checks.items()},
                "triggers": [t.to_dict() for t in self.triggers],
                "living_document_status": self.get_living_document_status(),
            }
        )

        return base_export


class ProvenanceValidator:
    """
    Validates evidence provenance for debate conclusions.

    Provides automated verification that:
    - All claims have traceable evidence
    - Evidence sources are still valid
    - No circular dependencies exist
    - Provenance chains are intact
    """

    def __init__(self, manager: EnhancedProvenanceManager):
        self.manager = manager

    async def full_validation(self) -> dict:
        """Run full provenance validation."""
        results: dict[str, Any] = {
            "validation_time": datetime.now().isoformat(),
            "debate_id": self.manager.debate_id,
            "chain_integrity": self._validate_chain(),
            "evidence_coverage": self._validate_coverage(),
            "circular_dependencies": self._check_circular(),
            "staleness": await self._check_staleness(),
        }

        # Overall pass/fail
        results["passed"] = all(
            [
                results["chain_integrity"]["valid"],
                results["evidence_coverage"]["ratio"] > 0.5,
                len(results["circular_dependencies"]) == 0,
                results["staleness"]["freshness_ratio"] > 0.7,
            ]
        )

        return results

    def _validate_chain(self) -> dict:
        """Validate provenance chain integrity."""
        valid, errors = self.manager.verify_chain_integrity()
        return {
            "valid": valid,
            "errors": errors,
            "record_count": len(self.manager.chain.records),
        }

    def _validate_coverage(self) -> dict:
        """Check evidence coverage across claims."""
        total_claims = len(self.manager.graph.claim_citations)
        claims_with_evidence = sum(
            1 for citations in self.manager.graph.claim_citations.values() if citations
        )

        return {
            "total_claims": total_claims,
            "claims_with_evidence": claims_with_evidence,
            "ratio": claims_with_evidence / total_claims if total_claims > 0 else 0,
        }

    def _check_circular(self) -> list[list[str]]:
        """Check for circular citation dependencies."""
        return self.manager.graph.find_circular_dependencies()

    async def _check_staleness(self) -> dict:
        """Check evidence staleness."""
        checks = await self.manager.check_all_staleness()

        fresh = sum(1 for c in checks if c.status == StalenessStatus.FRESH)
        total = len(checks)

        return {
            "total_checked": total,
            "fresh_count": fresh,
            "stale_count": total - fresh,
            "freshness_ratio": fresh / total if total > 0 else 1.0,
        }
