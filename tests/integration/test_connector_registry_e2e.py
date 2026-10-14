"""End-to-end integration tests for ConnectorRegistry + ConnectorManagementHandler.

Verifies that the runtime connector registry correctly discovers connectors
and that the management handler exposes consistent data through its REST-like
interface (handle / handle_post dispatch).
"""

from __future__ import annotations

import json
import time

import pytest

from aragora.billing.auth.context import UserAuthContext
from aragora.connectors.runtime_registry import (
    ConnectorInfo,
    ConnectorRegistry,
    ConnectorStatus,
    get_connector_registry,
)
from aragora.server.handlers.connectors.management import ConnectorManagementHandler


@pytest.fixture(autouse=True)
def _owner_caller(monkeypatch):
    """Per-connector health and test authorize with RBAC v2; owners hold both permissions."""
    owner = UserAuthContext(
        authenticated=True, user_id="test-owner", email="owner@example.com", role="owner"
    )
    monkeypatch.setattr(
        ConnectorManagementHandler, "require_auth_or_error", lambda self, handler: (owner, None)
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_body(result) -> dict:
    """Decode the HandlerResult body into a dict."""
    return json.loads(result.body.decode("utf-8"))


def _fresh_registry() -> ConnectorRegistry:
    """Reset the singleton and return a brand-new registry."""
    ConnectorRegistry.reset_instance()
    return get_connector_registry()


def _make_handler(registry: ConnectorRegistry | None = None) -> ConnectorManagementHandler:
    """Create a ConnectorManagementHandler wired to *registry*."""
    h = ConnectorManagementHandler(server_context={})
    if registry is not None:
        # Inject the registry so the handler skips the singleton lookup.
        h._registry = registry
    return h


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure each test starts with a clean singleton."""
    ConnectorRegistry.reset_instance()
    yield
    ConnectorRegistry.reset_instance()


@pytest.fixture()
def registry() -> ConnectorRegistry:
    return _fresh_registry()


@pytest.fixture()
def handler(registry: ConnectorRegistry) -> ConnectorManagementHandler:
    return _make_handler(registry)


# ---------------------------------------------------------------------------
# 1. Registry discovers real connectors on init
# ---------------------------------------------------------------------------


class TestRegistryDiscovery:
    """ConnectorRegistry._discover_connectors finds importable modules."""

    def test_discovers_at_least_some_connectors(self, registry: ConnectorRegistry):
        """The registry should contain a non-trivial number of entries after
        auto-discovery (the codebase has 20+ connector module paths)."""
        all_connectors = registry.list_all()
        assert len(all_connectors) >= 5, (
            f"Expected at least 5 discovered connectors, got {len(all_connectors)}"
        )

    def test_at_least_one_healthy(self, registry: ConnectorRegistry):
        """At least one connector should be importable and therefore HEALTHY."""
        healthy = registry.list_by_status(ConnectorStatus.HEALTHY)
        assert len(healthy) >= 1, "No HEALTHY connectors found after discovery"

    def test_connector_info_fields(self, registry: ConnectorRegistry):
        """Each discovered connector should have well-formed ConnectorInfo."""
        for info in registry.list_all():
            assert info.name, "name must be non-empty"
            assert info.connector_type, "connector_type must be non-empty"
            assert info.module_path.startswith("aragora."), (
                f"Unexpected module_path: {info.module_path}"
            )
            assert isinstance(info.status, ConnectorStatus)
            assert info.last_health_check is not None


# ---------------------------------------------------------------------------
# 2. Registry -> handler -> list all -> verify counts match
# ---------------------------------------------------------------------------


class TestListAllEndpoint:
    """GET /api/v1/connectors returns the same data as registry.list_all()."""

    def test_counts_match(self, registry: ConnectorRegistry, handler: ConnectorManagementHandler):
        expected = registry.list_all()
        result = handler.handle("/api/v1/connectors", {}, None)

        assert result is not None
        assert result.status_code == 200

        body = _parse_body(result)
        assert body["total"] == len(expected)
        assert len(body["connectors"]) == len(expected)

    def test_connector_names_match(
        self, registry: ConnectorRegistry, handler: ConnectorManagementHandler
    ):
        expected_names = sorted(c.name for c in registry.list_all())
        result = handler.handle("/api/v1/connectors", {}, None)
        body = _parse_body(result)
        returned_names = sorted(c["name"] for c in body["connectors"])
        assert returned_names == expected_names


# ---------------------------------------------------------------------------
# 3. Registry health check -> handler health endpoint -> status matches
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """GET /api/v1/connectors/<name>/health agrees with registry.health_check()."""

    def test_health_status_matches_registry(
        self, registry: ConnectorRegistry, handler: ConnectorManagementHandler
    ):
        # Pick the first connector (they are sorted by name).
        first = registry.list_all()[0]
        name = first.name

        # Run health check through registry directly.
        direct_status = registry.health_check(name)

        # Run health check through handler.
        result = handler.handle(f"/api/v1/connectors/{name}/health", {}, None)
        assert result is not None
        assert result.status_code == 200

        body = _parse_body(result)
        assert body["name"] == name
        assert body["status"] == direct_status.value

    def test_health_updates_last_check(
        self, registry: ConnectorRegistry, handler: ConnectorManagementHandler
    ):
        first = registry.list_all()[0]
        old_check = first.last_health_check

        # Small sleep so timestamp differs.
        time.sleep(0.01)

        result = handler.handle(f"/api/v1/connectors/{first.name}/health", {}, None)
        body = _parse_body(result)

        assert body["last_health_check"] is not None
        assert body["last_health_check"] >= old_check


# ---------------------------------------------------------------------------
# 4. Filter by type through handler matches registry.list_by_type()
# ---------------------------------------------------------------------------


class TestFilterByType:
    """GET /api/v1/connectors?type=<type> returns the same set as list_by_type()."""

    def test_filter_chat_type(
        self, registry: ConnectorRegistry, handler: ConnectorManagementHandler
    ):
        expected = registry.list_by_type("chat")
        result = handler.handle("/api/v1/connectors", {"type": "chat"}, None)

        assert result is not None
        assert result.status_code == 200

        body = _parse_body(result)
        assert body["total"] == len(expected)
        returned_names = {c["name"] for c in body["connectors"]}
        expected_names = {c.name for c in expected}
        assert returned_names == expected_names

    def test_filter_nonexistent_type_returns_empty(self, handler: ConnectorManagementHandler):
        result = handler.handle("/api/v1/connectors", {"type": "nonexistent_xyz"}, None)
        assert result is not None
        body = _parse_body(result)
        assert body["total"] == 0
        assert body["connectors"] == []

    def test_filter_by_status(
        self, registry: ConnectorRegistry, handler: ConnectorManagementHandler
    ):
        """GET /api/v1/connectors?status=healthy filters correctly."""
        expected = registry.list_by_status(ConnectorStatus.HEALTHY)
        result = handler.handle("/api/v1/connectors", {"status": "healthy"}, None)

        assert result is not None
        assert result.status_code == 200

        body = _parse_body(result)
        assert body["total"] == len(expected)


# ---------------------------------------------------------------------------
# 5. Full lifecycle: register -> health check -> list -> verify -> unregister
# ---------------------------------------------------------------------------


class TestCustomConnectorLifecycle:
    """Register a custom connector, exercise it through the handler, then remove it."""

    def test_full_lifecycle(self, registry: ConnectorRegistry, handler: ConnectorManagementHandler):
        custom = ConnectorInfo(
            name="test_custom",
            connector_type="testing",
            module_path="aragora.connectors.runtime_registry",  # importable module
            status=ConnectorStatus.UNKNOWN,
            last_health_check=None,
            capabilities=["unit_test"],
        )

        # -- Register --
        registry.register(custom)
        assert registry.get("test_custom") is not None

        # -- Detail via handler --
        detail_result = handler.handle("/api/v1/connectors/test_custom", {}, None)
        assert detail_result is not None
        assert detail_result.status_code == 200
        detail = _parse_body(detail_result)
        assert detail["name"] == "test_custom"
        assert detail["connector_type"] == "testing"
        assert detail["capabilities"] == ["unit_test"]

        # -- Health check via handler --
        health_result = handler.handle("/api/v1/connectors/test_custom/health", {}, None)
        assert health_result is not None
        health = _parse_body(health_result)
        # The module path is importable, so status should become healthy.
        assert health["status"] == "healthy"

        # -- Appears in list --
        list_result = handler.handle("/api/v1/connectors", {}, None)
        list_body = _parse_body(list_result)
        names = [c["name"] for c in list_body["connectors"]]
        assert "test_custom" in names

        # -- Unregister --
        removed = registry.unregister("test_custom")
        assert removed is True
        assert registry.get("test_custom") is None

        # -- No longer in list --
        list_result2 = handler.handle("/api/v1/connectors", {}, None)
        list_body2 = _parse_body(list_result2)
        names2 = [c["name"] for c in list_body2["connectors"]]
        assert "test_custom" not in names2


# ---------------------------------------------------------------------------
# 6. Handler returns 404 for non-existent connector
# ---------------------------------------------------------------------------


class TestNotFound:
    """Handler correctly returns 404 for unknown connector names."""

    def test_detail_404(self, handler: ConnectorManagementHandler):
        result = handler.handle("/api/v1/connectors/does_not_exist", {}, None)
        assert result is not None
        assert result.status_code == 404
        body = _parse_body(result)
        assert "error" in body

    def test_health_404(self, handler: ConnectorManagementHandler):
        result = handler.handle("/api/v1/connectors/does_not_exist/health", {}, None)
        assert result is not None
        assert result.status_code == 404

    def test_post_test_404(self, handler: ConnectorManagementHandler):
        result = handler.handle_post("/api/v1/connectors/does_not_exist/test", {}, None)
        assert result is not None
        assert result.status_code == 404


# ---------------------------------------------------------------------------
# 7. Summary endpoint aggregates correctly
# ---------------------------------------------------------------------------


class TestSummaryEndpoint:
    """GET /api/v1/connectors/summary matches registry.get_summary()."""

    def test_summary_totals(self, registry: ConnectorRegistry, handler: ConnectorManagementHandler):
        expected = registry.get_summary()
        result = handler.handle("/api/v1/connectors/summary", {}, None)

        assert result is not None
        assert result.status_code == 200

        body = _parse_body(result)
        assert body["total"] == expected["total"]
        assert body["by_type"] == expected["by_type"]
        assert body["by_status"] == expected["by_status"]
        assert len(body["connectors"]) == expected["total"]

    def test_summary_type_counts_add_up(
        self, registry: ConnectorRegistry, handler: ConnectorManagementHandler
    ):
        result = handler.handle("/api/v1/connectors/summary", {}, None)
        body = _parse_body(result)

        type_total = sum(body["by_type"].values())
        assert type_total == body["total"], (
            f"by_type counts ({type_total}) do not add up to total ({body['total']})"
        )

        status_total = sum(body["by_status"].values())
        assert status_total == body["total"], (
            f"by_status counts ({status_total}) do not add up to total ({body['total']})"
        )
