"""Decision workspace API: agent options, decisions, sources and passages.

Endpoints (all need a signed-in user with an org):
- GET  /api/v1/workspace/agent-options
- GET  /api/v1/workspace/decisions
- GET  /api/v1/workspace/decisions/{decision_id}
- GET  /api/v1/workspace/decisions/{decision_id}/sources
- GET  /api/v1/workspace/decisions/{decision_id}/passages/{passage_id}

No user -> 401 ``auth_required``; a user without an org (or the static API
token) -> 403 ``org_required``. Another org's decision, source or passage
answers exactly like a missing one (404 ``not_found``).
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
    PassageRecord,
    SourceRecord,
    WorkspaceStore,
    get_workspace_store,
)
from aragora.rbac.decorators import require_permission
from aragora.tenancy.record_scope import (
    OrgScope,
    record_not_found,
    require_org_scope,
    scope_denial_first,
)

from ..base import BaseHandler, HandlerResult, handle_errors, json_response

logger = logging.getLogger(__name__)

PREFIX = "/api/v1/workspace"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ROUTE_PATTERNS = (
    ("agent_options", re.compile(r"^/agent-options$")),
    ("decisions", re.compile(r"^/decisions$")),
    ("decision", re.compile(r"^/decisions/(?P<decision_id>[^/]+)$")),
    ("sources", re.compile(r"^/decisions/(?P<decision_id>[^/]+)/sources$")),
    (
        "passage",
        re.compile(r"^/decisions/(?P<decision_id>[^/]+)/passages/(?P<passage_id>[^/]+)$"),
    ),
)
_ALLOWED_METHODS = {
    "agent_options": "GET",
    "decisions": "GET",
    "decision": "GET",
    "sources": "GET",
    "passage": "GET",
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
        route, params = matched
        if route == "agent_options":
            return self._agent_options()
        if route == "decisions":
            return self._list_decisions(query_params, scope)
        decision = self._visible_decision(params["decision_id"], scope)
        if decision is None:
            return record_not_found("Decision")
        if route == "decision":
            return json_response(_decision_body(decision))
        if route == "sources":
            return json_response(self._sources_body(decision, scope))
        return self._get_passage(decision, params["passage_id"], scope)

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

    def _visible_decision(self, decision_id: str, scope: OrgScope) -> DecisionRecord | None:
        if not _SAFE_ID.match(decision_id):
            return None
        return self._store().get_decision(decision_id, scope.org_id)

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

    def _sources_body(self, decision: DecisionRecord, scope: OrgScope) -> dict[str, Any]:
        store = self._store()
        sources = store.list_sources(decision.plan_id, scope.org_id)
        passages = store.list_passages(decision.plan_id, scope.org_id)
        return {
            "decision_id": decision.plan_id,
            "sources": _sources_payload(sources, passages),
        }

    def _get_passage(
        self, decision: DecisionRecord, passage_id: str, scope: OrgScope
    ) -> HandlerResult:
        passage = (
            self._store().get_passage(decision.plan_id, passage_id, scope.org_id)
            if _SAFE_ID.match(passage_id)
            else None
        )
        if passage is None:
            return record_not_found("Passage")
        return json_response(_passage_body(passage))


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


def _decision_body(decision: DecisionRecord) -> dict[str, Any]:
    return {
        "id": decision.plan_id,
        "question": decision.question,
        "status": decision.status,
        "agents": list(decision.agents),
        "rounds": decision.rounds,
        "created_by": decision.created_by,
        "created_at": decision.created_at,
        "updated_at": decision.updated_at,
        "current_revision_id": decision.current_revision_id,
        "budget_usd": decision.budget_usd,
        "cost_actual_usd": decision.cost_actual_usd,
        "cost_estimated_usd": decision.cost_estimated_usd,
        "source_count": decision.source_count,
        "passage_count": decision.passage_count,
    }


def _sources_payload(
    sources: list[SourceRecord], passages: list[PassageRecord]
) -> list[dict[str, Any]]:
    by_source: dict[str, list[PassageRecord]] = {}
    for passage in passages:
        by_source.setdefault(passage.source_id, []).append(passage)
    return [
        {
            "source_id": source.source_id,
            "label": source.label,
            "kind": source.kind,
            "filename": source.filename,
            "document_id": source.document_id,
            "content_sha256": source.content_sha256,
            "char_count": source.char_count,
            "passage_count": source.passage_count,
            "created_at": source.created_at,
            "passages": [
                {
                    "passage_id": p.passage_id,
                    "label": p.label,
                    "seq": p.seq,
                    "heading": p.heading,
                    "char_count": len(p.text),
                    "sha256": p.sha256,
                    "in_context": p.in_context,
                }
                for p in by_source.get(source.source_id, [])
            ],
        }
        for source in sources
    ]


def _passage_body(passage: PassageRecord) -> dict[str, Any]:
    return {
        "passage_id": passage.passage_id,
        "decision_id": passage.plan_id,
        "source_id": passage.source_id,
        "source_label": passage.source_label,
        "label": passage.label,
        "seq": passage.seq,
        "heading": passage.heading,
        "start_char": passage.start_char,
        "end_char": passage.end_char,
        "text": passage.text,
        "sha256": passage.sha256,
        "in_context": passage.in_context,
        "created_at": passage.created_at,
    }


__all__ = ["WorkspaceDecisionsHandler"]
