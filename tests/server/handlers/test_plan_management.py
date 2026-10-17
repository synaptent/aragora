"""
Tests for decision plan management handler.

Tests:
- Route matching (can_handle)
- GET /api/v1/plans (list, pagination, status filter)
- GET /api/v1/plans/:id (detail, not found)
- PUT /api/v1/plans/:id/approve (approve, not found)
- GET /api/v1/plans/:id/memo (memo generation, not found)
- Dict-based plans
- Object-based plans (DecisionPlan)
- Rate limiting
- Error handling
"""

import json
import pytest
from datetime import datetime
from unittest.mock import MagicMock

from aragora.server.handlers.pipeline.plans import (
    PlanManagementHandler,
    _plan_limiter,
    _plan_store,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_http_handler():
    """Create mock HTTP handler."""
    mock = MagicMock()
    mock.client_address = ("127.0.0.1", 12345)
    mock.headers = {"Content-Length": "0"}
    mock.rfile = MagicMock()
    mock.rfile.read.return_value = b""
    return mock


def _make_put_handler(body: dict) -> MagicMock:
    """Create a mock handler with JSON body."""
    mock = MagicMock()
    mock.client_address = ("127.0.0.1", 12345)
    body_bytes = json.dumps(body).encode()
    mock.headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body_bytes)),
    }
    mock.rfile = MagicMock()
    mock.rfile.read.return_value = body_bytes
    return mock


@pytest.fixture
def sample_plans():
    """Create sample plan data."""
    return {
        "dp-001": {
            "id": "dp-001",
            "task": "Design a rate limiter",
            "status": "created",
            "debate_id": "d-100",
            "created_at": "2026-02-14T10:00:00",
            "requires_human_approval": True,
        },
        "dp-002": {
            "id": "dp-002",
            "task": "Implement caching layer",
            "status": "approved",
            "debate_id": "d-101",
            "created_at": "2026-02-13T09:00:00",
            "requires_human_approval": False,
        },
        "dp-003": {
            "id": "dp-003",
            "task": "Add monitoring",
            "status": "created",
            "debate_id": "d-102",
            "created_at": "2026-02-12T08:00:00",
            "requires_human_approval": True,
        },
    }


@pytest.fixture
def handler(sample_plans):
    """Create handler with sample plan store."""
    return PlanManagementHandler(ctx={"plan_store": sample_plans})


@pytest.fixture(autouse=True)
def clear_state():
    """Clear rate limiter and plan store between tests."""
    _plan_limiter._buckets.clear()
    _plan_store.clear()
    yield
    _plan_store.clear()


# ===========================================================================
# Route Matching
# ===========================================================================


class TestRouteMatching:
    """The retired handler's store has no owners, so it must not serve any plans route."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/plans",
            "/api/plans",
            "/api/v1/plans/dp-001",
            "/api/v1/plans/dp-001/approve",
            "/api/v1/plans/dp-001/memo",
        ],
    )
    def test_does_not_handle_plans_routes(self, handler, path):
        assert handler.can_handle(path) is False

    def test_declares_no_routes(self, handler):
        assert not hasattr(PlanManagementHandler, "ROUTES")

    def test_cannot_handle_debates(self, handler):
        assert handler.can_handle("/api/v1/debates") is False

    def test_cannot_handle_agents(self, handler):
        assert handler.can_handle("/api/v1/agents") is False


# ===========================================================================
# GET /api/v1/plans
# ===========================================================================


class TestListPlans:
    def test_lists_all_plans(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans", {}, mock_http_handler)
        assert result is not None
        body = result[0]
        assert body["count"] == 3
        assert body["total"] == 3

    def test_plans_sorted_by_created_at_descending(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans", {}, mock_http_handler)
        body = result[0]
        plans = body["plans"]
        assert plans[0]["id"] == "dp-001"  # Most recent
        assert plans[-1]["id"] == "dp-003"  # Oldest

    def test_pagination_limit(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans", {"limit": "2"}, mock_http_handler)
        body = result[0]
        assert body["count"] == 2
        assert body["total"] == 3
        assert body["limit"] == 2

    def test_pagination_offset(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans", {"offset": "1", "limit": "2"}, mock_http_handler)
        body = result[0]
        assert body["count"] == 2
        assert body["offset"] == 1

    def test_filter_by_status(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans", {"status": "created"}, mock_http_handler)
        body = result[0]
        assert body["count"] == 2
        for plan in body["plans"]:
            assert plan["status"] == "created"

    def test_filter_by_approved_status(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans", {"status": "approved"}, mock_http_handler)
        body = result[0]
        assert body["count"] == 1
        assert body["plans"][0]["status"] == "approved"

    def test_plan_summary_fields(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans", {}, mock_http_handler)
        body = result[0]
        plan = body["plans"][0]
        assert "id" in plan
        assert "task" in plan
        assert "status" in plan
        assert "debate_id" in plan

    def test_empty_store(self, mock_http_handler):
        handler = PlanManagementHandler(ctx={"plan_store": {}})
        result = handler.handle("/api/v1/plans", {}, mock_http_handler)
        body = result[0]
        assert body["count"] == 0
        assert body["total"] == 0


# ===========================================================================
# GET /api/v1/plans/:id
# ===========================================================================


class TestGetPlan:
    def test_get_existing_plan(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans/dp-001", {}, mock_http_handler)
        assert result is not None
        body = result[0]
        assert body["id"] == "dp-001"
        assert body["task"] == "Design a rate limiter"

    def test_plan_not_found(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans/dp-999", {}, mock_http_handler)
        assert result is not None
        assert result[1] == 404

    def test_get_plan_with_object(self, mock_http_handler):
        """Test with a plan object that has to_dict()."""
        plan_obj = MagicMock()
        plan_obj.to_dict.return_value = {
            "id": "dp-obj",
            "task": "Object plan",
            "status": "created",
        }
        store = {"dp-obj": plan_obj}
        handler = PlanManagementHandler(ctx={"plan_store": store})

        result = handler.handle("/api/v1/plans/dp-obj", {}, mock_http_handler)
        body = result[0]
        assert body["id"] == "dp-obj"
        plan_obj.to_dict.assert_called_once()

    def test_invalid_plan_id(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans/'; DROP TABLE plans;--", {}, mock_http_handler)
        assert result is not None
        assert result[1] == 400


# ===========================================================================
# PUT /api/v1/plans/:id/approve
# ===========================================================================


class TestApprovePlan:
    def test_approve_dict_plan(self, handler, mock_http_handler):
        put_handler = _make_put_handler({"reason": "Looks good"})
        result = handler.handle_put("/api/v1/plans/dp-001/approve", {}, put_handler)
        assert result is not None
        body = result[0]
        assert body["approved"] is True
        assert body["plan_id"] == "dp-001"

    def test_approve_updates_status(self, handler, sample_plans, mock_http_handler):
        put_handler = _make_put_handler({"reason": "Approved"})
        handler.handle_put("/api/v1/plans/dp-001/approve", {}, put_handler)
        assert sample_plans["dp-001"]["status"] == "approved"

    def test_approve_with_conditions(self, handler, mock_http_handler):
        put_handler = _make_put_handler(
            {
                "reason": "Conditional approval",
                "conditions": ["Must pass tests", "Review needed"],
            }
        )
        result = handler.handle_put("/api/v1/plans/dp-001/approve", {}, put_handler)
        body = result[0]
        assert body["plan"]["approval_record"]["conditions"] == [
            "Must pass tests",
            "Review needed",
        ]

    def test_approve_object_plan(self, mock_http_handler):
        plan_obj = MagicMock()
        plan_obj.to_dict.return_value = {"id": "dp-obj", "status": "approved"}
        store = {"dp-obj": plan_obj}
        handler = PlanManagementHandler(ctx={"plan_store": store})

        put_handler = _make_put_handler({"reason": "OK"})
        result = handler.handle_put("/api/v1/plans/dp-obj/approve", {}, put_handler)
        body = result[0]
        assert body["approved"] is True
        plan_obj.approve.assert_called_once()

    def test_approve_not_found(self, handler, mock_http_handler):
        put_handler = _make_put_handler({})
        result = handler.handle_put("/api/v1/plans/dp-999/approve", {}, put_handler)
        assert result[1] == 404

    def test_approve_empty_body(self, handler, mock_http_handler):
        result = handler.handle_put("/api/v1/plans/dp-001/approve", {}, mock_http_handler)
        assert result is not None
        body = result[0]
        assert body["approved"] is True


# ===========================================================================
# GET /api/v1/plans/:id/memo
# ===========================================================================


class TestGetMemo:
    def test_memo_for_dict_plan(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans/dp-001/memo", {}, mock_http_handler)
        assert result is not None
        body = result[0]
        assert body["plan_id"] == "dp-001"
        assert body["format"] == "markdown"
        assert "Decision Memo" in body["memo"]
        assert "Design a rate limiter" in body["memo"]

    def test_memo_not_found(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans/dp-999/memo", {}, mock_http_handler)
        assert result[1] == 404

    def test_memo_includes_status(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans/dp-001/memo", {}, mock_http_handler)
        body = result[0]
        assert "created" in body["memo"]

    def test_memo_includes_debate_id(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/plans/dp-001/memo", {}, mock_http_handler)
        body = result[0]
        assert "d-100" in body["memo"]


# ===========================================================================
# Rate Limiting
# ===========================================================================


class TestPlanRateLimiting:
    def test_rate_limit_on_list(self, handler, mock_http_handler):
        for _ in range(35):
            _plan_limiter.is_allowed("127.0.0.1")

        result = handler.handle("/api/v1/plans", {}, mock_http_handler)
        assert result[1] == 429

    def test_rate_limit_on_put(self, handler, mock_http_handler):
        for _ in range(35):
            _plan_limiter.is_allowed("127.0.0.1")

        put_handler = _make_put_handler({})
        result = handler.handle_put("/api/v1/plans/dp-001/approve", {}, put_handler)
        assert result[1] == 429
