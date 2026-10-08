"""Org scope and permissions for the FastAPI pipeline and canvas pipeline routes.

FastAPI form of :mod:`aragora.tenancy.pipeline_access`. Every route needs a
signed-in caller acting for an org (401 ``auth_required`` / 403
``org_required`` otherwise). Routes on one pipeline or run check that the
caller's org owns it before checking the permission, so another org's record,
an unowned one and a missing one answer the same 404 whatever the caller's
role. Permissions are the canvas keys listed in
:mod:`aragora.tenancy.pipeline_access`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends

from aragora.rbac.models import AuthorizationContext
from aragora.tenancy.pipeline_access import (
    PIPELINE_CREATE,
    PIPELINE_DELETE,
    PIPELINE_READ,
    PIPELINE_RUN,
    PIPELINE_UPDATE,
)
from aragora.tenancy.record_scope import OrgScope, require_org_scope_fastapi

from .auth import check_permission, require_authenticated


@dataclass(frozen=True, slots=True)
class PipelineCaller:
    """A signed-in caller and the org it acts for."""

    auth: AuthorizationContext
    scope: OrgScope

    def owner_fields(self) -> dict[str, str]:
        """Owner columns for a record created on behalf of this caller."""
        return {"org_id": self.scope.org_id, "created_by": self.scope.user_id}


async def require_pipeline_caller(
    auth: AuthorizationContext = Depends(require_authenticated),
    scope: OrgScope = Depends(require_org_scope_fastapi),
) -> PipelineCaller:
    """The caller and its org scope, with no permission checked yet."""
    return PipelineCaller(auth=auth, scope=scope)


def pipeline_permission(permission: str) -> Callable[..., Awaitable[PipelineCaller]]:
    """Dependency for routes that act on no stored record: org scope, then ``permission``."""

    async def dependency(
        caller: PipelineCaller = Depends(require_pipeline_caller),
    ) -> PipelineCaller:
        check_permission(caller.auth, permission)
        return caller

    return dependency


__all__ = [
    "PIPELINE_CREATE",
    "PIPELINE_DELETE",
    "PIPELINE_READ",
    "PIPELINE_RUN",
    "PIPELINE_UPDATE",
    "PipelineCaller",
    "pipeline_permission",
    "require_pipeline_caller",
]
