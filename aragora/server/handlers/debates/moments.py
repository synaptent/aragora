"""
Moments endpoint handlers.

Endpoints:
- GET /api/moments/summary - Global moments overview
- GET /api/moments/timeline - Chronological moments (limit, offset)
- GET /api/moments/by-type/{type} - Filter moments by type
- GET /api/moments/trending - Most significant recent moments
"""

from __future__ import annotations

__all__ = [
    "MomentsHandler",
    "VALID_MOMENT_TYPES",
]

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from aragora.utils.optional_imports import try_import

from ..base import (
    HandlerResult,
    error_response,
    get_int_param,
    json_response,
)
from ..secure import SecureHandler
from ..utils.auth import ForbiddenError, UnauthorizedError
from ..utils.rate_limit import RateLimiter, get_client_ip
from aragora.server.versioning.compat import strip_version_prefix

logger = logging.getLogger(__name__)

# Rate limiter for moments endpoints (30 requests per minute - analytics queries)
_moments_limiter = RateLimiter(requests_per_minute=30)

# Valid moment types
VALID_MOMENT_TYPES = {
    "upset_victory",
    "position_reversal",
    "calibration_vindication",
    "alliance_shift",
    "consensus_breakthrough",
    "streak_achievement",
    "domain_mastery",
}

# Lazy imports for optional dependencies using centralized utility
_moment_imports, MOMENT_DETECTOR_AVAILABLE = try_import(
    "aragora.agents.grounded", "MomentDetector", "SignificantMoment"
)
MomentDetector = _moment_imports["MomentDetector"]
SignificantMoment = _moment_imports["SignificantMoment"]

from aragora.server.errors import safe_error_message as _safe_error_message


class MomentsHandler(SecureHandler):
    """Handler for moments endpoints with RBAC protection."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    RESOURCE_TYPE = "moments"

    ROUTES = [
        "/api/moments",
        "/api/moments/summary",
        "/api/moments/timeline",
        "/api/moments/trending",
        "/api/moments/recent",
        "/api/moments/by-type/*",
        "/api/v1/moments/by-type",
        "/api/v1/moments/recent",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        if normalized == "/api/moments":
            return True
        if normalized in self.ROUTES:
            return True
        # Handle dynamic route: /api/moments/by-type/{type}
        if normalized.startswith("/api/moments/by-type/"):
            return True
        if normalized == "/api/moments/recent":
            return True
        return False

    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route moments requests to appropriate methods."""
        # Auth: skip for GET (public read-only dashboard data)
        method = getattr(handler, "command", "GET") if handler else "GET"
        if method != "GET":
            try:
                auth_context = await self.get_auth_context(handler, require_auth=True)
                self.check_permission(auth_context, "moments:write")
            except UnauthorizedError:
                return error_response("Authentication required", 401)
            except ForbiddenError as e:
                logger.warning("Handler error: %s", e)
                return error_response("Permission denied", 403)

        # Normalize path to handle both /api/... and /api/v1/... paths
        normalized = strip_version_prefix(path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _moments_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for moments endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if normalized == "/api/moments":
            return self._get_summary()

        if normalized == "/api/moments/summary":
            return self._get_summary()

        if normalized == "/api/moments/timeline":
            limit = get_int_param(query_params, "limit", 50)
            offset = get_int_param(query_params, "offset", 0)
            return self._get_timeline(max(1, min(limit, 200)), max(0, offset))

        if normalized == "/api/moments/recent":
            limit = get_int_param(query_params, "limit", 20)
            return self._get_timeline(max(1, min(limit, 200)), 0)

        if normalized == "/api/moments/trending":
            limit = get_int_param(query_params, "limit", 10)
            return self._get_trending(max(1, min(limit, 50)))

        # Handle /api/moments/by-type/{type}
        if normalized.startswith("/api/moments/by-type/"):
            moment_type, err = self.extract_path_param(normalized, 4, "moment_type")
            if err:
                return err
            if moment_type not in VALID_MOMENT_TYPES:
                return error_response(
                    f"Invalid moment type: {moment_type}. Valid types: {', '.join(sorted(VALID_MOMENT_TYPES))}",
                    400,
                )
            limit = get_int_param(query_params, "limit", 50)
            return self._get_by_type(moment_type, max(1, min(limit, 200)))

        return None

    def _get_moment_detector(self) -> object | None:
        """Get moment detector from context or return None."""
        return self.ctx.get("moment_detector")

    def _get_all_moments(self) -> list[Any]:
        """Get all moments from all agents."""
        detector = self._get_moment_detector()
        if not detector:
            return []

        all_moments = []
        # Access the internal cache to get all moments
        if hasattr(detector, "_moment_cache"):
            for agent_name, moments in detector._moment_cache.items():
                all_moments.extend(moments)

        return all_moments

    def _moment_to_dict(self, moment: Any) -> dict[str, Any]:
        """Convert a SignificantMoment to a dict for JSON response."""
        return {
            "id": moment.id,
            "type": moment.moment_type,
            "agent": moment.agent_name,
            "description": moment.description,
            "significance": moment.significance_score,
            "debate_id": moment.debate_id,
            "other_agents": moment.other_agents or [],
            "metadata": moment.metadata or {},
            "created_at": moment.created_at if hasattr(moment, "created_at") else None,
        }

    def _get_summary(self) -> HandlerResult:
        """Get global moments summary."""
        if not MOMENT_DETECTOR_AVAILABLE:
            return json_response(
                {
                    "total_moments": 0,
                    "by_type": {},
                    "by_agent": {},
                    "most_significant": None,
                    "recent": [],
                    "message": "Moment detection not available",
                }
            )

        detector = self._get_moment_detector()
        if not detector:
            return json_response(
                {
                    "total_moments": 0,
                    "by_type": {},
                    "by_agent": {},
                    "most_significant": None,
                    "recent": [],
                    "message": "Moment detector not configured",
                }
            )

        try:
            all_moments = self._get_all_moments()

            # Count by type
            by_type: dict[str, int] = {}
            for moment in all_moments:
                mt = moment.moment_type
                by_type[mt] = by_type.get(mt, 0) + 1

            # Count by agent
            by_agent: dict[str, int] = {}
            for moment in all_moments:
                agent = moment.agent_name
                by_agent[agent] = by_agent.get(agent, 0) + 1

            # Most significant moment
            most_significant = None
            if all_moments:
                sorted_moments = sorted(
                    all_moments, key=lambda m: m.significance_score, reverse=True
                )
                most_significant = self._moment_to_dict(sorted_moments[0])

            # Recent moments (last 5)
            recent = sorted(
                all_moments, key=lambda m: getattr(m, "created_at", "") or "", reverse=True
            )[:5]

            return json_response(
                {
                    "total_moments": len(all_moments),
                    "by_type": by_type,
                    "by_agent": by_agent,
                    "most_significant": most_significant,
                    "recent": [self._moment_to_dict(m) for m in recent],
                }
            )
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning("Data error in moments summary: %s", e)
            return error_response(_safe_error_message(e, "moments summary"), 400)
        except (RuntimeError, ValueError, OSError) as e:
            logger.exception("Unexpected error getting moments summary: %s", e)
            return error_response(_safe_error_message(e, "moments summary"), 500)

    def _get_timeline(self, limit: int, offset: int) -> HandlerResult:
        """Get chronological moments timeline."""
        if not MOMENT_DETECTOR_AVAILABLE:
            return json_response(
                {
                    "moments": [],
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "has_more": False,
                    "message": "Moment detection not available",
                }
            )

        detector = self._get_moment_detector()
        if not detector:
            return json_response(
                {
                    "moments": [],
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "has_more": False,
                    "message": "Moment detector not configured",
                }
            )

        try:
            all_moments = self._get_all_moments()

            # Sort by created_at descending (most recent first)
            sorted_moments = sorted(
                all_moments, key=lambda m: getattr(m, "created_at", "") or "", reverse=True
            )

            # Apply pagination
            paginated = sorted_moments[offset : offset + limit]

            return json_response(
                {
                    "moments": [self._moment_to_dict(m) for m in paginated],
                    "total": len(all_moments),
                    "limit": limit,
                    "offset": offset,
                    "has_more": offset + limit < len(all_moments),
                }
            )
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning("Data error in moments timeline: %s", e)
            return error_response(_safe_error_message(e, "moments timeline"), 400)
        except (RuntimeError, ValueError, OSError) as e:
            logger.exception("Unexpected error getting moments timeline: %s", e)
            return error_response(_safe_error_message(e, "moments timeline"), 500)

    def _get_trending(self, limit: int) -> HandlerResult:
        """Get most significant recent moments."""
        if not MOMENT_DETECTOR_AVAILABLE:
            return json_response(
                {
                    "trending": [],
                    "count": 0,
                    "message": "Moment detection not available",
                }
            )

        detector = self._get_moment_detector()
        if not detector:
            return json_response(
                {
                    "trending": [],
                    "count": 0,
                    "message": "Moment detector not configured",
                }
            )

        try:
            all_moments = self._get_all_moments()

            # Sort by significance descending
            sorted_moments = sorted(all_moments, key=lambda m: m.significance_score, reverse=True)[
                :limit
            ]

            return json_response(
                {
                    "trending": [self._moment_to_dict(m) for m in sorted_moments],
                    "count": len(sorted_moments),
                }
            )
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning("Data error in moments trending: %s", e)
            return error_response(_safe_error_message(e, "moments trending"), 400)
        except (RuntimeError, ValueError, OSError) as e:
            logger.exception("Unexpected error getting moments trending: %s", e)
            return error_response(_safe_error_message(e, "moments trending"), 500)

    def _get_by_type(self, moment_type: str, limit: int) -> HandlerResult:
        """Get moments filtered by type."""
        if not MOMENT_DETECTOR_AVAILABLE:
            return json_response(
                {
                    "type": moment_type,
                    "moments": [],
                    "total": 0,
                    "limit": limit,
                    "message": "Moment detection not available",
                }
            )

        detector = self._get_moment_detector()
        if not detector:
            return json_response(
                {
                    "type": moment_type,
                    "moments": [],
                    "total": 0,
                    "limit": limit,
                    "message": "Moment detector not configured",
                }
            )

        try:
            all_moments = self._get_all_moments()

            # Filter by type
            filtered = [m for m in all_moments if m.moment_type == moment_type]

            # Sort by significance descending
            sorted_moments = sorted(filtered, key=lambda m: m.significance_score, reverse=True)[
                :limit
            ]

            return json_response(
                {
                    "type": moment_type,
                    "moments": [self._moment_to_dict(m) for m in sorted_moments],
                    "total": len(filtered),
                    "limit": limit,
                }
            )
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning("Data error in moments by type %s: %s", moment_type, e)
            return error_response(_safe_error_message(e, f"moments by type {moment_type}"), 400)
        except (RuntimeError, ValueError, OSError) as e:
            logger.exception("Unexpected error getting moments by type %s: %s", moment_type, e)
            return error_response(_safe_error_message(e, f"moments by type {moment_type}"), 500)
