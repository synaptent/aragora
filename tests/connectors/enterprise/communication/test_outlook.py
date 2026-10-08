"""
Tests for Outlook/Microsoft 365 Enterprise Connector.

Comprehensive tests for OutlookConnector covering:
- OAuth authentication flow
- Token management and refresh
- Message retrieval and parsing
- Folder management
- Email actions
- Delta Query API for incremental sync
- Circuit breaker integration
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from aragora.connectors.enterprise.communication.outlook import (
    OutlookConnector,
    OUTLOOK_SCOPES,
    OUTLOOK_SCOPES_READONLY,
    OUTLOOK_SCOPES_FULL,
)
from aragora.connectors.enterprise.communication.models import (
    EmailAttachment,
    EmailMessage,
    EmailThread,
    OutlookFolder,
    OutlookSyncState,
)
from aragora.connectors.enterprise.base import SyncState


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def outlook_connector():
    """Create an Outlook connector for testing."""
    return OutlookConnector(
        folders=["Inbox", "Important"],
        exclude_folders=["Deleted Items", "Junk Email"],
        max_results=50,
        include_deleted=False,
    )


@pytest.fixture
def authenticated_connector():
    """Create an authenticated Outlook connector."""
    connector = OutlookConnector()
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
        response.content = content or b'{"value": []}'
        response.text = response.content.decode() if response.content else ""
        response.raise_for_status = Mock()
        if status_code >= 400:
            import httpx

            request = httpx.Request("GET", "https://graph.microsoft.com/test")
            response.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Error", request=request, response=response
            )
        return response

    return _create


@pytest.fixture
def sample_outlook_message():
    """Sample Microsoft Graph API message response."""
    return {
        "id": "msg_123",
        "conversationId": "conv_456",
        "subject": "Test Subject",
        "from": {"emailAddress": {"name": "Sender", "address": "sender@example.com"}},
        "toRecipients": [
            {"emailAddress": {"name": "Recipient", "address": "recipient@example.com"}}
        ],
        "ccRecipients": [{"emailAddress": {"name": "CC", "address": "cc@example.com"}}],
        "bccRecipients": [],
        "receivedDateTime": "2024-01-15T10:30:00Z",
        "bodyPreview": "This is a preview...",
        "body": {
            "contentType": "text",
            "content": "This is the full email body.",
        },
        "isRead": False,
        "flag": {"flagStatus": "notFlagged"},
        "importance": "normal",
        "hasAttachments": False,
        "internetMessageHeaders": [{"name": "Message-ID", "value": "<msg123@example.com>"}],
        "parentFolderId": "inbox_folder_id",
    }


# =============================================================================
# Initialization Tests
# =============================================================================


class TestOutlookConnectorInitialization:
    """Tests for OutlookConnector initialization."""

    def test_default_initialization(self):
        """Test default connector initialization."""
        connector = OutlookConnector()

        assert connector.connector_id == "outlook"
        assert connector.folders is None
        assert connector.exclude_folders == set()
        assert connector.max_results == 100
        assert connector.include_deleted is False
        assert connector.user_id == "me"
        assert connector._access_token is None
        assert connector._refresh_token is None

    def test_custom_initialization(self, outlook_connector):
        """Test connector with custom parameters."""
        assert outlook_connector.folders == ["Inbox", "Important"]
        assert outlook_connector.exclude_folders == {"Deleted Items", "Junk Email"}
        assert outlook_connector.max_results == 50
        assert outlook_connector.include_deleted is False

    def test_source_type(self, outlook_connector):
        """Test source type property."""
        from aragora.reasoning.provenance import SourceType

        assert outlook_connector.source_type == SourceType.DOCUMENT

    def test_name_property(self, outlook_connector):
        """Test name property."""
        assert outlook_connector.name == "Outlook"

    def test_is_configured_without_env(self, outlook_connector):
        """Test is_configured returns False without credentials."""
        with patch.dict("os.environ", {}, clear=True):
            assert outlook_connector.is_configured is False

    def test_is_configured_with_env(self, outlook_connector):
        """Test is_configured returns True with credentials."""
        with patch.dict("os.environ", {"OUTLOOK_CLIENT_ID": "test_client_id"}):
            assert outlook_connector.is_configured is True

    def test_is_configured_with_azure_prefix(self, outlook_connector):
        """Test is_configured with AZURE_ prefix."""
        with patch.dict("os.environ", {"AZURE_CLIENT_ID": "test_client_id"}):
            assert outlook_connector.is_configured is True

    def test_is_configured_with_microsoft_prefix(self, outlook_connector):
        """Test is_configured with MICROSOFT_ prefix."""
        with patch.dict("os.environ", {"MICROSOFT_CLIENT_ID": "test_client_id"}):
            assert outlook_connector.is_configured is True


# =============================================================================
# OAuth Flow Tests
# =============================================================================


class TestOAuthFlow:
    """Tests for OAuth authentication flow."""

    def test_get_oauth_url_basic(self, outlook_connector):
        """Test OAuth URL generation."""
        with patch.dict("os.environ", {"OUTLOOK_CLIENT_ID": "test_client_id"}):
            url = outlook_connector.get_oauth_url(
                redirect_uri="https://example.com/callback",
                state="test_state",
            )

            assert "login.microsoftonline.com" in url
            assert "client_id=test_client_id" in url
            assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in url
            assert "response_type=code" in url
            assert "state=test_state" in url

    def test_get_oauth_url_without_state(self, outlook_connector):
        """Test OAuth URL without state parameter."""
        with patch.dict("os.environ", {"OUTLOOK_CLIENT_ID": "test_client_id"}):
            url = outlook_connector.get_oauth_url(
                redirect_uri="https://example.com/callback",
            )

            assert "state=" not in url

    def test_get_oauth_url_includes_scopes(self, outlook_connector):
        """Test OAuth URL includes correct scopes."""
        with patch.dict("os.environ", {"OUTLOOK_CLIENT_ID": "test_client_id"}):
            url = outlook_connector.get_oauth_url(
                redirect_uri="https://example.com/callback",
            )

            assert "Mail.Read" in url
            assert "offline_access" in url

    def test_get_oauth_url_with_custom_tenant(self, outlook_connector):
        """Test OAuth URL with custom tenant."""
        with patch.dict(
            "os.environ",
            {
                "OUTLOOK_CLIENT_ID": "test_client_id",
                "OUTLOOK_TENANT_ID": "my-tenant-id",
            },
        ):
            url = outlook_connector.get_oauth_url(
                redirect_uri="https://example.com/callback",
            )

            assert "my-tenant-id" in url


# =============================================================================
# Authentication Tests
# =============================================================================


class TestAuthentication:
    """Tests for authentication methods."""

    @pytest.mark.asyncio
    async def test_authenticate_with_code(self, outlook_connector, mock_httpx_response):
        """Test authentication with authorization code."""
        token_response = {
            "access_token": "new_access_token",
            "refresh_token": "new_refresh_token",
            "expires_in": 3600,
        }

        with patch.dict(
            "os.environ",
            {
                "OUTLOOK_CLIENT_ID": "test_client_id",
                "OUTLOOK_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post = AsyncMock(
                    return_value=mock_httpx_response(200, token_response)
                )
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                result = await outlook_connector.authenticate(
                    code="auth_code",
                    redirect_uri="https://example.com/callback",
                )

                assert result is True
                assert outlook_connector._access_token == "new_access_token"
                assert outlook_connector._refresh_token == "new_refresh_token"
                assert outlook_connector._token_expiry is not None

    @pytest.mark.asyncio
    async def test_authenticate_with_refresh_token(self, outlook_connector, mock_httpx_response):
        """Test authentication with refresh token."""
        token_response = {
            "access_token": "refreshed_access_token",
            "expires_in": 3600,
        }

        with patch.dict(
            "os.environ",
            {
                "OUTLOOK_CLIENT_ID": "test_client_id",
                "OUTLOOK_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post = AsyncMock(
                    return_value=mock_httpx_response(200, token_response)
                )
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                result = await outlook_connector.authenticate(
                    refresh_token="existing_refresh_token",
                )

                assert result is True
                assert outlook_connector._access_token == "refreshed_access_token"
                assert outlook_connector._refresh_token == "existing_refresh_token"

    @pytest.mark.asyncio
    async def test_authenticate_missing_credentials(self, outlook_connector):
        """Test authentication fails without credentials."""
        with patch.dict("os.environ", {}, clear=True):
            result = await outlook_connector.authenticate(
                code="auth_code",
                redirect_uri="https://example.com/callback",
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_no_code_or_token(self, outlook_connector):
        """Test authentication fails without code or refresh token."""
        with patch.dict(
            "os.environ",
            {
                "OUTLOOK_CLIENT_ID": "test_client_id",
                "OUTLOOK_CLIENT_SECRET": "test_secret",
            },
        ):
            result = await outlook_connector.authenticate()
            assert result is False

    @pytest.mark.asyncio
    async def test_authenticate_api_error(self, outlook_connector, mock_httpx_response):
        """Test authentication handles API errors."""
        with patch.dict(
            "os.environ",
            {
                "OUTLOOK_CLIENT_ID": "test_client_id",
                "OUTLOOK_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post = AsyncMock(side_effect=ConnectionError("invalid_grant"))
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                result = await outlook_connector.authenticate(
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
                "OUTLOOK_CLIENT_ID": "test_client_id",
                "OUTLOOK_CLIENT_SECRET": "test_secret",
            },
        ):
            with patch("httpx.AsyncClient") as mock_client:
                mock_instance = AsyncMock()
                mock_instance.post = AsyncMock(
                    return_value=mock_httpx_response(200, token_response)
                )
                mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
                mock_instance.__aexit__ = AsyncMock(return_value=False)
                mock_client.return_value = mock_instance

                token = await authenticated_connector._get_access_token()

                assert token == "new_access_token"

    @pytest.mark.asyncio
    async def test_get_access_token_no_refresh_token(self, outlook_connector):
        """Test error when no refresh token available."""
        outlook_connector._access_token = None
        outlook_connector._refresh_token = None

        with pytest.raises(ValueError, match="No valid access token"):
            await outlook_connector._get_access_token()


# =============================================================================
# API Request Tests
# =============================================================================


class TestApiRequests:
    """Tests for API request handling."""

    @pytest.mark.asyncio
    async def test_api_request_success(self, authenticated_connector, mock_httpx_response):
        """Test successful API request."""
        response_data = {"value": [{"id": "msg_1"}]}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.request = AsyncMock(return_value=mock_httpx_response(200, response_data))
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = mock_instance

            result = await authenticated_connector._api_request("/messages")

            assert result == response_data

    @pytest.mark.asyncio
    async def test_api_request_with_absolute_url(
        self, authenticated_connector, mock_httpx_response
    ):
        """Test API request with absolute URL (delta links)."""
        delta_url = "https://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=xyz"
        response_data = {"value": []}

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.request = AsyncMock(return_value=mock_httpx_response(200, response_data))
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client.return_value = mock_instance

            result = await authenticated_connector._api_request(delta_url)

            # Verify the absolute URL was used
            call_args = mock_instance.request.call_args
            assert call_args[0][1] == delta_url

    @pytest.mark.asyncio
    async def test_api_request_circuit_breaker_open(self, authenticated_connector):
        """Test API request fails when circuit breaker is open."""
        with patch.object(authenticated_connector, "check_circuit_breaker", return_value=False):
            with patch.object(
                authenticated_connector,
                "get_circuit_breaker_status",
                return_value={"cooldown_seconds": 60},
            ):
                with pytest.raises(ConnectionError, match="Circuit breaker open"):
                    await authenticated_connector._api_request("/messages")


# =============================================================================
# User Info and Folders Tests
# =============================================================================


class TestUserInfoAndFolders:
    """Tests for user info and folder operations."""

    @pytest.mark.asyncio
    async def test_get_user_info(self, authenticated_connector):
        """Test getting user profile."""
        profile_data = {
            "displayName": "Test User",
            "mail": "user@example.com",
        }

        with patch.object(authenticated_connector, "_api_request", return_value=profile_data):
            result = await authenticated_connector.get_user_info()

            assert result["displayName"] == "Test User"
            assert result["mail"] == "user@example.com"

    @pytest.mark.asyncio
    async def test_list_folders(self, authenticated_connector):
        """Test listing mail folders."""
        folders_data = {
            "value": [
                {
                    "id": "inbox_id",
                    "displayName": "Inbox",
                    "parentFolderId": None,
                    "childFolderCount": 0,
                    "unreadItemCount": 5,
                    "totalItemCount": 100,
                },
                {
                    "id": "sent_id",
                    "displayName": "Sent Items",
                    "parentFolderId": None,
                    "childFolderCount": 0,
                    "unreadItemCount": 0,
                    "totalItemCount": 50,
                },
            ]
        }

        with patch.object(authenticated_connector, "_api_request", return_value=folders_data):
            folders = await authenticated_connector.list_folders()

            assert len(folders) == 2
            assert isinstance(folders[0], OutlookFolder)
            assert folders[0].display_name == "Inbox"
            assert folders[0].unread_item_count == 5


# =============================================================================
# Message Operations Tests
# =============================================================================


class TestMessageOperations:
    """Tests for message operations."""

    @pytest.mark.asyncio
    async def test_list_messages(self, authenticated_connector):
        """Test listing message IDs."""
        response = {
            "value": [
                {"id": "msg_1"},
                {"id": "msg_2"},
                {"id": "msg_3"},
            ],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=3",
        }

        with patch.object(authenticated_connector, "_api_request", return_value=response):
            message_ids, next_link = await authenticated_connector.list_messages(
                folder_id="inbox_id",
                max_results=10,
            )

            assert len(message_ids) == 3
            assert "msg_1" in message_ids
            assert next_link is not None

    @pytest.mark.asyncio
    async def test_list_messages_with_query(self, authenticated_connector):
        """Test listing messages with OData filter."""
        response = {"value": [{"id": "msg_1"}]}

        with patch.object(
            authenticated_connector, "_api_request", return_value=response
        ) as mock_request:
            await authenticated_connector.list_messages(
                query="isRead eq false",
            )

            call_args = mock_request.call_args
            assert "$filter" in call_args.kwargs.get("params", {})

    @pytest.mark.asyncio
    async def test_list_messages_with_pagination(self, authenticated_connector):
        """Test listing messages using pagination token."""
        response = {"value": [{"id": "msg_4"}]}
        next_url = "https://graph.microsoft.com/v1.0/me/messages?$skip=3"

        with patch.object(
            authenticated_connector, "_api_request", return_value=response
        ) as mock_request:
            await authenticated_connector.list_messages(page_token=next_url)

            # Verify the next link was used directly
            call_args = mock_request.call_args
            assert call_args[0][0] == next_url

    @pytest.mark.asyncio
    async def test_get_message(self, authenticated_connector, sample_outlook_message):
        """Test getting a single message."""
        with patch.object(
            authenticated_connector, "_api_request", return_value=sample_outlook_message
        ):
            message = await authenticated_connector.get_message("msg_123")

            assert isinstance(message, EmailMessage)
            assert message.id == "msg_123"
            assert message.thread_id == "conv_456"
            assert message.subject == "Test Subject"
            assert message.from_address == "sender@example.com"
            assert "recipient@example.com" in message.to_addresses
            assert message.is_read is False

    @pytest.mark.asyncio
    async def test_get_message_without_body(self, authenticated_connector, sample_outlook_message):
        """Test getting message without body content."""
        del sample_outlook_message["body"]

        with patch.object(
            authenticated_connector, "_api_request", return_value=sample_outlook_message
        ):
            message = await authenticated_connector.get_message("msg_123", include_body=False)

            assert message.body_text == ""


class TestMessageParsing:
    """Tests for message parsing logic."""

    def test_parse_message_basic(self, outlook_connector, sample_outlook_message):
        """Test basic message parsing."""
        message = outlook_connector._parse_message(sample_outlook_message)

        assert message.id == "msg_123"
        assert message.subject == "Test Subject"
        assert message.body_text == "This is the full email body."

    def test_parse_message_html_body(self, outlook_connector):
        """Test parsing message with HTML body."""
        message_data = {
            "id": "msg_html",
            "conversationId": "conv_html",
            "subject": "HTML Email",
            "from": {"emailAddress": {"address": "sender@example.com"}},
            "toRecipients": [],
            "ccRecipients": [],
            "bccRecipients": [],
            "receivedDateTime": "2024-01-15T12:00:00Z",
            "bodyPreview": "Preview...",
            "body": {
                "contentType": "html",
                "content": "<html><body><h1>HTML Content</h1></body></html>",
            },
            "isRead": True,
            "flag": {"flagStatus": "flagged"},
            "importance": "high",
        }

        message = outlook_connector._parse_message(message_data)

        assert message.body_html == "<html><body><h1>HTML Content</h1></body></html>"
        assert message.is_starred is True  # flagged
        assert message.is_important is True  # high importance

    def test_parse_message_with_headers(self, outlook_connector, sample_outlook_message):
        """Test parsing message with internet headers."""
        message = outlook_connector._parse_message(sample_outlook_message)

        assert "message-id" in message.headers
        assert message.headers["message-id"] == "<msg123@example.com>"


# =============================================================================
# Attachments Tests
# =============================================================================


class TestAttachments:
    """Tests for attachment operations."""

    @pytest.mark.asyncio
    async def test_get_message_attachments(self, authenticated_connector):
        """Test getting message attachments."""
        attachments_data = {
            "value": [
                {
                    "id": "att_1",
                    "name": "document.pdf",
                    "contentType": "application/pdf",
                    "size": 12345,
                },
                {
                    "id": "att_2",
                    "name": "image.png",
                    "contentType": "image/png",
                    "size": 5678,
                },
            ]
        }

        with patch.object(authenticated_connector, "_api_request", return_value=attachments_data):
            attachments = await authenticated_connector.get_message_attachments("msg_123")

            assert len(attachments) == 2
            assert attachments[0].filename == "document.pdf"
            assert attachments[0].mime_type == "application/pdf"
            assert attachments[1].filename == "image.png"


# =============================================================================
# Conversation Tests
# =============================================================================


class TestConversationOperations:
    """Tests for conversation/thread operations."""

    @pytest.mark.asyncio
    async def test_get_conversation(self, authenticated_connector, sample_outlook_message):
        """Test getting a conversation thread."""
        conversation_data = {
            "value": [
                sample_outlook_message,
                {**sample_outlook_message, "id": "msg_124"},
            ]
        }

        with patch.object(authenticated_connector, "_api_request", return_value=conversation_data):
            thread = await authenticated_connector.get_conversation("conv_456")

            assert isinstance(thread, EmailThread)
            assert thread.id == "conv_456"
            assert len(thread.messages) == 2
            assert thread.message_count == 2
            assert "sender@example.com" in thread.participants


# =============================================================================
# Delta Query API Tests
# =============================================================================


class TestDeltaQueryApi:
    """Tests for Delta Query API (incremental sync)."""

    @pytest.mark.asyncio
    async def test_get_delta_new(self, authenticated_connector):
        """Test starting new delta tracking."""
        delta_data = {
            "value": [
                {"id": "msg_1", "receivedDateTime": "2024-01-15T10:00:00Z"},
            ],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=abc123",
        }

        with patch.object(authenticated_connector, "_api_request", return_value=delta_data):
            changes, next_link, delta_link = await authenticated_connector.get_delta(
                folder_id="inbox_id"
            )

            assert len(changes) == 1
            assert next_link is None
            assert delta_link is not None
            assert "$deltatoken=abc123" in delta_link

    @pytest.mark.asyncio
    async def test_get_delta_incremental(self, authenticated_connector):
        """Test continuing delta from previous link."""
        delta_data = {
            "value": [
                {"id": "msg_new"},
            ],
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=xyz789",
        }

        with patch.object(
            authenticated_connector, "_api_request", return_value=delta_data
        ) as mock_request:
            changes, _, delta_link = await authenticated_connector.get_delta(
                delta_link="https://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=abc123"
            )

            assert len(changes) == 1
            assert delta_link is not None
            # Verify the delta link was used
            call_args = mock_request.call_args
            assert "deltatoken=abc123" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_delta_with_pagination(self, authenticated_connector):
        """Test delta with multiple pages."""
        delta_data = {
            "value": [{"id": "msg_1"}],
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages/delta?$skiptoken=page2",
        }

        with patch.object(authenticated_connector, "_api_request", return_value=delta_data):
            changes, next_link, delta_link = await authenticated_connector.get_delta(
                folder_id="inbox_id"
            )

            assert len(changes) == 1
            assert next_link is not None
            assert delta_link is None  # No final delta link yet


# =============================================================================
# Search and Fetch Tests
# =============================================================================


class TestSearchAndFetch:
    """Tests for search and fetch operations."""

    @pytest.mark.asyncio
    async def test_search(self, authenticated_connector):
        """Test Outlook search."""
        search_results = {
            "value": [
                {
                    "id": "msg_1",
                    "subject": "Test Subject",
                    "from": {"emailAddress": {"address": "sender@example.com"}},
                    "bodyPreview": "Preview text",
                    "receivedDateTime": "2024-01-15T10:00:00Z",
                    "parentFolderId": "inbox_id",
                },
            ]
        }

        with patch.object(authenticated_connector, "_api_request", return_value=search_results):
            results = await authenticated_connector.search("test query", limit=10)

            assert len(results) == 1
            assert results[0].source_id == "msg_1"
            assert results[0].title == "Test Subject"

    @pytest.mark.asyncio
    async def test_fetch(self, authenticated_connector):
        """Test fetching a specific email."""
        mock_msg = EmailMessage(
            id="msg_123",
            thread_id="conv_456",
            subject="Test Subject",
            from_address="sender@example.com",
            to_addresses=["recipient@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Email body",
            snippet="Snippet",
        )

        with patch.object(authenticated_connector, "get_message", return_value=mock_msg):
            evidence = await authenticated_connector.fetch("outlook-msg_123")

            assert evidence is not None
            assert evidence.source_id == "msg_123"
            assert evidence.title == "Test Subject"

    @pytest.mark.asyncio
    async def test_fetch_without_prefix(self, authenticated_connector):
        """Test fetching without outlook- prefix."""
        mock_msg = EmailMessage(
            id="msg_123",
            thread_id="conv_456",
            subject="Test",
            from_address="sender@example.com",
            to_addresses=["recipient@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Body",
            snippet="",
        )

        with patch.object(authenticated_connector, "get_message", return_value=mock_msg):
            evidence = await authenticated_connector.fetch("msg_123")

            assert evidence is not None
            assert evidence.source_id == "msg_123"


# =============================================================================
# Send Message Tests
# =============================================================================


class TestSendMessage:
    """Tests for sending messages."""

    @pytest.mark.asyncio
    async def test_send_message_basic(self, authenticated_connector):
        """Test sending a basic email."""
        with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
            with patch.object(authenticated_connector, "_api_request") as mock_request:
                mock_request.return_value = {}

                result = await authenticated_connector.send_message(
                    to=["recipient@example.com"],
                    subject="Test Subject",
                    body="Test body",
                )

                assert result["success"] is True
                mock_request.assert_called_once()

                # Verify the request payload
                call_args = mock_request.call_args
                json_data = call_args.kwargs["json_data"]
                assert json_data["message"]["subject"] == "Test Subject"
                assert json_data["message"]["body"]["contentType"] == "text"

    @pytest.mark.asyncio
    async def test_send_message_with_cc_bcc(self, authenticated_connector):
        """Test sending email with CC and BCC."""
        with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
            with patch.object(authenticated_connector, "_api_request") as mock_request:
                mock_request.return_value = {}

                result = await authenticated_connector.send_message(
                    to=["to@example.com"],
                    subject="Test",
                    body="Body",
                    cc=["cc@example.com"],
                    bcc=["bcc@example.com"],
                )

                assert result["success"] is True
                json_data = mock_request.call_args.kwargs["json_data"]
                assert "ccRecipients" in json_data["message"]
                assert "bccRecipients" in json_data["message"]

    @pytest.mark.asyncio
    async def test_send_message_html(self, authenticated_connector):
        """Test sending email with HTML body."""
        with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
            with patch.object(authenticated_connector, "_api_request") as mock_request:
                mock_request.return_value = {}

                result = await authenticated_connector.send_message(
                    to=["to@example.com"],
                    subject="HTML Email",
                    body="Plain text fallback",
                    html_body="<html><body><h1>HTML Content</h1></body></html>",
                )

                assert result["success"] is True
                json_data = mock_request.call_args.kwargs["json_data"]
                assert json_data["message"]["body"]["contentType"] == "html"

    @pytest.mark.asyncio
    async def test_send_message_circuit_breaker_open(self, authenticated_connector):
        """Test send fails when circuit breaker is open."""
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
    async def test_reply_to_message(self, authenticated_connector):
        """Test replying to a message."""
        with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
            with patch.object(authenticated_connector, "_api_request") as mock_request:
                mock_request.return_value = {}

                result = await authenticated_connector.reply_to_message(
                    original_message_id="original_msg",
                    body="Reply body",
                )

                assert result["success"] is True
                assert result["in_reply_to"] == "original_msg"

                # Verify endpoint
                call_args = mock_request.call_args
                assert "/messages/original_msg/reply" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_reply_all(self, authenticated_connector):
        """Test reply all."""
        with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
            with patch.object(authenticated_connector, "_api_request") as mock_request:
                mock_request.return_value = {}

                result = await authenticated_connector.reply_to_message(
                    original_message_id="original_msg",
                    body="Reply body",
                    reply_all=True,
                )

                assert result["success"] is True

                # Verify endpoint uses replyAll
                call_args = mock_request.call_args
                assert "/messages/original_msg/replyAll" in call_args[0][0]


# =============================================================================
# Sync Items Tests
# =============================================================================


class TestSyncItems:
    """Tests for sync item operations."""

    @pytest.mark.asyncio
    async def test_sync_items_full_sync(self, authenticated_connector):
        """Test full sync with no cursor."""
        state = SyncState(connector_id="outlook")

        folders_data = [OutlookFolder(id="inbox_id", display_name="Inbox", total_item_count=1)]

        mock_msg = EmailMessage(
            id="msg_1",
            thread_id="conv_1",
            subject="Test",
            from_address="sender@example.com",
            to_addresses=["test@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Body",
            labels=["inbox_id"],
        )

        with patch.object(authenticated_connector, "list_folders", return_value=folders_data):
            with patch.object(
                authenticated_connector, "get_delta", return_value=([], None, "delta_link")
            ):
                with patch.object(
                    authenticated_connector, "list_messages", return_value=(["msg_1"], None)
                ):
                    with patch.object(
                        authenticated_connector, "get_message", return_value=mock_msg
                    ):
                        items = []
                        async for item in authenticated_connector.sync_items(state, batch_size=10):
                            items.append(item)

                        assert len(items) == 1
                        assert state.cursor == "delta_link"

    @pytest.mark.asyncio
    async def test_sync_items_incremental(self, authenticated_connector):
        """Test incremental sync with cursor."""
        state = SyncState(connector_id="outlook", cursor="old_delta_link")

        mock_msg = EmailMessage(
            id="new_msg",
            thread_id="new_conv",
            subject="New",
            from_address="sender@example.com",
            to_addresses=["test@example.com"],
            date=datetime.now(timezone.utc),
            body_text="New body",
            labels=["inbox_id"],
        )

        with patch.object(authenticated_connector, "get_delta") as mock_delta:
            mock_delta.return_value = (
                [{"id": "new_msg"}],
                None,
                "new_delta_link",
            )
            with patch.object(authenticated_connector, "get_message", return_value=mock_msg):
                items = []
                async for item in authenticated_connector.sync_items(state, batch_size=10):
                    items.append(item)

                assert len(items) == 1
                assert state.cursor == "new_delta_link"

    @pytest.mark.asyncio
    async def test_sync_items_handles_deleted(self, authenticated_connector):
        """Test sync handles deleted messages."""
        state = SyncState(connector_id="outlook", cursor="delta_link")

        with patch.object(authenticated_connector, "get_delta") as mock_delta:
            mock_delta.return_value = (
                [{"id": "deleted_msg", "@removed": {"reason": "deleted"}}],
                None,
                "new_delta_link",
            )

            items = []
            async for item in authenticated_connector.sync_items(state, batch_size=10):
                items.append(item)

            # Deleted messages should be skipped
            assert len(items) == 0

    def test_message_to_sync_item(self, outlook_connector):
        """Test converting EmailMessage to SyncItem."""
        msg = EmailMessage(
            id="msg_123",
            thread_id="conv_123",
            subject="Test Subject",
            from_address="sender@example.com",
            to_addresses=["recipient@example.com"],
            cc_addresses=["cc@example.com"],
            date=datetime.now(timezone.utc),
            body_text="Email body content",
            snippet="Snippet...",
            labels=["inbox_id"],
            attachments=[],
            is_read=True,
            is_starred=False,
            is_important=True,
        )

        sync_item = outlook_connector._message_to_sync_item(msg)

        assert sync_item.id == "outlook-msg_123"
        assert sync_item.source_type == "email"
        assert sync_item.title == "Test Subject"
        assert sync_item.author == "sender@example.com"
        assert "Subject: Test Subject" in sync_item.content
        assert sync_item.metadata["conversation_id"] == "conv_123"
        assert sync_item.metadata["is_important"] is True


# =============================================================================
# Model Tests
# =============================================================================


class TestOutlookModels:
    """Tests for Outlook data models."""

    def test_outlook_folder_creation(self):
        """Test OutlookFolder creation."""
        folder = OutlookFolder(
            id="inbox_id",
            display_name="Inbox",
            parent_folder_id=None,
            child_folder_count=0,
            unread_item_count=10,
            total_item_count=100,
            is_hidden=False,
        )

        assert folder.id == "inbox_id"
        assert folder.display_name == "Inbox"
        assert folder.unread_item_count == 10

    def test_outlook_sync_state_serialization(self):
        """Test OutlookSyncState serialization/deserialization."""
        state = OutlookSyncState(
            user_id="me",
            delta_link="https://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=abc",
            email_address="test@example.com",
            total_messages=1000,
            indexed_messages=500,
            folders_synced=["Inbox", "Sent Items"],
        )

        data = state.to_dict()
        restored = OutlookSyncState.from_dict(data)

        assert restored.user_id == state.user_id
        assert restored.delta_link == state.delta_link
        assert restored.total_messages == 1000
        assert "Inbox" in restored.folders_synced


# =============================================================================
# Scope Constants Tests
# =============================================================================


class TestScopeConstants:
    """Tests for Outlook scope constants."""

    def test_readonly_scopes(self):
        """Test readonly scopes."""
        scope_str = " ".join(OUTLOOK_SCOPES_READONLY)
        assert "Mail.Read" in scope_str
        assert "User.Read" in scope_str
        assert "Mail.Send" not in scope_str

    def test_full_scopes(self):
        """Test full scopes include send and readwrite."""
        scope_str = " ".join(OUTLOOK_SCOPES_FULL)
        assert "Mail.Read" in scope_str
        assert "Mail.ReadWrite" in scope_str
        assert "Mail.Send" in scope_str

    def test_default_scopes(self):
        """Test default scopes are readonly."""
        assert OUTLOOK_SCOPES == OUTLOOK_SCOPES_READONLY


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_fetch_error_returns_none(self, authenticated_connector):
        """Test fetch returns None on error."""
        with patch.object(
            authenticated_connector, "get_message", side_effect=ConnectionError("API Error")
        ):
            result = await authenticated_connector.fetch("msg_123")
            assert result is None

    @pytest.mark.asyncio
    async def test_send_message_api_error(self, authenticated_connector):
        """Test send message raises on API error."""
        with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
            with patch.object(
                authenticated_connector, "_api_request", side_effect=ConnectionError("Send failed")
            ):
                with pytest.raises(RuntimeError, match="Failed to send email"):
                    await authenticated_connector.send_message(
                        to=["to@example.com"],
                        subject="Test",
                        body="Body",
                    )

    @pytest.mark.asyncio
    async def test_reply_api_error(self, authenticated_connector):
        """Test reply raises on API error."""
        with patch.object(authenticated_connector, "check_circuit_breaker", return_value=True):
            with patch.object(
                authenticated_connector, "_api_request", side_effect=ConnectionError("Reply failed")
            ):
                with pytest.raises(RuntimeError, match="Failed to send reply"):
                    await authenticated_connector.reply_to_message(
                        original_message_id="msg_123",
                        body="Reply",
                    )
