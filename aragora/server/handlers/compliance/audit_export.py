"""
Audit Export API Handler.

Provides endpoints for audit log query and compliance exports.

Endpoints:
    GET  /api/audit/events      - Query audit events
    GET  /api/audit/stats       - Audit log statistics
    POST /api/audit/export      - Export audit log (JSON, CSV, SOC2)
    POST /api/audit/verify      - Verify audit log integrity
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

from aragora.server.handlers.utils import parse_json_body
from aragora.server.handlers.utils.aiohttp_responses import web_error_response
from aragora.server.handlers.utils.decorators import require_permission

if TYPE_CHECKING:
    from aragora.audit import AuditLog

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependencies
_audit_log = None


def get_audit_log() -> AuditLog:
    """Get or create audit log instance."""
    global _audit_log
    if _audit_log is None:
        from aragora.audit import AuditLog

        _audit_log = AuditLog()
    return _audit_log


@require_permission("audit:read")
async def handle_audit_events(request: web.Request) -> web.Response:
    """
    Query audit events.

    GET /api/audit/events?start_date=...&end_date=...&category=...

    Query params:
        start_date: ISO date (default: 30 days ago)
        end_date: ISO date (default: now)
        category: Filter by category
        action: Filter by action
        actor_id: Filter by actor
        outcome: Filter by outcome
        org_id: Filter by organization
        search: Full-text search
        limit: Max results (default: 100, max: 1000)
        offset: Pagination offset

    Returns:
        JSON with events array
    """
    from aragora.audit import AuditCategory, AuditOutcome, AuditQuery

    audit = get_audit_log()

    # Parse query params
    params = request.query

    # Date range
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=30)

    if params.get("start_date"):
        try:
            start_date = datetime.fromisoformat(params["start_date"].replace("Z", "+00:00"))
        except ValueError:
            return web_error_response("Invalid start_date format", 400)

    if params.get("end_date"):
        try:
            end_date = datetime.fromisoformat(params["end_date"].replace("Z", "+00:00"))
        except ValueError:
            return web_error_response("Invalid end_date format", 400)

    # Build query
    query = AuditQuery(
        start_date=start_date,
        end_date=end_date,
        limit=min(int(params.get("limit", 100) or 100), 1000),
        offset=max(0, int(params.get("offset", 0) or 0)),
    )

    if params.get("category"):
        try:
            query.category = AuditCategory(params["category"])
        except ValueError:
            return web_error_response(f"Invalid category: {params['category']}", 400)

    if params.get("action"):
        query.action = params["action"]

    if params.get("actor_id"):
        query.actor_id = params["actor_id"]

    if params.get("outcome"):
        try:
            query.outcome = AuditOutcome(params["outcome"])
        except ValueError:
            return web_error_response(f"Invalid outcome: {params['outcome']}", 400)

    if params.get("org_id"):
        query.org_id = params["org_id"]

    if params.get("search"):
        query.search_text = params["search"]

    # Execute query
    events = audit.query(query)

    return web.json_response(
        {
            "events": [e.to_dict() for e in events],
            "count": len(events),
            "query": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "limit": query.limit,
                "offset": query.offset,
            },
        }
    )


@require_permission("audit:read")
async def handle_audit_stats(request: web.Request) -> web.Response:
    """
    Get audit log statistics.

    GET /api/audit/stats

    Returns:
        JSON with statistics
    """
    audit = get_audit_log()
    stats = audit.get_stats()
    return web.json_response(stats)


@require_permission("audit:export")
async def handle_audit_export(request: web.Request) -> web.Response:
    """
    Export audit log.

    POST /api/audit/export

    Body:
        format: "json" | "csv" | "soc2" (default: "json")
        start_date: ISO date (required)
        end_date: ISO date (required)
        org_id: Filter by organization (optional)

    Returns:
        File download or JSON with download URL
    """
    audit = get_audit_log()

    body, err = await parse_json_body(request, context="audit_export")
    if err:
        return err

    # Validate required fields
    if not body.get("start_date"):
        return web_error_response("start_date is required", 400)
    if not body.get("end_date"):
        return web_error_response("end_date is required", 400)

    try:
        start_date = datetime.fromisoformat(body["start_date"].replace("Z", "+00:00"))
        end_date = datetime.fromisoformat(body["end_date"].replace("Z", "+00:00"))
    except ValueError:
        return web_error_response("Invalid date format. Use ISO 8601.", 400)

    export_format = body.get("format", "json").lower()
    org_id = body.get("org_id")

    # Create temp file for export
    suffix = ".json" if export_format in ("json", "soc2") else ".csv"
    with tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False) as f:
        output_path = Path(f.name)

    try:
        if export_format == "json":
            count = audit.export_json(output_path, start_date, end_date, org_id)
            content_type = "application/json"
            filename = f"audit_export_{start_date.date()}_{end_date.date()}.json"

        elif export_format == "csv":
            count = audit.export_csv(output_path, start_date, end_date, org_id)
            content_type = "text/csv"
            filename = f"audit_export_{start_date.date()}_{end_date.date()}.csv"

        elif export_format == "soc2":
            result = audit.export_soc2(output_path, start_date, end_date, org_id)
            count = result["events_exported"]
            content_type = "application/json"
            filename = f"soc2_audit_{start_date.date()}_{end_date.date()}.json"

        else:
            return web_error_response(
                f"Invalid format: {export_format}. Use json, csv, or soc2.", 400
            )

        # Read file content
        with open(output_path) as f:
            content = f.read()

        logger.info(
            "audit_export format=%s events=%s period=%s-%s",
            export_format,
            count,
            start_date.date(),
            end_date.date(),
        )

        return web.Response(
            body=content,
            content_type=content_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Audit-Event-Count": str(count),
            },
        )

    finally:
        # Clean up temp file
        if output_path.exists():
            output_path.unlink()


@require_permission("audit:verify")
async def handle_audit_verify(request: web.Request) -> web.Response:
    """
    Verify audit log integrity.

    POST /api/audit/verify

    Body:
        start_date: ISO date (optional)
        end_date: ISO date (optional)

    Returns:
        JSON with verification result
    """
    audit = get_audit_log()

    body, err = await parse_json_body(request, context="audit_verify")
    if err:
        body = {}

    start_date = None
    end_date = None

    if body.get("start_date"):
        try:
            start_date = datetime.fromisoformat(body["start_date"].replace("Z", "+00:00"))
        except ValueError:
            return web_error_response("Invalid start_date format", 400)

    if body.get("end_date"):
        try:
            end_date = datetime.fromisoformat(body["end_date"].replace("Z", "+00:00"))
        except ValueError:
            return web_error_response("Invalid end_date format", 400)

    is_valid, errors = audit.verify_integrity(start_date, end_date)

    return web.json_response(
        {
            "verified": is_valid,
            "errors": errors[:20],  # Limit errors in response
            "total_errors": len(errors),
            "verified_range": {
                "start_date": start_date.isoformat() if start_date else "beginning",
                "end_date": end_date.isoformat() if end_date else "now",
            },
        }
    )


def register_handlers(app: web.Application) -> None:
    """Register audit handlers."""
    app.router.add_get("/api/v1/audit/events", handle_audit_events)
    app.router.add_get("/api/v1/audit/stats", handle_audit_stats)
    app.router.add_post("/api/v1/audit/export", handle_audit_export)
    app.router.add_post("/api/v1/audit/verify", handle_audit_verify)


__all__ = [
    "handle_audit_events",
    "handle_audit_export",
    "handle_audit_stats",
    "handle_audit_verify",
    "register_handlers",
]
