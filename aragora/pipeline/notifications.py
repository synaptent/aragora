"""Plan lifecycle notification service.

Sends notifications through configured channels when plan lifecycle events
occur (creation, approval, rejection, execution start/complete/fail).

Integrates with the existing ``aragora.notifications`` service as a thin
adapter, following the same convenience-function pattern used by
``notify_finding_created``, ``notify_checkpoint_approval_requested``, etc.

Usage:
    from aragora.pipeline.notifications import (
        notify_plan_created,
        notify_plan_approved,
        notify_plan_rejected,
        notify_execution_started,
        notify_execution_completed,
        notify_execution_failed,
    )

    await notify_plan_created(plan)
    await notify_plan_approved(plan, approved_by="user-123")

Every notification carries the plan's ``org_id`` so org-owned recipients only
receive their own tenant's plans. A plan without an org, or one whose org
differs from the ``org_id`` the caller acts for, is not announced at all.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.notifications.models import Notification
    from aragora.pipeline.decision_plan.core import DecisionPlan

logger = logging.getLogger(__name__)


def _owning_org(plan: DecisionPlan, org_id: str | None) -> str | None:
    """The plan's org when it may be announced for ``org_id``; otherwise None.

    ``org_id`` of None means the caller acts for whichever org owns the plan.
    """
    plan_org = str(getattr(plan, "org_id", None) or "").strip()
    if not plan_org:
        return None
    if org_id is not None and str(org_id).strip() != plan_org:
        return None
    return plan_org


async def _send(notification: Notification, event: str) -> list[Any]:
    from aragora.notifications.service import get_notification_service

    service = get_notification_service()
    results = await service.notify(notification)
    await service.notify_all_webhooks(notification, event)
    return results


def _refused(plan: DecisionPlan, event: str) -> list[Any]:
    logger.warning(
        "Skipping %s notification for plan %s: not owned by the acting org", event, plan.id
    )
    return []


def _risk_to_severity(plan: DecisionPlan) -> str:
    """Map a plan's highest risk level to notification severity."""
    from aragora.pipeline.risk_register import RiskLevel

    mapping = {
        RiskLevel.CRITICAL: "critical",
        RiskLevel.HIGH: "error",
        RiskLevel.MEDIUM: "warning",
        RiskLevel.LOW: "info",
    }
    return mapping.get(plan.highest_risk_level, "info")


def _plan_summary_text(plan: DecisionPlan) -> str:
    """Build a concise summary block for embedding in notification messages."""
    parts = [f"Task: {plan.task[:200]}"]

    if plan.debate_result:
        parts.append(f"Confidence: {plan.debate_result.confidence:.0%}")

    parts.append(f"Risk: {plan.highest_risk_level.value}")

    if plan.risk_register:
        s = plan.risk_register.summary
        parts.append(
            f"Risks: {s['total_risks']} total ({s['critical']} critical, {s['high']} high)"
        )

    if plan.implement_plan:
        parts.append(f"Tasks: {len(plan.implement_plan.tasks)}")

    if plan.budget.limit_usd is not None:
        parts.append(f"Budget: ${plan.budget.limit_usd:.2f}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Convenience notification functions
# ---------------------------------------------------------------------------


async def notify_plan_created(
    plan: DecisionPlan,
    channels: list[str] | None = None,
    action_url: str | None = None,
    *,
    org_id: str | None = None,
) -> list[Any]:
    """Notify approvers that a plan needs review.

    Args:
        plan: The newly created DecisionPlan.
        channels: Optional explicit channel list (for tests/overrides).
        action_url: URL where approvers can review the plan.
        org_id: Org the caller acts for; must own the plan when given.

    Returns:
        List of NotificationResult from each channel.
    """
    from aragora.notifications.models import Notification, NotificationPriority

    owner = _owning_org(plan, org_id)
    if owner is None:
        return _refused(plan, "plan.created")

    severity = _risk_to_severity(plan)
    priority = (
        NotificationPriority.HIGH if plan.requires_human_approval else NotificationPriority.NORMAL
    )

    title = "Plan Awaiting Approval" if plan.requires_human_approval else "New Plan Created"
    body = _plan_summary_text(plan)
    if plan.requires_human_approval:
        body += "\n\nThis plan requires human approval before execution."

    url = action_url or f"/api/v1/plans/{plan.id}"

    notification = Notification(
        title=title,
        message=body,
        severity=severity,
        priority=priority,
        resource_type="decision_plan",
        resource_id=plan.id,
        org_id=owner,
        action_url=url,
        action_label="Review Plan",
        metadata={
            "plan_id": plan.id,
            "debate_id": plan.debate_id,
            "org_id": owner,
            "event": "plan.created",
            "requires_approval": plan.requires_human_approval,
        },
    )

    return await _send(notification, "plan.created")


async def notify_plan_approved(
    plan: DecisionPlan,
    approved_by: str,
    channels: list[str] | None = None,
    *,
    org_id: str | None = None,
) -> list[Any]:
    """Notify stakeholders that a plan was approved.

    Args:
        plan: The approved DecisionPlan.
        approved_by: User ID of the approver.
        channels: Optional explicit channel list.
        org_id: Org the caller acts for; must own the plan when given.

    Returns:
        List of NotificationResult.
    """
    from aragora.notifications.models import Notification, NotificationPriority

    owner = _owning_org(plan, org_id)
    if owner is None:
        return _refused(plan, "plan.approved")

    body = _plan_summary_text(plan)
    body += f"\n\nApproved by: {approved_by}"
    if plan.approval_record and plan.approval_record.reason:
        body += f"\nReason: {plan.approval_record.reason}"
    if plan.approval_record and plan.approval_record.conditions:
        body += f"\nConditions: {', '.join(plan.approval_record.conditions)}"

    notification = Notification(
        title=f"Plan Approved: {plan.task[:60]}",
        message=body,
        severity="info",
        priority=NotificationPriority.NORMAL,
        resource_type="decision_plan",
        resource_id=plan.id,
        org_id=owner,
        action_url=f"/api/v1/plans/{plan.id}",
        action_label="View Plan",
        metadata={
            "plan_id": plan.id,
            "debate_id": plan.debate_id,
            "org_id": owner,
            "event": "plan.approved",
            "approved_by": approved_by,
        },
    )

    return await _send(notification, "plan.approved")


async def notify_plan_rejected(
    plan: DecisionPlan,
    rejected_by: str,
    reason: str,
    channels: list[str] | None = None,
    *,
    org_id: str | None = None,
) -> list[Any]:
    """Notify stakeholders that a plan was rejected.

    Args:
        plan: The rejected DecisionPlan.
        rejected_by: User ID of the rejector.
        reason: Reason for rejection.
        channels: Optional explicit channel list.
        org_id: Org the caller acts for; must own the plan when given.

    Returns:
        List of NotificationResult.
    """
    from aragora.notifications.models import Notification, NotificationPriority

    owner = _owning_org(plan, org_id)
    if owner is None:
        return _refused(plan, "plan.rejected")

    body = _plan_summary_text(plan)
    body += f"\n\nRejected by: {rejected_by}"
    body += f"\nReason: {reason}"

    notification = Notification(
        title=f"Plan Rejected: {plan.task[:60]}",
        message=body,
        severity="warning",
        priority=NotificationPriority.HIGH,
        resource_type="decision_plan",
        resource_id=plan.id,
        org_id=owner,
        action_url=f"/api/v1/plans/{plan.id}",
        action_label="View Plan",
        metadata={
            "plan_id": plan.id,
            "debate_id": plan.debate_id,
            "org_id": owner,
            "event": "plan.rejected",
            "rejected_by": rejected_by,
            "reason": reason,
        },
    )

    return await _send(notification, "plan.rejected")


async def notify_execution_started(
    plan: DecisionPlan,
    channels: list[str] | None = None,
    *,
    org_id: str | None = None,
) -> list[Any]:
    """Notify that plan execution has begun.

    Args:
        plan: The plan being executed.
        channels: Optional explicit channel list.
        org_id: Org the caller acts for; must own the plan when given.

    Returns:
        List of NotificationResult.
    """
    from aragora.notifications.models import Notification, NotificationPriority

    owner = _owning_org(plan, org_id)
    if owner is None:
        return _refused(plan, "plan.execution_started")

    task_count = len(plan.implement_plan.tasks) if plan.implement_plan else 0
    body = _plan_summary_text(plan)
    body += f"\n\nExecution started with {task_count} tasks."

    notification = Notification(
        title=f"Execution Started: {plan.task[:60]}",
        message=body,
        severity="info",
        priority=NotificationPriority.NORMAL,
        resource_type="decision_plan",
        resource_id=plan.id,
        org_id=owner,
        action_url=f"/api/v1/plans/{plan.id}",
        action_label="View Execution",
        metadata={
            "plan_id": plan.id,
            "debate_id": plan.debate_id,
            "org_id": owner,
            "event": "plan.execution_started",
            "task_count": task_count,
        },
    )

    return await _send(notification, "plan.execution_started")


async def notify_execution_completed(
    plan: DecisionPlan,
    result: dict[str, Any] | None = None,
    channels: list[str] | None = None,
    *,
    org_id: str | None = None,
) -> list[Any]:
    """Notify that plan execution completed successfully.

    Args:
        plan: The completed plan.
        result: Optional execution result summary.
        channels: Optional explicit channel list.
        org_id: Org the caller acts for; must own the plan when given.

    Returns:
        List of NotificationResult.
    """
    from aragora.notifications.models import Notification, NotificationPriority

    owner = _owning_org(plan, org_id)
    if owner is None:
        return _refused(plan, "plan.execution_completed")

    body = _plan_summary_text(plan)
    body += "\n\nExecution completed successfully."
    if result:
        completed = result.get("completed_tasks", 0)
        failed = result.get("failed_tasks", 0)
        elapsed = result.get("elapsed_seconds", 0)
        body += f"\nCompleted: {completed}, Failed: {failed}"
        if elapsed:
            body += f", Duration: {elapsed:.1f}s"

    notification = Notification(
        title=f"Execution Complete: {plan.task[:60]}",
        message=body,
        severity="info",
        priority=NotificationPriority.NORMAL,
        resource_type="decision_plan",
        resource_id=plan.id,
        org_id=owner,
        action_url=f"/api/v1/plans/{plan.id}",
        action_label="View Results",
        metadata={
            "plan_id": plan.id,
            "debate_id": plan.debate_id,
            "org_id": owner,
            "event": "plan.execution_completed",
            "result": result or {},
        },
    )

    return await _send(notification, "plan.execution_completed")


async def notify_execution_failed(
    plan: DecisionPlan,
    error: str,
    channels: list[str] | None = None,
    *,
    org_id: str | None = None,
) -> list[Any]:
    """Notify that plan execution failed.

    Args:
        plan: The failed plan.
        error: Error message describing the failure.
        channels: Optional explicit channel list.
        org_id: Org the caller acts for; must own the plan when given.

    Returns:
        List of NotificationResult.
    """
    from aragora.notifications.models import Notification, NotificationPriority

    owner = _owning_org(plan, org_id)
    if owner is None:
        return _refused(plan, "plan.execution_failed")

    body = _plan_summary_text(plan)
    body += f"\n\nExecution failed: {error}"

    notification = Notification(
        title=f"Execution Failed: {plan.task[:60]}",
        message=body,
        severity="error",
        priority=NotificationPriority.URGENT,
        resource_type="decision_plan",
        resource_id=plan.id,
        org_id=owner,
        action_url=f"/api/v1/plans/{plan.id}",
        action_label="View Error",
        metadata={
            "plan_id": plan.id,
            "debate_id": plan.debate_id,
            "org_id": owner,
            "event": "plan.execution_failed",
            "error": error,
        },
    )

    return await _send(notification, "plan.execution_failed")


__all__ = [
    "notify_plan_created",
    "notify_plan_approved",
    "notify_plan_rejected",
    "notify_execution_started",
    "notify_execution_completed",
    "notify_execution_failed",
]
