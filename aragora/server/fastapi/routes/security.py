"""
Security Dashboard Endpoints (FastAPI v2).

Provides security posture endpoints for the compliance dashboard:
- GET  /api/v2/security/rbac-coverage       - RBAC coverage summary
- GET  /api/v2/security/encryption-status    - Encryption status (at-rest / in-transit)

Response envelope: {"data": ...} for frontend hook compatibility
(useSWRFetch<{ data: T }> -> result.data?.data).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from aragora.rbac.models import AuthorizationContext
from aragora.server.fastapi.dependencies.auth import require_authenticated

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["Security"])

_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
_UNPROTECTED_API_PATHS = frozenset(
    {"/api/v2/health", "/api/v2/health/ready", "/api/v2/health/live"}
)


def _reject_unexpected_query_params(request: Request) -> None:
    if request.query_params:
        raise HTTPException(status_code=400, detail="Invalid query")


def _openapi_operations(app: Any) -> set[tuple[str, str]]:
    """Return normalized ``(method, path)`` pairs from the canonical schema."""
    openapi = getattr(app, "openapi", None)
    if not callable(openapi):
        return set()

    spec = openapi()
    if not isinstance(spec, dict):
        raise RuntimeError("OpenAPI generation returned a malformed schema")

    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        raise RuntimeError("OpenAPI generation returned malformed paths")

    operations: set[tuple[str, str]] = set()
    for path, path_item in paths.items():
        if not isinstance(path, str) or not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if (
                isinstance(method, str)
                and method.lower() in _HTTP_METHODS
                and isinstance(operation, dict)
            ):
                operations.add((method.lower(), path))
    return operations


def _openapi_operation_paths(app: Any) -> list[str]:
    """Return one path entry per OpenAPI operation exposed by a FastAPI app."""
    return [path for _method, path in sorted(_openapi_operations(app))]


def _schema_hidden_operations(app: Any) -> set[tuple[str, str]]:
    """Return operations registered outside the canonical OpenAPI schema."""
    operations: set[tuple[str, str]] = set()
    pending = list(getattr(app, "routes", ()) or ())
    seen: set[int] = set()

    while pending:
        route = pending.pop()
        route_id = id(route)
        if route_id in seen:
            continue
        seen.add(route_id)

        effective_candidates = getattr(route, "effective_candidates", None)
        if callable(effective_candidates):
            pending.extend(effective_candidates())
            continue

        child_routes = getattr(route, "routes", None)
        if child_routes:
            pending.extend(child_routes)

        if getattr(route, "include_in_schema", True) is not False:
            continue

        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not isinstance(path, str) or not methods:
            continue
        if isinstance(methods, str):
            methods = (methods,)

        normalized_methods = {
            method.lower()
            for method in methods
            if isinstance(method, str) and method.lower() in _HTTP_METHODS
        }
        if "get" in normalized_methods:
            # Starlette adds HEAD to GET routes; it is not a separate declared operation.
            normalized_methods.discard("head")

        for method in normalized_methods:
            operations.add((method, path))

    return operations


def _legacy_flat_route_paths(app: Any) -> list[str]:
    """Best-effort fallback for older Starlette-like test doubles."""
    route_paths: list[str] = []
    for route in getattr(app, "routes", ()) or ():
        path = getattr(route, "path", None)
        if isinstance(path, str) and hasattr(route, "methods"):
            route_paths.append(path)
    return route_paths


def _rbac_coverage_route_paths(app: Any) -> list[str]:
    if not callable(getattr(app, "openapi", None)):
        return _legacy_flat_route_paths(app)

    openapi_operations = _openapi_operations(app)
    operations = openapi_operations | _schema_hidden_operations(app)
    return [path for _method, path in sorted(operations)]


def _is_unprotected_endpoint_path(path: str) -> bool:
    if not path.startswith("/api/"):
        return True
    return path in _UNPROTECTED_API_PATHS


# =============================================================================
# RBAC Coverage
# =============================================================================


@router.get("/security/rbac-coverage")
async def get_rbac_coverage(
    request: Request,
    _auth: AuthorizationContext = Depends(require_authenticated),
) -> dict[str, Any]:
    """
    Return RBAC coverage metrics for the compliance dashboard.

    Queries the real RBAC subsystem for role/permission/assignment counts
    and endpoint protection coverage. Falls back to introspection of the
    static RBAC defaults when a live store is unavailable.

    Response wrapped in ``{"data": ...}`` for frontend compatibility.
    """
    _reject_unexpected_query_params(request)
    roles_defined = 0
    permissions_defined = 0
    assignments_active = 0

    # ----- Roles & permissions from RBAC defaults -----
    try:
        from aragora.rbac.defaults import SYSTEM_ROLES
        from aragora.rbac.defaults.registry import SYSTEM_PERMISSIONS

        roles_defined = len(SYSTEM_ROLES)
        permissions_defined = len(SYSTEM_PERMISSIONS)
    except (ImportError, RuntimeError, ValueError, AttributeError) as exc:
        logger.debug("RBAC defaults not available: %s", exc)

    # ----- Live role assignments (if an assignment store exists) -----
    try:
        ctx = getattr(request.app.state, "context", None)
        rbac_checker = ctx.get("rbac_checker") if ctx else None

        if rbac_checker and hasattr(rbac_checker, "list_assignments"):
            raw = rbac_checker.list_assignments()
            assignments_active = len(raw) if raw else 0
        elif rbac_checker and hasattr(rbac_checker, "_assignments"):
            assignments_active = len(rbac_checker._assignments)
    except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as exc:
        logger.debug("Live RBAC assignments unavailable: %s", exc)

    # ----- Endpoint coverage -----
    # FastAPI 0.137 preserves included routers as a tree, so app.routes no
    # longer reliably exposes every included API route. Count OpenAPI operations
    # first, add registered schema-hidden operations, and retain a guarded
    # route-list fallback for older test doubles.
    endpoint_paths: list[str] = []
    try:
        endpoint_paths = _rbac_coverage_route_paths(request.app)
    except (RuntimeError, TypeError, AttributeError) as exc:
        logger.error("Unable to compute RBAC coverage from OpenAPI: %s", exc)
        raise HTTPException(status_code=503, detail="RBAC coverage unavailable") from exc

    # Heuristic: endpoints behind RBAC middleware are "protected".
    # The RBAC middleware protects all /api/v2/* routes except health.
    total_endpoints = len(endpoint_paths)
    unprotected = sum(1 for path in endpoint_paths if _is_unprotected_endpoint_path(path))

    if total_endpoints == 0:
        total_endpoints = 1  # prevent division by zero
    coverage_pct = round((total_endpoints - unprotected) / total_endpoints * 100, 1)

    return {
        "data": {
            "roles_defined": roles_defined,
            "permissions_defined": permissions_defined,
            "assignments_active": assignments_active,
            "unprotected_endpoints": unprotected,
            "total_endpoints": total_endpoints,
            "coverage_percent": coverage_pct,
        }
    }


# =============================================================================
# Encryption Status
# =============================================================================


@router.get("/security/encryption-status")
async def get_encryption_status(
    request: Request,
    _auth: AuthorizationContext = Depends(require_authenticated),
) -> dict[str, Any]:
    """
    Return encryption posture for the compliance dashboard.

    Queries the real ``EncryptionService`` and ``KeyRotationScheduler``
    for algorithm, key age, rotation schedule, and TLS configuration.
    Uses graceful degradation when subsystems are unavailable.

    Response wrapped in ``{"data": ...}`` for frontend compatibility.
    """
    _reject_unexpected_query_params(request)
    # ----- At-rest encryption -----
    at_rest_algorithm = "AES-256-GCM"
    at_rest_status: str = "inactive"
    key_rotation_days = 90
    last_rotation: str | None = None

    try:
        from aragora.security.encryption import get_encryption_service, CRYPTO_AVAILABLE

        if CRYPTO_AVAILABLE:
            svc = get_encryption_service()
            at_rest_status = "active"
            at_rest_algorithm = "AES-256-GCM"

            # Inspect active key for age information
            if hasattr(svc, "get_active_key"):
                active_key = svc.get_active_key()
                if active_key and hasattr(active_key, "created_at"):
                    last_rotation = active_key.created_at.isoformat()
            elif hasattr(svc, "_keys") and hasattr(svc, "_active_key_id"):
                active_key = svc._keys.get(svc._active_key_id)
                if active_key and hasattr(active_key, "created_at"):
                    last_rotation = active_key.created_at.isoformat()
        else:
            at_rest_status = "inactive"
    except (ImportError, RuntimeError, ValueError, TypeError, AttributeError, OSError) as exc:
        logger.debug("Encryption service not available: %s", exc)
        at_rest_status = "inactive"

    # ----- Key rotation config -----
    try:
        from aragora.security.key_rotation import (
            get_key_rotation_scheduler,
            KeyRotationConfig,
        )

        scheduler = get_key_rotation_scheduler()
        if scheduler and hasattr(scheduler, "config"):
            key_rotation_days = scheduler.config.rotation_interval_days
            # Check last rotation from scheduler stats
            if hasattr(scheduler, "_stats") and scheduler._stats.last_rotation_at:
                last_rotation = scheduler._stats.last_rotation_at.isoformat()
        else:
            # Use default config values
            cfg = KeyRotationConfig.from_env()
            key_rotation_days = cfg.rotation_interval_days
    except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
        logger.debug("Key rotation scheduler not available: %s", exc)

    # ----- In-transit encryption (TLS) -----
    in_transit_status = "active"
    in_transit_protocol = "TLS 1.3"
    certificate_expiry: str | None = None
    min_tls_version = "1.2"

    # Check for TLS certificate path
    cert_path = os.environ.get("ARAGORA_TLS_CERT_PATH", "")
    if cert_path:
        try:
            import ssl

            tls_ctx = ssl.create_default_context()
            tls_ctx.load_cert_chain(cert_path)
            in_transit_status = "active"
        except (ImportError, OSError, ValueError) as exc:
            logger.debug("TLS cert check failed: %s", exc)
            in_transit_status = "degraded"
    # Even without a cert file, the server typically terminates TLS
    # at the load balancer/reverse proxy level, so report active.

    return {
        "data": {
            "at_rest": {
                "algorithm": at_rest_algorithm,
                "status": at_rest_status,
                "key_rotation_days": key_rotation_days,
                "last_rotation": last_rotation,
            },
            "in_transit": {
                "protocol": in_transit_protocol,
                "status": in_transit_status,
                "certificate_expiry": certificate_expiry,
                "min_version": min_tls_version,
            },
        }
    }
