"""
Tests for Gmail Enterprise Connector.

Comprehensive tests for GmailConnector covering:
- OAuth authentication flow
- Token management and refresh
- Message retrieval and parsing
- Label management
- Email actions (archive, trash, star, etc.)
- Batch operations
- Pub/Sub watch management
- Incremental sync via History API
- Circuit breaker integration
"""

from __future__ import annotations

import asyncio
import base64
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from aragora.connectors.enterprise.communication.gmail import (
    GmailConnector,
    GMAIL_SCOPES,
    GMAIL_SCOPES_READONLY,
    GMAIL_SCOPES_FULL,
)
from aragora.connectors.enterprise.communication.models import (
    EmailAttachment,
    EmailMessage,
    EmailThread,
    GmailLabel,
    GmailSyncState,
    GmailWebhookPayload,
)
from aragora.connectors.enterprise.base import SyncState


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def gmail_connector():
    """Create a Gmail connector for testing."""
    return GmailConnector(
        labels=["INBOX", "IMPORTANT"],
        exclude_labels=["SPAM", "TRASH"],
        max_results=50,
        include_spam_trash=False,
    )


@pytest.fixture(autouse=True)
def reset_refresh_token_fallback():
    """Prevent live saved Gmail tokens from leaking into connector tests."""
    with (
        patch(
            "aragora.connectors.enterprise.communication.gmail._load_refresh_token_fallback",
            return_value=None,
        ),
        patch(
            "aragora.connectors.enterprise.communication.gmail.client._load_refresh_token_fallback",
            return_value=None,
        ),
    ):
        yield


@pytest.fixture
def authenticated_connector():
    """Create an authenticated Gmail connector."""
    connector = GmailConnector()
    connector._access_token = "test_access_token"
    connector._refresh_token = "test_refresh_token"
    connector._token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    return connector


@pytest.fixture
def mock_httpx_response():
    """Factory for creating mock httpx responses."""

    def _create(status_code: int = 200, json_data: dict = None, content: bytes = b""):
        response = Mock()
        response.status_code = status_code
        response.json = Mock(return_value=json_data or {})
        response.content = content or json.dumps(json_data or {}).encode()
        response.text = content.decode() if content else json.dumps(json_data or {})
        response.raise_for_status = Mock()
        if status_code >= 400:
            from httpx import HTTPStatusError

            response.raise_for_status.side_effect = HTTPStatusError(
                "Error", request=Mock(), response=response
            )
        return response

    return _create


@pytest.fixture
def sample_gmail_message():
    """Sample Gmail API message response."""
    return {
        "id": "msg_123",
        "threadId": "thread_456",
        "labelIds": ["INBOX", "UNREAD", "IMPORTANT"],
        "snippet": "This is a test email...",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "recipient@example.com"},
                {"name": "Subject", "value": "Test Subject"},
                {"name": "Date", "value": "Mon, 15 Jan 2024 10:30:00 +0000"},
                {"name": "CC", "value": "cc@example.com"},
            ],
            "body": {"data": base64.urlsafe_b64encode(b"Hello, this is the email body.").decode()},
        },
    }


@pytest.fixture
def sample_multipart_message():
    """Sample multipart Gmail API message response."""
    return {
        "id": "msg_multipart",
        "threadId": "thread_multipart",
        "labelIds": ["INBOX", "STARRED"],
        "snippet": "Multipart email...",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "recipient@example.com"},
                {"name": "Subject", "value": "Multipart Test"},
                {"name": "Date", "value": "Tue, 16 Jan 2024 14:00:00 +0000"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": base64.urlsafe_b64encode(b"Plain text body").decode()},
                },
                {
                    "mimeType": "text/html",
                    "body": {
                        "data": base64.urlsafe_b64encode(
                            b"<html><body>HTML body</body></html>"
                        ).decode()
                    },
                },
            ],
        },
    }


# =============================================================================
# Initialization Tests
# =============================================================================


class TestGmailConnectorInitialization:
    """Tests for GmailConnector initialization."""

    def test_default_initialization(self):
        """Test default connector initialization."""
        with patch(
            "aragora.connectors.enterprise.communication.gmail._load_refresh_token_fallback",
            return_value=None,
        ):
            connector = GmailConnector()

        assert connector.connector_id == "gmail"
        assert connector.labels is None
        assert connector.exclude_labels == set()
        assert connector.max_results == 100
        assert connector.include_spam_trash is False
        assert connector.user_id == "me"
        assert connector._access_token is None
        assert connector._refresh_token is None

    def test_initialization_loads_saved_refresh_token(self):
        """Test connector initialization loads the saved refresh token fallback."""
        with patch(
            "aragora.connectors.enterprise.communication.gmail._load_refresh_token_fallback",
            return_value="saved-refresh-token",
        ):
            connector = GmailConnector()

        assert connector._refresh_token == "saved-refresh-token"

    def test_custom_initialization(self, gmail_connector):
        """Test connector with custom parameters."""
        assert gmail_connector.labels == ["INBOX", "IMPORTANT"]
        assert gmail_connector.exclude_labels == {"SPAM", "TRASH"}
        assert gmail_connector.max_results == 50
        assert gmail_connector.include_spam_trash is False

    def test_source_type(self, gmail_connector):
        """Test source type property."""
        from aragora.reasoning.provenance import SourceType

        assert gmail_connector.source_type == SourceType.DOCUMENT

    def test_name_property(self, gmail_connector):
        """Test name property."""
        assert gmail_connector.name == "Gmail"

    def test_is_configured_without_env(self, gmail_connector):
        """Test is_configured returns False without credentials."""
        with patch.dict("os.environ", {}, clear=True):
            assert gmail_connector.is_configured is False

    def test_is_configured_with_env(self, gmail_connector):
        """Test is_configured returns True with credentials."""
        with patch.dict("os.environ", {"GMAIL_CLIENT_ID": "test_client_id"}):
            assert gmail_connector.is_configured is True

    def test_is_configured_with_google_prefix(self, gmail_connector):
        """Test is_configured with GOOGLE_ prefix."""
        with patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "test_client_id"}):
            assert gmail_connector.is_configured is True


# =============================================================================
# OAuth Flow Tests
# =============================================================================


class TestOAuthFlow:
    """Tests for OAuth authentication flow."""

    def test_get_oauth_url_basic(self, gmail_connector):
        """Test OAuth URL generation."""
        with patch.dict("os.environ", {"GMAIL_CLIENT_ID": "test_client_id"}):
            url = gmail_connector.get_oauth_url(
                redirect_uri="https://example.com/callback",
                state="test_state",
            )

            assert "accounts.google.com" in url
            assert "client_id=test_client_id" in url
            assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in url
            assert "response_type=code" in url
            assert "access_type=offline" in url
            assert "state=test_state" in url

    def test_get_oauth_url_without_state(self, gmail_connector):
        """Test OAuth URL without state parameter."""
        with patch.dict("os.environ", {"GMAIL_CLIENT_ID": "test_client_id"}):
            url = gmail_connector.get_oauth_url(
                redirect_uri="https://example.com/callback",
            )

            assert "state=" not in url

    def test_get_oauth_url_includes_scopes(self, gmail_connector):
        """Test OAuth URL includes correct scopes."""
        with patch.dict("os.environ", {"GMAIL_CLIENT_ID": "test_client_id"}):
            url = gmail_connector.get_oauth_url(
                redirect_uri="https://example.com/callback",
            )

            # Check for readonly scope
            assert "gmail.readonly" in url


# =============================================================================
# Authentication Tests
# =============================================================================


class TestAuthentication:
    """Tests for authentication methods."""

    @pytest.mark.asyncio
    async def test_authenticate_with_code(self, gmail_connector, mock_httpx_response):
        """Test authentication with authorization code."""
        token_response = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
        }

        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "test_client_id",
                "GMAIL_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post = AsyncMock(
                    return_value=mock_httpx_response(200, token_response)
                )
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock()
                mock_client.return_value = mock_instance

                result = await gmail_connector.authenticate(
                    code="auth_code",
                    redirect_uri="https://example.com/callback",
                )

                assert result is True
                assert gmail_connector._access_token == "new_access_token"
                assert gmail_connector._refresh_token == "new_refresh_token"
                assert gmail_connector._token_expiry is not None

    @pytest.mark.asyncio
    async def test_authenticate_with_refresh_token(self, gmail_connector, mock_httpx_response):
        """Test authentication with refresh token."""
        token_response = {
            "access_token": "refreshed_access_token",
            "expires_in": 3600,
        }

        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "test_client_id",
                "GMAIL_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post = AsyncMock(
                    return_value=mock_httpx_response(200, token_response)
                )
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock()
                mock_client.return_value = mock_instance

                result = await gmail_connector.authenticate(
                    refresh_token="existing_refresh_token",
                )

                assert result is True
                assert gmail_connector._access_token == "refreshed_access_token"
                assert gmail_connector._refresh_token == "existing_refresh_token"

    @pytest.mark.asyncio
    async def test_authenticate_missing_credentials(self, gmail_connector):
        """Test authentication fails without credentials."""
        with patch.dict("os.environ", {}, clear=True):
            result = await gmail_connector.authenticate(
                code="auth_code",
                redirect_uri="https://example.com/callback",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_no_code_or_token(self, gmail_connector):
        """Test authentication fails without code or refresh token."""
        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "test_client_id",
                "GMAIL_CLIENT_SECRET": "test_secret",
            },
        ):
            result = await gmail_connector.authenticate()
            assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_api_error(self, gmail_connector, mock_httpx_response):
        """Test authentication handles API errors."""
        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "test_client_id",
                "GMAIL_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post = AsyncMock(
                    return_value=mock_httpx_response(401, {"error": "invalid_grant"})
                )
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock()
                mock_client.return_value = mock_instance

                result = await gmail_connector.authenticate(
                    code="invalid_code",
                    redirect_uri="https://example.com/callback",
                )

                assert result is False


# =============================================================================
# Token Management Tests
# =============================================================================


class TestTokenManagement:
    """Tests for token management."""

    def test_token_properties(self, authenticated_connector):
        """Test token property accessors."""
        assert authenticated_connector.access_token == "test_access_token"
        assert authenticated_connector.refresh_token == "test_refresh_token"
        assert authenticated_connector.token_expiry is not None

    @pytest.mark.asyncio
    async def test_get_access_token_valid(self, authenticated_connector):
        """Test getting valid access token."""
        token = await authenticated_connector._get_access_token()
        assert token == "test_access_token"

    @pytest.mark.asyncio
    async def test_get_access_token_expired_refreshes(
        self, authenticated_connector, mock_httpx_response
    ):
        """Test that expired token triggers refresh."""
        # Set token to expired
        authenticated_connector._token_expiry = datetime.now(timezone.utc) - timedelta(hours=1)

        token_response = {
            "access_token": "new_access_token",
            "expires_in": 3600,
        }

        with patch.dict(
            "os.environ",
            {
                "GMAIL_CLIENT_ID": "test_client_id",
                "GMAIL_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post = AsyncMock(
                    return_value=mock_httpx_response(200, token_response)
                )
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock()
                mock_client.return_value = mock_instance

                token = await authenticated_connector._get_access_token()

                assert token == "new_access_token"

    @pytest.mark.asyncio
    async def test_get_access_token_no_refresh_token(self, gmail_connector):
        """Test error when no refresh token available."""
        gmail_connector._access_token = None
        gmail_connector._refresh_token = None

        with pytest.raises(ValueError, match="No valid access token"):
            await gmail_connector._get_access_token()


# =============================================================================
# API Request Tests
# =============================================================================


class TestApiRequests:
    """Tests for API request handling."""

    @pytest.mark.asyncio
    async def test_api_request_success(self, authenticated_connector, mock_httpx_response):
        """Test successful API request."""
        response_data = {"messages": [{"id": "msg_1"}]}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.request = AsyncMock(return_value=mock_httpx_response(200, response_data))
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock()
            mock_client.return_value = mock_instance

            result = await authenticated_connector._api_request("/messages")

            assert result == response_data

    @pytest.mark.asyncio
    async def test_api_request_circuit_breaker_open(self, authenticated_connector):
        """Test API request fails when circuit breaker is open."""
        authenticated_connector._failure_count = 100
        authenticated_connector._circuit_open = True
        authenticated_connector._circuit_opened_at = datetime.now(timezone.utc)

        with patch.object(authenticated_connector, "check_circuit_breaker", return_value=False):
            with patch.object(
                authenticated_connector,
                "get_circuit_breaker_status",
                return_value={"cooldown_seconds": 60},
            ):
                with pytest.raises(ConnectionError, match="Circuit breaker open"):
                    await authenticated_connector._api_request("/messages")

    @pytest.mark.asyncio
    async def test_api_request_records_failure_on_5xx(self, authenticated_connector):
        """Test that 5xx errors record failures."""
        import httpx

        # Create mock response for 500 error
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = '{"error": "Server error"}'
        mock_response.content = b'{"error": "Server error"}'
        mock_response.json = Mock(return_value={"error": "Server error"})

        # Create a proper side_effect for raise_for_status
        request = httpx.Request("GET", "https://gmail.googleapis.com/test")
        error = httpx.HTTPStatusError("Server Error", request=request, response=mock_response)
        mock_response.raise_for_status = Mock(side_effect=error)

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.request = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock()
            mock_client.return_value = mock_instance

            with patch.object(authenticated_connector, "record_failure") as mock_failure:
                try:
                    await authenticated_connector._api_request("/messages")
                except httpx.HTTPStatusError:
                    pass  # Expected

                # Verify record_failure was called for 5xx error
                mock_failure.assert_called_once()


# =============================================================================
# User Info and Labels Tests
# =============================================================================


class TestUserInfoAndLabels:
    """Tests for user info and label operations."""

    @pytest.mark.asyncio
    async def test_get_user_info(self, authenticated_connector):
        """Test getting user profile."""
        profile_data = {
            "emailAddress": "user@example.com",
            "messagesTotal": 1000,
            "historyId": "12345",
        }

        with patch.object(authenticated_connector, "_api_request", return_value=profile_data):
            result = await authenticated_connector.get_user_info()

            assert result["emailAddress"] == "user@example.com"
            assert result["historyId"] == "12345"

    @pytest.mark.asyncio
    async def test_list_labels(self, authenticated_connector):
        """Test listing Gmail labels."""
        labels_data = {
            "labels": [
                {"id": "INBOX", "name": "INBOX", "type": "system"},
                {"id": "Label_1", "name": "Work", "type": "user"},
            ]
        }

        with patch.object(authenticated_connector, "_api_request", return_value=labels_data):
            labels = await authenticated_connector.list_labels()

            assert len(labels) == 2
            assert isinstance(labels[0], GmailLabel)
            assert labels[0].id == "INBOX"
            assert labels[1].name == "Work"

    @pytest.mark.asyncio
    async def test_create_label(self, authenticated_connector, mock_httpx_response):
        """Test creating a new label."""
        label_data = {
            "id": "Label_new",
            "name": "New Label",
            "type": "user",
        }

        with patch.object(authenticated_connector, "_get_access_token", return_value="token"):
            with patch.object(authenticated_connector, "_get_client") as mock_get_client:
                mock_client = AsyncMock()
                mock_client.post = AsyncMock(return_value=mock_httpx_response(200, label_data))
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock()
                mock_get_client.return_value = mock_client

                label = await authenticated_connector.create_label("New Label")

                assert isinstance(label, GmailLabel)
                assert label.id == "Label_new"
                assert label.name == "New Label"


# =============================================================================
# Message Operations Tests
# =============================================================================


class TestMessageOperations:
    """Tests for message operations."""

    @pytest.mark.asyncio
    async def test_list_messages(self, authenticated_connector):
        """Test listing message IDs."""
        response = {
            "messages": [
                {"id": "msg_1"},
                {"id": "msg_2"},
                {"id": "msg_3"},
            ],
            "nextPageToken": "next_token",
        }

        with patch.object(authenticated_connector, "_api_request", return_value=response):
            message_ids, next_token = await authenticated_connector.list_messages(
                query="from:test@example.com",
                max_results=10,
            )

            assert len(message_ids) == 3
            assert "msg_1" in message_ids
            assert next_token == "next_token"

    @pytest.mark.asyncio
    async def test_list_messages_with_labels(self, authenticated_connector):
        """Test listing messages with label filter."""
        response = {"messages": [{"id": "msg_1"}]}

        with patch.object(
            authenticated_connector, "_api_request", return_value=response
        ) as mock_request:
            await authenticated_connector.list_messages(
                label_ids=["INBOX", "IMPORTANT"],
            )

            call_args = mock_request.call_args
            assert "labelIds" in call_args.kwargs.get("params", {})

    @pytest.mark.asyncio
    async def test_get_message(self, authenticated_connector, sample_gmail_message):
        """Test getting a single message."""
        with patch.object(
            authenticated_connector, "_api_request", return_value=sample_gmail_message
        ):
            message = await authenticated_connector.get_message("msg_123")

            assert isinstance(message, EmailMessage)
            assert message.id == "msg_123"
            assert message.thread_id == "thread_456"
            assert message.subject == "Test Subject"
            assert message.from_address == "sender@example.com"
            assert "recipient@example.com" in message.to_addresses
            assert message.is_read is False  # Has UNREAD label
            assert message.is_important is True  # Has IMPORTANT label

    @pytest.mark.asyncio
    async def test_get_message_multipart(self, authenticated_connector, sample_multipart_message):
        """Test getting a multipart message."""
        with patch.object(
            authenticated_connector, "_api_request", return_value=sample_multipart_message
        ):
            message = await authenticated_connector.get_message("msg_multipart")

            assert message.body_text == "Plain text body"
            assert "HTML body" in message.body_html
            assert message.is_starred is True  # Has STARRED label


class TestBatchMessageFetching:
    """Tests for batch message fetching (get_messages)."""

    @pytest.mark.asyncio
    async def test_get_messages_empty_list(self, authenticated_connector):
        """Test get_messages with empty list returns empty list."""
        result = await authenticated_connector.get_messages([])
        assert result == []

    @pytest.mark.asyncio
    async def test_get_messages_single(self, authenticated_connector, sample_gmail_message):
        """Test get_messages with single message ID."""
        with patch.object(
            authenticated_connector, "_api_request", return_value=sample_gmail_message
        ):
            messages = await authenticated_connector.get_messages(["msg_123"])

            assert len(messages) == 1
            assert isinstance(messages[0], EmailMessage)
            assert messages[0].id == "msg_123"

    @pytest.mark.asyncio
    async def test_get_messages_multiple(self, authenticated_connector, sample_gmail_message):
        """Test get_messages with multiple message IDs fetches in parallel."""
        msg_1 = {**sample_gmail_message, "id": "msg_1"}
        msg_2 = {**sample_gmail_message, "id": "msg_2"}
        msg_3 = {**sample_gmail_message, "id": "msg_3"}

        call_count = 0

        async def mock_api_request(endpoint, **kwargs):
            nonlocal call_count
            call_count += 1
            if "msg_1" in endpoint:
                return msg_1
            elif "msg_2" in endpoint:
                return msg_2
            elif "msg_3" in endpoint:
                return msg_3
            return sample_gmail_message

        with patch.object(authenticated_connector, "_api_request", side_effect=mock_api_request):
            messages = await authenticated_connector.get_messages(["msg_1", "msg_2", "msg_3"])

            assert len(messages) == 3
            assert call_count == 3  # All three fetched
            ids = {msg.id for msg in messages}
            assert ids == {"msg_1", "msg_2", "msg_3"}

    @pytest.mark.asyncio
    async def test_get_messages_handles_failures_gracefully(
        self, authenticated_connector, sample_gmail_message
    ):
        """Test get_messages continues on individual failures and returns partial results."""
        msg_1 = {**sample_gmail_message, "id": "msg_1"}
        msg_3 = {**sample_gmail_message, "id": "msg_3"}

        async def mock_api_request(endpoint, **kwargs):
            if "msg_1" in endpoint:
                return msg_1
            elif "msg_2" in endpoint:
                raise RuntimeError("API error for msg_2")
            elif "msg_3" in endpoint:
                return msg_3
            return sample_gmail_message

        with patch.object(authenticated_connector, "_api_request", side_effect=mock_api_request):
            messages = await authenticated_connector.get_messages(["msg_1", "msg_2", "msg_3"])

            # Should return 2 messages (msg_2 failed)
            assert len(messages) == 2
            ids = {msg.id for msg in messages}
            assert ids == {"msg_1", "msg_3"}

    @pytest.mark.asyncio
    async def test_get_messages_respects_max_concurrent(
        self, authenticated_connector, sample_gmail_message
    ):
        """Test get_messages respects max_concurrent limit."""

        concurrent_count = 0
        max_concurrent_observed = 0

        async def mock_api_request(endpoint, **kwargs):
            nonlocal concurrent_count, max_concurrent_observed
            concurrent_count += 1
            max_concurrent_observed = max(max_concurrent_observed, concurrent_count)
            await asyncio.sleep(0.01)  # Small delay to test concurrency
            concurrent_count -= 1
            return {**sample_gmail_message, "id": endpoint.split("/")[-1]}

        with patch.object(authenticated_connector, "_api_request", side_effect=mock_api_request):
            message_ids = [f"msg_{i}" for i in range(20)]
            messages = await authenticated_connector.get_messages(message_ids, max_concurrent=5)

            assert len(messages) == 20
            # max_concurrent should have limited concurrent requests
            assert max_concurrent_observed <= 5

    @pytest.mark.asyncio
    async def test_get_messages_with_format_parameter(
        self, authenticated_connector, sample_gmail_message
    ):
        """Test get_messages passes format parameter correctly."""
        formats_requested = []

        async def mock_api_request(endpoint, params=None, **kwargs):
            if params:
                formats_requested.append(params.get("format"))
            return sample_gmail_message

        with patch.object(authenticated_connector, "_api_request", side_effect=mock_api_request):
            await authenticated_connector.get_messages(["msg_1", "msg_2"], format="metadata")

            assert all(f == "metadata" for f in formats_requested)

    @pytest.mark.asyncio
    async def test_get_messages_all_fail(self, authenticated_connector):
        """Test get_messages returns empty list when all fetches fail."""

        async def mock_api_request(endpoint, **kwargs):
            raise RuntimeError("All API calls fail")

        with patch.object(authenticated_connector, "_api_request", side_effect=mock_api_request):
            messages = await authenticated_connector.get_messages(["msg_1", "msg_2", "msg_3"])

            assert messages == []

    @pytest.mark.asyncio
    async def test_get_messages_strict_mode_raises_on_failure(
        self, authenticated_connector, sample_gmail_message
    ):
        """Test get_messages with strict=True raises when any fetch fails."""
        msg_1 = {**sample_gmail_message, "id": "msg_1"}

        async def mock_api_request(endpoint, **kwargs):
            if "msg_1" in endpoint:
                return msg_1
            elif "msg_2" in endpoint:
                raise RuntimeError("API error for msg_2")
            return sample_gmail_message

        with patch.object(authenticated_connector, "_api_request", side_effect=mock_api_request):
            with pytest.raises(RuntimeError, match="Failed to fetch 1 of 2 messages"):
                await authenticated_connector.get_messages(["msg_1", "msg_2"], strict=True)

    @pytest.mark.asyncio
    async def test_get_messages_strict_mode_success_when_all_pass(
        self, authenticated_connector, sample_gmail_message
    ):
        """Test get_messages with strict=True succeeds when all fetches pass."""
        msg_1 = {**sample_gmail_message, "id": "msg_1"}
        msg_2 = {**sample_gmail_message, "id": "msg_2"}

        async def mock_api_request(endpoint, **kwargs):
            if "msg_1" in endpoint:
                return msg_1
            elif "msg_2" in endpoint:
                return msg_2
            return sample_gmail_message

        with patch.object(authenticated_connector, "_api_request", side_effect=mock_api_request):
            messages = await authenticated_connector.get_messages(["msg_1", "msg_2"], strict=True)
            assert len(messages) == 2

    @pytest.mark.asyncio
    async def test_get_messages_batch_returns_result_object(
        self, authenticated_connector, sample_gmail_message
    ):
        """Test get_messages_batch returns BatchFetchResult with proper structure."""
        from aragora.connectors.enterprise.communication.models import BatchFetchResult

        msg_1 = {**sample_gmail_message, "id": "msg_1"}
        msg_3 = {**sample_gmail_message, "id": "msg_3"}

        async def mock_api_request(endpoint, **kwargs):
            if "msg_1" in endpoint:
                return msg_1
            elif "msg_2" in endpoint:
                raise ValueError("Message not found")
            elif "msg_3" in endpoint:
                return msg_3
            return sample_gmail_message

        with patch.object(authenticated_connector, "_api_request", side_effect=mock_api_request):
            result = await authenticated_connector.get_messages_batch(["msg_1", "msg_2", "msg_3"])

            assert isinstance(result, BatchFetchResult)
            assert result.total_requested == 3
            assert result.success_count == 2
            assert result.failure_count == 1
            assert result.is_partial is True
            assert result.is_complete is False
            assert result.is_total_failure is False
            assert "msg_2" in result.failed_ids
            assert len(result.messages) == 2

    @pytest.mark.asyncio
    async def test_get_messages_batch_failure_details(
        self, authenticated_connector, sample_gmail_message
    ):
        """Test get_messages_batch captures failure details correctly."""

        async def mock_api_request(endpoint, **kwargs):
            if "msg_1" in endpoint:
                raise TimeoutError("Connection timed out")
            elif "msg_2" in endpoint:
                raise ValueError("Invalid message format")
            return sample_gmail_message

        with patch.object(authenticated_connector, "_api_request", side_effect=mock_api_request):
            result = await authenticated_connector.get_messages_batch(["msg_1", "msg_2"])

            assert result.failure_count == 2
            assert result.is_total_failure is True

            # Check failure details
            failures_by_id = {f.message_id: f for f in result.failures}

            assert "msg_1" in failures_by_id
            assert failures_by_id["msg_1"].error_type == "TimeoutError"
            assert failures_by_id["msg_1"].is_retryable is True

            assert "msg_2" in failures_by_id
            assert failures_by_id["msg_2"].error_type == "ValueError"
            assert failures_by_id["msg_2"].is_retryable is False

    @pytest.mark.asyncio
    async def test_get_messages_batch_retryable_ids(
        self, authenticated_connector, sample_gmail_message
    ):
        """Test get_messages_batch correctly identifies retryable errors."""

        async def mock_api_request(endpoint, **kwargs):
            if "msg_1" in endpoint:
                raise ConnectionError("Connection reset")
            elif "msg_2" in endpoint:
                raise ValueError("Invalid data")
            elif "msg_3" in endpoint:
                raise RuntimeError("429 rate limit exceeded")
            return sample_gmail_message

        with patch.object(authenticated_connector, "_api_request", side_effect=mock_api_request):
            result = await authenticated_connector.get_messages_batch(["msg_1", "msg_2", "msg_3"])

            # msg_1 (connection) and msg_3 (429) should be retryable
            assert len(result.retryable_ids) == 2
            assert "msg_1" in result.retryable_ids
            assert "msg_3" in result.retryable_ids
            assert "msg_2" not in result.retryable_ids

    @pytest.mark.asyncio
    async def test_get_messages_batch_empty_input(self, authenticated_connector):
        """Test get_messages_batch with empty input returns empty result."""
        result = await authenticated_connector.get_messages_batch([])

        assert result.total_requested == 0
        assert result.success_count == 0
        assert result.failure_count == 0
        assert result.is_complete is True
        assert result.is_total_failure is False

    @pytest.mark.asyncio
    async def test_get_messages_batch_to_dict(self, authenticated_connector, sample_gmail_message):
        """Test BatchFetchResult.to_dict() serialization."""
        msg_1 = {**sample_gmail_message, "id": "msg_1"}

        async def mock_api_request(endpoint, **kwargs):
            if "msg_1" in endpoint:
                return msg_1
            raise ValueError("Not found")

        with patch.object(authenticated_connector, "_api_request", side_effect=mock_api_request):
            result = await authenticated_connector.get_messages_batch(["msg_1", "msg_2"])
            result_dict = result.to_dict()

            assert result_dict["success_count"] == 1
            assert result_dict["failure_count"] == 1
            assert result_dict["total_requested"] == 2
            assert result_dict["is_partial"] is True
            assert "msg_2" in result_dict["failed_ids"]
            assert len(result_dict["failures"]) == 1
            assert result_dict["failures"][0]["message_id"] == "msg_2"


class TestMessageParsing:
    """Tests for message parsing logic."""

    def test_parse_message_basic(self, gmail_connector, sample_gmail_message):
        """Test basic message parsing."""
        message = gmail_connector._parse_message(sample_gmail_message)

        assert message.id == "msg_123"
        assert message.subject == "Test Subject"
        assert message.body_text == "Hello, this is the email body."

    def test_parse_message_with_attachments(self, gmail_connector):
        """Test parsing message with attachments."""
        message_data = {
            "id": "msg_attach",
            "threadId": "thread_attach",
            "labelIds": ["INBOX"],
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [
                    {"name": "Subject", "value": "Message with attachment"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Wed, 17 Jan 2024 09:00:00 +0000"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": base64.urlsafe_b64encode(b"Email body").decode()},
                    },
                    {
                        "mimeType": "application/pdf",
                        "filename": "document.pdf",
                        "body": {
                            "attachmentId": "attach_123",
                            "size": 12345,
                        },
                    },
                ],
            },
        }

        message = gmail_connector._parse_message(message_data)

        assert len(message.attachments) == 1
        assert message.attachments[0].filename == "document.pdf"
        assert message.attachments[0].mime_type == "application/pdf"
        assert message.attachments[0].size == 12345

    def test_parse_message_nested_multipart(self, gmail_connector):
        """Test parsing nested multipart message."""
        message_data = {
            "id": "msg_nested",
            "threadId": "thread_nested",
            "labelIds": ["INBOX"],
            "payload": {
                "mimeType": "multipart/mixed",
                "headers": [
                    {"name": "Subject", "value": "Nested multipart"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Thu, 18 Jan 2024 11:00:00 +0000"},
                ],
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "parts": [
                            {
                                "mimeType": "text/plain",
                                "body": {"data": base64.urlsafe_b64encode(b"Plain text").decode()},
                            },
                            {
                                "mimeType": "text/html",
                                "body": {"data": base64.urlsafe_b64encode(b"<p>HTML</p>").decode()},
                            },
                        ],
                    },
                ],
            },
        }

        message = gmail_connector._parse_message(message_data)

        assert message.body_text == "Plain text"
        assert message.body_html == "<p>HTML</p>"


# =============================================================================
# Thread Tests
# =============================================================================


class TestThreadOperations:
    """Tests for thread operations."""

    @pytest.mark.asyncio
    async def test_get_thread(self, authenticated_connector, sample_gmail_message):
        """Test getting a conversation thread."""
        thread_data = {
            "id": "thread_456",
            "snippet": "Thread snippet...",
            "messages": [
                sample_gmail_message,
                {**sample_gmail_message, "id": "msg_124"},
            ],
        }

        with patch.object(authenticated_connector, "_api_request", return_value=thread_data):
            thread = await authenticated_connector.get_thread("thread_456")

            assert isinstance(thread, EmailThread)
            assert thread.id == "thread_456"
            assert len(thread.messages) == 2
            assert thread.message_count == 2
            assert "sender@example.com" in thread.participants


# =============================================================================
# History API Tests
# =============================================================================


class TestHistoryApi:
    """Tests for History API (incremental sync)."""

    @pytest.mark.asyncio
    async def test_get_history(self, authenticated_connector):
        """Test getting message history."""
        history_data = {
            "history": [
                {
                    "id": "100",
                    "messagesAdded": [{"message": {"id": "msg_new"}}],
                },
            ],
            "historyId": "101",
        }

        with patch.object(authenticated_connector, "_api_request", return_value=history_data):
            history, next_token, new_id = await authenticated_connector.get_history("99")

            assert len(history) == 1
            assert history[0]["messagesAdded"][0]["message"]["id"] == "msg_new"
            assert new_id == "101"

    @pytest.mark.asyncio
    async def test_get_history_expired(self, authenticated_connector):
        """Test handling expired history ID."""
        with patch.object(authenticated_connector, "_api_request") as mock_request:
            mock_request.side_effect = RuntimeError("404 historyId expired")

            history, next_token, new_id = await authenticated_connector.get_history("old_id")

            assert history == []
            assert new_id == ""


# =============================================================================
# Search and Fetch Tests
# =============================================================================


class TestSearchAndFetch:
    """Tests for search and fetch operations."""

    @pytest.mark.asyncio
    async def test_search(self, authenticated_connector, sample_gmail_message):
        """Test Gmail search uses batch fetching to avoid N+1 queries."""
        mock_msg = EmailMessage(
            id="msg_123",
            thread_id="thread_456",
            subject="Test",
            from_address="test@example.com",
            to_addresses=["recipient@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Body",
            snippet="Snippet",
        )

        with patch.object(
            authenticated_connector, "list_messages", return_value=(["msg_123"], None)
        ):
            with patch.object(
                authenticated_connector, "get_messages", return_value=[mock_msg]
            ) as mock_get_batch:
                results = await authenticated_connector.search("from:test@example.com", limit=10)

                assert len(results) == 1
                assert results[0].source_id == "msg_123"
                # Verify batch method was called instead of individual get_message
                mock_get_batch.assert_called_once_with(["msg_123"], format="metadata")

    @pytest.mark.asyncio
    async def test_search_multiple_results(self, authenticated_connector):
        """Test Gmail search with multiple results uses batch fetching."""
        mock_msgs = [
            EmailMessage(
                id=f"msg_{i}",
                thread_id=f"thread_{i}",
                subject=f"Test {i}",
                from_address="test@example.com",
                to_addresses=["recipient@example.com"],
                date=datetime.now(timezone.utc),
                body_text="Body",
                snippet="Snippet",
            )
            for i in range(3)
        ]

        with patch.object(
            authenticated_connector,
            "list_messages",
            return_value=(["msg_0", "msg_1", "msg_2"], None),
        ):
            with patch.object(
                authenticated_connector, "get_messages", return_value=mock_msgs
            ) as mock_get_batch:
                results = await authenticated_connector.search("from:test@example.com", limit=10)

                assert len(results) == 3
                # Verify single batch call instead of 3 individual calls
                mock_get_batch.assert_called_once_with(
                    ["msg_0", "msg_1", "msg_2"], format="metadata"
                )

    @pytest.mark.asyncio
    async def test_fetch(self, authenticated_connector):
        """Test fetching a specific email."""
        mock_msg = EmailMessage(
            id="msg_123",
            thread_id="thread_456",
            subject="Test Subject",
            from_address="sender@example.com",
            to_addresses=["recipient@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Email body",
            snippet="Snippet",
        )

        with patch.object(authenticated_connector, "get_message", return_value=mock_msg):
            evidence = await authenticated_connector.fetch("gmail-msg_123")

            assert evidence is not None
            assert evidence.source_id == "msg_123"
            assert evidence.title == "Test Subject"


# =============================================================================
# Send Message Tests
# =============================================================================


class TestSendMessage:
    """Tests for sending messages."""

    @pytest.mark.asyncio
    async def test_send_message_basic(self, authenticated_connector, mock_httpx_response):
        """Test sending a basic email."""
        response_data = {
            "id": "sent_msg_123",
            "threadId": "new_thread_123",
        }

        with patch.object(authenticated_connector, "_get_access_token", return_value="token"):
            with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
                with patch.object(authenticated_connector, "_get_client") as mock_get_client:
                    mock_client = AsyncMock()
                    mock_client.post = AsyncMock(
                        return_value=mock_httpx_response(200, response_data)
                    )
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock()
                    mock_get_client.return_value = mock_client

                    result = await authenticated_connector.send_message(
                        to=["recipient@example.com"],
                        subject="Test Subject",
                        body="Test body",
                    )

                    assert result["success"] is True
                    assert result["message_id"] == "sent_msg_123"

    @pytest.mark.asyncio
    async def test_send_message_with_cc_bcc(self, authenticated_connector, mock_httpx_response):
        """Test sending email with CC and BCC."""
        response_data = {"id": "sent_msg", "threadId": "thread"}

        with patch.object(authenticated_connector, "_get_access_token", return_value="token"):
            with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
                with patch.object(authenticated_connector, "_get_client") as mock_get_client:
                    mock_client = AsyncMock()
                    mock_client.post = AsyncMock(
                        return_value=mock_httpx_response(200, response_data)
                    )
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock()
                    mock_get_client.return_value = mock_client

                    result = await authenticated_connector.send_message(
                        to=["to@example.com"],
                        subject="Test",
                        body="Body",
                        cc=["cc@example.com"],
                        bcc=["bcc@example.com"],
                    )

                    assert result["success"] is True

    @pytest.mark.asyncio
    async def test_send_message_html(self, authenticated_connector, mock_httpx_response):
        """Test sending email with HTML body."""
        response_data = {"id": "sent_msg", "threadId": "thread"}

        with patch.object(authenticated_connector, "_get_access_token", return_value="token"):
            with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
                with patch.object(authenticated_connector, "_get_client") as mock_get_client:
                    mock_client = AsyncMock()
                    mock_client.post = AsyncMock(
                        return_value=mock_httpx_response(200, response_data)
                    )
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock()
                    mock_get_client.return_value = mock_client

                    result = await authenticated_connector.send_message(
                        to=["to@example.com"],
                        subject="HTML Email",
                        body="Plain text fallback",
                        html_body="<html><body><h1>HTML Content</h1></body></html>",
                    )

                    assert result["success"] is True

    @pytest.mark.asyncio
    async def test_send_message_circuit_breaker_open(self, authenticated_connector):
        """Test send fails when circuit breaker is open."""
        with patch.object(authenticated_connector, "_get_access_token", return_value="token"):
            with patch.object(authenticated_connector, "check_circuit_breaker", return_value=False):
                with patch.object(
                    authenticated_connector,
                    "get_circuit_breaker_status",
                    return_value={"cooldown_seconds": 60},
                ):
                    with pytest.raises(ConnectionError, match="Circuit breaker open"):
                        await authenticated_connector.send_message(
                            to=["to@example.com"],
                            subject="Test",
                            body="Body",
                        )


# =============================================================================
# Reply Tests
# =============================================================================


class TestReplyToMessage:
    """Tests for replying to messages."""

    @pytest.mark.asyncio
    async def test_reply_to_message(self, authenticated_connector, mock_httpx_response):
        """Test replying to a message."""
        original_msg = EmailMessage(
            id="original_msg",
            thread_id="original_thread",
            subject="Original Subject",
            from_address="original@example.com",
            to_addresses=["me@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Original body",
            headers={"message-id": "<original@example.com>"},
        )

        response_data = {
            "id": "reply_msg",
            "threadId": "original_thread",
        }

        with patch.object(authenticated_connector, "_get_access_token", return_value="token"):
            with patch.object(authenticated_connector, "get_message", return_value=original_msg):
                with patch.object(
                    authenticated_connector, "check_circuit_breaker", return_value=True
                ):
                    with patch.object(authenticated_connector, "_get_client") as mock_get_client:
                        mock_client = AsyncMock()
                        mock_client.post = AsyncMock(
                            return_value=mock_httpx_response(200, response_data)
                        )
                        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                        mock_client.__aexit__ = AsyncMock()
                        mock_get_client.return_value = mock_client

                        result = await authenticated_connector.reply_to_message(
                            original_message_id="original_msg",
                            body="Reply body",
                        )

                        assert result["success"] is True
                        assert result["in_reply_to"] == "original_msg"
                        assert result["thread_id"] == "original_thread"


# =============================================================================
# Email Actions Tests
# =============================================================================


class TestEmailActions:
    """Tests for email actions (archive, trash, star, etc.)."""

    @pytest.mark.asyncio
    async def test_modify_message(self, authenticated_connector, mock_httpx_response):
        """Test modifying message labels."""
        response_data = {
            "id": "msg_123",
            "labelIds": ["INBOX", "STARRED"],
        }

        with patch.object(authenticated_connector, "_get_access_token", return_value="token"):
            with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
                with patch.object(authenticated_connector, "_get_client") as mock_get_client:
                    mock_client = AsyncMock()
                    mock_client.post = AsyncMock(
                        return_value=mock_httpx_response(200, response_data)
                    )
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock()
                    mock_get_client.return_value = mock_client

                    result = await authenticated_connector.modify_message(
                        "msg_123",
                        add_labels=["STARRED"],
                        remove_labels=["UNREAD"],
                    )

                    assert result["success"] is True
                    assert "STARRED" in result["labels"]

    @pytest.mark.asyncio
    async def test_archive_message(self, authenticated_connector):
        """Test archiving a message."""
        with patch.object(authenticated_connector, "modify_message") as mock_modify:
            mock_modify.return_value = {"message_id": "msg_123", "success": True}

            result = await authenticated_connector.archive_message("msg_123")

            mock_modify.assert_called_once_with("msg_123", remove_labels=["INBOX"])
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_trash_message(self, authenticated_connector, mock_httpx_response):
        """Test trashing a message."""
        with patch.object(authenticated_connector, "_get_access_token", return_value="token"):
            with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
                with patch.object(authenticated_connector, "_get_client") as mock_get_client:
                    mock_client = AsyncMock()
                    mock_client.post = AsyncMock(return_value=mock_httpx_response(200, {}))
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock()
                    mock_get_client.return_value = mock_client

                    result = await authenticated_connector.trash_message("msg_123")

                    assert result["success"] is True

    @pytest.mark.asyncio
    async def test_untrash_message(self, authenticated_connector, mock_httpx_response):
        """Test untrashing a message."""
        with patch.object(authenticated_connector, "_get_access_token", return_value="token"):
            with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
                with patch.object(authenticated_connector, "_get_client") as mock_get_client:
                    mock_client = AsyncMock()
                    mock_client.post = AsyncMock(return_value=mock_httpx_response(200, {}))
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock()
                    mock_get_client.return_value = mock_client

                    result = await authenticated_connector.untrash_message("msg_123")

                    assert result["success"] is True

    @pytest.mark.asyncio
    async def test_mark_as_read(self, authenticated_connector):
        """Test marking message as read."""
        with patch.object(authenticated_connector, "modify_message") as mock_modify:
            mock_modify.return_value = {"message_id": "msg_123", "success": True}

            result = await authenticated_connector.mark_as_read("msg_123")

            mock_modify.assert_called_once_with("msg_123", remove_labels=["UNREAD"])
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_mark_as_unread(self, authenticated_connector):
        """Test marking message as unread."""
        with patch.object(authenticated_connector, "modify_message") as mock_modify:
            mock_modify.return_value = {"message_id": "msg_123", "success": True}

            result = await authenticated_connector.mark_as_unread("msg_123")

            mock_modify.assert_called_once_with("msg_123", add_labels=["UNREAD"])

    @pytest.mark.asyncio
    async def test_star_message(self, authenticated_connector):
        """Test starring a message."""
        with patch.object(authenticated_connector, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            result = await authenticated_connector.star_message("msg_123")

            mock_modify.assert_called_once_with("msg_123", add_labels=["STARRED"])

    @pytest.mark.asyncio
    async def test_unstar_message(self, authenticated_connector):
        """Test unstarring a message."""
        with patch.object(authenticated_connector, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            await authenticated_connector.unstar_message("msg_123")

            mock_modify.assert_called_once_with("msg_123", remove_labels=["STARRED"])

    @pytest.mark.asyncio
    async def test_mark_important(self, authenticated_connector):
        """Test marking message as important."""
        with patch.object(authenticated_connector, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            await authenticated_connector.mark_important("msg_123")

            mock_modify.assert_called_once_with("msg_123", add_labels=["IMPORTANT"])

    @pytest.mark.asyncio
    async def test_mark_not_important(self, authenticated_connector):
        """Test removing important flag."""
        with patch.object(authenticated_connector, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            await authenticated_connector.mark_not_important("msg_123")

            mock_modify.assert_called_once_with("msg_123", remove_labels=["IMPORTANT"])

    @pytest.mark.asyncio
    async def test_move_to_folder(self, authenticated_connector):
        """Test moving message to folder."""
        with patch.object(authenticated_connector, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            await authenticated_connector.move_to_folder("msg_123", "Label_Work")

            mock_modify.assert_called_once_with(
                "msg_123",
                add_labels=["Label_Work"],
                remove_labels=["INBOX"],
            )

    @pytest.mark.asyncio
    async def test_snooze_message(self, authenticated_connector):
        """Test snoozing a message."""
        snooze_until = datetime.now(timezone.utc) + timedelta(hours=2)

        with patch.object(authenticated_connector, "archive_message") as mock_archive:
            with patch.object(authenticated_connector, "modify_message") as mock_modify:
                mock_archive.return_value = {"success": True}
                mock_modify.return_value = {"success": True}

                result = await authenticated_connector.snooze_message("msg_123", snooze_until)

                mock_archive.assert_called_once_with("msg_123")
                assert result["success"] is True
                assert "snoozed_until" in result

    @pytest.mark.asyncio
    async def test_add_label(self, authenticated_connector):
        """Test adding a label to message."""
        with patch.object(authenticated_connector, "modify_message") as mock_modify:
            mock_modify.return_value = {"success": True}

            await authenticated_connector.add_label("msg_123", "Label_Custom")

            mock_modify.assert_called_once_with("msg_123", add_labels=["Label_Custom"])


# =============================================================================
# Batch Operations Tests
# =============================================================================


class TestBatchOperations:
    """Tests for batch operations."""

    @pytest.mark.asyncio
    async def test_batch_modify(self, authenticated_connector, mock_httpx_response):
        """Test batch modifying messages."""
        with patch.object(authenticated_connector, "_get_access_token", return_value="token"):
            with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
                with patch.object(authenticated_connector, "_get_client") as mock_get_client:
                    mock_client = AsyncMock()
                    mock_response = Mock()
                    mock_response.status_code = 204
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock()
                    mock_get_client.return_value = mock_client

                    result = await authenticated_connector.batch_modify(
                        ["msg_1", "msg_2", "msg_3"],
                        add_labels=["STARRED"],
                        remove_labels=["UNREAD"],
                    )

                    assert result["success"] is True
                    assert result["modified_count"] == 3

    @pytest.mark.asyncio
    async def test_batch_archive(self, authenticated_connector):
        """Test batch archiving messages."""
        with patch.object(authenticated_connector, "batch_modify") as mock_batch:
            mock_batch.return_value = {"success": True, "modified_count": 3}

            result = await authenticated_connector.batch_archive(["msg_1", "msg_2", "msg_3"])

            mock_batch.assert_called_once_with(
                ["msg_1", "msg_2", "msg_3"],
                remove_labels=["INBOX"],
            )
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_batch_trash(self, authenticated_connector, mock_httpx_response):
        """Test batch deleting messages."""
        with patch.object(authenticated_connector, "_get_access_token", return_value="token"):
            with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
                with patch.object(authenticated_connector, "_get_client") as mock_get_client:
                    mock_client = AsyncMock()
                    mock_response = Mock()
                    mock_response.status_code = 204
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock()
                    mock_get_client.return_value = mock_client

                    result = await authenticated_connector.batch_trash(["msg_1", "msg_2"])

                    assert result["success"] is True
                    assert result["deleted_count"] == 2


# =============================================================================
# Pub/Sub Watch Tests
# =============================================================================


class TestPubSubWatch:
    """Tests for Pub/Sub watch management."""

    @pytest.mark.asyncio
    async def test_setup_watch(self, authenticated_connector, mock_httpx_response):
        """Test setting up Gmail watch."""
        watch_response = {
            "historyId": "12345",
            "expiration": str(
                int((datetime.now(timezone.utc) + timedelta(days=7)).timestamp() * 1000)
            ),
        }

        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "my-project"}):
            with patch.object(authenticated_connector, "_get_access_token", return_value="token"):
                with patch.object(
                    authenticated_connector, "check_circuit_breaker", return_value=True
                ):
                    with patch.object(authenticated_connector, "_get_client") as mock_get_client:
                        mock_client = AsyncMock()
                        mock_client.post = AsyncMock(
                            return_value=mock_httpx_response(200, watch_response)
                        )
                        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                        mock_client.__aexit__ = AsyncMock()
                        mock_get_client.return_value = mock_client

                        result = await authenticated_connector.setup_watch(
                            topic_name="gmail-notifications",
                            label_ids=["INBOX"],
                        )

                        assert result["success"] is True
                        assert result["history_id"] == "12345"
                        assert "expiration" in result

    @pytest.mark.asyncio
    async def test_setup_watch_no_project_id(self, authenticated_connector):
        """Test setup_watch fails without project ID."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="project_id required"):
                await authenticated_connector.setup_watch("topic")

    @pytest.mark.asyncio
    async def test_stop_watch(self, authenticated_connector, mock_httpx_response):
        """Test stopping Gmail watch."""
        with patch.object(authenticated_connector, "_get_access_token", return_value="token"):
            with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
                with patch.object(authenticated_connector, "_get_client") as mock_get_client:
                    mock_client = AsyncMock()
                    mock_response = Mock()
                    mock_response.status_code = 204
                    mock_client.post = AsyncMock(return_value=mock_response)
                    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                    mock_client.__aexit__ = AsyncMock()
                    mock_get_client.return_value = mock_client

                    result = await authenticated_connector.stop_watch()

                    assert result["success"] is True

    @pytest.mark.asyncio
    async def test_handle_pubsub_notification(self, authenticated_connector):
        """Test handling Pub/Sub notification."""
        # Set up connector state
        authenticated_connector._gmail_state = GmailSyncState(
            user_id="me",
            email_address="test@example.com",
            history_id="12345",
        )

        # Create webhook payload
        data = {
            "emailAddress": "test@example.com",
            "historyId": "12346",
        }
        data_b64 = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()

        payload = {
            "message": {
                "data": data_b64,
                "messageId": "webhook_msg",
            },
            "subscription": "projects/test/subscriptions/gmail-sub",
        }

        mock_msg = EmailMessage(
            id="new_msg",
            thread_id="new_thread",
            subject="New Message",
            from_address="sender@example.com",
            to_addresses=["test@example.com"],
            date=datetime.now(timezone.utc),
            body_text="New message body",
        )

        with patch.object(authenticated_connector, "get_history") as mock_history:
            mock_history.return_value = (
                [{"messagesAdded": [{"message": {"id": "new_msg"}}]}],
                None,
                "12346",
            )
            with patch.object(authenticated_connector, "get_message", return_value=mock_msg):
                messages = await authenticated_connector.handle_pubsub_notification(payload)

                assert len(messages) == 1
                assert messages[0].id == "new_msg"

    @pytest.mark.asyncio
    async def test_handle_pubsub_wrong_email(self, authenticated_connector):
        """Test webhook for wrong email is ignored."""
        authenticated_connector._gmail_state = GmailSyncState(
            user_id="me",
            email_address="correct@example.com",
            history_id="12345",
        )

        data = {
            "emailAddress": "wrong@example.com",
            "historyId": "12346",
        }
        data_b64 = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()

        payload = {
            "message": {"data": data_b64, "messageId": "msg"},
            "subscription": "test",
        }

        messages = await authenticated_connector.handle_pubsub_notification(payload)

        assert messages == []


# =============================================================================
# State Persistence Tests
# =============================================================================


class TestStatePersistence:
    """Tests for state persistence."""

    @pytest.mark.asyncio
    async def test_save_gmail_state_memory(self, authenticated_connector):
        """Test saving state to memory."""
        authenticated_connector._gmail_state = GmailSyncState(
            user_id="me",
            history_id="12345",
            email_address="test@example.com",
        )

        result = await authenticated_connector.save_gmail_state(
            tenant_id="tenant_1",
            user_id="user_1",
            backend="memory",
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_save_gmail_state_no_state(self, authenticated_connector):
        """Test saving when no state exists."""
        authenticated_connector._gmail_state = None

        result = await authenticated_connector.save_gmail_state(
            tenant_id="tenant_1",
            user_id="user_1",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_load_gmail_state_not_found(self, authenticated_connector):
        """Test loading state when not found."""
        result = await authenticated_connector.load_gmail_state(
            tenant_id="tenant_1",
            user_id="user_1",
            backend="memory",
        )

        assert result is None

    def test_get_sync_stats(self, authenticated_connector):
        """Test getting sync statistics."""
        authenticated_connector._gmail_state = GmailSyncState(
            user_id="me",
            email_address="test@example.com",
            history_id="12345",
            total_messages=1000,
            indexed_messages=500,
            initial_sync_complete=True,
        )

        stats = authenticated_connector.get_sync_stats()

        assert stats["user_id"] == "me"
        assert stats["email_address"] == "test@example.com"
        assert stats["history_id"] == "12345"
        assert stats["total_messages"] == 1000
        assert stats["indexed_messages"] == 500
        assert stats["initial_sync_complete"] is True


# =============================================================================
# Sync Items Tests
# =============================================================================


class TestSyncItems:
    """Tests for sync item operations."""

    @pytest.mark.asyncio
    async def test_sync_items_full_sync(self, authenticated_connector):
        """Test full sync with no cursor."""
        state = SyncState(connector_id="gmail")

        profile_data = {
            "emailAddress": "test@example.com",
            "historyId": "12345",
        }

        mock_msg = EmailMessage(
            id="msg_1",
            thread_id="thread_1",
            subject="Test",
            from_address="sender@example.com",
            to_addresses=["test@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Body",
            labels=["INBOX"],
        )

        with patch.object(authenticated_connector, "get_user_info", return_value=profile_data):
            with patch.object(
                authenticated_connector, "list_messages", return_value=(["msg_1"], None)
            ):
                with patch.object(authenticated_connector, "get_message", return_value=mock_msg):
                    items = []
                    async for item in authenticated_connector.sync_items(state, batch_size=10):
                        items.append(item)

                    assert len(items) == 1
                    assert state.cursor == "12345"

    @pytest.mark.asyncio
    async def test_sync_items_incremental(self, authenticated_connector):
        """Test incremental sync with cursor."""
        state = SyncState(connector_id="gmail", cursor="12345")

        mock_msg = EmailMessage(
            id="new_msg",
            thread_id="new_thread",
            subject="New",
            from_address="sender@example.com",
            to_addresses=["test@example.com"],
            date=datetime.now(timezone.utc),
            body_text="New body",
            labels=["INBOX"],
        )

        with patch.object(authenticated_connector, "get_history") as mock_history:
            mock_history.return_value = (
                [{"messagesAdded": [{"message": {"id": "new_msg"}}]}],
                None,
                "12346",
            )
            with patch.object(authenticated_connector, "get_message", return_value=mock_msg):
                items = []
                async for item in authenticated_connector.sync_items(state, batch_size=10):
                    items.append(item)

                assert len(items) == 1
                assert state.cursor == "12346"

    @pytest.mark.asyncio
    async def test_sync_items_excludes_labels(self, gmail_connector):
        """Test sync excludes specified labels."""
        state = SyncState(connector_id="gmail", cursor="12345")

        mock_msg = EmailMessage(
            id="spam_msg",
            thread_id="spam_thread",
            subject="Spam",
            from_address="spammer@example.com",
            to_addresses=["test@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Spam body",
            labels=["SPAM"],  # In exclude_labels
        )

        gmail_connector._access_token = "token"
        gmail_connector._refresh_token = "refresh"
        gmail_connector._token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)

        with patch.object(gmail_connector, "get_history") as mock_history:
            mock_history.return_value = (
                [{"messagesAdded": [{"message": {"id": "spam_msg"}}]}],
                None,
                "12346",
            )
            with patch.object(gmail_connector, "get_message", return_value=mock_msg):
                items = []
                async for item in gmail_connector.sync_items(state, batch_size=10):
                    items.append(item)

                # Should be excluded because SPAM is in exclude_labels
                assert len(items) == 0

    def test_message_to_sync_item(self, gmail_connector):
        """Test converting EmailMessage to SyncItem."""
        msg = EmailMessage(
            id="msg_123",
            thread_id="thread_123",
            subject="Test Subject",
            from_address="sender@example.com",
            to_addresses=["recipient@example.com"],
            cc_addresses=["cc@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Email body content",
            snippet="Snippet...",
            labels=["INBOX", "IMPORTANT"],
            attachments=[
                EmailAttachment(
                    id="att_1", filename="file.pdf", mime_type="application/pdf", size=1000
                )
            ],
            is_read=True,
            is_starred=False,
            is_important=True,
        )

        sync_item = gmail_connector._message_to_sync_item(msg)

        assert sync_item.id == "gmail-msg_123"
        assert sync_item.source_type == "email"
        assert sync_item.title == "Test Subject"
        assert sync_item.author == "sender@example.com"
        assert "Subject: Test Subject" in sync_item.content
        assert "From: sender@example.com" in sync_item.content
        assert sync_item.metadata["has_attachments"] is True
        assert sync_item.metadata["is_important"] is True


# =============================================================================
# Prioritization Tests
# =============================================================================


class TestPrioritization:
    """Tests for email prioritization integration."""

    @pytest.mark.asyncio
    async def test_sync_with_prioritization_no_messages(self, authenticated_connector):
        """Test prioritization with empty message list."""
        results = await authenticated_connector.sync_with_prioritization([])
        assert results == []

    @pytest.mark.asyncio
    async def test_sync_with_prioritization_no_prioritizer(self, authenticated_connector):
        """Test prioritization when EmailPrioritizer not available."""
        msg = EmailMessage(
            id="msg_1",
            thread_id="thread_1",
            subject="Test",
            from_address="sender@example.com",
            to_addresses=["test@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Body",
        )

        # Mock import failure for EmailPrioritizer
        with patch.dict("sys.modules", {"aragora.services.email_prioritization": None}):
            with patch("aragora.connectors.enterprise.communication.gmail.logger"):
                results = await authenticated_connector.sync_with_prioritization([msg])

                assert len(results) == 1
                assert results[0]["priority"] == "MEDIUM"
                assert results[0]["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_rank_inbox(self, authenticated_connector):
        """Test rank inbox uses batch fetching to avoid N+1 queries."""
        mock_msg = EmailMessage(
            id="msg_1",
            thread_id="thread_1",
            subject="Test",
            from_address="sender@example.com",
            to_addresses=["test@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Body",
        )

        with patch.object(authenticated_connector, "list_messages", return_value=(["msg_1"], None)):
            with patch.object(
                authenticated_connector, "get_messages", return_value=[mock_msg]
            ) as mock_get_batch:
                with patch.object(authenticated_connector, "sync_with_prioritization") as mock_prio:
                    mock_prio.return_value = [{"message": mock_msg, "priority": "HIGH"}]

                    results = await authenticated_connector.rank_inbox(max_messages=10)

                    assert len(results) == 1
                    # Verify batch method was used instead of individual get_message
                    mock_get_batch.assert_called_once_with(["msg_1"])

    @pytest.mark.asyncio
    async def test_rank_inbox_multiple_messages(self, authenticated_connector):
        """Test rank inbox with multiple messages uses batch fetching."""
        mock_msgs = [
            EmailMessage(
                id=f"msg_{i}",
                thread_id=f"thread_{i}",
                subject=f"Test {i}",
                from_address="sender@example.com",
                to_addresses=["test@example.com"],
                date=datetime.now(timezone.utc),
                body_text="Body",
            )
            for i in range(5)
        ]

        with patch.object(
            authenticated_connector,
            "list_messages",
            return_value=([f"msg_{i}" for i in range(5)], None),
        ):
            with patch.object(
                authenticated_connector, "get_messages", return_value=mock_msgs
            ) as mock_get_batch:
                with patch.object(authenticated_connector, "sync_with_prioritization") as mock_prio:
                    mock_prio.return_value = [
                        {"message": msg, "priority": "HIGH"} for msg in mock_msgs
                    ]

                    results = await authenticated_connector.rank_inbox(max_messages=10)

                    assert len(results) == 5
                    # Verify single batch call instead of 5 individual calls
                    mock_get_batch.assert_called_once()


# =============================================================================
# Model Tests
# =============================================================================


class TestGmailModels:
    """Tests for Gmail data models."""

    def test_email_message_to_dict(self):
        """Test EmailMessage serialization."""
        msg = EmailMessage(
            id="msg_1",
            thread_id="thread_1",
            subject="Test",
            from_address="sender@example.com",
            to_addresses=["to@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Body",
            is_read=True,
            importance_score=0.8,
        )

        data = msg.to_dict()

        assert data["id"] == "msg_1"
        assert data["subject"] == "Test"
        assert data["is_read"] is True
        assert data["importance_score"] == 0.8

    def test_email_message_from_dict(self):
        """Test EmailMessage deserialization."""
        data = {
            "id": "msg_1",
            "thread_id": "thread_1",
            "subject": "Test",
            "from_address": "sender@example.com",
            "to_addresses": ["to@example.com"],
            "date": "2024-01-15T10:00:00+00:00",
            "body_text": "Body",
            "attachments": [
                {"id": "att_1", "filename": "file.pdf", "mime_type": "application/pdf", "size": 100}
            ],
        }

        msg = EmailMessage.from_dict(data)

        assert msg.id == "msg_1"
        assert msg.subject == "Test"
        assert len(msg.attachments) == 1
        assert msg.attachments[0].filename == "file.pdf"

    def test_email_thread_to_dict(self):
        """Test EmailThread serialization."""
        thread = EmailThread(
            id="thread_1",
            subject="Test Thread",
            participants=["a@example.com", "b@example.com"],
            message_count=3,
        )

        data = thread.to_dict()

        assert data["id"] == "thread_1"
        assert data["message_count"] == 3

    def test_gmail_sync_state_serialization(self):
        """Test GmailSyncState serialization/deserialization."""
        state = GmailSyncState(
            user_id="me",
            history_id="12345",
            email_address="test@example.com",
            initial_sync_complete=True,
            total_messages=1000,
            indexed_messages=500,
        )

        data = state.to_dict()
        restored = GmailSyncState.from_dict(data)

        assert restored.user_id == state.user_id
        assert restored.history_id == state.history_id
        assert restored.initial_sync_complete is True

    def test_webhook_payload_parsing(self):
        """Test GmailWebhookPayload parsing."""
        data = {
            "emailAddress": "user@example.com",
            "historyId": "12345",
        }
        data_b64 = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()

        payload = {
            "message": {
                "data": data_b64,
                "messageId": "webhook_123",
            },
            "subscription": "projects/proj/subscriptions/sub",
        }

        webhook = GmailWebhookPayload.from_pubsub(payload)

        assert webhook.message_id == "webhook_123"
        assert webhook.email_address == "user@example.com"
        assert webhook.history_id == "12345"


# =============================================================================
# Scope Constants Tests
# =============================================================================


class TestScopeConstants:
    """Tests for Gmail scope constants."""

    def test_readonly_scopes(self):
        """Test readonly scopes."""
        assert "gmail.readonly" in GMAIL_SCOPES_READONLY[0]
        assert len(GMAIL_SCOPES_READONLY) == 1

    def test_full_scopes(self):
        """Test full scopes include send and modify."""
        scope_str = " ".join(GMAIL_SCOPES_FULL)
        assert "gmail.readonly" in scope_str
        assert "gmail.send" in scope_str
        assert "gmail.modify" in scope_str

    def test_default_scopes(self):
        """Test default scopes are readonly."""
        assert GMAIL_SCOPES == GMAIL_SCOPES_READONLY
