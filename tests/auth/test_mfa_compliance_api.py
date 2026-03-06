"""
Tests for the admin MFA compliance API endpoint (GET /api/v1/admin/mfa/compliance).

Covers:
- Correct counts with all admins MFA-enabled (100% compliance)
- Mixed compliance (some admins with MFA, some without)
- Grace period users counted correctly
- RBAC protection (admin:read required)
- No admins in the system (edge case)

GitHub Issue: #510 — Admin MFA enforcement completion
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from aragora.server.handlers.auth.mfa import handle_mfa_compliance


# ---------------------------------------------------------------------------
# Fake user fixtures
# ---------------------------------------------------------------------------


@dataclass
class _AdminUser:
    """Admin user with configurable MFA state."""

    id: str = "admin-1"
    role: str = "admin"
    mfa_enabled: bool = False
    mfa_grace_period_started_at: str | None = None


@dataclass
class _RegularUser:
    """Non-admin user."""

    id: str = "user-1"
    role: str = "member"
    mfa_enabled: bool = False


@dataclass
class _OwnerUser:
    """Owner-role user."""

    id: str = "owner-1"
    role: str = "owner"
    mfa_enabled: bool = True


@dataclass
class _MultiRoleAdmin:
    """User with roles set attribute."""

    id: str = "multi-1"
    roles: set[str] = field(default_factory=lambda: {"admin", "member"})
    role: str = "member"  # Primary role is member, but roles set includes admin
    mfa_enabled: bool = False
    mfa_grace_period_started_at: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler_instance(users: list, permission_allowed: bool = True):
    """Create a mock AuthHandler with a fake user store."""
    store = MagicMock()
    store.list_users.return_value = users

    instance = MagicMock()
    instance._get_user_store.return_value = store

    if permission_allowed:
        instance._check_permission.return_value = None
    else:
        # Return a HandlerResult-like error (the real _check_permission returns
        # a HandlerResult from error_response on failure)
        from aragora.server.handlers.base import error_response

        instance._check_permission.return_value = error_response("Permission denied", 403)

    return instance


def _parse_result(result):
    """Parse a HandlerResult into (body_dict, status_code)."""
    # HandlerResult supports tuple unpacking: (body, status, headers)
    body, status, _headers = result
    if isinstance(body, bytes):
        body = json.loads(body.decode("utf-8"))
    return body, status


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMFAComplianceAllEnabled:
    """All admins have MFA enabled — 100% compliance."""

    def test_returns_100_percent_compliance(self):
        admin1 = _AdminUser(id="a1", mfa_enabled=True)
        admin2 = _AdminUser(id="a2", mfa_enabled=True)
        regular = _RegularUser(id="u1")
        users = [admin1, admin2, regular]

        instance = _make_handler_instance(users)
        handler = MagicMock()

        result = handle_mfa_compliance(instance, handler)
        body, status = _parse_result(result)

        assert status == 200
        assert body["total_admins"] == 2
        assert body["mfa_enabled_count"] == 2
        assert body["mfa_disabled_count"] == 0
        assert body["in_grace_period"] == 0
        assert body["compliance_pct"] == 100.0
        assert body["non_compliant_users"] == []


class TestMFAComplianceMixed:
    """Some admins with MFA, some without."""

    def test_returns_correct_mixed_counts(self):
        admin_with_mfa = _AdminUser(id="a1", mfa_enabled=True)
        admin_no_mfa = _AdminUser(id="a2", mfa_enabled=False)
        admin_grace = _AdminUser(
            id="a3",
            mfa_enabled=False,
            mfa_grace_period_started_at="2026-03-01T00:00:00Z",
        )
        owner_with_mfa = _OwnerUser(id="o1", mfa_enabled=True)
        regular = _RegularUser(id="u1")
        users = [admin_with_mfa, admin_no_mfa, admin_grace, owner_with_mfa, regular]

        instance = _make_handler_instance(users)
        handler = MagicMock()

        result = handle_mfa_compliance(instance, handler)
        body, status = _parse_result(result)

        assert status == 200
        assert body["total_admins"] == 4
        assert body["mfa_enabled_count"] == 2
        assert body["mfa_disabled_count"] == 2
        assert body["in_grace_period"] == 1
        assert body["compliance_pct"] == 50.0
        assert len(body["non_compliant_users"]) == 2

    def test_non_compliant_users_include_user_id_and_role(self):
        admin_no_mfa = _AdminUser(id="a2", mfa_enabled=False)
        users = [admin_no_mfa]

        instance = _make_handler_instance(users)
        handler = MagicMock()

        result = handle_mfa_compliance(instance, handler)
        body, status = _parse_result(result)

        nc = body["non_compliant_users"]
        assert len(nc) == 1
        assert nc[0]["user_id"] == "a2"
        assert nc[0]["role"] == "admin"
        assert nc[0]["in_grace_period"] is False

    def test_grace_period_user_flagged(self):
        admin_grace = _AdminUser(
            id="a-grace",
            mfa_enabled=False,
            mfa_grace_period_started_at="2026-03-05T12:00:00Z",
        )
        users = [admin_grace]

        instance = _make_handler_instance(users)
        handler = MagicMock()

        result = handle_mfa_compliance(instance, handler)
        body, status = _parse_result(result)

        nc = body["non_compliant_users"]
        assert len(nc) == 1
        assert nc[0]["in_grace_period"] is True
        assert body["in_grace_period"] == 1


class TestMFAComplianceRBACProtection:
    """The endpoint requires admin:read permission."""

    def test_permission_denied_returns_403(self):
        instance = _make_handler_instance([], permission_allowed=False)
        handler = MagicMock()

        result = handle_mfa_compliance(instance, handler)
        _body, status, _headers = result

        assert status == 403

    def test_permission_check_uses_admin_read(self):
        instance = _make_handler_instance([])
        handler = MagicMock()

        handle_mfa_compliance(instance, handler)

        instance._check_permission.assert_called_once_with(handler, "admin:read")


class TestMFAComplianceNoAdmins:
    """Edge case: no admin users in the system."""

    def test_no_admins_returns_100_percent(self):
        regular1 = _RegularUser(id="u1")
        regular2 = _RegularUser(id="u2")
        users = [regular1, regular2]

        instance = _make_handler_instance(users)
        handler = MagicMock()

        result = handle_mfa_compliance(instance, handler)
        body, status = _parse_result(result)

        assert status == 200
        assert body["total_admins"] == 0
        assert body["mfa_enabled_count"] == 0
        assert body["mfa_disabled_count"] == 0
        assert body["compliance_pct"] == 100.0
        assert body["non_compliant_users"] == []


class TestMFAComplianceMultiRole:
    """Users with roles set (not just single role) are detected correctly."""

    def test_multi_role_admin_detected(self):
        multi = _MultiRoleAdmin(id="multi-1", mfa_enabled=False)
        users = [multi]

        instance = _make_handler_instance(users)
        handler = MagicMock()

        result = handle_mfa_compliance(instance, handler)
        body, status = _parse_result(result)

        assert status == 200
        assert body["total_admins"] == 1
        assert body["mfa_disabled_count"] == 1
        assert len(body["non_compliant_users"]) == 1
