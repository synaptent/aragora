"""Tests for pre-execution receipt gating of DecisionPlan actions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.gauntlet.receipt_store import ReceiptState, get_receipt_store, reset_receipt_store
from aragora.pipeline.decision_plan.core import (
    ApprovalMode,
    ApprovalRecord,
    DecisionPlan,
    PlanStatus,
)
from aragora.pipeline.decision_plan.memory import PlanOutcome
from aragora.pipeline.executor import PlanExecutor
from aragora.pipeline.receipt_gate import PlanReceiptGateError, ensure_plan_receipt


@pytest.fixture(autouse=True)
def _reset_receipts() -> None:
    reset_receipt_store()
    yield
    reset_receipt_store()


def _plan(
    *,
    status: PlanStatus = PlanStatus.APPROVED,
    approval_mode: ApprovalMode = ApprovalMode.ALWAYS,
    approval_record: ApprovalRecord | None = None,
    metadata: dict[str, object] | None = None,
) -> DecisionPlan:
    return DecisionPlan(
        id="dp-receipt-gate",
        debate_id="debate-receipt-gate",
        task="Ship the approved workflow changes",
        status=status,
        approval_mode=approval_mode,
        approval_record=approval_record,
        metadata=metadata or {},
    )


def test_ensure_plan_receipt_supports_documented_exemption() -> None:
    plan = _plan(
        metadata={
            "receipt_gate_exemption": {
                "reason": "Legacy admin remediation path",
                "approved_by": "admin-user",
            }
        }
    )

    status = ensure_plan_receipt(plan)

    assert status.exempted is True
    assert plan.metadata["decision_receipt"]["state"] == "EXEMPTED"
    assert get_receipt_store().list_receipts() == []


def test_existing_tampered_receipt_fails_closed() -> None:
    plan = _plan(
        status=PlanStatus.CREATED,
        approval_mode=ApprovalMode.NEVER,
        metadata={
            "execution_gate": {
                "provider_diversity": 2,
                "model_family_diversity": 2,
                "providers": ["openai", "anthropic"],
                "model_families": ["gpt", "claude"],
            }
        },
    )

    status = ensure_plan_receipt(plan)
    receipt_id = status.receipt_id
    assert receipt_id is not None

    store = get_receipt_store()
    stored = store.get(receipt_id)
    assert stored is not None
    stored.signature = "tampered-signature"

    with pytest.raises(PlanReceiptGateError, match="signature verification"):
        ensure_plan_receipt(plan)


@pytest.mark.asyncio
async def test_executor_verifies_receipt_before_running_actions() -> None:
    plan = _plan(
        approval_record=ApprovalRecord(approved=True, approver_id="user-42"),
        metadata={
            "execution_gate": {
                "provider_diversity": 2,
                "model_family_diversity": 2,
                "providers": ["openai", "anthropic"],
                "model_families": ["gpt", "claude"],
                "context_taint_detected": True,
                "reason_codes": ["tainted_context_detected"],
            },
            "deliberation_bundle": {
                "confidence": 0.82,
                "consensus_reached": True,
                "dissenting_views": ["critic: verify rollback path"],
                "taint_flags": ["external_unverified"],
            },
        },
    )

    store = get_receipt_store()

    async def _run_workflow_assert_receipt(*args, **kwargs):
        receipt_id = plan.metadata["decision_receipt"]["receipt_id"]
        stored = store.get(receipt_id)
        assert stored is not None
        assert stored.state == ReceiptState.APPROVED
        return PlanOutcome(
            plan_id=plan.id,
            debate_id=plan.debate_id,
            task=plan.task,
            success=True,
            tasks_completed=1,
            tasks_total=1,
            duration_seconds=0.1,
        )

    executor = PlanExecutor()
    with (
        patch.object(
            PlanExecutor, "_run_workflow", AsyncMock(side_effect=_run_workflow_assert_receipt)
        ),
        patch.object(PlanExecutor, "_generate_receipt", AsyncMock(return_value=None)),
        patch.object(PlanExecutor, "_ingest_to_km", AsyncMock()),
        patch("aragora.pipeline.executor.record_plan_outcome", AsyncMock()),
        patch.object(PlanExecutor, "_emit_plan_event"),
        patch("aragora.workspace.convoy.ConvoyTracker", MagicMock()),
    ):
        outcome = await executor.execute(plan, execution_mode="workflow")

    receipt_id = plan.metadata["decision_receipt"]["receipt_id"]
    stored = store.get(receipt_id)
    assert outcome.success is True
    assert stored is not None
    assert stored.state == ReceiptState.EXECUTED
    assert stored.receipt_data["config_used"]["taint_analysis"]["tainted"] is True
    assert stored.receipt_data["config_used"]["execution_gate"]["provider_diversity"] == 2
