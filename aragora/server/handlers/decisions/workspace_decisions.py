"""Decision workspace API: agent options and the decision list.

Endpoints (all need a signed-in user with an org):
- GET  /api/v1/workspace/agent-options
- GET  /api/v1/workspace/decisions

No user -> 401 ``auth_required``; a user without an org (or the static API
token) -> 403 ``org_required``. A list only ever shows the caller's org.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from aragora.decision_workspace.config import agent_options, workspace_limits
from aragora.decision_workspace.intake import (
    ACCEPTED_EXTENSIONS,
    DEFAULT_ROUNDS,
    MAX_ROUNDS,
    MIN_ROUNDS,
)
from aragora.decision_workspace.store import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    DecisionRecord,
    WorkspaceStore,
    get_workspace_store,
)
from aragora.rbac.decorators import require_permission
from aragora.tenancy.record_scope import (
    OrgScope,
    require_org_scope,
    scope_denial_first,
)

from ..base import BaseHandler, HandlerResult, handle_errors, json_response

logger = logging.getLogger(__name__)

PREFIX = "/api/v1/workspace"
_ROUTE_PATTERNS = (
    ("agent_options", re.compile(r"^/agent-options$")),
    ("decisions", re.compile(r"^/decisions$")),
)
_ALLOWED_METHODS = {
    "agent_options": "GET",
    "decisions": "GET",
}


def _match(path: str) -> tuple[str, dict[str, str]] | None:
    """``(route, params)`` for a workspace path (one trailing slash allowed)."""
    if not path.startswith(PREFIX + "/"):
        return None
    rest = path[len(PREFIX) :]
    if rest.endswith("/") and rest != "/":
        rest = rest[:-1]
    for name, pattern in _ROUTE_PATTERNS:
        found = pattern.match(rest)
        if found:
            return name, found.groupdict()
    return None


def _not_found() -> HandlerResult:
    return json_response({"error": "Unknown workspace route", "code": "not_found"}, status=404)


def _method_not_allowed(route: str) -> HandlerResult:
    return json_response(
        {"error": "Method not allowed", "code": "method_not_allowed"},
        status=405,
        headers={"Allow": _ALLOWED_METHODS[route]},
    )


def _error(status: int, code: str, message: str, **extra: Any) -> HandlerResult:
    return json_response({"error": message, "code": code, **extra}, status=status)


def _query_value(query_params: dict[str, Any], name: str) -> str | None:
    value = query_params.get(name)
    if isinstance(value, list):
        value = value[0] if value else None
    return None if value is None else str(value)


def _get_plan_store() -> Any:
    from aragora.pipeline.plan_store import get_plan_store

    return get_plan_store()


class WorkspaceDecisionsHandler(BaseHandler):
    """Decision workspace read routes."""

    # Dynamic sub-routes are routed through the registry's PREFIX_PATTERNS entry
    # rather than ROUTE_PREFIXES, which the spec generator would publish as a
    # bare "/api/v1/workspace/{param}" placeholder operation.
    ROUTES = [f"{PREFIX}/agent-options", f"{PREFIX}/decisions"]

    def __init__(self, ctx: dict[str, Any]) -> None:
        super().__init__(ctx)

    def can_handle(self, path: str) -> bool:
        return path.startswith(PREFIX + "/")

    @handle_errors("workspace decision read")
    @scope_denial_first
    @require_permission("decisions:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        scope, err = require_org_scope(handler)
        if scope is None:
            return err
        matched = _match(path)
        if matched is None:
            return _not_found()
        route, _params = matched
        if route == "agent_options":
            return self._agent_options()
        return self._list_decisions(query_params, scope)

    @handle_errors("workspace decision creation")
    @scope_denial_first
    @require_permission("decisions:create")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        return self._unsupported(path, handler)

    @handle_errors("workspace decision update")
    @scope_denial_first
    @require_permission("decisions:update")
    def handle_put(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        return self._unsupported(path, handler)

    @handle_errors("workspace decision update")
    @scope_denial_first
    @require_permission("decisions:update")
    def handle_patch(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        return self._unsupported(path, handler)

    @handle_errors("workspace decision deletion")
    @scope_denial_first
    @require_permission("decisions:update")
    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        return self._unsupported(path, handler)

    def _unsupported(self, path: str, handler: Any) -> HandlerResult:
        # Always answer here: a None result would fall through to the GET handler.
        scope, err = require_org_scope(handler)
        if scope is None:
            return err
        matched = _match(path)
        if matched is None:
            return _not_found()
        return _method_not_allowed(matched[0])

    # -- reads -------------------------------------------------------------

    @staticmethod
    def _store() -> WorkspaceStore:
        return get_workspace_store(_get_plan_store().db_path)

    @staticmethod
    def _agent_options() -> HandlerResult:
        options = agent_options()
        limits = workspace_limits()
        return json_response(
            {
                "configured": options.configured,
                "agents": [option.to_dict() for option in options.agents],
                "message": options.error,
                "limits": {
                    "max_documents": limits.max_documents,
                    "max_file_bytes": limits.max_file_bytes,
                    "max_pasted_chars": limits.max_pasted_chars,
                },
                "accepted_extensions": list(ACCEPTED_EXTENSIONS),
                "rounds": {"min": MIN_ROUNDS, "max": MAX_ROUNDS, "default": DEFAULT_ROUNDS},
            }
        )

    def _list_decisions(self, query_params: dict[str, Any], scope: OrgScope) -> HandlerResult:
        limit = _bounded_int(
            _query_value(query_params, "limit"), DEFAULT_LIST_LIMIT, 1, MAX_LIST_LIMIT
        )
        offset = _bounded_int(_query_value(query_params, "offset"), 0, 0, None)
        if limit is None:
            return _error(
                400, "invalid_parameter", f"limit must be 1 to {MAX_LIST_LIMIT}.", field="limit"
            )
        if offset is None:
            return _error(400, "invalid_parameter", "offset must be 0 or more.", field="offset")
        decisions, total = self._store().list_decisions(scope.org_id, limit=limit, offset=offset)
        return json_response(
            {
                "decisions": [_decision_summary(d) for d in decisions],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )


def _bounded_int(raw: str | None, default: int, low: int, high: int | None) -> int | None:
    if raw is None or raw == "":
        return default
    text = raw.strip()
    if not (text.isascii() and text.isdigit()) or len(text) > 9:
        return None
    value = int(text)
    if value < low or (high is not None and value > high):
        return None
    return value


def _decision_summary(decision: DecisionRecord) -> dict[str, Any]:
    return {
        "id": decision.plan_id,
        "question": decision.question,
        "status": decision.status,
        "source_count": decision.source_count,
        "created_at": decision.created_at,
        "updated_at": decision.updated_at,
    }


__all__ = ["WorkspaceDecisionsHandler"]
