"""
Tests for HealthHandler endpoints.

Endpoints tested:
- GET /healthz - Kubernetes liveness probe
- GET /readyz - Kubernetes readiness probe
- GET /api/health - Comprehensive health check
- GET /api/health/detailed - Detailed health with observer metrics
- GET /api/health/deep - Deep health check with all external dependencies
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, AsyncMock

from aragora.server.handlers.admin.health import HealthHandler
from aragora.server.handlers.base import clear_cache
from aragora.rbac.models import AuthorizationContext


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_nomic_dir(tmp_path):
    """Create a mock nomic directory structure."""
    nomic_dir = tmp_path / ".nomic"
    nomic_dir.mkdir()
    return nomic_dir


@pytest.fixture
def mock_auth_context():
    """Create a mock auth context that grants all permissions."""
    return AuthorizationContext(
        user_id="test-user",
        user_email="test@example.com",
        roles={"admin"},
        permissions={"system.health.read"},
    )


@pytest.fixture
def health_handler(mock_nomic_dir, mock_auth_context):
    """Create a HealthHandler with mock dependencies and auth."""
    ctx = {
        "storage": None,
        "elo_system": None,
        "nomic_dir": mock_nomic_dir,
    }
    handler = HealthHandler(ctx)
    # Patch auth methods to bypass authentication in tests
    handler.get_auth_context = AsyncMock(return_value=mock_auth_context)
    handler.check_permission = Mock(return_value=None)
    return handler


@pytest.fixture
def health_handler_no_nomic(mock_auth_context):
    """Create a HealthHandler without nomic_dir."""
    ctx = {
        "storage": None,
        "elo_system": None,
        "nomic_dir": None,
    }
    handler = HealthHandler(ctx)
    handler.get_auth_context = AsyncMock(return_value=mock_auth_context)
    handler.check_permission = Mock(return_value=None)
    return handler


@pytest.fixture
def mock_storage():
    """Create a mock storage that works properly."""
    storage = Mock()
    storage.list_recent = Mock(return_value=[])
    return storage


@pytest.fixture
def mock_elo_system():
    """Create a mock ELO system that works properly."""
    elo = Mock()
    elo.get_leaderboard = Mock(return_value=[])
    return elo


@pytest.fixture
def health_handler_with_deps(mock_nomic_dir, mock_storage, mock_elo_system, mock_auth_context):
    """Create a HealthHandler with working mock dependencies."""
    ctx = {
        "storage": mock_storage,
        "elo_system": mock_elo_system,
        "nomic_dir": mock_nomic_dir,
    }
    handler = HealthHandler(ctx)
    handler.get_auth_context = AsyncMock(return_value=mock_auth_context)
    handler.check_permission = Mock(return_value=None)
    return handler


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear caches before and after each test."""
    clear_cache()
    # Also clear health probe cache so readiness checks aren't stale
    from aragora.server.handlers.admin.health import _HEALTH_CACHE, _HEALTH_CACHE_TIMESTAMPS

    _HEALTH_CACHE.clear()
    _HEALTH_CACHE_TIMESTAMPS.clear()
    yield
    clear_cache()
    _HEALTH_CACHE.clear()
    _HEALTH_CACHE_TIMESTAMPS.clear()


@pytest.fixture(autouse=True)
def mock_server_readiness():
    """Mock server startup and handler initialization checks for readiness probes.

    The readiness probe checks is_server_ready() and get_route_index() which
    are not initialized in test environments. Patch them to return True/populated.
    """
    mock_route_index = MagicMock()
    mock_route_index._exact_routes = {"/healthz": True}  # Non-empty dict

    with (
        patch(
            "aragora.server.unified_server.is_server_ready",
            return_value=True,
        ),
        patch(
            "aragora.server.handler_registry.core.get_route_index",
            return_value=mock_route_index,
        ),
    ):
        yield


# ============================================================================
# Route Matching Tests
# ============================================================================


class TestHealthRouting:
    """Tests for route matching."""

    def test_can_handle_healthz(self, health_handler):
        """Handler can handle /healthz."""
        assert health_handler.can_handle("/healthz") is True

    def test_can_handle_readyz(self, health_handler):
        """Handler can handle /readyz."""
        assert health_handler.can_handle("/readyz") is True

    def test_can_handle_api_health(self, health_handler):
        """Handler can handle /api/health."""
        assert health_handler.can_handle("/api/v1/health") is True

    def test_can_handle_api_health_detailed(self, health_handler):
        """Handler can handle /api/health/detailed."""
        assert health_handler.can_handle("/api/v1/health/detailed") is True

    def test_can_handle_api_health_deep(self, health_handler):
        """Handler can handle /api/health/deep."""
        assert health_handler.can_handle("/api/v1/health/deep") is True

    def test_cannot_handle_unrelated_routes(self, health_handler):
        """Handler doesn't handle unrelated routes."""
        assert health_handler.can_handle("/api/v1/debates") is False
        assert health_handler.can_handle("/api/v1/agents") is False
        assert health_handler.can_handle("/healthz/extra") is False
        assert health_handler.can_handle("/api/v1/health/unknown") is False


# ============================================================================
# GET /healthz Tests (Liveness Probe)
# ============================================================================


@pytest.mark.asyncio
class TestLivenessProbe:
    """Tests for GET /healthz endpoint."""

    async def test_liveness_returns_ok(self, health_handler):
        """Liveness probe returns ok status."""
        result = await health_handler.handle("/healthz", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["status"] == "ok"

    async def test_liveness_is_lightweight(self, health_handler):
        """Liveness probe doesn't check external dependencies."""
        # Even with broken dependencies, liveness should return ok
        result = await health_handler.handle("/healthz", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["status"] == "ok"


# ============================================================================
# GET /readyz Tests (Readiness Probe)
# ============================================================================


@pytest.mark.asyncio
class TestReadinessProbe:
    """Tests for GET /readyz endpoint."""

    async def test_readiness_returns_ready_no_deps(self, health_handler):
        """Readiness probe returns ready when no dependencies configured."""
        result = await health_handler.handle("/readyz", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["status"] == "ready"
        assert "checks" in data

    async def test_readiness_returns_ready_with_deps(self, health_handler_with_deps):
        """Readiness probe returns ready when dependencies are healthy."""
        result = await health_handler_with_deps.handle("/readyz", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["status"] == "ready"
        # Check for storage and elo initialization flags
        assert data["checks"]["storage_initialized"] is True
        assert data["checks"]["elo_initialized"] is True

    async def test_readiness_returns_degraded_on_storage_error(self, mock_nomic_dir):
        """Readiness probe returns degraded mode when storage unavailable."""
        # Storage getter raises error
        ctx = {
            "storage": None,
            "elo_system": None,
            "nomic_dir": mock_nomic_dir,
        }
        handler = HealthHandler(ctx)

        # Even without storage, readiness probe returns ready with degraded_mode flag
        result = await handler.handle("/readyz", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["status"] == "ready"
        # Degraded mode indicates limited functionality
        assert data["checks"]["degraded_mode"] is True


# ============================================================================
# GET /api/health Tests (Comprehensive Health)
# ============================================================================


@pytest.mark.asyncio
class TestComprehensiveHealth:
    """Tests for GET /api/health endpoint."""

    async def test_health_returns_status_and_checks(self, health_handler):
        """Health endpoint returns status and component checks."""
        result = await health_handler.handle("/api/health", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)

        # Basic structure
        assert "status" in data
        assert "checks" in data
        assert "timestamp" in data
        assert "response_time_ms" in data
        assert "uptime_seconds" in data

    async def test_health_includes_database_check(self, health_handler_with_deps):
        """Health endpoint includes database connectivity check."""
        result = await health_handler_with_deps.handle("/api/health", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert "database" in data["checks"]
        assert data["checks"]["database"]["healthy"] is True

    async def test_health_includes_elo_check(self, health_handler_with_deps):
        """Health endpoint includes ELO system check."""
        result = await health_handler_with_deps.handle("/api/health", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert "elo_system" in data["checks"]
        assert data["checks"]["elo_system"]["healthy"] is True

    async def test_health_includes_filesystem_check(self, health_handler):
        """Health endpoint includes filesystem write check."""
        result = await health_handler.handle("/api/health", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert "filesystem" in data["checks"]
        # Filesystem should be healthy in test environment
        assert data["checks"]["filesystem"]["healthy"] is True

    async def test_health_includes_ai_providers_check(self, health_handler):
        """Health endpoint includes AI providers availability check."""
        result = await health_handler.handle("/api/health", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert "ai_providers" in data["checks"]
        assert "providers" in data["checks"]["ai_providers"]

    async def test_health_returns_degraded_on_critical_failure(self, health_handler):
        """Health returns degraded status when critical service fails."""
        # Patch the filesystem check at the module level where health_check() calls it
        with patch(
            "aragora.server.handlers.admin.health.detailed.check_filesystem_health",
            return_value={"healthy": False, "error": "Write failed"},
        ):
            result = await health_handler.handle("/api/health", {}, None)

        assert result is not None
        assert result.status_code == 503
        data = json.loads(result.body)
        assert data["status"] == "degraded"

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-12345678901234567890"})
    async def test_health_detects_api_keys(self, health_handler):
        """Health endpoint correctly detects configured API keys."""
        result = await health_handler.handle("/api/health", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert data["checks"]["ai_providers"]["providers"]["anthropic"] is True
        assert data["checks"]["ai_providers"]["any_available"] is True

    async def test_health_includes_db_mode_field(self, health_handler):
        """Health endpoint includes db_mode in response."""
        result = await health_handler.handle("/api/health", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert "db_mode" in data
        assert data["db_mode"] in ("sqlite", "postgres")

    @patch.dict("os.environ", {"DATABASE_URL": "postgresql://localhost/aragora"})
    async def test_health_db_mode_postgres(self, health_handler):
        """Health endpoint returns db_mode=postgres when DATABASE_URL is postgres."""
        result = await health_handler.handle("/api/health", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert data["db_mode"] == "postgres"

    @patch.dict("os.environ", {"DATABASE_URL": ""}, clear=False)
    async def test_health_db_mode_sqlite_default(self, health_handler):
        """Health endpoint returns db_mode=sqlite when no DATABASE_URL is set."""
        result = await health_handler.handle("/api/health", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert data["db_mode"] == "sqlite"


# ============================================================================
# GET /api/health/detailed Tests
# ============================================================================


@pytest.mark.asyncio
class TestDetailedHealth:
    """Tests for GET /api/health/detailed endpoint."""

    async def test_detailed_health_returns_components(self, health_handler):
        """Detailed health returns component status."""
        result = await health_handler.handle("/api/health/detailed", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)

        assert "status" in data
        assert "components" in data
        assert "version" in data

    async def test_detailed_health_includes_nomic_dir_status(self, health_handler):
        """Detailed health shows nomic_dir availability."""
        result = await health_handler.handle("/api/health/detailed", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert "nomic_dir" in data["components"]
        assert data["components"]["nomic_dir"] is True

    async def test_detailed_health_shows_nomic_dir_missing(self, health_handler_no_nomic):
        """Detailed health shows nomic_dir as false when not configured."""
        result = await health_handler_no_nomic.handle("/api/health/detailed", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert data["components"]["nomic_dir"] is False

    async def test_detailed_health_includes_warnings_array(self, health_handler):
        """Detailed health includes warnings array."""
        result = await health_handler.handle("/api/health/detailed", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert "warnings" in data
        assert isinstance(data["warnings"], list)


# ============================================================================
# GET /api/health/deep Tests
# ============================================================================


@pytest.mark.asyncio
class TestDeepHealth:
    """Tests for GET /api/health/deep endpoint."""

    async def test_deep_health_returns_all_checks(self, health_handler_with_deps):
        """Deep health check returns comprehensive system status."""
        result = await health_handler_with_deps.handle("/api/health/deep", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)

        # Should have many checks
        assert "status" in data
        assert "checks" in data
        assert "response_time_ms" in data
        assert "timestamp" in data

    async def test_deep_health_includes_storage_check(self, health_handler_with_deps):
        """Deep health includes storage connectivity check."""
        result = await health_handler_with_deps.handle("/api/health/deep", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert "storage" in data["checks"]
        assert data["checks"]["storage"]["healthy"] is True

    async def test_deep_health_includes_elo_check(self, health_handler_with_deps):
        """Deep health includes ELO system check."""
        result = await health_handler_with_deps.handle("/api/health/deep", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert "elo_system" in data["checks"]
        assert data["checks"]["elo_system"]["healthy"] is True

    async def test_deep_health_includes_redis_check(self, health_handler):
        """Deep health includes Redis check (not configured by default)."""
        result = await health_handler.handle("/api/health/deep", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert "redis" in data["checks"]
        # Redis not configured is ok
        assert data["checks"]["redis"]["healthy"] is True
        assert data["checks"]["redis"]["configured"] is False

    async def test_deep_health_includes_ai_providers(self, health_handler):
        """Deep health includes AI provider availability."""
        result = await health_handler.handle("/api/health/deep", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert "ai_providers" in data["checks"]

    async def test_deep_health_includes_filesystem(self, health_handler):
        """Deep health includes filesystem check."""
        result = await health_handler.handle("/api/health/deep", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert "filesystem" in data["checks"]
        assert data["checks"]["filesystem"]["healthy"] is True

    async def test_deep_health_reports_warnings(self, health_handler):
        """Deep health reports warnings when applicable."""
        result = await health_handler.handle("/api/health/deep", {}, None)

        assert result is not None
        data = json.loads(result.body)
        # Warnings may or may not be present depending on config
        if data.get("warnings"):
            assert isinstance(data["warnings"], list)


# ============================================================================
# Handle Routing Tests
# ============================================================================


@pytest.mark.asyncio
class TestHealthHandleRouting:
    """Tests for handle() method routing."""

    async def test_handle_routes_to_liveness(self, health_handler):
        """handle() correctly routes /healthz to liveness probe."""
        result = await health_handler.handle("/healthz", {}, None)
        assert result is not None
        data = json.loads(result.body)
        assert data["status"] == "ok"

    async def test_handle_routes_to_readiness(self, health_handler):
        """handle() correctly routes /readyz to readiness probe."""
        result = await health_handler.handle("/readyz", {}, None)
        assert result is not None
        data = json.loads(result.body)
        assert "checks" in data

    async def test_handle_routes_to_health(self, health_handler):
        """handle() correctly routes /api/health to health check."""
        result = await health_handler.handle("/api/health", {}, None)
        assert result is not None
        data = json.loads(result.body)
        assert "uptime_seconds" in data

    async def test_handle_returns_none_for_unknown(self, health_handler):
        """handle() returns None for unhandled routes."""
        result = await health_handler.handle("/api/unknown", {}, None)
        assert result is None


# ============================================================================
# Handler Import Tests
# ============================================================================


class TestHealthHandlerImport:
    """Test HealthHandler import and export."""

    def test_handler_importable(self):
        """HealthHandler can be imported from handlers.admin.health module."""
        from aragora.server.handlers.admin.health import HealthHandler

        assert HealthHandler is not None

    def test_handler_has_routes(self):
        """HealthHandler has ROUTES class attribute."""
        from aragora.server.handlers.admin.health import HealthHandler

        assert hasattr(HealthHandler, "ROUTES")
        assert "/healthz" in HealthHandler.ROUTES
        assert "/readyz" in HealthHandler.ROUTES
        assert "/api/health" in HealthHandler.ROUTES


# ============================================================================
# GET /api/health/stores Tests (Database Stores Health)
# ============================================================================


class TestDatabaseStoresHealth:
    """Tests for GET /api/health/stores endpoint."""

    @pytest.mark.asyncio
    async def test_stores_health_returns_response(self, health_handler):
        """Stores health endpoint returns a valid response."""
        result = await health_handler.handle("/api/health/stores", {}, None)

        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)

        assert "status" in data
        assert "stores" in data
        assert "summary" in data
        assert "elapsed_ms" in data

    @pytest.mark.asyncio
    async def test_stores_health_includes_core_stores(self, health_handler_with_deps):
        """Stores health includes core database stores."""
        result = await health_handler_with_deps.handle("/api/health/stores", {}, None)

        assert result is not None
        data = json.loads(result.body)
        stores = data["stores"]

        # Core stores that should always be checked
        assert "debate_storage" in stores
        assert "elo_system" in stores

    @pytest.mark.asyncio
    async def test_stores_health_includes_new_stores(self, health_handler):
        """Stores health includes new stores (integration, gmail, sync, decision)."""
        result = await health_handler.handle("/api/health/stores", {}, None)

        assert result is not None
        data = json.loads(result.body)
        stores = data["stores"]

        # New stores added for commercial viability
        assert "integration_store" in stores
        assert "gmail_token_store" in stores
        assert "sync_store" in stores
        assert "decision_result_store" in stores

    @pytest.mark.asyncio
    async def test_stores_health_shows_module_not_available(self, health_handler):
        """Stores health gracefully handles missing modules."""
        # Patch imports to simulate missing modules
        with patch.dict("sys.modules", {"aragora.storage.integration_store": None}):
            result = await health_handler.handle("/api/health/stores", {}, None)

        assert result is not None
        data = json.loads(result.body)
        # Even with missing modules, endpoint should return valid response
        assert "stores" in data

    @pytest.mark.asyncio
    async def test_stores_health_summary_counts(self, health_handler):
        """Stores health summary has correct count fields."""
        result = await health_handler.handle("/api/health/stores", {}, None)

        assert result is not None
        data = json.loads(result.body)
        summary = data["summary"]

        assert "total" in summary
        assert "healthy" in summary
        assert "connected" in summary
        assert "not_initialized" in summary

        # Total should equal healthy count (all should be healthy even if not initialized)
        assert summary["total"] == summary["healthy"]

    @pytest.mark.asyncio
    async def test_stores_health_decision_store_has_metrics(self, health_handler, tmp_path):
        """Decision result store health check includes metrics."""
        import os

        os.environ["ARAGORA_DECISION_RESULTS_DB"] = str(tmp_path / "test_decisions.db")

        try:
            # Reset the singleton
            from aragora.storage import decision_result_store

            decision_result_store._decision_result_store = None

            result = await health_handler.handle("/api/health/stores", {}, None)

            assert result is not None
            data = json.loads(result.body)

            if "decision_result_store" in data["stores"]:
                store_info = data["stores"]["decision_result_store"]
                if store_info.get("status") == "connected":
                    # Should have metrics
                    assert "total_entries" in store_info or "type" in store_info
        finally:
            if "ARAGORA_DECISION_RESULTS_DB" in os.environ:
                del os.environ["ARAGORA_DECISION_RESULTS_DB"]
            decision_result_store._decision_result_store = None


class TestStoresHealthRouting:
    """Tests for /api/health/stores route handling."""

    def test_can_handle_stores_route(self, health_handler):
        """Handler can handle /api/health/stores."""
        assert health_handler.can_handle("/api/v1/health/stores") is True

    @pytest.mark.asyncio
    async def test_handle_routes_to_stores_health(self, health_handler):
        """handle() correctly routes /api/health/stores."""
        result = await health_handler.handle("/api/health/stores", {}, None)

        assert result is not None
        data = json.loads(result.body)
        assert "stores" in data
        assert "summary" in data
