"""
Usage Metering API Handlers.

Provides billing usage endpoints for ENTERPRISE tier:
- GET /api/v1/billing/usage - Current usage summary
- GET /api/v1/billing/usage/breakdown - Detailed breakdown
- GET /api/v1/billing/limits - Current limits and usage %
- POST /api/v1/quotas/request-increase - Submit a quota increase request

Phase 4.3 Implementation.
"""

from __future__ import annotations

import logging
import math
import unicodedata
import uuid
from datetime import datetime, timezone

from aragora.billing.models import SubscriptionTier

from .base import (
    error_response,
    get_string_param,
    handle_errors,
    json_response,
)
from .utils.responses import HandlerResult
from .secure import SecureHandler
from .utils.decorators import require_permission
from .utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for usage endpoints (30 requests per minute)
_usage_limiter = RateLimiter(requests_per_minute=30)


class UsageMeteringHandler(SecureHandler):
    """Handler for usage metering endpoints.

    Provides comprehensive usage tracking and billing information
    for ENTERPRISE tier customers.
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    RESOURCE_TYPE = "billing_usage"

    ROUTES = [
        "/api/v1/billing/usage",
        "/api/v1/billing/usage/breakdown",
        "/api/v1/billing/usage/summary",
        "/api/v1/billing/usage/export",
        "/api/v1/billing/limits",
        "/api/v1/quotas",
        "/api/v1/quotas/usage",
    ]

    DYNAMIC_ROUTES = [
        "/api/v1/quotas/{resource}",
    ]

    _QUOTA_PREFIX = "/api/v1/quotas/"
    _REQUEST_INCREASE_PATH = "/api/v1/quotas/request-increase"

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        if path in self.ROUTES:
            return True
        # Dynamic: /api/v1/quotas/{resource} (but not /api/v1/quotas/usage)
        if path.startswith(self._QUOTA_PREFIX) and path.count("/") == 4:
            return True
        return False

    async def handle(
        self,
        path: str,
        query_params: dict,
        handler,
        method: str = "GET",
    ) -> HandlerResult | None:
        """Route usage metering requests to appropriate methods."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _usage_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for usage endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # Determine HTTP method from handler if not provided
        if hasattr(handler, "command"):
            method = handler.command

        if path == "/api/v1/billing/usage" and method == "GET":
            return await self._get_usage(handler, query_params)

        if path == "/api/v1/billing/usage/summary" and method == "GET":
            return await self._get_usage(handler, query_params)

        if path == "/api/v1/billing/usage/breakdown" and method == "GET":
            return await self._get_usage_breakdown(handler, query_params)

        if path == "/api/v1/billing/limits" and method == "GET":
            return await self._get_limits(handler, query_params)

        if path == "/api/v1/billing/usage/export" and method == "GET":
            return await self._export_usage(handler, query_params)

        if path == "/api/v1/quotas" and method == "GET":
            return await self._get_quota_status(handler, query_params)

        if path == "/api/v1/quotas/usage" and method == "GET":
            return await self._get_quota_usage(handler, query_params)

        # Action literal: must win over the /api/v1/quotas/{resource} branch
        # below, otherwise GET would be mis-served as a lookup for the
        # nonsense resource "request-increase".
        if path == self._REQUEST_INCREASE_PATH:
            if method == "POST":
                return await self._request_quota_increase(handler)
            return error_response("Method not allowed", 405)

        # Dynamic: /api/v1/quotas/{resource}
        if path.startswith(self._QUOTA_PREFIX) and path.count("/") == 4 and method == "GET":
            resource = path.split("/")[4]
            return await self._get_quota_for_resource(handler, resource)

        return error_response("Method not allowed", 405)

    def _get_user_store(self):
        """Get user store from context."""
        return self.ctx.get("user_store")

    def _get_usage_meter(self):
        """Get usage meter instance."""
        from aragora.services.usage_metering import get_usage_meter

        return get_usage_meter()

    def _get_org_tier(self, org) -> str:
        """Get organization tier as string."""
        if org is None:
            return "free"
        if isinstance(org.tier, SubscriptionTier):
            return org.tier.value
        return str(org.tier) if org.tier else "free"

    @handle_errors("get usage")
    @require_permission("org:billing")
    async def _get_usage(
        self,
        handler,
        query_params: dict,
        user=None,
    ) -> HandlerResult:
        """
        Get current usage for the authenticated user's organization.

        Query Parameters:
            period: Billing period (hour, day, week, month, quarter, year)
                   Default: month

        Returns:
            JSON response with usage summary:
            {
                "usage": {
                    "period_start": "2025-01-01T00:00:00Z",
                    "period_end": "2025-01-31T23:59:59Z",
                    "period_type": "month",
                    "tokens": {
                        "input": 500000,
                        "output": 250000,
                        "total": 750000,
                        "cost": "12.50"
                    },
                    "counts": {
                        "debates": 45,
                        "api_calls": 1500
                    },
                    "by_provider": {...},
                    "limits": {...},
                    "usage_percent": {...}
                }
            }
        """
        # Get user and organization
        user_store = self._get_user_store()
        if not user_store:
            return error_response("Service unavailable", 503)

        db_user = user_store.get_user_by_id(user.user_id)
        if not db_user:
            return error_response("User not found", 404)

        org = None
        if db_user.org_id:
            org = user_store.get_organization_by_id(db_user.org_id)

        if not org:
            return error_response("No organization found", 404)

        # Get query parameters
        period = get_string_param(handler, "period", "month")

        # Get tier
        tier = self._get_org_tier(org)

        # Get usage meter
        meter = self._get_usage_meter()

        # Get usage summary
        summary = await meter.get_usage_summary(
            org_id=org.id,
            period=period,
            tier=tier,
        )

        return json_response({"usage": summary.to_dict()})

    @handle_errors("get usage breakdown")
    @require_permission("org:billing")
    async def _get_usage_breakdown(
        self,
        handler,
        query_params: dict,
        user=None,
    ) -> HandlerResult:
        """
        Get detailed usage breakdown for billing.

        Query Parameters:
            start: Start date (ISO format)
            end: End date (ISO format)

        Returns:
            JSON response with detailed breakdown:
            {
                "breakdown": {
                    "totals": {
                        "cost": "125.50",
                        "tokens": 5000000,
                        "debates": 150,
                        "api_calls": 5000
                    },
                    "by_model": [...],
                    "by_provider": [...],
                    "by_day": [...],
                    "by_user": [...]
                }
            }
        """
        # Get user and organization
        user_store = self._get_user_store()
        if not user_store:
            return error_response("Service unavailable", 503)

        db_user = user_store.get_user_by_id(user.user_id)
        if not db_user:
            return error_response("User not found", 404)

        org = None
        if db_user.org_id:
            org = user_store.get_organization_by_id(db_user.org_id)

        if not org:
            return error_response("No organization found", 404)

        # Parse date parameters
        start_str = get_string_param(handler, "start", None)
        end_str = get_string_param(handler, "end", None)

        start_date = None
        end_date = None
        if start_str:
            try:
                start_date = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except ValueError:
                return error_response("Invalid start date format", 400)
        if end_str:
            try:
                end_date = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            except ValueError:
                return error_response("Invalid end date format", 400)

        # Get usage meter
        meter = self._get_usage_meter()

        # Get detailed breakdown
        breakdown = await meter.get_usage_breakdown(
            org_id=org.id,
            start_date=start_date,
            end_date=end_date,
        )

        return json_response({"breakdown": breakdown.to_dict()})

    @handle_errors("get limits")
    @require_permission("org:billing")
    async def _get_limits(
        self,
        handler,
        query_params: dict,
        user=None,
    ) -> HandlerResult:
        """
        Get current usage limits and utilization percentages.

        Returns:
            JSON response with limits and usage:
            {
                "limits": {
                    "tier": "enterprise",
                    "limits": {
                        "tokens": 999999999,
                        "debates": 999999,
                        "api_calls": 999999
                    },
                    "used": {
                        "tokens": 750000,
                        "debates": 45,
                        "api_calls": 1500
                    },
                    "percent": {
                        "tokens": 0.075,
                        "debates": 0.0045,
                        "api_calls": 0.15
                    },
                    "exceeded": {
                        "tokens": false,
                        "debates": false,
                        "api_calls": false
                    }
                }
            }
        """
        # Get user and organization
        user_store = self._get_user_store()
        if not user_store:
            return error_response("Service unavailable", 503)

        db_user = user_store.get_user_by_id(user.user_id)
        if not db_user:
            return error_response("User not found", 404)

        org = None
        if db_user.org_id:
            org = user_store.get_organization_by_id(db_user.org_id)

        if not org:
            return error_response("No organization found", 404)

        # Get tier
        tier = self._get_org_tier(org)

        # Get usage meter
        meter = self._get_usage_meter()

        # Get limits
        limits = await meter.get_usage_limits(
            org_id=org.id,
            tier=tier,
        )

        return json_response({"limits": limits.to_dict()})

    @handle_errors("get quota status")
    @require_permission("org:billing")
    async def _get_quota_status(
        self,
        handler,
        query_params: dict,
        user=None,
    ) -> HandlerResult:
        """
        Get current quota status using the unified QuotaManager.

        Returns:
            JSON response with quota status for all resources:
            {
                "quotas": {
                    "debates": {
                        "limit": 100,
                        "current": 45,
                        "remaining": 55,
                        "period": "day",
                        "percentage_used": 45.0,
                        "is_exceeded": false,
                        "is_warning": false
                    },
                    "api_requests": {...},
                    "tokens": {...}
                }
            }
        """
        from aragora.server.middleware.tier_enforcement import get_quota_manager

        # Get user and organization
        user_store = self._get_user_store()
        if not user_store:
            return error_response("Service unavailable", 503)

        db_user = user_store.get_user_by_id(user.user_id)
        if not db_user:
            return error_response("User not found", 404)

        org = None
        if db_user.org_id:
            org = user_store.get_organization_by_id(db_user.org_id)

        if not org:
            return error_response("No organization found", 404)

        # Get quota status from QuotaManager
        manager = get_quota_manager()

        # Core resources to check
        resources = ["debates", "api_requests", "tokens", "storage_bytes", "knowledge_bytes"]

        quotas = {}
        for resource in resources:
            try:
                status = await manager.get_quota_status(resource, tenant_id=org.id)
                if status:
                    quotas[resource] = {
                        "limit": status.limit,
                        "current": status.current,
                        "remaining": status.remaining,
                        "period": status.period.value,
                        "percentage_used": status.percentage_used,
                        "is_exceeded": status.is_exceeded,
                        "is_warning": status.is_warning,
                        "resets_at": (
                            status.period_resets_at.isoformat() if status.period_resets_at else None
                        ),
                    }
            except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
                logger.warning("Failed to get quota status for %s: %s", resource, e)
                continue

        return json_response({"quotas": quotas})

    @handle_errors("export usage")
    @require_permission("org:billing")
    async def _export_usage(
        self,
        handler,
        query_params: dict,
        user=None,
    ) -> HandlerResult:
        """
        Export usage data as CSV.

        Query Parameters:
            start: Start date (ISO format)
            end: End date (ISO format)
            format: Export format (csv or json), default: csv

        Returns:
            CSV file download or JSON response
        """
        import csv
        import io

        # Get user and organization
        user_store = self._get_user_store()
        if not user_store:
            return error_response("Service unavailable", 503)

        db_user = user_store.get_user_by_id(user.user_id)
        if not db_user:
            return error_response("User not found", 404)

        org = None
        if db_user.org_id:
            org = user_store.get_organization_by_id(db_user.org_id)

        if not org:
            return error_response("No organization found", 404)

        # Parse date parameters
        start_str = get_string_param(handler, "start", None)
        end_str = get_string_param(handler, "end", None)
        export_format = get_string_param(handler, "format", "csv")

        start_date = None
        end_date = None
        if start_str:
            try:
                start_date = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except ValueError:
                return error_response("Invalid start date format", 400)
        if end_str:
            try:
                end_date = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            except ValueError:
                return error_response("Invalid end date format", 400)

        # Get usage meter
        meter = self._get_usage_meter()

        # Get detailed breakdown
        breakdown = await meter.get_usage_breakdown(
            org_id=org.id,
            start_date=start_date,
            end_date=end_date,
        )

        if export_format == "json":
            return json_response(breakdown.to_dict())

        # Build CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(["Usage Export Report"])
        writer.writerow(["Organization", org.name])
        writer.writerow(["Period Start", breakdown.period_start.isoformat()])
        writer.writerow(["Period End", breakdown.period_end.isoformat()])
        writer.writerow([])

        # Totals
        writer.writerow(["Summary"])
        writer.writerow(["Total Cost (USD)", breakdown.total_cost])
        writer.writerow(["Total Tokens", breakdown.total_tokens])
        writer.writerow(["Total Debates", breakdown.total_debates])
        writer.writerow(["Total API Calls", breakdown.total_api_calls])
        writer.writerow([])

        # By model breakdown
        writer.writerow(["Usage by Model"])
        writer.writerow(
            ["Model", "Input Tokens", "Output Tokens", "Total Tokens", "Cost", "Requests"]
        )
        for item in breakdown.by_model:
            writer.writerow(
                [
                    item.get("model", ""),
                    item.get("input_tokens", 0),
                    item.get("output_tokens", 0),
                    item.get("total_tokens", 0),
                    item.get("cost", "0"),
                    item.get("requests", 0),
                ]
            )
        writer.writerow([])

        # By provider breakdown
        writer.writerow(["Usage by Provider"])
        writer.writerow(["Provider", "Total Tokens", "Cost", "Requests"])
        for item in breakdown.by_provider:
            writer.writerow(
                [
                    item.get("provider", ""),
                    item.get("total_tokens", 0),
                    item.get("cost", "0"),
                    item.get("requests", 0),
                ]
            )
        writer.writerow([])

        # Daily breakdown
        writer.writerow(["Daily Usage"])
        writer.writerow(["Date", "Tokens", "Cost", "Debates", "API Calls"])
        for item in breakdown.by_day:
            writer.writerow(
                [
                    item.get("day", ""),
                    item.get("total_tokens", 0),
                    item.get("cost", "0"),
                    item.get("debates", 0),
                    item.get("api_calls", 0),
                ]
            )

        csv_content = output.getvalue()
        output.close()

        # Return CSV file
        filename = f"usage_export_{org.slug}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
        return HandlerResult(
            status_code=200,
            content_type="text/csv",
            body=csv_content.encode("utf-8"),
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @handle_errors("get quota usage")
    @require_permission("org:billing")
    async def _get_quota_usage(
        self,
        handler,
        query_params: dict,
        user=None,
    ) -> HandlerResult:
        """Get quota usage summary across all resource types."""
        from aragora.server.middleware.tier_enforcement import get_quota_manager

        user_store = self._get_user_store()
        if not user_store:
            return error_response("Service unavailable", 503)

        db_user = user_store.get_user_by_id(user.user_id)
        if not db_user:
            return error_response("User not found", 404)

        org = None
        if db_user.org_id:
            org = user_store.get_organization_by_id(db_user.org_id)
        if not org:
            return error_response("No organization found", 404)

        manager = get_quota_manager()
        period = query_params.get("period", ["24h"])[0] if query_params.get("period") else "24h"

        resources = ["debates", "api_requests", "tokens", "storage_bytes", "knowledge_bytes"]
        usage = {}
        for resource in resources:
            try:
                status = await manager.get_quota_status(resource, tenant_id=org.id)
                if status:
                    usage[resource] = {
                        "current": status.current,
                        "limit": status.limit,
                        "percentage_used": status.percentage_used,
                    }
            except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
                logger.warning("Failed to get quota usage for %s: %s", resource, e)
                continue

        return json_response({"usage": usage, "period": period})

    @handle_errors("get quota for resource")
    @require_permission("org:billing")
    async def _get_quota_for_resource(
        self,
        handler,
        resource: str,
        user=None,
    ) -> HandlerResult:
        """Get detailed quota information for a specific resource type."""
        from aragora.server.middleware.tier_enforcement import get_quota_manager

        user_store = self._get_user_store()
        if not user_store:
            return error_response("Service unavailable", 503)

        db_user = user_store.get_user_by_id(user.user_id)
        if not db_user:
            return error_response("User not found", 404)

        org = None
        if db_user.org_id:
            org = user_store.get_organization_by_id(db_user.org_id)
        if not org:
            return error_response("No organization found", 404)

        manager = get_quota_manager()

        try:
            status = await manager.get_quota_status(resource, tenant_id=org.id)
        except (ValueError, TypeError, KeyError, AttributeError, OSError, RuntimeError) as e:
            logger.warning("Failed to get quota for %s: %s", resource, e)
            return error_response("Failed to retrieve quota information", 500)

        if not status:
            return error_response(f"Unknown resource type: {resource}", 404)

        return json_response(
            {
                "resource": resource,
                "limit": status.limit,
                "current": status.current,
                "remaining": status.remaining,
                "period": status.period.value,
                "percentage_used": status.percentage_used,
                "is_exceeded": status.is_exceeded,
                "is_warning": status.is_warning,
                "resets_at": status.period_resets_at.isoformat()
                if status.period_resets_at
                else None,
            }
        )

    @handle_errors("request quota increase")
    @require_permission("org:billing")
    async def _request_quota_increase(
        self,
        handler,
        user=None,
    ) -> HandlerResult:
        """
        Submit a quota increase request for review.

        Body Parameters:
            resource: Resource type the increase applies to (required)
            requested_limit: Desired new limit, positive number (optional)
            reason: Why the increase is needed (optional; also accepted as
                    'justification', the key the python SDK documents)

        Returns:
            JSON response with the submission receipt:
            {
                "request_id": "qir-...",
                "status": "pending",
                "resource": "debates",
                "requested_limit": 500,
                "reason": "scaling up",
                "org_id": "org-001",
                "submitted_by": "user-001",
                "submitted_at": "2026-01-01T00:00:00+00:00"
            }
        """
        user_store = self._get_user_store()
        if not user_store:
            return error_response("Service unavailable", 503)

        db_user = user_store.get_user_by_id(user.user_id)
        if not db_user:
            return error_response("User not found", 404)

        org = None
        if db_user.org_id:
            org = user_store.get_organization_by_id(db_user.org_id)
        if not org:
            return error_response("No organization found", 404)

        body, err = self.read_json_object_or_error(handler)
        if err:
            return err
        if body is None:  # pragma: no cover - read_json_object_or_error guarantees this
            return error_response("Invalid JSON body", 400)

        resource = body.get("resource")
        if not isinstance(resource, str) or not resource.strip():
            return error_response("Field 'resource' is required", 400)
        resource = resource.strip()
        # O(1) length cap before the per-character category scan below, so an
        # oversized value never pays for a full scan.
        if len(resource) > 256:
            return error_response("Field 'resource' exceeds maximum length of 256", 400)
        # The value feeds the audit log line below; control characters and
        # unicode line separators would allow forged log entries. Category Cc
        # covers C0, DEL, and C1 (e.g. U+009B bare CSI, a terminal-escape
        # vector when logs are viewed in terminals); Cf covers format chars
        # (e.g. U+202E RLO, zero-width joiners) that visually spoof the line;
        # Cs covers lone surrogates (reachable via JSON \ud800 escapes) that
        # a utf-8 log handler cannot encode, silently dropping the audit
        # line; LS/PS are separators outside those categories.
        if any(
            unicodedata.category(ch) in ("Cc", "Cf", "Cs") or ch in "\u2028\u2029"
            for ch in resource
        ):
            return error_response("Field 'resource' contains invalid characters", 400)

        requested_limit = body.get("requested_limit")
        # isfinite only applies to floats: converting an arbitrary-precision
        # JSON int to float raises OverflowError, and ints are always finite.
        if requested_limit is not None and (
            isinstance(requested_limit, bool)
            or not isinstance(requested_limit, (int, float))
            or (isinstance(requested_limit, float) and not math.isfinite(requested_limit))
            or requested_limit <= 0
        ):
            return error_response("Field 'requested_limit' must be a positive number", 400)

        reason = body.get("reason")
        if reason is None:
            reason = body.get("justification")
        if reason is not None and not isinstance(reason, str):
            return error_response("Field 'reason' must be a string", 400)
        if reason is not None and len(reason) > 2000:
            return error_response("Field 'reason' exceeds maximum length of 2000", 400)

        request_id = f"qir-{uuid.uuid4().hex}"
        submitted_at = datetime.now(timezone.utc).isoformat()

        # No persistence layer exists for increase requests yet; the audit
        # trail is this structured log line until a review workflow lands.
        logger.info(
            "Quota increase request %s submitted: org=%s resource=%s requested_limit=%s user=%s",
            request_id,
            org.id,
            resource,
            requested_limit,
            user.user_id,
        )

        return json_response(
            {
                "request_id": request_id,
                "status": "pending",
                "resource": resource,
                "requested_limit": requested_limit,
                "reason": reason,
                "org_id": org.id,
                "submitted_by": user.user_id,
                "submitted_at": submitted_at,
            }
        )


__all__ = ["UsageMeteringHandler"]
