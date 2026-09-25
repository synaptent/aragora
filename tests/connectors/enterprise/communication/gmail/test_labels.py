"""
Tests for Gmail Labels Mixin.

Comprehensive tests for GmailLabelsMixin covering:
- Label listing and creation
- Message label modification
- Email actions (archive, trash, star, mark read/unread, etc.)
- Snooze functionality
- Batch operations (batch modify, batch archive, batch trash)
- Circuit breaker integration
- Error handling
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from aragora.connectors.enterprise.communication.models import GmailLabel


# =============================================================================
# Test Fixtures
# =============================================================================


class MockAsyncContextManager:
    """Mock async context manager for HTTP client."""

    def __init__(self, mock_client):
        self.mock_client = mock_client

    async def __aenter__(self):
        return self.mock_client

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class MockGmailBase:
    """Mock base class that implements GmailBaseMethods protocol."""

    def __init__(self):
        self.user_id = "me"
        self._access_token = "test_token"
        self._circuit_open = False
        self._failure_count = 0
        self._success_count = 0
        self._mock_client = None

    async def _get_access_token(self) -> str:
        return self._access_token

    async def _api_request(self, endpoint: str, method: str = "GET", **kwargs):
        return {}

    def _get_client(self):
        """Return context manager for HTTP client."""
        if self._mock_client is None:
            self._mock_client = AsyncMock()
        return MockAsyncContextManager(self._mock_client)

    def check_circuit_breaker(self) -> bool:
        return not self._circuit_open

    def get_circuit_breaker_status(self) -> dict:
        return {"cooldown_seconds": 60, "failure_count": self._failure_count}

    def record_success(self) -> None:
        self._success_count += 1

    def record_failure(self) -> None:
        self._failure_count += 1


@pytest.fixture
def mock_httpx_response():
    """Factory for creating mock httpx responses."""

    def _create(status_code: int = 200, json_data: dict = None, content: bytes = b""):
        response = Mock()
        response.status_code = status_code
        response.json = Mock(return_value=json_data or {})
        response.content = content or b"{}"
        response.text = (json_data and str(json_data)) or "{}"
        response.raise_for_status = Mock()
        if status_code >= 400:
            import httpx

            request = httpx.Request("GET", "https://gmail.googleapis.com/test")
            response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Error", request=request, response=response
            )
        return response

    return _create


@pytest.fixture
def labels_mixin():
    """Create a labels mixin instance with mock base."""
    from aragora.connectors.enterprise.communication.gmail.labels import GmailLabelsMixin

    class TestMixin(GmailLabelsMixin, MockGmailBase):
        pass

    return TestMixin()


# =============================================================================
# List Labels Tests
# =============================================================================


class TestListLabels:
    """Tests for listing Gmail labels."""

    @pytest.mark.asyncio
    async def test_list_labels_success(self, labels_mixin):
        """Test listing labels returns GmailLabel objects."""
        labels_data = {
            "labels": [
                {
                    "id": "INBOX",
                    "name": "INBOX",
                    "type": "system",
                    "messageListVisibility": "show",
                    "labelListVisibility": "labelShow",
                },
                {
                    "id": "Label_1",
                    "name": "Work",
                    "type": "user",
                    "messageListVisibility": "show",
                    "labelListVisibility": "labelShow",
                },
                {
                    "id": "Label_2",
                    "name": "Personal",
                    "type": "user",
                },
            ]
        }

        with patch.object(labels_mixin, "_api_request", return_value=labels_data):
            labels = await labels_mixin.list_labels()

            assert len(labels) == 3
            assert isinstance(labels[0], GmailLabel)
            assert labels[0].id == "INBOX"
            assert labels[0].type == "system"
            assert labels[1].name == "Work"
            assert labels[2].name == "Personal"

    @pytest.mark.asyncio
    async def test_list_labels_empty(self, labels_mixin):
        """Test listing labels when no labels exist."""
        with patch.object(labels_mixin, "_api_request", return_value={"labels": []}):
            labels = await labels_mixin.list_labels()
            assert labels == []

    @pytest.mark.asyncio
    async def test_list_labels_missing_fields(self, labels_mixin):
        """Test listing labels handles missing optional fields."""
        labels_data = {
            "labels": [
                {"id": "Label_1"},  # Only required field
            ]
        }

        with patch.object(labels_mixin, "_api_request", return_value=labels_data):
            labels = await labels_mixin.list_labels()

            assert len(labels) == 1
            assert labels[0].id == "Label_1"
            assert labels[0].name == "Label_1"  # Falls back to id
            assert labels[0].type == "user"  # Default


# =============================================================================
# Create Label Tests
# =============================================================================


class TestCreateLabel:
    """Tests for creating Gmail labels."""

    @pytest.mark.asyncio
    async def test_create_label_success(self, labels_mixin, mock_httpx_response):
        """Test creating a new label."""
        label_data = {
            "id": "Label_new",
            "name": "New Label",
            "type": "user",
            "messageListVisibility": "show",
            "labelListVisibility": "labelShow",
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, label_data))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            label = await labels_mixin.create_label("New Label")

            assert isinstance(label, GmailLabel)
            assert label.id == "Label_new"
            assert label.name == "New Label"
            assert label.type == "user"

    @pytest.mark.asyncio
    async def test_create_label_calls_correct_endpoint(self, labels_mixin, mock_httpx_response):
        """Test create label calls correct Gmail API endpoint."""
        label_data = {"id": "Label_1", "name": "Test", "type": "user"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, label_data))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            await labels_mixin.create_label("Test")

            call_args = mock_client.post.call_args
            assert "users/me/labels" in call_args[0][0]
            assert call_args.kwargs["json"]["name"] == "Test"


# =============================================================================
# Add Label Tests
# =============================================================================


class TestAddLabel:
    """Tests for adding labels to messages."""

    @pytest.mark.asyncio
    async def test_add_label_delegates_to_modify_message(self, labels_mixin):
        """Test add_label calls modify_message with correct parameters."""
        with patch.object(labels_mixin, "modify_message") as mock_modify:
            mock_modify.return_value = {"message_id": "msg_1", "success": True}

            result = await labels_mixin.add_label("msg_1", "Label_Work")

            mock_modify.assert_called_once_with("msg_1", add_labels=["Label_Work"])
            assert result["success"] is True


# =============================================================================
# Modify Message Tests
# =============================================================================


class TestModifyMessage:
    """Tests for modifying message labels."""

    @pytest.mark.asyncio
    async def test_modify_message_add_labels(self, labels_mixin, mock_httpx_response):
        """Test adding labels to a message."""
        response_data = {
            "id": "msg_123",
            "labelIds": ["INBOX", "STARRED", "Label_Work"],
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, response_data))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            result = await labels_mixin.modify_message(
                "msg_123", add_labels=["STARRED", "Label_Work"]
            )

            assert result["success"] is True
            assert result["message_id"] == "msg_123"
            assert "STARRED" in result["labels"]

    @pytest.mark.asyncio
    async def test_modify_message_remove_labels(self, labels_mixin, mock_httpx_response):
        """Test removing labels from a message."""
        response_data = {
            "id": "msg_123",
            "labelIds": ["INBOX"],
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, response_data))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            result = await labels_mixin.modify_message(
                "msg_123", remove_labels=["UNREAD", "STARRED"]
            )

            assert result["success"] is True
            assert "UNREAD" not in result["labels"]

    @pytest.mark.asyncio
    async def test_modify_message_circuit_breaker_open(self, labels_mixin):
        """Test modify_message fails when circuit breaker is open."""
        labels_mixin._circuit_open = True

        with pytest.raises(ConnectionError, match="Circuit breaker open"):
            await labels_mixin.modify_message("msg_123", add_labels=["STARRED"])

    @pytest.mark.asyncio
    async def test_modify_message_records_failure_on_5xx(self, labels_mixin, mock_httpx_response):
        """Test that 5xx errors record failures for circuit breaker."""
        error_response = mock_httpx_response(500, {"error": {"message": "Server error"}})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=error_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            with pytest.raises(RuntimeError, match="Failed to modify message"):
                await labels_mixin.modify_message("msg_123", add_labels=["STARRED"])

            assert labels_mixin._failure_count == 1

    @pytest.mark.asyncio
    async def test_modify_message_records_failure_on_429(self, labels_mixin, mock_httpx_response):
        """Test that rate limit errors record failures."""
        error_response = mock_httpx_response(429, {"error": {"message": "Rate limit exceeded"}})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=error_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            with pytest.raises(RuntimeError):
                await labels_mixin.modify_message("msg_123", add_labels=["STARRED"])

            assert labels_mixin._failure_count == 1

    @pytest.mark.asyncio
    async def test_modify_message_records_success(self, labels_mixin, mock_httpx_response):
        """Test that successful operations record success."""
        response_data = {"id": "msg_123", "labelIds": ["INBOX"]}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, response_data))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            await labels_mixin.modify_message("msg_123", add_labels=["STARRED"])

            assert labels_mixin._success_count == 1


# =============================================================================
# Archive Message Tests
# =============================================================================


class TestArchiveMessage:
    """Tests for archiving messages."""

    @pytest.mark.asyncio
    async def test_archive_message_removes_inbox_label(self, labels_mixin):
        """Test archive removes INBOX label."""
        with patch.object(labels_mixin, "modify_message") as mock_modify:
            mock_modify.return_value = {"message_id": "msg_123", "success": True}

            result = await labels_mixin.archive_message("msg_123")

            mock_modify.assert_called_once_with("msg_123", remove_labels=["INBOX"])
            assert result["success"] is True


# =============================================================================
# Trash/Untrash Message Tests
# =============================================================================


class TestTrashMessage:
    """Tests for trashing and untrashing messages."""

    @pytest.mark.asyncio
    async def test_trash_message_success(self, labels_mixin, mock_httpx_response):
        """Test trashing a message."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, {}))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            result = await labels_mixin.trash_message("msg_123")

            assert result["success"] is True
            assert result["message_id"] == "msg_123"

    @pytest.mark.asyncio
    async def test_trash_message_circuit_breaker_open(self, labels_mixin):
        """Test trash fails when circuit breaker is open."""
        labels_mixin._circuit_open = True

        with pytest.raises(ConnectionError, match="Circuit breaker open"):
            await labels_mixin.trash_message("msg_123")

    @pytest.mark.asyncio
    async def test_untrash_message_success(self, labels_mixin, mock_httpx_response):
        """Test untrashing a message."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, {}))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            result = await labels_mixin.untrash_message("msg_123")

            assert result["success"] is True
            assert result["message_id"] == "msg_123"

    @pytest.mark.asyncio
    async def test_untrash_message_records_failure_on_error(
        self, labels_mixin, mock_httpx_response
    ):
        """Test untrash records failure on server error."""
        error_response = mock_httpx_response(500, {"error": {"message": "Error"}})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=error_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            with pytest.raises(RuntimeError):
                await labels_mixin.untrash_message("msg_123")

            assert labels_mixin._failure_count == 1


# =============================================================================
# Mark Read/Unread Tests
# =============================================================================


class TestMarkReadUnread:
    """Tests for marking messages as read/unread."""

    @pytest.mark.asyncio
    async def test_mark_as_read(self, labels_mixin):
        """Test marking message as read removes UNREAD label."""
        with patch.object(labels_mixin, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            result = await labels_mixin.mark_as_read("msg_123")

            mock_modify.assert_called_once_with("msg_123", remove_labels=["UNREAD"])
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_mark_as_unread(self, labels_mixin):
        """Test marking message as unread adds UNREAD label."""
        with patch.object(labels_mixin, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            result = await labels_mixin.mark_as_unread("msg_123")

            mock_modify.assert_called_once_with("msg_123", add_labels=["UNREAD"])
            assert result["success"] is True


# =============================================================================
# Star/Unstar Message Tests
# =============================================================================


class TestStarUnstar:
    """Tests for starring and unstarring messages."""

    @pytest.mark.asyncio
    async def test_star_message(self, labels_mixin):
        """Test starring a message adds STARRED label."""
        with patch.object(labels_mixin, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            result = await labels_mixin.star_message("msg_123")

            mock_modify.assert_called_once_with("msg_123", add_labels=["STARRED"])
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_unstar_message(self, labels_mixin):
        """Test unstarring a message removes STARRED label."""
        with patch.object(labels_mixin, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            result = await labels_mixin.unstar_message("msg_123")

            mock_modify.assert_called_once_with("msg_123", remove_labels=["STARRED"])
            assert result["success"] is True


# =============================================================================
# Mark Important Tests
# =============================================================================


class TestMarkImportant:
    """Tests for marking messages as important/not important."""

    @pytest.mark.asyncio
    async def test_mark_important(self, labels_mixin):
        """Test marking message as important."""
        with patch.object(labels_mixin, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            result = await labels_mixin.mark_important("msg_123")

            mock_modify.assert_called_once_with("msg_123", add_labels=["IMPORTANT"])
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_mark_not_important(self, labels_mixin):
        """Test marking message as not important."""
        with patch.object(labels_mixin, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            result = await labels_mixin.mark_not_important("msg_123")

            mock_modify.assert_called_once_with("msg_123", remove_labels=["IMPORTANT"])
            assert result["success"] is True


# =============================================================================
# Move to Folder Tests
# =============================================================================


class TestMoveToFolder:
    """Tests for moving messages to folders."""

    @pytest.mark.asyncio
    async def test_move_to_folder_removes_inbox(self, labels_mixin):
        """Test moving to folder removes from inbox by default."""
        with patch.object(labels_mixin, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            result = await labels_mixin.move_to_folder("msg_123", "Label_Work")

            mock_modify.assert_called_once_with(
                "msg_123",
                add_labels=["Label_Work"],
                remove_labels=["INBOX"],
            )
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_move_to_folder_keep_in_inbox(self, labels_mixin):
        """Test moving to folder without removing from inbox."""
        with patch.object(labels_mixin, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            result = await labels_mixin.move_to_folder(
                "msg_123", "Label_Work", remove_from_inbox=False
            )

            mock_modify.assert_called_once_with(
                "msg_123",
                add_labels=["Label_Work"],
                remove_labels=[],
            )
            assert result["success"] is True


# =============================================================================
# Snooze Message Tests
# =============================================================================


class TestSnoozeMessage:
    """Tests for snoozing messages."""

    @pytest.mark.asyncio
    async def test_snooze_message_archives_first(self, labels_mixin):
        """Test snooze archives the message first."""
        snooze_until = datetime.now(timezone.utc) + timedelta(hours=2)

        with patch.object(labels_mixin, "archive_message") as mock_archive:
            with patch.object(labels_mixin, "modify_message") as mock_modify:
                mock_archive.return_value = {"success": True}
                mock_modify.return_value = {"success": True}

                result = await labels_mixin.snooze_message("msg_123", snooze_until)

                mock_archive.assert_called_once_with("msg_123")
                assert result["success"] is True
                assert "snoozed_until" in result

    @pytest.mark.asyncio
    async def test_snooze_message_adds_snoozed_label(self, labels_mixin):
        """Test snooze tries to add SNOOZED label."""
        snooze_until = datetime.now(timezone.utc) + timedelta(hours=2)

        with patch.object(labels_mixin, "archive_message") as mock_archive:
            with patch.object(labels_mixin, "modify_message") as mock_modify:
                mock_archive.return_value = {"success": True}
                mock_modify.return_value = {"success": True}

                await labels_mixin.snooze_message("msg_123", snooze_until)

                # Verify modify_message was called to add SNOOZED label
                mock_modify.assert_called_once_with("msg_123", add_labels=["SNOOZED"])

    @pytest.mark.asyncio
    async def test_snooze_message_handles_missing_snoozed_label(self, labels_mixin):
        """Test snooze handles case when SNOOZED label doesn't exist."""
        snooze_until = datetime.now(timezone.utc) + timedelta(hours=2)

        with patch.object(labels_mixin, "archive_message") as mock_archive:
            with patch.object(labels_mixin, "modify_message") as mock_modify:
                mock_archive.return_value = {"success": True}
                mock_modify.side_effect = RuntimeError("Label not found")

                # Should not raise, just log
                result = await labels_mixin.snooze_message("msg_123", snooze_until)

                assert result["success"] is True


# =============================================================================
# Batch Modify Tests
# =============================================================================


class TestBatchModify:
    """Tests for batch modifying messages."""

    @pytest.mark.asyncio
    async def test_batch_modify_success(self, labels_mixin):
        """Test batch modifying multiple messages."""
        mock_response = Mock()
        mock_response.status_code = 204

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            result = await labels_mixin.batch_modify(
                ["msg_1", "msg_2", "msg_3"],
                add_labels=["STARRED"],
                remove_labels=["UNREAD"],
            )

            assert result["success"] is True
            assert result["modified_count"] == 3

    @pytest.mark.asyncio
    async def test_batch_modify_sends_correct_payload(self, labels_mixin):
        """Test batch modify sends correct API payload."""
        mock_response = Mock()
        mock_response.status_code = 204

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            await labels_mixin.batch_modify(
                ["msg_1", "msg_2"],
                add_labels=["STARRED"],
                remove_labels=["UNREAD"],
            )

            call_args = mock_client.post.call_args
            assert "batchModify" in call_args[0][0]
            assert call_args.kwargs["json"]["ids"] == ["msg_1", "msg_2"]
            assert call_args.kwargs["json"]["addLabelIds"] == ["STARRED"]
            assert call_args.kwargs["json"]["removeLabelIds"] == ["UNREAD"]

    @pytest.mark.asyncio
    async def test_batch_modify_circuit_breaker_open(self, labels_mixin):
        """Test batch modify fails when circuit breaker is open."""
        labels_mixin._circuit_open = True

        with pytest.raises(ConnectionError, match="Circuit breaker open"):
            await labels_mixin.batch_modify(["msg_1"], add_labels=["STARRED"])

    @pytest.mark.asyncio
    async def test_batch_modify_records_failure_on_error(self, labels_mixin, mock_httpx_response):
        """Test batch modify records failure on server error."""
        error_response = mock_httpx_response(500, {"error": {"message": "Error"}})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=error_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            with pytest.raises(RuntimeError):
                await labels_mixin.batch_modify(["msg_1"], add_labels=["STARRED"])

            assert labels_mixin._failure_count == 1


# =============================================================================
# Batch Archive Tests
# =============================================================================


class TestBatchArchive:
    """Tests for batch archiving messages."""

    @pytest.mark.asyncio
    async def test_batch_archive_delegates_to_batch_modify(self, labels_mixin):
        """Test batch archive calls batch_modify correctly."""
        with patch.object(labels_mixin, "batch_modify") as mock_batch:
            mock_batch.return_value = {"success": True, "modified_count": 3}

            result = await labels_mixin.batch_archive(["msg_1", "msg_2", "msg_3"])

            mock_batch.assert_called_once_with(
                ["msg_1", "msg_2", "msg_3"],
                remove_labels=["INBOX"],
            )
            assert result["success"] is True
            assert result["modified_count"] == 3


# =============================================================================
# Batch Trash Tests
# =============================================================================


class TestBatchTrash:
    """Tests for batch trashing (deleting) messages."""

    @pytest.mark.asyncio
    async def test_batch_trash_success(self, labels_mixin):
        """Test batch trashing multiple messages."""
        mock_response = Mock()
        mock_response.status_code = 204

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            result = await labels_mixin.batch_trash(["msg_1", "msg_2"])

            assert result["success"] is True
            assert result["deleted_count"] == 2

    @pytest.mark.asyncio
    async def test_batch_trash_sends_correct_payload(self, labels_mixin):
        """Test batch trash sends correct API payload."""
        mock_response = Mock()
        mock_response.status_code = 204

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            await labels_mixin.batch_trash(["msg_1", "msg_2"])

            call_args = mock_client.post.call_args
            assert "batchDelete" in call_args[0][0]
            assert call_args.kwargs["json"]["ids"] == ["msg_1", "msg_2"]

    @pytest.mark.asyncio
    async def test_batch_trash_circuit_breaker_open(self, labels_mixin):
        """Test batch trash fails when circuit breaker is open."""
        labels_mixin._circuit_open = True

        with pytest.raises(ConnectionError, match="Circuit breaker open"):
            await labels_mixin.batch_trash(["msg_1", "msg_2"])

    @pytest.mark.asyncio
    async def test_batch_trash_records_success(self, labels_mixin):
        """Test batch trash records success."""
        mock_response = Mock()
        mock_response.status_code = 204

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            await labels_mixin.batch_trash(["msg_1"])

            assert labels_mixin._success_count == 1


# =============================================================================
# Connection Error Handling Tests
# =============================================================================


class TestConnectionErrorHandling:
    """Tests for handling connection errors."""

    @pytest.mark.asyncio
    async def test_modify_message_records_failure_on_connection_error(self, labels_mixin):
        """Test connection errors are recorded as failures."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectionError("Network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            with pytest.raises(ConnectionError):
                await labels_mixin.modify_message("msg_123", add_labels=["STARRED"])

            assert labels_mixin._failure_count == 1

    @pytest.mark.asyncio
    async def test_trash_message_records_failure_on_os_error(self, labels_mixin):
        """Test OS errors are recorded as failures."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=OSError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            with pytest.raises(OSError):
                await labels_mixin.trash_message("msg_123")

            assert labels_mixin._failure_count == 1

    @pytest.mark.asyncio
    async def test_batch_modify_records_failure_on_connection_error(self, labels_mixin):
        """Test batch modify records failure on connection error."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectionError("Network error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(labels_mixin, "_get_client", return_value=mock_client):
            with pytest.raises(ConnectionError):
                await labels_mixin.batch_modify(["msg_1"], add_labels=["STARRED"])

            assert labels_mixin._failure_count == 1
