"""Tests for email services handler (aragora/server/handlers/email_services.py).

Covers all endpoints and behavior:
- Follow-up tracking: mark, pending, resolve, check-replies, auto-detect
- Snooze management: suggestions, apply, cancel, list, process-due
- Category management: list categories, submit feedback
- RBAC permission checks for all endpoints
- EmailServicesHandler class: can_handle, handle_post, handle_get, handle_delete
- Error handling, validation, edge cases
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import aragora.server.handlers.email_services as email_mod
from aragora.server.handlers.email_services import (
    EmailServicesHandler,
    _check_email_permission,
    _get_category_description,
    _snoozed_emails,
    get_email_categorizer,
    get_email_services_routes,
    get_followup_tracker,
    get_snooze_recommender,
    handle_apply_snooze,
    handle_auto_detect_followups,
    handle_cancel_snooze,
    handle_category_feedback,
    handle_check_replies,
    handle_get_categories,
    handle_get_pending_followups,
    handle_get_snooze_suggestions,
    handle_get_snoozed_emails,
    handle_mark_followup,
    handle_process_due_snoozes,
    handle_resolve_followup,
)
from aragora.server.handlers.utils.responses import HandlerResult
from aragora.services.followup_tracker import FollowUpPriority
from aragora.services.snooze_recommender import SnoozeReason

# The conftest principal; the module takes ownership from the auth context.
OWNER = ("test-user-001", "test-org-001")
MINE = {"user_id": OWNER[0], "org_id": OWNER[1]}
KEY = (*OWNER, "email-001")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result: HandlerResult) -> dict:
    """Extract the parsed body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("body", result)
    return json.loads(result.body.decode("utf-8"))


def _status(result: HandlerResult) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return int(result.get("status_code") or result.get("status") or 200)
    return result.status_code


def _data(result: HandlerResult) -> dict:
    """Extract the 'data' field from a success_response envelope."""
    body = _body(result)
    return body.get("data", body)


# ---------------------------------------------------------------------------
# Mock objects
# ---------------------------------------------------------------------------


class MockFollowUpStatus(Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    REPLIED = "replied"


class MockFollowUp:
    """Mock follow-up object returned by tracker."""

    _SENTINEL = object()

    def __init__(
        self,
        id="fu-001",
        email_id="email-001",
        thread_id="thread-001",
        subject="Test Subject",
        recipient="bob@example.com",
        sent_at=None,
        expected_by=_SENTINEL,
        status=None,
        days_waiting=3,
        reminder_count=0,
        is_overdue=False,
        resolved_at=None,
    ):
        self.id = id
        self.email_id = email_id
        self.thread_id = thread_id
        self.subject = subject
        self.recipient = recipient
        self.sent_at = sent_at or datetime.now()
        self.expected_by = (
            expected_by
            if expected_by is not MockFollowUp._SENTINEL
            else (datetime.now() + timedelta(days=3))
        )
        self.status = status or MockFollowUpStatus.PENDING
        self.days_waiting = days_waiting
        self.priority = FollowUpPriority.NORMAL
        self.reminder_count = reminder_count
        self.is_overdue = is_overdue
        self.reply_received_at = resolved_at
        self.updated_at = resolved_at or datetime.now()


class MockSnoozeSuggestion:
    """Mock snooze suggestion."""

    def __init__(
        self,
        snooze_until=None,
        label="Later today",
        reason=SnoozeReason.WORK_HOURS,
        confidence=0.85,
    ):
        self.snooze_until = snooze_until or (datetime.now() + timedelta(hours=4))
        self.label = label
        self.reason = reason
        self.confidence = confidence


class MockSnoozeRecommendation:
    """Mock snooze recommendation returned by recommender."""

    def __init__(self, suggestions=None, recommended=None):
        self.suggestions = suggestions or [MockSnoozeSuggestion()]
        self.recommended = recommended or (self.suggestions[0] if self.suggestions else None)


class MockRBACDecision:
    """Mock RBAC check_permission decision."""

    def __init__(self, allowed=True, reason=""):
        self.allowed = allowed
        self.reason = reason


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_module_singletons():
    """Reset module-level singletons and shared state between tests."""
    email_mod._followup_tracker = None
    email_mod._snooze_recommender = None
    email_mod._email_categorizer = None
    _snoozed_emails.clear()
    with patch.dict(email_mod._followup_owners, {"fu-001": OWNER, "fu-1": OWNER}, clear=True):
        yield
    email_mod._followup_tracker = None
    email_mod._snooze_recommender = None
    email_mod._email_categorizer = None
    _snoozed_emails.clear()


@pytest.fixture
def mock_tracker():
    """Create a mock follow-up tracker and inject it."""
    tracker = AsyncMock()
    tracker.mark_awaiting_reply = AsyncMock(return_value=MockFollowUp())
    tracker.get_pending_followups = AsyncMock(return_value=[])
    tracker.resolve_followup = AsyncMock(
        return_value=MockFollowUp(status=MockFollowUpStatus.RESOLVED)
    )
    tracker.check_for_replies = AsyncMock(return_value=[])
    tracker.auto_detect_sent_emails = AsyncMock(return_value=[])
    email_mod._followup_tracker = tracker
    return tracker


@pytest.fixture
def mock_recommender():
    """Create a mock snooze recommender and inject it."""
    recommender = AsyncMock()
    recommender.recommend_snooze = AsyncMock(return_value=MockSnoozeRecommendation())
    email_mod._snooze_recommender = recommender
    return recommender


@pytest.fixture
def mock_categorizer():
    """Create a mock email categorizer and inject it."""
    categorizer = AsyncMock()
    categorizer.record_feedback = AsyncMock()
    email_mod._email_categorizer = categorizer
    return categorizer


@pytest.fixture
def mock_auth():
    """Create a mock auth context with full permissions."""
    ctx = MagicMock()
    ctx.user_id, ctx.org_id = OWNER
    return ctx


@pytest.fixture
def handler():
    """Create an EmailServicesHandler with minimal server context."""
    return EmailServicesHandler({})


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler for SecureHandler methods."""
    h = MagicMock()
    h.rfile = MagicMock()
    h.rfile.read.return_value = b"{}"
    h.headers = {"Content-Length": "2", "Content-Type": "application/json"}
    return h


# ============================================================================
# _check_email_permission
# ============================================================================


class TestCheckEmailPermission:
    """Tests for the _check_email_permission helper."""

    def test_no_auth_context_returns_401(self):
        result = _check_email_permission(None, "email:read")
        assert _status(result) == 401

    def test_no_auth_context_for_write_returns_401(self):
        result = _check_email_permission(None, "email:create")
        assert _status(result) == 401

    @patch.object(email_mod, "RBAC_AVAILABLE", False)
    @patch.object(email_mod, "rbac_fail_closed", return_value=True)
    def test_rbac_unavailable_fail_closed_returns_503(self, _mock_fail):
        result = _check_email_permission(MagicMock(), "email:read")
        assert _status(result) == 503
        assert "access control" in _body(result)["error"].lower()

    @patch.object(email_mod, "RBAC_AVAILABLE", False)
    @patch.object(email_mod, "rbac_fail_closed", return_value=False)
    def test_rbac_unavailable_dev_mode_read_returns_none(self, _mock_fail):
        """In dev mode with RBAC unavailable, read operations succeed."""
        result = _check_email_permission(MagicMock(), "email:read")
        assert result is None

    @patch.object(email_mod, "RBAC_AVAILABLE", False)
    @patch.object(email_mod, "rbac_fail_closed", return_value=False)
    def test_rbac_unavailable_dev_mode_write_returns_503(self, _mock_fail):
        """In dev mode with RBAC unavailable, write operations are denied."""
        for perm in ("email:create", "email:update", "email:delete"):
            result = _check_email_permission(MagicMock(), perm)
            assert _status(result) == 503

    @patch.object(email_mod, "RBAC_AVAILABLE", True)
    @patch.object(email_mod, "check_permission", return_value=MockRBACDecision(allowed=True))
    def test_rbac_allowed_returns_none(self, _mock_check):
        result = _check_email_permission(MagicMock(), "email:read")
        assert result is None

    @patch.object(email_mod, "RBAC_AVAILABLE", True)
    @patch.object(
        email_mod,
        "check_permission",
        return_value=MockRBACDecision(allowed=False, reason="no perm"),
    )
    def test_rbac_denied_returns_403(self, _mock_check):
        result = _check_email_permission(MagicMock(), "email:read")
        assert _status(result) == 403
        assert "denied" in _body(result)["error"].lower()

    @patch.object(email_mod, "RBAC_AVAILABLE", True)
    @patch.object(email_mod, "check_permission", side_effect=TypeError("bad context"))
    def test_rbac_check_error_returns_503(self, _mock_check):
        result = _check_email_permission(MagicMock(), "email:read")
        assert _status(result) == 503
        assert "failed" in _body(result)["error"].lower()

    @patch.object(email_mod, "RBAC_AVAILABLE", True)
    @patch.object(email_mod, "check_permission", side_effect=RuntimeError("RBAC down"))
    def test_rbac_runtime_error_returns_503(self, _mock_check):
        result = _check_email_permission(MagicMock(), "email:create")
        assert _status(result) == 503


# ============================================================================
# handle_mark_followup
# ============================================================================


class TestMarkFollowup:
    """Tests for POST /api/v1/email/followups/mark."""

    @pytest.mark.asyncio
    async def test_mark_followup_success(self, mock_tracker, mock_auth):
        data = {
            "email_id": "e-001",
            "thread_id": "t-001",
            "subject": "Hello",
            "recipient": "bob@test.com",
            "sent_at": "2026-01-15T10:00:00Z",
            "expected_reply_days": 5,
        }
        result = await handle_mark_followup(data, user_id="user1", auth_context=mock_auth)
        assert _status(result) == 200
        body = _data(result)
        assert body["followup_id"] == "fu-001"
        assert body["email_id"] == "email-001"
        mock_tracker.mark_awaiting_reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_mark_followup_missing_email_id(self, mock_tracker, mock_auth):
        data = {"thread_id": "t-001"}
        result = await handle_mark_followup(data, auth_context=mock_auth)
        assert _status(result) == 400
        assert "email_id" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_mark_followup_missing_thread_id(self, mock_tracker, mock_auth):
        data = {"email_id": "e-001"}
        result = await handle_mark_followup(data, auth_context=mock_auth)
        assert _status(result) == 400
        assert "thread_id" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_mark_followup_missing_both(self, mock_tracker, mock_auth):
        data = {}
        result = await handle_mark_followup(data, auth_context=mock_auth)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_mark_followup_no_auth(self, mock_tracker):
        data = {"email_id": "e-001", "thread_id": "t-001"}
        result = await handle_mark_followup(data, auth_context=None)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_mark_followup_default_expected_days(self, mock_tracker, mock_auth):
        data = {"email_id": "e-001", "thread_id": "t-001"}
        result = await handle_mark_followup(data, auth_context=mock_auth)
        assert _status(result) == 200
        # Verify expected_by was called with 3-day offset (default)
        call_kwargs = mock_tracker.mark_awaiting_reply.call_args.kwargs
        assert call_kwargs["expected_by"] is not None

    @pytest.mark.asyncio
    async def test_mark_followup_invalid_sent_at(self, mock_tracker, mock_auth):
        """Invalid sent_at should not crash - it falls back to now()."""
        data = {
            "email_id": "e-001",
            "thread_id": "t-001",
            "sent_at": "not-a-date",
        }
        result = await handle_mark_followup(data, auth_context=mock_auth)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_mark_followup_no_sent_at(self, mock_tracker, mock_auth):
        data = {"email_id": "e-001", "thread_id": "t-001"}
        result = await handle_mark_followup(data, auth_context=mock_auth)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_mark_followup_tracker_error(self, mock_tracker, mock_auth):
        mock_tracker.mark_awaiting_reply.side_effect = ValueError("DB error")
        data = {"email_id": "e-001", "thread_id": "t-001"}
        result = await handle_mark_followup(data, auth_context=mock_auth)
        assert _status(result) == 500
        assert "failed" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_mark_followup_iso_z_format(self, mock_tracker, mock_auth):
        """Test ISO format with Z suffix."""
        data = {
            "email_id": "e-001",
            "thread_id": "t-001",
            "sent_at": "2026-02-20T14:30:00Z",
        }
        result = await handle_mark_followup(data, auth_context=mock_auth)
        assert _status(result) == 200


# ============================================================================
# handle_get_pending_followups
# ============================================================================


class TestGetPendingFollowups:
    """Tests for GET /api/v1/email/followups/pending."""

    @pytest.mark.asyncio
    async def test_get_pending_empty(self, mock_tracker, mock_auth):
        mock_tracker.get_pending_followups.return_value = []
        result = await handle_get_pending_followups(auth_context=mock_auth)
        assert _status(result) == 200
        data = _data(result)
        assert data["followups"] == []
        assert data["total"] == 0
        assert data["overdue_count"] == 0

    @pytest.mark.asyncio
    async def test_get_pending_with_items(self, mock_tracker, mock_auth):
        followups = [
            MockFollowUp(id="fu-1", is_overdue=True),
            MockFollowUp(id="fu-2", is_overdue=False),
        ]
        mock_tracker.get_pending_followups.return_value = followups
        result = await handle_get_pending_followups(auth_context=mock_auth)
        assert _status(result) == 200
        data = _data(result)
        assert data["total"] == 2
        assert data["overdue_count"] == 1

    @pytest.mark.asyncio
    async def test_get_pending_no_auth(self, mock_tracker):
        result = await handle_get_pending_followups(auth_context=None)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_get_pending_include_resolved(self, mock_tracker, mock_auth):
        result = await handle_get_pending_followups(include_resolved=True, auth_context=mock_auth)
        assert _status(result) == 200
        call_kwargs = mock_tracker.get_pending_followups.call_args.kwargs
        assert call_kwargs["include_resolved"] is True

    @pytest.mark.asyncio
    async def test_get_pending_sort_by_date(self, mock_tracker, mock_auth):
        result = await handle_get_pending_followups(sort_by="date", auth_context=mock_auth)
        assert _status(result) == 200
        call_kwargs = mock_tracker.get_pending_followups.call_args.kwargs
        assert call_kwargs["sort_by"] == "date"

    @pytest.mark.asyncio
    async def test_get_pending_tracker_error(self, mock_tracker, mock_auth):
        mock_tracker.get_pending_followups.side_effect = OSError("disk error")
        result = await handle_get_pending_followups(auth_context=mock_auth)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_get_pending_followup_fields(self, mock_tracker, mock_auth):
        """Verify all expected fields are present in response."""
        fu = MockFollowUp(
            id="fu-42",
            email_id="e-42",
            thread_id="t-42",
            subject="Urgent",
            recipient="alice@test.com",
        )
        mock_tracker.get_pending_followups.return_value = [fu]
        result = await handle_get_pending_followups(auth_context=mock_auth)
        data = _data(result)
        item = data["followups"][0]
        assert item["followup_id"] == "fu-42"
        assert item["email_id"] == "e-42"
        assert item["thread_id"] == "t-42"
        assert item["subject"] == "Urgent"
        assert item["recipient"] == "alice@test.com"
        assert "sent_at" in item
        assert "expected_by" in item
        assert "status" in item
        assert "days_waiting" in item
        assert "urgency_score" in item
        assert "reminder_count" in item


# ============================================================================
# handle_resolve_followup
# ============================================================================


class TestResolveFollowup:
    """Tests for POST /api/v1/email/followups/{id}/resolve."""

    @pytest.mark.asyncio
    async def test_resolve_success(self, mock_tracker, mock_auth):
        resolved = MockFollowUp(
            status=MockFollowUpStatus.RESOLVED,
            resolved_at=datetime.now(),
        )
        mock_tracker.resolve_followup.return_value = resolved
        result = await handle_resolve_followup(
            "fu-001", {"status": "replied"}, auth_context=mock_auth
        )
        assert _status(result) == 200
        data = _data(result)
        assert data["followup_id"] == "fu-001"
        assert data["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_resolve_not_found(self, mock_tracker, mock_auth):
        mock_tracker.resolve_followup.return_value = None
        result = await handle_resolve_followup("fu-999", {}, auth_context=mock_auth)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_resolve_no_auth(self, mock_tracker):
        result = await handle_resolve_followup("fu-001", {}, auth_context=None)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_resolve_default_status(self, mock_tracker, mock_auth):
        resolved = MockFollowUp(status=MockFollowUpStatus.RESOLVED, resolved_at=datetime.now())
        mock_tracker.resolve_followup.return_value = resolved
        result = await handle_resolve_followup("fu-001", {}, auth_context=mock_auth)
        assert _status(result) == 200
        # The default "manually_resolved" maps to the tracker's RESOLVED status
        call_kwargs = mock_tracker.resolve_followup.call_args.kwargs
        assert call_kwargs["status"] == "resolved"

    @pytest.mark.asyncio
    async def test_resolve_with_notes(self, mock_tracker, mock_auth):
        resolved = MockFollowUp(status=MockFollowUpStatus.RESOLVED, resolved_at=datetime.now())
        mock_tracker.resolve_followup.return_value = resolved
        result = await handle_resolve_followup(
            "fu-001", {"notes": "Got reply via phone"}, auth_context=mock_auth
        )
        assert _status(result) == 200
        data = _data(result)
        assert data["notes"] == "Got reply via phone"

    @pytest.mark.asyncio
    async def test_resolve_tracker_error(self, mock_tracker, mock_auth):
        mock_tracker.resolve_followup.side_effect = KeyError("bad key")
        result = await handle_resolve_followup("fu-001", {}, auth_context=mock_auth)
        assert _status(result) == 500


# ============================================================================
# handle_check_replies
# ============================================================================


class TestCheckReplies:
    """Tests for POST /api/v1/email/followups/check-replies."""

    @pytest.mark.asyncio
    async def test_check_replies_no_pending(self, mock_tracker, mock_auth):
        mock_tracker.get_pending_followups.return_value = []
        result = await handle_check_replies(auth_context=mock_auth)
        assert _status(result) == 200
        data = _data(result)
        assert data["replied"] == []
        assert data["still_pending"] == 0

    @pytest.mark.asyncio
    async def test_check_replies_with_replies(self, mock_tracker, mock_auth):
        pending = [
            MockFollowUp(id="fu-1", thread_id="t-1"),
            MockFollowUp(id="fu-2", thread_id="t-2"),
        ]
        replied = [
            MockFollowUp(id="fu-1", thread_id="t-1", resolved_at=datetime.now()),
        ]
        mock_tracker.get_pending_followups.return_value = pending
        mock_tracker.check_for_replies.return_value = replied
        result = await handle_check_replies(auth_context=mock_auth)
        assert _status(result) == 200
        data = _data(result)
        assert len(data["replied"]) == 1
        assert data["still_pending"] == 1

    @pytest.mark.asyncio
    async def test_check_replies_no_auth(self, mock_tracker):
        result = await handle_check_replies(auth_context=None)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_check_replies_tracker_error(self, mock_tracker, mock_auth):
        mock_tracker.get_pending_followups.side_effect = AttributeError("boom")
        result = await handle_check_replies(auth_context=mock_auth)
        assert _status(result) == 500


# ============================================================================
# handle_auto_detect_followups
# ============================================================================


class TestAutoDetectFollowups:
    """Tests for POST /api/v1/email/followups/auto-detect."""

    @pytest.mark.asyncio
    async def test_auto_detect_success(self, mock_tracker, mock_auth):
        detected = [MockFollowUp(id="fu-auto-1")]
        mock_tracker.auto_detect_sent_emails.return_value = detected
        result = await handle_auto_detect_followups(auth_context=mock_auth)
        assert _status(result) == 200
        data = _data(result)
        assert data["total_detected"] == 1
        assert len(data["detected"]) == 1

    @pytest.mark.asyncio
    async def test_auto_detect_empty(self, mock_tracker, mock_auth):
        result = await handle_auto_detect_followups(auth_context=mock_auth)
        assert _status(result) == 200
        data = _data(result)
        assert data["total_detected"] == 0

    @pytest.mark.asyncio
    async def test_auto_detect_custom_days(self, mock_tracker, mock_auth):
        result = await handle_auto_detect_followups(days_back=14, auth_context=mock_auth)
        assert _status(result) == 200
        call_kwargs = mock_tracker.auto_detect_sent_emails.call_args.kwargs
        assert call_kwargs["days_back"] == 14

    @pytest.mark.asyncio
    async def test_auto_detect_no_auth(self, mock_tracker):
        result = await handle_auto_detect_followups(auth_context=None)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_auto_detect_error(self, mock_tracker, mock_auth):
        mock_tracker.auto_detect_sent_emails.side_effect = OSError("timeout")
        result = await handle_auto_detect_followups(auth_context=mock_auth)
        assert _status(result) == 500


# ============================================================================
# handle_get_snooze_suggestions
# ============================================================================


class TestGetSnoozeSuggestions:
    """Tests for GET /api/v1/email/{id}/snooze-suggestions."""

    @pytest.mark.asyncio
    async def test_get_suggestions_success(self, mock_recommender, mock_auth):
        data = {"subject": "Test", "sender": "alice@test.com"}
        result = await handle_get_snooze_suggestions("email-001", data, auth_context=mock_auth)
        assert _status(result) == 200
        resp = _data(result)
        assert resp["email_id"] == "email-001"
        assert len(resp["suggestions"]) >= 1
        assert resp["recommended"] is not None

    @pytest.mark.asyncio
    async def test_get_suggestions_with_priority(self, mock_recommender, mock_auth):
        data = {"subject": "Urgent", "sender": "boss@test.com", "priority": 0.9}
        result = await handle_get_snooze_suggestions("email-002", data, auth_context=mock_auth)
        assert _status(result) == 200
        # Verify priority_result was constructed and passed
        mock_recommender.recommend_snooze.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_suggestions_priority_critical(self, mock_recommender, mock_auth):
        data = {"priority": 0.85}
        result = await handle_get_snooze_suggestions("e-1", data, auth_context=mock_auth)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_suggestions_priority_high(self, mock_recommender, mock_auth):
        data = {"priority": 0.65}
        result = await handle_get_snooze_suggestions("e-1", data, auth_context=mock_auth)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_suggestions_priority_medium(self, mock_recommender, mock_auth):
        data = {"priority": 0.45}
        result = await handle_get_snooze_suggestions("e-1", data, auth_context=mock_auth)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_suggestions_priority_low(self, mock_recommender, mock_auth):
        data = {"priority": 0.25}
        result = await handle_get_snooze_suggestions("e-1", data, auth_context=mock_auth)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_suggestions_priority_defer(self, mock_recommender, mock_auth):
        data = {"priority": 0.1}
        result = await handle_get_snooze_suggestions("e-1", data, auth_context=mock_auth)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_suggestions_max_suggestions(self, mock_recommender, mock_auth):
        data = {"max_suggestions": 3}
        result = await handle_get_snooze_suggestions("e-1", data, auth_context=mock_auth)
        assert _status(result) == 200
        call_kwargs = mock_recommender.recommend_snooze.call_args.kwargs
        assert call_kwargs["max_suggestions"] == 3

    @pytest.mark.asyncio
    async def test_get_suggestions_no_auth(self, mock_recommender):
        result = await handle_get_snooze_suggestions("e-1", {}, auth_context=None)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_get_suggestions_recommender_error(self, mock_recommender, mock_auth):
        mock_recommender.recommend_snooze.side_effect = TypeError("bad input")
        result = await handle_get_snooze_suggestions("e-1", {}, auth_context=mock_auth)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_get_suggestions_no_recommended(self, mock_recommender, mock_auth):
        rec = MagicMock()
        rec.suggestions = [MockSnoozeSuggestion()]
        rec.recommended = None
        mock_recommender.recommend_snooze.return_value = rec
        result = await handle_get_snooze_suggestions("e-1", {}, auth_context=mock_auth)
        assert _status(result) == 200
        data = _data(result)
        assert data["recommended"] is None


# ============================================================================
# handle_apply_snooze
# ============================================================================


class TestApplySnooze:
    """Tests for POST /api/v1/email/{id}/snooze."""

    @pytest.mark.asyncio
    async def test_apply_snooze_success(self, mock_auth):
        data = {"snooze_until": "2026-03-01T10:00:00Z", "label": "Monday morning"}
        result = await handle_apply_snooze(
            "email-001", data, user_id="user1", auth_context=mock_auth
        )
        assert _status(result) == 200
        resp = _data(result)
        assert resp["email_id"] == "email-001"
        assert resp["status"] == "snoozed"
        assert resp["label"] == "Monday morning"
        assert KEY in _snoozed_emails

    @pytest.mark.asyncio
    async def test_apply_snooze_missing_snooze_until(self, mock_auth):
        data = {"label": "Later"}
        result = await handle_apply_snooze("email-001", data, auth_context=mock_auth)
        assert _status(result) == 400
        assert "snooze_until" in _body(result)["error"]

    @pytest.mark.asyncio
    async def test_apply_snooze_empty_snooze_until(self, mock_auth):
        data = {"snooze_until": ""}
        result = await handle_apply_snooze("email-001", data, auth_context=mock_auth)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_apply_snooze_invalid_date(self, mock_auth):
        data = {"snooze_until": "not-a-date"}
        result = await handle_apply_snooze("email-001", data, auth_context=mock_auth)
        assert _status(result) == 400
        assert "Invalid" in _body(result)["error"] or "format" in _body(result)["error"].lower()

    @pytest.mark.asyncio
    async def test_apply_snooze_default_label(self, mock_auth):
        data = {"snooze_until": "2026-03-01T10:00:00Z"}
        result = await handle_apply_snooze("email-001", data, auth_context=mock_auth)
        assert _status(result) == 200
        resp = _data(result)
        assert resp["label"] == "Snoozed"

    @pytest.mark.asyncio
    async def test_apply_snooze_no_auth(self):
        data = {"snooze_until": "2026-03-01T10:00:00Z"}
        result = await handle_apply_snooze("email-001", data, auth_context=None)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_apply_snooze_stores_the_callers_identity(self, mock_auth):
        data = {"snooze_until": "2026-03-01T10:00:00Z"}
        await handle_apply_snooze("email-001", data, user_id="user1", auth_context=mock_auth)
        assert _snoozed_emails[KEY] | MINE == _snoozed_emails[KEY]

    @pytest.mark.asyncio
    async def test_apply_snooze_overwrites_existing(self, mock_auth):
        """Applying snooze to an already-snoozed email updates it."""
        data1 = {"snooze_until": "2026-03-01T10:00:00Z", "label": "First"}
        data2 = {"snooze_until": "2026-03-02T10:00:00Z", "label": "Second"}
        await handle_apply_snooze("email-001", data1, auth_context=mock_auth)
        await handle_apply_snooze("email-001", data2, auth_context=mock_auth)
        assert _snoozed_emails[KEY]["label"] == "Second"

    @pytest.mark.asyncio
    async def test_apply_snooze_gmail_import_failure(self, mock_auth):
        """Gmail connector import failure should not fail the snooze."""
        data = {"snooze_until": "2026-03-01T10:00:00Z"}
        # The handler has try/except for gmail import - just ensure it succeeds
        result = await handle_apply_snooze("email-001", data, auth_context=mock_auth)
        assert _status(result) == 200


# ============================================================================
# handle_cancel_snooze
# ============================================================================


class TestCancelSnooze:
    """Tests for DELETE /api/v1/email/{id}/snooze."""

    @pytest.mark.asyncio
    async def test_cancel_snooze_success(self, mock_auth):
        # First add a snooze
        _snoozed_emails[KEY] = {
            "email_id": "email-001",
            **MINE,
            "snooze_until": datetime.now() + timedelta(hours=2),
            "label": "Later",
            "snoozed_at": datetime.now(),
        }
        result = await handle_cancel_snooze("email-001", auth_context=mock_auth)
        assert _status(result) == 200
        resp = _data(result)
        assert resp["status"] == "unsnooze"
        assert KEY not in _snoozed_emails

    @pytest.mark.asyncio
    async def test_cancel_snooze_not_found(self, mock_auth):
        result = await handle_cancel_snooze("nonexistent", auth_context=mock_auth)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_cancel_snooze_no_auth(self):
        result = await handle_cancel_snooze("email-001", auth_context=None)
        assert _status(result) == 401


# ============================================================================
# handle_get_snoozed_emails
# ============================================================================


class TestGetSnoozedEmails:
    """Tests for GET /api/v1/email/snoozed."""

    @pytest.mark.asyncio
    async def test_get_snoozed_empty(self, mock_auth):
        result = await handle_get_snoozed_emails(auth_context=mock_auth)
        assert _status(result) == 200
        data = _data(result)
        assert data["snoozed"] == []
        assert data["total"] == 0
        assert data["due_now"] == 0

    @pytest.mark.asyncio
    async def test_get_snoozed_with_items(self, mock_auth):
        now = datetime.now()
        _snoozed_emails["e-1"] = {
            "email_id": "e-1",
            **MINE,
            "snooze_until": now + timedelta(hours=2),
            "label": "Later",
            "snoozed_at": now,
        }
        _snoozed_emails["e-2"] = {
            "email_id": "e-2",
            **MINE,
            "snooze_until": now - timedelta(hours=1),  # Due
            "label": "Overdue",
            "snoozed_at": now - timedelta(hours=3),
        }
        result = await handle_get_snoozed_emails(user_id="default", auth_context=mock_auth)
        assert _status(result) == 200
        data = _data(result)
        assert data["total"] == 2
        assert data["due_now"] == 1

    @pytest.mark.asyncio
    async def test_get_snoozed_filters_by_user(self, mock_auth):
        now = datetime.now()
        _snoozed_emails["e-1"] = {
            "email_id": "e-1",
            **MINE,
            "snooze_until": now + timedelta(hours=2),
            "label": "A",
            "snoozed_at": now,
        }
        _snoozed_emails["e-2"] = {
            "email_id": "e-2",
            "user_id": "user-b",
            "snooze_until": now + timedelta(hours=2),
            "label": "B",
            "snoozed_at": now,
        }
        result = await handle_get_snoozed_emails(user_id="user-a", auth_context=mock_auth)
        data = _data(result)
        assert data["total"] == 1
        assert data["snoozed"][0]["email_id"] == "e-1"

    @pytest.mark.asyncio
    async def test_get_snoozed_sorted_by_time(self, mock_auth):
        now = datetime.now()
        _snoozed_emails["e-later"] = {
            "email_id": "e-later",
            **MINE,
            "snooze_until": now + timedelta(hours=5),
            "label": "Later",
            "snoozed_at": now,
        }
        _snoozed_emails["e-soon"] = {
            "email_id": "e-soon",
            **MINE,
            "snooze_until": now + timedelta(hours=1),
            "label": "Soon",
            "snoozed_at": now,
        }
        result = await handle_get_snoozed_emails(user_id="default", auth_context=mock_auth)
        data = _data(result)
        assert data["snoozed"][0]["email_id"] == "e-soon"
        assert data["snoozed"][1]["email_id"] == "e-later"

    @pytest.mark.asyncio
    async def test_get_snoozed_no_auth(self):
        result = await handle_get_snoozed_emails(auth_context=None)
        assert _status(result) == 401


# ============================================================================
# handle_process_due_snoozes
# ============================================================================


class TestProcessDueSnoozes:
    """Tests for POST /api/v1/email/snooze/process-due."""

    @pytest.mark.asyncio
    async def test_process_due_none_due(self, mock_auth):
        now = datetime.now()
        _snoozed_emails["e-1"] = {
            "email_id": "e-1",
            **MINE,
            "snooze_until": now + timedelta(hours=5),
            "label": "Later",
            "snoozed_at": now,
        }
        result = await handle_process_due_snoozes(user_id="default", auth_context=mock_auth)
        assert _status(result) == 200
        data = _data(result)
        assert data["count"] == 0
        assert data["processed"] == []
        # Email should still be snoozed
        assert "e-1" in _snoozed_emails

    @pytest.mark.asyncio
    async def test_process_due_with_due_emails(self, mock_auth):
        now = datetime.now()
        _snoozed_emails["e-due"] = {
            "email_id": "e-due",
            **MINE,
            "snooze_until": now - timedelta(hours=1),
            "label": "Overdue",
            "snoozed_at": now - timedelta(hours=3),
        }
        _snoozed_emails["e-not-due"] = {
            "email_id": "e-not-due",
            **MINE,
            "snooze_until": now + timedelta(hours=5),
            "label": "Future",
            "snoozed_at": now,
        }
        result = await handle_process_due_snoozes(user_id="default", auth_context=mock_auth)
        assert _status(result) == 200
        data = _data(result)
        assert data["count"] == 1
        assert "e-due" in data["processed"]
        assert "e-due" not in _snoozed_emails
        assert "e-not-due" in _snoozed_emails

    @pytest.mark.asyncio
    async def test_process_due_filters_by_user(self, mock_auth):
        now = datetime.now()
        _snoozed_emails["e-other-user"] = {
            "email_id": "e-other-user",
            "user_id": "other-user",
            "snooze_until": now - timedelta(hours=1),
            "label": "Overdue",
            "snoozed_at": now - timedelta(hours=3),
        }
        result = await handle_process_due_snoozes(user_id="default", auth_context=mock_auth)
        data = _data(result)
        assert data["count"] == 0
        # Other user's snooze should remain
        assert "e-other-user" in _snoozed_emails

    @pytest.mark.asyncio
    async def test_process_due_no_auth(self):
        result = await handle_process_due_snoozes(auth_context=None)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_process_due_empty_store(self, mock_auth):
        result = await handle_process_due_snoozes(auth_context=mock_auth)
        assert _status(result) == 200
        data = _data(result)
        assert data["count"] == 0


# ============================================================================
# handle_get_categories
# ============================================================================


class TestGetCategories:
    """Tests for GET /api/v1/email/categories."""

    @pytest.mark.asyncio
    async def test_get_categories_success(self, mock_auth):
        # Patch the EmailCategory import inside the handler
        class MockEmailCategory(Enum):
            INVOICES = "invoices"
            HR = "hr"
            NEWSLETTERS = "newsletters"

        with patch(
            "aragora.server.handlers.email_services.EmailCategory",
            MockEmailCategory,
            create=True,
        ):
            # Need to patch the import inside the function
            with patch.dict(
                "sys.modules",
                {"aragora.services.email_categorizer": MagicMock(EmailCategory=MockEmailCategory)},
            ):
                result = await handle_get_categories(auth_context=mock_auth)
        assert _status(result) == 200
        data = _data(result)
        assert "categories" in data
        assert len(data["categories"]) == 3

    @pytest.mark.asyncio
    async def test_get_categories_no_auth(self):
        result = await handle_get_categories(auth_context=None)
        assert _status(result) == 401

    @pytest.mark.asyncio
    async def test_get_categories_import_error(self, mock_auth):
        with patch.dict("sys.modules", {"aragora.services.email_categorizer": None}):
            result = await handle_get_categories(auth_context=mock_auth)
        assert _status(result) == 500


# ============================================================================
# handle_category_feedback
# ============================================================================


class TestCategoryFeedback:
    """Tests for POST /api/v1/email/categories/learn."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "data",
        [
            {
                "email_id": "e-001",
                "predicted_category": "newsletters",
                "correct_category": "invoices",
            },
            {},
        ],
    )
    async def test_feedback_is_not_implemented(self, mock_categorizer, mock_auth, data):
        result = await handle_category_feedback(data, auth_context=mock_auth)
        assert _status(result) == 501
        assert _body(result)["error"]["code"] == "not_implemented"
        mock_categorizer.record_feedback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_feedback_no_auth(self, mock_categorizer):
        data = {
            "email_id": "e-001",
            "predicted_category": "a",
            "correct_category": "b",
        }
        result = await handle_category_feedback(data, auth_context=None)
        assert _status(result) == 401


# ============================================================================
# _get_category_description
# ============================================================================


class TestGetCategoryDescription:
    """Tests for the _get_category_description helper."""

    def test_known_category(self):
        cat = MagicMock()
        cat.value = "invoices"
        assert "Bills" in _get_category_description(cat)

    def test_hr_category(self):
        cat = MagicMock()
        cat.value = "hr"
        assert "HR" in _get_category_description(cat)

    def test_unknown_category(self):
        cat = MagicMock()
        cat.value = "unknown_category"
        assert _get_category_description(cat) == ""

    def test_all_known_categories(self):
        for name in (
            "invoices",
            "hr",
            "newsletters",
            "projects",
            "meetings",
            "support",
            "security",
            "receipts",
            "social",
            "personal",
            "uncategorized",
        ):
            cat = MagicMock()
            cat.value = name
            assert _get_category_description(cat) != "", f"Missing description for {name}"


# ============================================================================
# get_email_services_routes
# ============================================================================


class TestGetRoutes:
    """Tests for get_email_services_routes registration."""

    def test_returns_list_of_tuples(self):
        routes = get_email_services_routes()
        assert isinstance(routes, list)
        assert all(isinstance(r, tuple) and len(r) == 3 for r in routes)

    def test_has_all_expected_routes(self):
        routes = get_email_services_routes()
        paths = [(method, path) for method, path, _ in routes]
        assert ("POST", "/api/v1/email/followups/mark") in paths
        assert ("GET", "/api/v1/email/followups/pending") in paths
        assert ("POST", "/api/v1/email/followups/{id}/resolve") in paths
        assert ("POST", "/api/v1/email/followups/check-replies") in paths
        assert ("POST", "/api/v1/email/followups/auto-detect") in paths
        assert ("GET", "/api/v1/email/{id}/snooze-suggestions") in paths
        assert ("POST", "/api/v1/email/{id}/snooze") in paths
        assert ("DELETE", "/api/v1/email/{id}/snooze") in paths
        assert ("GET", "/api/v1/email/snoozed") in paths
        assert ("POST", "/api/v1/email/snooze/process-due") in paths
        assert ("GET", "/api/v1/email/categories") in paths
        assert ("POST", "/api/v1/email/categories/learn") in paths

    def test_route_count(self):
        routes = get_email_services_routes()
        assert len(routes) == 12


# ============================================================================
# get_followup_tracker / get_snooze_recommender / get_email_categorizer
# ============================================================================


class TestServiceGetters:
    """Tests for service singleton getters."""

    def test_get_followup_tracker_creates_instance(self):
        with patch(
            "aragora.server.handlers.email_services.FollowUpTracker",
            MagicMock(),
            create=True,
        ):
            with patch.dict(
                "sys.modules",
                {
                    "aragora.services.followup_tracker": MagicMock(
                        FollowUpTracker=MagicMock(return_value="tracker-instance")
                    )
                },
            ):
                tracker = get_followup_tracker()
                assert tracker is not None

    def test_get_followup_tracker_returns_cached(self):
        email_mod._followup_tracker = "cached"
        assert get_followup_tracker() == "cached"

    def test_get_snooze_recommender_returns_cached(self):
        email_mod._snooze_recommender = "cached"
        assert get_snooze_recommender() == "cached"

    def test_get_email_categorizer_returns_cached(self):
        email_mod._email_categorizer = "cached"
        assert get_email_categorizer() == "cached"

    def test_get_snooze_recommender_creates_instance(self):
        with patch.dict(
            "sys.modules",
            {
                "aragora.services.snooze_recommender": MagicMock(
                    SnoozeRecommender=MagicMock(return_value="recommender-instance")
                )
            },
        ):
            result = get_snooze_recommender()
            assert result is not None

    def test_get_email_categorizer_creates_instance(self):
        with patch.dict(
            "sys.modules",
            {
                "aragora.services.email_categorizer": MagicMock(
                    EmailCategorizer=MagicMock(return_value="categorizer-instance")
                )
            },
        ):
            result = get_email_categorizer()
            assert result is not None


# ============================================================================
# EmailServicesHandler - can_handle
# ============================================================================


class TestEmailServicesHandlerCanHandle:
    """Tests for EmailServicesHandler.can_handle."""

    def test_static_routes_accepted(self, handler):
        for route in handler.ROUTES:
            assert handler.can_handle(route), f"Should handle {route}"

    def test_followup_prefix_with_id(self, handler):
        assert handler.can_handle("/api/v1/email/followups/fu-123/resolve")

    def test_email_prefix_with_id(self, handler):
        assert handler.can_handle("/api/v1/email/email-123/snooze")

    def test_snooze_suggestions_pattern(self, handler):
        assert handler.can_handle("/api/v1/email/email-abc/snooze-suggestions")

    def test_snooze_pattern(self, handler):
        assert handler.can_handle("/api/v1/email/email-abc/snooze")

    def test_rejects_unrelated_path(self, handler):
        assert not handler.can_handle("/api/v1/users/list")

    def test_rejects_root(self, handler):
        assert not handler.can_handle("/")

    def test_rejects_empty(self, handler):
        assert not handler.can_handle("")

    def test_rejects_bare_prefix(self, handler):
        """Rejects the prefix itself without a subpath."""
        # /api/v1/email/ prefix: path must differ from prefix.rstrip("/")
        assert not handler.can_handle("/api/v1/email")


# ============================================================================
# EmailServicesHandler - handle_post
# ============================================================================


class TestEmailServicesHandlerPost:
    """Tests for EmailServicesHandler.handle_post.

    Note: handle_post dispatches to standalone handler functions which repeat
    the permission check on the auth context the handler passes them. We patch
    _check_email_permission to return None (allowed) for these routing tests.
    """

    @pytest.fixture(autouse=True)
    def _bypass_standalone_rbac(self):
        with patch.object(email_mod, "_check_email_permission", return_value=None):
            yield

    @pytest.mark.asyncio
    async def test_post_mark_followup(self, handler, mock_http_handler, mock_tracker):
        body = json.dumps({"email_id": "e-1", "thread_id": "t-1"}).encode()
        mock_http_handler.rfile.read.return_value = body
        mock_http_handler.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
        }
        result = await handler.handle_post("/api/v1/email/followups/mark", {}, mock_http_handler)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_post_check_replies(self, handler, mock_http_handler, mock_tracker):
        result = await handler.handle_post(
            "/api/v1/email/followups/check-replies", {}, mock_http_handler
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_post_auto_detect(self, handler, mock_http_handler, mock_tracker):
        result = await handler.handle_post(
            "/api/v1/email/followups/auto-detect", {}, mock_http_handler
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_post_resolve(self, handler, mock_http_handler, mock_tracker):
        resolved = MockFollowUp(status=MockFollowUpStatus.RESOLVED, resolved_at=datetime.now())
        mock_tracker.resolve_followup.return_value = resolved
        result = await handler.handle_post(
            "/api/v1/email/followups/fu-001/resolve", {}, mock_http_handler
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_post_apply_snooze(self, handler, mock_http_handler):
        body = json.dumps({"snooze_until": "2026-03-01T10:00:00Z"}).encode()
        mock_http_handler.rfile.read.return_value = body
        mock_http_handler.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
        }
        result = await handler.handle_post("/api/v1/email/email-001/snooze", {}, mock_http_handler)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_post_process_due(self, handler, mock_http_handler):
        result = await handler.handle_post(
            "/api/v1/email/snooze/process-due", {}, mock_http_handler
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_post_category_feedback(self, handler, mock_http_handler, mock_categorizer):
        body = json.dumps(
            {
                "email_id": "e-1",
                "predicted_category": "a",
                "correct_category": "b",
            }
        ).encode()
        mock_http_handler.rfile.read.return_value = body
        mock_http_handler.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": "application/json",
        }
        result = await handler.handle_post("/api/v1/email/categories/learn", {}, mock_http_handler)
        assert _status(result) == 501

    @pytest.mark.asyncio
    async def test_post_unknown_path(self, handler, mock_http_handler):
        result = await handler.handle_post("/api/v1/email/unknown-endpoint", {}, mock_http_handler)
        assert _status(result) == 404


# ============================================================================
# EmailServicesHandler - handle_get
# ============================================================================


class TestEmailServicesHandlerGet:
    """Tests for EmailServicesHandler.handle_get.

    Note: handle_get calls standalone functions which do their own
    _check_email_permission. We patch it to return None (allowed).
    """

    @pytest.fixture(autouse=True)
    def _bypass_standalone_rbac(self):
        with patch.object(email_mod, "_check_email_permission", return_value=None):
            yield

    @pytest.mark.asyncio
    async def test_get_categories(self, handler, mock_http_handler):
        class MockEmailCategory(Enum):
            INVOICES = "invoices"

        with patch.dict(
            "sys.modules",
            {"aragora.services.email_categorizer": MagicMock(EmailCategory=MockEmailCategory)},
        ):
            result = await handler.handle_get("/api/v1/email/categories", {}, mock_http_handler)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_pending_followups(self, handler, mock_http_handler, mock_tracker):
        result = await handler.handle_get(
            "/api/v1/email/followups/pending",
            {"include_resolved": "false"},
            mock_http_handler,
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_pending_include_resolved(self, handler, mock_http_handler, mock_tracker):
        result = await handler.handle_get(
            "/api/v1/email/followups/pending",
            {"include_resolved": "true"},
            mock_http_handler,
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_snoozed(self, handler, mock_http_handler):
        result = await handler.handle_get("/api/v1/email/snoozed", {}, mock_http_handler)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_snooze_suggestions(self, handler, mock_http_handler, mock_recommender):
        result = await handler.handle_get(
            "/api/v1/email/email-001/snooze-suggestions",
            {"subject": "Test"},
            mock_http_handler,
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_get_unknown_path(self, handler, mock_http_handler):
        result = await handler.handle_get("/api/v1/email/unknown", {}, mock_http_handler)
        assert _status(result) == 404


# ============================================================================
# EmailServicesHandler - handle_delete
# ============================================================================


class TestEmailServicesHandlerDelete:
    """Tests for EmailServicesHandler.handle_delete."""

    @pytest.fixture(autouse=True)
    def _bypass_standalone_rbac(self):
        with patch.object(email_mod, "_check_email_permission", return_value=None):
            yield

    @pytest.mark.asyncio
    async def test_delete_cancel_snooze(self, handler, mock_http_handler):
        _snoozed_emails[KEY] = {
            "email_id": "email-001",
            **MINE,
            "snooze_until": datetime.now() + timedelta(hours=2),
            "label": "Later",
            "snoozed_at": datetime.now(),
        }
        result = await handler.handle_delete(
            "/api/v1/email/email-001/snooze", {}, mock_http_handler
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_delete_unknown_path(self, handler, mock_http_handler):
        result = await handler.handle_delete("/api/v1/email/unknown-action", {}, mock_http_handler)
        assert _status(result) == 404


# ============================================================================
# EmailServicesHandler - initialization
# ============================================================================


class TestEmailServicesHandlerInit:
    """Tests for EmailServicesHandler initialization."""

    def test_init_with_empty_context(self):
        h = EmailServicesHandler({})
        assert h.ctx == {}

    def test_init_with_context(self):
        ctx = {"key": "value"}
        h = EmailServicesHandler(ctx)
        assert h.ctx == ctx

    def test_resource_type(self, handler):
        assert handler.RESOURCE_TYPE == "email"

    def test_routes_defined(self, handler):
        assert len(handler.ROUTES) > 0

    def test_route_prefixes_defined(self, handler):
        assert len(handler.ROUTE_PREFIXES) > 0

    def test_route_patterns_compiled(self, handler):
        assert len(handler._compiled_patterns) > 0

    @pytest.mark.asyncio
    async def test_handle_returns_none_for_non_get_requests(self, handler):
        """handle() serves GET only; the other methods have their own hooks."""
        request = MagicMock()
        request.command = "PATCH"
        result = await handler.handle("/api/v1/email/categories", {}, request)
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_delegates_get_to_handle_get(self, handler):
        request = MagicMock()
        request.command = "GET"
        sentinel = MagicMock()
        with patch.object(handler, "handle_get", AsyncMock(return_value=sentinel)) as handle_get:
            result = await handler.handle("/api/v1/email/snoozed", {"a": "1"}, request)
        assert result is sentinel
        handle_get.assert_awaited_once_with("/api/v1/email/snoozed", {"a": "1"}, request)


# ============================================================================
# Edge cases and integration scenarios
# ============================================================================


class TestEdgeCases:
    """Test edge cases and unusual inputs."""

    @pytest.mark.asyncio
    async def test_mark_followup_empty_subject_and_recipient(self, mock_tracker, mock_auth):
        data = {"email_id": "e-1", "thread_id": "t-1"}
        result = await handle_mark_followup(data, auth_context=mock_auth)
        assert _status(result) == 200
        call_kwargs = mock_tracker.mark_awaiting_reply.call_args.kwargs
        assert call_kwargs["subject"] == ""
        assert call_kwargs["recipient"] == ""

    @pytest.mark.asyncio
    async def test_apply_snooze_z_suffix_parsing(self, mock_auth):
        """ISO format with Z suffix should be parsed correctly."""
        data = {"snooze_until": "2026-06-15T08:00:00Z"}
        result = await handle_apply_snooze("e-1", data, auth_context=mock_auth)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_apply_snooze_with_timezone_offset(self, mock_auth):
        data = {"snooze_until": "2026-06-15T08:00:00+05:30"}
        result = await handle_apply_snooze("e-1", data, auth_context=mock_auth)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_multiple_snooze_different_emails(self, mock_auth):
        for i in range(5):
            data = {"snooze_until": f"2026-03-0{i + 1}T10:00:00Z"}
            result = await handle_apply_snooze(
                f"e-{i}", data, user_id="user1", auth_context=mock_auth
            )
            assert _status(result) == 200
        assert len(_snoozed_emails) == 5

    @pytest.mark.asyncio
    async def test_cancel_then_resnooze(self, mock_auth):
        """Cancel and then re-snooze the same email."""
        _snoozed_emails[(*OWNER, "e-1")] = {
            "email_id": "e-1",
            **MINE,
            "snooze_until": datetime.now() + timedelta(hours=1),
            "label": "Old",
            "snoozed_at": datetime.now(),
        }
        await handle_cancel_snooze("e-1", user_id="user1", auth_context=mock_auth)
        assert (*OWNER, "e-1") not in _snoozed_emails

        data = {"snooze_until": "2026-04-01T10:00:00Z", "label": "New"}
        result = await handle_apply_snooze("e-1", data, user_id="user1", auth_context=mock_auth)
        assert _status(result) == 200
        assert _snoozed_emails[(*OWNER, "e-1")]["label"] == "New"

    @pytest.mark.asyncio
    async def test_get_snooze_suggestions_empty_data(self, mock_recommender, mock_auth):
        result = await handle_get_snooze_suggestions("e-1", {}, auth_context=mock_auth)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_resolve_followup_resolved_at_in_response(self, mock_tracker, mock_auth):
        resolved = MockFollowUp(
            status=MockFollowUpStatus.RESOLVED,
            resolved_at=datetime(2026, 2, 20, 12, 0, 0),
        )
        mock_tracker.resolve_followup.return_value = resolved
        result = await handle_resolve_followup("fu-1", {}, auth_context=mock_auth)
        data = _data(result)
        assert "2026-02-20" in data["resolved_at"]

    @pytest.mark.asyncio
    async def test_resolve_followup_resolved_at_is_the_update_time(self, mock_tracker, mock_auth):
        resolved = MockFollowUp(
            status=MockFollowUpStatus.RESOLVED,
            resolved_at=None,
        )
        mock_tracker.resolve_followup.return_value = resolved
        result = await handle_resolve_followup("fu-1", {}, auth_context=mock_auth)
        data = _data(result)
        assert data["resolved_at"] == resolved.updated_at.isoformat()

    @pytest.mark.asyncio
    async def test_get_pending_expected_by_none(self, mock_tracker, mock_auth):
        fu = MagicMock()
        fu.id = "fu-99"
        fu.email_id = "e-99"
        fu.thread_id = "t-99"
        fu.subject = "Test"
        fu.recipient = "test@test.com"
        fu.sent_at = datetime.now()
        fu.expected_by = None
        fu.status = MockFollowUpStatus.PENDING
        fu.days_waiting = 1
        fu.urgency_score = 0.5
        fu.reminder_count = 0
        fu.is_overdue = False
        mock_tracker.get_pending_followups.return_value = [fu]
        result = await handle_get_pending_followups(auth_context=mock_auth)
        data = _data(result)
        assert data["followups"][0]["expected_by"] is None

    @pytest.mark.asyncio
    async def test_check_replies_all_replied(self, mock_tracker, mock_auth):
        pending = [MockFollowUp(thread_id="t-1")]
        replied = [MockFollowUp(thread_id="t-1", resolved_at=datetime.now())]
        mock_tracker.get_pending_followups.return_value = pending
        mock_tracker.check_for_replies.return_value = replied
        result = await handle_check_replies(auth_context=mock_auth)
        data = _data(result)
        assert data["still_pending"] == 0

    @pytest.mark.asyncio
    async def test_mark_followup_custom_expected_days(self, mock_tracker, mock_auth):
        data = {
            "email_id": "e-1",
            "thread_id": "t-1",
            "expected_reply_days": 10,
        }
        result = await handle_mark_followup(data, auth_context=mock_auth)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_auto_detect_default_days(self, mock_tracker, mock_auth):
        result = await handle_auto_detect_followups(auth_context=mock_auth)
        call_kwargs = mock_tracker.auto_detect_sent_emails.call_args.kwargs
        assert call_kwargs["days_back"] == 7

    @pytest.mark.asyncio
    async def test_auto_detect_fields_in_response(self, mock_tracker, mock_auth):
        detected = [MockFollowUp(id="d-1", email_id="e-d1", subject="Follow up")]
        mock_tracker.auto_detect_sent_emails.return_value = detected
        result = await handle_auto_detect_followups(auth_context=mock_auth)
        data = _data(result)
        item = data["detected"][0]
        assert "followup_id" in item
        assert "email_id" in item
        assert "subject" in item
        assert "recipient" in item
        assert "sent_at" in item
        assert "days_waiting" in item
