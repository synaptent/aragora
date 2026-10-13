"""The HTTP server pieces that the org-scope helpers in record_scope call.

aragora.tenancy (infrastructure layer) must not import the server package (interface
layer), so the server registers one :class:`ServerBindings` here. The first lookup that
finds none runs, once per process, the registrations declared under the
``aragora.tenancy_bindings`` entry-point group in aragora's ``pyproject.toml``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from aragora.utils.declared_registrations import DeclaredRegistrations

TENANCY_BINDINGS_ENTRY_POINT_GROUP = "aragora.tenancy_bindings"


class ServerBindingsNotRegisteredError(RuntimeError):
    """The org-scope helpers were used before the server registered its bindings."""


@dataclass(frozen=True, slots=True)
class ServerBindings:
    # () -> the current static-token config (api_token, validate_token)
    auth_config: Callable[[], Any]
    # (request) -> the FastAPI caller identity (user_id, org_id, roles)
    get_auth_context: Callable[[Any], Awaitable[Any]]
    # (message, *, status_code, code) -> the exception the FastAPI app renders as {error, code}
    api_error: Callable[..., Any]
    # (body, *, status) -> a legacy handler result
    json_response: Callable[..., Any]


_bindings: ServerBindings | None = None
_declared = DeclaredRegistrations(TENANCY_BINDINGS_ENTRY_POINT_GROUP)


def register_server_bindings(bindings: ServerBindings) -> None:
    """Make ``bindings`` the server implementation, replacing any earlier one."""
    global _bindings
    _bindings = bindings


def get_server_bindings() -> ServerBindings:
    """Return the registered bindings, running the declared registrations on the first miss."""
    if _bindings is None:
        _declared.load()
    if _bindings is None:
        raise ServerBindingsNotRegisteredError(
            "no server bindings are registered for the org-scope helpers; the server "
            f"registers them through the {TENANCY_BINDINGS_ENTRY_POINT_GROUP!r} entry-point group"
        )
    return _bindings
