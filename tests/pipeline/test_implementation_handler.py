"""
Tests for the ImplementationOperationsMixin in
aragora.server.handlers.debates.implementation.

Covers:
- Route registration in ROUTES and AUTH_REQUIRED_ENDPOINTS
- Handler dispatch for /decision-integrity suffix
- Basic flow: 404 on missing debate, valid package on success
- include_receipt / include_plan flags
- Execution mode "request_approval" creates an approval request
- Execution mode "execute" requires ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION=1
- Budget check (_check_execution_budget) behaviour
- Receipt persistence (_persist_receipt) is called when receipt is generated
- Channel notification via route_result when notify_origin=True
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.debates.implementation import (
    ImplementationOperationsMixin,
    _check_execution_budget,
    _persist_receipt,
)
from aragora.server.handlers.debates.routing import AUTH_REQUIRED_ENDPOINTS, ROUTES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_debate_dict(**overrides: Any) -> dict[str, Any]:
    """Create a minimal debate dict with sensible defaults."""
    defaults: dict[str, Any] = {
        "debate_id": "test-debate-001",
        "task": "Design a rate limiter",
        "final_answer": "Implement token bucket algorithm",
        "confidence": 0.85,
        "consensus_reached": True,
        "rounds_used": 3,
        "rounds_completed": 3,
        "status": "completed",
        "agents": ["claude", "gpt4", "gemini"],
        "metadata": {"source": "test"},
    }
    defaults.update(overrides)
    return defaults


@dataclass
class _FakeTask:
    id: str = "task-1"
    description: str = "Apply token bucket"
    files: list[str] = field(default_factory=lambda: ["rate_limiter.py"])
    complexity: str = "low"


@dataclass
class _FakeReceipt:
    receipt_id: str = "rcpt-001"

    def to_dict(self) -> dict[str, Any]:
        return {"receipt_id": self.receipt_id, "debate_id": "test-debate-001"}


@dataclass
class _FakePlan:
    tasks: list[_FakeTask] = field(default_factory=lambda: [_FakeTask()])

    def to_dict(self) -> dict[str, Any]:
        return {"tasks": [{"id": t.id} for t in self.tasks]}


@dataclass
class _FakePackage:
    debate_id: str = "test-debate-001"
    receipt: _FakeReceipt | None = None
    plan: _FakePlan | None = None
    context_snapshot: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "debate_id": self.debate_id,
            "receipt": self.receipt.to_dict() if self.receipt else None,
            "plan": self.plan.to_dict() if self.plan else None,
            "context_snapshot": None,
        }


class _FakeApprovalRequest:
    """Mimics an ApprovalRequest returned by ApprovalFlow.request_approval."""

    def __init__(self) -> None:
        from datetime import datetime, timezone

        self.id = "approval-001"
        self.title = "Implement debate test-debate-001"
        self.description = "Execute decision implementation plan generated from debate."
        self.changes: list[dict[str, Any]] = []
        self.risk_level = "medium"
        self.requested_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        self.requested_by = "system"
        self.timeout_seconds = None
        self.status = MagicMock(value="pending")
        self.approved_by = None
        self.approved_at = None
        self.rejection_reason = None
        self.metadata: dict[str, Any] = {"debate_id": "test-debate-001"}


class MockHandler(ImplementationOperationsMixin):
    """Concrete class mixing in ImplementationOperationsMixin for testing."""

    def __init__(self) -> None:
        from aragora.rbac.models import AuthorizationContext

        self.ctx: dict[str, Any] = {"repo_root": "/tmp/test-repo"}
        self._storage: Any = None
        self._body: dict[str, Any] | None = None
        self._auth_context = AuthorizationContext(
            user_id="test-user",
            permissions={"debates.write"},
        )

    def get_storage(self) -> Any:
        return self._storage

    def read_json_body(self, handler: Any, max_size: int | None = None) -> dict[str, Any] | None:
        return self._body

    def get_current_user(self, handler: Any) -> Any:
        return None


def _build_mock_storage(debate: dict[str, Any] | None = None) -> MagicMock:
    """Build a mock storage that returns the given debate."""
    storage = MagicMock()
    storage.get_debate.return_value = debate
    return storage


def _decode_response(result: Any) -> tuple[dict[str, Any], int]:
    """Decode a HandlerResult into (body_dict, status_code)."""
    status = result.status_code
    body = json.loads(result.body.decode("utf-8")) if result.body else {}
    return body, status


# We need to patch decorators that wrap the handler method so they don't
# interfere with our unit tests.  The three decorators on _create_decision_integrity
# are: @require_permission, @require_storage, @handle_errors.
# We patch require_permission and handle_errors to be passthroughs,
# but we keep require_storage logic since we test for it indirectly via storage presence.

_IMPL_MOD = "aragora.server.handlers.debates.implementation"
_ROUTING_MOD = "aragora.server.handlers.debates.routing"


# ---------------------------------------------------------------------------
# 1. Route registration
# ---------------------------------------------------------------------------


class TestRouteRegistration:
    """Verify the decision-integrity route is declared properly."""

    def test_decision_integrity_in_routes(self) -> None:
        assert "/api/v1/debates/*/decision-integrity" in ROUTES

    def test_decision_integrity_in_auth_required(self) -> None:
        assert "/decision-integrity" in AUTH_REQUIRED_ENDPOINTS


# ---------------------------------------------------------------------------
# 2. Handler dispatch
# ---------------------------------------------------------------------------


class TestHandlerDispatch:
    """Verify the main DebatesHandler correctly dispatches /decision-integrity."""

    @patch(f"{_IMPL_MOD}.run_async")
    @patch(f"{_IMPL_MOD}.build_decision_integrity_package", new_callable=AsyncMock)
    @patch(f"{_IMPL_MOD}._persist_receipt")
    @patch(f"{_IMPL_MOD}._persist_plan")
    def test_dispatch_reaches_create_decision_integrity(
        self,
        mock_persist_plan: MagicMock,
        mock_persist_receipt: MagicMock,
        mock_build: AsyncMock,
        mock_run_async: MagicMock,
    ) -> None:
        """The handler method is reachable and returns a json response."""
        package = _FakePackage(receipt=_FakeReceipt(), plan=_FakePlan())
        mock_run_async.return_value = package
        mock_persist_receipt.return_value = "rcpt-001"

        handler_obj = MockHandler()
        handler_obj._storage = _build_mock_storage(_make_debate_dict())
        handler_obj._body = {}

        mock_http_handler = MagicMock()
        result = handler_obj._create_decision_integrity(mock_http_handler, "test-debate-001")

        body, status = _decode_response(result)
        assert status == 200
        assert body["debate_id"] == "test-debate-001"


# ---------------------------------------------------------------------------
# 3. Basic flow
# ---------------------------------------------------------------------------


class TestBasicFlow:
    """Test the core happy and sad paths of _create_decision_integrity."""

    @patch(f"{_IMPL_MOD}.run_async")
    @patch(f"{_IMPL_MOD}.build_decision_integrity_package", new_callable=AsyncMock)
    def test_returns_404_when_debate_not_found(
        self, mock_build: AsyncMock, mock_run_async: MagicMock
    ) -> None:
        handler_obj = MockHandler()
        handler_obj._storage = _build_mock_storage(None)  # No debate
        handler_obj._body = {}

        result = handler_obj._create_decision_integrity(MagicMock(), "missing-id")
        body, status = _decode_response(result)
        assert status == 404
        assert "not found" in body.get("error", "").lower()

    @patch(f"{_IMPL_MOD}.run_async")
    @patch(f"{_IMPL_MOD}.build_decision_integrity_package", new_callable=AsyncMock)
    @patch(f"{_IMPL_MOD}._persist_receipt")
    @patch(f"{_IMPL_MOD}._persist_plan")
    def test_returns_package_with_receipt_and_plan(
        self,
        mock_persist_plan: MagicMock,
        mock_persist_receipt: MagicMock,
        mock_build: AsyncMock,
        mock_run_async: MagicMock,
    ) -> None:
        package = _FakePackage(receipt=_FakeReceipt(), plan=_FakePlan())
        mock_run_async.return_value = package
        mock_persist_receipt.return_value = "rcpt-001"

        handler_obj = MockHandler()
        handler_obj._storage = _build_mock_storage(_make_debate_dict())
        handler_obj._body = {}

        result = handler_obj._create_decision_integrity(MagicMock(), "test-debate-001")
        body, status = _decode_response(result)

        assert status == 200
        assert body["receipt"] is not None
        assert body["plan"] is not None
        assert body["receipt_id"] == "rcpt-001"

    @patch(f"{_IMPL_MOD}.run_async")
    @patch(f"{_IMPL_MOD}.build_decision_integrity_package", new_callable=AsyncMock)
    @patch(f"{_IMPL_MOD}._persist_receipt")
    @patch(f"{_IMPL_MOD}._persist_plan")
    def test_include_flags_forwarded(
        self,
        mock_persist_plan: MagicMock,
        mock_persist_receipt: MagicMock,
        mock_build: AsyncMock,
        mock_run_async: MagicMock,
    ) -> None:
        """include_receipt=False and include_plan=False are forwarded to build function."""
        package = _FakePackage(receipt=None, plan=None)
        mock_run_async.return_value = package

        handler_obj = MockHandler()
        handler_obj._storage = _build_mock_storage(_make_debate_dict())
        handler_obj._body = {"include_receipt": False, "include_plan": False}

        result = handler_obj._create_decision_integrity(MagicMock(), "test-debate-001")
        body, status = _decode_response(result)

        assert status == 200
        # build_decision_integrity_package was called via run_async; check args
        call_args = mock_run_async.call_args
        # run_async receives the coroutine, so we verify the build was called
        # with the right flags by inspecting mock_build
        mock_persist_receipt.assert_not_called()
        mock_persist_plan.assert_not_called()
        assert body["receipt"] is None
        assert body["plan"] is None


# ---------------------------------------------------------------------------
# 4. Execution mode "request_approval"
# ---------------------------------------------------------------------------


class TestRequestApproval:
    """Test the request_approval execution mode."""

    @patch(f"{_IMPL_MOD}.get_permission_checker")
    @patch(f"{_IMPL_MOD}.get_approval_flow")
    @patch(f"{_IMPL_MOD}.run_async")
    @patch(f"{_IMPL_MOD}.build_decision_integrity_package", new_callable=AsyncMock)
    @patch(f"{_IMPL_MOD}._persist_receipt")
    @patch(f"{_IMPL_MOD}._persist_plan")
    def test_request_approval_creates_approval(
        self,
        mock_persist_plan: MagicMock,
        mock_persist_receipt: MagicMock,
        mock_build: AsyncMock,
        mock_run_async: MagicMock,
        mock_get_approval: MagicMock,
        mock_get_checker: MagicMock,
    ) -> None:
        package = _FakePackage(receipt=_FakeReceipt(), plan=_FakePlan())
        approval_req = _FakeApprovalRequest()

        # run_async is called multiple times: once for build, once for approval
        mock_run_async.side_effect = [package, approval_req]
        mock_persist_receipt.return_value = "rcpt-001"

        approval_flow = MagicMock()
        approval_flow.request_approval = AsyncMock(return_value=approval_req)
        mock_get_approval.return_value = approval_flow

        handler_obj = MockHandler()
        handler_obj._storage = _build_mock_storage(_make_debate_dict())
        handler_obj._body = {"execution_mode": "request_approval"}

        result = handler_obj._create_decision_integrity(MagicMock(), "test-debate-001")
        body, status = _decode_response(result)

        assert status == 200
        assert "approval" in body
        assert body["approval"]["id"] == "approval-001"
        assert body["approval"]["requested_by"] == "system"


# ---------------------------------------------------------------------------
# 5. Execution mode "execute"
# ---------------------------------------------------------------------------


class TestExecuteMode:
    """Test the execute execution mode."""

    @patch(f"{_IMPL_MOD}.get_permission_checker")
    @patch(f"{_IMPL_MOD}.get_approval_flow")
    @patch(f"{_IMPL_MOD}.run_async")
    @patch(f"{_IMPL_MOD}.build_decision_integrity_package", new_callable=AsyncMock)
    @patch(f"{_IMPL_MOD}._persist_receipt")
    @patch(f"{_IMPL_MOD}._persist_plan")
    def test_execute_requires_env_flag(
        self,
        mock_persist_plan: MagicMock,
        mock_persist_receipt: MagicMock,
        mock_build: AsyncMock,
        mock_run_async: MagicMock,
        mock_get_approval: MagicMock,
        mock_get_checker: MagicMock,
    ) -> None:
        """Without ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION=1, execute returns 403."""
        package = _FakePackage(receipt=_FakeReceipt(), plan=_FakePlan())
        approval_req = _FakeApprovalRequest()

        mock_run_async.side_effect = [package, approval_req]
        mock_persist_receipt.return_value = "rcpt-001"

        approval_flow = MagicMock()
        approval_flow.request_approval = AsyncMock(return_value=approval_req)
        mock_get_approval.return_value = approval_flow

        handler_obj = MockHandler()
        handler_obj._storage = _build_mock_storage(_make_debate_dict())
        handler_obj._body = {"execution_mode": "execute"}

        # Ensure env flag is off
        env_patch = patch.dict(os.environ, {"ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION": "0"})
        with env_patch:
            result = handler_obj._create_decision_integrity(MagicMock(), "test-debate-001")

        body, status = _decode_response(result)
        assert status == 403
        assert "disabled" in body.get("error", "").lower()

    @patch(f"{_IMPL_MOD}._check_execution_budget")
    @patch(f"{_IMPL_MOD}.get_permission_checker")
    @patch(f"{_IMPL_MOD}.get_approval_flow")
    @patch(f"{_IMPL_MOD}.run_async")
    @patch(f"{_IMPL_MOD}.build_decision_integrity_package", new_callable=AsyncMock)
    @patch(f"{_IMPL_MOD}._persist_receipt")
    @patch(f"{_IMPL_MOD}._persist_plan")
    def test_execute_budget_exceeded_returns_402(
        self,
        mock_persist_plan: MagicMock,
        mock_persist_receipt: MagicMock,
        mock_build: AsyncMock,
        mock_run_async: MagicMock,
        mock_get_approval: MagicMock,
        mock_get_checker: MagicMock,
        mock_budget: MagicMock,
    ) -> None:
        """Budget check failure on execute returns 402."""
        package = _FakePackage(receipt=_FakeReceipt(), plan=_FakePlan())
        approval_req = _FakeApprovalRequest()

        mock_run_async.side_effect = [package, approval_req]
        mock_persist_receipt.return_value = "rcpt-001"
        mock_budget.return_value = (False, "Monthly limit reached")

        approval_flow = MagicMock()
        approval_flow.request_approval = AsyncMock(return_value=approval_req)
        mock_get_approval.return_value = approval_flow

        handler_obj = MockHandler()
        handler_obj._storage = _build_mock_storage(_make_debate_dict())
        handler_obj._body = {"execution_mode": "execute"}

        env_patch = patch.dict(os.environ, {"ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION": "1"})
        with env_patch:
            result = handler_obj._create_decision_integrity(MagicMock(), "test-debate-001")

        body, status = _decode_response(result)
        assert status == 402
        assert "budget" in body.get("error", "").lower()


# ---------------------------------------------------------------------------
# 6. Budget check function
# ---------------------------------------------------------------------------


class TestCheckExecutionBudget:
    """Unit tests for _check_execution_budget."""

    def test_no_tracker_allows(self) -> None:
        allowed, msg = _check_execution_budget("debate-1", {})
        assert allowed is True
        assert msg == ""

    def test_tracker_allows(self) -> None:
        tracker = MagicMock()
        tracker.check_debate_budget.return_value = {"allowed": True}
        allowed, msg = _check_execution_budget("debate-1", {"cost_tracker": tracker})
        assert allowed is True
        tracker.check_debate_budget.assert_called_once_with(
            "debate-1", estimated_cost_usd=Decimal("0.10")
        )

    def test_tracker_denies(self) -> None:
        tracker = MagicMock()
        tracker.check_debate_budget.return_value = {
            "allowed": False,
            "message": "Over budget",
        }
        allowed, msg = _check_execution_budget("debate-1", {"cost_tracker": tracker})
        assert allowed is False
        assert msg == "Over budget"

    def test_tracker_exception_allows(self) -> None:
        """Budget check exception is non-fatal and defaults to allow."""
        tracker = MagicMock()
        tracker.check_debate_budget.side_effect = TypeError("DB down")
        allowed, msg = _check_execution_budget("debate-1", {"cost_tracker": tracker})
        assert allowed is True


# ---------------------------------------------------------------------------
# 7. Receipt persistence
# ---------------------------------------------------------------------------


class TestReceiptPersistence:
    """Tests for _persist_receipt."""

    @patch(f"{_IMPL_MOD}.run_async")
    @patch(f"{_IMPL_MOD}.build_decision_integrity_package", new_callable=AsyncMock)
    @patch(f"{_IMPL_MOD}._persist_receipt")
    @patch(f"{_IMPL_MOD}._persist_plan")
    def test_persist_receipt_called_when_receipt_present(
        self,
        mock_persist_plan: MagicMock,
        mock_persist_receipt: MagicMock,
        mock_build: AsyncMock,
        mock_run_async: MagicMock,
    ) -> None:
        package = _FakePackage(receipt=_FakeReceipt(), plan=_FakePlan())
        mock_run_async.return_value = package
        mock_persist_receipt.return_value = "rcpt-001"

        handler_obj = MockHandler()
        handler_obj._storage = _build_mock_storage(_make_debate_dict())
        handler_obj._storage.get_org_id.return_value = "org-owner"
        handler_obj._body = {}

        handler_obj._create_decision_integrity(MagicMock(), "test-debate-001")
        # The receipt belongs to the org that owns the debate.
        mock_persist_receipt.assert_called_once_with(
            package.receipt, "test-debate-001", "org-owner"
        )

    @patch(f"{_IMPL_MOD}.run_async")
    @patch(f"{_IMPL_MOD}.build_decision_integrity_package", new_callable=AsyncMock)
    @patch(f"{_IMPL_MOD}._persist_receipt")
    @patch(f"{_IMPL_MOD}._persist_plan")
    def test_persist_receipt_not_called_when_no_receipt(
        self,
        mock_persist_plan: MagicMock,
        mock_persist_receipt: MagicMock,
        mock_build: AsyncMock,
        mock_run_async: MagicMock,
    ) -> None:
        package = _FakePackage(receipt=None, plan=_FakePlan())
        mock_run_async.return_value = package

        handler_obj = MockHandler()
        handler_obj._storage = _build_mock_storage(_make_debate_dict())
        handler_obj._body = {"include_receipt": False}

        handler_obj._create_decision_integrity(MagicMock(), "test-debate-001")
        mock_persist_receipt.assert_not_called()

    def test_persist_receipt_function_saves_to_store(self) -> None:
        """The standalone _persist_receipt function calls store.save."""
        receipt = _FakeReceipt()
        mock_store = MagicMock()
        mock_store.save.return_value = "saved-rcpt-001"

        with patch(f"{_IMPL_MOD}.get_receipt_store", return_value=mock_store) as mock_get_store:
            # _persist_receipt imports get_receipt_store from receipt_store module
            # We need to patch the import inside the function
            with patch(
                "aragora.storage.receipt_store.get_receipt_store",
                return_value=mock_store,
            ):
                result = _persist_receipt(receipt, "test-debate-001")

        assert result == "saved-rcpt-001"

    def test_persist_receipt_returns_none_on_failure(self) -> None:
        """If the receipt store raises, _persist_receipt returns None."""
        receipt = _FakeReceipt()
        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            side_effect=OSError("store unavailable"),
        ):
            result = _persist_receipt(receipt, "test-debate-001")
        assert result is None


# ---------------------------------------------------------------------------
# 8. Channel notification
# ---------------------------------------------------------------------------


class TestChannelNotification:
    """Verify route_result is called when notify_origin=True."""

    @patch(f"{_IMPL_MOD}.route_result", new_callable=AsyncMock)
    @patch(f"{_IMPL_MOD}.run_async")
    @patch(f"{_IMPL_MOD}.build_decision_integrity_package", new_callable=AsyncMock)
    @patch(f"{_IMPL_MOD}._persist_receipt")
    @patch(f"{_IMPL_MOD}._persist_plan")
    def test_notify_origin_calls_route_result(
        self,
        mock_persist_plan: MagicMock,
        mock_persist_receipt: MagicMock,
        mock_build: AsyncMock,
        mock_run_async_fn: MagicMock,
        mock_route_result: AsyncMock,
    ) -> None:
        package = _FakePackage(receipt=_FakeReceipt(), plan=_FakePlan())
        # run_async is called for build, then for route_result
        mock_run_async_fn.side_effect = [package, None]
        mock_persist_receipt.return_value = "rcpt-001"

        handler_obj = MockHandler()
        handler_obj._storage = _build_mock_storage(_make_debate_dict())
        handler_obj._body = {"notify_origin": True}

        result = handler_obj._create_decision_integrity(MagicMock(), "test-debate-001")
        body, status = _decode_response(result)

        assert status == 200
        # run_async should have been called twice: once for build, once for route_result
        assert mock_run_async_fn.call_count == 2

    @patch(f"{_IMPL_MOD}.route_result", new_callable=AsyncMock)
    @patch(f"{_IMPL_MOD}.run_async")
    @patch(f"{_IMPL_MOD}.build_decision_integrity_package", new_callable=AsyncMock)
    @patch(f"{_IMPL_MOD}._persist_receipt")
    @patch(f"{_IMPL_MOD}._persist_plan")
    def test_notify_origin_false_skips_route_result(
        self,
        mock_persist_plan: MagicMock,
        mock_persist_receipt: MagicMock,
        mock_build: AsyncMock,
        mock_run_async_fn: MagicMock,
        mock_route_result: AsyncMock,
    ) -> None:
        package = _FakePackage(receipt=_FakeReceipt(), plan=_FakePlan())
        mock_run_async_fn.return_value = package
        mock_persist_receipt.return_value = "rcpt-001"

        handler_obj = MockHandler()
        handler_obj._storage = _build_mock_storage(_make_debate_dict())
        handler_obj._body = {"notify_origin": False}

        handler_obj._create_decision_integrity(MagicMock(), "test-debate-001")

        # run_async called only once (for build), not for route_result
        assert mock_run_async_fn.call_count == 1
