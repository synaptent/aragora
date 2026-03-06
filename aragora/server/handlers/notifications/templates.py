"""
Notification template management endpoints.

Provides:
- GET  /api/v1/notifications/templates           (list all templates)
- GET  /api/v1/notifications/templates/{id}      (get single template)
- PUT  /api/v1/notifications/templates/{id}      (update subject/body)
- POST /api/v1/notifications/templates/{id}/reset    (reset to default)
- POST /api/v1/notifications/templates/{id}/preview  (render with sample values)
"""

from __future__ import annotations

import copy
import logging
import re
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..utils.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

_templates_limiter = RateLimiter(requests_per_minute=60)

# ---------------------------------------------------------------------------
# Default templates
# ---------------------------------------------------------------------------

_DEFAULT_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "debate_completed",
        "name": "Debate Completed",
        "description": "Sent when a debate finishes and a verdict is available.",
        "channel": "email",
        "subject": 'Your debate on "{{topic}}" is complete',
        "body": (
            "Hello {{user_name}},\n\n"
            'The debate on "{{topic}}" has concluded.\n\n'
            "Verdict: {{verdict}}\n"
            "Confidence: {{confidence}}%\n"
            "Duration: {{duration}}\n\n"
            "View the full results at: {{result_url}}\n\n"
            "— Aragora"
        ),
        "variables": ["topic", "user_name", "verdict", "confidence", "duration", "result_url"],
        "sample_values": {
            "topic": "Should we migrate to microservices?",
            "user_name": "Alex",
            "verdict": "Consensus reached — proceed with phased migration",
            "confidence": "87",
            "duration": "4m 32s",
            "result_url": "https://app.aragora.ai/debates/abc123",
        },
    },
    {
        "id": "finding_critical",
        "name": "Critical Finding",
        "description": "Sent immediately when a critical-severity finding is detected.",
        "channel": "email",
        "subject": "⚠ Critical finding: {{finding_title}}",
        "body": (
            "Hello {{user_name}},\n\n"
            "A critical finding requires your attention:\n\n"
            "Title: {{finding_title}}\n"
            "Severity: {{severity}}\n"
            "Detected: {{detected_at}}\n"
            "Detail: {{detail}}\n\n"
            "Review it now: {{finding_url}}\n\n"
            "— Aragora"
        ),
        "variables": [
            "user_name",
            "finding_title",
            "severity",
            "detected_at",
            "detail",
            "finding_url",
        ],
        "sample_values": {
            "user_name": "Alex",
            "finding_title": "Unvalidated external input in payment flow",
            "severity": "CRITICAL",
            "detected_at": "2026-03-06 09:14 UTC",
            "detail": "User-supplied data reaches SQL query without sanitisation.",
            "finding_url": "https://app.aragora.ai/findings/xyz789",
        },
    },
    {
        "id": "audit_completed",
        "name": "Audit Completed",
        "description": "Sent when a codebase or compliance audit finishes.",
        "channel": "email",
        "subject": "Audit complete: {{audit_name}}",
        "body": (
            "Hello {{user_name}},\n\n"
            'Audit "{{audit_name}}" has finished.\n\n'
            "Files scanned: {{files_scanned}}\n"
            "Issues found: {{issues_found}}\n"
            "Critical: {{critical_count}}\n\n"
            "Download report: {{report_url}}\n\n"
            "— Aragora"
        ),
        "variables": [
            "user_name",
            "audit_name",
            "files_scanned",
            "issues_found",
            "critical_count",
            "report_url",
        ],
        "sample_values": {
            "user_name": "Alex",
            "audit_name": "Q1 Compliance Scan",
            "files_scanned": "1,247",
            "issues_found": "14",
            "critical_count": "2",
            "report_url": "https://app.aragora.ai/audits/report-q1",
        },
    },
    {
        "id": "budget_alert",
        "name": "Budget Alert",
        "description": "Sent when API spend approaches or exceeds a configured threshold.",
        "channel": "email",
        "subject": "Budget alert: {{percent_used}}% of {{budget_name}} used",
        "body": (
            "Hello {{user_name}},\n\n"
            'Your budget "{{budget_name}}" has reached {{percent_used}}% utilisation.\n\n'
            "Spent so far: {{amount_spent}}\n"
            "Budget limit: {{budget_limit}}\n"
            "Period: {{period}}\n\n"
            "Manage budgets: {{settings_url}}\n\n"
            "— Aragora"
        ),
        "variables": [
            "user_name",
            "budget_name",
            "percent_used",
            "amount_spent",
            "budget_limit",
            "period",
            "settings_url",
        ],
        "sample_values": {
            "user_name": "Alex",
            "budget_name": "Production API",
            "percent_used": "80",
            "amount_spent": "$8.23",
            "budget_limit": "$10.00",
            "period": "March 2026",
            "settings_url": "https://app.aragora.ai/settings/billing",
        },
    },
    {
        "id": "weekly_digest",
        "name": "Weekly Digest",
        "description": "Weekly summary of debate activity, findings, and cost.",
        "channel": "email",
        "subject": "Your Aragora weekly digest — {{week_of}}",
        "body": (
            "Hello {{user_name}},\n\n"
            "Here's your week in review:\n\n"
            "Debates run: {{debates_count}}\n"
            "Consensus rate: {{consensus_rate}}%\n"
            "Findings flagged: {{findings_count}}\n"
            "API cost: {{api_cost}}\n\n"
            "Full dashboard: {{dashboard_url}}\n\n"
            "— Aragora"
        ),
        "variables": [
            "user_name",
            "week_of",
            "debates_count",
            "consensus_rate",
            "findings_count",
            "api_cost",
            "dashboard_url",
        ],
        "sample_values": {
            "user_name": "Alex",
            "week_of": "3–9 March 2026",
            "debates_count": "12",
            "consensus_rate": "75",
            "findings_count": "3",
            "api_cost": "$4.57",
            "dashboard_url": "https://app.aragora.ai/dashboard",
        },
    },
]

# template_id → default dict, for fast lookup
_DEFAULT_TEMPLATES_BY_ID: dict[str, dict[str, Any]] = {t["id"]: t for t in _DEFAULT_TEMPLATES}

# Per-user overrides: { user_id → { template_id → { "subject": …, "body": … } } }
_user_template_overrides: dict[str, dict[str, dict[str, str]]] = {}

_VARIABLE_RE = re.compile(r"\{\{(\w+)\}\}")


def _render_template(text: str, values: dict[str, str]) -> str:
    """Replace {{variable}} placeholders with values from *values*.

    Unknown variables are left as-is.
    """
    return _VARIABLE_RE.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def _template_with_overrides(template_id: str, user_id: str) -> dict[str, Any] | None:
    """Return a template dict with any per-user overrides applied."""
    base = _DEFAULT_TEMPLATES_BY_ID.get(template_id)
    if base is None:
        return None
    result = copy.deepcopy(base)
    user_overrides = _user_template_overrides.get(user_id, {})
    tpl_overrides = user_overrides.get(template_id, {})
    if "subject" in tpl_overrides:
        result["subject"] = tpl_overrides["subject"]
    if "body" in tpl_overrides:
        result["body"] = tpl_overrides["body"]
    result["customized"] = bool(tpl_overrides)
    return result


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

_PATH_PREFIX = "/api/notifications/templates"


class NotificationTemplatesHandler(BaseHandler):
    """CRUD handler for per-user notification templates."""

    ROUTES = [
        "/api/v1/notifications/templates",
        "/api/v1/notifications/templates/{id}",
        "/api/v1/notifications/templates/{id}/reset",
        "/api/v1/notifications/templates/{id}/preview",
    ]
    ROUTE_PREFIXES = [
        "/api/notifications/templates",
        "/api/v1/notifications/templates",
    ]

    def __init__(self, ctx: dict[str, Any] | None = None):
        self.ctx = ctx or {}

    # ------------------------------------------------------------------
    # Routing helpers
    # ------------------------------------------------------------------

    def can_handle(self, path: str) -> bool:
        cleaned = strip_version_prefix(path)
        return cleaned.startswith(_PATH_PREFIX)

    def _get_user_id(self, handler: Any) -> str:
        user = self.get_current_user(handler)
        if user and hasattr(user, "user_id"):
            return user.user_id
        return "anonymous"

    def _parse_template_id(self, cleaned_path: str) -> str | None:
        """Extract template id from path like /api/notifications/templates/{id}[/…]."""
        parts = cleaned_path.split("/")
        # parts: ['', 'api', 'notifications', 'templates', '{id}', ...]
        if len(parts) < 5 or not parts[4]:
            return None
        return parts[4]

    def _is_reset(self, cleaned_path: str) -> bool:
        return cleaned_path.endswith("/reset")

    def _is_preview(self, cleaned_path: str) -> bool:
        return cleaned_path.endswith("/preview")

    # ------------------------------------------------------------------
    # GET dispatch
    # ------------------------------------------------------------------

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        cleaned = strip_version_prefix(path)
        if not cleaned.startswith(_PATH_PREFIX):
            return None

        client_ip = get_client_ip(handler)
        if not _templates_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        template_id = self._parse_template_id(cleaned)
        if template_id is None:
            return self._list_templates(handler)
        return self._get_template(handler, template_id)

    # ------------------------------------------------------------------
    # PUT (update subject/body)
    # ------------------------------------------------------------------

    @handle_errors("notification template update")
    @require_permission("notifications:manage_preferences")
    def handle_put(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        cleaned = strip_version_prefix(path)
        if not cleaned.startswith(_PATH_PREFIX):
            return None

        client_ip = get_client_ip(handler)
        if not _templates_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        template_id = self._parse_template_id(cleaned)
        if template_id is None:
            return error_response("Template ID required", 400)
        return self._update_template(handler, template_id)

    # ------------------------------------------------------------------
    # POST (reset or preview)
    # ------------------------------------------------------------------

    @handle_errors("notification template action")
    @require_permission("notifications:manage_preferences")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        cleaned = strip_version_prefix(path)
        if not cleaned.startswith(_PATH_PREFIX):
            return None

        client_ip = get_client_ip(handler)
        if not _templates_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        template_id = self._parse_template_id(cleaned)
        if template_id is None:
            return error_response("Template ID required", 400)

        if self._is_reset(cleaned):
            return self._reset_template(handler, template_id)
        if self._is_preview(cleaned):
            return self._preview_template(handler, template_id)
        return error_response("Unknown action", 400)

    # ------------------------------------------------------------------
    # Implementation
    # ------------------------------------------------------------------

    def _list_templates(self, handler: Any) -> HandlerResult:
        user_id = self._get_user_id(handler)
        templates = [_template_with_overrides(t["id"], user_id) for t in _DEFAULT_TEMPLATES]
        return json_response({"templates": templates, "count": len(templates)})

    def _get_template(self, handler: Any, template_id: str) -> HandlerResult:
        user_id = self._get_user_id(handler)
        tpl = _template_with_overrides(template_id, user_id)
        if tpl is None:
            return error_response(f"Template '{template_id}' not found", 404)
        return json_response({"template": tpl})

    def _update_template(self, handler: Any, template_id: str) -> HandlerResult:
        if template_id not in _DEFAULT_TEMPLATES_BY_ID:
            return error_response(f"Template '{template_id}' not found", 404)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        subject = body.get("subject")
        body_text = body.get("body")

        if subject is None and body_text is None:
            return error_response("Provide 'subject' and/or 'body' to update", 400)

        if subject is not None and not isinstance(subject, str):
            return error_response("'subject' must be a string", 400)
        if body_text is not None and not isinstance(body_text, str):
            return error_response("'body' must be a string", 400)

        user_id = self._get_user_id(handler)
        if user_id not in _user_template_overrides:
            _user_template_overrides[user_id] = {}
        if template_id not in _user_template_overrides[user_id]:
            _user_template_overrides[user_id][template_id] = {}

        if subject is not None:
            _user_template_overrides[user_id][template_id]["subject"] = subject
        if body_text is not None:
            _user_template_overrides[user_id][template_id]["body"] = body_text

        tpl = _template_with_overrides(template_id, user_id)
        return json_response({"template": tpl, "updated": True})

    def _reset_template(self, handler: Any, template_id: str) -> HandlerResult:
        if template_id not in _DEFAULT_TEMPLATES_BY_ID:
            return error_response(f"Template '{template_id}' not found", 404)

        user_id = self._get_user_id(handler)
        user_overrides = _user_template_overrides.get(user_id, {})
        user_overrides.pop(template_id, None)
        if not user_overrides and user_id in _user_template_overrides:
            del _user_template_overrides[user_id]

        tpl = _template_with_overrides(template_id, user_id)
        return json_response({"template": tpl, "reset": True})

    def _preview_template(self, handler: Any, template_id: str) -> HandlerResult:
        user_id = self._get_user_id(handler)
        tpl = _template_with_overrides(template_id, user_id)
        if tpl is None:
            return error_response(f"Template '{template_id}' not found", 404)

        body = self.read_json_body(handler) or {}
        values: dict[str, str] = {**tpl["sample_values"], **body.get("values", {})}

        rendered_subject = _render_template(tpl["subject"], values)
        rendered_body = _render_template(tpl["body"], values)

        return json_response(
            {
                "template_id": template_id,
                "rendered_subject": rendered_subject,
                "rendered_body": rendered_body,
                "values_used": values,
            }
        )
