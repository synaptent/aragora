"""Registers the server's auth and response helpers with :mod:`aragora.tenancy.server_bindings`.

Reached through the ``aragora.tenancy_bindings`` entry point in ``pyproject.toml`` on the
first org-scope lookup in a process. Each helper imports its server module when called,
so installs without the FastAPI extra never import it, and a test that replaces
``aragora.server.auth.auth_config`` is seen on the next call.
"""

from __future__ import annotations

from typing import Any

from aragora.tenancy.server_bindings import ServerBindings, register_server_bindings


def _auth_config() -> Any:
    from aragora.server import auth as server_auth

    return server_auth.auth_config


async def _get_auth_context(request: Any) -> Any:
    from aragora.server.fastapi.dependencies.auth import get_auth_context

    return await get_auth_context(request)


def _api_error(message: str, *, status_code: int, code: str) -> Exception:
    from aragora.server.fastapi.middleware.error_handling import APIError

    return APIError(message, status_code=status_code, code=code)


def _json_response(body: dict[str, Any], *, status: int) -> Any:
    from aragora.server.handlers.utils.responses import json_response

    return json_response(body, status=status)


SERVER_BINDINGS = ServerBindings(
    auth_config=_auth_config,
    get_auth_context=_get_auth_context,
    api_error=_api_error,
    json_response=_json_response,
)


def register_tenancy_bindings() -> None:
    """Register the server bindings; safe to call more than once."""
    register_server_bindings(SERVER_BINDINGS)


__all__ = ["SERVER_BINDINGS", "register_tenancy_bindings"]
