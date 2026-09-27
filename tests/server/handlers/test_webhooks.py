"""
Tests for WebhookHandler - Webhook management HTTP endpoints.

Tests cover:
- Route registration and can_handle
- POST /api/v1/webhooks (register webhook)
- GET /api/v1/webhooks (list webhooks)
- GET /api/v1/webhooks/:id (get specific webhook)
- DELETE /api/v1/webhooks/:id (delete webhook)
- PATCH /api/v1/webhooks/:id (update webhook)
- POST /api/v1/webhooks/:id/test (send test event)
- GET /api/v1/webhooks/events (list event types)
- GET /api/v1/webhooks/slo/status (SLO status)
- POST /api/v1/webhooks/slo/test (test SLO notification)
- Dead-letter queue endpoints
- RBAC permission checks
- Error cases (missing params, not found, invalid input)
- Signature generation and verification utilities
- Edge cases (ownership checks, wildcard events)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from aragora.server.handlers.webhook_management import (
    WebhookHandler,
    generate_signature,
    verify_signature,
)
from aragora.storage.webhook_config_store import (
    WEBHOOK_EVENTS,
    WebhookConfig,
)
import builtins


# ===========================================================================
# Test Fixtures and Mocks
# ===========================================================================


def _make_webhook(
    webhook_id: str = "wh-001",
    url: str = "https://example.com/hook",
    events: list[str] | None = None,
    secret: str = "test-secret-key",
    active: bool = True,
    user_id: str | None = "user-1",
    workspace_id: str | None = None,
    name: str | None = "Test Webhook",
    description: str | None = "A test webhook",
) -> WebhookConfig:
    """Create a WebhookConfig for testing."""
    return WebhookConfig(
        id=webhook_id,
        url=url,
        events=events or ["debate_end"],
        secret=secret,
        active=active,
        user_id=user_id,
        workspace_id=workspace_id,
        name=name,
        description=description,
        created_at=time.time(),
        updated_at=time.time(),
    )


@dataclass
class MockUser:
    """Mock user auth context."""

    user_id: str = "user-1"
    role: str = "admin"
    org_id: str | None = None


class MockWebhookStore:
    """Mock webhook config store for testing."""

    def __init__(self):
        self._webhooks: dict[str, WebhookConfig] = {}

    def register(
        self,
        url: str,
        events: builtins.list[str],
        name: str | None = None,
        description: str | None = None,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> WebhookConfig:
        webhook = _make_webhook(
            webhook_id=f"wh-{len(self._webhooks) + 1:03d}",
            url=url,
            events=events,
            name=name,
            description=description,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        self._webhooks[webhook.id] = webhook
        return webhook

    def get(self, webhook_id: str) -> WebhookConfig | None:
        return self._webhooks.get(webhook_id)

    def list(
        self,
        user_id: str | None = None,
        workspace_id: str | None = None,
        active_only: bool = False,
    ) -> builtins.list[WebhookConfig]:
        result = list(self._webhooks.values())
        if user_id:
            result = [w for w in result if w.user_id == user_id]
        if workspace_id:
            result = [w for w in result if w.workspace_id == workspace_id]
        if active_only:
            result = [w for w in result if w.active]
        return result

    def delete(self, webhook_id: str) -> bool:
        if webhook_id in self._webhooks:
            del self._webhooks[webhook_id]
            return True
        return False

    def update(
        self,
        webhook_id: str,
        url: str | None = None,
        events: builtins.list[str] | None = None,
        active: bool | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> WebhookConfig:
        webhook = self._webhooks[webhook_id]
        if url is not None:
            webhook.url = url
        if events is not None:
            webhook.events = events
        if active is not None:
            webhook.active = active
        if name is not None:
            webhook.name = name
        if description is not None:
            webhook.description = description
        webhook.updated_at = time.time()
        return webhook


def _make_handler_instance(
    webhook_store: MockWebhookStore | None = None,
) -> WebhookHandler:
    """Create a WebhookHandler with mocked dependencies."""
    store = webhook_store or MockWebhookStore()
    ctx: dict[str, Any] = {"webhook_store": store}
    handler = WebhookHandler(ctx)  # type: ignore[arg-type]
    return handler


def _make_mock_http_handler(user: MockUser | None = None) -> MagicMock:
    """Create a mock HTTP handler (simulates the request handler object)."""
    mock = MagicMock()
    mock.headers = {"Content-Type": "application/json"}
    mock._user = user
    return mock


def _parse_result(result) -> tuple[int, dict]:
    """Parse a HandlerResult into (status_code, body_dict)."""
    return result.status_code, json.loads(result.body)


# ===========================================================================
# Signature Utility Tests
# ===========================================================================


class TestSignatureUtilities:
    """Tests for HMAC-SHA256 signature generation and verification."""

    def test_generate_signature_returns_sha256_prefix(self):
        sig = generate_signature("payload", "secret")
        assert sig.startswith("sha256=")

    def test_generate_signature_deterministic(self):
        sig1 = generate_signature("payload", "secret")
        sig2 = generate_signature("payload", "secret")
        assert sig1 == sig2

    def test_generate_signature_differs_with_different_payload(self):
        sig1 = generate_signature("payload-a", "secret")
        sig2 = generate_signature("payload-b", "secret")
        assert sig1 != sig2

    def test_generate_signature_differs_with_different_secret(self):
        sig1 = generate_signature("payload", "secret-a")
        sig2 = generate_signature("payload", "secret-b")
        assert sig1 != sig2

    def test_verify_signature_valid(self):
        sig = generate_signature("test-payload", "my-secret")
        assert verify_signature("test-payload", sig, "my-secret") is True

    def test_verify_signature_invalid(self):
        assert verify_signature("payload", "sha256=invalid", "secret") is False

    def test_verify_signature_wrong_secret(self):
        sig = generate_signature("payload", "correct-secret")
        assert verify_signature("payload", sig, "wrong-secret") is False


# ===========================================================================
# Route Registration and can_handle Tests
# ===========================================================================


class TestRouteRegistration:
    """Tests for route registration and can_handle."""

    def test_can_handle_webhooks_root(self):
        assert WebhookHandler.can_handle("/api/v1/webhooks") is True

    def test_can_handle_webhooks_subpath(self):
        assert WebhookHandler.can_handle("/api/v1/webhooks/events") is True
        assert WebhookHandler.can_handle("/api/v1/webhooks/wh-001") is True
        assert WebhookHandler.can_handle("/api/v1/webhooks/wh-001/test") is True

    def test_can_handle_durable_canary_alias(self):
        assert WebhookHandler.can_handle("/api/v1/webhook-configs") is True
        assert WebhookHandler.can_handle("/api/v1/webhook-configs/wh-001") is True
        assert WebhookHandler._normalize_path("/api/v1/webhook-configs/wh-001") == (
            "/api/v1/webhooks/wh-001"
        )
        assert not any(
            route.startswith("/api/v1/webhook-configs") for route in WebhookHandler.ROUTES
        )

    def test_can_handle_rejects_non_webhook_path(self):
        assert WebhookHandler.can_handle("/api/v1/debates") is False
        assert WebhookHandler.can_handle("/api/v1/backups") is False
        assert WebhookHandler.can_handle("/api/webhooks") is False

    def test_routes_class_attribute_defined(self):
        assert hasattr(WebhookHandler, "routes")
        assert len(WebhookHandler.routes) > 0

    def test_routes_include_expected_endpoints(self):
        route_strs = WebhookHandler.routes
        assert "POST /api/webhooks" in route_strs
        assert "GET /api/webhooks" in route_strs
        assert "GET /api/webhooks/events" in route_strs
        assert "DELETE /api/webhooks/:id" in route_strs
        assert "PATCH /api/webhooks/:id" in route_strs
        assert "POST /api/webhooks/:id/test" in route_strs

    def test_resource_type_is_webhook(self):
        assert WebhookHandler.RESOURCE_TYPE == "webhook"


# ===========================================================================
# GET /api/v1/webhooks/events Tests
# ===========================================================================


class TestListEvents:
    """Tests for GET /api/v1/webhooks/events."""

    @pytest.fixture
    def handler(self):
        h = _make_handler_instance()
        # Disable RBAC for these tests
        h._check_rbac_permission = MagicMock(return_value=None)
        return h

    @pytest.mark.asyncio
    async def test_list_events_returns_sorted_events(self, handler):
        result = await handler.handle("/api/v1/webhooks/events", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 200
        assert "events" in body
        assert body["events"] == sorted(body["events"])
        assert body["count"] == len(WEBHOOK_EVENTS)

    @pytest.mark.asyncio
    async def test_list_events_includes_descriptions(self, handler):
        result = await handler.handle("/api/v1/webhooks/events", {}, _make_mock_http_handler())
        _, body = _parse_result(result)
        assert "description" in body
        assert "debate_start" in body["description"]
        assert "debate_end" in body["description"]

    @pytest.mark.asyncio
    async def test_list_events_count_matches(self, handler):
        result = await handler.handle("/api/v1/webhooks/events", {}, _make_mock_http_handler())
        _, body = _parse_result(result)
        assert body["count"] == len(body["events"])


# ===========================================================================
# GET /api/v1/webhooks Tests
# ===========================================================================


class TestListWebhooks:
    """Tests for GET /api/v1/webhooks."""

    @pytest.fixture
    def store(self):
        s = MockWebhookStore()
        s.register(url="https://a.com/hook", events=["debate_end"], user_id="user-1")
        s.register(url="https://b.com/hook", events=["consensus"], user_id="user-1")
        return s

    @pytest.fixture
    def handler(self, store):
        h = _make_handler_instance(webhook_store=store)
        h._check_rbac_permission = MagicMock(return_value=None)
        h.get_current_user = MagicMock(return_value=MockUser(user_id="user-1"))
        return h

    @pytest.mark.asyncio
    async def test_list_webhooks_returns_all(self, handler):
        result = await handler.handle("/api/v1/webhooks", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 200
        assert body["count"] == 2
        assert len(body["webhooks"]) == 2

    @pytest.mark.asyncio
    async def test_list_webhooks_excludes_secret(self, handler):
        result = await handler.handle("/api/v1/webhooks", {}, _make_mock_http_handler())
        _, body = _parse_result(result)
        for wh in body["webhooks"]:
            assert "secret" not in wh

    @pytest.mark.asyncio
    async def test_list_webhooks_active_only(self, handler, store):
        # Make one webhook inactive
        store.update(webhook_id="wh-001", active=False)
        result = await handler.handle(
            "/api/v1/webhooks",
            {"active_only": ["true"]},
            _make_mock_http_handler(),
        )
        _, body = _parse_result(result)
        assert body["count"] == 1


# ===========================================================================
# GET /api/v1/webhooks/:id Tests
# ===========================================================================


class TestGetWebhook:
    """Tests for GET /api/v1/webhooks/:id."""

    @pytest.fixture
    def store(self):
        s = MockWebhookStore()
        s.register(url="https://a.com/hook", events=["debate_end"], user_id="user-1")
        return s

    @pytest.fixture
    def handler(self, store):
        h = _make_handler_instance(webhook_store=store)
        h._check_rbac_permission = MagicMock(return_value=None)
        h.get_current_user = MagicMock(return_value=MockUser(user_id="user-1"))
        return h

    @pytest.mark.asyncio
    async def test_get_webhook_found(self, handler):
        result = await handler.handle("/api/v1/webhooks/wh-001", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 200
        assert body["webhook"]["id"] == "wh-001"

    @pytest.mark.asyncio
    async def test_get_webhook_not_found(self, handler):
        result = await handler.handle("/api/v1/webhooks/nonexistent", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 404

    @pytest.mark.asyncio
    async def test_get_webhook_excludes_secret(self, handler):
        result = await handler.handle("/api/v1/webhooks/wh-001", {}, _make_mock_http_handler())
        _, body = _parse_result(result)
        assert "secret" not in body["webhook"]

    @pytest.mark.asyncio
    async def test_get_webhook_access_denied_different_user(self, handler):
        handler.get_current_user = MagicMock(return_value=MockUser(user_id="other-user"))
        result = await handler.handle("/api/v1/webhooks/wh-001", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 404


# ===========================================================================
# POST /api/v1/webhooks Tests
# ===========================================================================


class TestRegisterWebhook:
    """Tests for POST /api/v1/webhooks (register new webhook)."""

    @pytest.fixture
    def handler(self):
        h = _make_handler_instance()
        h._check_rbac_permission = MagicMock(return_value=None)
        h.get_current_user = MagicMock(return_value=MockUser(user_id="user-1"))
        return h

    def _mock_body(self, handler_inst, body: dict):
        """Mock read_json_body_validated to return the given body."""
        handler_inst.read_json_body_validated = MagicMock(return_value=(body, None))

    @pytest.mark.asyncio
    @patch(
        "aragora.server.handlers.webhook_management.validate_webhook_url",
        return_value=(True, ""),
    )
    async def test_register_webhook_success(self, mock_validate, handler):
        self._mock_body(
            handler,
            {
                "url": "https://example.com/hook",
                "events": ["debate_end"],
                "name": "My Webhook",
            },
        )
        result = await handler.handle_post("/api/v1/webhooks", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 201
        assert "webhook" in body
        assert body["webhook"]["url"] == "https://example.com/hook"
        assert "secret" in body["webhook"]  # Secret shown on creation
        assert "message" in body

    @pytest.mark.asyncio
    @patch(
        "aragora.server.handlers.webhook_management.validate_webhook_url",
        return_value=(True, ""),
    )
    async def test_durable_alias_registers_canary_probe(self, mock_validate, handler):
        self._mock_body(
            handler,
            {
                "url": "https://example.com/canary-probe",
                "events": ["canary_probe"],
                "name": "Canary probe",
            },
        )

        result = await handler.handle_post("/api/v1/webhook-configs", {}, _make_mock_http_handler())

        status, body = _parse_result(result)
        assert status == 201
        assert body["webhook"]["url"] == "https://example.com/canary-probe"
        webhook = handler._get_webhook_store().get(body["webhook"]["id"])
        assert webhook is not None
        assert webhook.url == "https://example.com/canary-probe"
        assert webhook.events == ["canary_probe"]
        assert webhook.name == "Canary probe"
        mock_validate.assert_called_once_with(
            "https://example.com/canary-probe", allow_localhost=False
        )

    @pytest.mark.asyncio
    async def test_register_webhook_missing_url(self, handler):
        self._mock_body(handler, {"events": ["debate_end"]})
        result = await handler.handle_post("/api/v1/webhooks", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 400

    @pytest.mark.asyncio
    async def test_register_webhook_empty_url(self, handler):
        self._mock_body(handler, {"url": "  ", "events": ["debate_end"]})
        result = await handler.handle_post("/api/v1/webhooks", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 400

    @pytest.mark.asyncio
    @patch(
        "aragora.server.handlers.webhook_management.validate_webhook_url",
        return_value=(True, ""),
    )
    async def test_register_webhook_missing_events(self, mock_validate, handler):
        self._mock_body(handler, {"url": "https://example.com/hook"})
        result = await handler.handle_post("/api/v1/webhooks", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 400

    @pytest.mark.asyncio
    @patch(
        "aragora.server.handlers.webhook_management.validate_webhook_url",
        return_value=(True, ""),
    )
    async def test_register_webhook_invalid_event_type(self, mock_validate, handler):
        self._mock_body(
            handler,
            {
                "url": "https://example.com/hook",
                "events": ["nonexistent_event"],
            },
        )
        result = await handler.handle_post("/api/v1/webhooks", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 400
        assert "Invalid event types" in body.get("error", body.get("message", ""))

    @pytest.mark.asyncio
    @patch(
        "aragora.server.handlers.webhook_management.validate_webhook_url",
        return_value=(True, ""),
    )
    async def test_register_webhook_wildcard_event(self, mock_validate, handler):
        self._mock_body(
            handler,
            {
                "url": "https://example.com/hook",
                "events": ["*"],
            },
        )
        result = await handler.handle_post("/api/v1/webhooks", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 201

    @pytest.mark.asyncio
    @patch(
        "aragora.server.handlers.webhook_management.validate_webhook_url",
        return_value=(False, "URL resolves to private IP"),
    )
    async def test_register_webhook_ssrf_rejected(self, mock_validate, handler):
        self._mock_body(
            handler,
            {
                "url": "http://169.254.169.254/metadata",
                "events": ["debate_end"],
            },
        )
        result = await handler.handle_post("/api/v1/webhooks", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 400
        assert "Invalid webhook URL" in body.get("error", body.get("message", ""))

    @pytest.mark.asyncio
    async def test_register_webhook_body_parse_error(self, handler):
        """When read_json_body_validated returns an error."""
        from aragora.server.handlers.utils.responses import error_response

        err = error_response("Invalid JSON", 400)
        handler.read_json_body_validated = MagicMock(return_value=(None, err))
        result = await handler.handle_post("/api/v1/webhooks", {}, _make_mock_http_handler())
        status, _ = _parse_result(result)
        assert status == 400


# ===========================================================================
# DELETE /api/v1/webhooks/:id Tests
# ===========================================================================


class TestDeleteWebhook:
    """Tests for DELETE /api/v1/webhooks/:id."""

    @pytest.fixture
    def store(self):
        s = MockWebhookStore()
        s.register(url="https://a.com/hook", events=["debate_end"], user_id="user-1")
        return s

    @pytest.fixture
    def handler(self, store):
        h = _make_handler_instance(webhook_store=store)
        h._check_rbac_permission = MagicMock(return_value=None)
        h.get_current_user = MagicMock(return_value=MockUser(user_id="user-1"))
        return h

    @pytest.mark.asyncio
    async def test_delete_webhook_success(self, handler, store):
        result = await handler.handle_delete(
            "/api/v1/webhooks/wh-001", {}, _make_mock_http_handler()
        )
        status, body = _parse_result(result)
        assert status == 200
        assert body["deleted"] is True
        assert body["webhook_id"] == "wh-001"
        assert store.get("wh-001") is None

    @pytest.mark.asyncio
    async def test_delete_webhook_not_found(self, handler):
        result = await handler.handle_delete(
            "/api/v1/webhooks/nonexistent", {}, _make_mock_http_handler()
        )
        status, _ = _parse_result(result)
        assert status == 404

    @pytest.mark.asyncio
    async def test_delete_webhook_access_denied(self, handler):
        handler.get_current_user = MagicMock(return_value=MockUser(user_id="other-user"))
        result = await handler.handle_delete(
            "/api/v1/webhooks/wh-001", {}, _make_mock_http_handler()
        )
        status, _ = _parse_result(result)
        assert status == 404


# ===========================================================================
# PATCH /api/v1/webhooks/:id Tests
# ===========================================================================


class TestUpdateWebhook:
    """Tests for PATCH /api/v1/webhooks/:id."""

    @pytest.fixture
    def store(self):
        s = MockWebhookStore()
        s.register(url="https://a.com/hook", events=["debate_end"], user_id="user-1")
        return s

    @pytest.fixture
    def handler(self, store):
        h = _make_handler_instance(webhook_store=store)
        h._check_rbac_permission = MagicMock(return_value=None)
        h.get_current_user = MagicMock(return_value=MockUser(user_id="user-1"))
        return h

    def _mock_body(self, handler_inst, body: dict):
        handler_inst.read_json_body_validated = MagicMock(return_value=(body, None))

    @patch(
        "aragora.server.handlers.webhook_management.validate_webhook_url",
        return_value=(True, ""),
    )
    def test_update_webhook_url(self, mock_validate, handler):
        self._mock_body(handler, {"url": "https://new.example.com/hook"})
        result = handler.handle_patch("/api/v1/webhooks/wh-001", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 200
        assert body["webhook"]["url"] == "https://new.example.com/hook"

    def test_update_webhook_name(self, handler):
        self._mock_body(handler, {"name": "Renamed"})
        result = handler.handle_patch("/api/v1/webhooks/wh-001", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 200
        assert body["webhook"]["name"] == "Renamed"

    def test_update_webhook_not_found(self, handler):
        self._mock_body(handler, {"name": "X"})
        result = handler.handle_patch("/api/v1/webhooks/nonexistent", {}, _make_mock_http_handler())
        status, _ = _parse_result(result)
        assert status == 404

    def test_update_webhook_access_denied(self, handler):
        handler.get_current_user = MagicMock(return_value=MockUser(user_id="other-user"))
        self._mock_body(handler, {"name": "X"})
        result = handler.handle_patch("/api/v1/webhooks/wh-001", {}, _make_mock_http_handler())
        status, _ = _parse_result(result)
        assert status == 404

    def test_update_webhook_invalid_events(self, handler):
        self._mock_body(handler, {"events": ["invalid_event_xyz"]})
        result = handler.handle_patch("/api/v1/webhooks/wh-001", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 400
        assert "Invalid event types" in body.get("error", body.get("message", ""))

    @patch(
        "aragora.server.handlers.webhook_management.validate_webhook_url",
        return_value=(False, "URL resolves to private IP"),
    )
    def test_update_webhook_ssrf_url_rejected(self, mock_validate, handler):
        self._mock_body(handler, {"url": "http://10.0.0.1/internal"})
        result = handler.handle_patch("/api/v1/webhooks/wh-001", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 400
        assert "Invalid webhook URL" in body.get("error", body.get("message", ""))


# ===========================================================================
# POST /api/v1/webhooks/:id/test Tests
# ===========================================================================


class TestTestWebhook:
    """Tests for POST /api/v1/webhooks/:id/test."""

    @pytest.fixture
    def store(self):
        s = MockWebhookStore()
        s.register(url="https://a.com/hook", events=["debate_end"], user_id="user-1")
        return s

    @pytest.fixture
    def handler(self, store):
        h = _make_handler_instance(webhook_store=store)
        h._check_rbac_permission = MagicMock(return_value=None)
        h.get_current_user = MagicMock(return_value=MockUser(user_id="user-1"))
        return h

    @pytest.mark.asyncio
    @patch("aragora.events.dispatcher.dispatch_webhook", return_value=(True, 200, None))
    async def test_test_webhook_success(self, mock_dispatch, handler):
        result = await handler.handle_post(
            "/api/v1/webhooks/wh-001/test", {}, _make_mock_http_handler()
        )
        status, body = _parse_result(result)
        assert status == 200
        assert body["success"] is True
        assert body["status_code"] == 200

    @pytest.mark.asyncio
    @patch(
        "aragora.events.dispatcher.dispatch_webhook",
        return_value=(False, 500, "Connection refused"),
    )
    async def test_test_webhook_delivery_failed(self, mock_dispatch, handler):
        result = await handler.handle_post(
            "/api/v1/webhooks/wh-001/test", {}, _make_mock_http_handler()
        )
        status, body = _parse_result(result)
        assert status == 502
        assert body["success"] is False
        assert "Connection refused" in body["error"]

    @pytest.mark.asyncio
    async def test_test_webhook_not_found(self, handler):
        result = await handler.handle_post(
            "/api/v1/webhooks/nonexistent/test", {}, _make_mock_http_handler()
        )
        status, _ = _parse_result(result)
        assert status == 404

    @pytest.mark.asyncio
    async def test_test_webhook_access_denied(self, handler):
        handler.get_current_user = MagicMock(return_value=MockUser(user_id="other-user"))
        result = await handler.handle_post(
            "/api/v1/webhooks/wh-001/test", {}, _make_mock_http_handler()
        )
        status, _ = _parse_result(result)
        assert status == 404


# ===========================================================================
# RBAC Permission Check Tests
# ===========================================================================


class TestRBACPermissions:
    """Tests for RBAC permission enforcement."""

    @pytest.fixture
    def handler(self):
        store = MockWebhookStore()
        store.register(url="https://a.com/hook", events=["debate_end"], user_id="user-1")
        h = _make_handler_instance(webhook_store=store)
        h.get_current_user = MagicMock(return_value=MockUser(user_id="user-1"))
        return h

    @pytest.mark.asyncio
    async def test_list_events_rbac_denied(self, handler):
        from aragora.server.handlers.utils.responses import error_response

        denied = error_response("Permission denied: insufficient privileges", 403)
        handler._check_rbac_permission = MagicMock(return_value=denied)

        result = await handler.handle("/api/v1/webhooks/events", {}, _make_mock_http_handler())
        status, body = _parse_result(result)
        assert status == 403

    @pytest.mark.asyncio
    async def test_list_webhooks_rbac_denied(self, handler):
        from aragora.server.handlers.utils.responses import error_response

        denied = error_response("Permission denied", 403)
        handler._check_rbac_permission = MagicMock(return_value=denied)

        result = await handler.handle("/api/v1/webhooks", {}, _make_mock_http_handler())
        status, _ = _parse_result(result)
        assert status == 403

    @pytest.mark.asyncio
    async def test_delete_webhook_rbac_denied(self, handler):
        from aragora.server.handlers.utils.responses import error_response

        denied = error_response("Permission denied", 403)
        handler._check_rbac_permission = MagicMock(return_value=denied)

        result = await handler.handle_delete(
            "/api/v1/webhooks/wh-001", {}, _make_mock_http_handler()
        )
        status, _ = _parse_result(result)
        assert status == 403


# ===========================================================================
# SLO Endpoint Tests
# ===========================================================================


class TestSLOEndpoints:
    """Tests for SLO webhook endpoints."""

    @pytest.fixture
    def handler(self):
        h = _make_handler_instance()
        h._check_rbac_permission = MagicMock(return_value=None)
        h.get_current_user = MagicMock(return_value=MockUser(user_id="user-1"))
        return h

    @pytest.mark.asyncio
    @patch(
        "aragora.server.handlers.webhook_management.WebhookHandler._handle_slo_status",
    )
    async def test_slo_status_route_dispatches(self, mock_slo, handler):
        """Verify the route dispatches to the SLO status handler."""
        from aragora.server.handlers.utils.responses import json_response

        mock_slo.return_value = json_response({"slo_webhooks": {"enabled": False}})
        result = await handler.handle("/api/v1/webhooks/slo/status", {}, _make_mock_http_handler())
        mock_slo.assert_called_once()

    @pytest.mark.asyncio
    async def test_slo_status_import_error_graceful(self, handler):
        """When SLO module is unavailable, returns graceful fallback."""
        with patch.dict("sys.modules", {"aragora.observability.metrics.slo": None}):
            # Force an ImportError path by calling the method directly
            result = handler._handle_slo_status(_make_mock_http_handler())
            status, body = _parse_result(result)
            assert status == 200
            assert body["slo_webhooks"]["enabled"] is False
            assert body["active_violations"] == 0


# ===========================================================================
# Handle Routing Tests (unmatched paths return None)
# ===========================================================================


class TestRoutingReturnsNone:
    """Tests that unmatched paths return None."""

    @pytest.fixture
    def handler(self):
        h = _make_handler_instance()
        h._check_rbac_permission = MagicMock(return_value=None)
        return h

    @pytest.mark.asyncio
    async def test_handle_unmatched_get_returns_none(self, handler):
        result = await handler.handle("/api/v1/other", {}, _make_mock_http_handler())
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_post_unmatched_returns_none(self, handler):
        result = await handler.handle_post("/api/v1/other", {}, _make_mock_http_handler())
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_delete_unmatched_returns_none(self, handler):
        result = await handler.handle_delete("/api/v1/other", {}, _make_mock_http_handler())
        assert result is None

    def test_handle_patch_unmatched_returns_none(self, handler):
        result = handler.handle_patch("/api/v1/other", {}, _make_mock_http_handler())
        assert result is None
