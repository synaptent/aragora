"""
Marketplace API Handlers.

Provides REST API endpoints for the agent template marketplace,
including template CRUD, search, ratings, and import/export.

Stability: STABLE
- Circuit breaker pattern for registry access resilience
- Rate limiting on all endpoints (60 req/min read, 20 req/min write)
- Comprehensive input validation (IDs, pagination, ratings, review text)
- RBAC permission enforcement (marketplace:read, marketplace:write, marketplace:delete)

Endpoints:
- GET  /api/v1/marketplace/templates          - List all templates
- GET  /api/v1/marketplace/templates/{id}     - Get template details
- POST /api/v1/marketplace/templates          - Create a template
- DELETE /api/v1/marketplace/templates/{id}   - Delete a template
- POST /api/v1/marketplace/templates/{id}/ratings - Rate a template
- GET  /api/v1/marketplace/templates/{id}/ratings  - Get template ratings
- POST /api/v1/marketplace/templates/{id}/star     - Star a template
- GET  /api/v1/marketplace/categories         - List categories
- GET  /api/v1/marketplace/templates/{id}/export   - Export template
- POST /api/v1/marketplace/templates/import   - Import a template
- GET  /api/v1/marketplace/status             - Health and circuit breaker status
"""

from __future__ import annotations

import json
import logging
import re
import threading
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import BaseHandler, HandlerResult, handle_errors
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.validation.core import sanitize_string

if TYPE_CHECKING:
    from aragora.marketplace import TemplateRegistry

logger = logging.getLogger(__name__)

# =============================================================================
# Constants for Input Validation
# =============================================================================

# Safe pattern for template IDs: alphanumeric, hyphens, underscores
SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")

MAX_TEMPLATE_ID_LENGTH = 128
MAX_QUERY_LENGTH = 500
MAX_TAGS_LENGTH = 1000
MAX_REVIEW_LENGTH = 2000
MIN_RATING = 1
MAX_RATING = 5
DEFAULT_LIMIT = 50
MIN_LIMIT = 1
MAX_LIMIT = 200
MAX_OFFSET = 10000

# =============================================================================
# Input Validation Functions
# =============================================================================


def _validate_template_id(value: str) -> tuple[bool, str]:
    """Validate a template ID string.

    Returns:
        Tuple of (is_valid, error_message). error_message is empty if valid.
    """
    if not value or not isinstance(value, str):
        return False, "Template ID is required"
    if len(value) > MAX_TEMPLATE_ID_LENGTH:
        return False, f"Template ID must be at most {MAX_TEMPLATE_ID_LENGTH} characters"
    if not SAFE_ID_PATTERN.match(value):
        return False, "Template ID contains invalid characters"
    return True, ""


def _validate_pagination(query_params: dict[str, Any]) -> tuple[int, int, str]:
    """Validate and clamp pagination parameters.

    Returns:
        Tuple of (limit, offset, error_message). error_message is empty if valid.
    """
    try:
        limit = int(query_params.get("limit") or DEFAULT_LIMIT)
    except (ValueError, TypeError):
        return DEFAULT_LIMIT, 0, "limit must be an integer"

    try:
        offset = int(query_params.get("offset") or 0)
    except (ValueError, TypeError):
        return DEFAULT_LIMIT, 0, "offset must be an integer"

    # Clamp values
    limit = max(MIN_LIMIT, min(limit, MAX_LIMIT))
    offset = max(0, min(offset, MAX_OFFSET))

    return limit, offset, ""


def _validate_rating(value: Any) -> tuple[bool, int, str]:
    """Validate a rating value.

    Returns:
        Tuple of (is_valid, sanitized_value, error_message).
    """
    if value is None:
        return False, 0, "Score required"
    if not isinstance(value, int):
        return False, 0, "Rating score must be an integer"
    if value < MIN_RATING or value > MAX_RATING:
        return False, 0, f"Rating score must be between {MIN_RATING}-{MAX_RATING}"
    return True, value, ""


def _validate_review(value: Any) -> tuple[bool, str | None, str]:
    """Validate a review string.

    Returns:
        Tuple of (is_valid, sanitized_value, error_message).
    """
    if value is None:
        return True, None, ""
    if not isinstance(value, str):
        return False, None, "Review must be a string"
    if len(value) > MAX_REVIEW_LENGTH:
        return False, None, f"Review must be at most {MAX_REVIEW_LENGTH} characters"
    return True, sanitize_string(value, MAX_REVIEW_LENGTH), ""


def _validate_query(value: Any) -> tuple[bool, str, str]:
    """Validate a search query string.

    Returns:
        Tuple of (is_valid, sanitized_value, error_message).
    """
    if value is None or value == "":
        return True, "", ""
    if not isinstance(value, str):
        return False, "", "Search query must be a string"
    if len(value) > MAX_QUERY_LENGTH:
        return False, "", f"Search query must be at most {MAX_QUERY_LENGTH} characters"
    return True, sanitize_string(value, MAX_QUERY_LENGTH), ""


def _validate_tags(value: Any) -> tuple[bool, list[str], str]:
    """Validate tags parameter (comma-separated string).

    Returns:
        Tuple of (is_valid, sanitized_value, error_message).
    """
    if value is None or value == "":
        return True, [], ""
    if not isinstance(value, str):
        return False, [], "Tags must be a comma-separated string"
    if len(value) > MAX_TAGS_LENGTH:
        return False, [], f"Tags string must be at most {MAX_TAGS_LENGTH} characters"
    # Split and sanitize each tag
    tags = [sanitize_string(t.strip(), 100) for t in value.split(",") if t.strip()]
    return True, tags, ""


# =============================================================================
# Circuit Breaker
# =============================================================================


from aragora.resilience.simple_circuit_breaker import (
    SimpleCircuitBreaker as MarketplaceCircuitBreaker,
)


# Global circuit breaker instance
_circuit_breaker: MarketplaceCircuitBreaker | None = None
_circuit_breaker_lock = threading.Lock()


def _get_circuit_breaker() -> MarketplaceCircuitBreaker:
    """Get or create the marketplace circuit breaker."""
    global _circuit_breaker
    with _circuit_breaker_lock:
        if _circuit_breaker is None:
            _circuit_breaker = MarketplaceCircuitBreaker()
        return _circuit_breaker


def get_marketplace_circuit_breaker() -> MarketplaceCircuitBreaker:
    """Public accessor for the marketplace circuit breaker."""
    return _get_circuit_breaker()


def get_marketplace_circuit_breaker_status() -> dict[str, Any]:
    """Get the marketplace circuit breaker status."""
    return get_marketplace_circuit_breaker().get_status()


def reset_marketplace_circuit_breaker() -> None:
    """Reset the marketplace circuit breaker (for testing)."""
    global _circuit_breaker
    with _circuit_breaker_lock:
        if _circuit_breaker is not None:
            _circuit_breaker.reset()


# =============================================================================
# Registry Management
# =============================================================================

# Lazy import to avoid circular dependencies
_registry: TemplateRegistry | None = None


def _get_registry() -> TemplateRegistry:
    """Get or create the template registry."""
    global _registry
    if _registry is None:
        from aragora.marketplace import TemplateRegistry

        _registry = TemplateRegistry()
    return _registry


def _clear_registry() -> None:
    """Clear the registry (for testing)."""
    global _registry
    _registry = None


# =============================================================================
# Handler Implementation
# =============================================================================


class MarketplaceHandler(BaseHandler):
    """Handler for marketplace template operations.

    Production-ready with:
    - Circuit breaker for registry access resilience
    - Rate limiting (60 req/min for reads, 20 req/min for writes)
    - Input validation for IDs, pagination, ratings, review text
    - RBAC permission enforcement
    """

    def __init__(self, ctx: dict | None = None, server_context: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = server_context or ctx or {}
        self._circuit_breaker = _get_circuit_breaker()

    @require_permission("marketplace:read")
    @rate_limit(requests_per_minute=60, limiter_name="marketplace.list")
    def handle_list_templates(self) -> HandlerResult:
        """
        GET /api/v1/marketplace/templates

        Query params:
            q: Search query
            category: Filter by category
            type: Filter by template type
            tags: Comma-separated tags
            limit: Max results (default 50)
            offset: Pagination offset
        """
        # Check circuit breaker
        if not self._circuit_breaker.can_proceed():
            return self.json_error(
                "Marketplace temporarily unavailable. Please try again later.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:
            # Validate and sanitize query parameter
            raw_query = self.get_query_param("q")
            valid, query, err = _validate_query(raw_query)
            if not valid:
                return self.json_error(err, HTTPStatus.BAD_REQUEST)

            # Validate pagination
            query_params = self._current_query_params or {}
            limit, offset, err = _validate_pagination(query_params)
            if err:
                return self.json_error(err, HTTPStatus.BAD_REQUEST)

            # Validate tags
            tags_str = self.get_query_param("tags")
            valid, tags, err = _validate_tags(tags_str)
            if not valid:
                return self.json_error(err, HTTPStatus.BAD_REQUEST)

            category_str = self.get_query_param("category")
            template_type = self.get_query_param("type")

            # Convert category string to enum
            category = None
            if category_str:
                from aragora.marketplace import TemplateCategory

                try:
                    category = TemplateCategory(category_str)
                except ValueError:
                    return self.json_error(
                        f"Invalid category: {category_str}",
                        HTTPStatus.BAD_REQUEST,
                    )

            registry = _get_registry()

            # Search templates
            templates = registry.search(
                query=query if query else None,
                category=category,
                template_type=template_type,
                tags=tags if tags else None,
                limit=limit,
                offset=offset,
            )

            self._circuit_breaker.record_success()

            return self.json_response(
                {
                    "templates": [t.to_dict() for t in templates],
                    "count": len(templates),
                    "limit": limit,
                    "offset": offset,
                }
            )

        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Error listing templates: %s", e)
            return self.json_error("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)

    @require_permission("marketplace:read")
    @rate_limit(requests_per_minute=60, limiter_name="marketplace.get")
    def handle_get_template(self, template_id: str) -> HandlerResult:
        """
        GET /api/v1/marketplace/templates/{id}
        """
        # Validate template ID
        valid, err = _validate_template_id(template_id)
        if not valid:
            return self.json_error(err, HTTPStatus.BAD_REQUEST)

        # Check circuit breaker
        if not self._circuit_breaker.can_proceed():
            return self.json_error(
                "Marketplace temporarily unavailable. Please try again later.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:
            registry = _get_registry()
            template = registry.get(template_id)

            if template is None:
                return self.json_error(
                    f"Template not found: {template_id}",
                    HTTPStatus.NOT_FOUND,
                )

            # Increment download count
            registry.increment_downloads(template_id)

            self._circuit_breaker.record_success()

            return self.json_response(template.to_dict())

        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Error getting template %s: %s", template_id, e)
            return self.json_error("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)

    @require_permission("marketplace:write")
    @rate_limit(requests_per_minute=20, limiter_name="marketplace.create")
    def handle_create_template(self) -> HandlerResult:
        """
        POST /api/v1/marketplace/templates

        Body: Template JSON
        """
        # Check circuit breaker
        if not self._circuit_breaker.can_proceed():
            return self.json_error(
                "Marketplace temporarily unavailable. Please try again later.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:
            user, error = self.require_auth_or_error(self._current_handler)
            if error:
                return error

            body = self.get_json_body()

            if not body:
                return self.json_error("Request body required", HTTPStatus.BAD_REQUEST)

            # Validate template ID if provided
            if "id" in body:
                valid, err = _validate_template_id(body["id"])
                if not valid:
                    return self.json_error(err, HTTPStatus.BAD_REQUEST)

            registry = _get_registry()

            # Import and register template
            template_id = registry.import_template(json.dumps(body))

            self._circuit_breaker.record_success()

            return self.json_response(
                {"id": template_id, "success": True},
                status=HTTPStatus.CREATED,
            )

        except ValueError as e:
            logger.warning("Invalid template data: %s", e)
            return self.json_error("Invalid template data", HTTPStatus.BAD_REQUEST)
        except (KeyError, TypeError, OSError, json.JSONDecodeError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Error creating template: %s", e)
            return self.json_error("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)

    @handle_errors("marketplace operation")
    @require_permission("marketplace:delete")
    @rate_limit(requests_per_minute=20, limiter_name="marketplace.delete")
    def handle_delete_template(self, template_id: str) -> HandlerResult:
        """
        DELETE /api/v1/marketplace/templates/{id}
        """
        # Validate template ID
        valid, err = _validate_template_id(template_id)
        if not valid:
            return self.json_error(err, HTTPStatus.BAD_REQUEST)

        # Check circuit breaker
        if not self._circuit_breaker.can_proceed():
            return self.json_error(
                "Marketplace temporarily unavailable. Please try again later.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:
            user, error = self.require_auth_or_error(self._current_handler)
            if error:
                return error

            registry = _get_registry()
            result = registry.delete(template_id)

            if not result:
                return self.json_error(
                    f"Cannot delete template: {template_id} (may be built-in)",
                    HTTPStatus.FORBIDDEN,
                )

            self._circuit_breaker.record_success()

            return self.json_response({"success": True, "deleted": template_id})

        except (KeyError, ValueError, TypeError, OSError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Error deleting template %s: %s", template_id, e)
            return self.json_error("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)

    @require_permission("marketplace:write")
    @rate_limit(requests_per_minute=20, limiter_name="marketplace.rate")
    def handle_rate_template(self, template_id: str) -> HandlerResult:
        """
        POST /api/v1/marketplace/templates/{id}/ratings

        Body: {"score": 1-5, "review": "optional review text"}
        """
        # Validate template ID
        valid, err = _validate_template_id(template_id)
        if not valid:
            return self.json_error(err, HTTPStatus.BAD_REQUEST)

        # Check circuit breaker
        if not self._circuit_breaker.can_proceed():
            return self.json_error(
                "Marketplace temporarily unavailable. Please try again later.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:
            user, error = self.require_auth_or_error(self._current_handler)
            if error:
                return error

            body = self.get_json_body()

            if not body:
                return self.json_error("Request body required", HTTPStatus.BAD_REQUEST)

            # Validate rating score
            valid, score, err = _validate_rating(body.get("score"))
            if not valid:
                return self.json_error(err, HTTPStatus.BAD_REQUEST)

            # Validate review text
            valid, review, err = _validate_review(body.get("review"))
            if not valid:
                return self.json_error(err, HTTPStatus.BAD_REQUEST)

            from aragora.marketplace import TemplateRating

            registry = _get_registry()

            rating = TemplateRating(
                user_id=user.id if hasattr(user, "id") else str(user),
                template_id=template_id,
                score=score,
                review=review,
            )
            registry.rate(rating)

            self._circuit_breaker.record_success()

            return self.json_response(
                {
                    "success": True,
                    "average_rating": registry.get_average_rating(template_id),
                }
            )

        except ValueError as e:
            logger.warning("Invalid rating data for template %s: %s", template_id, e)
            return self.json_error("Invalid rating data", HTTPStatus.BAD_REQUEST)
        except (KeyError, TypeError, AttributeError, OSError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Error rating template %s: %s", template_id, e)
            return self.json_error("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)

    @require_permission("marketplace:read")
    @rate_limit(requests_per_minute=60, limiter_name="marketplace.get_ratings")
    def handle_get_ratings(self, template_id: str) -> HandlerResult:
        """
        GET /api/v1/marketplace/templates/{id}/ratings
        """
        # Validate template ID
        valid, err = _validate_template_id(template_id)
        if not valid:
            return self.json_error(err, HTTPStatus.BAD_REQUEST)

        # Check circuit breaker
        if not self._circuit_breaker.can_proceed():
            return self.json_error(
                "Marketplace temporarily unavailable. Please try again later.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:
            registry = _get_registry()
            ratings = registry.get_ratings(template_id)
            avg = registry.get_average_rating(template_id)

            self._circuit_breaker.record_success()

            return self.json_response(
                {
                    "ratings": [
                        {
                            "user_id": r.user_id,
                            "score": r.score,
                            "review": r.review,
                            "created_at": r.created_at.isoformat(),
                        }
                        for r in ratings
                    ],
                    "average": avg,
                    "count": len(ratings),
                }
            )

        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Error getting ratings for %s: %s", template_id, e)
            return self.json_error("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)

    @require_permission("marketplace:write")
    @rate_limit(requests_per_minute=30, limiter_name="marketplace.star")
    def handle_star_template(self, template_id: str) -> HandlerResult:
        """
        POST /api/v1/marketplace/templates/{id}/star
        """
        # Validate template ID
        valid, err = _validate_template_id(template_id)
        if not valid:
            return self.json_error(err, HTTPStatus.BAD_REQUEST)

        # Check circuit breaker
        if not self._circuit_breaker.can_proceed():
            return self.json_error(
                "Marketplace temporarily unavailable. Please try again later.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:
            user, error = self.require_auth_or_error(self._current_handler)
            if error:
                return error

            registry = _get_registry()
            registry.star(template_id)

            template = registry.get(template_id)
            stars = template.metadata.stars if template else 0

            self._circuit_breaker.record_success()

            return self.json_response({"success": True, "stars": stars})

        except (KeyError, ValueError, TypeError, AttributeError, OSError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Error starring template %s: %s", template_id, e)
            return self.json_error("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)

    @require_permission("marketplace:read")
    @rate_limit(requests_per_minute=60, limiter_name="marketplace.categories")
    def handle_list_categories(self) -> HandlerResult:
        """
        GET /api/v1/marketplace/categories
        """
        # Check circuit breaker
        if not self._circuit_breaker.can_proceed():
            return self.json_error(
                "Marketplace temporarily unavailable. Please try again later.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:
            registry = _get_registry()
            categories = registry.list_categories()

            self._circuit_breaker.record_success()

            return self.json_response({"categories": categories})

        except (KeyError, ValueError, TypeError, OSError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Error listing categories: %s", e)
            return self.json_error("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)

    @require_permission("marketplace:read")
    @rate_limit(requests_per_minute=30, limiter_name="marketplace.export")
    def handle_export_template(self, template_id: str) -> HandlerResult:
        """
        GET /api/v1/marketplace/templates/{id}/export
        """
        # Validate template ID
        valid, err = _validate_template_id(template_id)
        if not valid:
            return self.json_error(err, HTTPStatus.BAD_REQUEST)

        # Check circuit breaker
        if not self._circuit_breaker.can_proceed():
            return self.json_error(
                "Marketplace temporarily unavailable. Please try again later.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:
            registry = _get_registry()
            json_str = registry.export_template(template_id)

            if json_str is None:
                return self.json_error(
                    f"Template not found: {template_id}",
                    HTTPStatus.NOT_FOUND,
                )

            self._circuit_breaker.record_success()

            return HandlerResult(
                status_code=HTTPStatus.OK,
                content_type="application/json",
                body=json_str.encode("utf-8"),
                headers={"Content-Disposition": f'attachment; filename="{template_id}.json"'},
            )

        except (KeyError, ValueError, TypeError, OSError, UnicodeEncodeError) as e:
            self._circuit_breaker.record_failure()
            logger.exception("Error exporting template %s: %s", template_id, e)
            return self.json_error("Internal server error", HTTPStatus.INTERNAL_SERVER_ERROR)

    @require_permission("marketplace:write")
    @rate_limit(requests_per_minute=20, limiter_name="marketplace.import")
    def handle_import_template(self) -> HandlerResult:
        """
        POST /api/v1/marketplace/templates/import

        Body: Template JSON
        """
        return self.handle_create_template()

    @require_permission("marketplace:read")
    def handle_status(self) -> HandlerResult:
        """
        GET /api/v1/marketplace/status

        Returns health and circuit breaker status.
        """
        cb_status = self._circuit_breaker.get_status()
        return self.json_response(
            {
                "status": "healthy" if cb_status["state"] == "closed" else "degraded",
                "circuit_breaker": cb_status,
            }
        )
