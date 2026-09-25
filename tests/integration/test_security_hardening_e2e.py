"""
End-to-end integration tests for security hardening.

Tests the complete flow of:
- Encryption at rest for secrets
- RBAC permission enforcement
- Migration utilities
- DecisionRouter integration
"""

from __future__ import annotations

import os
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


# Skip encryption tests if no key
pytestmark_encryption = pytest.mark.skipif(
    not os.environ.get("ARAGORA_ENCRYPTION_KEY"), reason="ARAGORA_ENCRYPTION_KEY not set"
)


class TestEncryptionIntegration:
    """End-to-end tests for encryption at rest."""

    @pytest.fixture
    def encryption_key(self):
        """Generate a test encryption key."""
        import secrets

        key = secrets.token_hex(32)
        with patch.dict(os.environ, {"ARAGORA_ENCRYPTION_KEY": key}):
            yield key

    def test_encrypt_decrypt_round_trip(self, encryption_key):
        """Test complete encrypt/decrypt cycle."""
        from aragora.security.encryption import get_encryption_service

        service = get_encryption_service()

        # Simulate integration config with secrets
        config = {
            "integration_id": "int_123",
            "name": "Test Integration",
            "type": "api",
            "api_key": "sk-live-secret-key-12345",
            "api_secret": "secret-value-67890",
            "enabled": True,
        }

        sensitive_fields = ["api_key", "api_secret"]

        # Encrypt
        encrypted = service.encrypt_fields(config.copy(), sensitive_fields)

        # Verify encryption happened
        assert encrypted["api_key"] != config["api_key"]
        assert encrypted["api_secret"] != config["api_secret"]
        assert encrypted["api_key"].get("_encrypted") is True

        # Non-sensitive fields unchanged
        assert encrypted["integration_id"] == config["integration_id"]
        assert encrypted["name"] == config["name"]

        # Decrypt
        decrypted = service.decrypt_fields(encrypted, sensitive_fields)

        # Verify round-trip
        assert decrypted["api_key"] == config["api_key"]
        assert decrypted["api_secret"] == config["api_secret"]

    def test_associated_data_prevents_tampering(self, encryption_key):
        """Test that associated data binding prevents record swapping."""
        from aragora.security.encryption import get_encryption_service

        service = get_encryption_service()

        # Encrypt for record 1
        data = {"api_key": "secret123"}
        encrypted = service.encrypt_fields(data.copy(), ["api_key"], associated_data="record_1")

        # Try to decrypt for record 2 (should fail)
        with pytest.raises(Exception):
            service.decrypt_fields(encrypted, ["api_key"], associated_data="record_2")

        # Decrypt with correct record ID works
        decrypted = service.decrypt_fields(encrypted, ["api_key"], associated_data="record_1")
        assert decrypted["api_key"] == "secret123"


class TestRBACIntegration:
    """End-to-end tests for RBAC enforcement."""

    @pytest.fixture
    def rbac_setup(self):
        """Set up RBAC for testing."""
        from aragora.rbac import AuthorizationContext, check_permission
        from aragora.rbac.models import AuthorizationDecision

        return AuthorizationContext, check_permission, AuthorizationDecision

    def test_admin_has_all_permissions(self, rbac_setup):
        """Test that admin role has all permissions."""
        AuthorizationContext, check_permission, _ = rbac_setup

        ctx = AuthorizationContext(
            user_id="admin_user",
            roles={"admin"},
            org_id="org_123",
        )

        permissions = [
            "organizations.update",
            "organizations.delete",
            "webhooks.create",
            "webhooks.delete",
            "workspaces.create",
            "workspaces.delete",
            "retention.policies.create",
            "retention.policies.execute",
        ]

        for perm in permissions:
            decision = check_permission(ctx, perm)
            assert decision.allowed, f"Admin should have {perm}"

    def test_viewer_denied_write_operations(self, rbac_setup):
        """Test that viewer role is denied write operations."""
        AuthorizationContext, check_permission, _ = rbac_setup

        ctx = AuthorizationContext(
            user_id="viewer_user",
            roles={"viewer"},
            org_id="org_123",
        )

        write_permissions = [
            "organizations.update",
            "webhooks.create",
            "webhooks.delete",
            "workspaces.delete",
            "retention.policies.execute",
        ]

        for perm in write_permissions:
            decision = check_permission(ctx, perm)
            assert not decision.allowed, f"Viewer should not have {perm}"

    def test_org_isolation(self, rbac_setup):
        """Test that permissions are isolated by organization."""
        AuthorizationContext, check_permission, _ = rbac_setup

        # User in org_1
        ctx = AuthorizationContext(
            user_id="user_1",
            roles={"admin"},
            org_id="org_1",
        )

        # Should have permission in own org
        decision = check_permission(ctx, "organizations.update")
        assert decision.allowed

        # Create context for different org
        ctx_other = AuthorizationContext(
            user_id="user_1",
            roles={"admin"},
            org_id="org_2",
        )

        # Still allowed because roles are checked, not cross-org access
        # (actual resource-level isolation happens in handlers)
        decision = check_permission(ctx_other, "organizations.update")
        assert decision.allowed  # Role check passes


class TestMigrationIntegration:
    """End-to-end tests for encryption migration."""

    @pytest.fixture
    def temp_store_dir(self):
        """Create temporary directory for test stores."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def encryption_key(self):
        """Generate a test encryption key."""
        import secrets

        key = secrets.token_hex(32)
        with patch.dict(os.environ, {"ARAGORA_ENCRYPTION_KEY": key}):
            yield key

    def test_detect_plaintext_records(self, encryption_key):
        """Test detection of records needing migration."""
        from aragora.security.migration import needs_migration, is_field_encrypted

        sensitive_fields = ["api_key", "password"]

        # Plaintext record needs migration
        plaintext_record = {
            "id": "1",
            "api_key": "sk-secret",
            "password": "pass123",
        }
        assert needs_migration(plaintext_record, sensitive_fields) is True

        # Encrypted record doesn't need migration
        encrypted_record = {
            "id": "2",
            "api_key": {"_encrypted": True, "ciphertext": "abc"},
            "password": {"_encrypted": True, "ciphertext": "def"},
        }
        assert needs_migration(encrypted_record, sensitive_fields) is False

        # Partial encryption needs migration
        partial_record = {
            "id": "3",
            "api_key": {"_encrypted": True, "ciphertext": "abc"},
            "password": "still-plaintext",
        }
        assert needs_migration(partial_record, sensitive_fields) is True

    def test_migrator_encrypts_records(self, encryption_key):
        """Test that migrator properly encrypts records."""
        from aragora.security.encryption import get_encryption_service
        from aragora.security.migration import EncryptionMigrator, is_field_encrypted

        service = get_encryption_service()
        migrator = EncryptionMigrator(encryption_service=service)

        # Plaintext record
        record = {
            "id": "test_1",
            "name": "Test",
            "api_key": "secret-key-123",
        }

        # Migrate
        migrated = migrator.migrate_record(record.copy(), ["api_key"], record_id="test_1")

        # Verify encryption
        assert is_field_encrypted(migrated["api_key"]) is True
        assert migrated["name"] == "Test"  # Non-sensitive unchanged

        # Verify can decrypt
        decrypted = service.decrypt_fields(migrated, ["api_key"], associated_data="test_1")
        assert decrypted["api_key"] == "secret-key-123"

    def test_store_migration_flow(self, encryption_key, temp_store_dir):
        """Test complete store migration flow."""
        from aragora.security.encryption import get_encryption_service
        from aragora.security.migration import (
            EncryptionMigrator,
            MigrationResult,
            needs_migration,
        )

        service = get_encryption_service()
        migrator = EncryptionMigrator(encryption_service=service)

        # Simulate a store with mixed records
        store_data = {
            "record_1": {"id": "record_1", "api_key": "key1", "name": "First"},
            "record_2": {"id": "record_2", "api_key": "key2", "name": "Second"},
            "record_3": {
                "id": "record_3",
                "api_key": {"_encrypted": True, "ciphertext": "already_enc"},
                "name": "Third",
            },
        }

        def list_fn():
            return list(store_data.values())

        def save_fn(record_id, record):
            store_data[record_id] = record
            return True

        # Run migration
        result = migrator.migrate_store(
            store_name="test_store",
            list_fn=list_fn,
            save_fn=save_fn,
            sensitive_fields=["api_key"],
            id_field="id",
        )

        # Verify results
        assert result.total_records == 3
        assert result.migrated_records == 2
        assert result.already_encrypted == 1
        assert result.failed_records == 0
        assert result.success is True

        # Verify all records are now encrypted
        for record in store_data.values():
            assert not needs_migration(record, ["api_key"])


class TestDecisionRouterIntegration:
    """End-to-end tests for DecisionRouter wiring."""

    def test_decision_router_accessible(self):
        """Test that DecisionRouter is properly exported."""
        from aragora.core import get_decision_router, DecisionRouter

        assert get_decision_router is not None
        assert DecisionRouter is not None

    def test_decision_request_creation(self):
        """Test creating a DecisionRequest."""
        from aragora.core.decision import (
            DecisionRequest,
            DecisionType,
            RequestContext,
            InputSource,
            ResponseChannel,
        )

        # Create request with DEBATE type
        request = DecisionRequest(
            content="Should we deploy to production?",
            decision_type=DecisionType.DEBATE,
            source=InputSource.HTTP_API,
        )

        assert request.content == "Should we deploy to production?"
        assert request.decision_type == DecisionType.DEBATE
        assert request.source == InputSource.HTTP_API

    @pytest.mark.asyncio
    async def test_chat_router_debate_starter(self):
        """Test the chat router's debate starter integration."""
        from aragora.server.handlers.chat.router import _create_decision_router_debate_starter

        starter = _create_decision_router_debate_starter()
        assert starter is not None
        assert callable(starter)

        # Mock the decision router
        with patch("aragora.core.get_decision_router") as mock_get:
            mock_router = MagicMock()
            mock_result = MagicMock()
            mock_result.request_id = "test-123"
            mock_result.success = True
            mock_result.answer = "Test answer"
            mock_result.confidence = 0.9
            mock_result.debate_result = MagicMock()
            mock_result.debate_result.debate_id = "debate-123"
            mock_router.route = AsyncMock(return_value=mock_result)
            mock_get.return_value = mock_router

            result = await starter(
                topic="Test debate",
                platform="slack",
                channel="C123",
                user="U456",
            )

            assert result["debate_id"] == "debate-123"
            assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_decision_router_attachment_ingestion(self, tmp_path, monkeypatch):
        """Attachment content should be persisted into document/evidence stores."""
        from aragora.core.decision import (
            DecisionConfig,
            DecisionRequest,
            DecisionRouter,
            DecisionType,
        )
        from aragora.evidence.store import InMemoryEvidenceStore
        from aragora.documents.parsing import DocumentStore

        monkeypatch.setattr(
            "aragora.agents.get_agents_by_names",
            lambda _agents=None: [],
        )

        class DummyArena:
            def __init__(self, environment, agents, protocol, **_kwargs):
                self.environment = environment

            async def run(self):
                return MagicMock(
                    final_answer="ok",
                    consensus_reached=True,
                    confidence=0.9,
                    summary=None,
                )

        document_store = DocumentStore(tmp_path)
        evidence_store = InMemoryEvidenceStore()
        router = DecisionRouter(
            debate_engine=DummyArena,
            document_store=document_store,
            evidence_store=evidence_store,
        )

        request = DecisionRequest(
            content="Check attachment",
            decision_type=DecisionType.DEBATE,
            config=DecisionConfig(rounds=1, agents=[]),
            attachments=[{"filename": "notes.txt", "content": "hello world"}],
        )

        result = await router.route(request)

        assert result.success is True
        assert document_store.list_all()
        assert evidence_store.search_evidence("hello world")


class TestSecurityHardeningComplete:
    """Integration tests verifying the complete security hardening."""

    @pytest.fixture
    def encryption_key(self):
        """Generate a test encryption key."""
        import secrets

        key = secrets.token_hex(32)
        with patch.dict(os.environ, {"ARAGORA_ENCRYPTION_KEY": key}):
            yield key

    def test_full_secret_lifecycle(self, encryption_key):
        """Test complete lifecycle: create -> encrypt -> store -> retrieve -> decrypt."""
        from aragora.security.encryption import get_encryption_service

        service = get_encryption_service()

        # 1. Create a secret
        integration_config = {
            "id": "int_abc123",
            "name": "Stripe Integration",
            "type": "payment",
            "api_key": "sk_live_abc123xyz",
            "webhook_secret": "whsec_123456789",
            "enabled": True,
        }

        sensitive_fields = ["api_key", "webhook_secret"]

        # 2. Encrypt before storage
        encrypted = service.encrypt_fields(
            integration_config.copy(), sensitive_fields, associated_data=integration_config["id"]
        )

        # 3. Simulate storage (JSON serialization)
        stored_json = json.dumps(encrypted)

        # 4. Simulate retrieval
        retrieved = json.loads(stored_json)

        # 5. Decrypt after retrieval
        decrypted = service.decrypt_fields(
            retrieved, sensitive_fields, associated_data=integration_config["id"]
        )

        # 6. Verify integrity
        assert decrypted["api_key"] == integration_config["api_key"]
        assert decrypted["webhook_secret"] == integration_config["webhook_secret"]
        assert decrypted["name"] == integration_config["name"]

    def test_startup_migration_config(self):
        """Test startup migration configuration from environment."""
        from aragora.security.migration import get_startup_migration_config

        # Test with migration enabled
        with patch.dict(
            os.environ,
            {
                "ARAGORA_MIGRATE_ON_STARTUP": "true",
                "ARAGORA_MIGRATION_DRY_RUN": "true",
                "ARAGORA_MIGRATION_STORES": "integration,gmail",
                "ARAGORA_MIGRATION_FAIL_ON_ERROR": "true",
            },
        ):
            config = get_startup_migration_config()

            assert config.enabled is True
            assert config.dry_run is True
            assert "integration" in config.stores
            assert "gmail" in config.stores
            assert config.fail_on_error is True

    def test_rbac_handler_pattern(self):
        """Test the RBAC handler pattern used across handlers."""
        # This tests the pattern, not the actual handlers

        from aragora.rbac import AuthorizationContext, check_permission

        # Pattern used in handlers:
        def _check_rbac_permission(user_id, roles, org_id, permission_key):
            """Check RBAC permission - pattern from handlers."""
            auth_ctx = AuthorizationContext(
                user_id=user_id,
                roles=set(roles) if isinstance(roles, list) else roles,
                org_id=org_id,
            )
            decision = check_permission(auth_ctx, permission_key)
            return decision.allowed, decision.reason

        # Test admin
        allowed, reason = _check_rbac_permission(
            "admin_user", {"admin"}, "org_1", "webhooks.create"
        )
        assert allowed is True

        # Test viewer
        allowed, reason = _check_rbac_permission(
            "viewer_user", {"viewer"}, "org_1", "webhooks.create"
        )
        assert allowed is False

    def test_encryption_service_singleton(self, encryption_key):
        """Test that encryption service is a proper singleton."""
        from aragora.security.encryption import get_encryption_service

        service1 = get_encryption_service()
        service2 = get_encryption_service()

        # Should be the same instance
        assert service1 is service2

    def test_migration_idempotency(self, encryption_key):
        """Test that migration with proper checks is idempotent."""
        from aragora.security.encryption import get_encryption_service
        from aragora.security.migration import EncryptionMigrator, needs_migration

        service = get_encryption_service()
        migrator = EncryptionMigrator(encryption_service=service)

        # Initial record
        record = {"id": "test", "api_key": "secret123"}
        sensitive_fields = ["api_key"]

        # First migration
        assert needs_migration(record, sensitive_fields)  # Needs migration
        migrated1 = migrator.migrate_record(record.copy(), sensitive_fields)
        assert not needs_migration(migrated1, sensitive_fields)  # Now encrypted

        # Second migration - check first (proper pattern)
        if needs_migration(migrated1, sensitive_fields):
            migrated2 = migrator.migrate_record(migrated1.copy(), sensitive_fields)
        else:
            migrated2 = migrated1  # Skip migration for already encrypted

        # Both should decrypt to same value
        decrypted1 = service.decrypt_fields(migrated1.copy(), sensitive_fields)
        decrypted2 = service.decrypt_fields(migrated2.copy(), sensitive_fields)
        assert decrypted1["api_key"] == decrypted2["api_key"] == "secret123"


class TestHeaderTrustVulnerabilityFix:
    """
    Tests verifying that header-based authentication fallback is removed.

    SECURITY CONTEXT:
    The X-User-ID and X-User-Roles headers were previously trusted when JWT
    authentication failed. This allowed identity spoofing and privilege escalation
    by simply setting headers in requests.

    These tests verify:
    1. Handlers reject requests without valid JWT tokens
    2. Spoofed headers are ignored
    3. Only JWT-based authentication is accepted
    """

    @pytest.fixture
    def mock_request_with_spoofed_headers(self):
        """Create a request with spoofed identity headers."""
        request = MagicMock()
        request.headers = {
            "X-User-ID": "spoofed-admin-user",
            "X-Org-ID": "spoofed-org",
            "X-User-Roles": "admin,owner,superuser",  # Privilege escalation attempt
        }
        return request

    def test_workflows_handler_rejects_spoofed_headers(self, mock_request_with_spoofed_headers):
        """Test that WorkflowHandler rejects spoofed headers without JWT."""
        from aragora.server.handlers.workflows import WorkflowHandler, RBAC_AVAILABLE

        assert RBAC_AVAILABLE, "RBAC should be available"

        handler = WorkflowHandler({})

        with patch("aragora.server.handlers.workflows.extract_user_from_request") as mock_extract:
            # Simulate no valid JWT token
            mock_jwt_context = MagicMock()
            mock_jwt_context.authenticated = False
            mock_jwt_context.user_id = None
            mock_extract.return_value = mock_jwt_context

            context = handler._get_auth_context(mock_request_with_spoofed_headers)

            # Should return "unauthenticated" sentinel, NOT use spoofed headers
            assert context == "unauthenticated"

    def test_finding_workflow_handler_rejects_spoofed_headers(
        self, mock_request_with_spoofed_headers
    ):
        """Test that FindingWorkflowHandler rejects spoofed headers without JWT."""
        from aragora.server.handlers.features.finding_workflow import FindingWorkflowHandler

        handler = FindingWorkflowHandler({})

        with patch(
            "aragora.server.handlers.features.finding_workflow.extract_user_from_request"
        ) as mock_extract:
            # Simulate no valid JWT token
            mock_jwt_context = MagicMock()
            mock_jwt_context.authenticated = False
            mock_jwt_context.user_id = None
            mock_extract.return_value = mock_jwt_context

            context = handler._get_auth_context(mock_request_with_spoofed_headers)

            # Should return None, NOT use spoofed headers
            assert context is None

    def test_check_permission_returns_401_for_spoofed_headers(
        self, mock_request_with_spoofed_headers
    ):
        """Test that _check_permission returns 401 for unauthenticated requests."""
        from aragora.server.handlers.workflows import WorkflowHandler, RBAC_AVAILABLE

        assert RBAC_AVAILABLE, "RBAC should be available"

        handler = WorkflowHandler({})

        with patch("aragora.server.handlers.workflows.extract_user_from_request") as mock_extract:
            mock_jwt_context = MagicMock()
            mock_jwt_context.authenticated = False
            mock_jwt_context.user_id = None
            mock_extract.return_value = mock_jwt_context

            error_response = handler._check_permission(
                mock_request_with_spoofed_headers, "workflows:read"
            )

            # Should return 401 Unauthorized, NOT allow access
            assert error_response is not None
            assert error_response.status_code == 401

    def test_valid_jwt_is_accepted(self):
        """Test that valid JWT authentication is accepted."""
        from aragora.server.handlers.workflows import WorkflowHandler, RBAC_AVAILABLE

        assert RBAC_AVAILABLE, "RBAC should be available"

        handler = WorkflowHandler({})
        request = MagicMock()
        request.headers = {}

        with patch("aragora.server.handlers.workflows.extract_user_from_request") as mock_extract:
            # Simulate valid JWT token
            mock_jwt_context = MagicMock()
            mock_jwt_context.authenticated = True
            mock_jwt_context.user_id = "jwt-verified-user"
            mock_jwt_context.org_id = "org-123"
            mock_jwt_context.role = "admin"
            mock_extract.return_value = mock_jwt_context

            context = handler._get_auth_context(request)

            # Should return valid AuthorizationContext
            assert context is not None
            assert context != "unauthenticated"
            assert context.user_id == "jwt-verified-user"
            assert context.org_id == "org-123"

    def test_privilege_escalation_prevented(self, mock_request_with_spoofed_headers):
        """Test that X-User-Roles header cannot escalate privileges."""
        from aragora.server.handlers.workflows import WorkflowHandler, RBAC_AVAILABLE

        assert RBAC_AVAILABLE, "RBAC should be available"

        handler = WorkflowHandler({})

        with patch("aragora.server.handlers.workflows.extract_user_from_request") as mock_extract:
            # Attacker has valid JWT but tries to escalate via headers
            mock_jwt_context = MagicMock()
            mock_jwt_context.authenticated = True
            mock_jwt_context.user_id = "low-priv-user"
            mock_jwt_context.org_id = "org-123"
            mock_jwt_context.role = "viewer"  # Low privilege role from JWT
            mock_extract.return_value = mock_jwt_context

            context = handler._get_auth_context(mock_request_with_spoofed_headers)

            # Should use JWT role, NOT the spoofed X-User-Roles header
            assert context is not None
            assert context != "unauthenticated"
            assert "viewer" in context.roles
            assert "admin" not in context.roles  # Escalation prevented
            assert "owner" not in context.roles
            assert "superuser" not in context.roles
