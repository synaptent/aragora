"""
SQL injection prevention tests.

Verifies that SQL identifier validation blocks injection attempts
in PRAGMA statements and other dynamic SQL.
"""

import pytest
import sqlite3
import tempfile
import os

from aragora.storage.debate_storage import _validate_sql_identifier


class TestSqlIdentifierValidation:
    """Test _validate_sql_identifier blocks injection patterns."""

    def test_valid_simple_name(self):
        """Valid simple table names should pass."""
        assert _validate_sql_identifier("users") is True
        assert _validate_sql_identifier("debate_logs") is True
        assert _validate_sql_identifier("elo_ratings") is True

    def test_valid_with_numbers(self):
        """Names with numbers should pass."""
        assert _validate_sql_identifier("table1") is True
        assert _validate_sql_identifier("v2_users") is True

    def test_valid_starts_with_underscore(self):
        """Names starting with underscore should pass."""
        assert _validate_sql_identifier("_private") is True
        assert _validate_sql_identifier("__dunder__") is True

    def test_rejects_semicolon_injection(self):
        """Semicolons used for SQL injection should be rejected."""
        assert _validate_sql_identifier("users; DROP TABLE users; --") is False

    def test_rejects_comment_injection(self):
        """SQL comments used for injection should be rejected."""
        assert _validate_sql_identifier("users--") is False
        assert _validate_sql_identifier("users/*comment*/") is False

    def test_rejects_parentheses(self):
        """Parentheses used for subqueries should be rejected."""
        assert _validate_sql_identifier("users()") is False
        assert _validate_sql_identifier("(SELECT * FROM secrets)") is False

    def test_rejects_quotes(self):
        """Quote characters should be rejected."""
        assert _validate_sql_identifier("users'") is False
        assert _validate_sql_identifier('users"') is False
        assert _validate_sql_identifier("users`") is False

    def test_rejects_union_injection(self):
        """UNION-based injection patterns should be rejected."""
        assert _validate_sql_identifier("users UNION SELECT * FROM passwords") is False

    def test_rejects_empty_string(self):
        """Empty strings should be rejected."""
        assert _validate_sql_identifier("") is False

    def test_rejects_whitespace_only(self):
        """Whitespace-only strings should be rejected."""
        assert _validate_sql_identifier("   ") is False
        assert _validate_sql_identifier("\t\n") is False

    def test_rejects_spaces_in_name(self):
        """Names with embedded spaces should be rejected."""
        assert _validate_sql_identifier("user name") is False
        assert _validate_sql_identifier("table name") is False

    def test_rejects_sql_keywords_as_injection(self):
        """SQL keywords embedded in strings should be rejected."""
        assert _validate_sql_identifier("users; SELECT") is False
        assert _validate_sql_identifier("users DROP") is False

    def test_rejects_null_bytes(self):
        """Null bytes should be rejected."""
        assert _validate_sql_identifier("users\x00") is False

    def test_rejects_unicode_escapes(self):
        """Unicode escape sequences should be rejected."""
        assert _validate_sql_identifier("users\u0000") is False

    def test_rejects_backslash(self):
        """Backslashes should be rejected."""
        assert _validate_sql_identifier("users\\") is False

    def test_rejects_equals(self):
        """Equals signs should be rejected."""
        assert _validate_sql_identifier("users=1") is False

    def test_rejects_pipes(self):
        """Pipe characters should be rejected."""
        assert _validate_sql_identifier("users||'injected'") is False

    def test_rejects_at_sign(self):
        """At signs should be rejected."""
        assert _validate_sql_identifier("@variable") is False

    def test_rejects_dollar_sign(self):
        """Dollar signs should be rejected."""
        assert _validate_sql_identifier("$variable") is False

    def test_rejects_hash(self):
        """Hash characters should be rejected."""
        assert _validate_sql_identifier("#comment") is False

    def test_rejects_percent(self):
        """Percent signs should be rejected."""
        assert _validate_sql_identifier("%wildcard%") is False

    def test_rejects_ampersand(self):
        """Ampersands should be rejected."""
        assert _validate_sql_identifier("users&admin") is False

    def test_rejects_asterisk(self):
        """Asterisks should be rejected."""
        assert _validate_sql_identifier("users*") is False

    def test_rejects_plus(self):
        """Plus signs should be rejected."""
        assert _validate_sql_identifier("users+1") is False

    def test_rejects_less_greater(self):
        """Less than and greater than should be rejected."""
        assert _validate_sql_identifier("users<>admin") is False
        assert _validate_sql_identifier("users>1") is False

    def test_rejects_exclamation(self):
        """Exclamation marks should be rejected."""
        assert _validate_sql_identifier("users!=admin") is False

    def test_rejects_question_mark(self):
        """Question marks should be rejected."""
        assert _validate_sql_identifier("users?") is False

    def test_rejects_caret(self):
        """Carets should be rejected."""
        assert _validate_sql_identifier("users^admin") is False

    def test_rejects_tilde(self):
        """Tildes should be rejected."""
        assert _validate_sql_identifier("~users") is False

    def test_rejects_brackets(self):
        """Square brackets should be rejected."""
        assert _validate_sql_identifier("users[0]") is False
        assert _validate_sql_identifier("[users]") is False

    def test_rejects_braces(self):
        """Curly braces should be rejected."""
        assert _validate_sql_identifier("users{}") is False
        assert _validate_sql_identifier("{fn now()}") is False

    def test_rejects_colon(self):
        """Colons should be rejected."""
        assert _validate_sql_identifier("users:password") is False

    def test_rejects_comma(self):
        """Commas should be rejected."""
        assert _validate_sql_identifier("users,passwords") is False

    def test_rejects_period(self):
        """Periods should be rejected (could indicate schema.table)."""
        assert _validate_sql_identifier("main.users") is False

    def test_rejects_leading_digit(self):
        """Names starting with digits should be rejected."""
        assert _validate_sql_identifier("1users") is False
        assert _validate_sql_identifier("123") is False

    def test_rejects_hyphen(self):
        """Hyphens should be rejected."""
        assert _validate_sql_identifier("user-name") is False


class TestLikeEscaping:
    """Test LIKE pattern escaping for injection prevention."""

    def test_escape_percent(self):
        """Percent signs in LIKE should be escaped."""
        from aragora.storage.debate_storage import _escape_like_pattern

        assert _escape_like_pattern("100%") == "100\\%"

    def test_escape_underscore(self):
        """Underscores in LIKE should be escaped."""
        from aragora.storage.debate_storage import _escape_like_pattern

        assert _escape_like_pattern("user_name") == "user\\_name"

    def test_escape_backslash(self):
        """Backslashes in LIKE should be escaped."""
        from aragora.storage.debate_storage import _escape_like_pattern

        assert _escape_like_pattern("path\\file") == "path\\\\file"

    def test_escape_combined(self):
        """Multiple special chars should all be escaped."""
        from aragora.storage.debate_storage import _escape_like_pattern

        assert _escape_like_pattern("100%_test\\end") == "100\\%\\_test\\\\end"


class TestAuthEnforcement:
    """Test @require_auth decorator enforcement."""

    def test_require_auth_blocks_without_token(self):
        """require_auth should block requests without token."""
        from aragora.server.handlers.base import require_auth, error_response

        class MockHandler:
            headers = {}

        @require_auth
        def sensitive_endpoint(handler):
            return {"success": True}

        result = sensitive_endpoint(handler=MockHandler())
        assert result.status_code == 401

    def test_require_auth_blocks_invalid_token(self):
        """require_auth should block requests with invalid token."""
        from aragora.server.handlers.base import require_auth
        from aragora.server.auth import auth_config
        import os

        # Set a known token
        original_token = auth_config.api_token
        os.environ["ARAGORA_API_TOKEN"] = "valid-secret-token"
        auth_config.api_token = "valid-secret-token"

        try:

            class MockHandler:
                headers = {"Authorization": "Bearer wrong-token"}

            @require_auth
            def sensitive_endpoint(handler):
                return {"success": True}

            result = sensitive_endpoint(handler=MockHandler())
            assert result.status_code == 401
        finally:
            # Restore
            if original_token:
                os.environ["ARAGORA_API_TOKEN"] = original_token
                auth_config.api_token = original_token
            else:
                os.environ.pop("ARAGORA_API_TOKEN", None)
                auth_config.api_token = None

    def test_require_auth_allows_valid_token(self):
        """require_auth should allow requests with valid token."""
        from aragora.server.handlers.base import require_auth, json_response
        from aragora.server.auth import auth_config
        import os

        # Set a known secret key
        original_token = auth_config.api_token
        os.environ["ARAGORA_API_TOKEN"] = "valid-secret-key"
        auth_config.api_token = "valid-secret-key"

        try:
            # Generate a properly signed token
            valid_token = auth_config.generate_token(loop_id="test")

            class MockHandler:
                headers = {"Authorization": f"Bearer {valid_token}"}

            @require_auth
            def sensitive_endpoint(handler):
                return json_response({"success": True})

            result = sensitive_endpoint(handler=MockHandler())
            assert result.status_code == 200
        finally:
            # Restore
            if original_token:
                os.environ["ARAGORA_API_TOKEN"] = original_token
                auth_config.api_token = original_token
            else:
                os.environ.pop("ARAGORA_API_TOKEN", None)
                auth_config.api_token = None

    def test_require_auth_no_handler(self):
        """require_auth should reject when no handler is provided."""
        from aragora.server.handlers.base import require_auth

        @require_auth
        def sensitive_endpoint():
            return {"success": True}

        result = sensitive_endpoint()
        assert result.status_code == 401


class TestDatabaseResilience:
    """Test ResilientConnection retry behavior."""

    def test_is_transient_error_locked(self):
        """database is locked should be transient."""
        from aragora.storage.resilience import is_transient_error

        class MockError(Exception):
            pass

        assert is_transient_error(MockError("database is locked"))
        assert is_transient_error(MockError("Database is LOCKED"))  # Case insensitive

    def test_is_transient_error_busy(self):
        """database is busy should be transient."""
        from aragora.storage.resilience import is_transient_error

        class MockError(Exception):
            pass

        assert is_transient_error(MockError("database is busy"))

    def test_is_transient_error_disk_io(self):
        """disk i/o error should be transient."""
        from aragora.storage.resilience import is_transient_error

        class MockError(Exception):
            pass

        assert is_transient_error(MockError("disk i/o error"))
        assert is_transient_error(MockError("Disk I/O Error"))  # Case insensitive

    def test_is_not_transient_error(self):
        """Other errors should not be transient."""
        from aragora.storage.resilience import is_transient_error

        class MockError(Exception):
            pass

        assert not is_transient_error(MockError("syntax error"))
        assert not is_transient_error(MockError("table not found"))
        assert not is_transient_error(MockError("constraint violation"))

    def test_resilient_connection_success(self):
        """ResilientConnection should work for successful operations."""
        from aragora.storage.resilience import ResilientConnection

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = ResilientConnection(db_path)
            with conn.transaction() as cursor:
                cursor.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
                cursor.execute("INSERT INTO test (name) VALUES (?)", ("hello",))

            # Verify insert worked
            with conn.transaction() as cursor:
                cursor.execute("SELECT name FROM test WHERE id = 1")
                row = cursor.fetchone()
                assert row["name"] == "hello"
        finally:
            os.unlink(db_path)

    def test_resilient_connection_execute(self):
        """ResilientConnection.execute should work."""
        from aragora.storage.resilience import ResilientConnection

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = ResilientConnection(db_path)
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
            rowid = conn.execute("INSERT INTO test (name) VALUES (?)", ("test",))
            assert rowid == 1

            rows = conn.execute("SELECT * FROM test", fetch=True)
            assert len(rows) == 1
            assert rows[0]["name"] == "test"
        finally:
            os.unlink(db_path)

    def test_resilient_connection_executemany(self):
        """ResilientConnection.executemany should work."""
        from aragora.storage.resilience import ResilientConnection

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            conn = ResilientConnection(db_path)
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")

            data = [("a",), ("b",), ("c",)]
            count = conn.executemany("INSERT INTO test (name) VALUES (?)", data)
            assert count == 3

            rows = conn.execute("SELECT * FROM test", fetch=True)
            assert len(rows) == 3
        finally:
            os.unlink(db_path)


class TestConnectionPool:
    """Test ConnectionPool behavior."""

    def test_pool_reuses_connections(self):
        """ConnectionPool should reuse healthy connections."""
        from aragora.storage.resilience import ConnectionPool

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            pool = ConnectionPool(db_path, max_connections=2)

            # Use and release a connection
            with pool.get_connection() as conn1:
                conn1.execute("SELECT 1")
                id1 = id(conn1)

            # Should get the same connection back
            with pool.get_connection() as conn2:
                id2 = id(conn2)

            assert id1 == id2

            pool.close_all()
        finally:
            os.unlink(db_path)

    def test_pool_respects_max_connections(self):
        """ConnectionPool should not exceed max_connections."""
        from aragora.storage.resilience import ConnectionPool

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            pool = ConnectionPool(db_path, max_connections=1)

            # Get connection and return it
            with pool.get_connection():
                pass

            # Get another and return it
            with pool.get_connection():
                pass

            # Pool should only have 1 connection
            assert len(pool._pool) <= 1

            pool.close_all()
        finally:
            os.unlink(db_path)

    def test_pool_close_all(self):
        """ConnectionPool.close_all should clear the pool."""
        from aragora.storage.resilience import ConnectionPool

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            pool = ConnectionPool(db_path)

            # Create some connections
            with pool.get_connection():
                pass
            with pool.get_connection():
                pass

            pool.close_all()
            assert len(pool._pool) == 0
            assert len(pool._in_use) == 0
        finally:
            os.unlink(db_path)
