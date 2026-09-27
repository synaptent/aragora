"""FastAPI bridge routes for backup endpoints used by the live admin UI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from aragora.rbac.models import AuthorizationContext
from aragora.server.fastapi.compat import _FakeHandler, _handler_result_to_response
from aragora.server.fastapi.dependencies.auth import require_permission
from aragora.server.handlers.admin.backup_handler import BackupHandler

router = APIRouter(prefix="/api/v2", tags=["Backups"])


def _request_context(request: Request) -> dict[str, object]:
    app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    return getattr(state, "context", None) or {}


def _build_handler(request: Request, auth: AuthorizationContext) -> BackupHandler:
    ctx = _request_context(request)
    handler = BackupHandler(ctx)
    backup_manager: Any = ctx.get("backup_manager")
    if backup_manager is not None:
        handler._manager = backup_manager
    handler._auth_context = auth
    return handler


async def _dispatch(handler: BackupHandler, request: Request) -> Response:
    body = await request.body() if request.method in {"POST", "PUT", "PATCH"} else None
    fake = _FakeHandler(request, body)
    result = await handler.handle(str(request.url.path), dict(request.query_params), fake)
    return _handler_result_to_response(result)


@router.get("/backups")
async def list_backups(
    request: Request,
    auth: AuthorizationContext = Depends(require_permission("backups:read")),
) -> Response:
    return await _dispatch(_build_handler(request, auth), request)


@router.get("/backups/stats")
async def backup_stats(
    request: Request,
    auth: AuthorizationContext = Depends(require_permission("backups:read")),
) -> Response:
    return await _dispatch(_build_handler(request, auth), request)


@router.post("/backups", status_code=201)
async def create_backup(
    request: Request,
    auth: AuthorizationContext = Depends(require_permission("backups:create")),
) -> Response:
    return await _dispatch(_build_handler(request, auth), request)
