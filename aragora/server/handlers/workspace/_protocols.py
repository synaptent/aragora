"""
Protocol stubs describing the cross-mixin host contract for workspace handlers.

Each of the workspace handler modules (``crud``, ``policies``, ``members``,
``invites``, ``settings``) defines a ``*Mixin`` class that is combined into
the concrete :class:`aragora.server.handlers.workspace.workspace_module.WorkspaceHandler`
together with :class:`aragora.server.handlers.secure.SecureHandler`.  At
runtime the ``self`` of any of those mixins is the fully assembled handler,
which is why it is safe to call accessors like ``self._get_audit_log()``
from within the mixin even though the method itself is defined on the
concrete handler (or on a sibling mixin).

mypy cannot see that cross-mixin relationship from the isolated mixin class,
so it raises ``attr-defined`` errors on every access.  The
:class:`WorkspaceMixinHost` protocol below captures the contract the mixins
expect from their host class.  Each mixin then re-declares the relevant
members under ``if TYPE_CHECKING:`` -- which mirrors this protocol -- to let
mypy resolve those attribute accesses without changing runtime behaviour.

The protocol and the TYPE_CHECKING stubs are purely type-level.  Nothing
here is imported at runtime (see the ``TYPE_CHECKING`` guard below), so
there is zero runtime impact and no new import cycles.

Stability: STABLE
"""

from __future__ import annotations

from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from aragora.billing.auth.context import UserAuthContext
    from aragora.privacy import (
        DataIsolationManager,
        PrivacyAuditLog,
        RetentionPolicyManager,
        SensitivityClassifier,
    )
    from aragora.protocols import HTTPRequestHandler
    from aragora.server.handlers.base import HandlerResult


T = TypeVar("T")


class WorkspaceMixinHost(Protocol):
    """Cross-mixin contract for workspace handler mixin classes.

    The concrete handler
    (:class:`aragora.server.handlers.workspace.workspace_module.WorkspaceHandler`)
    satisfies this protocol through a combination of methods defined on it
    directly and methods inherited from
    :class:`aragora.server.handlers.secure.SecureHandler` (via
    ``SecureHandler`` -> :class:`aragora.server.handlers.base.BaseHandler`).

    Mixins in this package should *not* inherit from this protocol at
    runtime; they re-declare the members they use under ``TYPE_CHECKING``
    so the runtime MRO is unchanged.
    """

    # -- Subsystem accessors (defined on WorkspaceHandler) --------------
    def _get_user_store(self) -> Any: ...

    def _get_isolation_manager(self) -> DataIsolationManager: ...

    def _get_retention_manager(self) -> RetentionPolicyManager: ...

    def _get_classifier(self) -> SensitivityClassifier: ...

    def _get_audit_log(self) -> PrivacyAuditLog: ...

    # -- Async adapter ---------------------------------------------------
    def _run_async(self, coro: Coroutine[Any, Any, T]) -> T: ...

    # -- RBAC helper -----------------------------------------------------
    def _check_rbac_permission(
        self,
        handler: HTTPRequestHandler,
        permission_key: str,
        auth_ctx: UserAuthContext | None = ...,
    ) -> HandlerResult | None: ...

    # -- Request-body helper (inherited from SecureHandler / BaseHandler)
    def read_json_body(
        self,
        handler: Any,
        max_size: int | None = ...,
    ) -> dict[str, Any] | None: ...


__all__ = ["WorkspaceMixinHost"]
