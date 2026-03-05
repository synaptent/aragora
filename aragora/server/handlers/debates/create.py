"""
Debate creation and lifecycle operations handler mixin.

Extracted from handler.py for modularity. Provides:
- Create debate (POST /api/debates)
- Cancel debate
- Decision router integration
- Spam content checking
"""

from __future__ import annotations

import importlib
import logging
import sys
from typing import TYPE_CHECKING, Any, Protocol

from aragora.resilience import with_timeout_sync
from aragora.server.http_utils import run_async
from aragora.server.validation.pydantic_models import validate_debate_request
from aragora.server.validation.schema import (
    DEBATE_START_SCHEMA,
    validate_against_schema,
)

from aragora.events.handler_events import emit_handler_event, CREATED
from aragora.rbac.decorators import require_permission

from ..base import (
    HandlerResult,
    error_response,
    json_response,
    safe_error_message,
)
from ..openapi_decorator import api_endpoint
from ..utils.rate_limit import rate_limit, user_rate_limit
from aragora.server.middleware.tier_enforcement import require_quota

if TYPE_CHECKING:
    from aragora.billing.auth.context import UserAuthContext


logger = logging.getLogger(__name__)


def _get_validate_against_schema():
    handler_module = sys.modules.get("aragora.server.handlers.debates.handler")
    if handler_module is not None:
        candidate = getattr(handler_module, "validate_against_schema", None)
        if callable(candidate):
            return candidate
    return validate_against_schema


class _DebatesHandlerProtocol(Protocol):
    """Protocol defining the interface expected by CreateOperationsMixin.

    This protocol enables proper type checking for mixin classes that
    expect to be mixed into a class providing these methods/attributes.
    """

    ctx: dict[str, Any]

    def get_storage(self) -> Any | None:
        """Get debate storage instance."""
        ...

    def read_json_body(self, handler: Any, max_size: int | None = None) -> dict[str, Any] | None:
        """Read and parse JSON body from request handler."""
        ...

    def get_current_user(self, handler: Any) -> UserAuthContext | None:
        """Get authenticated user from request."""
        ...

    def _check_spam_content(self, body: dict[str, Any]) -> HandlerResult | None:
        """Check if debate content contains spam patterns."""
        ...

    def _create_debate_direct(self, handler: Any, body: dict[str, Any]) -> HandlerResult:
        """Create debate directly without decision router."""
        ...


class CreateOperationsMixin:
    """Mixin providing debate creation and lifecycle operations for DebatesHandler."""

    @api_endpoint(
        method="POST",
        path="/api/v1/debates",
        summary="Create a new debate",
        description="Start an ad-hoc debate with specified question, agents, and configuration. Rate limited and quota enforced.",
        tags=["Debates"],
        responses={
            "200": {
                "description": "Debate created successfully",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/DebateCreateResponse"}
                    }
                },
            },
            "400": {"description": "Invalid request body or validation error"},
            "401": {"description": "Unauthorized"},
            "402": {"description": "Quota exceeded"},
            "429": {"description": "Rate limit exceeded"},
            "500": {"description": "Internal server error"},
        },
    )
    @require_permission("debates:create")
    @with_timeout_sync(120.0)
    @user_rate_limit(action="debate_create")
    @rate_limit(requests_per_minute=5, limiter_name="debates_create")
    @require_quota("debate")
    def _create_debate(self: _DebatesHandlerProtocol, handler: Any) -> HandlerResult:
        """Start an ad-hoc debate with specified question.

        Accepts JSON body with:
            question: The topic/question to debate (required)
            agents: Comma-separated agent list (optional, default varies)
            rounds: Number of debate rounds (optional, default: 3)
            consensus: Consensus method (optional, default: "majority")
            auto_select: Whether to auto-select agents (optional, default: False)
            use_trending: Whether to use trending topic (optional, default: False)

        Routes through DecisionRouter for unified routing, deduplication,
        and caching. Falls back to direct controller if router unavailable.

        Rate limited and quota enforced via decorators.
        Returns 402 Payment Required if monthly debate quota exceeded.
        """
        logger.info("[_create_debate] Called via DebatesHandler")

        # Rate limit expensive debate creation
        try:
            if hasattr(handler, "_check_rate_limit") and not handler._check_rate_limit():
                logger.info("[_create_debate] Rate limit check failed")
                return error_response("Rate limit exceeded", 429)
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
            logger.exception("[_create_debate] Rate limit check error: %s", e)
            return error_response("Rate limit check failed", 500)

        logger.info("[_create_debate] Rate limit passed")

        # Tier-aware rate limiting based on subscription
        try:
            if hasattr(handler, "_check_tier_rate_limit") and not handler._check_tier_rate_limit():
                return error_response("Tier rate limit exceeded", 429)
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
            logger.warning("Tier rate limit check failed, proceeding: %s", e)

        # Check if debate orchestrator is available
        debate_available = False
        try:
            importlib.import_module("aragora.debate.orchestrator")
            debate_available = True
        except ImportError:
            pass

        if not debate_available:
            return error_response("Debate orchestrator not available", 500)

        stream_emitter = getattr(handler, "stream_emitter", None)
        if not stream_emitter:
            return error_response("Event streaming not configured", 500)

        # Read and validate request body
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid or missing JSON body", 400)

        if not body:
            return error_response("No content provided", 400)

        # Schema validation for input sanitization
        validation_result = _get_validate_against_schema()(body, DEBATE_START_SCHEMA)
        if not validation_result.is_valid:
            return error_response(validation_result.error, 400)

        # Pydantic v2 strict validation (question length, rounds bounds, agents limit)
        # Only applies when the body contains a 'question' field (the primary field);
        # requests using the legacy 'task' field bypass this layer to preserve compatibility.
        if "question" in body:
            _pydantic_req, _pydantic_err = validate_debate_request(body)
            if _pydantic_err is not None:
                return error_response(_pydantic_err, 422)

        # Spam check for debate content
        spam_result = self._check_spam_content(body)
        if spam_result:
            return spam_result

        # Use direct controller approach for ad-hoc debates.
        # The DecisionRouter is designed for synchronous decisions and blocks
        # until the debate completes (minutes). For HTTP requests, we need to
        # return immediately with the debate_id and let the client poll/stream.
        #
        # DecisionRouter can still be used for:
        # - Chat connector decisions (Slack/Telegram) that need sync responses
        # - Internal orchestration where blocking is acceptable
        return self._create_debate_direct(handler, body)

    async def _route_through_decision_router(
        self: _DebatesHandlerProtocol, handler: Any, body: dict[str, Any], headers: dict[str, Any]
    ) -> HandlerResult:
        """Route debate creation through DecisionRouter.

        This provides unified handling including:
        - Deduplication of concurrent identical requests
        - Result caching
        - Origin registration for bidirectional routing
        - Unified metrics and tracing
        """
        from aragora.core.decision import (
            DecisionRequest,
            DecisionType,
            InputSource,
            get_decision_router,
        )

        # Create unified decision request from HTTP body
        request = DecisionRequest.from_http(body, headers)

        # Force debate type for this endpoint
        request.decision_type = DecisionType.DEBATE
        request.source = InputSource.HTTP_API

        # Get authenticated user context
        user = self.get_current_user(handler)
        if user:
            if not request.context.user_id:
                request.context.user_id = user.user_id
            if not request.context.workspace_id:
                request.context.workspace_id = getattr(user, "org_id", None)

        # Route through DecisionRouter
        router = get_decision_router()
        result = await router.route(request)

        logger.info(
            "DecisionRouter completed debate %s (success=%s, debate_id=%s)",
            request.request_id,
            result.success,
            getattr(result, "debate_id", "N/A"),
        )

        # Build response
        status_code = 200 if result.success else 500
        response_data = {
            "request_id": request.request_id,
            "debate_id": getattr(result, "debate_id", request.request_id),
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

        return json_response(response_data, status=status_code)

    def _create_debate_direct(
        self: _DebatesHandlerProtocol, handler: Any, body: dict[str, Any]
    ) -> HandlerResult:
        """Direct debate creation via controller (fallback path)."""
        # Parse and validate request using DebateRequest
        try:
            from aragora.server.debate_controller import DebateRequest

            request = DebateRequest.from_dict(body)
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)

        # Get debate controller and start debate
        try:
            controller = handler._get_debate_controller()
            response = controller.start_debate(request)
        except (TypeError, ValueError, AttributeError, KeyError, RuntimeError, OSError) as e:
            logger.exception("Failed to start debate: %s", e)
            return error_response(safe_error_message(e, "start debate"), 500)

        # Note: Usage increment is handled by @require_quota decorator on success
        emit_handler_event("debate", CREATED, {"debate_id": response.debate_id})
        return json_response(response.to_dict(), status=response.status_code)

    @api_endpoint(
        method="POST",
        path="/api/v1/debates/{id}/cancel",
        summary="Cancel a running debate",
        description="Cancel a debate that is currently running. Marks as cancelled and attempts to cancel running tasks.",
        tags=["Debates"],
        parameters=[{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
        responses={
            "200": {
                "description": "Debate cancelled successfully",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "success": {"type": "boolean"},
                                "debate_id": {"type": "string"},
                                "status": {"type": "string"},
                                "message": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "400": {"description": "Debate cannot be cancelled"},
            "404": {"description": "Debate not found"},
        },
    )
    @require_permission("debates:stop")
    def _cancel_debate(
        self: _DebatesHandlerProtocol, handler: Any, debate_id: str
    ) -> HandlerResult:
        """Cancel a running debate.

        Marks the debate as cancelled and attempts to cancel any running tasks.

        Args:
            handler: The HTTP handler
            debate_id: ID of the debate to cancel

        Returns:
            HandlerResult with cancellation status
        """
        from aragora.server.debate_utils import update_debate_status
        from aragora.server.state import get_state_manager
        from aragora.server.stream import StreamEvent, StreamEventType

        manager = get_state_manager()
        state = manager.get_debate(debate_id)

        if not state:
            # Check if debate exists in storage but already completed
            storage = self.get_storage()
            if storage:
                debate = storage.get_debate(debate_id)
                if debate:
                    return error_response(
                        f"Debate {debate_id} already completed (status: {debate.get('status', 'unknown')})",
                        400,
                    )
            return error_response(f"Debate not found: {debate_id}", 404)

        # Check if debate is in a cancellable state
        if state.status not in ("running", "starting"):
            return error_response(
                f"Debate {debate_id} cannot be cancelled (status: {state.status})",
                400,
            )

        # Mark as cancelled
        update_debate_status(debate_id, "cancelled", error="Cancelled by user")
        manager.update_debate_status(debate_id, status="cancelled")

        # Try to cancel the asyncio task if tracked
        task = state.metadata.get("_task")
        if task and hasattr(task, "cancel") and not getattr(task, "done", lambda: True)():
            try:
                task.cancel()
                logger.info("Cancelled running task for debate %s", debate_id)
            except (RuntimeError, TypeError, AttributeError, OSError) as e:
                logger.warning("Failed to cancel task for %s: %s", debate_id, e)

        # Emit cancellation event to all subscribers
        stream_emitter = getattr(handler, "stream_emitter", None)
        if stream_emitter:
            stream_emitter.emit(
                StreamEvent(
                    type=StreamEventType.DEBATE_END,
                    data={
                        "debate_id": debate_id,
                        "status": "cancelled",
                        "reason": "Cancelled by user",
                    },
                    loop_id=debate_id,
                )
            )

        logger.info("Debate %s cancelled by user", debate_id)

        return json_response(
            {
                "success": True,
                "debate_id": debate_id,
                "status": "cancelled",
                "message": "Debate cancelled successfully",
            }
        )

    @api_endpoint(
        method="POST",
        path="/api/v1/debate-this",
        summary="One-click debate launcher",
        description="Convenience endpoint for quick debate creation. Only requires a question; auto-detects format and selects agents.",
        tags=["Debates"],
        responses={
            "200": {
                "description": "Debate created successfully",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/DebateCreateResponse"}
                    }
                },
            },
            "400": {"description": "Invalid request body"},
            "401": {"description": "Unauthorized"},
            "402": {"description": "Quota exceeded"},
            "429": {"description": "Rate limit exceeded"},
        },
    )
    @require_permission("debates:create")
    @with_timeout_sync(120.0)
    @user_rate_limit(action="debate_create")
    @rate_limit(requests_per_minute=5, limiter_name="debate_this")
    @require_quota("debate")
    def _debate_this(self: _DebatesHandlerProtocol, handler: Any) -> HandlerResult:
        """One-click debate launcher.

        Accepts a minimal JSON body with just a question. Auto-detects
        format based on question length and always auto-selects agents.

        Body:
            question: The topic to debate (required)
            context: Optional context string
            source: Source surface identifier (default: "debate_this")
        """
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid or missing JSON body", 400)

        question = body.get("question", "").strip()
        if not question:
            return error_response("Missing required field: question", 400)

        # Auto-detect format: longer questions get more thorough debates
        rounds = 9 if len(question) > 200 else 4
        source = body.get("source", "debate_this")

        # Build the full debate body with defaults
        debate_body: dict[str, Any] = {
            "question": question,
            "rounds": body.get("rounds", rounds),
            "auto_select": True,
            "metadata": {"source": source},
        }

        context = body.get("context")
        if context:
            debate_body["context"] = context

        # Delegate to existing creation logic
        result = self._create_debate_direct(handler, debate_body)

        # Add spectate_url to successful responses
        if result and result.status_code == 200 and result.body:
            try:
                import json as _json

                data = _json.loads(result.body)
                debate_id = data.get("debate_id")
                if debate_id:
                    data["spectate_url"] = f"/spectate/{debate_id}"
                    return json_response(data, status=200)
            except (ValueError, TypeError, AttributeError):
                pass

        return result

    def _check_spam_content(
        self: _DebatesHandlerProtocol, body: dict[str, Any]
    ) -> HandlerResult | None:
        """
        Check debate input content for spam.

        Runs the spam moderation integration against the debate task/question
        and context. Returns an error response if content should be blocked,
        or None if content passes.

        Args:
            body: The request body containing task/question and context

        Returns:
            HandlerResult with 400 error if spam detected, None otherwise
        """
        try:
            from aragora.moderation import check_debate_content, ContentModerationError

            # Extract content to check
            proposal = body.get("task") or body.get("question", "")
            context = body.get("context", "")

            if not proposal:
                return None  # Let schema validation handle this

            # Run async spam check
            result = run_async(check_debate_content(proposal, context))

            if result.should_block:
                logger.warning(
                    f"Spam content blocked: verdict={result.verdict.value}, "
                    f"confidence={result.confidence:.2f}, "
                    f"reasons={result.reasons[:3]}"
                )
                return error_response(
                    "Content blocked by spam filter. Please revise your input.",
                    400,
                )

            if result.should_flag_for_review:
                # Log suspicious content but allow it through
                logger.info(
                    f"Suspicious content flagged: verdict={result.verdict.value}, "
                    f"confidence={result.confidence:.2f}"
                )

            return None  # Content passed

        except ImportError:
            # Moderation module not available - allow content through
            logger.debug("Spam moderation not available, skipping check")
            return None
        except ContentModerationError as e:
            # Moderation explicitly rejected content
            logger.warning("Content moderation error: %s", e)
            return error_response("Invalid request", 400)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.error("Spam check failed unexpectedly: %s", e, exc_info=True)
            return None


__all__ = ["CreateOperationsMixin"]
