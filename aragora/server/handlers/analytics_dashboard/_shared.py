"""Shared imports, constants, and utilities for analytics dashboard handlers."""

from __future__ import annotations

import logging
from typing import Any, TypeVar
from collections.abc import Coroutine

from aragora.api_errors import safe_error_message
from aragora.server.handlers.analytics.cache import cached_analytics, cached_analytics_org
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_clamped_int_param,
    get_string_param,
    handle_errors,
    json_response,
    rate_limit,
    require_permission,
    require_user_auth,
)
from aragora.server.http_utils import run_async
from aragora.server.versioning.compat import strip_version_prefix


# RBAC Permission constants
PERM_ANALYTICS_READ = "analytics:dashboard:read"
PERM_ANALYTICS_WRITE = "analytics:dashboard:write"
PERM_ANALYTICS_EXPORT = "analytics:export"
PERM_ANALYTICS_ADMIN = "analytics:admin"
PERM_ANALYTICS_COST = "analytics:cost:read"
PERM_ANALYTICS_COMPLIANCE = "analytics:compliance:read"
PERM_ANALYTICS_TOKENS = "analytics:tokens:read"
PERM_ANALYTICS_FLIPS = "analytics:flips:read"
PERM_ANALYTICS_DELIBERATIONS = "analytics:deliberations:read"

# RBAC imports (optional - graceful degradation in dev, fail-closed in production)
from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

try:
    from aragora.rbac import (
        AuthorizationContext,
        check_permission,
        PermissionDeniedError,
    )
    from aragora.billing.auth import extract_user_from_request

    RBAC_AVAILABLE = True
except ImportError:
    # SECURITY: In production, rbac_fail_closed() returns True and handlers
    # using RBAC_AVAILABLE must deny access rather than skip checks.
    RBAC_AVAILABLE = False
    AuthorizationContext = None  # type: ignore[misc]
    check_permission = None  # type: ignore[misc]
    PermissionDeniedError = Exception  # type: ignore[misc, assignment]
    extract_user_from_request = None

# Metrics imports (optional)
try:
    from aragora.observability.metrics import record_rbac_check

    METRICS_AVAILABLE = True
except ImportError:
    METRICS_AVAILABLE = False

    def record_rbac_check(*args, **kwargs):
        pass


logger = logging.getLogger(__name__)

T = TypeVar("T")


def _run_async(coro: Coroutine[Any, Any, T]) -> T:
    """Run async coroutine in sync context."""
    return run_async(coro)


def _build_analytics_stub_responses() -> dict[str, dict]:
    """Build demo-quality fallback responses for unauthenticated analytics.

    Returns realistic sample data so the dashboard looks populated
    even without auth context or workspace ID.  Each response includes
    ``"demo": True`` so the frontend can distinguish sample data from
    real database results.
    """
    return {
        "/api/analytics/summary": {
            "demo": True,
            "summary": {
                "total_debates": 47,
                "total_messages": 312,
                "consensus_rate": 72.3,
                "avg_debate_duration_ms": 45200,
                "active_users_24h": 3,
                "top_topics": [
                    {"topic": "API rate limiting strategy", "count": 8},
                    {"topic": "Database migration approach", "count": 6},
                    {"topic": "Authentication architecture", "count": 5},
                    {"topic": "Cost optimization", "count": 4},
                ],
            },
        },
        "/api/analytics/trends/findings": {
            "demo": True,
            "trends": [
                {"date": "2026-02-16", "findings": 3, "resolved": 2},
                {"date": "2026-02-17", "findings": 5, "resolved": 4},
                {"date": "2026-02-18", "findings": 2, "resolved": 3},
                {"date": "2026-02-19", "findings": 7, "resolved": 5},
                {"date": "2026-02-20", "findings": 4, "resolved": 4},
            ],
        },
        "/api/analytics/remediation": {
            "demo": True,
            "metrics": {
                "total_findings": 21,
                "remediated": 18,
                "pending": 3,
                "avg_remediation_time_hours": 2.4,
                "remediation_rate": 85.7,
            },
        },
        "/api/analytics/agents": {
            "demo": True,
            "agents": [
                {
                    "agent_id": "claude-opus",
                    "name": "Claude Opus",
                    "debates": 42,
                    "win_rate": 0.78,
                    "elo": 1847,
                },
                {
                    "agent_id": "gpt-4o",
                    "name": "GPT-4o",
                    "debates": 38,
                    "win_rate": 0.71,
                    "elo": 1792,
                },
                {
                    "agent_id": "gemini-pro",
                    "name": "Gemini Pro",
                    "debates": 35,
                    "win_rate": 0.65,
                    "elo": 1734,
                },
                {
                    "agent_id": "claude-sonnet",
                    "name": "Claude Sonnet",
                    "debates": 40,
                    "win_rate": 0.62,
                    "elo": 1715,
                },
                {
                    "agent_id": "mistral-large",
                    "name": "Mistral Large",
                    "debates": 28,
                    "win_rate": 0.58,
                    "elo": 1688,
                },
            ],
        },
        "/api/analytics/cost": {
            "demo": True,
            "analysis": {
                "total_cost_usd": 12.47,
                "cost_by_model": {
                    "claude-opus-4": 5.82,
                    "gpt-4o": 3.91,
                    "claude-opus-4-8": 1.64,
                    "gemini-1.5-pro": 0.78,
                    "mistral-large": 0.32,
                },
                "cost_by_debate_type": {"structured": 8.12, "freeform": 3.05, "tournament": 1.30},
                "projected_monthly_cost": 18.70,
                "cost_trend": [
                    {"date": "2026-02-16", "cost_usd": 2.10},
                    {"date": "2026-02-17", "cost_usd": 2.85},
                    {"date": "2026-02-18", "cost_usd": 1.92},
                    {"date": "2026-02-19", "cost_usd": 3.14},
                    {"date": "2026-02-20", "cost_usd": 2.46},
                ],
            },
        },
        "/api/analytics/cost/breakdown": {
            "demo": True,
            "breakdown": {
                "total_spend_usd": 12.47,
                "agents": [
                    {"agent": "claude-opus", "spend_usd": 5.82, "debates": 42},
                    {"agent": "gpt-4o", "spend_usd": 3.91, "debates": 38},
                    {"agent": "claude-sonnet", "spend_usd": 1.64, "debates": 40},
                    {"agent": "gemini-pro", "spend_usd": 0.78, "debates": 35},
                    {"agent": "mistral-large", "spend_usd": 0.32, "debates": 28},
                ],
                "budget_utilization_pct": 62.4,
            },
        },
        "/api/analytics/compliance": {
            "demo": True,
            "compliance": {
                "overall_score": 94,
                "categories": [
                    {"name": "Audit Trail", "score": 98, "status": "pass"},
                    {"name": "Data Retention", "score": 95, "status": "pass"},
                    {"name": "Access Control", "score": 92, "status": "pass"},
                    {"name": "Encryption", "score": 91, "status": "pass"},
                ],
                "last_audit": "2026-02-20T10:30:00Z",
            },
        },
        "/api/analytics/heatmap": {
            "demo": True,
            "heatmap": {
                "x_labels": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                "y_labels": ["9AM", "12PM", "3PM", "6PM"],
                "values": [
                    [3, 5, 2, 7, 4],
                    [6, 4, 8, 3, 5],
                    [2, 7, 5, 6, 3],
                    [4, 3, 6, 2, 1],
                ],
                "max_value": 8,
            },
        },
        "/api/analytics/tokens": {
            "demo": True,
            "summary": {
                "total_tokens_in": 284500,
                "total_tokens_out": 142300,
                "total_tokens": 426800,
                "avg_tokens_per_day": 85360,
            },
            "by_agent": {
                "claude-opus": 168200,
                "gpt-4o": 124600,
                "gemini-pro": 72400,
                "claude-sonnet": 38900,
                "mistral-large": 22700,
            },
            "by_model": {
                "claude-opus-4": 168200,
                "gpt-4o-2024-11": 124600,
                "gemini-1.5-pro": 72400,
                "claude-opus-4-8": 38900,
                "mistral-large-latest": 22700,
            },
        },
        "/api/analytics/tokens/trends": {
            "demo": True,
            "trends": [
                {"date": "2026-02-16", "tokens_in": 52100, "tokens_out": 26400},
                {"date": "2026-02-17", "tokens_in": 61800, "tokens_out": 30900},
                {"date": "2026-02-18", "tokens_in": 48300, "tokens_out": 24200},
                {"date": "2026-02-19", "tokens_in": 68900, "tokens_out": 34500},
                {"date": "2026-02-20", "tokens_in": 53400, "tokens_out": 26300},
            ],
        },
        "/api/analytics/tokens/providers": {
            "demo": True,
            "providers": [
                {"provider": "Anthropic", "tokens": 207100, "pct": 48.5},
                {"provider": "OpenAI", "tokens": 124600, "pct": 29.2},
                {"provider": "Google", "tokens": 72400, "pct": 17.0},
                {"provider": "Mistral", "tokens": 22700, "pct": 5.3},
            ],
        },
        "/api/analytics/flips/summary": {
            "demo": True,
            "summary": {"total": 14, "consistent": 11, "inconsistent": 3},
        },
        "/api/analytics/flips/recent": {
            "demo": True,
            "flips": [
                {
                    "agent": "gpt-4o",
                    "topic": "Rate limiting",
                    "from": "reject",
                    "to": "approve",
                    "date": "2026-02-19",
                },
                {
                    "agent": "gemini-pro",
                    "topic": "Auth flow",
                    "from": "approve",
                    "to": "defer",
                    "date": "2026-02-18",
                },
                {
                    "agent": "mistral-large",
                    "topic": "Cost model",
                    "from": "reject",
                    "to": "approve",
                    "date": "2026-02-17",
                },
            ],
        },
        "/api/analytics/flips/consistency": {
            "demo": True,
            "consistency": [
                {"agent": "claude-opus", "consistency_score": 0.94},
                {"agent": "gpt-4o", "consistency_score": 0.87},
                {"agent": "gemini-pro", "consistency_score": 0.82},
                {"agent": "claude-sonnet", "consistency_score": 0.90},
                {"agent": "mistral-large", "consistency_score": 0.85},
            ],
        },
        "/api/analytics/flips/trends": {
            "demo": True,
            "trends": [
                {"date": "2026-02-16", "flips": 2},
                {"date": "2026-02-17", "flips": 3},
                {"date": "2026-02-18", "flips": 4},
                {"date": "2026-02-19", "flips": 3},
                {"date": "2026-02-20", "flips": 2},
            ],
        },
        "/api/analytics/deliberations": {
            "demo": True,
            "summary": {"total": 47, "consensus_rate": 72.3},
        },
        "/api/analytics/deliberations/channels": {
            "demo": True,
            "channels": [
                {"channel": "web", "count": 28, "consensus_rate": 75.0},
                {"channel": "api", "count": 12, "consensus_rate": 66.7},
                {"channel": "cli", "count": 7, "consensus_rate": 71.4},
            ],
        },
        "/api/analytics/deliberations/consensus": {
            "demo": True,
            "consensus": [
                {"method": "majority", "count": 22, "avg_rounds": 2.8},
                {"method": "supermajority", "count": 15, "avg_rounds": 3.4},
                {"method": "unanimous", "count": 10, "avg_rounds": 4.1},
            ],
        },
        "/api/analytics/deliberations/performance": {
            "demo": True,
            "performance": [
                {"metric": "avg_duration_s", "value": 45.2},
                {"metric": "avg_rounds", "value": 3.1},
                {"metric": "avg_agents", "value": 4.2},
                {"metric": "convergence_rate", "value": 0.84},
            ],
        },
    }


# Demo fallback data (always available)
_DEMO_FALLBACK_RESPONSES = _build_analytics_stub_responses()


def get_analytics_response(path: str) -> dict:
    """Get analytics response for *path*, preferring live database data.

    Attempts a real database query first via :mod:`._live_queries`.
    If the query returns data, the result is returned as-is (no ``"demo"``
    key).  If the database is empty or the query fails for any reason, the
    hardcoded demo data is returned with ``"demo": True`` so the frontend
    knows it is sample data.

    Args:
        path: Normalised endpoint path (e.g. ``"/api/analytics/summary"``).

    Returns:
        A dict suitable for passing to ``json_response()``.
    """
    try:
        from ._live_queries import LIVE_QUERY_REGISTRY

        query_fn = LIVE_QUERY_REGISTRY.get(path)
        if query_fn is not None:
            result = query_fn()
            if result is not None:
                return result
    except Exception:  # noqa: BLE001 -- graceful fallback to demo data
        logger.debug("Live analytics query failed for %s, using demo fallback", path)

    # Fallback: return demo data with demo flag
    return _DEMO_FALLBACK_RESPONSES.get(path, {})


# Backwards-compatible alias -- existing code references ANALYTICS_STUB_RESPONSES
# to decide *which* paths get the fast-path treatment.
ANALYTICS_STUB_RESPONSES = _DEMO_FALLBACK_RESPONSES

__all__ = [
    "ANALYTICS_STUB_RESPONSES",
    "AuthorizationContext",
    "BaseHandler",
    "HandlerResult",
    "METRICS_AVAILABLE",
    "PERM_ANALYTICS_ADMIN",
    "PERM_ANALYTICS_COMPLIANCE",
    "PERM_ANALYTICS_COST",
    "PERM_ANALYTICS_DELIBERATIONS",
    "PERM_ANALYTICS_EXPORT",
    "PERM_ANALYTICS_FLIPS",
    "PERM_ANALYTICS_READ",
    "PERM_ANALYTICS_TOKENS",
    "PERM_ANALYTICS_WRITE",
    "PermissionDeniedError",
    "RBAC_AVAILABLE",
    "rbac_fail_closed",
    "_run_async",
    "cached_analytics",
    "cached_analytics_org",
    "check_permission",
    "error_response",
    "extract_user_from_request",
    "get_analytics_response",
    "get_clamped_int_param",
    "get_string_param",
    "handle_errors",
    "json_response",
    "logger",
    "rate_limit",
    "record_rbac_check",
    "require_permission",
    "require_user_auth",
    "safe_error_message",
    "strip_version_prefix",
]
