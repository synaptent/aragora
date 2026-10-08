"""Tests for plan lifecycle notification service.

Validates that each plan lifecycle event generates the correct notification
with proper titles, severity, priority, metadata, and webhook event types.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.pipeline.decision_plan.core import (
    ApprovalMode,
    ApprovalRecord,
    BudgetAllocation,
    DecisionPlan,
    PlanStatus,
)
from aragora.pipeline.risk_register import Risk, RiskCategory, RiskLevel, RiskRegister
from aragora.implement.types import ImplementPlan, ImplementTask

ORG = "org-a"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def basic_plan():
    """A minimal DecisionPlan for testing."""
    return DecisionPlan(
        id="dp-test001",
        debate_id="d-abc123",
        task="Refactor the billing module",
        status=PlanStatus.CREATED,
        approval_mode=ApprovalMode.RISK_BASED,
        org_id=ORG,
    )


@pytest.fixture
def plan_with_risks():
    """A plan with a risk register containing critical risks."""
    plan = DecisionPlan(
        id="dp-risk001",
        debate_id="d-risk123",
        task="Deploy new authentication provider",
        status=PlanStatus.AWAITING_APPROVAL,
        approval_mode=ApprovalMode.ALWAYS,
        budget=BudgetAllocation(limit_usd=500.0),
        org_id=ORG,
    )
    plan.risk_register = RiskRegister(
        debate_id="d-risk123",
        risks=[
            Risk(
                id="r-1",
                title="Auth downtime",
                description="Migration may cause auth downtime",
                level=RiskLevel.CRITICAL,
                category=RiskCategory.SECURITY,
                source="debate",
                mitigation="Staged rollout",
            ),
            Risk(
                id="r-2",
                title="Token invalidation",
                description="Existing tokens may be invalidated",
                level=RiskLevel.HIGH,
                category=RiskCategory.SECURITY,
                source="debate",
                mitigation="Grace period for old tokens",
            ),
        ],
    )
    plan.implement_plan = ImplementPlan(
        design_hash="abc123",
        tasks=[
            ImplementTask(
                id="t-1",
                description="Update auth provider config",
                files=["aragora/auth/provider.py"],
                complexity="moderate",
            ),
            ImplementTask(
                id="t-2",
                description="Add migration script",
                files=["scripts/migrate_auth.py"],
                complexity="simple",
            ),
        ],
    )
    return plan


@pytest.fixture
def approved_plan(plan_with_risks):
    """A plan that has been approved."""
    plan_with_risks.approve(
        "user-approver", reason="Looks good", conditions=["Monitor after deploy"]
    )
    return plan_with_risks


@pytest.fixture
def mock_notification_service():
    """Mock the notification service for all tests."""
    service = MagicMock()
    service.notify = AsyncMock(return_value=[])
    service.notify_all_webhooks = AsyncMock(return_value=[])
    with patch(
        "aragora.notifications.service.get_notification_service",
        return_value=service,
    ):
        yield service


# ---------------------------------------------------------------------------
# notify_plan_created
# ---------------------------------------------------------------------------


class TestNotifyPlanCreated:
    """Tests for notify_plan_created."""

    @pytest.mark.asyncio
    async def test_basic_notification(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_created

        await notify_plan_created(basic_plan)

        mock_notification_service.notify.assert_awaited_once()
        notification = mock_notification_service.notify.call_args[0][0]

        assert "Plan" in notification.title
        assert basic_plan.task in notification.message
        assert notification.resource_type == "decision_plan"
        assert notification.resource_id == basic_plan.id

    @pytest.mark.asyncio
    async def test_approval_required_flag(self, plan_with_risks, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_created

        await notify_plan_created(plan_with_risks)

        notification = mock_notification_service.notify.call_args[0][0]
        assert "Approval" in notification.title
        assert "requires human approval" in notification.message.lower()
        assert notification.metadata["requires_approval"] is True

    @pytest.mark.asyncio
    async def test_risk_severity_mapping(self, plan_with_risks, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_created

        await notify_plan_created(plan_with_risks)

        notification = mock_notification_service.notify.call_args[0][0]
        # Plan has critical risks -> severity should be "critical"
        assert notification.severity == "critical"

    @pytest.mark.asyncio
    async def test_webhook_event_type(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_created

        await notify_plan_created(basic_plan)

        mock_notification_service.notify_all_webhooks.assert_awaited_once()
        args = mock_notification_service.notify_all_webhooks.call_args
        assert args[0][1] == "plan.created"

    @pytest.mark.asyncio
    async def test_custom_action_url(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_created

        await notify_plan_created(basic_plan, action_url="https://app.example.com/plans/dp-test001")

        notification = mock_notification_service.notify.call_args[0][0]
        assert notification.action_url == "https://app.example.com/plans/dp-test001"

    @pytest.mark.asyncio
    async def test_default_action_url(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_created

        await notify_plan_created(basic_plan)

        notification = mock_notification_service.notify.call_args[0][0]
        assert notification.action_url == f"/api/v1/plans/{basic_plan.id}"

    @pytest.mark.asyncio
    async def test_metadata_contains_plan_and_debate_ids(
        self, basic_plan, mock_notification_service
    ):
        from aragora.pipeline.notifications import notify_plan_created

        await notify_plan_created(basic_plan)

        notification = mock_notification_service.notify.call_args[0][0]
        assert notification.metadata["plan_id"] == basic_plan.id
        assert notification.metadata["debate_id"] == basic_plan.debate_id
        assert notification.metadata["event"] == "plan.created"

    @pytest.mark.asyncio
    async def test_budget_in_summary(self, plan_with_risks, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_created

        await notify_plan_created(plan_with_risks)

        notification = mock_notification_service.notify.call_args[0][0]
        assert "500.00" in notification.message

    @pytest.mark.asyncio
    async def test_task_count_in_summary(self, plan_with_risks, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_created

        await notify_plan_created(plan_with_risks)

        notification = mock_notification_service.notify.call_args[0][0]
        assert "Tasks: 2" in notification.message


# ---------------------------------------------------------------------------
# notify_plan_approved
# ---------------------------------------------------------------------------


class TestNotifyPlanApproved:
    """Tests for notify_plan_approved."""

    @pytest.mark.asyncio
    async def test_basic_approval(self, approved_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_approved

        await notify_plan_approved(approved_plan, approved_by="user-approver")

        mock_notification_service.notify.assert_awaited_once()
        notification = mock_notification_service.notify.call_args[0][0]

        assert "Approved" in notification.title
        assert "user-approver" in notification.message
        assert notification.severity == "info"
        assert notification.metadata["approved_by"] == "user-approver"

    @pytest.mark.asyncio
    async def test_approval_reason_included(self, approved_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_approved

        await notify_plan_approved(approved_plan, approved_by="user-approver")

        notification = mock_notification_service.notify.call_args[0][0]
        assert "Looks good" in notification.message

    @pytest.mark.asyncio
    async def test_approval_conditions_included(self, approved_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_approved

        await notify_plan_approved(approved_plan, approved_by="user-approver")

        notification = mock_notification_service.notify.call_args[0][0]
        assert "Monitor after deploy" in notification.message

    @pytest.mark.asyncio
    async def test_webhook_event_type(self, approved_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_approved

        await notify_plan_approved(approved_plan, approved_by="user-approver")

        args = mock_notification_service.notify_all_webhooks.call_args
        assert args[0][1] == "plan.approved"


# ---------------------------------------------------------------------------
# notify_plan_rejected
# ---------------------------------------------------------------------------


class TestNotifyPlanRejected:
    """Tests for notify_plan_rejected."""

    @pytest.mark.asyncio
    async def test_basic_rejection(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_rejected

        await notify_plan_rejected(
            basic_plan,
            rejected_by="user-reviewer",
            reason="Risk too high without rollback plan",
        )

        mock_notification_service.notify.assert_awaited_once()
        notification = mock_notification_service.notify.call_args[0][0]

        assert "Rejected" in notification.title
        assert "user-reviewer" in notification.message
        assert "Risk too high" in notification.message
        assert notification.severity == "warning"

    @pytest.mark.asyncio
    async def test_rejection_priority(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_rejected
        from aragora.notifications.models import NotificationPriority

        await notify_plan_rejected(basic_plan, rejected_by="admin", reason="Blocked")

        notification = mock_notification_service.notify.call_args[0][0]
        assert notification.priority == NotificationPriority.HIGH

    @pytest.mark.asyncio
    async def test_rejection_metadata(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_rejected

        await notify_plan_rejected(basic_plan, rejected_by="admin", reason="No budget")

        notification = mock_notification_service.notify.call_args[0][0]
        assert notification.metadata["rejected_by"] == "admin"
        assert notification.metadata["reason"] == "No budget"
        assert notification.metadata["event"] == "plan.rejected"

    @pytest.mark.asyncio
    async def test_webhook_event_type(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_rejected

        await notify_plan_rejected(basic_plan, rejected_by="admin", reason="No")

        args = mock_notification_service.notify_all_webhooks.call_args
        assert args[0][1] == "plan.rejected"


# ---------------------------------------------------------------------------
# notify_execution_started
# ---------------------------------------------------------------------------


class TestNotifyExecutionStarted:
    """Tests for notify_execution_started."""

    @pytest.mark.asyncio
    async def test_basic_execution_start(self, plan_with_risks, mock_notification_service):
        from aragora.pipeline.notifications import notify_execution_started

        await notify_execution_started(plan_with_risks)

        mock_notification_service.notify.assert_awaited_once()
        notification = mock_notification_service.notify.call_args[0][0]

        assert "Execution Started" in notification.title
        assert "2 tasks" in notification.message
        assert notification.metadata["event"] == "plan.execution_started"
        assert notification.metadata["task_count"] == 2

    @pytest.mark.asyncio
    async def test_no_tasks(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_execution_started

        await notify_execution_started(basic_plan)

        notification = mock_notification_service.notify.call_args[0][0]
        assert "0 tasks" in notification.message

    @pytest.mark.asyncio
    async def test_webhook_event_type(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_execution_started

        await notify_execution_started(basic_plan)

        args = mock_notification_service.notify_all_webhooks.call_args
        assert args[0][1] == "plan.execution_started"


# ---------------------------------------------------------------------------
# notify_execution_completed
# ---------------------------------------------------------------------------


class TestNotifyExecutionCompleted:
    """Tests for notify_execution_completed."""

    @pytest.mark.asyncio
    async def test_basic_completion(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_execution_completed

        await notify_execution_completed(basic_plan)

        notification = mock_notification_service.notify.call_args[0][0]
        assert "Complete" in notification.title
        assert "completed successfully" in notification.message
        assert notification.severity == "info"

    @pytest.mark.asyncio
    async def test_with_result_details(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_execution_completed

        result = {
            "completed_tasks": 5,
            "failed_tasks": 1,
            "elapsed_seconds": 42.5,
        }
        await notify_execution_completed(basic_plan, result=result)

        notification = mock_notification_service.notify.call_args[0][0]
        assert "Completed: 5" in notification.message
        assert "Failed: 1" in notification.message
        assert "42.5s" in notification.message

    @pytest.mark.asyncio
    async def test_webhook_event_type(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_execution_completed

        await notify_execution_completed(basic_plan)

        args = mock_notification_service.notify_all_webhooks.call_args
        assert args[0][1] == "plan.execution_completed"


# ---------------------------------------------------------------------------
# notify_execution_failed
# ---------------------------------------------------------------------------


class TestNotifyExecutionFailed:
    """Tests for notify_execution_failed."""

    @pytest.mark.asyncio
    async def test_basic_failure(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_execution_failed
        from aragora.notifications.models import NotificationPriority

        await notify_execution_failed(basic_plan, error="Agent timeout after 300s")

        notification = mock_notification_service.notify.call_args[0][0]
        assert "Failed" in notification.title
        assert "Agent timeout" in notification.message
        assert notification.severity == "error"
        assert notification.priority == NotificationPriority.URGENT

    @pytest.mark.asyncio
    async def test_failure_metadata(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_execution_failed

        await notify_execution_failed(basic_plan, error="OOM killed")

        notification = mock_notification_service.notify.call_args[0][0]
        assert notification.metadata["error"] == "OOM killed"
        assert notification.metadata["event"] == "plan.execution_failed"

    @pytest.mark.asyncio
    async def test_webhook_event_type(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_execution_failed

        await notify_execution_failed(basic_plan, error="Crash")

        args = mock_notification_service.notify_all_webhooks.call_args
        assert args[0][1] == "plan.execution_failed"


# ---------------------------------------------------------------------------
# Risk-to-severity mapping
# ---------------------------------------------------------------------------


class TestRiskSeverityMapping:
    """Tests for _risk_to_severity helper."""

    @pytest.mark.asyncio
    async def test_low_risk_plan(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_created

        # basic_plan has no risks -> lowest risk level -> "info"
        await notify_plan_created(basic_plan)
        notification = mock_notification_service.notify.call_args[0][0]
        assert notification.severity == "info"

    @pytest.mark.asyncio
    async def test_medium_risk_plan(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_created

        basic_plan.risk_register = RiskRegister(
            debate_id="d-abc123",
            risks=[
                Risk(
                    id="r-m",
                    title="Medium risk",
                    description="Something moderate",
                    level=RiskLevel.MEDIUM,
                    category=RiskCategory.TECHNICAL,
                    source="debate",
                    mitigation="Watch it",
                ),
            ],
        )
        await notify_plan_created(basic_plan)
        notification = mock_notification_service.notify.call_args[0][0]
        assert notification.severity == "warning"

    @pytest.mark.asyncio
    async def test_high_risk_plan(self, basic_plan, mock_notification_service):
        from aragora.pipeline.notifications import notify_plan_created

        basic_plan.risk_register = RiskRegister(
            debate_id="d-abc123",
            risks=[
                Risk(
                    id="r-h",
                    title="High risk",
                    description="Something serious",
                    level=RiskLevel.HIGH,
                    category=RiskCategory.TECHNICAL,
                    source="debate",
                    mitigation="Be careful",
                ),
            ],
        )
        await notify_plan_created(basic_plan)
        notification = mock_notification_service.notify.call_args[0][0]
        assert notification.severity == "error"


# ---------------------------------------------------------------------------
# Channel routing (action_label field)
# ---------------------------------------------------------------------------


class TestChannelFormatting:
    """Tests for channel formatting details."""

    @pytest.mark.asyncio
    async def test_action_labels(self, basic_plan, mock_notification_service):
        """Each event type has an appropriate action label."""
        from aragora.pipeline.notifications import (
            notify_plan_created,
            notify_plan_approved,
            notify_plan_rejected,
            notify_execution_started,
            notify_execution_completed,
            notify_execution_failed,
        )

        expected_labels = {
            notify_plan_created: "Review Plan",
            notify_plan_approved: "View Plan",
            notify_plan_rejected: "View Plan",
            notify_execution_started: "View Execution",
            notify_execution_completed: "View Results",
            notify_execution_failed: "View Error",
        }

        for func, expected_label in expected_labels.items():
            mock_notification_service.notify.reset_mock()

            if func == notify_plan_approved:
                await func(basic_plan, approved_by="admin")
            elif func == notify_plan_rejected:
                await func(basic_plan, rejected_by="admin", reason="No")
            elif func == notify_execution_failed:
                await func(basic_plan, error="Crash")
            elif func == notify_execution_completed:
                await func(basic_plan)
            else:
                await func(basic_plan)

            notification = mock_notification_service.notify.call_args[0][0]
            assert notification.action_label == expected_label, (
                f"{func.__name__}: expected '{expected_label}', got '{notification.action_label}'"
            )

    @pytest.mark.asyncio
    async def test_all_events_set_resource_type(self, basic_plan, mock_notification_service):
        """All notifications use resource_type='decision_plan'."""
        from aragora.pipeline.notifications import (
            notify_plan_created,
            notify_execution_failed,
        )

        await notify_plan_created(basic_plan)
        n1 = mock_notification_service.notify.call_args[0][0]
        assert n1.resource_type == "decision_plan"

        mock_notification_service.notify.reset_mock()
        await notify_execution_failed(basic_plan, error="err")
        n2 = mock_notification_service.notify.call_args[0][0]
        assert n2.resource_type == "decision_plan"


# ---------------------------------------------------------------------------
# Handler integration (_fire_plan_notification)
# ---------------------------------------------------------------------------


class TestFirePlanNotification:
    """Tests for the _fire_plan_notification helper in plans handler."""

    def test_no_running_loop_does_not_crash(self):
        """_fire_plan_notification should not raise when there's no event loop."""
        from aragora.server.handlers.plans import _fire_plan_notification

        plan = DecisionPlan(
            id="dp-fire-test",
            debate_id="d-fire",
            task="Test fire-and-forget",
            org_id=ORG,
        )
        # Should not raise even without an event loop
        _fire_plan_notification("created", plan, org_id=ORG)

    def test_unknown_event_does_not_crash(self):
        """_fire_plan_notification ignores unknown event types gracefully."""
        from aragora.server.handlers.plans import _fire_plan_notification

        plan = DecisionPlan(id="dp-unk", debate_id="d-unk", task="Unknown test", org_id=ORG)
        _fire_plan_notification("nonexistent_event", plan, org_id=ORG)
