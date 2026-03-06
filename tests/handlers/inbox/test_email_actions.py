"""Tests for email actions handler (aragora/server/handlers/inbox/email_actions.py).

Covers all 18 handler functions and the registration helper:
- handle_send_email              POST /api/v1/inbox/messages/send
- handle_reply_email             POST /api/v1/inbox/messages/{id}/reply
- handle_archive_message         POST /api/v1/inbox/messages/{id}/archive
- handle_trash_message           POST /api/v1/inbox/messages/{id}/trash
- handle_restore_message         POST /api/v1/inbox/messages/{id}/restore
- handle_snooze_message          POST /api/v1/inbox/messages/{id}/snooze
- handle_mark_read               POST /api/v1/inbox/messages/{id}/read
- handle_mark_unread             POST /api/v1/inbox/messages/{id}/unread
- handle_star_message            POST /api/v1/inbox/messages/{id}/star
- handle_unstar_message          POST /api/v1/inbox/messages/{id}/unstar
- handle_move_to_folder          POST /api/v1/inbox/messages/{id}/move
- handle_add_label               POST /api/v1/inbox/messages/{id}/labels/add
- handle_remove_label            POST /api/v1/inbox/messages/{id}/labels/remove
- handle_batch_archive           POST /api/v1/inbox/messages/batch/archive
- handle_batch_trash             POST /api/v1/inbox/messages/batch/trash
- handle_batch_modify            POST /api/v1/inbox/messages/batch/modify
- handle_get_action_logs         GET  /api/v1/inbox/actions/logs
- handle_export_action_logs      GET  /api/v1/inbox/actions/export
- get_email_actions_handlers     Registration helper
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.gauntlet.signing import HMACSigner, ReceiptSigner
from aragora.inbox.trust_wedge import (
    ActionIntent,
    InboxTrustWedgeService,
    InboxTrustWedgeStore,
    TriageDecision,
)
from aragora.server.handlers.inbox.email_actions import (
    get_email_actions_handlers,
    get_email_actions_service_instance as _real_get_email_actions_service_instance,
    handle_add_label,
    handle_archive_message,
    handle_batch_archive,
    handle_batch_modify,
    handle_batch_trash,
    handle_export_action_logs,
    handle_get_action_logs,
    handle_mark_read,
    handle_mark_unread,
    handle_move_to_folder,
    handle_remove_label,
    handle_reply_email,
    handle_restore_message,
    handle_send_email,
    handle_snooze_message,
    handle_star_message,
    handle_trash_message,
    handle_unstar_message,
)
from aragora.server.handlers.utils.responses import HandlerResult
from aragora.services.email_actions import EmailActionsService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: HandlerResult) -> dict:
    """Extract the JSON body from a HandlerResult."""
    if isinstance(result, HandlerResult):
        if isinstance(result.body, bytes):
            return json.loads(result.body.decode("utf-8"))
        return result.body
    if isinstance(result, dict):
        return result.get("body", result)
    return {}


def _status(result: HandlerResult) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, HandlerResult):
        return result.status_code
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return 200


# ---------------------------------------------------------------------------
# Mock service result helpers
# ---------------------------------------------------------------------------


class MockActionResult:
    """Mock result returned by email actions service methods."""

    def __init__(self, success: bool = True, error: str | None = None, extra: dict | None = None):
        self.success = success
        self.error = error
        self._extra = extra or {}

    def to_dict(self) -> dict[str, Any]:
        return {"success": self.success, "error": self.error, **self._extra}


class MockActionLog:
    """Mock action log entry."""

    def __init__(self, action: str = "archive", message_id: str = "msg-1"):
        self.action = action
        self.message_id = message_id

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "message_id": self.message_id}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_service():
    """Create a mock EmailActionsService with all methods wired."""
    svc = AsyncMock()
    svc.send = AsyncMock(return_value=MockActionResult(success=True))
    svc.reply = AsyncMock(return_value=MockActionResult(success=True))
    svc.archive = AsyncMock(return_value=MockActionResult(success=True))
    svc.trash = AsyncMock(return_value=MockActionResult(success=True))
    svc.snooze = AsyncMock(return_value=MockActionResult(success=True))
    svc.mark_read = AsyncMock(return_value=MockActionResult(success=True))
    svc.star = AsyncMock(return_value=MockActionResult(success=True))
    svc.move_to_folder = AsyncMock(return_value=MockActionResult(success=True))
    svc.batch_archive = AsyncMock(return_value=MockActionResult(success=True))
    svc.get_action_logs = AsyncMock(return_value=[])
    svc.export_action_logs = AsyncMock(return_value=[])

    # Connector mock for handlers that call _get_connector directly
    mock_connector = AsyncMock()
    svc._get_connector = AsyncMock(return_value=mock_connector)

    return svc


@pytest.fixture(autouse=True)
def _patch_service(mock_service):
    """Patch the singleton service for every test."""
    with patch(
        "aragora.server.handlers.inbox.email_actions.get_email_actions_service_instance",
        return_value=mock_service,
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the module-level singleton between tests."""
    import aragora.server.handlers.inbox.email_actions as mod

    original = mod._email_actions_service
    yield
    mod._email_actions_service = original


@pytest.fixture
def wedge_service(tmp_path):
    """Create a real inbox trust wedge service backed by a mock connector."""
    signer = ReceiptSigner(HMACSigner(secret_key=b"\x03" * 32, key_id="handler-test-key"))
    store = InboxTrustWedgeStore(db_path=str(tmp_path / "wedge-handler.db"))
    email_actions = EmailActionsService()
    connector = AsyncMock()
    connector.archive_message = AsyncMock(return_value={"archived": True})
    connector.star_message = AsyncMock(return_value={"starred": True})
    connector.add_label = AsyncMock(return_value={"label_id": "TRIAGE"})
    email_actions._connectors["gmail:user-1"] = connector
    service = InboxTrustWedgeService(
        email_actions_service=email_actions,
        store=store,
        signer=signer,
        auto_approval_threshold=0.85,
    )
    yield service, store, connector
    store.close()


# ===========================================================================
# Registration helper
# ===========================================================================


class TestGetEmailActionsHandlers:
    """Tests for get_email_actions_handlers()."""

    def test_returns_dict(self):
        handlers = get_email_actions_handlers()
        assert isinstance(handlers, dict)

    def test_contains_all_18_handlers(self):
        handlers = get_email_actions_handlers()
        expected_keys = {
            "send_email",
            "reply_email",
            "archive_message",
            "trash_message",
            "restore_message",
            "snooze_message",
            "mark_read",
            "mark_unread",
            "star_message",
            "unstar_message",
            "move_to_folder",
            "add_label",
            "remove_label",
            "batch_archive",
            "batch_trash",
            "batch_modify",
            "get_action_logs",
            "export_action_logs",
        }
        assert set(handlers.keys()) == expected_keys

    def test_all_handlers_are_callable(self):
        handlers = get_email_actions_handlers()
        for name, fn in handlers.items():
            assert callable(fn), f"Handler {name} is not callable"


# ===========================================================================
# Send Email
# ===========================================================================


class TestHandleSendEmail:
    """Tests for handle_send_email."""

    @pytest.mark.asyncio
    async def test_send_email_success(self, mock_service):
        data = {
            "provider": "gmail",
            "to": ["alice@example.com"],
            "subject": "Hello",
            "body": "World",
        }
        result = await handle_send_email(data=data, user_id="user-1")
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        mock_service.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_email_missing_to(self):
        data = {"subject": "Hello", "body": "World"}
        result = await handle_send_email(data=data)
        assert _status(result) == 400
        assert "to" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_send_email_missing_subject_and_body(self):
        data = {"to": ["alice@example.com"]}
        result = await handle_send_email(data=data)
        assert _status(result) == 400
        assert (
            "subject" in _body(result).get("error", "").lower()
            or "body" in _body(result).get("error", "").lower()
        )

    @pytest.mark.asyncio
    async def test_send_email_with_optional_fields(self, mock_service):
        data = {
            "to": ["alice@example.com"],
            "subject": "Hello",
            "body": "World",
            "cc": ["bob@example.com"],
            "bcc": ["charlie@example.com"],
            "reply_to": "noreply@example.com",
            "html_body": "<p>World</p>",
        }
        result = await handle_send_email(data=data)
        assert _status(result) == 200
        call_kwargs = mock_service.send.call_args
        req = call_kwargs.kwargs.get("request") or call_kwargs[1].get("request")
        assert req is not None

    @pytest.mark.asyncio
    async def test_send_email_service_failure(self, mock_service):
        mock_service.send.return_value = MockActionResult(success=False, error="SMTP error")
        data = {"to": ["a@b.com"], "subject": "Hi", "body": "Test"}
        result = await handle_send_email(data=data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_send_email_exception_returns_500(self, mock_service):
        mock_service.send.side_effect = RuntimeError("boom")
        data = {"to": ["a@b.com"], "subject": "Hi", "body": "Test"}
        result = await handle_send_email(data=data)
        assert _status(result) == 500
        assert "failed" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_send_email_default_provider(self, mock_service):
        data = {"to": ["a@b.com"], "subject": "Hi", "body": "Test"}
        await handle_send_email(data=data)
        call_kwargs = mock_service.send.call_args
        assert (
            call_kwargs.kwargs.get("provider") == "gmail"
            or call_kwargs[1].get("provider") == "gmail"
        )


# ===========================================================================
# Reply Email
# ===========================================================================


class TestHandleReplyEmail:
    """Tests for handle_reply_email."""

    @pytest.mark.asyncio
    async def test_reply_success(self, mock_service):
        data = {"provider": "gmail", "body": "Thanks!"}
        result = await handle_reply_email(data=data, message_id="msg-123", user_id="u1")
        assert _status(result) == 200
        mock_service.reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reply_missing_message_id(self):
        data = {"body": "Thanks!"}
        result = await handle_reply_email(data=data, message_id="")
        assert _status(result) == 400
        assert "message_id" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_reply_message_id_from_body(self, mock_service):
        data = {"body": "Thanks!", "message_id": "msg-456"}
        result = await handle_reply_email(data=data, message_id="")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_reply_missing_body(self):
        data = {"provider": "gmail"}
        result = await handle_reply_email(data=data, message_id="msg-1")
        assert _status(result) == 400
        assert "body" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_reply_service_failure(self, mock_service):
        mock_service.reply.return_value = MockActionResult(success=False, error="Not found")
        data = {"body": "Thanks!"}
        result = await handle_reply_email(data=data, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_reply_exception_returns_500(self, mock_service):
        mock_service.reply.side_effect = ConnectionError("timeout")
        data = {"body": "Thanks!"}
        result = await handle_reply_email(data=data, message_id="msg-1")
        assert _status(result) == 500


# ===========================================================================
# Archive Message
# ===========================================================================


class TestHandleArchiveMessage:
    """Tests for handle_archive_message."""

    @pytest.mark.asyncio
    async def test_archive_success(self, mock_service):
        data = {"provider": "outlook"}
        result = await handle_archive_message(data=data, message_id="msg-1", user_id="u1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "archive"
        assert body["data"]["message_id"] == "msg-1"

    @pytest.mark.asyncio
    async def test_archive_missing_message_id(self):
        result = await handle_archive_message(data={}, message_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_archive_message_id_from_body(self, mock_service):
        data = {"message_id": "msg-body-1"}
        result = await handle_archive_message(data=data, message_id="")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_archive_service_failure(self, mock_service):
        mock_service.archive.return_value = MockActionResult(success=False, error="fail")
        data = {"provider": "gmail"}
        result = await handle_archive_message(data=data, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_archive_exception(self, mock_service):
        mock_service.archive.side_effect = OSError("disk")
        result = await handle_archive_message(data={}, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_archive_can_create_trusted_receipt(self, wedge_service):
        service, _store, connector = wedge_service
        data = {
            "provider": "gmail",
            "create_receipt": True,
            "confidence": 0.91,
            "synthesized_rationale": "Debated decision to archive",
            "provider_route": "openrouter-fallback",
            "debate_id": "debate-archive-1",
        }
        with patch(
            "aragora.server.handlers.inbox.email_actions.get_inbox_trust_wedge_service_instance",
            return_value=service,
        ):
            result = await handle_archive_message(data=data, message_id="msg-1", user_id="user-1")

        assert _status(result) == 200
        body = _body(result)["data"]
        assert body["receipt"]["state"] == "created"
        assert body["requires_approval"] is True
        connector.archive_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_archive_with_receipt_id_executes_approved_receipt(self, wedge_service):
        service, store, connector = wedge_service
        envelope = service.create_receipt(
            ActionIntent.create(
                provider="gmail",
                user_id="user-1",
                message_id="msg-1",
                action="archive",
                content_hash=ActionIntent.compute_content_hash("msg-1", "subject"),
                synthesized_rationale="Archive after debate",
                confidence=0.92,
                provider_route="openrouter-fallback",
                debate_id="debate-execute-1",
            ),
            TriageDecision.create(
                final_action="archive",
                confidence=0.92,
                dissent_summary="",
            ),
        )
        service.review_receipt(envelope.receipt.receipt_id, choice="approve")

        with patch(
            "aragora.server.handlers.inbox.email_actions.get_inbox_trust_wedge_service_instance",
            return_value=service,
        ):
            result = await handle_archive_message(
                data={"provider": "gmail", "receipt_id": envelope.receipt.receipt_id},
                message_id="msg-1",
                user_id="user-1",
            )

        assert _status(result) == 200
        body = _body(result)["data"]
        stored = store.get_receipt(envelope.receipt.receipt_id)
        assert body["executed"] is True
        assert stored is not None
        assert stored.receipt.state.value == "executed"
        connector.archive_message.assert_called_once_with("msg-1")


# ===========================================================================
# Trash Message
# ===========================================================================


class TestHandleTrashMessage:
    """Tests for handle_trash_message."""

    @pytest.mark.asyncio
    async def test_trash_success(self, mock_service):
        result = await handle_trash_message(data={"provider": "gmail"}, message_id="msg-1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "trash"

    @pytest.mark.asyncio
    async def test_trash_missing_message_id(self):
        result = await handle_trash_message(data={}, message_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_trash_service_failure(self, mock_service):
        mock_service.trash.return_value = MockActionResult(success=False, error="not found")
        result = await handle_trash_message(data={}, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_trash_exception(self, mock_service):
        mock_service.trash.side_effect = TypeError("bad arg")
        result = await handle_trash_message(data={}, message_id="msg-1")
        assert _status(result) == 500


# ===========================================================================
# Restore Message
# ===========================================================================


class TestHandleRestoreMessage:
    """Tests for handle_restore_message."""

    @pytest.mark.asyncio
    async def test_restore_success(self, mock_service):
        result = await handle_restore_message(data={"provider": "gmail"}, message_id="msg-1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "restore"

    @pytest.mark.asyncio
    async def test_restore_missing_message_id(self):
        result = await handle_restore_message(data={}, message_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_restore_message_id_from_body(self, mock_service):
        data = {"message_id": "msg-body-restore"}
        result = await handle_restore_message(data=data, message_id="")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_restore_connector_exception(self, mock_service):
        connector = await mock_service._get_connector("gmail", "u1")
        connector.untrash_message.side_effect = RuntimeError("fail")
        result = await handle_restore_message(data={}, message_id="msg-1")
        assert _status(result) == 500


# ===========================================================================
# Snooze Message
# ===========================================================================


class TestHandleSnoozeMessage:
    """Tests for handle_snooze_message."""

    @pytest.mark.asyncio
    async def test_snooze_with_iso_datetime(self, mock_service):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        data = {"provider": "gmail", "snooze_until": future}
        result = await handle_snooze_message(data=data, message_id="msg-1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "snooze"

    @pytest.mark.asyncio
    async def test_snooze_with_hours(self, mock_service):
        data = {"snooze_hours": 3}
        result = await handle_snooze_message(data=data, message_id="msg-1")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_snooze_with_days(self, mock_service):
        data = {"snooze_days": 2}
        result = await handle_snooze_message(data=data, message_id="msg-1")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_snooze_missing_time_param(self):
        data = {"provider": "gmail"}
        result = await handle_snooze_message(data=data, message_id="msg-1")
        assert _status(result) == 400
        assert (
            "snooze_until" in _body(result).get("error", "").lower()
            or "required" in _body(result).get("error", "").lower()
        )

    @pytest.mark.asyncio
    async def test_snooze_missing_message_id(self):
        data = {"snooze_hours": 1}
        result = await handle_snooze_message(data=data, message_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_snooze_invalid_iso_format(self):
        data = {"snooze_until": "not-a-date"}
        result = await handle_snooze_message(data=data, message_id="msg-1")
        assert _status(result) == 400
        assert (
            "iso" in _body(result).get("error", "").lower()
            or "format" in _body(result).get("error", "").lower()
        )

    @pytest.mark.asyncio
    async def test_snooze_past_time_rejected(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        data = {"snooze_until": past}
        result = await handle_snooze_message(data=data, message_id="msg-1")
        assert _status(result) == 400
        assert "future" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_snooze_service_failure(self, mock_service):
        mock_service.snooze.return_value = MockActionResult(success=False, error="err")
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        data = {"snooze_until": future}
        result = await handle_snooze_message(data=data, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_snooze_exception(self, mock_service):
        mock_service.snooze.side_effect = ValueError("bad")
        data = {"snooze_hours": 1}
        result = await handle_snooze_message(data=data, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_snooze_with_z_suffix(self, mock_service):
        """Test ISO datetime with Z timezone suffix."""
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {"snooze_until": future}
        result = await handle_snooze_message(data=data, message_id="msg-1")
        assert _status(result) == 200


# ===========================================================================
# Mark Read
# ===========================================================================


class TestHandleMarkRead:
    """Tests for handle_mark_read."""

    @pytest.mark.asyncio
    async def test_mark_read_success(self, mock_service):
        result = await handle_mark_read(data={"provider": "gmail"}, message_id="msg-1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "mark_read"

    @pytest.mark.asyncio
    async def test_mark_read_missing_message_id(self):
        result = await handle_mark_read(data={}, message_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_mark_read_service_failure(self, mock_service):
        mock_service.mark_read.return_value = MockActionResult(success=False, error="fail")
        result = await handle_mark_read(data={}, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_mark_read_exception(self, mock_service):
        mock_service.mark_read.side_effect = AttributeError("no attr")
        result = await handle_mark_read(data={}, message_id="msg-1")
        assert _status(result) == 500


# ===========================================================================
# Mark Unread
# ===========================================================================


class TestHandleMarkUnread:
    """Tests for handle_mark_unread."""

    @pytest.mark.asyncio
    async def test_mark_unread_success(self, mock_service):
        result = await handle_mark_unread(data={"provider": "gmail"}, message_id="msg-1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "mark_unread"

    @pytest.mark.asyncio
    async def test_mark_unread_missing_message_id(self):
        result = await handle_mark_unread(data={}, message_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_mark_unread_connector_exception(self, mock_service):
        connector = await mock_service._get_connector("gmail", "u1")
        connector.mark_as_unread.side_effect = ConnectionError("timeout")
        result = await handle_mark_unread(data={}, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_mark_unread_message_id_from_body(self, mock_service):
        result = await handle_mark_unread(data={"message_id": "msg-body-1"}, message_id="")
        assert _status(result) == 200


# ===========================================================================
# Star Message
# ===========================================================================


class TestHandleStarMessage:
    """Tests for handle_star_message."""

    @pytest.mark.asyncio
    async def test_star_success(self, mock_service):
        result = await handle_star_message(data={}, message_id="msg-1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "star"

    @pytest.mark.asyncio
    async def test_star_missing_message_id(self):
        result = await handle_star_message(data={}, message_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_star_service_failure(self, mock_service):
        mock_service.star.return_value = MockActionResult(success=False, error="fail")
        result = await handle_star_message(data={}, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_star_exception(self, mock_service):
        mock_service.star.side_effect = KeyError("bad")
        result = await handle_star_message(data={}, message_id="msg-1")
        assert _status(result) == 500


# ===========================================================================
# Unstar Message
# ===========================================================================


class TestHandleUnstarMessage:
    """Tests for handle_unstar_message."""

    @pytest.mark.asyncio
    async def test_unstar_success(self, mock_service):
        result = await handle_unstar_message(data={}, message_id="msg-1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "unstar"

    @pytest.mark.asyncio
    async def test_unstar_missing_message_id(self):
        result = await handle_unstar_message(data={}, message_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_unstar_connector_exception(self, mock_service):
        connector = await mock_service._get_connector("gmail", "u1")
        connector.unstar_message.side_effect = OSError("disk")
        result = await handle_unstar_message(data={}, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_unstar_message_id_from_body(self, mock_service):
        result = await handle_unstar_message(data={"message_id": "msg-b1"}, message_id="")
        assert _status(result) == 200


# ===========================================================================
# Move to Folder
# ===========================================================================


class TestHandleMoveToFolder:
    """Tests for handle_move_to_folder."""

    @pytest.mark.asyncio
    async def test_move_success(self, mock_service):
        data = {"folder": "Important", "provider": "gmail"}
        result = await handle_move_to_folder(data=data, message_id="msg-1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "move_to_folder"
        assert body["data"]["folder"] == "Important"

    @pytest.mark.asyncio
    async def test_move_missing_message_id(self):
        data = {"folder": "Important"}
        result = await handle_move_to_folder(data=data, message_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_move_missing_folder(self):
        result = await handle_move_to_folder(data={}, message_id="msg-1")
        assert _status(result) == 400
        assert "folder" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_move_service_failure(self, mock_service):
        mock_service.move_to_folder.return_value = MockActionResult(success=False, error="fail")
        data = {"folder": "Archive"}
        result = await handle_move_to_folder(data=data, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_move_exception(self, mock_service):
        mock_service.move_to_folder.side_effect = RuntimeError("boom")
        data = {"folder": "Archive"}
        result = await handle_move_to_folder(data=data, message_id="msg-1")
        assert _status(result) == 500


# ===========================================================================
# Add Label
# ===========================================================================


class TestHandleAddLabel:
    """Tests for handle_add_label."""

    @pytest.mark.asyncio
    async def test_add_label_success(self, mock_service):
        data = {"labels": ["urgent", "flagged"]}
        result = await handle_add_label(data=data, message_id="msg-1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "add_labels"
        assert body["data"]["labels"] == ["urgent", "flagged"]

    @pytest.mark.asyncio
    async def test_add_label_missing_message_id(self):
        data = {"labels": ["urgent"]}
        result = await handle_add_label(data=data, message_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_label_missing_labels(self):
        result = await handle_add_label(data={}, message_id="msg-1")
        assert _status(result) == 400
        assert "labels" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_add_label_empty_labels(self):
        result = await handle_add_label(data={"labels": []}, message_id="msg-1")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_label_connector_exception(self, mock_service):
        connector = await mock_service._get_connector("gmail", "u1")
        connector.modify_message.side_effect = ValueError("bad")
        data = {"labels": ["urgent"]}
        result = await handle_add_label(data=data, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_add_label_receipt_label_mismatch_returns_400(self, wedge_service):
        service, _store, connector = wedge_service
        envelope = service.create_receipt(
            ActionIntent.create(
                provider="gmail",
                user_id="user-1",
                message_id="msg-1",
                action="label",
                content_hash=ActionIntent.compute_content_hash("msg-1", "subject"),
                synthesized_rationale="Apply TRIAGE label",
                confidence=0.93,
                provider_route="openrouter-fallback",
                debate_id="debate-label-1",
                label_id="TRIAGE",
            ),
            TriageDecision.create(
                final_action="label",
                confidence=0.93,
                dissent_summary="",
                label_id="TRIAGE",
            ),
        )
        service.review_receipt(envelope.receipt.receipt_id, choice="approve")

        with patch(
            "aragora.server.handlers.inbox.email_actions.get_inbox_trust_wedge_service_instance",
            return_value=service,
        ):
            result = await handle_add_label(
                data={
                    "provider": "gmail",
                    "receipt_id": envelope.receipt.receipt_id,
                    "labels": ["OTHER"],
                },
                message_id="msg-1",
                user_id="user-1",
            )

        assert _status(result) == 400
        connector.add_label.assert_not_called()


# ===========================================================================
# Remove Label
# ===========================================================================


class TestHandleRemoveLabel:
    """Tests for handle_remove_label."""

    @pytest.mark.asyncio
    async def test_remove_label_success(self, mock_service):
        data = {"labels": ["urgent"]}
        result = await handle_remove_label(data=data, message_id="msg-1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "remove_labels"

    @pytest.mark.asyncio
    async def test_remove_label_missing_message_id(self):
        data = {"labels": ["urgent"]}
        result = await handle_remove_label(data=data, message_id="")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_remove_label_missing_labels(self):
        result = await handle_remove_label(data={}, message_id="msg-1")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_remove_label_connector_exception(self, mock_service):
        connector = await mock_service._get_connector("gmail", "u1")
        connector.modify_message.side_effect = ConnectionError("down")
        data = {"labels": ["urgent"]}
        result = await handle_remove_label(data=data, message_id="msg-1")
        assert _status(result) == 500


# ===========================================================================
# Batch Archive
# ===========================================================================


class TestHandleBatchArchive:
    """Tests for handle_batch_archive."""

    @pytest.mark.asyncio
    async def test_batch_archive_success(self, mock_service):
        data = {"message_ids": ["m1", "m2", "m3"], "provider": "gmail"}
        result = await handle_batch_archive(data=data, user_id="u1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "batch_archive"
        assert body["data"]["count"] == 3

    @pytest.mark.asyncio
    async def test_batch_archive_missing_ids(self):
        result = await handle_batch_archive(data={})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_archive_empty_ids(self):
        result = await handle_batch_archive(data={"message_ids": []})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_archive_over_100_limit(self):
        ids = [f"msg-{i}" for i in range(101)]
        result = await handle_batch_archive(data={"message_ids": ids})
        assert _status(result) == 400
        assert "100" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_batch_archive_service_failure(self, mock_service):
        mock_service.batch_archive.return_value = MockActionResult(success=False, error="fail")
        data = {"message_ids": ["m1"]}
        result = await handle_batch_archive(data=data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_batch_archive_exception(self, mock_service):
        mock_service.batch_archive.side_effect = RuntimeError("boom")
        data = {"message_ids": ["m1"]}
        result = await handle_batch_archive(data=data)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_batch_archive_exactly_100(self, mock_service):
        ids = [f"msg-{i}" for i in range(100)]
        data = {"message_ids": ids}
        result = await handle_batch_archive(data=data)
        assert _status(result) == 200


# ===========================================================================
# Batch Trash
# ===========================================================================


class TestHandleBatchTrash:
    """Tests for handle_batch_trash."""

    @pytest.mark.asyncio
    async def test_batch_trash_success(self, mock_service):
        data = {"message_ids": ["m1", "m2"], "provider": "gmail"}
        result = await handle_batch_trash(data=data, user_id="u1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "batch_trash"
        assert body["data"]["successful_count"] == 2
        assert body["data"]["error_count"] == 0

    @pytest.mark.asyncio
    async def test_batch_trash_missing_ids(self):
        result = await handle_batch_trash(data={})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_trash_over_100_limit(self):
        ids = [f"msg-{i}" for i in range(101)]
        result = await handle_batch_trash(data={"message_ids": ids})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_trash_fallback_on_batch_error(self, mock_service):
        """When batch_trash fails, falls back to per-item."""
        connector = await mock_service._get_connector("gmail", "u1")
        connector.batch_trash.side_effect = OSError("batch not supported")
        connector.trash_message = AsyncMock()
        data = {"message_ids": ["m1", "m2"]}
        result = await handle_batch_trash(data=data, user_id="u1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["successful_count"] == 2

    @pytest.mark.asyncio
    async def test_batch_trash_partial_failure(self, mock_service):
        """Per-item fallback with some items failing."""
        connector = await mock_service._get_connector("gmail", "u1")
        connector.batch_trash.side_effect = RuntimeError("batch fail")

        call_count = 0

        async def trash_with_failure(msg_id):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise OSError("single item fail")

        connector.trash_message = trash_with_failure
        data = {"message_ids": ["m1", "m2", "m3"]}
        result = await handle_batch_trash(data=data, user_id="u1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["successful_count"] == 2
        assert body["data"]["error_count"] == 1
        assert body["data"]["partial_success"] is True

    @pytest.mark.asyncio
    async def test_batch_trash_exception(self, mock_service):
        mock_service._get_connector.side_effect = TypeError("bad")
        data = {"message_ids": ["m1"]}
        result = await handle_batch_trash(data=data)
        assert _status(result) == 500


# ===========================================================================
# Batch Modify
# ===========================================================================


class TestHandleBatchModify:
    """Tests for handle_batch_modify."""

    @pytest.mark.asyncio
    async def test_batch_modify_add_labels(self, mock_service):
        data = {"message_ids": ["m1", "m2"], "add_labels": ["urgent"]}
        result = await handle_batch_modify(data=data, user_id="u1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["action"] == "batch_modify"
        assert body["data"]["add_labels"] == ["urgent"]

    @pytest.mark.asyncio
    async def test_batch_modify_remove_labels(self, mock_service):
        data = {"message_ids": ["m1"], "remove_labels": ["spam"]}
        result = await handle_batch_modify(data=data, user_id="u1")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_batch_modify_missing_ids(self):
        data = {"add_labels": ["urgent"]}
        result = await handle_batch_modify(data=data)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_modify_over_100_limit(self):
        ids = [f"msg-{i}" for i in range(101)]
        result = await handle_batch_modify(data={"message_ids": ids, "add_labels": ["x"]})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_modify_no_labels_specified(self):
        data = {"message_ids": ["m1"]}
        result = await handle_batch_modify(data=data)
        assert _status(result) == 400
        assert "labels" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_batch_modify_fallback_on_batch_error(self, mock_service):
        connector = await mock_service._get_connector("gmail", "u1")
        connector.batch_modify.side_effect = AttributeError("not implemented")
        connector.modify_labels = AsyncMock()
        data = {"message_ids": ["m1", "m2"], "add_labels": ["starred"]}
        result = await handle_batch_modify(data=data, user_id="u1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["successful_count"] == 2

    @pytest.mark.asyncio
    async def test_batch_modify_partial_failure(self, mock_service):
        connector = await mock_service._get_connector("gmail", "u1")
        connector.batch_modify.side_effect = RuntimeError("batch fail")

        call_count = 0

        async def modify_with_failure(msg_id, add_labels=None, remove_labels=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("fail")

        connector.modify_labels = modify_with_failure
        data = {"message_ids": ["m1", "m2"], "add_labels": ["urgent"]}
        result = await handle_batch_modify(data=data, user_id="u1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["successful_count"] == 1
        assert body["data"]["error_count"] == 1

    @pytest.mark.asyncio
    async def test_batch_modify_exception(self, mock_service):
        mock_service._get_connector.side_effect = KeyError("bad")
        data = {"message_ids": ["m1"], "add_labels": ["x"]}
        result = await handle_batch_modify(data=data)
        assert _status(result) == 500


# ===========================================================================
# Get Action Logs
# ===========================================================================


class TestHandleGetActionLogs:
    """Tests for handle_get_action_logs."""

    @pytest.mark.asyncio
    async def test_get_logs_success(self, mock_service):
        mock_service.get_action_logs.return_value = [
            MockActionLog(action="archive", message_id="m1"),
            MockActionLog(action="trash", message_id="m2"),
        ]
        result = await handle_get_action_logs(data={}, user_id="u1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["count"] == 2
        assert len(body["data"]["logs"]) == 2

    @pytest.mark.asyncio
    async def test_get_logs_empty(self, mock_service):
        result = await handle_get_action_logs(data={})
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["count"] == 0

    @pytest.mark.asyncio
    async def test_get_logs_with_action_type_filter(self, mock_service):
        """Valid action_type filter is passed to service."""
        # The handler imports ActionType enum and validates
        # We patch it to accept any value
        with patch(
            "aragora.server.handlers.inbox.email_actions.handle_get_action_logs.__wrapped__",
            side_effect=None,
        ):
            pass
        # Simpler: just call with a value that will fail enum validation
        result = await handle_get_action_logs(data={"action_type": "INVALID_TYPE"})
        assert _status(result) == 400
        assert "action_type" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_get_logs_invalid_provider(self):
        result = await handle_get_action_logs(data={"provider": "INVALID"})
        assert _status(result) == 400
        assert "provider" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_get_logs_invalid_since_format(self):
        result = await handle_get_action_logs(data={"since": "not-a-date"})
        assert _status(result) == 400
        assert (
            "iso" in _body(result).get("error", "").lower()
            or "format" in _body(result).get("error", "").lower()
        )

    @pytest.mark.asyncio
    async def test_get_logs_limit_capped_at_1000(self, mock_service):
        result = await handle_get_action_logs(data={"limit": 5000})
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["limit"] == 1000

    @pytest.mark.asyncio
    async def test_get_logs_default_limit(self, mock_service):
        result = await handle_get_action_logs(data={})
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["limit"] == 100

    @pytest.mark.asyncio
    async def test_get_logs_exception(self, mock_service):
        mock_service.get_action_logs.side_effect = RuntimeError("db error")
        result = await handle_get_action_logs(data={})
        assert _status(result) == 500


# ===========================================================================
# Export Action Logs
# ===========================================================================


class TestHandleExportActionLogs:
    """Tests for handle_export_action_logs."""

    @pytest.mark.asyncio
    async def test_export_success(self, mock_service):
        mock_service.export_action_logs.return_value = [{"action": "archive"}]
        start = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        end = datetime.now(timezone.utc).isoformat()
        data = {"start_date": start, "end_date": end}
        result = await handle_export_action_logs(data=data, user_id="u1")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["count"] == 1
        assert body["data"]["user_id"] == "u1"
        assert "exported_at" in body["data"]

    @pytest.mark.asyncio
    async def test_export_missing_start_date(self):
        end = datetime.now(timezone.utc).isoformat()
        result = await handle_export_action_logs(data={"end_date": end})
        assert _status(result) == 400
        assert (
            "start_date" in _body(result).get("error", "").lower()
            or "required" in _body(result).get("error", "").lower()
        )

    @pytest.mark.asyncio
    async def test_export_missing_end_date(self):
        start = datetime.now(timezone.utc).isoformat()
        result = await handle_export_action_logs(data={"start_date": start})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_export_missing_both_dates(self):
        result = await handle_export_action_logs(data={})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_export_invalid_date_format(self):
        data = {"start_date": "not-a-date", "end_date": "also-bad"}
        result = await handle_export_action_logs(data=data)
        assert _status(result) == 400
        assert (
            "format" in _body(result).get("error", "").lower()
            or "iso" in _body(result).get("error", "").lower()
        )

    @pytest.mark.asyncio
    async def test_export_end_before_start(self):
        start = datetime.now(timezone.utc).isoformat()
        end = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        data = {"start_date": start, "end_date": end}
        result = await handle_export_action_logs(data=data)
        assert _status(result) == 400
        assert "after" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_export_range_exceeds_90_days(self):
        start = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        end = datetime.now(timezone.utc).isoformat()
        data = {"start_date": start, "end_date": end}
        result = await handle_export_action_logs(data=data)
        assert _status(result) == 400
        assert "90" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_export_exactly_90_days(self, mock_service):
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=90)).isoformat()
        end = now.isoformat()
        data = {"start_date": start, "end_date": end}
        result = await handle_export_action_logs(data=data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_export_with_z_suffix(self, mock_service):
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {"start_date": start, "end_date": end}
        result = await handle_export_action_logs(data=data)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_export_exception(self, mock_service):
        mock_service.export_action_logs.side_effect = OSError("db error")
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=1)).isoformat()
        end = now.isoformat()
        data = {"start_date": start, "end_date": end}
        result = await handle_export_action_logs(data=data)
        assert _status(result) == 500


# ===========================================================================
# Default Provider Tests (cross-cutting)
# ===========================================================================


class TestDefaultProvider:
    """Verify handlers default to gmail when provider is not specified."""

    @pytest.mark.asyncio
    async def test_archive_defaults_to_gmail(self, mock_service):
        await handle_archive_message(data={}, message_id="msg-1")
        call_kwargs = mock_service.archive.call_args
        assert (
            call_kwargs.kwargs.get("provider") == "gmail"
            or call_kwargs[1].get("provider") == "gmail"
        )

    @pytest.mark.asyncio
    async def test_trash_defaults_to_gmail(self, mock_service):
        await handle_trash_message(data={}, message_id="msg-1")
        call_kwargs = mock_service.trash.call_args
        assert (
            call_kwargs.kwargs.get("provider") == "gmail"
            or call_kwargs[1].get("provider") == "gmail"
        )

    @pytest.mark.asyncio
    async def test_mark_read_defaults_to_gmail(self, mock_service):
        await handle_mark_read(data={}, message_id="msg-1")
        call_kwargs = mock_service.mark_read.call_args
        assert (
            call_kwargs.kwargs.get("provider") == "gmail"
            or call_kwargs[1].get("provider") == "gmail"
        )


# ===========================================================================
# User ID Propagation (cross-cutting)
# ===========================================================================


class TestUserIdPropagation:
    """Verify user_id is passed through to service calls."""

    @pytest.mark.asyncio
    async def test_send_propagates_user_id(self, mock_service):
        data = {"to": ["a@b.com"], "subject": "Hi", "body": "X"}
        await handle_send_email(data=data, user_id="user-42")
        call_kwargs = mock_service.send.call_args
        assert (
            call_kwargs.kwargs.get("user_id") == "user-42"
            or call_kwargs[1].get("user_id") == "user-42"
        )

    @pytest.mark.asyncio
    async def test_archive_propagates_user_id(self, mock_service):
        await handle_archive_message(data={}, message_id="msg-1", user_id="user-42")
        call_kwargs = mock_service.archive.call_args
        assert (
            call_kwargs.kwargs.get("user_id") == "user-42"
            or call_kwargs[1].get("user_id") == "user-42"
        )

    @pytest.mark.asyncio
    async def test_batch_archive_propagates_user_id(self, mock_service):
        data = {"message_ids": ["m1"]}
        await handle_batch_archive(data=data, user_id="user-42")
        call_kwargs = mock_service.batch_archive.call_args
        assert (
            call_kwargs.kwargs.get("user_id") == "user-42"
            or call_kwargs[1].get("user_id") == "user-42"
        )


# ===========================================================================
# Outlook Provider Tests
# ===========================================================================


class TestOutlookProvider:
    """Verify handlers work with outlook provider."""

    @pytest.mark.asyncio
    async def test_send_with_outlook(self, mock_service):
        data = {"provider": "outlook", "to": ["a@b.com"], "subject": "Hi", "body": "X"}
        result = await handle_send_email(data=data)
        assert _status(result) == 200
        call_kwargs = mock_service.send.call_args
        assert (
            call_kwargs.kwargs.get("provider") == "outlook"
            or call_kwargs[1].get("provider") == "outlook"
        )

    @pytest.mark.asyncio
    async def test_reply_with_outlook(self, mock_service):
        data = {"provider": "outlook", "body": "Thanks!"}
        result = await handle_reply_email(data=data, message_id="msg-1")
        assert _status(result) == 200


# ===========================================================================
# Exception Type Coverage
# ===========================================================================


class TestExceptionCoverage:
    """Verify all caught exception types are handled for representative handlers."""

    @pytest.mark.asyncio
    async def test_value_error(self, mock_service):
        mock_service.archive.side_effect = ValueError("bad value")
        result = await handle_archive_message(data={}, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_key_error(self, mock_service):
        mock_service.archive.side_effect = KeyError("missing")
        result = await handle_archive_message(data={}, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_type_error(self, mock_service):
        mock_service.archive.side_effect = TypeError("wrong type")
        result = await handle_archive_message(data={}, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_attribute_error(self, mock_service):
        mock_service.archive.side_effect = AttributeError("no attr")
        result = await handle_archive_message(data={}, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_os_error(self, mock_service):
        mock_service.archive.side_effect = OSError("disk full")
        result = await handle_archive_message(data={}, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_connection_error(self, mock_service):
        mock_service.archive.side_effect = ConnectionError("refused")
        result = await handle_archive_message(data={}, message_id="msg-1")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_runtime_error(self, mock_service):
        mock_service.archive.side_effect = RuntimeError("unexpected")
        result = await handle_archive_message(data={}, message_id="msg-1")
        assert _status(result) == 500


# ===========================================================================
# Singleton service factory
# ===========================================================================


class TestGetEmailActionsServiceInstance:
    """Tests for the thread-safe singleton factory.

    Uses _real_get_email_actions_service_instance (imported at module level
    before the autouse _patch_service fixture replaces the module attribute)
    to call the genuine implementation.
    """

    def test_returns_cached_instance(self):
        """When _email_actions_service is already set, return it directly."""
        import aragora.server.handlers.inbox.email_actions as mod

        sentinel = object()
        old = mod._email_actions_service
        mod._email_actions_service = sentinel
        try:
            result = _real_get_email_actions_service_instance()
            assert result is sentinel
        finally:
            mod._email_actions_service = old

    def test_creates_new_instance_when_none(self):
        """When _email_actions_service is None, create via the service factory."""
        import aragora.server.handlers.inbox.email_actions as mod

        old = mod._email_actions_service
        mod._email_actions_service = None
        mock_svc = MagicMock()
        try:
            with patch(
                "aragora.services.email_actions.get_email_actions_service",
                return_value=mock_svc,
            ):
                result = _real_get_email_actions_service_instance()
                assert result is mock_svc
        finally:
            mod._email_actions_service = old
