"""
Tests for cross-workspace coordination module.

Tests federation policies, data sharing consents, and cross-workspace operations.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

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
    get_coordinator,
)


class TestSharingScope:
    """Tests for SharingScope enum."""

    def test_all_scopes_exist(self):
        """All expected scopes are defined."""
        assert SharingScope.NONE.value == "none"
        assert SharingScope.METADATA.value == "metadata"
        assert SharingScope.SUMMARY.value == "summary"
        assert SharingScope.FULL.value == "full"
        assert SharingScope.SELECTIVE.value == "selective"

    def test_scope_from_string(self):
        """Scopes can be created from strings."""
        assert SharingScope("full") == SharingScope.FULL
        assert SharingScope("none") == SharingScope.NONE


class TestFederationMode:
    """Tests for FederationMode enum."""

    def test_all_modes_exist(self):
        """All expected modes are defined."""
        assert FederationMode.ISOLATED.value == "isolated"
        assert FederationMode.READONLY.value == "readonly"
        assert FederationMode.BIDIRECTIONAL.value == "bidirectional"
        assert FederationMode.ORCHESTRATED.value == "orchestrated"


class TestOperationType:
    """Tests for OperationType enum."""

    def test_all_operations_exist(self):
        """All expected operations are defined."""
        ops = [
            OperationType.READ_KNOWLEDGE,
            OperationType.QUERY_MOUND,
            OperationType.EXECUTE_AGENT,
            OperationType.RUN_WORKFLOW,
            OperationType.SHARE_FINDINGS,
            OperationType.SYNC_CULTURE,
            OperationType.BROADCAST_MESSAGE,
        ]
        assert len(ops) == 7


class TestFederationPolicy:
    """Tests for FederationPolicy dataclass."""

    def test_default_policy_is_isolated(self):
        """Default policy is isolated mode."""
        policy = FederationPolicy()
        assert policy.mode == FederationMode.ISOLATED
        assert policy.sharing_scope == SharingScope.NONE

    def test_policy_validity(self):
        """Policy validity checks work correctly."""
        # Valid policy
        policy = FederationPolicy(
            valid_from=datetime.now(timezone.utc) - timedelta(hours=1),
            valid_until=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert policy.is_valid()

        # Not yet valid
        future_policy = FederationPolicy(
            valid_from=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert not future_policy.is_valid()

        # Expired policy
        expired_policy = FederationPolicy(
            valid_from=datetime.now(timezone.utc) - timedelta(hours=2),
            valid_until=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert not expired_policy.is_valid()

    def test_policy_allows_operation_isolated(self):
        """Isolated mode blocks all operations."""
        policy = FederationPolicy(mode=FederationMode.ISOLATED)
        assert not policy.allows_operation(OperationType.READ_KNOWLEDGE, "ws1", "ws2")

    def test_policy_allows_operation_readonly(self):
        """Readonly mode allows read operations only."""
        policy = FederationPolicy(
            mode=FederationMode.READONLY,
            allowed_operations={OperationType.READ_KNOWLEDGE, OperationType.QUERY_MOUND},
        )

        # Read allowed
        assert policy.allows_operation(OperationType.READ_KNOWLEDGE, "ws1", "ws2")
        assert policy.allows_operation(OperationType.QUERY_MOUND, "ws1", "ws2")

        # Write blocked
        assert not policy.allows_operation(OperationType.EXECUTE_AGENT, "ws1", "ws2")
        assert not policy.allows_operation(OperationType.RUN_WORKFLOW, "ws1", "ws2")

    def test_policy_blocks_workspaces(self):
        """Blocked workspaces are denied."""
        policy = FederationPolicy(
            mode=FederationMode.BIDIRECTIONAL,
            blocked_workspaces={"blocked-ws"},
        )

        # Blocked source
        assert not policy.allows_operation(OperationType.READ_KNOWLEDGE, "blocked-ws", "ws2")

        # Blocked target
        assert not policy.allows_operation(OperationType.READ_KNOWLEDGE, "ws1", "blocked-ws")

        # Non-blocked allowed
        assert policy.allows_operation(OperationType.READ_KNOWLEDGE, "ws1", "ws2")

    def test_policy_allows_specific_workspaces(self):
        """Only allowed workspaces can interact."""
        policy = FederationPolicy(
            mode=FederationMode.BIDIRECTIONAL,
            allowed_source_workspaces={"allowed-src"},
            allowed_target_workspaces={"allowed-tgt"},
        )

        # Both allowed
        assert policy.allows_operation(OperationType.READ_KNOWLEDGE, "allowed-src", "allowed-tgt")

        # Source not allowed
        assert not policy.allows_operation(OperationType.READ_KNOWLEDGE, "other-src", "allowed-tgt")

        # Target not allowed
        assert not policy.allows_operation(OperationType.READ_KNOWLEDGE, "allowed-src", "other-tgt")

    def test_policy_blocked_operations(self):
        """Blocked operations are denied."""
        policy = FederationPolicy(
            mode=FederationMode.BIDIRECTIONAL,
            blocked_operations={OperationType.EXECUTE_AGENT},
        )

        assert policy.allows_operation(OperationType.READ_KNOWLEDGE, "ws1", "ws2")
        assert not policy.allows_operation(OperationType.EXECUTE_AGENT, "ws1", "ws2")

    def test_policy_to_dict(self):
        """Policy serializes to dictionary."""
        policy = FederationPolicy(
            name="test-policy",
            mode=FederationMode.READONLY,
            sharing_scope=SharingScope.METADATA,
        )
        d = policy.to_dict()

        assert d["name"] == "test-policy"
        assert d["mode"] == "readonly"
        assert d["sharing_scope"] == "metadata"


class TestDataSharingConsent:
    """Tests for DataSharingConsent dataclass."""

    def test_consent_validity(self):
        """Consent validity checks work."""
        # Valid consent
        consent = DataSharingConsent(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
        )
        assert consent.is_valid()

        # Expired consent
        expired = DataSharingConsent(
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert not expired.is_valid()

        # Revoked consent
        revoked = DataSharingConsent()
        revoked.revoke("user1")
        assert not revoked.is_valid()

    def test_consent_usage_tracking(self):
        """Consent tracks usage correctly."""
        consent = DataSharingConsent()
        assert consent.times_used == 0
        assert consent.data_transferred_bytes == 0

        consent.record_usage(1024)
        assert consent.times_used == 1
        assert consent.data_transferred_bytes == 1024
        assert consent.last_used is not None

        consent.record_usage(2048)
        assert consent.times_used == 2
        assert consent.data_transferred_bytes == 3072

    def test_consent_revocation(self):
        """Consent revocation works."""
        consent = DataSharingConsent()
        assert not consent.revoked

        consent.revoke("admin")
        assert consent.revoked
        assert consent.revoked_by == "admin"
        assert consent.revoked_at is not None
        assert not consent.is_valid()

    def test_consent_to_dict(self):
        """Consent serializes to dictionary."""
        consent = DataSharingConsent(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
            scope=SharingScope.FULL,
            granted_by="user1",
        )
        d = consent.to_dict()

        assert d["source_workspace_id"] == "ws1"
        assert d["target_workspace_id"] == "ws2"
        assert d["scope"] == "full"
        assert d["granted_by"] == "user1"
        assert d["is_valid"] is True


class TestFederatedWorkspace:
    """Tests for FederatedWorkspace dataclass."""

    def test_workspace_defaults(self):
        """Workspace has correct defaults."""
        ws = FederatedWorkspace(id="ws1", name="Test Workspace")
        assert ws.is_federated is True
        assert ws.federation_mode == FederationMode.READONLY
        assert ws.supports_agent_execution is True
        assert ws.is_online is True

    def test_workspace_to_dict(self):
        """Workspace serializes to dictionary."""
        ws = FederatedWorkspace(
            id="ws1",
            name="Test",
            org_id="org1",
            federation_mode=FederationMode.BIDIRECTIONAL,
        )
        d = ws.to_dict()

        assert d["id"] == "ws1"
        assert d["name"] == "Test"
        assert d["org_id"] == "org1"
        assert d["federation_mode"] == "bidirectional"


class TestCrossWorkspaceRequest:
    """Tests for CrossWorkspaceRequest dataclass."""

    def test_request_defaults(self):
        """Request has correct defaults."""
        req = CrossWorkspaceRequest(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
        )
        assert req.operation == OperationType.READ_KNOWLEDGE
        assert req.status == "pending"
        assert req.timeout_seconds == 30.0
        assert req.id  # Has an ID

    def test_request_to_dict(self):
        """Request serializes to dictionary."""
        req = CrossWorkspaceRequest(
            operation=OperationType.EXECUTE_AGENT,
            source_workspace_id="ws1",
            target_workspace_id="ws2",
            requester_id="user1",
        )
        d = req.to_dict()

        assert d["operation"] == "execute_agent"
        assert d["source_workspace_id"] == "ws1"
        assert d["target_workspace_id"] == "ws2"


class TestCrossWorkspaceResult:
    """Tests for CrossWorkspaceResult dataclass."""

    def test_result_success(self):
        """Successful result contains data."""
        result = CrossWorkspaceResult(
            request_id="req1",
            success=True,
            data={"key": "value"},
        )
        d = result.to_dict()

        assert d["success"] is True
        assert d["data"] == {"key": "value"}

    def test_result_failure(self):
        """Failed result contains error."""
        result = CrossWorkspaceResult(
            request_id="req1",
            success=False,
            error="Something went wrong",
            error_code="FAIL",
        )
        d = result.to_dict()

        assert d["success"] is False
        assert d["error"] == "Something went wrong"
        assert d["error_code"] == "FAIL"
        assert d["data"] is None


class TestCrossWorkspaceCoordinator:
    """Tests for CrossWorkspaceCoordinator class."""

    def test_coordinator_init(self):
        """Coordinator initializes correctly."""
        coordinator = CrossWorkspaceCoordinator()
        assert coordinator._default_policy.mode == FederationMode.ISOLATED

    def test_coordinator_with_custom_policy(self):
        """Coordinator accepts custom default policy."""
        policy = FederationPolicy(
            name="custom",
            mode=FederationMode.BIDIRECTIONAL,
        )
        coordinator = CrossWorkspaceCoordinator(default_policy=policy)
        assert coordinator._default_policy.mode == FederationMode.BIDIRECTIONAL

    def test_register_workspace(self):
        """Workspaces can be registered."""
        coordinator = CrossWorkspaceCoordinator()
        ws = FederatedWorkspace(id="ws1", name="Test")

        coordinator.register_workspace(ws)

        assert "ws1" in coordinator._workspaces
        assert coordinator._workspaces["ws1"] == ws

    def test_unregister_workspace(self):
        """Workspaces can be unregistered."""
        coordinator = CrossWorkspaceCoordinator()
        ws = FederatedWorkspace(id="ws1", name="Test")
        coordinator.register_workspace(ws)

        coordinator.unregister_workspace("ws1")

        assert "ws1" not in coordinator._workspaces

    def test_list_workspaces(self):
        """List returns all registered workspaces."""
        coordinator = CrossWorkspaceCoordinator()
        ws1 = FederatedWorkspace(id="ws1", name="Test1")
        ws2 = FederatedWorkspace(id="ws2", name="Test2")

        coordinator.register_workspace(ws1)
        coordinator.register_workspace(ws2)

        workspaces = coordinator.list_workspaces()
        assert len(workspaces) == 2
        assert ws1 in workspaces
        assert ws2 in workspaces

    def test_set_and_get_policy(self):
        """Policies can be set and retrieved."""
        coordinator = CrossWorkspaceCoordinator()
        policy = FederationPolicy(
            name="pair-policy",
            mode=FederationMode.READONLY,
        )

        coordinator.set_policy(
            policy,
            source_workspace_id="ws1",
            target_workspace_id="ws2",
        )

        retrieved = coordinator.get_policy("ws1", "ws2")
        assert retrieved.name == "pair-policy"
        assert retrieved.mode == FederationMode.READONLY

    def test_get_policy_falls_back_to_default(self):
        """Unknown workspace pairs use default policy."""
        coordinator = CrossWorkspaceCoordinator()

        policy = coordinator.get_policy("unknown1", "unknown2")
        assert policy.mode == FederationMode.ISOLATED

    def test_grant_consent(self):
        """Consent can be granted."""
        coordinator = CrossWorkspaceCoordinator()

        consent = coordinator.grant_consent(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
            scope=SharingScope.FULL,
            data_types={"debates", "findings"},
            operations={OperationType.READ_KNOWLEDGE},
            granted_by="admin",
        )

        assert consent.source_workspace_id == "ws1"
        assert consent.target_workspace_id == "ws2"
        assert consent.scope == SharingScope.FULL
        assert consent.is_valid()

    def test_grant_consent_with_expiry(self):
        """Consent with expiry is set correctly."""
        coordinator = CrossWorkspaceCoordinator()

        consent = coordinator.grant_consent(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
            scope=SharingScope.METADATA,
            data_types=set(),
            operations=set(),
            granted_by="admin",
            expires_in_days=30,
        )

        assert consent.expires_at is not None
        assert consent.expires_at > datetime.now(timezone.utc)

    def test_revoke_consent(self):
        """Consent can be revoked."""
        coordinator = CrossWorkspaceCoordinator()
        consent = coordinator.grant_consent(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
            scope=SharingScope.METADATA,
            data_types=set(),
            operations=set(),
            granted_by="admin",
        )

        result = coordinator.revoke_consent(consent.id, "admin")

        assert result is True
        assert not consent.is_valid()

    def test_revoke_nonexistent_consent(self):
        """Revoking nonexistent consent returns False."""
        coordinator = CrossWorkspaceCoordinator()
        result = coordinator.revoke_consent("nonexistent", "admin")
        assert result is False

    def test_get_consent(self):
        """Consent can be retrieved for operation."""
        coordinator = CrossWorkspaceCoordinator()
        coordinator.grant_consent(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
            scope=SharingScope.FULL,
            data_types={"debates"},
            operations={OperationType.READ_KNOWLEDGE},
            granted_by="admin",
        )

        consent = coordinator.get_consent("ws1", "ws2", OperationType.READ_KNOWLEDGE)
        assert consent is not None
        assert consent.source_workspace_id == "ws1"

    def test_get_consent_not_found(self):
        """Returns None when no matching consent."""
        coordinator = CrossWorkspaceCoordinator()
        consent = coordinator.get_consent("ws1", "ws2", OperationType.READ_KNOWLEDGE)
        assert consent is None

    def test_list_consents(self):
        """All consents can be listed."""
        coordinator = CrossWorkspaceCoordinator()
        coordinator.grant_consent("ws1", "ws2", SharingScope.METADATA, set(), set(), "admin")
        coordinator.grant_consent("ws2", "ws3", SharingScope.FULL, set(), set(), "admin")

        all_consents = coordinator.list_consents()
        assert len(all_consents) == 2

    def test_list_consents_by_workspace(self):
        """Consents can be filtered by workspace."""
        coordinator = CrossWorkspaceCoordinator()
        coordinator.grant_consent("ws1", "ws2", SharingScope.METADATA, set(), set(), "admin")
        coordinator.grant_consent("ws2", "ws3", SharingScope.FULL, set(), set(), "admin")

        ws1_consents = coordinator.list_consents("ws1")
        assert len(ws1_consents) == 1

    def test_register_handler(self):
        """Operation handlers can be registered."""
        coordinator = CrossWorkspaceCoordinator()

        def handler(request):
            return CrossWorkspaceResult(
                request_id=request.id,
                success=True,
                data="result",
            )

        coordinator.register_handler(OperationType.READ_KNOWLEDGE, handler)
        assert OperationType.READ_KNOWLEDGE in coordinator._handlers

    @pytest.mark.asyncio
    async def test_execute_workspace_not_found(self):
        """Execute fails when workspace not registered."""
        coordinator = CrossWorkspaceCoordinator()
        request = CrossWorkspaceRequest(
            source_workspace_id="unknown",
            target_workspace_id="ws2",
        )

        result = await coordinator.execute(request)

        assert not result.success
        assert result.error_code == "WORKSPACE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_execute_policy_denied(self):
        """Execute fails when policy denies operation."""
        coordinator = CrossWorkspaceCoordinator()

        # Register workspaces
        coordinator.register_workspace(FederatedWorkspace(id="ws1", name="WS1"))
        coordinator.register_workspace(FederatedWorkspace(id="ws2", name="WS2"))

        # Default policy is isolated, should deny
        request = CrossWorkspaceRequest(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
            operation=OperationType.READ_KNOWLEDGE,
        )

        result = await coordinator.execute(request)

        assert not result.success
        assert result.error_code == "POLICY_DENIED"

    @pytest.mark.asyncio
    async def test_execute_no_consent(self):
        """Execute fails when no consent exists."""
        coordinator = CrossWorkspaceCoordinator()

        # Register workspaces
        coordinator.register_workspace(FederatedWorkspace(id="ws1", name="WS1"))
        coordinator.register_workspace(FederatedWorkspace(id="ws2", name="WS2"))

        # Set permissive policy
        policy = FederationPolicy(
            mode=FederationMode.BIDIRECTIONAL,
            sharing_scope=SharingScope.FULL,
        )
        coordinator.set_policy(policy)

        request = CrossWorkspaceRequest(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
        )

        result = await coordinator.execute(request)

        assert not result.success
        assert result.error_code == "NO_CONSENT"

    @pytest.mark.asyncio
    async def test_execute_no_handler(self):
        """Execute fails when no handler registered."""
        coordinator = CrossWorkspaceCoordinator()

        # Setup workspaces, policy, and consent
        coordinator.register_workspace(FederatedWorkspace(id="ws1", name="WS1"))
        coordinator.register_workspace(FederatedWorkspace(id="ws2", name="WS2"))

        policy = FederationPolicy(
            mode=FederationMode.BIDIRECTIONAL,
            sharing_scope=SharingScope.FULL,
        )
        coordinator.set_policy(policy)

        coordinator.grant_consent(
            "ws1", "ws2", SharingScope.FULL, set(), {OperationType.READ_KNOWLEDGE}, "admin"
        )

        request = CrossWorkspaceRequest(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
        )

        result = await coordinator.execute(request)

        assert not result.success
        assert result.error_code == "NO_HANDLER"

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Execute succeeds with proper setup."""
        coordinator = CrossWorkspaceCoordinator()

        # Setup
        coordinator.register_workspace(FederatedWorkspace(id="ws1", name="WS1"))
        coordinator.register_workspace(FederatedWorkspace(id="ws2", name="WS2"))

        policy = FederationPolicy(
            mode=FederationMode.BIDIRECTIONAL,
            sharing_scope=SharingScope.FULL,
        )
        coordinator.set_policy(policy)

        coordinator.grant_consent(
            "ws1", "ws2", SharingScope.FULL, set(), {OperationType.READ_KNOWLEDGE}, "admin"
        )

        def handler(req):
            return CrossWorkspaceResult(
                request_id=req.id,
                success=True,
                data={"result": "data"},
            )

        coordinator.register_handler(OperationType.READ_KNOWLEDGE, handler)

        request = CrossWorkspaceRequest(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
            operation=OperationType.READ_KNOWLEDGE,
        )

        result = await coordinator.execute(request)

        assert result.success
        assert result.data == {"result": "data"}

    @pytest.mark.asyncio
    async def test_execute_rate_limited(self):
        """Execute fails when rate limited."""
        coordinator = CrossWorkspaceCoordinator()

        # Setup with very low rate limit
        coordinator.register_workspace(FederatedWorkspace(id="ws1", name="WS1"))
        coordinator.register_workspace(FederatedWorkspace(id="ws2", name="WS2"))

        policy = FederationPolicy(
            mode=FederationMode.BIDIRECTIONAL,
            sharing_scope=SharingScope.FULL,
            max_requests_per_hour=1,
        )
        coordinator.set_policy(policy)

        coordinator.grant_consent(
            "ws1", "ws2", SharingScope.FULL, set(), {OperationType.READ_KNOWLEDGE}, "admin"
        )

        def handler(req):
            return CrossWorkspaceResult(request_id=req.id, success=True)

        coordinator.register_handler(OperationType.READ_KNOWLEDGE, handler)

        # First request succeeds
        req1 = CrossWorkspaceRequest(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
        )
        result1 = await coordinator.execute(req1)
        assert result1.success

        # Second request is rate limited
        req2 = CrossWorkspaceRequest(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
        )
        result2 = await coordinator.execute(req2)
        assert not result2.success
        assert result2.error_code == "RATE_LIMIT_EXCEEDED"

    def test_approve_request(self):
        """Pending requests can be approved."""
        coordinator = CrossWorkspaceCoordinator()
        request = CrossWorkspaceRequest(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
        )
        coordinator._pending_requests[request.id] = request

        result = coordinator.approve_request(request.id, "admin")

        assert result is True
        assert request.status == "approved"
        assert request.approved_by == "admin"
        assert request.id not in coordinator._pending_requests

    def test_reject_request(self):
        """Pending requests can be rejected."""
        coordinator = CrossWorkspaceCoordinator()
        request = CrossWorkspaceRequest(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
        )
        coordinator._pending_requests[request.id] = request

        result = coordinator.reject_request(request.id, "admin", "Not allowed")

        assert result is True
        assert request.status == "rejected"
        assert request.id not in coordinator._pending_requests

    def test_list_pending_requests(self):
        """Pending requests can be listed."""
        coordinator = CrossWorkspaceCoordinator()
        req1 = CrossWorkspaceRequest(
            source_workspace_id="ws1",
            target_workspace_id="ws2",
        )
        req2 = CrossWorkspaceRequest(
            source_workspace_id="ws3",
            target_workspace_id="ws4",
        )
        coordinator._pending_requests[req1.id] = req1
        coordinator._pending_requests[req2.id] = req2

        all_pending = coordinator.list_pending_requests()
        assert len(all_pending) == 2

        ws2_pending = coordinator.list_pending_requests("ws2")
        assert len(ws2_pending) == 1

    def test_get_stats(self):
        """Statistics are correctly computed."""
        coordinator = CrossWorkspaceCoordinator()
        coordinator.register_workspace(FederatedWorkspace(id="ws1", name="WS1"))
        coordinator.grant_consent("ws1", "ws2", SharingScope.METADATA, set(), set(), "admin")

        stats = coordinator.get_stats()

        assert stats["total_workspaces"] == 1
        assert stats["total_consents"] == 1
        assert stats["valid_consents"] == 1
        assert stats["pending_requests"] == 0

    def test_audit_callback(self):
        """Audit callback is invoked on events."""
        audit_events = []

        def audit_cb(event):
            audit_events.append(event)

        coordinator = CrossWorkspaceCoordinator(audit_callback=audit_cb)
        coordinator.register_workspace(FederatedWorkspace(id="ws1", name="WS1"))

        assert len(audit_events) == 1
        assert audit_events[0]["event_type"] == "workspace_registered"


class TestGlobalCoordinator:
    """Tests for global coordinator accessor."""

    @pytest.fixture(autouse=True)
    def _reset_coordinator_singleton(self):
        """Reset coordinator singleton before/after each test."""
        import aragora.tenancy.cross_workspace as cw

        cw._coordinator = None
        yield
        cw._coordinator = None

    def test_get_coordinator_returns_instance(self):
        """get_coordinator returns a coordinator."""
        coordinator = get_coordinator()
        assert isinstance(coordinator, CrossWorkspaceCoordinator)

    def test_get_coordinator_returns_same_instance(self):
        """get_coordinator returns singleton."""
        c1 = get_coordinator()
        c2 = get_coordinator()
        assert c1 is c2
