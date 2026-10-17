from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aragora.pipeline.execution_mode import ExecutionMode
from aragora.server.handlers.decisions.pipeline import DecisionPipelineHandler
from aragora.tenancy.record_scope import OrgScope


def test_handler_propagates_interactive_mode_to_execution_bridge() -> None:
    handler = DecisionPipelineHandler({})
    request = MagicMock()
    user = SimpleNamespace(user_id="user-1", role="member", roles=["member"], permissions=[])
    scope = OrgScope(org_id="org-1", user_id="user-1", role="member")
    plan = MagicMock(id="plan-1", org_id="org-1")
    plan.to_dict.return_value = {"id": "plan-1"}
    outcome = MagicMock(success=True)
    outcome.to_dict.return_value = {"success": True}
    loop = MagicMock()
    loop.run_until_complete.return_value = (
        {"run_id": "run-1", "execution_id": "exec-1", "correlation_id": "corr-1"},
        outcome,
    )

    with (
        patch.object(handler, "read_json_body", return_value={"execution_mode": "workflow"}),
        patch("aragora.pipeline.executor.get_plan", return_value=plan),
        patch("aragora.pipeline.executor.PlanExecutor", return_value=MagicMock()),
        patch(
            "aragora.server.handlers.decisions.pipeline.execute_decision_plan_with_backbone",
            new=MagicMock(return_value="coro"),
        ) as mock_execute,
        patch("aragora.utils.async_utils.get_event_loop_safe", return_value=loop),
    ):
        result = handler._handle_execute_plan("plan-1", request, user, scope)

    assert result.status_code == 200
    assert mock_execute.call_args.kwargs["execution_mode"] == "workflow"
    assert mock_execute.call_args.kwargs["safety_mode"] == ExecutionMode.INTERACTIVE
