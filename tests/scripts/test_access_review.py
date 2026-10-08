from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path

from aragora.billing.models import User


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "access_review.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("access_review", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeStore:
    def __init__(self, users: list[User]) -> None:
        self._users = users

    def list_all_users(self, limit: int, offset: int, org_id_filter: str | None):
        return self._users, len(self._users)


def test_inactivity_days_accepts_datetime_last_login() -> None:
    module = _load_module()
    last_login = datetime.utcnow() - timedelta(days=120)

    assert module.calculate_inactivity_days(last_login) == 120


def test_inactivity_days_still_parses_iso_strings() -> None:
    module = _load_module()
    last_login = (datetime.utcnow() - timedelta(days=10)).isoformat() + "Z"

    assert module.calculate_inactivity_days(last_login) == 10


def test_report_uses_api_key_hash_and_datetime_logins() -> None:
    module = _load_module()
    dormant_admin = User(
        email="admin@example.com",
        role="admin",
        last_login_at=datetime.utcnow() - timedelta(days=200),
        api_key_hash="hashed",
    )
    member = User(email="member@example.com", role="member", last_login_at=datetime.utcnow())

    report = module.generate_access_report(_FakeStore([dormant_admin, member]))

    records = {record["email"]: record for record in report["users"]}
    assert records["admin@example.com"]["has_api_key"] is True
    assert records["admin@example.com"]["inactivity_days"] == 200
    assert records["member@example.com"]["has_api_key"] is False
    assert report["summary"]["dormant_accounts"] == 1
    finding_types = {finding["type"] for finding in report["findings"]}
    assert {"DORMANT_ACCOUNT", "ADMIN_NO_MFA", "API_KEY_NO_EXPIRY"} <= finding_types
