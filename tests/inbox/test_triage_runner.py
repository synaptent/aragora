"""Tests for the receipt-backed inbox triage runner."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.core import DebateResult
from aragora.inbox.triage_runner import InboxTriageRunner
from aragora.inbox.trust_wedge import (
    InboxWedgeAction,
    ReceiptState,
    TriageDecision,
    compute_content_hash,
)


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
async def test_run_triage_preserves_real_debate_result_confidence_and_id():
    gmail = _DummyGmail()
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-real",
            state=ReceiptState.APPROVED if auto_approve else ReceiptState.CREATED,
        )
    )

    runner = InboxTriageRunner(gmail_connector=gmail, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(
        return_value=DebateResult(
            debate_id="debate-real",
            final_answer="archive",
            confidence=0.73,
            consensus_reached=True,
        )
    )

    decisions = await runner.run_triage(batch_size=1, auto_approve=False)

    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.receipt_id == "receipt-real"
    assert decision.confidence == pytest.approx(0.73)
    assert decision.final_action == InboxWedgeAction.ARCHIVE
    assert decision.intent is not None
    assert decision.intent.debate_id == "debate-real"
    assert decision.intent.confidence == pytest.approx(0.73)


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


@pytest.mark.asyncio
async def test_no_consensus_forces_manual_review_and_preserves_reason():
    gmail = _DummyGmail()
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-no-consensus",
            state=ReceiptState.APPROVED if auto_approve else ReceiptState.CREATED,
        )
    )

    runner = InboxTriageRunner(gmail_connector=gmail, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(
        return_value=DebateResult(
            debate_id="debate-no-consensus",
            final_answer="archive",
            confidence=0.0,
            consensus_reached=False,
            dissenting_views=["critic preferred star"],
        )
    )

    decisions = await runner.run_triage(batch_size=1, auto_approve=True)

    decision = decisions[0]
    assert wedge_service.create_receipt.call_args.kwargs["auto_approve"] is False
    assert decision.receipt_state == ReceiptState.CREATED.value
    assert decision.final_action == InboxWedgeAction.ARCHIVE
    assert decision.blocked_by_policy is True
    assert "No consensus reached" in decision.dissent_summary
    assert "critic preferred star" in decision.dissent_summary
    wedge_service.execute_receipt.assert_not_awaited()


@pytest.mark.asyncio
async def test_unparseable_final_answer_falls_back_to_ignore_and_blocks_auto_approval():
    gmail = _DummyGmail()
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-parse",
            state=ReceiptState.APPROVED if auto_approve else ReceiptState.CREATED,
        )
    )

    runner = InboxTriageRunner(gmail_connector=gmail, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(
        return_value=DebateResult(
            debate_id="debate-parse",
            final_answer="Archive or ignore this email depending on urgency.",
            confidence=0.96,
            consensus_reached=True,
        )
    )

    decisions = await runner.run_triage(batch_size=1, auto_approve=True)

    decision = decisions[0]
    assert wedge_service.create_receipt.call_args.kwargs["auto_approve"] is False
    assert decision.receipt_state == ReceiptState.CREATED.value
    assert decision.final_action == InboxWedgeAction.IGNORE
    assert decision.blocked_by_policy is True
    assert "fell back to ignore" in decision.dissent_summary
    wedge_service.execute_receipt.assert_not_awaited()


@pytest.mark.asyncio
async def test_structured_proposal_header_takes_priority_over_other_action_mentions():
    gmail = _DummyGmail()
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-structured",
            state=ReceiptState.APPROVED if auto_approve else ReceiptState.CREATED,
        )
    )

    runner = InboxTriageRunner(gmail_connector=gmail, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(
        return_value=DebateResult(
            debate_id="debate-structured",
            final_answer=(
                "## Proposal: ARCHIVE this email\n\n"
                "Alternatives considered: ignore or star if the user wants to keep a trace."
            ),
            confidence=0.82,
            consensus_reached=True,
        )
    )

    decisions = await runner.run_triage(batch_size=1, auto_approve=False)

    decision = decisions[0]
    assert decision.final_action == InboxWedgeAction.ARCHIVE
    assert decision.blocked_by_policy is False
    assert decision.dissent_summary == ""


@pytest.mark.asyncio
async def test_word_form_action_parsing_preserves_archive():
    gmail = _DummyGmail()
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-word-form",
            state=ReceiptState.APPROVED if auto_approve else ReceiptState.CREATED,
        )
    )

    runner = InboxTriageRunner(gmail_connector=gmail, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(
        return_value=DebateResult(
            debate_id="debate-word-form",
            final_answer="I recommend archiving this email after review.",
            confidence=0.81,
            consensus_reached=True,
        )
    )

    decisions = await runner.run_triage(batch_size=1, auto_approve=False)

    decision = decisions[0]
    assert decision.final_action == InboxWedgeAction.ARCHIVE
    assert decision.blocked_by_policy is False
    assert decision.dissent_summary == ""


@pytest.mark.asyncio
async def test_triage_message_uses_from_address_and_body_text_when_present():
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-fields",
            state=ReceiptState.APPROVED if auto_approve else ReceiptState.CREATED,
        )
    )
    runner = InboxTriageRunner(gmail_connector=None, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(
        return_value={
            "final_answer": "archive",
            "confidence": 0.9,
            "debate_id": "debate-fields",
        }
    )
    msg = {
        "id": "msg-fields",
        "subject": "Important update",
        "from_address": "alice@example.com",
        "body_text": "Full message body",
        "snippet": "Preview",
    }

    decision = await runner._triage_message(msg)

    assert decision.intent is not None
    assert decision.intent._sender == "alice@example.com"  # type: ignore[attr-defined]
    assert decision.intent._subject == "Important update"  # type: ignore[attr-defined]
    assert decision.intent.content_hash == compute_content_hash("Full message body")


@pytest.mark.asyncio
async def test_triage_message_falls_back_to_body_when_body_text_missing():
    runner = InboxTriageRunner(gmail_connector=None)
    runner._run_debate = AsyncMock(
        return_value={
            "final_answer": "ignore",
            "confidence": 0.2,
            "debate_id": "debate-body-fallback",
        }
    )
    msg = {
        "id": "msg-body",
        "subject": "Fallback",
        "from_address": "bob@example.com",
        "body": "Body fallback content",
        "snippet": "Snippet fallback",
    }

    decision = await runner._triage_message(msg)

    assert decision.intent is not None
    assert decision.intent.content_hash == compute_content_hash("Body fallback content")


@pytest.mark.asyncio
async def test_run_debate_uses_agent_registry_and_explicit_action_prompt(monkeypatch):
    created_agents: list[object] = []
    captured_tasks: list[str] = []

    class _Arena:
        def __init__(self, env, agents, protocol):
            captured_tasks.append(env.task)
            created_agents.extend(agents)

        async def run(self):
            return {"final_answer": "archive", "confidence": 0.9}

    def _create_agent(model_type, name="", role="proposer"):
        return SimpleNamespace(name=name, role=role, model_type=model_type)

    def _environment(*, task):
        return SimpleNamespace(task=task)

    import aragora.agents.registry as reg_mod
    import aragora.core as core_mod
    import aragora.debate.orchestrator as orch_mod
    import aragora.debate.protocol as proto_mod

    monkeypatch.setattr(reg_mod.AgentRegistry, "create", staticmethod(_create_agent))
    monkeypatch.setattr(core_mod, "Environment", _environment)
    monkeypatch.setattr(proto_mod, "DebateProtocol", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(orch_mod, "Arena", _Arena)

    runner = InboxTriageRunner(gmail_connector=None)
    result = await runner._run_debate(
        {
            "id": "msg-prompt",
            "subject": "Prompt subject",
            "from_address": "sender@example.com",
            "body_text": "Prompt body",
        }
    )

    assert result["final_answer"] == "archive"
    assert len(created_agents) == 3
    assert len(captured_tasks) == 1
    assert "From: sender@example.com" in captured_tasks[0]
    assert "MUST begin with the action word" in captured_tasks[0]


@pytest.mark.asyncio
async def test_run_debate_falls_back_to_stub_when_fewer_than_two_agents(monkeypatch):
    created = 0

    def _create_agent(model_type, name="", role="proposer"):
        nonlocal created
        created += 1
        if created == 1:
            return SimpleNamespace(name=name, role=role, model_type=model_type)
        raise RuntimeError("missing credentials")

    import aragora.agents.registry as reg_mod
    import aragora.core as core_mod
    import aragora.debate.orchestrator as orch_mod
    import aragora.debate.protocol as proto_mod

    monkeypatch.setattr(reg_mod.AgentRegistry, "create", staticmethod(_create_agent))
    monkeypatch.setattr(core_mod, "Environment", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(proto_mod, "DebateProtocol", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(orch_mod, "Arena", MagicMock())

    runner = InboxTriageRunner(gmail_connector=None)
    result = await runner._run_debate(
        {
            "id": "msg-stub",
            "subject": "Stub subject",
            "from_address": "sender@example.com",
            "body_text": "Stub body",
        }
    )

    assert result["final_answer"] == "ignore"
    assert result["confidence"] == 0.0
