"""Tests for the Plans handler (aragora/server/handlers/plans.py).

Covers all routes and behavior of the PlansHandler class:
- can_handle() routing for versioned and unversioned paths
- GET  /api/v1/plans          - List plans with pagination/filtering
- GET  /api/v1/plans/{id}     - Get single plan
- POST /api/v1/plans          - Create a new plan
- POST /api/v1/plans/{id}/approve - Approve a plan
- POST /api/v1/plans/{id}/reject  - Reject a plan
- POST /api/v1/plans/{id}/execute - Execute an approved plan
- Error handling (missing params, not found, invalid status, conflict)
- Unversioned /api/plans alias routes
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import ANY, MagicMock, patch

import pytest

from aragora.pipeline.backbone_errors import BackbonePersistenceError, FAIL_CLOSED_BACKBONE_MESSAGE
from aragora.pipeline.decision_plan.core import (
    ApprovalMode,
    DecisionPlan,
    PlanStatus,
)
from aragora.pipeline.execution_mode import ExecutionMode
from aragora.pipeline.execution_ownership import ExecutionNotAuthorizedError
from aragora.server.handlers.plans import PlansHandler

pytestmark = pytest.mark.usefixtures("org_scoped_request_user")

TEST_ORG = "test-org-001"
NOT_FOUND_BODY = {"error": "Plan not found", "code": "not_found"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: object) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result: object) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


class MockHTTPHandler:
    """Mock HTTP request handler for PlansHandler tests."""

    def __init__(
        self,
        body: dict | None = None,
        method: str = "GET",
    ):
        self.command = method
        self.client_address = ("127.0.0.1", 12345)
        self.headers: dict[str, str] = {"User-Agent": "test-agent"}
        self.rfile = MagicMock()

        if body:
            body_bytes = json.dumps(body).encode()
            self.rfile.read.return_value = body_bytes
            self.headers["Content-Length"] = str(len(body_bytes))
        else:
            self.rfile.read.return_value = b"{}"
            self.headers["Content-Length"] = "2"


def _make_plan(**overrides: Any) -> DecisionPlan:
    """Factory to create DecisionPlan instances with sensible defaults.

    Uses the real DecisionPlan so enum comparisons work natively in the handler.
    """
    defaults = {
        "debate_id": "debate-001",
        "task": "Decide on rate-limiter design",
        "status": PlanStatus.AWAITING_APPROVAL,
        "approval_mode": ApprovalMode.RISK_BASED,
        "org_id": TEST_ORG,
        "created_by": "test-user-001",
    }
    defaults.update(overrides)
    return DecisionPlan(**defaults)


def _close_scheduled_coroutine(coro, *, name: str | None = None):
    """Close scheduled background coroutines in tests to avoid warnings."""
    coro.close()
    return {"scheduled": name}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_store():
    """Create a mock plan store."""
    store = MagicMock()
    store.list_for_org.return_value = []
    store.count_for_org.return_value = 0
    store.get.return_value = None
    store.create.return_value = None
    store.update_status_for_org.return_value = True
    return store


@pytest.fixture
def handler(mock_store):
    """Create a PlansHandler with a mock plan store patched in."""
    with patch("aragora.server.handlers.plans._get_plan_store", return_value=mock_store):
        h = PlansHandler({})
        yield h


@pytest.fixture
def http_get():
    """Create a GET MockHTTPHandler."""
    return MockHTTPHandler(method="GET")


@pytest.fixture
def http_post_factory():
    """Factory for creating POST MockHTTPHandlers with body."""

    def _create(body: dict | None = None) -> MockHTTPHandler:
        return MockHTTPHandler(body=body, method="POST")

    return _create


@pytest.fixture(autouse=True)
def patch_plan_backbone_helpers():
    """Keep plan handler tests isolated from the shared RunLedger store."""
    with (
        patch(
            "aragora.server.decision_integrity_utils.ensure_decision_plan_backbone_run",
            return_value="run-plan-1",
        ),
        patch(
            "aragora.server.decision_integrity_utils.sync_decision_plan_backbone_receipt",
            return_value=True,
        ),
    ):
        yield


# ---------------------------------------------------------------------------
# can_handle() routing tests
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for PlansHandler.can_handle()."""

    def test_handles_versioned_plans_root(self, handler):
        assert handler.can_handle("/api/v1/plans") is True

    def test_handles_unversioned_plans_root(self, handler):
        assert handler.can_handle("/api/plans") is True

    def test_handles_versioned_plan_by_id(self, handler):
        assert handler.can_handle("/api/v1/plans/dp-abc123") is True

    def test_handles_unversioned_plan_by_id(self, handler):
        assert handler.can_handle("/api/plans/dp-abc123") is True

    def test_handles_approve_path(self, handler):
        assert handler.can_handle("/api/v1/plans/dp-abc123/approve") is True

    def test_handles_reject_path(self, handler):
        assert handler.can_handle("/api/v1/plans/dp-abc123/reject") is True

    def test_handles_execute_path(self, handler):
        assert handler.can_handle("/api/v1/plans/dp-abc123/execute") is True

    def test_does_not_handle_unrelated_path(self, handler):
        assert handler.can_handle("/api/v1/debates") is False

    def test_does_not_handle_partial_prefix(self, handler):
        assert handler.can_handle("/api/v1/planning") is False


# ---------------------------------------------------------------------------
# GET /api/v1/plans - List plans
# ---------------------------------------------------------------------------


class TestListPlans:
    """Tests for listing plans (GET /api/v1/plans)."""

    def test_list_plans_empty(self, handler, mock_store, http_get):
        mock_store.list_for_org.return_value = []
        mock_store.count_for_org.return_value = 0

        result = handler.handle("/api/v1/plans", {}, http_get)
        body = _body(result)

        assert _status(result) == 200
        assert body["plans"] == []
        assert body["total"] == 0
        assert body["limit"] == 50
        assert body["offset"] == 0

    def test_list_plans_with_results(self, handler, mock_store, http_get):
        plan = _make_plan(id="dp-001", task="Test plan")
        mock_store.list_for_org.return_value = [plan]
        mock_store.count_for_org.return_value = 1

        result = handler.handle("/api/v1/plans", {}, http_get)
        body = _body(result)

        assert _status(result) == 200
        assert len(body["plans"]) == 1
        assert body["plans"][0]["id"] == "dp-001"
        assert body["total"] == 1

    def test_list_plans_with_pagination(self, handler, mock_store, http_get):
        mock_store.list_for_org.return_value = []
        mock_store.count_for_org.return_value = 100

        result = handler.handle("/api/v1/plans", {"limit": "10", "offset": "20"}, http_get)
        body = _body(result)

        assert _status(result) == 200
        assert body["limit"] == 10
        assert body["offset"] == 20

    def test_list_plans_with_debate_id_filter(self, handler, mock_store, http_get):
        mock_store.list_for_org.return_value = []
        mock_store.count_for_org.return_value = 0

        handler.handle("/api/v1/plans", {"debate_id": "dbt-xyz"}, http_get)

        mock_store.list_for_org.assert_called_once()
        call_kwargs = mock_store.list_for_org.call_args
        assert call_kwargs[1]["debate_id"] == "dbt-xyz"

    def test_list_plans_with_status_filter(self, handler, mock_store, http_get):
        mock_store.list_for_org.return_value = []
        mock_store.count_for_org.return_value = 0

        result = handler.handle("/api/v1/plans", {"status": "approved"}, http_get)

        assert _status(result) == 200
        # Verify the store received the PlanStatus enum value
        call_kwargs = mock_store.list_for_org.call_args[1]
        assert call_kwargs["status"] == PlanStatus.APPROVED

    def test_list_plans_invalid_status(self, handler, mock_store, http_get):
        result = handler.handle("/api/v1/plans", {"status": "invalid_status"}, http_get)

        assert _status(result) == 400
        assert "Invalid status" in _body(result)["error"]

    def test_list_plans_unversioned_path(self, handler, mock_store, http_get):
        mock_store.list_for_org.return_value = []
        mock_store.count_for_org.return_value = 0

        result = handler.handle("/api/plans", {}, http_get)
        body = _body(result)

        assert _status(result) == 200
        assert body["plans"] == []

    def test_list_plans_summary_truncates_task(self, handler, mock_store, http_get):
        long_task = "A" * 300
        plan = _make_plan(task=long_task)
        mock_store.list_for_org.return_value = [plan]
        mock_store.count_for_org.return_value = 1

        result = handler.handle("/api/v1/plans", {}, http_get)
        body = _body(result)

        # _plan_summary truncates task to 200 chars
        assert len(body["plans"][0]["task"]) == 200

    def test_list_plans_default_limit_and_offset(self, handler, mock_store, http_get):
        mock_store.list_for_org.return_value = []
        mock_store.count_for_org.return_value = 0

        handler.handle("/api/v1/plans", {}, http_get)

        call_kwargs = mock_store.list_for_org.call_args[1]
        assert call_kwargs["limit"] == 50
        assert call_kwargs["offset"] == 0


# ---------------------------------------------------------------------------
# GET /api/v1/plans/{plan_id} - Get plan details
# ---------------------------------------------------------------------------


class TestGetPlan:
    """Tests for getting a single plan by ID."""

    def test_get_plan_found(self, handler, mock_store, http_get):
        plan = _make_plan(id="dp-found")
        mock_store.get.return_value = plan

        result = handler.handle("/api/v1/plans/dp-found", {}, http_get)
        body = _body(result)

        assert _status(result) == 200
        assert body["id"] == "dp-found"

    def test_get_plan_not_found(self, handler, mock_store, http_get):
        mock_store.get.return_value = None

        result = handler.handle("/api/v1/plans/dp-missing", {}, http_get)

        assert _status(result) == 404
        assert "not found" in _body(result)["error"].lower()

    def test_get_plan_unversioned(self, handler, mock_store, http_get):
        plan = _make_plan(id="dp-unver")
        mock_store.get.return_value = plan

        result = handler.handle("/api/plans/dp-unver", {}, http_get)
        body = _body(result)

        assert _status(result) == 200
        assert body["id"] == "dp-unver"

    def test_get_plan_detail_includes_action_items(self, handler, mock_store, http_get):
        plan = _make_plan(
            id="dp-actions",
            metadata={"action_items": [{"title": "Item 1"}]},
        )
        mock_store.get.return_value = plan

        result = handler.handle("/api/v1/plans/dp-actions", {}, http_get)
        body = _body(result)

        assert _status(result) == 200
        assert body["action_items"] == [{"title": "Item 1"}]

    def test_get_plan_detail_includes_estimated_duration(self, handler, mock_store, http_get):
        plan = _make_plan(
            id="dp-dur",
            metadata={"estimated_duration": "2 hours"},
        )
        mock_store.get.return_value = plan

        result = handler.handle("/api/v1/plans/dp-dur", {}, http_get)
        body = _body(result)

        assert _status(result) == 200
        assert body["estimated_duration"] == "2 hours"

    def test_get_plan_looks_up_by_path_id(self, handler, mock_store, http_get):
        plan = _make_plan(id="dp-fallback")
        mock_store.get.return_value = plan

        result = handler.handle("/api/v1/plans/dp-fallback", {}, http_get)
        body = _body(result)

        assert _status(result) == 200
        assert body["id"] == "dp-fallback"
        mock_store.get.assert_called_once_with("dp-fallback")

    def test_get_plan_memo(self, handler, mock_store, http_get):
        mock_store.get.return_value = _make_plan(id="dp-memo")

        result = handler.handle("/api/v1/plans/dp-memo/memo", {}, http_get)
        body = _body(result)

        assert _status(result) == 200
        assert body["plan_id"] == "dp-memo"
        assert body["format"] == "markdown"
        assert isinstance(body["memo"], str) and body["memo"]

    def test_get_plan_detail_uses_to_dict(self, handler, mock_store, http_get):
        """Verify detail response includes full to_dict output."""
        plan = _make_plan(id="dp-detail", task="Full detail test")
        mock_store.get.return_value = plan

        result = handler.handle("/api/v1/plans/dp-detail", {}, http_get)
        body = _body(result)

        assert _status(result) == 200
        # Fields from to_dict
        assert body["id"] == "dp-detail"
        assert body["task"] == "Full detail test"
        assert body["status"] == "awaiting_approval"
        assert "budget" in body
        assert "created_at" in body


# ---------------------------------------------------------------------------
# POST /api/v1/plans - Create plan
# ---------------------------------------------------------------------------


class TestCreatePlan:
    """Tests for creating a new decision plan."""

    def test_create_plan_success(self, handler, mock_store, http_post_factory):
        http_handler = http_post_factory(
            body={"debate_id": "dbt-001", "task": "Design rate limiter"}
        )

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 201
        body = _body(result)
        assert body["debate_id"] == "dbt-001"
        assert body["task"] == "Design rate limiter"
        assert body["run_id"] == "run-plan-1"
        mock_store.create.assert_called_once()

    def test_create_plan_stamps_caller_ownership(self, handler, mock_store, http_post_factory):
        http_handler = http_post_factory(body={"debate_id": "dbt-001", "task": "Own it"})

        with (
            patch("aragora.server.handlers.plans._fire_plan_notification"),
            patch(
                "aragora.server.decision_integrity_utils.ensure_decision_plan_backbone_run",
                return_value="run-plan-1",
            ) as mock_ensure,
        ):
            result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 201
        stored_plan = mock_store.create.call_args.args[0]
        assert stored_plan.org_id == TEST_ORG
        assert stored_plan.created_by == "test-user-001"
        assert mock_ensure.call_args.kwargs["org_id"] == TEST_ORG
        assert mock_ensure.call_args.kwargs["created_by"] == "test-user-001"

    def test_create_plan_scrubs_reserved_backbone_metadata(
        self, handler, mock_store, http_post_factory
    ):
        http_handler = http_post_factory(
            body={
                "debate_id": "dbt-001",
                "task": "Design rate limiter",
                "metadata": {
                    "custom": "keep-me",
                    "source_surface": "spoofed",
                    "source_id": "spoofed-id",
                    "backbone_run_id": "run-spoofed",
                    "backbone_entrypoint": "spoofed.entrypoint",
                },
            }
        )

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 201
        stored_plan = mock_store.create.call_args.args[0]
        assert stored_plan.metadata["custom"] == "keep-me"
        assert "source_surface" not in stored_plan.metadata
        assert "source_id" not in stored_plan.metadata
        assert "backbone_run_id" not in stored_plan.metadata
        assert "backbone_entrypoint" not in stored_plan.metadata

    def test_create_plan_missing_body(self, handler, mock_store):
        http_handler = MockHTTPHandler(method="POST")
        # Set Content-Length to 0 to simulate no body
        http_handler.headers["Content-Length"] = "0"
        http_handler.rfile.read.return_value = b""

        result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 400
        assert "debate_id" in _body(result)["error"].lower()

    def test_create_plan_missing_debate_id(self, handler, mock_store, http_post_factory):
        http_handler = http_post_factory(body={"task": "Something"})

        result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 400
        assert "debate_id" in _body(result)["error"].lower()

    def test_create_plan_missing_task(self, handler, mock_store, http_post_factory):
        http_handler = http_post_factory(body={"debate_id": "dbt-001"})

        result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 400
        assert "task" in _body(result)["error"].lower()

    def test_create_plan_accepts_title_as_task(self, handler, mock_store, http_post_factory):
        http_handler = http_post_factory(body={"debate_id": "dbt-001", "title": "My title"})

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 201
        body = _body(result)
        assert body["task"] == "My title"

    def test_create_plan_accepts_summary_as_task(self, handler, mock_store, http_post_factory):
        http_handler = http_post_factory(body={"debate_id": "dbt-001", "summary": "My summary"})

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 201
        body = _body(result)
        assert body["task"] == "My summary"

    def test_create_plan_invalid_approval_mode(self, handler, mock_store, http_post_factory):
        http_handler = http_post_factory(
            body={
                "debate_id": "dbt-001",
                "task": "Something",
                "approval_mode": "bogus",
            }
        )

        result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 400
        assert "approval_mode" in _body(result)["error"].lower()

    def test_create_plan_with_budget(self, handler, mock_store, http_post_factory):
        http_handler = http_post_factory(
            body={
                "debate_id": "dbt-001",
                "task": "Something",
                "estimated_budget": 100.0,
            }
        )

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 201
        body = _body(result)
        assert body["budget"]["limit_usd"] == 100.0

    def test_create_plan_with_budget_limit_usd_field(self, handler, mock_store, http_post_factory):
        http_handler = http_post_factory(
            body={
                "debate_id": "dbt-001",
                "task": "Something",
                "budget_limit_usd": 50.0,
            }
        )

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 201
        body = _body(result)
        assert body["budget"]["limit_usd"] == 50.0

    def test_create_plan_with_action_items(self, handler, mock_store, http_post_factory):
        http_handler = http_post_factory(
            body={
                "debate_id": "dbt-001",
                "task": "Something",
                "action_items": [{"title": "Do this"}],
            }
        )

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 201
        body = _body(result)
        assert body["action_items"] == [{"title": "Do this"}]

    def test_create_plan_with_estimated_duration(self, handler, mock_store, http_post_factory):
        http_handler = http_post_factory(
            body={
                "debate_id": "dbt-001",
                "task": "Something",
                "estimated_duration": "3 days",
            }
        )

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 201
        body = _body(result)
        assert body["estimated_duration"] == "3 days"

    def test_create_plan_never_approval_sets_approved_status(
        self, handler, mock_store, http_post_factory
    ):
        """When approval_mode=never, status should be APPROVED directly."""
        http_handler = http_post_factory(
            body={
                "debate_id": "dbt-001",
                "task": "Something",
                "approval_mode": "never",
            }
        )

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 201
        body = _body(result)
        assert body["status"] == "approved"

    def test_create_plan_risk_based_approval_sets_awaiting(
        self, handler, mock_store, http_post_factory
    ):
        """When approval_mode=risk_based (default), status is awaiting_approval."""
        http_handler = http_post_factory(
            body={
                "debate_id": "dbt-001",
                "task": "Something",
            }
        )

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 201
        body = _body(result)
        assert body["status"] == "awaiting_approval"

    def test_create_plan_unversioned_path(self, handler, mock_store, http_post_factory):
        http_handler = http_post_factory(body={"debate_id": "dbt-001", "task": "Design something"})

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/plans", {}, http_handler)

        assert _status(result) == 201

    def test_create_plan_invalid_json_body(self, handler, mock_store):
        http_handler = MockHTTPHandler(method="POST")
        http_handler.headers["Content-Length"] = "5"
        http_handler.rfile.read.return_value = b"not-j"

        result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 400

    def test_create_plan_metadata_non_dict_ignored(self, handler, mock_store, http_post_factory):
        """When metadata is not a dict, it should be coerced to empty dict."""
        http_handler = http_post_factory(
            body={
                "debate_id": "dbt-001",
                "task": "Something",
                "metadata": "not-a-dict",
            }
        )

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 201

    def test_create_plan_invalid_budget_ignored(self, handler, mock_store, http_post_factory):
        """Non-numeric budget should be silently ignored."""
        http_handler = http_post_factory(
            body={
                "debate_id": "dbt-001",
                "task": "Something",
                "estimated_budget": "not-a-number",
            }
        )

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans", {}, http_handler)

        assert _status(result) == 201
        # Budget limit stays at None since it couldn't be parsed
        body = _body(result)
        assert body["budget"]["limit_usd"] is None


# ---------------------------------------------------------------------------
# POST /api/v1/plans/{plan_id}/approve
# ---------------------------------------------------------------------------


class TestApprovePlan:
    """Tests for approving a plan."""

    def test_approve_plan_success(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-app", status=PlanStatus.AWAITING_APPROVAL)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={"reason": "Looks good"})

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans/dp-app/approve", {}, http_handler)

        body = _body(result)
        assert _status(result) == 200
        assert body["status"] == "approved"
        assert body["plan_id"] == "dp-app"
        mock_store.update_status_for_org.assert_called_once()

    def test_approve_plan_not_found(self, handler, mock_store, http_post_factory):
        mock_store.get.return_value = None
        http_handler = http_post_factory(body={})

        result = handler.handle_post("/api/v1/plans/dp-missing/approve", {}, http_handler)

        assert _status(result) == 404

    def test_approve_plan_wrong_status_executing(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-exec", status=PlanStatus.EXECUTING)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        result = handler.handle_post("/api/v1/plans/dp-exec/approve", {}, http_handler)

        assert _status(result) == 409
        assert "cannot be approved" in _body(result)["error"].lower()

    def test_approve_plan_already_approved(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-dup", status=PlanStatus.APPROVED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        result = handler.handle_post("/api/v1/plans/dp-dup/approve", {}, http_handler)

        assert _status(result) == 409

    def test_approve_plan_with_auto_execute(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-auto", status=PlanStatus.AWAITING_APPROVAL)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={"auto_execute": True})

        launch = {
            "run_id": "run-approve-1",
            "execution_id": "exec-approve-1",
            "correlation_id": "corr-approve-1",
            "status": "queued",
            "execution_mode": "workflow",
        }
        with (
            patch("aragora.server.handlers.plans._fire_plan_notification"),
            patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=launch,
            ) as mock_queue,
            patch(
                "aragora.pipeline.canonical_execution.schedule_coroutine",
                side_effect=_close_scheduled_coroutine,
            ),
        ):
            result = handler.handle_post("/api/v1/plans/dp-auto/approve", {}, http_handler)

        body = _body(result)
        assert _status(result) == 200
        assert body["execution_scheduled"] is True
        assert body["run_id"] == "run-approve-1"
        assert body["execution_id"] == "exec-approve-1"
        assert body["correlation_id"] == "corr-approve-1"
        mock_queue.assert_called_once_with(
            plan,
            auth_context=ANY,
            execution_mode=None,
            safety_mode=ExecutionMode.INTERACTIVE,
            org_id=TEST_ORG,
            created_by="test-user-001",
        )

    def test_approve_plan_auto_execute_failure_still_approves(
        self, handler, mock_store, http_post_factory
    ):
        plan = _make_plan(id="dp-autofail", status=PlanStatus.AWAITING_APPROVAL)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={"auto_execute": True})

        with (
            patch("aragora.server.handlers.plans._fire_plan_notification"),
            patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                side_effect=RuntimeError("queue unavailable"),
            ),
        ):
            result = handler.handle_post("/api/v1/plans/dp-autofail/approve", {}, http_handler)

        body = _body(result)
        assert _status(result) == 200
        assert body["status"] == "approved"
        assert body["execution_scheduled"] is False

    def test_approve_plan_auto_execute_backbone_failure_is_explicit(
        self, handler, mock_store, http_post_factory
    ):
        plan = _make_plan(id="dp-autobackbone", status=PlanStatus.AWAITING_APPROVAL)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={"auto_execute": True})

        with (
            patch("aragora.server.handlers.plans._fire_plan_notification"),
            patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                side_effect=BackbonePersistenceError("run ledger unavailable"),
            ),
        ):
            result = handler.handle_post("/api/v1/plans/dp-autobackbone/approve", {}, http_handler)

        body = _body(result)
        assert _status(result) == 200
        assert body["status"] == "approved"
        assert body["execution_scheduled"] is False
        assert body["execution_error"] == FAIL_CLOSED_BACKBONE_MESSAGE

    def test_approve_plan_with_conditions(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-cond", status=PlanStatus.AWAITING_APPROVAL)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={"reason": "OK", "conditions": ["Run staging first"]})

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans/dp-cond/approve", {}, http_handler)

        assert _status(result) == 200

    def test_approve_plan_created_status(self, handler, mock_store, http_post_factory):
        """Plans in CREATED status can also be approved."""
        plan = _make_plan(id="dp-cr", status=PlanStatus.CREATED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans/dp-cr/approve", {}, http_handler)

        assert _status(result) == 200

    def test_approve_plan_rejected_status_conflict(self, handler, mock_store, http_post_factory):
        """Plans in REJECTED status cannot be approved."""
        plan = _make_plan(id="dp-rej", status=PlanStatus.REJECTED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        result = handler.handle_post("/api/v1/plans/dp-rej/approve", {}, http_handler)

        assert _status(result) == 409


# ---------------------------------------------------------------------------
# POST /api/v1/plans/{plan_id}/reject
# ---------------------------------------------------------------------------


class TestRejectPlan:
    """Tests for rejecting a plan."""

    def test_reject_plan_success(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-rej", status=PlanStatus.AWAITING_APPROVAL)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={"reason": "Too risky"})

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans/dp-rej/reject", {}, http_handler)

        body = _body(result)
        assert _status(result) == 200
        assert body["status"] == "rejected"
        assert body["reason"] == "Too risky"
        assert body["plan_id"] == "dp-rej"
        mock_store.update_status_for_org.assert_called_once()

    def test_reject_plan_not_found(self, handler, mock_store, http_post_factory):
        mock_store.get.return_value = None
        http_handler = http_post_factory(body={"reason": "Whatever"})

        result = handler.handle_post("/api/v1/plans/dp-gone/reject", {}, http_handler)

        assert _status(result) == 404

    def test_reject_plan_missing_reason(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-noreason", status=PlanStatus.AWAITING_APPROVAL)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        result = handler.handle_post("/api/v1/plans/dp-noreason/reject", {}, http_handler)

        assert _status(result) == 400
        assert "reason" in _body(result)["error"].lower()

    def test_reject_plan_empty_reason(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-empty", status=PlanStatus.AWAITING_APPROVAL)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={"reason": ""})

        result = handler.handle_post("/api/v1/plans/dp-empty/reject", {}, http_handler)

        assert _status(result) == 400
        assert "reason" in _body(result)["error"].lower()

    def test_reject_plan_wrong_status(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-approved", status=PlanStatus.APPROVED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={"reason": "Changed mind"})

        result = handler.handle_post("/api/v1/plans/dp-approved/reject", {}, http_handler)

        assert _status(result) == 409
        assert "cannot be rejected" in _body(result)["error"].lower()

    def test_reject_plan_created_status(self, handler, mock_store, http_post_factory):
        """Plans in CREATED status can also be rejected."""
        plan = _make_plan(id="dp-rej-cr", status=PlanStatus.CREATED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={"reason": "Not ready"})

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans/dp-rej-cr/reject", {}, http_handler)

        assert _status(result) == 200
        assert _body(result)["status"] == "rejected"

    def test_reject_plan_unversioned(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-urej", status=PlanStatus.AWAITING_APPROVAL)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={"reason": "Nope"})

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/plans/dp-urej/reject", {}, http_handler)

        assert _status(result) == 200

    def test_reject_plan_update_status_called_correctly(
        self, handler, mock_store, http_post_factory
    ):
        plan = _make_plan(id="dp-upd", status=PlanStatus.AWAITING_APPROVAL)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={"reason": "Bad idea"})

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            handler.handle_post("/api/v1/plans/dp-upd/reject", {}, http_handler)

        call_args = mock_store.update_status_for_org.call_args
        assert call_args[0][0] == "dp-upd"
        assert call_args[0][1] == TEST_ORG
        assert call_args[0][2] == PlanStatus.REJECTED
        assert call_args[1]["rejection_reason"] == "Bad idea"


# ---------------------------------------------------------------------------
# POST /api/v1/plans/{plan_id}/execute
# ---------------------------------------------------------------------------


class TestExecutePlan:
    """Tests for executing an approved plan."""

    def test_execute_plan_success(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-exec", status=PlanStatus.APPROVED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        launch = {
            "run_id": "run-exec-1",
            "execution_id": "exec-exec-1",
            "correlation_id": "corr-exec-1",
            "status": "queued",
            "execution_mode": "workflow",
        }
        with (
            patch("aragora.server.handlers.plans._fire_plan_notification"),
            patch("aragora.pipeline.canonical_execution.queue_plan_execution", return_value=launch),
            patch(
                "aragora.pipeline.canonical_execution.schedule_coroutine",
                side_effect=_close_scheduled_coroutine,
            ),
        ):
            result = handler.handle_post("/api/v1/plans/dp-exec/execute", {}, http_handler)

        body = _body(result)
        assert _status(result) == 202
        assert body["status"] == "executing"
        assert body["plan_id"] == "dp-exec"
        assert body["run_id"] == "run-exec-1"
        assert body["execution_id"] == "exec-exec-1"
        assert body["correlation_id"] == "corr-exec-1"

    def test_execute_plan_not_found(self, handler, mock_store, http_post_factory):
        mock_store.get.return_value = None
        http_handler = http_post_factory(body={})

        result = handler.handle_post("/api/v1/plans/dp-gone/execute", {}, http_handler)

        assert _status(result) == 404

    def test_execute_plan_not_approved(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-noapp", status=PlanStatus.AWAITING_APPROVAL)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        result = handler.handle_post("/api/v1/plans/dp-noapp/execute", {}, http_handler)

        assert _status(result) == 409
        assert "must be approved" in _body(result)["error"].lower()

    def test_execute_plan_already_executing(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-running", status=PlanStatus.EXECUTING)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        result = handler.handle_post("/api/v1/plans/dp-running/execute", {}, http_handler)

        assert _status(result) == 409
        assert "already executing" in _body(result)["error"].lower()

    def test_execute_plan_already_completed(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-done", status=PlanStatus.COMPLETED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        result = handler.handle_post("/api/v1/plans/dp-done/execute", {}, http_handler)

        assert _status(result) == 409
        assert "already been executed" in _body(result)["error"].lower()

    def test_execute_plan_already_failed(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-fail", status=PlanStatus.FAILED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        result = handler.handle_post("/api/v1/plans/dp-fail/execute", {}, http_handler)

        assert _status(result) == 409

    def test_execute_plan_bridge_failure(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-bridgefail", status=PlanStatus.APPROVED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        with patch(
            "aragora.pipeline.canonical_execution.queue_plan_execution",
            side_effect=RuntimeError("Queue unavailable"),
        ):
            result = handler.handle_post("/api/v1/plans/dp-bridgefail/execute", {}, http_handler)

        assert _status(result) == 500

    def test_execute_plan_backbone_failure_returns_503(
        self, handler, mock_store, http_post_factory
    ):
        plan = _make_plan(id="dp-backbonefail", status=PlanStatus.APPROVED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        with patch(
            "aragora.pipeline.canonical_execution.queue_plan_execution",
            side_effect=BackbonePersistenceError("run ledger unavailable"),
        ):
            result = handler.handle_post("/api/v1/plans/dp-backbonefail/execute", {}, http_handler)

        assert _status(result) == 503
        assert _body(result)["error"] == FAIL_CLOSED_BACKBONE_MESSAGE

    def test_execute_plan_with_execution_mode(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-mode", status=PlanStatus.APPROVED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={"execution_mode": "dry_run"})

        launch = {
            "run_id": "run-mode-1",
            "execution_id": "exec-mode-1",
            "correlation_id": "corr-mode-1",
            "status": "queued",
            "execution_mode": "dry_run",
        }
        with (
            patch("aragora.server.handlers.plans._fire_plan_notification"),
            patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value=launch,
            ) as mock_queue,
            patch(
                "aragora.pipeline.canonical_execution.schedule_coroutine",
                side_effect=_close_scheduled_coroutine,
            ),
        ):
            result = handler.handle_post("/api/v1/plans/dp-mode/execute", {}, http_handler)

        assert _status(result) == 202
        mock_queue.assert_called_once_with(
            plan,
            auth_context=ANY,
            execution_mode="dry_run",
            safety_mode=ExecutionMode.INTERACTIVE,
            org_id=TEST_ORG,
            created_by="test-user-001",
        )

    def test_execute_plan_unversioned(self, handler, mock_store, http_post_factory):
        plan = _make_plan(id="dp-uexec", status=PlanStatus.APPROVED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        with (
            patch("aragora.server.handlers.plans._fire_plan_notification"),
            patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                return_value={
                    "run_id": "run-uexec-1",
                    "execution_id": "exec-uexec-1",
                    "correlation_id": "corr-uexec-1",
                    "status": "queued",
                    "execution_mode": "workflow",
                },
            ),
            patch(
                "aragora.pipeline.canonical_execution.schedule_coroutine",
                side_effect=_close_scheduled_coroutine,
            ),
        ):
            result = handler.handle_post("/api/plans/dp-uexec/execute", {}, http_handler)

        assert _status(result) == 202

    def test_execute_plan_rejected_status_conflict(self, handler, mock_store, http_post_factory):
        """A rejected plan cannot be executed."""
        plan = _make_plan(id="dp-rej", status=PlanStatus.REJECTED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        result = handler.handle_post("/api/v1/plans/dp-rej/execute", {}, http_handler)

        assert _status(result) == 409

    def test_execute_plan_created_status_conflict(self, handler, mock_store, http_post_factory):
        """A plan in CREATED status cannot be executed (must be approved first)."""
        plan = _make_plan(id="dp-created", status=PlanStatus.CREATED)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        result = handler.handle_post("/api/v1/plans/dp-created/execute", {}, http_handler)

        assert _status(result) == 409
        assert "must be approved" in _body(result)["error"].lower()


# ---------------------------------------------------------------------------
# Edge cases and misc
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases and misc behavior."""

    def test_handle_returns_404_for_unrecognized_get_path(self, handler, http_get):
        result = handler.handle("/api/v1/other", {}, http_get)
        assert _status(result) == 404
        assert _body(result)["error"] == "Unknown plans route"

    def test_handle_post_returns_404_for_unrecognized_post_path(self, handler, http_post_factory):
        http_handler = http_post_factory(body={})
        result = handler.handle_post("/api/v1/other", {}, http_handler)
        assert _status(result) == 404
        assert _body(result)["error"] == "Unknown plans route"

    def test_multiple_plans_listed(self, handler, mock_store, http_get):
        plans = [_make_plan(id=f"dp-{i}", task=f"Plan {i}") for i in range(5)]
        mock_store.list_for_org.return_value = plans
        mock_store.count_for_org.return_value = 5

        result = handler.handle("/api/v1/plans", {}, http_get)
        body = _body(result)

        assert _status(result) == 200
        assert len(body["plans"]) == 5
        assert body["total"] == 5

    def test_plan_summary_fields(self, handler, mock_store, http_get):
        """Verify that plan summary includes all expected fields."""
        plan = _make_plan(
            id="dp-fields",
            debate_id="dbt-f",
            task="Test fields",
            status=PlanStatus.APPROVED,
            approval_mode=ApprovalMode.ALWAYS,
        )
        mock_store.list_for_org.return_value = [plan]
        mock_store.count_for_org.return_value = 1

        result = handler.handle("/api/v1/plans", {}, http_get)
        body = _body(result)
        summary = body["plans"][0]

        assert summary["id"] == "dp-fields"
        assert summary["debate_id"] == "dbt-f"
        assert summary["task"] == "Test fields"
        assert summary["status"] == "approved"
        assert summary["approval_mode"] == "always"
        assert "has_critical_risks" in summary
        assert "requires_human_approval" in summary
        assert "created_at" in summary

    def test_get_plan_trailing_slash_handled(self, handler, mock_store, http_get):
        result = handler.handle("/api/v1/plans/", {}, http_get)

        assert _status(result) == 404
        assert _body(result)["error"] == "Unknown plans route"
        mock_store.get.assert_not_called()

    def test_approve_plan_stores_approver_id_from_user(
        self, handler, mock_store, http_post_factory
    ):
        """The approver_id should be derived from the authenticated user context."""
        plan = _make_plan(id="dp-who", status=PlanStatus.AWAITING_APPROVAL)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={})

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans/dp-who/approve", {}, http_handler)

        body = _body(result)
        assert _status(result) == 200
        # The conftest mock_auth sets user_id to "test-user-001"
        assert body["approved_by"] == "test-user-001"

    def test_reject_plan_stores_rejecter_id(self, handler, mock_store, http_post_factory):
        """The rejected_by field should be derived from the authenticated user context."""
        plan = _make_plan(id="dp-rejwho", status=PlanStatus.AWAITING_APPROVAL)
        mock_store.get.return_value = plan

        http_handler = http_post_factory(body={"reason": "Nope"})

        with patch("aragora.server.handlers.plans._fire_plan_notification"):
            result = handler.handle_post("/api/v1/plans/dp-rejwho/reject", {}, http_handler)

        body = _body(result)
        assert _status(result) == 200
        assert body["rejected_by"] == "test-user-001"


# ---------------------------------------------------------------------------
# Org isolation
# ---------------------------------------------------------------------------
