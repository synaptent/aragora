"""
Tests for Email Actions Handler (aragora/server/handlers/inbox/email_actions.py).

Covers all 18 handler functions:
- handle_send_email            POST /api/v1/inbox/messages/send
- handle_reply_email           POST /api/v1/inbox/messages/{id}/reply
- handle_archive_message       POST /api/v1/inbox/messages/{id}/archive
- handle_trash_message         POST /api/v1/inbox/messages/{id}/trash
- handle_restore_message       POST /api/v1/inbox/messages/{id}/restore
- handle_snooze_message        POST /api/v1/inbox/messages/{id}/snooze
- handle_mark_read             POST /api/v1/inbox/messages/{id}/read
- handle_mark_unread           POST /api/v1/inbox/messages/{id}/unread
- handle_star_message          POST /api/v1/inbox/messages/{id}/star
- handle_unstar_message        POST /api/v1/inbox/messages/{id}/unstar
- handle_move_to_folder        POST /api/v1/inbox/messages/{id}/move
- handle_add_label             POST /api/v1/inbox/messages/{id}/labels/add
- handle_remove_label          POST /api/v1/inbox/messages/{id}/labels/remove
- handle_batch_archive         POST /api/v1/inbox/messages/batch/archive
- handle_batch_trash           POST /api/v1/inbox/messages/batch/trash
- handle_batch_modify          POST /api/v1/inbox/messages/batch/modify
- handle_get_action_logs       GET  /api/v1/inbox/actions/logs
- handle_export_action_logs    GET  /api/v1/inbox/actions/export
- get_email_actions_handlers   Handler registration helper

Test categories:
- Handler registration and initialization
- Happy path for each endpoint
- Validation errors (400): missing fields, invalid formats
- Service failures (500): raised exceptions, result.success=False
- Edge cases: empty data, batch limits, date ranges, partial failures
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.inbox import ReceiptState
from aragora.server.handlers.inbox.email_actions import (
    _email_actions_service,
    get_email_actions_handlers,
    get_email_actions_service_instance,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


def _data(result) -> dict:
    """Extract the 'data' envelope from a success response."""
    body = _body(result)
    return body.get("data", body)


# ---------------------------------------------------------------------------
# Mock service result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MockActionResult:
    """Mock result returned by the email actions service."""

    success: bool = True
    action_type: str = "send"
    message_ids: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "actionType": self.action_type,
            "messageIds": self.message_ids,
            "details": self.details,
            "error": self.error,
        }


@dataclass
class MockActionLog:
    """Mock action log entry."""

    id: str = "log-001"
    user_id: str = "test-user-001"
    action_type: str = "send"
    provider: str = "gmail"
    message_ids: list[str] = field(default_factory=list)
    status: str = "success"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "userId": self.user_id,
            "actionType": self.action_type,
            "provider": self.provider,
            "messageIds": self.message_ids,
            "status": self.status,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


def _make_wedge_envelope(
    *,
    receipt_id: str = "receipt-1",
    state: ReceiptState | str = "approved",
    provider: str = "gmail",
    user_id: str = "test-user-001",
    message_id: str = "msg-123",
    action: str = "archive",
    label_id: str | None = None,
) -> SimpleNamespace:
    state_value = state.value if hasattr(state, "value") else str(state)
    receipt_state = state if hasattr(state, "value") else SimpleNamespace(value=state_value)
    return SimpleNamespace(
        receipt=SimpleNamespace(
            receipt_id=receipt_id,
            state=receipt_state,
            to_dict=lambda: {"receipt_id": receipt_id, "state": state_value},
        ),
        intent=SimpleNamespace(
            provider=provider,
            user_id=user_id,
            message_id=message_id,
            action=action,
            label_id=label_id,
            to_dict=lambda: {
                "provider": provider,
                "user_id": user_id,
                "message_id": message_id,
                "action": action,
                "label_id": label_id,
            },
        ),
        decision=SimpleNamespace(
            label_id=label_id,
            to_dict=lambda: {"final_action": action, "label_id": label_id},
        ),
        provider_route="direct",
        debate_id=None,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_service():
    """Create a mock email actions service with all methods."""
    service = MagicMock()
    service.send = AsyncMock(return_value=MockActionResult(success=True))
    service.reply = AsyncMock(return_value=MockActionResult(success=True))
    service.archive = AsyncMock(return_value=MockActionResult(success=True))
    service.trash = AsyncMock(return_value=MockActionResult(success=True))
    service.snooze = AsyncMock(return_value=MockActionResult(success=True))
    service.mark_read = AsyncMock(return_value=MockActionResult(success=True))
    service.star = AsyncMock(return_value=MockActionResult(success=True))
    service.move_to_folder = AsyncMock(return_value=MockActionResult(success=True))
    service.batch_archive = AsyncMock(return_value=MockActionResult(success=True))
    service.get_action_logs = AsyncMock(return_value=[])
    service.export_action_logs = AsyncMock(return_value=[])

    # Connector mock for handlers that use _get_connector directly
    mock_connector = AsyncMock()
    service._get_connector = AsyncMock(return_value=mock_connector)

    return service


@pytest.fixture(autouse=True)
def _patch_service(monkeypatch, mock_service):
    """Patch the service singleton for all tests."""
    import aragora.server.handlers.inbox.email_actions as mod

    monkeypatch.setattr(mod, "_email_actions_service", mock_service)
    monkeypatch.setattr(
        mod,
        "get_email_actions_service_instance",
        lambda: mock_service,
    )
    yield
    # Reset to None after each test
    monkeypatch.setattr(mod, "_email_actions_service", None)


@pytest.fixture(autouse=True)
def _patch_send_email_request(monkeypatch):
    """Patch SendEmailRequest import inside handle_send_email to avoid real import."""

    # The handler does `from aragora.services.email_actions import SendEmailRequest`
    # at call time. We mock the module-level import target so it finds our mock.
    @dataclass
    class MockSendEmailRequest:
        to: list[str]
        subject: str
        body: str
        cc: list[str] | None = None
        bcc: list[str] | None = None
        reply_to: str | None = None
        html_body: str | None = None

    # Patch into the services module so the lazy import finds it
    try:
        import aragora.services.email_actions as svc_mod

        monkeypatch.setattr(svc_mod, "SendEmailRequest", MockSendEmailRequest)
    except (ImportError, AttributeError):
        pass


# ============================================================================
# Handler Registration
# ============================================================================


class TestGetEmailActionsHandlers:
    """Tests for the handler registration function."""

    def test_returns_dict(self):
        handlers = get_email_actions_handlers()
        assert isinstance(handlers, dict)

    def test_contains_all_expected_keys(self):
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

    def test_all_values_are_callable(self):
        handlers = get_email_actions_handlers()
        for name, handler in handlers.items():
            assert callable(handler), f"Handler {name} is not callable"

    def test_handler_count(self):
        handlers = get_email_actions_handlers()
        assert len(handlers) == 18


# ============================================================================
# Send Email
# ============================================================================


class TestSendEmail:
    """Tests for handle_send_email."""

    @pytest.mark.asyncio
    async def test_send_success(self, mock_service):
        data = {
            "provider": "gmail",
            "to": ["user@example.com"],
            "subject": "Hello",
            "body": "Test message",
        }
        result = await handle_send_email(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["success"] is True
        mock_service.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_with_cc_bcc(self, mock_service):
        data = {
            "to": ["a@example.com"],
            "subject": "Test",
            "body": "Body",
            "cc": ["cc@example.com"],
            "bcc": ["bcc@example.com"],
            "reply_to": "reply@example.com",
            "html_body": "<b>Bold</b>",
        }
        result = await handle_send_email(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_send_missing_to(self):
        data = {"subject": "Hello", "body": "Test"}
        result = await handle_send_email(data, user_id="test-user-001")
        assert _status(result) == 400
        assert "to" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_send_empty_to_list(self):
        data = {"to": [], "subject": "Hello", "body": "Test"}
        result = await handle_send_email(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_send_no_subject_no_body(self):
        data = {"to": ["user@example.com"], "subject": "", "body": ""}
        result = await handle_send_email(data, user_id="test-user-001")
        assert _status(result) == 400
        body = _body(result)
        assert "subject" in body.get("error", "").lower() or "body" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_send_subject_only(self, mock_service):
        data = {"to": ["user@example.com"], "subject": "Subject only"}
        result = await handle_send_email(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_send_body_only(self, mock_service):
        data = {"to": ["user@example.com"], "body": "Body only"}
        result = await handle_send_email(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_send_default_provider(self, mock_service):
        data = {"to": ["user@example.com"], "subject": "Test", "body": "Body"}
        result = await handle_send_email(data, user_id="test-user-001")
        assert _status(result) == 200
        call_kwargs = mock_service.send.call_args
        assert (
            call_kwargs.kwargs.get("provider") == "gmail"
            or call_kwargs[1].get("provider") == "gmail"
        )

    @pytest.mark.asyncio
    async def test_send_outlook_provider(self, mock_service):
        data = {"provider": "outlook", "to": ["u@e.com"], "subject": "T", "body": "B"}
        result = await handle_send_email(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_send_service_failure(self, mock_service):
        mock_service.send.return_value = MockActionResult(success=False, error="SMTP error")
        data = {"to": ["user@example.com"], "subject": "Hello", "body": "Body"}
        result = await handle_send_email(data, user_id="test-user-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_send_service_exception(self, mock_service):
        mock_service.send.side_effect = RuntimeError("Connection lost")
        data = {"to": ["user@example.com"], "subject": "Hello", "body": "Body"}
        result = await handle_send_email(data, user_id="test-user-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_send_empty_data(self):
        result = await handle_send_email({}, user_id="test-user-001")
        assert _status(result) == 400


# ============================================================================
# Reply Email
# ============================================================================


class TestReplyEmail:
    """Tests for handle_reply_email."""

    @pytest.mark.asyncio
    async def test_reply_success(self, mock_service):
        data = {"provider": "gmail", "body": "My reply"}
        result = await handle_reply_email(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200
        mock_service.reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reply_message_id_from_body(self, mock_service):
        data = {"message_id": "msg-456", "body": "Reply text"}
        result = await handle_reply_email(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_reply_missing_message_id(self):
        data = {"body": "Reply text"}
        result = await handle_reply_email(data, user_id="test-user-001")
        assert _status(result) == 400
        assert "message_id" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_reply_missing_body(self):
        data = {"provider": "gmail"}
        result = await handle_reply_email(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 400
        assert "body" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_reply_empty_body(self):
        data = {"body": ""}
        result = await handle_reply_email(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_reply_with_cc_and_html(self, mock_service):
        data = {"body": "Reply", "cc": ["cc@e.com"], "html_body": "<p>Reply</p>"}
        result = await handle_reply_email(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_reply_service_failure(self, mock_service):
        mock_service.reply.return_value = MockActionResult(success=False, error="Not found")
        data = {"body": "Reply"}
        result = await handle_reply_email(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_reply_service_exception(self, mock_service):
        mock_service.reply.side_effect = ValueError("Bad data")
        data = {"body": "Reply"}
        result = await handle_reply_email(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 500


# ============================================================================
# Archive Message
# ============================================================================


class TestArchiveMessage:
    """Tests for handle_archive_message."""

    @pytest.mark.asyncio
    async def test_archive_requires_receipt(self, mock_service):
        data = {"provider": "gmail"}
        result = await handle_archive_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 428
        assert "decision receipt" in _body(result).get("error", "").lower()
        mock_service.archive.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_archive_message_id_from_body_still_requires_receipt(self, mock_service):
        data = {"message_id": "msg-789"}
        result = await handle_archive_message(data, user_id="test-user-001")
        assert _status(result) == 428
        mock_service.archive.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_archive_missing_message_id(self):
        data = {"provider": "gmail"}
        result = await handle_archive_message(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_archive_create_receipt_auto_execute_success(self, monkeypatch, mock_service):
        created = _make_wedge_envelope(receipt_id="receipt-created", state=ReceiptState.APPROVED)
        executed = _make_wedge_envelope(receipt_id="receipt-created", state=ReceiptState.EXECUTED)
        wedge_service = MagicMock()
        wedge_service.create_receipt = MagicMock(return_value=created)
        wedge_service.execute_receipt = AsyncMock(
            return_value=SimpleNamespace(to_dict=lambda: {"status": "executed"})
        )
        wedge_service.store = SimpleNamespace(get_receipt=MagicMock(return_value=executed))
        monkeypatch.setattr(
            "aragora.server.handlers.inbox.email_actions.get_inbox_trust_wedge_service_instance",
            lambda: wedge_service,
        )

        data = {
            "provider": "gmail",
            "create_receipt": True,
            "auto_approve": True,
            "auto_execute": True,
        }
        result = await handle_archive_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["action"] == "archive"
        assert body["executed"] is True
        assert body["receipt"]["state"] == ReceiptState.EXECUTED.value
        wedge_service.create_receipt.assert_called_once()
        wedge_service.execute_receipt.assert_awaited_once_with("receipt-created")
        mock_service.archive.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_archive_does_not_fall_through_to_direct_service(self, mock_service):
        mock_service.archive.side_effect = OSError("Disk full")
        data = {"provider": "gmail"}
        result = await handle_archive_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 428
        mock_service.archive.assert_not_awaited()


# ============================================================================
# Trash Message
# ============================================================================


class TestTrashMessage:
    """Tests for handle_trash_message."""

    @pytest.mark.asyncio
    async def test_trash_success(self, mock_service):
        data = {"provider": "outlook"}
        result = await handle_trash_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["action"] == "trash"
        assert body["message_id"] == "msg-123"

    @pytest.mark.asyncio
    async def test_trash_message_id_from_body(self, mock_service):
        data = {"message_id": "msg-456"}
        result = await handle_trash_message(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_trash_missing_message_id(self):
        data = {}
        result = await handle_trash_message(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_trash_service_failure(self, mock_service):
        mock_service.trash.return_value = MockActionResult(success=False, error="Trash err")
        data = {}
        result = await handle_trash_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_trash_service_exception(self, mock_service):
        mock_service.trash.side_effect = ConnectionError("Timeout")
        data = {}
        result = await handle_trash_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 500


# ============================================================================
# Restore Message
# ============================================================================


class TestRestoreMessage:
    """Tests for handle_restore_message."""

    @pytest.mark.asyncio
    async def test_restore_success(self, mock_service):
        data = {"provider": "gmail"}
        result = await handle_restore_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["action"] == "restore"
        assert body["message_id"] == "msg-123"
        assert body["success"] is True

    @pytest.mark.asyncio
    async def test_restore_message_id_from_body(self, mock_service):
        data = {"message_id": "msg-789"}
        result = await handle_restore_message(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_restore_missing_message_id(self):
        data = {}
        result = await handle_restore_message(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_restore_connector_exception(self, mock_service):
        connector = await mock_service._get_connector("gmail", "test-user-001")
        connector.untrash_message.side_effect = RuntimeError("API error")
        data = {"provider": "gmail"}
        result = await handle_restore_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 500


# ============================================================================
# Snooze Message
# ============================================================================


class TestSnoozeMessage:
    """Tests for handle_snooze_message."""

    @pytest.mark.asyncio
    async def test_snooze_with_iso_datetime(self, mock_service):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        data = {"provider": "gmail", "snooze_until": future}
        result = await handle_snooze_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["action"] == "snooze"
        assert body["message_id"] == "msg-123"

    @pytest.mark.asyncio
    async def test_snooze_with_hours(self, mock_service):
        data = {"provider": "gmail", "snooze_hours": 4}
        result = await handle_snooze_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_snooze_with_days(self, mock_service):
        data = {"provider": "gmail", "snooze_days": 2}
        result = await handle_snooze_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_snooze_missing_message_id(self):
        data = {"snooze_hours": 1}
        result = await handle_snooze_message(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_snooze_no_time_specified(self):
        data = {"provider": "gmail"}
        result = await handle_snooze_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 400
        assert (
            "snooze_until" in _body(result).get("error", "").lower()
            or "snooze" in _body(result).get("error", "").lower()
        )

    @pytest.mark.asyncio
    async def test_snooze_invalid_datetime_format(self):
        data = {"snooze_until": "not-a-date"}
        result = await handle_snooze_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 400
        assert (
            "iso" in _body(result).get("error", "").lower()
            or "format" in _body(result).get("error", "").lower()
        )

    @pytest.mark.asyncio
    async def test_snooze_past_datetime(self):
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        data = {"snooze_until": past}
        result = await handle_snooze_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 400
        assert "future" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_snooze_with_z_suffix(self, mock_service):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        data = {"snooze_until": future}
        result = await handle_snooze_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_snooze_service_failure(self, mock_service):
        mock_service.snooze.return_value = MockActionResult(success=False, error="Snooze err")
        data = {"snooze_hours": 1}
        result = await handle_snooze_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_snooze_service_exception(self, mock_service):
        mock_service.snooze.side_effect = TypeError("Bad type")
        data = {"snooze_hours": 1}
        result = await handle_snooze_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_snooze_message_id_from_body(self, mock_service):
        data = {"message_id": "msg-body", "snooze_hours": 1}
        result = await handle_snooze_message(data, user_id="test-user-001")
        assert _status(result) == 200


# ============================================================================
# Mark Read / Unread
# ============================================================================


class TestMarkRead:
    """Tests for handle_mark_read."""

    @pytest.mark.asyncio
    async def test_mark_read_success(self, mock_service):
        data = {"provider": "gmail"}
        result = await handle_mark_read(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["action"] == "mark_read"
        assert body["message_id"] == "msg-123"

    @pytest.mark.asyncio
    async def test_mark_read_message_id_from_body(self, mock_service):
        data = {"message_id": "msg-456"}
        result = await handle_mark_read(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_mark_read_missing_message_id(self):
        data = {}
        result = await handle_mark_read(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_mark_read_service_failure(self, mock_service):
        mock_service.mark_read.return_value = MockActionResult(success=False, error="Err")
        data = {}
        result = await handle_mark_read(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_mark_read_exception(self, mock_service):
        mock_service.mark_read.side_effect = KeyError("missing")
        data = {}
        result = await handle_mark_read(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 500


class TestMarkUnread:
    """Tests for handle_mark_unread."""

    @pytest.mark.asyncio
    async def test_mark_unread_success(self, mock_service):
        data = {"provider": "gmail"}
        result = await handle_mark_unread(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["action"] == "mark_unread"
        assert body["message_id"] == "msg-123"

    @pytest.mark.asyncio
    async def test_mark_unread_message_id_from_body(self, mock_service):
        data = {"message_id": "msg-456"}
        result = await handle_mark_unread(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_mark_unread_missing_message_id(self):
        data = {}
        result = await handle_mark_unread(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_mark_unread_connector_exception(self, mock_service):
        connector = await mock_service._get_connector("gmail", "test-user-001")
        connector.mark_as_unread.side_effect = OSError("Network err")
        data = {"provider": "gmail"}
        result = await handle_mark_unread(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 500


# ============================================================================
# Star / Unstar
# ============================================================================


class TestStarMessage:
    """Tests for handle_star_message."""

    @pytest.mark.asyncio
    async def test_star_requires_receipt(self, mock_service):
        data = {"provider": "gmail"}
        result = await handle_star_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 428
        assert "decision receipt" in _body(result).get("error", "").lower()
        mock_service.star.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_star_message_id_from_body_still_requires_receipt(self, mock_service):
        data = {"message_id": "msg-456"}
        result = await handle_star_message(data, user_id="test-user-001")
        assert _status(result) == 428
        mock_service.star.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_star_missing_message_id(self):
        data = {}
        result = await handle_star_message(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_star_does_not_fall_through_on_service_failure(self, mock_service):
        mock_service.star.return_value = MockActionResult(success=False, error="Err")
        data = {}
        result = await handle_star_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 428
        mock_service.star.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_star_does_not_fall_through_on_service_exception(self, mock_service):
        mock_service.star.side_effect = AttributeError("no attr")
        data = {}
        result = await handle_star_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 428
        mock_service.star.assert_not_awaited()


class TestUnstarMessage:
    """Tests for handle_unstar_message."""

    @pytest.mark.asyncio
    async def test_unstar_success(self, mock_service):
        data = {"provider": "gmail"}
        result = await handle_unstar_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["action"] == "unstar"

    @pytest.mark.asyncio
    async def test_unstar_message_id_from_body(self, mock_service):
        data = {"message_id": "msg-456"}
        result = await handle_unstar_message(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_unstar_missing_message_id(self):
        data = {}
        result = await handle_unstar_message(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_unstar_connector_exception(self, mock_service):
        connector = await mock_service._get_connector("gmail", "test-user-001")
        connector.unstar_message.side_effect = ConnectionError("API down")
        data = {"provider": "gmail"}
        result = await handle_unstar_message(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 500


# ============================================================================
# Move to Folder
# ============================================================================


class TestMoveToFolder:
    """Tests for handle_move_to_folder."""

    @pytest.mark.asyncio
    async def test_move_success(self, mock_service):
        data = {"provider": "gmail", "folder": "Important"}
        result = await handle_move_to_folder(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["action"] == "move_to_folder"
        assert body["folder"] == "Important"

    @pytest.mark.asyncio
    async def test_move_missing_message_id(self):
        data = {"folder": "Spam"}
        result = await handle_move_to_folder(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_move_missing_folder(self):
        data = {"provider": "gmail"}
        result = await handle_move_to_folder(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 400
        assert "folder" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_move_empty_folder(self):
        data = {"folder": ""}
        result = await handle_move_to_folder(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_move_service_failure(self, mock_service):
        mock_service.move_to_folder.return_value = MockActionResult(success=False, error="Err")
        data = {"folder": "Archive"}
        result = await handle_move_to_folder(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_move_message_id_from_body(self, mock_service):
        data = {"message_id": "msg-789", "folder": "Trash"}
        result = await handle_move_to_folder(data, user_id="test-user-001")
        assert _status(result) == 200


# ============================================================================
# Add / Remove Label
# ============================================================================


class TestAddLabel:
    """Tests for handle_add_label."""

    @pytest.mark.asyncio
    async def test_add_label_requires_receipt(self, mock_service):
        data = {"provider": "gmail", "labels": ["urgent"]}
        result = await handle_add_label(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 428
        assert "decision receipt" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_add_label_missing_message_id(self):
        data = {"labels": ["urgent"]}
        result = await handle_add_label(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_label_missing_labels_requires_receipt_first(self):
        data = {"provider": "gmail"}
        result = await handle_add_label(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 428
        assert "decision receipt" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_add_label_empty_labels_requires_receipt_first(self):
        data = {"labels": []}
        result = await handle_add_label(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 428

    @pytest.mark.asyncio
    async def test_add_label_create_receipt_requires_single_label(self):
        data = {"provider": "gmail", "labels": ["urgent", "work"], "create_receipt": True}
        result = await handle_add_label(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 400
        assert "exactly one label" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_add_label_message_id_from_body_still_requires_receipt(self, mock_service):
        data = {"message_id": "msg-body", "labels": ["label1"]}
        result = await handle_add_label(data, user_id="test-user-001")
        assert _status(result) == 428


class TestRemoveLabel:
    """Tests for handle_remove_label."""

    @pytest.mark.asyncio
    async def test_remove_label_success(self, mock_service):
        data = {"provider": "gmail", "labels": ["old-label"]}
        result = await handle_remove_label(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["action"] == "remove_labels"
        assert body["labels"] == ["old-label"]

    @pytest.mark.asyncio
    async def test_remove_label_missing_message_id(self):
        data = {"labels": ["label"]}
        result = await handle_remove_label(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_remove_label_missing_labels(self):
        data = {}
        result = await handle_remove_label(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_remove_label_empty_labels(self):
        data = {"labels": []}
        result = await handle_remove_label(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_remove_label_connector_exception(self, mock_service):
        connector = await mock_service._get_connector("gmail", "test-user-001")
        connector.modify_message.side_effect = ValueError("Invalid label")
        data = {"provider": "gmail", "labels": ["nonexistent"]}
        result = await handle_remove_label(data, message_id="msg-123", user_id="test-user-001")
        assert _status(result) == 500


# ============================================================================
# Batch Archive
# ============================================================================


class TestBatchArchive:
    """Tests for handle_batch_archive."""

    @pytest.mark.asyncio
    async def test_batch_archive_success(self, mock_service):
        data = {"provider": "gmail", "message_ids": ["m1", "m2", "m3"]}
        result = await handle_batch_archive(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["action"] == "batch_archive"
        assert body["count"] == 3

    @pytest.mark.asyncio
    async def test_batch_archive_empty_ids(self):
        data = {"message_ids": []}
        result = await handle_batch_archive(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_archive_missing_ids(self):
        data = {"provider": "gmail"}
        result = await handle_batch_archive(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_archive_exceeds_limit(self):
        data = {"message_ids": [f"m{i}" for i in range(101)]}
        result = await handle_batch_archive(data, user_id="test-user-001")
        assert _status(result) == 400
        assert "100" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_batch_archive_exactly_100(self, mock_service):
        data = {"message_ids": [f"m{i}" for i in range(100)]}
        result = await handle_batch_archive(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_batch_archive_service_failure(self, mock_service):
        mock_service.batch_archive.return_value = MockActionResult(success=False, error="Bulk err")
        data = {"message_ids": ["m1"]}
        result = await handle_batch_archive(data, user_id="test-user-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_batch_archive_service_exception(self, mock_service):
        mock_service.batch_archive.side_effect = RuntimeError("Server error")
        data = {"message_ids": ["m1"]}
        result = await handle_batch_archive(data, user_id="test-user-001")
        assert _status(result) == 500


# ============================================================================
# Batch Trash
# ============================================================================


class TestBatchTrash:
    """Tests for handle_batch_trash."""

    @pytest.mark.asyncio
    async def test_batch_trash_success(self, mock_service):
        data = {"provider": "gmail", "message_ids": ["m1", "m2"]}
        result = await handle_batch_trash(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["action"] == "batch_trash"
        assert body["successful_count"] == 2
        assert body["error_count"] == 0
        assert body["success"] is True

    @pytest.mark.asyncio
    async def test_batch_trash_empty_ids(self):
        data = {"message_ids": []}
        result = await handle_batch_trash(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_trash_exceeds_limit(self):
        data = {"message_ids": [f"m{i}" for i in range(101)]}
        result = await handle_batch_trash(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_trash_fallback_on_batch_failure(self, mock_service):
        """When batch_trash fails, falls back to per-item trash_message."""
        connector = await mock_service._get_connector("gmail", "test-user-001")
        connector.batch_trash.side_effect = RuntimeError("Batch not supported")
        connector.trash_message = AsyncMock()  # Per-item succeeds
        data = {"provider": "gmail", "message_ids": ["m1", "m2"]}
        result = await handle_batch_trash(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["successful_count"] == 2
        assert body["error_count"] == 0

    @pytest.mark.asyncio
    async def test_batch_trash_partial_failure(self, mock_service):
        """When batch_trash fails and some per-item calls fail too."""
        connector = await mock_service._get_connector("gmail", "test-user-001")
        connector.batch_trash.side_effect = RuntimeError("Batch fail")

        call_count = 0

        async def trash_with_failure(msg_id):
            nonlocal call_count
            call_count += 1
            if msg_id == "m2":
                raise OSError("Failed for m2")

        connector.trash_message = trash_with_failure
        data = {"provider": "gmail", "message_ids": ["m1", "m2", "m3"]}
        result = await handle_batch_trash(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["successful_count"] == 2
        assert body["error_count"] == 1
        assert body["partial_success"] is True
        assert body["success"] is False

    @pytest.mark.asyncio
    async def test_batch_trash_connector_exception(self, mock_service):
        mock_service._get_connector.side_effect = ValueError("No provider")
        data = {"message_ids": ["m1"]}
        result = await handle_batch_trash(data, user_id="test-user-001")
        assert _status(result) == 500


# ============================================================================
# Batch Modify
# ============================================================================


class TestBatchModify:
    """Tests for handle_batch_modify."""

    @pytest.mark.asyncio
    async def test_batch_modify_add_labels(self, mock_service):
        data = {
            "provider": "gmail",
            "message_ids": ["m1", "m2"],
            "add_labels": ["urgent"],
        }
        result = await handle_batch_modify(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["action"] == "batch_modify"
        assert body["successful_count"] == 2
        assert body["add_labels"] == ["urgent"]

    @pytest.mark.asyncio
    async def test_batch_modify_remove_labels(self, mock_service):
        data = {
            "message_ids": ["m1"],
            "remove_labels": ["old"],
        }
        result = await handle_batch_modify(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_batch_modify_both_labels(self, mock_service):
        data = {
            "message_ids": ["m1"],
            "add_labels": ["new"],
            "remove_labels": ["old"],
        }
        result = await handle_batch_modify(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_batch_modify_empty_ids(self):
        data = {"message_ids": [], "add_labels": ["a"]}
        result = await handle_batch_modify(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_modify_missing_ids(self):
        data = {"add_labels": ["a"]}
        result = await handle_batch_modify(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_modify_exceeds_limit(self):
        data = {"message_ids": [f"m{i}" for i in range(101)], "add_labels": ["a"]}
        result = await handle_batch_modify(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_batch_modify_no_labels_specified(self):
        data = {"message_ids": ["m1"]}
        result = await handle_batch_modify(data, user_id="test-user-001")
        assert _status(result) == 400
        assert (
            "add_labels" in _body(result).get("error", "").lower()
            or "remove_labels" in _body(result).get("error", "").lower()
        )

    @pytest.mark.asyncio
    async def test_batch_modify_fallback_on_batch_failure(self, mock_service):
        connector = await mock_service._get_connector("gmail", "test-user-001")
        connector.batch_modify.side_effect = AttributeError("No batch_modify")
        connector.modify_labels = AsyncMock()
        data = {"message_ids": ["m1"], "add_labels": ["label"]}
        result = await handle_batch_modify(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["successful_count"] == 1

    @pytest.mark.asyncio
    async def test_batch_modify_partial_failure(self, mock_service):
        connector = await mock_service._get_connector("gmail", "test-user-001")
        connector.batch_modify.side_effect = RuntimeError("Batch fail")

        async def modify_with_failure(msg_id, add_labels=None, remove_labels=None):
            if msg_id == "m2":
                raise OSError("Failed for m2")

        connector.modify_labels = modify_with_failure
        data = {"message_ids": ["m1", "m2"], "add_labels": ["label"]}
        result = await handle_batch_modify(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["successful_count"] == 1
        assert body["error_count"] == 1
        assert body["partial_success"] is True

    @pytest.mark.asyncio
    async def test_batch_modify_connector_exception(self, mock_service):
        mock_service._get_connector.side_effect = KeyError("No provider")
        data = {"message_ids": ["m1"], "add_labels": ["a"]}
        result = await handle_batch_modify(data, user_id="test-user-001")
        assert _status(result) == 500


# ============================================================================
# Get Action Logs
# ============================================================================


class TestGetActionLogs:
    """Tests for handle_get_action_logs."""

    @pytest.mark.asyncio
    async def test_get_logs_empty(self, mock_service):
        mock_service.get_action_logs.return_value = []
        data = {}
        result = await handle_get_action_logs(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["logs"] == []
        assert body["count"] == 0

    @pytest.mark.asyncio
    async def test_get_logs_with_results(self, mock_service):
        mock_service.get_action_logs.return_value = [MockActionLog(), MockActionLog(id="log-002")]
        data = {}
        result = await handle_get_action_logs(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["count"] == 2

    @pytest.mark.asyncio
    async def test_get_logs_with_action_type_filter(self, mock_service):
        mock_service.get_action_logs.return_value = []
        data = {"action_type": "send"}
        result = await handle_get_action_logs(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_logs_invalid_action_type(self):
        data = {"action_type": "nonexistent_action"}
        result = await handle_get_action_logs(data, user_id="test-user-001")
        assert _status(result) == 400
        assert "action_type" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_get_logs_with_provider_filter(self, mock_service):
        mock_service.get_action_logs.return_value = []
        data = {"provider": "gmail"}
        result = await handle_get_action_logs(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_logs_invalid_provider(self):
        data = {"provider": "yahoo"}
        result = await handle_get_action_logs(data, user_id="test-user-001")
        assert _status(result) == 400
        assert "provider" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_get_logs_with_since_filter(self, mock_service):
        mock_service.get_action_logs.return_value = []
        data = {"since": "2025-01-01T00:00:00Z"}
        result = await handle_get_action_logs(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_logs_invalid_since(self):
        data = {"since": "not-a-date"}
        result = await handle_get_action_logs(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_get_logs_custom_limit(self, mock_service):
        mock_service.get_action_logs.return_value = []
        data = {"limit": 50}
        result = await handle_get_action_logs(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["limit"] == 50

    @pytest.mark.asyncio
    async def test_get_logs_limit_capped_at_1000(self, mock_service):
        mock_service.get_action_logs.return_value = []
        data = {"limit": 5000}
        result = await handle_get_action_logs(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["limit"] == 1000

    @pytest.mark.asyncio
    async def test_get_logs_default_limit(self, mock_service):
        mock_service.get_action_logs.return_value = []
        data = {}
        result = await handle_get_action_logs(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["limit"] == 100

    @pytest.mark.asyncio
    async def test_get_logs_service_exception(self, mock_service):
        mock_service.get_action_logs.side_effect = RuntimeError("DB error")
        data = {}
        result = await handle_get_action_logs(data, user_id="test-user-001")
        assert _status(result) == 500


# ============================================================================
# Export Action Logs
# ============================================================================


class TestExportActionLogs:
    """Tests for handle_export_action_logs."""

    @pytest.mark.asyncio
    async def test_export_success(self, mock_service):
        mock_service.export_action_logs.return_value = [{"id": "log-1"}]
        data = {
            "start_date": "2025-01-01T00:00:00Z",
            "end_date": "2025-01-31T23:59:59Z",
        }
        result = await handle_export_action_logs(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["count"] == 1
        assert body["user_id"] == "test-user-001"
        assert "exported_at" in body

    @pytest.mark.asyncio
    async def test_export_missing_start_date(self):
        data = {"end_date": "2025-01-31T00:00:00Z"}
        result = await handle_export_action_logs(data, user_id="test-user-001")
        assert _status(result) == 400
        assert (
            "start_date" in _body(result).get("error", "").lower()
            or "end_date" in _body(result).get("error", "").lower()
        )

    @pytest.mark.asyncio
    async def test_export_missing_end_date(self):
        data = {"start_date": "2025-01-01T00:00:00Z"}
        result = await handle_export_action_logs(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_export_missing_both_dates(self):
        data = {}
        result = await handle_export_action_logs(data, user_id="test-user-001")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_export_invalid_date_format(self):
        data = {"start_date": "not-a-date", "end_date": "2025-01-31T00:00:00Z"}
        result = await handle_export_action_logs(data, user_id="test-user-001")
        assert _status(result) == 400
        assert (
            "iso" in _body(result).get("error", "").lower()
            or "format" in _body(result).get("error", "").lower()
        )

    @pytest.mark.asyncio
    async def test_export_end_before_start(self):
        data = {
            "start_date": "2025-02-01T00:00:00Z",
            "end_date": "2025-01-01T00:00:00Z",
        }
        result = await handle_export_action_logs(data, user_id="test-user-001")
        assert _status(result) == 400
        assert "after" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_export_exceeds_90_day_range(self):
        data = {
            "start_date": "2025-01-01T00:00:00Z",
            "end_date": "2025-06-01T00:00:00Z",
        }
        result = await handle_export_action_logs(data, user_id="test-user-001")
        assert _status(result) == 400
        assert "90" in _body(result).get("error", "")

    @pytest.mark.asyncio
    async def test_export_exactly_90_days(self, mock_service):
        mock_service.export_action_logs.return_value = []
        data = {
            "start_date": "2025-01-01T00:00:00+00:00",
            "end_date": "2025-04-01T00:00:00+00:00",
        }
        result = await handle_export_action_logs(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_export_empty_results(self, mock_service):
        mock_service.export_action_logs.return_value = []
        data = {
            "start_date": "2025-01-01T00:00:00Z",
            "end_date": "2025-01-02T00:00:00Z",
        }
        result = await handle_export_action_logs(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert body["count"] == 0
        assert body["logs"] == []

    @pytest.mark.asyncio
    async def test_export_service_exception(self, mock_service):
        mock_service.export_action_logs.side_effect = OSError("File error")
        data = {
            "start_date": "2025-01-01T00:00:00Z",
            "end_date": "2025-01-02T00:00:00Z",
        }
        result = await handle_export_action_logs(data, user_id="test-user-001")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_export_with_z_suffix(self, mock_service):
        mock_service.export_action_logs.return_value = []
        data = {
            "start_date": "2025-01-01T00:00:00Z",
            "end_date": "2025-01-31T23:59:59Z",
        }
        result = await handle_export_action_logs(data, user_id="test-user-001")
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_export_response_includes_dates(self, mock_service):
        mock_service.export_action_logs.return_value = []
        data = {
            "start_date": "2025-03-01T00:00:00+00:00",
            "end_date": "2025-03-15T00:00:00+00:00",
        }
        result = await handle_export_action_logs(data, user_id="test-user-001")
        assert _status(result) == 200
        body = _data(result)
        assert "start_date" in body
        assert "end_date" in body


# ============================================================================
# Cross-cutting: default provider
# ============================================================================


class TestDefaultProvider:
    """Tests that verify default provider is 'gmail' when not specified."""

    @pytest.mark.asyncio
    async def test_archive_default_provider(self, monkeypatch, mock_service):
        created = _make_wedge_envelope(
            receipt_id="receipt-created",
            state=ReceiptState.CREATED,
            provider="gmail",
            message_id="msg-1",
        )
        wedge_service = MagicMock()
        wedge_service.create_receipt = MagicMock(return_value=created)
        monkeypatch.setattr(
            "aragora.server.handlers.inbox.email_actions.get_inbox_trust_wedge_service_instance",
            lambda: wedge_service,
        )

        data = {"message_id": "msg-1", "create_receipt": True}
        result = await handle_archive_message(data, user_id="test-user-001")
        assert _status(result) == 200
        intent = wedge_service.create_receipt.call_args.args[0]
        assert intent.provider == "gmail"
        mock_service.archive.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_trash_default_provider(self, mock_service):
        data = {"message_id": "msg-1"}
        result = await handle_trash_message(data, user_id="test-user-001")
        assert _status(result) == 200
        call_kwargs = mock_service.trash.call_args
        assert (
            call_kwargs.kwargs.get("provider") == "gmail"
            or call_kwargs[1].get("provider") == "gmail"
        )


# ============================================================================
# Cross-cutting: message_id precedence
# ============================================================================


class TestMessageIdPrecedence:
    """Tests that message_id parameter takes precedence over body field."""

    @pytest.mark.asyncio
    async def test_param_takes_precedence_over_body(self, mock_service):
        data = {"message_id": "body-id", "body": "reply"}
        result = await handle_reply_email(data, message_id="param-id", user_id="test-user-001")
        assert _status(result) == 200
        call_kwargs = mock_service.reply.call_args
        assert (
            call_kwargs.kwargs.get("message_id") == "param-id"
            or call_kwargs[1].get("message_id") == "param-id"
        )

    @pytest.mark.asyncio
    async def test_falls_back_to_body_when_param_empty(self, mock_service):
        data = {"message_id": "body-id", "body": "reply"}
        result = await handle_reply_email(data, message_id="", user_id="test-user-001")
        assert _status(result) == 200
        call_kwargs = mock_service.reply.call_args
        assert (
            call_kwargs.kwargs.get("message_id") == "body-id"
            or call_kwargs[1].get("message_id") == "body-id"
        )
