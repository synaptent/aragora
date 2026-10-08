"""
Decision Router HTTP Handler.

Provides REST API endpoints for unified decision-making capabilities:
- POST /api/v1/decisions - Create a new decision request (debate, workflow, gauntlet)
- GET  /api/v1/decisions/:id - Get decision result by ID
- GET  /api/v1/decisions/:id/status - Get decision status for polling

Usage:
    # In unified_server.py
    from aragora.server.handlers.decisions.decision import DecisionHandler

    handlers.append(DecisionHandler(ctx))
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.utils.lazy_stores import LazyStoreFactory
from aragora.server.validation.query_params import safe_query_int

logger = logging.getLogger(__name__)

# Lazy-loaded router instance
_decision_router = None


def _get_decision_router(ctx: dict | None = None):
    """Get or create the decision router singleton."""
    global _decision_router
    if _decision_router is None:
        try:
            from aragora.core.decision import DecisionRouter

            ctx = ctx or {}
            _decision_router = DecisionRouter(
                document_store=ctx.get("document_store"),
                evidence_store=ctx.get("evidence_store"),
            )
        except (ImportError, TypeError, ValueError, AttributeError) as e:
            logger.warning("DecisionRouter not available: %s", e)
    elif ctx:
        # Fill in stores if they were not set initially.
        if getattr(_decision_router, "_document_store", None) is None:
            _decision_router._document_store = ctx.get("document_store")  # type: ignore[attr-defined]
        if getattr(_decision_router, "_evidence_store", None) is None:
            _decision_router._evidence_store = ctx.get("evidence_store")  # type: ignore[attr-defined]
    return _decision_router


# Lazy-loaded result store instance
_decision_result_store = LazyStoreFactory(
    store_name="decision_result_store",
    import_path="aragora.storage.decision_result_store",
    factory_name="get_decision_result_store",
    logger_context="Decision",
)


# Fallback in-memory cache (used only if persistent store fails)
_decision_results_fallback: dict[str, dict[str, Any]] = {}


def _save_result(request_id: str, data: dict[str, Any]) -> None:
    """Save a decision result to persistent store with fallback."""
    store = _decision_result_store.get()
    if store:
        try:
            store.save(request_id, data)
            return
        except (KeyError, ValueError, OSError, TypeError) as e:
            logger.warning("Failed to persist result, using fallback: %s", e)
    # Fallback to in-memory
    _decision_results_fallback[request_id] = data


def _get_result(request_id: str) -> dict[str, Any] | None:
    """Get a decision result from persistent store with fallback."""
    store = _decision_result_store.get()
    if store:
        try:
            result = store.get(request_id)
            if result:
                return result
        except (KeyError, ValueError, OSError, TypeError) as e:
            logger.warning("Failed to retrieve from store: %s", e)
    # Fallback to in-memory
    return _decision_results_fallback.get(request_id)


class DecisionHandler(BaseHandler):
    """
    Handler for unified decision-making API endpoints.

    Provides a single entry point for debates, workflows, gauntlets,
    and quick decisions via the DecisionRouter.
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/decisions",
        "/api/v1/decisions/*",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the request."""
        if path == "/api/v1/decisions":
            return True
        if path.startswith("/api/v1/decisions/"):
            return True
        return False

    @require_permission("decisions:read")
    def handle(self, path: str, query_params: dict, handler=None) -> HandlerResult | None:
        """Handle GET requests."""
        if path == "/api/v1/decisions":
            # List recent decisions (optional)
            return self._list_decisions(query_params)

        if path.startswith("/api/v1/decisions/"):
            parts = path.split("/")
            # parts = ['', 'api', 'v1', 'decisions', '<request_id>', ...]
            if len(parts) >= 5:
                request_id = parts[4]
                if len(parts) == 6 and parts[5] == "status":
                    return self._get_decision_status(request_id)
                return self._get_decision(request_id)

        return None

    @handle_errors("decision creation")
    async def handle_post(
        self, path: str, query_params: dict, handler=None
    ) -> HandlerResult | None:
        """Handle POST requests."""
        if path == "/api/v1/decisions":
            _, perm_error = self.require_permission_or_error(handler, "decisions:create")
            if perm_error:
                return perm_error
            return await self._create_decision(handler)

        # Handle /api/v1/decisions/:id/cancel
        if path.startswith("/api/v1/decisions/") and path.endswith("/cancel"):
            parts = path.split("/")
            if len(parts) == 6:  # ['', 'api', 'v1', 'decisions', '<id>', 'cancel']
                request_id = parts[4]
                _, perm_error = self.require_permission_or_error(handler, "decisions:update")
                if perm_error:
                    return perm_error
                return await self._cancel_decision(request_id, handler)

        # Handle /api/v1/decisions/:id/retry
        if path.startswith("/api/v1/decisions/") and path.endswith("/retry"):
            parts = path.split("/")
            if len(parts) == 6:  # ['', 'api', 'v1', 'decisions', '<id>', 'retry']
                request_id = parts[4]
                _, perm_error = self.require_permission_or_error(handler, "decisions:update")
                if perm_error:
                    return perm_error
                return await self._retry_decision(request_id, handler)

        return None

    async def _create_decision(self, handler) -> HandlerResult:
        """
        Create a new decision request.

        Expected body:
        {
            "content": "Question or topic",
            "decision_type": "debate|workflow|gauntlet|quick|auto",
            "config": {
                "agents": ["anthropic-api", "openai-api"],
                "rounds": 3,
                "consensus": "majority",
                "timeout_seconds": 300
            },
            "context": {
                "user_id": "user-123",
                "workspace_id": "ws-456"
            },
            "priority": "high|normal|low",
            "response_channels": [
                {"platform": "http_api"}
            ]
        }
        """
        # Parse body
        body, err = self.read_json_body_validated(handler)
        if err:
            return err

        if not body.get("content"):
            return error_response("Missing required field: content", 400)

        # Get authentication context
        from aragora.billing.auth import extract_user_from_request

        auth_ctx = extract_user_from_request(handler)

        # Build decision request
        try:
            from aragora.core.decision import DecisionRequest

            # Get headers for correlation ID
            headers = {}
            if hasattr(handler, "headers"):
                headers = dict(handler.headers)

            request = DecisionRequest.from_http(body, headers)

            # Set user context from auth if not provided
            if auth_ctx.authenticated:
                if not request.context.user_id:
                    request.context.user_id = auth_ctx.user_id
                if not request.context.workspace_id:
                    request.context.workspace_id = auth_ctx.org_id

        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)
        except (ImportError, TypeError, KeyError, AttributeError) as e:
            logger.warning("Failed to parse decision request: %s", e)
            return error_response("Failed to parse request", 400)

        # Get router
        router = _get_decision_router(self.ctx)
        if not router:
            return error_response("Decision router not available", 503)

        # Check RBAC if user is authenticated
        if auth_ctx.authenticated:
            try:
                from aragora.rbac import (
                    RBACEnforcer,
                    ResourceType,
                    Action,
                    IsolationContext,
                )

                enforcer = RBACEnforcer()
                ctx = IsolationContext(
                    actor_id=request.context.user_id,
                    workspace_id=request.context.workspace_id,
                )
                await enforcer.require(
                    auth_ctx.user_id,
                    ResourceType.DEBATE,
                    Action.CREATE,
                    ctx,
                )
            except (ImportError, TypeError, ValueError, AttributeError, RuntimeError) as e:
                logger.error("RBAC authorization check failed: %s", e)
                return error_response("Authorization service unavailable", 503)

        # Route the decision
        try:
            result = await router.route(request)

            # Cache result for polling (persistent)
            _save_result(
                request.request_id,
                {
                    "request_id": request.request_id,
                    "status": "completed" if result.success else "failed",
                    "result": result.to_dict(),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            return json_response(
                {
                    "request_id": request.request_id,
                    "status": "completed" if result.success else "failed",
                    "decision_type": result.decision_type.value,
                    "answer": result.answer,
                    "confidence": result.confidence,
                    "consensus_reached": result.consensus_reached,
                    "reasoning": result.reasoning,
                    "evidence_used": result.evidence_used,
                    "duration_seconds": result.duration_seconds,
                    "error": result.error,
                }
            )

        except asyncio.TimeoutError:
            # Save as pending for async polling
            _save_result(
                request.request_id,
                {
                    "request_id": request.request_id,
                    "status": "timeout",
                    "error": "Decision timed out",
                },
            )
            return error_response("Decision request timed out", 408)

        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.exception("Decision routing failed: %s", e)
            _save_result(
                request.request_id,
                {
                    "request_id": request.request_id,
                    "status": "failed",
                    "error": "Decision processing failed",
                },
            )
            logger.warning("Handler error: %s", e)
            return error_response("Decision processing failed", 500)

    def _get_decision(self, request_id: str) -> HandlerResult:
        """Get a decision result by ID."""
        result = _get_result(request_id)
        if result:
            return json_response(result)
        return error_response("Decision not found", 404)

    def _get_decision_status(self, request_id: str) -> HandlerResult:
        """Get decision status for polling."""
        store = _decision_result_store.get()
        if store:
            try:
                return json_response(store.get_status(request_id))
            except (KeyError, ValueError, OSError, TypeError) as e:
                logger.warning("Failed to get status from store: %s", e)

        # Fallback to in-memory
        if request_id in _decision_results_fallback:
            result = _decision_results_fallback[request_id]
            return json_response(
                {
                    "request_id": request_id,
                    "status": result.get("status", "unknown"),
                    "completed_at": result.get("completed_at"),
                }
            )
        return json_response(
            {
                "request_id": request_id,
                "status": "not_found",
            }
        )

    def _list_decisions(self, query_params: dict) -> HandlerResult:
        """List recent decisions."""
        limit = safe_query_int(query_params, "limit", default=20, min_val=1, max_val=100)

        store = _decision_result_store.get()
        if store:
            try:
                decisions = store.list_recent(limit)
                total = store.count()
                return json_response(
                    {
                        "decisions": decisions,
                        "total": total,
                    }
                )
            except (KeyError, ValueError, OSError, TypeError) as e:
                logger.warning("Failed to list from store: %s", e)

        # Fallback to in-memory
        decisions = list(_decision_results_fallback.values())[-limit:]
        return json_response(
            {
                "decisions": [
                    {
                        "request_id": d["request_id"],
                        "status": d.get("status"),
                        "completed_at": d.get("completed_at"),
                    }
                    for d in decisions
                ],
                "total": len(_decision_results_fallback),
            }
        )

    async def _cancel_decision(self, request_id: str, handler) -> HandlerResult:
        """
        Cancel a pending or running decision.

        Only decisions in PENDING or RUNNING status can be cancelled.
        """
        # Get current result
        result = _get_result(request_id)
        if not result:
            return error_response("Decision not found", 404)

        current_status = result.get("status", "unknown")

        # Validate state transition
        cancellable_statuses = {"pending", "running", "processing"}
        if current_status not in cancellable_statuses:
            return error_response(
                f"Cannot cancel decision in '{current_status}' status. "
                f"Only decisions in {cancellable_statuses} can be cancelled.",
                409,
            )

        # Parse optional reason from body
        reason = None
        try:
            body, _ = self.read_json_body_validated(handler)
            if body:
                reason = body.get("reason")
        except (TypeError, AttributeError, ValueError):
            pass  # Reason is optional

        # Update the result with cancelled status
        result["status"] = "cancelled"
        result["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        if reason:
            result["cancellation_reason"] = reason

        # Persist the update
        _save_result(request_id, result)

        logger.info(
            "Decision %s cancelled by user. Reason: %s", request_id, reason or "not provided"
        )

        return json_response(
            {
                "request_id": request_id,
                "status": "cancelled",
                "cancelled_at": result["cancelled_at"],
                "reason": reason,
            }
        )

    async def _retry_decision(self, request_id: str, handler) -> HandlerResult:
        """
        Retry a failed or cancelled decision.

        Creates a new decision with the same parameters as the original.
        """
        # Get original result
        original = _get_result(request_id)
        if not original:
            return error_response("Decision not found", 404)

        current_status = original.get("status", "unknown")

        # Validate state transition
        retryable_statuses = {"failed", "cancelled", "timeout"}
        if current_status not in retryable_statuses:
            return error_response(
                f"Cannot retry decision in '{current_status}' status. "
                f"Only decisions in {retryable_statuses} can be retried.",
                409,
            )

        # Get the original request data
        original_result = original.get("result", {})
        original_request = original_result.get("request", {})

        # Extract the original content/task
        content = (
            original_request.get("content")
            or original_result.get("task")
            or original.get("content")
        )
        if not content:
            return error_response(
                "Cannot retry: original decision content not found",
                400,
            )

        # Get router
        router = _get_decision_router(self.ctx)
        if not router:
            return error_response("Decision router not available", 503)

        # Build new decision request
        try:
            from aragora.core.decision import DecisionRequest
            import uuid

            # Generate new request ID
            new_request_id = f"dec_{uuid.uuid4().hex[:12]}"

            # Create new request with same parameters
            new_body = {
                "content": content,
                "decision_type": original_request.get("decision_type", "auto"),
                "config": original_request.get("config", {}),
                "context": original_request.get("context", {}),
            }

            request = DecisionRequest.from_http(new_body, {})
            request.request_id = new_request_id

            # Track retry lineage
            request.context.metadata = request.context.metadata or {}
            request.context.metadata["retried_from"] = request_id
            request.context.metadata["retry_count"] = original_result.get("retry_count", 0) + 1

        except (ImportError, TypeError, ValueError, KeyError, AttributeError) as e:
            logger.warning("Failed to build retry request: %s", e)
            return error_response("Retry request creation failed", 400)

        # Route the new decision
        try:
            result = await router.route(request)

            # Cache result
            _save_result(
                new_request_id,
                {
                    "request_id": new_request_id,
                    "status": "completed" if result.success else "failed",
                    "result": result.to_dict(),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "retried_from": request_id,
                },
            )

            logger.info("Decision %s retried as %s", request_id, new_request_id)

            return json_response(
                {
                    "request_id": new_request_id,
                    "status": "completed" if result.success else "failed",
                    "retried_from": request_id,
                    "decision_type": result.decision_type.value,
                    "answer": result.answer,
                    "confidence": result.confidence,
                    "consensus_reached": result.consensus_reached,
                }
            )

        except asyncio.TimeoutError:
            _save_result(
                new_request_id,
                {
                    "request_id": new_request_id,
                    "status": "timeout",
                    "error": "Decision retry timed out",
                    "retried_from": request_id,
                },
            )
            return error_response("Decision retry timed out", 408)

        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.exception("Decision retry failed: %s", e)
            _save_result(
                new_request_id,
                {
                    "request_id": new_request_id,
                    "status": "failed",
                    "error": "Decision retry failed",
                    "retried_from": request_id,
                },
            )
            logger.warning("Handler error: %s", e)
            return error_response("Decision retry failed", 500)


__all__ = ["DecisionHandler"]
