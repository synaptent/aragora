"""
Analytics Performance endpoint handlers.

Provides REST APIs for analytics performance metrics:

- GET /api/v1/analytics/agents/performance - Aggregate agent performance metrics
- GET /api/v1/analytics/debates/summary - Debate summary statistics
- GET /api/v1/analytics/trends - General trend analysis

These endpoints complement the existing analytics handlers by providing
summary-level performance data suitable for dashboards and reports.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from aragora.config import CACHE_TTL_ANALYTICS
from aragora.rbac.decorators import require_permission
from aragora.server.validation.query_params import safe_query_int

try:
    from aragora.rbac.checker import check_permission  # noqa: F401
    from aragora.rbac.models import AuthorizationContext  # noqa: F401

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False
from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed
from aragora.server.versioning.compat import strip_version_prefix

from .cache import CACHE_CONFIGS, CacheConfig
from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    ttl_cache,
)
from ..openapi_decorator import api_endpoint, query_param, ok_response
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Permission required for analytics performance access
PERM_ANALYTICS_PERFORMANCE = "analytics:read"

# Rate limiter for analytics performance endpoints (60 requests per minute)
_analytics_performance_limiter = RateLimiter(requests_per_minute=60)

# Valid time ranges for trend queries
VALID_TIME_RANGES = {"7d", "14d", "30d", "90d", "180d", "365d", "all"}

# Valid granularities
VALID_GRANULARITIES = {"daily", "weekly", "monthly"}

# Add cache config for performance endpoints
if "agent_performance" not in CACHE_CONFIGS:
    CACHE_CONFIGS["agent_performance"] = CacheConfig(
        ttl_seconds=300.0,  # 5 minutes
        key_prefix="analytics_agent_performance",
        maxsize=200,
    )

if "debates_summary" not in CACHE_CONFIGS:
    CACHE_CONFIGS["debates_summary"] = CacheConfig(
        ttl_seconds=300.0,
        key_prefix="analytics_debates_summary",
        maxsize=200,
    )

if "general_trends" not in CACHE_CONFIGS:
    CACHE_CONFIGS["general_trends"] = CacheConfig(
        ttl_seconds=300.0,
        key_prefix="analytics_general_trends",
        maxsize=200,
    )


def _parse_time_range(time_range: str) -> datetime | None:
    """Parse time range string into a start datetime.

    Args:
        time_range: Time range string like '7d', '30d', '365d', or 'all'

    Returns:
        datetime for start of range, or None for 'all'
    """
    if time_range == "all":
        return None

    match = re.match(r"^(\d+)d$", time_range)
    if not match:
        return datetime.now(timezone.utc) - timedelta(days=30)  # Default

    days = int(match.group(1))
    return datetime.now(timezone.utc) - timedelta(days=days)


class AnalyticsPerformanceHandler(BaseHandler):
    """Handler for analytics performance endpoints.

    Provides aggregate performance metrics for agents and debates.
    Requires authentication and analytics:read permission (RBAC).
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/analytics/agents/performance",
        "/api/analytics/debates/summary",
        "/api/analytics/trends",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        return normalized in self.ROUTES

    @require_permission(PERM_ANALYTICS_PERFORMANCE)
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests to appropriate methods with RBAC."""
        normalized = strip_version_prefix(path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _analytics_performance_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for analytics performance: %s", client_ip)
            return error_response(
                "Rate limit exceeded. Please try again later.",
                429,
            )

        # RBAC inline check via rbac.checker if available
        if not RBAC_AVAILABLE:
            if rbac_fail_closed():
                return error_response("Service unavailable: access control module not loaded", 503)
        elif hasattr(handler, "auth_context"):
            decision = check_permission(handler.auth_context, PERM_ANALYTICS_PERFORMANCE)
            if not decision.allowed:
                logger.warning("RBAC denied analytics performance access: %s", decision.reason)
                return error_response(
                    "Permission denied",
                    403,
                    code="PERMISSION_DENIED",
                )

        # Route to appropriate handler
        if normalized == "/api/analytics/agents/performance":
            return self._get_agents_performance(query_params, handler)
        elif normalized == "/api/analytics/debates/summary":
            return self._get_debates_summary(query_params, handler)
        elif normalized == "/api/analytics/trends":
            return self._get_general_trends(query_params, handler)

        return None

    @api_endpoint(
        path="/api/v1/analytics/agents/performance",
        method="GET",
        summary="Get aggregate agent performance metrics",
        tags=["Analytics"],
        parameters=[
            query_param("time_range", "Time range filter (7d, 30d, 90d, 365d, all)", default="30d"),
            query_param("org_id", "Organization ID filter", required=False),
            query_param("limit", "Maximum agents to return", schema_type="integer", default=20),
        ],
        responses=ok_response(
            "Agent performance metrics",
            {
                "type": "object",
                "properties": {
                    "time_range": {"type": "string"},
                    "total_agents": {"type": "integer"},
                    "agents": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "agent_name": {"type": "string"},
                                "elo": {"type": "number"},
                                "win_rate": {"type": "number"},
                                "consensus_rate": {"type": "number"},
                                "avg_response_time_ms": {"type": "number"},
                                "total_debates": {"type": "integer"},
                            },
                        },
                    },
                    "summary": {
                        "type": "object",
                        "properties": {
                            "avg_elo": {"type": "number"},
                            "avg_win_rate": {"type": "number"},
                            "total_debates": {"type": "integer"},
                        },
                    },
                    "generated_at": {"type": "string", "format": "date-time"},
                },
            },
        ),
    )
    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_agents_performance")
    @handle_errors("get agents performance")
    def _get_agents_performance(
        self, query_params: dict[str, Any], handler: Any | None = None
    ) -> HandlerResult:
        """
        Get aggregate agent performance metrics.

        GET /api/v1/analytics/agents/performance

        Query params:
        - time_range: Time range filter (7d, 30d, 90d, 365d, all) - default 30d
        - org_id: Organization ID filter (optional)
        - limit: Maximum agents to return (default 20, max 100)

        Response:
        {
            "time_range": "30d",
            "total_agents": 15,
            "agents": [
                {
                    "agent_name": "claude",
                    "elo": 1650,
                    "win_rate": 75.0,
                    "consensus_rate": 88.5,
                    "avg_response_time_ms": 1250,
                    "total_debates": 160,
                    "wins": 120,
                    "losses": 30,
                    "draws": 10,
                    "rank": 1
                },
                ...
            ],
            "summary": {
                "avg_elo": 1520,
                "avg_win_rate": 52.5,
                "total_debates": 1250,
                "top_performer": "claude",
                "most_active": "gemini"
            },
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        time_range = query_params.get("time_range", "30d")
        if time_range not in VALID_TIME_RANGES:
            time_range = "30d"

        org_id = query_params.get("org_id")
        limit = safe_query_int(query_params, "limit", default=20, max_val=100)

        elo_system = self.get_elo_system()
        if not elo_system:
            return json_response(
                {
                    "time_range": time_range,
                    "org_id": org_id,
                    "total_agents": 0,
                    "agents": [],
                    "summary": {
                        "avg_elo": 1500,
                        "avg_win_rate": 0.0,
                        "total_debates": 0,
                    },
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        # Get leaderboard from ELO system
        agents = elo_system.get_leaderboard(limit=limit)

        # Calculate aggregate metrics
        agent_data = []
        total_elo = 0.0
        total_win_rate = 0.0
        total_debates = 0
        most_active_agent = None
        most_active_debates = 0

        for rank, agent in enumerate(agents, 1):
            debates_count = agent.games_played
            total_debates += debates_count

            if debates_count > most_active_debates:
                most_active_debates = debates_count
                most_active_agent = agent.agent_name

            total_elo += agent.elo
            total_win_rate += agent.win_rate * 100

            agent_info = {
                "agent_name": agent.agent_name,
                "elo": round(agent.elo, 0),
                "win_rate": round(agent.win_rate * 100, 1),
                "total_debates": debates_count,
                "wins": agent.wins,
                "losses": agent.losses,
                "draws": agent.draws,
                "rank": rank,
            }

            # Add consensus rate if available
            if hasattr(agent, "consensus_rate"):
                agent_info["consensus_rate"] = round(agent.consensus_rate * 100, 1)

            # Add response time if available
            if hasattr(agent, "avg_response_time_ms"):
                agent_info["avg_response_time_ms"] = round(agent.avg_response_time_ms, 0)

            # Add calibration score if available
            if hasattr(agent, "calibration_score"):
                agent_info["calibration_score"] = round(agent.calibration_score, 2)

            agent_data.append(agent_info)

        # Calculate averages
        num_agents = len(agents)
        avg_elo = total_elo / num_agents if num_agents > 0 else 1500
        avg_win_rate = total_win_rate / num_agents if num_agents > 0 else 0.0

        # Get top performer (first in leaderboard)
        top_performer = agents[0].agent_name if agents else None

        return json_response(
            {
                "time_range": time_range,
                "org_id": org_id,
                "total_agents": num_agents,
                "agents": agent_data,
                "summary": {
                    "avg_elo": round(avg_elo, 0),
                    "avg_win_rate": round(avg_win_rate, 1),
                    "total_debates": total_debates,
                    "top_performer": top_performer,
                    "most_active": most_active_agent,
                },
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    @api_endpoint(
        path="/api/v1/analytics/debates/summary",
        method="GET",
        summary="Get debate summary statistics",
        tags=["Analytics"],
        parameters=[
            query_param("time_range", "Time range filter (7d, 30d, 90d, 365d, all)", default="30d"),
            query_param("org_id", "Organization ID filter", required=False),
        ],
        responses=ok_response(
            "Debate summary statistics",
            {
                "type": "object",
                "properties": {
                    "time_range": {"type": "string"},
                    "total_debates": {"type": "integer"},
                    "consensus_reached": {"type": "integer"},
                    "consensus_rate": {"type": "number"},
                    "avg_rounds": {"type": "number"},
                    "avg_agents": {"type": "number"},
                    "by_outcome": {"type": "object"},
                    "by_domain": {"type": "object"},
                    "generated_at": {"type": "string", "format": "date-time"},
                },
            },
        ),
    )
    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_debates_summary")
    @handle_errors("get debates summary")
    def _get_debates_summary(
        self, query_params: dict[str, Any], handler: Any | None = None
    ) -> HandlerResult:
        """
        Get debate summary statistics.

        GET /api/v1/analytics/debates/summary

        Query params:
        - time_range: Time range filter (7d, 30d, 90d, 365d, all) - default 30d
        - org_id: Organization ID filter (optional)

        Response:
        {
            "time_range": "30d",
            "total_debates": 1250,
            "consensus_reached": 1100,
            "consensus_rate": 88.0,
            "avg_rounds": 3.2,
            "avg_agents": 3.5,
            "avg_confidence": 0.85,
            "avg_duration_seconds": 45.2,
            "by_outcome": {
                "consensus": 1100,
                "majority": 100,
                "dissent": 30,
                "no_resolution": 20
            },
            "by_domain": {
                "security": {"count": 350, "consensus_rate": 92.5},
                "performance": {"count": 280, "consensus_rate": 85.0}
            },
            "peak_hours": [14, 15, 16],
            "peak_days": ["Monday", "Wednesday"],
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        time_range = query_params.get("time_range", "30d")
        if time_range not in VALID_TIME_RANGES:
            time_range = "30d"

        org_id = query_params.get("org_id")

        storage = self.get_storage()
        if not storage:
            return json_response(
                {
                    "time_range": time_range,
                    "total_debates": 0,
                    "consensus_reached": 0,
                    "consensus_rate": 0.0,
                    "avg_rounds": 0.0,
                    "avg_agents": 0.0,
                    "avg_confidence": 0.0,
                    "by_outcome": {},
                    "by_domain": {},
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        # Get debates from storage
        debates = storage.list_debates(limit=10000, org_id=org_id)

        # Parse time range
        start_time = _parse_time_range(time_range)

        # Filter and aggregate debates
        total_debates = 0
        consensus_count = 0
        total_rounds = 0
        total_agents = 0
        total_confidence = 0.0
        confidence_count = 0
        total_duration = 0.0
        duration_count = 0

        by_outcome: dict[str, int] = defaultdict(int)
        by_domain: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "consensus_count": 0}
        )
        by_hour: Counter[int] = Counter()
        by_day: Counter[str] = Counter()

        for debate in debates:
            debate_dict = debate if isinstance(debate, dict) else vars(debate)
            created_at_str = debate_dict.get("created_at", "")

            # Parse and filter by time range
            if start_time:
                try:
                    if isinstance(created_at_str, datetime):
                        created_at = created_at_str
                    else:
                        created_at = datetime.fromisoformat(
                            str(created_at_str).replace("Z", "+00:00")
                        )

                    if created_at < start_time:
                        continue

                    # Track peak hours and days
                    by_hour[created_at.hour] += 1
                    by_day[created_at.strftime("%A")] += 1
                except (ValueError, TypeError):
                    continue

            total_debates += 1

            # Consensus tracking
            consensus_reached = debate_dict.get("consensus_reached", False)
            if consensus_reached:
                consensus_count += 1

            # Get result data
            result = debate_dict.get("result", {})
            if isinstance(result, dict):
                # Rounds
                rounds: Any = result.get("rounds_used", result.get("rounds", 0))
                total_rounds += rounds

                # Confidence
                confidence = result.get("confidence", 0.0)
                if confidence > 0:
                    total_confidence += confidence
                    confidence_count += 1

                # Duration
                duration = result.get("duration_seconds", 0)
                if duration > 0:
                    total_duration += duration
                    duration_count += 1

                # Outcome type
                outcome_type = result.get("outcome_type", "")
                if outcome_type:
                    by_outcome[outcome_type] += 1
                elif consensus_reached:
                    if confidence >= 0.8:
                        by_outcome["consensus"] += 1
                    else:
                        by_outcome["majority"] += 1
                else:
                    by_outcome["no_resolution"] += 1

                # Domain
                domain = result.get("domain", debate_dict.get("domain", "general"))
                if domain:
                    by_domain[domain]["count"] += 1
                    if consensus_reached:
                        by_domain[domain]["consensus_count"] += 1

            # Count agents
            agents = debate_dict.get("agents", [])
            if isinstance(agents, list):
                total_agents += len(agents)

        # Calculate averages
        consensus_rate = (consensus_count / total_debates * 100) if total_debates > 0 else 0.0
        avg_rounds = total_rounds / total_debates if total_debates > 0 else 0.0
        avg_agents = total_agents / total_debates if total_debates > 0 else 0.0
        avg_confidence = total_confidence / confidence_count if confidence_count > 0 else 0.0
        avg_duration = total_duration / duration_count if duration_count > 0 else 0.0

        # Calculate domain consensus rates
        domain_stats = {}
        for domain, stats in by_domain.items():
            count = stats["count"]
            consensus_domain = stats["consensus_count"]
            domain_rate = (consensus_domain / count * 100) if count > 0 else 0.0
            domain_stats[domain] = {
                "count": count,
                "consensus_rate": round(domain_rate, 1),
            }

        # Get peak hours and days
        peak_hours = [h for h, _ in by_hour.most_common(3)]
        peak_days = [d for d, _ in by_day.most_common(3)]

        return json_response(
            {
                "time_range": time_range,
                "org_id": org_id,
                "total_debates": total_debates,
                "consensus_reached": consensus_count,
                "consensus_rate": round(consensus_rate, 1),
                "avg_rounds": round(avg_rounds, 1),
                "avg_agents": round(avg_agents, 1),
                "avg_confidence": round(avg_confidence, 2),
                "avg_duration_seconds": round(avg_duration, 1),
                "by_outcome": dict(by_outcome),
                "by_domain": domain_stats,
                "peak_hours": peak_hours,
                "peak_days": peak_days,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    @api_endpoint(
        path="/api/v1/analytics/trends",
        method="GET",
        summary="Get general trend analysis",
        tags=["Analytics"],
        parameters=[
            query_param("time_range", "Time range filter (7d, 30d, 90d, 365d)", default="30d"),
            query_param(
                "granularity",
                "Time bucket granularity",
                enum=["daily", "weekly", "monthly"],
                default="daily",
            ),
            query_param("metrics", "Comma-separated metrics to include", required=False),
            query_param("org_id", "Organization ID filter", required=False),
        ],
        responses=ok_response(
            "Trend analysis data",
            {
                "type": "object",
                "properties": {
                    "time_range": {"type": "string"},
                    "granularity": {"type": "string"},
                    "data_points": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "period": {"type": "string"},
                                "debates_count": {"type": "integer"},
                                "consensus_rate": {"type": "number"},
                                "avg_confidence": {"type": "number"},
                                "active_agents": {"type": "integer"},
                            },
                        },
                    },
                    "trend_analysis": {
                        "type": "object",
                        "properties": {
                            "debates_trend": {"type": "string"},
                            "consensus_trend": {"type": "string"},
                            "growth_rate": {"type": "number"},
                        },
                    },
                    "generated_at": {"type": "string", "format": "date-time"},
                },
            },
        ),
    )
    @ttl_cache(ttl_seconds=CACHE_TTL_ANALYTICS, key_prefix="analytics_general_trends")
    @handle_errors("get general trends")
    def _get_general_trends(
        self, query_params: dict[str, Any], handler: Any | None = None
    ) -> HandlerResult:
        """
        Get general trend analysis.

        GET /api/v1/analytics/trends

        Query params:
        - time_range: Time range filter (7d, 30d, 90d, 365d) - default 30d
        - granularity: Time bucket granularity (daily, weekly, monthly) - default daily
        - metrics: Comma-separated metrics to include (debates, consensus, agents, tokens)
        - org_id: Organization ID filter (optional)

        Response:
        {
            "time_range": "30d",
            "granularity": "daily",
            "data_points": [
                {
                    "period": "2026-01-01",
                    "debates_count": 45,
                    "consensus_rate": 88.5,
                    "avg_confidence": 0.85,
                    "active_agents": 12,
                    "total_tokens": 150000
                },
                ...
            ],
            "trend_analysis": {
                "debates_trend": "increasing",
                "consensus_trend": "stable",
                "debates_growth_rate": 15.5,
                "consensus_change": -2.1
            },
            "generated_at": "2026-01-23T12:00:00Z"
        }
        """
        time_range = query_params.get("time_range", "30d")
        if time_range not in VALID_TIME_RANGES:
            time_range = "30d"

        granularity = query_params.get("granularity", "daily")
        if granularity not in VALID_GRANULARITIES:
            granularity = "daily"

        org_id = query_params.get("org_id")
        metrics_param = query_params.get("metrics", "debates,consensus,agents")
        requested_metrics = set(m.strip().lower() for m in metrics_param.split(","))

        storage = self.get_storage()
        if not storage:
            return json_response(
                {
                    "time_range": time_range,
                    "granularity": granularity,
                    "data_points": [],
                    "trend_analysis": {},
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        # Get debates from storage
        debates = storage.list_debates(limit=10000, org_id=org_id)

        # Parse time range
        start_time = _parse_time_range(time_range)

        # Group debates by period
        period_data: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "debates_count": 0,
                "consensus_count": 0,
                "total_confidence": 0.0,
                "confidence_count": 0,
                "agents": set(),
                "total_tokens": 0,
            }
        )

        for debate in debates:
            debate_dict = debate if isinstance(debate, dict) else vars(debate)
            created_at_str = debate_dict.get("created_at", "")

            # Parse timestamp
            try:
                if isinstance(created_at_str, datetime):
                    created_at = created_at_str
                else:
                    created_at = datetime.fromisoformat(str(created_at_str).replace("Z", "+00:00"))

                # Filter by time range
                if start_time and created_at < start_time:
                    continue

                # Generate period key
                if granularity == "daily":
                    period = created_at.strftime("%Y-%m-%d")
                elif granularity == "weekly":
                    period = created_at.strftime("%Y-W%W")
                else:
                    period = created_at.strftime("%Y-%m")

            except (ValueError, TypeError):
                continue

            # Aggregate data
            period_data[period]["debates_count"] += 1

            # Consensus
            if debate_dict.get("consensus_reached"):
                period_data[period]["consensus_count"] += 1

            # Confidence
            result = debate_dict.get("result", {})
            if isinstance(result, dict):
                confidence = result.get("confidence", 0.0)
                if confidence > 0:
                    period_data[period]["total_confidence"] += confidence
                    period_data[period]["confidence_count"] += 1

                # Tokens
                tokens = result.get("total_tokens", 0)
                period_data[period]["total_tokens"] += tokens

            # Track agents
            agents = debate_dict.get("agents", [])
            if isinstance(agents, list):
                for agent in agents:
                    agent_name = agent if isinstance(agent, str) else agent.get("name", "")
                    if agent_name:
                        period_data[period]["agents"].add(agent_name)

        # Build data points
        data_points = []
        sorted_periods = sorted(period_data.keys())

        for period in sorted_periods:
            pd = period_data[period]
            debates_count = pd["debates_count"]

            point: dict[str, Any] = {"period": period}

            if "debates" in requested_metrics:
                point["debates_count"] = debates_count

            if "consensus" in requested_metrics and debates_count > 0:
                consensus_rate = (pd["consensus_count"] / debates_count) * 100
                point["consensus_rate"] = round(consensus_rate, 1)

                if pd["confidence_count"] > 0:
                    avg_confidence = pd["total_confidence"] / pd["confidence_count"]
                    point["avg_confidence"] = round(avg_confidence, 2)

            if "agents" in requested_metrics:
                point["active_agents"] = len(pd["agents"])

            if "tokens" in requested_metrics:
                point["total_tokens"] = pd["total_tokens"]

            data_points.append(point)

        # Calculate trend analysis
        trend_analysis = self._calculate_trends(data_points)

        return json_response(
            {
                "time_range": time_range,
                "granularity": granularity,
                "org_id": org_id,
                "data_points": data_points,
                "trend_analysis": trend_analysis,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def _calculate_trends(self, data_points: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculate trend analysis from data points.

        Args:
            data_points: List of period data points

        Returns:
            Dict with trend analysis
        """
        if len(data_points) < 2:
            return {"debates_trend": "insufficient_data", "consensus_trend": "insufficient_data"}

        # Split into halves for comparison
        mid = len(data_points) // 2
        first_half = data_points[:mid]
        second_half = data_points[mid:]

        # Debates trend
        first_debates = sum(p.get("debates_count", 0) for p in first_half)
        second_debates = sum(p.get("debates_count", 0) for p in second_half)

        if first_debates > 0:
            debates_growth = ((second_debates - first_debates) / first_debates) * 100
        else:
            debates_growth = 100.0 if second_debates > 0 else 0.0

        if debates_growth > 10:
            debates_trend = "increasing"
        elif debates_growth < -10:
            debates_trend = "decreasing"
        else:
            debates_trend = "stable"

        # Consensus trend
        first_consensus = [p.get("consensus_rate", 0) for p in first_half if "consensus_rate" in p]
        second_consensus = [
            p.get("consensus_rate", 0) for p in second_half if "consensus_rate" in p
        ]

        first_avg_consensus = sum(first_consensus) / len(first_consensus) if first_consensus else 0
        second_avg_consensus = (
            sum(second_consensus) / len(second_consensus) if second_consensus else 0
        )
        consensus_change = second_avg_consensus - first_avg_consensus

        if consensus_change > 5:
            consensus_trend = "improving"
        elif consensus_change < -5:
            consensus_trend = "declining"
        else:
            consensus_trend = "stable"

        return {
            "debates_trend": debates_trend,
            "consensus_trend": consensus_trend,
            "debates_growth_rate": round(debates_growth, 1),
            "consensus_change": round(consensus_change, 1),
        }


__all__ = ["AnalyticsPerformanceHandler"]
