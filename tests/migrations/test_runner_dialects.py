"""Regression tests for dialect-specific bookkeeping and CLI database errors."""

import argparse
import logging
import os
import sqlite3
import subprocess
import sys
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from aragora.migrations import __main__ as cli
from aragora.migrations.runner import Migration, MigrationRunner
from aragora.storage.backends import PostgreSQLBackend, SQLiteBackend


def test_postgres_rollback_history_uses_serial():
    backend = MagicMock(spec=PostgreSQLBackend)
    MigrationRunner(backend=backend)
    ddl = backend.execute_write.call_args_list[-1].args[0]
    assert "id SERIAL PRIMARY KEY" in ddl
    assert "AUTOINCREMENT" not in ddl
    assert "version BIGINT NOT NULL" in ddl


def test_sqlite_rollback_history_keeps_autoincrement():
    backend = MagicMock(spec=SQLiteBackend)
    MigrationRunner(backend=backend)
    ddl = backend.execute_write.call_args_list[-1].args[0]
    assert "id INTEGER PRIMARY KEY AUTOINCREMENT" in ddl
    assert "version INTEGER NOT NULL" in ddl


def test_postgres_rollback_history_error_is_logged(caplog):
    psycopg2 = pytest.importorskip("psycopg2")
    backend = MagicMock(spec=PostgreSQLBackend)
    backend.execute_write.side_effect = [None, psycopg2.Error("cannot create audit table")]
    with caplog.at_level(logging.DEBUG, logger="aragora.migrations.runner"):
        MigrationRunner(backend=backend)
    assert "Could not create rollback history table: cannot create audit table" in caplog.text


def test_sqlite_rollback_history_error_is_still_logged(caplog):
    backend = MagicMock(spec=SQLiteBackend)
    backend.execute_write.side_effect = [None, sqlite3.OperationalError("read only")]
    with caplog.at_level(logging.DEBUG, logger="aragora.migrations.runner"):
        MigrationRunner(backend=backend)
    assert "Could not create rollback history table: read only" in caplog.text


@pytest.mark.parametrize("command", ["upgrade", "status", "downgrade", "rollback_history"])
@pytest.mark.parametrize("phase", ["connect", "execute"])
def test_cli_reports_postgres_errors_and_resets_runner(command, phase, capsys):
    psycopg2 = pytest.importorskip("psycopg2")
    error = psycopg2.OperationalError("password authentication failed")
    args = argparse.Namespace(db_path="unused.db", database_url=None, target=None)
    with (
        patch.object(cli, "get_migration_runner") as get_runner,
        patch.object(cli, "reset_runner") as reset,
    ):
        if phase == "connect":
            get_runner.side_effect = error
        else:
            method = "get_rollback_history" if command == "rollback_history" else command
            getattr(get_runner.return_value, method).side_effect = error
        assert getattr(cli, f"cmd_{command}")(args) == 1
        reset.assert_called_once_with()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "Error: password authentication failed\n"
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("operation", ["create", "drop"])
@pytest.mark.parametrize("fails", [False, True])
def test_concurrent_indexes_restore_connection_autocommit(operation, fails):
    psycopg2 = pytest.importorskip("psycopg2")
    from aragora.migrations.patterns import safe_create_index, safe_drop_index

    backend = MagicMock(spec=PostgreSQLBackend)
    backend.backend_type = "postgresql"
    connection = backend.connection.return_value.__enter__.return_value
    connection.autocommit = False
    connection.closed = False
    cursor = connection.cursor.return_value.__enter__.return_value

    def execute(statement):
        assert connection.autocommit is True
        assert "INDEX CONCURRENTLY" in statement
        if fails:
            raise psycopg2.Error("index failure")

    cursor.execute.side_effect = execute

    def run():
        if operation == "create":
            safe_create_index(backend, "test_idx", "test_table", ["id"])
        else:
            safe_drop_index(backend, "test_idx")

    if fails:
        with pytest.raises(psycopg2.Error, match="index failure"):
            run()
    else:
        run()
    cursor.execute.assert_called_once()
    backend.execute_write.assert_not_called()
    assert connection.autocommit is False


@pytest.mark.parametrize("operation", ["upgrade", "downgrade"])
def test_database_failure_logs_migration_version(operation, caplog):
    psycopg2 = pytest.importorskip("psycopg2")
    runner = MigrationRunner(backend=MagicMock(spec=SQLiteBackend))
    fail = MagicMock(side_effect=psycopg2.Error("migration failure"))
    runner.register(Migration(version=123, name="failing", up_fn=fail, down_fn=fail))
    applied = [123] if operation == "downgrade" else []
    with patch.object(runner, "get_applied_versions", return_value=applied):
        with pytest.raises(psycopg2.Error, match="migration failure"):
            getattr(runner, operation)()
    action = "apply" if operation == "upgrade" else "rollback"
    assert f"Failed to {action} migration 123: migration failure" in caplog.text


def test_postgres_rollback_history_insert_failure_is_nonfatal(caplog):
    psycopg2 = pytest.importorskip("psycopg2")
    backend = MagicMock(spec=PostgreSQLBackend)
    runner = MigrationRunner(backend=backend)
    backend.execute_write.side_effect = psycopg2.Error("audit table unavailable")
    runner._record_rollback(Migration(version=123, name="rolled_back", up_sql="SELECT 1"))
    assert "Failed to record rollback history for v123: audit table unavailable" in caplog.text


def test_concurrent_index_does_not_restore_closed_connection():
    psycopg2 = pytest.importorskip("psycopg2")
    from aragora.migrations.patterns import safe_drop_index

    backend = MagicMock(spec=PostgreSQLBackend)
    connection = backend.connection.return_value.__enter__.return_value
    autocommit = PropertyMock(
        side_effect=[False, None, psycopg2.InterfaceError("connection already closed")]
    )
    type(connection).autocommit = autocommit
    connection.closed = False

    def disconnect(statement):
        connection.closed = True
        raise psycopg2.OperationalError("server closed during index operation")

    connection.cursor.return_value.__enter__.return_value.execute.side_effect = disconnect
    with pytest.raises(psycopg2.OperationalError, match="server closed during index operation"):
        safe_drop_index(backend, "test_idx")
    assert autocommit.call_count == 2


def test_sqlite_cli_works_without_psycopg2(tmp_path):
    env = os.environ.copy()
    for key in ("DATABASE_URL", "ARAGORA_DATABASE_URL"):
        env.pop(key, None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy, sys; sys.modules['psycopg2'] = None; "
            "runpy.run_module('aragora.migrations', run_name='__main__')",
            "status",
            "--db-path",
            str(tmp_path / "sqlite-only.db"),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "  Backend: sqlite\n" in result.stdout
