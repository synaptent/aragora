"""
HTTP API Handlers for Email Services.

Provides REST APIs for advanced email management services:
- Follow-up tracking (mark, list, resolve, check replies)
- Snooze recommendations (suggest, apply, cancel)
- Email categorization management

Endpoints:
- POST /api/v1/email/followups/mark - Mark email as awaiting reply
- GET /api/v1/email/followups/pending - List pending follow-ups
- POST /api/v1/email/followups/{id}/resolve - Resolve a follow-up
- POST /api/v1/email/followups/check-replies - Check for replies
- GET /api/v1/email/{id}/snooze-suggestions - Get snooze recommendations
- POST /api/v1/email/{id}/snooze - Apply snooze to email
- DELETE /api/v1/email/{id}/snooze - Cancel snooze
- GET /api/v1/email/snoozed - List snoozed emails
- GET /api/v1/email/categories - List available categories
- POST /api/v1/email/categories/learn - Submit category feedback
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

from aragora.server.handlers.base import (
    error_response,
    success_response,
    handle_errors,
)
from aragora.server.handlers.secure import SecureHandler, UnauthorizedError, ForbiddenError
from aragora.server.handlers.utils.responses import HandlerResult

logger = logging.getLogger(__name__)

# RBAC imports (optional - graceful degradation if not available)
try:
    from aragora.rbac import check_permission

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed


def _check_email_permission(auth_context: Any | None, permission_key: str) -> HandlerResult | None:
    """Check RBAC permission, return error response if denied.

    SECURITY: All email operations require authentication. Both read and write
    operations must have a valid auth_context to prevent unauthorized access.
    """
    write_permissions = {"email:create", "email:update", "email:delete"}
    # SECURITY: Require authentication for ALL email operations (read and write)
    if auth_context is None:
        return error_response("Authentication required", status=401)

    if not RBAC_AVAILABLE:
        if rbac_fail_closed():
            return error_response(
                "Service unavailable: access control module not loaded", status=503
            )
        # Dev/test: fail closed for write operations only
        if permission_key in write_permissions:
            return error_response("RBAC unavailable", status=503)
        logger.warning("RBAC unavailable for permission check: %s", permission_key)
        return None

    try:
        decision = check_permission(auth_context, permission_key)
        if not decision.allowed:
            logger.warning("RBAC denied: permission=%s reason=%s", permission_key, decision.reason)
            return error_response("Permission denied", status=403)
    except (TypeError, ValueError, AttributeError, RuntimeError) as e:
        logger.warning("RBAC check failed: %s", e)
        # Fail closed - deny access if RBAC check fails
        return error_response("Authorization check failed", status=503)

    return None


# Thread-safe service instances
_followup_tracker: Any | None = None
_followup_tracker_lock = threading.Lock()
_snooze_recommender: Any | None = None
_snooze_recommender_lock = threading.Lock()
_email_categorizer: Any | None = None
_email_categorizer_lock = threading.Lock()

# In-memory snooze storage (replace with DB in production)
_snoozed_emails: dict[str, dict[str, Any]] = {}
_snoozed_emails_lock = threading.Lock()


def get_followup_tracker():
    """Get or create follow-up tracker (thread-safe)."""
    global _followup_tracker
    if _followup_tracker is not None:
        return _followup_tracker

    with _followup_tracker_lock:
        if _followup_tracker is None:
            from aragora.services.followup_tracker import FollowUpTracker

            _followup_tracker = FollowUpTracker()
        return _followup_tracker


def get_snooze_recommender():
    """Get or create snooze recommender (thread-safe)."""
    global _snooze_recommender
    if _snooze_recommender is not None:
        return _snooze_recommender

    with _snooze_recommender_lock:
        if _snooze_recommender is None:
            from aragora.services.snooze_recommender import SnoozeRecommender

            _snooze_recommender = SnoozeRecommender()
        return _snooze_recommender


def get_email_categorizer():
    """Get or create email categorizer (thread-safe)."""
    global _email_categorizer
    if _email_categorizer is not None:
        return _email_categorizer

    with _email_categorizer_lock:
        if _email_categorizer is None:
            from aragora.services.email_categorizer import EmailCategorizer

            _email_categorizer = EmailCategorizer()
        return _email_categorizer


# =============================================================================
# Follow-Up Tracking Handlers
# =============================================================================


async def handle_mark_followup(
    data: dict[str, Any],
    user_id: str = "default",
    auth_context: Any | None = None,
) -> HandlerResult:
    """
    Mark an email as awaiting reply.

    POST /api/v1/email/followups/mark
    Body: {
        email_id: str,
        thread_id: str,
        subject: str,
        recipient: str,
        sent_at: str (ISO format),
        expected_reply_days: int (optional, default 3)
    }
    """
    # Check RBAC permission
    perm_error = _check_email_permission(auth_context, "email:create")
    if perm_error:
        return perm_error

    try:
        tracker = get_followup_tracker()

        email_id = data.get("email_id")
        thread_id = data.get("thread_id")
        subject = data.get("subject", "")
        recipient = data.get("recipient", "")
        sent_at_str = data.get("sent_at")
        expected_days = data.get("expected_reply_days", 3)

        if not email_id or not thread_id:
            return error_response("email_id and thread_id are required", status=400)

        # Parse sent_at
        sent_at = datetime.now()
        if sent_at_str:
            try:
                sent_at = datetime.fromisoformat(sent_at_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        expected_by = sent_at + timedelta(days=expected_days)

        followup = await tracker.mark_awaiting_reply(
            email_id=email_id,
            thread_id=thread_id,
            subject=subject,
            recipient=recipient,
            sent_at=sent_at,
            expected_by=expected_by,
            user_id=user_id,
        )

        return success_response(
            {
                "followup_id": followup.id,
                "email_id": followup.email_id,
                "thread_id": followup.thread_id,
                "subject": followup.subject,
                "recipient": followup.recipient,
                "sent_at": followup.sent_at.isoformat(),
                "expected_by": followup.expected_by.isoformat() if followup.expected_by else None,
                "status": followup.status.value,
                "days_waiting": followup.days_waiting,
            }
        )

    except (TypeError, ValueError, KeyError, AttributeError, OSError):
        logger.exception("Error marking follow-up")
        return error_response("Follow-up marking failed", status=500)


async def handle_get_pending_followups(
    user_id: str = "default",
    include_resolved: bool = False,
    sort_by: str = "urgency",
    auth_context: Any | None = None,
) -> HandlerResult:
    """
    Get list of pending follow-ups.

    GET /api/v1/email/followups/pending
    Query params:
        include_resolved: bool (default false)
        sort_by: str (urgency, date, recipient)
    """
    # Check RBAC permission
    perm_error = _check_email_permission(auth_context, "email:read")
    if perm_error:
        return perm_error

    try:
        tracker = get_followup_tracker()

        followups = await tracker.get_pending_followups(
            user_id=user_id,
            include_resolved=include_resolved,
            sort_by=sort_by,
        )

        return success_response(
            {
                "followups": [
                    {
                        "followup_id": f.id,
                        "email_id": f.email_id,
                        "thread_id": f.thread_id,
                        "subject": f.subject,
                        "recipient": f.recipient,
                        "sent_at": f.sent_at.isoformat(),
                        "expected_by": f.expected_by.isoformat() if f.expected_by else None,
                        "status": f.status.value,
                        "days_waiting": f.days_waiting,
                        "urgency_score": f.urgency_score,
                        "reminder_count": f.reminder_count,
                    }
                    for f in followups
                ],
                "total": len(followups),
                "overdue_count": sum(1 for f in followups if f.is_overdue),
            }
        )

    except (TypeError, ValueError, KeyError, AttributeError, OSError):
        logger.exception("Error getting pending follow-ups")
        return error_response("Failed to retrieve follow-ups", status=500)


async def handle_resolve_followup(
    followup_id: str,
    data: dict[str, Any],
    user_id: str = "default",
    auth_context: Any | None = None,
) -> HandlerResult:
    """
    Resolve a follow-up.

    POST /api/v1/email/followups/{id}/resolve
    Body: {
        status: str (replied, no_longer_needed, manually_resolved),
        notes: str (optional)
    }
    """
    # Check RBAC permission
    perm_error = _check_email_permission(auth_context, "email:update")
    if perm_error:
        return perm_error

    try:
        tracker = get_followup_tracker()

        status = data.get("status", "manually_resolved")
        notes = data.get("notes", "")

        followup = await tracker.resolve_followup(
            followup_id=followup_id,
            status=status,
            notes=notes,
        )

        if not followup:
            return error_response("Follow-up not found", status=404)

        return success_response(
            {
                "followup_id": followup.id,
                "status": followup.status.value,
                "resolved_at": followup.resolved_at.isoformat() if followup.resolved_at else None,
                "notes": notes,
            }
        )

    except (TypeError, ValueError, KeyError, AttributeError, OSError):
        logger.exception("Error resolving follow-up")
        return error_response("Follow-up resolution failed", status=500)


async def handle_check_replies(
    user_id: str = "default",
    auth_context: Any | None = None,
) -> HandlerResult:
    """
    Check for replies to pending follow-ups.

    POST /api/v1/email/followups/check-replies
    """
    # Check RBAC permission
    perm_error = _check_email_permission(auth_context, "email:read")
    if perm_error:
        return perm_error

    try:
        tracker = get_followup_tracker()

        # Get pending follow-ups
        pending = await tracker.get_pending_followups(user_id=user_id)
        thread_ids = [f.thread_id for f in pending]

        if not thread_ids:
            return success_response({"replied": [], "still_pending": 0})

        # Check for replies
        replied = await tracker.check_for_replies(thread_ids)

        return success_response(
            {
                "replied": [
                    {
                        "followup_id": f.id,
                        "email_id": f.email_id,
                        "subject": f.subject,
                        "recipient": f.recipient,
                        "replied_at": f.resolved_at.isoformat() if f.resolved_at else None,
                    }
                    for f in replied
                ],
                "still_pending": len(pending) - len(replied),
            }
        )

    except (TypeError, ValueError, KeyError, AttributeError, OSError):
        logger.exception("Error checking replies")
        return error_response("Reply check failed", status=500)


async def handle_auto_detect_followups(
    user_id: str = "default",
    days_back: int = 7,
    auth_context: Any | None = None,
) -> HandlerResult:
    """
    Auto-detect sent emails that might need follow-up tracking.

    POST /api/v1/email/followups/auto-detect
    Body: { days_back: int (default 7) }
    """
    # Check RBAC permission
    perm_error = _check_email_permission(auth_context, "email:create")
    if perm_error:
        return perm_error

    try:
        tracker = get_followup_tracker()

        detected = await tracker.auto_detect_sent_emails(
            days_back=days_back,
            user_id=user_id,
        )

        return success_response(
            {
                "detected": [
                    {
                        "followup_id": f.id,
                        "email_id": f.email_id,
                        "subject": f.subject,
                        "recipient": f.recipient,
                        "sent_at": f.sent_at.isoformat(),
                        "days_waiting": f.days_waiting,
                    }
                    for f in detected
                ],
                "total_detected": len(detected),
            }
        )

    except (TypeError, ValueError, KeyError, AttributeError, OSError):
        logger.exception("Error auto-detecting follow-ups")
        return error_response("Auto-detection failed", status=500)


# =============================================================================
# Snooze Recommendation Handlers
# =============================================================================


async def handle_get_snooze_suggestions(
    email_id: str,
    data: dict[str, Any],
    user_id: str = "default",
    auth_context: Any | None = None,
) -> HandlerResult:
    """
    Get snooze time recommendations for an email.

    GET /api/v1/email/{id}/snooze-suggestions
    Query/Body: {
        subject: str,
        sender: str,
        priority: float (optional),
        max_suggestions: int (default 5)
    }
    """
    # Check RBAC permission
    perm_error = _check_email_permission(auth_context, "email:read")
    if perm_error:
        return perm_error

    try:
        recommender = get_snooze_recommender()

        # Build email dict
        email = {
            "id": email_id,
            "subject": data.get("subject", ""),
            "sender": data.get("sender", ""),
            "received_at": data.get("received_at", datetime.now().isoformat()),
        }

        # Build priority result if provided
        priority_result = None
        if data.get("priority") is not None:
            from aragora.services.email_prioritization import (
                EmailPriority,
                EmailPriorityResult,
                ScoringTier,
            )

            # Map priority score to EmailPriority enum
            priority_score = data.get("priority", 0.5)
            if priority_score >= 0.8:
                priority_enum = EmailPriority.CRITICAL
            elif priority_score >= 0.6:
                priority_enum = EmailPriority.HIGH
            elif priority_score >= 0.4:
                priority_enum = EmailPriority.MEDIUM
            elif priority_score >= 0.2:
                priority_enum = EmailPriority.LOW
            else:
                priority_enum = EmailPriority.DEFER

            priority_result = EmailPriorityResult(
                email_id=email_id,
                priority=priority_enum,
                confidence=priority_score,
                tier_used=ScoringTier.TIER_1_RULES,
                rationale="User-provided priority",
            )

        max_suggestions = data.get("max_suggestions", 5)

        recommendation = await recommender.recommend_snooze(
            email=email,
            priority_result=priority_result,
            max_suggestions=max_suggestions,
        )

        return success_response(
            {
                "email_id": email_id,
                "suggestions": [
                    {
                        "snooze_until": s.snooze_until.isoformat(),
                        "label": s.label,
                        "reason": s.reason,
                        "confidence": s.confidence,
                        "source": s.source,
                    }
                    for s in recommendation.suggestions
                ],
                "recommended": (
                    {
                        "snooze_until": recommendation.recommended.snooze_until.isoformat(),
                        "label": recommendation.recommended.label,
                        "reason": recommendation.recommended.reason,
                    }
                    if recommendation.recommended
                    else None
                ),
            }
        )

    except (TypeError, ValueError, KeyError, AttributeError, OSError):
        logger.exception("Error getting snooze suggestions")
        return error_response("Failed to retrieve suggestions", status=500)


async def handle_apply_snooze(
    email_id: str,
    data: dict[str, Any],
    user_id: str = "default",
    auth_context: Any | None = None,
) -> HandlerResult:
    """
    Apply snooze to an email.

    POST /api/v1/email/{id}/snooze
    Body: {
        snooze_until: str (ISO format),
        label: str (optional)
    }
    """
    # Check RBAC permission
    perm_error = _check_email_permission(auth_context, "email:update")
    if perm_error:
        return perm_error

    try:
        snooze_until_str = data.get("snooze_until")
        if not snooze_until_str:
            return error_response("snooze_until is required", status=400)

        try:
            snooze_until = datetime.fromisoformat(snooze_until_str.replace("Z", "+00:00"))
        except ValueError:
            return error_response("Invalid snooze_until format", status=400)

        label = data.get("label", "Snoozed")

        # Store snooze (in production, use Gmail API or database)
        with _snoozed_emails_lock:
            _snoozed_emails[email_id] = {
                "email_id": email_id,
                "user_id": user_id,
                "snooze_until": snooze_until,
                "label": label,
                "snoozed_at": datetime.now(),
            }

        # Try to apply Gmail label if available
        try:
            from aragora.connectors.enterprise.communication.gmail import GmailConnector

            gmail = GmailConnector()
            if hasattr(gmail, "is_connected") and gmail.is_connected:
                if hasattr(gmail, "add_label"):
                    await gmail.add_label(email_id, f"Snoozed/{label}")
                if hasattr(gmail, "archive_message"):
                    await gmail.archive_message(email_id)
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            AttributeError,
            ValueError,
            KeyError,  # Malformed OAuth response
        ) as gmail_error:
            logger.warning("Could not apply Gmail snooze: %s", gmail_error)

        return success_response(
            {
                "email_id": email_id,
                "snooze_until": snooze_until.isoformat(),
                "label": label,
                "status": "snoozed",
            }
        )

    except (TypeError, ValueError, KeyError, AttributeError, OSError):
        logger.exception("Error applying snooze")
        return error_response("Snooze application failed", status=500)


async def handle_cancel_snooze(
    email_id: str,
    user_id: str = "default",
    auth_context: Any | None = None,
) -> HandlerResult:
    """
    Cancel snooze on an email.

    DELETE /api/v1/email/{id}/snooze
    """
    # Check RBAC permission
    perm_error = _check_email_permission(auth_context, "email:delete")
    if perm_error:
        return perm_error

    try:
        with _snoozed_emails_lock:
            if email_id not in _snoozed_emails:
                return error_response("Email not snoozed", status=404)

            del _snoozed_emails[email_id]

        # Try to remove Gmail snooze label
        try:
            from aragora.connectors.enterprise.communication.gmail import GmailConnector

            gmail = GmailConnector()
            if hasattr(gmail, "is_connected") and gmail.is_connected:
                if hasattr(gmail, "remove_label"):
                    await gmail.remove_label(email_id, "Snoozed")
                if hasattr(gmail, "unarchive_message"):
                    await gmail.unarchive_message(email_id)
        except (
            ImportError,
            ConnectionError,
            TimeoutError,
            OSError,
            AttributeError,
            ValueError,
        ) as gmail_error:
            logger.warning("Could not remove Gmail snooze: %s", gmail_error)

        return success_response(
            {
                "email_id": email_id,
                "status": "unsnooze",
            }
        )

    except (TypeError, ValueError, KeyError, AttributeError, OSError):
        logger.exception("Error canceling snooze")
        return error_response("Snooze cancellation failed", status=500)


async def handle_get_snoozed_emails(
    user_id: str = "default",
    auth_context: Any | None = None,
) -> HandlerResult:
    """
    Get list of snoozed emails.

    GET /api/v1/email/snoozed
    """
    # Check RBAC permission
    perm_error = _check_email_permission(auth_context, "email:read")
    if perm_error:
        return perm_error

    try:
        now = datetime.now()

        with _snoozed_emails_lock:
            snoozed = [
                {
                    "email_id": s["email_id"],
                    "snooze_until": s["snooze_until"].isoformat(),
                    "label": s["label"],
                    "snoozed_at": s["snoozed_at"].isoformat(),
                    "is_due": s["snooze_until"] <= now,
                }
                for s in _snoozed_emails.values()
                if s.get("user_id") == user_id
            ]

        # Sort by snooze_until
        snoozed.sort(key=lambda x: x["snooze_until"])

        return success_response(
            {
                "snoozed": snoozed,
                "total": len(snoozed),
                "due_now": sum(1 for s in snoozed if s["is_due"]),
            }
        )

    except (TypeError, ValueError, KeyError, AttributeError):
        logger.exception("Error getting snoozed emails")
        return error_response("Failed to retrieve snoozed items", status=500)


async def handle_process_due_snoozes(
    user_id: str = "default",
    auth_context: Any | None = None,
) -> HandlerResult:
    """
    Process snoozed emails that are now due (bring back to inbox).

    POST /api/v1/email/snooze/process-due
    """
    # Check RBAC permission
    perm_error = _check_email_permission(auth_context, "email:update")
    if perm_error:
        return perm_error

    try:
        now = datetime.now()
        processed = []

        with _snoozed_emails_lock:
            due_emails = [
                (eid, s)
                for eid, s in _snoozed_emails.items()
                if s.get("user_id") == user_id and s["snooze_until"] <= now
            ]

            for email_id, snooze_data in due_emails:
                del _snoozed_emails[email_id]
                processed.append(email_id)

        # Try to unarchive in Gmail
        for email_id in processed:
            try:
                from aragora.connectors.enterprise.communication.gmail import GmailConnector

                gmail = GmailConnector()
                if hasattr(gmail, "is_connected") and gmail.is_connected:
                    if hasattr(gmail, "unarchive_message"):
                        await gmail.unarchive_message(email_id)
                    if hasattr(gmail, "remove_label"):
                        await gmail.remove_label(email_id, "Snoozed")
            except (
                ImportError,
                ConnectionError,
                TimeoutError,
                OSError,
                AttributeError,
                ValueError,
            ) as gmail_error:
                logger.warning("Could not unsnooze %s in Gmail: %s", email_id, gmail_error)

        return success_response(
            {
                "processed": processed,
                "count": len(processed),
            }
        )

    except (TypeError, ValueError, KeyError, AttributeError, OSError):
        logger.exception("Error processing due snoozes")
        return error_response("Snooze processing failed", status=500)


# =============================================================================
# Category Management Handlers
# =============================================================================


async def handle_get_categories(
    user_id: str = "default",
    auth_context: Any | None = None,
) -> HandlerResult:
    """
    Get available email categories.

    GET /api/v1/email/categories
    """
    # Check RBAC permission
    perm_error = _check_email_permission(auth_context, "email:read")
    if perm_error:
        return perm_error

    try:
        from aragora.services.email_categorizer import EmailCategory

        categories = [
            {
                "id": cat.value,
                "name": cat.value.replace("_", " ").title(),
                "description": _get_category_description(cat),
            }
            for cat in EmailCategory
        ]

        return success_response({"categories": categories})

    except (ImportError, TypeError, ValueError, AttributeError):
        logger.exception("Error getting categories")
        return error_response("Failed to retrieve categories", status=500)


async def handle_category_feedback(
    data: dict[str, Any],
    user_id: str = "default",
    auth_context: Any | None = None,
) -> HandlerResult:
    """
    Submit feedback on email categorization to improve learning.

    POST /api/v1/email/categories/learn
    Body: {
        email_id: str,
        predicted_category: str,
        correct_category: str,
        email_metadata: dict (optional)
    }
    """
    # Check RBAC permission
    perm_error = _check_email_permission(auth_context, "email:update")
    if perm_error:
        return perm_error

    try:
        categorizer = get_email_categorizer()

        email_id = data.get("email_id")
        predicted = data.get("predicted_category")
        correct = data.get("correct_category")

        if not email_id or not predicted or not correct:
            return error_response(
                "email_id, predicted_category, and correct_category are required",
                status=400,
            )

        # Record feedback for learning
        await categorizer.record_feedback(
            email_id=email_id,
            predicted_category=predicted,
            correct_category=correct,
            user_id=user_id,
        )

        return success_response(
            {
                "email_id": email_id,
                "feedback_recorded": True,
                "predicted": predicted,
                "correct": correct,
            }
        )

    except (TypeError, ValueError, KeyError, AttributeError, OSError):
        logger.exception("Error recording category feedback")
        return error_response("Feedback recording failed", status=500)


def _get_category_description(category) -> str:
    """Get description for a category."""
    descriptions = {
        "invoices": "Bills, payments, financial documents",
        "hr": "HR communications, benefits, payroll",
        "newsletters": "Subscriptions, marketing emails",
        "projects": "Project updates, task discussions",
        "meetings": "Calendar invites, meeting notes",
        "support": "Customer support, tickets",
        "security": "Security alerts, password resets",
        "receipts": "Order confirmations, shipping updates",
        "social": "Social media notifications",
        "personal": "Personal messages",
        "uncategorized": "Emails that don't fit other categories",
    }
    return descriptions.get(category.value, "")


# =============================================================================
# Handler Registration
# =============================================================================


def get_email_services_routes() -> list[tuple[str, str, Any]]:
    """
    Get route definitions for email services handlers.

    Returns list of (method, path, handler) tuples.
    """
    return [
        # Follow-up tracking
        ("POST", "/api/v1/email/followups/mark", handle_mark_followup),
        ("GET", "/api/v1/email/followups/pending", handle_get_pending_followups),
        ("POST", "/api/v1/email/followups/{id}/resolve", handle_resolve_followup),
        ("POST", "/api/v1/email/followups/check-replies", handle_check_replies),
        ("POST", "/api/v1/email/followups/auto-detect", handle_auto_detect_followups),
        # Snooze
        ("GET", "/api/v1/email/{id}/snooze-suggestions", handle_get_snooze_suggestions),
        ("POST", "/api/v1/email/{id}/snooze", handle_apply_snooze),
        ("DELETE", "/api/v1/email/{id}/snooze", handle_cancel_snooze),
        ("GET", "/api/v1/email/snoozed", handle_get_snoozed_emails),
        ("POST", "/api/v1/email/snooze/process-due", handle_process_due_snoozes),
        # Categories
        ("GET", "/api/v1/email/categories", handle_get_categories),
        ("POST", "/api/v1/email/categories/learn", handle_category_feedback),
    ]


class EmailServicesHandler(SecureHandler):
    """
    HTTP handler for email services endpoints.

    Provides follow-up tracking, snooze management, and categorization.
    Integrates with the Aragora server routing system.

    RBAC Permissions:
    - email:read - View emails, follow-ups, categories
    - email:create - Create follow-up tracking records
    - email:update - Modify email states (snooze, resolve, feedback)
    """

    RESOURCE_TYPE = "email"

    ROUTES = [
        "/api/v1/email/followups/mark",
        "/api/v1/email/followups/pending",
        "/api/v1/email/followups/check-replies",
        "/api/v1/email/followups/auto-detect",
        "/api/v1/email/snoozed",
        "/api/v1/email/snooze/process-due",
        "/api/v1/email/categories",
        "/api/v1/email/categories/learn",
    ]

    # Prefix routes for dynamic paths
    ROUTE_PREFIXES = [
        "/api/v1/email/followups/",
        "/api/v1/email/",
    ]

    # Pattern routes for specific path structures
    ROUTE_PATTERNS = [
        r"/api/v1/email/[^/]+/snooze-suggestions",
        r"/api/v1/email/[^/]+/snooze",
    ]

    def __init__(self, ctx: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(ctx)
        import re

        self._compiled_patterns = [re.compile(p) for p in self.ROUTE_PATTERNS]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        if path in self.ROUTES:
            return True
        for prefix in self.ROUTE_PREFIXES:
            if path.startswith(prefix) and path != prefix.rstrip("/"):
                return True
        for pattern in self._compiled_patterns:
            if pattern.match(path):
                return True
        return False

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route email services endpoint requests."""
        return None

    @handle_errors("email services creation")
    async def handle_post(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Handle POST requests with RBAC protection."""
        # Read JSON body from request
        data = self.read_json_body(handler) or {}

        # Require authentication for all email operations
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

        # Determine required permission based on operation
        if path in {"/api/v1/email/followups/mark", "/api/v1/email/followups/auto-detect"}:
            permission = "email:create"
        else:
            permission = "email:update"

        try:
            self.check_permission(auth_context, permission)
        except ForbiddenError:
            logger.warning(
                "Email permission denied: %s for user %s", permission, auth_context.user_id
            )
            return error_response("Permission denied", 403)

        user_id = auth_context.user_id

        if path == "/api/v1/email/followups/mark":
            return await handle_mark_followup(data, user_id=user_id)
        elif path == "/api/v1/email/followups/check-replies":
            return await handle_check_replies()
        elif path == "/api/v1/email/followups/auto-detect":
            days_back = data.get("days_back", 7)
            return await handle_auto_detect_followups(days_back=days_back)
        elif path.endswith("/resolve"):
            parts = path.split("/")
            if len(parts) >= 5:
                return await handle_resolve_followup(parts[-2], data)
        elif path.endswith("/snooze") and "process-due" not in path:
            parts = path.split("/")
            if len(parts) >= 5:
                return await handle_apply_snooze(parts[-2], data)
        elif path == "/api/v1/email/snooze/process-due":
            return await handle_process_due_snoozes()
        elif path == "/api/v1/email/categories/learn":
            return await handle_category_feedback(data)
        return error_response("Not found", status=404)

    async def handle_get(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Handle GET requests with RBAC protection."""
        # Categories endpoint is public (static reference data)
        if path == "/api/v1/email/categories":
            user_id = query_params.get("user_id", "default")
            return await handle_get_categories(user_id=user_id)

        # All other read operations require authentication
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

        try:
            self.check_permission(auth_context, "email:read")
        except ForbiddenError:
            logger.warning("Email read denied for user %s", auth_context.user_id)
            return error_response("Permission denied", 403)

        user_id = auth_context.user_id

        if path == "/api/v1/email/followups/pending":
            return await handle_get_pending_followups(
                user_id=user_id,
                include_resolved=query_params.get("include_resolved", "false").lower() == "true",
            )
        elif path == "/api/v1/email/snoozed":
            return await handle_get_snoozed_emails(user_id=user_id)
        elif "snooze-suggestions" in path:
            parts = path.split("/")
            if len(parts) >= 5:
                return await handle_get_snooze_suggestions(
                    parts[-2], data=query_params, user_id=user_id
                )
        return error_response("Not found", status=404)

    @handle_errors("email services deletion")
    async def handle_delete(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Handle DELETE requests with RBAC protection."""
        # Require authentication for all delete operations
        try:
            auth_context = await self.get_auth_context(handler, require_auth=True)
        except UnauthorizedError:
            return error_response("Authentication required", 401)
        except ForbiddenError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Permission denied", 403)

        try:
            self.check_permission(auth_context, "email:update")
        except ForbiddenError:
            logger.warning("Email update denied for user %s", auth_context.user_id)
            return error_response("Permission denied", 403)

        user_id = auth_context.user_id

        if "/snooze" in path:
            parts = path.split("/")
            if len(parts) >= 5:
                return await handle_cancel_snooze(parts[-2], user_id=user_id)
        return error_response("Not found", status=404)
