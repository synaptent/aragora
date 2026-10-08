"""
Email Vetted Decisionmaking HTTP Handler.

Provides REST API endpoints for multi-agent email vetted decisionmaking:
- POST /api/v1/email/prioritize - Prioritize a single email
- POST /api/v1/email/prioritize/batch - Prioritize multiple emails
- POST /api/v1/email/triage - Triage inbox with full categorization
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.utils.rate_limit import RateLimiter, get_client_ip
from aragora.services.email_debate import EmailDebateService, EmailInput

logger = logging.getLogger(__name__)

_email_debate_limiter = RateLimiter(requests_per_minute=10)


class EmailDebateHandler(BaseHandler):
    """
    Handler for email vetted decisionmaking API endpoints.

    Provides multi-agent email prioritization and triage.
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/email/prioritize",
        "/api/v1/email/prioritize/batch",
        "/api/v1/email/triage",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the request."""
        return path in self.ROUTES

    @require_permission("email:read")
    def handle(self, path: str, query_params: dict, handler=None) -> HandlerResult | None:
        """Handle GET requests (not supported)."""
        return error_response("Use POST method for email vetted decisionmaking", 405)

    @handle_errors("email debate creation")
    @require_permission("email:create")
    async def handle_post(
        self, path: str, query_params: dict, handler=None
    ) -> HandlerResult | None:
        """Handle POST requests."""
        client_ip = get_client_ip(handler)
        if not _email_debate_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/v1/email/prioritize":
            return await self._prioritize_single(handler)
        elif path == "/api/v1/email/prioritize/batch":
            return await self._prioritize_batch(handler)
        elif path == "/api/v1/email/triage":
            return await self._triage_inbox(handler)
        return None

    async def _prioritize_single(self, handler) -> HandlerResult:
        """
        Prioritize a single email.

        Expected body:
        {
            "subject": "Meeting tomorrow",
            "body": "Hi, can we meet tomorrow at 3pm?",
            "sender": "john@example.com",
            "received_at": "2024-01-15T10:30:00Z",
            "message_id": "msg-123",
            "user_id": "user-456"
        }
        """
        body, err = self.read_json_body_validated(handler)
        if err:
            return err

        if not body.get("subject") and not body.get("body"):
            return error_response("Missing required field: subject or body", 400)

        try:
            service = EmailDebateService(
                fast_mode=body.get("fast_mode", True),
                enable_pii_redaction=body.get("enable_pii_redaction", True),
            )

            # Parse received_at
            received_at = datetime.now(timezone.utc)
            if body.get("received_at"):
                try:
                    received_at = datetime.fromisoformat(body["received_at"].replace("Z", "+00:00"))
                except ValueError:
                    pass

            email = EmailInput(
                subject=body.get("subject", ""),
                body=body.get("body", ""),
                sender=body.get("sender", ""),
                received_at=received_at,
                message_id=body.get("message_id"),
                recipients=body.get("recipients", []),
                cc=body.get("cc", []),
                attachments=body.get("attachments", []),
            )

            user_id = body.get("user_id", "default")

            result = await service.prioritize_email(email, user_id)

            return json_response(result.to_dict())

        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
        ) as e:
            logger.exception("Email prioritization failed: %s", e)
            return error_response("Prioritization failed", 500)

    async def _prioritize_batch(self, handler) -> HandlerResult:
        """
        Prioritize multiple emails.

        Expected body:
        {
            "emails": [
                {
                    "subject": "...",
                    "body": "...",
                    "sender": "...",
                    "received_at": "...",
                    "message_id": "..."
                }
            ],
            "user_id": "user-456",
            "max_concurrent": 5
        }
        """
        body, err = self.read_json_body_validated(handler)
        if err:
            return err

        if not body.get("emails"):
            return error_response("Missing required field: emails", 400)

        try:
            service = EmailDebateService(
                fast_mode=body.get("fast_mode", True),
                enable_pii_redaction=body.get("enable_pii_redaction", True),
            )

            emails = []
            for e in body["emails"]:
                received_at = datetime.now(timezone.utc)
                if e.get("received_at"):
                    try:
                        received_at = datetime.fromisoformat(
                            e["received_at"].replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass

                emails.append(
                    EmailInput(
                        subject=e.get("subject", ""),
                        body=e.get("body", ""),
                        sender=e.get("sender", ""),
                        received_at=received_at,
                        message_id=e.get("message_id"),
                        recipients=e.get("recipients", []),
                        cc=e.get("cc", []),
                        attachments=e.get("attachments", []),
                    )
                )

            user_id = body.get("user_id", "default")
            max_concurrent = body.get("max_concurrent", 5)

            result = await service.prioritize_batch(emails, user_id, max_concurrent)

            return json_response(
                {
                    "results": [r.to_dict() for r in result.results],
                    "total_emails": result.total_emails,
                    "processed_emails": result.processed_emails,
                    "duration_seconds": result.duration_seconds,
                    "urgent_count": result.urgent_count,
                    "action_required_count": result.action_required_count,
                    "errors": result.errors,
                }
            )

        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
        ) as e:
            logger.exception("Batch prioritization failed: %s", e)
            return error_response("Batch prioritization failed", 500)

    async def _triage_inbox(self, handler) -> HandlerResult:
        """
        Full inbox triage with categorization and sorting.

        Expected body:
        {
            "emails": [...],
            "user_id": "user-456",
            "sort_by": "priority",
            "group_by": "category"
        }
        """
        body, err = self.read_json_body_validated(handler)
        if err:
            return err

        if not body.get("emails"):
            return error_response("Missing required field: emails", 400)

        try:
            service = EmailDebateService(
                fast_mode=body.get("fast_mode", True),
                enable_pii_redaction=body.get("enable_pii_redaction", True),
            )

            emails = []
            for e in body["emails"]:
                received_at = datetime.now(timezone.utc)
                if e.get("received_at"):
                    try:
                        received_at = datetime.fromisoformat(
                            e["received_at"].replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass

                emails.append(
                    EmailInput(
                        subject=e.get("subject", ""),
                        body=e.get("body", ""),
                        sender=e.get("sender", ""),
                        received_at=received_at,
                        message_id=e.get("message_id"),
                        recipients=e.get("recipients", []),
                        cc=e.get("cc", []),
                        attachments=e.get("attachments", []),
                    )
                )

            user_id = body.get("user_id", "default")

            result = await service.prioritize_batch(emails, user_id)

            # Sort results (sort_by parameter reserved for future use)
            _sort_by = body.get("sort_by", "priority")
            priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3, "spam": 4}

            sorted_results = sorted(
                result.results,
                key=lambda r: (
                    priority_order.get(r.priority.value, 5),
                    -r.confidence,
                ),
            )

            # Group by category if requested
            group_by = body.get("group_by")
            if group_by == "category":
                grouped: dict[str, list] = {}
                for r in sorted_results:
                    key = r.category.value
                    if key not in grouped:
                        grouped[key] = []
                    grouped[key].append(r.to_dict())

                return json_response(
                    {
                        "grouped": grouped,
                        "total_emails": result.total_emails,
                        "urgent_count": result.urgent_count,
                        "action_required_count": result.action_required_count,
                        "duration_seconds": result.duration_seconds,
                    }
                )
            elif group_by == "priority":
                grouped = result.by_priority
                return json_response(
                    {
                        "grouped": {k: [r.to_dict() for r in v] for k, v in grouped.items()},
                        "total_emails": result.total_emails,
                        "urgent_count": result.urgent_count,
                        "action_required_count": result.action_required_count,
                        "duration_seconds": result.duration_seconds,
                    }
                )

            return json_response(
                {
                    "results": [r.to_dict() for r in sorted_results],
                    "total_emails": result.total_emails,
                    "urgent_count": result.urgent_count,
                    "action_required_count": result.action_required_count,
                    "duration_seconds": result.duration_seconds,
                }
            )

        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
        ) as e:
            logger.exception("Inbox triage failed: %s", e)
            return error_response("Inbox triage failed", 500)


__all__ = ["EmailDebateHandler"]
