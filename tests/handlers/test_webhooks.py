"""
Tests for Webhook API Handler.

Tests for webhook management endpoints:
- Webhook registration and deletion
- Event listing
- Webhook updates
- Test deliveries
- Signature generation/verification
- SLO webhook status
"""

import pytest
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock


class TestWebhookSignature:
    """Tests for webhook signature utilities."""

    def test_generate_signature(self):
        """Test HMAC-SHA256 signature generation."""
        from aragora.server.handlers.webhook_management import generate_signature

        payload = '{"event": "test", "data": {}}'
        secret = "test_secret_key"

        signature = generate_signature(payload, secret)

        assert signature.startswith("sha256=")
        assert len(signature) > 10

    def test_generate_signature_deterministic(self):
        """Test signature is deterministic."""
        from aragora.server.handlers.webhook_management import generate_signature

        payload = '{"event": "test"}'
        secret = "secret"

        sig1 = generate_signature(payload, secret)
        sig2 = generate_signature(payload, secret)

        assert sig1 == sig2

    def test_generate_signature_different_secrets(self):
        """Test different secrets produce different signatures."""
        from aragora.server.handlers.webhook_management import generate_signature

        payload = '{"event": "test"}'

        sig1 = generate_signature(payload, "secret1")
        sig2 = generate_signature(payload, "secret2")

        assert sig1 != sig2

    def test_verify_signature_valid(self):
        """Test valid signature verification."""
        from aragora.server.handlers.webhook_management import (
            generate_signature,
            verify_signature,
        )

        payload = '{"event": "test"}'
        secret = "my_secret"
        signature = generate_signature(payload, secret)

        assert verify_signature(payload, signature, secret) is True

    def test_verify_signature_invalid(self):
        """Test invalid signature verification."""
        from aragora.server.handlers.webhook_management import verify_signature

        payload = '{"event": "test"}'
        secret = "my_secret"
        wrong_signature = "sha256=invalid_signature"

        assert verify_signature(payload, wrong_signature, secret) is False

    def test_verify_signature_wrong_secret(self):
        """Test signature with wrong secret fails."""
        from aragora.server.handlers.webhook_management import (
            generate_signature,
            verify_signature,
        )

        payload = '{"event": "test"}'
        signature = generate_signature(payload, "correct_secret")

        assert verify_signature(payload, signature, "wrong_secret") is False


class TestWebhookHandler:
    """Tests for WebhookHandler class."""

    @pytest.fixture
    def mock_context(self):
        """Create mock server context."""
        return {"webhook_store": MagicMock()}

    @pytest.fixture
    def handler(self, mock_context):
        """Create WebhookHandler instance."""
        from aragora.server.handlers.webhook_management import WebhookHandler

        return WebhookHandler(mock_context)

    def test_handler_initialization(self, handler):
        """Test handler initialization."""
        assert handler.RESOURCE_TYPE == "webhook"
        assert len(handler.routes) > 0

    def test_can_handle_webhooks_path(self):
        """Test can_handle for webhook paths."""
        from aragora.server.handlers.webhook_management import WebhookHandler

        assert WebhookHandler.can_handle("/api/v1/webhooks") is True
        assert WebhookHandler.can_handle("/api/v1/webhooks/123") is True
        assert WebhookHandler.can_handle("/api/v1/webhooks/events") is True
        assert WebhookHandler.can_handle("/api/v1/other") is False


class TestWebhookHandlerListEvents:
    """Tests for list events endpoint."""

    @pytest.fixture
    def handler(self):
        """Create WebhookHandler instance."""
        from aragora.server.handlers.webhook_management import WebhookHandler

        return WebhookHandler({})

    def test_handle_list_events(self, handler):
        """Test GET /api/webhooks/events."""
        result = handler._handle_list_events()

        assert result is not None
        assert result.status_code == 200

        data = json.loads(result.body)
        assert "events" in data
        assert "count" in data
        assert "description" in data
        assert len(data["events"]) > 0


class TestWebhookHandlerListWebhooks:
    """Tests for list webhooks endpoint."""

    @pytest.fixture
    def mock_store(self):
        """Create mock webhook store."""
        store = MagicMock()
        store.list.return_value = []
        return store

    @pytest.fixture
    def handler(self, mock_store):
        """Create WebhookHandler with mock store."""
        from aragora.server.handlers.webhook_management import WebhookHandler

        ctx = {"webhook_store": mock_store}
        return WebhookHandler(ctx)

    def test_handle_list_webhooks_empty(self, handler, mock_store):
        """Test anonymous listing requires authentication."""
        mock_handler = MagicMock()
        handler.get_current_user = MagicMock(return_value=None)

        result = handler._handle_list_webhooks({}, mock_handler)

        assert result is not None
        assert result.status_code == 401

    def test_handle_list_webhooks_with_webhooks(self, handler, mock_store):
        """Test authenticated listing returns webhook data."""
        webhook = MagicMock()
        webhook.user_id = "user_123"
        webhook.workspace_id = None
        webhook.to_dict.return_value = {
            "id": "wh_123",
            "url": "https://example.com/hook",
            "events": ["debate_end"],
            "active": True,
        }
        mock_store.list.return_value = [webhook]

        mock_handler = MagicMock()
        current_user = MagicMock()
        current_user.user_id = "user_123"
        current_user.org_id = None
        handler.get_current_user = MagicMock(return_value=current_user)
        handler._check_rbac_permission = MagicMock(return_value=None)

        result = handler._handle_list_webhooks({}, mock_handler)

        data = json.loads(result.body)
        assert data["count"] == 1
        assert len(data["webhooks"]) == 1

    def test_handle_list_webhooks_active_only(self, handler, mock_store):
        """Test active-only filter applies for authenticated requests."""
        mock_handler = MagicMock()
        current_user = MagicMock()
        current_user.user_id = "user_123"
        current_user.org_id = None
        handler.get_current_user = MagicMock(return_value=current_user)
        handler._check_rbac_permission = MagicMock(return_value=None)

        handler._handle_list_webhooks({"active_only": ["true"]}, mock_handler)

        mock_store.list.assert_called_once()
        call_kwargs = mock_store.list.call_args[1]
        assert call_kwargs.get("active_only") is True


class TestWebhookHandlerGetWebhook:
    """Tests for get webhook endpoint."""

    @pytest.fixture
    def mock_store(self):
        """Create mock webhook store."""
        store = MagicMock()
        return store

    @pytest.fixture
    def handler(self, mock_store):
        """Create WebhookHandler with mock store."""
        from aragora.server.handlers.webhook_management import WebhookHandler

        ctx = {"webhook_store": mock_store}
        return WebhookHandler(ctx)

    def test_handle_get_webhook_not_found(self, handler, mock_store):
        """Test getting non-existent webhook."""
        mock_store.get.return_value = None
        mock_handler = MagicMock()

        result = handler._handle_get_webhook("wh_nonexistent", mock_handler)

        assert result.status_code == 404

    def test_handle_get_webhook_success(self, handler, mock_store):
        """Test anonymous webhook reads require authentication."""
        webhook = MagicMock()
        webhook.user_id = None
        webhook.to_dict.return_value = {
            "id": "wh_123",
            "url": "https://example.com/hook",
        }
        mock_store.get.return_value = webhook

        mock_handler = MagicMock()
        handler.get_current_user = MagicMock(return_value=None)

        result = handler._handle_get_webhook("wh_123", mock_handler)

        assert result.status_code == 401

    def test_handle_get_webhook_access_denied(self, handler, mock_store):
        """Test access denied for other user's webhook."""
        webhook = MagicMock()
        webhook.user_id = "other_user"
        webhook.workspace_id = None
        mock_store.get.return_value = webhook

        mock_handler = MagicMock()
        current_user = MagicMock()
        current_user.user_id = "current_user"
        current_user.org_id = None
        handler.get_current_user = MagicMock(return_value=current_user)
        handler._check_rbac_permission = MagicMock(return_value=None)

        result = handler._handle_get_webhook("wh_123", mock_handler)

        assert result.status_code == 404

    def test_handle_get_webhook_private_requires_auth(self, handler, mock_store):
        """Test private webhook reads fail before ownership checks when anonymous."""
        webhook = MagicMock()
        webhook.user_id = "owner_user"
        mock_store.get.return_value = webhook

        mock_handler = MagicMock()
        handler.get_current_user = MagicMock(return_value=None)

        result = handler._handle_get_webhook("wh_123", mock_handler)

        assert result.status_code == 401


class TestWebhookHandlerRegister:
    """Tests for webhook registration."""

    @pytest.fixture
    def mock_store(self):
        """Create mock webhook store."""
        store = MagicMock()
        webhook = MagicMock()
        webhook.id = "wh_new_123"
        webhook.to_dict.return_value = {
            "id": "wh_new_123",
            "url": "https://example.com/webhook",
            "events": ["debate_end"],
            "secret": "secret_123",
        }
        store.register.return_value = webhook
        return store

    @pytest.fixture
    def handler(self, mock_store):
        """Create WebhookHandler with mock store."""
        from aragora.server.handlers.webhook_management import WebhookHandler

        ctx = {"webhook_store": mock_store}
        h = WebhookHandler(ctx)
        h._check_rbac_permission = MagicMock(return_value=None)
        return h

    def test_register_webhook_missing_url(self, handler):
        """Test registration without URL."""
        mock_handler = MagicMock()
        handler.get_current_user = MagicMock(return_value=None)

        result = handler._handle_register_webhook({"events": ["debate_end"]}, mock_handler)

        assert result.status_code == 400
        assert b"URL must be a non-empty string" in result.body

    def test_register_webhook_missing_events(self, handler):
        """Test registration without events."""
        mock_handler = MagicMock()
        handler.get_current_user = MagicMock(return_value=None)

        result = handler._handle_register_webhook({"url": "https://example.com/hook"}, mock_handler)

        assert result.status_code == 400
        assert b"event" in result.body.lower()

    def test_register_webhook_invalid_events(self, handler):
        """Test registration with invalid events."""
        mock_handler = MagicMock()
        handler.get_current_user = MagicMock(return_value=None)

        result = handler._handle_register_webhook(
            {"url": "https://example.com/hook", "events": ["invalid_event"]},
            mock_handler,
        )

        assert result.status_code == 400
        assert b"Invalid event" in result.body

    def test_register_webhook_success(self, handler, mock_store):
        """Test successful webhook registration."""
        mock_handler = MagicMock()
        handler.get_current_user = MagicMock(return_value=None)

        with patch(
            "aragora.server.handlers.webhook_management.validate_webhook_url",
            return_value=(True, None),
        ):
            result = handler._handle_register_webhook(
                {"url": "https://example.com/hook", "events": ["debate_end"]},
                mock_handler,
            )

        assert result.status_code == 201

        data = json.loads(result.body)
        assert data["webhook"]["id"] == "wh_new_123"
        assert "secret" in data["webhook"]


class TestWebhookHandlerDelete:
    """Tests for webhook deletion."""

    @pytest.fixture
    def mock_store(self):
        """Create mock webhook store."""
        store = MagicMock()
        return store

    @pytest.fixture
    def handler(self, mock_store):
        """Create WebhookHandler with mock store."""
        from aragora.server.handlers.webhook_management import WebhookHandler

        ctx = {"webhook_store": mock_store}
        h = WebhookHandler(ctx)
        h._check_rbac_permission = MagicMock(return_value=None)
        return h

    def test_delete_webhook_not_found(self, handler, mock_store):
        """Test deleting non-existent webhook."""
        mock_store.get.return_value = None
        mock_handler = MagicMock()

        result = handler._handle_delete_webhook("wh_nonexistent", mock_handler)

        assert result.status_code == 404

    def test_delete_webhook_success(self, handler, mock_store):
        """Test successful webhook deletion."""
        mock_handler = MagicMock()
        current_user = MagicMock()
        current_user.user_id = "current_user"
        current_user.org_id = None
        handler.get_current_user = MagicMock(return_value=current_user)

        webhook = MagicMock()
        webhook.user_id = current_user.user_id
        webhook.workspace_id = None
        mock_store.get.return_value = webhook

        result = handler._handle_delete_webhook("wh_123", mock_handler)

        assert result.status_code == 200

        data = json.loads(result.body)
        assert data["deleted"] is True
        mock_store.delete.assert_called_once_with("wh_123")

    def test_delete_webhook_access_denied(self, handler, mock_store):
        """Test deleting other user's webhook."""
        webhook = MagicMock()
        webhook.user_id = "other_user"
        webhook.workspace_id = None
        mock_store.get.return_value = webhook

        mock_handler = MagicMock()
        current_user = MagicMock()
        current_user.user_id = "current_user"
        current_user.org_id = None
        handler.get_current_user = MagicMock(return_value=current_user)

        result = handler._handle_delete_webhook("wh_123", mock_handler)

        assert result.status_code == 404


class TestWebhookHandlerUpdate:
    """Tests for webhook updates."""

    @pytest.fixture
    def mock_store(self):
        """Create mock webhook store."""
        store = MagicMock()
        return store

    @pytest.fixture
    def handler(self, mock_store):
        """Create WebhookHandler with mock store."""
        from aragora.server.handlers.webhook_management import WebhookHandler

        ctx = {"webhook_store": mock_store}
        h = WebhookHandler(ctx)
        h._check_rbac_permission = MagicMock(return_value=None)
        return h

    def test_update_webhook_not_found(self, handler, mock_store):
        """Test updating non-existent webhook."""
        mock_store.get.return_value = None
        mock_handler = MagicMock()

        result = handler._handle_update_webhook("wh_nonexistent", {}, mock_handler)

        assert result.status_code == 404

    def test_update_webhook_success(self, handler, mock_store):
        """Test successful webhook update."""
        updated = MagicMock()
        updated.to_dict.return_value = {
            "id": "wh_123",
            "url": "https://new-url.com/hook",
            "active": True,
        }
        mock_store.update.return_value = updated

        mock_handler = MagicMock()
        current_user = MagicMock()
        current_user.user_id = "current_user"
        current_user.org_id = None
        handler.get_current_user = MagicMock(return_value=current_user)

        webhook = MagicMock()
        webhook.user_id = current_user.user_id
        webhook.workspace_id = None
        mock_store.get.return_value = webhook

        with patch(
            "aragora.server.handlers.webhook_management.validate_webhook_url",
            return_value=(True, None),
        ):
            result = handler._handle_update_webhook(
                "wh_123",
                {"url": "https://new-url.com/hook"},
                mock_handler,
            )

        assert result.status_code == 200

    def test_update_webhook_invalid_events(self, handler, mock_store):
        """Test updating with invalid events."""
        mock_handler = MagicMock()
        current_user = MagicMock()
        current_user.user_id = "current_user"
        current_user.org_id = None
        handler.get_current_user = MagicMock(return_value=current_user)

        webhook = MagicMock()
        webhook.user_id = current_user.user_id
        webhook.workspace_id = None
        mock_store.get.return_value = webhook

        result = handler._handle_update_webhook(
            "wh_123",
            {"events": ["invalid_event"]},
            mock_handler,
        )

        assert result.status_code == 400


class TestWebhookHandlerTest:
    """Tests for webhook test delivery."""

    @pytest.fixture
    def mock_store(self):
        """Create mock webhook store."""
        store = MagicMock()
        return store

    @pytest.fixture
    def handler(self, mock_store):
        """Create WebhookHandler with mock store."""
        from aragora.server.handlers.webhook_management import WebhookHandler

        ctx = {"webhook_store": mock_store}
        h = WebhookHandler(ctx)
        h._check_rbac_permission = MagicMock(return_value=None)
        return h

    def test_test_webhook_not_found(self, handler, mock_store):
        """Test sending test to non-existent webhook."""
        mock_store.get.return_value = None
        mock_handler = MagicMock()

        result = handler._handle_test_webhook("wh_nonexistent", mock_handler)

        assert result.status_code == 404

    def test_test_webhook_success(self, handler, mock_store):
        """Test successful webhook test."""
        mock_handler = MagicMock()
        current_user = MagicMock()
        current_user.user_id = "current_user"
        current_user.org_id = None
        handler.get_current_user = MagicMock(return_value=current_user)

        webhook = MagicMock()
        webhook.id = "wh_123"
        webhook.name = "Test Webhook"
        webhook.user_id = current_user.user_id
        webhook.workspace_id = None
        mock_store.get.return_value = webhook

        with patch(
            "aragora.events.dispatcher.dispatch_webhook",
            return_value=(True, 200, None),
        ):
            result = handler._handle_test_webhook("wh_123", mock_handler)

        assert result.status_code == 200

        data = json.loads(result.body)
        assert data["success"] is True

    def test_test_webhook_failure(self, handler, mock_store):
        """Test failed webhook test."""
        mock_handler = MagicMock()
        current_user = MagicMock()
        current_user.user_id = "current_user"
        current_user.org_id = None
        handler.get_current_user = MagicMock(return_value=current_user)

        webhook = MagicMock()
        webhook.id = "wh_123"
        webhook.name = "Test Webhook"
        webhook.user_id = current_user.user_id
        webhook.workspace_id = None
        mock_store.get.return_value = webhook

        with patch(
            "aragora.events.dispatcher.dispatch_webhook",
            return_value=(False, 500, "Connection refused"),
        ):
            result = handler._handle_test_webhook("wh_123", mock_handler)

        assert result.status_code == 502

        data = json.loads(result.body)
        assert data["success"] is False


class TestWebhookHandlerSLO:
    """Tests for SLO webhook endpoints."""

    @pytest.fixture
    def handler(self):
        """Create WebhookHandler instance."""
        from aragora.server.handlers.webhook_management import WebhookHandler

        return WebhookHandler({})

    def test_handle_slo_status_success(self, handler):
        """Test SLO status when module is available."""
        mock_status = {"enabled": True, "config": {}, "notifications_sent": 5}
        mock_violation_state = {}

        with patch.dict(
            "sys.modules",
            {"aragora.observability.metrics.slo": MagicMock()},
        ):
            import sys

            slo_module = sys.modules["aragora.observability.metrics.slo"]
            slo_module.get_slo_webhook_status = MagicMock(return_value=mock_status)
            slo_module.get_violation_state = MagicMock(return_value=mock_violation_state)

            result = handler._handle_slo_status(MagicMock())

            assert result.status_code == 200

    def test_handle_slo_test_not_enabled(self, handler):
        """Test SLO test when webhooks not enabled."""
        mock_status = {"enabled": False}

        with patch.dict(
            "sys.modules",
            {"aragora.observability.metrics.slo": MagicMock()},
        ):
            import sys

            sys.modules["aragora.observability.metrics.slo"].get_slo_webhook_status = MagicMock(
                return_value=mock_status
            )

            result = handler._handle_slo_test(MagicMock())

            assert result.status_code == 400


class TestWebhookHandlerRouting:
    """Tests for request routing."""

    @pytest.fixture
    def handler(self):
        """Create WebhookHandler instance."""
        from aragora.server.handlers.webhook_management import WebhookHandler

        h = WebhookHandler({})
        h.get_current_user = MagicMock(return_value=None)
        return h

    @pytest.mark.asyncio
    async def test_handle_routes_to_list_events(self, handler):
        """Test routing to list events."""
        result = await handler.handle("/api/v1/webhooks/events", {}, MagicMock())
        assert result is not None

    @pytest.mark.asyncio
    async def test_handle_routes_to_list_webhooks(self, handler):
        """Test routing to list webhooks."""
        with patch.object(handler, "_get_webhook_store") as mock_store:
            mock_store.return_value.list.return_value = []
            result = await handler.handle("/api/v1/webhooks", {}, MagicMock())
            assert result is not None

    @pytest.mark.asyncio
    async def test_handle_unmatched_path(self, handler):
        """Test unmatched path returns None."""
        result = await handler.handle("/api/v1/other", {}, MagicMock())
        assert result is None
