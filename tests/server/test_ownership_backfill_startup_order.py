"""Ownership backfills wait for the authoritative user store during a cold start.

``UnifiedServer`` builds its stores before ``start()`` brings up the shared
PostgreSQL pool. With PostgreSQL configured, the user store registered at that
point is a SQLite fallback that ``upgrade_handler_stores`` later replaces, so
the one-time plan and receipt ownership backfills must not finalize against it.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aragora.pipeline import plan_store as plan_store_module
from aragora.server.initialization import register_startup_user_store, upgrade_handler_stores
from aragora.server.receipt_link_resolver import install_receipt_link_resolver
from aragora.storage import receipt_ownership
from aragora.storage.receipt_store import ReceiptStore
from aragora.storage.user_store.sqlite_store import UserStore
from aragora.tenancy import membership
from tests.pipeline.test_plan_ownership_backfill import LEGACY_SCHEMA, _execution, _plan, _rows
from tests.pipeline.test_plan_ownership_backfill import _schema_version as _plan_version
from tests.storage.test_receipt_ownership import _legacy_db as _legacy_receipts_db
from tests.storage.test_receipt_ownership import _owner as _receipt_owner
from tests.storage.test_receipt_ownership import _schema_version as _receipt_version

_DB_ENV = (
    "DATABASE_URL",
    "ARAGORA_POSTGRES_DSN",
    "SUPABASE_URL",
    "SUPABASE_POSTGRES_DSN",
    "ARAGORA_DB_BACKEND",
    "ARAGORA_USE_SHARED_POOL",
)


@pytest.fixture(autouse=True)
def _isolated_startup_state(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _DB_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(membership, "_registered_user_store", None)
    monkeypatch.setattr(membership, "_registered_store_is_provisional", False)
    monkeypatch.setattr(receipt_ownership, "_registered_resolver", None)
    monkeypatch.setattr(plan_store_module, "_store", None)


def _configure_postgres(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    """The supported auto/development configuration with a PostgreSQL DSN."""
    env = {
        "DATABASE_URL": "postgresql://aragora@127.0.0.1:1/aragora",
        "ARAGORA_DB_BACKEND": "auto",
        "ARAGORA_USE_SHARED_POOL": "true",
        "ARAGORA_ALLOW_SQLITE_FALLBACK": "true",
        **overrides,
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)


def _fake_postgres(monkeypatch: pytest.MonkeyPatch, members: UserStore) -> None:
    """A healthy shared pool whose PostgreSQL user store holds ``members``."""

    class Connection:
        async def fetchval(self, _query: str) -> int:
            return 1

    class Pool:
        @contextlib.asynccontextmanager
        async def acquire(self) -> AsyncIterator[Connection]:
            yield Connection()

    class PostgresUsers:
        def __init__(self, _pool: Pool) -> None:
            pass

        async def initialize(self) -> None:
            pass

        def __getattr__(self, name: str) -> Any:
            return getattr(members, name)

    class NotUnderTest:
        def __init__(self, _pool: Pool) -> None:
            raise RuntimeError("not part of this test")

    from aragora.server.handler_registry import UnifiedHandler

    monkeypatch.setattr(UnifiedHandler, "user_store", None, raising=False)
    monkeypatch.setattr("aragora.storage.pool_manager.is_pool_initialized", lambda: True)
    monkeypatch.setattr("aragora.storage.pool_manager.get_shared_pool", lambda: Pool())
    monkeypatch.setattr("aragora.storage.user_store.PostgresUserStore", PostgresUsers)
    for other_store in (
        "aragora.storage.job_queue_store.PostgresJobQueueStore",
        "aragora.storage.governance_store.PostgresGovernanceStore",
        "aragora.storage.unified_inbox_store.PostgresUnifiedInboxStore",
    ):
        monkeypatch.setattr(other_store, NotUnderTest)


@pytest.mark.parametrize(
    ("overrides", "provisional"),
    [
        ({}, True),
        ({"ARAGORA_USE_SHARED_POOL": "false"}, False),
        ({"ARAGORA_DB_BACKEND": "sqlite"}, False),
    ],
)
def test_startup_user_store_is_provisional_only_while_a_postgres_upgrade_is_due(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, str],
    provisional: bool,
) -> None:
    _configure_postgres(monkeypatch, **overrides)

    register_startup_user_store(UserStore(tmp_path / "users.db"))

    assert membership.user_org_ids("user-1") == frozenset()
    if provisional:
        with pytest.raises(membership.MembershipLookupError):
            membership.backfill_org_ids("user-1")
    else:
        assert membership.backfill_org_ids("user-1") == frozenset()


@pytest.mark.asyncio
async def test_cold_start_backfills_wait_for_the_postgres_user_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The scheduler's membership exists only in PostgreSQL; the fallback is empty.
    members = UserStore(tmp_path / "postgres_users.db")
    scheduler = members.create_user("a@example.com", "hash", "salt", name="a").id
    org = members.create_organization("Org A", owner_id=scheduler).id

    plans_db = str(tmp_path / "plans.db")
    conn = sqlite3.connect(plans_db)
    conn.executescript(LEGACY_SCHEMA)
    _plan(conn, "plan-a")
    _execution(conn, "exec-a", "plan-a", {"scheduled_by": scheduler})
    conn.commit()
    conn.close()
    monkeypatch.setattr(plan_store_module, "_get_db_path", lambda: plans_db)

    receipts_db = tmp_path / "receipts.db"
    _legacy_receipts_db(receipts_db, [("r-plan-a", None, {"config_used": {"plan_id": "plan-a"}})])
    receipts = ReceiptStore(db_path=receipts_db, file_receipt_dirs=[])
    monkeypatch.setattr("aragora.storage.receipt_store.get_receipt_store", lambda: receipts)

    # UnifiedServer._init_subsystems, before the shared pool exists.
    _configure_postgres(monkeypatch)
    register_startup_user_store(UserStore(tmp_path / "fallback_users.db"))
    assert install_receipt_link_resolver(SimpleNamespace(get_org_id=lambda _id: None)) is False

    assert _plan_version(plans_db) is None
    for table in ("plans", "plan_executions"):
        owners = {(r["org_id"], r["ownership_source"]) for r in _rows(plans_db, table).values()}
        assert owners == {(None, None)}, table
    assert _receipt_version(receipts_db) is None
    assert _receipt_owner(receipts_db, "r-plan-a") == (None, None, None)

    # UnifiedServer.start(): the PostgreSQL user store replaces the fallback.
    _fake_postgres(monkeypatch, members)
    results = await upgrade_handler_stores(tmp_path)

    assert results["user_store"] == "postgres"
    assert _plan_version(plans_db) == 1
    plan = _rows(plans_db, "plans")["plan-a"]
    assert (plan["org_id"], plan["created_by"], plan["ownership_source"]) == (
        org,
        None,
        "backfilled",
    )
    execution = _rows(plans_db, "plan_executions")["exec-a"]
    assert (execution["org_id"], execution["created_by"]) == (org, scheduler)
    assert _receipt_version(receipts_db) == 1
    assert _receipt_owner(receipts_db, "r-plan-a") == (org, None, "backfilled")
