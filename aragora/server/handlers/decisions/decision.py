"""
Decision Router HTTP Handler.

Provides REST API endpoints for unified decision-making capabilities:
- POST /api/v1/decisions - Create a new decision request (debate, workflow, gauntlet)
- GET  /api/v1/decisions/:id - Get decision result by ID
- GET  /api/v1/decisions/:id/status - Get decision status for polling

Every route needs an authenticated member of an organization. Decisions belong
to the org that created them; another org's (or an unknown owner's) decision
gets the same 404 as a missing one, on the status route too.

Usage:
    # In unified_server.py
    from aragora.server.handlers.decisions.decision import DecisionHandler

    handlers.append(DecisionHandler(ctx))
"""

from __future__ import annotations

import asyncio
import copy
import logging
import threading
from datetime import datetime, timezone
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.core.decision_results import without_stored_request
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.utils.lazy_stores import LazyStoreFactory
from aragora.server.validation.query_params import safe_query_int
from aragora.tenancy.record_scope import OrgScope, record_not_found, require_org_scope

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
# Legacy server requests run on separate threads; the owner check and the write
# must be one step, or two orgs could both claim a new id.
_decision_results_fallback_lock = threading.Lock()

# Request ids this process is routing (a create, or a retry of that id). Cancel
# does not stop routing, so a cancelled id stays here until its run returns.
_routing_request_ids: set[str] = set()
_routing_request_ids_lock = threading.Lock()

_REPLAYED_FIELDS = (
    "content",
    "decision_type",
    "config",
    "priority",
    "attachments",
    "evidence",
    "documents",
    "document_ids",
    "response_channels",
)
_REPLAYED_CONTEXT_FIELDS = ("tags", "metadata")


def _replay_body(body: dict[str, Any]) -> dict[str, Any]:
    """The request body a retry replays: ``body`` without ids or caller identity.

    It is stored under ``result["request"]`` and returned as a deep copy, so
    neither the stored record nor a later request shares its lists or dicts.
    """
    replay = {key: body[key] for key in _REPLAYED_FIELDS if key in body}
    context = body.get("context")
    if isinstance(context, dict):
        replay["context"] = {
            key: context[key] for key in _REPLAYED_CONTEXT_FIELDS if key in context
        }
    return copy.deepcopy(replay)


def _save_result(
    request_id: str,
    data: dict[str, Any],
    *,
    org_id: str | None = None,
    created_by: str | None = None,
) -> bool:
    """Save a decision result, owned by ``org_id``, to persistent store with fallback.

    Returns False, writing nothing, when ``request_id`` already belongs to
    another org or to no org.
    """
    store = _decision_result_store.get()
    if store:
        from aragora.storage.decision_result_store import DecisionOwnershipConflict

        try:
            store.save(request_id, data, org_id=org_id, created_by=created_by)
            return True
        except DecisionOwnershipConflict:
            return False
        except (KeyError, ValueError, OSError, TypeError) as e:
            logger.warning("Failed to persist result, using fallback: %s", e)
    # Fallback to in-memory, with the same ownership rule as the store.
    owner_org = org_id or data.get("org_id")
    with _decision_results_fallback_lock:
        previous = _decision_results_fallback.get(request_id)
        if previous is not None and previous.get("org_id") != owner_org:
            return False
        if previous is not None:
            creator = previous.get("created_by")
        else:
            creator = created_by or data.get("created_by")
        entry = {**data, "org_id": owner_org, "created_by": creator}
        _decision_results_fallback[request_id] = entry
    return True


def _claim_result(
    request_id: str,
    data: dict[str, Any],
    *,
    org_id: str,
    created_by: str | None,
) -> str | None:
    """Claim ``request_id`` for ``org_id``, storing ``data`` only when the id is new.

    Returns the stored status afterwards (an existing result of ``org_id`` is
    kept as it is), or None, writing nothing, when the id belongs to another
    org or to no org.
    """
    store = _decision_result_store.get()
    if store:
        from aragora.storage.decision_result_store import DecisionOwnershipConflict

        try:
            return store.claim(request_id, data, org_id=org_id, created_by=created_by)
        except DecisionOwnershipConflict:
            return None
        except (KeyError, ValueError, OSError, TypeError) as e:
            logger.warning("Failed to persist claim, using fallback: %s", e)
    with _decision_results_fallback_lock:
        previous = _decision_results_fallback.get(request_id)
        if previous is not None:
            if previous.get("org_id") != org_id:
                return None
            return str(previous.get("status", "unknown"))
        _decision_results_fallback[request_id] = {
            **data,
            "org_id": org_id,
            "created_by": created_by,
        }
    return str(data.get("status", "unknown"))


def _save_result_if_status(
    request_id: str,
    data: dict[str, Any],
    *,
    org_id: str,
    expected_status: str,
) -> bool:
    """Save ``data`` over ``org_id``'s result only while its status is ``expected_status``.

    Returns False, writing nothing, when the result changed meanwhile (for
    example it was cancelled), is missing, or belongs to another org.
    """
    store = _decision_result_store.get()
    if store:
        try:
            if store.save_if_status(
                request_id, data, org_id=org_id, expected_status=expected_status
            ):
                return True
        except (KeyError, ValueError, OSError, TypeError) as e:
            logger.warning("Failed to persist result, using fallback: %s", e)
    # The claim may have gone to the fallback while the store was failing.
    with _decision_results_fallback_lock:
        previous = _decision_results_fallback.get(request_id)
        if (
            previous is None
            or previous.get("org_id") != org_id
            or previous.get("status", "unknown") != expected_status
        ):
            return False
        _decision_results_fallback[request_id] = {
            **data,
            "org_id": org_id,
            "created_by": previous.get("created_by"),
        }
    return True


def _start_routing(request_id: str) -> bool:
    """Mark ``request_id`` as routing; False when this process is already routing it."""
    with _routing_request_ids_lock:
        if request_id in _routing_request_ids:
            return False
        _routing_request_ids.add(request_id)
        return True


def _finish_routing(request_id: str) -> None:
    with _routing_request_ids_lock:
        _routing_request_ids.discard(request_id)
    # The claim pinned the stored result against capacity eviction. A route that
    # ends without a conditional save (a re-submit that was cancelled or raised)
    # is unpinned only here. Unpinning after the discard means a same-id create
    # answered 409 in between does not leave its pin behind.
    store = _decision_result_store.get()
    if store:
        store.release_routing(request_id)


def _discarded_result_response(request_id: str, scope: OrgScope) -> HandlerResult:
    """Response for a routing result dropped because the stored decision changed."""
    current = _get_result(request_id, scope.org_id)
    if current is None:
        return record_not_found("Decision")
    status = current.get("status", "unknown")
    return json_response(
        {
            "request_id": request_id,
            "status": status,
            "error": f"Decision changed to '{status}' while it was running; "
            "its result was discarded",
        },
        status=409,
    )


def _get_result(request_id: str, org_id: str | None) -> dict[str, Any] | None:
    """Get a decision result owned by ``org_id``; None when missing or owned elsewhere."""
    if not org_id:
        return None
    store = _decision_result_store.get()
    if store:
        try:
            result = store.get_for_org(request_id, org_id)
            if result:
                return result
        except (KeyError, ValueError, OSError, TypeError) as e:
            logger.warning("Failed to retrieve from store: %s", e)
    # Fallback to in-memory
    result = _decision_results_fallback.get(request_id)
    if result is None or result.get("org_id") != org_id:
        return None
    return result


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
        if path != "/api/v1/decisions" and not path.startswith("/api/v1/decisions/"):
            return None
        scope, scope_err = require_org_scope(handler)
        if scope is None:
            return scope_err

        if path == "/api/v1/decisions":
            # List recent decisions (optional)
            return self._list_decisions(query_params, scope)

        parts = path.split("/")
        # parts = ['', 'api', 'v1', 'decisions', '<request_id>', ...]
        if len(parts) >= 5:
            request_id = parts[4]
            if len(parts) == 6 and parts[5] == "status":
                return self._get_decision_status(request_id, scope)
            return self._get_decision(request_id, scope)

        return None

    @handle_errors("decision creation")
    async def handle_post(
        self, path: str, query_params: dict, handler=None
    ) -> HandlerResult | None:
        """Handle POST requests."""
        if path != "/api/v1/decisions" and not path.startswith("/api/v1/decisions/"):
            return None
        scope, scope_err = require_org_scope(handler)
        if scope is None:
            return scope_err

        if path == "/api/v1/decisions":
            _, perm_error = self.require_permission_or_error(handler, "decisions:create")
            if perm_error:
                return perm_error
            return await self._create_decision(handler, scope)

        # Handle /api/v1/decisions/:id/cancel
        if path.startswith("/api/v1/decisions/") and path.endswith("/cancel"):
            parts = path.split("/")
            if len(parts) == 6:  # ['', 'api', 'v1', 'decisions', '<id>', 'cancel']
                request_id = parts[4]
                _, perm_error = self.require_permission_or_error(handler, "decisions:update")
                if perm_error:
                    return perm_error
                return await self._cancel_decision(request_id, handler, scope)

        # Handle /api/v1/decisions/:id/retry
        if path.startswith("/api/v1/decisions/") and path.endswith("/retry"):
            parts = path.split("/")
            if len(parts) == 6:  # ['', 'api', 'v1', 'decisions', '<id>', 'retry']
                request_id = parts[4]
                _, perm_error = self.require_permission_or_error(handler, "decisions:update")
                if perm_error:
                    return perm_error
                return await self._retry_decision(request_id, handler, scope)

        return None

    async def _create_decision(self, handler, scope: OrgScope) -> HandlerResult:
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

        # Build decision request
        try:
            from aragora.core.decision import DecisionRequest

            # Get headers for correlation ID
            headers = {}
            if hasattr(handler, "headers"):
                headers = dict(handler.headers)

            request = DecisionRequest.from_http(body, headers)

            # The decision always acts for the caller: a user or workspace in
            # the body must not select another tenant's identity or knowledge.
            request.context.user_id = scope.user_id
            request.context.workspace_id = scope.org_id

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

        replay = _replay_body(body)
        request_id = request.request_id

        # Claim the request id for the caller's org before routing, which can
        # already store attachments: a request_id that belongs to another org
        # (or to none) is refused, like a missing one, with no side effect. A
        # result the caller's org already has under this id stays as it is
        # until the new result replaces it.
        claimed_status = _claim_result(
            request_id,
            {"request_id": request_id, "status": "pending", "result": {"request": replay}},
            org_id=scope.org_id,
            created_by=scope.user_id,
        )
        if claimed_status is None:
            return record_not_found("Decision")
        if not _start_routing(request_id):
            return error_response("Decision is already running", 409)

        def save_outcome(outcome: dict[str, Any]) -> bool:
            # Lands only while the stored record is as the claim left it: a
            # decision cancelled during routing stays cancelled.
            saved = _save_result_if_status(
                request_id,
                {"request_id": request_id, **outcome},
                org_id=scope.org_id,
                expected_status=claimed_status,
            )
            if not saved:
                logger.warning(
                    "Decision %s changed while routing; discarding its late %s result",
                    request_id,
                    outcome["status"],
                )
            return saved

        try:
            result = await router.route(request)
            status = "completed" if result.success else "failed"

            if not save_outcome(
                {
                    "status": status,
                    "result": {**result.to_dict(), "request": replay},
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }
            ):
                return _discarded_result_response(request_id, scope)

            return json_response(
                {
                    "request_id": request_id,
                    "status": status,
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
            if not save_outcome(
                {"status": "timeout", "result": {"request": replay}, "error": "Decision timed out"}
            ):
                return _discarded_result_response(request_id, scope)
            return error_response("Decision request timed out", 408)

        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.exception("Decision routing failed: %s", e)
            if not save_outcome(
                {
                    "status": "failed",
                    "result": {"request": replay},
                    "error": "Decision processing failed",
                }
            ):
                return _discarded_result_response(request_id, scope)
            logger.warning("Handler error: %s", e)
            return error_response("Decision processing failed", 500)

        except BaseException:
            # Any other error, or cancellation, must not leave a new claim
            # pending: only failed decisions can be retried. An earlier result
            # kept by the claim stays as it was.
            if claimed_status == "pending":
                try:
                    save_outcome(
                        {
                            "status": "failed",
                            "result": {"request": replay},
                            "error": "Decision processing failed",
                        }
                    )
                except Exception:  # noqa: BLE001 - the original error must propagate
                    logger.exception("Could not record decision %s as failed", request_id)
            raise

        finally:
            _finish_routing(request_id)

    def _get_decision(self, request_id: str, scope: OrgScope) -> HandlerResult:
        """Get a decision result by ID."""
        result = _get_result(request_id, scope.org_id)
        if result:
            return json_response(without_stored_request(result))
        return record_not_found("Decision")

    def _get_decision_status(self, request_id: str, scope: OrgScope) -> HandlerResult:
        """Get decision status for polling.

        A missing decision, or one owned by another org or by no org, gets the
        same 404 as ``GET /api/v1/decisions/:id``.
        """
        result = _get_result(request_id, scope.org_id)
        if result:
            return json_response(
                {
                    "request_id": request_id,
                    "status": result.get("status", "unknown"),
                    "completed_at": result.get("completed_at"),
                }
            )
        return record_not_found("Decision")

    def _list_decisions(self, query_params: dict, scope: OrgScope) -> HandlerResult:
        """List the caller org's recent decisions."""
        limit = safe_query_int(query_params, "limit", default=20, min_val=1, max_val=100)

        store = _decision_result_store.get()
        if store:
            try:
                decisions = store.list_recent_for_org(scope.org_id, limit)
                total = store.count_for_org(scope.org_id)
                return json_response(
                    {
                        "decisions": decisions,
                        "total": total,
                    }
                )
            except (KeyError, ValueError, OSError, TypeError) as e:
                logger.warning("Failed to list from store: %s", e)

        # Fallback to in-memory
        owned = [d for d in _decision_results_fallback.values() if d.get("org_id") == scope.org_id]
        return json_response(
            {
                "decisions": [
                    {
                        "request_id": d["request_id"],
                        "status": d.get("status"),
                        "completed_at": d.get("completed_at"),
                    }
                    for d in owned[-limit:]
                ],
                "total": len(owned),
            }
        )

    async def _cancel_decision(self, request_id: str, handler, scope: OrgScope) -> HandlerResult:
        """
        Cancel a pending or running decision.

        Only decisions in PENDING or RUNNING status can be cancelled. Routing
        that is already running is not stopped; its late result is discarded.
        """
        # Get current result
        result = _get_result(request_id, scope.org_id)
        if not result:
            return record_not_found("Decision")

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

        # Update a copy: the fallback lookup returns the stored dict itself, and
        # a save that fails must leave it unchanged.
        result = dict(result)
        result["status"] = "cancelled"
        result["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        if reason:
            result["cancellation_reason"] = reason

        # Only while the decision is still in the status read above: routing
        # may have saved its result since then.
        if not _save_result_if_status(
            request_id,
            result,
            org_id=scope.org_id,
            expected_status=current_status,
        ):
            current = _get_result(request_id, scope.org_id)
            if current is None:
                return record_not_found("Decision")
            return error_response(
                f"Cannot cancel decision in '{current.get('status', 'unknown')}' status. "
                f"Only decisions in {cancellable_statuses} can be cancelled.",
                409,
            )

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

    async def _retry_decision(self, request_id: str, handler, scope: OrgScope) -> HandlerResult:
        """
        Retry a failed or cancelled decision.

        Creates a new decision, owned by the caller's org, with the same
        parameters as the original.
        """
        # Get original result
        original = _get_result(request_id, scope.org_id)
        if not original:
            return record_not_found("Decision")

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

        replay = {**_replay_body(original_request), "content": content}

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
            request = DecisionRequest.from_http(copy.deepcopy(replay), {})
            request.request_id = new_request_id
            request.context.user_id = scope.user_id
            request.context.workspace_id = scope.org_id

            # Track retry lineage
            request.context.metadata = request.context.metadata or {}
            request.context.metadata["retried_from"] = request_id
            request.context.metadata["retry_count"] = original_result.get("retry_count", 0) + 1

        except (ImportError, TypeError, ValueError, KeyError, AttributeError) as e:
            logger.warning("Failed to build retry request: %s", e)
            return error_response("Retry request creation failed", 400)

        # A cancelled decision can still be routing (cancel does not stop it).
        # Holding its id while the retry runs also keeps two retries of the
        # same decision from running at once.
        if not _start_routing(request_id):
            return error_response("Decision is still running; retry it after it stops", 409)

        # Route the new decision
        try:
            result = await router.route(request)

            # Cache result
            _save_result(
                new_request_id,
                {
                    "request_id": new_request_id,
                    "status": "completed" if result.success else "failed",
                    "result": {**result.to_dict(), "request": replay},
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "retried_from": request_id,
                },
                org_id=scope.org_id,
                created_by=scope.user_id,
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
                    "result": {"request": replay},
                    "error": "Decision retry timed out",
                    "retried_from": request_id,
                },
                org_id=scope.org_id,
                created_by=scope.user_id,
            )
            return error_response("Decision retry timed out", 408)

        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
            logger.exception("Decision retry failed: %s", e)
            _save_result(
                new_request_id,
                {
                    "request_id": new_request_id,
                    "status": "failed",
                    "result": {"request": replay},
                    "error": "Decision retry failed",
                    "retried_from": request_id,
                },
                org_id=scope.org_id,
                created_by=scope.user_id,
            )
            logger.warning("Handler error: %s", e)
            return error_response("Decision retry failed", 500)

        finally:
            _finish_routing(request_id)


__all__ = ["DecisionHandler"]
