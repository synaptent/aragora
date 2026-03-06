"""Tests for Gmail labels and filters handler.

Tests the GmailLabelsHandler covering:
- POST /api/v1/gmail/labels - Create label
- GET /api/v1/gmail/labels - List labels
- PATCH /api/v1/gmail/labels/:id - Update label
- DELETE /api/v1/gmail/labels/:id - Delete label
- POST /api/v1/gmail/messages/:id/labels - Modify message labels
- POST /api/v1/gmail/messages/:id/read - Mark as read/unread
- POST /api/v1/gmail/messages/:id/star - Star/unstar message
- POST /api/v1/gmail/messages/:id/archive - Archive message
- POST /api/v1/gmail/messages/:id/trash - Trash/untrash message
- POST /api/v1/gmail/filters - Create filter
- GET /api/v1/gmail/filters - List filters
- DELETE /api/v1/gmail/filters/:id - Delete filter
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.base import json_response
from aragora.server.handlers.features.gmail_labels import GmailLabelsHandler
from aragora.storage.gmail_token_store import GmailUserState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status(result) -> int:
    """Extract status code from HandlerResult."""
    return result.status_code


def _body(result) -> dict[str, Any]:
    """Extract parsed JSON body from HandlerResult."""
    return json.loads(result.body.decode("utf-8"))


@dataclass
class MockHTTPHandler:
    """Mock HTTP handler for tests."""

    path: str = "/"
    method: str = "GET"
    body: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    command: str = "GET"

    def __post_init__(self):
        if self.headers is None:
            self.headers = {"Content-Length": "0", "Content-Type": "application/json"}
        self.client_address = ("127.0.0.1", 12345)
        self.rfile = MagicMock()
        if self.body:
            body_bytes = json.dumps(self.body).encode()
            self.rfile.read.return_value = body_bytes
            self.headers["Content-Length"] = str(len(body_bytes))
        else:
            self.rfile.read.return_value = b"{}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# NOTE: get_user_state is async but the handler calls it WITHOUT await.
# The return value is consumed directly (not as a coroutine), so we must
# force a sync MagicMock via ``new=`` to prevent auto-AsyncMock detection.

_GET_USER_STATE = "aragora.server.handlers.features.gmail_labels.get_user_state"


def _patch_user_state(state):
    """Patch get_user_state as a sync function returning the state."""
    return patch(_GET_USER_STATE, new=MagicMock(return_value=state))


def _mock_http_pool():
    """Create a mock HTTP connection pool context manager."""
    mock_session = AsyncMock()
    mock_response = MagicMock()
    mock_response.json.return_value = {}
    mock_response.raise_for_status = MagicMock()
    mock_session.post = AsyncMock(return_value=mock_response)
    mock_session.get = AsyncMock(return_value=mock_response)
    mock_session.patch = AsyncMock(return_value=mock_response)
    mock_session.delete = AsyncMock(return_value=mock_response)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.get_session = MagicMock(return_value=mock_cm)

    return mock_pool, mock_session, mock_response


@pytest.fixture
def handler():
    """Create a GmailLabelsHandler with minimal context."""
    return GmailLabelsHandler(server_context={})


@pytest.fixture
def mock_http():
    """Create a basic mock HTTP handler (no body)."""
    return MockHTTPHandler()


@pytest.fixture
def mock_http_with_body():
    """Factory for mock HTTP handler with body."""

    def _create(body: dict[str, Any]) -> MockHTTPHandler:
        return MockHTTPHandler(body=body)

    return _create


@pytest.fixture
def gmail_state():
    """Create a GmailUserState with valid tokens."""
    return GmailUserState(
        user_id="default",
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        token_expiry=datetime(2099, 1, 1, tzinfo=timezone.utc),
        email_address="user@example.com",
    )


@pytest.fixture
def gmail_state_no_refresh():
    """Create a GmailUserState without a refresh token."""
    return GmailUserState(
        user_id="default",
        access_token="test-access-token",
        refresh_token="",
    )


# ---------------------------------------------------------------------------
# can_handle tests
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for can_handle route matching."""

    def test_labels_list(self, handler):
        assert handler.can_handle("/api/v1/gmail/labels") is True

    def test_filters_list(self, handler):
        assert handler.can_handle("/api/v1/gmail/filters") is True

    def test_label_by_id(self, handler):
        assert handler.can_handle("/api/v1/gmail/labels/Label_1") is True

    def test_filter_by_id(self, handler):
        assert handler.can_handle("/api/v1/gmail/filters/filter_abc") is True

    def test_message_labels(self, handler):
        assert handler.can_handle("/api/v1/gmail/messages/msg1/labels") is True

    def test_message_read(self, handler):
        assert handler.can_handle("/api/v1/gmail/messages/msg1/read") is True

    def test_message_star(self, handler):
        assert handler.can_handle("/api/v1/gmail/messages/msg1/star") is True

    def test_message_archive(self, handler):
        assert handler.can_handle("/api/v1/gmail/messages/msg1/archive") is True

    def test_message_trash(self, handler):
        assert handler.can_handle("/api/v1/gmail/messages/msg1/trash") is True

    def test_unrelated_path(self, handler):
        assert handler.can_handle("/api/v1/debates") is False

    def test_empty_path(self, handler):
        assert handler.can_handle("") is False

    def test_partial_labels(self, handler):
        assert handler.can_handle("/api/v1/gmail/label") is False

    def test_partial_filters(self, handler):
        assert handler.can_handle("/api/v1/gmail/filter") is False

    def test_gmail_root(self, handler):
        assert handler.can_handle("/api/v1/gmail") is False

    def test_different_api(self, handler):
        assert handler.can_handle("/api/v2/gmail/labels") is False

    def test_can_handle_with_method(self, handler):
        assert handler.can_handle("/api/v1/gmail/labels", "POST") is True
        assert handler.can_handle("/api/v1/gmail/labels", "DELETE") is True


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/labels - List labels
# ---------------------------------------------------------------------------


class TestListLabels:
    """Tests for GET /api/v1/gmail/labels."""

    @pytest.mark.asyncio
    async def test_list_labels_success(self, handler, mock_http, gmail_state):
        mock_label = MagicMock()
        mock_label.id = "Label_1"
        mock_label.name = "Work"
        mock_label.type = "user"
        mock_label.message_list_visibility = "show"
        mock_label.label_list_visibility = "labelShow"

        mock_connector = MagicMock()
        mock_connector.list_labels = AsyncMock(return_value=[mock_label])

        with _patch_user_state(gmail_state):
            with patch(
                "aragora.connectors.enterprise.communication.gmail.GmailConnector",
                return_value=mock_connector,
            ):
                result = await handler.handle("/api/v1/gmail/labels", {}, mock_http)

        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 1
        assert body["labels"][0]["id"] == "Label_1"
        assert body["labels"][0]["name"] == "Work"
        assert body["labels"][0]["type"] == "user"
        assert body["labels"][0]["message_list_visibility"] == "show"
        assert body["labels"][0]["label_list_visibility"] == "labelShow"

    @pytest.mark.asyncio
    async def test_list_labels_multiple(self, handler, mock_http, gmail_state):
        mock_labels = []
        for i, name in enumerate(["INBOX", "SENT", "Work", "Personal"]):
            lbl = MagicMock()
            lbl.id = f"Label_{i}"
            lbl.name = name
            lbl.type = "system" if i < 2 else "user"
            lbl.message_list_visibility = "show"
            lbl.label_list_visibility = "labelShow"
            mock_labels.append(lbl)

        mock_connector = MagicMock()
        mock_connector.list_labels = AsyncMock(return_value=mock_labels)

        with _patch_user_state(gmail_state):
            with patch(
                "aragora.connectors.enterprise.communication.gmail.GmailConnector",
                return_value=mock_connector,
            ):
                result = await handler.handle("/api/v1/gmail/labels", {}, mock_http)

        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 4
        assert len(body["labels"]) == 4

    @pytest.mark.asyncio
    async def test_list_labels_empty(self, handler, mock_http, gmail_state):
        mock_connector = MagicMock()
        mock_connector.list_labels = AsyncMock(return_value=[])

        with _patch_user_state(gmail_state):
            with patch(
                "aragora.connectors.enterprise.communication.gmail.GmailConnector",
                return_value=mock_connector,
            ):
                result = await handler.handle("/api/v1/gmail/labels", {}, mock_http)

        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 0
        assert body["labels"] == []

    @pytest.mark.asyncio
    async def test_list_labels_api_error(self, handler, mock_http, gmail_state):
        mock_connector = MagicMock()
        mock_connector.list_labels = AsyncMock(side_effect=ConnectionError("API down"))

        with _patch_user_state(gmail_state):
            with patch(
                "aragora.connectors.enterprise.communication.gmail.GmailConnector",
                return_value=mock_connector,
            ):
                result = await handler.handle("/api/v1/gmail/labels", {}, mock_http)

        assert _status(result) == 500
        assert "Failed to list labels" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_list_labels_timeout(self, handler, mock_http, gmail_state):
        mock_connector = MagicMock()
        mock_connector.list_labels = AsyncMock(side_effect=TimeoutError("timeout"))

        with _patch_user_state(gmail_state):
            with patch(
                "aragora.connectors.enterprise.communication.gmail.GmailConnector",
                return_value=mock_connector,
            ):
                result = await handler.handle("/api/v1/gmail/labels", {}, mock_http)

        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_list_labels_value_error(self, handler, mock_http, gmail_state):
        mock_connector = MagicMock()
        mock_connector.list_labels = AsyncMock(side_effect=ValueError("bad data"))

        with _patch_user_state(gmail_state):
            with patch(
                "aragora.connectors.enterprise.communication.gmail.GmailConnector",
                return_value=mock_connector,
            ):
                result = await handler.handle("/api/v1/gmail/labels", {}, mock_http)

        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_list_labels_attribute_error(self, handler, mock_http, gmail_state):
        mock_connector = MagicMock()
        mock_connector.list_labels = AsyncMock(side_effect=AttributeError("bad attr"))

        with _patch_user_state(gmail_state):
            with patch(
                "aragora.connectors.enterprise.communication.gmail.GmailConnector",
                return_value=mock_connector,
            ):
                result = await handler.handle("/api/v1/gmail/labels", {}, mock_http)

        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_list_labels_no_state(self, handler, mock_http):
        with _patch_user_state(None):
            result = await handler.handle("/api/v1/gmail/labels", {}, mock_http)

        assert _status(result) == 401
        assert "authenticate" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_list_labels_no_refresh_token(self, handler, mock_http, gmail_state_no_refresh):
        with _patch_user_state(gmail_state_no_refresh):
            result = await handler.handle("/api/v1/gmail/labels", {}, mock_http)

        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_list_labels_with_user_id(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state) as mock_get:
            with patch.object(
                handler,
                "_list_labels",
                new_callable=AsyncMock,
                return_value=MagicMock(
                    status_code=200,
                    body=json.dumps({"labels": [], "count": 0}).encode(),
                ),
            ):
                await handler.handle("/api/v1/gmail/labels", {"user_id": "user42"}, mock_http)
            mock_get.assert_called_once_with("user42")

    @pytest.mark.asyncio
    async def test_list_labels_default_user_id(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state) as mock_get:
            with patch.object(
                handler,
                "_list_labels",
                new_callable=AsyncMock,
                return_value=MagicMock(
                    status_code=200,
                    body=json.dumps({"labels": [], "count": 0}).encode(),
                ),
            ):
                await handler.handle("/api/v1/gmail/labels", {}, mock_http)
            mock_get.assert_called_once_with("default")


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/labels - Create label
# ---------------------------------------------------------------------------


class TestCreateLabel:
    """Tests for POST /api/v1/gmail/labels."""

    @pytest.mark.asyncio
    async def test_create_label_success(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({"name": "Projects"})
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_create_label",
                new_callable=AsyncMock,
                return_value={"id": "Label_99", "name": "Projects"},
            ):
                result = await handler.handle_post("/api/v1/gmail/labels", {}, http)
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["label"]["id"] == "Label_99"

    @pytest.mark.asyncio
    async def test_create_label_missing_name(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({})
        with _patch_user_state(gmail_state):
            result = await handler.handle_post("/api/v1/gmail/labels", {}, http)
        assert _status(result) == 400
        assert "name" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_create_label_empty_name(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({"name": ""})
        with _patch_user_state(gmail_state):
            result = await handler.handle_post("/api/v1/gmail/labels", {}, http)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_label_api_connection_error(
        self, handler, mock_http_with_body, gmail_state
    ):
        http = mock_http_with_body({"name": "Test"})
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_create_label",
                new_callable=AsyncMock,
                side_effect=ConnectionError("API fail"),
            ):
                result = await handler.handle_post("/api/v1/gmail/labels", {}, http)
        assert _status(result) == 500
        assert "creation failed" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_create_label_timeout(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({"name": "Test"})
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_create_label",
                new_callable=AsyncMock,
                side_effect=TimeoutError("timeout"),
            ):
                result = await handler.handle_post("/api/v1/gmail/labels", {}, http)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_create_label_os_error(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({"name": "Test"})
        with _patch_user_state(gmail_state):
            with patch.object(
                handler, "_api_create_label", new_callable=AsyncMock, side_effect=OSError("network")
            ):
                result = await handler.handle_post("/api/v1/gmail/labels", {}, http)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_create_label_no_state(self, handler, mock_http_with_body):
        http = mock_http_with_body({"name": "Test"})
        with _patch_user_state(None):
            result = await handler.handle_post("/api/v1/gmail/labels", {}, http)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_create_label_invalid_json(self, handler, mock_http):
        with patch.object(handler, "read_json_body", return_value=None):
            result = await handler.handle_post("/api/v1/gmail/labels", {}, mock_http)
        assert _status(result) == 400
        assert "json" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_create_label_with_colors(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body(
            {
                "name": "Important",
                "background_color": "#ff0000",
                "text_color": "#ffffff",
            }
        )
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_create_label",
                new_callable=AsyncMock,
                return_value={"id": "Lc", "name": "Important"},
            ) as mock_api:
                result = await handler.handle_post("/api/v1/gmail/labels", {}, http)
                opts = mock_api.call_args[0][2]
                assert opts["background_color"] == "#ff0000"
                assert opts["text_color"] == "#ffffff"
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_create_label_user_id_from_body(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({"name": "Test", "user_id": "custom_user"})
        with _patch_user_state(gmail_state) as mock_get:
            with patch.object(
                handler,
                "_api_create_label",
                new_callable=AsyncMock,
                return_value={"id": "L1", "name": "Test"},
            ):
                await handler.handle_post("/api/v1/gmail/labels", {}, http)
            mock_get.assert_called_once_with("custom_user")

    @pytest.mark.asyncio
    async def test_create_label_no_refresh_token(
        self, handler, mock_http_with_body, gmail_state_no_refresh
    ):
        http = mock_http_with_body({"name": "Test"})
        with _patch_user_state(gmail_state_no_refresh):
            result = await handler.handle_post("/api/v1/gmail/labels", {}, http)
        assert _status(result) == 401


# ---------------------------------------------------------------------------
# PATCH /api/v1/gmail/labels/:id - Update label
# ---------------------------------------------------------------------------


class TestUpdateLabel:
    """Tests for PATCH /api/v1/gmail/labels/:id."""

    @pytest.mark.asyncio
    async def test_update_label_success(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({"name": "Renamed"})
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_update_label",
                new_callable=AsyncMock,
                return_value={"id": "L1", "name": "Renamed"},
            ):
                result = await handler.handle_patch("/api/v1/gmail/labels/L1", {}, http)
        assert _status(result) == 200
        assert _body(result)["success"] is True
        assert _body(result)["label"]["name"] == "Renamed"

    @pytest.mark.asyncio
    async def test_update_label_api_error(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({"name": "Renamed"})
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_update_label",
                new_callable=AsyncMock,
                side_effect=ConnectionError("API fail"),
            ):
                result = await handler.handle_patch("/api/v1/gmail/labels/L1", {}, http)
        assert _status(result) == 500
        assert "update failed" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_update_label_no_state(self, handler, mock_http_with_body):
        http = mock_http_with_body({"name": "Renamed"})
        with _patch_user_state(None):
            result = await handler.handle_patch("/api/v1/gmail/labels/L1", {}, http)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_update_label_invalid_json(self, handler, mock_http):
        with patch.object(handler, "read_json_body", return_value=None):
            result = await handler.handle_patch("/api/v1/gmail/labels/L1", {}, mock_http)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_label_not_found_path(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({"name": "Renamed"})
        with _patch_user_state(gmail_state):
            result = await handler.handle_patch("/api/v1/gmail/unknown/x", {}, http)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_update_label_extracts_id(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({"name": "Updated"})
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_update_label",
                new_callable=AsyncMock,
                return_value={"id": "MyLabel123"},
            ) as mock_api:
                await handler.handle_patch("/api/v1/gmail/labels/MyLabel123", {}, http)
                assert mock_api.call_args[0][1] == "MyLabel123"

    @pytest.mark.asyncio
    async def test_update_label_no_refresh_token(
        self, handler, mock_http_with_body, gmail_state_no_refresh
    ):
        http = mock_http_with_body({"name": "Renamed"})
        with _patch_user_state(gmail_state_no_refresh):
            result = await handler.handle_patch("/api/v1/gmail/labels/L1", {}, http)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_update_label_value_error(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({"name": "Renamed"})
        with _patch_user_state(gmail_state):
            with patch.object(
                handler, "_api_update_label", new_callable=AsyncMock, side_effect=ValueError("bad")
            ):
                result = await handler.handle_patch("/api/v1/gmail/labels/L1", {}, http)
        assert _status(result) == 500


# ---------------------------------------------------------------------------
# DELETE /api/v1/gmail/labels/:id - Delete label
# ---------------------------------------------------------------------------


class TestDeleteLabel:
    """Tests for DELETE /api/v1/gmail/labels/:id."""

    @pytest.mark.asyncio
    async def test_delete_label_success(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state):
            with patch.object(handler, "_api_delete_label", new_callable=AsyncMock):
                result = await handler.handle_delete("/api/v1/gmail/labels/L1", {}, mock_http)
        assert _status(result) == 200
        assert _body(result)["success"] is True
        assert _body(result)["deleted"] == "L1"

    @pytest.mark.asyncio
    async def test_delete_label_api_error(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_delete_label",
                new_callable=AsyncMock,
                side_effect=ConnectionError("API fail"),
            ):
                result = await handler.handle_delete("/api/v1/gmail/labels/L1", {}, mock_http)
        assert _status(result) == 500
        assert "deletion failed" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_delete_label_no_state(self, handler, mock_http):
        with _patch_user_state(None):
            result = await handler.handle_delete("/api/v1/gmail/labels/L1", {}, mock_http)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_delete_label_user_id_param(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state) as mock_get:
            with patch.object(handler, "_api_delete_label", new_callable=AsyncMock):
                await handler.handle_delete(
                    "/api/v1/gmail/labels/L1", {"user_id": "u99"}, mock_http
                )
            mock_get.assert_called_once_with("u99")

    @pytest.mark.asyncio
    async def test_delete_label_not_found_path(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state):
            result = await handler.handle_delete("/api/v1/gmail/unknown/x", {}, mock_http)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_delete_label_no_refresh_token(self, handler, mock_http, gmail_state_no_refresh):
        with _patch_user_state(gmail_state_no_refresh):
            result = await handler.handle_delete("/api/v1/gmail/labels/L1", {}, mock_http)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_delete_label_timeout(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_delete_label",
                new_callable=AsyncMock,
                side_effect=TimeoutError("timeout"),
            ):
                result = await handler.handle_delete("/api/v1/gmail/labels/L1", {}, mock_http)
        assert _status(result) == 500


# ---------------------------------------------------------------------------
# Private method: _modify_message_labels
# ---------------------------------------------------------------------------


class TestModifyMessageLabels:
    """Tests for _modify_message_labels (tested directly)."""

    @pytest.mark.asyncio
    async def test_modify_labels_add(self, handler, gmail_state):
        with patch.object(
            handler,
            "_api_modify_labels",
            new_callable=AsyncMock,
            return_value={"labelIds": ["STARRED", "INBOX"]},
        ):
            result = await handler._modify_message_labels(
                gmail_state, "msg1", {"add": ["STARRED"], "remove": []}
            )
        assert _status(result) == 200
        body = _body(result)
        assert body["success"] is True
        assert body["message_id"] == "msg1"
        assert "STARRED" in body["labels"]

    @pytest.mark.asyncio
    async def test_modify_labels_remove(self, handler, gmail_state):
        with patch.object(
            handler,
            "_api_modify_labels",
            new_callable=AsyncMock,
            return_value={"labelIds": ["SENT"]},
        ):
            result = await handler._modify_message_labels(
                gmail_state, "msg1", {"add": [], "remove": ["INBOX"]}
            )
        assert _status(result) == 200
        assert "INBOX" not in _body(result)["labels"]

    @pytest.mark.asyncio
    async def test_modify_labels_add_and_remove(self, handler, gmail_state):
        with patch.object(
            handler,
            "_api_modify_labels",
            new_callable=AsyncMock,
            return_value={"labelIds": ["STARRED"]},
        ):
            result = await handler._modify_message_labels(
                gmail_state, "msg1", {"add": ["STARRED"], "remove": ["INBOX"]}
            )
        assert _status(result) == 200
        assert _body(result)["labels"] == ["STARRED"]

    @pytest.mark.asyncio
    async def test_modify_labels_empty(self, handler, gmail_state):
        result = await handler._modify_message_labels(
            gmail_state, "msg1", {"add": [], "remove": []}
        )
        assert _status(result) == 400
        assert "add or remove" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_modify_labels_no_fields(self, handler, gmail_state):
        result = await handler._modify_message_labels(gmail_state, "msg1", {})
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_modify_labels_api_error(self, handler, gmail_state):
        with patch.object(
            handler,
            "_api_modify_labels",
            new_callable=AsyncMock,
            side_effect=ConnectionError("API fail"),
        ):
            result = await handler._modify_message_labels(gmail_state, "msg1", {"add": ["STARRED"]})
        assert _status(result) == 500
        assert "modification failed" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_modify_labels_empty_result(self, handler, gmail_state):
        with patch.object(handler, "_api_modify_labels", new_callable=AsyncMock, return_value={}):
            result = await handler._modify_message_labels(gmail_state, "msg1", {"add": ["Custom"]})
        assert _status(result) == 200
        assert _body(result)["labels"] == []

    @pytest.mark.asyncio
    async def test_modify_labels_receipt_routes_to_inbox_wedge(self, handler, gmail_state):
        with patch(
            "aragora.server.handlers.inbox.email_actions.handle_add_label",
            new_callable=AsyncMock,
            return_value=json_response({"delegated": True}),
        ) as mock_handle:
            result = await handler._modify_message_labels(
                gmail_state,
                "msg1",
                {"add": ["TRIAGE"], "create_receipt": True, "user_id": "default"},
            )
        assert _status(result) == 200
        assert _body(result)["delegated"] is True
        mock_handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_modify_labels_receipt_rejects_remove_labels(self, handler, gmail_state):
        result = await handler._modify_message_labels(
            gmail_state,
            "msg1",
            {"add": ["TRIAGE"], "remove": ["INBOX"], "create_receipt": True},
        )
        assert _status(result) == 400
        assert "does not support remove labels" in _body(result)["error"].lower()


# ---------------------------------------------------------------------------
# Private method: _mark_read
# ---------------------------------------------------------------------------


class TestMarkRead:
    """Tests for _mark_read (tested directly)."""

    @pytest.mark.asyncio
    async def test_mark_read(self, handler, gmail_state):
        with patch.object(
            handler, "_api_modify_labels", new_callable=AsyncMock, return_value={}
        ) as mock_api:
            result = await handler._mark_read(gmail_state, "msg1", {"read": True})
        assert _status(result) == 200
        body = _body(result)
        assert body["is_read"] is True
        assert body["success"] is True
        # Mark as read removes UNREAD
        assert mock_api.call_args[0][2] == []  # add_labels
        assert mock_api.call_args[0][3] == ["UNREAD"]  # remove_labels

    @pytest.mark.asyncio
    async def test_mark_unread(self, handler, gmail_state):
        with patch.object(
            handler, "_api_modify_labels", new_callable=AsyncMock, return_value={}
        ) as mock_api:
            result = await handler._mark_read(gmail_state, "msg1", {"read": False})
        assert _status(result) == 200
        assert _body(result)["is_read"] is False
        assert mock_api.call_args[0][2] == ["UNREAD"]
        assert mock_api.call_args[0][3] == []

    @pytest.mark.asyncio
    async def test_mark_read_default_true(self, handler, gmail_state):
        with patch.object(handler, "_api_modify_labels", new_callable=AsyncMock, return_value={}):
            result = await handler._mark_read(gmail_state, "msg1", {})
        assert _body(result)["is_read"] is True

    @pytest.mark.asyncio
    async def test_mark_read_api_error(self, handler, gmail_state):
        with patch.object(
            handler, "_api_modify_labels", new_callable=AsyncMock, side_effect=ValueError("bad")
        ):
            result = await handler._mark_read(gmail_state, "msg1", {"read": True})
        assert _status(result) == 500


# ---------------------------------------------------------------------------
# Private method: _star_message
# ---------------------------------------------------------------------------


class TestStarMessage:
    """Tests for _star_message (tested directly)."""

    @pytest.mark.asyncio
    async def test_star_message(self, handler, gmail_state):
        with patch.object(
            handler, "_api_modify_labels", new_callable=AsyncMock, return_value={}
        ) as mock_api:
            result = await handler._star_message(gmail_state, "msg1", {"starred": True})
        assert _status(result) == 200
        assert _body(result)["is_starred"] is True
        assert mock_api.call_args[0][2] == ["STARRED"]
        assert mock_api.call_args[0][3] == []

    @pytest.mark.asyncio
    async def test_unstar_message(self, handler, gmail_state):
        with patch.object(
            handler, "_api_modify_labels", new_callable=AsyncMock, return_value={}
        ) as mock_api:
            result = await handler._star_message(gmail_state, "msg1", {"starred": False})
        assert _body(result)["is_starred"] is False
        assert mock_api.call_args[0][2] == []
        assert mock_api.call_args[0][3] == ["STARRED"]

    @pytest.mark.asyncio
    async def test_star_default_true(self, handler, gmail_state):
        with patch.object(handler, "_api_modify_labels", new_callable=AsyncMock, return_value={}):
            result = await handler._star_message(gmail_state, "msg1", {})
        assert _body(result)["is_starred"] is True

    @pytest.mark.asyncio
    async def test_star_api_error(self, handler, gmail_state):
        with patch.object(
            handler, "_api_modify_labels", new_callable=AsyncMock, side_effect=OSError("network")
        ):
            result = await handler._star_message(gmail_state, "msg1", {"starred": True})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_star_receipt_routes_to_inbox_wedge(self, handler, gmail_state):
        with patch(
            "aragora.server.handlers.inbox.email_actions.handle_star_message",
            new_callable=AsyncMock,
            return_value=json_response({"delegated": True}),
        ) as mock_handle:
            result = await handler._star_message(
                gmail_state, "msg1", {"starred": True, "receipt_id": "receipt-123"}
            )
        assert _status(result) == 200
        assert _body(result)["delegated"] is True
        mock_handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unstar_receipt_is_rejected(self, handler, gmail_state):
        result = await handler._star_message(
            gmail_state, "msg1", {"starred": False, "receipt_id": "receipt-123"}
        )
        assert _status(result) == 400
        assert "does not support gmail unstar receipts" in _body(result)["error"].lower()


# ---------------------------------------------------------------------------
# Private method: _archive_message
# ---------------------------------------------------------------------------


class TestArchiveMessage:
    """Tests for _archive_message (tested directly)."""

    @pytest.mark.asyncio
    async def test_archive_message(self, handler, gmail_state):
        with patch.object(
            handler, "_api_modify_labels", new_callable=AsyncMock, return_value={}
        ) as mock_api:
            result = await handler._archive_message(gmail_state, "msg1")
        assert _status(result) == 200
        body = _body(result)
        assert body["archived"] is True
        assert body["success"] is True
        assert body["message_id"] == "msg1"
        assert mock_api.call_args[0][2] == []
        assert mock_api.call_args[0][3] == ["INBOX"]

    @pytest.mark.asyncio
    async def test_archive_api_error(self, handler, gmail_state):
        with patch.object(
            handler,
            "_api_modify_labels",
            new_callable=AsyncMock,
            side_effect=ConnectionError("fail"),
        ):
            result = await handler._archive_message(gmail_state, "msg1")
        assert _status(result) == 500
        assert "archive" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_archive_receipt_routes_to_inbox_wedge(self, handler, gmail_state):
        with patch(
            "aragora.server.handlers.inbox.email_actions.handle_archive_message",
            new_callable=AsyncMock,
            return_value=json_response({"delegated": True}),
        ) as mock_handle:
            result = await handler._archive_message(
                gmail_state,
                "msg1",
                {"create_receipt": True, "confidence": 0.9},
            )
        assert _status(result) == 200
        assert _body(result)["delegated"] is True
        mock_handle.assert_awaited_once()


# ---------------------------------------------------------------------------
# Private method: _trash_message
# ---------------------------------------------------------------------------


class TestTrashMessage:
    """Tests for _trash_message (tested directly)."""

    @pytest.mark.asyncio
    async def test_trash_message(self, handler, gmail_state):
        with patch.object(handler, "_api_trash_message", new_callable=AsyncMock) as mock_trash:
            result = await handler._trash_message(gmail_state, "msg1", {"trash": True})
            mock_trash.assert_called_once()
        assert _status(result) == 200
        assert _body(result)["trashed"] is True

    @pytest.mark.asyncio
    async def test_untrash_message(self, handler, gmail_state):
        with patch.object(handler, "_api_untrash_message", new_callable=AsyncMock) as mock_untrash:
            result = await handler._trash_message(gmail_state, "msg1", {"trash": False})
            mock_untrash.assert_called_once()
        assert _status(result) == 200
        assert _body(result)["trashed"] is False

    @pytest.mark.asyncio
    async def test_trash_default_true(self, handler, gmail_state):
        with patch.object(handler, "_api_trash_message", new_callable=AsyncMock):
            result = await handler._trash_message(gmail_state, "msg1", {})
        assert _body(result)["trashed"] is True

    @pytest.mark.asyncio
    async def test_trash_api_error(self, handler, gmail_state):
        with patch.object(
            handler,
            "_api_trash_message",
            new_callable=AsyncMock,
            side_effect=ConnectionError("fail"),
        ):
            result = await handler._trash_message(gmail_state, "msg1", {"trash": True})
        assert _status(result) == 500
        assert "trash" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_untrash_api_error(self, handler, gmail_state):
        with patch.object(
            handler,
            "_api_untrash_message",
            new_callable=AsyncMock,
            side_effect=TimeoutError("timeout"),
        ):
            result = await handler._trash_message(gmail_state, "msg1", {"trash": False})
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_trash_message_id_in_response(self, handler, gmail_state):
        with patch.object(handler, "_api_trash_message", new_callable=AsyncMock):
            result = await handler._trash_message(gmail_state, "abc_def_123", {"trash": True})
        assert _body(result)["message_id"] == "abc_def_123"


# ---------------------------------------------------------------------------
# POST /api/v1/gmail/filters - Create filter
# ---------------------------------------------------------------------------


class TestCreateFilter:
    """Tests for POST /api/v1/gmail/filters."""

    @pytest.mark.asyncio
    async def test_create_filter_success(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body(
            {
                "criteria": {"from": "noreply@example.com"},
                "action": {"add_labels": ["Label_1"]},
            }
        )
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_create_filter",
                new_callable=AsyncMock,
                return_value={"id": "filter_1"},
            ):
                result = await handler.handle_post("/api/v1/gmail/filters", {}, http)
        assert _status(result) == 200
        assert _body(result)["success"] is True
        assert _body(result)["filter"]["id"] == "filter_1"

    @pytest.mark.asyncio
    async def test_create_filter_no_criteria(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({"criteria": {}, "action": {"add_labels": ["INBOX"]}})
        with _patch_user_state(gmail_state):
            result = await handler.handle_post("/api/v1/gmail/filters", {}, http)
        assert _status(result) == 400
        assert "criteria" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_create_filter_no_action(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({"criteria": {"from": "t@t.com"}, "action": {}})
        with _patch_user_state(gmail_state):
            result = await handler.handle_post("/api/v1/gmail/filters", {}, http)
        assert _status(result) == 400
        assert "action" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_create_filter_missing_both(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({})
        with _patch_user_state(gmail_state):
            result = await handler.handle_post("/api/v1/gmail/filters", {}, http)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_create_filter_api_error(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({"criteria": {"from": "x@x.com"}, "action": {"star": True}})
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_create_filter",
                new_callable=AsyncMock,
                side_effect=ValueError("bad filter"),
            ):
                result = await handler.handle_post("/api/v1/gmail/filters", {}, http)
        assert _status(result) == 500
        assert "creation failed" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_create_filter_no_state(self, handler, mock_http_with_body):
        http = mock_http_with_body({"criteria": {"from": "a@b.com"}, "action": {"star": True}})
        with _patch_user_state(None):
            result = await handler.handle_post("/api/v1/gmail/filters", {}, http)
        assert _status(result) == 401


# ---------------------------------------------------------------------------
# GET /api/v1/gmail/filters - List filters
# ---------------------------------------------------------------------------


class TestListFilters:
    """Tests for GET /api/v1/gmail/filters."""

    @pytest.mark.asyncio
    async def test_list_filters_success(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_list_filters",
                new_callable=AsyncMock,
                return_value=[{"id": "f1"}, {"id": "f2"}],
            ):
                result = await handler.handle("/api/v1/gmail/filters", {}, mock_http)
        assert _status(result) == 200
        body = _body(result)
        assert body["count"] == 2
        assert len(body["filters"]) == 2

    @pytest.mark.asyncio
    async def test_list_filters_empty(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state):
            with patch.object(
                handler, "_api_list_filters", new_callable=AsyncMock, return_value=[]
            ):
                result = await handler.handle("/api/v1/gmail/filters", {}, mock_http)
        assert _status(result) == 200
        assert _body(result)["count"] == 0
        assert _body(result)["filters"] == []

    @pytest.mark.asyncio
    async def test_list_filters_api_error(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_list_filters",
                new_callable=AsyncMock,
                side_effect=ConnectionError("API down"),
            ):
                result = await handler.handle("/api/v1/gmail/filters", {}, mock_http)
        assert _status(result) == 500
        assert "Failed to list filters" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_list_filters_no_state(self, handler, mock_http):
        with _patch_user_state(None):
            result = await handler.handle("/api/v1/gmail/filters", {}, mock_http)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_list_filters_timeout(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state):
            with patch.object(
                handler,
                "_api_list_filters",
                new_callable=AsyncMock,
                side_effect=TimeoutError("timeout"),
            ):
                result = await handler.handle("/api/v1/gmail/filters", {}, mock_http)
        assert _status(result) == 500


# ---------------------------------------------------------------------------
# DELETE /api/v1/gmail/filters/:id - Delete filter
# ---------------------------------------------------------------------------


class TestDeleteFilter:
    """Tests for DELETE /api/v1/gmail/filters/:id."""

    @pytest.mark.asyncio
    async def test_delete_filter_success(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state):
            with patch.object(handler, "_api_delete_filter", new_callable=AsyncMock):
                result = await handler.handle_delete("/api/v1/gmail/filters/f1", {}, mock_http)
        assert _status(result) == 200
        assert _body(result)["success"] is True
        assert _body(result)["deleted"] == "f1"

    @pytest.mark.asyncio
    async def test_delete_filter_api_error(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state):
            with patch.object(
                handler, "_api_delete_filter", new_callable=AsyncMock, side_effect=OSError("fail")
            ):
                result = await handler.handle_delete("/api/v1/gmail/filters/f1", {}, mock_http)
        assert _status(result) == 500
        assert "deletion failed" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_delete_filter_no_state(self, handler, mock_http):
        with _patch_user_state(None):
            result = await handler.handle_delete("/api/v1/gmail/filters/f1", {}, mock_http)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_delete_filter_id_extraction(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state):
            with patch.object(handler, "_api_delete_filter", new_callable=AsyncMock):
                result = await handler.handle_delete(
                    "/api/v1/gmail/filters/my_filter_xyz", {}, mock_http
                )
        assert _body(result)["deleted"] == "my_filter_xyz"


# ---------------------------------------------------------------------------
# POST routing edge cases
# ---------------------------------------------------------------------------


class TestPostRouting:
    """Tests for POST routing edge cases."""

    @pytest.mark.asyncio
    async def test_post_unknown_path(self, handler, mock_http_with_body, gmail_state):
        http = mock_http_with_body({})
        with _patch_user_state(gmail_state):
            result = await handler.handle_post("/api/v1/gmail/unknown", {}, http)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_post_invalid_json_body(self, handler, mock_http):
        with patch.object(handler, "read_json_body", return_value=None):
            result = await handler.handle_post("/api/v1/gmail/labels", {}, mock_http)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_post_no_refresh_token(
        self, handler, mock_http_with_body, gmail_state_no_refresh
    ):
        http = mock_http_with_body({"name": "Test"})
        with _patch_user_state(gmail_state_no_refresh):
            result = await handler.handle_post("/api/v1/gmail/labels", {}, http)
        assert _status(result) == 401


# ---------------------------------------------------------------------------
# GET routing edge cases
# ---------------------------------------------------------------------------


class TestGetRouting:
    """Tests for GET routing edge cases."""

    @pytest.mark.asyncio
    async def test_get_unknown_path(self, handler, mock_http, gmail_state):
        with _patch_user_state(gmail_state):
            result = await handler.handle("/api/v1/gmail/something", {}, mock_http)
        assert _status(result) == 404


# ---------------------------------------------------------------------------
# Auth/RBAC tests
# ---------------------------------------------------------------------------


class TestAuth:
    """Tests for authentication and permission handling."""

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_handle_unauthorized(self, mock_http):
        from aragora.server.handlers.secure import SecureHandler, UnauthorizedError

        h = GmailLabelsHandler(server_context={})
        with patch.object(
            SecureHandler,
            "get_auth_context",
            new_callable=AsyncMock,
            side_effect=UnauthorizedError("not auth"),
        ):
            result = await h.handle("/api/v1/gmail/labels", {}, mock_http)
        assert _status(result) == 401
        assert "Authentication required" in _body(result)["error"]

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_handle_forbidden(self, mock_http):
        from aragora.server.handlers.secure import ForbiddenError, SecureHandler
        from aragora.rbac.models import AuthorizationContext

        h = GmailLabelsHandler(server_context={})
        mock_ctx = AuthorizationContext(
            user_id="u1", user_email="u@e.com", roles={"viewer"}, permissions=set()
        )
        with patch.object(
            SecureHandler, "get_auth_context", new_callable=AsyncMock, return_value=mock_ctx
        ):
            with patch.object(
                SecureHandler, "check_permission", side_effect=ForbiddenError("no perm")
            ):
                result = await h.handle("/api/v1/gmail/labels", {}, mock_http)
        assert _status(result) == 403
        assert "Permission denied" in _body(result)["error"]

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_handle_post_unauthorized(self, mock_http_with_body):
        from aragora.server.handlers.secure import SecureHandler, UnauthorizedError

        h = GmailLabelsHandler(server_context={})
        http = mock_http_with_body({"name": "Test"})
        with patch.object(
            SecureHandler,
            "get_auth_context",
            new_callable=AsyncMock,
            side_effect=UnauthorizedError("not auth"),
        ):
            result = await h.handle_post("/api/v1/gmail/labels", {}, http)
        assert _status(result) == 401

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_handle_post_forbidden(self, mock_http_with_body):
        from aragora.server.handlers.secure import ForbiddenError, SecureHandler
        from aragora.rbac.models import AuthorizationContext

        h = GmailLabelsHandler(server_context={})
        http = mock_http_with_body({"name": "Test"})
        mock_ctx = AuthorizationContext(
            user_id="u1", user_email="u@e.com", roles={"viewer"}, permissions=set()
        )
        with patch.object(
            SecureHandler, "get_auth_context", new_callable=AsyncMock, return_value=mock_ctx
        ):
            with patch.object(
                SecureHandler, "check_permission", side_effect=ForbiddenError("no perm")
            ):
                result = await h.handle_post("/api/v1/gmail/labels", {}, http)
        assert _status(result) == 403

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_handle_patch_unauthorized(self, mock_http_with_body):
        from aragora.server.handlers.secure import SecureHandler, UnauthorizedError

        h = GmailLabelsHandler(server_context={})
        http = mock_http_with_body({"name": "Update"})
        with patch.object(
            SecureHandler,
            "get_auth_context",
            new_callable=AsyncMock,
            side_effect=UnauthorizedError("not auth"),
        ):
            result = await h.handle_patch("/api/v1/gmail/labels/L1", {}, http)
        assert _status(result) == 401

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_handle_patch_forbidden(self, mock_http_with_body):
        from aragora.server.handlers.secure import ForbiddenError, SecureHandler
        from aragora.rbac.models import AuthorizationContext

        h = GmailLabelsHandler(server_context={})
        http = mock_http_with_body({"name": "Update"})
        mock_ctx = AuthorizationContext(
            user_id="u1", user_email="u@e.com", roles={"viewer"}, permissions=set()
        )
        with patch.object(
            SecureHandler, "get_auth_context", new_callable=AsyncMock, return_value=mock_ctx
        ):
            with patch.object(
                SecureHandler, "check_permission", side_effect=ForbiddenError("no perm")
            ):
                result = await h.handle_patch("/api/v1/gmail/labels/L1", {}, http)
        assert _status(result) == 403

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_handle_delete_unauthorized(self, mock_http):
        from aragora.server.handlers.secure import SecureHandler, UnauthorizedError

        h = GmailLabelsHandler(server_context={})
        with patch.object(
            SecureHandler,
            "get_auth_context",
            new_callable=AsyncMock,
            side_effect=UnauthorizedError("not auth"),
        ):
            result = await h.handle_delete("/api/v1/gmail/labels/L1", {}, mock_http)
        assert _status(result) == 401

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_handle_delete_forbidden(self, mock_http):
        from aragora.server.handlers.secure import ForbiddenError, SecureHandler
        from aragora.rbac.models import AuthorizationContext

        h = GmailLabelsHandler(server_context={})
        mock_ctx = AuthorizationContext(
            user_id="u1", user_email="u@e.com", roles={"viewer"}, permissions=set()
        )
        with patch.object(
            SecureHandler, "get_auth_context", new_callable=AsyncMock, return_value=mock_ctx
        ):
            with patch.object(
                SecureHandler, "check_permission", side_effect=ForbiddenError("no perm")
            ):
                result = await h.handle_delete("/api/v1/gmail/labels/L1", {}, mock_http)
        assert _status(result) == 403


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestInit:
    """Tests for handler initialization."""

    def test_init_with_server_context(self):
        h = GmailLabelsHandler(server_context={"key": "val"})
        assert h.ctx == {"key": "val"}

    def test_init_with_ctx(self):
        h = GmailLabelsHandler(ctx={"other": 1})
        assert h.ctx == {"other": 1}

    def test_init_empty(self):
        h = GmailLabelsHandler()
        assert h.ctx == {}

    def test_init_server_context_overrides_ctx(self):
        h = GmailLabelsHandler(ctx={"a": 1}, server_context={"b": 2})
        assert h.ctx == {"b": 2}

    def test_routes(self):
        h = GmailLabelsHandler(server_context={})
        assert "/api/v1/gmail/labels" in h.ROUTES
        assert "/api/v1/gmail/filters" in h.ROUTES

    def test_route_prefixes(self):
        h = GmailLabelsHandler(server_context={})
        assert "/api/v1/gmail/labels/" in h.ROUTE_PREFIXES
        assert "/api/v1/gmail/messages/" in h.ROUTE_PREFIXES
        assert "/api/v1/gmail/filters/" in h.ROUTE_PREFIXES


# ---------------------------------------------------------------------------
# _api_create_filter criteria/action mapping
# ---------------------------------------------------------------------------


class TestApiCreateFilterMapping:
    """Tests verifying _api_create_filter correctly maps criteria and action fields."""

    @pytest.mark.asyncio
    async def test_filter_criteria_all_fields(self, handler, gmail_state):
        mock_pool, mock_session, mock_response = _mock_http_pool()
        mock_response.json.return_value = {"id": "f1"}

        criteria = {
            "from": "a@b.com",
            "to": "c@d.com",
            "subject": "test",
            "query": "is:important",
            "has_attachment": True,
            "exclude_chats": True,
            "size": 1000,
            "size_comparison": "smaller",
        }
        action = {
            "add_labels": ["L1"],
            "remove_labels": ["L2"],
            "star": True,
            "important": True,
            "archive": True,
            "delete": True,
            "mark_read": True,
            "forward": "fwd@test.com",
        }

        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            result = await handler._api_create_filter(gmail_state, criteria, action)

        assert result == {"id": "f1"}
        posted = mock_session.post.call_args[1]["json"]
        # Criteria
        assert posted["criteria"]["from"] == "a@b.com"
        assert posted["criteria"]["to"] == "c@d.com"
        assert posted["criteria"]["subject"] == "test"
        assert posted["criteria"]["query"] == "is:important"
        assert posted["criteria"]["hasAttachment"] is True
        assert posted["criteria"]["excludeChats"] is True
        assert posted["criteria"]["size"] == 1000
        assert posted["criteria"]["sizeComparison"] == "smaller"
        # Action
        act = posted["action"]
        assert "L1" in act["addLabelIds"]
        assert "STARRED" in act["addLabelIds"]
        assert "IMPORTANT" in act["addLabelIds"]
        assert "TRASH" in act["addLabelIds"]
        assert "L2" in act["removeLabelIds"]
        assert "INBOX" in act["removeLabelIds"]
        assert "UNREAD" in act["removeLabelIds"]
        assert act["forward"] == "fwd@test.com"

    @pytest.mark.asyncio
    async def test_filter_size_default_comparison(self, handler, gmail_state):
        mock_pool, mock_session, mock_response = _mock_http_pool()
        mock_response.json.return_value = {"id": "f2"}

        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_create_filter(gmail_state, {"size": 500}, {"star": True})

        posted = mock_session.post.call_args[1]["json"]
        assert posted["criteria"]["sizeComparison"] == "larger"

    @pytest.mark.asyncio
    async def test_filter_minimal_criteria(self, handler, gmail_state):
        mock_pool, mock_session, mock_response = _mock_http_pool()
        mock_response.json.return_value = {"id": "f3"}

        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_create_filter(gmail_state, {"from": "x@y.com"}, {"star": True})

        posted = mock_session.post.call_args[1]["json"]
        assert posted["criteria"] == {"from": "x@y.com"}
        assert "STARRED" in posted["action"]["addLabelIds"]


# ---------------------------------------------------------------------------
# _api_create_label / _api_update_label mapping
# ---------------------------------------------------------------------------


class TestApiLabelMapping:
    """Tests for label API mapping details."""

    @pytest.mark.asyncio
    async def test_create_label_with_color(self, handler, gmail_state):
        mock_pool, mock_session, mock_response = _mock_http_pool()
        mock_response.json.return_value = {"id": "L1", "name": "Colored"}

        options = {
            "name": "Colored",
            "background_color": "#ff0000",
            "text_color": "#00ff00",
            "label_list_visibility": "labelHide",
            "message_list_visibility": "hide",
        }
        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_create_label(gmail_state, "Colored", options)

        posted = mock_session.post.call_args[1]["json"]
        assert posted["name"] == "Colored"
        assert posted["labelListVisibility"] == "labelHide"
        assert posted["messageListVisibility"] == "hide"
        assert posted["color"]["backgroundColor"] == "#ff0000"
        assert posted["color"]["textColor"] == "#00ff00"

    @pytest.mark.asyncio
    async def test_create_label_default_visibility(self, handler, gmail_state):
        mock_pool, mock_session, mock_response = _mock_http_pool()
        mock_response.json.return_value = {"id": "L2"}

        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_create_label(gmail_state, "Simple", {})

        posted = mock_session.post.call_args[1]["json"]
        assert posted["labelListVisibility"] == "labelShow"
        assert posted["messageListVisibility"] == "show"
        assert "color" not in posted

    @pytest.mark.asyncio
    async def test_create_label_only_bg_color(self, handler, gmail_state):
        mock_pool, mock_session, mock_response = _mock_http_pool()
        mock_response.json.return_value = {"id": "L3"}

        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_create_label(gmail_state, "Test", {"background_color": "#aaa"})

        posted = mock_session.post.call_args[1]["json"]
        assert posted["color"]["backgroundColor"] == "#aaa"
        assert posted["color"]["textColor"] == "#ffffff"  # default

    @pytest.mark.asyncio
    async def test_update_label_partial(self, handler, gmail_state):
        mock_pool, mock_session, mock_response = _mock_http_pool()
        mock_response.json.return_value = {"id": "L1", "name": "New"}

        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_update_label(gmail_state, "L1", {"name": "New"})

        posted = mock_session.patch.call_args[1]["json"]
        assert posted == {"name": "New"}

    @pytest.mark.asyncio
    async def test_update_label_with_color(self, handler, gmail_state):
        mock_pool, mock_session, mock_response = _mock_http_pool()
        mock_response.json.return_value = {"id": "L1"}

        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_update_label(gmail_state, "L1", {"background_color": "#aabbcc"})

        posted = mock_session.patch.call_args[1]["json"]
        assert posted["color"]["backgroundColor"] == "#aabbcc"
        assert posted["color"]["textColor"] == "#ffffff"  # default

    @pytest.mark.asyncio
    async def test_update_label_visibility(self, handler, gmail_state):
        mock_pool, mock_session, mock_response = _mock_http_pool()
        mock_response.json.return_value = {"id": "L1"}

        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_update_label(
                gmail_state,
                "L1",
                {"label_list_visibility": "labelHide", "message_list_visibility": "hide"},
            )

        posted = mock_session.patch.call_args[1]["json"]
        assert posted["labelListVisibility"] == "labelHide"
        assert posted["messageListVisibility"] == "hide"


# ---------------------------------------------------------------------------
# _api_delete_label / _api_delete_filter
# ---------------------------------------------------------------------------


class TestApiDelete:
    """Tests for delete API calls."""

    @pytest.mark.asyncio
    async def test_delete_label_api_url(self, handler, gmail_state):
        mock_pool, mock_session, _ = _mock_http_pool()
        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_delete_label(gmail_state, "Label_42")
        url = mock_session.delete.call_args[0][0]
        assert "labels/Label_42" in url

    @pytest.mark.asyncio
    async def test_delete_filter_api_url(self, handler, gmail_state):
        mock_pool, mock_session, _ = _mock_http_pool()
        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_delete_filter(gmail_state, "filter_99")
        url = mock_session.delete.call_args[0][0]
        assert "filters/filter_99" in url


# ---------------------------------------------------------------------------
# _api_list_filters
# ---------------------------------------------------------------------------


class TestApiListFilters:
    """Tests for _api_list_filters response parsing."""

    @pytest.mark.asyncio
    async def test_list_filters_parses_filter_key(self, handler, gmail_state):
        mock_pool, mock_session, mock_response = _mock_http_pool()
        mock_response.json.return_value = {"filter": [{"id": "f1"}, {"id": "f2"}]}
        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            result = await handler._api_list_filters(gmail_state)
        assert len(result) == 2
        assert result[0]["id"] == "f1"

    @pytest.mark.asyncio
    async def test_list_filters_empty_response(self, handler, gmail_state):
        mock_pool, mock_session, mock_response = _mock_http_pool()
        mock_response.json.return_value = {}
        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            result = await handler._api_list_filters(gmail_state)
        assert result == []


# ---------------------------------------------------------------------------
# _api_modify_labels
# ---------------------------------------------------------------------------


class TestApiModifyLabels:
    """Tests for _api_modify_labels API call."""

    @pytest.mark.asyncio
    async def test_modify_labels_api_call(self, handler, gmail_state):
        mock_pool, mock_session, mock_response = _mock_http_pool()
        mock_response.json.return_value = {"labelIds": ["INBOX", "STARRED"]}
        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            result = await handler._api_modify_labels(
                gmail_state, "msg_abc", ["STARRED"], ["UNREAD"]
            )
        assert result["labelIds"] == ["INBOX", "STARRED"]
        posted = mock_session.post.call_args[1]["json"]
        assert posted["addLabelIds"] == ["STARRED"]
        assert posted["removeLabelIds"] == ["UNREAD"]
        assert "msg_abc/modify" in mock_session.post.call_args[0][0]


# ---------------------------------------------------------------------------
# _api_trash_message / _api_untrash_message
# ---------------------------------------------------------------------------


class TestApiTrashUntrash:
    """Tests for trash/untrash API calls."""

    @pytest.mark.asyncio
    async def test_api_trash_url(self, handler, gmail_state):
        mock_pool, mock_session, _ = _mock_http_pool()
        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_trash_message(gmail_state, "msg_xyz")
        assert "msg_xyz/trash" in mock_session.post.call_args[0][0]

    @pytest.mark.asyncio
    async def test_api_untrash_url(self, handler, gmail_state):
        mock_pool, mock_session, _ = _mock_http_pool()
        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_untrash_message(gmail_state, "msg_xyz")
        assert "msg_xyz/untrash" in mock_session.post.call_args[0][0]

    @pytest.mark.asyncio
    async def test_api_trash_auth_header(self, handler, gmail_state):
        mock_pool, mock_session, _ = _mock_http_pool()
        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_trash_message(gmail_state, "msg1")
        headers = mock_session.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer test-access-token"

    @pytest.mark.asyncio
    async def test_api_untrash_auth_header(self, handler, gmail_state):
        mock_pool, mock_session, _ = _mock_http_pool()
        with patch("aragora.server.http_client_pool.get_http_pool", return_value=mock_pool):
            await handler._api_untrash_message(gmail_state, "msg1")
        headers = mock_session.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer test-access-token"
