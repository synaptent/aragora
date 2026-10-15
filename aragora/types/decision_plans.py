"""Decision plan lifecycle, approval and risk enums.

``aragora.pipeline.decision_plan`` builds and runs decision plans with these values, and
``aragora.debate`` sets them on plans it receives without importing the pipeline. The
pipeline modules that defined them re-export the same classes.
"""

from __future__ import annotations

from enum import Enum


class PlanStatus(Enum):
    """Lifecycle status of a DecisionPlan."""

    CREATED = "created"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ApprovalMode(Enum):
    """How human approval is determined."""

    ALWAYS = "always"  # Always require human approval
    RISK_BASED = "risk_based"  # Auto-approve if no critical/high risks
    CONFIDENCE_BASED = "confidence_based"  # Auto-approve above confidence threshold
    NEVER = "never"  # Skip approval (for automated pipelines)


class RiskLevel(Enum):
    """Risk severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


__all__ = ["ApprovalMode", "PlanStatus", "RiskLevel"]
