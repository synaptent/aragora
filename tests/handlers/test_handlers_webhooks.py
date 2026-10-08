"""
Tests for WebhookHandler - webhook management endpoints.

Tests cover:
- POST   /api/webhooks              - Register a new webhook
- GET    /api/webhooks              - List registered webhooks
- GET    /api/webhooks/events       - List available event types
- GET    /api/webhooks/:id          - Get specific webhook
- DELETE /api/webhooks/:id          - Delete a webhook
- PATCH  /api/webhooks/:id          - Update a webhook
- POST   /api/webhooks/:id/test     - Send a test event to webhook

Additional tests:
- WebhookConfig model
- WebhookStore operations
- HMAC-SHA256 signature generation/verification
- Authorization/ownership checks
- Input validation
"""

import json
import pytest
import time
import uuid
from unittest.mock import Mock, MagicMock, patch

from aragora.server.handlers.webhook_management import (
    WebhookHandler,
    WebhookConfig,
    WebhookStore,
    WEBHOOK_EVENTS,
    generate_signature,
    verify_signature,
    get_webhook_store,
)
from aragora.server.handlers.utils.responses import HandlerResult

# Import concrete implementation for testing
from aragora.storage.webhook_config_store import InMemoryWebhookConfigStore


def parse_handler_result(result: HandlerResult) -> tuple[dict, int]:
    """Helper to parse HandlerResult into (body_dict, status_code)."""
    body_str = result.body.decode("utf-8") if isinstance(result.body, bytes) else result.body
    try:
        body_dict = json.loads(body_str)
    except (json.JSONDecodeError, TypeError):
        body_dict = {"raw": body_str}
    return body_dict, result.status_code


def get_response_body(result: HandlerResult) -> str:
    """Helper to get response body as string."""
    return result.body.decode("utf-8") if isinstance(result.body, bytes) else str(result.body)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _bypass_webhook_rbac(monkeypatch):
    """Bypass RBAC checks on WebhookHandler for all tests."""
    monkeypatch.setattr(WebhookHandler, "_check_rbac_permission", lambda self, handler, perm: None)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Reset webhook rate limiters before each test to prevent cross-test exhaustion."""
    from aragora.server.handlers import webhook_management

    for attr in ("_register_limiter", "_test_limiter", "_list_limiter"):
        limiter = getattr(webhook_management, attr)
        limiter.clear()
    yield
    for attr in ("_register_limiter", "_test_limiter", "_list_limiter"):
        limiter = getattr(webhook_management, attr)
        limiter.clear()


@pytest.fixture
def mock_user():
    """Create a mock user object."""
    user = Mock()
    user.user_id = "user-123"
    user.email = "user@example.com"
    user.name = "Test User"
    return user


@pytest.fixture
def mock_other_user():
    """Create a mock user object for ownership tests."""
    user = Mock()
    user.user_id = "other-user-456"
    user.email = "other@example.com"
    user.name = "Other User"
    return user


@pytest.fixture
def webhook_store():
    """Create a fresh in-memory webhook store for testing."""
    return InMemoryWebhookConfigStore()


@pytest.fixture
def sample_webhook(webhook_store, mock_user):
    """Create a sample webhook for testing."""
    return webhook_store.register(
        url="https://example.com/webhook",
        events=["debate_start", "debate_end"],
        name="Test Webhook",
        description="A test webhook",
        user_id=mock_user.user_id,
    )


@pytest.fixture
def server_context(webhook_store):
    """Create a mock server context with webhook store."""
    return {"webhook_store": webhook_store}


@pytest.fixture
def webhook_handler(server_context):
    """Create a WebhookHandler instance."""
    return WebhookHandler(server_context)


@pytest.fixture
def mock_http_handler(mock_user):
    """Create a mock HTTP handler with user context."""
    handler = Mock()
    handler.rfile = Mock()
    handler.headers = {"Content-Type": "application/json", "Content-Length": "100"}
    return handler


# ============================================================================
# WebhookConfig Model Tests
# ============================================================================


class TestWebhookConfig:
    """Tests for WebhookConfig dataclass."""

    def test_create_webhook_config(self):
        """Test creating a webhook config with required fields."""
        config = WebhookConfig(
            id="webhook-123",
            url="https://example.com/hook",
            events=["debate_start"],
            secret="test-secret",
        )
        assert config.id == "webhook-123"
        assert config.url == "https://example.com/hook"
        assert config.events == ["debate_start"]
        assert config.secret == "test-secret"
        assert config.active is True

    def test_webhook_config_defaults(self):
        """Test default values for optional fields."""
        config = WebhookConfig(
            id="webhook-123",
            url="https://example.com/hook",
            events=["debate_start"],
            secret="test-secret",
        )
        assert config.active is True
        assert config.name is None
        assert config.description is None
        assert config.last_delivery_at is None
        assert config.delivery_count == 0
        assert config.failure_count == 0
        assert config.user_id is None
        assert config.workspace_id is None

    def test_to_dict_excludes_secret_by_default(self):
        """Test that to_dict excludes secret by default."""
        config = WebhookConfig(
            id="webhook-123",
            url="https://example.com/hook",
            events=["debate_start"],
            secret="super-secret",
        )
        result = config.to_dict()
        assert "secret" not in result
        assert result["id"] == "webhook-123"
        assert result["url"] == "https://example.com/hook"

    def test_to_dict_includes_secret_when_requested(self):
        """Test that to_dict includes secret when requested."""
        config = WebhookConfig(
            id="webhook-123",
            url="https://example.com/hook",
            events=["debate_start"],
            secret="super-secret",
        )
        result = config.to_dict(include_secret=True)
        assert result["secret"] == "super-secret"

    def test_matches_event_when_active(self):
        """Test that active webhooks match subscribed events."""
        config = WebhookConfig(
            id="webhook-123",
            url="https://example.com/hook",
            events=["debate_start", "debate_end"],
            secret="test-secret",
            active=True,
        )
        assert config.matches_event("debate_start") is True
        assert config.matches_event("debate_end") is True
        assert config.matches_event("consensus") is False

    def test_matches_event_when_inactive(self):
        """Test that inactive webhooks don't match any events."""
        config = WebhookConfig(
            id="webhook-123",
            url="https://example.com/hook",
            events=["debate_start", "debate_end"],
            secret="test-secret",
            active=False,
        )
        assert config.matches_event("debate_start") is False
        assert config.matches_event("debate_end") is False

    def test_matches_event_with_wildcard(self):
        """Test wildcard event subscription."""
        config = WebhookConfig(
            id="webhook-123",
            url="https://example.com/hook",
            events=["*"],
            secret="test-secret",
            active=True,
        )
        # Should match all valid webhook events
        assert config.matches_event("debate_start") is True
        assert config.matches_event("consensus") is True
        assert config.matches_event("vote") is True
        # Invalid events should not match even with wildcard
        assert config.matches_event("invalid_event") is False


# ============================================================================
# WebhookStore Tests
# ============================================================================


class TestWebhookStore:
    """Tests for WebhookStore class."""

    def test_register_webhook(self, webhook_store):
        """Test registering a new webhook."""
        webhook = webhook_store.register(
            url="https://example.com/hook",
            events=["debate_start"],
            name="My Webhook",
        )
        assert webhook.id is not None
        assert webhook.url == "https://example.com/hook"
        assert webhook.events == ["debate_start"]
        assert webhook.name == "My Webhook"
        assert len(webhook.secret) > 20  # Generated secret

    def test_get_webhook(self, webhook_store, sample_webhook):
        """Test retrieving a webhook by ID."""
        retrieved = webhook_store.get(sample_webhook.id)
        assert retrieved is not None
        assert retrieved.id == sample_webhook.id
        assert retrieved.url == sample_webhook.url

    def test_get_nonexistent_webhook(self, webhook_store):
        """Test retrieving a non-existent webhook."""
        retrieved = webhook_store.get("nonexistent-id")
        assert retrieved is None

    def test_list_all_webhooks(self, webhook_store):
        """Test listing all webhooks."""
        webhook_store.register(url="https://example.com/hook1", events=["debate_start"])
        webhook_store.register(url="https://example.com/hook2", events=["debate_end"])

        webhooks = webhook_store.list()
        assert len(webhooks) == 2

    def test_list_webhooks_by_user(self, webhook_store):
        """Test filtering webhooks by user."""
        webhook_store.register(
            url="https://example.com/hook1",
            events=["debate_start"],
            user_id="user-1",
        )
        webhook_store.register(
            url="https://example.com/hook2",
            events=["debate_end"],
            user_id="user-2",
        )

        user1_webhooks = webhook_store.list(user_id="user-1")
        assert len(user1_webhooks) == 1
        assert user1_webhooks[0].user_id == "user-1"

    def test_list_active_webhooks_only(self, webhook_store):
        """Test filtering for active webhooks only."""
        webhook1 = webhook_store.register(
            url="https://example.com/hook1",
            events=["debate_start"],
        )
        webhook2 = webhook_store.register(
            url="https://example.com/hook2",
            events=["debate_end"],
        )
        webhook_store.update(webhook2.id, active=False)

        active_webhooks = webhook_store.list(active_only=True)
        assert len(active_webhooks) == 1
        assert active_webhooks[0].id == webhook1.id

    def test_delete_webhook(self, webhook_store, sample_webhook):
        """Test deleting a webhook."""
        result = webhook_store.delete(sample_webhook.id)
        assert result is True
        assert webhook_store.get(sample_webhook.id) is None

    def test_delete_nonexistent_webhook(self, webhook_store):
        """Test deleting a non-existent webhook."""
        result = webhook_store.delete("nonexistent-id")
        assert result is False

    def test_update_webhook(self, webhook_store, sample_webhook):
        """Test updating webhook fields."""
        updated = webhook_store.update(
            webhook_id=sample_webhook.id,
            url="https://new-url.com/hook",
            events=["consensus"],
            active=False,
            name="Updated Name",
        )
        assert updated.url == "https://new-url.com/hook"
        assert updated.events == ["consensus"]
        assert updated.active is False
        assert updated.name == "Updated Name"
        assert updated.updated_at > sample_webhook.created_at

    def test_update_nonexistent_webhook(self, webhook_store):
        """Test updating a non-existent webhook."""
        updated = webhook_store.update(
            webhook_id="nonexistent-id",
            url="https://new-url.com/hook",
        )
        assert updated is None

    def test_record_delivery_success(self, webhook_store, sample_webhook):
        """Test recording successful delivery."""
        webhook_store.record_delivery(sample_webhook.id, status_code=200, success=True)
        webhook = webhook_store.get(sample_webhook.id)
        assert webhook.delivery_count == 1
        assert webhook.failure_count == 0
        assert webhook.last_delivery_status == 200
        assert webhook.last_delivery_at is not None

    def test_record_delivery_failure(self, webhook_store, sample_webhook):
        """Test recording failed delivery."""
        webhook_store.record_delivery(sample_webhook.id, status_code=500, success=False)
        webhook = webhook_store.get(sample_webhook.id)
        assert webhook.delivery_count == 1
        assert webhook.failure_count == 1
        assert webhook.last_delivery_status == 500

    def test_get_for_event(self, webhook_store):
        """Test getting webhooks that match an event."""
        webhook_store.register(
            url="https://example.com/hook1",
            events=["debate_start", "debate_end"],
        )
        webhook_store.register(
            url="https://example.com/hook2",
            events=["consensus"],
        )
        webhook_store.register(
            url="https://example.com/hook3",
            events=["*"],
        )

        debate_webhooks = webhook_store.get_for_event("debate_start")
        assert len(debate_webhooks) == 2  # hook1 and hook3 (wildcard)

        consensus_webhooks = webhook_store.get_for_event("consensus")
        assert len(consensus_webhooks) == 2  # hook2 and hook3 (wildcard)


# ============================================================================
# Signature Tests
# ============================================================================


class TestSignatureGeneration:
    """Tests for HMAC-SHA256 signature utilities."""

    def test_generate_signature(self):
        """Test signature generation."""
        payload = '{"event": "test"}'
        secret = "my-secret-key"
        signature = generate_signature(payload, secret)
        assert signature.startswith("sha256=")
        assert len(signature) > 10

    def test_signature_consistency(self):
        """Test that same payload/secret produces same signature."""
        payload = '{"event": "test", "data": "value"}'
        secret = "consistent-secret"
        sig1 = generate_signature(payload, secret)
        sig2 = generate_signature(payload, secret)
        assert sig1 == sig2

    def test_different_payloads_different_signatures(self):
        """Test that different payloads produce different signatures."""
        secret = "same-secret"
        sig1 = generate_signature('{"event": "test1"}', secret)
        sig2 = generate_signature('{"event": "test2"}', secret)
        assert sig1 != sig2

    def test_different_secrets_different_signatures(self):
        """Test that different secrets produce different signatures."""
        payload = '{"event": "test"}'
        sig1 = generate_signature(payload, "secret1")
        sig2 = generate_signature(payload, "secret2")
        assert sig1 != sig2

    def test_verify_signature_valid(self):
        """Test verification of valid signature."""
        payload = '{"event": "test"}'
        secret = "my-secret"
        signature = generate_signature(payload, secret)
        assert verify_signature(payload, signature, secret) is True

    def test_verify_signature_invalid(self):
        """Test verification of invalid signature."""
        payload = '{"event": "test"}'
        secret = "my-secret"
        wrong_signature = "sha256=invalid"
        assert verify_signature(payload, wrong_signature, secret) is False

    def test_verify_signature_wrong_secret(self):
        """Test verification with wrong secret."""
        payload = '{"event": "test"}'
        signature = generate_signature(payload, "correct-secret")
        assert verify_signature(payload, signature, "wrong-secret") is False

    def test_verify_signature_tampered_payload(self):
        """Test verification with tampered payload."""
        original_payload = '{"event": "test"}'
        secret = "my-secret"
        signature = generate_signature(original_payload, secret)
        tampered_payload = '{"event": "hacked"}'
        assert verify_signature(tampered_payload, signature, secret) is False


# ============================================================================
# Handler Tests - GET /api/webhooks/events
# ============================================================================


class TestListEvents:
    """Tests for GET /api/webhooks/events endpoint."""

    def test_list_events(self, webhook_handler):
        """Test listing available webhook events."""
        result = webhook_handler._handle_list_events()
        data, status = parse_handler_result(result)

        assert status == 200
        assert "events" in data
        assert "count" in data
        assert "description" in data
        assert len(data["events"]) == data["count"]
        assert "debate_start" in data["events"]
        assert "consensus" in data["events"]

    def test_list_events_descriptions(self, webhook_handler):
        """Test that all events have descriptions."""
        result = webhook_handler._handle_list_events()
        data, _ = parse_handler_result(result)

        descriptions = data["description"]
        for event in data["events"]:
            assert event in descriptions, f"Missing description for {event}"


# ============================================================================
# Handler Tests - POST /api/webhooks
# ============================================================================


class TestRegisterWebhook:
    """Tests for POST /api/webhooks endpoint."""

    def test_register_webhook_success(self, webhook_handler, mock_http_handler, mock_user):
        """Test successful webhook registration."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            body = {
                "url": "https://example.com/webhook",
                "events": ["debate_start", "debate_end"],
                "name": "My Webhook",
                "description": "A test webhook",
            }
            result = webhook_handler._handle_register_webhook(body, mock_http_handler)
            data, status = parse_handler_result(result)

            assert status == 201
            assert "webhook" in data
            assert data["webhook"]["url"] == "https://example.com/webhook"
            assert "secret" in data["webhook"]  # Secret shown on creation
            assert "message" in data

    def test_register_webhook_missing_url(self, webhook_handler, mock_http_handler, mock_user):
        """Test registration with missing URL."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            body = {"events": ["debate_start"]}
            result = webhook_handler._handle_register_webhook(body, mock_http_handler)
            response_body = get_response_body(result)
            status = result.status_code

            assert status == 400
            assert "URL must be a non-empty string" in response_body

    def test_register_webhook_invalid_url(self, webhook_handler, mock_http_handler, mock_user):
        """Test registration with invalid URL format."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            body = {
                "url": "not-a-valid-url",
                "events": ["debate_start"],
            }
            result = webhook_handler._handle_register_webhook(body, mock_http_handler)
            response_body = get_response_body(result)
            status = result.status_code

            assert status == 400
            assert "Invalid webhook URL" in response_body

    def test_register_webhook_missing_events(self, webhook_handler, mock_http_handler, mock_user):
        """Test registration with missing events."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            body = {"url": "https://example.com/webhook"}
            result = webhook_handler._handle_register_webhook(body, mock_http_handler)
            response_body = get_response_body(result)
            status = result.status_code

            assert status == 400
            assert "At least one event type is required" in response_body

    def test_register_webhook_invalid_events(self, webhook_handler, mock_http_handler, mock_user):
        """Test registration with invalid event types."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            body = {
                "url": "https://example.com/webhook",
                "events": ["invalid_event", "another_invalid"],
            }
            result = webhook_handler._handle_register_webhook(body, mock_http_handler)
            response_body = get_response_body(result)
            status = result.status_code

            assert status == 400
            assert "Invalid event types" in response_body

    def test_register_webhook_wildcard_event(self, webhook_handler, mock_http_handler, mock_user):
        """Test registration with wildcard event."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            body = {
                "url": "https://example.com/webhook",
                "events": ["*"],
            }
            result = webhook_handler._handle_register_webhook(body, mock_http_handler)
            data, status = parse_handler_result(result)

            assert status == 201
            assert data["webhook"]["events"] == ["*"]


# ============================================================================
# Handler Tests - GET /api/webhooks
# ============================================================================


class TestListWebhooks:
    """Tests for GET /api/webhooks endpoint."""

    def test_list_webhooks(self, webhook_handler, mock_http_handler, mock_user, sample_webhook):
        """Test listing webhooks."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            result = webhook_handler._handle_list_webhooks({}, mock_http_handler)
            data, status = parse_handler_result(result)

            assert status == 200
            assert "webhooks" in data
            assert "count" in data
            assert len(data["webhooks"]) == 1

    def test_list_webhooks_excludes_secrets(
        self, webhook_handler, mock_http_handler, mock_user, sample_webhook
    ):
        """Test that listing webhooks doesn't expose secrets."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            result = webhook_handler._handle_list_webhooks({}, mock_http_handler)
            data, status = parse_handler_result(result)

            for webhook in data["webhooks"]:
                assert "secret" not in webhook

    def test_list_webhooks_active_only(
        self, webhook_handler, mock_http_handler, mock_user, webhook_store
    ):
        """Test filtering for active webhooks only."""
        # Create active and inactive webhooks
        active = webhook_store.register(
            url="https://example.com/active",
            events=["debate_start"],
            user_id=mock_user.user_id,
        )
        inactive = webhook_store.register(
            url="https://example.com/inactive",
            events=["debate_end"],
            user_id=mock_user.user_id,
        )
        webhook_store.update(inactive.id, active=False)

        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            result = webhook_handler._handle_list_webhooks(
                {"active_only": ["true"]}, mock_http_handler
            )
            data, status = parse_handler_result(result)

            assert status == 200
            assert len(data["webhooks"]) == 1
            assert data["webhooks"][0]["url"] == "https://example.com/active"


# ============================================================================
# Handler Tests - GET /api/webhooks/:id
# ============================================================================


class TestGetWebhook:
    """Tests for GET /api/webhooks/:id endpoint."""

    def test_get_webhook(self, webhook_handler, mock_http_handler, mock_user, sample_webhook):
        """Test getting a specific webhook."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            result = webhook_handler._handle_get_webhook(sample_webhook.id, mock_http_handler)
            data, status = parse_handler_result(result)

            assert status == 200
            assert "webhook" in data
            assert data["webhook"]["id"] == sample_webhook.id
            assert "secret" not in data["webhook"]

    def test_get_webhook_not_found(self, webhook_handler, mock_http_handler, mock_user):
        """Test getting a non-existent webhook."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            result = webhook_handler._handle_get_webhook("nonexistent-id", mock_http_handler)
            response_body = get_response_body(result)
            status = result.status_code

            assert status == 404
            assert "not found" in response_body.lower()

    def test_get_webhook_access_denied(
        self, webhook_handler, mock_http_handler, mock_other_user, sample_webhook
    ):
        """Test that users can't access other users' webhooks."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_other_user):
            result = webhook_handler._handle_get_webhook(sample_webhook.id, mock_http_handler)
            response_body = get_response_body(result)
            status = result.status_code

            # Denied access is reported as 404 to avoid revealing that the
            # webhook exists to non-owners (anti-enumeration).
            assert status == 404
            assert "not found" in response_body.lower()


# ============================================================================
# Handler Tests - DELETE /api/webhooks/:id
# ============================================================================


class TestDeleteWebhook:
    """Tests for DELETE /api/webhooks/:id endpoint."""

    def test_delete_webhook(self, webhook_handler, mock_http_handler, mock_user, sample_webhook):
        """Test deleting a webhook."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            result = webhook_handler._handle_delete_webhook(sample_webhook.id, mock_http_handler)
            data, status = parse_handler_result(result)

            assert status == 200
            assert data["deleted"] is True
            assert data["webhook_id"] == sample_webhook.id

    def test_delete_webhook_not_found(self, webhook_handler, mock_http_handler, mock_user):
        """Test deleting a non-existent webhook."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            result = webhook_handler._handle_delete_webhook("nonexistent-id", mock_http_handler)
            status = result.status_code

            assert status == 404

    def test_delete_webhook_access_denied(
        self, webhook_handler, mock_http_handler, mock_other_user, sample_webhook
    ):
        """Test that users can't delete other users' webhooks."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_other_user):
            result = webhook_handler._handle_delete_webhook(sample_webhook.id, mock_http_handler)
            status = result.status_code

            # 404, not 403 — non-owners must not learn the webhook exists
            assert status == 404


# ============================================================================
# Handler Tests - PATCH /api/webhooks/:id
# ============================================================================


class TestUpdateWebhook:
    """Tests for PATCH /api/webhooks/:id endpoint."""

    def test_update_webhook(self, webhook_handler, mock_http_handler, mock_user, sample_webhook):
        """Test updating a webhook."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            body = {
                "url": "https://new-url.com/webhook",
                "active": False,
                "name": "Updated Name",
            }
            result = webhook_handler._handle_update_webhook(
                sample_webhook.id, body, mock_http_handler
            )
            data, status = parse_handler_result(result)

            assert status == 200
            assert data["webhook"]["url"] == "https://new-url.com/webhook"
            assert data["webhook"]["active"] is False
            assert data["webhook"]["name"] == "Updated Name"

    def test_update_webhook_events(
        self, webhook_handler, mock_http_handler, mock_user, sample_webhook
    ):
        """Test updating webhook events."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            body = {"events": ["consensus", "vote"]}
            result = webhook_handler._handle_update_webhook(
                sample_webhook.id, body, mock_http_handler
            )
            data, status = parse_handler_result(result)

            assert status == 200
            assert data["webhook"]["events"] == ["consensus", "vote"]

    def test_update_webhook_invalid_events(
        self, webhook_handler, mock_http_handler, mock_user, sample_webhook
    ):
        """Test updating with invalid events."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            body = {"events": ["invalid_event"]}
            result = webhook_handler._handle_update_webhook(
                sample_webhook.id, body, mock_http_handler
            )
            response_body = get_response_body(result)
            status = result.status_code

            assert status == 400
            assert "Invalid event types" in response_body

    def test_update_webhook_not_found(self, webhook_handler, mock_http_handler, mock_user):
        """Test updating a non-existent webhook."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            body = {"name": "New Name"}
            result = webhook_handler._handle_update_webhook(
                "nonexistent-id", body, mock_http_handler
            )
            status = result.status_code

            assert status == 404

    def test_update_webhook_access_denied(
        self, webhook_handler, mock_http_handler, mock_other_user, sample_webhook
    ):
        """Test that users can't update other users' webhooks."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_other_user):
            body = {"name": "Hacked Name"}
            result = webhook_handler._handle_update_webhook(
                sample_webhook.id, body, mock_http_handler
            )
            status = result.status_code

            # 404, not 403 — non-owners must not learn the webhook exists
            assert status == 404


# ============================================================================
# Handler Tests - POST /api/webhooks/:id/test
# ============================================================================


class TestTestWebhook:
    """Tests for POST /api/webhooks/:id/test endpoint."""

    def test_test_webhook_success(
        self, webhook_handler, mock_http_handler, mock_user, sample_webhook
    ):
        """Test sending a test webhook."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            with patch("aragora.events.dispatcher.dispatch_webhook") as mock_dispatch:
                mock_dispatch.return_value = (True, 200, None)
                result = webhook_handler._handle_test_webhook(sample_webhook.id, mock_http_handler)
                data, status = parse_handler_result(result)

                assert status == 200
                assert data["success"] is True
                assert data["status_code"] == 200
                mock_dispatch.assert_called_once()

    def test_test_webhook_delivery_failure(
        self, webhook_handler, mock_http_handler, mock_user, sample_webhook
    ):
        """Test handling delivery failure."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            with patch("aragora.events.dispatcher.dispatch_webhook") as mock_dispatch:
                mock_dispatch.return_value = (False, 500, "Connection refused")
                result = webhook_handler._handle_test_webhook(sample_webhook.id, mock_http_handler)
                data, status = parse_handler_result(result)

                assert status == 502
                assert data["success"] is False
                assert "error" in data

    def test_test_webhook_not_found(self, webhook_handler, mock_http_handler, mock_user):
        """Test sending to non-existent webhook."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            result = webhook_handler._handle_test_webhook("nonexistent-id", mock_http_handler)
            status = result.status_code

            assert status == 404

    def test_test_webhook_access_denied(
        self, webhook_handler, mock_http_handler, mock_other_user, sample_webhook
    ):
        """Test that users can't test other users' webhooks."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_other_user):
            result = webhook_handler._handle_test_webhook(sample_webhook.id, mock_http_handler)
            status = result.status_code

            # 404, not 403 — non-owners must not learn the webhook exists
            assert status == 404


# ============================================================================
# Handler Routing Tests
# ============================================================================


class TestHandlerRouting:
    """Tests for handler routing logic."""

    def test_can_handle_webhook_paths(self, webhook_handler):
        """Test that handler recognizes webhook paths."""
        assert WebhookHandler.can_handle("/api/v1/webhooks") is True
        assert WebhookHandler.can_handle("/api/v1/webhooks/events") is True
        assert WebhookHandler.can_handle("/api/v1/webhooks/abc-123") is True
        assert WebhookHandler.can_handle("/api/v1/webhooks/abc-123/test") is True

    def test_does_not_handle_other_paths(self, webhook_handler):
        """Test that handler doesn't claim unrelated paths."""
        assert WebhookHandler.can_handle("/api/v1/debates") is False
        assert WebhookHandler.can_handle("/api/v1/agents") is False
        assert WebhookHandler.can_handle("/health") is False


# ============================================================================
# WEBHOOK_EVENTS Set Tests
# ============================================================================


class TestWebhookEvents:
    """Tests for WEBHOOK_EVENTS constant."""

    def test_webhook_events_not_empty(self):
        """Test that WEBHOOK_EVENTS is populated."""
        assert len(WEBHOOK_EVENTS) > 0

    def test_webhook_events_contains_core_events(self):
        """Test that core events are included."""
        core_events = [
            "debate_start",
            "debate_end",
            "consensus",
            "agent_message",
            "vote",
        ]
        for event in core_events:
            assert event in WEBHOOK_EVENTS, f"Missing core event: {event}"

    def test_webhook_events_are_strings(self):
        """Test that all events are strings."""
        for event in WEBHOOK_EVENTS:
            assert isinstance(event, str)
            assert len(event) > 0


# ============================================================================
# Global Store Tests
# ============================================================================


class TestGlobalWebhookStore:
    """Tests for global webhook store singleton."""

    @pytest.fixture(autouse=True)
    def _reset_webhook_store_singleton(self):
        """Reset webhook store singleton before/after each test."""
        from aragora.storage.webhook_config_store import reset_webhook_config_store

        reset_webhook_config_store()
        yield
        reset_webhook_config_store()

    def test_get_webhook_store_singleton(self):
        """Test that get_webhook_store returns the same instance."""
        store1 = get_webhook_store()
        store2 = get_webhook_store()
        assert store1 is store2


# ============================================================================
# Input Validation Tests
# ============================================================================


class TestInputValidation:
    """Tests for input validation and security."""

    def test_url_injection_prevention(self, webhook_handler, mock_http_handler, mock_user):
        """Test that malicious URLs are rejected."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            malicious_urls = [
                "javascript:alert(1)",
                "file:///etc/passwd",
                "ftp://example.com/file",
            ]
            for url in malicious_urls:
                body = {"url": url, "events": ["debate_start"]}
                result = webhook_handler._handle_register_webhook(body, mock_http_handler)
                status = result.status_code
                assert status == 400, f"URL {url} should be rejected"

    def test_empty_url_rejected(self, webhook_handler, mock_http_handler, mock_user):
        """Test that empty URLs are rejected."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            body = {"url": "", "events": ["debate_start"]}
            result = webhook_handler._handle_register_webhook(body, mock_http_handler)
            status = result.status_code
            assert status == 400

    def test_whitespace_url_rejected(self, webhook_handler, mock_http_handler, mock_user):
        """Test that whitespace-only URLs are rejected."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            body = {"url": "   ", "events": ["debate_start"]}
            result = webhook_handler._handle_register_webhook(body, mock_http_handler)
            status = result.status_code
            assert status == 400

    def test_empty_events_rejected(self, webhook_handler, mock_http_handler, mock_user):
        """Test that empty events list is rejected."""
        with patch.object(webhook_handler, "get_current_user", return_value=mock_user):
            body = {"url": "https://example.com/hook", "events": []}
            result = webhook_handler._handle_register_webhook(body, mock_http_handler)
            status = result.status_code
            assert status == 400
