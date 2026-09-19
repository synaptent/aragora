"""The documented PostgreSQL backend aliases must agree across stores."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from aragora.storage import connection_factory, password_reset_store

DSN = "postgresql://u:p@127.0.0.1:1/db"
STORES = [
    ("receipt_store", "ReceiptStore"),
    ("audit_trail_store", "AuditTrailStore"),
    ("share_store", "ShareLinkStore"),
    ("inbox_activity_store", "InboxActivityStore"),
    ("decision_result_store", "DecisionResultStore"),
]


class FakePostgreSQLBackend:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def execute_write(self, *args: Any, **kwargs: Any) -> int:
        return 0

    def fetch_one(self, *args: Any, **kwargs: Any) -> None:
        return None

    def fetch_all(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def backend_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ARAGORA_DATABASE_URL", raising=False)
    monkeypatch.delenv("ARAGORA_PASSWORD_RESET_BACKEND", raising=False)
    monkeypatch.setattr(password_reset_store, "_password_reset_store", None)


@pytest.mark.parametrize("module_name,class_name", STORES)
@pytest.mark.parametrize("spelling", ["postgres", "postgresql", "POSTGRES", "PostgreSQL"])
def test_store_accepts_postgres_alias(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    module_name: str,
    class_name: str,
    spelling: str,
) -> None:
    monkeypatch.setenv("ARAGORA_DB_BACKEND", spelling)
    module = importlib.import_module(f"aragora.storage.{module_name}")
    monkeypatch.setattr(module, "PostgreSQLBackend", FakePostgreSQLBackend)
    monkeypatch.setattr(module, "POSTGRESQL_AVAILABLE", True)

    store = getattr(module, class_name)(db_path=tmp_path / "store.db")
    assert store.backend_type == "postgresql"
    assert isinstance(store._backend, FakePostgreSQLBackend)
    assert store._backend.database_url == DSN


@pytest.mark.parametrize("spelling", ["postgres", "postgresql", "POSTGRES", "PostgreSQL"])
def test_password_reset_accepts_postgres_alias(
    monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    monkeypatch.setenv("ARAGORA_DB_BACKEND", spelling)
    pool = object()
    monkeypatch.setattr(connection_factory, "get_postgres_pool", lambda: pool)

    store = password_reset_store.get_password_reset_store()
    assert isinstance(store._backend, password_reset_store.PostgresPasswordResetStore)
    assert store._backend._pool is pool


@pytest.mark.parametrize("backend", ["sqlite", "supabase", "auto", "", None])
def test_non_postgres_backend_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, backend: str | None
) -> None:
    from aragora.storage.receipt_store import ReceiptStore

    if backend is None:
        monkeypatch.delenv("ARAGORA_DB_BACKEND", raising=False)
    else:
        monkeypatch.setenv("ARAGORA_DB_BACKEND", backend)
    store = ReceiptStore(db_path=tmp_path / "receipts.db")
    try:
        assert store.backend_type == "sqlite"
        reset_store = password_reset_store.get_password_reset_store()
        assert isinstance(reset_store._backend, password_reset_store.SQLitePasswordResetStore)
    finally:
        store.close()


@pytest.mark.parametrize("spelling", ["postgres", "postgresql"])
def test_postgres_without_dsn_uses_sqlite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, spelling: str
) -> None:
    from aragora.storage.receipt_store import ReceiptStore

    monkeypatch.setenv("ARAGORA_DB_BACKEND", spelling)
    monkeypatch.delenv("DATABASE_URL")
    store = ReceiptStore(db_path=tmp_path / "receipts.db")
    try:
        assert store.backend_type == "sqlite"
    finally:
        store.close()


@pytest.mark.parametrize("spelling", ["postgres", "postgresql"])
def test_password_reset_without_pool_uses_sqlite(
    monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    monkeypatch.setenv("ARAGORA_DB_BACKEND", spelling)
    monkeypatch.setattr(connection_factory, "get_postgres_pool", lambda: None)
    store = password_reset_store.get_password_reset_store()
    assert isinstance(store._backend, password_reset_store.SQLitePasswordResetStore)


@pytest.mark.parametrize("spelling", ["postgres", "postgresql"])
def test_password_reset_override_preserved(monkeypatch: pytest.MonkeyPatch, spelling: str) -> None:
    monkeypatch.setenv("ARAGORA_DB_BACKEND", spelling)
    monkeypatch.setenv("ARAGORA_PASSWORD_RESET_BACKEND", "memory")
    store = password_reset_store.get_password_reset_store()
    assert isinstance(store._backend, password_reset_store.InMemoryPasswordResetStore)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("postgres", True),
        ("PostgreSQL", True),
        (" POSTGRES ", True),
        ("sqlite", False),
        ("supabase", False),
        ("auto", False),
        ("", False),
        (None, False),
    ],
)
def test_postgres_predicate(value: str | None, expected: bool) -> None:
    assert connection_factory.is_postgres_backend(value) is expected
