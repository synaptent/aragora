from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest

from aragora.gauntlet.signing import HMACSigner, ReceiptSigner
from aragora.inbox.trust_wedge import (
    ActionIntent,
    InboxTrustWedgeService,
    InboxTrustWedgeStore,
    InboxWedgeAction,
    ReceiptState,
    TriageDecision,
)
from aragora.services.email_actions import EmailActionsService


def _build_intent(
    *,
    action: str = "archive",
    label_id: str | None = None,
) -> ActionIntent:
    return ActionIntent.create(
        provider="gmail",
        user_id="user-1",
        message_id="msg-1",
        action=action,
        content_hash=ActionIntent.compute_content_hash("subject", "body"),
        synthesized_rationale="Debated rationale",
        confidence=0.91,
        provider_route="openrouter-fallback",
        debate_id="debate-123",
        label_id=label_id,
    )


def _build_decision(
    *,
    action: str = "archive",
    confidence: float = 0.91,
    blocked_by_policy: bool = False,
    label_id: str | None = None,
) -> TriageDecision:
    return TriageDecision.create(
        final_action=action,
        confidence=confidence,
        dissent_summary="critic noted possible edge case",
        blocked_by_policy=blocked_by_policy,
        label_id=label_id,
    )


@pytest.fixture
def wedge(tmp_path):
    signer = ReceiptSigner(HMACSigner(secret_key=b"\x01" * 32, key_id="test-inbox-key"))
    store = InboxTrustWedgeStore(db_path=str(tmp_path / "wedge.db"))
    email_actions = EmailActionsService()
    connector = AsyncMock()
    connector.send_message = AsyncMock(return_value={"message_id": "sent"})
    connector.reply_to_message = AsyncMock(return_value={"message_id": "reply"})
    connector.archive_message = AsyncMock(return_value={"archived": True})
    connector.trash_message = AsyncMock(return_value={"trashed": True})
    connector.snooze_message = AsyncMock(return_value={"snoozed": True})
    connector.mark_as_read = AsyncMock(return_value={"read": True})
    connector.star_message = AsyncMock(return_value={"starred": True})
    connector.add_label = AsyncMock(return_value={"labels": ["TRIAGE"]})
    connector.move_to_folder = AsyncMock(return_value={"moved": True})
    connector.batch_archive = AsyncMock(return_value={"archived_count": 1})
    email_actions._connectors["gmail:user-1"] = connector
    service = InboxTrustWedgeService(
        email_actions_service=email_actions,
        store=store,
        signer=signer,
        auto_approval_threshold=0.85,
    )
    yield store, service, connector
    store.close()


@pytest.mark.asyncio
async def test_execute_requires_preexisting_approved_receipt(wedge):
    _, service, connector = wedge
    envelope = service.create_receipt(_build_intent(), _build_decision())

    with pytest.raises(ValueError, match="receipt state must be approved"):
        await service.execute_receipt(envelope.receipt.receipt_id)

    connector.archive_message.assert_not_called()


@pytest.mark.asyncio
async def test_archive_executes_only_after_approval(wedge):
    store, service, connector = wedge
    envelope = service.create_receipt(_build_intent(), _build_decision())

    approved = service.review_receipt(envelope.receipt.receipt_id, choice="approve")
    assert approved.receipt.state == ReceiptState.APPROVED

    result = await service.execute_receipt(envelope.receipt.receipt_id)
    stored = store.get_receipt(envelope.receipt.receipt_id)

    assert result.success is True
    assert stored is not None
    assert stored.receipt.state == ReceiptState.EXECUTED
    assert stored.receipt.execution_count == 1
    connector.archive_message.assert_called_once_with("msg-1")


def test_invalid_signature_blocks_approval(wedge):
    store, service, _ = wedge
    envelope = service.create_receipt(_build_intent(), _build_decision())
    store.tamper_signed_receipt_for_tests(envelope.receipt.receipt_id, signature="tampered")

    with pytest.raises(ValueError, match="signature verification failed"):
        service.review_receipt(envelope.receipt.receipt_id, choice="approve")


@pytest.mark.asyncio
async def test_expired_receipt_blocks_execution(wedge):
    store, service, connector = wedge
    envelope = service.create_receipt(_build_intent(), _build_decision())
    service.review_receipt(envelope.receipt.receipt_id, choice="approve")
    with store._cursor() as cursor:
        cursor.execute(
            """
            UPDATE inbox_trust_receipts
            SET expires_at = ?
            WHERE receipt_id = ?
            """,
            (
                (envelope.receipt.created_at - timedelta(minutes=1)).isoformat(),
                envelope.receipt.receipt_id,
            ),
        )

    with pytest.raises(ValueError, match="receipt expired"):
        await service.execute_receipt(envelope.receipt.receipt_id)

    connector.archive_message.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_execution_is_blocked(wedge):
    _, service, connector = wedge
    envelope = service.create_receipt(_build_intent(), _build_decision())
    service.review_receipt(envelope.receipt.receipt_id, choice="approve")

    await service.execute_receipt(envelope.receipt.receipt_id)

    with pytest.raises(ValueError, match="receipt already executed"):
        await service.execute_receipt(envelope.receipt.receipt_id)

    connector.archive_message.assert_called_once()


def test_intent_hash_mismatch_blocks_approval(wedge):
    store, service, _ = wedge
    envelope = service.create_receipt(_build_intent(), _build_decision())
    store.tamper_intent_for_tests(envelope.receipt.receipt_id, action="star")

    with pytest.raises(ValueError, match="intent hash mismatch"):
        service.review_receipt(envelope.receipt.receipt_id, choice="approve")


def test_edit_review_updates_action_and_signature_material(wedge):
    store, service, _ = wedge
    envelope = service.create_receipt(_build_intent(), _build_decision())

    edited = service.review_receipt(
        envelope.receipt.receipt_id,
        choice="edit",
        edited_action="star",
        edited_rationale="Edited rationale",
    )
    stored = store.get_receipt(envelope.receipt.receipt_id)

    assert edited.intent.action == InboxWedgeAction.STAR
    assert edited.intent.synthesized_rationale == "Edited rationale"
    assert edited.receipt.state == ReceiptState.CREATED
    assert stored is not None
    assert stored.receipt.signature != envelope.receipt.signature


def test_auto_approval_stays_narrow(wedge):
    _, service, _ = wedge

    auto_archive = service.create_receipt(
        _build_intent(action="archive"),
        _build_decision(action="archive", confidence=0.9),
        auto_approve=True,
    )
    manual_label = service.create_receipt(
        _build_intent(action="label", label_id="TRIAGE"),
        _build_decision(action="label", confidence=0.99, label_id="TRIAGE"),
        auto_approve=True,
    )
    blocked_archive = service.create_receipt(
        _build_intent(action="archive"),
        _build_decision(action="archive", confidence=0.9, blocked_by_policy=True),
        auto_approve=True,
    )

    assert auto_archive.receipt.state == ReceiptState.APPROVED
    assert manual_label.receipt.state == ReceiptState.CREATED
    assert blocked_archive.receipt.state == ReceiptState.CREATED


def test_action_intent_to_dict_tolerates_string_action():
    intent = ActionIntent(
        provider="gmail",
        user_id="user-1",
        message_id="msg-1",
        action="archive",
        content_hash=ActionIntent.compute_content_hash("subject", "body"),
        synthesized_rationale="Debated rationale",
        confidence=0.91,
        provider_route="openrouter-fallback",
        debate_id="debate-123",
    )

    payload = intent.to_dict()

    assert payload["action"] == "archive"


@pytest.mark.asyncio
async def test_label_action_uses_real_label_path(wedge):
    _, service, connector = wedge
    envelope = service.create_receipt(
        _build_intent(action="label", label_id="TRIAGE"),
        _build_decision(action="label", confidence=0.92, label_id="TRIAGE"),
    )
    service.review_receipt(envelope.receipt.receipt_id, choice="approve")

    result = await service.execute_receipt(envelope.receipt.receipt_id)

    assert result.success is True
    connector.add_label.assert_called_once_with("msg-1", "TRIAGE")
