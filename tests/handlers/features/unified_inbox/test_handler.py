"""Tests for the Unified Inbox handler.

Covers all routes and behavior of the UnifiedInboxHandler class:
- can_handle() routing
- GET  /api/v1/inbox/oauth/gmail     - Gmail OAuth URL generation
- GET  /api/v1/inbox/oauth/outlook   - Outlook OAuth URL generation
- POST /api/v1/inbox/connect         - Connect account (Gmail / Outlook)
- GET  /api/v1/inbox/accounts        - List connected accounts
- DELETE /api/v1/inbox/accounts/{id} - Disconnect account
- GET  /api/v1/inbox/messages        - List messages with filters
- GET  /api/v1/inbox/messages/{id}   - Get single message
- POST /api/v1/inbox/triage          - Multi-agent triage
- POST /api/v1/inbox/bulk-action     - Bulk actions on messages
- GET  /api/v1/inbox/stats           - Inbox health statistics
- GET  /api/v1/inbox/trends          - Priority trends
- Error handling (missing params, invalid input, not found, 404 route)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("body", result)
    # HandlerResult supports tuple-style indexing: [0] = decoded body
    try:
        body = result[0]
        if isinstance(body, dict):
            return body
        return json.loads(body)
    except Exception:
        return json.loads(result.body)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    try:
        return result[1]
    except Exception:
        return result.status_code


# ---------------------------------------------------------------------------
# Mock Request
# ---------------------------------------------------------------------------


@dataclass
class MockRequest:
    """Mock async HTTP request for UnifiedInboxHandler."""

    method: str = "GET"
    path: str = "/"
    query: dict[str, str] = field(default_factory=dict)
    _body: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    content_length: int | None = None

    async def json(self) -> dict[str, Any]:
        return self._body or {}

    async def body(self) -> bytes:
        return json.dumps(self._body or {}).encode()

    async def read(self) -> bytes:
        return json.dumps(self._body or {}).encode()


def _req(
    method: str = "GET",
    path: str = "/api/v1/inbox/accounts",
    query: dict | None = None,
    body: dict | None = None,
) -> MockRequest:
    """Shortcut to create a MockRequest."""
    return MockRequest(method=method, path=path, query=query or {}, _body=body or {})


# ---------------------------------------------------------------------------
# Sample store records
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 2, 23, 12, 0, 0, tzinfo=timezone.utc)


def _account_record(
    account_id: str = "acct-1",
    provider: str = "gmail",
    email: str = "user@gmail.com",
    status: str = "connected",
) -> dict[str, Any]:
    return {
        "id": account_id,
        "provider": provider,
        "email_address": email,
        "display_name": email.split("@")[0],
        "status": status,
        "connected_at": _NOW,
        "last_sync": _NOW,
        "total_messages": 10,
        "unread_count": 3,
        "sync_errors": 0,
        "metadata": {},
    }


def _message_record(
    message_id: str = "msg-1",
    account_id: str = "acct-1",
    provider: str = "gmail",
    subject: str = "Test Subject",
    priority_tier: str = "medium",
    is_read: bool = False,
) -> dict[str, Any]:
    return {
        "id": message_id,
        "account_id": account_id,
        "provider": provider,
        "external_id": "ext-123",
        "subject": subject,
        "sender_email": "sender@example.com",
        "sender_name": "Sender Name",
        "recipients": ["user@gmail.com"],
        "cc": [],
        "received_at": _NOW,
        "snippet": "Preview of the message...",
        "body_preview": "Full preview of the message body...",
        "is_read": is_read,
        "is_starred": False,
        "has_attachments": False,
        "labels": ["inbox"],
        "thread_id": None,
        "priority_score": 0.5,
        "priority_tier": priority_tier,
        "priority_reasons": [],
        "triage_action": None,
        "triage_rationale": None,
    }


def _triage_record(
    message_id: str = "msg-1",
    action: str = "defer",
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "recommended_action": action,
        "confidence": 0.85,
        "rationale": "Based on priority tier analysis",
        "suggested_response": None,
        "delegate_to": None,
        "schedule_for": None,
        "agents_involved": ["support_analyst", "product_expert"],
        "debate_summary": "Multi-agent analysis completed",
        "created_at": _NOW,
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_store():
    """Create a fully-mocked inbox store."""
    store = AsyncMock()
    # Accounts
    store.save_account = AsyncMock(return_value=None)
    store.get_account = AsyncMock(return_value=None)
    store.list_accounts = AsyncMock(return_value=[])
    store.delete_account = AsyncMock(return_value=True)
    store.update_account_fields = AsyncMock(return_value=None)
    store.increment_account_counts = AsyncMock(return_value=None)
    # Messages
    store.save_message = AsyncMock(return_value=("msg-1", True))
    store.get_message = AsyncMock(return_value=None)
    store.list_messages = AsyncMock(return_value=([], 0))
    store.delete_message = AsyncMock(return_value=True)
    store.update_message_flags = AsyncMock(return_value=True)
    store.update_message_triage = AsyncMock(return_value=None)
    # Triage
    store.save_triage_result = AsyncMock(return_value=None)
    store.get_triage_result = AsyncMock(return_value=None)
    return store


@pytest.fixture
def handler(mock_store):
    """Create a UnifiedInboxHandler with mocked store."""
    with patch(
        "aragora.server.handlers.features.unified_inbox.handler.get_canonical_gateway_stores"
    ) as mock_gw:
        mock_gw_instance = MagicMock()
        mock_gw_instance.inbox_store.return_value = mock_store
        mock_gw.return_value = mock_gw_instance

        from aragora.server.handlers.features.unified_inbox.handler import (
            UnifiedInboxHandler,
        )

        h = UnifiedInboxHandler({})
        # Ensure the handler uses our mock store
        h._store = mock_store
        return h


# ---------------------------------------------------------------------------
# can_handle Tests
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for can_handle routing."""

    def test_handles_inbox_accounts(self, handler):
        assert handler.can_handle("/api/v1/inbox/accounts") is True

    def test_handles_inbox_messages(self, handler):
        assert handler.can_handle("/api/v1/inbox/messages") is True

    def test_handles_inbox_connect(self, handler):
        assert handler.can_handle("/api/v1/inbox/connect") is True

    def test_handles_inbox_triage(self, handler):
        assert handler.can_handle("/api/v1/inbox/triage") is True

    def test_handles_inbox_stats(self, handler):
        assert handler.can_handle("/api/v1/inbox/stats") is True

    def test_handles_inbox_trends(self, handler):
        assert handler.can_handle("/api/v1/inbox/trends") is True

    def test_handles_inbox_oauth_gmail(self, handler):
        assert handler.can_handle("/api/v1/inbox/oauth/gmail") is True

    def test_handles_inbox_oauth_outlook(self, handler):
        assert handler.can_handle("/api/v1/inbox/oauth/outlook") is True

    def test_handles_inbox_bulk_action(self, handler):
        assert handler.can_handle("/api/v1/inbox/bulk-action") is True

    def test_handles_inbox_account_by_id(self, handler):
        assert handler.can_handle("/api/v1/inbox/accounts/acct-1") is True

    def test_handles_inbox_message_by_id(self, handler):
        assert handler.can_handle("/api/v1/inbox/messages/msg-1") is True

    def test_does_not_handle_unrelated_path(self, handler):
        assert handler.can_handle("/api/v1/debates") is False

    def test_does_not_handle_health(self, handler):
        assert handler.can_handle("/api/v1/health") is False


# ---------------------------------------------------------------------------
# ROUTES definition
# ---------------------------------------------------------------------------


class TestRoutes:
    """Tests for the ROUTES class attribute."""

    def test_routes_is_not_empty(self, handler):
        assert len(handler.ROUTES) > 0

    def test_routes_contain_key_paths(self, handler):
        expected = [
            "/api/v1/inbox/oauth/gmail",
            "/api/v1/inbox/oauth/outlook",
            "/api/v1/inbox/connect",
            "/api/v1/inbox/accounts",
            "/api/v1/inbox/messages",
            "/api/v1/inbox/triage",
            "/api/v1/inbox/bulk-action",
            "/api/v1/inbox/stats",
            "/api/v1/inbox/trends",
        ]
        for path in expected:
            assert path in handler.ROUTES, f"Missing route: {path}"


# ---------------------------------------------------------------------------
# GET /api/v1/inbox/oauth/gmail
# ---------------------------------------------------------------------------


class TestGmailOAuthUrl:
    """Tests for GET /api/v1/inbox/oauth/gmail."""

    @pytest.mark.asyncio
    async def test_gmail_oauth_url_success(self, handler):
        mock_result = {
            "success": True,
            "data": {
                "auth_url": "https://accounts.google.com/o/oauth2/auth?...",
                "provider": "gmail",
                "state": "some-state",
            },
        }
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.handle_gmail_oauth_url",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            req = _req(
                path="/api/v1/inbox/oauth/gmail",
                query={"redirect_uri": "http://localhost/callback"},
            )
            result = await handler.handle_request(req, "/api/v1/inbox/oauth/gmail", "GET")
            assert _status(result) == 200
            body = _body(result)
            assert body["success"] is True
            assert "auth_url" in body["data"]

    @pytest.mark.asyncio
    async def test_gmail_oauth_url_missing_redirect_uri(self, handler):
        mock_result = {
            "success": False,
            "error": "Missing redirect_uri parameter",
            "status_code": 400,
        }
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.handle_gmail_oauth_url",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            req = _req(path="/api/v1/inbox/oauth/gmail", query={})
            result = await handler.handle_request(req, "/api/v1/inbox/oauth/gmail", "GET")
            assert _status(result) == 400
            body = _body(result)
            assert "error" in body

    @pytest.mark.asyncio
    async def test_gmail_oauth_url_exception(self, handler):
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.handle_gmail_oauth_url",
            new_callable=AsyncMock,
            side_effect=ConnectionError("connection refused"),
        ):
            req = _req(
                path="/api/v1/inbox/oauth/gmail",
                query={"redirect_uri": "http://localhost/callback"},
            )
            result = await handler.handle_request(req, "/api/v1/inbox/oauth/gmail", "GET")
            assert _status(result) == 500


# ---------------------------------------------------------------------------
# GET /api/v1/inbox/oauth/outlook
# ---------------------------------------------------------------------------


class TestOutlookOAuthUrl:
    """Tests for GET /api/v1/inbox/oauth/outlook."""

    @pytest.mark.asyncio
    async def test_outlook_oauth_url_success(self, handler):
        mock_result = {
            "success": True,
            "data": {
                "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?...",
                "provider": "outlook",
                "state": "some-state",
            },
        }
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.handle_outlook_oauth_url",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            req = _req(
                path="/api/v1/inbox/oauth/outlook",
                query={"redirect_uri": "http://localhost/callback"},
            )
            result = await handler.handle_request(req, "/api/v1/inbox/oauth/outlook", "GET")
            assert _status(result) == 200
            body = _body(result)
            assert body["success"] is True
            assert body["data"]["provider"] == "outlook"

    @pytest.mark.asyncio
    async def test_outlook_oauth_url_missing_redirect_uri(self, handler):
        mock_result = {
            "success": False,
            "error": "Missing redirect_uri parameter",
            "status_code": 400,
        }
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.handle_outlook_oauth_url",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            req = _req(path="/api/v1/inbox/oauth/outlook", query={})
            result = await handler.handle_request(req, "/api/v1/inbox/oauth/outlook", "GET")
            assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_outlook_oauth_url_exception(self, handler):
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.handle_outlook_oauth_url",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timeout"),
        ):
            req = _req(
                path="/api/v1/inbox/oauth/outlook",
                query={"redirect_uri": "http://localhost/callback"},
            )
            result = await handler.handle_request(req, "/api/v1/inbox/oauth/outlook", "GET")
            assert _status(result) == 500


# ---------------------------------------------------------------------------
# POST /api/v1/inbox/connect
# ---------------------------------------------------------------------------


class TestConnect:
    """Tests for POST /api/v1/inbox/connect."""

    @pytest.mark.asyncio
    async def test_connect_gmail_success(self, handler, mock_store):
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.connect_gmail",
            new_callable=AsyncMock,
            return_value={"success": True},
        ):
            req = _req(
                method="POST",
                path="/api/v1/inbox/connect",
                body={
                    "provider": "gmail",
                    "auth_code": "auth-code-123",
                    "redirect_uri": "http://localhost/callback",
                },
            )
            result = await handler.handle_request(req, "/api/v1/inbox/connect", "POST")
            assert _status(result) == 200
            body = _body(result)
            assert body["success"] is True
            assert "account" in body["data"]
            mock_store.save_account.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_outlook_success(self, handler, mock_store):
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.connect_outlook",
            new_callable=AsyncMock,
            return_value={"success": True},
        ):
            req = _req(
                method="POST",
                path="/api/v1/inbox/connect",
                body={
                    "provider": "outlook",
                    "auth_code": "auth-code-456",
                    "redirect_uri": "http://localhost/callback",
                },
            )
            result = await handler.handle_request(req, "/api/v1/inbox/connect", "POST")
            assert _status(result) == 200
            body = _body(result)
            assert body["success"] is True
            mock_store.save_account.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_invalid_provider(self, handler, mock_store):
        req = _req(
            method="POST",
            path="/api/v1/inbox/connect",
            body={
                "provider": "yahoo",
                "auth_code": "auth-code-789",
            },
        )
        result = await handler.handle_request(req, "/api/v1/inbox/connect", "POST")
        assert _status(result) == 400
        body = _body(result)
        assert "Invalid provider" in body.get("error", "")
        mock_store.save_account.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_connect_missing_auth_code(self, handler, mock_store):
        req = _req(
            method="POST",
            path="/api/v1/inbox/connect",
            body={"provider": "gmail"},
        )
        result = await handler.handle_request(req, "/api/v1/inbox/connect", "POST")
        assert _status(result) == 400
        body = _body(result)
        assert "auth_code" in body.get("error", "").lower()
        mock_store.save_account.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_connect_empty_provider(self, handler, mock_store):
        req = _req(
            method="POST",
            path="/api/v1/inbox/connect",
            body={"provider": "", "auth_code": "code-123"},
        )
        result = await handler.handle_request(req, "/api/v1/inbox/connect", "POST")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_connect_gmail_failure(self, handler, mock_store):
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.connect_gmail",
            new_callable=AsyncMock,
            return_value={"success": False, "error": "Gmail authentication failed"},
        ):
            req = _req(
                method="POST",
                path="/api/v1/inbox/connect",
                body={
                    "provider": "gmail",
                    "auth_code": "bad-code",
                    "redirect_uri": "http://localhost/callback",
                },
            )
            result = await handler.handle_request(req, "/api/v1/inbox/connect", "POST")
            assert _status(result) == 400
            body = _body(result)
            assert "error" in body
            mock_store.save_account.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_connect_exception_returns_500(self, handler, mock_store):
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.connect_gmail",
            new_callable=AsyncMock,
            side_effect=ConnectionError("network error"),
        ):
            req = _req(
                method="POST",
                path="/api/v1/inbox/connect",
                body={
                    "provider": "gmail",
                    "auth_code": "auth-code-123",
                },
            )
            result = await handler.handle_request(req, "/api/v1/inbox/connect", "POST")
            assert _status(result) == 500


# ---------------------------------------------------------------------------
# GET /api/v1/inbox/accounts
# ---------------------------------------------------------------------------


class TestListAccounts:
    """Tests for GET /api/v1/inbox/accounts."""

    @pytest.mark.asyncio
    async def test_list_accounts_empty(self, handler, mock_store):
        mock_store.list_accounts.return_value = []
        req = _req(path="/api/v1/inbox/accounts")
        result = await handler.handle_request(req, "/api/v1/inbox/accounts", "GET")
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["data"]["accounts"] == []
        assert body["data"]["total"] == 0

    @pytest.mark.asyncio
    async def test_list_accounts_with_results(self, handler, mock_store):
        mock_store.list_accounts.return_value = [
            _account_record("acct-1", "gmail", "user1@gmail.com"),
            _account_record("acct-2", "outlook", "user2@outlook.com"),
        ]
        req = _req(path="/api/v1/inbox/accounts")
        result = await handler.handle_request(req, "/api/v1/inbox/accounts", "GET")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["total"] == 2
        accounts = body["data"]["accounts"]
        assert len(accounts) == 2
        assert accounts[0]["provider"] == "gmail"
        assert accounts[1]["provider"] == "outlook"


# ---------------------------------------------------------------------------
# DELETE /api/v1/inbox/accounts/{id}
# ---------------------------------------------------------------------------


class TestDisconnectAccount:
    """Tests for DELETE /api/v1/inbox/accounts/{id}."""

    @pytest.mark.asyncio
    async def test_disconnect_success(self, handler, mock_store):
        mock_store.get_account.return_value = _account_record("acct-1")
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.disconnect_account",
            new_callable=AsyncMock,
        ):
            req = _req(method="DELETE", path="/api/v1/inbox/accounts/acct-1")
            result = await handler.handle_request(req, "/api/v1/inbox/accounts/acct-1", "DELETE")
            assert _status(result) == 200
            body = _body(result)
            assert body["success"] is True
            assert body["data"]["account_id"] == "acct-1"
            mock_store.delete_account.assert_awaited_once_with("default", "acct-1")

    @pytest.mark.asyncio
    async def test_disconnect_not_found(self, handler, mock_store):
        mock_store.get_account.return_value = None
        req = _req(method="DELETE", path="/api/v1/inbox/accounts/nonexistent")
        result = await handler.handle_request(req, "/api/v1/inbox/accounts/nonexistent", "DELETE")
        assert _status(result) == 404
        body = _body(result)
        assert "not found" in body.get("error", "").lower()


# ---------------------------------------------------------------------------
# GET /api/v1/inbox/messages
# ---------------------------------------------------------------------------


class TestListMessages:
    """Tests for GET /api/v1/inbox/messages."""

    @pytest.mark.asyncio
    async def test_list_messages_empty(self, handler, mock_store):
        mock_store.list_messages.return_value = ([], 0)
        req = _req(path="/api/v1/inbox/messages")
        result = await handler.handle_request(req, "/api/v1/inbox/messages", "GET")
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        data = body["data"]
        assert data["messages"] == []
        assert data["total"] == 0
        assert data["limit"] == 50
        assert data["offset"] == 0
        assert data["has_more"] is False

    @pytest.mark.asyncio
    async def test_list_messages_with_results(self, handler, mock_store):
        records = [
            _message_record("msg-1", subject="First"),
            _message_record("msg-2", subject="Second"),
        ]
        mock_store.list_messages.return_value = (records, 2)
        req = _req(path="/api/v1/inbox/messages")
        result = await handler.handle_request(req, "/api/v1/inbox/messages", "GET")
        assert _status(result) == 200
        body = _body(result)
        data = body["data"]
        assert data["total"] == 2
        assert len(data["messages"]) == 2
        assert data["messages"][0]["subject"] == "First"
        assert data["messages"][1]["subject"] == "Second"

    @pytest.mark.asyncio
    async def test_list_messages_pagination(self, handler, mock_store):
        records = [_message_record("msg-3")]
        mock_store.list_messages.return_value = (records, 25)
        req = _req(
            path="/api/v1/inbox/messages",
            query={"limit": "10", "offset": "10"},
        )
        result = await handler.handle_request(req, "/api/v1/inbox/messages", "GET")
        assert _status(result) == 200
        body = _body(result)
        data = body["data"]
        assert data["limit"] == 10
        assert data["offset"] == 10
        assert data["has_more"] is True
        mock_store.list_messages.assert_awaited_once_with(
            tenant_id="default",
            limit=10,
            offset=10,
            priority_tier=None,
            account_id=None,
            unread_only=False,
            search=None,
        )

    @pytest.mark.asyncio
    async def test_list_messages_with_filters(self, handler, mock_store):
        mock_store.list_messages.return_value = ([], 0)
        req = _req(
            path="/api/v1/inbox/messages",
            query={
                "priority": "high",
                "account_id": "acct-1",
                "unread_only": "true",
                "search": "budget",
            },
        )
        result = await handler.handle_request(req, "/api/v1/inbox/messages", "GET")
        assert _status(result) == 200
        mock_store.list_messages.assert_awaited_once_with(
            tenant_id="default",
            limit=50,
            offset=0,
            priority_tier="high",
            account_id="acct-1",
            unread_only=True,
            search="budget",
        )

    @pytest.mark.asyncio
    async def test_list_messages_invalid_limit_defaults(self, handler, mock_store):
        mock_store.list_messages.return_value = ([], 0)
        req = _req(
            path="/api/v1/inbox/messages",
            query={"limit": "not_a_number", "offset": "bad"},
        )
        result = await handler.handle_request(req, "/api/v1/inbox/messages", "GET")
        assert _status(result) == 200
        # Should fall back to defaults
        mock_store.list_messages.assert_awaited_once_with(
            tenant_id="default",
            limit=50,
            offset=0,
            priority_tier=None,
            account_id=None,
            unread_only=False,
            search=None,
        )

    @pytest.mark.asyncio
    async def test_list_messages_has_more_false_at_end(self, handler, mock_store):
        records = [_message_record("msg-1")]
        mock_store.list_messages.return_value = (records, 5)
        req = _req(
            path="/api/v1/inbox/messages",
            query={"limit": "10", "offset": "0"},
        )
        result = await handler.handle_request(req, "/api/v1/inbox/messages", "GET")
        body = _body(result)
        # offset(0) + limit(10) = 10 >= total(5) -> has_more is False
        assert body["data"]["has_more"] is False


# ---------------------------------------------------------------------------
# GET /api/v1/inbox/messages/{id}
# ---------------------------------------------------------------------------


class TestGetMessage:
    """Tests for GET /api/v1/inbox/messages/{id}."""

    @pytest.mark.asyncio
    async def test_get_message_success(self, handler, mock_store):
        mock_store.get_message.return_value = _message_record("msg-1")
        mock_store.get_triage_result.return_value = None
        req = _req(path="/api/v1/inbox/messages/msg-1")
        result = await handler.handle_request(req, "/api/v1/inbox/messages/msg-1", "GET")
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["data"]["message"]["id"] == "msg-1"
        assert body["data"]["triage"] is None

    @pytest.mark.asyncio
    async def test_get_message_with_triage(self, handler, mock_store):
        mock_store.get_message.return_value = _message_record("msg-1")
        mock_store.get_triage_result.return_value = _triage_record("msg-1")
        req = _req(path="/api/v1/inbox/messages/msg-1")
        result = await handler.handle_request(req, "/api/v1/inbox/messages/msg-1", "GET")
        assert _status(result) == 200
        body = _body(result)
        assert body["data"]["triage"] is not None
        assert body["data"]["triage"]["message_id"] == "msg-1"

    @pytest.mark.asyncio
    async def test_get_message_not_found(self, handler, mock_store):
        mock_store.get_message.return_value = None
        req = _req(path="/api/v1/inbox/messages/nonexistent")
        result = await handler.handle_request(req, "/api/v1/inbox/messages/nonexistent", "GET")
        assert _status(result) == 404
        body = _body(result)
        assert "not found" in body.get("error", "").lower()


# ---------------------------------------------------------------------------
# POST /api/v1/inbox/messages/{id}/debate
# ---------------------------------------------------------------------------


class TestAutoDebate:
    """Tests for POST /api/v1/inbox/messages/{id}/debate."""

    @pytest.mark.asyncio
    async def test_auto_debate_success(self, handler, mock_store):
        mock_store.get_message.return_value = _message_record("msg-1")
        debate_result = {
            "debate_id": "debate-1",
            "final_answer": "Archive this low-priority message.",
            "consensus_reached": True,
            "confidence": 0.82,
            "latency_seconds": 1.3,
        }
        with patch("aragora.server.debate_factory.DebateFactory", return_value=MagicMock()):
            with patch(
                "aragora.server.handlers.features.unified_inbox.auto_debate.auto_spawn_debate_for_message",
                new_callable=AsyncMock,
                return_value=debate_result,
            ):
                req = _req(
                    method="POST",
                    path="/api/v1/inbox/messages/msg-1/debate",
                )
                result = await handler.handle_request(
                    req, "/api/v1/inbox/messages/msg-1/debate", "POST"
                )

        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["data"]["data"]["debate_id"] == "debate-1"
        assert body["data"]["source_message_id"] == "msg-1"
        assert body["data"]["provider_message_id"] == "ext-123"

    @pytest.mark.asyncio
    async def test_auto_debate_creates_receipt_for_safe_gmail_action(self, handler, mock_store):
        mock_store.get_message.return_value = _message_record("msg-1")
        debate_result = {
            "debate_id": "debate-archive-1",
            "final_answer": json.dumps(
                {
                    "recommended_action": "archive",
                    "confidence": 0.93,
                    "rationale": "Low-value message that can be safely archived.",
                    "dissent_summary": "No material dissent.",
                }
            ),
            "consensus_reached": True,
            "confidence": 0.91,
            "latency_seconds": 2.4,
        }
        mock_service = MagicMock()
        mock_envelope = MagicMock()
        mock_envelope.receipt.to_dict.return_value = {
            "receipt_id": "receipt-1",
            "state": "created",
        }
        mock_envelope.intent.to_dict.return_value = {
            "provider": "gmail",
            "user_id": "acct-1",
            "message_id": "ext-123",
            "action": "archive",
        }
        mock_envelope.decision.to_dict.return_value = {
            "final_action": "archive",
            "confidence": 0.93,
        }
        mock_envelope.provider_route = "openrouter"
        mock_envelope.debate_id = "debate-archive-1"
        mock_service.create_receipt.return_value = mock_envelope

        with patch("aragora.server.debate_factory.DebateFactory", return_value=MagicMock()):
            with patch(
                "aragora.server.handlers.features.unified_inbox.auto_debate.auto_spawn_debate_for_message",
                new_callable=AsyncMock,
                return_value=debate_result,
            ):
                with patch(
                    "aragora.inbox.get_inbox_trust_wedge_service",
                    return_value=mock_service,
                ):
                    req = _req(
                        method="POST",
                        path="/api/v1/inbox/messages/msg-1/debate",
                        body={
                            "create_receipt": True,
                            "provider_route": "openrouter",
                        },
                    )
                    result = await handler.handle_request(
                        req, "/api/v1/inbox/messages/msg-1/debate", "POST"
                    )

        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["data"]["receipt_created"] is True
        assert body["data"]["receipt"]["receipt_id"] == "receipt-1"
        assert body["data"]["provider_message_id"] == "ext-123"

        intent_arg, decision_arg = mock_service.create_receipt.call_args.args[:2]
        assert intent_arg.provider == "gmail"
        assert intent_arg.user_id == "acct-1"
        assert intent_arg.message_id == "ext-123"
        assert intent_arg.provider_route == "openrouter"
        assert intent_arg.action.value == "archive"
        assert decision_arg.final_action.value == "archive"
        assert decision_arg.latency_seconds == 2.4
        assert mock_service.create_receipt.call_args.kwargs["expires_in_hours"] == 24.0
        assert mock_service.create_receipt.call_args.kwargs["auto_approve"] is False

    @pytest.mark.asyncio
    async def test_auto_debate_receipt_not_created_without_safe_action(self, handler, mock_store):
        mock_store.get_message.return_value = _message_record("msg-1")
        debate_result = {
            "debate_id": "debate-none-1",
            "final_answer": json.dumps(
                {
                    "recommended_action": "none",
                    "confidence": 0.61,
                    "rationale": "Need human review before any safe inbox wedge action.",
                    "dissent_summary": "Mixed views on urgency.",
                }
            ),
            "consensus_reached": False,
            "confidence": 0.61,
            "latency_seconds": 1.9,
        }
        mock_service = MagicMock()

        with patch("aragora.server.debate_factory.DebateFactory", return_value=MagicMock()):
            with patch(
                "aragora.server.handlers.features.unified_inbox.auto_debate.auto_spawn_debate_for_message",
                new_callable=AsyncMock,
                return_value=debate_result,
            ):
                with patch(
                    "aragora.inbox.get_inbox_trust_wedge_service",
                    return_value=mock_service,
                ):
                    req = _req(
                        method="POST",
                        path="/api/v1/inbox/messages/msg-1/debate",
                        body={"create_receipt": True},
                    )
                    result = await handler.handle_request(
                        req, "/api/v1/inbox/messages/msg-1/debate", "POST"
                    )

        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["data"]["receipt_created"] is False
        assert body["data"]["receipt"] is None
        assert "safe inbox trust wedge action" in body["data"]["receipt_error"].lower()
        mock_service.create_receipt.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_debate_receipt_rejected_for_non_gmail(self, handler, mock_store):
        mock_store.get_message.return_value = _message_record("msg-1", provider="outlook")
        with patch("aragora.server.debate_factory.DebateFactory", return_value=MagicMock()):
            with patch(
                "aragora.server.handlers.features.unified_inbox.auto_debate.auto_spawn_debate_for_message",
                new_callable=AsyncMock,
            ) as mock_auto_debate:
                req = _req(
                    method="POST",
                    path="/api/v1/inbox/messages/msg-1/debate",
                    body={"create_receipt": True},
                )
                result = await handler.handle_request(
                    req, "/api/v1/inbox/messages/msg-1/debate", "POST"
                )

        assert _status(result) == 400
        assert "gmail unified inbox messages only" in _body(result)["error"].lower()
        mock_auto_debate.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /api/v1/inbox/triage
# ---------------------------------------------------------------------------


class TestTriage:
    """Tests for POST /api/v1/inbox/triage."""

    @pytest.mark.asyncio
    async def test_triage_success(self, handler, mock_store):
        mock_store.get_message.return_value = _message_record("msg-1")
        mock_triage_result = MagicMock()
        mock_triage_result.to_dict.return_value = {
            "message_id": "msg-1",
            "recommended_action": "defer",
            "confidence": 0.85,
            "rationale": "Priority analysis",
        }
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.run_triage",
            new_callable=AsyncMock,
            return_value=[mock_triage_result],
        ):
            req = _req(
                method="POST",
                path="/api/v1/inbox/triage",
                body={"message_ids": ["msg-1"], "context": {"user_preference": "auto"}},
            )
            result = await handler.handle_request(req, "/api/v1/inbox/triage", "POST")
            assert _status(result) == 200
            body = _body(result)
            assert body["success"] is True
            assert body["data"]["total_triaged"] == 1

    @pytest.mark.asyncio
    async def test_triage_no_message_ids(self, handler, mock_store):
        req = _req(
            method="POST",
            path="/api/v1/inbox/triage",
            body={"message_ids": []},
        )
        result = await handler.handle_request(req, "/api/v1/inbox/triage", "POST")
        assert _status(result) == 400
        body = _body(result)
        assert "No message IDs" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_triage_missing_message_ids_field(self, handler, mock_store):
        req = _req(
            method="POST",
            path="/api/v1/inbox/triage",
            body={},
        )
        result = await handler.handle_request(req, "/api/v1/inbox/triage", "POST")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_triage_no_matching_messages(self, handler, mock_store):
        mock_store.get_message.return_value = None
        req = _req(
            method="POST",
            path="/api/v1/inbox/triage",
            body={"message_ids": ["nonexistent-1", "nonexistent-2"]},
        )
        result = await handler.handle_request(req, "/api/v1/inbox/triage", "POST")
        assert _status(result) == 404
        body = _body(result)
        assert "No matching messages" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_triage_exception_returns_500(self, handler, mock_store):
        mock_store.get_message.return_value = _message_record("msg-1")
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.run_triage",
            new_callable=AsyncMock,
            side_effect=ValueError("triage error"),
        ):
            req = _req(
                method="POST",
                path="/api/v1/inbox/triage",
                body={"message_ids": ["msg-1"]},
            )
            result = await handler.handle_request(req, "/api/v1/inbox/triage", "POST")
            assert _status(result) == 500


# ---------------------------------------------------------------------------
# POST /api/v1/inbox/bulk-action
# ---------------------------------------------------------------------------


class TestBulkAction:
    """Tests for POST /api/v1/inbox/bulk-action."""

    @pytest.mark.asyncio
    async def test_bulk_action_mark_read(self, handler, mock_store):
        mock_result = {
            "action": "mark_read",
            "success_count": 2,
            "error_count": 0,
            "errors": None,
        }
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.execute_bulk_action",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            req = _req(
                method="POST",
                path="/api/v1/inbox/bulk-action",
                body={
                    "message_ids": ["msg-1", "msg-2"],
                    "action": "mark_read",
                },
            )
            result = await handler.handle_request(req, "/api/v1/inbox/bulk-action", "POST")
            assert _status(result) == 200
            body = _body(result)
            assert body["success"] is True
            assert body["data"]["success_count"] == 2

    @pytest.mark.asyncio
    async def test_bulk_action_archive(self, handler, mock_store):
        mock_result = {
            "action": "archive",
            "success_count": 1,
            "error_count": 0,
            "errors": None,
        }
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.execute_bulk_action",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            req = _req(
                method="POST",
                path="/api/v1/inbox/bulk-action",
                body={"message_ids": ["msg-1"], "action": "archive"},
            )
            result = await handler.handle_request(req, "/api/v1/inbox/bulk-action", "POST")
            assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_bulk_action_no_message_ids(self, handler, mock_store):
        req = _req(
            method="POST",
            path="/api/v1/inbox/bulk-action",
            body={"message_ids": [], "action": "mark_read"},
        )
        result = await handler.handle_request(req, "/api/v1/inbox/bulk-action", "POST")
        assert _status(result) == 400
        body = _body(result)
        assert "No message IDs" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_bulk_action_invalid_action(self, handler, mock_store):
        req = _req(
            method="POST",
            path="/api/v1/inbox/bulk-action",
            body={"message_ids": ["msg-1"], "action": "explode"},
        )
        result = await handler.handle_request(req, "/api/v1/inbox/bulk-action", "POST")
        assert _status(result) == 400
        body = _body(result)
        assert "Invalid action" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_bulk_action_missing_action(self, handler, mock_store):
        req = _req(
            method="POST",
            path="/api/v1/inbox/bulk-action",
            body={"message_ids": ["msg-1"]},
        )
        result = await handler.handle_request(req, "/api/v1/inbox/bulk-action", "POST")
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_bulk_action_exception_returns_500(self, handler, mock_store):
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.execute_bulk_action",
            new_callable=AsyncMock,
            side_effect=TypeError("type error"),
        ):
            req = _req(
                method="POST",
                path="/api/v1/inbox/bulk-action",
                body={"message_ids": ["msg-1"], "action": "mark_read"},
            )
            result = await handler.handle_request(req, "/api/v1/inbox/bulk-action", "POST")
            assert _status(result) == 500


# ---------------------------------------------------------------------------
# GET /api/v1/inbox/stats
# ---------------------------------------------------------------------------


class TestStats:
    """Tests for GET /api/v1/inbox/stats."""

    @pytest.mark.asyncio
    async def test_stats_empty_inbox(self, handler, mock_store):
        mock_store.list_accounts.return_value = []
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.fetch_all_messages",
            new_callable=AsyncMock,
            return_value=[],
        ):
            req = _req(path="/api/v1/inbox/stats")
            result = await handler.handle_request(req, "/api/v1/inbox/stats", "GET")
            assert _status(result) == 200
            body = _body(result)
            assert body["success"] is True
            stats = body["data"]["stats"]
            assert stats["total_accounts"] == 0
            assert stats["total_messages"] == 0

    @pytest.mark.asyncio
    async def test_stats_with_data(self, handler, mock_store):
        mock_store.list_accounts.return_value = [
            _account_record("acct-1", "gmail"),
            _account_record("acct-2", "outlook", "user@outlook.com"),
        ]

        # Create mock UnifiedMessage objects
        from aragora.server.handlers.features.unified_inbox.models import (
            EmailProvider,
            UnifiedMessage,
        )

        messages = [
            UnifiedMessage(
                id="m1",
                account_id="acct-1",
                provider=EmailProvider.GMAIL,
                external_id="ext1",
                subject="High priority",
                sender_email="boss@example.com",
                sender_name="Boss",
                recipients=["user@gmail.com"],
                cc=[],
                received_at=_NOW,
                snippet="Important",
                body_preview="Important message",
                is_read=False,
                is_starred=True,
                has_attachments=False,
                labels=["inbox"],
                priority_tier="high",
                priority_score=0.8,
            ),
            UnifiedMessage(
                id="m2",
                account_id="acct-2",
                provider=EmailProvider.OUTLOOK,
                external_id="ext2",
                subject="Low priority",
                sender_email="newsletter@example.com",
                sender_name="Newsletter",
                recipients=["user@outlook.com"],
                cc=[],
                received_at=_NOW,
                snippet="News update",
                body_preview="News update body",
                is_read=True,
                is_starred=False,
                has_attachments=False,
                labels=["inbox"],
                priority_tier="low",
                priority_score=0.2,
            ),
        ]

        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.fetch_all_messages",
            new_callable=AsyncMock,
            return_value=messages,
        ):
            req = _req(path="/api/v1/inbox/stats")
            result = await handler.handle_request(req, "/api/v1/inbox/stats", "GET")
            assert _status(result) == 200
            body = _body(result)
            stats = body["data"]["stats"]
            assert stats["total_accounts"] == 2
            assert stats["total_messages"] == 2
            assert stats["unread_count"] == 1
            assert stats["messages_by_priority"]["high"] == 1
            assert stats["messages_by_priority"]["low"] == 1
            assert stats["messages_by_provider"]["gmail"] == 1
            assert stats["messages_by_provider"]["outlook"] == 1


# ---------------------------------------------------------------------------
# GET /api/v1/inbox/trends
# ---------------------------------------------------------------------------


class TestTrends:
    """Tests for GET /api/v1/inbox/trends."""

    @pytest.mark.asyncio
    async def test_trends_default_days(self, handler, mock_store):
        req = _req(path="/api/v1/inbox/trends")
        result = await handler.handle_request(req, "/api/v1/inbox/trends", "GET")
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        trends = body["data"]["trends"]
        assert trends["period_days"] == 7
        assert "priority_trends" in trends
        assert "volume_trend" in trends
        assert "response_time_trend" in trends

    @pytest.mark.asyncio
    async def test_trends_custom_days(self, handler, mock_store):
        req = _req(path="/api/v1/inbox/trends", query={"days": "30"})
        result = await handler.handle_request(req, "/api/v1/inbox/trends", "GET")
        assert _status(result) == 200
        body = _body(result)
        trends = body["data"]["trends"]
        assert trends["period_days"] == 30

    @pytest.mark.asyncio
    async def test_trends_invalid_days_defaults_to_seven(self, handler, mock_store):
        req = _req(path="/api/v1/inbox/trends", query={"days": "not_a_number"})
        result = await handler.handle_request(req, "/api/v1/inbox/trends", "GET")
        assert _status(result) == 200
        body = _body(result)
        trends = body["data"]["trends"]
        assert trends["period_days"] == 7


# ---------------------------------------------------------------------------
# 404 Not Found Route
# ---------------------------------------------------------------------------


class TestNotFoundRoute:
    """Tests for unmatched routes returning 404."""

    @pytest.mark.asyncio
    async def test_unknown_inbox_path(self, handler):
        req = _req(path="/api/v1/inbox/nonexistent")
        result = await handler.handle_request(req, "/api/v1/inbox/nonexistent", "GET")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_wrong_method_for_accounts(self, handler):
        req = _req(method="POST", path="/api/v1/inbox/accounts")
        result = await handler.handle_request(req, "/api/v1/inbox/accounts", "POST")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_wrong_method_for_messages(self, handler):
        req = _req(method="DELETE", path="/api/v1/inbox/messages")
        result = await handler.handle_request(req, "/api/v1/inbox/messages", "DELETE")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_wrong_method_for_connect(self, handler):
        req = _req(method="GET", path="/api/v1/inbox/connect")
        result = await handler.handle_request(req, "/api/v1/inbox/connect", "GET")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_wrong_method_for_triage(self, handler):
        req = _req(method="GET", path="/api/v1/inbox/triage")
        result = await handler.handle_request(req, "/api/v1/inbox/triage", "GET")
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_wrong_method_for_bulk_action(self, handler):
        req = _req(method="GET", path="/api/v1/inbox/bulk-action")
        result = await handler.handle_request(req, "/api/v1/inbox/bulk-action", "GET")
        assert _status(result) == 404


# ---------------------------------------------------------------------------
# Tenant ID extraction
# ---------------------------------------------------------------------------


class TestTenantId:
    """Tests for tenant ID extraction from request."""

    @pytest.mark.asyncio
    async def test_default_tenant_id(self, handler, mock_store):
        mock_store.list_accounts.return_value = []
        req = _req(path="/api/v1/inbox/accounts")
        result = await handler.handle_request(req, "/api/v1/inbox/accounts", "GET")
        assert _status(result) == 200
        mock_store.list_accounts.assert_awaited_once_with("default")

    @pytest.mark.asyncio
    async def test_custom_tenant_id(self, handler, mock_store):
        mock_store.list_accounts.return_value = []
        req = _req(path="/api/v1/inbox/accounts")
        req.tenant_id = "tenant-42"
        result = await handler.handle_request(req, "/api/v1/inbox/accounts", "GET")
        assert _status(result) == 200
        mock_store.list_accounts.assert_awaited_once_with("tenant-42")


# ---------------------------------------------------------------------------
# Top-level exception handler
# ---------------------------------------------------------------------------


class TestTopLevelExceptionHandler:
    """Tests for the top-level try/except in handle_request."""

    @pytest.mark.asyncio
    async def test_value_error_returns_500(self, handler, mock_store):
        mock_store.list_accounts.side_effect = ValueError("bad value")
        req = _req(path="/api/v1/inbox/accounts")
        result = await handler.handle_request(req, "/api/v1/inbox/accounts", "GET")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_key_error_returns_500(self, handler, mock_store):
        mock_store.list_accounts.side_effect = KeyError("missing key")
        req = _req(path="/api/v1/inbox/accounts")
        result = await handler.handle_request(req, "/api/v1/inbox/accounts", "GET")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_type_error_returns_500(self, handler, mock_store):
        mock_store.list_accounts.side_effect = TypeError("type error")
        req = _req(path="/api/v1/inbox/accounts")
        result = await handler.handle_request(req, "/api/v1/inbox/accounts", "GET")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_runtime_error_returns_500(self, handler, mock_store):
        mock_store.list_accounts.side_effect = RuntimeError("runtime error")
        req = _req(path="/api/v1/inbox/accounts")
        result = await handler.handle_request(req, "/api/v1/inbox/accounts", "GET")
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_os_error_returns_500(self, handler, mock_store):
        mock_store.list_accounts.side_effect = OSError("disk error")
        req = _req(path="/api/v1/inbox/accounts")
        result = await handler.handle_request(req, "/api/v1/inbox/accounts", "GET")
        assert _status(result) == 500


# ---------------------------------------------------------------------------
# Module-level get_unified_inbox_handler / handle_unified_inbox
# ---------------------------------------------------------------------------


class TestModuleLevelFunctions:
    """Tests for module-level convenience functions."""

    def test_get_unified_inbox_handler_singleton(self):
        import aragora.server.handlers.features.unified_inbox.handler as mod

        # Reset singleton
        mod._handler_instance = None
        with patch.object(mod, "get_canonical_gateway_stores") as mock_gw:
            mock_gw_instance = MagicMock()
            mock_gw_instance.inbox_store.return_value = AsyncMock()
            mock_gw.return_value = mock_gw_instance
            h1 = mod.get_unified_inbox_handler()
            h2 = mod.get_unified_inbox_handler()
            assert h1 is h2
            mod._handler_instance = None  # cleanup

    @pytest.mark.asyncio
    async def test_handle_unified_inbox_delegates_to_handler(self):
        import aragora.server.handlers.features.unified_inbox.handler as mod

        mock_handler = AsyncMock()
        mock_handler.handle_request = AsyncMock(return_value={"status_code": 200})
        mod._handler_instance = None
        with patch.object(mod, "get_unified_inbox_handler", return_value=mock_handler):
            req = _req(path="/api/v1/inbox/accounts")
            await mod.handle_unified_inbox(req, "/api/v1/inbox/accounts", "GET")
            mock_handler.handle_request.assert_awaited_once_with(
                req, "/api/v1/inbox/accounts", "GET"
            )
        mod._handler_instance = None  # cleanup


# ---------------------------------------------------------------------------
# Persistence helper
# ---------------------------------------------------------------------------


class TestScheduleMessagePersist:
    """Tests for _schedule_message_persist."""

    @pytest.mark.asyncio
    async def test_schedule_message_persist_creates_task(self, handler, mock_store):
        from aragora.server.handlers.features.unified_inbox.models import (
            EmailProvider,
            UnifiedMessage,
        )

        message = UnifiedMessage(
            id="msg-persist",
            account_id="acct-1",
            provider=EmailProvider.GMAIL,
            external_id="ext-p",
            subject="Test",
            sender_email="sender@example.com",
            sender_name="Sender",
            recipients=["user@gmail.com"],
            cc=[],
            received_at=_NOW,
            snippet="Preview",
            body_preview="Body",
            is_read=False,
            is_starred=False,
            has_attachments=False,
            labels=["inbox"],
        )

        # Call the persist method -- it schedules a task on the running loop
        handler._schedule_message_persist("default", message)

        # Allow the scheduled task to run
        import asyncio

        await asyncio.sleep(0.05)

        mock_store.save_message.assert_awaited_once()
        mock_store.update_account_fields.assert_awaited_once()


# ---------------------------------------------------------------------------
# Valid actions list
# ---------------------------------------------------------------------------


class TestValidActions:
    """Verify VALID_ACTIONS matches expected set."""

    def test_valid_actions_contents(self):
        from aragora.server.handlers.features.unified_inbox.actions import VALID_ACTIONS

        assert "archive" in VALID_ACTIONS
        assert "mark_read" in VALID_ACTIONS
        assert "mark_unread" in VALID_ACTIONS
        assert "star" in VALID_ACTIONS
        assert "delete" in VALID_ACTIONS
        assert len(VALID_ACTIONS) == 5


# ---------------------------------------------------------------------------
# Bulk action valid actions
# ---------------------------------------------------------------------------


class TestBulkActionAllTypes:
    """Test each valid bulk action type."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", ["archive", "mark_read", "mark_unread", "star", "delete"])
    async def test_bulk_action_each_valid_type(self, handler, mock_store, action):
        mock_result = {
            "action": action,
            "success_count": 1,
            "error_count": 0,
            "errors": None,
        }
        with patch(
            "aragora.server.handlers.features.unified_inbox.handler.execute_bulk_action",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            req = _req(
                method="POST",
                path="/api/v1/inbox/bulk-action",
                body={"message_ids": ["msg-1"], "action": action},
            )
            result = await handler.handle_request(req, "/api/v1/inbox/bulk-action", "POST")
            assert _status(result) == 200
            body = _body(result)
            assert body["data"]["action"] == action


# ---------------------------------------------------------------------------
# Query params extraction
# ---------------------------------------------------------------------------


class TestQueryParamsExtraction:
    """Test _get_query_params from various request types."""

    def test_query_from_query_attribute(self, handler):
        req = MagicMock()
        req.query = {"key": "value"}
        delattr(req, "args") if hasattr(req, "args") else None
        params = handler._get_query_params(req)
        assert params == {"key": "value"}

    def test_query_from_args_attribute(self, handler):
        req = MagicMock(spec=[])
        req.args = {"key": "value"}
        params = handler._get_query_params(req)
        assert params == {"key": "value"}

    def test_query_empty_when_no_attributes(self, handler):
        req = MagicMock(spec=[])
        params = handler._get_query_params(req)
        assert params == {}
