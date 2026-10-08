"""
Marketplace Template Browsing API handler.

Exposes marketplace templates for browsing, featuring, and rating.

Endpoints:
- GET /api/v1/marketplace/templates — browse with category/search filtering
- GET /api/v1/marketplace/featured — curated top SME-relevant templates
- GET /api/v1/marketplace/popular — sorted by downloads
- POST /api/v1/marketplace/templates/{id}/rate — rate a template (auth required)
"""

from __future__ import annotations

__all__ = [
    "MarketplaceBrowseHandler",
]

import logging
from typing import Any

from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.rbac.decorators import require_permission
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter: 30 requests per minute per IP
_marketplace_limiter = RateLimiter(requests_per_minute=30)


def _get_marketplace_registry():
    """Get a marketplace registry instance (lazy import)."""
    from aragora.marketplace.registry import TemplateRegistry

    return TemplateRegistry()


class MarketplaceBrowseHandler(BaseHandler):
    """Handler for marketplace template browsing endpoints."""

    ROUTES: list[str] = [
        "/api/v1/marketplace/templates",
        "/api/v1/marketplace/templates/*",
        "/api/v1/marketplace/featured",
        "/api/v1/marketplace/popular",
    ]

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        self._registry = None

    def _get_registry(self):
        """Get or create the marketplace registry."""
        if self._registry is None:
            self._registry = _get_marketplace_registry()
        return self._registry

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        if normalized in (
            "/api/marketplace/templates",
            "/api/marketplace/featured",
            "/api/marketplace/popular",
        ):
            return True
        if normalized.startswith("/api/marketplace/templates/"):
            return True
        return False

    @require_permission("marketplace:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route marketplace browse requests."""
        normalized = strip_version_prefix(path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _marketplace_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Max 30 requests per minute.", 429)

        if normalized == "/api/marketplace/featured":
            return self._handle_featured()
        if normalized == "/api/marketplace/popular":
            return self._handle_popular(query_params)
        if normalized == "/api/marketplace/templates":
            return self._handle_browse(query_params)

        return None

    @handle_errors("marketplace browse creation")
    @require_permission("marketplace:write")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests (rating)."""
        normalized = strip_version_prefix(path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _marketplace_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Max 30 requests per minute.", 429)

        # POST /api/marketplace/templates/{id}/rate
        if normalized.startswith("/api/marketplace/templates/") and normalized.endswith("/rate"):
            parts = normalized.split("/")
            # ["", "api", "marketplace", "templates", "{id}", "rate"]
            if len(parts) >= 6:
                template_id = parts[4]
                return self._handle_rate(template_id, handler)

        return None

    def _handle_browse(self, query_params: dict[str, Any]) -> HandlerResult:
        """Browse marketplace templates with optional filtering."""
        registry = self._get_registry()

        query = query_params.get("search") or query_params.get("q")
        category_str = query_params.get("category")

        category = None
        if category_str:
            from aragora.marketplace.models import TemplateCategory

            try:
                category = TemplateCategory(category_str)
            except ValueError:
                pass

        templates = registry.search(
            query=query,
            category=category,
        )

        return json_response(
            {
                "templates": [t.to_dict() for t in templates],
                "count": len(templates),
            }
        )

    def _handle_featured(self) -> HandlerResult:
        """Return featured templates."""
        registry = self._get_registry()
        featured = registry.featured(limit=6)
        return json_response(
            {
                "featured": [t.to_dict() for t in featured],
                "count": len(featured),
            }
        )

    def _handle_popular(self, query_params: dict[str, Any]) -> HandlerResult:
        """Return popular templates sorted by downloads."""
        registry = self._get_registry()
        try:
            limit = min(int(query_params.get("limit", "10")), 50)
        except (ValueError, TypeError):
            limit = 10

        popular = registry.popular(limit=limit)
        return json_response(
            {
                "templates": [t.to_dict() for t in popular],
                "count": len(popular),
            }
        )

    def _handle_rate(self, template_id: str, handler: Any) -> HandlerResult:
        """Rate a marketplace template. Requires authentication."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        score = body.get("score")
        if not isinstance(score, int) or not (1 <= score <= 5):
            return error_response("Score must be an integer between 1 and 5", 400)

        review_text = body.get("review")
        if review_text is not None and not isinstance(review_text, str):
            return error_response("Review must be a string", 400)

        registry = self._get_registry()

        # Check template exists
        template = registry.get(template_id)
        if template is None:
            return error_response(f"Template '{template_id}' not found", 404)

        from aragora.marketplace.models import TemplateRating

        try:
            rating = TemplateRating(
                user_id=user.user_id,
                template_id=template_id,
                score=score,
                review=review_text,
            )
            registry.rate(rating)
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)

        return json_response({"status": "ok", "template_id": template_id, "score": score})
