"""
Tests for OpenClaw Session Orchestration Mixin.

Tests session management and action execution handlers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.base import error_response, json_response
from aragora.server.handlers.openclaw.models import ActionStatus, SessionStatus
from aragora.server.handlers.openclaw.orchestrator import SessionOrchestrationMixin
from aragora.server.handlers.openclaw.runtime import OpenClawExecutionRuntime


class MockStore:
    """Mock store for testing."""

    def __init__(self):
        self.sessions = {}
        self.actions = {}
        self.audit_entries = []

    def list_sessions(self, user_id, tenant_id, status, limit, offset):
        sessions = list(self.sessions.values())
        return sessions[:limit], len(sessions)

    def get_session(self, session_id):
        return self.sessions.get(session_id)

    def create_session(self, user_id, tenant_id, config, metadata):
        session = MagicMock()
        session.id = f"session_{len(self.sessions)}"
        session.user_id = user_id
        session.tenant_id = tenant_id
        session.config = config
        session.metadata = metadata
        session.status = SessionStatus.ACTIVE
        session.to_dict = lambda: {"id": session.id, "status": "active"}
        self.sessions[session.id] = session
        return session

    def update_session_status(self, session_id, status):
        if session_id in self.sessions:
            self.sessions[session_id].status = status

    def get_action(self, action_id):
        return self.actions.get(action_id)

    def create_action(self, session_id, action_type, input_data, metadata):
        action = MagicMock()
        action.id = f"action_{len(self.actions)}"
        action.session_id = session_id
        action.action_type = action_type
        action.input_data = input_data
        action.status = ActionStatus.PENDING
        action.to_dict = lambda: {"id": action.id, "status": "pending"}
        self.actions[action.id] = action
        return action

    def update_action(self, action_id, status):
        if action_id in self.actions:
            self.actions[action_id].status = status

    def add_audit_entry(self, **kwargs):
        self.audit_entries.append(kwargs)


class MockHandler(SessionOrchestrationMixin):
    """Mock handler for testing the mixin."""

    def __init__(self):
        self.store = MockStore()
        self._current_user = None

    def _get_user_id(self, handler):
        return "user_123"

    def _get_tenant_id(self, handler):
        return "tenant_456"

    def get_current_user(self, handler):
        return self._current_user


class TestListSessions:
    """Tests for _handle_list_sessions."""

    def setup_method(self):
        """Set up test fixtures."""
        self.handler = MockHandler()

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_list_sessions_success(self, mock_get_store):
        """Test successful session listing."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        # Add some sessions
        self.handler.store.create_session("user_123", "tenant_456", {}, {})
        self.handler.store.create_session("user_123", "tenant_456", {}, {})

        result = self.handler._handle_list_sessions({}, mock_http)

        assert result.status_code == 200

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_list_sessions_with_status_filter(self, mock_get_store):
        """Test listing sessions with status filter."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        result = self.handler._handle_list_sessions({"status": "active"}, mock_http)

        assert result.status_code == 200

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_list_sessions_invalid_status(self, mock_get_store):
        """Test listing sessions with invalid status."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        result = self.handler._handle_list_sessions({"status": "invalid"}, mock_http)

        assert result.status_code == 400


class TestGetSession:
    """Tests for _handle_get_session."""

    def setup_method(self):
        """Set up test fixtures."""
        self.handler = MockHandler()

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_get_session_success(self, mock_get_store):
        """Test successful session retrieval."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        session = self.handler.store.create_session("user_123", "tenant_456", {}, {})

        result = self.handler._handle_get_session(session.id, mock_http)

        assert result.status_code == 200

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_get_session_not_found(self, mock_get_store):
        """Test session not found."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        result = self.handler._handle_get_session("nonexistent", mock_http)

        assert result.status_code == 404


class TestCreateSession:
    """Tests for _handle_create_session."""

    def setup_method(self):
        """Set up test fixtures."""
        self.handler = MockHandler()

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_create_session_success(self, mock_get_store):
        """Test successful session creation."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        result = self.handler._handle_create_session(
            {"config": {"timeout": 300}, "metadata": {"name": "test"}}, mock_http
        )

        assert result.status_code == 201
        assert len(self.handler.store.sessions) == 1

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_create_session_empty_body(self, mock_get_store):
        """Test session creation with empty body."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        result = self.handler._handle_create_session({}, mock_http)

        # Should succeed with defaults
        assert result.status_code == 201


class TestCloseSession:
    """Tests for _handle_close_session."""

    def setup_method(self):
        """Set up test fixtures."""
        self.handler = MockHandler()

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_close_session_success(self, mock_get_store):
        """Test successful session closure."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        session = self.handler.store.create_session("user_123", "tenant_456", {}, {})

        result = self.handler._handle_close_session(session.id, mock_http)

        assert result.status_code == 200
        assert self.handler.store.sessions[session.id].status == SessionStatus.CLOSED

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_close_session_not_found(self, mock_get_store):
        """Test closing nonexistent session."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        result = self.handler._handle_close_session("nonexistent", mock_http)

        assert result.status_code == 404

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_close_session_access_denied(self, mock_get_store):
        """Test closing session owned by another user."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        # Create session owned by different user
        session = self.handler.store.create_session("other_user", "tenant_456", {}, {})

        result = self.handler._handle_close_session(session.id, mock_http)

        assert result.status_code == 403


class TestEndSession:
    """Tests for _handle_end_session (SDK-compatible endpoint)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.handler = MockHandler()

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_end_session_success(self, mock_get_store):
        """Test successful session ending."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        session = self.handler.store.create_session("user_123", "tenant_456", {}, {})

        result = self.handler._handle_end_session(session.id, mock_http)

        assert result.status_code == 200
        assert self.handler.store.sessions[session.id].status == SessionStatus.CLOSED


class TestGetAction:
    """Tests for _handle_get_action."""

    def setup_method(self):
        """Set up test fixtures."""
        self.handler = MockHandler()

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_get_action_success(self, mock_get_store):
        """Test successful action retrieval."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        session = self.handler.store.create_session("user_123", "tenant_456", {}, {})
        action = self.handler.store.create_action(session.id, "click", {}, {})

        result = self.handler._handle_get_action(action.id, mock_http)

        assert result.status_code == 200

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_get_action_not_found(self, mock_get_store):
        """Test action not found."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        result = self.handler._handle_get_action("nonexistent", mock_http)

        assert result.status_code == 404


class TestExecuteAction:
    """Tests for _handle_execute_action."""

    def setup_method(self):
        """Set up test fixtures."""
        self.handler = MockHandler()

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_execute_action_success(self, mock_get_store):
        """Test successful action execution."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        session = self.handler.store.create_session("user_123", "tenant_456", {}, {})

        result = self.handler._handle_execute_action(
            {
                "session_id": session.id,
                "action_type": "click",
                "input": {"x": 100, "y": 200},
            },
            mock_http,
        )

        assert result.status_code == 202
        assert len(self.handler.store.actions) == 1

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_execute_action_missing_session_id(self, mock_get_store):
        """Test action execution without session_id."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        result = self.handler._handle_execute_action(
            {"action_type": "click", "input": {}}, mock_http
        )

        assert result.status_code == 400

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_execute_action_session_not_found(self, mock_get_store):
        """Test action execution with nonexistent session."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        result = self.handler._handle_execute_action(
            {"session_id": "nonexistent", "action_type": "click"}, mock_http
        )

        assert result.status_code == 404

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_execute_action_session_not_active(self, mock_get_store):
        """Test action execution on closed session."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        session = self.handler.store.create_session("user_123", "tenant_456", {}, {})
        self.handler.store.update_session_status(session.id, SessionStatus.CLOSED)

        result = self.handler._handle_execute_action(
            {"session_id": session.id, "action_type": "click"}, mock_http
        )

        assert result.status_code == 400


class TestCancelAction:
    """Tests for _handle_cancel_action."""

    def setup_method(self):
        """Set up test fixtures."""
        self.handler = MockHandler()

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_cancel_action_success(self, mock_get_store):
        """Test successful action cancellation."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        session = self.handler.store.create_session("user_123", "tenant_456", {}, {})
        action = self.handler.store.create_action(session.id, "click", {}, {})
        self.handler.store.update_action(action.id, ActionStatus.RUNNING)

        result = self.handler._handle_cancel_action(action.id, mock_http)

        assert result.status_code == 200
        assert self.handler.store.actions[action.id].status == ActionStatus.CANCELLED

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_cancel_action_not_found(self, mock_get_store):
        """Test cancelling nonexistent action."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        result = self.handler._handle_cancel_action("nonexistent", mock_http)

        assert result.status_code == 404

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_cancel_action_already_completed(self, mock_get_store):
        """Test cancelling already completed action."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        session = self.handler.store.create_session("user_123", "tenant_456", {}, {})
        action = self.handler.store.create_action(session.id, "click", {}, {})
        self.handler.store.update_action(action.id, ActionStatus.COMPLETED)

        result = self.handler._handle_cancel_action(action.id, mock_http)

        assert result.status_code == 400


class TestAuditLogging:
    """Tests for audit logging in orchestration handlers."""

    def setup_method(self):
        """Set up test fixtures."""
        self.handler = MockHandler()

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_create_session_audit(self, mock_get_store):
        """Test audit entry created for session creation."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        self.handler._handle_create_session({"config": {}}, mock_http)

        assert len(self.handler.store.audit_entries) == 1
        assert self.handler.store.audit_entries[0]["action"] == "session.create"

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_close_session_audit(self, mock_get_store):
        """Test audit entry created for session closure."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        session = self.handler.store.create_session("user_123", "tenant_456", {}, {})
        self.handler.store.audit_entries.clear()

        self.handler._handle_close_session(session.id, mock_http)

        assert len(self.handler.store.audit_entries) == 1
        assert self.handler.store.audit_entries[0]["action"] == "session.close"

    @patch("aragora.server.handlers.openclaw.orchestrator._get_store")
    def test_execute_action_audit(self, mock_get_store):
        """Test audit entry created for action execution."""
        mock_get_store.return_value = self.handler.store
        mock_http = MagicMock()

        session = self.handler.store.create_session("user_123", "tenant_456", {}, {})
        self.handler.store.audit_entries.clear()

        self.handler._handle_execute_action(
            {"session_id": session.id, "action_type": "click"}, mock_http
        )

        assert len(self.handler.store.audit_entries) == 1
        assert self.handler.store.audit_entries[0]["action"] == "action.execute"


class TestExecutionRuntimeFailClosed:
    """Characterize inconsistent normalization results as execution failures."""

    def test_dispatch_rejects_missing_normalized_action(self):
        runtime = OpenClawExecutionRuntime()
        runtime._normalize_action = MagicMock(return_value=(None, None))
        session = MagicMock(id="session-1", user_id="user-1", tenant_id="tenant-1")
        action = MagicMock(id="action-1", action_type="click")

        result = runtime.dispatch_action(session, action)

        assert result.status == ActionStatus.FAILED
        assert result.executed is False
        assert result.error == "action_normalization_failed: click"
