"""
Reviews Handler - Serve shareable code reviews.

Endpoints:
- GET /api/reviews/{id} - Get a specific review by ID
- GET /api/reviews - List recent reviews
"""

from __future__ import annotations

__all__ = [
    "ReviewsHandler",
    "REVIEWS_DIR",
]

import json
import logging
from pathlib import Path
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix

from ..base import BaseHandler, HandlerResult, error_response, json_response
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for reviews endpoints (30 requests per minute)
_reviews_limiter = RateLimiter(requests_per_minute=30)

# Reviews are stored at ~/.aragora/reviews/
REVIEWS_DIR = Path.home() / ".aragora" / "reviews"


class ReviewsHandler(BaseHandler):
    """Handler for serving shareable code reviews."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/reviews",
        "/api/reviews/*",
        "/api/v1/reviews",
        "/api/v1/reviews/*",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the request."""
        normalized = strip_version_prefix(path)
        return normalized.startswith("/api/reviews")

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle the request."""
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _reviews_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for reviews endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # Auth: skip for GET (public read-only dashboard data)
        method = getattr(handler, "command", "GET") if handler else "GET"
        if method != "GET":
            user, err = self.require_auth_or_error(handler)
            if err:
                return err
            _, perm_err = self.require_permission_or_error(handler, "reviews:write")
            if perm_err:
                return perm_err

        # Normalize and strip prefix
        normalized = strip_version_prefix(path)
        prefix = "/api/reviews"
        subpath = normalized[len(prefix) :] if normalized.startswith(prefix) else ""

        if not subpath or subpath == "/":
            # List recent reviews
            return self._list_reviews()
        elif subpath.startswith("/"):
            # Get specific review
            review_id = subpath[1:].split("/")[0]
            return self._get_review(review_id)

        return None

    def _list_reviews(self, limit: int = 20) -> HandlerResult:
        """List recent reviews."""
        if not REVIEWS_DIR.exists():
            return json_response({"reviews": [], "total": 0})

        reviews = []
        for review_file in sorted(
            REVIEWS_DIR.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )[:limit]:
            try:
                data = json.loads(review_file.read_text())
                # Return summary only
                reviews.append(
                    {
                        "id": data.get("id"),
                        "created_at": data.get("created_at"),
                        "agents": data.get("agents", []),
                        "pr_url": data.get("pr_url"),
                        "unanimous_count": len(
                            data.get("findings", {}).get("unanimous_critiques", [])
                        ),
                        "agreement_score": data.get("findings", {}).get("agreement_score", 0),
                    }
                )
            except (json.JSONDecodeError, KeyError):
                continue

        return json_response({"reviews": reviews, "total": len(reviews)})

    def _get_review(self, review_id: str) -> HandlerResult:
        """Get a specific review by ID."""
        # Validate ID: must be alphanumeric and reasonable length
        if not review_id or not review_id.isalnum() or len(review_id) > 64:
            return error_response("Invalid review ID", 400)

        review_path = REVIEWS_DIR / f"{review_id}.json"
        if not review_path.exists():
            return error_response("Review not found", 404)

        try:
            data = json.loads(review_path.read_text())
            return json_response({"review": data})
        except json.JSONDecodeError:
            return error_response("Invalid review data", 500)
