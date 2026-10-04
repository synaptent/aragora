"""Tests for the PlanManagementHandler.

Covers:
  - Route registration and can_handle logic
  - GET /api/v1/plans (list plans with pagination, filtering, sorting)
  - GET /api/v1/plans/:id (plan detail)
  - GET /api/v1/plans/:id/memo (DecisionMemo markdown)
  - PUT /api/v1/plans/:id/approve (approval checkpoint)
  - Rate limiting
  - Path validation (SAFE_ID_PATTERN)
  - Plan store (context vs module-level)
  - Error handling (exception paths)
  - Edge cases (empty store, invalid IDs, non-dict plans)
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.pipeline.plans import (
    PlanManagementHandler,
    _plan_store,
    get_plan_store,
    _plan_limiter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_plan_store():
    """Reset the module-level plan store between tests."""
    _plan_store.clear()
    yield
    _plan_store.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset the rate limiter between tests."""
    _plan_limiter._buckets.clear()
    yield
    _plan_limiter._buckets.clear()


def _make_handler(ctx: dict[str, Any] | None = None) -> PlanManagementHandler:
    return PlanManagementHandler(ctx=ctx or {})


def _make_http_handler(
    body: dict[str, Any] | None = None,
    client_ip: str = "127.0.0.1",
) -> MagicMock:
    handler = MagicMock()
    handler.client_address = (client_ip, 12345)
    handler.headers = {"Content-Length": "0"}
    if body is not None:
        raw = json.dumps(body).encode()
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile.read.return_value = raw
    else:
        handler.rfile.read.return_value = b"{}"
        handler.headers = {"Content-Length": "2"}
    return handler


def _body(result) -> dict[str, Any]:
    """Extract JSON body from a HandlerResult."""
    if result is None:
        return {}
    if hasattr(result, "body"):
        raw = result.body
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw) if raw else {}
    if isinstance(result, tuple):
        return result[0] if isinstance(result[0], dict) else json.loads(result[0])
    return {}


def _status(result) -> int:
    """Extract status code from a HandlerResult."""
    if result is None:
        return 0
    if hasattr(result, "status_code"):
        return result.status_code
    if isinstance(result, tuple):
        return result[1]
    return 0


def _make_plan_dict(
    plan_id: str = "plan-001",
    task: str = "Refactor auth module",
    status: str = "pending",
    debate_id: str = "debate-abc",
    created_at: str = "2026-02-20T10:00:00Z",
    requires_human_approval: bool = False,
) -> dict[str, Any]:
    """Create a dict-based plan for testing."""
    return {
        "id": plan_id,
        "task": task,
        "status": status,
        "debate_id": debate_id,
        "created_at": created_at,
        "requires_human_approval": requires_human_approval,
    }


class MockPlanStatus(Enum):
    """Mock plan status enum."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class MockPlan:
    """Mock plan object with attribute-based access."""

    def __init__(
        self,
        plan_id: str = "plan-obj-001",
        task: str = "Build feature X",
        status: MockPlanStatus = MockPlanStatus.PENDING,
        debate_id: str = "debate-xyz",
        created_at: str = "2026-02-21T12:00:00Z",
        requires_human_approval: bool = True,
        debate_result: Any = None,
    ):
        self.id = plan_id
        self.task = task
        self.status = status
        self.debate_id = debate_id
        self.created_at = created_at
        self.requires_human_approval = requires_human_approval
        self.debate_result = debate_result
        self._approved = False
        self._approval_record: dict[str, Any] = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "status": self.status.value,
            "debate_id": self.debate_id,
            "created_at": self.created_at,
            "requires_human_approval": self.requires_human_approval,
        }

    def approve(self, approver_id: str, reason: str = "", conditions: list[str] | None = None):
        self._approved = True
        self.status = MockPlanStatus.APPROVED
        self._approval_record = {
            "approver_id": approver_id,
            "reason": reason,
            "conditions": conditions or [],
        }


# ---------------------------------------------------------------------------
# Route Registration and can_handle
# ---------------------------------------------------------------------------


class TestRouting:
    """Retired: the in-memory store has no owners, so no plans route is served here."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/plans",
            "/api/v1/plans/plan-001",
            "/api/v1/plans/plan-001/memo",
            "/api/v1/plans/plan-001/approve",
            "/api/plans",
            "/api/v2/plans",
        ],
    )
    def test_does_not_handle_plans_routes(self, path):
        h = _make_handler()
        assert h.can_handle(path) is False

    def test_cannot_handle_unrelated_path(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/debates") is False

    def test_cannot_handle_empty_path(self):
        h = _make_handler()
        assert h.can_handle("") is False

    def test_cannot_handle_partial_plans_prefix(self):
        h = _make_handler()
        assert h.can_handle("/api/v1/planning") is False

    def test_declares_no_routes(self):
        assert not hasattr(PlanManagementHandler, "ROUTES")

    def test_constructor_default_ctx(self):
        h = PlanManagementHandler()
        assert h.ctx == {}

    def test_constructor_with_ctx(self):
        ctx = {"plan_store": {}}
        h = PlanManagementHandler(ctx=ctx)
        assert h.ctx is ctx


# ---------------------------------------------------------------------------
# GET /api/v1/plans - List Plans
# ---------------------------------------------------------------------------


class TestListPlans:
    def test_list_empty_store(self):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["plans"] == []
        assert body["count"] == 0
        assert body["total"] == 0

    def test_list_with_plans(self):
        store = {
            "p1": _make_plan_dict("p1", created_at="2026-02-20T10:00:00Z"),
            "p2": _make_plan_dict("p2", created_at="2026-02-21T10:00:00Z"),
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 2
        assert body["total"] == 2

    def test_list_returns_summaries(self):
        store = {"p1": _make_plan_dict("p1", task="Do thing")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {}, http)
        body = _body(result)
        summary = body["plans"][0]
        assert summary["id"] == "p1"
        assert summary["task"] == "Do thing"
        assert "status" in summary
        assert "debate_id" in summary

    def test_list_sorted_by_created_at_descending(self):
        store = {
            "p1": _make_plan_dict("p1", created_at="2026-02-19T00:00:00Z"),
            "p2": _make_plan_dict("p2", created_at="2026-02-21T00:00:00Z"),
            "p3": _make_plan_dict("p3", created_at="2026-02-20T00:00:00Z"),
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {}, http)
        body = _body(result)
        ids = [p["id"] for p in body["plans"]]
        assert ids == ["p2", "p3", "p1"]

    def test_list_with_limit(self):
        store = {
            f"p{i}": _make_plan_dict(f"p{i}", created_at=f"2026-02-{10 + i:02d}T00:00:00Z")
            for i in range(5)
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {"limit": "2"}, http)
        body = _body(result)
        assert body["count"] == 2
        assert body["total"] == 5
        assert body["limit"] == 2

    def test_list_with_offset(self):
        store = {
            f"p{i}": _make_plan_dict(f"p{i}", created_at=f"2026-02-{10 + i:02d}T00:00:00Z")
            for i in range(5)
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {"offset": "3"}, http)
        body = _body(result)
        assert body["count"] == 2
        assert body["total"] == 5
        assert body["offset"] == 3

    def test_list_with_limit_and_offset(self):
        store = {
            f"p{i}": _make_plan_dict(f"p{i}", created_at=f"2026-02-{10 + i:02d}T00:00:00Z")
            for i in range(10)
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {"limit": "3", "offset": "2"}, http)
        body = _body(result)
        assert body["count"] == 3
        assert body["total"] == 10
        assert body["limit"] == 3
        assert body["offset"] == 2

    def test_list_limit_clamped_to_max_100(self):
        store = {"p1": _make_plan_dict("p1")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {"limit": "500"}, http)
        body = _body(result)
        assert body["limit"] == 100

    def test_list_limit_clamped_to_min_1(self):
        store = {"p1": _make_plan_dict("p1")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {"limit": "0"}, http)
        body = _body(result)
        assert body["limit"] == 1

    def test_list_negative_limit_clamped(self):
        store = {"p1": _make_plan_dict("p1")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {"limit": "-5"}, http)
        body = _body(result)
        assert body["limit"] == 1

    def test_list_negative_offset_clamped(self):
        store = {"p1": _make_plan_dict("p1")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {"offset": "-10"}, http)
        body = _body(result)
        assert body["offset"] == 0

    def test_list_status_filter(self):
        store = {
            "p1": _make_plan_dict("p1", status="pending"),
            "p2": _make_plan_dict("p2", status="approved"),
            "p3": _make_plan_dict("p3", status="pending"),
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {"status": "pending"}, http)
        body = _body(result)
        assert body["total"] == 2
        assert body["count"] == 2
        for plan in body["plans"]:
            assert plan["status"] == "pending"

    def test_list_status_filter_no_match(self):
        store = {
            "p1": _make_plan_dict("p1", status="pending"),
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {"status": "approved"}, http)
        body = _body(result)
        assert body["total"] == 0
        assert body["count"] == 0
        assert body["plans"] == []

    def test_list_status_filter_with_enum_plan(self):
        """Test status filter with object-based plans that have enum status."""
        plan = MockPlan(plan_id="obj-1", status=MockPlanStatus.PENDING)
        store = {"obj-1": plan}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {"status": "pending"}, http)
        body = _body(result)
        assert body["total"] == 1

    def test_list_uses_module_level_store_when_no_ctx(self):
        _plan_store["m1"] = _make_plan_dict("m1")
        h = _make_handler()  # No plan_store in ctx
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {}, http)
        body = _body(result)
        assert body["total"] == 1

    def test_list_uses_ctx_store_over_module_store(self):
        _plan_store["m1"] = _make_plan_dict("m1")
        ctx_store = {"c1": _make_plan_dict("c1")}
        h = _make_handler(ctx={"plan_store": ctx_store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {}, http)
        body = _body(result)
        assert body["total"] == 1
        assert body["plans"][0]["id"] == "c1"

    def test_list_default_limit_is_20(self):
        store = {
            f"p{i}": _make_plan_dict(f"p{i}", created_at=f"2026-01-{i + 1:02d}T00:00:00Z")
            for i in range(25)
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {}, http)
        body = _body(result)
        assert body["limit"] == 20
        assert body["count"] == 20
        assert body["total"] == 25

    def test_list_offset_beyond_total(self):
        store = {"p1": _make_plan_dict("p1")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {"offset": "100"}, http)
        body = _body(result)
        assert body["count"] == 0
        assert body["total"] == 1

    def test_list_plan_summary_dict_plan(self):
        store = {
            "p1": _make_plan_dict(
                "p1",
                task="Do stuff",
                status="approved",
                debate_id="d-1",
                created_at="2026-01-01T00:00:00Z",
                requires_human_approval=True,
            )
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {}, http)
        body = _body(result)
        summary = body["plans"][0]
        assert summary["id"] == "p1"
        assert summary["task"] == "Do stuff"
        assert summary["status"] == "approved"
        assert summary["debate_id"] == "d-1"
        assert summary["created_at"] == "2026-01-01T00:00:00Z"
        assert summary["requires_approval"] is True

    def test_list_plan_summary_object_plan(self):
        plan = MockPlan(
            plan_id="obj-1",
            task="Build Y",
            status=MockPlanStatus.APPROVED,
            debate_id="d-obj",
            created_at="2026-02-15T00:00:00Z",
            requires_human_approval=True,
        )
        store = {"obj-1": plan}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {}, http)
        body = _body(result)
        summary = body["plans"][0]
        assert summary["id"] == "obj-1"
        assert summary["task"] == "Build Y"
        assert summary["status"] == "approved"
        assert summary["requires_approval"] is True


# ---------------------------------------------------------------------------
# GET /api/v1/plans/:id - Get Plan Detail
# ---------------------------------------------------------------------------


class TestGetPlan:
    def test_get_plan_dict(self):
        store = {"p1": _make_plan_dict("p1", task="My task")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/p1", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["id"] == "p1"
        assert body["task"] == "My task"

    def test_get_plan_object_with_to_dict(self):
        plan = MockPlan(plan_id="obj-1", task="Object task")
        store = {"obj-1": plan}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/obj-1", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["id"] == "obj-1"
        assert body["task"] == "Object task"

    def test_get_plan_generic_object(self):
        """Plan that is neither dict nor has to_dict gets str() fallback."""

        class SimplePlan:
            def __str__(self):
                return "simple-plan-repr"

        store = {"sp": SimplePlan()}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/sp", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["id"] == "sp"
        assert "simple-plan-repr" in body["plan"]

    def test_get_plan_not_found(self):
        h = _make_handler(ctx={"plan_store": {}})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/nonexistent", {}, http)
        assert _status(result) == 404

    def test_get_plan_invalid_id(self):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/../../etc", {}, http)
        assert _status(result) == 400

    def test_get_plan_id_with_special_chars(self):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/<script>alert(1)</script>", {}, http)
        assert _status(result) == 400

    def test_get_plan_id_too_long(self):
        h = _make_handler()
        http = _make_http_handler()
        long_id = "a" * 100
        result = h.handle(f"/api/v1/plans/{long_id}", {}, http)
        assert _status(result) == 400

    def test_get_plan_valid_id_formats(self):
        """Test that various valid ID formats work."""
        store = {
            "plan-abc123": _make_plan_dict("plan-abc123"),
            "plan_def456": _make_plan_dict("plan_def456"),
            "PLAN-789": _make_plan_dict("PLAN-789"),
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()

        for pid in store:
            result = h.handle(f"/api/v1/plans/{pid}", {}, http)
            assert _status(result) == 200

    def test_get_plan_to_dict_raises(self):
        """When to_dict raises, handler catches and returns 500."""

        class BadPlan:
            def to_dict(self):
                raise ValueError("serialization error")

        store = {"bad": BadPlan()}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/bad", {}, http)
        assert _status(result) == 500


# ---------------------------------------------------------------------------
# GET /api/v1/plans/:id/memo - DecisionMemo
# ---------------------------------------------------------------------------


class TestGetMemo:
    def test_memo_plan_not_found(self):
        h = _make_handler(ctx={"plan_store": {}})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/nope/memo", {}, http)
        assert _status(result) == 404

    def test_memo_simple_from_dict_plan(self):
        store = {
            "p1": _make_plan_dict("p1", task="Analyze data", status="pending", debate_id="d-1")
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/p1/memo", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["plan_id"] == "p1"
        assert body["format"] == "markdown"
        assert "Analyze data" in body["memo"]
        assert "Decision Memo: p1" in body["memo"]

    def test_memo_simple_from_object_plan(self):
        plan = MockPlan(
            plan_id="obj-1",
            task="Build feature",
            status=MockPlanStatus.APPROVED,
            debate_id="d-obj",
        )
        store = {"obj-1": plan}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/obj-1/memo", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert "Build feature" in body["memo"]
        assert "approved" in body["memo"]
        assert "d-obj" in body["memo"]

    def test_memo_with_debate_result_pr_generator(self):
        """When plan has debate_result and PRGenerator is available."""
        plan = MockPlan(plan_id="pr-1", debate_result={"some": "result"})
        store = {"pr-1": plan}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()

        mock_memo = MagicMock()
        mock_memo.to_markdown.return_value = "# PR Generated Memo\nContent here"

        mock_generator = MagicMock()
        mock_generator.generate_decision_memo.return_value = mock_memo

        mock_artifact = MagicMock()

        with (
            patch(
                "aragora.server.handlers.pipeline.plans.PRGenerator",
                create=True,
            ) as mock_pr_cls,
            patch(
                "aragora.server.handlers.pipeline.plans.DebateArtifact",
                create=True,
            ) as mock_art_cls,
        ):
            # These get imported inside the method dynamically
            # We need to patch them where they're looked up
            pass

        # The imports happen inside the try block with dynamic import.
        # Let's patch the actual import mechanism.
        import importlib

        mock_pr_gen_mod = MagicMock()
        mock_pr_gen_mod.PRGenerator.return_value = mock_generator

        mock_artifact_mod = MagicMock()
        mock_artifact_mod.DebateArtifact.from_debate_result.return_value = mock_artifact

        with patch.dict(
            "sys.modules",
            {
                "aragora.pipeline.pr_generator": mock_pr_gen_mod,
                "aragora.export.artifact": mock_artifact_mod,
            },
        ):
            result = h.handle("/api/v1/plans/pr-1/memo", {}, http)

        assert _status(result) == 200
        body = _body(result)
        assert body["memo"] == "# PR Generated Memo\nContent here"

    def test_memo_pr_generator_import_error_falls_back(self):
        """When PRGenerator can't be imported, falls back to simple memo."""
        plan = MockPlan(
            plan_id="fb-1",
            task="Fallback task",
            debate_result={"some": "result"},
        )
        store = {"fb-1": plan}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()

        # Don't patch - let the ImportError happen naturally
        result = h.handle("/api/v1/plans/fb-1/memo", {}, http)
        assert _status(result) == 200
        body = _body(result)
        # Should fall back to simple memo
        assert "Decision Memo: fb-1" in body["memo"]
        assert "Fallback task" in body["memo"]

    def test_memo_no_debate_result_uses_simple_memo(self):
        plan = MockPlan(plan_id="s-1", task="Simple task", debate_result=None)
        store = {"s-1": plan}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/s-1/memo", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert "Simple task" in body["memo"]

    def test_memo_invalid_plan_id(self):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/../hack/memo", {}, http)
        assert _status(result) == 400

    def test_memo_generic_object_fallback(self):
        """Plan that is neither dict nor has .task uses str fallback."""

        class GenericPlan:
            pass

        store = {"gp": GenericPlan()}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/gp/memo", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["plan_id"] == "gp"
        assert body["format"] == "markdown"

    def test_memo_dict_plan_with_enum_status(self):
        """Dict plan where status is an enum value (edge case)."""
        store = {
            "e1": {
                "id": "e1",
                "task": "Enum status task",
                "status": "in_progress",
                "debate_id": "d-e1",
                "created_at": "2026-02-22T00:00:00Z",
            }
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/e1/memo", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert "in_progress" in body["memo"]


# ---------------------------------------------------------------------------
# PUT /api/v1/plans/:id/approve
# ---------------------------------------------------------------------------


class TestApprovePlan:
    def test_approve_dict_plan(self):
        store = {"p1": _make_plan_dict("p1", status="pending")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler(body={"reason": "Looks good", "conditions": ["review tests"]})
        result = h.handle_put("/api/v1/plans/p1/approve", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["approved"] is True
        assert body["plan_id"] == "p1"
        assert body["plan"]["status"] == "approved"
        assert body["plan"]["approval_record"]["reason"] == "Looks good"
        assert body["plan"]["approval_record"]["conditions"] == ["review tests"]

    def test_approve_object_plan(self):
        plan = MockPlan(plan_id="obj-1", status=MockPlanStatus.PENDING)
        store = {"obj-1": plan}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler(body={"reason": "Approved by lead"})
        result = h.handle_put("/api/v1/plans/obj-1/approve", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["approved"] is True
        assert body["plan_id"] == "obj-1"
        assert plan._approved is True

    def test_approve_plan_not_found(self):
        h = _make_handler(ctx={"plan_store": {}})
        http = _make_http_handler()
        result = h.handle_put("/api/v1/plans/nonexistent/approve", {}, http)
        assert _status(result) == 404

    def test_approve_plan_invalid_id(self):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put("/api/v1/plans/<script>/approve", {}, http)
        assert _status(result) == 400

    def test_approve_no_body(self):
        store = {"p1": _make_plan_dict("p1")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()  # No body
        result = h.handle_put("/api/v1/plans/p1/approve", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["approved"] is True
        # reason defaults to empty string
        assert body["plan"]["approval_record"]["reason"] == ""

    def test_approve_with_conditions(self):
        store = {"p1": _make_plan_dict("p1")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler(body={"conditions": ["pass CI", "code review", "security scan"]})
        result = h.handle_put("/api/v1/plans/p1/approve", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert len(body["plan"]["approval_record"]["conditions"]) == 3

    def test_approve_unsupported_plan_type(self):
        """Plan that is neither dict nor has approve method returns 400."""

        class UnsupportedPlan:
            pass

        store = {"u1": UnsupportedPlan()}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle_put("/api/v1/plans/u1/approve", {}, http)
        assert _status(result) == 400

    def test_approve_sets_approver_id_from_user(self):
        store = {"p1": _make_plan_dict("p1")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler(body={"reason": "ok"})
        result = h.handle_put("/api/v1/plans/p1/approve", {}, http)
        body = _body(result)
        # The conftest mocks get_current_user to return test-user-001
        assert body["approver_id"] == "test-user-001"

    def test_approve_object_plan_with_conditions(self):
        plan = MockPlan(plan_id="obj-1")
        store = {"obj-1": plan}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler(body={"reason": "Conditional", "conditions": ["A", "B"]})
        result = h.handle_put("/api/v1/plans/obj-1/approve", {}, http)
        assert _status(result) == 200
        assert plan._approval_record["conditions"] == ["A", "B"]
        assert plan._approval_record["reason"] == "Conditional"

    def test_approve_object_plan_approve_raises(self):
        """When plan.approve() raises, handler returns 500."""

        class FailPlan:
            def approve(self, **kwargs):
                raise ValueError("approval failed")

        store = {"f1": FailPlan()}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle_put("/api/v1/plans/f1/approve", {}, http)
        assert _status(result) == 500

    def test_approve_wrong_path_returns_none(self):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put("/api/v1/plans/p1/reject", {}, http)
        assert result is None

    def test_approve_missing_segments_returns_none(self):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put("/api/v1/plans", {}, http)
        assert result is None

    def test_approve_extra_segments_returns_none(self):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put("/api/v1/plans/p1/approve/extra", {}, http)
        assert result is None


# ---------------------------------------------------------------------------
# Rate Limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_rate_limit_on_handle(self):
        store = {"p1": _make_plan_dict("p1")}
        h = _make_handler(ctx={"plan_store": store})
        # Exhaust rate limiter
        for _ in range(30):
            http = _make_http_handler(client_ip="10.0.0.1")
            h.handle("/api/v1/plans", {}, http)
        # Next request should be rate limited
        http = _make_http_handler(client_ip="10.0.0.1")
        result = h.handle("/api/v1/plans", {}, http)
        assert _status(result) == 429

    def test_rate_limit_on_handle_put(self):
        store = {"p1": _make_plan_dict("p1")}
        h = _make_handler(ctx={"plan_store": store})
        for _ in range(30):
            http = _make_http_handler(client_ip="10.0.0.2")
            h.handle_put("/api/v1/plans/p1/approve", {}, http)
        http = _make_http_handler(client_ip="10.0.0.2")
        result = h.handle_put("/api/v1/plans/p1/approve", {}, http)
        assert _status(result) == 429

    def test_rate_limit_different_ips_independent(self):
        store = {"p1": _make_plan_dict("p1")}
        h = _make_handler(ctx={"plan_store": store})
        for _ in range(30):
            http = _make_http_handler(client_ip="10.0.0.3")
            h.handle("/api/v1/plans", {}, http)
        # Different IP should still be allowed
        http = _make_http_handler(client_ip="10.0.0.4")
        result = h.handle("/api/v1/plans", {}, http)
        assert _status(result) == 200


# ---------------------------------------------------------------------------
# handle() - Routing Logic
# ---------------------------------------------------------------------------


class TestHandleRouting:
    def test_handle_returns_none_for_unknown_path(self):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/other", {}, http)
        assert result is None

    def test_handle_returns_none_for_short_plan_path(self):
        h = _make_handler()
        http = _make_http_handler()
        # Path like /api/plans with only 3 segments doesn't match plan_id routes
        # but matches the list route - so it returns 200
        result = h.handle("/api/v1/plans", {}, http)
        assert _status(result) == 200

    def test_handle_unknown_subresource(self):
        """Path like /api/plans/:id/unknown returns None."""
        store = {"p1": _make_plan_dict("p1")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/p1/unknown", {}, http)
        assert result is None

    def test_handle_plans_id_memo_routes_correctly(self):
        store = {"p1": _make_plan_dict("p1", task="Memo task")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/p1/memo", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert "Memo task" in body["memo"]


# ---------------------------------------------------------------------------
# Plan Store Access
# ---------------------------------------------------------------------------


class TestPlanStore:
    def test_get_plan_store_returns_module_store(self):
        store = get_plan_store()
        assert store is _plan_store

    def test_ctx_plan_store_takes_precedence(self):
        ctx_store = {"ctx-plan": _make_plan_dict("ctx-plan")}
        h = _make_handler(ctx={"plan_store": ctx_store})
        store = h._get_plans_from_store()
        assert store is ctx_store

    def test_fallback_to_module_store(self):
        h = _make_handler(ctx={})
        store = h._get_plans_from_store()
        assert store is _plan_store

    def test_ctx_with_none_plan_store_uses_module(self):
        h = _make_handler(ctx={"plan_store": None})
        store = h._get_plans_from_store()
        assert store is _plan_store


# ---------------------------------------------------------------------------
# _plan_summary helper
# ---------------------------------------------------------------------------


class TestPlanSummary:
    def test_summary_from_dict(self):
        h = _make_handler()
        plan = _make_plan_dict(
            "ps-1",
            task="Summary task",
            status="approved",
            debate_id="d-s",
            created_at="2026-01-01T00:00:00Z",
            requires_human_approval=True,
        )
        summary = h._plan_summary(plan)
        assert summary == {
            "id": "ps-1",
            "task": "Summary task",
            "status": "approved",
            "debate_id": "d-s",
            "created_at": "2026-01-01T00:00:00Z",
            "requires_approval": True,
        }

    def test_summary_from_object(self):
        h = _make_handler()
        plan = MockPlan(
            plan_id="ps-obj",
            task="Object summary",
            status=MockPlanStatus.PENDING,
            debate_id="d-o",
            created_at="2026-02-01T00:00:00Z",
            requires_human_approval=False,
        )
        summary = h._plan_summary(plan)
        assert summary["id"] == "ps-obj"
        assert summary["task"] == "Object summary"
        assert summary["status"] == "pending"
        assert summary["requires_approval"] is False

    def test_summary_from_dict_missing_fields(self):
        h = _make_handler()
        plan: dict[str, Any] = {}
        summary = h._plan_summary(plan)
        assert summary["id"] == ""
        assert summary["task"] == ""
        assert summary["status"] == ""
        assert summary["requires_approval"] is False

    def test_summary_from_object_without_attrs(self):
        h = _make_handler()

        class BarePlan:
            pass

        plan = BarePlan()
        summary = h._plan_summary(plan)
        assert summary["id"] == ""
        assert summary["task"] == ""
        assert summary["requires_approval"] is False


# ---------------------------------------------------------------------------
# _get_plan_status helper
# ---------------------------------------------------------------------------


class TestGetPlanStatus:
    def test_status_from_dict(self):
        h = _make_handler()
        plan = {"status": "approved"}
        assert h._get_plan_status(plan) == "approved"

    def test_status_from_dict_missing(self):
        h = _make_handler()
        plan: dict[str, Any] = {}
        assert h._get_plan_status(plan) == ""

    def test_status_from_object_with_enum(self):
        h = _make_handler()
        plan = MockPlan(status=MockPlanStatus.REJECTED)
        assert h._get_plan_status(plan) == "rejected"

    def test_status_from_object_with_string(self):
        h = _make_handler()

        class StringPlan:
            status = "done"

        assert h._get_plan_status(StringPlan()) == "done"

    def test_status_from_object_without_status(self):
        h = _make_handler()

        class NoStatusPlan:
            pass

        assert h._get_plan_status(NoStatusPlan()) == ""


# ---------------------------------------------------------------------------
# _get_plan_created_at helper
# ---------------------------------------------------------------------------


class TestGetPlanCreatedAt:
    def test_created_at_from_dict(self):
        h = _make_handler()
        plan = {"created_at": "2026-02-20T00:00:00Z"}
        assert h._get_plan_created_at(plan) == "2026-02-20T00:00:00Z"

    def test_created_at_from_dict_missing(self):
        h = _make_handler()
        assert h._get_plan_created_at({}) == ""

    def test_created_at_from_object_string(self):
        h = _make_handler()
        plan = MockPlan(created_at="2026-02-21T00:00:00Z")
        assert h._get_plan_created_at(plan) == "2026-02-21T00:00:00Z"

    def test_created_at_from_object_with_isoformat(self):
        h = _make_handler()
        from datetime import datetime, timezone

        class DatePlan:
            created_at = datetime(2026, 2, 20, 12, 0, 0, tzinfo=timezone.utc)

        result = h._get_plan_created_at(DatePlan())
        assert "2026-02-20" in result

    def test_created_at_from_object_without_attr(self):
        h = _make_handler()

        class NoCAPlan:
            pass

        assert h._get_plan_created_at(NoCAPlan()) == ""


# ---------------------------------------------------------------------------
# _build_simple_memo helper
# ---------------------------------------------------------------------------


class TestBuildSimpleMemo:
    def test_simple_memo_from_dict(self):
        h = _make_handler()
        plan = _make_plan_dict("m1", task="Memo task", status="pending", debate_id="d-m")
        memo = h._build_simple_memo(plan, "m1")
        assert "Decision Memo: m1" in memo
        assert "Memo task" in memo
        assert "pending" in memo
        assert "d-m" in memo

    def test_simple_memo_from_object(self):
        h = _make_handler()
        plan = MockPlan(task="Obj task", status=MockPlanStatus.APPROVED, debate_id="d-o")
        memo = h._build_simple_memo(plan, "obj-memo")
        assert "Decision Memo: obj-memo" in memo
        assert "Obj task" in memo
        assert "approved" in memo
        assert "d-o" in memo

    def test_simple_memo_from_generic_object(self):
        h = _make_handler()

        class GenericPlan:
            pass

        memo = h._build_simple_memo(GenericPlan(), "gen-1")
        assert "Decision Memo: gen-1" in memo
        assert "Generated from plan data" in memo

    def test_simple_memo_empty_dict(self):
        h = _make_handler()
        memo = h._build_simple_memo({}, "empty")
        assert "Decision Memo: empty" in memo


# ---------------------------------------------------------------------------
# Edge Cases and Error Paths
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_handle_none_result_for_extra_path_segments(self):
        """Paths with more than 5 segments are not matched."""
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle("/api/v1/plans/p1/memo/extra", {}, http)
        assert result is None

    def test_list_with_non_default_params(self):
        store = {
            f"p{i}": _make_plan_dict(f"p{i}", created_at=f"2026-02-{i + 1:02d}T00:00:00Z")
            for i in range(3)
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {"limit": "1", "offset": "1"}, http)
        body = _body(result)
        assert body["count"] == 1
        assert body["offset"] == 1

    def test_approve_dict_plan_modifies_store_in_place(self):
        plan = _make_plan_dict("p1", status="pending")
        store = {"p1": plan}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler(body={"reason": "approved"})
        h.handle_put("/api/v1/plans/p1/approve", {}, http)
        # Verify the store was modified in place
        assert store["p1"]["status"] == "approved"
        assert store["p1"]["approval_record"]["approved"] is True

    def test_approve_object_plan_returns_to_dict_result(self):
        plan = MockPlan(plan_id="obj-1")
        store = {"obj-1": plan}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle_put("/api/v1/plans/obj-1/approve", {}, http)
        body = _body(result)
        # The plan's to_dict is called after approve
        assert body["plan"]["id"] == "obj-1"
        assert body["plan"]["status"] == "approved"

    def test_handle_version_prefix_stripping(self):
        """Verify version prefix is stripped before routing."""
        store = {"p1": _make_plan_dict("p1")}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        # v1
        r1 = h.handle("/api/v1/plans/p1", {}, http)
        assert _status(r1) == 200
        # v2
        r2 = h.handle("/api/v2/plans/p1", {}, http)
        assert _status(r2) == 200

    def test_empty_plan_id_segment(self):
        """ID segment that's empty should fail validation."""
        h = _make_handler()
        http = _make_http_handler()
        # The path /api/v1/plans// would have empty segment
        # split produces ['', 'api', 'plans', '', ...]
        result = h.handle("/api/v1/plans/", {}, http)
        # Either None or 400 depending on path parsing
        if result is not None:
            assert _status(result) == 400

    def test_list_plans_with_mixed_plan_types(self):
        """Mix dict and object plans in same store."""
        store = {
            "d1": _make_plan_dict("d1", created_at="2026-02-01T00:00:00Z"),
            "o1": MockPlan(plan_id="o1", created_at="2026-02-02T00:00:00Z"),
        }
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle("/api/v1/plans", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 2

    def test_approve_plan_object_without_to_dict_after_approve(self):
        """Plan with approve but no to_dict still returns plan_id."""

        class MinimalPlan:
            def approve(self, **kwargs):
                pass

        store = {"mp": MinimalPlan()}
        h = _make_handler(ctx={"plan_store": store})
        http = _make_http_handler()
        result = h.handle_put("/api/v1/plans/mp/approve", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["plan"] == {"id": "mp"}

    def test_handle_put_unrelated_path_returns_none(self):
        h = _make_handler()
        http = _make_http_handler()
        result = h.handle_put("/api/v1/debates/d1/approve", {}, http)
        assert result is None
