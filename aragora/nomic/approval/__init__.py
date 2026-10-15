"""
Change-approval workflows (compatibility path).

The module lives in :mod:`aragora.agents.change_approval`; this module re-exports the same objects.
"""

from __future__ import annotations

from aragora.agents.change_approval import (
    ApprovalDecision,
    ApprovalGate,
    ApprovalLevel,
    ApprovalPolicy,
    ApprovalRequest,
    ApprovalResult,
    ApprovalStatus,
    ApprovalWorkflow,
    ApproverVote,
    FileChange,
    is_protected_file,
    quick_approval_check,
)

__all__ = [
    "ApprovalDecision",
    "ApprovalGate",
    "ApprovalLevel",
    "ApprovalPolicy",
    "ApprovalRequest",
    "ApprovalResult",
    "ApprovalStatus",
    "ApprovalWorkflow",
    "ApproverVote",
    "FileChange",
    "is_protected_file",
    "quick_approval_check",
]
