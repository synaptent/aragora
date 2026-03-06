from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.gauntlet.signing import HMACSigner, ReceiptSigner
from aragora.inbox.trust_wedge import (
    ActionIntent,
    InboxTrustWedgeService,
    InboxTrustWedgeStore,
    TriageDecision,
)
from aragora.server.handlers.inbox.trust_wedge_handler import InboxTrustWedgeHandler
from aragora.services.email_actions import EmailActionsService


def _body(result) -> dict:
    if isinstance(result.body, bytes):
        return json.loads(result.body.decode("utf-8"))
    return result.body


@pytest.fixture
def handler():
    return InboxTrustWedgeHandler({})


@pytest.fixture
def http_get():
    request = MagicMock()
    request.command = "GET"
    return request


@pytest.fixture
def http_post():
    request = MagicMock()
    request.command = "POST"
    return request


@pytest.fixture
def wedge_service(tmp_path):
    signer = ReceiptSigner(HMACSigner(secret_key=b"\x05" * 32, key_id="handler-http-key"))
    store = InboxTrustWedgeStore(db_path=str(tmp_path / "handler-wedge.db"))
    email_actions = EmailActionsService()
    connector = AsyncMock()
    connector.archive_message = AsyncMock(return_value={"archived": True})
    email_actions._connectors["gmail:user-1"] = connector
    service = InboxTrustWedgeService(
        email_actions_service=email_actions,
        store=store,
        signer=signer,
    )
    yield service, store, connector
    store.close()


def test_list_receipts_returns_pending_wedge_receipts(handler, http_get, wedge_service):
    service, _store, _connector = wedge_service
    envelope = service.create_receipt(
        ActionIntent.create(
            provider="gmail",
            user_id="user-1",
            message_id="msg-1",
            action="archive",
            content_hash=ActionIntent.compute_content_hash("subject", "body"),
            synthesized_rationale="Archive low-priority message",
            confidence=0.91,
            provider_route="openrouter-fallback",
            debate_id="debate-http-1",
        ),
        TriageDecision.create(
            final_action="archive",
            confidence=0.91,
            dissent_summary="",
        ),
    )

    with patch.object(
        handler, "require_permission_or_error", return_value=(MagicMock(user_id="user-1"), None)
    ):
        with patch(
            "aragora.server.handlers.inbox.trust_wedge_handler.get_inbox_trust_wedge_service_instance",
            return_value=service,
        ):
            result = handler.handle("/api/v1/inbox/wedge/receipts", {"state": "created"}, http_get)

    assert result.status_code == 200
    body = _body(result)
    assert body["count"] == 1
    assert body["receipts"][0]["receipt"]["receipt_id"] == envelope.receipt.receipt_id


def test_review_route_can_approve_and_execute(handler, http_post, wedge_service):
    service, store, connector = wedge_service
    envelope = service.create_receipt(
        ActionIntent.create(
            provider="gmail",
            user_id="user-1",
            message_id="msg-1",
            action="archive",
            content_hash=ActionIntent.compute_content_hash("subject", "body"),
            synthesized_rationale="Archive after review",
            confidence=0.93,
            provider_route="openrouter-fallback",
            debate_id="debate-http-2",
        ),
        TriageDecision.create(
            final_action="archive",
            confidence=0.93,
            dissent_summary="",
        ),
    )

    with patch.object(
        handler, "require_permission_or_error", return_value=(MagicMock(user_id="user-1"), None)
    ):
        with patch.object(
            handler, "read_json_body", return_value={"choice": "approve", "execute": True}
        ):
            with patch(
                "aragora.server.handlers.inbox.trust_wedge_handler.get_inbox_trust_wedge_service_instance",
                return_value=service,
            ):
                result = handler.handle(
                    f"/api/v1/inbox/wedge/receipts/{envelope.receipt.receipt_id}/review",
                    {},
                    http_post,
                )

    assert result.status_code == 200
    body = _body(result)
    stored = store.get_receipt(envelope.receipt.receipt_id)
    assert body["executed"] is True
    assert stored is not None
    assert stored.receipt.state.value == "executed"
    connector.archive_message.assert_called_once_with("msg-1")
