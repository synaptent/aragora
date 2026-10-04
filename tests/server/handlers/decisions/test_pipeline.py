"""Tests for decision pipeline handler validation and RBAC dispatch."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aragora.pipeline.backbone_errors import BackbonePersistenceError, FAIL_CLOSED_BACKBONE_MESSAGE
from aragora.pipeline.decision_plan import DecisionPlan, PlanStatus
from aragora.pipeline.execution_mode import ExecutionMode
from aragora.server.handlers.base import error_response
from aragora.server.handlers.decisions.pipeline import (
    DECISION_CREATE_PERMISSION,
    DECISION_UPDATE_PERMISSION,
    DecisionPipelineHandler,
)
from aragora.tenancy.record_scope import OrgScope

SCOPE = OrgScope(org_id="test-org-001", user_id="test-user-001", role="admin")


def _make_http_handler(body: dict) -> MagicMock:
    """Create a mock HTTP handler with a JSON body."""
    payload = json.dumps(body).encode("utf-8")
    handler = MagicMock()
    handler.headers = {"Content-Length": str(len(payload))}
    handler.rfile = io.BytesIO(payload)
    return handler


def _parse_body(result) -> dict:
    """Parse HandlerResult body into a dictionary."""
    body = result.body
    if isinstance(body, bytes):
        return json.loads(body.decode("utf-8"))
    return json.loads(body)


@pytest.fixture(autouse=True)
def patch_backbone_create_helpers():
    """Patch create-time backbone helpers so validation tests stay local and deterministic."""
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


def test_handle_post_create_requires_create_permission() -> None:
    """Create-plan route should enforce decisions:create permission."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler({"debate_id": "deb-123"})
    user = SimpleNamespace(user_id="user-1")
    permission_error = error_response("forbidden", 403)

    with (
        patch.object(handler, "_check_circuit_breaker", return_value=None),
        patch.object(handler, "require_auth_or_error", return_value=(user, None)),
        patch.object(
            handler,
            "require_permission_or_error",
            return_value=(None, permission_error),
        ) as mock_permission,
    ):
        result = handler.handle_post("/api/v1/decisions/plans", {}, request)

    assert result.status_code == 403
    mock_permission.assert_called_once_with(request, DECISION_CREATE_PERMISSION)


def test_handle_post_execute_requires_update_permission() -> None:
    """Approve/reject/execute routes should enforce decisions:update permission."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler({})
    user = SimpleNamespace(user_id="user-1")
    permission_error = error_response("forbidden", 403)

    with (
        patch.object(handler, "_check_circuit_breaker", return_value=None),
        patch.object(handler, "require_auth_or_error", return_value=(user, None)),
        patch.object(
            handler,
            "require_permission_or_error",
            return_value=(None, permission_error),
        ) as mock_permission,
    ):
        result = handler.handle_post("/api/v1/decisions/plans/plan-1/execute", {}, request)

    assert result.status_code == 403
    mock_permission.assert_called_once_with(request, DECISION_UPDATE_PERMISSION)


def test_create_plan_rejects_invalid_approval_mode() -> None:
    """Invalid approval_mode should fail fast with 400."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler(
        {
            "debate_id": "deb-123",
            "approval_mode": "invalid-mode",
        }
    )

    mock_loop = MagicMock()
    mock_loop.run_until_complete.return_value = object()

    with (
        patch("asyncio.get_event_loop", return_value=mock_loop),
        patch(
            "aragora.server.handlers.decisions.pipeline._load_debate_result",
            return_value=object(),
        ),
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_debate_result"
        ) as mock_build,
    ):
        result = handler._handle_create_plan(request, SimpleNamespace(user_id="user-1"), SCOPE)

    assert result.status_code == 400
    assert "Invalid approval_mode" in _parse_body(result)["error"]
    mock_build.assert_not_called()


def test_create_plan_rejects_invalid_max_auto_risk() -> None:
    """Invalid max_auto_risk should fail fast with 400."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler(
        {
            "debate_id": "deb-123",
            "max_auto_risk": "catastrophic",
        }
    )

    mock_loop = MagicMock()
    mock_loop.run_until_complete.return_value = object()

    with (
        patch("asyncio.get_event_loop", return_value=mock_loop),
        patch(
            "aragora.server.handlers.decisions.pipeline._load_debate_result",
            return_value=object(),
        ),
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_debate_result"
        ) as mock_build,
    ):
        result = handler._handle_create_plan(request, SimpleNamespace(user_id="user-1"), SCOPE)

    assert result.status_code == 400
    assert "Invalid max_auto_risk" in _parse_body(result)["error"]
    mock_build.assert_not_called()


def test_create_plan_rejects_invalid_budget_limit_usd() -> None:
    """Invalid budget_limit_usd should fail with 400 instead of silently defaulting."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler(
        {
            "debate_id": "deb-123",
            "budget_limit_usd": "not-a-number",
        }
    )

    mock_loop = MagicMock()
    mock_loop.run_until_complete.return_value = object()

    with (
        patch("asyncio.get_event_loop", return_value=mock_loop),
        patch(
            "aragora.server.handlers.decisions.pipeline._load_debate_result",
            return_value=object(),
        ),
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_debate_result"
        ) as mock_build,
    ):
        result = handler._handle_create_plan(request, SimpleNamespace(user_id="user-1"), SCOPE)

    assert result.status_code == 400
    assert "budget_limit_usd" in _parse_body(result)["error"]
    mock_build.assert_not_called()


def test_create_plan_rejects_non_object_metadata() -> None:
    """metadata must be a JSON object."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler(
        {
            "debate_id": "deb-123",
            "metadata": ["not", "an", "object"],
        }
    )

    mock_loop = MagicMock()
    mock_loop.run_until_complete.return_value = object()

    with (
        patch("asyncio.get_event_loop", return_value=mock_loop),
        patch(
            "aragora.server.handlers.decisions.pipeline._load_debate_result",
            return_value=object(),
        ),
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_debate_result"
        ) as mock_build,
    ):
        result = handler._handle_create_plan(request, SimpleNamespace(user_id="user-1"), SCOPE)

    assert result.status_code == 400
    assert "metadata must be an object" in _parse_body(result)["error"]
    mock_build.assert_not_called()


def test_execute_plan_accepts_execution_overrides() -> None:
    """Execute endpoint should route execution through the backbone helper."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler(
        {
            "execution_mode": "hybrid",
            "parallel_execution": True,
            "max_parallel": 4,
        }
    )
    user = SimpleNamespace(
        user_id="user-1",
        role="member",
        roles=["member"],
        permissions=["decisions:update"],
    )

    mock_plan = MagicMock()
    mock_plan.id = "plan-1"
    mock_plan.org_id = "test-org-001"
    mock_plan.to_dict.return_value = {"id": "plan-1"}

    mock_outcome = MagicMock()
    mock_outcome.success = True
    mock_outcome.to_dict.return_value = {"success": True}
    launch = {
        "run_id": "run-plan-1",
        "execution_id": "exec-plan-1",
        "correlation_id": "corr-plan-1",
    }

    mock_executor = MagicMock()

    mock_loop = MagicMock()
    mock_loop.run_until_complete.return_value = (launch, mock_outcome)

    with (
        patch("aragora.pipeline.executor.get_plan", return_value=mock_plan),
        patch(
            "aragora.pipeline.executor.PlanExecutor", return_value=mock_executor
        ) as mock_exec_cls,
        patch(
            "aragora.server.handlers.decisions.pipeline.execute_decision_plan_with_backbone",
            return_value="coro",
        ) as mock_execute,
        patch("aragora.utils.async_utils.get_event_loop_safe", return_value=mock_loop),
    ):
        result = handler._handle_execute_plan("plan-1", request, user, SCOPE)

    assert result.status_code == 200
    payload = _parse_body(result)
    assert payload["run_id"] == "run-plan-1"
    assert payload["execution_id"] == "exec-plan-1"
    mock_exec_cls.assert_called_once_with(parallel_execution=True, max_parallel=4)
    kwargs = mock_execute.call_args.kwargs
    assert kwargs["execution_mode"] == "hybrid"
    assert kwargs["safety_mode"] == ExecutionMode.INTERACTIVE
    assert kwargs["executor"] is mock_executor
    assert kwargs["auth_context"].user_id == "test-user-001"
    assert kwargs["auth_context"].org_id == "test-org-001"


def test_execute_plan_rejects_invalid_execution_mode() -> None:
    """Execute endpoint should validate execution_mode values."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler({"execution_mode": "warp-drive"})
    user = SimpleNamespace(user_id="user-1")
    mock_plan = MagicMock()
    mock_plan.id = "plan-1"
    mock_plan.org_id = "test-org-001"

    with patch("aragora.pipeline.executor.get_plan", return_value=mock_plan):
        result = handler._handle_execute_plan("plan-1", request, user, SCOPE)

    assert result.status_code == 400
    assert "Invalid execution_mode" in _parse_body(result)["error"]


def test_execute_plan_rejects_invalid_parallel_settings() -> None:
    """Execute endpoint should validate parallel settings."""
    handler = DecisionPipelineHandler({})
    user = SimpleNamespace(user_id="user-1")
    mock_plan = MagicMock()
    mock_plan.id = "plan-1"
    mock_plan.org_id = "test-org-001"

    with patch("aragora.pipeline.executor.get_plan", return_value=mock_plan):
        result_parallel = handler._handle_execute_plan(
            "plan-1",
            _make_http_handler({"parallel_execution": "yes"}),
            user,
            SCOPE,
        )
        result_max_parallel = handler._handle_execute_plan(
            "plan-1",
            _make_http_handler({"max_parallel": 0}),
            user,
            SCOPE,
        )

    assert result_parallel.status_code == 400
    assert "parallel_execution must be a boolean" in _parse_body(result_parallel)["error"]
    assert result_max_parallel.status_code == 400
    assert "max_parallel must be >= 1" in _parse_body(result_max_parallel)["error"]


def test_execute_plan_normalizes_execution_mode_alias() -> None:
    """Execute endpoint should normalize known execution-mode aliases."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler({"execution_mode": "workflow_execute"})
    user = SimpleNamespace(user_id="user-1", role="member", roles=["member"], permissions=[])

    mock_plan = MagicMock()
    mock_plan.id = "plan-1"
    mock_plan.org_id = "test-org-001"
    mock_plan.to_dict.return_value = {"id": "plan-1"}

    mock_outcome = MagicMock()
    mock_outcome.success = True
    mock_outcome.to_dict.return_value = {"success": True}
    launch = {
        "run_id": "run-plan-2",
        "execution_id": "exec-plan-2",
        "correlation_id": "corr-plan-2",
    }

    mock_executor = MagicMock()

    mock_loop = MagicMock()
    mock_loop.run_until_complete.return_value = (launch, mock_outcome)

    with (
        patch("aragora.pipeline.executor.get_plan", return_value=mock_plan),
        patch("aragora.pipeline.executor.PlanExecutor", return_value=mock_executor),
        patch(
            "aragora.server.handlers.decisions.pipeline.execute_decision_plan_with_backbone",
            return_value="coro",
        ) as mock_execute,
        patch("aragora.utils.async_utils.get_event_loop_safe", return_value=mock_loop),
    ):
        result = handler._handle_execute_plan("plan-1", request, user, SCOPE)

    assert result.status_code == 200
    kwargs = mock_execute.call_args.kwargs
    assert kwargs["execution_mode"] == "workflow"
    assert kwargs["safety_mode"] == ExecutionMode.INTERACTIVE


def test_execute_plan_backbone_failure_returns_503() -> None:
    handler = DecisionPipelineHandler({})
    request = _make_http_handler({"execution_mode": "workflow"})
    user = SimpleNamespace(user_id="user-1", role="member", roles=["member"], permissions=[])

    mock_plan = MagicMock()
    mock_plan.id = "plan-1"
    mock_plan.org_id = "test-org-001"

    mock_loop = MagicMock()
    mock_loop.run_until_complete.side_effect = BackbonePersistenceError("run ledger unavailable")

    with (
        patch("aragora.pipeline.executor.get_plan", return_value=mock_plan),
        patch("aragora.pipeline.executor.PlanExecutor"),
        patch("aragora.utils.async_utils.get_event_loop_safe", return_value=mock_loop),
    ):
        result = handler._handle_execute_plan("plan-1", request, user, SCOPE)

    assert result.status_code == 503
    assert _parse_body(result)["error"] == FAIL_CLOSED_BACKBONE_MESSAGE


def test_create_plan_seeds_backbone_run_and_scrubs_reserved_metadata() -> None:
    """Create-plan should seed a backbone run and ignore spoofed backbone metadata."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler(
        {
            "debate_id": "deb-123",
            "metadata": {
                "custom": "value",
                "source_surface": "spoofed",
                "source_id": "spoofed-id",
                "backbone_run_id": "run-spoofed",
                "backbone_entrypoint": "spoofed.entrypoint",
            },
            "mode": "architect",
        }
    )

    mock_plan = MagicMock()
    mock_plan.id = "plan-1"
    mock_plan.debate_id = "deb-123"
    mock_plan.requires_human_approval = False
    mock_plan.status = SimpleNamespace(value="approved")
    mock_plan.to_dict.return_value = {"id": "plan-1"}

    mock_loop = MagicMock()
    mock_loop.run_until_complete.return_value = object()
    user = SimpleNamespace(user_id="user-1")

    with (
        patch("asyncio.get_event_loop", return_value=mock_loop),
        patch(
            "aragora.server.handlers.decisions.pipeline._load_debate_result",
            return_value=object(),
        ),
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_debate_result",
            return_value=mock_plan,
        ) as mock_build,
        patch("aragora.pipeline.executor.store_plan"),
        patch(
            "aragora.server.handlers.decisions.pipeline.ensure_decision_plan_backbone_run",
            return_value="run-plan-3",
        ) as mock_seed,
        patch(
            "aragora.server.handlers.decisions.pipeline.sync_decision_plan_backbone_receipt",
            return_value=True,
        ) as mock_sync,
    ):
        result = handler._handle_create_plan(request, user, SCOPE)

    assert result.status_code == 201
    payload = _parse_body(result)
    assert payload["run_id"] == "run-plan-3"
    metadata = mock_build.call_args.kwargs["metadata"]
    assert metadata["custom"] == "value"
    assert metadata["operational_mode"] == "architect"
    assert "source_surface" not in metadata
    assert "source_id" not in metadata
    assert "backbone_run_id" not in metadata
    assert "backbone_entrypoint" not in metadata
    mock_seed.assert_called_once_with(
        mock_plan,
        auth_context=user,
        source_surface="decision_pipeline",
        source_id="deb-123",
        org_id="test-org-001",
        created_by="test-user-001",
    )
    assert mock_plan.org_id == "test-org-001"
    assert mock_plan.created_by == "test-user-001"
    mock_sync.assert_called_once_with(mock_plan, append_event=False)


def test_create_plan_normalizes_profile_execution_mode_alias() -> None:
    """Create-plan endpoint should normalize execution-mode aliases in profile payload."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler(
        {
            "debate_id": "deb-123",
            "execution_mode": "computer-use",
        }
    )

    mock_plan = MagicMock()
    mock_plan.id = "plan-1"
    mock_plan.debate_id = "deb-123"
    mock_plan.requires_human_approval = False
    mock_plan.status = SimpleNamespace(value="approved")
    mock_plan.to_dict.return_value = {"id": "plan-1"}

    mock_loop = MagicMock()
    mock_loop.run_until_complete.return_value = object()

    with (
        patch("asyncio.get_event_loop", return_value=mock_loop),
        patch(
            "aragora.server.handlers.decisions.pipeline._load_debate_result",
            return_value=object(),
        ),
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_debate_result",
            return_value=mock_plan,
        ) as mock_build,
        patch("aragora.pipeline.executor.store_plan"),
    ):
        result = handler._handle_create_plan(request, SimpleNamespace(user_id="user-1"), SCOPE)

    assert result.status_code == 201
    kwargs = mock_build.call_args.kwargs
    assert kwargs["implementation_profile"]["execution_mode"] == "computer_use"


def test_create_plan_rejects_invalid_channel_targets_shape() -> None:
    """Create-plan should reject non-string/list channel target payloads."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler(
        {
            "debate_id": "deb-123",
            "channel_targets": {"slack": "#eng"},
        }
    )
    mock_loop = MagicMock()
    mock_loop.run_until_complete.return_value = object()

    with (
        patch("asyncio.get_event_loop", return_value=mock_loop),
        patch(
            "aragora.server.handlers.decisions.pipeline._load_debate_result",
            return_value=object(),
        ),
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_debate_result"
        ) as mock_build,
    ):
        result = handler._handle_create_plan(request, SimpleNamespace(user_id="user-1"), SCOPE)

    assert result.status_code == 400
    assert "channel_targets" in _parse_body(result)["error"]
    mock_build.assert_not_called()


def test_create_plan_rejects_invalid_thread_id_by_platform_shape() -> None:
    """Create-plan should reject non-object thread map payloads."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler(
        {
            "debate_id": "deb-123",
            "thread_id_by_platform": ["not", "a", "map"],
        }
    )
    mock_loop = MagicMock()
    mock_loop.run_until_complete.return_value = object()

    with (
        patch("asyncio.get_event_loop", return_value=mock_loop),
        patch(
            "aragora.server.handlers.decisions.pipeline._load_debate_result",
            return_value=object(),
        ),
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_debate_result"
        ) as mock_build,
    ):
        result = handler._handle_create_plan(request, SimpleNamespace(user_id="user-1"), SCOPE)

    assert result.status_code == 400
    assert "thread_id_by_platform" in _parse_body(result)["error"]
    mock_build.assert_not_called()


def test_create_plan_normalizes_channel_targets_and_thread_map() -> None:
    """Create-plan should normalize channel targets and thread mapping payloads."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler(
        {
            "debate_id": "deb-123",
            "channel_targets": "slack:#eng, teams:ops",
            "thread_id": " thread-42 ",
            "thread_id_by_platform": {"slack": " abc ", "teams": "xyz"},
        }
    )

    mock_plan = MagicMock()
    mock_plan.id = "plan-1"
    mock_plan.debate_id = "deb-123"
    mock_plan.requires_human_approval = False
    mock_plan.status = SimpleNamespace(value="approved")
    mock_plan.to_dict.return_value = {"id": "plan-1"}

    mock_loop = MagicMock()
    mock_loop.run_until_complete.return_value = object()

    with (
        patch("asyncio.get_event_loop", return_value=mock_loop),
        patch(
            "aragora.server.handlers.decisions.pipeline._load_debate_result",
            return_value=object(),
        ),
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_debate_result",
            return_value=mock_plan,
        ) as mock_build,
        patch("aragora.pipeline.executor.store_plan"),
    ):
        result = handler._handle_create_plan(request, SimpleNamespace(user_id="user-1"), SCOPE)

    assert result.status_code == 201
    profile = mock_build.call_args.kwargs["implementation_profile"]
    assert profile["channel_targets"] == ["slack:#eng", "teams:ops"]
    assert profile["thread_id"] == "thread-42"
    assert profile["thread_id_by_platform"] == {"slack": "abc", "teams": "xyz"}


def test_approve_plan_records_actor_reason_and_timestamp() -> None:
    """Approve should capture an auditable approval record."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler({"reason": "review complete", "conditions": ["qa-pass"]})
    user = SimpleNamespace(user_id="approver-123")
    plan = DecisionPlan(
        id="plan-approve-1", debate_id="deb-1", task="Ship it", org_id="test-org-001"
    )
    plan.status = PlanStatus.AWAITING_APPROVAL

    with (
        patch("aragora.pipeline.executor.get_plan", return_value=plan),
        patch("aragora.pipeline.executor.store_plan") as mock_store,
    ):
        result = handler._handle_approve_plan(plan.id, request, user, SCOPE)

    assert result.status_code == 200
    payload = _parse_body(result)
    record = payload["plan"]["approval_record"]
    assert record["approver_id"] == "approver-123"
    assert record["reason"] == "review complete"
    assert record["timestamp"]
    mock_store.assert_called_once()


def test_reject_plan_records_actor_reason_and_timestamp() -> None:
    """Reject should capture an auditable rejection record."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler({"reason": "risk unresolved"})
    user = SimpleNamespace(user_id="reviewer-9")
    plan = DecisionPlan(
        id="plan-reject-1", debate_id="deb-2", task="Deploy change", org_id="test-org-001"
    )
    plan.status = PlanStatus.CREATED

    with (
        patch("aragora.pipeline.executor.get_plan", return_value=plan),
        patch("aragora.pipeline.executor.store_plan") as mock_store,
    ):
        result = handler._handle_reject_plan(plan.id, request, user, SCOPE)

    assert result.status_code == 200
    payload = _parse_body(result)
    record = payload["plan"]["approval_record"]
    assert record["approver_id"] == "reviewer-9"
    assert record["reason"] == "risk unresolved"
    assert record["timestamp"]
    assert record["approved"] is False
    mock_store.assert_called_once()


def test_approve_plan_rejects_illegal_state_transition() -> None:
    """Approving an already approved/rejected/executing plan should fail with 409."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler({})
    user = SimpleNamespace(user_id="approver-123")
    plan = DecisionPlan(
        id="plan-approve-illegal", debate_id="deb-3", task="Task", org_id="test-org-001"
    )
    plan.status = PlanStatus.APPROVED

    with patch("aragora.pipeline.executor.get_plan", return_value=plan):
        result = handler._handle_approve_plan(plan.id, request, user, SCOPE)

    assert result.status_code == 409
    assert "cannot be approved in status" in _parse_body(result)["error"]


def test_reject_plan_rejects_illegal_state_transition() -> None:
    """Rejecting an already approved/rejected/executing plan should fail with 409."""
    handler = DecisionPipelineHandler({})
    request = _make_http_handler({"reason": "late rejection"})
    user = SimpleNamespace(user_id="reviewer-9")
    plan = DecisionPlan(
        id="plan-reject-illegal", debate_id="deb-4", task="Task", org_id="test-org-001"
    )
    plan.status = PlanStatus.REJECTED

    with patch("aragora.pipeline.executor.get_plan", return_value=plan):
        result = handler._handle_reject_plan(plan.id, request, user, SCOPE)

    assert result.status_code == 409
    assert "cannot be rejected in status" in _parse_body(result)["error"]
