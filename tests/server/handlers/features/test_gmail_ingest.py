"""Tests for Gmail Ingest Handler."""

import sys
import types as _types_mod

# Pre-stub Slack modules to prevent import chain failures
_SLACK_ATTRS = [
    "SlackHandler",
    "get_slack_handler",
    "get_slack_integration",
    "get_workspace_store",
    "resolve_workspace",
    "create_tracked_task",
    "_validate_slack_url",
    "SLACK_SIGNING_SECRET",
    "SLACK_BOT_TOKEN",
    "SLACK_WEBHOOK_URL",
    "SLACK_ALLOWED_DOMAINS",
    "SignatureVerifierMixin",
    "CommandsMixin",
    "EventsMixin",
    "init_slack_handler",
]
for _mod_name in (
    "aragora.server.handlers.social.slack.handler",
    "aragora.server.handlers.social.slack",
    "aragora.server.handlers.social._slack_impl",
):
    if _mod_name not in sys.modules:
        _m = _types_mod.ModuleType(_mod_name)
        for _a in _SLACK_ATTRS:
            setattr(_m, _a, None)
        sys.modules[_mod_name] = _m

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.server.handlers.features.gmail_ingest import (
    GmailIngestHandler,
)


@pytest.fixture
def handler():
    """Create handler instance."""
    return GmailIngestHandler({})


class TestGmailIngestHandler:
    """Tests for GmailIngestHandler class."""

    def test_handler_creation(self, handler):
        """Test creating handler instance."""
        assert handler is not None

    def test_handler_routes(self):
        """Test that handler has route definitions."""
        assert hasattr(GmailIngestHandler, "ROUTES")
        routes = GmailIngestHandler.ROUTES
        assert "/api/v1/gmail/connect" in routes
        assert "/api/v1/gmail/auth/url" in routes
        assert "/api/v1/gmail/auth/callback" in routes
        assert "/api/v1/gmail/sync" in routes
        assert "/api/v1/gmail/sync/status" in routes
        assert "/api/v1/gmail/messages" in routes
        assert "/api/v1/gmail/search" in routes
        assert "/api/v1/gmail/disconnect" in routes
        assert "/api/v1/gmail/status" in routes

    def test_can_handle_method(self, handler):
        """Test can_handle method for valid routes."""
        # Base routes
        assert handler.can_handle("/api/v1/gmail/connect") is True
        assert handler.can_handle("/api/v1/gmail/auth/url") is True
        assert handler.can_handle("/api/v1/gmail/auth/callback") is True
        assert handler.can_handle("/api/v1/gmail/sync") is True
        assert handler.can_handle("/api/v1/gmail/sync/status") is True
        assert handler.can_handle("/api/v1/gmail/messages") is True
        assert handler.can_handle("/api/v1/gmail/search") is True
        assert handler.can_handle("/api/v1/gmail/disconnect") is True
        assert handler.can_handle("/api/v1/gmail/status") is True

        # Prefixed routes
        assert handler.can_handle("/api/v1/gmail/message/msg123") is True

        # Invalid routes
        assert handler.can_handle("/api/v1/invalid/route") is False
        assert handler.can_handle("/api/v1/outlook/messages") is False

    def test_handler_has_handle_method(self, handler):
        """Test that handler has handle method."""
        assert hasattr(handler, "handle")
        assert callable(handler.handle)

    def test_handler_has_handle_post_method(self, handler):
        """Test that handler has handle_post method."""
        assert hasattr(handler, "handle_post")
        assert callable(handler.handle_post)

    def test_resource_type(self):
        """Test resource type for audit logging."""
        assert GmailIngestHandler.RESOURCE_TYPE == "gmail"


class TestGmailIngestAuthentication:
    """Tests for Gmail authentication flows."""

    def test_get_authenticated_user_no_auth(self):
        """Test _get_authenticated_user with no authentication."""
        handler = GmailIngestHandler({})
        mock_request = MagicMock()

        with patch(
            "aragora.server.handlers.features.gmail_ingest.extract_user_from_request"
        ) as mock_extract:
            mock_ctx = MagicMock()
            mock_ctx.authenticated = False
            mock_ctx.user_id = None
            mock_extract.return_value = mock_ctx

            user_id, org_id, error = handler._get_authenticated_user(mock_request)
            assert user_id is None
            assert org_id is None
            assert error is not None
            assert error.status_code == 401

    def test_get_authenticated_user_with_auth(self):
        """Test _get_authenticated_user with valid authentication."""
        handler = GmailIngestHandler({})
        mock_request = MagicMock()

        with patch(
            "aragora.server.handlers.features.gmail_ingest.extract_user_from_request"
        ) as mock_extract:
            mock_ctx = MagicMock()
            mock_ctx.authenticated = True
            mock_ctx.user_id = "user123"
            mock_ctx.org_id = "org456"
            mock_extract.return_value = mock_ctx

            user_id, org_id, error = handler._get_authenticated_user(mock_request)
            assert user_id == "user123"
            assert org_id == "org456"
            assert error is None

    def test_is_configured_no_env_vars(self):
        """Test _is_configured returns False when no env vars set."""
        handler = GmailIngestHandler({})
        with patch.dict("os.environ", {}, clear=True):
            assert handler._is_configured() is False

    def test_is_configured_with_gmail_client_id(self):
        """Test _is_configured returns True with GMAIL_CLIENT_ID."""
        handler = GmailIngestHandler({})
        with patch.dict("os.environ", {"GMAIL_CLIENT_ID": "test_id"}):
            assert handler._is_configured() is True

    def test_is_configured_with_google_client_id(self):
        """Test _is_configured returns True with GOOGLE_CLIENT_ID."""
        handler = GmailIngestHandler({})
        with patch.dict("os.environ", {"GOOGLE_CLIENT_ID": "test_id"}):
            assert handler._is_configured() is True


class TestGmailIngestStatus:
    """Tests for Gmail status endpoint."""

    @pytest.mark.asyncio
    async def test_get_status_not_connected(self):
        """Test status when user is not connected."""
        handler = GmailIngestHandler({})

        with patch(
            "aragora.server.handlers.features.gmail_ingest.get_user_state",
            new_callable=AsyncMock,
        ) as mock_get_state:
            mock_get_state.return_value = None
            result = await handler._get_status("user123")

            assert result.status_code == 200
            import json

            body = json.loads(result.body)
            assert body["connected"] is False

    @pytest.mark.asyncio
    async def test_get_status_connected(self):
        """Test status when user is connected."""
        handler = GmailIngestHandler({})

        mock_state = MagicMock()
        mock_state.refresh_token = "test_refresh_token"
        mock_state.email_address = "test@example.com"
        mock_state.indexed_count = 100
        mock_state.last_sync = None

        with patch(
            "aragora.server.handlers.features.gmail_ingest.get_user_state",
            new_callable=AsyncMock,
        ) as mock_get_state:
            mock_get_state.return_value = mock_state
            result = await handler._get_status("user123")

            assert result.status_code == 200
            import json

            body = json.loads(result.body)
            assert body["connected"] is True
            assert body["email_address"] == "test@example.com"
            assert body["indexed_count"] == 100


class TestGmailIngestOAuth:
    """Tests for Gmail OAuth flows."""

    def test_get_auth_url(self):
        """Test _get_auth_url generates OAuth URL."""
        handler = GmailIngestHandler({})

        with patch(
            "aragora.server.handlers.features.gmail_ingest.GmailConnector",
            create=True,
        ) as MockConnector:
            mock_instance = MagicMock()
            mock_instance.get_oauth_url.return_value = "https://oauth.google.com/auth"
            MockConnector.return_value = mock_instance

            result = handler._get_auth_url({"redirect_uri": "http://localhost:3000/callback"})
            assert result.status_code == 200
            import json

            body = json.loads(result.body)
            assert "url" in body

    def test_start_connect(self):
        """Test _start_connect starts OAuth flow."""
        handler = GmailIngestHandler({})

        with patch(
            "aragora.server.handlers.features.gmail_ingest.GmailConnector",
            create=True,
        ) as MockConnector:
            mock_instance = MagicMock()
            mock_instance.get_oauth_url.return_value = "https://oauth.google.com/auth"
            MockConnector.return_value = mock_instance

            result = handler._start_connect(
                {"redirect_uri": "http://localhost:3000/callback"}, "user123"
            )
            assert result.status_code == 200
            import json

            body = json.loads(result.body)
            assert "url" in body
            assert "state" in body


class TestGmailIngestSync:
    """Tests for Gmail sync operations."""

    @pytest.mark.asyncio
    async def test_start_sync_not_connected(self):
        """Test sync fails when user is not connected."""
        handler = GmailIngestHandler({})

        with patch(
            "aragora.server.handlers.features.gmail_ingest.get_user_state",
            new_callable=AsyncMock,
        ) as mock_get_state:
            mock_get_state.return_value = None
            result = await handler._start_sync({}, "user123")
            assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_get_sync_status(self):
        """Test getting sync status."""
        handler = GmailIngestHandler({})

        mock_state = MagicMock()
        mock_state.refresh_token = "test_token"
        mock_state.email_address = "test@example.com"
        mock_state.indexed_count = 50
        mock_state.last_sync = None

        mock_job = MagicMock()
        mock_job.status = "running"
        mock_job.progress = 50
        mock_job.messages_synced = 25
        mock_job.error = None

        with (
            patch(
                "aragora.server.handlers.features.gmail_ingest.get_user_state",
                new_callable=AsyncMock,
            ) as mock_get_state,
            patch(
                "aragora.server.handlers.features.gmail_ingest.get_sync_job",
                new_callable=AsyncMock,
            ) as mock_get_job,
        ):
            mock_get_state.return_value = mock_state
            mock_get_job.return_value = mock_job

            result = await handler._get_sync_status("user123")
            assert result.status_code == 200
            import json

            body = json.loads(result.body)
            assert body["connected"] is True
            assert body["job_status"] == "running"
            assert body["job_progress"] == 50


class TestGmailIngestMessages:
    """Tests for Gmail message operations."""

    @pytest.mark.asyncio
    async def test_list_messages_not_connected(self):
        """Test listing messages fails when not connected."""
        handler = GmailIngestHandler({})

        with patch(
            "aragora.server.handlers.features.gmail_ingest.get_user_state",
            new_callable=AsyncMock,
        ) as mock_get_state:
            mock_get_state.return_value = None
            result = await handler._list_messages("user123", {})
            assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_search_requires_query(self):
        """Test search requires query parameter."""
        handler = GmailIngestHandler({})

        mock_state = MagicMock()
        mock_state.refresh_token = "test_token"

        with patch(
            "aragora.server.handlers.features.gmail_ingest.get_user_state",
            new_callable=AsyncMock,
        ) as mock_get_state:
            mock_get_state.return_value = mock_state
            result = await handler._search("user123", {"query": ""})
            assert result.status_code == 400


class TestGmailIngestDisconnect:
    """Tests for Gmail disconnect operations."""

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test disconnecting Gmail account."""
        handler = GmailIngestHandler({})

        with (
            patch(
                "aragora.server.handlers.features.gmail_ingest.delete_user_state",
                new_callable=AsyncMock,
            ) as mock_delete_state,
            patch(
                "aragora.server.handlers.features.gmail_ingest.delete_sync_job",
                new_callable=AsyncMock,
            ) as mock_delete_job,
        ):
            mock_delete_state.return_value = True
            mock_delete_job.return_value = True

            result = await handler._disconnect("user123")
            assert result.status_code == 200
            import json

            body = json.loads(result.body)
            assert body["success"] is True
            assert body["was_connected"] is True
