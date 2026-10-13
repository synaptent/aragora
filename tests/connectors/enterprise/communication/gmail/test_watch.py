"""
Tests for Gmail Watch Mixin.

Comprehensive tests for GmailWatchMixin covering:
- Setting up Gmail Pub/Sub watch
- Stopping watch subscriptions
- Handling Pub/Sub webhook notifications
- Watch renewal background task
- History API integration
- Circuit breaker integration
- Error handling
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from aragora.connectors.enterprise.communication.models import (
    EmailMessage,
    GmailSyncState,
    GmailWebhookPayload,
)


# =============================================================================
# Test Fixtures
# =============================================================================


class MockGmailBase:
    """Mock base class that implements GmailBaseMethods protocol for watch mixin."""

    def __init__(self):
        self.user_id = "me"
        self.exclude_labels: set[str] = set()
        self._gmail_state: GmailSyncState | None = None
        self._watch_task: asyncio.Task | None = None
        self._watch_running: bool = False
        self._access_token = "test_token"
        self._circuit_open = False
        self._failure_count = 0
        self._success_count = 0

    async def _get_access_token(self) -> str:
        return self._access_token

    async def _api_request(self, endpoint: str, method: str = "GET", **kwargs):
        return {}

    def _get_client(self):
        """Return context manager for HTTP client."""
        return AsyncMock()

    def check_circuit_breaker(self) -> bool:
        return not self._circuit_open

    def get_circuit_breaker_status(self) -> dict:
        return {"cooldown_seconds": 60, "failure_count": self._failure_count}

    def record_success(self) -> None:
        self._success_count += 1

    def record_failure(self) -> None:
        self._failure_count += 1

    async def get_history(
        self, start_history_id: str, page_token: str | None = None
    ) -> tuple[list[dict], str | None, str | None]:
        return [], None, None

    async def get_message(self, message_id: str) -> EmailMessage:
        return EmailMessage(
            id=message_id,
            thread_id="thread_1",
            subject="Test",
            from_address="test@example.com",
            to_addresses=["recipient@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Test body",
        )


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
def watch_mixin():
    """Create a watch mixin instance with mock base."""
    from aragora.connectors.enterprise.communication.gmail.watch import GmailWatchMixin

    class TestMixin(GmailWatchMixin, MockGmailBase):
        pass

    return TestMixin()


@pytest.fixture
def sample_pubsub_payload():
    """Create a sample Pub/Sub webhook payload."""
    data = {
        "emailAddress": "test@example.com",
        "historyId": "12346",
    }
    data_b64 = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()

    return {
        "message": {
            "data": data_b64,
            "messageId": "webhook_123",
        },
        "subscription": "projects/test-project/subscriptions/gmail-sub",
    }


# =============================================================================
# Setup Watch Tests
# =============================================================================


class TestSetupWatch:
    """Tests for setting up Gmail Pub/Sub watch."""

    @pytest.mark.asyncio
    async def test_setup_watch_success(self, watch_mixin, mock_httpx_response):
        """Test successfully setting up watch."""
        expiration_ms = int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp() * 1000)
        watch_response = {
            "historyId": "12345",
            "expiration": str(expiration_ms),
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, watch_response))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "my-project"}):
            with patch.object(watch_mixin, "_get_client", return_value=mock_client):
                result = await watch_mixin.setup_watch(
                    topic_name="gmail-notifications",
                    label_ids=["INBOX"],
                )

                assert result["success"] is True
                assert result["history_id"] == "12345"
                assert result["topic"] == "projects/my-project/topics/gmail-notifications"
                assert result["labels"] == ["INBOX"]
                assert result["expiration"] is not None

    @pytest.mark.asyncio
    async def test_setup_watch_creates_gmail_state(self, watch_mixin, mock_httpx_response):
        """Test setup_watch creates GmailSyncState if not exists."""
        watch_response = {
            "historyId": "12345",
            "expiration": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, watch_response))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        assert watch_mixin._gmail_state is None

        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "my-project"}):
            with patch.object(watch_mixin, "_get_client", return_value=mock_client):
                await watch_mixin.setup_watch(topic_name="test-topic")

                assert watch_mixin._gmail_state is not None
                assert watch_mixin._gmail_state.history_id == "12345"
                assert watch_mixin._gmail_state.watch_resource_id == "active"

    @pytest.mark.asyncio
    async def test_setup_watch_updates_existing_state(self, watch_mixin, mock_httpx_response):
        """Test setup_watch updates existing GmailSyncState."""
        watch_mixin._gmail_state = GmailSyncState(
            user_id="me",
            history_id="old_id",
            email_address="test@example.com",
        )

        watch_response = {
            "historyId": "new_id",
            "expiration": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, watch_response))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "my-project"}):
            with patch.object(watch_mixin, "_get_client", return_value=mock_client):
                await watch_mixin.setup_watch(topic_name="test-topic")

                assert watch_mixin._gmail_state.history_id == "new_id"

    @pytest.mark.asyncio
    async def test_setup_watch_no_project_id(self, watch_mixin):
        """Test setup_watch fails without project ID."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="project_id required"):
                await watch_mixin.setup_watch(topic_name="test-topic")

    @pytest.mark.asyncio
    async def test_setup_watch_with_explicit_project_id(self, watch_mixin, mock_httpx_response):
        """Test setup_watch with explicit project ID parameter."""
        watch_response = {
            "historyId": "12345",
            "expiration": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, watch_response))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {}, clear=True):
            with patch.object(watch_mixin, "_get_client", return_value=mock_client):
                result = await watch_mixin.setup_watch(
                    topic_name="test-topic",
                    project_id="explicit-project",
                )

                assert result["topic"] == "projects/explicit-project/topics/test-topic"

    @pytest.mark.asyncio
    async def test_setup_watch_default_labels(self, watch_mixin, mock_httpx_response):
        """Test setup_watch defaults to INBOX label."""
        watch_response = {"historyId": "12345"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, watch_response))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "my-project"}):
            with patch.object(watch_mixin, "_get_client", return_value=mock_client):
                result = await watch_mixin.setup_watch(topic_name="test-topic")

                assert result["labels"] == ["INBOX"]

    @pytest.mark.asyncio
    async def test_setup_watch_circuit_breaker_open(self, watch_mixin):
        """Test setup_watch fails when circuit breaker is open."""
        watch_mixin._circuit_open = True

        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "my-project"}):
            with pytest.raises(ConnectionError, match="Circuit breaker open"):
                await watch_mixin.setup_watch(topic_name="test-topic")

    @pytest.mark.asyncio
    async def test_setup_watch_records_failure_on_error(self, watch_mixin, mock_httpx_response):
        """Test setup_watch records failure on server error."""
        error_response = mock_httpx_response(500, {"error": {"message": "Server error"}})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=error_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "my-project"}):
            with patch.object(watch_mixin, "_get_client", return_value=mock_client):
                with pytest.raises(RuntimeError):
                    await watch_mixin.setup_watch(topic_name="test-topic")

                assert watch_mixin._failure_count == 1

    @pytest.mark.asyncio
    async def test_setup_watch_records_success(self, watch_mixin, mock_httpx_response):
        """Test setup_watch records success."""
        watch_response = {"historyId": "12345"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, watch_response))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "my-project"}):
            with patch.object(watch_mixin, "_get_client", return_value=mock_client):
                await watch_mixin.setup_watch(topic_name="test-topic")

                assert watch_mixin._success_count == 1


# =============================================================================
# Stop Watch Tests
# =============================================================================


class TestStopWatch:
    """Tests for stopping Gmail Pub/Sub watch."""

    @pytest.mark.asyncio
    async def test_stop_watch_success(self, watch_mixin):
        """Test successfully stopping watch."""
        mock_response = Mock()
        mock_response.status_code = 204

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(watch_mixin, "_get_client", return_value=mock_client):
            result = await watch_mixin.stop_watch()

            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_stop_watch_clears_state(self, watch_mixin):
        """Test stop_watch clears watch state."""
        watch_mixin._gmail_state = GmailSyncState(
            user_id="me",
            history_id="12345",
            watch_resource_id="active",
            watch_expiration=datetime.now(timezone.utc),
        )

        mock_response = Mock()
        mock_response.status_code = 204

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(watch_mixin, "_get_client", return_value=mock_client):
            await watch_mixin.stop_watch()

            assert watch_mixin._gmail_state.watch_resource_id is None
            assert watch_mixin._gmail_state.watch_expiration is None

    @pytest.mark.asyncio
    async def test_stop_watch_cancels_renewal_task(self, watch_mixin):
        """Test stop_watch cancels running renewal task."""
        # Create a mock running task
        mock_task = AsyncMock()
        mock_task.done.return_value = False
        mock_task.cancel = Mock()

        watch_mixin._watch_task = mock_task
        watch_mixin._watch_running = True

        mock_response = Mock()
        mock_response.status_code = 204

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(watch_mixin, "_get_client", return_value=mock_client):
            await watch_mixin.stop_watch()

            mock_task.cancel.assert_called_once()
            assert watch_mixin._watch_running is False
            assert watch_mixin._watch_task is None

    @pytest.mark.asyncio
    async def test_stop_watch_circuit_breaker_open(self, watch_mixin):
        """Test stop_watch fails when circuit breaker is open."""
        watch_mixin._circuit_open = True

        with pytest.raises(ConnectionError, match="Circuit breaker open"):
            await watch_mixin.stop_watch()

    @pytest.mark.asyncio
    async def test_stop_watch_handles_error_response(self, watch_mixin, mock_httpx_response):
        """Test stop_watch handles non-204 response."""
        error_response = mock_httpx_response(400, {"error": {"message": "Bad request"}})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=error_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(watch_mixin, "_get_client", return_value=mock_client):
            result = await watch_mixin.stop_watch()

            assert result["success"] is False
            assert "error" in result

    @pytest.mark.asyncio
    async def test_stop_watch_records_success(self, watch_mixin):
        """Test stop_watch records success."""
        mock_response = Mock()
        mock_response.status_code = 204

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch.object(watch_mixin, "_get_client", return_value=mock_client):
            await watch_mixin.stop_watch()

            assert watch_mixin._success_count == 1


# =============================================================================
# Handle Pub/Sub Notification Tests
# =============================================================================


class TestHandlePubSubNotification:
    """Tests for handling Pub/Sub webhook notifications."""

    @pytest.mark.asyncio
    async def test_handle_notification_success(self, watch_mixin, sample_pubsub_payload):
        """Test successfully handling a Pub/Sub notification."""
        watch_mixin._gmail_state = GmailSyncState(
            user_id="me",
            email_address="test@example.com",
            history_id="12345",
        )

        mock_msg = EmailMessage(
            id="new_msg",
            thread_id="thread_1",
            subject="New Message",
            from_address="sender@example.com",
            to_addresses=["test@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Message body",
        )

        with patch.object(watch_mixin, "get_history") as mock_history:
            mock_history.return_value = (
                [{"messagesAdded": [{"message": {"id": "new_msg", "labelIds": ["INBOX"]}}]}],
                None,
                "12346",
            )
            with patch.object(watch_mixin, "get_message", return_value=mock_msg):
                messages = await watch_mixin.handle_pubsub_notification(sample_pubsub_payload)

                assert len(messages) == 1
                assert messages[0].id == "new_msg"

    @pytest.mark.asyncio
    async def test_handle_notification_updates_history_id(self, watch_mixin, sample_pubsub_payload):
        """Test notification handling updates history ID."""
        watch_mixin._gmail_state = GmailSyncState(
            user_id="me",
            email_address="test@example.com",
            history_id="12345",
        )

        with patch.object(watch_mixin, "get_history") as mock_history:
            mock_history.return_value = ([], None, "12346")

            await watch_mixin.handle_pubsub_notification(sample_pubsub_payload)

            assert watch_mixin._gmail_state.history_id == "12346"

    @pytest.mark.asyncio
    async def test_handle_notification_wrong_email_ignored(self, watch_mixin):
        """Test notification for different email is ignored."""
        watch_mixin._gmail_state = GmailSyncState(
            user_id="me",
            email_address="correct@example.com",
            history_id="12345",
        )

        data = {"emailAddress": "wrong@example.com", "historyId": "12346"}
        data_b64 = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()

        payload = {
            "message": {"data": data_b64, "messageId": "msg"},
            "subscription": "test",
        }

        messages = await watch_mixin.handle_pubsub_notification(payload)

        assert messages == []

    @pytest.mark.asyncio
    async def test_handle_notification_no_state_returns_empty(
        self, watch_mixin, sample_pubsub_payload
    ):
        """Test notification with no state returns empty list."""
        watch_mixin._gmail_state = None

        messages = await watch_mixin.handle_pubsub_notification(sample_pubsub_payload)

        assert messages == []

    @pytest.mark.asyncio
    async def test_handle_notification_no_history_id_returns_empty(
        self, watch_mixin, sample_pubsub_payload
    ):
        """Test notification with no history ID returns empty list."""
        watch_mixin._gmail_state = GmailSyncState(
            user_id="me",
            email_address="test@example.com",
            history_id="",  # Empty history ID
        )

        messages = await watch_mixin.handle_pubsub_notification(sample_pubsub_payload)

        assert messages == []

    @pytest.mark.asyncio
    async def test_handle_notification_excludes_labeled_messages(
        self, watch_mixin, sample_pubsub_payload
    ):
        """Test notification excludes messages with excluded labels."""
        watch_mixin._gmail_state = GmailSyncState(
            user_id="me",
            email_address="test@example.com",
            history_id="12345",
        )
        watch_mixin.exclude_labels = {"SPAM", "TRASH"}

        with patch.object(watch_mixin, "get_history") as mock_history:
            mock_history.return_value = (
                [
                    {
                        "messagesAdded": [
                            {"message": {"id": "spam_msg", "labelIds": ["SPAM"]}},
                            {"message": {"id": "good_msg", "labelIds": ["INBOX"]}},
                        ]
                    }
                ],
                None,
                "12346",
            )
            with patch.object(watch_mixin, "get_message") as mock_get:
                mock_get.return_value = EmailMessage(
                    id="good_msg",
                    thread_id="thread_1",
                    subject="Good",
                    from_address="test@example.com",
                    to_addresses=["test@example.com"],
                    date=datetime.now(timezone.utc),
                    body_text="Body",
                )

                messages = await watch_mixin.handle_pubsub_notification(sample_pubsub_payload)

                # Only good_msg should be returned, spam_msg excluded
                assert len(messages) == 1
                assert messages[0].id == "good_msg"

    @pytest.mark.asyncio
    async def test_handle_notification_raises_on_message_fetch_error(
        self, watch_mixin, sample_pubsub_payload
    ):
        """A failed per-message fetch fails the webhook closed: raise and record the error."""
        watch_mixin._gmail_state = GmailSyncState(
            user_id="me",
            email_address="test@example.com",
            history_id="12345",
        )

        with patch.object(watch_mixin, "get_history") as mock_history:
            mock_history.return_value = (
                [{"messagesAdded": [{"message": {"id": "msg_1"}}]}],
                None,
                "12346",
            )
            with patch.object(watch_mixin, "get_message") as mock_get:
                mock_get.side_effect = RuntimeError("Failed to fetch")

                with pytest.raises(RuntimeError, match="Failed to fetch message msg_1"):
                    await watch_mixin.handle_pubsub_notification(sample_pubsub_payload)

        assert watch_mixin._gmail_state.sync_errors == 1
        assert watch_mixin._gmail_state.last_error == "Webhook processing failed"

    @pytest.mark.asyncio
    async def test_handle_notification_with_pagination(self, watch_mixin, sample_pubsub_payload):
        """Test notification handles paginated history results."""
        watch_mixin._gmail_state = GmailSyncState(
            user_id="me",
            email_address="test@example.com",
            history_id="12345",
        )

        mock_msg = EmailMessage(
            id="msg_1",
            thread_id="thread_1",
            subject="Test",
            from_address="test@example.com",
            to_addresses=["test@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Body",
        )

        call_count = 0

        async def mock_get_history(start_id, page_token=None):
            nonlocal call_count
            call_count += 1
            if page_token is None:
                return (
                    [{"messagesAdded": [{"message": {"id": "msg_1"}}]}],
                    "page_2",
                    "12346",
                )
            else:
                return ([], None, "12347")

        with patch.object(watch_mixin, "get_history", side_effect=mock_get_history):
            with patch.object(watch_mixin, "get_message", return_value=mock_msg):
                messages = await watch_mixin.handle_pubsub_notification(sample_pubsub_payload)

                assert len(messages) == 1
                assert call_count == 2  # Two pages

    @pytest.mark.asyncio
    async def test_handle_notification_updates_stats(self, watch_mixin, sample_pubsub_payload):
        """Test notification handling updates state statistics."""
        watch_mixin._gmail_state = GmailSyncState(
            user_id="me",
            email_address="test@example.com",
            history_id="12345",
            indexed_messages=10,
        )

        mock_msg = EmailMessage(
            id="msg_1",
            thread_id="thread_1",
            subject="Test",
            from_address="test@example.com",
            to_addresses=["test@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Body",
        )

        with patch.object(watch_mixin, "get_history") as mock_history:
            mock_history.return_value = (
                [{"messagesAdded": [{"message": {"id": "msg_1"}}]}],
                None,
                "12346",
            )
            with patch.object(watch_mixin, "get_message", return_value=mock_msg):
                await watch_mixin.handle_pubsub_notification(sample_pubsub_payload)

                assert watch_mixin._gmail_state.indexed_messages == 11
                assert watch_mixin._gmail_state.last_sync is not None

    @pytest.mark.asyncio
    async def test_handle_notification_records_errors(self, watch_mixin, sample_pubsub_payload):
        """Test notification handling records errors in state."""
        watch_mixin._gmail_state = GmailSyncState(
            user_id="me",
            email_address="test@example.com",
            history_id="12345",
            sync_errors=0,
        )

        with patch.object(watch_mixin, "get_history") as mock_history:
            mock_history.side_effect = RuntimeError("History API error")

            with pytest.raises(RuntimeError):
                await watch_mixin.handle_pubsub_notification(sample_pubsub_payload)

            assert watch_mixin._gmail_state.sync_errors == 1
            assert watch_mixin._gmail_state.last_error is not None


# =============================================================================
# Watch Renewal Tests
# =============================================================================


class TestWatchRenewal:
    """Tests for watch renewal background task."""

    @pytest.mark.asyncio
    async def test_start_watch_renewal(self, watch_mixin):
        """Test starting watch renewal task."""
        with patch.object(watch_mixin, "_watch_renewal_loop", new_callable=AsyncMock) as mock_loop:
            await watch_mixin.start_watch_renewal(
                topic_name="test-topic",
                renewal_hours=144,
                project_id="test-project",
            )

            assert watch_mixin._watch_running is True
            assert watch_mixin._watch_task is not None

    @pytest.mark.asyncio
    async def test_start_watch_renewal_already_running(self, watch_mixin):
        """Test start_watch_renewal doesn't start duplicate tasks."""
        mock_task = MagicMock()
        mock_task.done.return_value = False
        watch_mixin._watch_task = mock_task

        with patch.object(watch_mixin, "_watch_renewal_loop", new_callable=AsyncMock):
            await watch_mixin.start_watch_renewal(topic_name="test-topic")

            # Should not create a new task
            assert watch_mixin._watch_task == mock_task

    @pytest.mark.asyncio
    async def test_watch_renewal_loop_calls_setup_watch(self, watch_mixin, mock_httpx_response):
        """Test renewal loop calls setup_watch periodically."""
        watch_response = {"historyId": "12345"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_httpx_response(200, watch_response))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        watch_mixin._watch_running = True

        async def stop_after_one():
            await asyncio.sleep(0.1)
            watch_mixin._watch_running = False

        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "my-project"}):
            with patch.object(watch_mixin, "_get_client", return_value=mock_client):
                with patch("asyncio.sleep") as mock_sleep:
                    mock_sleep.return_value = None

                    # Run loop briefly then stop
                    asyncio.create_task(stop_after_one())

                    await watch_mixin._watch_renewal_loop(
                        topic_name="test-topic",
                        renewal_hours=144,
                        project_id="my-project",
                    )

    @pytest.mark.asyncio
    async def test_watch_renewal_loop_handles_cancellation(self, watch_mixin):
        """Test renewal loop handles cancellation gracefully."""
        watch_mixin._watch_running = True

        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            # Should not raise
            await watch_mixin._watch_renewal_loop(
                topic_name="test-topic",
                renewal_hours=144,
                project_id="my-project",
            )

    @pytest.mark.asyncio
    async def test_watch_renewal_loop_stops_and_raises_on_failure(self, watch_mixin):
        """A failed renewal stops the loop and re-raises (fail closed, no silent retry)."""
        call_count = 0

        async def mock_setup_watch(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Setup failed")

        with patch.object(watch_mixin, "setup_watch", side_effect=mock_setup_watch):
            with patch("asyncio.sleep") as mock_sleep:
                mock_sleep.return_value = None

                watch_mixin._watch_running = True
                with pytest.raises(RuntimeError, match="Setup failed"):
                    await watch_mixin._watch_renewal_loop(
                        topic_name="test-topic",
                        renewal_hours=144,
                        project_id="my-project",
                    )

        assert call_count == 1
        assert watch_mixin._watch_running is False
        # The loop stops rather than scheduling a retry back-off.
        assert not any(call[0][0] == 60 for call in mock_sleep.call_args_list)


# =============================================================================
# Webhook Payload Parsing Tests
# =============================================================================


class TestWebhookPayloadParsing:
    """Tests for GmailWebhookPayload parsing."""

    def test_parse_valid_payload(self, sample_pubsub_payload):
        """Test parsing a valid Pub/Sub payload."""
        webhook = GmailWebhookPayload.from_pubsub(sample_pubsub_payload)

        assert webhook.message_id == "webhook_123"
        assert webhook.email_address == "test@example.com"
        assert webhook.history_id == "12346"
        assert webhook.subscription == "projects/test-project/subscriptions/gmail-sub"

    def test_parse_payload_with_message_id_field(self):
        """Test parsing payload with alternate message_id field."""
        data = {"emailAddress": "test@example.com", "historyId": "12345"}
        data_b64 = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()

        payload = {
            "message": {
                "data": data_b64,
                "message_id": "alt_msg_id",  # Alternate field
            },
            "subscription": "test",
        }

        webhook = GmailWebhookPayload.from_pubsub(payload)

        assert webhook.message_id == "alt_msg_id"

    def test_parse_payload_with_invalid_base64(self):
        """Test parsing payload with invalid base64 data."""
        payload = {
            "message": {
                "data": "invalid-base64!!!",
                "messageId": "msg_123",
            },
            "subscription": "test",
        }

        webhook = GmailWebhookPayload.from_pubsub(payload)

        # Should not raise, just return empty values
        assert webhook.email_address == ""
        assert webhook.history_id == ""

    def test_parse_payload_with_missing_data(self):
        """Test parsing payload with missing data field."""
        payload = {
            "message": {
                "messageId": "msg_123",
            },
            "subscription": "test",
        }

        webhook = GmailWebhookPayload.from_pubsub(payload)

        assert webhook.email_address == ""
        assert webhook.history_id == ""

    def test_parse_payload_stores_raw_data(self, sample_pubsub_payload):
        """Test webhook stores original raw payload."""
        webhook = GmailWebhookPayload.from_pubsub(sample_pubsub_payload)

        assert webhook.raw_data == sample_pubsub_payload
