"""Org scope and permissions for pipelines and pipeline graphs on legacy routes.

The canvas pipeline, pipeline execute, transitions, DAG and universal graph
handlers answer the same way through these helpers. The rules extend
:mod:`aragora.tenancy.record_scope`:

* :func:`authorize_pipeline_request` resolves the caller's org scope (401
  ``auth_required`` / 403 ``org_required``) and then checks one RBAC
  permission for the caller's role. Any failure of the permission checker
  denies with 403; an unavailable checker never lets a request through.
* :func:`record_owned` says whether the caller's org owns a pipeline (in
  ``PipelineResultStore``) or a graph (in ``GraphStore``). Missing, other-org
  and unknown-owner records all answer False, and handlers return
  :func:`~aragora.tenancy.record_scope.record_not_found` for each of them.
  :func:`graph_owned` and :func:`pipeline_owned` answer the same question
  against the shared stores for routes that only have an id.

There are no ``pipeline:*`` permissions in the role catalog, so pipeline
routes check the canvas permissions every org role already holds: reading
needs ``canvas:read``, creating ``canvas:create``, running, advancing or
approving ``canvas:run``, editing a saved pipeline or graph ``canvas:update``
and deleting ``canvas:delete``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aragora.tenancy.record_scope import OrgScope, record_visible, require_org_scope

if TYPE_CHECKING:
    from aragora.server.handlers.utils.responses import HandlerResult

logger = logging.getLogger(__name__)

PIPELINE_READ = "canvas:read"
PIPELINE_CREATE = "canvas:create"
PIPELINE_RUN = "canvas:run"
PIPELINE_UPDATE = "canvas:update"
PIPELINE_DELETE = "canvas:delete"

PERMISSION_DENIED_CODE = "permission_denied"


def check_pipeline_permission(scope: OrgScope, permission: str) -> HandlerResult | None:
    """None when the caller's role grants ``permission``, else a 403 response.

    Errors while importing or consulting the permission checker deny.
    """
    try:
        from aragora.rbac.checker import get_permission_checker
        from aragora.rbac.models import AuthorizationContext

        context = AuthorizationContext(
            user_id=scope.user_id,
            org_id=scope.org_id,
            roles={scope.role},
        )
        decision = get_permission_checker().check_permission(context, permission)
        allowed = getattr(decision, "allowed", False) is True
    except Exception as exc:  # noqa: BLE001 - any checker failure must deny, never allow
        logger.warning(
            "Permission check for %s failed; denying: %s", permission, type(exc).__name__
        )
        allowed = False
    if allowed:
        return None
    from aragora.server.handlers.utils.responses import json_response

    return json_response({"error": "Permission denied", "code": PERMISSION_DENIED_CODE}, status=403)


def authorize_pipeline_request(
    handler: Any, permission: str
) -> tuple[OrgScope, None] | tuple[None, HandlerResult]:
    """``(scope, None)`` when the caller has an org and ``permission``, else ``(None, error)``."""
    scope, denial = require_org_scope(handler)
    if scope is None:
        return None, denial
    denial = check_pipeline_permission(scope, permission)
    if denial is not None:
        return None, denial
    return scope, None


def store_owner_org(store: Any, record_id: str) -> str | None:
    """The owning org ``store.get_owner_org`` reports for ``record_id``, if any."""
    getter = getattr(store, "get_owner_org", None)
    if not callable(getter) or not isinstance(record_id, str) or not record_id:
        return None
    owner = getter(record_id)
    return owner if isinstance(owner, str) and owner else None


def record_owned(store: Any, record_id: str, scope: OrgScope | None) -> bool:
    """Whether ``record_id`` exists in ``store`` and belongs to the caller's org."""
    return record_visible(store_owner_org(store, record_id), scope)


def graph_owned(graph_id: str, scope: OrgScope | None, store: Any | None = None) -> bool:
    """Whether the caller's org owns the graph ``graph_id``.

    ``store`` defaults to the shared graph store. Store errors answer False.
    """
    try:
        if store is None:
            from aragora.pipeline.graph_store import get_graph_store

            store = get_graph_store()
        return record_owned(store, graph_id, scope)
    except Exception as exc:  # noqa: BLE001 - an unreadable owner must hide the graph
        logger.warning("Graph owner lookup failed; denying: %s", type(exc).__name__)
        return False


def pipeline_owned(pipeline_id: str, scope: OrgScope | None) -> bool:
    """Whether the caller's org owns the pipeline ``pipeline_id``.

    When the graph store holds a graph with this id, that graph's owner
    decides, because pipeline execution reads its nodes from the graph; a
    saved pipeline of the same id cannot vouch for someone else's graph.
    Otherwise the saved pipeline's owner decides. Store errors answer False.
    """
    try:
        from aragora.pipeline.graph_store import get_graph_store
        from aragora.storage.pipeline_store import get_pipeline_store

        graph_store = get_graph_store()
        if graph_store.get(pipeline_id) is not None:
            return record_owned(graph_store, pipeline_id, scope)
        return record_owned(get_pipeline_store(), pipeline_id, scope)
    except Exception as exc:  # noqa: BLE001 - an unreadable owner must hide the pipeline
        logger.warning("Pipeline owner lookup failed; denying: %s", type(exc).__name__)
        return False


__all__ = [
    "PERMISSION_DENIED_CODE",
    "PIPELINE_CREATE",
    "PIPELINE_DELETE",
    "PIPELINE_READ",
    "PIPELINE_RUN",
    "PIPELINE_UPDATE",
    "authorize_pipeline_request",
    "check_pipeline_permission",
    "graph_owned",
    "pipeline_owned",
    "record_owned",
    "store_owner_org",
]
