"""
Tests for MFA compliance dashboard endpoint.

Tests cover:
- Returns correct admin counts
- Handles empty admin list
- Calculates compliance rate correctly
- Returns per-admin details
- Handles missing user store
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from aragora.server.handlers.admin.mfa_compliance import MFAComplianceHandler


@dataclass
class FakeUser:
    """Minimal user for compliance testing."""

    id: str = "user-1"
    role: str = "admin"
    mfa_enabled: bool = False
    mfa_grace_period_started_at: str | None = None


class FakeUserStore:
    """Fake user store that returns a configurable list of users."""

    def __init__(self, users: list[FakeUser] | None = None):
        self._users = users or []

    def list_users(self) -> list[FakeUser]:
        return self._users

    def list_all_users(self, limit: int = 50, offset: int = 0) -> tuple[list[FakeUser], int]:
        batch = self._users[offset : offset + limit]
        return batch, len(self._users)

    def get_user_by_id(self, user_id: str) -> FakeUser | None:
        for u in self._users:
            if u.id == user_id:
                return u
        return None


def _parse_data(result: Any) -> dict:
    """Parse JSON body from HandlerResult and unwrap data envelope."""
    body = json.loads(result.body.decode("utf-8"))
    return body.get("data", body)


class TestMFAComplianceEndpoint:
    """Tests for GET /api/v1/admin/mfa-compliance."""

    def test_returns_correct_counts(self):
        users = [
            FakeUser(id="a1", role="admin", mfa_enabled=True),
            FakeUser(id="a2", role="admin", mfa_enabled=False),
            FakeUser(id="a3", role="owner", mfa_enabled=True),
            FakeUser(id="m1", role="member", mfa_enabled=False),
        ]
        handler = MFAComplianceHandler(ctx={"user_store": FakeUserStore(users)})
        result = handler._get_compliance(handler=None)

        data = _parse_data(result)
        # m1 is not admin so excluded; a1, a2, a3 are admins
        assert data["total_admins"] == 3
        assert data["mfa_enabled"] == 2
        assert data["mfa_disabled"] == 1
        assert data["in_grace_period"] == 0

    def test_handles_empty_admin_list(self):
        users = [
            FakeUser(id="m1", role="member"),
            FakeUser(id="m2", role="viewer"),
        ]
        handler = MFAComplianceHandler(ctx={"user_store": FakeUserStore(users)})
        result = handler._get_compliance(handler=None)

        data = _parse_data(result)
        assert data["total_admins"] == 0
        assert data["mfa_enabled"] == 0
        assert data["mfa_disabled"] == 0
        assert data["compliance_rate"] == 100.0

    def test_calculates_compliance_rate(self):
        users = [
            FakeUser(id="a1", role="admin", mfa_enabled=True),
            FakeUser(id="a2", role="admin", mfa_enabled=True),
            FakeUser(id="a3", role="admin", mfa_enabled=False),
            FakeUser(id="a4", role="admin", mfa_enabled=False),
        ]
        handler = MFAComplianceHandler(ctx={"user_store": FakeUserStore(users)})
        result = handler._get_compliance(handler=None)

        data = _parse_data(result)
        assert data["compliance_rate"] == 50.0

    def test_returns_details_per_admin(self):
        users = [
            FakeUser(id="a1", role="admin", mfa_enabled=True),
            FakeUser(
                id="a2",
                role="owner",
                mfa_enabled=False,
                mfa_grace_period_started_at="2026-01-01T00:00:00Z",
            ),
        ]
        handler = MFAComplianceHandler(ctx={"user_store": FakeUserStore(users)})
        result = handler._get_compliance(handler=None)

        data = _parse_data(result)
        assert len(data["details"]) == 2

        detail_map = {d["user_id"]: d for d in data["details"]}
        assert detail_map["a1"]["mfa_enabled"] is True
        assert detail_map["a1"]["status"] == "compliant"
        assert detail_map["a2"]["mfa_enabled"] is False
        assert detail_map["a2"]["status"] == "grace_period"

    def test_handles_missing_user_store(self):
        handler = MFAComplianceHandler(ctx={})
        result = handler._get_compliance(handler=None)

        assert result.status_code == 503

    def test_grace_period_counted(self):
        users = [
            FakeUser(
                id="a1",
                role="admin",
                mfa_enabled=False,
                mfa_grace_period_started_at="2026-02-20T00:00:00Z",
            ),
        ]
        handler = MFAComplianceHandler(ctx={"user_store": FakeUserStore(users)})
        result = handler._get_compliance(handler=None)

        data = _parse_data(result)
        assert data["in_grace_period"] == 1
        assert data["mfa_disabled"] == 0

    def test_list_all_users_tuple_supported(self):
        users = [
            FakeUser(id="a1", role="admin", mfa_enabled=True),
            FakeUser(id="m1", role="member", mfa_enabled=False),
        ]
        handler = MFAComplianceHandler(ctx={"user_store": FakeUserStore(users)})
        result = handler._get_compliance(handler=None)

        data = _parse_data(result)
        assert data["total_admins"] == 1
        assert data["mfa_enabled"] == 1
