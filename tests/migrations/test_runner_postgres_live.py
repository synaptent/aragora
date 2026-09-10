"""Opt-in PostgreSQL CLI tests; the test role must have CREATEDB permission."""

import importlib
import os
import subprocess
import sys
import uuid
from contextlib import closing
from pathlib import Path

import pytest


@pytest.fixture
def postgres_dsn():
    dsn = os.environ.get("ARAGORA_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("set ARAGORA_TEST_DATABASE_URL to run live PostgreSQL tests")
    pytest.importorskip("psycopg2")
    return dsn


@pytest.fixture
def isolated_database(postgres_dsn):
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import make_dsn

    database = "migration_test_" + uuid.uuid4().hex
    with closing(psycopg2.connect(postgres_dsn)) as conn:
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            try:
                yield make_dsn(postgres_dsn, dbname=database)
            finally:
                cursor.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def run_cli(command, dsn):
    return subprocess.run(
        [sys.executable, "-m", "aragora.migrations", command, "--database-url", dsn],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_upgrade_and_status_against_real_postgres(isolated_database):
    import psycopg2
    from aragora.migrations import versions

    dsn = isolated_database
    upgraded = run_cli("upgrade", dsn)
    assert upgraded.returncode == 0, upgraded.stderr
    assert "AUTOINCREMENT" not in upgraded.stderr
    expected = []
    for path in Path(versions.__file__).parent.glob("v*.py"):
        migration = importlib.import_module(f"aragora.migrations.versions.{path.stem}").migration
        assert path.stem.startswith(f"v{migration.version}_")
        expected.append((migration.version, migration.name))
    assert expected
    status = run_cli("status", dsn)
    assert status.returncode == 0, status.stderr
    assert "  Backend: postgresql\n" in status.stdout
    assert "  Pending: 0\n" in status.stdout
    assert f"  Applied: {len(expected)}\n" in status.stdout
    with closing(psycopg2.connect(dsn)) as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT version, name FROM _aragora_migrations ORDER BY version")
            assert cursor.fetchall() == sorted(expected)
            cursor.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
            )
            assert {"_aragora_migrations", "_aragora_rollback_history"} <= {
                row[0] for row in cursor.fetchall()
            }
    repeated = run_cli("upgrade", dsn)
    assert repeated.returncode == 0, repeated.stderr
    assert repeated.stdout == "No pending migrations.\n"


def test_concurrent_index_failure_leaves_pool_usable(isolated_database):
    import psycopg2
    from aragora.migrations.patterns import safe_create_index, safe_drop_index
    from aragora.storage.backends import PostgreSQLBackend

    with closing(PostgreSQLBackend(isolated_database, pool_size=1, pool_max_overflow=0)) as backend:
        backend.execute_write("CREATE TABLE index_test (id INTEGER)")
        safe_create_index(backend, "test_idx", "index_test", ["id"])
        assert backend.fetch_one("SELECT to_regclass('test_idx')")[0] == "test_idx"
        safe_drop_index(backend, "test_idx")
        assert backend.fetch_one("SELECT to_regclass('test_idx')")[0] is None
        with pytest.raises(psycopg2.errors.UndefinedTable):
            safe_create_index(backend, "missing_idx", "missing_table", ["id"])
        with backend.connection() as connection:
            assert connection.autocommit is False
        backend.execute_write("INSERT INTO index_test VALUES (1)")
        assert backend.fetch_one("SELECT COUNT(*) FROM index_test") == (1,)


def test_wrong_password_reports_authentication_without_traceback(postgres_dsn):
    from psycopg2.extensions import make_dsn

    wrong_dsn = make_dsn(postgres_dsn, password="wrong-" + uuid.uuid4().hex)
    for command in ("upgrade", "status"):
        result = run_cli(command, wrong_dsn)
        assert result.returncode != 0
        assert "authentication" in result.stderr.lower()
        assert "Traceback" not in result.stdout + result.stderr
