"""
Tests for EmailServicesHandler - Email Services HTTP endpoints.

Tests cover:
- Route matching (can_handle)
- RBAC permission enforcement
- Input validation
- Happy path operations for follow-ups, snooze, and categories
- Error handling
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.email_services import (
    EmailServicesHandler,
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
    _snoozed_emails,
    _snoozed_emails_lock,
)
from aragora.server.handlers.email.email_services import _followup_owners
from aragora.services.followup_tracker import FollowUpPriority
from aragora.services.snooze_recommender import SnoozeReason


# ===========================================================================
# Test Helpers
# ===========================================================================


def unwrap_response(body: dict) -> dict:
    """Unwrap success_response format if present.

    The success_response function wraps data in {"success": True, "data": {...}}.
    This helper extracts the data for easier assertions.
    """
    if isinstance(body, dict) and "data" in body and "success" in body:
        return body["data"]
    return body


# ===========================================================================
# Test Fixtures and Mocks
# ===========================================================================


class MockFollowUpStatus(str, Enum):
    """Mock follow-up status for testing."""

    AWAITING = "awaiting"
    OVERDUE = "overdue"
    RECEIVED = "received"
    RESOLVED = "resolved"


@dataclass
class MockFollowUpItem:
    """Mock follow-up item for testing."""

    id: str = "fu_test123"
    email_id: str = "email_001"
    thread_id: str = "thread_001"
    subject: str = "Test Subject"
    recipient: str = "test@example.com"
    sent_at: datetime = field(default_factory=datetime.now)
    expected_by: datetime | None = None
    status: MockFollowUpStatus = MockFollowUpStatus.AWAITING
    days_waiting: int = 2
    priority: FollowUpPriority = FollowUpPriority.NORMAL
    reminder_count: int = 0
    resolved_at: datetime | None = None
    updated_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        if self.expected_by is None:
            self.expected_by = self.sent_at + timedelta(days=3)

    @property
    def is_overdue(self) -> bool:
        """Check if follow-up is overdue."""
        if self.expected_by:
            return datetime.now() > self.expected_by
        return False


@dataclass
class MockSnoozeSuggestion:
    """Mock snooze suggestion for testing."""

    snooze_until: datetime
    label: str = "Tomorrow morning"
    reason: SnoozeReason = SnoozeReason.WORK_HOURS
    confidence: float = 0.85


@dataclass
class MockSnoozeRecommendation:
    """Mock snooze recommendation for testing."""

    suggestions: list[MockSnoozeSuggestion] = field(default_factory=list)
    recommended: MockSnoozeSuggestion | None = None

    def __post_init__(self):
        if not self.suggestions:
            tomorrow = datetime.now() + timedelta(days=1)
            tomorrow = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
            self.suggestions = [
                MockSnoozeSuggestion(snooze_until=tomorrow),
                MockSnoozeSuggestion(
                    snooze_until=datetime.now() + timedelta(hours=3),
                    label="Later today",
                ),
            ]
            self.recommended = self.suggestions[0]


class MockFollowUpTracker:
    """Mock follow-up tracker for testing."""

    def __init__(self):
        self._followups: dict[str, MockFollowUpItem] = {}

    async def mark_awaiting_reply(
        self,
        email_id: str,
        thread_id: str,
        subject: str,
        recipient: str,
        sent_at: datetime,
        expected_by: datetime,
        user_id: str = "default",
    ) -> MockFollowUpItem:
        item = MockFollowUpItem(
            id=f"fu_{email_id}_{datetime.now().timestamp()}",
            email_id=email_id,
            thread_id=thread_id,
            subject=subject,
            recipient=recipient,
            sent_at=sent_at,
            expected_by=expected_by,
        )
        self._followups[item.id] = item
        return item

    async def get_pending_followups(
        self,
        user_id: str = "default",
        include_resolved: bool = False,
        sort_by: str = "urgency",
        only_ids: set[str] | None = None,
    ) -> list[MockFollowUpItem]:
        items = [i for i in self._followups.values() if only_ids is None or i.id in only_ids]
        if not include_resolved:
            items = [
                i
                for i in items
                if i.status in [MockFollowUpStatus.AWAITING, MockFollowUpStatus.OVERDUE]
            ]
        return items

    async def resolve_followup(
        self,
        followup_id: str,
        status: str = "resolved",
        notes: str = "",
    ) -> MockFollowUpItem | None:
        item = self._followups.get(followup_id)
        if item:
            item.status = MockFollowUpStatus.RESOLVED
            item.resolved_at = datetime.now()
        return item

    async def check_for_replies(
        self, thread_ids: list[str], only_ids: set[str] | None = None
    ) -> list[MockFollowUpItem]:
        # Return empty list - no replies detected
        return []

    async def auto_detect_sent_emails(
        self,
        days_back: int = 7,
        user_id: str = "default",
    ) -> list[MockFollowUpItem]:
        # Return one detected email
        item = MockFollowUpItem(
            id="fu_auto_detected",
            email_id="auto_email_001",
            thread_id="auto_thread_001",
            subject="Auto-detected email",
            recipient="auto@example.com",
        )
        return [item]


class MockSnoozeRecommender:
    """Mock snooze recommender for testing."""

    async def recommend_snooze(
        self,
        email: dict[str, Any],
        priority_result: Any | None = None,
        max_suggestions: int = 5,
    ) -> MockSnoozeRecommendation:
        return MockSnoozeRecommendation()


class MockEmailCategorizer:
    """Mock email categorizer for testing."""

    async def record_feedback(
        self,
        email_id: str,
        predicted_category: str,
        correct_category: str,
        user_id: str,
        org_id: str | None,
        sender: str = "",
    ) -> None:
        pass


def create_mock_handler(
    method: str = "GET",
    body: dict[str, Any] | None = None,
    path: str = "/api/v1/email/followups/pending",
) -> MagicMock:
    """Create a mock HTTP handler for testing."""
    mock = MagicMock()
    mock.command = method
    mock.path = path

    if body is not None:
        body_bytes = json.dumps(body).encode()
    else:
        body_bytes = b"{}"

    mock.rfile = MagicMock()
    mock.rfile.read = MagicMock(return_value=body_bytes)

    mock.headers = {"Content-Length": str(len(body_bytes))}
    mock.client_address = ("127.0.0.1", 12345)
    mock.user_context = MagicMock()
    mock.user_context.user_id = "test_user"

    return mock


@dataclass
class MockAuthContext:
    """Mock authorization context for testing."""

    user_id: str = "test_user"
    org_id: str = "test_org"
    tenant_id: str = "test_tenant"
    roles: list[str] = field(default_factory=lambda: ["admin"])
    permissions: list[str] = field(
        default_factory=lambda: ["email:read", "email:create", "email:update", "email:delete"]
    )


@dataclass
class MockPermissionDecision:
    """Mock permission decision for RBAC."""

    allowed: bool = True
    reason: str = "allowed"


@pytest.fixture
def mock_auth_context():
    """Create mock auth context for tests that need authentication."""
    return MockAuthContext()


@pytest.fixture(autouse=True)
def auto_mock_rbac(request):
    """Auto-mock RBAC for most tests, skip for tests marked with no_auto_auth."""
    if "no_auto_auth" in [marker.name for marker in request.node.iter_markers()]:
        yield
        return

    with patch("aragora.server.handlers.email_services.check_permission") as mock_check:
        mock_check.return_value = MockPermissionDecision(allowed=True)
        yield mock_check


@pytest.fixture
def mock_server_context():
    """Create mock server context."""
    return MagicMock()


@pytest.fixture
def mock_followup_tracker():
    """Create mock follow-up tracker with sample data."""
    tracker = MockFollowUpTracker()
    # Add a sample follow-up
    import asyncio

    _loop = asyncio.new_event_loop()
    item = _loop.run_until_complete(
        tracker.mark_awaiting_reply(
            email_id="email_001",
            thread_id="thread_001",
            subject="Test Email",
            recipient="recipient@example.com",
            sent_at=datetime.now() - timedelta(days=2),
            expected_by=datetime.now() + timedelta(days=1),
        )
    )
    owner = (MockAuthContext.user_id, MockAuthContext.org_id)
    with patch.dict(_followup_owners, {item.id: owner}, clear=True):
        yield tracker


@pytest.fixture
def mock_snooze_recommender():
    """Create mock snooze recommender."""
    return MockSnoozeRecommender()


@pytest.fixture
def mock_email_categorizer():
    """Create mock email categorizer."""
    return MockEmailCategorizer()


@pytest.fixture
def handler(mock_server_context):
    """Create handler with mocked dependencies."""
    return EmailServicesHandler(mock_server_context)


@pytest.fixture(autouse=True)
def clear_snoozed_emails():
    """Clear the snoozed emails storage before each test."""
    with _snoozed_emails_lock:
        _snoozed_emails.clear()
    yield
    with _snoozed_emails_lock:
        _snoozed_emails.clear()


# ===========================================================================
# Route Matching Tests
# ===========================================================================


class TestEmailServicesHandlerRouting:
    """Test request routing."""

    def test_can_handle_followup_mark_path(self, handler):
        """Test that handler recognizes follow-up mark path."""
        assert handler.can_handle("/api/v1/email/followups/mark")

    def test_can_handle_followup_pending_path(self, handler):
        """Test that handler recognizes follow-up pending path."""
        assert handler.can_handle("/api/v1/email/followups/pending")

    def test_can_handle_followup_resolve_path(self, handler):
        """Test that handler recognizes follow-up resolve path."""
        assert handler.can_handle("/api/v1/email/followups/fu_123/resolve")

    def test_can_handle_followup_check_replies_path(self, handler):
        """Test that handler recognizes check-replies path."""
        assert handler.can_handle("/api/v1/email/followups/check-replies")

    def test_can_handle_snooze_suggestions_path(self, handler):
        """Test that handler recognizes snooze suggestions path."""
        assert handler.can_handle("/api/v1/email/email_123/snooze-suggestions")

    def test_can_handle_snooze_apply_path(self, handler):
        """Test that handler recognizes snooze apply path."""
        assert handler.can_handle("/api/v1/email/email_123/snooze")

    def test_can_handle_snoozed_emails_path(self, handler):
        """Test that handler recognizes snoozed emails path."""
        assert handler.can_handle("/api/v1/email/snoozed")

    def test_can_handle_categories_path(self, handler):
        """Test that handler recognizes categories path."""
        assert handler.can_handle("/api/v1/email/categories")

    def test_can_handle_category_learn_path(self, handler):
        """Test that handler recognizes category learn path."""
        assert handler.can_handle("/api/v1/email/categories/learn")

    def test_cannot_handle_other_paths(self, handler):
        """Test that handler rejects non-email paths."""
        assert not handler.can_handle("/api/v1/debates")
        assert not handler.can_handle("/api/v1/backups")
        assert not handler.can_handle("/api/v2/email/followups")


# ===========================================================================
# RBAC Permission Tests
# ===========================================================================


class TestEmailServicesHandlerRBAC:
    """Test RBAC permission enforcement."""

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_mark_followup_requires_auth(self, mock_server_context):
        """Test that marking follow-up requires authentication."""
        os.environ["ARAGORA_TEST_REAL_AUTH"] = "1"
        try:
            h = EmailServicesHandler(mock_server_context)
            mock_handler = create_mock_handler(
                method="POST",
                body={"email_id": "e1", "thread_id": "t1"},
                path="/api/v1/email/followups/mark",
            )

            result = await h.handle_post(
                "/api/v1/email/followups/mark",
                {"email_id": "e1", "thread_id": "t1"},
                mock_handler,
            )
            assert result is not None
            assert result.status_code == 401
        finally:
            del os.environ["ARAGORA_TEST_REAL_AUTH"]

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_apply_snooze_requires_auth(self, mock_server_context):
        """Test that applying snooze requires authentication."""
        os.environ["ARAGORA_TEST_REAL_AUTH"] = "1"
        try:
            h = EmailServicesHandler(mock_server_context)
            mock_handler = create_mock_handler(
                method="POST",
                body={"snooze_until": "2026-01-30T09:00:00"},
                path="/api/v1/email/email_123/snooze",
            )

            result = await h.handle_post(
                "/api/v1/email/email_123/snooze",
                {"snooze_until": "2026-01-30T09:00:00"},
                mock_handler,
            )
            assert result is not None
            assert result.status_code == 401
        finally:
            del os.environ["ARAGORA_TEST_REAL_AUTH"]

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_get_pending_requires_auth(self, mock_server_context):
        """Test that getting pending follow-ups requires authentication."""
        os.environ["ARAGORA_TEST_REAL_AUTH"] = "1"
        try:
            h = EmailServicesHandler(mock_server_context)
            mock_handler = create_mock_handler(
                method="GET",
                path="/api/v1/email/followups/pending",
            )

            result = await h.handle_get(
                "/api/v1/email/followups/pending",
                {},
                mock_handler,
            )
            assert result is not None
            assert result.status_code == 401
        finally:
            del os.environ["ARAGORA_TEST_REAL_AUTH"]


# ===========================================================================
# Input Validation Tests
# ===========================================================================


class TestEmailServicesValidation:
    """Test input validation."""

    @pytest.mark.asyncio
    async def test_mark_followup_missing_email_id(self, mock_auth_context):
        """Test marking follow-up without email_id returns 400."""
        with patch("aragora.server.handlers.email_services.get_followup_tracker") as mock_get:
            mock_get.return_value = MockFollowUpTracker()

            result = await handle_mark_followup(
                data={"thread_id": "t1"},
                user_id="test_user",
                auth_context=mock_auth_context,
            )

            assert result.status_code == 400
            body = unwrap_response(json.loads(result.body))
            assert "email_id" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_mark_followup_missing_thread_id(self, mock_auth_context):
        """Test marking follow-up without thread_id returns 400."""
        with patch("aragora.server.handlers.email_services.get_followup_tracker") as mock_get:
            mock_get.return_value = MockFollowUpTracker()

            result = await handle_mark_followup(
                data={"email_id": "e1"},
                user_id="test_user",
                auth_context=mock_auth_context,
            )

            assert result.status_code == 400
            body = unwrap_response(json.loads(result.body))
            assert "thread_id" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_apply_snooze_missing_snooze_until(self, mock_auth_context):
        """Test applying snooze without snooze_until returns 400."""
        result = await handle_apply_snooze(
            email_id="email_123",
            data={"label": "Test"},
            user_id="test_user",
            auth_context=mock_auth_context,
        )

        assert result.status_code == 400
        body = unwrap_response(json.loads(result.body))
        assert "snooze_until" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_apply_snooze_invalid_date_format(self, mock_auth_context):
        """Test applying snooze with invalid date format returns 400."""
        result = await handle_apply_snooze(
            email_id="email_123",
            data={"snooze_until": "not-a-valid-date"},
            user_id="test_user",
            auth_context=mock_auth_context,
        )

        assert result.status_code == 400
        body = unwrap_response(json.loads(result.body))
        assert "invalid" in body.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_category_feedback_missing_fields(self, mock_auth_context):
        """Test category feedback missing required fields returns 400."""
        with patch("aragora.server.handlers.email_services.get_email_categorizer") as mock_get:
            mock_get.return_value = MockEmailCategorizer()

            result = await handle_category_feedback(
                data={"email_id": "e1"},  # Missing predicted_category and correct_category
                user_id="test_user",
                auth_context=mock_auth_context,
            )

            assert result.status_code == 400
            body = unwrap_response(json.loads(result.body))
            assert "required" in body.get("error", "").lower()


# ===========================================================================
# Happy Path Tests - Follow-ups
# ===========================================================================


class TestMarkFollowup:
    """Test mark follow-up endpoint."""

    @pytest.mark.asyncio
    async def test_mark_followup_success(self, mock_auth_context):
        """Test successfully marking an email for follow-up."""
        with patch("aragora.server.handlers.email_services.get_followup_tracker") as mock_get:
            mock_get.return_value = MockFollowUpTracker()

            result = await handle_mark_followup(
                data={
                    "email_id": "email_001",
                    "thread_id": "thread_001",
                    "subject": "Test Subject",
                    "recipient": "test@example.com",
                    "sent_at": datetime.now().isoformat(),
                    "expected_reply_days": 5,
                },
                user_id="test_user",
                auth_context=mock_auth_context,
            )

            assert result.status_code == 200
            body = unwrap_response(json.loads(result.body))
            assert "followup_id" in body
            assert body["email_id"] == "email_001"
            assert body["thread_id"] == "thread_001"


class TestGetPendingFollowups:
    """Test get pending follow-ups endpoint."""

    @pytest.mark.asyncio
    async def test_get_pending_followups_success(self, mock_followup_tracker, mock_auth_context):
        """Test getting pending follow-ups."""
        with patch("aragora.server.handlers.email_services.get_followup_tracker") as mock_get:
            mock_get.return_value = mock_followup_tracker

            result = await handle_get_pending_followups(
                user_id="test_user",
                include_resolved=False,
                sort_by="urgency",
                auth_context=mock_auth_context,
            )

            assert result.status_code == 200
            body = unwrap_response(json.loads(result.body))
            assert "followups" in body
            assert "total" in body
            assert isinstance(body["followups"], list)


class TestResolveFollowup:
    """Test resolve follow-up endpoint."""

    @pytest.mark.asyncio
    async def test_resolve_followup_success(self, mock_followup_tracker, mock_auth_context):
        """Test resolving a follow-up."""
        with patch("aragora.server.handlers.email_services.get_followup_tracker") as mock_get:
            mock_get.return_value = mock_followup_tracker

            # Get a followup ID
            followups = list(mock_followup_tracker._followups.keys())
            if followups:
                followup_id = followups[0]

                result = await handle_resolve_followup(
                    followup_id=followup_id,
                    data={"status": "resolved", "notes": "Done"},
                    user_id="test_user",
                    auth_context=mock_auth_context,
                )

                assert result.status_code == 200
                body = unwrap_response(json.loads(result.body))
                assert body["followup_id"] == followup_id
                assert body["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_resolve_followup_not_found(self, mock_auth_context):
        """Test resolving non-existent follow-up returns 404."""
        with patch("aragora.server.handlers.email_services.get_followup_tracker") as mock_get:
            tracker = MockFollowUpTracker()
            mock_get.return_value = tracker

            result = await handle_resolve_followup(
                followup_id="nonexistent_id",
                data={"status": "resolved"},
                user_id="test_user",
                auth_context=mock_auth_context,
            )

            assert result.status_code == 404


class TestCheckReplies:
    """Test check replies endpoint."""

    @pytest.mark.asyncio
    async def test_check_replies_success(self, mock_followup_tracker, mock_auth_context):
        """Test checking for replies."""
        with patch("aragora.server.handlers.email_services.get_followup_tracker") as mock_get:
            mock_get.return_value = mock_followup_tracker

            result = await handle_check_replies(user_id="test_user", auth_context=mock_auth_context)

            assert result.status_code == 200
            body = unwrap_response(json.loads(result.body))
            assert "replied" in body
            assert "still_pending" in body


class TestAutoDetectFollowups:
    """Test auto-detect follow-ups endpoint."""

    @pytest.mark.asyncio
    async def test_auto_detect_followups_success(self, mock_auth_context):
        """Test auto-detecting emails needing follow-up."""
        with patch("aragora.server.handlers.email_services.get_followup_tracker") as mock_get:
            mock_get.return_value = MockFollowUpTracker()

            result = await handle_auto_detect_followups(
                user_id="test_user",
                days_back=7,
                auth_context=mock_auth_context,
            )

            assert result.status_code == 200
            body = unwrap_response(json.loads(result.body))
            assert "detected" in body
            assert "total_detected" in body


# ===========================================================================
# Happy Path Tests - Snooze
# ===========================================================================


class TestGetSnoozeSuggestions:
    """Test get snooze suggestions endpoint."""

    @pytest.mark.asyncio
    async def test_get_snooze_suggestions_success(self, mock_auth_context):
        """Test getting snooze suggestions for an email."""
        with patch("aragora.server.handlers.email_services.get_snooze_recommender") as mock_get:
            mock_get.return_value = MockSnoozeRecommender()

            result = await handle_get_snooze_suggestions(
                email_id="email_123",
                data={"subject": "Test", "sender": "test@example.com"},
                user_id="test_user",
                auth_context=mock_auth_context,
            )

            assert result.status_code == 200
            body = unwrap_response(json.loads(result.body))
            assert body["email_id"] == "email_123"
            assert "suggestions" in body
            assert isinstance(body["suggestions"], list)


class TestApplySnooze:
    """Test apply snooze endpoint."""

    @pytest.mark.asyncio
    async def test_apply_snooze_success(self, mock_auth_context):
        """Test applying snooze to an email."""
        snooze_until = (datetime.now() + timedelta(days=1)).isoformat()

        result = await handle_apply_snooze(
            email_id="email_123",
            data={"snooze_until": snooze_until, "label": "Tomorrow"},
            user_id="test_user",
            auth_context=mock_auth_context,
        )

        assert result.status_code == 200
        body = unwrap_response(json.loads(result.body))
        assert body["email_id"] == "email_123"
        assert body["status"] == "snoozed"
        assert body["label"] == "Tomorrow"


class TestCancelSnooze:
    """Test cancel snooze endpoint."""

    @pytest.mark.asyncio
    async def test_cancel_snooze_success(self, mock_auth_context):
        """Test canceling snooze on an email."""
        # First apply a snooze
        snooze_until = (datetime.now() + timedelta(days=1)).isoformat()
        await handle_apply_snooze(
            email_id="email_123",
            data={"snooze_until": snooze_until},
            user_id="test_user",
            auth_context=mock_auth_context,
        )

        # Then cancel it
        result = await handle_cancel_snooze(
            email_id="email_123",
            user_id="test_user",
            auth_context=mock_auth_context,
        )

        assert result.status_code == 200
        body = unwrap_response(json.loads(result.body))
        assert body["email_id"] == "email_123"
        assert body["status"] == "unsnooze"

    @pytest.mark.asyncio
    async def test_cancel_snooze_not_found(self, mock_auth_context):
        """Test canceling snooze on non-snoozed email returns 404."""
        result = await handle_cancel_snooze(
            email_id="not_snoozed_email",
            user_id="test_user",
            auth_context=mock_auth_context,
        )

        assert result.status_code == 404


class TestGetSnoozedEmails:
    """Test get snoozed emails endpoint."""

    @pytest.mark.asyncio
    async def test_get_snoozed_emails_success(self, mock_auth_context):
        """Test getting list of snoozed emails."""
        # First apply a snooze
        snooze_until = (datetime.now() + timedelta(days=1)).isoformat()
        await handle_apply_snooze(
            email_id="email_123",
            data={"snooze_until": snooze_until, "label": "Tomorrow"},
            user_id="test_user",
            auth_context=mock_auth_context,
        )

        result = await handle_get_snoozed_emails(
            user_id="test_user", auth_context=mock_auth_context
        )

        assert result.status_code == 200
        body = unwrap_response(json.loads(result.body))
        assert "snoozed" in body
        assert "total" in body
        assert body["total"] == 1


class TestProcessDueSnoozes:
    """Test process due snoozes endpoint."""

    @pytest.mark.asyncio
    async def test_process_due_snoozes_success(self, mock_auth_context):
        """Test processing snoozed emails that are now due."""
        # Apply a snooze that is already due
        snooze_until = (datetime.now() - timedelta(hours=1)).isoformat()
        await handle_apply_snooze(
            email_id="email_due",
            data={"snooze_until": snooze_until},
            user_id="test_user",
            auth_context=mock_auth_context,
        )

        result = await handle_process_due_snoozes(
            user_id="test_user", auth_context=mock_auth_context
        )

        assert result.status_code == 200
        body = unwrap_response(json.loads(result.body))
        assert "processed" in body
        assert "count" in body


# ===========================================================================
# Happy Path Tests - Categories
# ===========================================================================


class TestGetCategories:
    """Test get categories endpoint."""

    @pytest.mark.asyncio
    async def test_get_categories_success(self, mock_auth_context):
        """Test getting available email categories."""
        result = await handle_get_categories(user_id="test_user", auth_context=mock_auth_context)

        assert result.status_code == 200
        body = unwrap_response(json.loads(result.body))
        assert "categories" in body
        assert isinstance(body["categories"], list)
        assert len(body["categories"]) > 0

        # Check category structure
        for cat in body["categories"]:
            assert "id" in cat
            assert "name" in cat
            assert "description" in cat


class TestCategoryFeedback:
    """Test category feedback endpoint."""

    @pytest.mark.asyncio
    async def test_category_feedback_success(self, mock_auth_context):
        """Test submitting category feedback."""
        with patch("aragora.server.handlers.email_services.get_email_categorizer") as mock_get:
            mock_get.return_value = MockEmailCategorizer()

            result = await handle_category_feedback(
                data={
                    "email_id": "email_123",
                    "predicted_category": "newsletters",
                    "correct_category": "projects",
                },
                user_id="test_user",
                auth_context=mock_auth_context,
            )

            assert result.status_code == 200
            body = unwrap_response(json.loads(result.body))
            assert body["email_id"] == "email_123"
            assert body["feedback_recorded"] is True


# ===========================================================================
# Error Handling Tests
# ===========================================================================


class TestEmailServicesErrors:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_followup_tracker_error(self, mock_auth_context):
        """Test handling when follow-up tracker raises an error."""
        with patch("aragora.server.handlers.email_services.get_followup_tracker") as mock_get:
            tracker = MagicMock()
            tracker.mark_awaiting_reply = AsyncMock(side_effect=ValueError("Database error"))
            mock_get.return_value = tracker

            result = await handle_mark_followup(
                data={"email_id": "e1", "thread_id": "t1"},
                user_id="test_user",
                auth_context=mock_auth_context,
            )

            assert result.status_code == 500
            body = unwrap_response(json.loads(result.body))
            assert "error" in body

    @pytest.mark.asyncio
    async def test_snooze_recommender_error(self, mock_auth_context):
        """Test handling when snooze recommender raises an error."""
        with patch("aragora.server.handlers.email_services.get_snooze_recommender") as mock_get:
            recommender = MagicMock()
            recommender.recommend_snooze = AsyncMock(side_effect=ValueError("Service error"))
            mock_get.return_value = recommender

            result = await handle_get_snooze_suggestions(
                email_id="email_123",
                data={"subject": "Test"},
                user_id="test_user",
                auth_context=mock_auth_context,
            )

            assert result.status_code == 500
            body = unwrap_response(json.loads(result.body))
            assert "error" in body


# ===========================================================================
# Route Registration Tests
# ===========================================================================


class TestRouteRegistration:
    """Test route registration."""

    def test_get_email_services_routes_returns_correct_routes(self):
        """Test that route registration returns all expected routes."""
        routes = get_email_services_routes()

        # Check it returns a list of tuples
        assert isinstance(routes, list)
        assert len(routes) == 12  # 12 endpoints

        # Check route structure
        methods = [r[0] for r in routes]
        paths = [r[1] for r in routes]

        # Follow-up routes
        assert ("POST", "/api/v1/email/followups/mark") in [(r[0], r[1]) for r in routes]
        assert ("GET", "/api/v1/email/followups/pending") in [(r[0], r[1]) for r in routes]
        assert ("POST", "/api/v1/email/followups/{id}/resolve") in [(r[0], r[1]) for r in routes]
        assert ("POST", "/api/v1/email/followups/check-replies") in [(r[0], r[1]) for r in routes]
        assert ("POST", "/api/v1/email/followups/auto-detect") in [(r[0], r[1]) for r in routes]

        # Snooze routes
        assert ("GET", "/api/v1/email/{id}/snooze-suggestions") in [(r[0], r[1]) for r in routes]
        assert ("POST", "/api/v1/email/{id}/snooze") in [(r[0], r[1]) for r in routes]
        assert ("DELETE", "/api/v1/email/{id}/snooze") in [(r[0], r[1]) for r in routes]
        assert ("GET", "/api/v1/email/snoozed") in [(r[0], r[1]) for r in routes]

        # Category routes
        assert ("GET", "/api/v1/email/categories") in [(r[0], r[1]) for r in routes]
        assert ("POST", "/api/v1/email/categories/learn") in [(r[0], r[1]) for r in routes]


# ===========================================================================
# Handler Method Tests
# ===========================================================================


class TestHandlerMethods:
    """Test handler class methods."""

    @pytest.mark.no_auto_auth
    @pytest.mark.asyncio
    async def test_handle_get_categories_requires_auth(self, handler):
        """Test that categories endpoint requires authentication.

        Note: All email operations require authentication after the security
        hardening. The categories endpoint is no longer public.
        """
        os.environ["ARAGORA_TEST_REAL_AUTH"] = "1"
        try:
            mock_http = create_mock_handler(method="GET", path="/api/v1/email/categories")

            result = await handler.handle_get(
                "/api/v1/email/categories",
                {"user_id": "test_user"},
                mock_http,
            )

            assert result.status_code == 401
        finally:
            del os.environ["ARAGORA_TEST_REAL_AUTH"]

    @pytest.mark.asyncio
    async def test_handle_post_not_found(self, handler):
        """Test POST to unknown path returns 404."""
        mock_http = create_mock_handler(
            method="POST",
            body={},
            path="/api/v1/email/unknown/path",
        )

        result = await handler.handle_post(
            "/api/v1/email/unknown/path",
            {},
            mock_http,
        )

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_handle_get_not_found(self, handler):
        """Test GET to unknown path returns 404."""
        mock_http = create_mock_handler(method="GET", path="/api/v1/email/unknown")

        result = await handler.handle_get(
            "/api/v1/email/unknown",
            {},
            mock_http,
        )

        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_handle_delete_not_found(self, handler):
        """Test DELETE to non-snooze path returns 404."""
        mock_http = create_mock_handler(method="DELETE", path="/api/v1/email/unknown")

        result = await handler.handle_delete(
            "/api/v1/email/unknown",
            {},
            mock_http,
        )

        assert result.status_code == 404
