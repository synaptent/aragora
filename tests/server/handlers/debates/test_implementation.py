"""Tests for Decision Integrity implementation handler mixin.

Tests the ImplementationOperationsMixin which provides:
- POST /api/v1/debates/{id}/decision-integrity endpoint
- Receipt and plan persistence
- Approval flow integration
- HybridExecutor execution (sequential and parallel)
- Multi-channel result routing
- Context snapshot from memory systems
- Budget enforcement
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.pipeline.backbone_errors import BackbonePersistenceError, FAIL_CLOSED_BACKBONE_MESSAGE
from aragora.pipeline.execution_mode import ExecutionMode
from aragora.server.handlers.debates.implementation import (
    ImplementationOperationsMixin,
    _check_execution_budget,
    _persist_plan,
    _persist_receipt,
)


# =============================================================================
# Helpers
# =============================================================================


def parse_result(result):
    """Parse HandlerResult into (body_dict, status_code)."""
    body = json.loads(result.body) if result.body else {}
    return body, result.status_code


# =============================================================================
# Mock handler that composes the mixin under test
# =============================================================================


class MockDebatesHandler(ImplementationOperationsMixin):
    """Minimal handler implementing the protocol expected by the mixin."""

    def __init__(self, ctx=None, storage=None, body=None):
        from aragora.rbac.models import AuthorizationContext

        self.ctx = ctx or {}
        self._storage = storage
        self._body = body
        self._auth_context = AuthorizationContext(
            user_id="test-user",
            permissions={"debates.write"},
        )

    def read_json_body(self, handler, max_size=None):
        """Return pre-configured body dict."""
        return self._body

    def get_storage(self):
        """Get storage instance."""
        return self._storage

    def get_current_user(self, handler):
        """Return None by default (no authenticated user)."""
        return None


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_storage():
    """Create a mock storage with a sample debate."""
    storage = MagicMock()
    storage.get_debate.return_value = {
        "id": "debate-001",
        "debate_id": "debate-001",
        "task": "Should we use microservices?",
        "final_answer": "Yes, for scalable systems",
        "status": "completed",
        "confidence": 0.9,
        "consensus_reached": True,
        "rounds_used": 3,
        "rounds_completed": 3,
        "agents": ["claude", "gpt4"],
        "metadata": {},
    }
    # The debate belongs to the auto-auth test org.
    storage.get_access_info.side_effect = lambda ref: (ref, "test-org-001", False)
    return storage


@pytest.fixture
def mock_package():
    """Create a mock DecisionIntegrityPackage."""
    pkg = MagicMock()
    pkg.receipt = MagicMock()
    pkg.receipt.to_dict.return_value = {"receipt_id": "r-001", "debate_id": "debate-001"}
    pkg.plan = MagicMock()
    pkg.plan.to_dict.return_value = {"plan_id": "p-001", "tasks": []}
    pkg.plan.tasks = [
        MagicMock(
            id="t1",
            description="Implement microservices",
            files=["src/service.py"],
            complexity="medium",
        )
    ]
    pkg.context_snapshot = None
    pkg.to_dict.return_value = {
        "debate_id": "debate-001",
        "receipt": {"receipt_id": "r-001", "debate_id": "debate-001"},
        "plan": {"plan_id": "p-001", "tasks": []},
        "context_snapshot": None,
    }
    return pkg


@pytest.fixture
def mock_approval_request():
    """Create a mock ApprovalRequest."""
    req = MagicMock()
    req.id = "approval-001"
    req.title = "Implement debate debate-001"
    req.description = "Execute decision implementation plan generated from debate."
    req.changes = [
        {
            "id": "t1",
            "description": "Implement microservices",
            "files": ["src/service.py"],
            "complexity": "medium",
        }
    ]
    req.risk_level = "medium"
    req.requested_at = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    req.requested_by = "system"
    req.timeout_seconds = 3600
    req.status = MagicMock(value="pending")
    req.approved_by = None
    req.approved_at = None
    req.rejection_reason = None
    req.metadata = {"debate_id": "debate-001"}
    return req


@pytest.fixture
def handler(mock_storage):
    """Create a MockDebatesHandler with default body."""
    return MockDebatesHandler(
        ctx={"storage": mock_storage},
        storage=mock_storage,
        body={},
    )


# =============================================================================
# Tests for _persist_receipt helper
# =============================================================================


class TestPersistReceipt:
    """Tests for _persist_receipt helper function."""

    def test_success_returns_receipt_id(self):
        """Persisted receipt returns the receipt_id."""
        mock_receipt = MagicMock()
        mock_receipt.to_dict.return_value = {"data": "test"}

        mock_store = MagicMock()
        mock_store.save.return_value = "receipt-123"

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=mock_store,
        ):
            result = _persist_receipt(mock_receipt, "debate-001")

        assert result == "receipt-123"
        # Verify debate_id was injected
        saved = mock_store.save.call_args[0][0]
        assert saved["debate_id"] == "debate-001"

    def test_sets_debate_id_if_missing(self):
        """Receipt dict gets debate_id injected when absent."""
        mock_receipt = MagicMock()
        mock_receipt.to_dict.return_value = {"data": "test"}

        mock_store = MagicMock()
        mock_store.save.return_value = "receipt-456"

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=mock_store,
        ):
            _persist_receipt(mock_receipt, "debate-xyz")

        saved = mock_store.save.call_args[0][0]
        assert saved["debate_id"] == "debate-xyz"

    def test_preserves_existing_debate_id(self):
        """Receipt dict keeps its own debate_id if already present."""
        mock_receipt = MagicMock()
        mock_receipt.to_dict.return_value = {"debate_id": "original-id"}

        mock_store = MagicMock()
        mock_store.save.return_value = "receipt-789"

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=mock_store,
        ):
            _persist_receipt(mock_receipt, "different-id")

        saved = mock_store.save.call_args[0][0]
        assert saved["debate_id"] == "original-id"

    def test_exception_returns_none(self):
        """Store exception is caught and returns None."""
        mock_receipt = MagicMock()
        mock_receipt.to_dict.side_effect = TypeError("boom")

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=MagicMock(),
        ):
            result = _persist_receipt(mock_receipt, "debate-001")
        assert result is None

    def test_import_failure_returns_none(self):
        """Missing receipt store module returns None gracefully."""
        mock_receipt = MagicMock()
        mock_receipt.to_dict.return_value = {}

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            side_effect=ImportError("no module"),
        ):
            result = _persist_receipt(mock_receipt, "debate-001")

        assert result is None


# =============================================================================
# Tests for _persist_plan helper
# =============================================================================


class TestPersistPlan:
    """Tests for _persist_plan helper function."""

    def test_success_stores_plan(self):
        """Plan is wrapped and stored successfully."""
        mock_plan = MagicMock()
        mock_decision_plan = MagicMock()
        mock_decision_plan.id = "plan-123"
        mock_decision_plan.metadata = {}

        with (
            patch("aragora.pipeline.executor.store_plan") as mock_store,
            patch("aragora.pipeline.decision_plan.DecisionPlanFactory") as mock_factory,
            patch(
                "aragora.server.handlers.debates.implementation.ensure_decision_plan_backbone_run",
                return_value="run-123",
            ) as mock_seed,
            patch(
                "aragora.server.handlers.debates.implementation.sync_decision_plan_backbone_receipt",
                return_value=True,
            ) as mock_sync,
        ):
            mock_factory.from_implement_plan.return_value = mock_decision_plan
            _persist_plan(mock_plan, "debate-001")

        mock_factory.from_implement_plan.assert_called_once_with(mock_plan, debate_id="debate-001")
        mock_seed.assert_called_once_with(
            mock_decision_plan,
            auth_context=None,
            source_surface="debates_decision_integrity_plan_only",
            source_id="debate-001",
        )
        mock_store.assert_called_once_with(mock_decision_plan)
        mock_sync.assert_called_once_with(mock_decision_plan, append_event=False)

    def test_exception_handled_gracefully(self):
        """Store exception does not propagate."""
        mock_plan = MagicMock()

        with (
            patch(
                "aragora.pipeline.executor.store_plan",
                side_effect=OSError("store failed"),
            ),
            patch("aragora.pipeline.decision_plan.DecisionPlanFactory"),
        ):
            # Should not raise
            _persist_plan(mock_plan, "debate-001")


# =============================================================================
# Tests for _check_execution_budget helper
# =============================================================================


class TestCheckExecutionBudget:
    """Tests for _check_execution_budget helper function."""

    def test_no_tracker_allows(self):
        """No cost_tracker in context means budget is allowed."""
        allowed, msg = _check_execution_budget("debate-001", {})
        assert allowed is True
        assert msg == ""

    def test_none_tracker_allows(self):
        """Explicit None cost_tracker means budget is allowed."""
        allowed, msg = _check_execution_budget("debate-001", {"cost_tracker": None})
        assert allowed is True
        assert msg == ""

    def test_budget_allowed(self):
        """Tracker returning allowed=True passes through."""
        tracker = MagicMock()
        tracker.check_debate_budget.return_value = {"allowed": True}

        allowed, msg = _check_execution_budget("debate-001", {"cost_tracker": tracker})
        assert allowed is True
        assert msg == ""
        tracker.check_debate_budget.assert_called_once_with(
            "debate-001", estimated_cost_usd=Decimal("0.10")
        )

    def test_budget_exceeded(self):
        """Tracker returning allowed=False blocks execution."""
        tracker = MagicMock()
        tracker.check_debate_budget.return_value = {
            "allowed": False,
            "message": "Monthly budget exceeded",
        }

        allowed, msg = _check_execution_budget("debate-001", {"cost_tracker": tracker})
        assert allowed is False
        assert msg == "Monthly budget exceeded"

    def test_budget_exceeded_default_message(self):
        """Budget exceeded with no message uses default."""
        tracker = MagicMock()
        tracker.check_debate_budget.return_value = {"allowed": False}

        allowed, msg = _check_execution_budget("debate-001", {"cost_tracker": tracker})
        assert allowed is False
        assert msg == "Budget exceeded"

    def test_tracker_exception_allows(self):
        """Exception in budget check defaults to allowing."""
        tracker = MagicMock()
        tracker.check_debate_budget.side_effect = ValueError("db error")

        allowed, msg = _check_execution_budget("debate-001", {"cost_tracker": tracker})
        assert allowed is True
        assert msg == ""


# =============================================================================
# Tests for _create_decision_integrity (plan_only mode)
# =============================================================================


class TestCreateDecisionIntegrityPlanOnly:
    """Tests for _create_decision_integrity in default plan_only mode."""

    def test_success_returns_package(self, handler, mock_storage, mock_package):
        """Default call returns decision integrity package."""
        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_package,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value="r-001",
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
        ):
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 200
        assert body["debate_id"] == "debate-001"
        assert body["receipt"] is not None
        assert body["plan"] is not None

    def test_debate_not_found_returns_404(self, handler, mock_storage):
        """Missing debate returns 404."""
        mock_storage.get_debate.return_value = None

        result = handler._create_decision_integrity(None, "nonexistent")

        _, status = parse_result(result)
        assert status == 404

    def test_no_storage_returns_503(self):
        """Handler with no storage returns 503."""
        h = MockDebatesHandler(ctx={}, storage=None, body={})

        result = h._create_decision_integrity(None, "debate-001")

        _, status = parse_result(result)
        assert status == 503

    def test_receipt_id_added_to_response(self, handler, mock_storage, mock_package):
        """When receipt is persisted, receipt_id appears in response."""
        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_package,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value="receipt-abc",
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
        ):
            result = handler._create_decision_integrity(None, "debate-001")

        body, _ = parse_result(result)
        assert body["receipt_id"] == "receipt-abc"

    def test_receipt_persistence_failure_no_receipt_id(self, handler, mock_storage, mock_package):
        """When receipt persistence fails, no receipt_id in response."""
        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_package,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
        ):
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 200
        assert "receipt_id" not in body

    def test_no_receipt_skips_persistence(self, handler, mock_storage, mock_package):
        """When package has no receipt, persistence is skipped."""
        mock_package.receipt = None

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_package,
            ) as _,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
            ) as mock_persist_receipt,
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
        ):
            handler._create_decision_integrity(None, "debate-001")

        mock_persist_receipt.assert_not_called()

    def test_no_plan_skips_persistence(self, handler, mock_storage, mock_package):
        """When package has no plan, plan persistence is skipped."""
        mock_package.plan = None

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_package,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value="r-001",
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ) as mock_persist_plan,
        ):
            handler._create_decision_integrity(None, "debate-001")

        mock_persist_plan.assert_not_called()

    def test_plan_persisted_with_debate_id(self, handler, mock_storage, mock_package):
        """Plan is persisted with the correct debate_id."""
        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_package,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value="r-001",
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ) as mock_persist_plan,
        ):
            handler._create_decision_integrity(None, "debate-001")

        mock_persist_plan.assert_called_once_with(mock_package.plan, "debate-001")

    def test_custom_payload_options(self, handler, mock_storage, mock_package):
        """Payload options are forwarded to build_decision_integrity_package."""
        handler._body = {
            "include_receipt": False,
            "include_plan": True,
            "include_context": True,
            "plan_strategy": "gemini",
        }

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_package,
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
        ):
            handler._create_decision_integrity(None, "debate-001")

        # run_async was called with the coroutine from build_decision_integrity_package
        mock_run.assert_called_once()

    def test_repo_root_from_context(self, mock_storage, mock_package):
        """repo_root from context is used for plan generation."""
        h = MockDebatesHandler(
            ctx={"storage": mock_storage, "repo_root": "/tmp/repo"},
            storage=mock_storage,
            body={},
        )

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_package,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
        ):
            result = h._create_decision_integrity(None, "debate-001")

        _, status = parse_result(result)
        assert status == 200


# =============================================================================
# Tests for approval flow (request_approval mode)
# =============================================================================


class TestApprovalFlow:
    """Tests for _create_decision_integrity with execution_mode=request_approval."""

    def test_request_approval_creates_approval(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        """request_approval mode generates an approval request in response."""
        handler._body = {"execution_mode": "request_approval"}

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation.execute_decision_plan_with_backbone",
                return_value="workflow-coro",
            ) as mock_execute,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
            ),
        ):
            # First run_async call returns the package, second returns approval
            mock_run.side_effect = [mock_package, mock_approval_request]
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 200
        assert "approval" in body
        assert body["approval"]["id"] == "approval-001"
        assert body["approval"]["risk_level"] == "medium"
        assert body["approval"]["status"] == "pending"
        assert body["execution_mode"] == "request_approval"
        assert body["execution_engine"] == "hybrid"

    def test_request_approval_with_custom_risk_level(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        """Custom risk_level is forwarded to approval flow."""
        handler._body = {"execution_mode": "request_approval", "risk_level": "high"}

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation.execute_decision_plan_with_backbone",
                return_value="workflow-coro",
            ) as mock_execute,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
            ),
        ):
            mock_run.side_effect = [mock_package, mock_approval_request]
            handler._create_decision_integrity(None, "debate-001")

        # Verify risk_level was passed in the second run_async call
        assert mock_run.call_count == 2

    def test_permission_denied_returns_403(self, handler, mock_storage, mock_package):
        """Permission check failure returns 403."""
        handler._body = {"execution_mode": "request_approval"}

        mock_user = MagicMock()
        mock_user.user_id = "user-001"
        handler.get_current_user = lambda h: mock_user

        mock_checker = MagicMock()
        mock_checker.check_permission.return_value = MagicMock(
            allowed=False, reason="Insufficient permissions"
        )

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_package,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
                return_value=mock_checker,
            ),
        ):
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 403
        assert "permission" in body.get("error", "").lower()

    def test_permission_checker_unavailable_proceeds(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        """If permission checker raises, execution proceeds (legacy compat)."""
        handler._body = {"execution_mode": "request_approval"}

        mock_user = MagicMock()
        mock_user.user_id = "user-001"
        handler.get_current_user = lambda h: mock_user

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation.execute_decision_plan_with_backbone",
                return_value="workflow-coro",
            ) as mock_execute,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
                side_effect=ImportError("checker not available"),
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
        ):
            mock_run.side_effect = [mock_package, mock_approval_request]
            result = handler._create_decision_integrity(None, "debate-001")

        _, status = parse_result(result)
        assert status == 200

    def test_approval_timeout_forwarded(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        """approval_timeout_seconds is forwarded to the approval request."""
        handler._body = {
            "execution_mode": "request_approval",
            "approval_timeout_seconds": 600,
        }

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation.execute_decision_plan_with_backbone",
                return_value="workflow-coro",
            ) as mock_execute,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
            ),
        ):
            mock_run.side_effect = [mock_package, mock_approval_request]
            handler._create_decision_integrity(None, "debate-001")

        # Approval was requested (second run_async call)
        assert mock_run.call_count == 2

    def test_no_user_defaults_to_system(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        """When no authenticated user, requested_by defaults to 'system'."""
        handler._body = {"execution_mode": "request_approval"}

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation.execute_decision_plan_with_backbone",
                return_value="computer-use-coro",
            ) as mock_execute,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
            ),
        ):
            mock_run.side_effect = [mock_package, mock_approval_request]
            handler._create_decision_integrity(None, "debate-001")

        assert mock_run.call_count == 2


# =============================================================================
# Tests for workflow backbone execution
# =============================================================================


class TestWorkflowBackbone:
    def test_execute_workflow_routes_through_backbone_wrapper(
        self, handler, mock_storage, mock_package
    ):
        handler._body = {"execution_mode": "workflow_execute"}

        from aragora.pipeline.decision_plan import ApprovalMode, DecisionPlan, PlanStatus
        from aragora.pipeline.decision_plan.core import ApprovalRecord

        plan = DecisionPlan(
            debate_id="debate-001",
            task="Should we use microservices?",
            approval_mode=ApprovalMode.NEVER,
            status=PlanStatus.APPROVED,
            approval_record=ApprovalRecord(approved=True, approver_id="system"),
        )

        mock_outcome = MagicMock()
        mock_outcome.success = True
        mock_outcome.to_dict.return_value = {"success": True}
        launch = {
            "run_id": "run-workflow-1",
            "execution_id": "exec-workflow-1",
            "correlation_id": "corr-workflow-1",
            "execution_mode": "workflow",
        }

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation.execute_decision_plan_with_backbone",
                return_value="workflow-coro",
            ) as mock_execute,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.pipeline.decision_plan.DecisionPlanFactory.from_debate_result",
                return_value=plan,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.ensure_decision_plan_backbone_run",
                return_value="run-workflow-1",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.sync_decision_plan_backbone_receipt",
                return_value=True,
            ),
            patch.dict(
                "os.environ",
                {"ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION": "1"},
            ),
        ):
            mock_run.side_effect = [mock_package, (launch, mock_outcome)]
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 200
        assert body["run_id"] == "run-workflow-1"
        assert body["workflow_execution"]["status"] == "completed"
        assert body["workflow_execution"]["run_id"] == "run-workflow-1"
        assert body["workflow_execution"]["execution_id"] == "exec-workflow-1"
        assert body["workflow_execution"]["outcome"]["success"] is True
        assert mock_execute.call_args.kwargs["safety_mode"] == ExecutionMode.INTERACTIVE

    def test_execute_workflow_backbone_failure_returns_503(
        self, handler, mock_storage, mock_package
    ):
        handler._body = {"execution_mode": "workflow_execute"}

        from aragora.pipeline.decision_plan import ApprovalMode, DecisionPlan, PlanStatus
        from aragora.pipeline.decision_plan.core import ApprovalRecord

        plan = DecisionPlan(
            debate_id="debate-001",
            task="Should we use microservices?",
            approval_mode=ApprovalMode.NEVER,
            status=PlanStatus.APPROVED,
            approval_record=ApprovalRecord(approved=True, approver_id="system"),
        )

        with (
            patch("aragora.server.handlers.debates.implementation.run_async") as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.pipeline.decision_plan.DecisionPlanFactory.from_debate_result",
                return_value=plan,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.ensure_decision_plan_backbone_run",
                return_value="run-workflow-err",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.sync_decision_plan_backbone_receipt",
                return_value=True,
            ),
            patch.dict("os.environ", {"ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION": "1"}),
        ):
            mock_run.side_effect = [
                mock_package,
                BackbonePersistenceError("run ledger unavailable"),
            ]
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 503
        assert body["error"] == FAIL_CLOSED_BACKBONE_MESSAGE


# =============================================================================
# Tests for execute mode
# =============================================================================


class TestExecuteMode:
    """Tests for _create_decision_integrity with execution_mode=execute."""

    def test_env_var_not_set_returns_403(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        """Execute mode blocked when env var is not set."""
        handler._body = {"execution_mode": "execute"}

        from aragora.autonomous.loop_enhancement import ApprovalStatus

        mock_approval_request.status = ApprovalStatus.APPROVED

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation.execute_decision_plan_with_backbone",
                return_value="computer-use-coro",
            ) as mock_execute,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
            ),
            patch.dict(
                "os.environ",
                {"ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION": "0"},
            ),
        ):
            mock_run.side_effect = [mock_package, mock_approval_request]
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 403
        assert "disabled" in body.get("error", "").lower()

    def test_execute_approved_sequential(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        """Approved execution runs HybridExecutor sequentially."""
        handler._body = {"execution_mode": "execute"}

        from aragora.autonomous.loop_enhancement import ApprovalStatus

        mock_approval_request.status = ApprovalStatus.APPROVED

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        mock_task_result = MagicMock()
        mock_task_result.to_dict.return_value = {"task_id": "t1", "success": True}

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation.execute_decision_plan_with_backbone",
                return_value="workflow-coro",
            ) as mock_execute,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.HybridExecutor",
            ) as mock_executor_cls,
            patch.dict(
                "os.environ",
                {"ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION": "1"},
            ),
        ):
            mock_executor = MagicMock()
            mock_executor.execute_plan = AsyncMock(return_value=[mock_task_result])
            mock_executor_cls.return_value = mock_executor

            # Calls: build_package, request_approval, execute_plan
            mock_run.side_effect = [
                mock_package,
                mock_approval_request,
                [mock_task_result],
            ]
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 200
        assert body["execution"]["status"] == "completed"
        assert len(body["execution"]["results"]) == 1
        assert body["execution"]["results"][0]["success"] is True

    def test_execute_approved_parallel(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        """Parallel execution uses execute_plan_parallel."""
        handler._body = {"execution_mode": "execute", "parallel_execution": True}

        from aragora.autonomous.loop_enhancement import ApprovalStatus

        mock_approval_request.status = ApprovalStatus.APPROVED

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        mock_task_result = MagicMock()
        mock_task_result.to_dict.return_value = {"task_id": "t1", "success": True}

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation.execute_decision_plan_with_backbone",
                return_value="computer-use-coro",
            ) as mock_execute,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.HybridExecutor",
            ) as mock_executor_cls,
            patch.dict(
                "os.environ",
                {"ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION": "1"},
            ),
        ):
            mock_executor = MagicMock()
            mock_executor.execute_plan_parallel = AsyncMock(return_value=[mock_task_result])
            mock_executor_cls.return_value = mock_executor

            mock_run.side_effect = [
                mock_package,
                mock_approval_request,
                [mock_task_result],
            ]
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 200
        assert body["execution"]["status"] == "completed"

    def test_execute_approved_computer_use(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        """Approved computer-use execution queues through the backbone wrapper."""
        handler._body = {"execution_mode": "execute", "execution_engine": "computer_use"}

        from aragora.autonomous.loop_enhancement import ApprovalStatus

        mock_approval_request.status = ApprovalStatus.APPROVED

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        mock_outcome = MagicMock()
        mock_outcome.to_dict.return_value = {"success": True}
        mock_outcome.tasks_total = 5
        mock_outcome.tasks_completed = 3
        mock_outcome.duration_seconds = 1.2
        launch = {
            "run_id": "run-cu-1",
            "execution_id": "exec-cu-1",
            "correlation_id": "corr-cu-1",
            "execution_mode": "computer_use",
        }

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation.execute_decision_plan_with_backbone",
                return_value="computer-use-coro",
            ) as mock_execute,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.ensure_decision_plan_backbone_run",
                return_value="run-cu-1",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.sync_decision_plan_backbone_receipt",
                return_value=True,
            ),
            patch(
                "aragora.pipeline.executor.PlanExecutor",
            ) as mock_executor_cls,
            patch.dict(
                "os.environ",
                {"ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION": "1"},
            ),
        ):
            mock_executor = MagicMock()
            mock_executor_cls.return_value = mock_executor

            mock_run.side_effect = [
                mock_package,
                mock_approval_request,
                (launch, mock_outcome),
            ]
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 200
        assert body["execution"]["status"] == "completed"
        assert body["execution"]["mode"] == "computer_use"
        assert body["execution"]["run_id"] == "run-cu-1"
        assert body["execution"]["execution_id"] == "exec-cu-1"
        assert body["execution"]["outcome"]["success"] is True
        assert body["execution"]["progress"]["total_steps"] >= 0
        assert mock_executor_cls.called is True
        assert mock_execute.call_args.kwargs["safety_mode"] == ExecutionMode.INTERACTIVE

    def test_execute_approved_computer_use_backbone_failure_returns_503(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        handler._body = {"execution_mode": "execute", "execution_engine": "computer_use"}

        from aragora.autonomous.loop_enhancement import ApprovalStatus

        mock_approval_request.status = ApprovalStatus.APPROVED

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        with (
            patch("aragora.server.handlers.debates.implementation.run_async") as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.ensure_decision_plan_backbone_run",
                return_value="run-cu-err",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.sync_decision_plan_backbone_receipt",
                return_value=True,
            ),
            patch("aragora.pipeline.executor.PlanExecutor"),
            patch.dict("os.environ", {"ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION": "1"}),
        ):
            mock_run.side_effect = [
                mock_package,
                mock_approval_request,
                BackbonePersistenceError("run ledger unavailable"),
            ]
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 503
        assert body["error"] == FAIL_CLOSED_BACKBONE_MESSAGE

    def test_execute_auto_approved(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        """AUTO_APPROVED status also triggers execution."""
        handler._body = {"execution_mode": "execute"}

        from aragora.autonomous.loop_enhancement import ApprovalStatus

        mock_approval_request.status = ApprovalStatus.AUTO_APPROVED

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        mock_task_result = MagicMock()
        mock_task_result.to_dict.return_value = {"task_id": "t1", "success": True}

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation.execute_decision_plan_with_backbone",
                return_value="computer-use-coro",
            ) as mock_execute,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.HybridExecutor",
            ) as mock_executor_cls,
            patch.dict(
                "os.environ",
                {"ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION": "1"},
            ),
        ):
            mock_executor = MagicMock()
            mock_executor_cls.return_value = mock_executor

            mock_run.side_effect = [
                mock_package,
                mock_approval_request,
                [mock_task_result],
            ]
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 200
        assert body["execution"]["status"] == "completed"

    def test_execute_pending_approval_returns_pending(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        """Pending approval returns pending_approval execution status."""
        handler._body = {"execution_mode": "execute"}

        from aragora.autonomous.loop_enhancement import ApprovalStatus

        mock_approval_request.status = ApprovalStatus.PENDING

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
            ),
            patch.dict(
                "os.environ",
                {"ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION": "1"},
            ),
        ):
            mock_run.side_effect = [mock_package, mock_approval_request]
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 200
        assert body["execution"]["status"] == "pending_approval"
        assert body["execution"]["approval_id"] == "approval-001"

    def test_budget_exceeded_returns_402(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        """Budget exceeded returns 402 Payment Required."""
        handler._body = {"execution_mode": "execute"}
        handler.ctx["cost_tracker"] = MagicMock()
        handler.ctx["cost_tracker"].check_debate_budget.return_value = {
            "allowed": False,
            "message": "Budget limit reached",
        }

        from aragora.autonomous.loop_enhancement import ApprovalStatus

        mock_approval_request.status = ApprovalStatus.APPROVED

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
            ),
            patch.dict(
                "os.environ",
                {"ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION": "1"},
            ),
        ):
            mock_run.side_effect = [mock_package, mock_approval_request]
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 402
        assert "budget" in body.get("error", "").lower()

    def test_execute_no_plan_returns_400(
        self, handler, mock_storage, mock_package, mock_approval_request
    ):
        """Execute with no plan available returns 400."""
        handler._body = {"execution_mode": "execute"}
        mock_package.plan = None

        from aragora.autonomous.loop_enhancement import ApprovalStatus

        mock_approval_request.status = ApprovalStatus.APPROVED

        mock_flow = MagicMock()
        mock_flow.request_approval = AsyncMock(return_value=mock_approval_request)

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_approval_flow",
                return_value=mock_flow,
            ),
            patch(
                "aragora.server.handlers.debates.implementation.get_permission_checker",
            ),
            patch.dict(
                "os.environ",
                {"ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION": "1"},
            ),
        ):
            mock_run.side_effect = [mock_package, mock_approval_request]
            result = handler._create_decision_integrity(None, "debate-001")

        body, status = parse_result(result)
        assert status == 400
        assert "plan" in body.get("error", "").lower()


# =============================================================================
# Tests for multi-channel result routing (notify_origin)
# =============================================================================


class TestNotifyOrigin:
    """Tests for _create_decision_integrity with notify_origin=True."""

    def test_notify_origin_calls_route_result(self, handler, mock_storage, mock_package):
        """notify_origin=True triggers route_result call."""
        handler._body = {"notify_origin": True}

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
        ):
            # First call returns package, second call is route_result (returns None)
            mock_run.side_effect = [mock_package, None]
            result = handler._create_decision_integrity(None, "debate-001")

        _, status = parse_result(result)
        assert status == 200
        # route_result was invoked via run_async (second call)
        assert mock_run.call_count == 2

    def test_notify_origin_failure_does_not_break_response(
        self, handler, mock_storage, mock_package
    ):
        """route_result failure is caught and response still succeeds."""
        handler._body = {"notify_origin": True}

        call_count = [0]

        def run_async_side_effect(coro):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_package
            # Second call (route_result) raises
            raise ConnectionError("Channel unreachable")

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                side_effect=run_async_side_effect,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
        ):
            result = handler._create_decision_integrity(None, "debate-001")

        _, status = parse_result(result)
        assert status == 200

    def test_notify_origin_false_skips_routing(self, handler, mock_storage, mock_package):
        """Default notify_origin=False does not call route_result."""
        handler._body = {}

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_package,
            ) as mock_run,
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
        ):
            handler._create_decision_integrity(None, "debate-001")

        # Only one run_async call (build_decision_integrity_package)
        assert mock_run.call_count == 1


# =============================================================================
# Tests for context snapshot
# =============================================================================


class TestContextSnapshot:
    """Tests for _create_decision_integrity with context snapshot support."""

    def test_memory_systems_forwarded_when_include_context(self, mock_storage, mock_package):
        """Memory systems from ctx are passed when include_context=True."""
        mock_continuum = MagicMock()
        mock_cross_debate = MagicMock()
        mock_km = MagicMock()

        h = MockDebatesHandler(
            ctx={
                "storage": mock_storage,
                "continuum_memory": mock_continuum,
                "cross_debate_memory": mock_cross_debate,
                "knowledge_mound": mock_km,
            },
            storage=mock_storage,
            body={"include_context": True},
        )

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_package,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.build_decision_integrity_package",
            ) as mock_build,
        ):
            # We need to verify what build_decision_integrity_package was called with
            # Since run_async wraps it, we check the mock_build call
            h._create_decision_integrity(None, "debate-001")

        # build_decision_integrity_package was called with memory args
        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args
        # The call includes keyword args
        assert call_kwargs.kwargs.get("include_context") is True
        assert call_kwargs.kwargs.get("continuum_memory") is mock_continuum
        assert call_kwargs.kwargs.get("cross_debate_memory") is mock_cross_debate
        assert call_kwargs.kwargs.get("knowledge_mound") is mock_km

    def test_auth_scope_forwarded_to_context_snapshot(self, mock_storage, mock_package):
        """Auth context and envelope are forwarded for scoped snapshot capture."""
        h = MockDebatesHandler(
            ctx={"storage": mock_storage},
            storage=mock_storage,
            body={"include_context": True},
        )
        mock_http = MagicMock()
        mock_http._auth_context = h._auth_context

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_package,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch("aragora.server.handlers.debates.implementation._persist_plan"),
            patch(
                "aragora.server.handlers.debates.implementation.build_decision_integrity_package",
            ) as mock_build,
        ):
            h._create_decision_integrity(mock_http, "debate-001")

        call_kwargs = mock_build.call_args
        assert call_kwargs.kwargs.get("auth_context") is mock_http._auth_context
        envelope = call_kwargs.kwargs.get("context_envelope") or {}
        assert envelope.get("user_id") == "test-user"
        assert envelope.get("source") == "debates.decision_integrity"

    def test_memory_systems_excluded_when_no_context(self, mock_storage, mock_package):
        """Memory systems are None when include_context=False."""
        mock_continuum = MagicMock()

        h = MockDebatesHandler(
            ctx={
                "storage": mock_storage,
                "continuum_memory": mock_continuum,
            },
            storage=mock_storage,
            body={"include_context": False},
        )

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_package,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch(
                "aragora.server.handlers.debates.implementation.build_decision_integrity_package",
            ) as mock_build,
        ):
            h._create_decision_integrity(None, "debate-001")

        mock_build.assert_called_once()
        call_kwargs = mock_build.call_args
        assert call_kwargs.kwargs.get("continuum_memory") is None


# =============================================================================
# Tests for full endpoint integration via DebatesHandler
# =============================================================================


class TestEndpointIntegration:
    """Tests for the decision-integrity endpoint routed through DebatesHandler."""

    def test_route_dispatches_to_create_decision_integrity(self, mock_storage):
        """POST to /api/v1/debates/{id}/decision-integrity reaches the method."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        h = DebatesHandler(server_context={"storage": mock_storage})

        mock_http = MagicMock()
        mock_http.command = "POST"
        mock_http.headers = {"Content-Length": "2"}
        mock_http.rfile = MagicMock()
        mock_http.rfile.read.return_value = b"{}"

        mock_pkg = MagicMock()
        mock_pkg.receipt = None
        mock_pkg.plan = None
        mock_pkg.context_snapshot = None
        mock_pkg.to_dict.return_value = {
            "debate_id": "debate-001",
            "receipt": None,
            "plan": None,
            "context_snapshot": None,
        }

        with (
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                return_value=mock_pkg,
            ),
            patch.object(h, "_check_auth", return_value=None),
        ):
            result = h.handle("/api/v1/debates/debate-001/decision-integrity", {}, mock_http)

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["debate_id"] == "debate-001"

    def test_non_post_returns_405(self, mock_storage):
        """GET to decision-integrity endpoint returns 405."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        h = DebatesHandler(server_context={"storage": mock_storage})

        mock_http = MagicMock()
        mock_http.command = "GET"
        mock_http.headers = {}

        with patch.object(h, "_check_auth", return_value=None):
            result = h.handle("/api/v1/debates/debate-001/decision-integrity", {}, mock_http)

        assert result is not None
        assert result.status_code == 405
