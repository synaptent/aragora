"""Ralph campaign dashboard endpoint handler.

Provides REST APIs for Ralph campaign observability:

- GET /api/v1/ralph/campaigns          -- List all campaigns
- GET /api/v1/ralph/campaigns/{id}     -- Campaign detail
- GET /api/v1/ralph/campaigns/{id}/timeline  -- Campaign step timeline
- GET /api/v1/ralph/campaigns/{id}/blockers  -- Blocker breakdown
- GET /api/v1/ralph/campaigns/{id}/repairs   -- Repair stats
- GET /api/v1/ralph/campaigns/{id}/budget    -- Budget burn
- GET /api/v1/ralph/campaigns/{id}/pr-gate   -- PR merge gate status
- GET /api/v1/ralph/overview           -- Aggregate overview
- GET /api/v1/ralph/blockers           -- Global blocker breakdown
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.ralph.dashboard import RalphDashboard

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..utils.decorators import require_permission

logger = logging.getLogger(__name__)


class RalphDashboardHandler(BaseHandler):
    """Handler for Ralph campaign dashboard endpoints."""

    ROUTES = [
        "/api/ralph/campaigns",
        "/api/ralph/campaigns/{campaign_id}",
        "/api/ralph/campaigns/{campaign_id}/timeline",
        "/api/ralph/campaigns/{campaign_id}/blockers",
        "/api/ralph/campaigns/{campaign_id}/repairs",
        "/api/ralph/campaigns/{campaign_id}/budget",
        "/api/ralph/campaigns/{campaign_id}/pr-gate",
        "/api/ralph/overview",
        "/api/ralph/blockers",
    ]
    # Campaign-specific routes are matched by prefix
    _CAMPAIGN_PREFIX = "/api/ralph/campaigns/"

    # Registered with the dispatch route index so campaign-detail paths
    # (/api/ralph/campaigns/{id}/...) resolve without an exact-route hit.
    ROUTE_PREFIXES = [
        "/api/ralph/",
        "/api/v1/ralph/",
    ]

    def __init__(self, ctx: dict | None = None):
        self.ctx = ctx or {}

    def can_handle(self, path: str) -> bool:
        normalized = strip_version_prefix(path)
        if normalized in self.ROUTES:
            return True
        return normalized.startswith(self._CAMPAIGN_PREFIX) and len(normalized.split("/")) >= 5

    @require_permission("ralph:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        normalized = strip_version_prefix(path)

        if normalized == "/api/ralph/campaigns":
            return self._list_campaigns()
        if normalized == "/api/ralph/overview":
            return self._get_overview()
        if normalized == "/api/ralph/blockers":
            return self._get_global_blockers()

        if normalized.startswith(self._CAMPAIGN_PREFIX):
            return self._route_campaign(normalized)

        return None

    def _route_campaign(self, normalized: str) -> HandlerResult | None:
        parts = normalized.split("/")
        # /api/ralph/campaigns/{id} → parts = ['', 'api', 'ralph', 'campaigns', '{id}']
        if len(parts) < 5:
            return None
        campaign_id = parts[4]
        if not campaign_id:
            return None
        sub = parts[5] if len(parts) > 5 else None

        if sub is None:
            return self._get_campaign_detail(campaign_id)
        if sub == "timeline":
            return self._get_campaign_timeline(campaign_id)
        if sub == "blockers":
            return self._get_campaign_blockers(campaign_id)
        if sub == "repairs":
            return self._get_campaign_repairs(campaign_id)
        if sub == "budget":
            return self._get_campaign_budget(campaign_id)
        if sub == "pr-gate":
            return self._get_campaign_pr_gate(campaign_id)

        return None

    @handle_errors("list campaigns")
    def _list_campaigns(self) -> HandlerResult:
        dashboard = self._get_dashboard()
        campaigns = dashboard.list_campaigns()
        return json_response({"campaigns": campaigns, "count": len(campaigns)})

    @handle_errors("get overview")
    def _get_overview(self) -> HandlerResult:
        dashboard = self._get_dashboard()
        return json_response({"data": dashboard.get_overview()})

    @handle_errors("get global blockers")
    def _get_global_blockers(self) -> HandlerResult:
        dashboard = self._get_dashboard()
        return json_response({"data": dashboard.get_blocker_breakdown()})

    @handle_errors("get campaign detail")
    def _get_campaign_detail(self, campaign_id: str) -> HandlerResult:
        dashboard = self._get_dashboard()
        detail = dashboard.get_campaign_detail(campaign_id)
        if detail is None:
            return error_response(f"Campaign not found: {campaign_id}", 404)
        return json_response({"data": detail})

    @handle_errors("get campaign timeline")
    def _get_campaign_timeline(self, campaign_id: str) -> HandlerResult:
        dashboard = self._get_dashboard()
        timeline = dashboard.get_campaign_timeline(campaign_id)
        if not timeline:
            return error_response(f"Campaign not found: {campaign_id}", 404)
        return json_response({"timeline": timeline})

    @handle_errors("get campaign blockers")
    def _get_campaign_blockers(self, campaign_id: str) -> HandlerResult:
        dashboard = self._get_dashboard()
        breakdown = dashboard.get_blocker_breakdown(campaign_id)
        return json_response({"data": breakdown})

    @handle_errors("get campaign repairs")
    def _get_campaign_repairs(self, campaign_id: str) -> HandlerResult:
        dashboard = self._get_dashboard()
        stats = dashboard.get_repair_stats(campaign_id)
        return json_response({"data": stats})

    @handle_errors("get campaign budget")
    def _get_campaign_budget(self, campaign_id: str) -> HandlerResult:
        dashboard = self._get_dashboard()
        budget = dashboard.get_budget_summary(campaign_id)
        return json_response({"data": budget})

    @handle_errors("get campaign PR gate")
    def _get_campaign_pr_gate(self, campaign_id: str) -> HandlerResult:
        dashboard = self._get_dashboard()
        gate = dashboard.get_pr_gate_status(campaign_id)
        if gate is None:
            return error_response(f"Campaign not found: {campaign_id}", 404)
        return json_response({"data": gate})

    def _get_dashboard(self) -> RalphDashboard:
        from aragora.ralph.dashboard import RalphDashboard

        state_dir = self.ctx.get("ralph_state_dir")
        return RalphDashboard(state_dir=state_dir)
