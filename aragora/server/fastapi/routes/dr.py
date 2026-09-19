"""FastAPI bridge routes for DR endpoints used by the live admin UI."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from aragora.rbac.models import AuthorizationContext
from aragora.server.fastapi.compat import _FakeHandler, _handler_result_to_response
from aragora.server.fastapi.dependencies.auth import require_permission
from aragora.server.handlers.admin.dr_handler import DRHandler

router = APIRouter(prefix="/api/v2", tags=["Disaster Recovery"])


def _get_context(request: Request) -> dict:
    app = request.scope.get("app")
    return getattr(getattr(app, "state", None), "context", None) or {}


def _build_handler(request: Request, auth: AuthorizationContext) -> DRHandler:
    ctx = _get_context(request)
    handler = DRHandler(ctx)
    backup_manager = ctx.get("backup_manager")
    if backup_manager is not None:
        handler._manager = backup_manager
    handler._auth_context = auth
    return handler


async def _dispatch(handler: DRHandler, request: Request) -> Response:
    body = await request.body() if request.method in {"POST", "PUT", "PATCH"} else None
    fake = _FakeHandler(request, body)
    result = await handler.handle(str(request.url.path), dict(request.query_params), fake)
    return _handler_result_to_response(result)


async def _handle_route(request: Request, auth: AuthorizationContext) -> Response:
    return await _dispatch(_build_handler(request, auth), request)


@router.get("/dr/status")
async def dr_status(
    request: Request,
    auth: AuthorizationContext = Depends(require_permission("dr:read")),
) -> Response:
    return await _handle_route(request, auth)


@router.get("/dr/objectives")
async def dr_objectives(
    request: Request,
    auth: AuthorizationContext = Depends(require_permission("dr:read")),
) -> Response:
    return await _handle_route(request, auth)


@router.post("/dr/drill")
async def dr_drill(
    request: Request,
    auth: AuthorizationContext = Depends(require_permission("dr:drill")),
) -> Response:
    return await _handle_route(request, auth)
