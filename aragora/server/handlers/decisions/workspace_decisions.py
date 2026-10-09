"""Decision workspace API: intake, decisions, sources, passages and reruns.

Endpoints (all need a signed-in user with an org):
- GET  /api/v1/workspace/agent-options
- GET  /api/v1/workspace/decisions
- POST /api/v1/workspace/decisions          (multipart/form-data, or JSON for text only)
- GET  /api/v1/workspace/decisions/{decision_id}
- GET  /api/v1/workspace/decisions/{decision_id}/sources
- GET  /api/v1/workspace/decisions/{decision_id}/passages/{passage_id}
- POST /api/v1/workspace/decisions/{decision_id}/rerun

No user -> 401 ``auth_required``; a user without an org (or the static API
token) -> 403 ``org_required``. Another org's decision, source or passage
answers exactly like a missing one (404 ``not_found``). The owner of a new
decision always comes from the auth context, never from the request body.
A refused intake creates nothing: every check runs before the first write,
and a failed write removes what was already written. Intake and rerun each
start one run; a run that cannot be handed to the debate runner ends
``failed`` with the reason, so the decision can be rerun.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from aragora.decision_workspace.config import agent_options, workspace_limits
from aragora.decision_workspace.debate_hook import DebateStartRequest, launch_decision_run
from aragora.decision_workspace.forms import (
    IntakeError,
    max_request_bytes,
    parse_json_intake,
    parse_multipart_intake,
)
from aragora.decision_workspace.intake import (
    ACCEPTED_EXTENSIONS,
    DEFAULT_ROUNDS,
    KIND_UPLOAD,
    MAX_ROUNDS,
    MIN_ROUNDS,
    PreparedDecision,
    prepare_decision,
)
from aragora.decision_workspace.store import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    DecisionRecord,
    DecisionRows,
    PassageRecord,
    RevisionRecord,
    RunConflictError,
    RunRecord,
    SourceRecord,
    WorkspaceStore,
    get_workspace_store,
    new_decision_rows,
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
    ("rerun", re.compile(r"^/decisions/(?P<decision_id>[^/]+)/rerun$")),
)
_ALLOWED_METHODS = {
    "agent_options": "GET",
    "decisions": "GET, POST",
    "decision": "GET",
    "sources": "GET",
    "passage": "GET",
    "rerun": "POST",
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
    """Decision workspace intake and read routes."""

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
        if route == "rerun":
            return _method_not_allowed(route)
        decision = self._visible_decision(params["decision_id"], scope)
        if decision is None:
            return record_not_found("Decision")
        if route == "decision":
            return json_response(self._decision_detail(decision, scope))
        if route == "sources":
            return json_response(self._sources_body(decision, scope))
        return self._get_passage(decision, params["passage_id"], scope)

    @handle_errors("workspace decision request")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        matched = _match(path)
        if matched is not None and matched[0] == "rerun":
            return self._post_rerun(path, query_params, handler)
        return self._post_create(path, query_params, handler)

    @scope_denial_first
    @require_permission("decisions:create")
    def _post_create(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        scope, err = require_org_scope(handler)
        if scope is None:
            return err
        matched = _match(path)
        if matched is None:
            return _not_found()
        if matched[0] != "decisions":
            return _method_not_allowed(matched[0])
        return self._create_decision(handler, scope)

    @scope_denial_first
    @require_permission("decisions:update")
    def _post_rerun(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        scope, err = require_org_scope(handler)
        if scope is None:
            return err
        matched = _match(path)
        if matched is None:
            return _not_found()
        return self._rerun(matched[1]["decision_id"], scope)

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

    # -- intake ------------------------------------------------------------

    def _create_decision(self, handler: Any, scope: OrgScope) -> HandlerResult:
        limits = workspace_limits()
        cap = max_request_bytes(limits)
        raw_length = handler.headers.get("Content-Length")
        if raw_length is None:
            return _error(411, "length_required", "Content-Length is required.")
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            length = -1
        if length < 0:
            return _error(400, "invalid_content_length", "Content-Length must be a byte count.")
        if length > cap:
            return _error(
                413,
                "request_too_large",
                f"The request is {length} bytes; at most {cap} bytes are accepted.",
                limit=cap,
            )
        body = handler.rfile.read(length) if length else b""
        if len(body) != length:
            return _error(400, "incomplete_body", "The request body ended early.")

        content_type = handler.headers.get("Content-Type", "") or ""
        media_type = content_type.split(";", 1)[0].strip().lower()
        try:
            if media_type == "multipart/form-data":
                form = parse_multipart_intake(body, content_type)
            elif media_type == "application/json":
                form = parse_json_intake(body)
            else:
                raise IntakeError(
                    415,
                    None,
                    "unsupported_media_type",
                    "Send the decision as multipart/form-data, or as JSON without files.",
                )
            prepared = prepare_decision(form, options=agent_options(), limits=limits)
        except IntakeError as exc:
            return json_response(exc.body(), status=exc.status)

        if any(source.kind == KIND_UPLOAD for source in prepared.sources):
            if self.ctx.get("document_store") is None:
                return _error(
                    503,
                    "document_store_unavailable",
                    "File uploads are unavailable: the document store is not configured.",
                )
        rows = self._store_decision(prepared, scope)
        decision = rows.decision
        if rows.run is not None:
            launch_decision_run(
                self._store(),
                DebateStartRequest(
                    plan_id=decision.plan_id,
                    org_id=scope.org_id,
                    user_id=scope.user_id,
                    question=decision.question,
                    agents=decision.agents,
                    rounds=decision.rounds,
                    run_id=rows.run.run_id,
                ),
            )
        decision = self._visible_decision(decision.plan_id, scope) or decision
        body_out = self._decision_detail(decision, scope)
        body_out.update(self._sources_body(decision, scope))
        return json_response(body_out, status=202)

    # -- runs --------------------------------------------------------------

    def _rerun(self, decision_id: str, scope: OrgScope) -> HandlerResult:
        if not _SAFE_ID.match(decision_id):
            return record_not_found("Decision")
        store = self._store()
        try:
            run = store.start_run(decision_id, scope.org_id, scope.user_id)
        except LookupError:
            return record_not_found("Decision")
        except RunConflictError as exc:
            return _error(409, exc.code, str(exc), run_id=exc.run_id)
        decision = store.get_decision(decision_id, scope.org_id)
        if decision is None:
            return record_not_found("Decision")
        launch_decision_run(
            store,
            DebateStartRequest(
                plan_id=decision.plan_id,
                org_id=scope.org_id,
                user_id=scope.user_id,
                question=decision.question,
                agents=run.agents,
                rounds=run.rounds,
                run_id=run.run_id,
            ),
        )
        logger.info(
            "Workspace decision %s rerun by %s as %s", decision_id, scope.user_id, run.run_id
        )
        decision = store.get_decision(decision_id, scope.org_id) or decision
        return json_response(self._decision_detail(decision, scope), status=202)

    def _decision_detail(self, decision: DecisionRecord, scope: OrgScope) -> dict[str, Any]:
        store = self._store()
        runs = store.list_runs(decision.plan_id, scope.org_id)
        current = (
            store.get_revision(decision.plan_id, decision.current_revision_id, scope.org_id)
            if decision.current_revision_id
            else None
        )
        body = _decision_body(decision)
        body["run"] = _run_body(runs[0], with_result=True) if runs else None
        body["runs"] = [_run_body(run, with_result=False) for run in runs]
        body["current_revision"] = _revision_body(current) if current is not None else None
        return body

    def _store_decision(self, prepared: PreparedDecision, scope: OrgScope) -> DecisionRows:
        """Store documents, the plan with its backbone run and the workspace rows.

        A failure part way removes everything already written.
        """
        from aragora.documents.parsing import parse_document
        from aragora.pipeline.decision_integrity_utils import ensure_decision_plan_backbone_run
        from aragora.pipeline.decision_plan.core import ApprovalMode, DecisionPlan

        plan_store = _get_plan_store()
        workspace = get_workspace_store(plan_store.db_path)
        documents = self.ctx.get("document_store")
        plan = DecisionPlan(
            task=prepared.question,
            approval_mode=ApprovalMode.ALWAYS,
            metadata={
                "source": "decision_workspace",
                "agents": list(prepared.agents),
                "rounds": prepared.rounds,
            },
            org_id=scope.org_id,
            created_by=scope.user_id,
        )
        new_documents: list[str] = []
        document_ids: dict[str, str] = {}
        plan_created = False
        try:
            for source in prepared.sources:
                if source.kind != KIND_UPLOAD or source.content is None:
                    continue
                doc = parse_document(
                    source.content,
                    source.filename or "",
                    org_id=scope.org_id,
                    created_by=scope.user_id,
                )
                if documents.get(doc.id) is None:
                    new_documents.append(doc.id)
                documents.add(doc)
                document_ids[source.label] = doc.id
            ensure_decision_plan_backbone_run(
                plan,
                auth_context=scope,
                source_surface="decision_workspace",
                source_id="",
                org_id=scope.org_id,
                created_by=scope.user_id,
            )
            plan_store.create(plan)
            plan_created = True
            rows = new_decision_rows(
                prepared,
                plan_id=plan.id,
                org_id=scope.org_id,
                user_id=scope.user_id,
                document_ids=document_ids,
            )
            workspace.insert_decision(rows)
        except Exception:
            self._undo(
                plan_store,
                plan.id if plan_created else None,
                plan.metadata.get("backbone_run_id"),
                documents,
                new_documents,
            )
            raise
        logger.info(
            "Workspace decision %s created by %s in %s with %d sources",
            plan.id,
            scope.user_id,
            scope.org_id,
            len(rows.sources),
        )
        return rows

    @staticmethod
    def _undo(
        plan_store: Any,
        plan_id: str | None,
        run_id: str | None,
        documents: Any,
        document_ids: list[str],
    ) -> None:
        try:
            if plan_id is not None:
                plan_store.delete(plan_id)
            if run_id:
                plan_store.delete_run(run_id)
            for doc_id in document_ids:
                documents.delete(doc_id)
        except Exception:  # noqa: BLE001 - keep the original failure as the one raised
            logger.exception("Could not undo a failed workspace intake (plan %s)", plan_id)


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
        "omitted_passage_count": decision.omitted_passage_count,
    }


def _run_body(run: RunRecord, *, with_result: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "run_id": run.run_id,
        "status": run.status,
        "debate_id": run.debate_id,
        "agents": list(run.agents),
        "rounds": run.rounds,
        "started_by": run.started_by,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error": run.error,
        "budget_usd": run.budget_usd,
        "cost_actual_usd": run.cost_actual_usd,
        "cost_estimated_usd": run.cost_estimated_usd,
    }
    if with_result:
        body["result"] = run.result
    return body


def _revision_body(revision: RevisionRecord) -> dict[str, Any]:
    return {
        "revision_id": revision.revision_id,
        "number": revision.number,
        "parent_revision_id": revision.parent_revision_id,
        "status": revision.status,
        "origin": revision.origin,
        "author_id": revision.author_id,
        "content": revision.content,
        "content_hash": revision.content_hash,
        "created_at": revision.created_at,
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
