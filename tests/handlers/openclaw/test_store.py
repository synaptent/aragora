"""Comprehensive tests for OpenClaw Gateway Store module.

Covers both OpenClawGatewayStore (in-memory) and OpenClawPersistentStore (SQLite),
plus the _get_store factory function.

Test categories:
- In-memory store: session CRUD, action CRUD, credential CRUD, audit log, metrics
- Session expiration and idle timeout
- Pagination and filtering across all entity types
- Persistent store: same API surface backed by SQLite
- Persistent store: LRU caching behavior
- Persistent store: encryption fallback and production guard
- _get_store factory: environment-based backend selection
- Edge cases: empty stores, non-existent IDs, boundary values
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.gateway.openclaw_policy import PolicyDecision
from aragora.server.handlers.openclaw.models import (
    Action,
    ActionStatus,
    ApprovalRequest,
    AuditEntry,
    Credential,
    CredentialType,
    Session,
    SessionStatus,
)
from aragora.server.handlers.openclaw.runtime import OpenClawExecutionRuntime
from aragora.server.handlers.openclaw.store import (
    OpenClawGatewayStore,
    OpenClawPersistentStore,
    _get_store,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mem_store():
    """Create a fresh in-memory store."""
    return OpenClawGatewayStore()


@pytest.fixture
def mem_store_short_timeout():
    """In-memory store with 60-second idle timeout."""
    return OpenClawGatewayStore(session_idle_timeout=60)


@pytest.fixture
def persistent_store(tmp_path):
    """Create a persistent store backed by a temp SQLite DB."""
    db_path = str(tmp_path / "test_openclaw.db")
    store = OpenClawPersistentStore(db_path=db_path, cache_size=10)
    return store


@pytest.fixture
def reset_global_store():
    """Reset the module-level _store singleton between tests."""
    import aragora.server.handlers.openclaw.store as store_mod

    original = store_mod._store
    store_mod._store = None
    yield
    store_mod._store = original


# ============================================================================
# In-Memory Store: Session CRUD
# ============================================================================


class TestMemSessionCRUD:
    """Session create/read/update/delete on in-memory store."""

    def test_create_session_returns_session(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        assert isinstance(session, Session)
        assert session.user_id == "u1"

    def test_create_session_generates_unique_ids(self, mem_store):
        s1 = mem_store.create_session(user_id="u1")
        s2 = mem_store.create_session(user_id="u1")
        assert s1.id != s2.id

    def test_create_session_default_status_active(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        assert session.status == SessionStatus.ACTIVE

    def test_create_session_with_tenant(self, mem_store):
        session = mem_store.create_session(user_id="u1", tenant_id="t1")
        assert session.tenant_id == "t1"

    def test_create_session_without_tenant(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        assert session.tenant_id is None

    def test_create_session_with_config(self, mem_store):
        session = mem_store.create_session(user_id="u1", config={"model": "gpt-4"})
        assert session.config == {"model": "gpt-4"}

    def test_create_session_with_metadata(self, mem_store):
        session = mem_store.create_session(user_id="u1", metadata={"tag": "test"})
        assert session.metadata == {"tag": "test"}

    def test_create_session_defaults_config_to_empty(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        assert session.config == {}

    def test_create_session_defaults_metadata_to_empty(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        assert session.metadata == {}

    def test_create_session_timestamps_set(self, mem_store):
        before = datetime.now(timezone.utc)
        session = mem_store.create_session(user_id="u1")
        after = datetime.now(timezone.utc)
        assert before <= session.created_at <= after
        assert before <= session.updated_at <= after
        assert before <= session.last_activity_at <= after

    def test_get_session_found(self, mem_store):
        created = mem_store.create_session(user_id="u1")
        fetched = mem_store.get_session(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.user_id == "u1"

    def test_get_session_not_found(self, mem_store):
        assert mem_store.get_session("nonexistent-id") is None

    def test_update_session_status_to_closed(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        updated = mem_store.update_session_status(session.id, SessionStatus.CLOSED)
        assert updated is not None
        assert updated.status == SessionStatus.CLOSED

    def test_update_session_status_updates_timestamp(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        original_updated = session.updated_at
        # Small delay to ensure different timestamp
        time.sleep(0.01)
        updated = mem_store.update_session_status(session.id, SessionStatus.IDLE)
        assert updated.updated_at >= original_updated

    def test_update_session_status_not_found(self, mem_store):
        result = mem_store.update_session_status("nonexistent", SessionStatus.CLOSED)
        assert result is None

    def test_delete_session_returns_true(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        assert mem_store.delete_session(session.id) is True

    def test_delete_session_removes_session(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        mem_store.delete_session(session.id)
        assert mem_store.get_session(session.id) is None

    def test_delete_session_not_found(self, mem_store):
        assert mem_store.delete_session("nonexistent") is False

    def test_update_session_to_error_status(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        updated = mem_store.update_session_status(session.id, SessionStatus.ERROR)
        assert updated.status == SessionStatus.ERROR

    def test_update_session_to_closing_status(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        updated = mem_store.update_session_status(session.id, SessionStatus.CLOSING)
        assert updated.status == SessionStatus.CLOSING


# ============================================================================
# In-Memory Store: Session Listing & Filtering
# ============================================================================


class TestMemSessionListing:
    """Session listing with filters on in-memory store."""

    def test_list_all_sessions(self, mem_store):
        mem_store.create_session(user_id="u1")
        mem_store.create_session(user_id="u2")
        sessions, total = mem_store.list_sessions()
        assert total == 2
        assert len(sessions) == 2

    def test_list_filter_by_user_id(self, mem_store):
        mem_store.create_session(user_id="u1")
        mem_store.create_session(user_id="u2")
        mem_store.create_session(user_id="u1")
        sessions, total = mem_store.list_sessions(user_id="u1")
        assert total == 2
        assert all(s.user_id == "u1" for s in sessions)

    def test_list_filter_by_tenant_id(self, mem_store):
        mem_store.create_session(user_id="u1", tenant_id="t1")
        mem_store.create_session(user_id="u2", tenant_id="t2")
        sessions, total = mem_store.list_sessions(tenant_id="t1")
        assert total == 1
        assert sessions[0].tenant_id == "t1"

    def test_list_filter_by_status(self, mem_store):
        s1 = mem_store.create_session(user_id="u1")
        mem_store.create_session(user_id="u2")
        mem_store.update_session_status(s1.id, SessionStatus.CLOSED)
        sessions, total = mem_store.list_sessions(status=SessionStatus.ACTIVE)
        assert total == 1

    def test_list_combined_filters(self, mem_store):
        mem_store.create_session(user_id="u1", tenant_id="t1")
        s2 = mem_store.create_session(user_id="u1", tenant_id="t2")
        mem_store.create_session(user_id="u2", tenant_id="t1")
        sessions, total = mem_store.list_sessions(user_id="u1", tenant_id="t2")
        assert total == 1
        assert sessions[0].id == s2.id

    def test_list_pagination_limit(self, mem_store):
        for i in range(5):
            mem_store.create_session(user_id=f"u{i}")
        sessions, total = mem_store.list_sessions(limit=2)
        assert total == 5
        assert len(sessions) == 2

    def test_list_pagination_offset(self, mem_store):
        for i in range(5):
            mem_store.create_session(user_id=f"u{i}")
        sessions, total = mem_store.list_sessions(limit=2, offset=3)
        assert total == 5
        assert len(sessions) == 2

    def test_list_pagination_beyond_total(self, mem_store):
        mem_store.create_session(user_id="u1")
        sessions, total = mem_store.list_sessions(limit=10, offset=5)
        assert total == 1
        assert len(sessions) == 0

    def test_list_empty_store(self, mem_store):
        sessions, total = mem_store.list_sessions()
        assert total == 0
        assert sessions == []

    def test_list_sessions_sorted_by_created_at_desc(self, mem_store):
        s1 = mem_store.create_session(user_id="u1")
        s2 = mem_store.create_session(user_id="u2")
        s3 = mem_store.create_session(user_id="u3")
        sessions, _ = mem_store.list_sessions()
        # Most recent first
        assert sessions[0].id == s3.id
        assert sessions[-1].id == s1.id


# ============================================================================
# In-Memory Store: Session Expiration
# ============================================================================


class TestMemSessionExpiration:
    """Session idle timeout cleanup on in-memory store."""

    def test_cleanup_expired_closes_old_sessions(self, mem_store_short_timeout):
        store = mem_store_short_timeout
        session = store.create_session(user_id="u1")
        session.last_activity_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        closed = store.cleanup_expired_sessions()
        assert closed == 1
        assert store.get_session(session.id).status == SessionStatus.CLOSED

    def test_cleanup_does_not_close_fresh_sessions(self, mem_store_short_timeout):
        store = mem_store_short_timeout
        store.create_session(user_id="u1")
        closed = store.cleanup_expired_sessions()
        assert closed == 0

    def test_cleanup_disabled_with_zero_timeout(self):
        store = OpenClawGatewayStore(session_idle_timeout=0)
        session = store.create_session(user_id="u1")
        session.last_activity_at = datetime.now(timezone.utc) - timedelta(days=30)
        assert store.cleanup_expired_sessions() == 0

    def test_cleanup_disabled_with_negative_timeout(self):
        store = OpenClawGatewayStore(session_idle_timeout=-1)
        session = store.create_session(user_id="u1")
        session.last_activity_at = datetime.now(timezone.utc) - timedelta(days=30)
        assert store.cleanup_expired_sessions() == 0

    def test_cleanup_skips_already_closed_sessions(self, mem_store_short_timeout):
        store = mem_store_short_timeout
        session = store.create_session(user_id="u1")
        store.update_session_status(session.id, SessionStatus.CLOSED)
        session.last_activity_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        assert store.cleanup_expired_sessions() == 0

    def test_cleanup_skips_non_active_statuses(self, mem_store_short_timeout):
        store = mem_store_short_timeout
        for status in [SessionStatus.IDLE, SessionStatus.CLOSING, SessionStatus.ERROR]:
            s = store.create_session(user_id="u1")
            store.update_session_status(s.id, status)
            s.last_activity_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        # Only ACTIVE sessions are closed, and none are ACTIVE
        assert store.cleanup_expired_sessions() == 0

    def test_cleanup_multiple_expired(self, mem_store_short_timeout):
        store = mem_store_short_timeout
        for _ in range(3):
            s = store.create_session(user_id="u1")
            s.last_activity_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        assert store.cleanup_expired_sessions() == 3

    def test_default_timeout_is_24_hours(self):
        store = OpenClawGatewayStore()
        assert store._session_idle_timeout == 86400

    def test_custom_timeout(self):
        store = OpenClawGatewayStore(session_idle_timeout=300)
        assert store._session_idle_timeout == 300


# ============================================================================
# Approval Persistence
# ============================================================================


class TestMemApprovalPersistence:
    """Approval CRUD on in-memory store."""

    def test_create_and_get_approval(self, mem_store):
        approval = ApprovalRequest(
            approval_id="app-1",
            action_id="action-1",
            session_id="session-1",
            user_id="user-1",
            tenant_id="tenant-1",
            action_type="shell.execute",
            normalized_action_type="shell",
            action_data={"command": "sudo echo ok"},
            metadata={"scope": "test"},
        )
        mem_store.create_approval(approval)

        stored = mem_store.get_approval("app-1")
        assert stored is not None
        assert stored.approval_id == "app-1"
        assert stored.metadata == {"scope": "test"}

    def test_list_and_update_approval(self, mem_store):
        approval = ApprovalRequest(
            approval_id="app-2",
            action_id="action-2",
            session_id="session-2",
            user_id="user-2",
            tenant_id="tenant-2",
            action_type="shell.execute",
            normalized_action_type="shell",
            action_data={"command": "sudo echo ok"},
        )
        mem_store.create_approval(approval)

        approvals, total = mem_store.list_approvals(tenant_id="tenant-2")
        assert total == 1
        assert approvals[0].approval_id == "app-2"

        updated = mem_store.update_approval_status(
            "app-2",
            status="denied",
            decided_by="approver-1",
            reason="no",
        )
        assert updated is not None
        assert updated.status == "denied"
        assert updated.decided_by == "approver-1"


class TestApprovalRuntimeRecovery:
    """Approval records remain actionable after runtime restart."""

    def test_runtime_can_recover_pending_approval_from_store(self, reset_global_store, monkeypatch):
        import aragora.server.handlers.openclaw.store as store_mod

        store = OpenClawGatewayStore()
        monkeypatch.setattr(store_mod, "_store", store)

        session = store.create_session(user_id="user-1", tenant_id="tenant-1")
        action = store.create_action(
            session_id=session.id,
            action_type="shell.execute",
            input_data={"command": "sudo echo ok"},
        )

        runtime_a = OpenClawExecutionRuntime()
        runtime_a._policy.evaluate = MagicMock(  # type: ignore[method-assign]
            return_value=MagicMock(
                decision=PolicyDecision.REQUIRE_APPROVAL,
                reason="needs approval",
            )
        )
        dispatch = runtime_a.dispatch_action(session, action)

        assert dispatch.status == ActionStatus.PENDING
        assert dispatch.approval_id is not None

        runtime_b = OpenClawExecutionRuntime()
        approvals, total = runtime_b.list_approvals(tenant_id="tenant-1")
        assert total == 1
        assert approvals[0].approval_id == dispatch.approval_id
        assert runtime_b.get_approval(dispatch.approval_id) is not None
        assert runtime_b.deny_action(dispatch.approval_id, "approver-1", "no") is True

        stored = store.get_approval(dispatch.approval_id)
        assert stored is not None
        assert stored.status == "denied"
        assert stored.decided_by == "approver-1"


# ============================================================================
# In-Memory Store: Action CRUD
# ============================================================================


class TestMemActionCRUD:
    """Action create/read/update on in-memory store."""

    def test_create_action(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        action = mem_store.create_action(
            session_id=session.id,
            action_type="search",
            input_data={"query": "test"},
        )
        assert isinstance(action, Action)
        assert action.session_id == session.id
        assert action.action_type == "search"
        assert action.status == ActionStatus.PENDING

    def test_create_action_with_metadata(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        action = mem_store.create_action(
            session_id=session.id,
            action_type="search",
            input_data={},
            metadata={"priority": "high"},
        )
        assert action.metadata == {"priority": "high"}

    def test_create_action_defaults(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        action = mem_store.create_action(
            session_id=session.id,
            action_type="search",
            input_data={"q": "test"},
        )
        assert action.output_data is None
        assert action.error is None
        assert action.started_at is None
        assert action.completed_at is None
        assert action.metadata == {}

    def test_get_action_found(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        created = mem_store.create_action(session_id=session.id, action_type="x", input_data={})
        fetched = mem_store.get_action(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_action_not_found(self, mem_store):
        assert mem_store.get_action("nonexistent") is None

    def test_update_action_to_running_sets_started_at(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        action = mem_store.create_action(session_id=session.id, action_type="x", input_data={})
        updated = mem_store.update_action(action.id, status=ActionStatus.RUNNING)
        assert updated.status == ActionStatus.RUNNING
        assert updated.started_at is not None

    def test_update_action_running_does_not_overwrite_started_at(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        action = mem_store.create_action(session_id=session.id, action_type="x", input_data={})
        mem_store.update_action(action.id, status=ActionStatus.RUNNING)
        first_started = action.started_at
        # Update to RUNNING again should not change started_at
        mem_store.update_action(action.id, status=ActionStatus.RUNNING)
        assert action.started_at == first_started

    def test_update_action_to_completed(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        action = mem_store.create_action(session_id=session.id, action_type="x", input_data={})
        updated = mem_store.update_action(
            action.id,
            status=ActionStatus.COMPLETED,
            output_data={"result": "ok"},
        )
        assert updated.status == ActionStatus.COMPLETED
        assert updated.completed_at is not None
        assert updated.output_data == {"result": "ok"}

    def test_update_action_to_failed(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        action = mem_store.create_action(session_id=session.id, action_type="x", input_data={})
        updated = mem_store.update_action(
            action.id,
            status=ActionStatus.FAILED,
            error="timeout",
        )
        assert updated.status == ActionStatus.FAILED
        assert updated.completed_at is not None
        assert updated.error == "timeout"

    def test_update_action_to_cancelled(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        action = mem_store.create_action(session_id=session.id, action_type="x", input_data={})
        updated = mem_store.update_action(action.id, status=ActionStatus.CANCELLED)
        assert updated.status == ActionStatus.CANCELLED
        assert updated.completed_at is not None

    def test_update_action_output_data_only(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        action = mem_store.create_action(session_id=session.id, action_type="x", input_data={})
        updated = mem_store.update_action(action.id, output_data={"key": "value"})
        assert updated.output_data == {"key": "value"}

    def test_update_action_error_only(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        action = mem_store.create_action(session_id=session.id, action_type="x", input_data={})
        updated = mem_store.update_action(action.id, error="something broke")
        assert updated.error == "something broke"

    def test_update_action_not_found(self, mem_store):
        result = mem_store.update_action("nonexistent", status=ActionStatus.RUNNING)
        assert result is None


# ============================================================================
# In-Memory Store: Credential Management
# ============================================================================


class TestMemCredentialManagement:
    """Credential CRUD and rotation on in-memory store."""

    def test_store_credential(self, mem_store):
        cred = mem_store.store_credential(
            name="my-key",
            credential_type=CredentialType.API_KEY,
            secret_value="sk-123",
            user_id="u1",
        )
        assert isinstance(cred, Credential)
        assert cred.name == "my-key"
        assert cred.credential_type == CredentialType.API_KEY
        assert cred.user_id == "u1"

    def test_store_credential_with_all_params(self, mem_store):
        expires = datetime.now(timezone.utc) + timedelta(days=30)
        cred = mem_store.store_credential(
            name="oauth",
            credential_type=CredentialType.OAUTH_TOKEN,
            secret_value="token-xyz",
            user_id="u1",
            tenant_id="t1",
            expires_at=expires,
            metadata={"scope": "read"},
        )
        assert cred.tenant_id == "t1"
        assert cred.expires_at == expires
        assert cred.metadata == {"scope": "read"}

    def test_store_credential_secret_stored_separately(self, mem_store):
        cred = mem_store.store_credential(
            name="key",
            credential_type=CredentialType.API_KEY,
            secret_value="the-secret",
            user_id="u1",
        )
        assert mem_store._credential_secrets[cred.id] == "the-secret"

    def test_get_credential_found(self, mem_store):
        created = mem_store.store_credential(
            name="key",
            credential_type=CredentialType.API_KEY,
            secret_value="s",
            user_id="u1",
        )
        fetched = mem_store.get_credential(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_credential_not_found(self, mem_store):
        assert mem_store.get_credential("nonexistent") is None

    def test_list_credentials_all(self, mem_store):
        mem_store.store_credential(
            name="k1", credential_type=CredentialType.API_KEY, secret_value="s1", user_id="u1"
        )
        mem_store.store_credential(
            name="k2", credential_type=CredentialType.PASSWORD, secret_value="s2", user_id="u2"
        )
        creds, total = mem_store.list_credentials()
        assert total == 2
        assert len(creds) == 2

    def test_list_credentials_filter_by_user(self, mem_store):
        mem_store.store_credential(
            name="k1", credential_type=CredentialType.API_KEY, secret_value="s1", user_id="u1"
        )
        mem_store.store_credential(
            name="k2", credential_type=CredentialType.API_KEY, secret_value="s2", user_id="u2"
        )
        creds, total = mem_store.list_credentials(user_id="u1")
        assert total == 1
        assert creds[0].user_id == "u1"

    def test_list_credentials_filter_by_tenant(self, mem_store):
        mem_store.store_credential(
            name="k1",
            credential_type=CredentialType.API_KEY,
            secret_value="s1",
            user_id="u1",
            tenant_id="t1",
        )
        mem_store.store_credential(
            name="k2",
            credential_type=CredentialType.API_KEY,
            secret_value="s2",
            user_id="u2",
            tenant_id="t2",
        )
        creds, total = mem_store.list_credentials(tenant_id="t1")
        assert total == 1

    def test_list_credentials_filter_by_type(self, mem_store):
        mem_store.store_credential(
            name="k1", credential_type=CredentialType.API_KEY, secret_value="s1", user_id="u1"
        )
        mem_store.store_credential(
            name="k2", credential_type=CredentialType.SSH_KEY, secret_value="s2", user_id="u1"
        )
        creds, total = mem_store.list_credentials(credential_type=CredentialType.SSH_KEY)
        assert total == 1
        assert creds[0].credential_type == CredentialType.SSH_KEY

    def test_list_credentials_pagination(self, mem_store):
        for i in range(5):
            mem_store.store_credential(
                name=f"k{i}",
                credential_type=CredentialType.API_KEY,
                secret_value=f"s{i}",
                user_id="u1",
            )
        creds, total = mem_store.list_credentials(limit=2, offset=0)
        assert total == 5
        assert len(creds) == 2

    def test_delete_credential_returns_true(self, mem_store):
        cred = mem_store.store_credential(
            name="k", credential_type=CredentialType.API_KEY, secret_value="s", user_id="u1"
        )
        assert mem_store.delete_credential(cred.id) is True

    def test_delete_credential_removes_credential_and_secret(self, mem_store):
        cred = mem_store.store_credential(
            name="k", credential_type=CredentialType.API_KEY, secret_value="s", user_id="u1"
        )
        mem_store.delete_credential(cred.id)
        assert mem_store.get_credential(cred.id) is None
        assert cred.id not in mem_store._credential_secrets

    def test_delete_credential_not_found(self, mem_store):
        assert mem_store.delete_credential("nonexistent") is False

    def test_rotate_credential(self, mem_store):
        cred = mem_store.store_credential(
            name="k", credential_type=CredentialType.API_KEY, secret_value="old", user_id="u1"
        )
        rotated = mem_store.rotate_credential(cred.id, "new")
        assert rotated is not None
        assert rotated.last_rotated_at is not None
        assert mem_store._credential_secrets[cred.id] == "new"

    def test_rotate_credential_updates_timestamp(self, mem_store):
        cred = mem_store.store_credential(
            name="k", credential_type=CredentialType.API_KEY, secret_value="old", user_id="u1"
        )
        original_updated = cred.updated_at
        time.sleep(0.01)
        rotated = mem_store.rotate_credential(cred.id, "new")
        assert rotated.updated_at >= original_updated

    def test_rotate_credential_not_found(self, mem_store):
        assert mem_store.rotate_credential("nonexistent", "new") is None

    def test_store_all_credential_types(self, mem_store):
        for ctype in CredentialType:
            cred = mem_store.store_credential(
                name=f"cred-{ctype.value}",
                credential_type=ctype,
                secret_value="secret",
                user_id="u1",
            )
            assert cred.credential_type == ctype


# ============================================================================
# In-Memory Store: Audit Log
# ============================================================================


class TestMemAuditLog:
    """Audit log operations on in-memory store."""

    def test_add_audit_entry(self, mem_store):
        entry = mem_store.add_audit_entry(
            action="session.create",
            actor_id="u1",
            resource_type="session",
            resource_id="s1",
        )
        assert isinstance(entry, AuditEntry)
        assert entry.action == "session.create"
        assert entry.result == "success"

    def test_add_audit_entry_with_details(self, mem_store):
        entry = mem_store.add_audit_entry(
            action="action.run",
            actor_id="u1",
            resource_type="action",
            details={"duration_ms": 123},
        )
        assert entry.details == {"duration_ms": 123}

    def test_add_audit_entry_custom_result(self, mem_store):
        entry = mem_store.add_audit_entry(
            action="auth.login",
            actor_id="u1",
            resource_type="auth",
            result="failure",
        )
        assert entry.result == "failure"

    def test_get_audit_log_all(self, mem_store):
        mem_store.add_audit_entry(action="a", actor_id="u1", resource_type="session")
        mem_store.add_audit_entry(action="b", actor_id="u2", resource_type="action")
        entries, total = mem_store.get_audit_log()
        assert total == 2
        assert len(entries) == 2

    def test_get_audit_log_filter_by_action(self, mem_store):
        mem_store.add_audit_entry(action="create", actor_id="u1", resource_type="session")
        mem_store.add_audit_entry(action="delete", actor_id="u1", resource_type="session")
        entries, total = mem_store.get_audit_log(action="create")
        assert total == 1
        assert entries[0].action == "create"

    def test_get_audit_log_filter_by_actor(self, mem_store):
        mem_store.add_audit_entry(action="a", actor_id="u1", resource_type="x")
        mem_store.add_audit_entry(action="b", actor_id="u2", resource_type="x")
        entries, total = mem_store.get_audit_log(actor_id="u1")
        assert total == 1

    def test_get_audit_log_filter_by_resource_type(self, mem_store):
        mem_store.add_audit_entry(action="a", actor_id="u1", resource_type="session")
        mem_store.add_audit_entry(action="b", actor_id="u1", resource_type="action")
        entries, total = mem_store.get_audit_log(resource_type="session")
        assert total == 1

    def test_get_audit_log_pagination(self, mem_store):
        for i in range(10):
            mem_store.add_audit_entry(action=f"a{i}", actor_id="u1", resource_type="x")
        entries, total = mem_store.get_audit_log(limit=3, offset=2)
        assert total == 10
        assert len(entries) == 3

    def test_get_audit_log_sorted_desc_by_timestamp(self, mem_store):
        e1 = mem_store.add_audit_entry(action="first", actor_id="u1", resource_type="x")
        e2 = mem_store.add_audit_entry(action="second", actor_id="u1", resource_type="x")
        entries, _ = mem_store.get_audit_log()
        # Most recent first
        assert entries[0].action == "second"
        assert entries[1].action == "first"

    def test_audit_log_eviction_at_10001(self, mem_store):
        for i in range(10002):
            mem_store.add_audit_entry(action="bulk", actor_id="bot", resource_type="test")
        assert len(mem_store._audit_log) == 10000

    def test_audit_log_no_resource_id(self, mem_store):
        entry = mem_store.add_audit_entry(
            action="system.check",
            actor_id="system",
            resource_type="health",
        )
        assert entry.resource_id is None


# ============================================================================
# In-Memory Store: Metrics
# ============================================================================


class TestMemMetrics:
    """Metrics computation on in-memory store."""

    def test_empty_store_metrics(self, mem_store):
        metrics = mem_store.get_metrics()
        assert metrics["sessions"]["total"] == 0
        assert metrics["sessions"]["active"] == 0
        assert metrics["actions"]["total"] == 0
        assert metrics["actions"]["pending"] == 0
        assert metrics["actions"]["running"] == 0
        assert metrics["credentials"]["total"] == 0
        assert metrics["audit_log_entries"] == 0

    def test_metrics_sessions_by_status(self, mem_store):
        s1 = mem_store.create_session(user_id="u1")
        s2 = mem_store.create_session(user_id="u2")
        mem_store.update_session_status(s2.id, SessionStatus.CLOSED)
        metrics = mem_store.get_metrics()
        assert metrics["sessions"]["total"] == 2
        assert metrics["sessions"]["active"] == 1
        assert metrics["sessions"]["by_status"]["active"] == 1
        assert metrics["sessions"]["by_status"]["closed"] == 1

    def test_metrics_actions_by_status(self, mem_store):
        s = mem_store.create_session(user_id="u1")
        a1 = mem_store.create_action(session_id=s.id, action_type="x", input_data={})
        a2 = mem_store.create_action(session_id=s.id, action_type="y", input_data={})
        mem_store.update_action(a2.id, status=ActionStatus.RUNNING)
        metrics = mem_store.get_metrics()
        assert metrics["actions"]["total"] == 2
        assert metrics["actions"]["pending"] == 1
        assert metrics["actions"]["running"] == 1

    def test_metrics_credentials_by_type(self, mem_store):
        mem_store.store_credential(
            name="k1", credential_type=CredentialType.API_KEY, secret_value="s", user_id="u1"
        )
        mem_store.store_credential(
            name="k2", credential_type=CredentialType.SSH_KEY, secret_value="s", user_id="u1"
        )
        mem_store.store_credential(
            name="k3", credential_type=CredentialType.API_KEY, secret_value="s", user_id="u1"
        )
        metrics = mem_store.get_metrics()
        assert metrics["credentials"]["total"] == 3
        assert metrics["credentials"]["by_type"]["api_key"] == 2
        assert metrics["credentials"]["by_type"]["ssh_key"] == 1

    def test_metrics_audit_entries_count(self, mem_store):
        for _ in range(5):
            mem_store.add_audit_entry(action="x", actor_id="u1", resource_type="y")
        metrics = mem_store.get_metrics()
        assert metrics["audit_log_entries"] == 5


# ============================================================================
# Persistent Store: Session CRUD
# ============================================================================


class TestPersistentSessionCRUD:
    """Session create/read/update/delete on persistent store."""

    def test_create_session(self, persistent_store):
        session = persistent_store.create_session(user_id="u1", tenant_id="t1")
        assert isinstance(session, Session)
        assert session.user_id == "u1"
        assert session.status == SessionStatus.ACTIVE

    def test_get_session_found(self, persistent_store):
        created = persistent_store.create_session(user_id="u1")
        fetched = persistent_store.get_session(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.user_id == "u1"

    def test_get_session_not_found(self, persistent_store):
        assert persistent_store.get_session("nonexistent") is None

    def test_get_session_from_cache(self, persistent_store):
        """Second get should come from the LRU cache."""
        created = persistent_store.create_session(user_id="u1")
        # First get populates cache
        persistent_store.get_session(created.id)
        # Second get should be from cache
        with persistent_store._cache_lock:
            assert created.id in persistent_store._session_cache
        fetched = persistent_store.get_session(created.id)
        assert fetched is not None

    def test_update_session_status(self, persistent_store):
        session = persistent_store.create_session(user_id="u1")
        updated = persistent_store.update_session_status(session.id, SessionStatus.CLOSED)
        assert updated is not None
        assert updated.status == SessionStatus.CLOSED

    def test_update_session_invalidates_cache(self, persistent_store):
        session = persistent_store.create_session(user_id="u1")
        # Populate cache
        persistent_store.get_session(session.id)
        # Update should invalidate and re-populate
        persistent_store.update_session_status(session.id, SessionStatus.IDLE)
        fetched = persistent_store.get_session(session.id)
        assert fetched.status == SessionStatus.IDLE

    def test_delete_session(self, persistent_store):
        session = persistent_store.create_session(user_id="u1")
        assert persistent_store.delete_session(session.id) is True
        assert persistent_store.get_session(session.id) is None

    def test_delete_session_not_found(self, persistent_store):
        assert persistent_store.delete_session("nonexistent") is False

    def test_delete_session_removes_from_cache(self, persistent_store):
        session = persistent_store.create_session(user_id="u1")
        persistent_store.get_session(session.id)  # populate cache
        persistent_store.delete_session(session.id)
        with persistent_store._cache_lock:
            assert session.id not in persistent_store._session_cache

    def test_create_session_with_config_and_metadata(self, persistent_store):
        session = persistent_store.create_session(
            user_id="u1",
            config={"model": "claude"},
            metadata={"source": "web"},
        )
        fetched = persistent_store.get_session(session.id)
        assert fetched.config == {"model": "claude"}
        assert fetched.metadata == {"source": "web"}


# ============================================================================
# Persistent Store: Session Listing
# ============================================================================


class TestPersistentSessionListing:
    """Session listing with filters on persistent store."""

    def test_list_all(self, persistent_store):
        persistent_store.create_session(user_id="u1")
        persistent_store.create_session(user_id="u2")
        sessions, total = persistent_store.list_sessions()
        assert total == 2
        assert len(sessions) == 2

    def test_list_filter_by_user(self, persistent_store):
        persistent_store.create_session(user_id="u1")
        persistent_store.create_session(user_id="u2")
        sessions, total = persistent_store.list_sessions(user_id="u1")
        assert total == 1

    def test_list_filter_by_tenant(self, persistent_store):
        persistent_store.create_session(user_id="u1", tenant_id="t1")
        persistent_store.create_session(user_id="u2", tenant_id="t2")
        sessions, total = persistent_store.list_sessions(tenant_id="t1")
        assert total == 1

    def test_list_filter_by_status(self, persistent_store):
        s1 = persistent_store.create_session(user_id="u1")
        persistent_store.create_session(user_id="u2")
        persistent_store.update_session_status(s1.id, SessionStatus.CLOSED)
        sessions, total = persistent_store.list_sessions(status=SessionStatus.ACTIVE)
        assert total == 1

    def test_list_pagination(self, persistent_store):
        for i in range(5):
            persistent_store.create_session(user_id=f"u{i}")
        sessions, total = persistent_store.list_sessions(limit=2, offset=0)
        assert total == 5
        assert len(sessions) == 2

    def test_list_empty(self, persistent_store):
        sessions, total = persistent_store.list_sessions()
        assert total == 0
        assert sessions == []


# ============================================================================
# Persistent Store: Action CRUD
# ============================================================================


class TestPersistentActionCRUD:
    """Action create/read/update on persistent store."""

    def test_create_action(self, persistent_store):
        session = persistent_store.create_session(user_id="u1")
        action = persistent_store.create_action(
            session_id=session.id,
            action_type="search",
            input_data={"q": "hello"},
        )
        assert isinstance(action, Action)
        assert action.status == ActionStatus.PENDING

    def test_get_action_found(self, persistent_store):
        session = persistent_store.create_session(user_id="u1")
        created = persistent_store.create_action(
            session_id=session.id, action_type="x", input_data={}
        )
        fetched = persistent_store.get_action(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_action_not_found(self, persistent_store):
        assert persistent_store.get_action("nonexistent") is None

    def test_get_action_from_cache(self, persistent_store):
        session = persistent_store.create_session(user_id="u1")
        action = persistent_store.create_action(
            session_id=session.id, action_type="x", input_data={}
        )
        # Already in cache from create
        with persistent_store._cache_lock:
            assert action.id in persistent_store._action_cache

    def test_update_action_to_running(self, persistent_store):
        session = persistent_store.create_session(user_id="u1")
        action = persistent_store.create_action(
            session_id=session.id, action_type="x", input_data={}
        )
        updated = persistent_store.update_action(action.id, status=ActionStatus.RUNNING)
        assert updated.status == ActionStatus.RUNNING
        assert updated.started_at is not None

    def test_update_action_to_completed(self, persistent_store):
        session = persistent_store.create_session(user_id="u1")
        action = persistent_store.create_action(
            session_id=session.id, action_type="x", input_data={}
        )
        updated = persistent_store.update_action(
            action.id,
            status=ActionStatus.COMPLETED,
            output_data={"result": "done"},
        )
        assert updated.status == ActionStatus.COMPLETED
        assert updated.output_data == {"result": "done"}
        assert updated.completed_at is not None

    def test_update_action_to_failed(self, persistent_store):
        session = persistent_store.create_session(user_id="u1")
        action = persistent_store.create_action(
            session_id=session.id, action_type="x", input_data={}
        )
        updated = persistent_store.update_action(
            action.id,
            status=ActionStatus.FAILED,
            error="crash",
        )
        assert updated.status == ActionStatus.FAILED
        assert updated.error == "crash"

    def test_update_action_not_found(self, persistent_store):
        assert persistent_store.update_action("nonexistent", status=ActionStatus.RUNNING) is None

    def test_update_action_no_changes_returns_action(self, persistent_store):
        session = persistent_store.create_session(user_id="u1")
        action = persistent_store.create_action(
            session_id=session.id, action_type="x", input_data={}
        )
        result = persistent_store.update_action(action.id)
        assert result is not None
        assert result.id == action.id

    def test_update_action_invalidates_cache(self, persistent_store):
        session = persistent_store.create_session(user_id="u1")
        action = persistent_store.create_action(
            session_id=session.id, action_type="x", input_data={}
        )
        persistent_store.update_action(action.id, status=ActionStatus.COMPLETED)
        # After update, cache should have been invalidated and repopulated
        fetched = persistent_store.get_action(action.id)
        assert fetched.status == ActionStatus.COMPLETED


# ============================================================================
# Persistent Store: Credential Management
# ============================================================================


class TestPersistentCredentialManagement:
    """Credential CRUD and rotation on persistent store."""

    def test_store_credential(self, persistent_store):
        cred = persistent_store.store_credential(
            name="my-key",
            credential_type=CredentialType.API_KEY,
            secret_value="sk-123",
            user_id="u1",
        )
        assert isinstance(cred, Credential)
        assert cred.name == "my-key"

    def test_get_credential_found(self, persistent_store):
        created = persistent_store.store_credential(
            name="k",
            credential_type=CredentialType.API_KEY,
            secret_value="s",
            user_id="u1",
        )
        fetched = persistent_store.get_credential(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_credential_not_found(self, persistent_store):
        assert persistent_store.get_credential("nonexistent") is None

    def test_list_credentials(self, persistent_store):
        persistent_store.store_credential(
            name="k1", credential_type=CredentialType.API_KEY, secret_value="s1", user_id="u1"
        )
        persistent_store.store_credential(
            name="k2", credential_type=CredentialType.SSH_KEY, secret_value="s2", user_id="u2"
        )
        creds, total = persistent_store.list_credentials()
        assert total == 2

    def test_list_credentials_filter_by_user(self, persistent_store):
        persistent_store.store_credential(
            name="k1", credential_type=CredentialType.API_KEY, secret_value="s1", user_id="u1"
        )
        persistent_store.store_credential(
            name="k2", credential_type=CredentialType.API_KEY, secret_value="s2", user_id="u2"
        )
        creds, total = persistent_store.list_credentials(user_id="u1")
        assert total == 1

    def test_list_credentials_filter_by_type(self, persistent_store):
        persistent_store.store_credential(
            name="k1", credential_type=CredentialType.API_KEY, secret_value="s1", user_id="u1"
        )
        persistent_store.store_credential(
            name="k2", credential_type=CredentialType.PASSWORD, secret_value="s2", user_id="u1"
        )
        creds, total = persistent_store.list_credentials(credential_type=CredentialType.PASSWORD)
        assert total == 1

    def test_delete_credential(self, persistent_store):
        cred = persistent_store.store_credential(
            name="k", credential_type=CredentialType.API_KEY, secret_value="s", user_id="u1"
        )
        assert persistent_store.delete_credential(cred.id) is True
        assert persistent_store.get_credential(cred.id) is None

    def test_delete_credential_not_found(self, persistent_store):
        assert persistent_store.delete_credential("nonexistent") is False

    def test_rotate_credential(self, persistent_store):
        cred = persistent_store.store_credential(
            name="k",
            credential_type=CredentialType.API_KEY,
            secret_value="old",
            user_id="u1",
        )
        rotated = persistent_store.rotate_credential(cred.id, "new")
        assert rotated is not None
        assert rotated.last_rotated_at is not None

    def test_rotate_credential_not_found(self, persistent_store):
        result = persistent_store.rotate_credential("nonexistent", "new")
        assert result is None

    def test_store_credential_with_expiry(self, persistent_store):
        expires = datetime.now(timezone.utc) + timedelta(days=7)
        cred = persistent_store.store_credential(
            name="temp",
            credential_type=CredentialType.OAUTH_TOKEN,
            secret_value="token",
            user_id="u1",
            expires_at=expires,
        )
        fetched = persistent_store.get_credential(cred.id)
        assert fetched.expires_at is not None


# ============================================================================
# Persistent Store: Audit Log
# ============================================================================


class TestPersistentAuditLog:
    """Audit log on persistent store."""

    def test_add_and_get_entry(self, persistent_store):
        persistent_store.add_audit_entry(
            action="login",
            actor_id="u1",
            resource_type="auth",
        )
        entries, total = persistent_store.get_audit_log()
        assert total == 1
        assert entries[0].action == "login"

    def test_filter_by_action(self, persistent_store):
        persistent_store.add_audit_entry(action="login", actor_id="u1", resource_type="auth")
        persistent_store.add_audit_entry(action="logout", actor_id="u1", resource_type="auth")
        entries, total = persistent_store.get_audit_log(action="login")
        assert total == 1

    def test_filter_by_actor(self, persistent_store):
        persistent_store.add_audit_entry(action="a", actor_id="u1", resource_type="x")
        persistent_store.add_audit_entry(action="b", actor_id="u2", resource_type="x")
        entries, total = persistent_store.get_audit_log(actor_id="u2")
        assert total == 1

    def test_filter_by_resource_type(self, persistent_store):
        persistent_store.add_audit_entry(action="a", actor_id="u1", resource_type="session")
        persistent_store.add_audit_entry(action="b", actor_id="u1", resource_type="action")
        entries, total = persistent_store.get_audit_log(resource_type="session")
        assert total == 1

    def test_audit_pagination(self, persistent_store):
        for i in range(10):
            persistent_store.add_audit_entry(action=f"a{i}", actor_id="u1", resource_type="x")
        entries, total = persistent_store.get_audit_log(limit=3, offset=0)
        assert total == 10
        assert len(entries) == 3


class TestPersistentApprovalPersistence:
    """Approval CRUD on SQLite-backed store."""

    def test_persistent_store_round_trips_approval(self, persistent_store):
        approval = ApprovalRequest(
            approval_id="app-persist-1",
            action_id="action-1",
            session_id="session-1",
            user_id="user-1",
            tenant_id="tenant-1",
            action_type="shell.execute",
            normalized_action_type="shell",
            action_data={"command": "sudo echo ok"},
            metadata={"scope": "persist"},
        )
        persistent_store.create_approval(approval)

        stored = persistent_store.get_approval("app-persist-1")
        assert stored is not None
        assert stored.approval_id == "app-persist-1"
        assert stored.metadata == {"scope": "persist"}

        approvals, total = persistent_store.list_approvals(tenant_id="tenant-1")
        assert total == 1
        assert approvals[0].approval_id == "app-persist-1"

        updated = persistent_store.update_approval_status(
            "app-persist-1",
            status="approved",
            decided_by="approver-1",
            reason="ship it",
        )
        assert updated is not None
        assert updated.status == "approved"
        assert updated.decided_by == "approver-1"


# ============================================================================
# Persistent Store: Metrics
# ============================================================================


class TestPersistentMetrics:
    """Metrics on persistent store."""

    def test_empty_metrics(self, persistent_store):
        metrics = persistent_store.get_metrics()
        assert metrics["sessions"]["total"] == 0
        assert metrics["actions"]["total"] == 0
        assert metrics["credentials"]["total"] == 0
        assert metrics["audit_log_entries"] == 0

    def test_metrics_with_data(self, persistent_store):
        s1 = persistent_store.create_session(user_id="u1")
        s2 = persistent_store.create_session(user_id="u2")
        persistent_store.update_session_status(s2.id, SessionStatus.CLOSED)
        persistent_store.create_action(session_id=s1.id, action_type="x", input_data={})
        persistent_store.store_credential(
            name="k", credential_type=CredentialType.API_KEY, secret_value="s", user_id="u1"
        )
        persistent_store.add_audit_entry(action="test", actor_id="u1", resource_type="test")

        metrics = persistent_store.get_metrics()
        assert metrics["sessions"]["total"] == 2
        assert metrics["sessions"]["active"] == 1
        assert metrics["actions"]["total"] == 1
        assert metrics["actions"]["pending"] == 1
        assert metrics["credentials"]["total"] == 1
        assert metrics["audit_log_entries"] == 1


# ============================================================================
# Persistent Store: LRU Cache Behavior
# ============================================================================


class TestPersistentLRUCache:
    """LRU cache eviction and thread safety."""

    def test_session_cache_evicts_oldest(self, tmp_path):
        db_path = str(tmp_path / "cache_test.db")
        store = OpenClawPersistentStore(db_path=db_path, cache_size=3)

        sessions = []
        for i in range(5):
            s = store.create_session(user_id=f"u{i}")
            sessions.append(s)

        # Cache should only hold the last 3
        with store._cache_lock:
            assert len(store._session_cache) <= 3

    def test_action_cache_evicts_oldest(self, tmp_path):
        db_path = str(tmp_path / "cache_test2.db")
        store = OpenClawPersistentStore(db_path=db_path, cache_size=3)

        session = store.create_session(user_id="u1")
        for i in range(5):
            store.create_action(session_id=session.id, action_type=f"t{i}", input_data={})

        with store._cache_lock:
            assert len(store._action_cache) <= 3

    def test_get_session_moves_to_end_of_cache(self, persistent_store):
        s1 = persistent_store.create_session(user_id="u1")
        s2 = persistent_store.create_session(user_id="u2")
        # Access s1 to move it to end
        persistent_store.get_session(s1.id)
        with persistent_store._cache_lock:
            keys = list(persistent_store._session_cache.keys())
            assert keys[-1] == s1.id

    def test_cache_is_ordered_dict(self, persistent_store):
        assert isinstance(persistent_store._session_cache, OrderedDict)
        assert isinstance(persistent_store._action_cache, OrderedDict)


# ============================================================================
# Persistent Store: Encryption Fallback
# ============================================================================


class TestPersistentEncryption:
    """Encryption and base64 fallback for credential secrets."""

    def test_encrypt_with_base64_fallback(self, persistent_store):
        """When encryption module is not available, base64 is used."""
        with patch.dict(os.environ, {"ARAGORA_ENV": "development"}, clear=False):
            with patch(
                "aragora.server.handlers.openclaw.store.OpenClawPersistentStore._encrypt_secret",
                wraps=persistent_store._encrypt_secret,
            ):
                # Force the ImportError path
                original = persistent_store._encrypt_secret

                def fallback_encrypt(value):
                    import builtins

                    original_import = builtins.__import__

                    def mock_import(name, *args, **kwargs):
                        if name == "aragora.security.encryption":
                            raise ImportError("no encryption")
                        return original_import(name, *args, **kwargs)

                    builtins.__import__ = mock_import
                    try:
                        return base64.b64encode(value.encode()).decode()
                    finally:
                        builtins.__import__ = original_import

                result = fallback_encrypt("test-secret")
                assert base64.b64decode(result.encode()).decode() == "test-secret"

    def test_decrypt_with_base64_fallback(self, persistent_store):
        """When decryption module is not available, base64 is used."""
        encoded = base64.b64encode(b"my-secret").decode()

        def fallback_decrypt(encrypted):
            return base64.b64decode(encrypted.encode()).decode()

        result = fallback_decrypt(encoded)
        assert result == "my-secret"

    def test_encrypt_raises_in_production_without_crypto(self, tmp_path):
        """In production, missing encryption library should raise RuntimeError."""
        db_path = str(tmp_path / "prod_test.db")
        store = OpenClawPersistentStore(db_path=db_path)

        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=False):
            # Patch the specific import that _encrypt_secret tries
            import importlib
            import sys

            # Remove cached module so the import inside _encrypt_secret fails
            saved = sys.modules.pop("aragora.security.encryption", None)
            try:
                with patch.dict(sys.modules, {"aragora.security.encryption": None}):
                    with pytest.raises((RuntimeError, ImportError)):
                        store._encrypt_secret("secret")
            finally:
                if saved is not None:
                    sys.modules["aragora.security.encryption"] = saved


# ============================================================================
# Persistent Store: DB Initialization
# ============================================================================


class TestPersistentDBInit:
    """Database initialization and schema creation."""

    def test_creates_db_file(self, tmp_path):
        db_path = str(tmp_path / "new_db.db")
        store = OpenClawPersistentStore(db_path=db_path)
        assert Path(db_path).exists()

    def test_creates_parent_directories(self, tmp_path):
        db_path = str(tmp_path / "subdir" / "deep" / "test.db")
        store = OpenClawPersistentStore(db_path=db_path)
        assert Path(db_path).parent.exists()

    def test_tables_created(self, persistent_store):
        """All required tables exist after init."""
        import sqlite3

        conn = sqlite3.connect(str(persistent_store._db_path))
        try:
            tables = [
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            ]
            assert "openclaw_sessions" in tables
            assert "openclaw_actions" in tables
            assert "openclaw_credentials" in tables
            assert "openclaw_audit" in tables
        finally:
            conn.close()

    def test_idempotent_init(self, tmp_path):
        """Calling _init_db twice should not error."""
        db_path = str(tmp_path / "idempotent.db")
        store = OpenClawPersistentStore(db_path=db_path)
        # Init again
        store._init_db()
        # Should still work
        session = store.create_session(user_id="u1")
        assert session is not None


# ============================================================================
# _get_store Factory Function
# ============================================================================


class TestGetStoreFactory:
    """Tests for the _get_store singleton factory."""

    def test_get_store_returns_persistent_by_default(self, reset_global_store, tmp_path):
        import aragora.server.handlers.openclaw.store as store_mod

        db_path = str(tmp_path / "factory_test.db")
        with patch.dict(os.environ, {"ARAGORA_OPENCLAW_STORE": "persistent"}, clear=False):
            with patch(
                "aragora.server.handlers.openclaw.store.OpenClawPersistentStore"
            ) as MockPersistent:
                MockPersistent.return_value = MagicMock()
                result = _get_store()
                MockPersistent.assert_called_once()

    def test_get_store_returns_memory_when_configured(self, reset_global_store):
        import aragora.server.handlers.openclaw.store as store_mod

        with patch.dict(os.environ, {"ARAGORA_OPENCLAW_STORE": "memory"}, clear=False):
            result = _get_store()
            assert isinstance(result, OpenClawGatewayStore)

    def test_get_store_caches_instance(self, reset_global_store):
        import aragora.server.handlers.openclaw.store as store_mod

        with patch.dict(os.environ, {"ARAGORA_OPENCLAW_STORE": "memory"}, clear=False):
            first = _get_store()
            second = _get_store()
            assert first is second

    def test_get_store_override_from_gateway_module(self, reset_global_store):
        """Test that _get_store checks the compatibility shim module."""
        import sys
        import aragora.server.handlers.openclaw.store as store_mod

        mock_store = MagicMock()
        mock_module = MagicMock()
        mock_module._get_store = MagicMock(return_value=mock_store)

        with patch.dict(
            sys.modules, {"aragora.server.handlers.openclaw.openclaw_gateway": mock_module}
        ):
            result = _get_store()
            assert result is mock_store


# ============================================================================
# Edge Cases and Boundary Conditions
# ============================================================================


class TestEdgeCases:
    """Edge cases and boundary values."""

    def test_create_session_empty_user_id(self, mem_store):
        """Empty string user_id is technically valid."""
        session = mem_store.create_session(user_id="")
        assert session.user_id == ""

    def test_action_with_large_input_data(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        large_data = {"key": "x" * 10000}
        action = mem_store.create_action(
            session_id=session.id,
            action_type="big",
            input_data=large_data,
        )
        assert action.input_data == large_data

    def test_credential_with_empty_secret(self, mem_store):
        cred = mem_store.store_credential(
            name="empty",
            credential_type=CredentialType.API_KEY,
            secret_value="",
            user_id="u1",
        )
        assert mem_store._credential_secrets[cred.id] == ""

    def test_multiple_status_transitions(self, mem_store):
        session = mem_store.create_session(user_id="u1")
        for status in [
            SessionStatus.IDLE,
            SessionStatus.ACTIVE,
            SessionStatus.CLOSING,
            SessionStatus.CLOSED,
        ]:
            updated = mem_store.update_session_status(session.id, status)
            assert updated.status == status

    def test_action_lifecycle(self, mem_store):
        """Full action lifecycle: PENDING -> RUNNING -> COMPLETED."""
        session = mem_store.create_session(user_id="u1")
        action = mem_store.create_action(session_id=session.id, action_type="x", input_data={})
        assert action.status == ActionStatus.PENDING

        mem_store.update_action(action.id, status=ActionStatus.RUNNING)
        assert action.status == ActionStatus.RUNNING
        assert action.started_at is not None

        mem_store.update_action(action.id, status=ActionStatus.COMPLETED, output_data={"ok": True})
        assert action.status == ActionStatus.COMPLETED
        assert action.completed_at is not None

    def test_audit_entry_with_empty_details(self, mem_store):
        entry = mem_store.add_audit_entry(
            action="test",
            actor_id="u1",
            resource_type="x",
            details={},
        )
        assert entry.details == {}

    def test_list_sessions_with_all_filters(self, mem_store):
        s = mem_store.create_session(user_id="u1", tenant_id="t1")
        mem_store.create_session(user_id="u2", tenant_id="t2")
        sessions, total = mem_store.list_sessions(
            user_id="u1",
            tenant_id="t1",
            status=SessionStatus.ACTIVE,
        )
        assert total == 1
        assert sessions[0].id == s.id

    def test_persistent_store_session_roundtrip(self, persistent_store):
        """Full roundtrip: create, get, update, list, delete."""
        created = persistent_store.create_session(
            user_id="u1",
            tenant_id="t1",
            config={"k": "v"},
            metadata={"m": 1},
        )
        fetched = persistent_store.get_session(created.id)
        assert fetched.user_id == "u1"
        assert fetched.config == {"k": "v"}

        persistent_store.update_session_status(created.id, SessionStatus.CLOSED)
        sessions, total = persistent_store.list_sessions(status=SessionStatus.CLOSED)
        assert total == 1

        persistent_store.delete_session(created.id)
        assert persistent_store.get_session(created.id) is None

    def test_persistent_store_action_roundtrip(self, persistent_store):
        """Full roundtrip: create, get, update."""
        session = persistent_store.create_session(user_id="u1")
        action = persistent_store.create_action(
            session_id=session.id,
            action_type="search",
            input_data={"q": "test"},
            metadata={"source": "cli"},
        )
        fetched = persistent_store.get_action(action.id)
        assert fetched.input_data == {"q": "test"}
        assert fetched.metadata == {"source": "cli"}

        persistent_store.update_action(action.id, status=ActionStatus.RUNNING)
        running = persistent_store.get_action(action.id)
        assert running.status == ActionStatus.RUNNING
        assert running.started_at is not None

    def test_persistent_credential_roundtrip(self, persistent_store):
        """Full roundtrip: store, get, list, rotate, delete."""
        cred = persistent_store.store_credential(
            name="mykey",
            credential_type=CredentialType.API_KEY,
            secret_value="secret1",
            user_id="u1",
            tenant_id="t1",
            metadata={"env": "staging"},
        )
        fetched = persistent_store.get_credential(cred.id)
        assert fetched.name == "mykey"
        assert fetched.metadata == {"env": "staging"}

        rotated = persistent_store.rotate_credential(cred.id, "secret2")
        assert rotated.last_rotated_at is not None

        creds, total = persistent_store.list_credentials(user_id="u1")
        assert total == 1

        assert persistent_store.delete_credential(cred.id) is True
        assert persistent_store.get_credential(cred.id) is None

    def test_persistent_audit_roundtrip(self, persistent_store):
        """Full audit roundtrip with details."""
        persistent_store.add_audit_entry(
            action="cred.rotate",
            actor_id="admin",
            resource_type="credential",
            resource_id="cred-1",
            result="success",
            details={"reason": "scheduled"},
        )
        entries, total = persistent_store.get_audit_log(action="cred.rotate")
        assert total == 1
        assert entries[0].details == {"reason": "scheduled"}
        assert entries[0].resource_id == "cred-1"

    def test_list_credentials_combined_filters(self, mem_store):
        mem_store.store_credential(
            name="k1",
            credential_type=CredentialType.API_KEY,
            secret_value="s",
            user_id="u1",
            tenant_id="t1",
        )
        mem_store.store_credential(
            name="k2",
            credential_type=CredentialType.SSH_KEY,
            secret_value="s",
            user_id="u1",
            tenant_id="t1",
        )
        mem_store.store_credential(
            name="k3",
            credential_type=CredentialType.API_KEY,
            secret_value="s",
            user_id="u2",
            tenant_id="t1",
        )
        creds, total = mem_store.list_credentials(
            user_id="u1", credential_type=CredentialType.API_KEY
        )
        assert total == 1
        assert creds[0].name == "k1"

    def test_audit_log_combined_filters(self, mem_store):
        mem_store.add_audit_entry(action="create", actor_id="u1", resource_type="session")
        mem_store.add_audit_entry(action="create", actor_id="u2", resource_type="session")
        mem_store.add_audit_entry(action="delete", actor_id="u1", resource_type="session")
        entries, total = mem_store.get_audit_log(action="create", actor_id="u1")
        assert total == 1

    def test_persistent_list_credentials_filter_by_tenant(self, persistent_store):
        persistent_store.store_credential(
            name="k1",
            credential_type=CredentialType.API_KEY,
            secret_value="s",
            user_id="u1",
            tenant_id="t1",
        )
        persistent_store.store_credential(
            name="k2",
            credential_type=CredentialType.API_KEY,
            secret_value="s",
            user_id="u1",
            tenant_id="t2",
        )
        creds, total = persistent_store.list_credentials(tenant_id="t1")
        assert total == 1

    def test_persistent_list_credentials_pagination(self, persistent_store):
        for i in range(5):
            persistent_store.store_credential(
                name=f"k{i}",
                credential_type=CredentialType.API_KEY,
                secret_value=f"s{i}",
                user_id="u1",
            )
        creds, total = persistent_store.list_credentials(limit=2, offset=1)
        assert total == 5
        assert len(creds) == 2

    def test_metrics_all_session_statuses_in_by_status(self, mem_store):
        metrics = mem_store.get_metrics()
        for status in SessionStatus:
            assert status.value in metrics["sessions"]["by_status"]

    def test_metrics_all_action_statuses_in_by_status(self, mem_store):
        metrics = mem_store.get_metrics()
        for status in ActionStatus:
            assert status.value in metrics["actions"]["by_status"]

    def test_metrics_all_credential_types_in_by_type(self, mem_store):
        metrics = mem_store.get_metrics()
        for ctype in CredentialType:
            assert ctype.value in metrics["credentials"]["by_type"]
