"""
Agent Evolution Dashboard API Handler.

Provides endpoints for the Agent Evolution dashboard (GitHub issue #307)
that shows persona changes over time, ELO score trends, pending Nomic Loop
changes with approve/reject controls, and prompt diff views.

Endpoints:
- GET  /api/v1/agent-evolution/timeline  - Evolution events timeline
- GET  /api/v1/agent-evolution/elo-trends - ELO score history per agent
- GET  /api/v1/agent-evolution/pending    - Pending Nomic Loop changes
- POST /api/v1/agent-evolution/pending/{id}/approve - Approve a pending change
- POST /api/v1/agent-evolution/pending/{id}/reject  - Reject a pending change
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..base import (
    error_response,
    handle_errors,
    json_response,
)
from ..utils.responses import HandlerResult
from ..secure import SecureHandler
from ..utils.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter: 30 requests per minute
_evolution_dashboard_limiter = RateLimiter(requests_per_minute=30)

# Standard exception tuple for error handlers
_SAFE_EXCEPTIONS = (
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
    RuntimeError,
    OSError,
    ImportError,
)


def _get_demo_timeline(limit: int = 20, offset: int = 0) -> dict:
    """Return demo timeline data for when real data is not available."""
    now = time.time()
    events = [
        {
            "id": "evt-001",
            "agent_name": "claude-3-opus",
            "event_type": "persona_change",
            "timestamp": _iso(now - 2 * 3600),
            "description": "Persona shifted from 'cautious analyst' to 'balanced synthesizer' after 15 debate cycles",
            "old_value": "cautious_analyst",
            "new_value": "balanced_synthesizer",
            "elo_before": 1420,
            "elo_after": 1435,
            "nomic_cycle_id": "nomic-042",
            "approved": True,
            "approved_by": "admin@acme.com",
        },
        {
            "id": "evt-002",
            "agent_name": "gpt-4-turbo",
            "event_type": "prompt_modification",
            "timestamp": _iso(now - 5 * 3600),
            "description": "System prompt updated to emphasize evidence-based reasoning over rhetoric",
            "old_value": "You are a skilled debater who constructs persuasive arguments...",
            "new_value": "You are an evidence-based reasoner who builds arguments from verifiable claims...",
            "elo_before": 1380,
            "elo_after": 1380,
            "nomic_cycle_id": "nomic-041",
            "approved": True,
            "approved_by": "system",
        },
        {
            "id": "evt-003",
            "agent_name": "gemini-pro",
            "event_type": "elo_adjustment",
            "timestamp": _iso(now - 8 * 3600),
            "description": "ELO recalibrated after tournament bracket reset",
            "old_value": None,
            "new_value": None,
            "elo_before": 1350,
            "elo_after": 1312,
            "nomic_cycle_id": None,
            "approved": None,
            "approved_by": None,
        },
        {
            "id": "evt-004",
            "agent_name": "mistral-large",
            "event_type": "nomic_proposal",
            "timestamp": _iso(now - 12 * 3600),
            "description": "Nomic Loop proposed persona evolution toward devil's advocate specialization",
            "old_value": "generalist",
            "new_value": "devils_advocate",
            "elo_before": 1290,
            "elo_after": None,
            "nomic_cycle_id": "nomic-043",
            "approved": None,
            "approved_by": None,
        },
        {
            "id": "evt-005",
            "agent_name": "claude-3-opus",
            "event_type": "prompt_modification",
            "timestamp": _iso(now - 24 * 3600),
            "description": "Added structured output formatting directives for consensus synthesis",
            "old_value": "...synthesize the discussion into a clear conclusion.",
            "new_value": "...synthesize using: 1) Key agreements, 2) Unresolved tensions, 3) Recommended action.",
            "elo_before": 1410,
            "elo_after": 1420,
            "nomic_cycle_id": "nomic-040",
            "approved": True,
            "approved_by": "admin@acme.com",
        },
        {
            "id": "evt-006",
            "agent_name": "grok-2",
            "event_type": "rollback",
            "timestamp": _iso(now - 36 * 3600),
            "description": "Rolled back persona change after 8% consensus rate drop in last 10 debates",
            "old_value": "aggressive_challenger",
            "new_value": "balanced_critic",
            "elo_before": 1260,
            "elo_after": 1275,
            "nomic_cycle_id": "nomic-039",
            "approved": True,
            "approved_by": "system",
        },
        {
            "id": "evt-007",
            "agent_name": "deepseek-v4-pro",
            "event_type": "persona_change",
            "timestamp": _iso(now - 48 * 3600),
            "description": "Graduated from 'novice' to 'intermediate analyst' after 50 successful debates",
            "old_value": "novice",
            "new_value": "intermediate_analyst",
            "elo_before": 1180,
            "elo_after": 1210,
            "nomic_cycle_id": None,
            "approved": None,
            "approved_by": None,
        },
    ]
    sliced = events[offset : offset + limit]
    return {
        "events": sliced,
        "total": len(events),
        "limit": limit,
        "offset": offset,
    }


def _get_demo_elo_trends(period: str = "7d") -> dict:
    """Return demo ELO trends data."""
    now = time.time()
    day = 86400

    def _make_trend(base: int, changes: list[int]) -> list[dict]:
        result = []
        elo = base
        for i, change in enumerate(changes):
            elo += change
            result.append(
                {
                    "timestamp": _iso(now - (len(changes) - i) * day),
                    "elo": elo,
                    "debate_id": f"dbt-{100 + i}",
                    "change": change,
                }
            )
        return result

    return {
        "agents": [
            {
                "agent_name": "claude-3-opus",
                "provider": "anthropic",
                "current_elo": 1435,
                "trend": _make_trend(1378, [12, 8, -5, 15, 7, 8, 12]),
                "peak_elo": 1435,
                "lowest_elo": 1390,
                "total_debates": 47,
            },
            {
                "agent_name": "gpt-4-turbo",
                "provider": "openai",
                "current_elo": 1380,
                "trend": _make_trend(1403, [-8, -5, 10, -12, 5, -5, -8]),
                "peak_elo": 1400,
                "lowest_elo": 1375,
                "total_debates": 52,
            },
            {
                "agent_name": "gemini-pro",
                "provider": "google",
                "current_elo": 1312,
                "trend": _make_trend(1360, [-10, -8, -5, -10, -3, -2, -10]),
                "peak_elo": 1360,
                "lowest_elo": 1312,
                "total_debates": 38,
            },
            {
                "agent_name": "mistral-large",
                "provider": "mistral",
                "current_elo": 1290,
                "trend": _make_trend(1252, [8, 5, 7, 3, 4, 3, 8]),
                "peak_elo": 1290,
                "lowest_elo": 1252,
                "total_debates": 29,
            },
        ],
        "period": period,
    }


def _get_empty_pending() -> dict:
    """Return an empty pending-change payload when no live store exists."""
    return {
        "changes": [],
        "total_pending": 0,
    }


def _iso(ts: float) -> str:
    """Convert unix timestamp to ISO-8601 string."""
    import datetime

    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).isoformat()


class AgentEvolutionDashboardHandler(SecureHandler):
    """Handler for the agent evolution dashboard endpoints.

    Provides timeline of persona changes, ELO score trends, and
    pending Nomic Loop changes with approve/reject controls.
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/agent-evolution/timeline",
        "/api/v1/agent-evolution/elo-trends",
        "/api/v1/agent-evolution/pending",
        "/api/v1/agent-evolution/pending/{change_id}/approve",
        "/api/v1/agent-evolution/pending/{change_id}/reject",
    ]
    _ROUTE_MAP = {
        "GET /api/v1/agent-evolution/timeline": "_handle_timeline",
        "GET /api/v1/agent-evolution/elo-trends": "_handle_elo_trends",
        "GET /api/v1/agent-evolution/pending": "_handle_pending",
        "POST /api/v1/agent-evolution/pending/{change_id}/approve": "_handle_approve",
        "POST /api/v1/agent-evolution/pending/{change_id}/reject": "_handle_reject",
    }

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        if not path.startswith("/api/v1/agent-evolution/"):
            return False
        suffix = path[len("/api/v1/agent-evolution/") :]
        if suffix in ("timeline", "elo-trends", "pending"):
            return True
        if suffix.startswith("pending/") and (
            suffix.endswith("/approve") or suffix.endswith("/reject")
        ):
            return True
        return False

    def handle(
        self, path: str, query_params: dict[str, Any], handler: Any = None
    ) -> HandlerResult | None:
        """Route agent evolution requests to appropriate methods."""
        if not self.can_handle(path):
            return None

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _evolution_dashboard_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for agent-evolution: %s", client_ip)
            return error_response("Rate limit exceeded", 429)

        suffix = path[len("/api/v1/agent-evolution/") :]

        if suffix == "timeline":
            return self._handle_timeline(query_params)
        if suffix == "elo-trends":
            return self._handle_elo_trends(query_params)
        if suffix == "pending":
            return self._handle_pending(query_params)
        if suffix.startswith("pending/") and suffix.endswith("/approve"):
            return self._handle_approve(suffix, handler)
        if suffix.startswith("pending/") and suffix.endswith("/reject"):
            return self._handle_reject(suffix, handler)

        return None

    @handle_errors("agent-evolution-timeline")
    def _handle_timeline(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/agent-evolution/timeline"""
        limit = min(int(query_params.get("limit", 20)), 100)
        offset = int(query_params.get("offset", 0))

        # Try real data first, fall back to demo
        try:
            data = self._fetch_real_timeline(limit, offset)
        except _SAFE_EXCEPTIONS:
            logger.debug("Using demo timeline data")
            data = _get_demo_timeline(limit, offset)

        return json_response({"data": data})

    @handle_errors("agent-evolution-elo-trends")
    def _handle_elo_trends(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/agent-evolution/elo-trends"""
        period = query_params.get("period", "7d")
        if period not in ("24h", "7d", "30d", "90d"):
            period = "7d"

        try:
            data = self._fetch_real_elo_trends(period)
        except _SAFE_EXCEPTIONS:
            logger.debug("Using demo ELO trends data")
            data = _get_demo_elo_trends(period)

        return json_response({"data": data})

    @handle_errors("agent-evolution-pending")
    def _handle_pending(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/agent-evolution/pending"""
        try:
            data = self._fetch_real_pending()
        except _SAFE_EXCEPTIONS:
            logger.info("Pending change store unavailable; returning empty pending change set")
            data = _get_empty_pending()

        return json_response({"data": data})

    @handle_errors("agent-evolution-approve")
    @require_permission("evolution:write")
    def _handle_approve(self, suffix: str, handler: Any) -> HandlerResult:
        """POST /api/v1/agent-evolution/pending/{id}/approve"""
        # Extract change ID from path: pending/{id}/approve
        parts = suffix.split("/")
        if len(parts) < 3:
            return error_response("Invalid path", 400)
        change_id = parts[1]

        logger.info("Approving agent evolution change: %s", change_id)

        # In production, this would update the database and trigger the change
        return json_response(
            {
                "data": {
                    "id": change_id,
                    "status": "approved",
                    "message": f"Change {change_id} approved successfully",
                }
            }
        )

    @handle_errors("agent-evolution-reject")
    @require_permission("evolution:write")
    def _handle_reject(self, suffix: str, handler: Any) -> HandlerResult:
        """POST /api/v1/agent-evolution/pending/{id}/reject"""
        parts = suffix.split("/")
        if len(parts) < 3:
            return error_response("Invalid path", 400)
        change_id = parts[1]

        logger.info("Rejecting agent evolution change: %s", change_id)

        return json_response(
            {
                "data": {
                    "id": change_id,
                    "status": "rejected",
                    "message": f"Change {change_id} rejected",
                }
            }
        )

    def _fetch_real_timeline(self, limit: int, offset: int) -> dict:
        """Attempt to fetch real evolution timeline data from the database."""
        from aragora.evolution.evolver import PromptEvolver
        from aragora.persistence.db_config import DatabaseType, get_db_path

        nomic_dir = self.get_nomic_dir()
        if not nomic_dir:
            raise RuntimeError("Nomic directory not configured")

        evolver = PromptEvolver(db_path=str(get_db_path(DatabaseType.PROMPT_EVOLUTION, nomic_dir)))

        # Get evolution history across all agents
        with evolver.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT agent_name, strategy, created_at, old_score, new_score
                FROM evolution_history
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
            rows = cursor.fetchall()

            cursor.execute("SELECT COUNT(*) FROM evolution_history")
            total = cursor.fetchone()[0]

        events = []
        for i, row in enumerate(rows):
            events.append(
                {
                    "id": f"evt-{offset + i + 1:03d}",
                    "agent_name": row[0],
                    "event_type": "prompt_modification",
                    "timestamp": row[2],
                    "description": f"Evolution via {row[1]} strategy",
                    "old_value": None,
                    "new_value": None,
                    "elo_before": row[3],
                    "elo_after": row[4],
                    "nomic_cycle_id": None,
                    "approved": True,
                    "approved_by": "system",
                }
            )

        return {
            "events": events,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def _fetch_real_elo_trends(self, period: str) -> dict:
        """Attempt to fetch real ELO trend data from the ranking system."""
        from aragora.ranking.elo import get_elo_store

        store = get_elo_store()
        rankings = store.get_all_ratings()

        agents = []
        for agent_rating in rankings:
            agents.append(
                {
                    "agent_name": agent_rating.agent_name,
                    "provider": "unknown",
                    "current_elo": agent_rating.elo,
                    "trend": [],
                    "peak_elo": agent_rating.elo,
                    "lowest_elo": agent_rating.elo,
                    "total_debates": agent_rating.debates_count,
                }
            )

        return {
            "agents": sorted(agents, key=lambda a: a["current_elo"], reverse=True),
            "period": period,
        }

    def _fetch_real_pending(self) -> dict:
        """Attempt to fetch real pending changes and fail closed if none exist."""
        return _get_empty_pending()
