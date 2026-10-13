"""
HTTP API Handlers for Code Review.

Stability: STABLE
Graduated from EXPERIMENTAL on 2026-02-02.

Provides REST APIs for multi-agent code review:
- Code review requests
- Diff review
- PR review integration
- Review result management

Endpoints:
- POST /api/v1/code-review/review - Review code snippet
- POST /api/v1/code-review/diff - Review diff/patch
- POST /api/v1/code-review/pr - Review GitHub PR
- GET /api/v1/code-review/results/{id} - Get review results
- GET /api/v1/code-review/history - Get review history
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from aragora.resilience import CircuitBreaker
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    success_response,
)
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.rbac.decorators import require_permission

logger = logging.getLogger(__name__)

# RBAC permissions for code review
CODE_REVIEW_READ_PERMISSION = "code_review:read"
CODE_REVIEW_WRITE_PERMISSION = "code_review:write"

# =============================================================================
# Circuit Breaker Configuration
# =============================================================================

# Circuit breaker for code review operations
# Opens after 5 consecutive failures, recovers after 30 seconds
_code_review_circuit_breaker = CircuitBreaker(
    name="code_review_handler",
    failure_threshold=5,
    cooldown_seconds=30.0,
    half_open_success_threshold=2,
    half_open_max_calls=3,
)
_code_review_circuit_breaker_lock = threading.Lock()


def get_code_review_circuit_breaker() -> CircuitBreaker:
    """Get the global circuit breaker for code review operations."""
    return _code_review_circuit_breaker


def reset_code_review_circuit_breaker() -> None:
    """Reset the global circuit breaker (for testing)."""
    with _code_review_circuit_breaker_lock:
        _code_review_circuit_breaker._single_failures = 0
        _code_review_circuit_breaker._single_open_at = 0.0
        _code_review_circuit_breaker._single_successes = 0
        _code_review_circuit_breaker._single_half_open_calls = 0


# Thread-safe service instance
_code_reviewer: Any | None = None
_code_reviewer_lock = threading.Lock()

# In-memory storage for review results
_review_results: dict[str, Any] = {}
_review_results_lock = threading.Lock()


def get_code_reviewer():
    """Get or create code reviewer (thread-safe singleton)."""
    global _code_reviewer
    if _code_reviewer is not None:
        return _code_reviewer

    with _code_reviewer_lock:
        if _code_reviewer is None:
            from aragora.agents.code_reviewer import CodeReviewOrchestrator

            _code_reviewer = CodeReviewOrchestrator()
        return _code_reviewer


def store_review_result(result: Any) -> str:
    """Store review result and return ID."""
    with _review_results_lock:
        result_dict = result.to_dict() if hasattr(result, "to_dict") else result
        result_id = result_dict.get("id", f"review_{datetime.now().timestamp()}")
        _review_results[result_id] = {
            **result_dict,
            "stored_at": datetime.now().isoformat(),
        }
        return result_id


# =============================================================================
# Code Review Endpoints
# =============================================================================


@rate_limit(requests_per_minute=20, limiter_name="code_review_review")
@require_permission(CODE_REVIEW_WRITE_PERMISSION)
async def handle_review_code(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Review a code snippet.

    POST /api/v1/code-review/review
    Body: {
        code: str (required),
        language: str (optional, auto-detected if not provided),
        file_path: str (optional, for context),
        review_types: list[str] (optional - security, performance, maintainability, test_coverage),
        context: str (optional, additional context)
    }
    """
    # Check circuit breaker
    cb = get_code_review_circuit_breaker()
    if not cb.can_proceed():
        logger.warning("Code review circuit breaker is open")
        return error_response("Service temporarily unavailable due to high error rate", status=503)

    try:
        reviewer = get_code_reviewer()

        code = data.get("code")
        if not code:
            return error_response("code is required", status=400)

        language = data.get("language")
        file_path = data.get("file_path")
        review_types = data.get("review_types")
        context = data.get("context")

        result = await reviewer.review_code(
            code=code,
            language=language,
            file_path=file_path,
            review_types=review_types,
            context=context,
        )

        result_id = store_review_result(result)

        # Record success for circuit breaker
        cb.record_success()

        return success_response(
            {
                "result": result.to_dict(),
                "result_id": result_id,
                "message": "Code review completed",
            }
        )

    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError):
        # Record failure for circuit breaker
        cb.record_failure()
        logger.exception("Error reviewing code")
        return error_response("Code review failed", status=500)


@rate_limit(requests_per_minute=20, limiter_name="code_review_diff")
@require_permission(CODE_REVIEW_WRITE_PERMISSION)
async def handle_review_diff(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Review a diff/patch.

    POST /api/v1/code-review/diff
    Body: {
        diff: str (required, unified diff format),
        base_branch: str (optional),
        head_branch: str (optional),
        review_types: list[str] (optional),
        context: str (optional)
    }
    """
    # Check circuit breaker
    cb = get_code_review_circuit_breaker()
    if not cb.can_proceed():
        logger.warning("Code review circuit breaker is open")
        return error_response("Service temporarily unavailable due to high error rate", status=503)

    try:
        reviewer = get_code_reviewer()

        diff = data.get("diff")
        if not diff:
            return error_response("diff is required", status=400)

        result = await reviewer.review_diff(
            diff=diff,
            base_branch=data.get("base_branch"),
            head_branch=data.get("head_branch"),
            review_types=data.get("review_types"),
            context=data.get("context"),
        )

        result_id = store_review_result(result)

        # Record success for circuit breaker
        cb.record_success()

        return success_response(
            {
                "result": result.to_dict(),
                "result_id": result_id,
                "message": "Diff review completed",
            }
        )

    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError):
        # Record failure for circuit breaker
        cb.record_failure()
        logger.exception("Error reviewing diff")
        return error_response("Diff review failed", status=500)


@rate_limit(requests_per_minute=10, limiter_name="code_review_pr")
@require_permission(CODE_REVIEW_WRITE_PERMISSION)
async def handle_review_pr(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Review a GitHub pull request.

    POST /api/v1/code-review/pr
    Body: {
        pr_url: str (required, GitHub PR URL),
        review_types: list[str] (optional),
        post_comments: bool (optional, default false - requires GitHub token)
    }
    """
    # Check circuit breaker
    cb = get_code_review_circuit_breaker()
    if not cb.can_proceed():
        logger.warning("Code review circuit breaker is open")
        return error_response("Service temporarily unavailable due to high error rate", status=503)

    try:
        reviewer = get_code_reviewer()

        pr_url = data.get("pr_url")
        if not pr_url:
            return error_response("pr_url is required", status=400)

        # Validate PR URL format
        if "github.com" not in pr_url or "/pull/" not in pr_url:
            return error_response(
                "Invalid PR URL. Expected format: https://github.com/owner/repo/pull/123",
                status=400,
            )

        result = await reviewer.review_pr(
            pr_url=pr_url,
            review_types=data.get("review_types"),
            post_comments=data.get("post_comments", False),
        )

        result_id = store_review_result(result)

        # Record success for circuit breaker
        cb.record_success()

        return success_response(
            {
                "result": result.to_dict(),
                "result_id": result_id,
                "message": "PR review completed",
            }
        )

    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError):
        # Record failure for circuit breaker
        cb.record_failure()
        logger.exception("Error reviewing PR: %s", data.get("pr_url"))
        return error_response("PR review failed", status=500)


@require_permission(CODE_REVIEW_READ_PERMISSION)
async def handle_get_review_result(
    data: dict[str, Any],
    result_id: str,
    user_id: str = "default",
) -> HandlerResult:
    """
    Get a review result by ID.

    GET /api/v1/code-review/results/{result_id}
    """
    try:
        with _review_results_lock:
            result = _review_results.get(result_id)

        if not result:
            return error_response(f"Review result {result_id} not found", status=404)

        return success_response({"result": result})

    except (KeyError, ValueError, TypeError):
        logger.exception("Error getting review result %s", result_id)
        return error_response("Failed to retrieve result", status=500)


@require_permission(CODE_REVIEW_READ_PERMISSION)
async def handle_get_review_history(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get review history.

    GET /api/v1/code-review/history
    Query params: {
        limit: int (optional, default 50),
        offset: int (optional, default 0)
    }
    """
    try:
        limit = max(1, min(int(data.get("limit", 50)), 500))
        offset = max(0, int(data.get("offset", 0)))

        with _review_results_lock:
            # Sort by stored_at descending
            sorted_results = sorted(
                _review_results.values(),
                key=lambda x: x.get("stored_at", ""),
                reverse=True,
            )
            paginated = sorted_results[offset : offset + limit]

        return success_response(
            {
                "reviews": paginated,
                "total": len(_review_results),
                "limit": limit,
                "offset": offset,
            }
        )

    except (KeyError, ValueError, TypeError):
        logger.exception("Error getting review history")
        return error_response("Failed to retrieve history", status=500)


# =============================================================================
# Quick Review Endpoints
# =============================================================================


@require_permission(CODE_REVIEW_WRITE_PERMISSION)
async def handle_quick_security_scan(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Quick security-focused code scan.

    POST /api/v1/code-review/security-scan
    Body: {
        code: str (required),
        language: str (optional)
    }
    """
    try:
        reviewer = get_code_reviewer()

        code = data.get("code")
        if not code:
            return error_response("code is required", status=400)

        result = await reviewer.review_code(
            code=code,
            language=data.get("language"),
            review_types=["security"],
        )

        # Extract only security findings
        security_findings = [f for f in result.findings if f.category == "security"]

        return success_response(
            {
                "findings": [f.to_dict() for f in security_findings],
                "total": len(security_findings),
                "severity_summary": {
                    "critical": sum(1 for f in security_findings if f.severity == "critical"),
                    "high": sum(1 for f in security_findings if f.severity == "high"),
                    "medium": sum(1 for f in security_findings if f.severity == "medium"),
                    "low": sum(1 for f in security_findings if f.severity == "low"),
                },
            }
        )

    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError):
        logger.exception("Error in security scan")
        return error_response("Code scan failed", status=500)


# =============================================================================
# Handler Registration
# =============================================================================


class CodeReviewHandler(BaseHandler):
    """Handler class for code review endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    _ROUTE_MAP: dict[str, Any] = {
        "POST /api/v1/code-review/review": handle_review_code,
        "POST /api/v1/code-review/diff": handle_review_diff,
        "POST /api/v1/code-review/pr": handle_review_pr,
        "GET /api/v1/code-review/history": handle_get_review_history,
        "POST /api/v1/code-review/security-scan": handle_quick_security_scan,
    }

    ROUTES = [
        "/api/v1/code-review/review",
        "/api/v1/code-review/diff",
        "/api/v1/code-review/pr",
        "/api/v1/code-review/history",
        "/api/v1/code-review/security-scan",
    ]

    DYNAMIC_ROUTES: dict[str, Any] = {
        "GET /api/v1/code-review/results/{result_id}": handle_get_review_result,
    }
