"""
Evolution A/B testing endpoint handlers.

Endpoints:
- GET /api/evolution/ab-tests - List all A/B tests
- GET /api/evolution/ab-tests/{agent}/active - Get active test for agent
- POST /api/evolution/ab-tests - Start new A/B test
- GET /api/evolution/ab-tests/{id} - Get specific test
- POST /api/evolution/ab-tests/{id}/record - Record debate result
- POST /api/evolution/ab-tests/{id}/conclude - Conclude test
- DELETE /api/evolution/ab-tests/{id} - Cancel test
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from aragora.rbac.decorators import require_permission
from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_clamped_int_param,
    get_db_connection,
    handle_errors,
    json_response,
    validate_path_segment,
)

if TYPE_CHECKING:
    from ..base import ServerContext

logger = logging.getLogger(__name__)

# Allowed status values for query filtering
_VALID_STATUSES = frozenset({"active", "concluded", "cancelled"})

# Pattern for debate IDs - alphanumeric, hyphens, underscores, max 128 chars
_DEBATE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")

# Try to import A/B testing module
ABTestManager: Any
try:
    from aragora.evolution.ab_testing import ABTestManager

    AB_TESTING_AVAILABLE = True
except ImportError as e:
    AB_TESTING_AVAILABLE = False
    ABTestManager = None
    logger.debug("A/B testing module not available: %s", e)


class EvolutionABTestingHandler(BaseHandler):
    """Handler for evolution A/B testing endpoints."""

    HANDLE_POST_JSON_BODY = True

    ROUTES = [
        "/api/evolution/ab-tests",
        "/api/evolution/ab-tests/",
        "/api/v1/evolution/ab-tests",
        "/api/v1/evolution/ab-tests/",
    ]

    AUTH_REQUIRED_ENDPOINTS = [
        "/api/evolution/ab-tests",
        "/api/v1/evolution/ab-tests",
    ]

    def __init__(self, ctx: ServerContext | None = None):
        """Initialize with context."""
        super().__init__(ctx or {})
        self._manager: ABTestManager | None = None

    @property
    def manager(self) -> ABTestManager | None:
        """Lazy-load A/B test manager."""
        if self._manager is None and AB_TESTING_AVAILABLE:
            db_path_value = self.ctx.get("ab_tests_db", "ab_tests.db")
            db_path: str = db_path_value if isinstance(db_path_value, str) else "ab_tests.db"
            self._manager = ABTestManager(db_path=db_path)
        return self._manager

    def _get_user_store(self) -> Any:
        """Get user store from context."""
        return self.ctx.get("user_store")

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        return normalized.startswith("/api/evolution/ab-tests")

    @require_permission("testing:read")
    def handle(
        self, path: str, query_params: dict[str, Any], handler: Any = None
    ) -> HandlerResult | None:
        """Route GET requests."""
        if not AB_TESTING_AVAILABLE:
            return error_response("A/B testing module not available", 503)

        normalized = strip_version_prefix(path)

        if normalized == "/api/evolution/ab-tests" or normalized == "/api/evolution/ab-tests/":
            return self._list_tests(query_params)

        # Parse path segments from normalized path
        parts = normalized.rstrip("/").split("/")
        # /api/evolution/ab-tests/{id}
        # parts: ['', 'api', 'evolution', 'ab-tests', '{id}', ...]

        if len(parts) >= 5:
            segment = parts[4]

            # Validate path segment before using in queries
            valid, err = validate_path_segment(segment, "id_or_agent")
            if not valid:
                return error_response(err or "Invalid path segment", 400)

            # GET /api/evolution/ab-tests/{agent}/active
            if len(parts) == 6 and parts[5] == "active":
                return self._get_active_test(segment)

            # GET /api/evolution/ab-tests/{id}
            if len(parts) == 5:
                return self._get_test(segment)

        return None

    @handle_errors("evolution a b testing creation")
    @require_permission("testing:create")
    def handle_post(
        self, path: str, body: dict[str, Any], handler: Any = None
    ) -> HandlerResult | None:
        """Route POST requests."""
        if not AB_TESTING_AVAILABLE:
            return error_response("A/B testing module not available", 503)

        normalized = strip_version_prefix(path)

        # POST /api/evolution/ab-tests - Create new test
        if normalized == "/api/evolution/ab-tests" or normalized == "/api/evolution/ab-tests/":
            return self._create_test(body)

        parts = normalized.rstrip("/").split("/")

        if len(parts) >= 6:
            test_id = parts[4]
            action = parts[5]

            # Validate test_id before using in queries
            valid, err = validate_path_segment(test_id, "test_id")
            if not valid:
                return error_response(err or "Invalid test ID", 400)

            # POST /api/evolution/ab-tests/{id}/record
            if action == "record":
                return self._record_result(test_id, body)

            # POST /api/evolution/ab-tests/{id}/conclude
            if action == "conclude":
                return self._conclude_test(test_id, body)

        return None

    @handle_errors("evolution a b testing deletion")
    @require_permission("testing:delete")
    def handle_delete(
        self, path: str, query_params: dict, handler: Any = None
    ) -> HandlerResult | None:
        """Route DELETE requests with auth and rate limiting."""
        from aragora.billing.jwt_auth import extract_user_from_request

        from ..utils.rate_limit import RateLimiter, get_client_ip

        if not AB_TESTING_AVAILABLE:
            return error_response("A/B testing module not available", 503)

        normalized = strip_version_prefix(path)
        parts = normalized.rstrip("/").split("/")

        # DELETE /api/evolution/ab-tests/{id}
        # parts: ['', 'api', 'evolution', 'ab-tests', '{id}']
        if len(parts) == 5:
            test_id = parts[4]

            # Validate test_id before using in queries
            valid, err = validate_path_segment(test_id, "test_id")
            if not valid:
                return error_response(err or "Invalid test ID", 400)

            # Require authentication for state mutation
            user_store = self._get_user_store()
            auth_ctx = extract_user_from_request(handler, user_store)
            if not auth_ctx.is_authenticated:
                return error_response("Authentication required", 401)

            # Rate limit: 10 deletes per minute per IP
            if not hasattr(self, "_delete_limiter"):
                self._delete_limiter = RateLimiter(requests_per_minute=10)
            client_ip = get_client_ip(handler)
            if not self._delete_limiter.is_allowed(client_ip):
                return error_response("Rate limit exceeded. Please try again later.", 429)

            return self._cancel_test(test_id)

        return None

    @handle_errors("list A/B tests")
    def _list_tests(self, query_params: dict) -> HandlerResult:
        """List all A/B tests with optional filters."""
        if not self.manager:
            return error_response("A/B testing not configured", 503)

        agent = query_params.get("agent")
        status = query_params.get("status")
        limit = get_clamped_int_param(query_params, "limit", 50, min_val=1, max_val=200)

        # Validate status against allowed values
        if status is not None and status not in _VALID_STATUSES:
            return error_response(
                f"Invalid status filter. Allowed values: {', '.join(sorted(_VALID_STATUSES))}",
                400,
            )

        # Validate agent if provided
        if agent:
            valid, err = validate_path_segment(agent, "agent")
            if not valid:
                return error_response(err or "Invalid agent name", 400)

        # Get tests from database
        if agent:
            tests = self.manager.get_agent_tests(agent, limit=limit)
        else:
            # Get all tests (need to add this method or query directly)
            tests = self._get_all_tests(limit, status)

        return json_response(
            {
                "tests": [t.to_dict() for t in tests],
                "count": len(tests),
            }
        )

    def _get_all_tests(self, limit: int, status: str | None = None) -> list:
        """Get all tests with optional status filter.

        Args:
            limit: Maximum number of tests to return (already clamped by caller).
            status: Optional status filter (already validated against _VALID_STATUSES).
        """
        from aragora.evolution.ab_testing import AB_TEST_COLUMNS, ABTest

        with get_db_connection(str(self.manager.db_path)) as conn:
            cursor = conn.cursor()

            if status:
                cursor.execute(
                    f"""
                    SELECT {AB_TEST_COLUMNS} FROM ab_tests
                    WHERE status = ?
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,  # nosec B608 - AB_TEST_COLUMNS is a module-level constant  # noqa: S608
                    (status, limit),
                )
            else:
                cursor.execute(
                    f"""
                    SELECT {AB_TEST_COLUMNS} FROM ab_tests
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,  # nosec B608 - AB_TEST_COLUMNS is a module-level constant  # noqa: S608
                    (limit,),
                )

            return [ABTest.from_row(row) for row in cursor.fetchall()]

    @handle_errors("get A/B test")
    def _get_test(self, test_id: str) -> HandlerResult:
        """Get a specific A/B test."""
        if not self.manager:
            return error_response("A/B testing not configured", 503)

        valid, err = validate_path_segment(test_id, "test_id")
        if not valid:
            return error_response(err or "Invalid test ID", 400)

        test = self.manager.get_test(test_id)
        if not test:
            return error_response("A/B test not found", 404)

        return json_response(test.to_dict())

    @handle_errors("get active A/B test")
    def _get_active_test(self, agent: str) -> HandlerResult:
        """Get the active A/B test for an agent."""
        if not self.manager:
            return error_response("A/B testing not configured", 503)

        valid, err = validate_path_segment(agent, "agent")
        if not valid:
            return error_response(err or "Invalid agent name", 400)

        test = self.manager.get_active_test(agent)
        if not test:
            return json_response(
                {
                    "agent": agent,
                    "has_active_test": False,
                    "test": None,
                }
            )

        return json_response(
            {
                "agent": agent,
                "has_active_test": True,
                "test": test.to_dict(),
            }
        )

    @handle_errors("create A/B test")
    def _create_test(self, body: dict) -> HandlerResult:
        """Create a new A/B test."""
        if not self.manager:
            return error_response("A/B testing not configured", 503)

        agent = body.get("agent")
        if not agent:
            return error_response("agent is required", 400)

        # Validate agent name
        if not isinstance(agent, str):
            return error_response("agent must be a string", 400)
        valid, err = validate_path_segment(agent, "agent")
        if not valid:
            return error_response(err or "Invalid agent name", 400)

        baseline_version = body.get("baseline_version")
        evolved_version = body.get("evolved_version")

        if baseline_version is None or evolved_version is None:
            return error_response(
                "baseline_version and evolved_version are required",
                400,
            )

        # Validate version numbers are integers (separate from business logic)
        try:
            baseline_ver = int(baseline_version)
            evolved_ver = int(evolved_version)
        except (ValueError, TypeError):
            return error_response(
                "baseline_version and evolved_version must be integers",
                400,
            )

        try:
            test = self.manager.start_test(
                agent=agent,
                baseline_version=baseline_ver,
                evolved_version=evolved_ver,
                metadata=body.get("metadata"),
            )

            return json_response(
                {
                    "message": "A/B test created",
                    "test": test.to_dict(),
                },
                status=201,
            )

        except ValueError as e:
            # Business logic conflict (e.g., duplicate test, invalid state)
            logger.warning("A/B test creation conflict: %s", e)
            return error_response("A/B test creation failed - conflict", 409)

    @handle_errors("record A/B test result")
    def _record_result(self, test_id: str, body: dict) -> HandlerResult:
        """Record a debate result for an A/B test."""
        if not self.manager:
            return error_response("A/B testing not configured", 503)

        valid, err = validate_path_segment(test_id, "test_id")
        if not valid:
            return error_response(err or "Invalid test ID", 400)

        # Get the test to find the agent
        test = self.manager.get_test(test_id)
        if not test:
            return error_response("A/B test not found", 404)

        if test.status.value != "active":
            return error_response("Cannot record results for concluded test", 400)

        debate_id = body.get("debate_id")
        variant = body.get("variant")
        won = body.get("won")

        if not debate_id:
            return error_response("debate_id is required", 400)

        # Validate debate_id format to prevent injection via downstream usage
        if not isinstance(debate_id, str) or not _DEBATE_ID_PATTERN.match(debate_id):
            return error_response(
                "debate_id must be alphanumeric (hyphens/underscores allowed, max 128 chars)",
                400,
            )

        if variant not in ("baseline", "evolved"):
            return error_response(
                "variant must be 'baseline' or 'evolved'",
                400,
            )

        if won is None:
            return error_response("won is required", 400)

        updated_test = self.manager.record_result(
            agent=test.agent,
            debate_id=debate_id,
            variant=variant,
            won=bool(won),
        )

        if not updated_test:
            return error_response("Failed to record result", 500)

        return json_response(
            {
                "message": "Result recorded",
                "test": updated_test.to_dict(),
            }
        )

    @handle_errors("conclude A/B test")
    def _conclude_test(self, test_id: str, body: dict) -> HandlerResult:
        """Conclude an A/B test."""
        if not self.manager:
            return error_response("A/B testing not configured", 503)

        valid, err = validate_path_segment(test_id, "test_id")
        if not valid:
            return error_response(err or "Invalid test ID", 400)

        force = body.get("force", False)

        try:
            result = self.manager.conclude_test(test_id, force=force)

            return json_response(
                {
                    "message": "A/B test concluded",
                    "result": {
                        "test_id": result.test_id,
                        "winner": result.winner,
                        "confidence": result.confidence,
                        "recommendation": result.recommendation,
                        "stats": result.stats,
                    },
                }
            )

        except ValueError as e:
            logger.warning("A/B test conclusion failed: %s: %s", type(e).__name__, e)
            return error_response("A/B test conclusion failed", 400)

    @handle_errors("cancel A/B test")
    def _cancel_test(self, test_id: str) -> HandlerResult:
        """Cancel an active A/B test."""
        if not self.manager:
            return error_response("A/B testing not configured", 503)

        valid, err = validate_path_segment(test_id, "test_id")
        if not valid:
            return error_response(err or "Invalid test ID", 400)

        success = self.manager.cancel_test(test_id)

        if not success:
            return error_response(
                "A/B test not found or already concluded",
                404,
            )

        return json_response(
            {
                "message": "A/B test cancelled",
                "test_id": test_id,
            }
        )
