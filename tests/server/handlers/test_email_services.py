"""
Tests for Email Services Handler.

Tests the email services API endpoints including:
- Follow-up tracking
- Snooze recommendations
- Category management
"""

import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.server.handlers.email_services import (
    handle_mark_followup,
    handle_get_pending_followups,
    handle_resolve_followup,
    handle_check_replies,
    handle_auto_detect_followups,
    handle_get_snooze_suggestions,
    handle_apply_snooze,
    handle_cancel_snooze,
    handle_get_snoozed_emails,
    handle_process_due_snoozes,
    handle_get_categories,
    handle_category_feedback,
    get_email_services_routes,
)
from aragora.server.handlers.utils.responses import HandlerResult
from aragora.rbac.models import AuthorizationContext


@pytest.fixture
def admin_auth():
    """Create admin auth context for RBAC-protected handlers."""
    return AuthorizationContext(
        user_id="test-user-001",
        user_email="test@example.com",
        org_id="test-org-001",
        roles={"admin"},
        permissions={"*"},  # Wildcard grants all permissions
    )


@pytest.fixture(autouse=True)
def bypass_email_permission_check():
    """Bypass email permission checks for all tests in this module.

    The email_services handlers check RBAC permissions internally via
    _check_email_permission. This fixture patches it to always allow.
    """
    with patch(
        "aragora.server.handlers.email_services._check_email_permission",
        return_value=None,  # None = no error = allowed
    ):
        yield


def parse_result(result: HandlerResult) -> dict:
    """Parse HandlerResult body to dict for assertions."""
    data = json.loads(result.body.decode("utf-8"))
    data["_status_code"] = result.status_code
    # Normalize success field - if "error" exists, it's a failure
    if "success" not in data:
        data["success"] = "error" not in data
    return data


class TestEmailServicesRoutes:
    """Test route definitions."""

    def test_routes_defined(self):
        """Should define all expected routes."""
        routes = get_email_services_routes()
        route_paths = [r[1] for r in routes]

        # Follow-up routes
        assert "/api/v1/email/followups/mark" in route_paths
        assert "/api/v1/email/followups/pending" in route_paths
        assert "/api/v1/email/followups/{id}/resolve" in route_paths
        assert "/api/v1/email/followups/check-replies" in route_paths
        assert "/api/v1/email/followups/auto-detect" in route_paths

        # Snooze routes
        assert "/api/v1/email/{id}/snooze-suggestions" in route_paths
        assert "/api/v1/email/{id}/snooze" in route_paths
        assert "/api/v1/email/snoozed" in route_paths
        assert "/api/v1/email/snooze/process-due" in route_paths

        # Category routes
        assert "/api/v1/email/categories" in route_paths
        assert "/api/v1/email/categories/learn" in route_paths

    def test_route_methods(self):
        """Should use correct HTTP methods."""
        routes = get_email_services_routes()
        route_dict = {r[1]: r[0] for r in routes}

        assert route_dict["/api/v1/email/followups/mark"] == "POST"
        assert route_dict["/api/v1/email/followups/pending"] == "GET"
        assert route_dict["/api/v1/email/followups/{id}/resolve"] == "POST"
        assert route_dict["/api/v1/email/{id}/snooze"] == "DELETE"
        assert route_dict["/api/v1/email/categories"] == "GET"


class TestFollowUpHandlers:
    """Test follow-up tracking handlers."""

    @pytest.fixture
    def mock_tracker(self):
        """Create mock follow-up tracker."""
        with patch("aragora.server.handlers.email_services.get_followup_tracker") as mock:
            tracker = MagicMock()
            mock.return_value = tracker
            yield tracker

    @pytest.mark.asyncio
    async def test_mark_followup_success(self, mock_tracker, admin_auth):
        """Should successfully mark email for follow-up."""
        mock_item = MagicMock()
        mock_item.id = "fu_123"
        mock_item.email_id = "email_123"
        mock_item.thread_id = "thread_123"
        mock_item.subject = "Test Subject"
        mock_item.recipient = "test@example.com"
        mock_item.sent_at = datetime.now()
        mock_item.expected_by = datetime.now() + timedelta(days=3)
        mock_item.status.value = "awaiting"
        mock_item.days_waiting = 0

        mock_tracker.mark_awaiting_reply = AsyncMock(return_value=mock_item)

        data = {
            "email_id": "email_123",
            "thread_id": "thread_123",
            "subject": "Test Subject",
            "recipient": "test@example.com",
            "sent_at": datetime.now().isoformat(),
        }

        result = parse_result(
            await handle_mark_followup(data, user_id="user_1", auth_context=admin_auth)
        )

        assert result["success"] is True
        assert result["data"]["followup_id"] == "fu_123"
        assert result["data"]["status"] == "awaiting"

    @pytest.mark.asyncio
    async def test_mark_followup_missing_required(self, mock_tracker, admin_auth):
        """Should fail when missing required fields."""
        result = parse_result(
            await handle_mark_followup({"email_id": "123"}, auth_context=admin_auth)
        )

        assert result["success"] is False or "error" in result
        assert "thread_id" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_get_pending_followups(self, mock_tracker, admin_auth):
        """Should return pending follow-ups."""
        mock_item = MagicMock()
        mock_item.id = "fu_123"
        mock_item.email_id = "email_123"
        mock_item.thread_id = "thread_123"
        mock_item.subject = "Test"
        mock_item.recipient = "test@example.com"
        mock_item.sent_at = datetime.now()
        mock_item.expected_by = datetime.now() + timedelta(days=1)
        mock_item.status.value = "awaiting"
        mock_item.days_waiting = 2
        mock_item.urgency_score = 0.7
        mock_item.reminder_count = 0
        mock_item.is_overdue = False

        mock_tracker.get_pending_followups = AsyncMock(return_value=[mock_item])

        result = parse_result(await handle_get_pending_followups(auth_context=admin_auth))

        assert result["success"] is True
        assert len(result["data"]["followups"]) == 1
        assert result["data"]["total"] == 1
        assert result["data"]["overdue_count"] == 0

    @pytest.mark.asyncio
    async def test_resolve_followup_success(self, mock_tracker, admin_auth):
        """Should resolve follow-up successfully."""
        mock_item = MagicMock()
        mock_item.id = "fu_123"
        mock_item.status.value = "received"
        mock_item.resolved_at = datetime.now()

        mock_tracker.resolve_followup = AsyncMock(return_value=mock_item)

        result = parse_result(
            await handle_resolve_followup(
                followup_id="fu_123",
                data={"status": "received"},
                user_id="user_1",
                auth_context=admin_auth,
            )
        )

        assert result["success"] is True
        assert result["data"]["status"] == "received"

    @pytest.mark.asyncio
    async def test_resolve_followup_not_found(self, mock_tracker, admin_auth):
        """Should return 404 when follow-up not found."""
        mock_tracker.resolve_followup = AsyncMock(return_value=None)

        result = parse_result(
            await handle_resolve_followup(
                followup_id="fu_invalid",
                data={"status": "received"},
                auth_context=admin_auth,
            )
        )

        assert result["success"] is False or "error" in result
        assert result["_status_code"] == 404

    @pytest.mark.asyncio
    async def test_check_replies(self, mock_tracker, admin_auth):
        """Should check for replies."""
        mock_tracker.get_pending_followups = AsyncMock(return_value=[])
        mock_tracker.check_for_replies = AsyncMock(return_value=[])

        result = parse_result(await handle_check_replies(auth_context=admin_auth))

        assert result["success"] is True
        assert result["data"]["replied"] == []
        assert result["data"]["still_pending"] == 0


class TestSnoozeHandlers:
    """Test snooze recommendation handlers."""

    @pytest.fixture
    def mock_recommender(self):
        """Create mock snooze recommender."""
        with patch("aragora.server.handlers.email_services.get_snooze_recommender") as mock:
            recommender = MagicMock()
            mock.return_value = recommender
            yield recommender

    @pytest.mark.asyncio
    async def test_get_snooze_suggestions(self, mock_recommender):
        """Should return snooze suggestions."""
        mock_suggestion = MagicMock()
        mock_suggestion.snooze_until = datetime.now() + timedelta(hours=2)
        mock_suggestion.label = "In 2 hours"
        mock_suggestion.reason.value = "work_hours"
        mock_suggestion.confidence = 0.8

        mock_recommendation = MagicMock()
        mock_recommendation.suggestions = [mock_suggestion]
        mock_recommendation.recommended = mock_suggestion

        mock_recommender.recommend_snooze = AsyncMock(return_value=mock_recommendation)

        result = parse_result(
            await handle_get_snooze_suggestions(
                email_id="email_123",
                data={"subject": "Test", "sender": "test@example.com"},
            )
        )

        assert result["success"] is True
        assert len(result["data"]["suggestions"]) >= 1
        assert result["data"]["recommended"] is not None

    @pytest.mark.asyncio
    async def test_apply_snooze_success(self, admin_auth):
        """Should apply snooze successfully."""
        snooze_until = (datetime.now() + timedelta(hours=2)).isoformat()

        result = parse_result(
            await handle_apply_snooze(
                email_id="email_123",
                data={"snooze_until": snooze_until},
                user_id="user_1",
                auth_context=admin_auth,
            )
        )

        assert result["success"] is True
        assert result["data"]["status"] == "snoozed"

    @pytest.mark.asyncio
    async def test_apply_snooze_missing_time(self, admin_auth):
        """Should fail without snooze_until."""
        result = parse_result(
            await handle_apply_snooze(
                email_id="email_123",
                data={},
                auth_context=admin_auth,
            )
        )

        assert result["success"] is False or "error" in result
        assert "snooze_until" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_apply_snooze_invalid_time(self, admin_auth):
        """Should fail with invalid time format."""
        result = parse_result(
            await handle_apply_snooze(
                email_id="email_123",
                data={"snooze_until": "invalid-date"},
                auth_context=admin_auth,
            )
        )

        assert result["success"] is False or "error" in result

    @pytest.mark.asyncio
    async def test_get_snoozed_emails(self, admin_auth):
        """Should return snoozed emails list."""
        # First snooze an email
        snooze_until = (datetime.now() + timedelta(hours=2)).isoformat()
        await handle_apply_snooze(
            email_id="email_test",
            data={"snooze_until": snooze_until},
            user_id="user_1",
            auth_context=admin_auth,
        )

        result = parse_result(await handle_get_snoozed_emails(auth_context=admin_auth))

        assert result["success"] is True
        assert "snoozed" in result["data"]
        assert "total" in result["data"]

    @pytest.mark.asyncio
    async def test_cancel_snooze(self, admin_auth):
        """Should cancel snooze."""
        # First snooze an email
        snooze_until = (datetime.now() + timedelta(hours=2)).isoformat()
        await handle_apply_snooze(
            email_id="email_cancel_test",
            data={"snooze_until": snooze_until},
            user_id="user_1",
            auth_context=admin_auth,
        )

        result = parse_result(
            await handle_cancel_snooze(
                email_id="email_cancel_test",
                user_id="user_1",
                auth_context=admin_auth,
            )
        )

        assert result["success"] is True
        assert result["data"]["status"] == "unsnooze"

    @pytest.mark.asyncio
    async def test_cancel_snooze_not_found(self, admin_auth):
        """Should return 404 when email not snoozed."""
        result = parse_result(
            await handle_cancel_snooze(
                email_id="email_not_snoozed",
                user_id="user_1",
                auth_context=admin_auth,
            )
        )

        assert result["success"] is False or "error" in result
        assert result["_status_code"] == 404


class TestCategoryHandlers:
    """Test category management handlers."""

    @pytest.mark.asyncio
    async def test_get_categories(self):
        """Should return available categories."""
        result = parse_result(await handle_get_categories())

        assert result["success"] is True
        assert "categories" in result["data"]
        assert len(result["data"]["categories"]) > 0

        # Check category structure
        cat = result["data"]["categories"][0]
        assert "id" in cat
        assert "name" in cat
        assert "description" in cat

    @pytest.mark.asyncio
    async def test_category_feedback_is_not_implemented(self, admin_auth):
        """Authorized category feedback answers 501; nothing is learned."""
        result = parse_result(
            await handle_category_feedback(
                data={
                    "email_id": "email_123",
                    "predicted_category": "newsletters",
                    "correct_category": "projects",
                },
                user_id="user_1",
                auth_context=admin_auth,
            )
        )

        assert result["_status_code"] == 501
        assert result["error"]["code"] == "not_implemented"


class TestProcessDueSnoozes:
    """Test snooze processing handlers."""

    @pytest.mark.asyncio
    async def test_process_due_snoozes(self, admin_auth):
        """Should process due snoozes."""
        # Snooze with past time
        with patch(
            "aragora.server.handlers.email_services._snoozed_emails",
            {
                "email_due": {
                    "email_id": "email_due",
                    "user_id": "user_1",
                    "snooze_until": datetime.now() - timedelta(hours=1),
                    "label": "Test",
                    "snoozed_at": datetime.now() - timedelta(hours=2),
                }
            },
        ):
            result = parse_result(
                await handle_process_due_snoozes(user_id="user_1", auth_context=admin_auth)
            )

        assert result["success"] is True
        assert "processed" in result["data"]
        assert "count" in result["data"]


class TestAutoDetectFollowups:
    """Test auto-detection of follow-ups."""

    @pytest.fixture
    def mock_tracker(self):
        """Create mock follow-up tracker."""
        with patch("aragora.server.handlers.email_services.get_followup_tracker") as mock:
            tracker = MagicMock()
            mock.return_value = tracker
            yield tracker

    @pytest.mark.asyncio
    async def test_auto_detect_followups(self, mock_tracker, admin_auth):
        """Should auto-detect sent emails needing follow-up."""
        mock_item = MagicMock()
        mock_item.id = "fu_auto_123"
        mock_item.email_id = "email_sent_123"
        mock_item.subject = "Auto-detected"
        mock_item.recipient = "test@example.com"
        mock_item.sent_at = datetime.now() - timedelta(days=3)
        mock_item.days_waiting = 3

        mock_tracker.auto_detect_sent_emails = AsyncMock(return_value=[mock_item])

        result = parse_result(
            await handle_auto_detect_followups(
                user_id="user_1",
                days_back=7,
                auth_context=admin_auth,
            )
        )

        assert result["success"] is True
        assert "detected" in result["data"]
        assert result["data"]["total_detected"] == 1
