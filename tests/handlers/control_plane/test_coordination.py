"""Tests for coordination handler endpoints."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.coordination.cross_workspace import (
    CrossWorkspaceCoordinator,
    CrossWorkspaceRequest,
    CrossWorkspaceResult,
    DataSharingConsent,
    FederatedWorkspace,
    FederationMode,
    FederationPolicy,
    OperationType,
    SharingScope,
)
from aragora.server.handlers.control_plane import ControlPlaneHandler
from aragora.worktree.integration_worker import FleetIntegrationOutcome


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def coordinator() -> CrossWorkspaceCoordinator:
    """Create a fresh coordinator for tests."""
    return CrossWorkspaceCoordinator()


@pytest.fixture
def handler(coordinator: CrossWorkspaceCoordinator) -> ControlPlaneHandler:
    """Create a handler with a coordination coordinator."""
    ctx: dict[str, Any] = {
        "coordination_coordinator": coordinator,
        "control_plane_coordinator": MagicMock(),
    }
    h = ControlPlaneHandler(ctx)
    return h


@pytest.fixture
def mock_http_handler() -> MagicMock:
    """Create a mock HTTP handler for POST requests."""
    m = MagicMock()
    m.path = "/api/v1/coordination/workspaces"
    return m


def _set_body(mock_handler: MagicMock, body: dict[str, Any]) -> None:
    """Set up mock handler to return JSON body."""
    raw = json.dumps(body).encode()
    mock_handler.rfile.read.return_value = raw
    mock_handler.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}


# ============================================================================
# Workspace Endpoints
# ============================================================================


class TestRegisterWorkspace:
    def test_register_workspace_success(
        self, handler: ControlPlaneHandler, mock_http_handler: MagicMock
    ):
        _set_body(
            mock_http_handler,
            {
                "id": "ws-1",
                "name": "Primary",
                "org_id": "org-1",
                "federation_mode": "readonly",
            },
        )
        result = handler._handle_register_workspace(
            {
                "id": "ws-1",
                "name": "Primary",
                "org_id": "org-1",
                "federation_mode": "readonly",
            }
        )
        assert result.status_code == 201
        data = json.loads(result.body)
        assert data["id"] == "ws-1"
        assert data["name"] == "Primary"
        assert data["federation_mode"] == "readonly"

    def test_register_workspace_missing_id(self, handler: ControlPlaneHandler):
        result = handler._handle_register_workspace({"name": "No ID"})
        assert result.status_code == 400
        assert "id" in json.loads(result.body).get("error", "").lower()

    def test_register_workspace_invalid_mode(self, handler: ControlPlaneHandler):
        result = handler._handle_register_workspace(
            {
                "id": "ws-bad",
                "federation_mode": "invalid_mode",
            }
        )
        assert result.status_code == 400


class TestListWorkspaces:
    def test_list_empty(self, handler: ControlPlaneHandler):
        result = handler._handle_list_workspaces({})
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["total"] == 0
        assert data["workspaces"] == []

    def test_list_after_register(
        self, handler: ControlPlaneHandler, coordinator: CrossWorkspaceCoordinator
    ):
        ws = FederatedWorkspace(id="ws-1", name="Test", org_id="org-1")
        coordinator.register_workspace(ws)
        result = handler._handle_list_workspaces({})
        data = json.loads(result.body)
        assert data["total"] == 1
        assert data["workspaces"][0]["id"] == "ws-1"


class TestUnregisterWorkspace:
    def test_unregister_success(
        self, handler: ControlPlaneHandler, coordinator: CrossWorkspaceCoordinator
    ):
        ws = FederatedWorkspace(id="ws-1", name="Test", org_id="org-1")
        coordinator.register_workspace(ws)
        result = handler._handle_unregister_workspace("ws-1")
        assert result.status_code == 200
        assert json.loads(result.body)["unregistered"] is True
        # Verify removed
        assert len(coordinator.list_workspaces()) == 0


# ============================================================================
# Federation Policy Endpoints
# ============================================================================


class TestCreateFederationPolicy:
    def test_create_policy_success(self, handler: ControlPlaneHandler):
        result = handler._handle_create_federation_policy(
            {
                "name": "test-policy",
                "description": "A test policy",
                "mode": "bidirectional",
                "sharing_scope": "metadata",
                "allowed_operations": ["read_knowledge", "query_mound"],
            }
        )
        assert result.status_code == 201
        data = json.loads(result.body)
        assert data["name"] == "test-policy"
        assert data["mode"] == "bidirectional"

    def test_create_policy_missing_name(self, handler: ControlPlaneHandler):
        result = handler._handle_create_federation_policy({"mode": "readonly"})
        assert result.status_code == 400

    def test_create_policy_invalid_mode(self, handler: ControlPlaneHandler):
        result = handler._handle_create_federation_policy(
            {
                "name": "bad-policy",
                "mode": "nonexistent",
            }
        )
        assert result.status_code == 400


class TestListFederationPolicies:
    def test_list_default_policy(self, handler: ControlPlaneHandler):
        result = handler._handle_list_federation_policies({})
        assert result.status_code == 200
        data = json.loads(result.body)
        # Should include at least the default policy
        assert data["total"] >= 1

    def test_list_after_create(
        self, handler: ControlPlaneHandler, coordinator: CrossWorkspaceCoordinator
    ):
        policy = FederationPolicy(name="custom", mode=FederationMode.BIDIRECTIONAL)
        coordinator.set_policy(policy, workspace_id="ws-1")
        result = handler._handle_list_federation_policies({})
        data = json.loads(result.body)
        # default + workspace-specific
        assert data["total"] >= 2


# ============================================================================
# Execution Endpoints
# ============================================================================


class TestExecute:
    def test_execute_missing_fields(self, handler: ControlPlaneHandler):
        result = handler._handle_execute({"operation": "read_knowledge"})
        assert result.status_code == 400


class TestSwarmRun:
    @patch("aragora.swarm.SwarmSupervisor")
    @patch("aragora.server.handlers.control_plane.coordination.resolve_repo_root")
    def test_swarm_run_from_goal(
        self,
        mock_resolve,
        mock_supervisor_cls,
        handler: ControlPlaneHandler,
    ):
        mock_resolve.return_value = Path("/tmp/repo")
        fake_run = MagicMock()
        fake_run.to_dict.return_value = {"run_id": "run-123", "status": "active"}
        mock_supervisor = mock_supervisor_cls.return_value
        mock_supervisor.start_run.return_value = fake_run
        mock_supervisor.dispatch_workers = AsyncMock(return_value=[])
        mock_supervisor.store.get_supervisor_run.return_value = None

        result = handler._handle_swarm_run(
            {
                "goal": "Ship the supervisor lane",
                "target_branch": "main",
                "concurrency_cap": 4,
            }
        )

        assert result.status_code == 201
        data = json.loads(result.body)
        assert data["run_id"] == "run-123"

    @patch("aragora.swarm.SwarmReconciler")
    @patch("aragora.server.handlers.control_plane.coordination.resolve_repo_root")
    def test_swarm_reconcile_run(
        self,
        mock_resolve,
        mock_reconciler_cls,
        handler: ControlPlaneHandler,
    ):
        mock_resolve.return_value = Path("/tmp/repo")
        fake_run = MagicMock()
        fake_run.to_dict.return_value = {"run_id": "run-123", "status": "active"}
        mock_reconciler_cls.return_value.tick_run = AsyncMock(return_value=fake_run)

        result = handler._handle_swarm_reconcile({"run_id": "run-123"})

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["run_id"] == "run-123"

    def test_execute_workspace_not_found(self, handler: ControlPlaneHandler):
        result = handler._handle_execute(
            {
                "operation": "read_knowledge",
                "source_workspace_id": "ws-missing",
                "target_workspace_id": "ws-also-missing",
            }
        )
        # Should return 422 because the coordinator returns failure
        data = json.loads(result.body)
        assert data["success"] is False

    def test_execute_invalid_operation(self, handler: ControlPlaneHandler):
        result = handler._handle_execute(
            {
                "operation": "not_real_op",
                "source_workspace_id": "ws-1",
                "target_workspace_id": "ws-2",
            }
        )
        assert result.status_code == 400


class TestListExecutions:
    def test_list_empty(self, handler: ControlPlaneHandler):
        result = handler._handle_list_executions({})
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["total"] == 0

    def test_list_with_filter(self, handler: ControlPlaneHandler):
        result = handler._handle_list_executions({"workspace_id": "ws-1"})
        assert result.status_code == 200


# ============================================================================
# Consent Endpoints
# ============================================================================


class TestGrantConsent:
    def test_grant_consent_success(self, handler: ControlPlaneHandler):
        result = handler._handle_grant_consent(
            {
                "source_workspace_id": "ws-1",
                "target_workspace_id": "ws-2",
                "scope": "metadata",
                "data_types": ["debates"],
                "operations": ["read_knowledge"],
                "granted_by": "admin",
            }
        )
        assert result.status_code == 201
        data = json.loads(result.body)
        assert data["source_workspace_id"] == "ws-1"
        assert data["is_valid"] is True

    def test_grant_consent_missing_workspaces(self, handler: ControlPlaneHandler):
        result = handler._handle_grant_consent({"scope": "full"})
        assert result.status_code == 400


class TestRevokeConsent:
    def test_revoke_consent_not_found(self, handler: ControlPlaneHandler):
        result = handler._handle_revoke_consent("nonexistent-id", {})
        assert result.status_code == 404

    def test_revoke_consent_success(
        self, handler: ControlPlaneHandler, coordinator: CrossWorkspaceCoordinator
    ):
        consent = coordinator.grant_consent(
            source_workspace_id="ws-1",
            target_workspace_id="ws-2",
            scope=SharingScope.METADATA,
            data_types={"debates"},
            operations={OperationType.READ_KNOWLEDGE},
            granted_by="admin",
        )
        result = handler._handle_revoke_consent(consent.id, {})
        assert result.status_code == 200
        assert json.loads(result.body)["revoked"] is True


class TestListConsents:
    def test_list_empty(self, handler: ControlPlaneHandler):
        result = handler._handle_list_consents({})
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["total"] == 0

    def test_list_with_workspace_filter(
        self, handler: ControlPlaneHandler, coordinator: CrossWorkspaceCoordinator
    ):
        coordinator.grant_consent(
            source_workspace_id="ws-1",
            target_workspace_id="ws-2",
            scope=SharingScope.METADATA,
            data_types={"debates"},
            operations={OperationType.READ_KNOWLEDGE},
            granted_by="admin",
        )
        result = handler._handle_list_consents({"workspace_id": "ws-1"})
        data = json.loads(result.body)
        assert data["total"] == 1


# ============================================================================
# Approval Endpoints
# ============================================================================


class TestApproveRequest:
    def test_approve_not_found(self, handler: ControlPlaneHandler):
        result = handler._handle_approve_request("nonexistent", {})
        assert result.status_code == 404

    def test_approve_success(
        self, handler: ControlPlaneHandler, coordinator: CrossWorkspaceCoordinator
    ):
        # Manually add a pending request
        req = CrossWorkspaceRequest(
            operation=OperationType.READ_KNOWLEDGE,
            source_workspace_id="ws-1",
            target_workspace_id="ws-2",
        )
        coordinator._pending_requests[req.id] = req
        result = handler._handle_approve_request(req.id, {"approved_by": "admin"})
        assert result.status_code == 200
        assert json.loads(result.body)["approved"] is True


# ============================================================================
# Stats and Health Endpoints
# ============================================================================


class TestCoordinationStats:
    def test_get_stats(self, handler: ControlPlaneHandler):
        result = handler._handle_coordination_stats({})
        assert result.status_code == 200
        data = json.loads(result.body)
        assert "total_workspaces" in data
        assert "total_consents" in data

    def test_get_stats_no_coordinator(self):
        h = ControlPlaneHandler({"control_plane_coordinator": MagicMock()})
        result = h._handle_coordination_stats({})
        assert result.status_code == 503


class TestCoordinationHealth:
    def test_health_available(self, handler: ControlPlaneHandler):
        result = handler._handle_coordination_health({})
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["status"] == "healthy"

    def test_health_unavailable(self):
        h = ControlPlaneHandler({"control_plane_coordinator": MagicMock()})
        result = h._handle_coordination_health({})
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["status"] == "unavailable"


class TestFleetStatus:
    @patch("aragora.server.handlers.control_plane.coordination.FleetCoordinationStore")
    @patch("aragora.server.handlers.control_plane.coordination.build_fleet_rows")
    @patch("aragora.server.handlers.control_plane.coordination.resolve_repo_root")
    def test_fleet_status_success(
        self, mock_resolve, mock_build, mock_store_cls, handler: ControlPlaneHandler
    ):
        mock_resolve.return_value = Path("/tmp/repo")
        mock_build.return_value = [
            {
                "session_id": "session-a",
                "path": "/tmp/repo/.worktrees/codex/session-a",
                "branch": "codex/session-a",
                "log_tail": ["line-1", "line-2"],
            }
        ]
        store = MagicMock()
        store.list_claims.return_value = [{"session_id": "session-a", "path": "aragora/x.py"}]
        store.list_merge_queue.return_value = [
            {"session_id": "session-a", "branch": "codex/session-a"}
        ]
        mock_store_cls.return_value = store

        result = handler._handle_fleet_status({"tail": "200"})
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["repo_root"] == "/tmp/repo"
        assert data["tail"] == 200
        assert data["total"] == 1
        assert data["worktrees"][0]["session_id"] == "session-a"
        assert data["worktrees"][0]["claimed_paths"] == ["aragora/x.py"]

    @patch(
        "aragora.nomic.dev_coordination.DevCoordinationStore.status_summary",
        side_effect=sqlite3.OperationalError("database is locked"),
    )
    @patch("aragora.server.handlers.control_plane.coordination.FleetCoordinationStore")
    @patch("aragora.server.handlers.control_plane.coordination.build_fleet_rows")
    @patch("aragora.server.handlers.control_plane.coordination.resolve_repo_root")
    def test_fleet_status_handles_sqlite_coordination_error(
        self,
        mock_resolve,
        mock_build,
        mock_store_cls,
        _mock_status_summary,
        handler: ControlPlaneHandler,
    ):
        mock_resolve.return_value = Path(__file__).resolve().parents[3]
        mock_build.return_value = []
        store = MagicMock()
        store.list_claims.return_value = []
        store.list_merge_queue.return_value = []
        mock_store_cls.return_value = store

        result = handler._handle_fleet_status({})

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["coordination"]["counts"] == {}
        assert "database is locked" in data["coordination"]["error"]

    @patch("aragora.server.handlers.control_plane.coordination.build_fleet_rows")
    @patch("aragora.server.handlers.control_plane.coordination.resolve_repo_root")
    def test_fleet_logs_success(self, mock_resolve, mock_build, handler: ControlPlaneHandler):
        mock_resolve.return_value = Path("/tmp/repo")
        mock_build.return_value = [
            {
                "session_id": "session-a",
                "path": "/tmp/repo/.worktrees/codex/session-a",
                "branch": "codex/session-a",
                "log_tail": ["line-1", "line-2"],
            }
        ]

        result = handler._handle_fleet_logs({"session_id": "session-a", "tail": "2"})
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["session_id"] == "session-a"
        assert data["worktree"]["log_tail"] == ["line-1", "line-2"]

    def test_fleet_logs_requires_session_id(self, handler: ControlPlaneHandler):
        result = handler._handle_fleet_logs({})
        assert result.status_code == 400
        assert "session_id" in json.loads(result.body).get("error", "").lower()

    @patch("aragora.server.handlers.control_plane.coordination.build_fleet_rows")
    @patch("aragora.server.handlers.control_plane.coordination.resolve_repo_root")
    def test_fleet_logs_not_found(self, mock_resolve, mock_build, handler: ControlPlaneHandler):
        mock_resolve.return_value = Path("/tmp/repo")
        mock_build.return_value = []
        result = handler._handle_fleet_logs({"session_id": "missing"})
        assert result.status_code == 404

    @patch("aragora.server.handlers.control_plane.coordination.FleetCoordinationStore")
    @patch("aragora.server.handlers.control_plane.coordination.resolve_repo_root")
    def test_fleet_claim_endpoints(
        self, mock_resolve, mock_store_cls, handler: ControlPlaneHandler
    ):
        mock_resolve.return_value = Path("/tmp/repo")
        store = MagicMock()
        store.claim_paths.return_value = {
            "session_id": "session-a",
            "claimed": ["aragora/a.py"],
            "conflicts": [],
        }
        store.release_paths.return_value = {"session_id": "session-a", "released": 1}
        store.list_claims.return_value = [{"session_id": "session-a", "path": "aragora/a.py"}]
        mock_store_cls.return_value = store

        claim_result = handler._handle_fleet_claim(
            {
                "session_id": "session-a",
                "paths": ["aragora/a.py"],
            }
        )
        assert claim_result.status_code == 200
        claim_body = json.loads(claim_result.body)
        assert claim_body["claimed"] == ["aragora/a.py"]

        list_result = handler._handle_fleet_claims({})
        assert list_result.status_code == 200
        list_body = json.loads(list_result.body)
        assert list_body["total"] == 1

        release_result = handler._handle_fleet_release({"session_id": "session-a"})
        assert release_result.status_code == 200
        release_body = json.loads(release_result.body)
        assert release_body["released"] == 1

    @patch("aragora.server.handlers.control_plane.coordination.FleetCoordinationStore")
    @patch("aragora.server.handlers.control_plane.coordination.resolve_repo_root")
    def test_fleet_merge_queue_endpoints(
        self, mock_resolve, mock_store_cls, handler: ControlPlaneHandler
    ):
        mock_resolve.return_value = Path("/tmp/repo")
        store = MagicMock()
        store.enqueue_merge.return_value = {
            "queued": True,
            "duplicate": False,
            "item": {"id": "mq-1", "branch": "codex/x"},
        }
        store.list_merge_queue.return_value = [{"id": "mq-1", "branch": "codex/x"}]
        mock_store_cls.return_value = store

        enqueue = handler._handle_fleet_merge_enqueue(
            {"session_id": "session-a", "branch": "codex/x", "priority": 60}
        )
        assert enqueue.status_code == 201
        enqueue_data = json.loads(enqueue.body)
        assert enqueue_data["item"]["id"] == "mq-1"

        listing = handler._handle_fleet_merge_queue({})
        assert listing.status_code == 200
        listing_data = json.loads(listing.body)
        assert listing_data["total"] == 1

    @patch("aragora.server.handlers.control_plane.coordination.resolve_repo_root")
    @patch("aragora.server.handlers.control_plane.coordination.FleetIntegrationWorker")
    def test_fleet_merge_process_next(
        self, mock_worker_cls, mock_resolve, handler: ControlPlaneHandler
    ):
        mock_resolve.return_value = Path("/tmp/repo")
        worker = MagicMock()
        worker.process_next = AsyncMock(
            return_value=FleetIntegrationOutcome(
                queue_item_id="mq-1",
                branch="codex/x",
                queue_status="needs_human",
                action="validated",
                dry_run_success=True,
            )
        )
        mock_worker_cls.return_value = worker

        result = handler._handle_fleet_merge_process_next(
            {
                "worker_session_id": "integrator-1",
                "target_branch": "main",
                "execute": False,
                "test_gate": False,
            }
        )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["queue_item_id"] == "mq-1"
        assert data["action"] == "validated"

    def test_fleet_merge_process_next_requires_worker_session_id(
        self, handler: ControlPlaneHandler
    ):
        result = handler._handle_fleet_merge_process_next({})
        assert result.status_code == 400


# ============================================================================
# Route Dispatch
# ============================================================================


class TestRouteDispatch:
    def test_can_handle_coordination_path(self, handler: ControlPlaneHandler):
        assert handler.can_handle("/api/v1/coordination/workspaces")
        assert handler.can_handle("/api/v1/coordination/health")

    def test_get_coordination_workspaces(
        self, handler: ControlPlaneHandler, mock_http_handler: MagicMock
    ):
        mock_http_handler.path = "/api/v1/coordination/workspaces"
        result = handler.handle("/api/v1/coordination/workspaces", {}, mock_http_handler)
        assert result is not None
        assert result.status_code == 200

    def test_get_coordination_stats(
        self, handler: ControlPlaneHandler, mock_http_handler: MagicMock
    ):
        mock_http_handler.path = "/api/v1/coordination/stats"
        result = handler.handle("/api/v1/coordination/stats", {}, mock_http_handler)
        assert result is not None
        assert result.status_code == 200

    def test_get_coordination_health(
        self, handler: ControlPlaneHandler, mock_http_handler: MagicMock
    ):
        mock_http_handler.path = "/api/v1/coordination/health"
        result = handler.handle("/api/v1/coordination/health", {}, mock_http_handler)
        assert result is not None
        assert result.status_code == 200

    @patch("aragora.server.handlers.control_plane.coordination.FleetCoordinationStore")
    @patch("aragora.server.handlers.control_plane.coordination.build_fleet_rows", return_value=[])
    @patch("aragora.server.handlers.control_plane.coordination.resolve_repo_root")
    def test_get_coordination_fleet_status(
        self,
        mock_resolve,
        mock_build_rows,
        mock_store_cls,
        handler: ControlPlaneHandler,
        mock_http_handler: MagicMock,
    ):
        mock_resolve.return_value = Path("/tmp/repo")
        store = MagicMock()
        store.list_claims.return_value = []
        store.list_merge_queue.return_value = []
        mock_store_cls.return_value = store
        mock_http_handler.path = "/api/v1/coordination/fleet/status"
        result = handler.handle("/api/v1/coordination/fleet/status", {}, mock_http_handler)
        assert result is not None
        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["integrator_view"]["summary"]["total_lanes"] == 0

    @patch("aragora.server.handlers.control_plane.coordination.FleetCoordinationStore")
    @patch("aragora.server.handlers.control_plane.coordination.build_fleet_rows")
    @patch("aragora.swarm.SwarmSupervisor")
    @patch("aragora.server.handlers.control_plane.coordination.resolve_repo_root")
    def test_get_coordination_swarm_status(
        self,
        mock_resolve,
        mock_supervisor_cls,
        mock_build_rows,
        mock_store_cls,
        handler: ControlPlaneHandler,
    ):
        mock_resolve.return_value = Path("/tmp/repo")
        mock_build_rows.return_value = [
            {
                "session_id": "sess-a",
                "path": "/tmp/repo/.worktrees/docs",
                "branch": "codex/docs-lane",
                "has_lock": True,
                "pid_alive": False,
                "agent": "codex",
                "last_activity": "2026-03-06T00:00:00+00:00",
            }
        ]
        store = MagicMock()
        store.list_claims.return_value = [
            {"session_id": "sess-a", "path": "aragora/swarm/reporter.py"},
            {"session_id": "sess-b", "path": "aragora/swarm/reporter.py"},
        ]
        store.list_merge_queue.return_value = [
            {
                "id": "mq-1",
                "branch": "codex/docs-lane",
                "session_id": "sess-a",
                "status": "needs_human",
                "metadata": {},
            }
        ]
        mock_store_cls.return_value = store
        mock_supervisor_cls.return_value.status_summary.return_value = {
            "runs": [
                {
                    "run_id": "run-1",
                    "status": "active",
                    "goal": "dogfood",
                    "work_orders": [
                        {
                            "work_order_id": "docs-lane",
                            "title": "Write operator guide",
                            "status": "needs_human",
                            "branch": "codex/docs-lane",
                            "worktree_path": "/tmp/repo/.worktrees/docs",
                            "target_agent": "codex",
                            "last_progress_at": "2026-03-06T00:00:00+00:00",
                            "dispatch_error": "worker exited without receipt or exit marker",
                        }
                    ],
                }
            ],
            "counts": {"runs": 0},
            "coordination": {},
        }
        result = handler._handle_swarm_status({})
        assert result.status_code == 200
        data = json.loads(result.body)
        summary = data["integrator_view"]["summary"]
        assert summary["blocked_lanes"] == 1
        assert summary["stale_heartbeat_lanes"] == 1
        assert summary["missing_receipt_lanes"] == 1
        assert data["integrator_view"]["alerts"]["collisions"][0]["reasons"] == [
            "path:aragora/swarm/reporter.py"
        ]

    @patch("aragora.server.handlers.control_plane.coordination.FleetCoordinationStore")
    @patch("aragora.server.handlers.control_plane.coordination.resolve_repo_root")
    def test_get_coordination_fleet_claims(
        self,
        mock_resolve,
        mock_store_cls,
        handler: ControlPlaneHandler,
        mock_http_handler: MagicMock,
    ):
        mock_resolve.return_value = Path("/tmp/repo")
        store = MagicMock()
        store.list_claims.return_value = [{"session_id": "session-a", "path": "aragora/x.py"}]
        mock_store_cls.return_value = store
        mock_http_handler.path = "/api/v1/coordination/fleet/claims"
        result = handler.handle("/api/v1/coordination/fleet/claims", {}, mock_http_handler)
        assert result is not None
        assert result.status_code == 200
