from __future__ import annotations

from unittest.mock import patch

from aragora.approvals.inbox import DEFAULT_APPROVAL_SOURCES, collect_pending_approvals
from aragora.gauntlet.signing import HMACSigner, ReceiptSigner
from aragora.inbox.trust_wedge import (
    ActionIntent,
    InboxTrustWedgeService,
    InboxTrustWedgeStore,
    TriageDecision,
)
from aragora.services.email_actions import EmailActionsService


def test_default_approval_sources_include_inbox_wedge():
    assert "inbox_wedge" in DEFAULT_APPROVAL_SOURCES


def test_collect_pending_approvals_includes_inbox_wedge_receipts(tmp_path):
    signer = ReceiptSigner(HMACSigner(secret_key=b"\x04" * 32, key_id="approval-test-key"))
    store = InboxTrustWedgeStore(db_path=str(tmp_path / "approvals-wedge.db"))
    service = InboxTrustWedgeService(
        email_actions_service=EmailActionsService(),
        store=store,
        signer=signer,
    )
    envelope = service.create_receipt(
        ActionIntent.create(
            provider="gmail",
            user_id="user-1",
            message_id="msg-1",
            action="archive",
            content_hash=ActionIntent.compute_content_hash("subject", "body"),
            synthesized_rationale="Archive promotional noise",
            confidence=0.9,
            provider_route="openrouter-fallback",
            debate_id="debate-approval-1",
        ),
        TriageDecision.create(
            final_action="archive",
            confidence=0.9,
            dissent_summary="critic asked for a quick human check",
        ),
    )

    with patch("aragora.inbox.get_inbox_trust_wedge_store", return_value=store):
        approvals = collect_pending_approvals(limit=10, sources=["inbox_wedge"])

    store.close()

    assert len(approvals) == 1
    item = approvals[0]
    assert item["id"] == envelope.receipt.receipt_id
    assert item["kind"] == "inbox_wedge"
    assert item["metadata"]["message_id"] == "msg-1"
    assert item["actions"]["approve"]["path"].endswith(
        f"/api/v1/inbox/wedge/receipts/{envelope.receipt.receipt_id}/review"
    )
    assert item["actions"]["approve"]["body"] == {"choice": "approve", "execute": True}
