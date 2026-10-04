"""Tests for decision pipeline handler.

Tests the decision pipeline API endpoints (gold path):
- POST /api/v1/decisions/plans - Create plan from debate result
- GET  /api/v1/decisions/plans - List plans
- GET  /api/v1/decisions/plans/{plan_id} - Get plan details
- POST /api/v1/decisions/plans/{plan_id}/approve - Approve plan
- POST /api/v1/decisions/plans/{plan_id}/reject - Reject plan
- POST /api/v1/decisions/plans/{plan_id}/execute - Execute approved plan
- GET  /api/v1/decisions/plans/{plan_id}/outcome - Get execution outcome
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.pipeline.execution_mode import ExecutionMode

pytestmark = pytest.mark.usefixtures("org_scoped_request_user")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


_NOT_FOUND = {"error": "Plan not found", "code": "not_found"}


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


# ---------------------------------------------------------------------------
# Lightweight mock types (avoid importing heavy pipeline modules at top level)
# ---------------------------------------------------------------------------


class _PlanStatus(Enum):
    CREATED = "created"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class _ApprovalRecord:
    approved: bool = False
    approver_id: str = ""
    reason: str = ""
    conditions: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "approver_id": self.approver_id,
            "reason": self.reason,
            "conditions": self.conditions,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class _MockPlan:
    id: str = "dp-abc123"
    debate_id: str = "debate-001"
    task: str = "Should we deploy?"
    status: _PlanStatus = _PlanStatus.CREATED
    requires_human_approval: bool = False
    approval_record: _ApprovalRecord | None = None
    risk_register: Any = None
    highest_risk_level: Any = None
    debate_result: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    org_id: str | None = "test-org-001"
    created_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "debate_id": self.debate_id,
            "task": self.task,
            "status": self.status.value,
        }

    def approve(self, approver_id: str, reason: str = "", conditions: list[str] | None = None):
        self.approval_record = _ApprovalRecord(
            approved=True,
            approver_id=approver_id,
            reason=reason,
            conditions=conditions or [],
        )
        self.status = _PlanStatus.APPROVED

    def reject(self, approver_id: str, reason: str = ""):
        self.approval_record = _ApprovalRecord(
            approved=False,
            approver_id=approver_id,
            reason=reason,
        )
        self.status = _PlanStatus.REJECTED


@dataclass
class _MockOutcome:
    success: bool = True
    plan_id: str = "dp-abc123"

    def to_dict(self) -> dict[str, Any]:
        return {"success": self.success, "plan_id": self.plan_id}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a DecisionPipelineHandler instance with empty context."""
    from aragora.server.handlers.decisions.pipeline import DecisionPipelineHandler

    return DecisionPipelineHandler(ctx={})


@pytest.fixture
def mock_http_handler():
    """Create mock HTTP handler (no body)."""
    h = MagicMock()
    h.client_address = ("127.0.0.1", 12345)
    h.headers = {"Content-Length": "2"}
    h.rfile = MagicMock()
    h.rfile.read.return_value = b"{}"
    return h


def _make_http_handler(body: dict[str, Any] | None = None):
    """Create mock HTTP handler with optional JSON body."""
    h = MagicMock()
    h.client_address = ("127.0.0.1", 12345)
    if body is not None:
        raw = json.dumps(body).encode()
        h.headers = {"Content-Length": str(len(raw))}
        h.rfile = MagicMock()
        h.rfile.read.return_value = raw
    else:
        h.headers = {"Content-Length": "2"}
        h.rfile = MagicMock()
        h.rfile.read.return_value = b"{}"
    return h


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    """Reset the module-level circuit breaker before each test."""
    import aragora.server.handlers.decisions.pipeline as mod

    mod._pipeline_cb = None
    yield


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset rate limiter before each test."""
    from aragora.server.handlers.decisions import pipeline as mod
    from aragora.server.handlers.utils.rate_limit import RateLimiter

    mod._pipeline_limiter = RateLimiter(requests_per_minute=60)
    yield


@pytest.fixture(autouse=True)
def patch_backbone_create_helpers():
    """Patch backbone create-time helpers so tests stay local and deterministic."""
    with (
        patch(
            "aragora.server.handlers.decisions.pipeline.ensure_decision_plan_backbone_run",
            return_value="run-decision-pipeline",
        ),
        patch(
            "aragora.server.handlers.decisions.pipeline.sync_decision_plan_backbone_receipt",
            return_value=True,
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# can_handle routing
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for the can_handle routing method."""

    def test_can_handle_plans_list(self, handler):
        assert handler.can_handle("/api/v1/decisions/plans")

    def test_can_handle_plan_detail(self, handler):
        assert handler.can_handle("/api/v1/decisions/plans/dp-abc123")

    def test_can_handle_approve(self, handler):
        assert handler.can_handle("/api/v1/decisions/plans/dp-abc123/approve")

    def test_can_handle_reject(self, handler):
        assert handler.can_handle("/api/v1/decisions/plans/dp-abc123/reject")

    def test_can_handle_execute(self, handler):
        assert handler.can_handle("/api/v1/decisions/plans/dp-abc123/execute")

    def test_can_handle_outcome(self, handler):
        assert handler.can_handle("/api/v1/decisions/plans/dp-abc123/outcome")

    def test_cannot_handle_unrelated_path(self, handler):
        assert not handler.can_handle("/api/v1/debates")

    def test_cannot_handle_decisions_root(self, handler):
        assert not handler.can_handle("/api/v1/decisions")

    def test_cannot_handle_other_api(self, handler):
        assert not handler.can_handle("/api/health")

    def test_cannot_handle_partial_prefix(self, handler):
        assert not handler.can_handle("/api/v1/decisions/plan")


# ---------------------------------------------------------------------------
# _extract_plan_id
# ---------------------------------------------------------------------------


class TestExtractPlanId:
    """Tests for plan ID extraction from path."""

    def test_extracts_plan_id(self, handler):
        assert handler._extract_plan_id("/api/v1/decisions/plans/dp-abc123") == "dp-abc123"

    def test_extracts_plan_id_with_action(self, handler):
        assert handler._extract_plan_id("/api/v1/decisions/plans/dp-xyz/approve") == "dp-xyz"

    def test_returns_none_for_short_path(self, handler):
        assert handler._extract_plan_id("/api/v1/decisions/plans") is None

    def test_returns_none_for_very_short_path(self, handler):
        assert handler._extract_plan_id("/api/v1") is None


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """Tests for circuit breaker integration."""

    def test_get_open_returns_503(self, handler, mock_http_handler):
        mock_cb = MagicMock()
        mock_cb.can_execute.return_value = False
        with patch(
            "aragora.server.handlers.decisions.pipeline._get_circuit_breaker",
            return_value=mock_cb,
        ):
            result = handler.handle("/api/v1/decisions/plans", {}, mock_http_handler)
        assert _status(result) == 503
        assert "unavailable" in _body(result).get("error", "").lower()

    def test_post_open_returns_503(self, handler, mock_http_handler):
        mock_cb = MagicMock()
        mock_cb.can_execute.return_value = False
        with patch(
            "aragora.server.handlers.decisions.pipeline._get_circuit_breaker",
            return_value=mock_cb,
        ):
            result = handler.handle_post("/api/v1/decisions/plans", {}, mock_http_handler)
        assert _status(result) == 503


# ---------------------------------------------------------------------------
# GET /api/v1/decisions/plans  (list)
# ---------------------------------------------------------------------------


class TestListPlans:
    """Tests for listing decision plans."""

    @patch("aragora.pipeline.executor.list_plans")
    @patch("aragora.pipeline.decision_plan.PlanStatus")
    def test_list_plans_no_filter(self, _mock_status_cls, mock_list, handler, mock_http_handler):
        plan = _MockPlan()
        mock_list.return_value = [plan]
        result = handler.handle("/api/v1/decisions/plans", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["count"] == 1
        assert body["plans"][0]["id"] == "dp-abc123"

    @patch("aragora.pipeline.executor.list_plans")
    @patch("aragora.pipeline.decision_plan.PlanStatus")
    def test_list_plans_empty(self, _mock_status_cls, mock_list, handler, mock_http_handler):
        mock_list.return_value = []
        result = handler.handle("/api/v1/decisions/plans", {}, mock_http_handler)
        assert _status(result) == 200
        assert _body(result)["count"] == 0

    @patch("aragora.pipeline.executor.list_plans")
    @patch("aragora.pipeline.decision_plan.PlanStatus")
    def test_list_plans_with_status_filter(
        self, mock_status_cls, mock_list, handler, mock_http_handler
    ):
        mock_status_cls.side_effect = lambda v: _PlanStatus(v)
        mock_list.return_value = []
        result = handler.handle(
            "/api/v1/decisions/plans", {"status": "approved"}, mock_http_handler
        )
        assert _status(result) == 200

    def test_list_plans_invalid_status(self, handler, mock_http_handler):
        # PlanStatus("nonsense") raises ValueError -> 400
        result = handler.handle(
            "/api/v1/decisions/plans", {"status": "nonsense"}, mock_http_handler
        )
        assert _status(result) == 400
        assert "invalid status" in _body(result).get("error", "").lower()

    @patch("aragora.pipeline.executor.list_plans")
    @patch("aragora.pipeline.decision_plan.PlanStatus")
    def test_list_plans_with_limit(self, _mock_status_cls, mock_list, handler, mock_http_handler):
        mock_list.return_value = []
        result = handler.handle("/api/v1/decisions/plans", {"limit": "10"}, mock_http_handler)
        assert _status(result) == 200
        mock_list.assert_called_once()
        call_kwargs = mock_list.call_args
        mock_list.assert_called_once_with(status=None, limit=10, org_id="test-org-001")

    @patch("aragora.pipeline.executor.list_plans")
    @patch("aragora.pipeline.decision_plan.PlanStatus")
    def test_list_plans_limit_capped_at_200(
        self, _mock_status_cls, mock_list, handler, mock_http_handler
    ):
        mock_list.return_value = []
        result = handler.handle("/api/v1/decisions/plans", {"limit": "999"}, mock_http_handler)
        assert _status(result) == 200
        call_kwargs = mock_list.call_args
        assert call_kwargs[1].get("limit", call_kwargs[0][0] if call_kwargs[0] else None) <= 200

    @patch("aragora.pipeline.executor.list_plans")
    @patch("aragora.pipeline.decision_plan.PlanStatus")
    def test_list_plans_limit_minimum_1(
        self, _mock_status_cls, mock_list, handler, mock_http_handler
    ):
        mock_list.return_value = []
        result = handler.handle("/api/v1/decisions/plans", {"limit": "-5"}, mock_http_handler)
        assert _status(result) == 200

    @patch("aragora.pipeline.executor.list_plans")
    @patch("aragora.pipeline.decision_plan.PlanStatus")
    def test_list_plans_invalid_limit_ignored(
        self, _mock_status_cls, mock_list, handler, mock_http_handler
    ):
        mock_list.return_value = []
        result = handler.handle("/api/v1/decisions/plans", {"limit": "abc"}, mock_http_handler)
        assert _status(result) == 200
        # Falls back to default 50
        call_kwargs = mock_list.call_args
        assert call_kwargs[1].get("limit", 50) == 50


# ---------------------------------------------------------------------------
# GET /api/v1/decisions/plans/{plan_id}  (detail)
# ---------------------------------------------------------------------------


class TestGetPlan:
    """Tests for getting plan details."""

    @patch("aragora.pipeline.executor.get_outcome")
    @patch("aragora.pipeline.executor.get_plan")
    def test_get_plan_found(self, mock_get, mock_outcome, handler, mock_http_handler):
        plan = _MockPlan(id="dp-001")
        mock_get.return_value = plan
        mock_outcome.return_value = None
        result = handler.handle("/api/v1/decisions/plans/dp-001", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["plan"]["id"] == "dp-001"
        assert "outcome" not in body

    @patch("aragora.pipeline.executor.get_outcome")
    @patch("aragora.pipeline.executor.get_plan")
    def test_get_plan_with_outcome(self, mock_get, mock_outcome, handler, mock_http_handler):
        plan = _MockPlan(id="dp-001")
        outcome = _MockOutcome(success=True)
        mock_get.return_value = plan
        mock_outcome.return_value = outcome
        result = handler.handle("/api/v1/decisions/plans/dp-001", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["outcome"]["success"] is True

    @patch("aragora.pipeline.executor.get_plan")
    def test_get_plan_not_found(self, mock_get, handler, mock_http_handler):
        mock_get.return_value = None
        result = handler.handle("/api/v1/decisions/plans/dp-notexist", {}, mock_http_handler)
        assert _status(result) == 404
        assert _body(result) == _NOT_FOUND


# ---------------------------------------------------------------------------
# GET /api/v1/decisions/plans/{plan_id}/outcome
# ---------------------------------------------------------------------------


class TestGetOutcome:
    """Tests for getting plan execution outcome."""

    @patch("aragora.pipeline.executor.get_outcome")
    @patch("aragora.pipeline.executor.get_plan")
    def test_get_outcome_found(self, mock_get, mock_outcome, handler, mock_http_handler):
        mock_get.return_value = _MockPlan(id="dp-001")
        mock_outcome.return_value = _MockOutcome(success=True)
        result = handler.handle("/api/v1/decisions/plans/dp-001/outcome", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["outcome"]["success"] is True

    @patch("aragora.pipeline.executor.get_plan")
    def test_get_outcome_plan_not_found(self, mock_get, handler, mock_http_handler):
        mock_get.return_value = None
        result = handler.handle("/api/v1/decisions/plans/dp-001/outcome", {}, mock_http_handler)
        assert _status(result) == 404
        assert _body(result) == _NOT_FOUND

    @patch("aragora.pipeline.executor.get_outcome")
    @patch("aragora.pipeline.executor.get_plan")
    def test_get_outcome_no_outcome_yet(self, mock_get, mock_outcome, handler, mock_http_handler):
        mock_get.return_value = _MockPlan()
        mock_outcome.return_value = None
        result = handler.handle("/api/v1/decisions/plans/dp-abc123/outcome", {}, mock_http_handler)
        assert _status(result) == 404
        assert "no outcome" in _body(result).get("error", "").lower()


# ---------------------------------------------------------------------------
# GET routing edge cases
# ---------------------------------------------------------------------------


class TestGetRouting:
    """Tests for GET request routing edge cases."""

    def test_get_invalid_plan_path_returns_400(self, handler, mock_http_handler):
        # Path shorter than 6 segments -> no plan_id extracted -> 400
        result = handler.handle("/api/v1/decisions/plans/", {}, mock_http_handler)
        # Empty plan_id extracted -> still dispatches but the functions will
        # handle gracefully depending on what endpoint matched.
        # With "/" trailing, parts[5] is empty string, which is falsy -> 400
        assert _status(result) == 400

    @patch("aragora.pipeline.executor.get_outcome")
    @patch("aragora.pipeline.executor.get_plan")
    def test_get_unmatched_subpath_returns_none(
        self, mock_get, mock_outcome, handler, mock_http_handler
    ):
        """Unknown sub-path after plan_id returns None (not handled)."""
        mock_get.return_value = _MockPlan()
        mock_outcome.return_value = None
        result = handler.handle("/api/v1/decisions/plans/dp-001/unknown", {}, mock_http_handler)
        assert result is None


# ---------------------------------------------------------------------------
# POST /api/v1/decisions/plans  (create)
# ---------------------------------------------------------------------------


class TestCreatePlan:
    """Tests for creating a decision plan from a debate result."""

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_create_plan_success(self, mock_load, mock_factory, mock_store, handler):
        mock_plan = _MockPlan(id="dp-new")
        mock_factory.from_debate_result.return_value = mock_plan
        h = _make_http_handler({"debate_id": "debate-001"})
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 201
        body = _body(result)
        assert body["success"] is True
        assert body["plan"]["id"] == "dp-new"
        mock_store.assert_called_once_with(mock_plan)

    def test_create_plan_invalid_json(self, handler):
        h = MagicMock()
        h.client_address = ("127.0.0.1", 12345)
        h.headers = {"Content-Length": "5"}
        h.rfile = MagicMock()
        h.rfile.read.return_value = b"notjson"
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 400
        assert "json" in _body(result).get("error", "").lower()

    def test_create_plan_missing_debate_id(self, handler):
        h = _make_http_handler({"some_field": "value"})
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 400
        assert "debate_id" in _body(result).get("error", "").lower()

    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=None,
    )
    def test_create_plan_debate_not_found(self, _mock_load, handler):
        h = _make_http_handler({"debate_id": "debate-404"})
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_create_plan_invalid_approval_mode(self, _mock_load, handler):
        h = _make_http_handler({"debate_id": "debate-001", "approval_mode": "banana"})
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 400
        assert "approval_mode" in _body(result).get("error", "").lower()

    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_create_plan_invalid_max_auto_risk(self, _mock_load, handler):
        h = _make_http_handler({"debate_id": "debate-001", "max_auto_risk": "extreme"})
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 400
        assert "max_auto_risk" in _body(result).get("error", "").lower()

    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_create_plan_invalid_budget_limit_non_numeric(self, _mock_load, handler):
        h = _make_http_handler({"debate_id": "debate-001", "budget_limit_usd": "abc"})
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 400
        assert "budget_limit_usd" in _body(result).get("error", "").lower()

    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_create_plan_negative_budget_limit(self, _mock_load, handler):
        h = _make_http_handler({"debate_id": "debate-001", "budget_limit_usd": -10})
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 400
        assert ">= 0" in _body(result).get("error", "")

    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_create_plan_invalid_metadata_type(self, _mock_load, handler):
        h = _make_http_handler({"debate_id": "debate-001", "metadata": "not_a_dict"})
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 400
        assert "metadata" in _body(result).get("error", "").lower()

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_create_plan_with_metadata_and_mode(
        self, _mock_load, mock_factory, _mock_store, handler
    ):
        plan = _MockPlan()
        mock_factory.from_debate_result.return_value = plan
        h = _make_http_handler(
            {
                "debate_id": "debate-001",
                "metadata": {"key": "val"},
                "mode": "architect",
            }
        )
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 201
        call_kwargs = mock_factory.from_debate_result.call_args
        meta = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata")
        assert meta["key"] == "val"
        assert meta["operational_mode"] == "architect"

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_create_plan_with_valid_budget(self, _mock_load, mock_factory, _mock_store, handler):
        plan = _MockPlan()
        mock_factory.from_debate_result.return_value = plan
        h = _make_http_handler({"debate_id": "debate-001", "budget_limit_usd": 100.5})
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 201
        call_kwargs = mock_factory.from_debate_result.call_args
        assert call_kwargs.kwargs.get("budget_limit_usd") == 100.5

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_create_plan_zero_budget(self, _mock_load, mock_factory, _mock_store, handler):
        plan = _MockPlan()
        mock_factory.from_debate_result.return_value = plan
        h = _make_http_handler({"debate_id": "debate-001", "budget_limit_usd": 0})
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 201


# ---------------------------------------------------------------------------
# POST /api/v1/decisions/plans/{plan_id}/approve
# ---------------------------------------------------------------------------


class TestApprovePlan:
    """Tests for approving a decision plan."""

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.executor.get_plan")
    def test_approve_created_plan(self, mock_get, mock_store, handler):
        plan = _MockPlan(status=_PlanStatus.CREATED)
        mock_get.return_value = plan
        with patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus):
            h = _make_http_handler({"reason": "Looks good", "conditions": ["monitor"]})
            result = handler.handle_post("/api/v1/decisions/plans/dp-abc123/approve", {}, h)
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["plan"]["status"] == "approved"
        assert plan.approval_record is not None
        assert plan.approval_record.approved is True

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.executor.get_plan")
    def test_approve_awaiting_approval_plan(self, mock_get, mock_store, handler):
        plan = _MockPlan(status=_PlanStatus.AWAITING_APPROVAL)
        mock_get.return_value = plan
        with patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus):
            h = _make_http_handler({})
            result = handler.handle_post("/api/v1/decisions/plans/dp-abc123/approve", {}, h)
        assert _status(result) == 200

    @patch("aragora.pipeline.executor.get_plan")
    def test_approve_not_found(self, mock_get, handler):
        mock_get.return_value = None
        h = _make_http_handler({})
        result = handler.handle_post("/api/v1/decisions/plans/dp-404/approve", {}, h)
        assert _status(result) == 404
        assert _body(result) == _NOT_FOUND

    @patch("aragora.pipeline.executor.get_plan")
    def test_approve_wrong_status(self, mock_get, handler):
        plan = _MockPlan(status=_PlanStatus.APPROVED)
        mock_get.return_value = plan
        with patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus):
            h = _make_http_handler({})
            result = handler.handle_post("/api/v1/decisions/plans/dp-001/approve", {}, h)
        assert _status(result) == 409
        assert "cannot be approved" in _body(result).get("error", "").lower()

    @patch("aragora.pipeline.executor.get_plan")
    def test_approve_rejected_status_conflict(self, mock_get, handler):
        plan = _MockPlan(status=_PlanStatus.REJECTED)
        mock_get.return_value = plan
        with patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus):
            h = _make_http_handler({})
            result = handler.handle_post("/api/v1/decisions/plans/dp-001/approve", {}, h)
        assert _status(result) == 409

    @patch("aragora.pipeline.executor.get_plan")
    def test_approve_completed_status_conflict(self, mock_get, handler):
        plan = _MockPlan(status=_PlanStatus.COMPLETED)
        mock_get.return_value = plan
        with patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus):
            h = _make_http_handler({})
            result = handler.handle_post("/api/v1/decisions/plans/dp-001/approve", {}, h)
        assert _status(result) == 409


# ---------------------------------------------------------------------------
# POST /api/v1/decisions/plans/{plan_id}/reject
# ---------------------------------------------------------------------------


class TestRejectPlan:
    """Tests for rejecting a decision plan."""

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.executor.get_plan")
    def test_reject_plan(self, mock_get, mock_store, handler):
        plan = _MockPlan(status=_PlanStatus.CREATED)
        mock_get.return_value = plan
        with patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus):
            h = _make_http_handler({"reason": "Too risky"})
            result = handler.handle_post("/api/v1/decisions/plans/dp-001/reject", {}, h)
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["plan"]["status"] == "rejected"
        assert plan.approval_record.reason == "Too risky"

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.executor.get_plan")
    def test_reject_awaiting_approval(self, mock_get, mock_store, handler):
        plan = _MockPlan(status=_PlanStatus.AWAITING_APPROVAL)
        mock_get.return_value = plan
        with patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus):
            h = _make_http_handler({})
            result = handler.handle_post("/api/v1/decisions/plans/dp-001/reject", {}, h)
        assert _status(result) == 200
        assert plan.approval_record.reason == "No reason provided"

    @patch("aragora.pipeline.executor.get_plan")
    def test_reject_not_found(self, mock_get, handler):
        mock_get.return_value = None
        h = _make_http_handler({})
        result = handler.handle_post("/api/v1/decisions/plans/dp-404/reject", {}, h)
        assert _status(result) == 404
        assert _body(result) == _NOT_FOUND

    @patch("aragora.pipeline.executor.get_plan")
    def test_reject_wrong_status(self, mock_get, handler):
        plan = _MockPlan(status=_PlanStatus.EXECUTING)
        mock_get.return_value = plan
        with patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus):
            h = _make_http_handler({})
            result = handler.handle_post("/api/v1/decisions/plans/dp-001/reject", {}, h)
        assert _status(result) == 409

    @patch("aragora.pipeline.executor.get_plan")
    def test_reject_already_rejected_conflict(self, mock_get, handler):
        plan = _MockPlan(status=_PlanStatus.REJECTED)
        mock_get.return_value = plan
        with patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus):
            h = _make_http_handler({})
            result = handler.handle_post("/api/v1/decisions/plans/dp-001/reject", {}, h)
        assert _status(result) == 409


# ---------------------------------------------------------------------------
# POST /api/v1/decisions/plans/{plan_id}/execute
# ---------------------------------------------------------------------------


class TestExecutePlan:
    """Tests for executing an approved decision plan."""

    def _patch_executor(self):
        """Helper to create a patched PlanExecutor constructor."""
        mock_executor_inst = MagicMock()
        mock_executor_cls = MagicMock(return_value=mock_executor_inst)
        return mock_executor_cls, mock_executor_inst

    @patch("aragora.pipeline.executor.get_plan")
    def test_execute_plan_success(self, mock_get, handler):
        plan = _MockPlan(id="dp-001", status=_PlanStatus.APPROVED)
        refreshed_plan = _MockPlan(id="dp-001", status=_PlanStatus.COMPLETED)
        mock_get.side_effect = [plan, refreshed_plan]
        outcome = _MockOutcome(success=True)
        launch = {
            "run_id": "run-dp-001",
            "execution_id": "exec-dp-001",
            "correlation_id": "corr-dp-001",
        }
        executor_cls, executor_inst = self._patch_executor()
        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = (launch, outcome)

        h = _make_http_handler({"execution_mode": "workflow"})
        with (
            patch("aragora.pipeline.executor.PlanExecutor", executor_cls),
            patch(
                "aragora.server.handlers.decisions.pipeline.normalize_execution_mode",
                return_value="workflow",
            ),
            patch(
                "aragora.server.handlers.decisions.pipeline.execute_decision_plan_with_backbone",
                return_value="coro",
            ) as mock_execute,
            patch("aragora.utils.async_utils.get_event_loop_safe", return_value=mock_loop),
        ):
            result = handler.handle_post("/api/v1/decisions/plans/dp-001/execute", {}, h)
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["outcome"]["success"] is True
        assert body["run_id"] == "run-dp-001"
        assert body["execution_id"] == "exec-dp-001"
        assert body["correlation_id"] == "corr-dp-001"
        assert body["plan"]["status"] == "completed"
        executor_cls.assert_called_once_with(parallel_execution=False, max_parallel=None)
        kwargs = mock_execute.call_args.kwargs
        assert kwargs["executor"] is executor_inst
        assert kwargs["execution_mode"] == "workflow"
        assert kwargs["safety_mode"] == ExecutionMode.INTERACTIVE

    @patch("aragora.pipeline.executor.get_plan")
    def test_execute_plan_not_found(self, mock_get, handler):
        mock_get.return_value = None
        h = _make_http_handler({})
        result = handler.handle_post("/api/v1/decisions/plans/dp-404/execute", {}, h)
        assert _status(result) == 404
        assert _body(result) == _NOT_FOUND

    @patch("aragora.pipeline.executor.get_plan")
    def test_execute_plan_invalid_json_body(self, mock_get, handler):
        mock_get.return_value = _MockPlan()
        h = MagicMock()
        h.client_address = ("127.0.0.1", 12345)
        h.headers = {"Content-Length": "7"}
        h.rfile = MagicMock()
        h.rfile.read.return_value = b"invalid"
        result = handler.handle_post("/api/v1/decisions/plans/dp-001/execute", {}, h)
        assert _status(result) == 400

    @patch("aragora.pipeline.executor.get_plan")
    def test_execute_plan_invalid_execution_mode(self, mock_get, handler):
        mock_get.return_value = _MockPlan()
        h = _make_http_handler({"execution_mode": "teleport"})
        with patch(
            "aragora.server.handlers.decisions.pipeline.normalize_execution_mode",
            return_value="teleport",
        ):
            result = handler.handle_post("/api/v1/decisions/plans/dp-001/execute", {}, h)
        assert _status(result) == 400
        assert "execution_mode" in _body(result).get("error", "").lower()

    @patch("aragora.pipeline.executor.get_plan")
    def test_execute_plan_parallel_not_bool(self, mock_get, handler):
        mock_get.return_value = _MockPlan()
        h = _make_http_handler({"parallel_execution": "yes"})
        result = handler.handle_post("/api/v1/decisions/plans/dp-001/execute", {}, h)
        assert _status(result) == 400
        assert "parallel_execution" in _body(result).get("error", "").lower()

    @patch("aragora.pipeline.executor.get_plan")
    def test_execute_plan_max_parallel_not_int(self, mock_get, handler):
        mock_get.return_value = _MockPlan()
        h = _make_http_handler({"max_parallel": "abc"})
        result = handler.handle_post("/api/v1/decisions/plans/dp-001/execute", {}, h)
        assert _status(result) == 400
        assert "max_parallel" in _body(result).get("error", "").lower()

    @patch("aragora.pipeline.executor.get_plan")
    def test_execute_plan_max_parallel_too_small(self, mock_get, handler):
        mock_get.return_value = _MockPlan()
        h = _make_http_handler({"max_parallel": 0})
        result = handler.handle_post("/api/v1/decisions/plans/dp-001/execute", {}, h)
        assert _status(result) == 400
        assert ">= 1" in _body(result).get("error", "")

    @patch("aragora.pipeline.executor.get_plan")
    def test_execute_plan_permission_error(self, mock_get, handler):
        mock_get.return_value = _MockPlan(status=_PlanStatus.APPROVED)
        executor_cls, _ = self._patch_executor()
        mock_loop = MagicMock()
        mock_loop.run_until_complete.side_effect = PermissionError("denied")

        h = _make_http_handler({})
        with (
            patch("aragora.pipeline.executor.PlanExecutor", executor_cls),
            patch(
                "aragora.server.handlers.decisions.pipeline.execute_decision_plan_with_backbone",
                return_value="coro",
            ),
            patch("aragora.utils.async_utils.get_event_loop_safe", return_value=mock_loop),
        ):
            result = handler.handle_post("/api/v1/decisions/plans/dp-001/execute", {}, h)
        assert _status(result) == 403

    @patch("aragora.pipeline.executor.get_plan")
    def test_execute_plan_value_error_conflict(self, mock_get, handler):
        mock_get.return_value = _MockPlan(status=_PlanStatus.APPROVED)
        executor_cls, _ = self._patch_executor()
        mock_loop = MagicMock()
        mock_loop.run_until_complete.side_effect = ValueError("not approved")

        h = _make_http_handler({})
        with (
            patch("aragora.pipeline.executor.PlanExecutor", executor_cls),
            patch(
                "aragora.server.handlers.decisions.pipeline.execute_decision_plan_with_backbone",
                return_value="coro",
            ),
            patch("aragora.utils.async_utils.get_event_loop_safe", return_value=mock_loop),
        ):
            result = handler.handle_post("/api/v1/decisions/plans/dp-001/execute", {}, h)
        assert _status(result) == 409

    @patch("aragora.pipeline.executor.get_plan")
    def test_execute_plan_no_execution_mode(self, mock_get, handler):
        """Execution mode is optional - defaults to None."""
        plan = _MockPlan(status=_PlanStatus.APPROVED)
        mock_get.side_effect = [plan, plan]
        outcome = _MockOutcome()
        executor_cls, executor_inst = self._patch_executor()
        mock_loop = MagicMock()
        mock_loop.run_until_complete.return_value = (
            {
                "run_id": "run-dp-002",
                "execution_id": "exec-dp-002",
                "correlation_id": "corr-dp-002",
            },
            outcome,
        )

        h = _make_http_handler({})
        with (
            patch("aragora.pipeline.executor.PlanExecutor", executor_cls),
            patch(
                "aragora.server.handlers.decisions.pipeline.execute_decision_plan_with_backbone",
                return_value="coro",
            ) as mock_execute,
            patch("aragora.utils.async_utils.get_event_loop_safe", return_value=mock_loop),
        ):
            result = handler.handle_post("/api/v1/decisions/plans/dp-001/execute", {}, h)
        assert _status(result) == 200
        kwargs = mock_execute.call_args.kwargs
        assert kwargs["execution_mode"] is None
        assert kwargs["executor"] is executor_inst
        assert kwargs["safety_mode"] == ExecutionMode.INTERACTIVE

    @patch("aragora.pipeline.executor.get_plan")
    def test_execute_valid_modes(self, mock_get, handler):
        """All valid execution modes should pass validation."""
        for mode in ("workflow", "hybrid", "fabric", "computer_use"):
            plan = _MockPlan(status=_PlanStatus.APPROVED)
            mock_get.side_effect = [plan, plan]
            outcome = _MockOutcome()
            executor_cls, _ = self._patch_executor()
            mock_loop = MagicMock()
            mock_loop.run_until_complete.return_value = (
                {
                    "run_id": f"run-{mode}",
                    "execution_id": f"exec-{mode}",
                    "correlation_id": f"corr-{mode}",
                },
                outcome,
            )

            h = _make_http_handler({"execution_mode": mode})
            with (
                patch("aragora.pipeline.executor.PlanExecutor", executor_cls),
                patch(
                    "aragora.server.handlers.decisions.pipeline.normalize_execution_mode",
                    return_value=mode,
                ),
                patch(
                    "aragora.server.handlers.decisions.pipeline.execute_decision_plan_with_backbone",
                    return_value="coro",
                ),
                patch("aragora.utils.async_utils.get_event_loop_safe", return_value=mock_loop),
            ):
                result = handler.handle_post("/api/v1/decisions/plans/dp-001/execute", {}, h)
            assert _status(result) == 200, f"Mode {mode} should be valid"


# ---------------------------------------------------------------------------
# POST routing edge cases
# ---------------------------------------------------------------------------


class TestPostRouting:
    """Tests for POST request routing."""

    def test_post_invalid_plan_path(self, handler, mock_http_handler):
        # Path too short -> no plan_id -> 400
        result = handler.handle_post("/api/v1/decisions/plans/", {}, mock_http_handler)
        assert _status(result) == 400

    def test_post_unknown_action_returns_none(self, handler, mock_http_handler):
        result = handler.handle_post(
            "/api/v1/decisions/plans/dp-001/unknown", {}, mock_http_handler
        )
        assert result is None

    def test_post_plans_creates(self, handler):
        """POST to /api/v1/decisions/plans routes to create."""
        h = _make_http_handler({"debate_id": "debate-001"})
        with patch(
            "aragora.server.handlers.decisions.pipeline._load_debate_result",
            return_value=None,
        ):
            result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        # Should reach _handle_create_plan -> debate not found -> 404
        assert _status(result) == 404


# ---------------------------------------------------------------------------
# Org isolation
# ---------------------------------------------------------------------------


def _request(handler, method: str, path: str):
    h = _make_http_handler({})
    if method == "GET":
        return handler.handle(path, {}, h)
    return handler.handle_post(path, {}, h)


_PLAN_ROUTES = [
    ("GET", "/api/v1/decisions/plans/{id}"),
    ("GET", "/api/v1/decisions/plans/{id}/outcome"),
    ("POST", "/api/v1/decisions/plans/{id}/approve"),
    ("POST", "/api/v1/decisions/plans/{id}/reject"),
    ("POST", "/api/v1/decisions/plans/{id}/execute"),
]


class TestOrgIsolation:
    """Plans are visible only to their owning org; everything else is a 404."""

    @pytest.mark.parametrize("method,route", _PLAN_ROUTES)
    @pytest.mark.parametrize("owner", ["other-org", None])
    def test_foreign_or_unowned_plan_is_indistinguishable_from_missing(
        self, handler, method, route, owner
    ):
        foreign = _MockPlan(id="dp-foreign", status=_PlanStatus.APPROVED, org_id=owner)
        plans = {"dp-foreign": foreign}
        with (
            patch("aragora.pipeline.executor.get_plan", side_effect=plans.get),
            patch("aragora.pipeline.executor.get_outcome", return_value=_MockOutcome()),
            patch("aragora.pipeline.executor.store_plan") as mock_store,
            patch(
                "aragora.server.handlers.decisions.pipeline.execute_decision_plan_with_backbone"
            ) as mock_execute,
            patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus),
        ):
            foreign_result = _request(handler, method, route.format(id="dp-foreign"))
            missing_result = _request(handler, method, route.format(id="dp-missing"))

        assert _status(foreign_result) == _status(missing_result) == 404
        assert _body(foreign_result) == _body(missing_result) == _NOT_FOUND
        mock_store.assert_not_called()
        mock_execute.assert_not_called()
        assert foreign.status == _PlanStatus.APPROVED
        assert foreign.approval_record is None

    @patch("aragora.pipeline.executor.list_plans", return_value=[])
    def test_list_is_scoped_to_caller_org(self, mock_list, handler, mock_http_handler):
        result = handler.handle("/api/v1/decisions/plans", {}, mock_http_handler)
        assert _status(result) == 200
        mock_list.assert_called_once_with(status=None, limit=50, org_id="test-org-001")

    @pytest.mark.parametrize("method,route", [("GET", "/api/v1/decisions/plans"), *_PLAN_ROUTES])
    def test_anonymous_request_is_401(self, handler, method, route):
        from aragora.billing.auth.context import UserAuthContext

        with (
            patch(
                "aragora.billing.jwt_auth.extract_user_from_request",
                return_value=UserAuthContext(authenticated=False),
            ),
            patch("aragora.pipeline.executor.get_plan") as mock_get,
            patch("aragora.pipeline.executor.list_plans") as mock_list,
        ):
            result = _request(handler, method, route.format(id="dp-abc123"))

        assert _status(result) == 401
        assert _body(result)["code"] == "auth_required"
        mock_get.assert_not_called()
        mock_list.assert_not_called()

    def test_user_without_org_is_403(self, handler):
        from aragora.billing.auth.context import UserAuthContext

        orgless = UserAuthContext(authenticated=True, user_id="test-user-001", org_id=None)
        with (
            patch("aragora.billing.jwt_auth.extract_user_from_request", return_value=orgless),
            patch("aragora.pipeline.executor.list_plans") as mock_list,
        ):
            result = _request(handler, "GET", "/api/v1/decisions/plans")

        assert _status(result) == 403
        assert _body(result)["code"] == "org_required"
        mock_list.assert_not_called()

    @patch("aragora.pipeline.executor.get_plan")
    def test_execution_not_authorized_maps_to_not_found(self, mock_get, handler):
        from aragora.pipeline.execution_ownership import ExecutionNotAuthorizedError

        mock_get.return_value = _MockPlan(status=_PlanStatus.APPROVED)
        mock_loop = MagicMock()
        mock_loop.run_until_complete.side_effect = ExecutionNotAuthorizedError(
            "org_mismatch", "plan belongs to another org"
        )
        with (
            patch("aragora.pipeline.executor.PlanExecutor"),
            patch(
                "aragora.server.handlers.decisions.pipeline.execute_decision_plan_with_backbone",
                return_value="coro",
            ) as mock_execute,
            patch("aragora.utils.async_utils.get_event_loop_safe", return_value=mock_loop),
        ):
            result = _request(handler, "POST", "/api/v1/decisions/plans/dp-abc123/execute")

        assert _status(result) == 404
        assert _body(result) == _NOT_FOUND
        auth_context = mock_execute.call_args.kwargs["auth_context"]
        assert auth_context.user_id == "test-user-001"
        assert auth_context.org_id == "test-org-001"

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_create_stamps_org_and_creator(self, _mock_load, mock_factory, mock_store, handler):
        plan = _MockPlan(id="dp-new", org_id=None)
        mock_factory.from_debate_result.return_value = plan
        h = _make_http_handler({"debate_id": "debate-001", "org_id": "other-org"})
        with patch(
            "aragora.server.handlers.decisions.pipeline.ensure_decision_plan_backbone_run",
            return_value="run-1",
        ) as mock_seed:
            result = handler.handle_post("/api/v1/decisions/plans", {}, h)

        assert _status(result) == 201
        assert plan.org_id == "test-org-001"
        assert plan.created_by == "test-user-001"
        assert mock_seed.call_args.kwargs["org_id"] == "test-org-001"
        assert mock_seed.call_args.kwargs["created_by"] == "test-user-001"
        mock_store.assert_called_once_with(plan)


# ---------------------------------------------------------------------------
# _normalize_string_list helper
# ---------------------------------------------------------------------------


class TestNormalizeStringList:
    """Tests for the _normalize_string_list helper function."""

    def test_none_returns_none(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_string_list

        assert _normalize_string_list(None, "test") is None

    def test_empty_string_returns_none(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_string_list

        assert _normalize_string_list("", "test") is None

    def test_comma_separated_string(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_string_list

        result = _normalize_string_list("slack,teams,email", "targets")
        assert result == ["slack", "teams", "email"]

    def test_string_with_whitespace(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_string_list

        result = _normalize_string_list(" slack , teams ", "targets")
        assert result == ["slack", "teams"]

    def test_list_input(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_string_list

        result = _normalize_string_list(["slack", "teams"], "targets")
        assert result == ["slack", "teams"]

    def test_list_with_empty_strings(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_string_list

        result = _normalize_string_list(["slack", "", " "], "targets")
        assert result == ["slack"]

    def test_empty_list_returns_none(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_string_list

        assert _normalize_string_list([], "targets") is None

    def test_list_with_non_string_raises(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_string_list

        with pytest.raises(ValueError, match="must be a string"):
            _normalize_string_list([123], "targets")

    def test_invalid_type_raises(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_string_list

        with pytest.raises(ValueError, match="must be a string"):
            _normalize_string_list(123, "targets")

    def test_tuple_input(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_string_list

        result = _normalize_string_list(("a", "b"), "targets")
        assert result == ["a", "b"]


# ---------------------------------------------------------------------------
# _normalize_thread_map helper
# ---------------------------------------------------------------------------


class TestNormalizeThreadMap:
    """Tests for the _normalize_thread_map helper function."""

    def test_none_returns_none(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_thread_map

        assert _normalize_thread_map(None) is None

    def test_valid_map(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_thread_map

        result = _normalize_thread_map({"slack": "thread-1", "teams": "thread-2"})
        assert result == {"slack": "thread-1", "teams": "thread-2"}

    def test_strips_whitespace(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_thread_map

        result = _normalize_thread_map({" slack ": " thread-1 "})
        assert result == {"slack": "thread-1"}

    def test_empty_map_returns_none(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_thread_map

        assert _normalize_thread_map({}) is None

    def test_map_with_empty_values_returns_none(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_thread_map

        assert _normalize_thread_map({"": ""}) is None

    def test_non_dict_raises(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_thread_map

        with pytest.raises(ValueError, match="must be an object"):
            _normalize_thread_map("not a dict")

    def test_non_string_key_raises(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_thread_map

        with pytest.raises(ValueError, match="must be strings"):
            _normalize_thread_map({123: "thread"})

    def test_non_string_value_raises(self):
        from aragora.server.handlers.decisions.pipeline import _normalize_thread_map

        with pytest.raises(ValueError, match="must be strings"):
            _normalize_thread_map({"slack": 123})


# ---------------------------------------------------------------------------
# _build_implementation_profile_payload helper
# ---------------------------------------------------------------------------


class TestBuildImplementationProfilePayload:
    """Tests for the implementation profile builder."""

    def test_empty_body_returns_none(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload({})
        assert result is None

    def test_with_execution_engine(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        with patch(
            "aragora.server.handlers.decisions.pipeline.normalize_execution_mode",
            return_value="workflow",
        ):
            result = _build_implementation_profile_payload({"execution_engine": "workflow"})
        assert result is not None
        assert result["execution_mode"] == "workflow"

    def test_with_implementers(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload({"implementers": ["claude"]})
        assert result is not None
        assert result["implementers"] == ["claude"]

    def test_profile_dict_preserved(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload(
            {
                "implementation_profile": {"strategy": "parallel", "critic": "gpt-4"},
            }
        )
        assert result["strategy"] == "parallel"
        assert result["critic"] == "gpt-4"

    def test_top_level_does_not_override_profile(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload(
            {
                "implementation_profile": {"strategy": "serial"},
                "strategy": "parallel",
            }
        )
        # profile key takes precedence -- _maybe_set checks "if key not in payload"
        assert result["strategy"] == "serial"

    def test_channel_targets_normalized(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload({"channel_targets": "slack,teams"})
        assert result["channel_targets"] == ["slack", "teams"]

    def test_channel_targets_alias_chat_targets(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload({"chat_targets": "discord"})
        assert result["channel_targets"] == ["discord"]

    def test_thread_id_validated(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload({"thread_id": "  t-123 "})
        assert result["thread_id"] == "t-123"

    def test_empty_thread_id_raises(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        with pytest.raises(ValueError, match="non-empty string"):
            _build_implementation_profile_payload({"thread_id": "  "})

    def test_thread_id_by_platform_normalized(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload(
            {
                "thread_id_by_platform": {"slack": "t-1"},
            }
        )
        assert result["thread_id_by_platform"] == {"slack": "t-1"}

    def test_fabric_fields(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload(
            {
                "fabric_models": ["claude", "gpt-4"],
                "fabric_pool_id": "pool-1",
                "fabric_min_agents": 2,
                "fabric_max_agents": 5,
                "fabric_timeout_seconds": 300,
            }
        )
        assert result["fabric_models"] == ["claude", "gpt-4"]
        assert result["fabric_pool_id"] == "pool-1"
        assert result["fabric_min_agents"] == 2
        assert result["fabric_max_agents"] == 5
        assert result["fabric_timeout_seconds"] == 300

    def test_origin_thread_id_alias(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload({"origin_thread_id": "t-origin"})
        assert result["thread_id"] == "t-origin"

    def test_complexity_router_alias(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload({"agent_by_complexity": {"high": "claude"}})
        assert result["complexity_router"] == {"high": "claude"}

    def test_task_type_router_alias(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload({"agent_by_task_type": {"test": "gpt-4"}})
        assert result["task_type_router"] == {"test": "gpt-4"}

    def test_capability_router_alias(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload({"agent_by_capability": {"code": "codex"}})
        assert result["capability_router"] == {"code": "codex"}

    def test_none_channel_targets_removed(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload(
            {
                "channel_targets": "",
                "strategy": "serial",
            }
        )
        assert "channel_targets" not in result

    def test_none_thread_id_removed(self):
        from aragora.server.handlers.decisions.pipeline import (
            _build_implementation_profile_payload,
        )

        result = _build_implementation_profile_payload(
            {
                "implementation_profile": {"thread_id": None},
                "strategy": "serial",
            }
        )
        assert "thread_id" not in result


# ---------------------------------------------------------------------------
# _load_debate_result async helper
# ---------------------------------------------------------------------------


class TestLoadDebateResult:
    """Tests for the _load_debate_result helper."""

    @pytest.mark.asyncio
    async def test_loads_from_trace(self):
        from aragora.server.handlers.decisions.pipeline import _load_debate_result
        import tempfile
        import os
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            traces_dir = Path(tmpdir) / "traces"
            traces_dir.mkdir()
            # Create a stub trace file
            (traces_dir / "debate-001.json").write_text('{"task":"test"}')

            mock_trace = MagicMock()
            mock_trace.to_debate_result.return_value = MagicMock(task="test")
            with patch("aragora.debate.traces.DebateTrace") as MockTrace:
                MockTrace.load.return_value = mock_trace
                result = await _load_debate_result("debate-001", {"nomic_dir": tmpdir})
            assert result is not None

    @pytest.mark.asyncio
    async def test_loads_from_storage(self):
        from aragora.server.handlers.decisions.pipeline import _load_debate_result

        mock_storage = MagicMock()
        mock_result = MagicMock()
        mock_storage.get_result = MagicMock(return_value=mock_result)

        # Make get_result a proper awaitable
        import asyncio

        async def mock_get_result(debate_id):
            return mock_result

        mock_storage.get_result = mock_get_result
        result = await _load_debate_result("debate-001", {"storage": mock_storage})
        assert result is mock_result

    @pytest.mark.asyncio
    async def test_loads_from_cache(self):
        from aragora.server.handlers.decisions.pipeline import _load_debate_result

        mock_cache = MagicMock()
        mock_cache.get.return_value = MagicMock()
        with patch("aragora.core.decision_cache.get_decision_cache", return_value=mock_cache):
            result = await _load_debate_result("debate-001", {})
        assert result is not None

    @pytest.mark.asyncio
    async def test_returns_none_when_all_fail(self):
        from aragora.server.handlers.decisions.pipeline import _load_debate_result

        with patch("aragora.core.decision_cache.get_decision_cache", return_value=None):
            result = await _load_debate_result("debate-notexist", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_storage_error_falls_through(self):
        from aragora.server.handlers.decisions.pipeline import _load_debate_result

        mock_storage = MagicMock()

        async def mock_get_result(debate_id):
            raise ValueError("broken")

        mock_storage.get_result = mock_get_result

        with patch("aragora.core.decision_cache.get_decision_cache", return_value=None):
            result = await _load_debate_result("debate-001", {"storage": mock_storage})
        assert result is None


# ---------------------------------------------------------------------------
# Implementation profile in create plan (integration-level)
# ---------------------------------------------------------------------------


class TestCreatePlanImplementationProfile:
    """Tests for implementation profile handling in plan creation."""

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_implementation_profile_passed_to_factory(
        self, _mock_load, mock_factory, _mock_store, handler
    ):
        plan = _MockPlan()
        mock_factory.from_debate_result.return_value = plan
        h = _make_http_handler(
            {
                "debate_id": "debate-001",
                "execution_engine": "workflow",
                "implementers": ["claude"],
            }
        )
        with patch(
            "aragora.server.handlers.decisions.pipeline.normalize_execution_mode",
            return_value="workflow",
        ):
            result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 201
        call_kwargs = mock_factory.from_debate_result.call_args
        profile = call_kwargs.kwargs.get("implementation_profile") or call_kwargs[1].get(
            "implementation_profile"
        )
        assert profile is not None
        assert profile["execution_mode"] == "workflow"
        assert profile["implementers"] == ["claude"]

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_invalid_implementation_profile_thread_id(
        self, _mock_load, mock_factory, _mock_store, handler
    ):
        h = _make_http_handler(
            {
                "debate_id": "debate-001",
                "thread_id": "   ",
            }
        )
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 400
        assert "non-empty string" in _body(result).get("error", "")


# ---------------------------------------------------------------------------
# Human approval notification in create plan
# ---------------------------------------------------------------------------


class TestCreatePlanApprovalNotification:
    """Tests for approval notification logic in plan creation."""

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_no_notification_when_no_human_approval(
        self, _mock_load, mock_factory, _mock_store, handler
    ):
        plan = _MockPlan(requires_human_approval=False)
        mock_factory.from_debate_result.return_value = plan
        h = _make_http_handler({"debate_id": "debate-001"})
        with patch("aragora.approvals.chat.send_chat_approval_request") as mock_send:
            result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 201
        mock_send.assert_not_called()

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_notification_failure_does_not_break_create(
        self, _mock_load, mock_factory, _mock_store, handler
    ):
        """Even if notification fails, the plan should still be created."""
        plan = _MockPlan(requires_human_approval=True)
        mock_factory.from_debate_result.return_value = plan
        h = _make_http_handler(
            {
                "debate_id": "debate-001",
                "approval_targets": ["slack:general"],
            }
        )
        with patch(
            "aragora.approvals.chat.send_chat_approval_request",
            side_effect=ImportError("no module"),
        ):
            result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 201


# ---------------------------------------------------------------------------
# Misc / edge cases
# ---------------------------------------------------------------------------


class TestMiscEdgeCases:
    """Miscellaneous edge case tests."""

    def test_handler_init_default_context(self):
        from aragora.server.handlers.decisions.pipeline import DecisionPipelineHandler

        h = DecisionPipelineHandler(ctx=None)
        assert h.ctx == {}

    def test_handler_init_with_context(self):
        from aragora.server.handlers.decisions.pipeline import DecisionPipelineHandler

        h = DecisionPipelineHandler(ctx={"storage": "mock"})
        assert h.ctx["storage"] == "mock"

    def test_routes_attribute(self, handler):
        assert len(handler.ROUTES) >= 6

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.executor.get_plan")
    def test_approve_stores_plan(self, mock_get, mock_store, handler):
        """Verify store_plan is called after approve."""
        plan = _MockPlan(status=_PlanStatus.CREATED)
        mock_get.return_value = plan
        with patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus):
            h = _make_http_handler({})
            handler.handle_post("/api/v1/decisions/plans/dp-001/approve", {}, h)
        mock_store.assert_called_once_with(plan)

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.executor.get_plan")
    def test_reject_stores_plan(self, mock_get, mock_store, handler):
        """Verify store_plan is called after reject."""
        plan = _MockPlan(status=_PlanStatus.CREATED)
        mock_get.return_value = plan
        with patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus):
            h = _make_http_handler({})
            handler.handle_post("/api/v1/decisions/plans/dp-001/reject", {}, h)
        mock_store.assert_called_once_with(plan)

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.executor.get_plan")
    def test_approve_with_no_body(self, mock_get, mock_store, handler):
        """Approve with empty body should use defaults."""
        plan = _MockPlan(status=_PlanStatus.CREATED)
        mock_get.return_value = plan
        with patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus):
            h = _make_http_handler(None)
            result = handler.handle_post("/api/v1/decisions/plans/dp-001/approve", {}, h)
        assert _status(result) == 200
        assert plan.approval_record.reason == ""

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.executor.get_plan")
    def test_reject_default_reason(self, mock_get, mock_store, handler):
        """Reject without reason should use default message."""
        plan = _MockPlan(status=_PlanStatus.CREATED)
        mock_get.return_value = plan
        with patch("aragora.pipeline.decision_plan.PlanStatus", _PlanStatus):
            h = _make_http_handler({})
            handler.handle_post("/api/v1/decisions/plans/dp-001/reject", {}, h)
        assert plan.approval_record.reason == "No reason provided"

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_create_plan_null_metadata_defaults_to_empty(
        self, _mock_load, mock_factory, _mock_store, handler
    ):
        """When metadata is None/absent, it defaults to empty dict."""
        plan = _MockPlan()
        mock_factory.from_debate_result.return_value = plan
        h = _make_http_handler({"debate_id": "debate-001"})
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 201
        call_kwargs = mock_factory.from_debate_result.call_args
        meta = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata")
        assert isinstance(meta, dict)

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_create_plan_approval_mode_always(self, _mock_load, mock_factory, _mock_store, handler):
        plan = _MockPlan()
        mock_factory.from_debate_result.return_value = plan
        h = _make_http_handler({"debate_id": "debate-001", "approval_mode": "always"})
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 201

    @patch("aragora.pipeline.executor.store_plan")
    @patch("aragora.pipeline.decision_plan.DecisionPlanFactory")
    @patch(
        "aragora.server.handlers.decisions.pipeline._load_debate_result",
        return_value=MagicMock(),
    )
    def test_create_plan_approval_mode_never(self, _mock_load, mock_factory, _mock_store, handler):
        plan = _MockPlan()
        mock_factory.from_debate_result.return_value = plan
        h = _make_http_handler({"debate_id": "debate-001", "approval_mode": "never"})
        result = handler.handle_post("/api/v1/decisions/plans", {}, h)
        assert _status(result) == 201
