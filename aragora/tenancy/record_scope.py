"""Org scope for tenant-owned records.

The one implementation of "which organization is this caller acting for, and
may it see this record" used by legacy handlers, FastAPI routes and background
tasks for plans, plan executions, backbone runs, documents, receipts, debates
and pipeline runs.

Rules:

* The caller's org comes from the authenticated user (JWT ``org_id`` claim, or
  the user behind a user API key). No authenticated user -> 401
  ``auth_required``. An authenticated user without an org -> 403
  ``org_required``. A request carrying only the static ``ARAGORA_API_TOKEN``
  (or a token signed with it) has no user and therefore no org -> 403
  ``org_required``.
* None of this depends on whether ``ARAGORA_API_TOKEN`` is configured. Unlike
  ``aragora.rbac.decorators.require_permission``, nothing here allows anonymous
  access when the static token is unset.
* A record is visible only when its ``org_id`` is non-empty and equals the
  caller's org. Records with an unknown (null) owner are visible to nobody.
* Another org's record and an unknown-owner record get exactly the same 404 as
  a missing record, so a response never reveals that a record exists.

Usage (legacy handler)::

    scope, err = require_org_scope(handler)
    if err:
        return err
    plan = store.get(plan_id)
    if plan is None or not record_visible(plan.org_id, scope):
        return record_not_found("Plan")

Usage (FastAPI route)::

    @router.get("/receipts/{receipt_id}")
    async def get_receipt(
        receipt_id: str, scope: OrgScope = Depends(require_org_scope_fastapi)
    ):
        receipt = store.get(receipt_id)
        if receipt is None or not record_visible(receipt.org_id, scope):
            raise record_not_found_error("Receipt")
"""

from __future__ import annotations

import hmac
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starlette.requests import Request

    from aragora.server.fastapi.middleware.error_handling import APIError
    from aragora.server.handlers.utils.responses import HandlerResult
else:
    # FastAPI resolves the dependency's ``request: Request`` annotation at
    # runtime, but legacy handlers import this module on installs without the
    # optional gateway extra (fastapi/starlette).
    try:
        from starlette.requests import Request
    except ImportError:  # pragma: no cover - exercised only without the gateway extra
        Request = Any

AUTH_REQUIRED_CODE = "auth_required"
ORG_REQUIRED_CODE = "org_required"
NOT_FOUND_CODE = "not_found"

_ANONYMOUS_USER_ID = "anonymous"


@dataclass(frozen=True, slots=True)
class OrgScope:
    """The organization a caller acts for, with the user and role behind it."""

    org_id: str
    user_id: str
    role: str

    def __post_init__(self) -> None:
        if not isinstance(self.org_id, str) or not self.org_id.strip():
            raise ValueError("OrgScope requires a non-empty org_id")


@dataclass(frozen=True, slots=True)
class ScopeDenial:
    """Why a request has no org scope, as an HTTP status and error body."""

    status: int
    code: str
    message: str

    def body(self) -> dict[str, str]:
        return {"error": self.message, "code": self.code}


AUTH_REQUIRED = ScopeDenial(401, AUTH_REQUIRED_CODE, "Authentication required")
ORG_REQUIRED = ScopeDenial(
    403,
    ORG_REQUIRED_CODE,
    "This resource belongs to an organization; sign in as a member of one",
)


def record_visible(record_org_id: str | None, scope: OrgScope | None) -> bool:
    """Return True only when the record has a known owner equal to the caller's org."""
    if scope is None or not isinstance(record_org_id, str) or not record_org_id:
        return False
    return record_org_id == scope.org_id


def resolve_org_scope(
    *,
    user_id: str | None,
    org_id: str | None,
    role: str | None,
    static_token: bool,
) -> OrgScope | ScopeDenial:
    """Decide the scope for an identity; shared by every entry point.

    ``user_id`` is None when no user is authenticated. ``static_token`` says
    whether the request carried the static API token (only consulted then).
    """
    if not isinstance(user_id, str) or not user_id:
        return ORG_REQUIRED if static_token else AUTH_REQUIRED
    if not isinstance(org_id, str) or not org_id.strip():
        return ORG_REQUIRED
    return OrgScope(
        org_id=org_id,
        user_id=user_id,
        role=role if isinstance(role, str) and role else "member",
    )


def carries_static_api_token(headers: Any) -> bool:
    """Whether the Authorization header holds the configured static API token.

    Tokens signed with the static token (``AuthConfig.generate_token``) count
    too: the server's token gate admits both without identifying a user.
    """
    token = _bearer_token(headers)
    if not token:
        return False

    from aragora.server import auth as server_auth

    config = server_auth.auth_config
    api_token = getattr(config, "api_token", None)
    if not isinstance(api_token, str) or not api_token:
        return False
    if hmac.compare_digest(token.encode("utf-8"), api_token.encode("utf-8")):
        return True
    return config.validate_token(token) is True


def require_org_scope(
    handler: Any, user_store: Any | None = None
) -> tuple[OrgScope, None] | tuple[None, HandlerResult]:
    """Legacy-handler entry point: ``(scope, None)`` or ``(None, error_result)``.

    ``handler`` is the HTTP request handler. ``user_store`` resolves user API
    keys and defaults to ``handler.user_store`` when present.
    """
    from aragora.billing.jwt_auth import extract_user_from_request

    if user_store is None:
        user_store = getattr(handler, "user_store", None)
    user = extract_user_from_request(handler, user_store)
    authenticated = bool(getattr(user, "is_authenticated", False))
    outcome = resolve_org_scope(
        user_id=getattr(user, "user_id", None) if authenticated else None,
        org_id=getattr(user, "org_id", None),
        role=getattr(user, "role", None),
        static_token=(
            not authenticated and carries_static_api_token(getattr(handler, "headers", None))
        ),
    )
    if isinstance(outcome, OrgScope):
        return outcome, None
    return None, _denial_result(outcome)


async def require_org_scope_fastapi(request: Request) -> OrgScope:
    """FastAPI dependency with the same semantics as :func:`require_org_scope`.

    Identity comes from ``aragora.server.fastapi.dependencies.auth.get_auth_context``.
    Denials are raised as ``APIError`` so the app's exception handler renders
    the same ``{"error", "code"}`` body as the legacy helper.
    """
    from aragora.server.fastapi.dependencies.auth import get_auth_context
    from aragora.server.fastapi.middleware.error_handling import APIError

    auth = await get_auth_context(request)
    user_id = auth.user_id if auth.user_id != _ANONYMOUS_USER_ID else None
    outcome = resolve_org_scope(
        user_id=user_id,
        org_id=auth.org_id,
        role=_primary_role(auth.roles),
        static_token=user_id is None and carries_static_api_token(request.headers),
    )
    if isinstance(outcome, ScopeDenial):
        raise APIError(outcome.message, status_code=outcome.status, code=outcome.code)
    return outcome


def not_found_body(resource: str = "Record") -> dict[str, str]:
    """The not-found body; deliberately carries no record id, owner or content."""
    return {"error": f"{resource} not found", "code": NOT_FOUND_CODE}


def record_not_found(resource: str = "Record") -> HandlerResult:
    """Legacy 404 for a missing, other-org or unknown-owner record."""
    from aragora.server.handlers.utils.responses import json_response

    return json_response(not_found_body(resource), status=404)


def record_not_found_error(resource: str = "Record") -> APIError:
    """FastAPI 404 (to ``raise``) for a missing, other-org or unknown-owner record."""
    from aragora.server.fastapi.middleware.error_handling import APIError

    body = not_found_body(resource)
    return APIError(body["error"], status_code=404, code=body["code"])


def _denial_result(denial: ScopeDenial) -> HandlerResult:
    from aragora.server.handlers.utils.responses import json_response

    return json_response(denial.body(), status=denial.status)


def _bearer_token(headers: Any) -> str | None:
    if headers is None or not hasattr(headers, "get"):
        return None
    value = headers.get("Authorization", "")
    if not isinstance(value, str) or not value.startswith("Bearer "):
        return None
    return value[7:] or None


def _primary_role(roles: Iterable[str] | None) -> str:
    candidates = {role for role in roles or () if isinstance(role, str) and role}
    for role in ("owner", "admin"):
        if role in candidates:
            return role
    return min(candidates) if candidates else "member"


__all__ = [
    "AUTH_REQUIRED",
    "AUTH_REQUIRED_CODE",
    "NOT_FOUND_CODE",
    "ORG_REQUIRED",
    "ORG_REQUIRED_CODE",
    "OrgScope",
    "ScopeDenial",
    "carries_static_api_token",
    "not_found_body",
    "record_not_found",
    "record_not_found_error",
    "record_visible",
    "require_org_scope",
    "require_org_scope_fastapi",
    "resolve_org_scope",
]
