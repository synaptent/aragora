"""
Marketplace Pilot API Handler.

Provides the unified REST API for the marketplace pilot, serving listings
that span workflow templates, agent packs, skills, and connectors through
the ``MarketplaceService``.

Endpoints:
    GET  /api/v1/marketplace/listings          - Browse listings with filters
    GET  /api/v1/marketplace/listings/featured  - Featured listings
    GET  /api/v1/marketplace/listings/stats     - Marketplace statistics
    GET  /api/v1/marketplace/listings/{id}      - Get listing details
    POST /api/v1/marketplace/listings/{id}/install       - Install a listing
    POST /api/v1/marketplace/listings/{id}/rate           - Rate a listing
    POST /api/v1/marketplace/listings/{id}/launch-debate - Launch debate from listing

All GET endpoints return ``{"data": {...}}`` envelope.
Write endpoints use ``@handle_errors`` as outermost decorator.
RBAC enforced via ``@require_permission``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.validation.core import sanitize_string
from aragora.server.versioning.compat import strip_version_prefix

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Input validation constants
# ---------------------------------------------------------------------------

SAFE_ITEM_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")
MAX_SEARCH_LENGTH = 500
MAX_REVIEW_LENGTH = 2000
MAX_QUESTION_LENGTH = 5000
MIN_ROUNDS = 1
MAX_ROUNDS = 20
MIN_RATING = 1
MAX_RATING = 5


def _validate_item_id(value: str) -> tuple[bool, str]:
    """Validate an item ID string."""
    if not value or not isinstance(value, str):
        return False, "Item ID is required"
    if len(value) > 128:
        return False, "Item ID must be at most 128 characters"
    if not SAFE_ITEM_ID_PATTERN.match(value):
        return False, "Item ID contains invalid characters"
    return True, ""


# ---------------------------------------------------------------------------
# Service accessor (lazy)
# ---------------------------------------------------------------------------


def _get_service():
    """Get the global MarketplaceService (lazy import)."""
    from aragora.marketplace.service import get_marketplace_service

    return get_marketplace_service()


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class MarketplacePilotHandler(BaseHandler):
    """Handler for marketplace pilot API.

    Serves unified catalog listings (templates, agent packs, skills,
    connectors) with install and rating support.
    """

    ROUTES: list[str] = [
        "/api/v1/marketplace/listings",
        "/api/v1/marketplace/listings/*",
    ]

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        self._service = None  # Lazy; overridden in tests

    def _get_svc(self):
        """Get or create the marketplace service."""
        if self._service is None:
            self._service = _get_service()
        return self._service

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        return normalized.startswith("/api/marketplace/listings")

    # ----- GET routing ------------------------------------------------------

    @require_permission("marketplace:read")
    @rate_limit(requests_per_minute=60, limiter_name="marketplace_pilot.read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests."""
        normalized = strip_version_prefix(path)

        # GET /api/marketplace/listings
        if normalized == "/api/marketplace/listings":
            return self._handle_list(query_params)

        # GET /api/marketplace/listings/featured
        if normalized == "/api/marketplace/listings/featured":
            return self._handle_featured(query_params)

        # GET /api/marketplace/listings/stats
        if normalized == "/api/marketplace/listings/stats":
            return self._handle_stats()

        # GET /api/marketplace/listings/{id}
        if normalized.startswith("/api/marketplace/listings/"):
            parts = normalized.split("/")
            # ["", "api", "marketplace", "listings", "{id}"]
            if len(parts) == 5:
                item_id = parts[4]
                return self._handle_get_detail(item_id)

        return None

    # ----- POST routing -----------------------------------------------------

    @handle_errors("marketplace pilot write")
    @require_permission("marketplace:write")
    @rate_limit(requests_per_minute=20, limiter_name="marketplace_pilot.write")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route POST requests."""
        normalized = strip_version_prefix(path)

        if not normalized.startswith("/api/marketplace/listings/"):
            return None

        parts = normalized.split("/")
        # ["", "api", "marketplace", "listings", "{id}", "action"]

        if len(parts) < 6:
            return None

        item_id = parts[4]
        action = parts[5]

        valid, err = _validate_item_id(item_id)
        if not valid:
            return error_response(err, 400)

        if action == "install":
            return self._handle_install(item_id, handler)

        if action == "rate":
            return self._handle_rate(item_id, handler)

        if action == "launch-debate":
            return self._handle_launch_debate(item_id, handler)

        return None

    # ----- GET implementations ----------------------------------------------

    def _handle_list(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/marketplace/listings -- browse with filters."""
        svc = self._get_svc()

        # Parse and sanitize query params
        item_type = query_params.get("type")
        tag = query_params.get("tag")
        category = query_params.get("category")
        raw_search = query_params.get("search") or query_params.get("q")

        search = None
        if raw_search:
            if len(raw_search) > MAX_SEARCH_LENGTH:
                return error_response(
                    f"Search query must be at most {MAX_SEARCH_LENGTH} characters",
                    400,
                )
            search = sanitize_string(raw_search, MAX_SEARCH_LENGTH)

        try:
            limit = min(int(query_params.get("limit", 50)), 200)
        except (ValueError, TypeError):
            limit = 50
        try:
            offset = max(0, int(query_params.get("offset", 0)))
        except (ValueError, TypeError):
            offset = 0

        result = svc.list_listings(
            item_type=item_type,
            tag=tag,
            search=search,
            category=category,
            limit=limit,
            offset=offset,
        )

        return json_response({"data": result})

    def _handle_featured(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/marketplace/listings/featured."""
        svc = self._get_svc()

        try:
            limit = min(int(query_params.get("limit", 10)), 50)
        except (ValueError, TypeError):
            limit = 10

        result = svc.list_listings(featured_only=True, limit=limit)
        return json_response({"data": result})

    def _handle_stats(self) -> HandlerResult:
        """GET /api/v1/marketplace/listings/stats."""
        svc = self._get_svc()
        stats = svc.get_stats()
        return json_response({"data": stats})

    def _handle_get_detail(self, item_id: str) -> HandlerResult:
        """GET /api/v1/marketplace/listings/{id}."""
        valid, err = _validate_item_id(item_id)
        if not valid:
            return error_response(err, 400)

        svc = self._get_svc()
        item = svc.get_listing(item_id)

        if item is None:
            return error_response(f"Listing not found: {item_id}", 404)

        return json_response({"data": item})

    # ----- POST implementations ---------------------------------------------

    def _handle_install(self, item_id: str, handler: Any) -> HandlerResult:
        """POST /api/v1/marketplace/listings/{id}/install."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        user_id = getattr(user, "user_id", None) or getattr(user, "id", None) or str(user)

        svc = self._get_svc()
        result = svc.install_listing(item_id, user_id=str(user_id))

        if not result.success:
            all_errors = (
                result.catalog_result.errors if hasattr(result, "catalog_result") else []
            ) + (result.errors if hasattr(result, "errors") else [])
            return error_response(
                all_errors[0] if all_errors else "Installation failed",
                404,
            )

        return json_response(
            {
                "data": result.to_dict(),
            },
            status=200,
        )

    def _handle_rate(self, item_id: str, handler: Any) -> HandlerResult:
        """POST /api/v1/marketplace/listings/{id}/rate."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        user_id = getattr(user, "user_id", None) or getattr(user, "id", None) or str(user)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        # Validate score
        score = body.get("score")
        if not isinstance(score, int) or not (MIN_RATING <= score <= MAX_RATING):
            return error_response(
                f"Score must be an integer between {MIN_RATING} and {MAX_RATING}",
                400,
            )

        # Validate review
        review = body.get("review")
        if review is not None:
            if not isinstance(review, str):
                return error_response("Review must be a string", 400)
            if len(review) > MAX_REVIEW_LENGTH:
                return error_response(
                    f"Review must be at most {MAX_REVIEW_LENGTH} characters",
                    400,
                )
            review = sanitize_string(review, MAX_REVIEW_LENGTH)

        svc = self._get_svc()
        try:
            result = svc.rate_listing(
                item_id,
                user_id=str(user_id),
                score=score,
                review=review,
            )
        except KeyError:
            return error_response(f"Listing not found: {item_id}", 404)
        except ValueError as e:
            logger.warning("Invalid rating: %s", e)
            return error_response("Invalid rating data", 400)

        return json_response({"data": result})

    def _handle_launch_debate(self, item_id: str, handler: Any) -> HandlerResult:
        """POST /api/v1/marketplace/listings/{id}/launch-debate.

        Launch a debate using the template configuration from a marketplace
        listing.  The handler builds the debate config via
        ``MarketplaceService.launch_debate_from_listing`` and returns it to
        the caller.  Actual Arena execution is the caller's responsibility.
        """
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        user_id = getattr(user, "user_id", None) or getattr(user, "id", None) or str(user)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        # Validate question
        question = body.get("question")
        if not question or not isinstance(question, str):
            return error_response("A non-empty 'question' string is required", 400)
        if len(question) > MAX_QUESTION_LENGTH:
            return error_response(
                f"Question must be at most {MAX_QUESTION_LENGTH} characters",
                400,
            )
        question = sanitize_string(question, MAX_QUESTION_LENGTH)

        # Optional rounds override
        rounds_override: int | None = None
        raw_rounds = body.get("rounds")
        if raw_rounds is not None:
            if not isinstance(raw_rounds, int) or not (MIN_ROUNDS <= raw_rounds <= MAX_ROUNDS):
                return error_response(
                    f"Rounds must be an integer between {MIN_ROUNDS} and {MAX_ROUNDS}",
                    400,
                )
            rounds_override = raw_rounds

        svc = self._get_svc()
        try:
            result = svc.launch_debate_from_listing(
                item_id,
                question=question,
                user_id=str(user_id),
                rounds_override=rounds_override,
            )
        except KeyError:
            return error_response(f"Listing not found: {item_id}", 404)

        return json_response({"data": result})


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_marketplace_pilot_handler(
    server_context: dict[str, Any],
) -> MarketplacePilotHandler:
    """Factory function for handler registration."""
    return MarketplacePilotHandler(server_context)
