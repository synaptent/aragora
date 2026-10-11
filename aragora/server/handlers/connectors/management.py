"""Connector Management REST Endpoints.

Provides a :class:`BaseHandler` subclass that exposes the runtime connector
registry over HTTP so that operators and dashboards can discover, inspect,
and health-check connectors without direct Python access.

Routes handled (prefix ``/api/v1/connectors``):
    GET  /                   - List all connectors (optional ``?type=`` filter)
    GET  /summary            - Aggregated health summary
    GET  /<name>             - Single connector detail
    GET  /<name>/health      - Run health check for a connector
    POST /<name>/test        - Test connector connectivity

Phase Y: Connector Consolidation.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from aragora.connectors.runtime_registry import (
    ConnectorRegistry,
    ConnectorStatus,
    get_connector_registry,
)
from aragora.rbac.checker import get_permission_checker
from aragora.rbac.models import AuthorizationContext
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)

logger = logging.getLogger(__name__)

# Only allow alphanumeric + underscore for connector names in URL paths.
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")

# Prefix for all routes this handler owns.
_PREFIX = "/api/v1/connectors"


class ConnectorManagementHandler(BaseHandler):
    """REST interface to the unified connector runtime registry."""

    def __init__(self, server_context: dict[str, Any] | None = None) -> None:
        # BaseHandler.__init__ expects a context dict; fall back to empty.
        super().__init__(server_context or {})
        self._registry: ConnectorRegistry | None = None

    def can_handle(self, path: str) -> bool:
        return path.startswith(_PREFIX)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_registry(self) -> ConnectorRegistry:
        """Lazily obtain the global registry singleton."""
        if self._registry is None:
            self._registry = get_connector_registry()
        return self._registry

    @staticmethod
    def _validate_name(name: str) -> HandlerResult | None:
        """Return an error response if *name* is invalid, else ``None``."""
        if not name or not _SAFE_NAME_RE.match(name):
            return error_response(f"Invalid connector name: {name!r}", 400)
        return None

    @staticmethod
    def _check_rbac_permission(user: Any, permission: str) -> HandlerResult | None:
        """Authorize with the RBAC v2 checker, building the context as ConnectorsHandler does."""
        role = getattr(user, "role", None)
        context = AuthorizationContext(
            user_id=user.user_id,
            user_email=getattr(user, "email", None),
            org_id=getattr(user, "org_id", None),
            roles={role} if role else {"member"},
        )
        if not get_permission_checker().check_permission(context, permission).allowed:
            return error_response("Permission denied", 403)
        return None

    @staticmethod
    def _not_a_runtime_name(name: str) -> HandlerResult | None:
        """Answer 501 for ids the runtime registry cannot hold, such as stored connectors' UUIDs."""
        if _SAFE_NAME_RE.match(name):
            return None
        return error_response(
            "Health checks and tests for stored connectors are not implemented",
            501,
            code="not_implemented",
        )

    # ------------------------------------------------------------------
    # GET routing
    # ------------------------------------------------------------------

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests under ``/api/v1/connectors``."""
        if not path.startswith(_PREFIX):
            return None

        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        sub = path[len(_PREFIX) :]
        # Strip leading slash for further matching.
        parts = sub.lstrip("/").split("/")
        name = parts[0]

        # GET /api/v1/connectors/<name>/health
        if len(parts) == 2 and parts[1] == "health":
            if perm_err := self._check_rbac_permission(user, "connectors:read"):
                return perm_err
            if unsupported := self._not_a_runtime_name(name):
                return unsupported
            return self._handle_health(name)

        # GET /api/v1/connectors/summary
        if sub == "/summary":
            if perm_err := self._check_rbac_permission(user, "connectors:read"):
                return perm_err
            return self._handle_summary()

        _, perm_err = self.require_permission_or_error(handler, "connectors:read")
        if perm_err:
            return perm_err

        # GET /api/v1/connectors  or  /api/v1/connectors/
        if sub in ("", "/"):
            return self._handle_list(query_params)

        # GET /api/v1/connectors/<name>
        if len(parts) == 1:
            return self._handle_detail(name)

        return None

    # ------------------------------------------------------------------
    # POST routing
    # ------------------------------------------------------------------

    @handle_errors("connector management creation")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route POST requests under ``/api/v1/connectors``."""
        if not path.startswith(_PREFIX):
            return None

        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        sub = path[len(_PREFIX) :]
        parts = sub.lstrip("/").split("/")

        # POST /api/v1/connectors/<name>/test
        if len(parts) == 2 and parts[1] == "test":
            if perm_err := self._check_rbac_permission(user, "connectors:test"):
                return perm_err
            if unsupported := self._not_a_runtime_name(parts[0]):
                return unsupported
            headers = getattr(handler, "headers", None)
            content_length = 0
            if isinstance(headers, Mapping):
                try:
                    content_length = int(headers.get("Content-Length", 0))
                except (TypeError, ValueError):
                    content_length = 0

            request = getattr(handler, "request", None)
            has_explicit_body = any(
                isinstance(raw_body, (bytes, bytearray, str))
                for raw_body in (
                    getattr(handler, "body", None),
                    getattr(request, "body", None) if request is not None else None,
                )
            )

            if has_explicit_body or content_length > 0:
                _, body_error = self.read_json_object_or_error(handler)
                if body_error:
                    return body_error
            return self._handle_test(parts[0])

        _, perm_err = self.require_permission_or_error(handler, "connectors:test")
        return perm_err

    # ------------------------------------------------------------------
    # Endpoint implementations
    # ------------------------------------------------------------------

    def _handle_list(self, query_params: dict[str, Any]) -> HandlerResult:
        """GET /api/v1/connectors — list all (optionally filtered by type)."""
        registry = self._get_registry()
        connector_type = query_params.get("type")
        status_filter = query_params.get("status")

        if connector_type:
            connectors = registry.list_by_type(str(connector_type))
        else:
            connectors = registry.list_all()

        if status_filter:
            try:
                status_enum = ConnectorStatus(str(status_filter))
                connectors = [c for c in connectors if c.status == status_enum]
            except ValueError:
                return error_response(
                    f"Invalid status filter: {status_filter!r}. "
                    f"Valid values: {', '.join(s.value for s in ConnectorStatus)}",
                    400,
                )

        return json_response(
            {
                "connectors": [c.to_dict() for c in connectors],
                "total": len(connectors),
            }
        )

    def _handle_summary(self) -> HandlerResult:
        """GET /api/v1/connectors/summary — aggregated health overview."""
        registry = self._get_registry()
        return json_response(registry.get_summary())

    def _handle_detail(self, name: str) -> HandlerResult:
        """GET /api/v1/connectors/<name> — single connector detail."""
        err = self._validate_name(name)
        if err is not None:
            return err

        registry = self._get_registry()
        info = registry.get(name)
        if info is None:
            return error_response(f"Connector not found: {name}", 404)

        return json_response(info.to_dict())

    def _handle_health(self, name: str) -> HandlerResult:
        """GET /api/v1/connectors/<name>/health — run live health check."""
        err = self._validate_name(name)
        if err is not None:
            return err

        registry = self._get_registry()
        info = registry.get(name)
        if info is None:
            return error_response(f"Connector not found: {name}", 404)

        status = registry.health_check(name)
        # Re-fetch to get updated info after health check.
        info = registry.get(name)
        return json_response(
            {
                "name": name,
                "status": status.value,
                "last_health_check": info.last_health_check if info else None,
                "metadata": info.metadata if info else {},
            }
        )

    def _handle_test(self, name: str) -> HandlerResult:
        """POST /api/v1/connectors/<name>/test — test connectivity.

        Runs a health check and returns a richer diagnostic payload.
        """
        err = self._validate_name(name)
        if err is not None:
            return err

        registry = self._get_registry()
        info = registry.get(name)
        if info is None:
            return error_response(f"Connector not found: {name}", 404)

        status = registry.health_check(name)
        info = registry.get(name)

        result: dict[str, Any] = {
            "name": name,
            "connector_type": info.connector_type if info else "unknown",
            "status": status.value,
            "importable": info.metadata.get("importable", False) if info else False,
            "capabilities": info.capabilities if info else [],
            "last_health_check": info.last_health_check if info else None,
        }

        if status == ConnectorStatus.UNHEALTHY:
            result["error"] = (
                info.metadata.get("import_error", "Unknown error") if info else "Unknown error"
            )

        if status == ConnectorStatus.DEGRADED:
            result["warning"] = (
                info.metadata.get("health_error", "Degraded") if info else "Degraded"
            )

        return json_response(result)
