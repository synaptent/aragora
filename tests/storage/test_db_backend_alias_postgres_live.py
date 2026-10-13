"""Opt-in PostgreSQL tests for ARAGORA_DB_BACKEND=postgres; the role needs CREATEDB."""

from __future__ import annotations

import os
import time
import uuid
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("ARAGORA_TEST_DATABASE_URL"),
    reason="set ARAGORA_TEST_DATABASE_URL to run live PostgreSQL tests",
)


@pytest.fixture
def isolated_database():
    pytest.importorskip("psycopg2")
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import make_dsn

    postgres_dsn = os.environ["ARAGORA_TEST_DATABASE_URL"]
    database = "backend_alias_test_" + uuid.uuid4().hex
    with closing(psycopg2.connect(postgres_dsn)) as conn:
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            try:
                yield make_dsn(postgres_dsn, dbname=database)
            finally:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database))
                )


@pytest.fixture
def hosted_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_database: str):
    """Mirror the hosted compose file: ARAGORA_DB_BACKEND=postgres plus DATABASE_URL."""
    from aragora.config.settings import reset_settings
    from aragora.gauntlet import storage as gauntlet_storage
    from aragora.storage import backends, receipt_store

    monkeypatch.setenv("ARAGORA_DB_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", isolated_database)
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ARAGORA_DATABASE_URL", raising=False)
    # Any SQLite fallback would land here, where the test can see it.
    monkeypatch.setattr(receipt_store, "DEFAULT_DB_PATH", tmp_path / "receipts.db")
    monkeypatch.chdir(tmp_path)
    receipt_store.set_receipt_store(None)
    gauntlet_storage.reset_storage()
    backends.reset_database_backend()
    reset_settings()
    yield isolated_database
    receipt_store.set_receipt_store(None)
    gauntlet_storage.reset_storage()
    backends.reset_database_backend()
    reset_settings()


def _fetch_one(dsn: str, query: str, params: tuple = ()) -> tuple | None:
    import psycopg2

    with closing(psycopg2.connect(dsn)) as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchone()


def test_hosted_receipt_and_gauntlet_rows_land_in_postgres(
    hosted_environment: str, tmp_path: Path
) -> None:
    from aragora.gauntlet.storage import get_storage
    from aragora.security.capability_gate import CapabilityGateStore
    from aragora.storage.backends import PostgreSQLBackend, get_database_backend
    from aragora.storage.receipt_store import get_receipt_store

    dsn = hosted_environment
    receipt_id = "receipt-live-" + uuid.uuid4().hex
    gauntlet_id = "gauntlet-live-" + uuid.uuid4().hex

    receipts = get_receipt_store()
    assert receipts.backend_type == "postgresql"
    receipts.save(
        {
            "receipt_id": receipt_id,
            "gauntlet_id": gauntlet_id,
            "debate_id": "debate-live",
            "timestamp": time.time(),
            "verdict": "APPROVED",
            "confidence": 0.9,
            "risk_level": "LOW",
            "risk_score": 0.1,
            "checksum": "sha256:live",
        }
    )
    stored = receipts.get(receipt_id)
    assert stored is not None and stored.verdict == "APPROVED"

    gauntlet = get_storage()
    assert gauntlet.backend_type == "postgresql"
    result = SimpleNamespace(
        gauntlet_id=gauntlet_id,
        input_hash="live-hash",
        input_summary="live alias check",
        verdict="pass",
        confidence=0.8,
        robustness_score=0.7,
        agents_used=["claude"],
        template_used="security",
        duration_seconds=1.0,
    )
    gauntlet.save(result)
    loaded = gauntlet.get(gauntlet_id)
    assert loaded is not None and loaded["gauntlet_id"] == gauntlet_id

    backend = get_database_backend()
    assert isinstance(backend, PostgreSQLBackend)
    CapabilityGateStore(backend=backend)

    assert _fetch_one(dsn, "SELECT verdict FROM receipts WHERE receipt_id = %s", (receipt_id,)) == (
        "APPROVED",
    )
    assert _fetch_one(
        dsn, "SELECT verdict FROM gauntlet_results WHERE gauntlet_id = %s", (gauntlet_id,)
    ) == ("pass",)
    assert _fetch_one(dsn, "SELECT to_regclass('capability_approvals')::text") == (
        "capability_approvals",
    )
    assert not list(tmp_path.rglob("*.db"))
