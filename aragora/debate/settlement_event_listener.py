"""Due settlement event listener.

Subscribes to due settlement events from the SettlementReviewScheduler
and performs three actions:

1. Logs the due settlement for audit trail.
2. Emits a notification event that the notification service can pick up.
3. Records the review-due status in the settlement store via the tracker.

This module is wired into the scheduler's ``on_review_due`` callback
during server startup (see ``init_debate_settlement_scheduler``).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def on_settlement_review_due(event: Any) -> None:
    """Handle a due settlement event from the SettlementReviewScheduler.

    This is the main entry point called by the scheduler's
    ``on_review_due`` callback for each settlement that is flagged as
    due for review.

    Args:
        event: A ``SettlementReviewEvent`` instance from
            ``aragora.debate.settlement_scheduler``.
    """
    debate_id = getattr(event, "debate_id", "unknown")

    # 1. Audit log
    _log_due_settlement(event)

    # 2. Emit notification event
    _emit_notification_event(event)

    # 3. Record review-due status in settlement store
    _record_review_due_status(event)

    logger.info(
        "Processed due settlement event for debate %s",
        debate_id,
    )


def _log_due_settlement(event: Any) -> None:
    """Log the due settlement for the audit trail.

    Uses structured logging fields so that log aggregation tools
    can index settlement review events.
    """
    debate_id = getattr(event, "debate_id", "unknown")
    confidence = getattr(event, "confidence", 0.0)
    falsifier_count = getattr(event, "falsifier_count", 0)
    settled_at = getattr(event, "settled_at", "")
    review_horizon = getattr(event, "review_horizon", "")

    logger.info(
        "Settlement due for review: debate=%s confidence=%.3f "
        "falsifiers=%d settled_at=%s review_horizon=%s",
        debate_id,
        confidence,
        falsifier_count,
        settled_at,
        review_horizon,
    )

    # Also record in the audit subsystem if available
    try:
        from aragora.observability.audit_log import AuditCategory, AuditEvent, get_audit_log

        audit = get_audit_log()
        audit.log(
            AuditEvent(
                category=AuditCategory.DEBATE,
                action="settlement_review_due",
                actor_id="system",
                resource_type="debate",
                resource_id=debate_id,
                details={
                    "confidence": confidence,
                    "falsifier_count": falsifier_count,
                    "settled_at": settled_at,
                    "review_horizon": review_horizon,
                },
            )
        )
    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError):
        # Audit subsystem not available; standard logging above is sufficient
        pass


def _emit_notification_event(event: Any) -> None:
    """Emit a notification event for downstream consumers.

    Attempts two delivery mechanisms:
    1. StreamEvent via the events subsystem (for WebSocket clients).
    2. NotificationService for Slack/email/webhook delivery.
    """
    debate_id = getattr(event, "debate_id", "unknown")
    event_dict = event.to_dict() if hasattr(event, "to_dict") else {"debate_id": debate_id}

    # StreamEvent emission (WebSocket clients)
    try:
        from aragora.events.types import StreamEvent, StreamEventType

        stream_event = StreamEvent(
            type=StreamEventType.PHASE_PROGRESS,
            data={
                "source": "settlement_event_listener",
                "action": "settlement_review_due",
                **event_dict,
            },
        )
        # Try to deliver via the global emitter if one is available
        try:
            from aragora.server.stream import get_global_emitter

            emitter = get_global_emitter()
            if emitter is not None:
                emitter.emit(stream_event)
                logger.debug("Emitted stream event for due settlement: %s", debate_id)
        except (ImportError, AttributeError, RuntimeError):
            # No global emitter available; event was created for
            # observability logging only.
            pass
    except ImportError:
        pass  # Events subsystem not available
    except (AttributeError, TypeError, ValueError) as e:
        logger.debug("Could not emit stream event for settlement review: %s", e)

    # NotificationService delivery (Slack/email/webhook)
    try:
        from aragora.notifications.service import get_notification_service
        from aragora.notifications.models import Notification

        confidence = getattr(event, "confidence", 0.0)
        service = get_notification_service()
        notification = Notification(
            title="Settlement Due for Review",
            message=(
                f"Debate {debate_id} settlement is due for review (confidence: {confidence:.2f})."
            ),
            severity="info",
            resource_type="settlement",
            resource_id=debate_id,
        )
        from aragora.utils.async_utils import run_async

        run_async(service.notify(notification))
    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as e:
        logger.debug("Notification service delivery skipped: %s", e)


def _record_review_due_status(event: Any) -> None:
    """Record the review-due status in the settlement store.

    If the scheduler's tracker is available, mark the settlement as
    due for review so that downstream queries (dashboards, CLI) can
    surface it.
    """
    debate_id = getattr(event, "debate_id", "unknown")

    try:
        from aragora.debate.settlement_scheduler import get_scheduler

        scheduler = get_scheduler()
        tracker = getattr(scheduler, "_tracker", None)
        if tracker is None:
            return

        tracker.mark_reviewed(
            debate_id,
            status="due_review",
            notes="Flagged by settlement event listener",
            reviewed_by="settlement_event_listener",
        )
        logger.debug("Recorded review-due status for debate %s", debate_id)
    except (ImportError, AttributeError, TypeError, ValueError, KeyError, RuntimeError) as e:
        logger.debug("Could not record review-due status for %s: %s", debate_id, e)


__all__ = [
    "on_settlement_review_due",
]
