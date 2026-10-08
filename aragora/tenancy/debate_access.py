"""Org scope for reads and writes of a single debate.

Every legacy route that returns data about one debate (by id or slug) asks
:func:`authorize_debate_read` before it reads anything, then reads the debate by
the id it returns. Every route that changes a debate or creates something from
it asks :func:`authorize_debate_write` before it has any effect. The rules
extend :mod:`aragora.tenancy.record_scope`:

* A debate stored with ``is_public = 1`` is readable by anyone, signed in or
  not. Nothing else makes a debate public on these routes. Public grants no
  write: only the owning org may change a public debate.
* Otherwise the caller needs an org scope (401 ``auth_required`` / 403
  ``org_required``), and the debate's ``org_id`` must equal the caller's org.
  Writes always need the org scope, checked before the debate is looked up.
* A missing debate, another org's debate and a debate with no recorded org all
  get the same 404 body.
* A debate that is still running has no stored row yet. Its org comes from the
  server's active-debate registry, where the create path records it.

FastAPI routes use :func:`authorize_debate_read_fastapi` and
:func:`authorize_debate_write_fastapi`, which apply the same rules and raise
the same bodies as ``APIError``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from aragora.tenancy.record_scope import (
    OrgScope,
    record_not_found,
    record_not_found_error,
    record_visible,
    require_org_scope,
    require_org_scope_fastapi,
)

if TYPE_CHECKING:
    from starlette.requests import Request

    from aragora.server.handlers.utils.responses import HandlerResult


@dataclass(frozen=True, slots=True)
class DebateAccess:
    """Who may read a debate: its owning org and whether it is public."""

    debate_id: str
    org_id: str | None
    is_public: bool


def find_debate_access(storage: Any, ref: str) -> DebateAccess | None:
    """Ownership of the debate ``ref`` names (an id, else a slug), or None if unknown.

    Looks at the stored row first and then at debates still running.
    """
    if not isinstance(ref, str) or not ref:
        return None
    getter = getattr(storage, "get_access_info", None) if storage else None
    row = getter(ref) if callable(getter) else None
    if isinstance(row, tuple) and len(row) == 3 and isinstance(row[0], str):
        org_id = row[1] if isinstance(row[1], str) and row[1] else None
        return DebateAccess(debate_id=row[0], org_id=org_id, is_public=bool(row[2]))
    return _running_debate_access(ref)


def debate_visible_to_org(access: DebateAccess | None, org_id: str | None) -> bool:
    """Whether a caller acting for ``org_id`` may read the debate."""
    if access is None:
        return False
    if access.is_public:
        return True
    return isinstance(org_id, str) and bool(org_id) and access.org_id == org_id


def authorize_debate_read(
    handler: Any, storage: Any, ref: str, resource: str = "Debate"
) -> tuple[str, None] | tuple[None, HandlerResult]:
    """``(debate_id, None)`` when the caller may read the debate ``ref`` names, else
    ``(None, error)``.

    ``ref`` is an id or a slug; ``debate_id`` is the id of the debate that was
    authorized. Debate loaders look debates up by id only, so callers must read
    by ``debate_id`` and never by ``ref``.
    """
    access = find_debate_access(storage, ref)
    if access is not None and access.is_public:
        return access.debate_id, None
    scope, denial = require_org_scope(handler)
    if denial is not None:
        return None, denial
    if access is None and not storage:
        from aragora.server.handlers.utils.responses import error_response

        return None, error_response("Storage not available", 503)
    if scope is None or access is None or not debate_visible_to_org(access, scope.org_id):
        return None, record_not_found(resource)
    return access.debate_id, None


@dataclass(frozen=True, slots=True)
class DebateWrite:
    """A write the caller may make: the debate it targets and the caller's scope."""

    debate_id: str
    scope: OrgScope


def authorize_debate_write(
    handler: Any, storage: Any, ref: str, resource: str = "Debate"
) -> tuple[DebateWrite, None] | tuple[None, HandlerResult]:
    """``(write, None)`` when the caller's org owns the debate ``ref`` names, else
    ``(None, error)``.

    For every route that changes a debate or derives a record from it. Being
    public does not let another org (or an anonymous caller) write. Callers act
    on ``write.debate_id`` (never on ``ref``, which may be a slug) and stamp
    ``write.scope.org_id`` on anything they create.
    """
    scope, denial = require_org_scope(handler)
    if denial is not None:
        return None, denial
    access = find_debate_access(storage, ref)
    if access is None and not storage:
        from aragora.server.handlers.utils.responses import error_response

        return None, error_response("Storage not available", 503)
    if scope is None or access is None or not record_visible(access.org_id, scope):
        return None, record_not_found(resource)
    return DebateWrite(debate_id=access.debate_id, scope=scope), None


async def authorize_debate_read_fastapi(
    request: Request, storage: Any, ref: str, resource: str = "Debate"
) -> str:
    """The id of the debate ``ref`` names when the caller may read it, else raise.

    FastAPI form of :func:`authorize_debate_read`: a public debate needs no
    scope; otherwise the scope denial (401/403) or the shared 404 is raised as
    ``APIError``. Read the debate by the returned id, never by ``ref``.
    """
    access = await asyncio.to_thread(find_debate_access, storage, ref)
    if access is not None and access.is_public:
        return access.debate_id
    scope = await require_org_scope_fastapi(request)
    if access is None or not debate_visible_to_org(access, scope.org_id):
        raise record_not_found_error(resource)
    return access.debate_id


async def authorize_debate_write_fastapi(
    scope: OrgScope, storage: Any, ref: str, resource: str = "Debate"
) -> DebateWrite:
    """The write the caller's org may make to the debate ``ref`` names, else raise
    the shared 404.

    FastAPI form of :func:`authorize_debate_write`; ``scope`` comes from the
    ``require_org_scope_fastapi`` dependency, so it is checked before the lookup.
    """
    access = await asyncio.to_thread(find_debate_access, storage, ref)
    if access is None or not record_visible(access.org_id, scope):
        raise record_not_found_error(resource)
    return DebateWrite(debate_id=access.debate_id, scope=scope)


def _running_debate_access(debate_id: str) -> DebateAccess | None:
    try:
        from aragora.server.state import get_state_manager

        state = get_state_manager().get_debate(debate_id)
    except (ImportError, RuntimeError):
        return None
    if state is None:
        return None
    metadata = getattr(state, "metadata", None)
    org_id = metadata.get("org_id") if isinstance(metadata, dict) else None
    return DebateAccess(
        debate_id=debate_id,
        org_id=org_id if isinstance(org_id, str) and org_id else None,
        is_public=False,
    )


__all__ = [
    "DebateAccess",
    "DebateWrite",
    "authorize_debate_read",
    "authorize_debate_read_fastapi",
    "authorize_debate_write",
    "authorize_debate_write_fastapi",
    "debate_visible_to_org",
    "find_debate_access",
]
