"""Shared fixtures for connector tests."""

from __future__ import annotations

from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def _bypass_connector_management_rbac(monkeypatch):
    """Bypass RBAC/auth checks on ConnectorManagementHandler for all tests.

    The security hardening added ``require_auth_or_error`` and
    ``require_permission_or_error`` checks to the management handler.
    Test code passes ``None`` as the HTTP handler object, which causes
    a 401 response.  This fixture patches both methods to return a mock
    authenticated user so the handler tests can exercise the business
    logic without needing a full auth stack.
    """
    try:
        from aragora.server.handlers.connectors.management import (
            ConnectorManagementHandler,
        )
    except ImportError:
        yield
        return

    mock_user = Mock()
    mock_user.user_id = "test-user"
    mock_user.email = "test-user@example.com"
    mock_user.org_id = None
    # Per-connector health and test check the RBAC v2 role grants, where only
    # owners hold connectors.test.
    mock_user.role = "owner"
    mock_user.is_authenticated = True
    mock_user.permissions = {"connectors:read", "connectors:test"}

    monkeypatch.setattr(
        ConnectorManagementHandler,
        "require_auth_or_error",
        lambda self, handler: (mock_user, None),
    )
    monkeypatch.setattr(
        ConnectorManagementHandler,
        "require_permission_or_error",
        lambda self, handler, perm: (mock_user, None),
    )
    yield
