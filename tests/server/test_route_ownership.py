"""Characterization tests for route ownership after collision resolution.

Companion to tests/server/test_route_collisions.py. That test guards
against NEW collisions; this one pins WHICH handler owns the routes whose
collisions were resolved in the 2026-06-10 cluster-1 fix (health probes,
/metrics, /api/auth/revoke), so a future re-registration cannot silently
flip ownership back.

Ownership is computed exactly the way ``RouteIndex.build()``
(aragora/server/handler_registry/core.py) computes it: iterate
HANDLER_REGISTRY in order and apply first-wins insertion over each
handler's ``ROUTES``. No server start, no network.
"""

from __future__ import annotations

from functools import lru_cache

import pytest

from aragora.server.handler_registry import HANDLER_REGISTRY
from aragora.server.handler_registry.core import _DeferredImport


@lru_cache(maxsize=1)
def _first_wins_route_owners() -> dict[str, str]:
    """Map exact route path -> owning handler class name (first-wins).

    Mirrors RouteIndex.build()'s exact-route insertion semantics.
    """
    owners: dict[str, str] = {}
    for _attr_name, entry in HANDLER_REGISTRY:
        handler_cls = entry.resolve() if isinstance(entry, _DeferredImport) else entry
        if handler_cls is None:
            continue
        routes = getattr(handler_cls, "ROUTES", None) or []
        if isinstance(routes, dict):
            routes = list(routes.keys())
        for raw in routes:
            if isinstance(raw, (tuple, list)) and len(raw) >= 2:
                path = raw[1]
            elif isinstance(raw, str):
                path = raw.partition(" ")[2] if " " in raw else raw
            else:
                continue
            if isinstance(path, str) and path and path not in owners:
                owners[path] = handler_cls.__name__
    return owners


# ---------------------------------------------------------------------------
# Cluster 1a: K8s probes and storage health — monolithic HealthHandler owns
# all health routes; the focused Liveness/Readiness/StorageHealth handlers
# are deliberately unregistered (they delegated to the same implementation
# functions and were fully shadowed — dead registry weight).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/healthz",
        "/readyz",
        "/readyz/dependencies",
        "/api/health/stores",
        "/api/v1/health/stores",
        "/api/v1/health/database",
    ],
)
def test_health_routes_owned_by_health_handler(path: str) -> None:
    owners = _first_wins_route_owners()
    assert owners.get(path) == "HealthHandler", (
        f"{path} must be served by the monolithic HealthHandler "
        f"(got {owners.get(path)!r}). The focused Liveness/Readiness/"
        "StorageHealth handlers are intentionally NOT in HANDLER_REGISTRY — "
        "they duplicate HealthHandler's routes and would be silently "
        "shadowed (see aragora/server/handler_registry/admin.py)."
    )


def test_focused_health_handlers_not_registered() -> None:
    """The focused health handlers must stay out of the registry.

    Registering them alongside HealthHandler re-creates the shadowed-route
    collisions resolved on 2026-06-10. They remain importable for
    direct/standalone use.
    """
    registered = set()
    for _attr_name, entry in HANDLER_REGISTRY:
        handler_cls = entry.resolve() if isinstance(entry, _DeferredImport) else entry
        if handler_cls is not None:
            registered.add(handler_cls.__name__)
    overlap = registered & {"LivenessHandler", "ReadinessHandler", "StorageHealthHandler"}
    assert not overlap, (
        f"Focused health handlers re-registered: {sorted(overlap)}. "
        "All their routes are already claimed by HealthHandler (first-wins), "
        "so registering them only adds silently shadowed duplicates. "
        "If you intend to split the monolith for real, remove the routes "
        "from HealthHandler.ROUTES in the same change."
    )


def test_focused_health_handlers_still_importable() -> None:
    """Direct/standalone use of the focused handlers keeps working."""
    from aragora.server.handlers.admin.health import (
        LivenessHandler,
        ReadinessHandler,
        StorageHealthHandler,
    )

    assert LivenessHandler(ctx={}).can_handle("/healthz")
    assert ReadinessHandler(ctx={}).can_handle("/readyz")
    assert StorageHealthHandler(ctx={}).can_handle("/api/v1/health/stores")


# ---------------------------------------------------------------------------
# Cluster 1b: /metrics — MetricsHandler owns the Prometheus scrape target.
# Contract (docs/operations/PRODUCTION_RUNBOOK.md, docs/reference/
# ENVIRONMENT.md): public scrape endpoint, optionally gated by
# ARAGORA_METRICS_TOKEN, rate-limited. SystemHandler's RBAC-gated claim
# (monitoring:metrics) broke anonymous scrapes with a 500
# PermissionDeniedError in production and was removed.
# ---------------------------------------------------------------------------


def test_metrics_owned_by_metrics_handler() -> None:
    owners = _first_wins_route_owners()
    assert owners.get("/metrics") == "MetricsHandler", (
        f"/metrics must be served by MetricsHandler (got "
        f"{owners.get('/metrics')!r}). It implements the documented scrape "
        "contract: public by default, optional ARAGORA_METRICS_TOKEN bearer "
        "gate, rate-limited. Do not re-add /metrics to SystemHandler "
        "(RBAC-gated — breaks Prometheus scrapers) or UnifiedMetricsHandler "
        "(shadowed; use /api/v1/metrics/prometheus instead)."
    )


def test_metrics_handler_serves_prometheus_text() -> None:
    """Pin the surviving /metrics behavior: Prometheus text, no RBAC."""
    from unittest.mock import MagicMock

    from aragora.server.handlers.metrics.handler import MetricsHandler

    handler = MetricsHandler(ctx={})
    assert handler.can_handle("/metrics")

    http = MagicMock()
    http.headers = {}
    http.client_address = ("127.0.0.1", 12345)
    result = handler.handle("/metrics", {}, http)
    assert result is not None
    assert result.status_code == 200
    assert "text/plain" in result.content_type


def test_metrics_handler_is_core_tier() -> None:
    """The /metrics owner must survive tier-filtered (minimal) deployments.

    SystemHandler (the previous /metrics claimant) is tier "core"; when its
    claim moved to MetricsHandler, MetricsHandler must be core too or
    minimal deployments silently lose the Prometheus scrape endpoint.
    """
    from aragora.server.handler_registry.core import HANDLER_TIERS

    assert HANDLER_TIERS.get("_metrics_handler") == "core", (
        "_metrics_handler must be tier 'core' in HANDLER_TIERS — it owns "
        "/metrics, and tier-filtered deployments that disable 'extended' "
        "would otherwise lose the documented Prometheus scrape endpoint."
    )


def test_unified_metrics_handler_does_not_claim_metrics_route() -> None:
    from aragora.server.handlers.metrics_endpoint import UnifiedMetricsHandler

    assert "/metrics" not in UnifiedMetricsHandler.ROUTES, (
        "UnifiedMetricsHandler must not claim /metrics in the registry "
        "(first-wins shadowing). It still serves /metrics when invoked "
        "directly; via the unified server use /api/v1/metrics/prometheus."
    )


# ---------------------------------------------------------------------------
# Cluster 1c: /api/auth/revoke — AuthHandler owns the canonical contract.
# Evidence: aragora/rbac/middleware.py maps POST /api/(v1/)?auth/revoke to
# the session.revoke permission; aragora/server/openapi/endpoints/auth.py
# documents it as a user-facing Authentication endpoint; docs/STATUS.md
# records the migration to AuthHandler. SystemHandler's legacy admin-gated
# claim shadowed all of that and was removed.
# ---------------------------------------------------------------------------


def test_auth_revoke_owned_by_auth_handler() -> None:
    owners = _first_wins_route_owners()
    assert owners.get("/api/auth/revoke") == "AuthHandler", (
        f"/api/auth/revoke must be served by AuthHandler (got "
        f"{owners.get('/api/auth/revoke')!r}): session.revoke permission, "
        "JWT blacklist + persistent revocation, self-revoke fallback when "
        "no token is supplied in the body. SystemHandler's legacy "
        "admin-gated implementation was removed on 2026-06-10."
    )


def test_system_handler_no_longer_claims_revoke_or_metrics() -> None:
    from aragora.server.handlers.admin.system import SystemHandler

    handler = SystemHandler(ctx={})
    assert not handler.can_handle("/api/auth/revoke")
    assert not handler.can_handle("/metrics")
    # SystemHandler keeps its legitimate routes.
    assert handler.can_handle("/api/auth/stats")
    assert handler.can_handle("/api/circuit-breakers")


def test_system_handler_post_compat_hook_does_not_reclaim_removed_routes() -> None:
    from aragora.server.handlers.admin.system import SystemHandler

    handler = SystemHandler(ctx={})
    assert handler.handle_post("/api/auth/revoke", {}, None) is None
    assert handler.handle_post("/metrics", {}, None) is None


def test_system_openapi_placeholder_methods_do_not_drift_when_revoke_moves() -> None:
    from aragora.server.openapi_impl import generate_openapi_schema

    paths = generate_openapi_schema()["paths"]
    for path in (
        "/api/auth/stats",
        "/api/circuit-breakers",
        "/api/debug/test",
        "/api/v1/diagnostics/handlers",
    ):
        assert "post" in paths[path]
        assert "get" not in paths[path]
        assert paths[path]["post"].get("x-autogenerated") is True


@pytest.mark.parametrize("path", ["/api/v1/km/checkpoints", "/api/v1/km/checkpoints/compare"])
def test_km_checkpoint_routes_owned_by_checkpoint_handler(path: str) -> None:
    """KMCheckpointHandler owns the checkpoint collection path.

    KnowledgeMoundHandler used to claim /api/v1/km/checkpoints in ROUTES
    without implementing list/create, so the documented operations were
    unserved. The claim was removed; do not re-add it to the mound handler.
    """
    owners = _first_wins_route_owners()
    assert owners.get(path) == "KMCheckpointHandler", (
        f"{path} must be served by KMCheckpointHandler (got {owners.get(path)!r}). "
        "It implements list (GET, knowledge:read) and create (POST, "
        "knowledge:write) on the collection path; KnowledgeMoundHandler "
        "has no checkpoint logic."
    )


def test_auth_handler_revoke_requires_session_revoke_permission() -> None:
    """Pin the surviving security semantics of POST /api/auth/revoke.

    The surviving implementation gates on session.revoke (user-level token
    self-management) rather than SystemHandler's removed admin:write +
    admin:security gate. An unauthenticated request must be rejected, not
    silently revoke anything.
    """
    import asyncio
    from unittest.mock import MagicMock

    from aragora.server.handlers.auth.handler import AuthHandler

    handler = AuthHandler(ctx={})
    assert handler.can_handle("/api/auth/revoke")

    http = MagicMock()
    http.headers = {}
    http.command = "POST"
    http.rfile = None

    result = asyncio.run(handler.handle("/api/auth/revoke", {}, http, method="POST"))
    assert result is not None
    assert result.status_code in (401, 403), (
        f"Unauthenticated POST /api/auth/revoke must be rejected (got {result.status_code})"
    )
