"""
Tests for aragora.server.handlers.plans - Decision Plan Handlers.

Tests cover:
- PlansHandler: instantiation, can_handle routing
- GET /api/v1/plans: list plans with pagination and filters
- GET /api/v1/plans/{id}: get plan by ID
- POST /api/v1/plans: create plan with validation
- POST /api/v1/plans/{id}/approve: approve plan workflow
- POST /api/v1/plans/{id}/reject: reject plan workflow
- POST /api/v1/plans/{id}/execute: execute approved plan
- Serialization: _plan_summary, _plan_detail
- Error paths: plan not found, invalid status, missing fields
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.plans import PlansHandler
from aragora.server.handlers.utils.responses import HandlerResult
from aragora.tenancy.record_scope import OrgScope

TEST_ORG = "test-org-001"
SCOPE = OrgScope(org_id=TEST_ORG, user_id="test-user-001", role="admin")


# ===========================================================================
# Helpers
# ===========================================================================


def _parse_body(result: HandlerResult) -> dict[str, Any]:
    """Parse JSON body from HandlerResult."""
    return json.loads(result.body)


def _close_scheduled_coroutine(coro, *args, **kwargs):
    """Close scheduled coroutines in tests to avoid background execution."""
    coro.close()
    return None


class MockPlanStatus(str, Enum):
    CREATED = "created"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class MockApprovalMode(str, Enum):
    ALWAYS = "always"
    RISK_BASED = "risk_based"
    NEVER = "never"


class MockPlan:
    """Mock DecisionPlan."""

    def __init__(
        self,
        plan_id: str = "plan-001",
        debate_id: str = "debate-001",
        task: str = "Implement feature X",
        status: str = "awaiting_approval",
        approval_mode: str = "risk_based",
        org_id: str | None = TEST_ORG,
        **kwargs,
    ):
        self.id = plan_id
        self.org_id = org_id
        self.created_by = "test-user-001"
        self.debate_id = debate_id
        self.task = task
        self.status = MockPlanStatus(status)
        self.approval_mode = MockApprovalMode(approval_mode)
        self.created_at = datetime.now(timezone.utc)
        self.has_critical_risks = False
        self.requires_human_approval = True
        self.metadata = {"action_items": ["Item 1"], "estimated_duration": "2h"}
        self.budget = MagicMock()
        self.budget.limit_usd = 100.0

    def approve(self, approver_id: str, reason: str = "", conditions: list | None = None):
        self.status = MockPlanStatus.APPROVED

    def reject(self, rejecter_id: str, reason: str = ""):
        self.status = MockPlanStatus.REJECTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "debate_id": self.debate_id,
            "task": self.task,
            "status": self.status.value,
            "approval_mode": self.approval_mode.value,
            "created_at": self.created_at.isoformat(),
            "has_critical_risks": self.has_critical_risks,
            "requires_human_approval": self.requires_human_approval,
            "metadata": self.metadata,
        }


def _make_mock_handler(
    method: str = "GET",
    body: bytes = b"",
    user_id: str = "user-001",
) -> MagicMock:
    """Create a mock HTTP handler."""
    handler = MagicMock()
    handler.command = method
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {
        "Content-Length": str(len(body)),
        "Content-Type": "application/json",
        "Authorization": "Bearer test-token",
    }
    handler.rfile = MagicMock()
    handler.rfile.read.return_value = body
    # Simulate auth
    mock_user = MagicMock()
    mock_user.user_id = user_id
    handler._user = mock_user
    return handler


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_store():
    """Create a mock plan store."""
    store = MagicMock()
    store.list_for_org.return_value = [MockPlan(), MockPlan("plan-002", task="Another task")]
    store.count_for_org.return_value = 2
    store.get.return_value = MockPlan()
    store.create.return_value = None
    store.update_status_for_org.return_value = True
    return store


@pytest.fixture
def handler(mock_store):
    """Create PlansHandler with mocked dependencies."""
    with patch(
        "aragora.server.handlers.plans._get_plan_store",
        return_value=mock_store,
    ):
        h = PlansHandler(ctx={})
        # Mock auth methods
        mock_user = MagicMock()
        mock_user.user_id = "user-001"
        h.require_auth_or_error = MagicMock(return_value=(mock_user, None))
        h.require_permission_or_error = MagicMock(return_value=(mock_user, None))
        yield h


# ===========================================================================
# Test Basics
# ===========================================================================


class TestPlansHandlerBasics:
    """Basic instantiation and routing tests."""

    def test_instantiation(self, handler):
        assert handler is not None
        assert isinstance(handler, PlansHandler)

    def test_can_handle_list(self, handler):
        assert handler.can_handle("/api/v1/plans") is True

    def test_can_handle_unversioned(self, handler):
        assert handler.can_handle("/api/plans") is True

    def test_can_handle_specific_plan(self, handler):
        assert handler.can_handle("/api/v1/plans/plan-001") is True

    def test_can_handle_approve(self, handler):
        assert handler.can_handle("/api/v1/plans/plan-001/approve") is True

    def test_can_handle_reject(self, handler):
        assert handler.can_handle("/api/v1/plans/plan-001/reject") is True

    def test_can_handle_execute(self, handler):
        assert handler.can_handle("/api/v1/plans/plan-001/execute") is True

    def test_cannot_handle_other(self, handler):
        assert handler.can_handle("/api/debates") is False

    def test_cannot_handle_partial_prefix(self, handler):
        assert handler.can_handle("/api/v1/planning") is False


# ===========================================================================
# Test _list_plans
# ===========================================================================


class TestListPlans:
    """Tests for GET /api/v1/plans."""

    def test_list_plans_success(self, handler, mock_store):
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
        ):
            result = handler._list_plans({}, SCOPE)
            assert result.status_code == 200
            data = _parse_body(result)
            assert data["total"] == 2
            assert len(data["plans"]) == 2

    def test_list_plans_with_status_filter(self, handler, mock_store):
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
        ):
            result = handler._list_plans({"status": "approved"}, SCOPE)
            assert result.status_code == 200

    def test_list_plans_invalid_status(self, handler, mock_store):
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
        ):
            result = handler._list_plans({"status": "nonexistent_status"}, SCOPE)
            assert result.status_code == 400

    def test_list_plans_with_pagination(self, handler, mock_store):
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
        ):
            result = handler._list_plans({"limit": "10", "offset": "5"}, SCOPE)
            assert result.status_code == 200
            data = _parse_body(result)
            assert data["limit"] == 10
            assert data["offset"] == 5


# ===========================================================================
# Test _get_plan
# ===========================================================================


class TestGetPlan:
    """Tests for GET /api/v1/plans/{id}."""

    def test_get_plan_success(self, handler, mock_store):
        with patch(
            "aragora.server.handlers.plans._get_plan_store",
            return_value=mock_store,
        ):
            result = handler._get_plan({"plan_id": "plan-001"}, SCOPE)
            assert result.status_code == 200
            data = _parse_body(result)
            assert data["id"] == "plan-001"

    def test_get_plan_not_found(self, handler, mock_store):
        mock_store.get.return_value = None
        with patch(
            "aragora.server.handlers.plans._get_plan_store",
            return_value=mock_store,
        ):
            result = handler._get_plan({"plan_id": "nonexistent"}, SCOPE)
            assert result.status_code == 404


# ===========================================================================
# Test _create_plan
# ===========================================================================


class TestCreatePlan:
    """Tests for POST /api/v1/plans."""

    def test_create_plan_success(self, handler, mock_store):
        body = {"debate_id": "debate-001", "task": "Implement feature"}
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch.object(handler, "get_json_body", return_value=body),
            patch(
                "aragora.pipeline.decision_plan.core.DecisionPlan",
                MockPlan,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.ApprovalMode",
                MockApprovalMode,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
            patch(
                "aragora.server.handlers.plans._fire_plan_notification",
            ),
        ):
            result = handler._create_plan(SCOPE)
            assert result.status_code == 201

    def test_create_plan_missing_body(self, handler, mock_store):
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch.object(handler, "get_json_body", return_value=None),
        ):
            result = handler._create_plan(SCOPE)
            assert result.status_code == 400

    def test_create_plan_missing_debate_id(self, handler, mock_store):
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch.object(handler, "get_json_body", return_value={"task": "Do something"}),
        ):
            result = handler._create_plan(SCOPE)
            assert result.status_code == 400

    def test_create_plan_missing_task(self, handler, mock_store):
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch.object(handler, "get_json_body", return_value={"debate_id": "d-1"}),
        ):
            result = handler._create_plan(SCOPE)
            assert result.status_code == 400


# ===========================================================================
# Test _approve_plan
# ===========================================================================


class TestApprovePlan:
    """Tests for POST /api/v1/plans/{id}/approve."""

    def test_approve_plan_success(self, handler, mock_store):
        plan = MockPlan(status="awaiting_approval")
        mock_store.get.return_value = plan

        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
            patch.object(handler, "get_json_body", return_value={}),
            patch(
                "aragora.server.handlers.plans._fire_plan_notification",
            ),
        ):
            result = handler._approve_plan({"plan_id": "plan-001"}, SCOPE)
            assert result.status_code == 200
            data = _parse_body(result)
            assert data["status"] == "approved"

    def test_approve_plan_not_found(self, handler, mock_store):
        mock_store.get.return_value = None
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
        ):
            result = handler._approve_plan({"plan_id": "nonexistent"}, SCOPE)
            assert result.status_code == 404

    def test_approve_already_approved(self, handler, mock_store):
        plan = MockPlan(status="approved")
        mock_store.get.return_value = plan
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
        ):
            result = handler._approve_plan({"plan_id": "plan-001"}, SCOPE)
            assert result.status_code == 409


# ===========================================================================
# Test _reject_plan
# ===========================================================================


class TestRejectPlan:
    """Tests for POST /api/v1/plans/{id}/reject."""

    def test_reject_plan_success(self, handler, mock_store):
        plan = MockPlan(status="awaiting_approval")
        mock_store.get.return_value = plan

        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
            patch.object(handler, "get_json_body", return_value={"reason": "Not ready"}),
            patch(
                "aragora.server.handlers.plans._fire_plan_notification",
            ),
        ):
            result = handler._reject_plan({"plan_id": "plan-001"}, SCOPE)
            assert result.status_code == 200
            data = _parse_body(result)
            assert data["status"] == "rejected"
            assert data["reason"] == "Not ready"

    def test_reject_plan_missing_reason(self, handler, mock_store):
        plan = MockPlan(status="awaiting_approval")
        mock_store.get.return_value = plan
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
            patch.object(handler, "get_json_body", return_value={}),
        ):
            result = handler._reject_plan({"plan_id": "plan-001"}, SCOPE)
            assert result.status_code == 400

    def test_reject_plan_not_found(self, handler, mock_store):
        mock_store.get.return_value = None
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
        ):
            result = handler._reject_plan({"plan_id": "nonexistent"}, SCOPE)
            assert result.status_code == 404


# ===========================================================================
# Test _execute_plan
# ===========================================================================


class TestExecutePlan:
    """Tests for POST /api/v1/plans/{id}/execute."""

    def test_execute_approved_plan(self, handler, mock_store):
        plan = MockPlan(status="approved")
        mock_store.get.return_value = plan
        launch = {
            "plan_id": "plan-001",
            "run_id": "run-001",
            "execution_id": "exec-001",
            "correlation_id": "corr-001",
            "execution_mode": "interactive",
            "status": "queued",
        }

        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
            patch.object(handler, "get_json_body", return_value={}),
            patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=launch,
            ) as mock_queue,
            patch(
                "aragora.pipeline.canonical_execution.execute_queued_plan",
                new=AsyncMock(),
            ) as mock_execute,
            patch(
                "aragora.pipeline.canonical_execution.schedule_coroutine",
                side_effect=_close_scheduled_coroutine,
            ) as mock_schedule,
            patch(
                "aragora.server.handlers.plans._fire_plan_notification",
            ),
        ):
            result = handler._execute_plan({"plan_id": "plan-001"}, SCOPE)
            assert result.status_code == 202
            body = _parse_body(result)
            assert body["run_id"] == "run-001"
            assert body["execution_id"] == "exec-001"
            mock_queue.assert_called_once()
            mock_execute.assert_called_once()
            mock_schedule.assert_called_once()

    def test_execute_unapproved_plan(self, handler, mock_store):
        plan = MockPlan(status="awaiting_approval")
        mock_store.get.return_value = plan
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
            patch.object(handler, "get_json_body", return_value={}),
        ):
            result = handler._execute_plan({"plan_id": "plan-001"}, SCOPE)
            assert result.status_code == 409

    def test_execute_already_executing(self, handler, mock_store):
        plan = MockPlan(status="executing")
        mock_store.get.return_value = plan
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
            patch.object(handler, "get_json_body", return_value={}),
        ):
            result = handler._execute_plan({"plan_id": "plan-001"}, SCOPE)
            assert result.status_code == 409

    def test_execute_completed_plan(self, handler, mock_store):
        plan = MockPlan(status="completed")
        mock_store.get.return_value = plan
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
            patch.object(handler, "get_json_body", return_value={}),
        ):
            result = handler._execute_plan({"plan_id": "plan-001"}, SCOPE)
            assert result.status_code == 409

    def test_execute_not_found(self, handler, mock_store):
        mock_store.get.return_value = None
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
            patch.object(handler, "get_json_body", return_value={}),
        ):
            result = handler._execute_plan({"plan_id": "nonexistent"}, SCOPE)
            assert result.status_code == 404


# ===========================================================================
# Test Serialization
# ===========================================================================


class TestSerialization:
    """Tests for plan serialization helpers."""

    def test_plan_summary(self):
        plan = MockPlan()
        summary = PlansHandler._plan_summary(plan)
        assert summary["id"] == "plan-001"
        assert summary["status"] == "awaiting_approval"
        assert "created_at" in summary
        assert len(summary["task"]) <= 200

    def test_plan_detail(self):
        plan = MockPlan()
        detail = PlansHandler._plan_detail(plan)
        assert detail["id"] == "plan-001"
        assert "action_items" in detail
        assert detail["estimated_duration"] == "2h"

    def test_plan_summary_truncates_long_task(self):
        plan = MockPlan(task="x" * 300)
        summary = PlansHandler._plan_summary(plan)
        assert len(summary["task"]) == 200


# ===========================================================================
# Test handle() routing
# ===========================================================================


class TestHandleRouting:
    """Tests for top-level handle() method routing."""

    def test_handle_list_plans(self, handler, mock_store):
        mock_handler = _make_mock_handler()
        with (
            patch(
                "aragora.server.handlers.plans._get_plan_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.pipeline.decision_plan.core.PlanStatus",
                MockPlanStatus,
            ),
        ):
            result = handler.handle("/api/v1/plans", {}, mock_handler)
            assert result is not None
            assert result.status_code == 200
            mock_store.list_for_org.assert_called_once()
            assert mock_store.list_for_org.call_args.args[0] == TEST_ORG

    def test_handle_get_by_id(self, handler, mock_store):
        with patch(
            "aragora.server.handlers.plans._get_plan_store",
            return_value=mock_store,
        ):
            result = handler.handle("/api/v1/plans/plan-001", {}, _make_mock_handler())
            assert result is not None
            assert result.status_code == 200

    def test_handle_unversioned_path(self, handler, mock_store):
        with patch(
            "aragora.server.handlers.plans._get_plan_store",
            return_value=mock_store,
        ):
            result = handler.handle("/api/plans/plan-001", {}, _make_mock_handler())
            assert result is not None
            assert result.status_code == 200

    def test_handle_other_org_plan_is_not_found(self, handler, mock_store):
        mock_store.get.return_value = MockPlan(org_id="other-org-999")
        with patch(
            "aragora.server.handlers.plans._get_plan_store",
            return_value=mock_store,
        ):
            result = handler.handle("/api/v1/plans/plan-001", {}, _make_mock_handler())
            assert result.status_code == 404
            assert _parse_body(result) == {"error": "Plan not found", "code": "not_found"}

    @pytest.mark.no_auto_auth
    def test_handle_anonymous_is_unauthorized(self, handler, mock_store):
        mock_handler = _make_mock_handler()
        mock_handler.headers.pop("Authorization")
        with patch(
            "aragora.server.handlers.plans._get_plan_store",
            return_value=mock_store,
        ):
            result = handler.handle("/api/v1/plans", {}, mock_handler)
            assert result.status_code == 401
            mock_store.list_for_org.assert_not_called()
