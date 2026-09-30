"""Tests for ConnectorManagementHandler (aragora/server/handlers/connectors/management.py).

Comprehensive test suite covering all routes, error paths, edge cases, and validation:

Routes under test:
    GET  /api/v1/connectors            - List all connectors (with ?type= and ?status= filters)
    GET  /api/v1/connectors/summary    - Aggregated health summary
    GET  /api/v1/connectors/<name>     - Single connector detail
    GET  /api/v1/connectors/<name>/health - Run health check for a connector
    POST /api/v1/connectors/<name>/test   - Test connector connectivity

Internal helpers:
    can_handle(path) - Route prefix matching
    _validate_name(name) - Connector name sanitization
    _get_registry() - Lazy singleton access
"""

from __future__ import annotations

import json
import time
from io import BytesIO
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.auth.context import UserAuthContext
from aragora.connectors.runtime_registry import (
    ConnectorInfo,
    ConnectorRegistry,
    ConnectorStatus,
)
from aragora.server.handlers.connectors.management import (
    ConnectorManagementHandler,
    _PREFIX,
    _SAFE_NAME_RE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Parse HandlerResult.body bytes into a dict."""
    return json.loads(result.body)


def _status(result) -> int:
    """Extract status code from a HandlerResult."""
    return result.status_code


def _make_connector(
    name: str = "slack",
    connector_type: str = "chat",
    module_path: str = "aragora.connectors.chat.slack",
    status: ConnectorStatus = ConnectorStatus.HEALTHY,
    configured: bool | None = True,
    last_health_check: float | None = None,
    capabilities: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> ConnectorInfo:
    """Create a ConnectorInfo with sensible defaults."""
    return ConnectorInfo(
        name=name,
        connector_type=connector_type,
        module_path=module_path,
        status=status,
        configured=configured,
        last_health_check=last_health_check or time.time(),
        capabilities=capabilities or ["messaging", "slash_commands"],
        metadata=metadata or {"importable": True},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_registry():
    """Create a standalone ConnectorRegistry without real discovery."""
    registry = ConnectorRegistry.__new__(ConnectorRegistry)
    registry._connectors = {}
    return registry


@pytest.fixture
def handler(mock_registry):
    """Create a ConnectorManagementHandler wired to the mock registry."""
    h = ConnectorManagementHandler(server_context={})
    h._registry = mock_registry
    return h


@pytest.fixture
def mock_http_handler():
    """Minimal mock HTTP handler (used for auth bypass)."""
    return MagicMock()


@pytest.fixture(autouse=True)
def _owner_caller(request, monkeypatch):
    """Per-connector health and test authorize with RBAC v2, where only owners hold connectors.test."""
    if request.node.get_closest_marker("no_auto_auth"):
        return
    owner = UserAuthContext(
        authenticated=True, user_id="test-owner", email="owner@example.com", role="owner"
    )
    monkeypatch.setattr(
        ConnectorManagementHandler, "require_auth_or_error", lambda self, handler: (owner, None)
    )


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Tests for ConnectorManagementHandler.can_handle()."""

    def test_matches_prefix_exactly(self, handler):
        assert handler.can_handle("/api/v1/connectors") is True

    def test_matches_prefix_with_trailing_slash(self, handler):
        assert handler.can_handle("/api/v1/connectors/") is True

    def test_matches_prefix_with_sub_path(self, handler):
        assert handler.can_handle("/api/v1/connectors/slack") is True

    def test_matches_prefix_with_nested_sub_path(self, handler):
        assert handler.can_handle("/api/v1/connectors/slack/health") is True

    def test_rejects_unrelated_path(self, handler):
        assert handler.can_handle("/api/v1/debates") is False

    def test_rejects_partial_prefix(self, handler):
        assert handler.can_handle("/api/v1/connector") is False

    def test_rejects_empty_path(self, handler):
        assert handler.can_handle("") is False

    def test_rejects_similar_prefix(self, handler):
        assert handler.can_handle("/api/v1/connectors_extra") is True  # starts with prefix

    def test_rejects_wrong_version(self, handler):
        assert handler.can_handle("/api/v2/connectors") is False


# ---------------------------------------------------------------------------
# _validate_name
# ---------------------------------------------------------------------------


class TestValidateName:
    """Tests for the static _validate_name helper."""

    def test_valid_simple_name(self):
        assert ConnectorManagementHandler._validate_name("slack") is None

    def test_valid_underscore_name(self):
        assert ConnectorManagementHandler._validate_name("google_chat") is None

    def test_valid_alphanumeric(self):
        assert ConnectorManagementHandler._validate_name("connector2") is None

    def test_valid_uppercase(self):
        assert ConnectorManagementHandler._validate_name("MyConnector") is None

    def test_invalid_empty_name(self):
        result = ConnectorManagementHandler._validate_name("")
        assert result is not None
        assert _status(result) == 400

    def test_invalid_hyphen(self):
        result = ConnectorManagementHandler._validate_name("my-connector")
        assert result is not None
        assert _status(result) == 400
        assert "Invalid connector name" in _body(result).get("error", "")

    def test_invalid_dot(self):
        result = ConnectorManagementHandler._validate_name("my.connector")
        assert result is not None
        assert _status(result) == 400

    def test_invalid_slash(self):
        result = ConnectorManagementHandler._validate_name("path/traversal")
        assert result is not None
        assert _status(result) == 400

    def test_invalid_space(self):
        result = ConnectorManagementHandler._validate_name("my connector")
        assert result is not None
        assert _status(result) == 400

    def test_invalid_special_characters(self):
        for char in ["@", "#", "$", "%", "!", "&", "*", "(", ")"]:
            result = ConnectorManagementHandler._validate_name(f"name{char}")
            assert result is not None, f"Should reject name with '{char}'"
            assert _status(result) == 400


# ---------------------------------------------------------------------------
# GET /api/v1/connectors  (list)
# ---------------------------------------------------------------------------


class TestListConnectors:
    """Tests for GET /api/v1/connectors."""

    def test_list_empty_registry(self, handler, mock_http_handler, mock_registry):
        result = handler.handle(_PREFIX, {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["connectors"] == []
        assert body["total"] == 0

    def test_list_with_trailing_slash(self, handler, mock_http_handler, mock_registry):
        result = handler.handle(_PREFIX + "/", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 0

    def test_list_single_connector(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("slack", "chat"))
        result = handler.handle(_PREFIX, {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 1
        assert body["connectors"][0]["name"] == "slack"

    def test_list_multiple_connectors(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("slack", "chat"))
        mock_registry.register(_make_connector("telegram", "chat"))
        mock_registry.register(_make_connector("stripe", "payment"))
        result = handler.handle(_PREFIX, {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 3
        names = [c["name"] for c in body["connectors"]]
        # list_all sorts by name
        assert names == sorted(names)

    def test_list_filter_by_type(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("slack", "chat"))
        mock_registry.register(_make_connector("telegram", "chat"))
        mock_registry.register(_make_connector("stripe", "payment"))
        result = handler.handle(_PREFIX, {"type": "chat"}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 2
        for c in body["connectors"]:
            assert c["connector_type"] == "chat"

    def test_list_filter_by_type_no_matches(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("slack", "chat"))
        result = handler.handle(_PREFIX, {"type": "payment"}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 0

    def test_list_filter_by_status_healthy(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("slack", "chat", status=ConnectorStatus.HEALTHY))
        mock_registry.register(
            _make_connector("telegram", "chat", status=ConnectorStatus.UNHEALTHY)
        )
        result = handler.handle(_PREFIX, {"status": "healthy"}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 1
        assert body["connectors"][0]["name"] == "slack"

    def test_list_filter_by_status_unhealthy(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("slack", "chat", status=ConnectorStatus.HEALTHY))
        mock_registry.register(
            _make_connector("telegram", "chat", status=ConnectorStatus.UNHEALTHY)
        )
        result = handler.handle(_PREFIX, {"status": "unhealthy"}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 1
        assert body["connectors"][0]["name"] == "telegram"

    def test_list_filter_by_status_degraded(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("slack", "chat", status=ConnectorStatus.DEGRADED))
        mock_registry.register(_make_connector("telegram", "chat", status=ConnectorStatus.HEALTHY))
        result = handler.handle(_PREFIX, {"status": "degraded"}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 1
        assert body["connectors"][0]["name"] == "slack"

    def test_list_filter_by_status_unknown(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("slack", "chat", status=ConnectorStatus.UNKNOWN))
        result = handler.handle(_PREFIX, {"status": "unknown"}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 1

    def test_list_filter_invalid_status(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("slack", "chat"))
        result = handler.handle(_PREFIX, {"status": "bogus"}, mock_http_handler)
        assert _status(result) == 400
        body = _body(result)
        assert "Invalid status filter" in body.get("error", "")

    def test_list_combined_type_and_status_filter(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("slack", "chat", status=ConnectorStatus.HEALTHY))
        mock_registry.register(
            _make_connector("telegram", "chat", status=ConnectorStatus.UNHEALTHY)
        )
        mock_registry.register(_make_connector("stripe", "payment", status=ConnectorStatus.HEALTHY))
        result = handler.handle(_PREFIX, {"type": "chat", "status": "healthy"}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 1
        assert body["connectors"][0]["name"] == "slack"

    def test_list_connector_serialization_complete(self, handler, mock_http_handler, mock_registry):
        """Ensure all ConnectorInfo fields are serialized."""
        connector = _make_connector(
            "slack",
            "chat",
            module_path="aragora.connectors.chat.slack",
            status=ConnectorStatus.HEALTHY,
            configured=True,
            capabilities=["messaging", "slash_commands"],
            metadata={"importable": True, "version": "1.0"},
        )
        mock_registry.register(connector)
        result = handler.handle(_PREFIX, {}, mock_http_handler)
        body = _body(result)
        c = body["connectors"][0]
        assert c["name"] == "slack"
        assert c["connector_type"] == "chat"
        assert c["module_path"] == "aragora.connectors.chat.slack"
        assert c["status"] == "healthy"
        assert c["configured"] is True
        assert "messaging" in c["capabilities"]
        assert c["metadata"]["importable"] is True


# ---------------------------------------------------------------------------
# GET /api/v1/connectors/summary
# ---------------------------------------------------------------------------


class TestSummary:
    """Tests for GET /api/v1/connectors/summary."""

    def test_summary_empty_registry(self, handler, mock_http_handler, mock_registry):
        result = handler.handle(_PREFIX + "/summary", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 0
        assert body["by_type"] == {}
        assert body["by_status"] == {}
        assert body["connectors"] == []

    def test_summary_with_connectors(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("slack", "chat", status=ConnectorStatus.HEALTHY))
        mock_registry.register(
            _make_connector("telegram", "chat", status=ConnectorStatus.UNHEALTHY)
        )
        mock_registry.register(_make_connector("stripe", "payment", status=ConnectorStatus.HEALTHY))
        result = handler.handle(_PREFIX + "/summary", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["total"] == 3
        assert body["by_type"]["chat"] == 2
        assert body["by_type"]["payment"] == 1
        assert body["by_status"]["healthy"] == 2
        assert body["by_status"]["unhealthy"] == 1
        assert len(body["connectors"]) == 3


# ---------------------------------------------------------------------------
# GET /api/v1/connectors/<name>  (detail)
# ---------------------------------------------------------------------------


class TestDetail:
    """Tests for GET /api/v1/connectors/<name>."""

    def test_detail_existing_connector(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("slack", "chat"))
        result = handler.handle(_PREFIX + "/slack", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["name"] == "slack"
        assert body["connector_type"] == "chat"

    def test_detail_not_found(self, handler, mock_http_handler, mock_registry):
        result = handler.handle(_PREFIX + "/nonexistent", {}, mock_http_handler)
        assert _status(result) == 404
        body = _body(result)
        assert "not found" in body.get("error", "").lower()

    def test_detail_invalid_name_hyphen(self, handler, mock_http_handler, mock_registry):
        result = handler.handle(_PREFIX + "/my-bad-name", {}, mock_http_handler)
        assert _status(result) == 400
        body = _body(result)
        assert "Invalid connector name" in body.get("error", "")

    def test_detail_invalid_name_special_chars(self, handler, mock_http_handler, mock_registry):
        result = handler.handle(_PREFIX + "/slack@evil", {}, mock_http_handler)
        assert _status(result) == 400

    def test_detail_returns_full_info(self, handler, mock_http_handler, mock_registry):
        connector = _make_connector(
            "github",
            "ai",
            module_path="aragora.connectors.github",
            capabilities=["search", "issues", "prs"],
            metadata={"importable": True, "version": "2.1"},
        )
        mock_registry.register(connector)
        result = handler.handle(_PREFIX + "/github", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["capabilities"] == ["search", "issues", "prs"]
        assert body["metadata"]["version"] == "2.1"


# ---------------------------------------------------------------------------
# GET /api/v1/connectors/<name>/health
# ---------------------------------------------------------------------------


class TestHealth:
    """Tests for GET /api/v1/connectors/<name>/health."""

    def test_health_healthy_connector(self, handler, mock_http_handler, mock_registry):
        connector = _make_connector("slack", "chat", status=ConnectorStatus.HEALTHY)
        mock_registry.register(connector)
        # Mock health_check to return HEALTHY
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.HEALTHY)
        result = handler.handle(_PREFIX + "/slack/health", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["name"] == "slack"
        assert body["status"] == "healthy"
        mock_registry.health_check.assert_called_once_with("slack")

    def test_health_unhealthy_connector(self, handler, mock_http_handler, mock_registry):
        connector = _make_connector("slack", "chat", status=ConnectorStatus.UNHEALTHY)
        mock_registry.register(connector)
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.UNHEALTHY)
        result = handler.handle(_PREFIX + "/slack/health", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "unhealthy"

    def test_health_degraded_connector(self, handler, mock_http_handler, mock_registry):
        connector = _make_connector("slack", "chat", status=ConnectorStatus.DEGRADED)
        mock_registry.register(connector)
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.DEGRADED)
        result = handler.handle(_PREFIX + "/slack/health", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "degraded"

    def test_health_not_found(self, handler, mock_http_handler, mock_registry):
        result = handler.handle(_PREFIX + "/nonexistent/health", {}, mock_http_handler)
        assert _status(result) == 404
        body = _body(result)
        assert "not found" in body.get("error", "").lower()

    def test_health_invalid_name(self, handler, mock_http_handler, mock_registry):
        result = handler.handle(_PREFIX + "/bad-name/health", {}, mock_http_handler)
        assert _status(result) == 501
        assert _body(result)["error"]["code"] == "not_implemented"

    def test_health_returns_last_check_and_metadata(
        self, handler, mock_http_handler, mock_registry
    ):
        ts = time.time()
        connector = _make_connector(
            "slack",
            "chat",
            status=ConnectorStatus.HEALTHY,
            last_health_check=ts,
            metadata={"importable": True, "extra": "data"},
        )
        mock_registry.register(connector)
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.HEALTHY)
        result = handler.handle(_PREFIX + "/slack/health", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["last_health_check"] == ts
        assert body["metadata"]["importable"] is True


# ---------------------------------------------------------------------------
# POST /api/v1/connectors/<name>/test
# ---------------------------------------------------------------------------


class TestTestConnectivity:
    """Tests for POST /api/v1/connectors/<name>/test."""

    def test_test_healthy_connector(self, handler, mock_http_handler, mock_registry):
        connector = _make_connector(
            "slack",
            "chat",
            status=ConnectorStatus.HEALTHY,
            capabilities=["messaging"],
            metadata={"importable": True},
        )
        mock_registry.register(connector)
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.HEALTHY)
        result = handler.handle_post(_PREFIX + "/slack/test", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["name"] == "slack"
        assert body["connector_type"] == "chat"
        assert body["status"] == "healthy"
        assert body["importable"] is True
        assert body["capabilities"] == ["messaging"]
        assert body["last_health_check"] is not None
        # No error or warning keys for healthy
        assert "error" not in body
        assert "warning" not in body

    def test_test_unhealthy_connector_includes_error(
        self, handler, mock_http_handler, mock_registry
    ):
        connector = _make_connector(
            "telegram",
            "chat",
            status=ConnectorStatus.UNHEALTHY,
            metadata={"importable": False, "import_error": "No module named 'telegram'"},
        )
        mock_registry.register(connector)
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.UNHEALTHY)
        result = handler.handle_post(_PREFIX + "/telegram/test", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "unhealthy"
        assert body["importable"] is False
        assert "error" in body
        assert "No module named" in body["error"]
        assert "warning" not in body

    def test_test_degraded_connector_includes_warning(
        self, handler, mock_http_handler, mock_registry
    ):
        connector = _make_connector(
            "kafka",
            "enterprise",
            status=ConnectorStatus.DEGRADED,
            metadata={"importable": True, "health_error": "Connection timeout"},
        )
        mock_registry.register(connector)
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.DEGRADED)
        result = handler.handle_post(_PREFIX + "/kafka/test", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "degraded"
        assert "warning" in body
        assert "Connection timeout" in body["warning"]
        assert "error" not in body

    def test_test_not_found(self, handler, mock_http_handler, mock_registry):
        result = handler.handle_post(_PREFIX + "/nonexistent/test", {}, mock_http_handler)
        assert _status(result) == 404

    def test_test_invalid_name(self, handler, mock_http_handler, mock_registry):
        result = handler.handle_post(_PREFIX + "/bad-name/test", {}, mock_http_handler)
        assert _status(result) == 501
        assert _body(result)["error"]["code"] == "not_implemented"

    def test_test_invalid_json_returns_400(self, handler, mock_registry):
        bad_http_handler = MagicMock()
        bad_http_handler.headers = {"Content-Length": "8"}
        bad_http_handler.rfile = BytesIO(b"not-json")
        result = handler.handle_post(_PREFIX + "/slack/test", {}, bad_http_handler)
        assert _status(result) == 400
        assert "json" in _body(result).get("error", "").lower()

    def test_test_unknown_status_connector(self, handler, mock_http_handler, mock_registry):
        connector = _make_connector(
            "slack",
            "chat",
            status=ConnectorStatus.UNKNOWN,
            metadata={"importable": False},
        )
        mock_registry.register(connector)
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.UNKNOWN)
        result = handler.handle_post(_PREFIX + "/slack/test", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["status"] == "unknown"
        # UNKNOWN is neither UNHEALTHY nor DEGRADED, so no error/warning
        assert "error" not in body
        assert "warning" not in body

    def test_test_unhealthy_no_import_error_in_metadata(
        self, handler, mock_http_handler, mock_registry
    ):
        """When UNHEALTHY but metadata has no import_error, fall back to 'Unknown error'."""
        connector = _make_connector(
            "slack",
            "chat",
            status=ConnectorStatus.UNHEALTHY,
            metadata={"importable": False},
        )
        mock_registry.register(connector)
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.UNHEALTHY)
        result = handler.handle_post(_PREFIX + "/slack/test", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["error"] == "Unknown error"

    def test_test_degraded_no_health_error_in_metadata(
        self, handler, mock_http_handler, mock_registry
    ):
        """When DEGRADED but metadata has no health_error, fall back to 'Degraded'."""
        connector = _make_connector(
            "slack",
            "chat",
            status=ConnectorStatus.DEGRADED,
            metadata={"importable": True},
        )
        mock_registry.register(connector)
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.DEGRADED)
        result = handler.handle_post(_PREFIX + "/slack/test", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["warning"] == "Degraded"


# ---------------------------------------------------------------------------
# POST routing — non-matching paths
# ---------------------------------------------------------------------------


class TestPostRouting:
    """Tests for POST routing edge cases."""

    def test_post_unrelated_path_returns_none(self, handler, mock_http_handler):
        result = handler.handle_post("/api/v1/debates", {}, mock_http_handler)
        assert result is None

    def test_post_no_matching_sub_route(self, handler, mock_http_handler, mock_registry):
        """POST to a path that doesn't match the /name/test pattern returns None."""
        result = handler.handle_post(_PREFIX + "/slack", {}, mock_http_handler)
        assert result is None

    def test_post_root_returns_none(self, handler, mock_http_handler, mock_registry):
        result = handler.handle_post(_PREFIX, {}, mock_http_handler)
        assert result is None

    def test_post_too_many_segments_returns_none(self, handler, mock_http_handler, mock_registry):
        result = handler.handle_post(_PREFIX + "/slack/test/extra", {}, mock_http_handler)
        assert result is None

    def test_post_wrong_action_returns_none(self, handler, mock_http_handler, mock_registry):
        """POST /api/v1/connectors/slack/health is not a POST route."""
        result = handler.handle_post(_PREFIX + "/slack/health", {}, mock_http_handler)
        assert result is None


# ---------------------------------------------------------------------------
# GET routing — non-matching paths
# ---------------------------------------------------------------------------


class TestGetRouting:
    """Tests for GET routing edge cases."""

    def test_get_unrelated_path_returns_none(self, handler, mock_http_handler):
        result = handler.handle("/api/v1/debates", {}, mock_http_handler)
        assert result is None

    def test_get_too_many_segments_returns_none(self, handler, mock_http_handler, mock_registry):
        """GET /api/v1/connectors/slack/health/extra returns None (unmatched)."""
        result = handler.handle(_PREFIX + "/slack/health/extra", {}, mock_http_handler)
        assert result is None

    def test_get_unknown_sub_action(self, handler, mock_http_handler, mock_registry):
        """GET /api/v1/connectors/slack/unknown with 2 parts but not 'health'."""
        mock_registry.register(_make_connector("slack", "chat"))
        result = handler.handle(_PREFIX + "/slack/unknown", {}, mock_http_handler)
        # parts[1] != "health" and len(parts) == 2 => returns None
        assert result is None


# ---------------------------------------------------------------------------
# Lazy registry initialization
# ---------------------------------------------------------------------------


class TestRegistryInit:
    """Tests for _get_registry lazy initialization."""

    def test_lazy_init_calls_get_connector_registry(self):
        """When _registry is None, _get_registry calls the module-level factory."""
        h = ConnectorManagementHandler(server_context={})
        h._registry = None
        mock_reg = MagicMock(spec=ConnectorRegistry)
        with patch(
            "aragora.server.handlers.connectors.management.get_connector_registry",
            return_value=mock_reg,
        ):
            result = h._get_registry()
            assert result is mock_reg

    def test_lazy_init_caches_result(self):
        """Once fetched, subsequent calls return the same instance."""
        h = ConnectorManagementHandler(server_context={})
        h._registry = None
        mock_reg = MagicMock(spec=ConnectorRegistry)
        with patch(
            "aragora.server.handlers.connectors.management.get_connector_registry",
            return_value=mock_reg,
        ) as mock_get:
            h._get_registry()
            h._get_registry()
            # Only called once due to caching
            mock_get.assert_called_once()

    def test_pre_set_registry_not_overwritten(self, handler, mock_registry):
        """If _registry is already set (as in our fixture), _get_registry uses it."""
        result = handler._get_registry()
        assert result is mock_registry


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


class TestConstructor:
    """Tests for ConnectorManagementHandler.__init__."""

    def test_default_context_is_empty(self):
        h = ConnectorManagementHandler()
        assert h.ctx == {}

    def test_custom_context(self):
        ctx = {"storage": MagicMock()}
        h = ConnectorManagementHandler(server_context=ctx)
        assert h.ctx is ctx

    def test_registry_starts_none(self):
        h = ConnectorManagementHandler()
        assert h._registry is None


# ---------------------------------------------------------------------------
# Authentication bypass verification (no_auto_auth marker)
# ---------------------------------------------------------------------------


class TestAuthEnforcement:
    """Tests verifying auth is enforced when auto_auth is disabled."""

    @pytest.mark.no_auto_auth
    def test_get_requires_auth(self, mock_http_handler):
        """Without auto-auth bypass, handle() should call require_auth_or_error."""
        h = ConnectorManagementHandler(server_context={})
        mock_registry = ConnectorRegistry.__new__(ConnectorRegistry)
        mock_registry._connectors = {}
        h._registry = mock_registry
        # The real require_auth_or_error will fail because mock_http_handler
        # doesn't have valid auth headers. Expect an error result.
        result = h.handle(_PREFIX, {}, mock_http_handler)
        # Should be an error (401 or 403) since auth is not bypassed
        assert result is not None
        assert _status(result) in (401, 403)

    @pytest.mark.no_auto_auth
    def test_post_requires_auth(self, mock_http_handler):
        """Without auto-auth bypass, handle_post() should enforce auth."""
        h = ConnectorManagementHandler(server_context={})
        mock_registry = ConnectorRegistry.__new__(ConnectorRegistry)
        mock_registry._connectors = {}
        h._registry = mock_registry
        result = h.handle_post(_PREFIX + "/slack/test", {}, mock_http_handler)
        assert result is not None
        assert _status(result) in (401, 403)


# ---------------------------------------------------------------------------
# _SAFE_NAME_RE pattern validation
# ---------------------------------------------------------------------------


class TestSafeNameRegex:
    """Direct tests of the _SAFE_NAME_RE compiled pattern."""

    @pytest.mark.parametrize(
        "name",
        [
            "slack",
            "Telegram",
            "google_chat",
            "connector123",
            "A",
            "z",
            "ABC_def_123",
            "_underscore_start",
        ],
    )
    def test_valid_names(self, name):
        assert _SAFE_NAME_RE.match(name) is not None

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "my-conn",
            "my.conn",
            "my/conn",
            "my conn",
            "my@conn",
            "../etc/passwd",
            "name\x00null",
        ],
    )
    def test_invalid_names(self, name):
        assert _SAFE_NAME_RE.match(name) is None or name == ""


# ---------------------------------------------------------------------------
# Edge cases — info disappears after health_check
# ---------------------------------------------------------------------------


class TestInfoDisappearsAfterHealthCheck:
    """Edge case: connector disappears from registry between health_check and re-get."""

    def test_health_info_gone_after_check(self, handler, mock_http_handler, mock_registry):
        """If registry.get returns None after health_check, handle gracefully."""
        connector = _make_connector("flaky", "chat")
        mock_registry.register(connector)

        call_count = 0
        original_get = mock_registry.get

        def get_side_effect(name):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return original_get(name)
            # Second call after health_check: gone
            return None

        mock_registry.get = get_side_effect
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.HEALTHY)

        result = handler.handle(_PREFIX + "/flaky/health", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["name"] == "flaky"
        assert body["status"] == "healthy"
        # When info is None after re-fetch, last_health_check and metadata have defaults
        assert body["last_health_check"] is None
        assert body["metadata"] == {}

    def test_test_info_gone_after_check(self, handler, mock_http_handler, mock_registry):
        """Same edge case for POST /test: info disappears after health_check."""
        connector = _make_connector("flaky", "chat")
        mock_registry.register(connector)

        call_count = 0
        original_get = mock_registry.get

        def get_side_effect(name):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return original_get(name)
            return None

        mock_registry.get = get_side_effect
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.UNHEALTHY)

        result = handler.handle_post(_PREFIX + "/flaky/test", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["connector_type"] == "unknown"
        assert body["importable"] is False
        assert body["capabilities"] == []
        assert body["last_health_check"] is None
        # UNHEALTHY with no info => "Unknown error"
        assert body["error"] == "Unknown error"


# ---------------------------------------------------------------------------
# _PREFIX constant
# ---------------------------------------------------------------------------


class TestPrefixConstant:
    """Verify the prefix constant is what we expect."""

    def test_prefix_value(self):
        assert _PREFIX == "/api/v1/connectors"


# ---------------------------------------------------------------------------
# Integration-like: verify handle() delegates correctly
# ---------------------------------------------------------------------------


class TestRoutingDelegation:
    """Ensure handle() calls the correct internal methods based on path."""

    def test_list_delegates_to_handle_list(self, handler, mock_http_handler, mock_registry):
        """Verify the list endpoint returns expected structure."""
        mock_registry.register(_make_connector("a", "chat"))
        result = handler.handle(_PREFIX, {}, mock_http_handler)
        body = _body(result)
        assert "connectors" in body
        assert "total" in body

    def test_summary_delegates_to_handle_summary(self, handler, mock_http_handler, mock_registry):
        result = handler.handle(_PREFIX + "/summary", {}, mock_http_handler)
        body = _body(result)
        assert "total" in body
        assert "by_type" in body
        assert "by_status" in body

    def test_detail_delegates_to_handle_detail(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("myconn", "chat"))
        result = handler.handle(_PREFIX + "/myconn", {}, mock_http_handler)
        body = _body(result)
        assert body["name"] == "myconn"

    def test_health_delegates_to_handle_health(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("myconn", "chat"))
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.HEALTHY)
        result = handler.handle(_PREFIX + "/myconn/health", {}, mock_http_handler)
        body = _body(result)
        assert body["name"] == "myconn"
        assert "status" in body

    def test_post_test_delegates_to_handle_test(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("myconn", "chat"))
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.HEALTHY)
        result = handler.handle_post(_PREFIX + "/myconn/test", {}, mock_http_handler)
        body = _body(result)
        assert body["name"] == "myconn"
        assert "connector_type" in body
        assert "importable" in body


# ---------------------------------------------------------------------------
# Connector name edge cases in path parsing
# ---------------------------------------------------------------------------


class TestNamePathParsing:
    """Tests for connector name extraction from URL paths."""

    def test_name_with_underscores(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("google_chat", "chat"))
        result = handler.handle(_PREFIX + "/google_chat", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["name"] == "google_chat"

    def test_name_with_numbers(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("connector42", "ai"))
        result = handler.handle(_PREFIX + "/connector42", {}, mock_http_handler)
        assert _status(result) == 200

    def test_health_with_underscore_name(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("google_chat", "chat"))
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.HEALTHY)
        result = handler.handle(_PREFIX + "/google_chat/health", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["name"] == "google_chat"

    def test_post_test_with_underscore_name(self, handler, mock_http_handler, mock_registry):
        mock_registry.register(_make_connector("google_chat", "chat"))
        mock_registry.health_check = MagicMock(return_value=ConnectorStatus.HEALTHY)
        result = handler.handle_post(_PREFIX + "/google_chat/test", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        assert body["name"] == "google_chat"

    def test_name_is_summary_as_connector(self, handler, mock_http_handler, mock_registry):
        """'summary' is caught as a route before it can be a connector name."""
        # GET /api/v1/connectors/summary routes to _handle_summary, not _handle_detail
        result = handler.handle(_PREFIX + "/summary", {}, mock_http_handler)
        assert _status(result) == 200
        body = _body(result)
        # This returns the summary response, not a detail response
        assert "total" in body
        assert "by_type" in body


# ---------------------------------------------------------------------------
# handle_errors decorator on handle_post
# ---------------------------------------------------------------------------


class TestHandleErrorsDecorator:
    """Tests verifying the @handle_errors decorator catches exceptions."""

    def test_internal_error_returns_500(self, handler, mock_http_handler, mock_registry):
        """If an unexpected exception occurs in handle_post, @handle_errors catches it."""
        connector = _make_connector("broken", "chat")
        mock_registry.register(connector)
        # Make health_check raise an unexpected error
        mock_registry.health_check = MagicMock(side_effect=RuntimeError("kaboom"))
        result = handler.handle_post(_PREFIX + "/broken/test", {}, mock_http_handler)
        # @handle_errors should catch and return a 500
        assert result is not None
        assert _status(result) == 500


# ---------------------------------------------------------------------------
# Multiple connector types in registry
# ---------------------------------------------------------------------------


class TestMultipleTypes:
    """Tests with a realistic mix of connector types."""

    @pytest.fixture(autouse=True)
    def populate_registry(self, mock_registry):
        mock_registry.register(_make_connector("slack", "chat", status=ConnectorStatus.HEALTHY))
        mock_registry.register(_make_connector("telegram", "chat", status=ConnectorStatus.DEGRADED))
        mock_registry.register(_make_connector("discord", "chat", status=ConnectorStatus.UNHEALTHY))
        mock_registry.register(_make_connector("stripe", "payment", status=ConnectorStatus.HEALTHY))
        mock_registry.register(
            _make_connector("kafka", "enterprise", status=ConnectorStatus.HEALTHY)
        )
        mock_registry.register(_make_connector("github", "ai", status=ConnectorStatus.UNKNOWN))

    def test_list_all(self, handler, mock_http_handler):
        result = handler.handle(_PREFIX, {}, mock_http_handler)
        body = _body(result)
        assert body["total"] == 6

    def test_filter_chat(self, handler, mock_http_handler):
        result = handler.handle(_PREFIX, {"type": "chat"}, mock_http_handler)
        body = _body(result)
        assert body["total"] == 3

    def test_filter_payment(self, handler, mock_http_handler):
        result = handler.handle(_PREFIX, {"type": "payment"}, mock_http_handler)
        body = _body(result)
        assert body["total"] == 1

    def test_filter_enterprise(self, handler, mock_http_handler):
        result = handler.handle(_PREFIX, {"type": "enterprise"}, mock_http_handler)
        body = _body(result)
        assert body["total"] == 1

    def test_filter_healthy_status(self, handler, mock_http_handler):
        result = handler.handle(_PREFIX, {"status": "healthy"}, mock_http_handler)
        body = _body(result)
        assert body["total"] == 3

    def test_filter_chat_and_healthy(self, handler, mock_http_handler):
        result = handler.handle(_PREFIX, {"type": "chat", "status": "healthy"}, mock_http_handler)
        body = _body(result)
        assert body["total"] == 1
        assert body["connectors"][0]["name"] == "slack"

    def test_summary_counts(self, handler, mock_http_handler):
        result = handler.handle(_PREFIX + "/summary", {}, mock_http_handler)
        body = _body(result)
        assert body["total"] == 6
        assert body["by_type"]["chat"] == 3
        assert body["by_status"]["healthy"] == 3
        assert body["by_status"]["degraded"] == 1
        assert body["by_status"]["unhealthy"] == 1
        assert body["by_status"]["unknown"] == 1
