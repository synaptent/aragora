"""
Tests for Email Actions Service.

Tests for the unified email actions service including:
- Email sending, replying, forwarding
- Archive/trash operations
- Snooze functionality
- Label/folder management
- Batch operations
- Action logging and audit trail
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


class TestActionEnums:
    """Tests for action-related enums."""

    def test_email_provider_values(self):
        """Test EmailProvider enum values."""
        from aragora.services.email_actions import EmailProvider

        assert EmailProvider.GMAIL.value == "gmail"
        assert EmailProvider.OUTLOOK.value == "outlook"

    def test_action_type_values(self):
        """Test ActionType enum values."""
        from aragora.services.email_actions import ActionType

        assert ActionType.SEND.value == "send"
        assert ActionType.REPLY.value == "reply"
        assert ActionType.FORWARD.value == "forward"
        assert ActionType.ARCHIVE.value == "archive"
        assert ActionType.TRASH.value == "trash"
        assert ActionType.SNOOZE.value == "snooze"
        assert ActionType.MARK_READ.value == "mark_read"
        assert ActionType.STAR.value == "star"
        assert ActionType.IGNORE.value == "ignore"
        assert ActionType.MOVE_TO_FOLDER.value == "move_to_folder"
        assert ActionType.BATCH_ARCHIVE.value == "batch_archive"

    def test_action_status_values(self):
        """Test ActionStatus enum values."""
        from aragora.services.email_actions import ActionStatus

        assert ActionStatus.PENDING.value == "pending"
        assert ActionStatus.SUCCESS.value == "success"
        assert ActionStatus.FAILED.value == "failed"
        assert ActionStatus.CANCELLED.value == "cancelled"


class TestActionLog:
    """Tests for ActionLog dataclass."""

    def test_action_log_creation(self):
        """Test creating an ActionLog."""
        from aragora.services.email_actions import (
            ActionLog,
            ActionType,
            ActionStatus,
            EmailProvider,
        )

        log = ActionLog(
            id="action_001",
            user_id="user_123",
            action_type=ActionType.SEND,
            provider=EmailProvider.GMAIL,
            message_ids=["msg_1", "msg_2"],
            status=ActionStatus.SUCCESS,
            timestamp=datetime.now(timezone.utc),
            details={"to": ["recipient@example.com"]},
            duration_ms=150.5,
        )

        assert log.id == "action_001"
        assert log.user_id == "user_123"
        assert log.action_type == ActionType.SEND
        assert log.provider == EmailProvider.GMAIL
        assert len(log.message_ids) == 2
        assert log.status == ActionStatus.SUCCESS
        assert log.error_message is None
        assert log.duration_ms == 150.5

    def test_action_log_to_dict(self):
        """Test ActionLog.to_dict serialization."""
        from aragora.services.email_actions import (
            ActionLog,
            ActionType,
            ActionStatus,
            EmailProvider,
        )

        timestamp = datetime.now(timezone.utc)
        log = ActionLog(
            id="action_002",
            user_id="user_456",
            action_type=ActionType.ARCHIVE,
            provider=EmailProvider.OUTLOOK,
            message_ids=["msg_3"],
            status=ActionStatus.SUCCESS,
            timestamp=timestamp,
        )

        data = log.to_dict()

        assert data["id"] == "action_002"
        assert data["userId"] == "user_456"
        assert data["actionType"] == "archive"
        assert data["provider"] == "outlook"
        assert data["messageIds"] == ["msg_3"]
        assert data["status"] == "success"
        assert data["timestamp"] == timestamp.isoformat()
        assert data["errorMessage"] is None

    def test_action_log_with_error(self):
        """Test ActionLog with error message."""
        from aragora.services.email_actions import (
            ActionLog,
            ActionType,
            ActionStatus,
            EmailProvider,
        )

        log = ActionLog(
            id="action_003",
            user_id="user_789",
            action_type=ActionType.SEND,
            provider=EmailProvider.GMAIL,
            message_ids=[],
            status=ActionStatus.FAILED,
            timestamp=datetime.now(timezone.utc),
            error_message="SMTP connection failed",
            duration_ms=2500.0,
        )

        assert log.status == ActionStatus.FAILED
        assert log.error_message == "SMTP connection failed"
        assert log.duration_ms == 2500.0


class TestSendEmailRequest:
    """Tests for SendEmailRequest dataclass."""

    def test_send_request_minimal(self):
        """Test minimal SendEmailRequest."""
        from aragora.services.email_actions import SendEmailRequest

        request = SendEmailRequest(
            to=["recipient@example.com"],
            subject="Test Subject",
            body="Test body",
        )

        assert request.to == ["recipient@example.com"]
        assert request.subject == "Test Subject"
        assert request.body == "Test body"
        assert request.cc is None
        assert request.bcc is None
        assert request.attachments is None

    def test_send_request_full(self):
        """Test full SendEmailRequest with all fields."""
        from aragora.services.email_actions import SendEmailRequest

        request = SendEmailRequest(
            to=["to@example.com"],
            subject="Full Email",
            body="Plain text body",
            cc=["cc@example.com"],
            bcc=["bcc@example.com"],
            reply_to="reply-to@example.com",
            html_body="<p>HTML body</p>",
            attachments=[{"filename": "doc.pdf", "content": "base64data"}],
        )

        assert len(request.cc) == 1
        assert len(request.bcc) == 1
        assert request.reply_to == "reply-to@example.com"
        assert request.html_body == "<p>HTML body</p>"
        assert len(request.attachments) == 1


class TestSnoozeRequest:
    """Tests for SnoozeRequest dataclass."""

    def test_snooze_request_creation(self):
        """Test creating a SnoozeRequest."""
        from aragora.services.email_actions import SnoozeRequest

        snooze_time = datetime.now(timezone.utc) + timedelta(hours=2)
        request = SnoozeRequest(
            message_id="msg_123",
            snooze_until=snooze_time,
        )

        assert request.message_id == "msg_123"
        assert request.snooze_until == snooze_time
        assert request.restore_to_inbox is True

    def test_snooze_request_no_restore(self):
        """Test SnoozeRequest with restore_to_inbox=False."""
        from aragora.services.email_actions import SnoozeRequest

        snooze_time = datetime.now(timezone.utc) + timedelta(days=1)
        request = SnoozeRequest(
            message_id="msg_456",
            snooze_until=snooze_time,
            restore_to_inbox=False,
        )

        assert request.restore_to_inbox is False


class TestActionResult:
    """Tests for ActionResult dataclass."""

    def test_action_result_success(self):
        """Test successful ActionResult."""
        from aragora.services.email_actions import ActionResult, ActionType

        result = ActionResult(
            success=True,
            action_type=ActionType.ARCHIVE,
            message_ids=["msg_1"],
            details={"archived": True},
        )

        assert result.success is True
        assert result.action_type == ActionType.ARCHIVE
        assert result.error is None

    def test_action_result_failure(self):
        """Test failed ActionResult."""
        from aragora.services.email_actions import ActionResult, ActionType

        result = ActionResult(
            success=False,
            action_type=ActionType.SEND,
            message_ids=[],
            error="Failed to connect to mail server",
        )

        assert result.success is False
        assert result.error == "Failed to connect to mail server"

    def test_action_result_to_dict(self):
        """Test ActionResult.to_dict serialization."""
        from aragora.services.email_actions import ActionResult, ActionType

        result = ActionResult(
            success=True,
            action_type=ActionType.STAR,
            message_ids=["msg_123"],
            details={"starred": True},
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["actionType"] == "star"
        assert data["messageIds"] == ["msg_123"]
        assert data["details"]["starred"] is True


class TestEmailActionsService:
    """Tests for EmailActionsService."""

    def test_service_initialization(self):
        """Test service initialization."""
        from aragora.services.email_actions import EmailActionsService

        service = EmailActionsService()

        assert service._action_logs == []
        assert service._snoozed_messages == {}
        assert service._connectors == {}
        assert service._action_counter == 0

    def test_generate_action_id(self):
        """Test action ID generation."""
        from aragora.services.email_actions import EmailActionsService

        service = EmailActionsService()

        id1 = service._generate_action_id()
        id2 = service._generate_action_id()

        assert id1.startswith("action_")
        assert id2.startswith("action_")
        assert id1 != id2
        assert service._action_counter == 2

    @pytest.mark.asyncio
    async def test_get_connector_gmail(self):
        """Test getting Gmail connector."""
        from aragora.services.email_actions import EmailActionsService

        service = EmailActionsService()
        mock_store = MagicMock()
        mock_store.get = AsyncMock(
            return_value=MagicMock(
                access_token="access-token",
                refresh_token="refresh-token",
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )

        with patch(
            "aragora.connectors.enterprise.communication.gmail.GmailConnector"
        ) as mock_gmail:
            connector_instance = MagicMock()
            mock_gmail.return_value = connector_instance
            with patch(
                "aragora.storage.gmail_token_store.get_gmail_token_store",
                return_value=mock_store,
            ):
                connector = await service._get_connector("gmail", "user_123")

            assert connector is not None
            mock_gmail.assert_called_once()
            mock_store.get.assert_awaited_once_with("user_123")
            assert connector_instance._access_token == "access-token"
            assert connector_instance._refresh_token == "refresh-token"

    @pytest.mark.asyncio
    async def test_get_connector_outlook(self):
        """Test getting Outlook connector."""
        from aragora.services.email_actions import EmailActionsService

        service = EmailActionsService()

        with patch(
            "aragora.connectors.enterprise.communication.outlook.OutlookConnector"
        ) as mock_outlook:
            mock_outlook.return_value = MagicMock()
            connector = await service._get_connector("outlook", "user_456")

            assert connector is not None
            mock_outlook.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_connector_unsupported(self):
        """Test error for unsupported provider."""
        from aragora.services.email_actions import EmailActionsService

        service = EmailActionsService()

        with pytest.raises(ValueError, match="Unsupported provider"):
            await service._get_connector("yahoo", "user_789")

    @pytest.mark.asyncio
    async def test_get_connector_caching(self):
        """Test connector caching."""
        from aragora.services.email_actions import EmailActionsService

        service = EmailActionsService()
        mock_store = MagicMock()
        mock_store.get = AsyncMock(
            return_value=MagicMock(
                access_token="access-token",
                refresh_token="refresh-token",
                token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )

        with patch(
            "aragora.connectors.enterprise.communication.gmail.GmailConnector"
        ) as mock_gmail:
            mock_gmail.return_value = MagicMock()
            with patch(
                "aragora.storage.gmail_token_store.get_gmail_token_store",
                return_value=mock_store,
            ):
                connector1 = await service._get_connector("gmail", "user_123")
                connector2 = await service._get_connector("gmail", "user_123")

            assert connector1 is connector2
            mock_gmail.assert_called_once()  # Only one instantiation
            mock_store.get.assert_awaited_once_with("user_123")

    @pytest.mark.asyncio
    async def test_get_connector_gmail_requires_saved_tokens(self):
        """Gmail connector creation should fail closed when no OAuth state exists."""
        from aragora.services.email_actions import EmailActionsService

        service = EmailActionsService()
        mock_store = MagicMock()
        mock_store.get = AsyncMock(return_value=None)

        with patch(
            "aragora.storage.gmail_token_store.get_gmail_token_store",
            return_value=mock_store,
        ):
            with pytest.raises(RuntimeError, match="not authenticated"):
                await service._get_connector("gmail", "user_123")

    @pytest.mark.asyncio
    async def test_log_action(self):
        """Test action logging."""
        from aragora.services.email_actions import (
            EmailActionsService,
            ActionType,
            ActionStatus,
        )

        service = EmailActionsService()

        log = await service._log_action(
            user_id="user_123",
            action_type=ActionType.ARCHIVE,
            provider="gmail",
            message_ids=["msg_1"],
            status=ActionStatus.SUCCESS,
            details={"archived": True},
            duration_ms=100.0,
        )

        assert log.user_id == "user_123"
        assert log.action_type == ActionType.ARCHIVE
        assert log.status == ActionStatus.SUCCESS
        assert len(service._action_logs) == 1

    @pytest.mark.asyncio
    async def test_log_action_limit(self):
        """Test action log limit (10000)."""
        from aragora.services.email_actions import (
            EmailActionsService,
            ActionType,
            ActionStatus,
        )

        service = EmailActionsService()

        # Add 10005 logs
        for i in range(10005):
            await service._log_action(
                user_id="user",
                action_type=ActionType.ARCHIVE,
                provider="gmail",
                message_ids=[f"msg_{i}"],
                status=ActionStatus.SUCCESS,
            )

        # Should be limited to 10000
        assert len(service._action_logs) == 10000


class TestEmailActionsServiceActions:
    """Tests for actual email actions."""

    @pytest.fixture
    def mock_connector(self):
        """Create a mock connector."""
        connector = AsyncMock()
        connector.send_message = AsyncMock(
            return_value={"message_id": "sent_123", "thread_id": "thread_456"}
        )
        connector.reply_to_message = AsyncMock(
            return_value={"message_id": "reply_123", "thread_id": "thread_456"}
        )
        connector.archive_message = AsyncMock(return_value={"archived": True})
        connector.trash_message = AsyncMock(return_value={"trashed": True})
        connector.snooze_message = AsyncMock(return_value={"snoozed": True})
        connector.mark_as_read = AsyncMock(return_value={"read": True})
        connector.star_message = AsyncMock(return_value={"starred": True})
        connector.add_label = AsyncMock(return_value={"labels": ["TRIAGE"]})
        connector.move_to_folder = AsyncMock(return_value={"moved": True})
        connector.batch_archive = AsyncMock(return_value={"archived_count": 3})
        return connector

    @pytest.mark.asyncio
    async def test_send_email_success(self, mock_connector):
        """Test sending an email successfully."""
        from aragora.services.email_actions import (
            EmailActionsService,
            SendEmailRequest,
            ActionType,
        )

        service = EmailActionsService()
        service._connectors["gmail:user_123"] = mock_connector

        request = SendEmailRequest(
            to=["recipient@example.com"],
            subject="Test Subject",
            body="Test body",
        )

        result = await service.send("gmail", "user_123", request)

        assert result.success is True
        assert result.action_type == ActionType.SEND
        assert "sent_123" in result.message_ids
        mock_connector.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_email_failure(self, mock_connector):
        """Test sending an email that fails."""
        from aragora.services.email_actions import (
            EmailActionsService,
            SendEmailRequest,
            ActionType,
        )

        mock_connector.send_message.side_effect = OSError("SMTP error")
        service = EmailActionsService()
        service._connectors["gmail:user_123"] = mock_connector

        request = SendEmailRequest(
            to=["recipient@example.com"],
            subject="Test",
            body="Body",
        )

        result = await service.send("gmail", "user_123", request)

        assert result.success is False
        assert result.action_type == ActionType.SEND
        assert result.error == "Send failed"

    @pytest.mark.asyncio
    async def test_reply_email_success(self, mock_connector):
        """Test replying to an email."""
        from aragora.services.email_actions import EmailActionsService, ActionType

        service = EmailActionsService()
        service._connectors["gmail:user_123"] = mock_connector

        result = await service.reply(
            provider="gmail",
            user_id="user_123",
            message_id="original_msg",
            body="This is my reply",
        )

        assert result.success is True
        assert result.action_type == ActionType.REPLY
        mock_connector.reply_to_message.assert_called_once_with(
            original_message_id="original_msg",
            body="This is my reply",
            cc=None,
            html_body=None,
        )

    @pytest.mark.asyncio
    async def test_archive_success(self, mock_connector):
        """Test archiving a message."""
        from aragora.services.email_actions import EmailActionsService, ActionType

        service = EmailActionsService()
        service._connectors["gmail:user_123"] = mock_connector

        result = await service.archive("gmail", "user_123", "msg_to_archive")

        assert result.success is True
        assert result.action_type == ActionType.ARCHIVE
        assert "msg_to_archive" in result.message_ids
        mock_connector.archive_message.assert_called_once_with("msg_to_archive")

    @pytest.mark.asyncio
    async def test_trash_success(self, mock_connector):
        """Test trashing a message."""
        from aragora.services.email_actions import EmailActionsService, ActionType

        service = EmailActionsService()
        service._connectors["gmail:user_123"] = mock_connector

        result = await service.trash("gmail", "user_123", "msg_to_trash")

        assert result.success is True
        assert result.action_type == ActionType.TRASH
        mock_connector.trash_message.assert_called_once_with("msg_to_trash")

    @pytest.mark.asyncio
    async def test_snooze_success(self, mock_connector):
        """Test snoozing a message."""
        from aragora.services.email_actions import EmailActionsService, ActionType

        service = EmailActionsService()
        service._connectors["gmail:user_123"] = mock_connector

        snooze_time = datetime.now(timezone.utc) + timedelta(hours=2)
        result = await service.snooze("gmail", "user_123", "msg_to_snooze", snooze_time)

        assert result.success is True
        assert result.action_type == ActionType.SNOOZE

        # Check snooze was stored
        snooze_key = "gmail:user_123:msg_to_snooze"
        assert snooze_key in service._snoozed_messages
        assert service._snoozed_messages[snooze_key].snooze_until == snooze_time

    @pytest.mark.asyncio
    async def test_mark_read_success(self, mock_connector):
        """Test marking a message as read."""
        from aragora.services.email_actions import EmailActionsService, ActionType

        service = EmailActionsService()
        service._connectors["gmail:user_123"] = mock_connector

        result = await service.mark_read("gmail", "user_123", "msg_to_mark")

        assert result.success is True
        assert result.action_type == ActionType.MARK_READ
        mock_connector.mark_as_read.assert_called_once_with("msg_to_mark")

    @pytest.mark.asyncio
    async def test_star_success(self, mock_connector):
        """Test starring a message."""
        from aragora.services.email_actions import EmailActionsService, ActionType

        service = EmailActionsService()
        service._connectors["gmail:user_123"] = mock_connector

        result = await service.star("gmail", "user_123", "msg_to_star")

        assert result.success is True
        assert result.action_type == ActionType.STAR
        mock_connector.star_message.assert_called_once_with("msg_to_star")

    @pytest.mark.asyncio
    async def test_move_to_folder_success(self, mock_connector):
        """Test moving a message to a folder."""
        from aragora.services.email_actions import EmailActionsService, ActionType

        service = EmailActionsService()
        service._connectors["outlook:user_123"] = mock_connector

        result = await service.move_to_folder("outlook", "user_123", "msg_to_move", "Archive/2024")

        assert result.success is True
        assert result.action_type == ActionType.MOVE_TO_FOLDER
        mock_connector.move_to_folder.assert_called_once_with("msg_to_move", "Archive/2024")

    @pytest.mark.asyncio
    async def test_add_label_success(self, mock_connector):
        """Test labeling a message."""
        from aragora.services.email_actions import EmailActionsService, ActionType

        service = EmailActionsService()
        service._connectors["gmail:user_123"] = mock_connector

        result = await service.add_label("gmail", "user_123", "msg_to_label", "TRIAGE")

        assert result.success is True
        assert result.action_type == ActionType.ADD_LABEL
        mock_connector.add_label.assert_called_once_with("msg_to_label", "TRIAGE")

    @pytest.mark.asyncio
    async def test_ignore_success(self, mock_connector):
        """Test no-op ignore action."""
        from aragora.services.email_actions import EmailActionsService, ActionType

        service = EmailActionsService()
        service._connectors["gmail:user_123"] = mock_connector

        result = await service.ignore("gmail", "user_123", "msg_to_ignore")

        assert result.success is True
        assert result.action_type == ActionType.IGNORE
        assert result.details["ignored"] is True

    @pytest.mark.asyncio
    async def test_batch_archive_success(self, mock_connector):
        """Test batch archiving messages."""
        from aragora.services.email_actions import EmailActionsService, ActionType

        service = EmailActionsService()
        service._connectors["gmail:user_123"] = mock_connector

        message_ids = ["msg_1", "msg_2", "msg_3"]
        result = await service.batch_archive("gmail", "user_123", message_ids)

        assert result.success is True
        assert result.action_type == ActionType.BATCH_ARCHIVE
        assert result.message_ids == message_ids
        mock_connector.batch_archive.assert_called_once_with(message_ids)


class TestEmailActionsServiceLogs:
    """Tests for action log retrieval and export."""

    @pytest.mark.asyncio
    async def test_get_action_logs_all(self):
        """Test getting all action logs."""
        from aragora.services.email_actions import (
            EmailActionsService,
            ActionType,
            ActionStatus,
        )

        service = EmailActionsService()

        # Add some logs
        for i in range(5):
            await service._log_action(
                user_id="user_123",
                action_type=ActionType.ARCHIVE,
                provider="gmail",
                message_ids=[f"msg_{i}"],
                status=ActionStatus.SUCCESS,
            )

        logs = await service.get_action_logs()

        assert len(logs) == 5

    @pytest.mark.asyncio
    async def test_get_action_logs_filter_user(self):
        """Test filtering logs by user."""
        from aragora.services.email_actions import (
            EmailActionsService,
            ActionType,
            ActionStatus,
        )

        service = EmailActionsService()

        await service._log_action(
            user_id="user_A",
            action_type=ActionType.ARCHIVE,
            provider="gmail",
            message_ids=["msg_1"],
            status=ActionStatus.SUCCESS,
        )
        await service._log_action(
            user_id="user_B",
            action_type=ActionType.ARCHIVE,
            provider="gmail",
            message_ids=["msg_2"],
            status=ActionStatus.SUCCESS,
        )

        logs = await service.get_action_logs(user_id="user_A")

        assert len(logs) == 1
        assert logs[0].user_id == "user_A"

    @pytest.mark.asyncio
    async def test_get_action_logs_filter_action_type(self):
        """Test filtering logs by action type."""
        from aragora.services.email_actions import (
            EmailActionsService,
            ActionType,
            ActionStatus,
        )

        service = EmailActionsService()

        await service._log_action(
            user_id="user",
            action_type=ActionType.SEND,
            provider="gmail",
            message_ids=["msg_1"],
            status=ActionStatus.SUCCESS,
        )
        await service._log_action(
            user_id="user",
            action_type=ActionType.ARCHIVE,
            provider="gmail",
            message_ids=["msg_2"],
            status=ActionStatus.SUCCESS,
        )

        logs = await service.get_action_logs(action_type=ActionType.SEND)

        assert len(logs) == 1
        assert logs[0].action_type == ActionType.SEND

    @pytest.mark.asyncio
    async def test_get_action_logs_filter_since(self):
        """Test filtering logs by timestamp."""
        from aragora.services.email_actions import (
            EmailActionsService,
            ActionType,
            ActionStatus,
        )

        service = EmailActionsService()

        await service._log_action(
            user_id="user",
            action_type=ActionType.ARCHIVE,
            provider="gmail",
            message_ids=["msg_1"],
            status=ActionStatus.SUCCESS,
        )

        # Logs since now should include the one we just added
        since_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        logs = await service.get_action_logs(since=since_time)

        assert len(logs) >= 1

    @pytest.mark.asyncio
    async def test_get_action_logs_limit(self):
        """Test limiting log results."""
        from aragora.services.email_actions import (
            EmailActionsService,
            ActionType,
            ActionStatus,
        )

        service = EmailActionsService()

        for i in range(10):
            await service._log_action(
                user_id="user",
                action_type=ActionType.ARCHIVE,
                provider="gmail",
                message_ids=[f"msg_{i}"],
                status=ActionStatus.SUCCESS,
            )

        logs = await service.get_action_logs(limit=3)

        assert len(logs) == 3

    @pytest.mark.asyncio
    async def test_export_action_logs(self):
        """Test exporting action logs."""
        from aragora.services.email_actions import (
            EmailActionsService,
            ActionType,
            ActionStatus,
        )

        service = EmailActionsService()

        await service._log_action(
            user_id="user_export",
            action_type=ActionType.SEND,
            provider="gmail",
            message_ids=["msg_1"],
            status=ActionStatus.SUCCESS,
        )

        start = datetime.now(timezone.utc) - timedelta(hours=1)
        end = datetime.now(timezone.utc) + timedelta(hours=1)

        exported = await service.export_action_logs("user_export", start, end)

        assert len(exported) == 1
        assert exported[0]["userId"] == "user_export"


class TestEmailActionsServiceSingleton:
    """Tests for singleton pattern."""

    def test_get_email_actions_service(self):
        """Test getting singleton service."""
        from aragora.services.email_actions import (
            get_email_actions_service,
            EmailActionsService,
        )

        # Reset singleton
        import aragora.services.email_actions as module

        module._email_actions_service = None

        service1 = get_email_actions_service()
        service2 = get_email_actions_service()

        assert service1 is service2
        assert isinstance(service1, EmailActionsService)


class TestEmailProviderEnum:
    """Tests for EmailProvider with enum provider parameter."""

    @pytest.mark.asyncio
    async def test_action_with_enum_provider(self):
        """Test action with EmailProvider enum."""
        from aragora.services.email_actions import (
            EmailActionsService,
            EmailProvider,
        )

        service = EmailActionsService()

        mock_connector = AsyncMock()
        mock_connector.archive_message = AsyncMock(return_value={"archived": True})
        service._connectors["gmail:user_123"] = mock_connector

        result = await service.archive(EmailProvider.GMAIL, "user_123", "msg_1")

        assert result.success is True
        mock_connector.archive_message.assert_called_once()
