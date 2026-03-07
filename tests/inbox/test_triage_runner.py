"""Tests for the receipt-backed inbox triage runner."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.inbox.triage_runner import InboxTriageRunner
from aragora.inbox.trust_wedge import ReceiptState, TriageDecision


class _DummyGmail:
    connector_id = "gmail"
    user_id = "me"

    async def list_messages(self, *, query: str, max_results: int):
        return ["msg-1"], None

    async def get_message(self, _message_id: str):
        return {
            "id": "msg-1",
            "subject": "Test subject",
            "from": "sender@example.com",
            "snippet": "Test snippet",
            "body": "Body text",
        }


def _make_envelope(
    decision: TriageDecision,
    *,
    receipt_id: str,
    state: ReceiptState,
):
    updated = TriageDecision.create(
        final_action=decision.final_action,
        confidence=decision.confidence,
        dissent_summary=decision.dissent_summary,
        receipt_id=receipt_id,
        auto_approval_eligible=state is ReceiptState.APPROVED,
        receipt_state=state.value,
        intent=decision.intent,
        provider_route=decision.provider_route,
        label_id=decision.label_id,
        blocked_by_policy=decision.blocked_by_policy,
    )
    return SimpleNamespace(
        intent=decision.intent,
        decision=updated,
        receipt=SimpleNamespace(receipt_id=receipt_id, state=state),
        provider_route=decision.provider_route,
    )


@pytest.mark.asyncio
async def test_run_triage_creates_persisted_receipt():
    gmail = _DummyGmail()
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-1",
            state=ReceiptState.APPROVED if auto_approve else ReceiptState.CREATED,
        )
    )

    runner = InboxTriageRunner(gmail_connector=gmail, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(
        return_value={
            "final_answer": "archive",
            "confidence": 0.91,
            "debate_id": "debate-1",
        }
    )

    decisions = await runner.run_triage(batch_size=1, auto_approve=False)

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.receipt_id == "receipt-1"
    assert decision.receipt_state == ReceiptState.CREATED.value
    assert decision.intent is not None
    assert decision.intent.provider == "gmail"
    assert decision.intent.user_id == "me"
    assert wedge_service.create_receipt.call_args.kwargs["auto_approve"] is False
    wedge_service.execute_receipt.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_triage_executes_auto_approved_receipts():
    gmail = _DummyGmail()
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-2",
            state=ReceiptState.APPROVED if auto_approve else ReceiptState.CREATED,
        )
    )

    runner = InboxTriageRunner(gmail_connector=gmail, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(
        return_value={
            "final_answer": "archive",
            "confidence": 0.99,
            "debate_id": "debate-2",
        }
    )

    decisions = await runner.run_triage(batch_size=1, auto_approve=True)

    assert decisions[0].receipt_state == ReceiptState.EXECUTED.value
    wedge_service.execute_receipt.assert_awaited_once_with("receipt-2")


@pytest.mark.asyncio
async def test_dissent_blocks_auto_approval_before_receipt_execution():
    gmail = _DummyGmail()
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-3",
            state=ReceiptState.APPROVED if auto_approve else ReceiptState.CREATED,
        )
    )

    runner = InboxTriageRunner(gmail_connector=gmail, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(
        return_value={
            "final_answer": "archive",
            "confidence": 0.99,
            "debate_id": "debate-3",
            "dissenting_views": ["Needs human review"],
        }
    )

    decisions = await runner.run_triage(batch_size=1, auto_approve=True)

    assert wedge_service.create_receipt.call_args.kwargs["auto_approve"] is False
    assert decisions[0].receipt_state == ReceiptState.CREATED.value
    wedge_service.execute_receipt.assert_not_awaited()
