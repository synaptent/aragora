"""
Critique pattern and reputation endpoint handlers.

Endpoints:
- GET /api/critiques/patterns - Get high-impact critique patterns
- GET /api/critiques/archive - Get archive statistics
- GET /api/reputation/all - Get all agent reputations
- GET /api/agent/:name/reputation - Get specific agent reputation
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from aragora.server.validation import validate_agent_name_with_version
from aragora.server.versioning.compat import strip_version_prefix
from aragora.stores.canonical import get_critique_store, is_critique_store_available

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_bounded_float_param,
    get_clamped_int_param,
    json_response,
)
from aragora.rbac.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for critique endpoints (60 requests per minute - read-heavy)
_critique_limiter = RateLimiter(requests_per_minute=60)

# Check if CritiqueStore is available
CRITIQUE_STORE_AVAILABLE = is_critique_store_available()

from aragora.server.errors import safe_error_message as _safe_error_message


class CritiqueHandler(BaseHandler):
    """Handler for critique pattern and reputation endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/critiques/patterns",
        "/api/critiques/archive",
        "/api/reputation/all",
        "/api/reputation/history",
        "/api/reputation/domain",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        path = strip_version_prefix(path)
        if path in self.ROUTES:
            return True
        # Dynamic route for agent reputation
        if path.startswith("/api/agent/") and path.endswith("/reputation"):
            return True
        return False

    @require_permission("critiques:read")
    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route critique requests to appropriate methods."""
        path = strip_version_prefix(path)
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _critique_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for critique endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        nomic_dir = self.ctx.get("nomic_dir")

        if path == "/api/critiques/patterns":
            limit = get_clamped_int_param(query_params, "limit", 10, min_val=1, max_val=50)
            min_success = get_bounded_float_param(
                query_params, "min_success", 0.5, min_val=0.0, max_val=1.0
            )
            return self._get_critique_patterns(nomic_dir, limit, min_success)

        if path == "/api/critiques/archive":
            return self._get_archive_stats(nomic_dir)

        if path == "/api/reputation/all":
            return self._get_all_reputations(nomic_dir)

        if path == "/api/reputation/history":
            limit = get_clamped_int_param(query_params, "limit", 100, min_val=1, max_val=1000)
            agent = self._get_query_string(query_params, "agent")
            start_date = self._get_query_string(query_params, "start_date")
            end_date = self._get_query_string(query_params, "end_date")
            return self._get_reputation_history(nomic_dir, limit, agent, start_date, end_date)

        if path == "/api/reputation/domain":
            domain = self._get_query_string(query_params, "domain")
            if not domain:
                return error_response("Missing required query parameter: domain", 400)
            limit = get_clamped_int_param(query_params, "limit", 100, min_val=1, max_val=1000)
            return self._get_reputation_by_domain(nomic_dir, domain, limit)

        if path.startswith("/api/agent/") and path.endswith("/reputation"):
            agent_name = self._extract_agent_name(path)
            if agent_name is None:
                return error_response("Invalid agent name", 400)
            return self._get_agent_reputation(nomic_dir, agent_name)

        return None

    def _extract_agent_name(self, path: str) -> str | None:
        """Extract and validate agent name from path."""
        # Pattern: /api/agent/{name}/reputation
        # Parts: ["", "api", "agent", "{name}", "reputation"]
        # Block path traversal attempts
        if ".." in path:
            return None
        parts = path.split("/")
        if len(parts) >= 5:
            agent = parts[3]
            is_valid, _ = validate_agent_name_with_version(agent)
            if is_valid:
                return agent
        return None

    @staticmethod
    def _get_query_string(query_params: dict[str, Any], key: str) -> str:
        """Extract query param as a single trimmed string."""
        value = query_params.get(key)
        if isinstance(value, list):
            value = value[0] if value else ""
        if value is None:
            return ""
        return str(value).strip()

    @staticmethod
    def _parse_iso8601(value: str) -> datetime | None:
        """Parse ISO date/datetime input, accepting trailing 'Z'."""
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _agent_matches_domain(agent_name: str, domain: str) -> bool:
        """Heuristic domain matcher for agent names."""
        domain_norm = domain.strip().lower()
        if not domain_norm:
            return False
        tokens = [t for t in re.split(r"[^a-z0-9]+", agent_name.lower()) if t]
        return domain_norm in tokens

    def _get_critique_patterns(
        self, nomic_dir: Path | None, limit: int, min_success: float
    ) -> HandlerResult:
        """Get high-impact critique patterns for learning."""
        if not CRITIQUE_STORE_AVAILABLE:
            return error_response("Critique store not available", 503)

        try:
            store = get_critique_store(nomic_dir)
            if store is None:
                return json_response({"patterns": [], "count": 0})

            patterns = store.retrieve_patterns(min_success_rate=min_success, limit=limit)
            stats = store.get_stats()

            return json_response(
                {
                    "patterns": [
                        {
                            "issue_type": p.issue_type,
                            "pattern": p.pattern_text,
                            "success_rate": p.success_rate,
                            "usage_count": p.usage_count,
                        }
                        for p in patterns
                    ],
                    "count": len(patterns),
                    "stats": stats,
                }
            )
        except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
            return error_response(_safe_error_message(e, "critique_patterns"), 500)

    def _get_archive_stats(self, nomic_dir: Path | None) -> HandlerResult:
        """Get archive statistics from critique store."""
        if not CRITIQUE_STORE_AVAILABLE:
            return error_response("Critique store not available", 503)

        try:
            store = get_critique_store(nomic_dir)
            if store is None:
                return json_response({"archived": 0, "by_type": {}})

            stats = store.get_archive_stats()
            return json_response(stats)
        except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
            return error_response(_safe_error_message(e, "archive_stats"), 500)

    def _get_all_reputations(self, nomic_dir: Path | None) -> HandlerResult:
        """Get all agent reputations ranked by score."""
        if not CRITIQUE_STORE_AVAILABLE:
            return error_response("Critique store not available", 503)

        try:
            store = get_critique_store(nomic_dir)
            if store is None:
                return json_response({"reputations": [], "count": 0})

            reputations = store.get_all_reputations()
            return json_response(
                {
                    "reputations": [
                        {
                            "agent": r.agent_name,
                            "score": r.reputation_score,
                            "vote_weight": r.vote_weight,
                            "proposal_acceptance_rate": r.proposal_acceptance_rate,
                            "critique_value": r.critique_value,
                            "debates_participated": r.debates_participated,
                        }
                        for r in reputations
                    ],
                    "count": len(reputations),
                }
            )
        except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
            return error_response(_safe_error_message(e, "reputations"), 500)

    def _get_agent_reputation(self, nomic_dir: Path | None, agent: str) -> HandlerResult:
        """Get reputation for a specific agent."""
        if not CRITIQUE_STORE_AVAILABLE:
            return error_response("Critique store not available", 503)

        try:
            store = get_critique_store(nomic_dir)
            if store is None:
                return json_response(
                    {"agent": agent, "reputation": None, "message": "No reputation data available"}
                )

            rep = store.get_reputation(agent)

            if rep:
                return json_response(
                    {
                        "agent": agent,
                        "reputation": {
                            "score": rep.reputation_score,
                            "vote_weight": rep.vote_weight,
                            "proposal_acceptance_rate": rep.proposal_acceptance_rate,
                            "critique_value": rep.critique_value,
                            "debates_participated": rep.debates_participated,
                        },
                    }
                )
            else:
                return json_response(
                    {"agent": agent, "reputation": None, "message": "Agent not found"}
                )
        except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
            return error_response(_safe_error_message(e, "agent_reputation"), 500)

    def _get_reputation_history(
        self,
        nomic_dir: Path | None,
        limit: int,
        agent: str,
        start_date: str,
        end_date: str,
    ) -> HandlerResult:
        """Return reputation timeline snapshots derived from stored reputation rows."""
        if not CRITIQUE_STORE_AVAILABLE:
            return error_response("Critique store not available", 503)

        start_dt = self._parse_iso8601(start_date) if start_date else None
        end_dt = self._parse_iso8601(end_date) if end_date else None
        if start_date and start_dt is None:
            return error_response("Invalid start_date (expected ISO-8601)", 400)
        if end_date and end_dt is None:
            return error_response("Invalid end_date (expected ISO-8601)", 400)

        try:
            store = get_critique_store(nomic_dir)
            if store is None:
                return json_response({"history": [], "count": 0})

            # Fetch extra rows so post-filters still have enough data.
            reputations = store.get_all_reputations(limit=max(limit * 2, 200))
            history: list[dict[str, Any]] = []
            for rep in reputations:
                if agent and rep.agent_name != agent:
                    continue
                updated_at = rep.updated_at
                updated_dt = self._parse_iso8601(updated_at) if updated_at else None
                if start_dt and updated_dt and updated_dt < start_dt:
                    continue
                if end_dt and updated_dt and updated_dt > end_dt:
                    continue
                history.append(
                    {
                        "timestamp": updated_at,
                        "agent": rep.agent_name,
                        "reputation": rep.reputation_score,
                        "event": "snapshot",
                    }
                )
                if len(history) >= limit:
                    break

            return json_response({"history": history, "count": len(history)})
        except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
            return error_response(_safe_error_message(e, "reputation_history"), 500)

    def _get_reputation_by_domain(
        self,
        nomic_dir: Path | None,
        domain: str,
        limit: int,
    ) -> HandlerResult:
        """Return reputations for agents matching a requested domain token."""
        if not CRITIQUE_STORE_AVAILABLE:
            return error_response("Critique store not available", 503)

        try:
            store = get_critique_store(nomic_dir)
            if store is None:
                return json_response({"domain": domain, "reputations": [], "count": 0})

            reputations = store.get_all_reputations(limit=max(limit * 3, 300))
            filtered = [
                {
                    "agent": rep.agent_name,
                    "score": rep.reputation_score,
                    "vote_weight": rep.vote_weight,
                    "proposal_acceptance_rate": rep.proposal_acceptance_rate,
                    "critique_value": rep.critique_value,
                    "debates_participated": rep.debates_participated,
                }
                for rep in reputations
                if self._agent_matches_domain(rep.agent_name, domain)
            ][:limit]

            return json_response(
                {"domain": domain, "reputations": filtered, "count": len(filtered)}
            )
        except (KeyError, ValueError, OSError, TypeError, AttributeError) as e:
            return error_response(_safe_error_message(e, "reputation_domain"), 500)
