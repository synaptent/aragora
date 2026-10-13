"""POST /api/v1/decisions/plans stores the new plan with the caller's org as owner."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from aragora.pipeline.decision_plan import ApprovalMode, DecisionPlan
from aragora.pipeline.plan_store import PlanStore
from aragora.server.handlers.decisions.pipeline import DecisionPipelineHandler

PIPELINE = "aragora.server.handlers.decisions.pipeline"


def test_created_plan_is_listed_for_the_callers_org(tmp_path, monkeypatch):
    store = PlanStore(db_path=str(tmp_path / "plans.db"))
    monkeypatch.setattr("aragora.pipeline.executor._backing_store", store)
    monkeypatch.setattr(f"{PIPELINE}._pipeline_cb", None)
    plan = DecisionPlan(debate_id="debate-001", task="t", approval_mode=ApprovalMode.NEVER)
    raw = json.dumps({"debate_id": "debate-001"}).encode()
    request = MagicMock(client_address=("127.0.0.1", 1), headers={"Content-Length": str(len(raw))})
    request.rfile.read.return_value = raw

    with (
        patch(f"{PIPELINE}._load_debate_result", return_value=MagicMock()),
        patch(f"{PIPELINE}.ensure_decision_plan_backbone_run", return_value="run-owner"),
        patch(f"{PIPELINE}.sync_decision_plan_backbone_receipt", return_value=True),
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_debate_result",
            return_value=plan,
        ),
    ):
        result = DecisionPipelineHandler(ctx={}).handle_post("/api/v1/decisions/plans", {}, request)

    assert result.status_code == 201
    # The caller is the authenticated user that tests/handlers/conftest.py provides.
    owned = store.list_for_org("test-org-001")
    assert [(p.id, p.org_id, p.created_by) for p in owned] == [
        (plan.id, "test-org-001", "test-user-001")
    ]
