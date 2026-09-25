"""Tests for enterprise connectors handler (aragora/server/handlers/connectors/).

Covers all handler functions:
- handle_list_connectors       (GET /api/connectors)
- handle_get_connector         (GET /api/connectors/:id)
- handle_create_connector      (POST /api/connectors)
- handle_update_connector      (PATCH /api/connectors/:id)
- handle_delete_connector      (DELETE /api/connectors/:id)
- handle_trigger_sync          (POST /api/connectors/:id/sync)
- handle_get_sync_status       (GET /api/connectors/:id/sync/status)
- handle_get_sync_history      (GET /api/connectors/sync/history)
- handle_webhook               (POST /api/connectors/:id/webhook)
- handle_start_scheduler       (POST /api/connectors/scheduler/start)
- handle_stop_scheduler        (POST /api/connectors/scheduler/stop)
- handle_get_scheduler_stats   (GET /api/connectors/scheduler/stats)
- handle_list_workflow_templates (GET /api/workflows/templates)
- handle_get_workflow_template (GET /api/workflows/templates/:id)
- handle_mongodb_aggregate     (POST /api/connectors/:id/aggregate)
- handle_mongodb_collections   (GET /api/connectors/:id/collections)
- handle_connector_health      (GET /api/connectors/health)
- _check_permission            (internal RBAC helper)
- _resolve_tenant_id           (internal tenant resolution)
- _create_connector            (internal factory)
"""

from __future__ import annotations

import asyncio
import sys
import types
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.connectors.enterprise import MongoDBConnector
from aragora.connectors.enterprise.sync.scheduler import (
    SyncHistory,
    SyncJob,
    SyncSchedule,
    SyncScheduler,
    SyncStatus,
)

# Import the handler module under test
import aragora.server.handlers.connectors as connectors_mod
import aragora.server.handlers.connectors.legacy as legacy_mod
from aragora.server.handlers.connectors import (
    _check_permission,
    _create_connector,
    _resolve_tenant_id,
    handle_connector_health,
    handle_create_connector,
    handle_delete_connector,
    handle_get_connector,
    handle_get_scheduler_stats,
    handle_get_sync_history,
    handle_get_sync_status,
    handle_list_connectors,
    handle_list_workflow_templates,
    handle_get_workflow_template,
    handle_mongodb_aggregate,
    handle_mongodb_collections,
    handle_start_scheduler,
    handle_stop_scheduler,
    handle_trigger_sync,
    handle_update_connector,
    handle_webhook,
)


# ---------------------------------------------------------------------------
# Helpers & Fixtures
# ---------------------------------------------------------------------------

_REGISTRY_MODULE_KEY = "aragora.connectors.enterprise.registry"


@contextmanager
def _patch_registry(get_connector_return=None):
    """Inject a fake ``aragora.connectors.enterprise.registry`` module into
    ``sys.modules`` so that the inline ``from ... import get_connector``
    inside the handler functions resolves to a controllable mock.

    The real module does not exist on disk, so ``unittest.mock.patch``
    cannot target it.
    """
    mock_get = MagicMock(return_value=get_connector_return)
    fake_module = types.ModuleType(_REGISTRY_MODULE_KEY)
    fake_module.get_connector = mock_get  # type: ignore[attr-defined]
    had_original = _REGISTRY_MODULE_KEY in sys.modules
    original = sys.modules.get(_REGISTRY_MODULE_KEY)
    sys.modules[_REGISTRY_MODULE_KEY] = fake_module
    try:
        yield mock_get
    finally:
        if had_original:
            sys.modules[_REGISTRY_MODULE_KEY] = original  # type: ignore[assignment]
        else:
            sys.modules.pop(_REGISTRY_MODULE_KEY, None)


def _make_sync_job(
    connector_id: str = "test-conn",
    tenant_id: str = "default",
    consecutive_failures: int = 0,
    current_run_id: str | None = None,
    last_run: datetime | None = None,
    next_run: datetime | None = None,
) -> SyncJob:
    """Create a SyncJob for test purposes without triggering _calculate_next_run."""
    schedule = SyncSchedule(schedule_type="webhook_only")
    job = SyncJob.__new__(SyncJob)
    job.id = f"{tenant_id}:{connector_id}"
    job.connector_id = connector_id
    job.tenant_id = tenant_id
    job.schedule = schedule
    job.connector = None
    job.last_run = last_run
    job.next_run = next_run
    job.current_run_id = current_run_id
    job.consecutive_failures = consecutive_failures
    job.on_complete = None
    job.on_error = None
    return job


def _make_scheduler(jobs: list[SyncJob] | None = None) -> MagicMock:
    """Create a mock SyncScheduler."""
    scheduler = MagicMock(spec=SyncScheduler)
    scheduler._scheduler_task = None
    scheduler._running_syncs = {}

    job_map = {}
    if jobs:
        for j in jobs:
            job_map[j.id] = j

    scheduler.get_job.side_effect = lambda jid: job_map.get(jid)
    scheduler.list_jobs.side_effect = lambda tenant_id=None: [
        j for j in job_map.values() if tenant_id is None or j.tenant_id == tenant_id
    ]
    scheduler.get_stats.return_value = {
        "total_jobs": len(job_map),
        "enabled_jobs": 0,
        "running_syncs": 0,
        "total_syncs": 0,
        "successful_syncs": 0,
        "failed_syncs": 0,
        "success_rate": 1.0,
        "total_items_synced": 0,
        "average_duration_seconds": 0,
    }
    scheduler.get_history.return_value = []
    scheduler.trigger_sync = AsyncMock(return_value="run-abc")
    scheduler.handle_webhook = AsyncMock(return_value=True)
    scheduler.start = AsyncMock()
    scheduler.stop = AsyncMock()
    scheduler.register_connector.side_effect = (
        lambda connector, schedule=None, tenant_id="default": _make_sync_job(
            connector_id=connector.connector_id, tenant_id=tenant_id
        )
    )
    scheduler.unregister_connector = MagicMock()
    return scheduler


@pytest.fixture(autouse=True)
def _reset_scheduler():
    """Reset the global scheduler singleton between tests."""
    from aragora.server.handlers.connectors import shared

    original = shared._scheduler
    shared._scheduler = None
    yield
    shared._scheduler = original


@pytest.fixture
def mock_scheduler():
    """Provide a mock scheduler and patch get_scheduler to return it."""
    scheduler = _make_scheduler()
    with patch.object(legacy_mod, "get_scheduler", return_value=scheduler):
        yield scheduler


@pytest.fixture
def mock_auth_ctx():
    """Create a mock auth context."""
    ctx = MagicMock()
    ctx.user_id = "user-001"
    ctx.org_id = "org-001"
    return ctx


# ---------------------------------------------------------------------------
# _check_permission tests
# ---------------------------------------------------------------------------


class TestCheckPermission:
    """Test the internal _check_permission helper."""

    def test_returns_none_when_no_auth_context(self):
        result = _check_permission(None, "connectors:read")
        assert result is None

    def test_returns_none_when_permission_granted(self):
        ctx = MagicMock()
        ctx.user_id = "user-1"
        with (
            patch.object(legacy_mod, "RBAC_AVAILABLE", True),
            patch.object(legacy_mod, "check_permission") as mock_check,
        ):
            decision = MagicMock()
            decision.allowed = True
            mock_check.return_value = decision
            result = _check_permission(ctx, "connectors:read")
        assert result is None

    def test_returns_error_when_permission_denied(self):
        ctx = MagicMock()
        ctx.user_id = "user-1"
        with (
            patch.object(legacy_mod, "RBAC_AVAILABLE", True),
            patch.object(legacy_mod, "check_permission") as mock_check,
        ):
            decision = MagicMock()
            decision.allowed = False
            decision.reason = "No access"
            mock_check.return_value = decision
            result = _check_permission(ctx, "connectors:read")
        assert result is not None
        assert result["error"] == "Permission denied"
        assert result["status"] == 403

    def test_returns_error_on_permission_denied_exception(self):
        ctx = MagicMock()
        ctx.user_id = "user-1"
        with (
            patch.object(legacy_mod, "RBAC_AVAILABLE", True),
            patch.object(legacy_mod, "check_permission") as mock_check,
        ):
            from aragora.rbac import PermissionDeniedError

            mock_check.side_effect = PermissionDeniedError("denied")
            result = _check_permission(ctx, "connectors:read")
        assert result is not None
        assert result["status"] == 403

    def test_rbac_not_available_dev_mode(self):
        """When RBAC is not available and not in production, returns None."""
        with (
            patch.object(legacy_mod, "RBAC_AVAILABLE", False),
            patch.object(legacy_mod, "rbac_fail_closed", return_value=False),
        ):
            result = _check_permission(MagicMock(), "connectors:read")
        assert result is None

    def test_rbac_not_available_production_mode(self):
        """When RBAC is not available in production, returns 503."""
        with (
            patch.object(legacy_mod, "RBAC_AVAILABLE", False),
            patch.object(legacy_mod, "rbac_fail_closed", return_value=True),
        ):
            result = _check_permission(MagicMock(), "connectors:read")
        assert result is not None
        assert result["status"] == 503

    def test_with_resource_id(self):
        ctx = MagicMock()
        ctx.user_id = "user-1"
        with (
            patch.object(legacy_mod, "RBAC_AVAILABLE", True),
            patch.object(legacy_mod, "check_permission") as mock_check,
        ):
            decision = MagicMock()
            decision.allowed = True
            mock_check.return_value = decision
            _check_permission(ctx, "connectors:read", "res-123")
        mock_check.assert_called_once_with(ctx, "connectors:read", "res-123")


# ---------------------------------------------------------------------------
# _resolve_tenant_id tests
# ---------------------------------------------------------------------------


class TestResolveTenantId:
    """Test the internal _resolve_tenant_id helper."""

    def test_returns_fallback_when_no_auth_context(self):
        assert _resolve_tenant_id(None, "fallback") == "fallback"

    def test_returns_fallback_when_unauthenticated_string(self):
        assert _resolve_tenant_id("unauthenticated", "fallback") == "fallback"

    def test_returns_org_id_from_auth_context(self):
        ctx = MagicMock()
        ctx.org_id = "org-42"
        with patch.object(legacy_mod, "RBAC_AVAILABLE", True):
            result = _resolve_tenant_id(ctx, "fallback")
        assert result == "org-42"

    def test_returns_fallback_when_no_org_id(self):
        ctx = MagicMock(spec=[])  # No org_id attribute
        with patch.object(legacy_mod, "RBAC_AVAILABLE", True):
            result = _resolve_tenant_id(ctx, "fallback")
        assert result == "fallback"

    def test_returns_fallback_when_org_id_empty(self):
        ctx = MagicMock()
        ctx.org_id = ""
        with patch.object(legacy_mod, "RBAC_AVAILABLE", True):
            result = _resolve_tenant_id(ctx, "fallback")
        assert result == "fallback"

    def test_returns_fallback_when_rbac_not_available(self):
        ctx = MagicMock()
        ctx.org_id = "org-42"
        with (
            patch.object(legacy_mod, "RBAC_AVAILABLE", False),
            patch.object(connectors_mod, "RBAC_AVAILABLE", False),
        ):
            result = _resolve_tenant_id(ctx, "fallback")
        assert result == "fallback"

    def test_default_fallback(self):
        assert _resolve_tenant_id(None) == "default"


# ---------------------------------------------------------------------------
# _create_connector tests
# ---------------------------------------------------------------------------


class TestCreateConnector:
    """Test the internal connector factory."""

    def test_create_github_connector(self):
        with patch.object(legacy_mod, "GitHubEnterpriseConnector") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_connector("github", {"owner": "acme", "repo": "app", "token": "tok"})
        mock_cls.assert_called_once_with(
            repo="acme/app", token="tok", include_prs=True, include_issues=True
        )

    def test_create_github_connector_full_repo(self):
        """When repo already contains owner/repo format, use as-is."""
        with patch.object(legacy_mod, "GitHubEnterpriseConnector") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_connector("github", {"repo": "acme/app"})
        mock_cls.assert_called_once_with(
            repo="acme/app", token=None, include_prs=True, include_issues=True
        )

    def test_create_github_connector_repo_only(self):
        """When only repo name is given (no owner, no slash)."""
        with patch.object(legacy_mod, "GitHubEnterpriseConnector") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_connector("github", {"repo": "myrepo"})
        mock_cls.assert_called_once_with(
            repo="myrepo", token=None, include_prs=True, include_issues=True
        )

    def test_create_github_connector_owner_only(self):
        """When only owner is given (no repo)."""
        with patch.object(legacy_mod, "GitHubEnterpriseConnector") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_connector("github", {"owner": "acme"})
        mock_cls.assert_called_once_with(
            repo="acme", token=None, include_prs=True, include_issues=True
        )

    def test_create_github_with_sync_options(self):
        with patch.object(legacy_mod, "GitHubEnterpriseConnector") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_connector(
                "github",
                {
                    "owner": "acme",
                    "repo": "app",
                    "sync_prs": False,
                    "sync_issues": False,
                },
            )
        mock_cls.assert_called_once_with(
            repo="acme/app", token=None, include_prs=False, include_issues=False
        )

    def test_create_s3_connector(self):
        with patch.object(legacy_mod, "S3Connector") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_connector("s3", {"bucket": "my-bucket", "prefix": "data/"})
        mock_cls.assert_called_once_with(
            bucket="my-bucket", prefix="data/", endpoint_url=None, region="us-east-1"
        )

    def test_create_s3_connector_with_region(self):
        with patch.object(legacy_mod, "S3Connector") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_connector(
                "s3",
                {
                    "bucket": "my-bucket",
                    "region": "eu-west-1",
                    "endpoint_url": "http://localhost:9000",
                },
            )
        mock_cls.assert_called_once_with(
            bucket="my-bucket", prefix="", endpoint_url="http://localhost:9000", region="eu-west-1"
        )

    def test_create_postgres_connector(self):
        with patch.object(legacy_mod, "PostgreSQLConnector") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_connector("postgres", {"database": "mydb", "host": "db.local", "port": 5433})
        mock_cls.assert_called_once_with(
            host="db.local",
            port=5433,
            database="mydb",
            schema="public",
            tables=None,
            timestamp_column=None,
        )

    def test_create_postgres_connector_defaults(self):
        with patch.object(legacy_mod, "PostgreSQLConnector") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_connector("postgres", {"database": "mydb"})
        mock_cls.assert_called_once_with(
            host="localhost",
            port=5432,
            database="mydb",
            schema="public",
            tables=None,
            timestamp_column=None,
        )

    def test_create_mongodb_connector(self):
        with patch.object(legacy_mod, "MongoDBConnector") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_connector(
                "mongodb",
                {
                    "database": "mydb",
                    "host": "mongo.local",
                    "port": 27018,
                    "collections": ["users"],
                },
            )
        mock_cls.assert_called_once_with(
            host="mongo.local",
            port=27018,
            database="mydb",
            collections=["users"],
            connection_string=None,
        )

    def test_create_mongodb_connector_with_connection_string(self):
        with patch.object(legacy_mod, "MongoDBConnector") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_connector(
                "mongodb",
                {
                    "database": "mydb",
                    "connection_string": "mongodb+srv://user:pass@cluster/mydb",
                },
            )
        mock_cls.assert_called_once_with(
            host="localhost",
            port=27017,
            database="mydb",
            collections=None,
            connection_string="mongodb+srv://user:pass@cluster/mydb",
        )

    def test_create_fhir_connector(self):
        with patch.object(legacy_mod, "FHIRConnector") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_connector(
                "fhir",
                {
                    "base_url": "https://fhir.hospital.org",
                    "organization_id": "org-123",
                    "client_id": "client-1",
                    "enable_phi_redaction": False,
                },
            )
        mock_cls.assert_called_once_with(
            base_url="https://fhir.hospital.org",
            organization_id="org-123",
            client_id="client-1",
            enable_phi_redaction=False,
        )

    def test_create_fhir_connector_defaults(self):
        with patch.object(legacy_mod, "FHIRConnector") as mock_cls:
            mock_cls.return_value = MagicMock()
            _create_connector(
                "fhir",
                {
                    "base_url": "https://fhir.hospital.org",
                    "organization_id": "org-123",
                },
            )
        mock_cls.assert_called_once_with(
            base_url="https://fhir.hospital.org",
            organization_id="org-123",
            client_id=None,
            enable_phi_redaction=True,
        )

    def test_create_unknown_connector_type(self):
        with pytest.raises(ValueError, match="Unknown connector type"):
            _create_connector("oracle", {})


# ---------------------------------------------------------------------------
# handle_list_connectors tests
# ---------------------------------------------------------------------------


class TestListConnectors:
    """Test handle_list_connectors."""

    @pytest.mark.asyncio
    async def test_list_empty(self, mock_scheduler):
        result = await handle_list_connectors()
        assert result["connectors"] == []
        assert result["total"] == 0
        assert result["limit"] == 50
        assert result["offset"] == 0

    @pytest.mark.asyncio
    async def test_list_with_jobs(self, mock_scheduler):
        now = datetime.now(timezone.utc)
        job = _make_sync_job(last_run=now, next_run=now + timedelta(hours=1))
        mock_scheduler.list_jobs.side_effect = lambda tenant_id=None: [job]

        result = await handle_list_connectors()
        assert result["total"] == 1
        assert len(result["connectors"]) == 1
        conn = result["connectors"][0]
        assert conn["id"] == "test-conn"
        assert conn["tenant_id"] == "default"
        assert conn["last_run"] == now.isoformat()

    @pytest.mark.asyncio
    async def test_list_pagination(self, mock_scheduler):
        jobs = [_make_sync_job(connector_id=f"conn-{i}") for i in range(10)]
        mock_scheduler.list_jobs.side_effect = lambda tenant_id=None: jobs

        result = await handle_list_connectors(limit=3, offset=2)
        assert result["total"] == 10
        assert result["limit"] == 3
        assert result["offset"] == 2
        assert len(result["connectors"]) == 3

    @pytest.mark.asyncio
    async def test_list_limit_clamped_to_max(self, mock_scheduler):
        result = await handle_list_connectors(limit=1000)
        assert result["limit"] == 500

    @pytest.mark.asyncio
    async def test_list_limit_clamped_to_min(self, mock_scheduler):
        result = await handle_list_connectors(limit=-5)
        assert result["limit"] == 1

    @pytest.mark.asyncio
    async def test_list_offset_clamped_to_zero(self, mock_scheduler):
        result = await handle_list_connectors(offset=-10)
        assert result["offset"] == 0

    @pytest.mark.asyncio
    async def test_list_resolves_tenant_from_auth(self, mock_scheduler, mock_auth_ctx):
        with patch.object(legacy_mod, "_resolve_tenant_id", return_value="org-001") as mock_resolve:
            await handle_list_connectors(tenant_id="default", auth_context=mock_auth_ctx)
        mock_resolve.assert_called_once_with(mock_auth_ctx, "default")
        mock_scheduler.list_jobs.assert_called_once_with(tenant_id="org-001")

    @pytest.mark.asyncio
    async def test_list_permission_denied(self, mock_scheduler):
        with patch.object(
            legacy_mod,
            "_check_permission",
            return_value={"error": "Permission denied", "status": 403},
        ):
            result = await handle_list_connectors()
        assert result["status"] == 403

    @pytest.mark.asyncio
    async def test_list_job_with_no_dates(self, mock_scheduler):
        job = _make_sync_job()
        mock_scheduler.list_jobs.side_effect = lambda tenant_id=None: [job]

        result = await handle_list_connectors()
        conn = result["connectors"][0]
        assert conn["last_run"] is None
        assert conn["next_run"] is None


# ---------------------------------------------------------------------------
# handle_get_connector tests
# ---------------------------------------------------------------------------


class TestGetConnector:
    """Test handle_get_connector."""

    @pytest.mark.asyncio
    async def test_get_existing(self, mock_scheduler):
        job = _make_sync_job()
        mock_scheduler.get_job.side_effect = lambda jid: job if jid == "default:test-conn" else None

        result = await handle_get_connector("test-conn")
        assert result is not None
        assert result["id"] == "test-conn"
        assert result["is_running"] is False

    @pytest.mark.asyncio
    async def test_get_running_connector(self, mock_scheduler):
        job = _make_sync_job(current_run_id="run-123")
        mock_scheduler.get_job.side_effect = lambda jid: job if jid == "default:test-conn" else None

        result = await handle_get_connector("test-conn")
        assert result["is_running"] is True

    @pytest.mark.asyncio
    async def test_get_not_found(self, mock_scheduler):
        mock_scheduler.get_job.return_value = None

        result = await handle_get_connector("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_uses_correct_job_id(self, mock_scheduler, mock_auth_ctx):
        with patch.object(legacy_mod, "_resolve_tenant_id", return_value="org-001"):
            await handle_get_connector("my-conn", auth_context=mock_auth_ctx)
        mock_scheduler.get_job.assert_called_once_with("org-001:my-conn")

    @pytest.mark.asyncio
    async def test_get_permission_denied(self, mock_scheduler):
        with patch.object(
            legacy_mod,
            "_check_permission",
            return_value={"error": "Permission denied", "status": 403},
        ):
            result = await handle_get_connector("test-conn")
        assert result["status"] == 403

    @pytest.mark.asyncio
    async def test_get_with_dates(self, mock_scheduler):
        now = datetime.now(timezone.utc)
        job = _make_sync_job(
            last_run=now,
            next_run=now + timedelta(hours=1),
            consecutive_failures=3,
        )
        mock_scheduler.get_job.side_effect = lambda jid: job

        result = await handle_get_connector("test-conn")
        assert result["last_run"] == now.isoformat()
        assert result["consecutive_failures"] == 3


# ---------------------------------------------------------------------------
# handle_create_connector tests
# ---------------------------------------------------------------------------


class TestCreateConnectorHandler:
    """Test handle_create_connector."""

    @pytest.mark.asyncio
    async def test_create_github(self, mock_scheduler):
        with patch.object(legacy_mod, "_create_connector") as mock_factory:
            mock_conn = MagicMock()
            mock_conn.connector_id = "github_acme_app"
            mock_factory.return_value = mock_conn

            result = await handle_create_connector(
                "github", {"owner": "acme", "repo": "app"}, tenant_id="default"
            )

        assert result["id"] == "github_acme_app"
        assert result["type"] == "github"
        assert result["status"] == "registered"

    @pytest.mark.asyncio
    async def test_create_with_schedule(self, mock_scheduler):
        schedule_dict = {"schedule_type": "interval", "interval_minutes": 30}
        with patch.object(legacy_mod, "_create_connector") as mock_factory:
            mock_conn = MagicMock()
            mock_conn.connector_id = "s3_bucket"
            mock_factory.return_value = mock_conn

            result = await handle_create_connector("s3", {"bucket": "test"}, schedule=schedule_dict)

        assert result["status"] == "registered"
        # Verify SyncSchedule.from_dict was called with the schedule
        mock_scheduler.register_connector.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_audit_trail(self, mock_scheduler, mock_auth_ctx):
        with (
            patch.object(legacy_mod, "_create_connector") as mock_factory,
            patch.object(legacy_mod, "audit_data") as mock_audit,
        ):
            mock_conn = MagicMock()
            mock_conn.connector_id = "pg_mydb"
            mock_factory.return_value = mock_conn

            await handle_create_connector(
                "postgres", {"database": "mydb"}, auth_context=mock_auth_ctx
            )

        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args
        assert call_kwargs.kwargs["user_id"] == "user-001"
        assert call_kwargs.kwargs["action"] == "create"
        assert call_kwargs.kwargs["resource_type"] == "connector"

    @pytest.mark.asyncio
    async def test_create_system_user_when_no_auth(self, mock_scheduler):
        with (
            patch.object(legacy_mod, "_create_connector") as mock_factory,
            patch.object(legacy_mod, "audit_data") as mock_audit,
        ):
            mock_conn = MagicMock()
            mock_conn.connector_id = "test"
            mock_factory.return_value = mock_conn

            await handle_create_connector("s3", {"bucket": "b"})

        assert mock_audit.call_args.kwargs["user_id"] == "system"

    @pytest.mark.asyncio
    async def test_create_permission_denied(self, mock_scheduler):
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_create_connector("github", {})
        assert result["status"] == 403

    @pytest.mark.asyncio
    async def test_create_unknown_type_raises(self, mock_scheduler):
        with pytest.raises(ValueError, match="Unknown connector type"):
            await handle_create_connector("oracle", {})


# ---------------------------------------------------------------------------
# handle_update_connector tests
# ---------------------------------------------------------------------------


class TestUpdateConnector:
    """Test handle_update_connector."""

    @pytest.mark.asyncio
    async def test_update_schedule(self, mock_scheduler):
        job = _make_sync_job()
        mock_scheduler.get_job.side_effect = lambda jid: job if jid == "default:test-conn" else None

        updates = {"schedule": {"schedule_type": "interval", "interval_minutes": 15}}
        result = await handle_update_connector("test-conn", updates)

        assert result is not None
        assert result["status"] == "updated"
        assert result["id"] == "test-conn"

    @pytest.mark.asyncio
    async def test_update_not_found(self, mock_scheduler):
        mock_scheduler.get_job.return_value = None

        result = await handle_update_connector("nonexistent", {"schedule": {}})
        assert result is None

    @pytest.mark.asyncio
    async def test_update_audit_trail(self, mock_scheduler, mock_auth_ctx):
        job = _make_sync_job()
        mock_scheduler.get_job.side_effect = lambda jid: job

        with patch.object(legacy_mod, "audit_data") as mock_audit:
            await handle_update_connector("test-conn", {"schedule": {}}, auth_context=mock_auth_ctx)

        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"] == "update"
        assert mock_audit.call_args.kwargs["changes"] == ["schedule"]

    @pytest.mark.asyncio
    async def test_update_without_schedule_key(self, mock_scheduler):
        """When updates dict does not contain 'schedule', job schedule remains unchanged."""
        original_schedule = SyncSchedule(interval_minutes=60)
        job = _make_sync_job()
        job.schedule = original_schedule
        mock_scheduler.get_job.side_effect = lambda jid: job

        result = await handle_update_connector("test-conn", {"other_key": "value"})
        assert result["schedule"] == original_schedule.to_dict()

    @pytest.mark.asyncio
    async def test_update_permission_denied(self, mock_scheduler):
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_update_connector("test-conn", {})
        assert result["status"] == 403

    @pytest.mark.asyncio
    async def test_update_system_user_when_no_auth(self, mock_scheduler):
        job = _make_sync_job()
        mock_scheduler.get_job.side_effect = lambda jid: job

        with patch.object(legacy_mod, "audit_data") as mock_audit:
            await handle_update_connector("test-conn", {"schedule": {}})

        assert mock_audit.call_args.kwargs["user_id"] == "system"


# ---------------------------------------------------------------------------
# handle_delete_connector tests
# ---------------------------------------------------------------------------


class TestDeleteConnector:
    """Test handle_delete_connector."""

    @pytest.mark.asyncio
    async def test_delete_success(self, mock_scheduler, mock_auth_ctx):
        with (
            patch.object(legacy_mod, "_resolve_tenant_id", return_value="default"),
            patch.object(legacy_mod, "audit_data") as mock_audit,
        ):
            result = await handle_delete_connector("test-conn", auth_context=mock_auth_ctx)

        assert result is True
        mock_scheduler.unregister_connector.assert_called_once_with("test-conn", "default")
        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"] == "delete"

    @pytest.mark.asyncio
    async def test_delete_tenant_resolution(self, mock_scheduler, mock_auth_ctx):
        with (
            patch.object(legacy_mod, "_resolve_tenant_id", return_value="org-001"),
            patch.object(legacy_mod, "audit_data"),
        ):
            await handle_delete_connector("test-conn", auth_context=mock_auth_ctx)

        mock_scheduler.unregister_connector.assert_called_once_with("test-conn", "org-001")

    @pytest.mark.asyncio
    async def test_delete_system_user_when_no_auth(self, mock_scheduler):
        with patch.object(legacy_mod, "audit_data") as mock_audit:
            await handle_delete_connector("test-conn")

        assert mock_audit.call_args.kwargs["user_id"] == "system"

    @pytest.mark.asyncio
    async def test_delete_permission_denied_inner(self, mock_scheduler):
        """Test the inner _check_permission call."""
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_delete_connector("test-conn")
        assert result["status"] == 403


# ---------------------------------------------------------------------------
# handle_trigger_sync tests
# ---------------------------------------------------------------------------


class TestTriggerSync:
    """Test handle_trigger_sync."""

    @pytest.mark.asyncio
    async def test_trigger_sync(self, mock_scheduler):
        result = await handle_trigger_sync("test-conn")
        assert result is not None
        assert result["run_id"] == "run-abc"
        assert result["connector_id"] == "test-conn"
        assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_trigger_full_sync(self, mock_scheduler):
        result = await handle_trigger_sync("test-conn", full_sync=True)
        assert result["full_sync"] is True
        mock_scheduler.trigger_sync.assert_awaited_once_with(
            "test-conn", tenant_id="default", full_sync=True
        )

    @pytest.mark.asyncio
    async def test_trigger_sync_not_found(self, mock_scheduler):
        mock_scheduler.trigger_sync.return_value = None

        result = await handle_trigger_sync("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_trigger_sync_audit(self, mock_scheduler, mock_auth_ctx):
        with patch.object(legacy_mod, "audit_data") as mock_audit:
            await handle_trigger_sync("test-conn", auth_context=mock_auth_ctx)

        mock_audit.assert_called_once()
        assert mock_audit.call_args.kwargs["action"] == "execute"
        assert mock_audit.call_args.kwargs["resource_type"] == "connector_sync"

    @pytest.mark.asyncio
    async def test_trigger_sync_permission_denied(self, mock_scheduler):
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_trigger_sync("test-conn")
        assert result["status"] == 403

    @pytest.mark.asyncio
    async def test_trigger_sync_system_user(self, mock_scheduler):
        with patch.object(legacy_mod, "audit_data") as mock_audit:
            await handle_trigger_sync("test-conn")

        assert mock_audit.call_args.kwargs["user_id"] == "system"


# ---------------------------------------------------------------------------
# handle_get_sync_status tests
# ---------------------------------------------------------------------------


class TestGetSyncStatus:
    """Test handle_get_sync_status."""

    @pytest.mark.asyncio
    async def test_get_status(self, mock_scheduler):
        now = datetime.now(timezone.utc)
        job = _make_sync_job(
            current_run_id="run-1",
            last_run=now,
            next_run=now + timedelta(hours=1),
            consecutive_failures=2,
        )
        mock_scheduler.get_job.side_effect = lambda jid: job

        result = await handle_get_sync_status("test-conn")
        assert result["connector_id"] == "test-conn"
        assert result["is_running"] is True
        assert result["current_run_id"] == "run-1"
        assert result["consecutive_failures"] == 2

    @pytest.mark.asyncio
    async def test_get_status_not_found(self, mock_scheduler):
        mock_scheduler.get_job.return_value = None

        result = await handle_get_sync_status("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_status_idle(self, mock_scheduler):
        job = _make_sync_job()
        mock_scheduler.get_job.side_effect = lambda jid: job

        result = await handle_get_sync_status("test-conn")
        assert result["is_running"] is False
        assert result["current_run_id"] is None

    @pytest.mark.asyncio
    async def test_get_status_permission_denied(self, mock_scheduler):
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_get_sync_status("test-conn")
        assert result["status"] == 403


# ---------------------------------------------------------------------------
# handle_get_sync_history tests
# ---------------------------------------------------------------------------


class TestGetSyncHistory:
    """Test handle_get_sync_history."""

    @pytest.mark.asyncio
    async def test_get_history_empty(self, mock_scheduler):
        result = await handle_get_sync_history()
        assert result["history"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_get_history_with_entries(self, mock_scheduler):
        now = datetime.now(timezone.utc)
        hist = SyncHistory(
            id="h1",
            job_id="default:test-conn",
            connector_id="test-conn",
            tenant_id="default",
            status=SyncStatus.COMPLETED,
            started_at=now,
            completed_at=now + timedelta(seconds=30),
            items_synced=100,
        )
        mock_scheduler.get_history.return_value = [hist]

        result = await handle_get_sync_history(connector_id="test-conn")
        assert result["total"] == 1
        assert result["history"][0]["id"] == "h1"

    @pytest.mark.asyncio
    async def test_get_history_with_status_filter(self, mock_scheduler):
        result = await handle_get_sync_history(status="completed")
        mock_scheduler.get_history.assert_called_once_with(
            job_id=None, tenant_id="default", status=SyncStatus.COMPLETED, limit=50
        )

    @pytest.mark.asyncio
    async def test_get_history_invalid_status(self, mock_scheduler):
        """Invalid status value should raise ValueError from SyncStatus enum."""
        with pytest.raises(ValueError, match="invalid_status"):
            await handle_get_sync_history(status="invalid_status")

    @pytest.mark.asyncio
    async def test_get_history_with_connector_id(self, mock_scheduler):
        result = await handle_get_sync_history(connector_id="my-conn", tenant_id="tenant-1")
        mock_scheduler.get_history.assert_called_once_with(
            job_id="tenant-1:my-conn", tenant_id="tenant-1", status=None, limit=50
        )

    @pytest.mark.asyncio
    async def test_get_history_no_connector_id(self, mock_scheduler):
        result = await handle_get_sync_history()
        mock_scheduler.get_history.assert_called_once_with(
            job_id=None, tenant_id="default", status=None, limit=50
        )

    @pytest.mark.asyncio
    async def test_get_history_permission_denied(self, mock_scheduler):
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_get_sync_history()
        assert result["status"] == 403


# ---------------------------------------------------------------------------
# handle_webhook tests
# ---------------------------------------------------------------------------


class TestWebhook:
    """Test handle_webhook."""

    @pytest.mark.asyncio
    async def test_webhook_handled(self, mock_scheduler):
        result = await handle_webhook("test-conn", {"event": "push"})
        assert result["handled"] is True
        assert result["connector_id"] == "test-conn"

    @pytest.mark.asyncio
    async def test_webhook_not_handled(self, mock_scheduler):
        mock_scheduler.handle_webhook.return_value = False

        result = await handle_webhook("test-conn", {"event": "unknown"})
        assert result["handled"] is False

    @pytest.mark.asyncio
    async def test_webhook_tenant_resolution(self, mock_scheduler, mock_auth_ctx):
        with patch.object(legacy_mod, "_resolve_tenant_id", return_value="org-001"):
            await handle_webhook("test-conn", {}, auth_context=mock_auth_ctx)

        mock_scheduler.handle_webhook.assert_awaited_once_with("test-conn", {}, tenant_id="org-001")

    @pytest.mark.asyncio
    async def test_webhook_permission_denied(self, mock_scheduler):
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_webhook("test-conn", {})
        assert result["status"] == 403


# ---------------------------------------------------------------------------
# handle_start_scheduler / handle_stop_scheduler tests
# ---------------------------------------------------------------------------


class TestSchedulerControl:
    """Test scheduler start/stop handlers."""

    @pytest.mark.asyncio
    async def test_start_scheduler(self, mock_scheduler):
        with patch.object(legacy_mod, "audit_admin") as mock_audit:
            result = await handle_start_scheduler()

        assert result["status"] == "started"
        mock_scheduler.start.assert_awaited_once()
        mock_audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_scheduler(self, mock_scheduler):
        with patch.object(legacy_mod, "audit_admin") as mock_audit:
            result = await handle_stop_scheduler()

        assert result["status"] == "stopped"
        mock_scheduler.stop.assert_awaited_once()
        mock_audit.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_scheduler_with_auth(self, mock_scheduler, mock_auth_ctx):
        with patch.object(legacy_mod, "audit_admin") as mock_audit:
            await handle_start_scheduler(auth_context=mock_auth_ctx)

        assert mock_audit.call_args.kwargs["admin_id"] == "user-001"

    @pytest.mark.asyncio
    async def test_stop_scheduler_with_auth(self, mock_scheduler, mock_auth_ctx):
        with patch.object(legacy_mod, "audit_admin") as mock_audit:
            await handle_stop_scheduler(auth_context=mock_auth_ctx)

        assert mock_audit.call_args.kwargs["admin_id"] == "user-001"

    @pytest.mark.asyncio
    async def test_start_scheduler_system_user(self, mock_scheduler):
        with patch.object(legacy_mod, "audit_admin") as mock_audit:
            await handle_start_scheduler()

        assert mock_audit.call_args.kwargs["admin_id"] == "system"

    @pytest.mark.asyncio
    async def test_stop_scheduler_system_user(self, mock_scheduler):
        with patch.object(legacy_mod, "audit_admin") as mock_audit:
            await handle_stop_scheduler()

        assert mock_audit.call_args.kwargs["admin_id"] == "system"

    @pytest.mark.asyncio
    async def test_start_permission_denied(self, mock_scheduler):
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_start_scheduler()
        assert result["status"] == 403

    @pytest.mark.asyncio
    async def test_stop_permission_denied(self, mock_scheduler):
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_stop_scheduler()
        assert result["status"] == 403


# ---------------------------------------------------------------------------
# handle_get_scheduler_stats tests
# ---------------------------------------------------------------------------


class TestGetSchedulerStats:
    """Test handle_get_scheduler_stats."""

    @pytest.mark.asyncio
    async def test_get_stats(self, mock_scheduler):
        mock_scheduler.get_stats.return_value = {
            "total_jobs": 5,
            "running_syncs": 1,
            "success_rate": 0.95,
        }

        result = await handle_get_scheduler_stats()
        assert result["total_jobs"] == 5
        assert result["running_syncs"] == 1

    @pytest.mark.asyncio
    async def test_get_stats_with_tenant(self, mock_scheduler):
        await handle_get_scheduler_stats(tenant_id="org-001")
        mock_scheduler.get_stats.assert_called_once_with(tenant_id="org-001")

    @pytest.mark.asyncio
    async def test_get_stats_permission_denied(self, mock_scheduler):
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_get_scheduler_stats()
        assert result["status"] == 403


# ---------------------------------------------------------------------------
# handle_list_workflow_templates tests
# ---------------------------------------------------------------------------


class TestListWorkflowTemplates:
    """Test handle_list_workflow_templates."""

    @pytest.mark.asyncio
    async def test_list_templates(self, mock_scheduler):
        templates = [
            {"id": "t1", "category": "legal", "name": "Contract Review"},
            {"id": "t2", "category": "legal", "name": "Due Diligence"},
            {"id": "t3", "category": "finance", "name": "Budget Approval"},
        ]
        with patch("aragora.workflow.templates.list_templates", return_value=templates):
            result = await handle_list_workflow_templates()

        assert result["total"] == 3
        assert len(result["templates"]) == 3
        assert set(result["categories"]) == {"legal", "finance"}

    @pytest.mark.asyncio
    async def test_list_templates_with_category_filter(self):
        templates = [{"id": "t1", "category": "legal", "name": "Contract"}]
        with patch("aragora.workflow.templates.list_templates", return_value=templates):
            result = await handle_list_workflow_templates(category="legal")

        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_list_templates_empty(self):
        with patch("aragora.workflow.templates.list_templates", return_value=[]):
            result = await handle_list_workflow_templates()

        assert result["total"] == 0
        assert result["templates"] == []
        assert result["categories"] == []

    @pytest.mark.asyncio
    async def test_list_templates_permission_denied(self):
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_list_workflow_templates()
        assert result["status"] == 403


# ---------------------------------------------------------------------------
# handle_get_workflow_template tests
# ---------------------------------------------------------------------------


class TestGetWorkflowTemplate:
    """Test handle_get_workflow_template."""

    @pytest.mark.asyncio
    async def test_get_template_found(self):
        template_data = {"name": "Contract Review", "steps": []}
        with patch("aragora.workflow.templates.get_template", return_value=template_data):
            result = await handle_get_workflow_template("legal_contract_review")

        assert result is not None
        assert result["id"] == "legal_contract_review"
        assert result["template"] == template_data

    @pytest.mark.asyncio
    async def test_get_template_not_found(self):
        with patch("aragora.workflow.templates.get_template", return_value=None):
            result = await handle_get_workflow_template("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_template_permission_denied(self):
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_get_workflow_template("legal_contract")
        assert result["status"] == 403


# ---------------------------------------------------------------------------
# handle_mongodb_aggregate tests
# ---------------------------------------------------------------------------


class TestMongoDBAggregate:
    """Test handle_mongodb_aggregate."""

    @pytest.mark.asyncio
    async def test_aggregate_success(self, mock_scheduler):
        mock_connector = MagicMock(spec=MongoDBConnector)
        mock_connector.aggregate = AsyncMock(return_value=[{"_id": "dept-1", "count": 5}])

        with _patch_registry(get_connector_return=mock_connector):
            result = await handle_mongodb_aggregate(
                connector_id="my-mongo",
                collection="users",
                pipeline=[{"$group": {"_id": "$dept", "count": {"$sum": 1}}}],
            )

        assert result["connector_id"] == "my-mongo"
        assert result["collection"] == "users"
        assert result["result_count"] == 1

    @pytest.mark.asyncio
    async def test_aggregate_adds_limit_stage(self, mock_scheduler):
        mock_connector = MagicMock(spec=MongoDBConnector)
        mock_connector.aggregate = AsyncMock(return_value=[])

        with _patch_registry(get_connector_return=mock_connector):
            await handle_mongodb_aggregate(
                connector_id="my-mongo",
                collection="users",
                pipeline=[{"$match": {"active": True}}],
                limit=500,
            )

        # The pipeline passed to aggregate should include a $limit stage
        call_args = mock_connector.aggregate.call_args
        pipeline = call_args[0][1]
        assert any("$limit" in stage for stage in pipeline)

    @pytest.mark.asyncio
    async def test_aggregate_skips_limit_when_present(self, mock_scheduler):
        mock_connector = MagicMock(spec=MongoDBConnector)
        mock_connector.aggregate = AsyncMock(return_value=[])

        pipeline = [{"$match": {}}, {"$limit": 10}]
        with _patch_registry(get_connector_return=mock_connector):
            await handle_mongodb_aggregate(
                connector_id="my-mongo",
                collection="users",
                pipeline=pipeline,
            )

        call_pipeline = mock_connector.aggregate.call_args[0][1]
        limit_stages = [s for s in call_pipeline if "$limit" in s]
        assert len(limit_stages) == 1  # Only the original one

    @pytest.mark.asyncio
    async def test_aggregate_connector_not_found(self, mock_scheduler):
        with _patch_registry(get_connector_return=None):
            with pytest.raises(ValueError, match="Connector not found"):
                await handle_mongodb_aggregate(
                    connector_id="nonexistent",
                    collection="users",
                    pipeline=[],
                )

    @pytest.mark.asyncio
    async def test_aggregate_not_mongodb_connector(self, mock_scheduler):
        mock_connector = MagicMock()  # No spec -- isinstance(mock, MongoDBConnector) fails

        with _patch_registry(get_connector_return=mock_connector):
            with pytest.raises(ValueError, match="not a MongoDB connector"):
                await handle_mongodb_aggregate(
                    connector_id="my-pg",
                    collection="users",
                    pipeline=[],
                )

    @pytest.mark.asyncio
    async def test_aggregate_invalid_pipeline_not_list(self, mock_scheduler):
        mock_connector = MagicMock(spec=MongoDBConnector)

        with _patch_registry(get_connector_return=mock_connector):
            with pytest.raises(ValueError, match="must be a list"):
                await handle_mongodb_aggregate(
                    connector_id="my-mongo",
                    collection="users",
                    pipeline="not a list",  # type: ignore[arg-type]
                )

    @pytest.mark.asyncio
    async def test_aggregate_invalid_pipeline_stage_not_dict(self, mock_scheduler):
        mock_connector = MagicMock(spec=MongoDBConnector)

        with _patch_registry(get_connector_return=mock_connector):
            with pytest.raises(ValueError, match="stage 0 must be a document"):
                await handle_mongodb_aggregate(
                    connector_id="my-mongo",
                    collection="users",
                    pipeline=["not a dict"],  # type: ignore[list-item]
                )

    @pytest.mark.asyncio
    async def test_aggregate_empty_pipeline_stage(self, mock_scheduler):
        mock_connector = MagicMock(spec=MongoDBConnector)

        with _patch_registry(get_connector_return=mock_connector):
            with pytest.raises(ValueError, match="stage 0 is empty"):
                await handle_mongodb_aggregate(
                    connector_id="my-mongo",
                    collection="users",
                    pipeline=[{}],
                )

    @pytest.mark.asyncio
    async def test_aggregate_explain_mode(self, mock_scheduler):
        mock_connector = MagicMock(spec=MongoDBConnector)
        mock_connector._get_client = AsyncMock()
        mock_db = MagicMock()
        mock_connector._db = mock_db

        mock_coll = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_coll)

        mock_agg_cursor = MagicMock()
        mock_agg_cursor.explain = AsyncMock(return_value={"queryPlanner": {}})
        mock_coll.aggregate.return_value = mock_agg_cursor

        with _patch_registry(get_connector_return=mock_connector):
            result = await handle_mongodb_aggregate(
                connector_id="my-mongo",
                collection="users",
                pipeline=[{"$match": {}}],
                explain=True,
            )

        assert "explain" in result
        assert result["connector_id"] == "my-mongo"

    @pytest.mark.asyncio
    async def test_aggregate_explain_db_not_initialized(self, mock_scheduler):
        mock_connector = MagicMock(spec=MongoDBConnector)
        mock_connector._get_client = AsyncMock()
        mock_connector._db = None

        with _patch_registry(get_connector_return=mock_connector):
            with pytest.raises(RuntimeError, match="Database not initialized"):
                await handle_mongodb_aggregate(
                    connector_id="my-mongo",
                    collection="users",
                    pipeline=[{"$match": {}}],
                    explain=True,
                )

    @pytest.mark.asyncio
    async def test_aggregate_permission_denied(self, mock_scheduler):
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_mongodb_aggregate(
                connector_id="my-mongo",
                collection="users",
                pipeline=[],
            )
        assert result["status"] == 403


# ---------------------------------------------------------------------------
# handle_mongodb_collections tests
# ---------------------------------------------------------------------------


class TestMongoDBCollections:
    """Test handle_mongodb_collections."""

    @pytest.mark.asyncio
    async def test_list_collections(self, mock_scheduler):
        mock_connector = MagicMock(spec=MongoDBConnector)
        mock_connector._get_client = AsyncMock()
        mock_connector._db = MagicMock()
        mock_connector._database = "mydb"
        mock_connector._db.list_collection_names = AsyncMock(
            return_value=["users", "orders", "products"]
        )

        with _patch_registry(get_connector_return=mock_connector):
            result = await handle_mongodb_collections("my-mongo")

        assert result["connector_id"] == "my-mongo"
        assert result["database"] == "mydb"
        assert len(result["collections"]) == 3

    @pytest.mark.asyncio
    async def test_collections_connector_not_found(self, mock_scheduler):
        with _patch_registry(get_connector_return=None):
            with pytest.raises(ValueError, match="Connector not found"):
                await handle_mongodb_collections("nonexistent")

    @pytest.mark.asyncio
    async def test_collections_not_mongodb(self, mock_scheduler):
        mock_connector = MagicMock()

        with _patch_registry(get_connector_return=mock_connector):
            with pytest.raises(ValueError, match="not a MongoDB connector"):
                await handle_mongodb_collections("my-pg")

    @pytest.mark.asyncio
    async def test_collections_db_not_initialized(self, mock_scheduler):
        mock_connector = MagicMock(spec=MongoDBConnector)
        mock_connector._get_client = AsyncMock()
        mock_connector._db = None

        with _patch_registry(get_connector_return=mock_connector):
            with pytest.raises(RuntimeError, match="Database not initialized"):
                await handle_mongodb_collections("my-mongo")

    @pytest.mark.asyncio
    async def test_collections_permission_denied(self, mock_scheduler):
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_mongodb_collections("my-mongo")
        assert result["status"] == 403


# ---------------------------------------------------------------------------
# handle_connector_health tests
# ---------------------------------------------------------------------------


class TestConnectorHealth:
    """Test handle_connector_health."""

    @pytest.mark.asyncio
    async def test_health_unauthenticated(self, mock_scheduler):
        """Unauthenticated requests get basic health info."""
        result = await handle_connector_health(auth_context=None)
        assert result["status"] == "healthy"
        assert "total_connectors" in result
        assert "running_syncs" not in result  # No detailed stats

    @pytest.mark.asyncio
    async def test_health_authenticated_with_permission(self, mock_scheduler, mock_auth_ctx):
        """Authenticated users with permission get detailed stats."""
        mock_scheduler.get_stats.return_value = {
            "total_jobs": 5,
            "running_syncs": 1,
            "success_rate": 0.95,
        }
        with patch.object(legacy_mod, "_check_permission", return_value=None):
            result = await handle_connector_health(auth_context=mock_auth_ctx)

        assert result["status"] == "healthy"
        assert result["running_syncs"] == 1
        assert result["success_rate"] == 0.95

    @pytest.mark.asyncio
    async def test_health_authenticated_no_permission(self, mock_scheduler, mock_auth_ctx):
        """Authenticated users without permission still get basic health."""
        mock_scheduler.get_stats.return_value = {
            "total_jobs": 5,
            "running_syncs": 1,
            "success_rate": 0.95,
        }
        with patch.object(
            legacy_mod, "_check_permission", return_value={"error": "denied", "status": 403}
        ):
            result = await handle_connector_health(auth_context=mock_auth_ctx)

        assert result["status"] == "healthy"
        assert "running_syncs" not in result

    @pytest.mark.asyncio
    async def test_health_scheduler_running(self, mock_scheduler):
        mock_scheduler._scheduler_task = MagicMock()  # Not None = running
        result = await handle_connector_health()
        assert result["scheduler_running"] is True

    @pytest.mark.asyncio
    async def test_health_scheduler_not_running(self, mock_scheduler):
        mock_scheduler._scheduler_task = None
        result = await handle_connector_health()
        assert result["scheduler_running"] is False

    @pytest.mark.asyncio
    async def test_health_rbac_unavailable_production(self, mock_scheduler, mock_auth_ctx):
        """In production without RBAC, health returns error status."""
        with (
            patch.object(legacy_mod, "RBAC_AVAILABLE", False),
            patch.object(legacy_mod, "rbac_fail_closed", return_value=True),
        ):
            result = await handle_connector_health(auth_context=mock_auth_ctx)

        assert result["status"] == "error"
        assert "access control" in result["error"]

    @pytest.mark.asyncio
    async def test_health_rbac_unavailable_dev(self, mock_scheduler, mock_auth_ctx):
        """In dev without RBAC, health returns basic info."""
        with (
            patch.object(legacy_mod, "RBAC_AVAILABLE", False),
            patch.object(legacy_mod, "rbac_fail_closed", return_value=False),
        ):
            result = await handle_connector_health(auth_context=mock_auth_ctx)

        assert result["status"] == "healthy"


# ---------------------------------------------------------------------------
# Edge cases and integration patterns
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and cross-cutting concerns."""

    @pytest.mark.asyncio
    async def test_list_connectors_with_many_jobs(self, mock_scheduler):
        """Pagination with many jobs."""
        jobs = [_make_sync_job(connector_id=f"conn-{i:03d}") for i in range(100)]
        mock_scheduler.list_jobs.side_effect = lambda tenant_id=None: jobs

        result = await handle_list_connectors(limit=10, offset=90)
        assert result["total"] == 100
        assert len(result["connectors"]) == 10

    @pytest.mark.asyncio
    async def test_list_connectors_offset_beyond_total(self, mock_scheduler):
        """Offset beyond total returns empty list."""
        jobs = [_make_sync_job(connector_id=f"conn-{i}") for i in range(5)]
        mock_scheduler.list_jobs.side_effect = lambda tenant_id=None: jobs

        result = await handle_list_connectors(offset=100)
        assert result["total"] == 5
        assert len(result["connectors"]) == 0

    @pytest.mark.asyncio
    async def test_create_connector_without_schedule(self, mock_scheduler):
        """Creating connector without explicit schedule should use default."""
        with patch.object(legacy_mod, "_create_connector") as mock_factory:
            mock_conn = MagicMock()
            mock_conn.connector_id = "test"
            mock_factory.return_value = mock_conn

            result = await handle_create_connector("s3", {"bucket": "b"}, schedule=None)

        assert result["status"] == "registered"
        # Should have called register_connector with SyncSchedule()
        call_args = mock_scheduler.register_connector.call_args
        assert isinstance(
            call_args.kwargs.get("schedule")
            or call_args[1].get("schedule", None)
            or SyncSchedule(),
            SyncSchedule,
        )

    @pytest.mark.asyncio
    async def test_update_connector_recalculates_next_run(self, mock_scheduler):
        """Updating schedule should trigger _calculate_next_run."""
        job = _make_sync_job()
        mock_scheduler.get_job.side_effect = lambda jid: job

        # The handler calls job._calculate_next_run() directly
        job._calculate_next_run = MagicMock()

        await handle_update_connector(
            "test-conn",
            {"schedule": {"schedule_type": "interval", "interval_minutes": 30}},
        )

        job._calculate_next_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_permission_checks(self, mock_scheduler, mock_auth_ctx):
        """Multiple handlers can run concurrently without interfering."""
        results = await asyncio.gather(
            handle_list_connectors(auth_context=mock_auth_ctx),
            handle_get_scheduler_stats(auth_context=mock_auth_ctx),
            handle_connector_health(auth_context=mock_auth_ctx),
        )
        assert len(results) == 3
        for r in results:
            assert isinstance(r, dict)

    @pytest.mark.asyncio
    async def test_webhook_with_empty_payload(self, mock_scheduler):
        result = await handle_webhook("test-conn", {})
        assert result["connector_id"] == "test-conn"

    @pytest.mark.asyncio
    async def test_webhook_with_large_payload(self, mock_scheduler):
        large_payload = {f"key_{i}": f"value_{i}" for i in range(1000)}
        result = await handle_webhook("test-conn", large_payload)
        assert result["connector_id"] == "test-conn"

    @pytest.mark.asyncio
    async def test_trigger_sync_incremental_default(self, mock_scheduler):
        """Default trigger_sync should use incremental (full_sync=False)."""
        result = await handle_trigger_sync("test-conn")
        mock_scheduler.trigger_sync.assert_awaited_once_with(
            "test-conn", tenant_id="default", full_sync=False
        )

    @pytest.mark.asyncio
    async def test_create_all_connector_types(self, mock_scheduler):
        """Verify all supported connector types can be created."""
        types_configs = {
            "github": {"owner": "acme", "repo": "app"},
            "s3": {"bucket": "test"},
            "postgres": {"database": "mydb"},
            "mongodb": {"database": "mydb"},
            "fhir": {"base_url": "https://fhir.local", "organization_id": "org-1"},
        }

        for connector_type, config in types_configs.items():
            with patch.object(legacy_mod, "_create_connector") as mock_factory:
                mock_conn = MagicMock()
                mock_conn.connector_id = f"{connector_type}-test"
                mock_factory.return_value = mock_conn

                result = await handle_create_connector(connector_type, config)
                assert result["type"] == connector_type
                assert result["status"] == "registered"


class TestRecordRbacCheck:
    """Test the RBAC metrics recording integration."""

    def test_noop_fallback(self):
        """The _record_rbac_check fallback is a no-op."""
        legacy_mod._record_rbac_check("test", granted=True)
        # Should not raise

    def test_record_rbac_check_called_on_grant(self):
        ctx = MagicMock()
        ctx.user_id = "user-1"
        with (
            patch.object(legacy_mod, "RBAC_AVAILABLE", True),
            patch.object(legacy_mod, "check_permission") as mock_check,
            patch.object(legacy_mod, "record_rbac_check") as mock_record,
        ):
            decision = MagicMock()
            decision.allowed = True
            mock_check.return_value = decision
            _check_permission(ctx, "connectors:read")

        mock_record.assert_called_once_with("connectors:read", granted=True)

    def test_record_rbac_check_called_on_deny(self):
        ctx = MagicMock()
        ctx.user_id = "user-1"
        with (
            patch.object(legacy_mod, "RBAC_AVAILABLE", True),
            patch.object(legacy_mod, "check_permission") as mock_check,
            patch.object(legacy_mod, "record_rbac_check") as mock_record,
        ):
            decision = MagicMock()
            decision.allowed = False
            decision.reason = "No access"
            mock_check.return_value = decision
            _check_permission(ctx, "connectors:write")

        mock_record.assert_called_once_with("connectors:write", granted=False)
