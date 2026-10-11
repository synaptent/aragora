"""The HTTP server pieces that the org-scope helpers in record_scope call.

``aragora.tenancy`` sits in the infrastructure layer and must not import the server
package (interface layer), which owns the static API token configuration, the FastAPI
auth context and error type, and the legacy JSON response. The server registers one
:class:`ServerBindings` here and record_scope looks it up at call time.

A process that has not loaded the server yet still reaches it: the first lookup that
finds nothing registered runs, once per process, the registrations declared under the
``aragora.tenancy_bindings`` entry-point group in aragora's ``pyproject.toml``.
:func:`get_server_bindings` raises :class:`ServerBindingsNotRegisteredError` when
nothing is registered after that. A later registration replaces the earlier one.
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
    """What the org-scope helpers need from the server.

    ``auth_config()`` returns the current static-token auth config (``api_token`` and
    ``validate_token``); ``get_auth_context(request)`` resolves a FastAPI request's
    identity (``user_id``, ``org_id``, ``roles``); ``api_error(message, *, status_code,
    code)`` builds the exception the FastAPI app renders as ``{"error", "code"}``;
    ``json_response(body, *, status)`` builds a legacy handler result.
    """

    auth_config: Callable[[], Any]
    get_auth_context: Callable[[Any], Awaitable[Any]]
    api_error: Callable[..., Any]
    json_response: Callable[..., Any]


_bindings: ServerBindings | None = None
_declared = DeclaredRegistrations(TENANCY_BINDINGS_ENTRY_POINT_GROUP)


def register_server_bindings(bindings: ServerBindings) -> None:
    """Make ``bindings`` the server implementation, replacing any earlier one."""
    global _bindings
    _bindings = bindings


def get_server_bindings() -> ServerBindings:
    """Return the registered bindings, running the declared registrations on first miss."""
    bindings = _bindings
    if bindings is None:
        _declared.load()
        bindings = _bindings
    if bindings is None:
        raise ServerBindingsNotRegisteredError(
            "no server bindings are registered for the org-scope helpers; the server "
            "package registers them through the "
            f"{TENANCY_BINDINGS_ENTRY_POINT_GROUP!r} entry-point group"
        )
    return bindings


__all__ = [
    "TENANCY_BINDINGS_ENTRY_POINT_GROUP",
    "ServerBindings",
    "ServerBindingsNotRegisteredError",
    "get_server_bindings",
    "register_server_bindings",
]
