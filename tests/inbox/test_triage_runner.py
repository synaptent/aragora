"""Tests for the receipt-backed inbox triage runner."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.core import DebateResult
from aragora.inbox.triage_diagnostics import DiagnosticSeverity, TriageRunDiagnostics
from aragora.inbox.triage_runner import (
    InboxTriageRunner,
    _create_triage_agents,
    _extract_fast_tier_json,
    _normalize_triage_profile,
    _result_consensus_reached,
)
from aragora.inbox.trust_wedge import (
    InboxWedgeAction,
    ReceiptState,
    TriageDecision,
    compute_content_hash,
)
from aragora.agents.semantic_extraction import ExtractionResult


class _DummyGmail:
    connector_id = "gmail"
    user_id = "me"

    async def list_messages(
        self,
        *,
        query: str,
        max_results: int,
        page_token: str | None = None,
    ):
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


def test_normalize_triage_profile_defaults_to_staged_v1():
    assert _normalize_triage_profile(None) == "staged_v1"
    assert _normalize_triage_profile("unknown-profile") == "staged_v1"


def test_extract_fast_tier_json_parses_fenced_payload():
    parsed = _extract_fast_tier_json(
        """```json
        {"action":"archive","confidence":0.95,"rationale":"Promotional email."}
        ```"""
    )

    assert parsed == {
        "action": "archive",
        "confidence": 0.95,
        "rationale": "Promotional email.",
    }


@pytest.mark.asyncio
async def test_run_fast_tier_once_uses_shared_semantic_extraction(monkeypatch):
    runner = InboxTriageRunner(gmail_connector=None)

    async def fake_extract(prompt, **kwargs):
        assert "Test subject" in prompt
        providers = kwargs["providers"]
        guarded_providers = {
            provider.agent_type for provider in providers if provider.disable_web_search
        }
        assert {"gemini", "openai-api", "anthropic-api"} <= guarded_providers
        return ExtractionResult(
            value={
                "action": "archive",
                "confidence": 0.95,
                "rationale": "Promotional email.",
            },
            source="openai-api",
        )

    monkeypatch.setattr(
        "aragora.inbox.triage_runner.extract_json_object_llm_first",
        fake_extract,
    )

    result = await runner._run_fast_tier_once(
        {
            "subject": "Test subject",
            "from_address": "sender@example.com",
            "body_text": "Promotional body",
        }
    )

    assert result["final_answer"] == "archive: Promotional email."
    assert result["confidence"] == pytest.approx(0.95)
    assert result["status"] == "completed"
    assert result["metadata"]["triage_fast_provider"] == "openai-api"


@pytest.mark.asyncio
async def test_run_fast_tier_once_returns_blocked_when_no_provider_available(monkeypatch):
    runner = InboxTriageRunner(gmail_connector=None)

    async def fake_extract(_prompt, **kwargs):
        return ExtractionResult(
            value=None,
            source="none",
            error="no_available_providers",
        )

    monkeypatch.setattr(
        "aragora.inbox.triage_runner.extract_json_object_llm_first",
        fake_extract,
    )

    result = await runner._run_fast_tier_once(
        {
            "subject": "Test subject",
            "from_address": "sender@example.com",
            "body_text": "Promotional body",
        }
    )

    assert result["confidence"] == 0.0
    assert result["status"] == "insufficient_participation"


@pytest.mark.asyncio
async def test_run_fast_tier_once_returns_failed_when_semantic_extraction_fails(monkeypatch):
    runner = InboxTriageRunner(gmail_connector=None)

    async def fake_extract(_prompt, **kwargs):
        return ExtractionResult(
            value=None,
            source="openai-api",
            raw_response="not-json",
            error="openai-api:invalid_json",
        )

    monkeypatch.setattr(
        "aragora.inbox.triage_runner.extract_json_object_llm_first",
        fake_extract,
    )

    result = await runner._run_fast_tier_once(
        {
            "subject": "Test subject",
            "from_address": "sender@example.com",
            "body_text": "Promotional body",
        }
    )

    assert result["confidence"] == 0.0
    assert result["status"] == "failed"


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
async def test_run_triage_tracks_next_page_token():
    gmail = _DummyGmail()
    gmail.list_messages = AsyncMock(return_value=(["msg-1"], "next-page-123"))
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-page-token",
            state=ReceiptState.APPROVED if auto_approve else ReceiptState.CREATED,
        )
    )

    runner = InboxTriageRunner(gmail_connector=gmail, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(
        return_value={
            "final_answer": "archive",
            "confidence": 0.91,
            "debate_id": "debate-page-token",
        }
    )

    decisions = await runner.run_triage(batch_size=1, auto_approve=False, page_token="cursor-1")

    assert len(decisions) == 1
    gmail.list_messages.assert_awaited_once_with(
        query="in:inbox is:unread",
        max_results=1,
        page_token="cursor-1",
    )
    assert runner.next_page_token == "next-page-123"


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
async def test_financial_subject_forces_manual_review_even_with_high_confidence_archive():
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-finance-guard",
            state=ReceiptState.APPROVED if auto_approve else ReceiptState.CREATED,
        )
    )

    runner = InboxTriageRunner(gmail_connector=None, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(
        return_value={
            "final_answer": "archive",
            "confidence": 0.99,
            "debate_id": "debate-finance-guard",
        }
    )

    decision = await runner._triage_message(
        {
            "id": "msg-finance-guard",
            "subject": "Your receipt from Loom, Inc.",
            "from": "billing@example.com",
            "body": "Payment confirmed.",
        },
        auto_approve=True,
    )

    assert wedge_service.create_receipt.call_args.kwargs["auto_approve"] is False
    assert decision.receipt_state == ReceiptState.CREATED.value
    wedge_service.execute_receipt.assert_not_awaited()


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


@pytest.mark.parametrize(
    ("debate_result", "rationale", "expected"),
    [
        ({"consensus_reached": "true"}, "", True),
        ({"consensus_reached": "1"}, "", True),
        ({"consensus_reached": "yes"}, "", True),
        ({"consensus_reached": "on"}, "", True),
        ({"consensus_reached": "false"}, "archive", False),
        ({"consensus_reached": "0"}, "archive", False),
        ({"consensus_reached": "no"}, "archive", False),
        ({"consensus_reached": "off"}, "archive", False),
        ({"consensus_reached": ""}, "archive", False),
        ({"consensus_reached": "malformed"}, "archive", False),
        ({}, "archive", True),
        ({"consensus_reached": None}, "archive", True),
    ],
)
def test_result_consensus_reached_parses_string_values_fail_closed(
    debate_result, rationale, expected
):
    assert _result_consensus_reached(debate_result, rationale) is expected


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
    assert "showing a blocked recommendation" in decision.dissent_summary
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
async def test_emphasized_action_header_preserves_archive_under_manual_review():
    gmail = _DummyGmail()
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-emphasized",
            state=ReceiptState.APPROVED if auto_approve else ReceiptState.CREATED,
        )
    )

    runner = InboxTriageRunner(gmail_connector=gmail, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(
        return_value=DebateResult(
            debate_id="debate-emphasized",
            final_answer=(
                "## ACTION: **ARCHIVE**\n\n"
                "Alternatives considered: ignore, star, or label depending on follow-up needs."
            ),
            confidence=0.5,
            consensus_reached=False,
        )
    )

    decisions = await runner.run_triage(batch_size=1, auto_approve=True)

    decision = decisions[0]
    assert wedge_service.create_receipt.call_args.kwargs["auto_approve"] is False
    assert decision.final_action == InboxWedgeAction.ARCHIVE
    assert decision.blocked_by_policy is True
    assert "No consensus reached" in decision.dissent_summary
    assert "fell back to ignore" not in decision.dissent_summary
    wedge_service.execute_receipt.assert_not_awaited()


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
    runner = InboxTriageRunner(gmail_connector=None, profile="baseline")
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
async def test_run_debate_uses_fast_agent_subset_and_explicit_action_prompt(monkeypatch):
    created_agents: list[object] = []
    captured_tasks: list[str] = []

    class _Arena:
        def __init__(self, env, agents, protocol, **kwargs):
            captured_tasks.append(env.task)
            created_agents.extend(agents)
            self.kwargs = kwargs

        async def run(self):
            return {"final_answer": "archive", "confidence": 0.9}

    def _environment(*, task):
        return SimpleNamespace(task=task)

    import aragora.core as core_mod
    import aragora.debate.orchestrator as orch_mod
    import aragora.debate.protocol as proto_mod

    monkeypatch.setattr(
        "aragora.inbox.triage_runner._create_triage_agents",
        lambda **kwargs: [
            SimpleNamespace(name="triage-proposer", role="proposer", model_type="anthropic-api"),
            SimpleNamespace(name="triage-critic", role="critic", model_type="openrouter"),
        ],
    )
    monkeypatch.setattr(core_mod, "Environment", _environment)
    monkeypatch.setattr(proto_mod, "DebateProtocol", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(orch_mod, "Arena", _Arena)

    runner = InboxTriageRunner(gmail_connector=None, profile="baseline")
    result = await runner._run_debate(
        {
            "id": "msg-prompt",
            "subject": "Prompt subject",
            "from_address": "sender@example.com",
            "body_text": "Prompt body",
        }
    )

    assert result["final_answer"] == "archive"
    assert len(created_agents) == 2
    assert len(captured_tasks) == 1
    assert "From: sender@example.com" in captured_tasks[0]
    assert "MUST begin with the action word" in captured_tasks[0]


@pytest.mark.asyncio
async def test_run_debate_disables_trending_and_post_debate_pipeline(monkeypatch):
    captured_kwargs: dict[str, object] = {}
    captured_protocol: dict[str, object] = {}

    class _Arena:
        def __init__(self, env, agents, protocol, **kwargs):
            captured_kwargs.update(kwargs)
            captured_protocol.update(protocol.__dict__)

        async def run(self):
            assert os.environ.get("ARAGORA_DISABLE_TRENDING") == "true"
            return {"final_answer": "archive", "confidence": 0.9}

    def _environment(*, task):
        return SimpleNamespace(task=task)

    import os
    import aragora.core as core_mod
    import aragora.debate.orchestrator as orch_mod
    import aragora.debate.protocol as proto_mod

    monkeypatch.delenv("ARAGORA_DISABLE_TRENDING", raising=False)
    monkeypatch.setattr(
        "aragora.inbox.triage_runner._create_triage_agents",
        lambda **kwargs: [
            SimpleNamespace(name="triage-proposer", role="proposer", model_type="openai-api"),
            SimpleNamespace(name="triage-critic", role="critic", model_type="openrouter"),
        ],
    )
    monkeypatch.setattr(core_mod, "Environment", _environment)
    monkeypatch.setattr(proto_mod, "DebateProtocol", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(orch_mod, "Arena", _Arena)

    runner = InboxTriageRunner(gmail_connector=None, profile="baseline")
    await runner._run_debate(
        {
            "id": "msg-runtime-flags",
            "subject": "Runtime flags",
            "from_address": "sender@example.com",
            "body_text": "Body",
        }
    )

    assert captured_kwargs["disable_post_debate_pipeline"] is True
    assert captured_kwargs["enable_belief_guidance"] is False
    assert captured_kwargs["enable_knowledge_retrieval"] is False
    assert captured_kwargs["use_rlm_limiter"] is False
    assert captured_protocol["convergence_detection"] is False
    assert captured_protocol["enable_research"] is False
    assert captured_protocol["vote_grouping"] is False
    assert "ARAGORA_DISABLE_TRENDING" not in os.environ


@pytest.mark.asyncio
async def test_run_debate_returns_blocked_result_when_fewer_than_two_agents(monkeypatch):
    import aragora.core as core_mod
    import aragora.debate.orchestrator as orch_mod
    import aragora.debate.protocol as proto_mod

    monkeypatch.setattr(
        "aragora.inbox.triage_runner._create_triage_agents",
        lambda **kwargs: [
            SimpleNamespace(name="triage-proposer", role="proposer", model_type="anthropic-api")
        ],
    )
    monkeypatch.setattr(core_mod, "Environment", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(proto_mod, "DebateProtocol", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(orch_mod, "Arena", MagicMock())

    runner = InboxTriageRunner(gmail_connector=None, profile="baseline")
    result = await runner._run_debate(
        {
            "id": "msg-stub",
            "subject": "Stub subject",
            "from_address": "sender@example.com",
            "body_text": "Stub body",
        }
    )

    assert result["final_answer"] == ""
    assert result["confidence"] == 0.0
    assert result["status"] == "insufficient_participation"


def test_create_triage_agents_prefers_fast_pair(monkeypatch):
    calls: list[tuple[str, str, str | None]] = []

    def fake_create_agent(
        model_type: str,
        name: str | None = None,
        role: str = "proposer",
        model: str | None = None,
        **_: object,
    ):
        calls.append((model_type, role, model))
        return {"model_type": model_type, "name": name, "role": role, "model": model}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setattr("aragora.agents.base.create_agent", fake_create_agent)

    agents = _create_triage_agents()

    assert len(agents) == 3
    assert calls == [
        ("openai-api", "proposer", "gpt-5.4"),
        ("openrouter", "critic", "deepseek/deepseek-v4-pro"),
        ("anthropic-api", "synthesizer", "claude-haiku-4-5-20251001"),
    ]


def test_create_triage_agents_falls_back_to_openai_when_needed(monkeypatch):
    calls: list[tuple[str, str, str | None]] = []

    def fake_create_agent(
        model_type: str,
        name: str | None = None,
        role: str = "proposer",
        model: str | None = None,
        **_: object,
    ):
        calls.append((model_type, role, model))
        return {"model_type": model_type, "name": name, "role": role, "model": model}

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setattr("aragora.agents.base.create_agent", fake_create_agent)

    agents = _create_triage_agents()

    assert len(agents) == 3
    assert calls == [
        ("openai-api", "proposer", "gpt-5.4"),
        ("openai-api", "critic", "gpt-5.4"),
        ("anthropic-api", "synthesizer", "claude-haiku-4-5-20251001"),
    ]


@pytest.mark.asyncio
async def test_triage_message_reattaches_subject_after_receipt_creation():
    gmail = _DummyGmail()
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()

    def _create_envelope(intent, decision, auto_approve=False):
        copied_intent = type(intent)(**intent.to_dict())
        updated = TriageDecision.create(
            final_action=decision.final_action,
            confidence=decision.confidence,
            dissent_summary=decision.dissent_summary,
            receipt_id="receipt-copy",
            auto_approval_eligible=auto_approve,
            receipt_state=ReceiptState.CREATED.value,
            intent=copied_intent,
            provider_route=decision.provider_route,
            label_id=decision.label_id,
            blocked_by_policy=decision.blocked_by_policy,
        )
        return SimpleNamespace(
            intent=copied_intent,
            decision=updated,
            receipt=SimpleNamespace(receipt_id="receipt-copy", state=ReceiptState.CREATED),
            provider_route=decision.provider_route,
        )

    wedge_service.create_receipt = MagicMock(side_effect=_create_envelope)

    runner = InboxTriageRunner(gmail_connector=gmail, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(
        return_value={
            "final_answer": "archive",
            "confidence": 0.9,
            "debate_id": "debate-copy",
        }
    )

    decisions = await runner.run_triage(batch_size=1, auto_approve=False)

    intent = decisions[0].intent
    assert intent is not None
    assert intent._subject == "Test subject"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_stub_debate_result_is_blocked_instead_of_silent_ignore(monkeypatch):
    import aragora.core as core_mod
    import aragora.debate.orchestrator as orch_mod
    import aragora.debate.protocol as proto_mod

    monkeypatch.setattr(
        "aragora.inbox.triage_runner._create_triage_agents",
        lambda **kwargs: [
            SimpleNamespace(name="triage-proposer", role="proposer", model_type="openai-api")
        ],
    )
    monkeypatch.setattr(core_mod, "Environment", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(proto_mod, "DebateProtocol", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(orch_mod, "Arena", MagicMock())

    runner = InboxTriageRunner(gmail_connector=None, profile="baseline")
    result = await runner._run_debate(
        {
            "id": "msg-stub",
            "subject": "Stub subject",
            "from_address": "sender@example.com",
            "body_text": "Stub body",
        }
    )

    assert result["final_answer"] == ""
    assert result["confidence"] == 0.0
    assert result["status"] == "insufficient_participation"


@pytest.mark.asyncio
async def test_staged_profile_uses_fast_tier_without_escalation(tmp_path):
    diagnostics = TriageRunDiagnostics(
        profile="staged_v1",
        batch_size=1,
        auto_approve=False,
        dry_run=True,
        verbose=False,
        diagnostics_dir=tmp_path,
    )
    runner = InboxTriageRunner(gmail_connector=None, diagnostics=diagnostics, profile="staged_v1")
    runner._run_fast_tier_once = AsyncMock(
        return_value={
            "final_answer": "archive",
            "confidence": 0.96,
            "consensus_reached": True,
            "debate_id": "debate-fast",
        }
    )

    with diagnostics.activate():
        result = await runner._run_debate(
            {
                "id": "msg-fast",
                "subject": "Fast path",
                "from_address": "sender@example.com",
                "body_text": "Body",
            }
        )

    execution = result["metadata"]["triage_execution"]
    assert execution["execution_tier"] == "fast"
    assert execution["escalation_reasons"] == []
    runner._run_fast_tier_once.assert_awaited_once_with(
        {
            "id": "msg-fast",
            "subject": "Fast path",
            "from_address": "sender@example.com",
            "body_text": "Body",
        },
    )


@pytest.mark.asyncio
async def test_staged_profile_escalates_high_risk_actions(tmp_path):
    diagnostics = TriageRunDiagnostics(
        profile="staged_v1",
        batch_size=1,
        auto_approve=False,
        dry_run=True,
        verbose=False,
        diagnostics_dir=tmp_path,
    )
    runner = InboxTriageRunner(gmail_connector=None, diagnostics=diagnostics, profile="staged_v1")
    runner._run_fast_tier_once = AsyncMock(
        return_value={
            "final_answer": "star",
            "confidence": 0.97,
            "consensus_reached": True,
            "debate_id": "debate-fast",
        }
    )
    runner._run_debate_once = AsyncMock(
        return_value={
            "final_answer": "archive",
            "confidence": 0.91,
            "consensus_reached": True,
            "debate_id": "debate-escalated",
        }
    )

    with diagnostics.activate(), diagnostics.message_scope("msg-escalated"):
        result = await runner._run_debate(
            {
                "id": "msg-escalated",
                "subject": "Escalate",
                "from_address": "sender@example.com",
                "body_text": "Body",
            }
        )

    execution = result["metadata"]["triage_execution"]
    assert execution["execution_tier"] == "escalated"
    assert "high_risk_action" in execution["escalation_reasons"]
    runner._run_fast_tier_once.assert_awaited_once()
    runner._run_debate_once.assert_awaited_once_with(
        {
            "id": "msg-escalated",
            "subject": "Escalate",
            "from_address": "sender@example.com",
            "body_text": "Body",
        },
        tier="escalated",
        rounds=1,
        max_agents=None,
    )
    event_codes = [
        json.loads(line)["code"]
        for line in diagnostics.events_path.read_text().splitlines()
        if line.strip()
    ]
    assert "fast_tier_escalation" in event_codes


@pytest.mark.asyncio
async def test_run_debate_once_disables_introspection(monkeypatch):
    import aragora.core as core_mod
    import aragora.debate.orchestrator as orch_mod
    import aragora.debate.protocol as proto_mod

    captured: dict[str, object] = {}

    class _FakeArena:
        def __init__(self, env, agents, protocol, **kwargs):
            captured["env"] = env
            captured["agents"] = agents
            captured["protocol"] = protocol
            captured["kwargs"] = kwargs

        async def run(self):
            return {
                "final_answer": "archive",
                "confidence": 0.91,
                "consensus_reached": True,
                "debate_id": "debate-escalated",
            }

    monkeypatch.setattr(
        "aragora.inbox.triage_runner._create_triage_agents",
        lambda max_agents=None: [
            SimpleNamespace(name="triage-proposer", role="proposer", model_type="openai-api"),
            SimpleNamespace(name="triage-critic", role="critic", model_type="openai-api"),
        ],
    )
    monkeypatch.setattr(core_mod, "Environment", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(proto_mod, "DebateProtocol", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(orch_mod, "Arena", _FakeArena)

    runner = InboxTriageRunner(gmail_connector=None, profile="staged_v1")
    result = await runner._run_debate_once(
        {
            "id": "msg-introspection",
            "subject": "Disable introspection",
            "from_address": "sender@example.com",
            "body_text": "Body",
        },
        tier="escalated",
        rounds=1,
        max_agents=None,
    )

    assert result["debate_id"] == "debate-escalated"
    assert captured["kwargs"]["enable_introspection"] is False


@pytest.mark.asyncio
async def test_staged_profile_truthfully_stops_on_no_consensus(tmp_path):
    diagnostics = TriageRunDiagnostics(
        profile="staged_v1",
        batch_size=1,
        auto_approve=False,
        dry_run=True,
        verbose=False,
        diagnostics_dir=tmp_path,
    )
    runner = InboxTriageRunner(gmail_connector=None, diagnostics=diagnostics, profile="staged_v1")
    runner._run_fast_tier_once = AsyncMock(
        return_value={
            "final_answer": "archive",
            "confidence": 0.84,
            "consensus_reached": False,
            "debate_id": "debate-no-consensus-fast",
        }
    )

    with diagnostics.activate(), diagnostics.message_scope("msg-no-consensus"):
        result = await runner._run_debate(
            {
                "id": "msg-no-consensus",
                "subject": "No consensus",
                "from_address": "sender@example.com",
                "body_text": "Body",
            }
        )

    execution = result["metadata"]["triage_execution"]
    assert execution["execution_tier"] == "fast"
    assert execution["escalation_reasons"] == ["no_consensus"]
    runner._run_fast_tier_once.assert_awaited_once()
    event_codes = [
        json.loads(line)["code"]
        for line in diagnostics.events_path.read_text().splitlines()
        if line.strip()
    ]
    assert "fast_tier_truthful_stop" in event_codes


@pytest.mark.asyncio
async def test_staged_profile_truthfully_stops_on_parse_failed_fast_result(tmp_path):
    diagnostics = TriageRunDiagnostics(
        profile="staged_v1",
        batch_size=1,
        auto_approve=False,
        dry_run=True,
        verbose=False,
        diagnostics_dir=tmp_path,
    )
    runner = InboxTriageRunner(gmail_connector=None, diagnostics=diagnostics, profile="staged_v1")
    runner._run_fast_tier_once = AsyncMock(
        return_value={
            "final_answer": "archive or ignore depending on urgency",
            "confidence": 0.94,
            "consensus_reached": True,
            "debate_id": "debate-parse-fast",
        }
    )

    with diagnostics.activate(), diagnostics.message_scope("msg-parse-fast"):
        result = await runner._run_debate(
            {
                "id": "msg-parse-fast",
                "subject": "Parse failed",
                "from_address": "sender@example.com",
                "body_text": "Body",
            }
        )

    execution = result["metadata"]["triage_execution"]
    assert execution["execution_tier"] == "fast"
    assert execution["escalation_reasons"] == ["parse_failed"]
    runner._run_fast_tier_once.assert_awaited_once()


@pytest.mark.asyncio
async def test_staged_profile_returns_blocked_timeout_without_escalation(tmp_path, monkeypatch):
    diagnostics = TriageRunDiagnostics(
        profile="staged_v1",
        batch_size=1,
        auto_approve=False,
        dry_run=True,
        verbose=False,
        diagnostics_dir=tmp_path,
    )
    runner = InboxTriageRunner(gmail_connector=None, diagnostics=diagnostics, profile="staged_v1")

    async def _slow_debate(*args, **kwargs):
        await asyncio.sleep(0.05)
        return {
            "final_answer": "archive",
            "confidence": 0.95,
            "consensus_reached": True,
            "debate_id": "debate-slow-fast",
        }

    monkeypatch.setattr("aragora.inbox.triage_runner._FAST_TIER_TIMEOUT_SECONDS", 0.01)
    runner._run_fast_tier_once = AsyncMock(side_effect=_slow_debate)

    with diagnostics.activate(), diagnostics.message_scope("msg-timeout-fast"):
        result = await runner._run_debate(
            {
                "id": "msg-timeout-fast",
                "subject": "Timeout",
                "from_address": "sender@example.com",
                "body_text": "Body",
            }
        )

    execution = result["metadata"]["triage_execution"]
    assert execution["execution_tier"] == "fast"
    assert execution["escalation_reasons"] == ["fast_timeout", "no_consensus", "parse_failed"]
    assert result["status"] == "timeout"
    runner._run_fast_tier_once.assert_awaited_once()
    event_codes = [
        json.loads(line)["code"]
        for line in diagnostics.events_path.read_text().splitlines()
        if line.strip()
    ]
    assert "fast_tier_timeout" in event_codes
    assert "fast_tier_truthful_stop" in event_codes


@pytest.mark.asyncio
async def test_triage_message_carries_execution_and_diagnostics_metadata(tmp_path):
    diagnostics = TriageRunDiagnostics(
        profile="staged_v1",
        batch_size=1,
        auto_approve=False,
        dry_run=True,
        verbose=False,
        diagnostics_dir=tmp_path,
    )
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-meta",
            state=ReceiptState.CREATED,
        )
    )
    runner = InboxTriageRunner(
        gmail_connector=None,
        wedge_service=wedge_service,
        diagnostics=diagnostics,
        profile="staged_v1",
    )
    runner._run_debate = AsyncMock(
        return_value={
            "final_answer": "archive",
            "confidence": 0.91,
            "consensus_reached": True,
            "debate_id": "debate-meta",
            "metadata": {
                "triage_execution": {
                    "execution_tier": "escalated",
                    "escalation_reasons": ["low_confidence"],
                }
            },
        }
    )

    with diagnostics.activate(), diagnostics.message_scope("msg-meta"):
        diagnostics.record_event(
            code="provider_fallback",
            severity=DiagnosticSeverity.DEGRADED,
            logger_name="aragora.server.research_phase",
            summary="Fallback to OpenRouter",
            tier="escalated",
        )
        decision = await runner._triage_message(
            {
                "id": "msg-meta",
                "subject": "Metadata",
                "from_address": "sender@example.com",
                "body_text": "Body",
            }
        )

    assert decision.execution_tier == "escalated"
    assert decision.escalation_reasons == ["low_confidence"]
    assert decision.suppressed_diagnostics_count == 1
    assert decision.blocked_by_policy is True


@pytest.mark.asyncio
async def test_debate_dispatch_error_produces_blocked_decision_not_silent_skip():
    """When _triage_message raises, run_triage must produce a blocked
    TriageDecision instead of silently dropping the message."""
    gmail = _DummyGmail()
    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock()

    runner = InboxTriageRunner(gmail_connector=gmail, wedge_service=wedge_service)
    runner._run_debate = AsyncMock(side_effect=RuntimeError("provider unreachable"))

    decisions = await runner.run_triage(batch_size=1, auto_approve=False)

    assert len(decisions) == 1, "Failed triage must still produce a decision"
    decision = decisions[0]
    assert decision.blocked_by_policy is True
    assert decision.confidence == 0.0
    assert decision.receipt_state == "blocked"
    assert "RuntimeError" in decision.dissent_summary
    assert decision.final_action == InboxWedgeAction.IGNORE


@pytest.mark.asyncio
async def test_escalated_runtime_error_stays_blocked_and_skips_fast_fallback(monkeypatch):
    import aragora.core as core_mod
    import aragora.debate.orchestrator as orch_mod
    import aragora.debate.protocol as proto_mod

    monkeypatch.setattr(
        "aragora.inbox.triage_runner._create_triage_agents",
        lambda **kwargs: [
            SimpleNamespace(name="triage-proposer", role="proposer", model_type="openai-api"),
            SimpleNamespace(name="triage-critic", role="critic", model_type="anthropic-api"),
        ],
    )
    monkeypatch.setattr(core_mod, "Environment", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(proto_mod, "DebateProtocol", lambda **kwargs: SimpleNamespace(**kwargs))

    class _BoomArena:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("debate backend down")

    monkeypatch.setattr(orch_mod, "Arena", _BoomArena)

    wedge_service = SimpleNamespace()
    wedge_service.execute_receipt = AsyncMock()
    wedge_service.create_receipt = MagicMock(
        side_effect=lambda intent, decision, auto_approve=False: _make_envelope(
            decision,
            receipt_id="receipt-escalated-failure",
            state=ReceiptState.APPROVED if auto_approve else ReceiptState.CREATED,
        )
    )

    runner = InboxTriageRunner(
        gmail_connector=None,
        wedge_service=wedge_service,
        profile="staged_v1",
    )
    runner._run_fast_tier_once = AsyncMock(
        side_effect=[
            {
                "final_answer": "star: founder-intent signal",
                "confidence": 0.97,
                "consensus_reached": True,
                "debate_id": "fast-first",
                "status": "completed",
            },
            {
                "final_answer": "archive: unsafe second guess",
                "confidence": 0.98,
                "consensus_reached": True,
                "debate_id": "fast-second",
                "status": "completed",
            },
        ]
    )

    decision = await runner._triage_message(
        {
            "id": "msg-escalated-failure",
            "subject": "Founder note",
            "from_address": "sender@example.com",
            "body_text": "Please read this",
        },
        auto_approve=True,
    )

    assert decision.final_action == InboxWedgeAction.IGNORE
    assert decision.blocked_by_policy is True
    assert decision.receipt_state == ReceiptState.CREATED.value
    assert decision.execution_tier == "escalated"
    assert decision.escalation_reasons == ["high_risk_action"]
    assert "runtime error" in decision.dissent_summary.lower()
    assert runner._run_fast_tier_once.await_count == 1
