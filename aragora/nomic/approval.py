"""
Approval workflows for multi-agent code changes.

Provides multi-level approval gates for code changes:
- INFO: Notify, auto-approve after timeout
- REVIEW: Require one approval
- CRITICAL: Require all approvers

Policies determine approval levels based on file paths and change sensitivity.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import Callable
import uuid

logger = logging.getLogger(__name__)


class ApprovalLevel(Enum):
    """Approval requirement levels."""

    INFO = "info"  # Notify, auto-approve after timeout
    REVIEW = "review"  # Require at least one approval
    CRITICAL = "critical"  # Require all approvers


class ApprovalStatus(Enum):
    """Status of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


@dataclass
class FileChange:
    """Represents a change to a file."""

    path: str
    change_type: str  # add, modify, delete
    content_before: str | None = None
    content_after: str | None = None
    lines_added: int = 0
    lines_removed: int = 0
    is_binary: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "path": self.path,
            "change_type": self.change_type,
            "lines_added": self.lines_added,
            "lines_removed": self.lines_removed,
            "is_binary": self.is_binary,
        }


@dataclass
class ApproverVote:
    """Vote from an approver."""

    approver_id: str
    approved: bool
    comment: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "approver_id": self.approver_id,
            "approved": self.approved,
            "comment": self.comment,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ApprovalRequest:
    """Request for approval of changes."""

    request_id: str
    changes: list[FileChange]
    level: ApprovalLevel
    approvers: list[str]
    status: ApprovalStatus = ApprovalStatus.PENDING
    votes: list[ApproverVote] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    timeout_seconds: int = 300  # 5 minutes default
    description: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_id": self.request_id,
            "changes": [c.to_dict() for c in self.changes],
            "level": self.level.value,
            "approvers": self.approvers,
            "status": self.status.value,
            "votes": [v.to_dict() for v in self.votes],
            "created_at": self.created_at.isoformat(),
            "timeout_seconds": self.timeout_seconds,
            "description": self.description,
            "context": self.context,
        }


@dataclass
class ApprovalResult:
    """Result of an approval request."""

    request_id: str
    status: ApprovalStatus
    approved: bool
    votes: list[ApproverVote] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_id": self.request_id,
            "status": self.status.value,
            "approved": self.approved,
            "votes": [v.to_dict() for v in self.votes],
            "elapsed_seconds": self.elapsed_seconds,
            "message": self.message,
        }


class ApprovalPolicy:
    """
    Policy for determining approval levels based on file paths.

    Supports pattern matching with glob-style wildcards and regex.
    """

    def __init__(self):
        # Default patterns for each level
        self._critical_patterns: list[str] = [
            "CLAUDE.md",
            "*.env*",
            "credentials*",
            "secrets*",
            "**/core.py",
            "**/core_types.py",
            "**/core/__init__.py",
            "**/__init__.py",
            "pyproject.toml",
            "setup.py",
            "Makefile",
            "Dockerfile*",
            ".github/**",
            "**/security/**",
            "**/auth/**",
            "**/crypto/**",
        ]
        self._review_patterns: list[str] = [
            "**/handlers/**",
            "**/api/**",
            "**/routes/**",
            "**/models/**",
            "**/services/**",
            "**/database/**",
            "requirements*.txt",
        ]
        self._info_patterns: list[str] = [
            "tests/**",
            "docs/**",
            "*.md",
            "**/*.md",
            "**/test_*.py",
        ]

    def add_critical_pattern(self, pattern: str) -> None:
        """Add a pattern that requires critical approval."""
        if pattern not in self._critical_patterns:
            self._critical_patterns.insert(0, pattern)

    def add_review_pattern(self, pattern: str) -> None:
        """Add a pattern that requires review approval."""
        if pattern not in self._review_patterns:
            self._review_patterns.insert(0, pattern)

    def add_info_pattern(self, pattern: str) -> None:
        """Add a pattern that only requires info notification."""
        if pattern not in self._info_patterns:
            self._info_patterns.insert(0, pattern)

    def _matches_pattern(self, path: str, pattern: str) -> bool:
        """Check if a path matches a glob-style pattern."""
        # Convert glob pattern to regex
        regex_pattern = pattern.replace(".", r"\.")
        regex_pattern = regex_pattern.replace("**", "{{DOUBLE_STAR}}")
        regex_pattern = regex_pattern.replace("*", r"[^/]*")
        regex_pattern = regex_pattern.replace("{{DOUBLE_STAR}}", r".*")
        regex_pattern = f"^{regex_pattern}$"
        return bool(re.match(regex_pattern, path))

    def get_approval_level(self, file_path: str) -> ApprovalLevel:
        """
        Determine the approval level required for a file.

        Args:
            file_path: Path to the file (relative or absolute)

        Returns:
            ApprovalLevel for the file
        """
        # Normalize path
        path = Path(file_path).as_posix()

        # Check critical patterns first (highest priority)
        for pattern in self._critical_patterns:
            if self._matches_pattern(path, pattern):
                return ApprovalLevel.CRITICAL

        # Check review patterns
        for pattern in self._review_patterns:
            if self._matches_pattern(path, pattern):
                return ApprovalLevel.REVIEW

        # Check info patterns
        for pattern in self._info_patterns:
            if self._matches_pattern(path, pattern):
                return ApprovalLevel.INFO

        # Default to review for unknown files
        return ApprovalLevel.REVIEW

    def get_max_approval_level(self, changes: list[FileChange]) -> ApprovalLevel:
        """Get the highest approval level required for a set of changes."""
        if not changes:
            return ApprovalLevel.INFO

        levels = [self.get_approval_level(c.path) for c in changes]

        # Priority: CRITICAL > REVIEW > INFO
        if ApprovalLevel.CRITICAL in levels:
            return ApprovalLevel.CRITICAL
        if ApprovalLevel.REVIEW in levels:
            return ApprovalLevel.REVIEW
        return ApprovalLevel.INFO


class ApprovalWorkflow:
    """
    Multi-level approval gates for code changes.

    Manages approval requests, tracks votes, and enforces policies.
    """

    def __init__(
        self,
        policy: ApprovalPolicy | None = None,
        notify_fn: Callable[[ApprovalRequest], None] | None = None,
        default_approvers: list[str] | None = None,
    ):
        """
        Initialize the approval workflow.

        Args:
            policy: Policy for determining approval levels
            notify_fn: Function to notify approvers
            default_approvers: Default list of approver IDs
        """
        self.policy = policy or ApprovalPolicy()
        self._notify = notify_fn or (lambda r: None)
        self.default_approvers = default_approvers or []
        self._requests: dict[str, ApprovalRequest] = {}
        self._pending_tasks: dict[str, asyncio.Task] = {}

    def create_request(
        self,
        changes: list[FileChange],
        approvers: list[str] | None = None,
        level: ApprovalLevel | None = None,
        description: str | None = None,
        timeout_seconds: int = 300,
        context: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """
        Create an approval request for changes.

        Args:
            changes: List of file changes
            approvers: List of approver IDs (defaults to default_approvers)
            level: Override approval level (auto-detected if None)
            description: Description of the changes
            timeout_seconds: Timeout for auto-approval (INFO level only)
            context: Additional context for the request

        Returns:
            ApprovalRequest
        """
        request_id = str(uuid.uuid4())[:8]

        # Determine approval level
        if level is None:
            level = self.policy.get_max_approval_level(changes)

        # Use default approvers if not specified
        approver_list = approvers or self.default_approvers

        request = ApprovalRequest(
            request_id=request_id,
            changes=changes,
            level=level,
            approvers=approver_list,
            description=description,
            timeout_seconds=timeout_seconds,
            context=context or {},
        )

        self._requests[request_id] = request
        logger.info(
            "[%s] Created %s approval request for %s changes, %s approvers",
            request_id,
            level.value,
            len(changes),
            len(approver_list),
        )

        return request

    async def request_approval(
        self,
        changes: list[FileChange],
        approvers: list[str] | None = None,
        level: ApprovalLevel | None = None,
        description: str | None = None,
        timeout_seconds: int = 300,
        context: dict[str, Any] | None = None,
    ) -> ApprovalResult:
        """
        Request approval for changes and wait for result.

        For INFO level: Auto-approves after timeout if no rejection
        For REVIEW level: Requires at least one approval
        For CRITICAL level: Requires all approvers to approve

        Args:
            changes: List of file changes
            approvers: List of approver IDs
            level: Override approval level
            description: Description of the changes
            timeout_seconds: Timeout for waiting
            context: Additional context

        Returns:
            ApprovalResult with final status
        """
        request = self.create_request(
            changes=changes,
            approvers=approvers,
            level=level,
            description=description,
            timeout_seconds=timeout_seconds,
            context=context,
        )

        # Notify approvers
        self._notify(request)

        start_time = time.time()

        # For INFO level, just wait for timeout
        if request.level == ApprovalLevel.INFO:
            await asyncio.sleep(min(timeout_seconds, 5))  # Quick timeout for INFO
            if request.status == ApprovalStatus.PENDING:
                request.status = ApprovalStatus.APPROVED
                elapsed = time.time() - start_time
                return ApprovalResult(
                    request_id=request.request_id,
                    status=ApprovalStatus.APPROVED,
                    approved=True,
                    elapsed_seconds=elapsed,
                    message="Auto-approved (INFO level, no objections)",
                )

        # For REVIEW and CRITICAL, wait for votes
        return await self._wait_for_approval(request, start_time)

    async def _wait_for_approval(
        self,
        request: ApprovalRequest,
        start_time: float,
    ) -> ApprovalResult:
        """Wait for approval votes."""
        timeout = request.timeout_seconds
        check_interval = 0.5

        while True:
            # Check if request is resolved
            if request.status != ApprovalStatus.PENDING:
                break

            # Check for timeout
            elapsed = time.time() - start_time
            if elapsed > timeout:
                request.status = ApprovalStatus.TIMED_OUT
                logger.warning(
                    "[%s] Approval request timed out after %.1fs", request.request_id, elapsed
                )
                break

            # Check if enough votes
            if self._check_approval_complete(request):
                break

            await asyncio.sleep(check_interval)

        # Calculate result
        elapsed = time.time() - start_time
        approved = request.status == ApprovalStatus.APPROVED

        return ApprovalResult(
            request_id=request.request_id,
            status=request.status,
            approved=approved,
            votes=request.votes,
            elapsed_seconds=elapsed,
            message=self._get_result_message(request),
        )

    def _check_approval_complete(self, request: ApprovalRequest) -> bool:
        """Check if approval is complete based on level."""
        if not request.votes:
            return False

        # Check for any rejections
        rejections = [v for v in request.votes if not v.approved]
        if rejections:
            request.status = ApprovalStatus.REJECTED
            return True

        approvals = [v for v in request.votes if v.approved]

        if request.level == ApprovalLevel.REVIEW:
            # Need at least one approval
            if len(approvals) >= 1:
                request.status = ApprovalStatus.APPROVED
                return True

        elif request.level == ApprovalLevel.CRITICAL:
            # Need all approvers
            approved_ids = {v.approver_id for v in approvals}
            required_ids = set(request.approvers)
            if approved_ids >= required_ids:
                request.status = ApprovalStatus.APPROVED
                return True

        return False

    def _get_result_message(self, request: ApprovalRequest) -> str:
        """Get a human-readable result message."""
        if request.status == ApprovalStatus.APPROVED:
            return f"Approved with {len(request.votes)} vote(s)"
        elif request.status == ApprovalStatus.REJECTED:
            rejections = [v for v in request.votes if not v.approved]
            return f"Rejected by {rejections[0].approver_id}: {rejections[0].comment or 'No reason given'}"
        elif request.status == ApprovalStatus.TIMED_OUT:
            return f"Timed out waiting for {len(request.approvers)} approver(s)"
        elif request.status == ApprovalStatus.CANCELLED:
            return "Request was cancelled"
        return "Pending"

    def submit_vote(
        self,
        request_id: str,
        approver_id: str,
        approved: bool,
        comment: str | None = None,
    ) -> bool:
        """
        Submit a vote for an approval request.

        Args:
            request_id: ID of the approval request
            approver_id: ID of the approver
            approved: Whether to approve or reject
            comment: Optional comment

        Returns:
            True if vote was accepted, False otherwise
        """
        if request_id not in self._requests:
            logger.warning("[%s] Approval request not found", request_id)
            return False

        request = self._requests[request_id]

        if request.status != ApprovalStatus.PENDING:
            logger.warning("[%s] Cannot vote on %s request", request_id, request.status.value)
            return False

        # Check if approver is authorized
        if request.approvers and approver_id not in request.approvers:
            logger.warning("[%s] %s is not an authorized approver", request_id, approver_id)
            return False

        # Check for duplicate vote
        existing = [v for v in request.votes if v.approver_id == approver_id]
        if existing:
            logger.warning("[%s] %s has already voted", request_id, approver_id)
            return False

        # Record vote
        vote = ApproverVote(
            approver_id=approver_id,
            approved=approved,
            comment=comment,
        )
        request.votes.append(vote)

        logger.info(
            "[%s] %s voted: %s", request_id, approver_id, "approved" if approved else "rejected"
        )

        # Check if approval is complete
        self._check_approval_complete(request)

        return True

    def cancel_request(self, request_id: str, reason: str | None = None) -> bool:
        """Cancel an approval request."""
        if request_id not in self._requests:
            return False

        request = self._requests[request_id]
        if request.status != ApprovalStatus.PENDING:
            return False

        request.status = ApprovalStatus.CANCELLED
        logger.info("[%s] Request cancelled: %s", request_id, reason or "No reason given")
        return True

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Get an approval request by ID."""
        return self._requests.get(request_id)

    def get_pending_requests(self) -> list[ApprovalRequest]:
        """Get all pending approval requests."""
        return [r for r in self._requests.values() if r.status == ApprovalStatus.PENDING]

    def get_policy(self, file_path: str) -> ApprovalLevel:
        """Get the approval policy for a file."""
        return self.policy.get_approval_level(file_path)


# =============================================================================
# Convenience Functions
# =============================================================================


def quick_approval_check(
    changes: list[FileChange],
    policy: ApprovalPolicy | None = None,
) -> ApprovalLevel:
    """Quick check of what approval level is needed for changes."""
    p = policy or ApprovalPolicy()
    return p.get_max_approval_level(changes)


def is_protected_file(file_path: str, policy: ApprovalPolicy | None = None) -> bool:
    """Check if a file requires critical approval."""
    p = policy or ApprovalPolicy()
    return p.get_approval_level(file_path) == ApprovalLevel.CRITICAL


# =============================================================================
# Self-Improvement Approval Gate
# =============================================================================

# Patterns indicating safety-critical operations in prompts
_SAFETY_KEYWORDS = frozenset(
    {
        "security",
        "auth",
        "encryption",
        "key_rotation",
        "secrets",
        "password",
        "token",
        "credential",
    }
)

_DANGEROUS_OPERATIONS = frozenset(
    {
        "force push",
        "reset --hard",
        "drop table",
        "rm -rf",
        "delete database",
        "truncate",
    }
)


class ApprovalDecision(str, Enum):
    """Decision from the self-improvement approval gate."""

    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"
    SKIP = "skip"


class ApprovalGate:
    """Lightweight approval gate for self-improvement subtask execution.

    Three modes:
        cli:  Interactive terminal prompt for human-in-the-loop.
        api:  POST instruction to a callback URL and await response.
        auto: Risk-based auto-approve (low/medium → approve, high → defer).

    Usage::

        gate = ApprovalGate(mode="auto")
        decision = await gate.request_approval(instruction)
        if decision == ApprovalDecision.APPROVE:
            ...execute...
    """

    def __init__(
        self,
        mode: str = "auto",
        callback_url: str | None = None,
    ) -> None:
        if mode not in ("cli", "api", "auto"):
            raise ValueError(f"Invalid approval mode: {mode!r}")
        self.mode = mode
        self.callback_url = callback_url
        self._policy = ApprovalPolicy()

    async def request_approval(self, instruction: Any) -> ApprovalDecision:
        """Request approval for executing an instruction.

        Args:
            instruction: Object with ``to_agent_prompt()``, ``subtask_id``,
                and optionally ``files`` attributes.

        Returns:
            ApprovalDecision indicating whether to proceed.
        """
        if self.mode == "cli":
            return self._cli_prompt(instruction)
        elif self.mode == "api":
            return await self._api_callback(instruction)
        return self._auto_approve(instruction)

    # -- Mode implementations -------------------------------------------------

    def _cli_prompt(self, instruction: Any) -> ApprovalDecision:
        """Interactive CLI approval prompt."""
        subtask_id = getattr(instruction, "subtask_id", "unknown")[:30]
        prompt_text = self._get_prompt_text(instruction)
        risk = self._assess_risk(instruction)
        files = getattr(instruction, "files", [])

        print(f"\n{'=' * 60}")
        print(f"APPROVAL REQUIRED — subtask: {subtask_id}")
        print(f"Risk level: {risk}")
        if files:
            print(f"Files affected: {', '.join(str(f) for f in files[:10])}")
        print(f"\nInstruction preview:\n{prompt_text[:500]}")
        print(f"{'=' * 60}")

        try:
            response = input("[A]pprove / [R]eject / [S]kip / [D]efer? ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return ApprovalDecision.REJECT

        _map = {
            "a": ApprovalDecision.APPROVE,
            "approve": ApprovalDecision.APPROVE,
            "y": ApprovalDecision.APPROVE,
            "yes": ApprovalDecision.APPROVE,
            "r": ApprovalDecision.REJECT,
            "reject": ApprovalDecision.REJECT,
            "n": ApprovalDecision.REJECT,
            "no": ApprovalDecision.REJECT,
            "s": ApprovalDecision.SKIP,
            "skip": ApprovalDecision.SKIP,
            "d": ApprovalDecision.DEFER,
            "defer": ApprovalDecision.DEFER,
        }
        return _map.get(response, ApprovalDecision.REJECT)

    async def _api_callback(self, instruction: Any) -> ApprovalDecision:
        """POST instruction to a callback URL for external approval."""
        if not self.callback_url:
            logger.warning("API approval mode but no callback_url configured")
            return ApprovalDecision.DEFER

        try:
            import aiohttp
        except ImportError:
            logger.warning("aiohttp not available for API approval callback")
            return ApprovalDecision.DEFER

        subtask_id = getattr(instruction, "subtask_id", "unknown")
        payload = {
            "subtask_id": subtask_id,
            "prompt": self._get_prompt_text(instruction)[:2000],
            "risk_level": self._assess_risk(instruction),
            "files": [str(f) for f in getattr(instruction, "files", [])][:20],
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.callback_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=300),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        decision_str = data.get("decision", "reject")
                        try:
                            return ApprovalDecision(decision_str)
                        except ValueError:
                            return ApprovalDecision.REJECT
                    logger.warning("Approval API returned status %d", resp.status)
                    return ApprovalDecision.DEFER
        except (OSError, ValueError) as exc:
            logger.warning("Approval API callback failed: %s", exc)
            return ApprovalDecision.DEFER

    def _auto_approve(self, instruction: Any) -> ApprovalDecision:
        """Risk-based auto-approval for autonomous mode."""
        risk = self._assess_risk(instruction)
        subtask_id = getattr(instruction, "subtask_id", "unknown")[:20]

        if risk == "high":
            logger.info("auto_deferred subtask=%s risk=high", subtask_id)
            return ApprovalDecision.DEFER

        logger.info("auto_approved subtask=%s risk=%s", subtask_id, risk)
        return ApprovalDecision.APPROVE

    # -- Helpers --------------------------------------------------------------

    def _assess_risk(self, instruction: Any) -> str:
        """Assess the risk level of an instruction.

        Returns ``'low'``, ``'medium'``, or ``'high'``.
        """
        files = [str(f) for f in getattr(instruction, "files", [])]
        prompt = self._get_prompt_text(instruction).lower()

        # Use the existing ApprovalPolicy for file-level risk
        for f in files:
            level = self._policy.get_approval_level(f)
            if level == ApprovalLevel.CRITICAL:
                return "high"
            if level == ApprovalLevel.REVIEW:
                # Only escalate if combined with dangerous operations
                if any(op in prompt for op in _DANGEROUS_OPERATIONS):
                    return "high"

        # Check for dangerous operations even without file context
        if any(op in prompt for op in _DANGEROUS_OPERATIONS):
            return "high"

        # Safety-critical keywords combined with destructive verbs
        if any(kw in prompt for kw in _SAFETY_KEYWORDS) and any(
            word in prompt for word in ("delete", "remove", "drop", "reset")
        ):
            return "high"

        # Medium risk: modifying tests or CI config
        for f in files:
            if "test" in f or ".github" in f or "ci" in f.lower():
                return "medium"

        return "low"

    @staticmethod
    def _get_prompt_text(instruction: Any) -> str:
        """Extract prompt text from an instruction object."""
        try:
            return instruction.to_agent_prompt()
        except (AttributeError, TypeError):
            return str(instruction)
