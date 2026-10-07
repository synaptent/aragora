"""
Tests for Audit Log System.

Comprehensive test suite for the audit logging module covering:
- AuditEvent creation and serialization
- AuditLog initialization and database backends
- Event logging with hash chain integrity
- Query operations
- Integrity verification
- Export functions (JSON, CSV, SOC2)
- Retention policy application
- Convenience functions
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aragora.observability.audit_log import (
    AUDIT_COLUMNS,
    AuditCategory,
    AuditEvent,
    AuditLog,
    AuditOutcome,
    AuditQuery,
    SQLiteBackend,
    audit_admin_action,
    audit_auth_login,
    audit_data_access,
    get_audit_log,
    reset_audit_log,
)


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database path for testing."""
    return tmp_path / "audit.db"


@pytest.fixture
def audit_log(temp_db_path):
    """Create a fresh AuditLog instance for testing."""
    # Reset singleton to ensure clean state
    reset_audit_log()
    # Clear environment variables that could affect backend selection
    with patch.dict(os.environ, {}, clear=True):
        log = AuditLog(db_path=temp_db_path)
    yield log
    # Cleanup
    log._backend.close_all()


@pytest.fixture
def sample_event():
    """Create a sample AuditEvent for testing."""
    return AuditEvent(
        category=AuditCategory.AUTH,
        action="login",
        actor_id="user_123",
        resource_type="session",
        resource_id="sess_abc",
        outcome=AuditOutcome.SUCCESS,
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
        org_id="org_456",
        details={"method": "password"},
    )


# ===========================================================================
# Tests: AuditCategory Enum
# ===========================================================================


class TestAuditCategory:
    """Tests for AuditCategory enum."""

    def test_all_categories_exist(self):
        """Test all audit categories exist."""
        assert AuditCategory.AUTH.value == "auth"
        assert AuditCategory.ACCESS.value == "access"
        assert AuditCategory.DATA.value == "data"
        assert AuditCategory.ADMIN.value == "admin"
        assert AuditCategory.BILLING.value == "billing"
        assert AuditCategory.DEBATE.value == "debate"
        assert AuditCategory.API.value == "api"
        assert AuditCategory.SECURITY.value == "security"
        assert AuditCategory.SYSTEM.value == "system"

    def test_category_is_enum(self):
        """Test that categories are proper enums."""
        assert isinstance(AuditCategory.AUTH, AuditCategory)
        assert AuditCategory.AUTH != "auth"  # Enum vs string comparison


# ===========================================================================
# Tests: AuditOutcome Enum
# ===========================================================================


class TestAuditOutcome:
    """Tests for AuditOutcome enum."""

    def test_all_outcomes_exist(self):
        """Test all audit outcomes exist."""
        assert AuditOutcome.SUCCESS.value == "success"
        assert AuditOutcome.FAILURE.value == "failure"
        assert AuditOutcome.DENIED.value == "denied"
        assert AuditOutcome.ERROR.value == "error"


# ===========================================================================
# Tests: AuditEvent Dataclass
# ===========================================================================


class TestAuditEvent:
    """Tests for AuditEvent dataclass."""

    def test_creation_with_required_fields(self):
        """Test creating an event with required fields only."""
        event = AuditEvent(
            category=AuditCategory.AUTH,
            action="login",
            actor_id="user_123",
        )

        assert event.category == AuditCategory.AUTH
        assert event.action == "login"
        assert event.actor_id == "user_123"
        assert event.outcome == AuditOutcome.SUCCESS  # Default
        assert event.id is not None
        assert event.timestamp is not None

    def test_creation_with_all_fields(self, sample_event):
        """Test creating an event with all fields."""
        assert sample_event.category == AuditCategory.AUTH
        assert sample_event.action == "login"
        assert sample_event.actor_id == "user_123"
        assert sample_event.resource_type == "session"
        assert sample_event.resource_id == "sess_abc"
        assert sample_event.outcome == AuditOutcome.SUCCESS
        assert sample_event.ip_address == "192.168.1.1"
        assert sample_event.org_id == "org_456"
        assert sample_event.details == {"method": "password"}

    def test_compute_hash(self, sample_event):
        """Test hash computation."""
        sample_event.previous_hash = "abc123"
        hash_value = sample_event.compute_hash()

        assert hash_value is not None
        assert len(hash_value) == 32  # SHA-256 truncated to 32 chars
        assert isinstance(hash_value, str)

    def test_hash_changes_with_content(self):
        """Test that hash changes when content changes."""
        event1 = AuditEvent(
            category=AuditCategory.AUTH,
            action="login",
            actor_id="user_123",
        )
        event2 = AuditEvent(
            category=AuditCategory.AUTH,
            action="logout",
            actor_id="user_123",
        )

        hash1 = event1.compute_hash()
        hash2 = event2.compute_hash()

        assert hash1 != hash2

    def test_to_dict(self, sample_event):
        """Test converting event to dictionary."""
        result = sample_event.to_dict()

        assert result["category"] == "auth"
        assert result["action"] == "login"
        assert result["actor_id"] == "user_123"
        assert result["resource_type"] == "session"
        assert result["outcome"] == "success"
        assert result["details"] == {"method": "password"}
        assert "timestamp" in result
        assert "id" in result

    def test_from_dict(self):
        """Test creating event from dictionary."""
        data = {
            "id": "event_123",
            "timestamp": "2024-01-15T10:30:00",
            "category": "auth",
            "action": "login",
            "actor_id": "user_456",
            "resource_type": "session",
            "resource_id": "sess_789",
            "outcome": "success",
            "ip_address": "10.0.0.1",
            "details": {"key": "value"},
        }

        event = AuditEvent.from_dict(data)

        assert event.id == "event_123"
        assert event.category == AuditCategory.AUTH
        assert event.action == "login"
        assert event.actor_id == "user_456"
        assert event.outcome == AuditOutcome.SUCCESS
        assert event.details == {"key": "value"}

    def test_from_dict_with_minimal_data(self):
        """Test creating event from minimal dictionary."""
        data = {
            "action": "test",
            "actor_id": "user_1",
        }

        event = AuditEvent.from_dict(data)

        assert event.action == "test"
        assert event.actor_id == "user_1"
        assert event.category == AuditCategory.SYSTEM  # Default
        assert event.outcome == AuditOutcome.SUCCESS  # Default


# ===========================================================================
# Tests: AuditQuery Dataclass
# ===========================================================================


class TestAuditQuery:
    """Tests for AuditQuery dataclass."""

    def test_default_values(self):
        """Test AuditQuery default values."""
        query = AuditQuery()

        assert query.start_date is None
        assert query.end_date is None
        assert query.category is None
        assert query.action is None
        assert query.actor_id is None
        assert query.limit == 1000
        assert query.offset == 0

    def test_creation_with_filters(self):
        """Test AuditQuery with filters."""
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 31, tzinfo=timezone.utc)

        query = AuditQuery(
            start_date=start,
            end_date=end,
            category=AuditCategory.AUTH,
            actor_id="user_123",
            outcome=AuditOutcome.FAILURE,
            limit=100,
        )

        assert query.start_date == start
        assert query.end_date == end
        assert query.category == AuditCategory.AUTH
        assert query.actor_id == "user_123"
        assert query.outcome == AuditOutcome.FAILURE
        assert query.limit == 100


# ===========================================================================
# Tests: SQLiteBackend
# ===========================================================================


class TestSQLiteBackend:
    """Tests for SQLiteBackend class."""

    def test_create_backend(self, temp_db_path):
        """Test creating SQLite backend."""
        backend = SQLiteBackend(temp_db_path)

        assert backend.db_path == temp_db_path

    def test_execute_write(self, temp_db_path):
        """Test executing write operations."""
        backend = SQLiteBackend(temp_db_path)

        # Create a test table
        backend.execute_write(
            "CREATE TABLE IF NOT EXISTS test_table (id TEXT PRIMARY KEY, name TEXT)"
        )
        backend.execute_write("INSERT INTO test_table VALUES (?, ?)", ("1", "test"))

        # Verify
        row = backend.fetch_one("SELECT name FROM test_table WHERE id = ?", ("1",))
        assert row[0] == "test"

        backend.close_all()

    def test_fetch_all(self, temp_db_path):
        """Test fetching all rows."""
        backend = SQLiteBackend(temp_db_path)

        backend.execute_write("CREATE TABLE test (id INTEGER)")
        for i in range(5):
            backend.execute_write("INSERT INTO test VALUES (?)", (i,))

        rows = backend.fetch_all("SELECT * FROM test ORDER BY id")

        assert len(rows) == 5
        assert rows[0][0] == 0
        assert rows[4][0] == 4

        backend.close_all()

    def test_close(self, temp_db_path):
        """Test closing connection."""
        backend = SQLiteBackend(temp_db_path)
        backend.execute_write("CREATE TABLE test (id INTEGER)")

        backend.close()

        # Connection should be reset
        assert backend._conn_var.get() is None


# ===========================================================================
# Tests: AuditLog Initialization
# ===========================================================================


class TestAuditLogInit:
    """Tests for AuditLog initialization."""

    def test_create_with_default_path(self, tmp_path):
        """Test creating audit log with default path."""
        reset_audit_log()
        with patch.dict(os.environ, {}, clear=True):
            with patch("aragora.observability.audit_log.Path") as mock_path:
                mock_path.return_value = tmp_path / "audit.db"
                # We need to patch at the right place
                log = AuditLog(db_path=tmp_path / "audit.db")

        assert log._backend_type == "sqlite"
        log._backend.close_all()

    def test_create_with_custom_path(self, temp_db_path):
        """Test creating audit log with custom path."""
        reset_audit_log()
        with patch.dict(os.environ, {}, clear=True):
            log = AuditLog(db_path=temp_db_path)

        assert log.db_path == temp_db_path
        log._backend.close_all()

    def test_custom_retention_days(self, temp_db_path):
        """Test custom retention days."""
        reset_audit_log()
        with patch.dict(os.environ, {}, clear=True):
            log = AuditLog(db_path=temp_db_path, retention_days=30)

        assert log.retention_days == 30
        log._backend.close_all()

    def test_default_retention_7_years(self, temp_db_path):
        """Test default retention is 7 years (SOX requirement)."""
        reset_audit_log()
        with patch.dict(os.environ, {}, clear=True):
            log = AuditLog(db_path=temp_db_path)

        assert log.retention_days == 365 * 7
        log._backend.close_all()


# ===========================================================================
# Tests: Event Logging
# ===========================================================================


class TestEventLogging:
    """Tests for event logging functionality."""

    def test_log_simple_event(self, audit_log, sample_event):
        """Test logging a simple event."""
        event_id = audit_log.log(sample_event)

        assert event_id is not None
        assert event_id == sample_event.id

    def test_log_sets_hash_chain(self, audit_log):
        """Test that logging sets hash chain correctly."""
        event1 = AuditEvent(
            category=AuditCategory.AUTH,
            action="login",
            actor_id="user_1",
        )
        event2 = AuditEvent(
            category=AuditCategory.AUTH,
            action="logout",
            actor_id="user_1",
        )

        audit_log.log(event1)
        audit_log.log(event2)

        # Event 2's previous_hash should be event 1's hash
        assert event2.previous_hash == event1.event_hash
        assert event2.event_hash != event1.event_hash

    def test_log_computes_hash(self, audit_log, sample_event):
        """Test that logging computes event hash."""
        assert sample_event.event_hash == ""

        audit_log.log(sample_event)

        assert sample_event.event_hash != ""
        assert len(sample_event.event_hash) == 32

    def test_log_multiple_events(self, audit_log):
        """Test logging multiple events."""
        events = []
        for i in range(10):
            event = AuditEvent(
                category=AuditCategory.AUTH,
                action=f"action_{i}",
                actor_id=f"user_{i}",
            )
            audit_log.log(event)
            events.append(event)

        # Verify hash chain
        for i in range(1, len(events)):
            assert events[i].previous_hash == events[i - 1].event_hash


# ===========================================================================
# Tests: Query Operations
# ===========================================================================


class TestQueryOperations:
    """Tests for query operations."""

    def test_query_all_events(self, audit_log):
        """Test querying all events."""
        # Log some events
        for i in range(5):
            audit_log.log(
                AuditEvent(
                    category=AuditCategory.AUTH,
                    action=f"action_{i}",
                    actor_id="user_1",
                )
            )

        result = audit_log.query(AuditQuery())

        assert len(result) == 5

    def test_query_by_category(self, audit_log):
        """Test querying by category."""
        audit_log.log(AuditEvent(category=AuditCategory.AUTH, action="login", actor_id="user_1"))
        audit_log.log(AuditEvent(category=AuditCategory.DATA, action="read", actor_id="user_1"))
        audit_log.log(AuditEvent(category=AuditCategory.AUTH, action="logout", actor_id="user_1"))

        result = audit_log.query(AuditQuery(category=AuditCategory.AUTH))

        assert len(result) == 2
        assert all(e.category == AuditCategory.AUTH for e in result)

    def test_query_by_actor(self, audit_log):
        """Test querying by actor_id."""
        audit_log.log(AuditEvent(category=AuditCategory.AUTH, action="login", actor_id="user_1"))
        audit_log.log(AuditEvent(category=AuditCategory.AUTH, action="login", actor_id="user_2"))
        audit_log.log(AuditEvent(category=AuditCategory.AUTH, action="login", actor_id="user_1"))

        result = audit_log.query(AuditQuery(actor_id="user_1"))

        assert len(result) == 2
        assert all(e.actor_id == "user_1" for e in result)

    def test_query_by_date_range(self, audit_log):
        """Test querying by date range."""
        # Log events
        event = AuditEvent(category=AuditCategory.AUTH, action="login", actor_id="user_1")
        audit_log.log(event)

        # Query with date range
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)

        result = audit_log.query(AuditQuery(start_date=start, end_date=end))

        assert len(result) == 1

    def test_query_by_outcome(self, audit_log):
        """Test querying by outcome."""
        audit_log.log(
            AuditEvent(
                category=AuditCategory.AUTH,
                action="login",
                actor_id="user_1",
                outcome=AuditOutcome.SUCCESS,
            )
        )
        audit_log.log(
            AuditEvent(
                category=AuditCategory.AUTH,
                action="login",
                actor_id="user_2",
                outcome=AuditOutcome.FAILURE,
            )
        )

        result = audit_log.query(AuditQuery(outcome=AuditOutcome.FAILURE))

        assert len(result) == 1
        assert result[0].outcome == AuditOutcome.FAILURE

    def test_query_with_limit(self, audit_log):
        """Test querying with limit."""
        for i in range(10):
            audit_log.log(
                AuditEvent(category=AuditCategory.AUTH, action=f"action_{i}", actor_id="user_1")
            )

        result = audit_log.query(AuditQuery(limit=5))

        assert len(result) == 5

    def test_query_with_offset(self, audit_log):
        """Test querying with offset."""
        for i in range(10):
            audit_log.log(
                AuditEvent(category=AuditCategory.AUTH, action=f"action_{i}", actor_id="user_1")
            )

        result = audit_log.query(AuditQuery(limit=5, offset=5))

        assert len(result) == 5

    def test_query_by_resource(self, audit_log):
        """Test querying by resource type and id."""
        audit_log.log(
            AuditEvent(
                category=AuditCategory.DATA,
                action="read",
                actor_id="user_1",
                resource_type="document",
                resource_id="doc_123",
            )
        )
        audit_log.log(
            AuditEvent(
                category=AuditCategory.DATA,
                action="write",
                actor_id="user_1",
                resource_type="debate",
                resource_id="debate_456",
            )
        )

        result = audit_log.query(AuditQuery(resource_type="document", resource_id="doc_123"))

        assert len(result) == 1
        assert result[0].resource_type == "document"

    def test_query_by_org_id(self, audit_log):
        """Test querying by organization ID."""
        audit_log.log(
            AuditEvent(
                category=AuditCategory.AUTH,
                action="login",
                actor_id="user_1",
                org_id="org_1",
            )
        )
        audit_log.log(
            AuditEvent(
                category=AuditCategory.AUTH,
                action="login",
                actor_id="user_2",
                org_id="org_2",
            )
        )

        result = audit_log.query(AuditQuery(org_id="org_1"))

        assert len(result) == 1
        assert result[0].org_id == "org_1"


# ===========================================================================
# Tests: Integrity Verification
# ===========================================================================


class TestIntegrityVerification:
    """Tests for integrity verification."""

    def test_verify_empty_log(self, audit_log):
        """Test verifying empty audit log."""
        is_valid, errors = audit_log.verify_integrity()

        assert is_valid is True
        assert len(errors) == 0

    def test_verify_valid_chain(self, audit_log):
        """Test verifying a valid hash chain."""
        for i in range(5):
            audit_log.log(
                AuditEvent(category=AuditCategory.AUTH, action=f"action_{i}", actor_id="user_1")
            )

        is_valid, errors = audit_log.verify_integrity()

        assert is_valid is True
        assert len(errors) == 0

    def test_verify_detects_tampering(self, audit_log):
        """Test that verification detects tampering."""
        # Log events
        for i in range(3):
            audit_log.log(
                AuditEvent(category=AuditCategory.AUTH, action=f"action_{i}", actor_id="user_1")
            )

        # Tamper with the database directly
        audit_log._backend.execute_write(
            "UPDATE audit_events SET action = ? WHERE action = ?",
            ("tampered_action", "action_1"),
        )

        is_valid, errors = audit_log.verify_integrity()

        assert is_valid is False
        assert len(errors) > 0
        assert "mismatch" in errors[0].lower()

    def test_verify_with_date_range(self, audit_log):
        """Test verifying with date range."""
        for i in range(3):
            audit_log.log(
                AuditEvent(category=AuditCategory.AUTH, action=f"action_{i}", actor_id="user_1")
            )

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)

        is_valid, errors = audit_log.verify_integrity(start_date=start, end_date=end)

        assert is_valid is True


# ===========================================================================
# Tests: Export Functions
# ===========================================================================


class TestExportFunctions:
    """Tests for export functions."""

    def test_export_json(self, audit_log, tmp_path):
        """Test exporting to JSON."""
        # Log some events
        for i in range(3):
            audit_log.log(
                AuditEvent(category=AuditCategory.AUTH, action=f"action_{i}", actor_id="user_1")
            )

        output_path = tmp_path / "export.json"
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)

        count = audit_log.export_json(output_path, start, end)

        assert count == 3
        assert output_path.exists()

        # Verify content
        with open(output_path) as f:
            data = json.load(f)

        assert data["event_count"] == 3
        assert len(data["events"]) == 3

    def test_export_csv(self, audit_log, tmp_path):
        """Test exporting to CSV."""
        # Log some events
        for i in range(3):
            audit_log.log(
                AuditEvent(
                    category=AuditCategory.AUTH,
                    action=f"action_{i}",
                    actor_id="user_1",
                    org_id="org_1",
                )
            )

        output_path = tmp_path / "export.csv"
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)

        count = audit_log.export_csv(output_path, start, end)

        assert count == 3
        assert output_path.exists()

        # Verify content
        with open(output_path) as f:
            content = f.read()

        assert "id" in content
        assert "timestamp" in content
        assert "category" in content
        assert "action_0" in content

    def test_export_soc2(self, audit_log, tmp_path):
        """Test exporting SOC2 report."""
        # Log various events for SOC2 report
        audit_log.log(
            AuditEvent(
                category=AuditCategory.AUTH,
                action="login",
                actor_id="user_1",
                outcome=AuditOutcome.SUCCESS,
            )
        )
        audit_log.log(
            AuditEvent(
                category=AuditCategory.AUTH,
                action="login",
                actor_id="user_2",
                outcome=AuditOutcome.FAILURE,
            )
        )
        audit_log.log(
            AuditEvent(
                category=AuditCategory.ACCESS,
                action="read",
                actor_id="user_1",
                outcome=AuditOutcome.DENIED,
            )
        )
        audit_log.log(
            AuditEvent(
                category=AuditCategory.SECURITY,
                action="alert",
                actor_id="system",
            )
        )

        output_path = tmp_path / "soc2_report.json"
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)

        result = audit_log.export_soc2(output_path, start, end)

        assert result["events_exported"] == 4
        assert result["integrity_verified"] is True
        assert output_path.exists()

        # Verify report content
        with open(output_path) as f:
            report = json.load(f)

        assert report["report_type"] == "SOC 2 Type II Audit Log Export"
        assert report["summary"]["total_events"] == 4
        assert report["security_metrics"]["authentication_failures"] == 1
        assert report["security_metrics"]["access_denials"] == 1
        assert report["security_metrics"]["security_events"] == 1

    def test_export_with_org_filter(self, audit_log, tmp_path):
        """Test export with organization filter."""
        audit_log.log(
            AuditEvent(
                category=AuditCategory.AUTH,
                action="login",
                actor_id="user_1",
                org_id="org_1",
            )
        )
        audit_log.log(
            AuditEvent(
                category=AuditCategory.AUTH,
                action="login",
                actor_id="user_2",
                org_id="org_2",
            )
        )

        output_path = tmp_path / "export.json"
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=1)
        end = now + timedelta(hours=1)

        count = audit_log.export_json(output_path, start, end, org_id="org_1")

        assert count == 1


# ===========================================================================
# Tests: Retention Policy
# ===========================================================================


class TestRetentionPolicy:
    """Tests for retention policy application."""

    def test_apply_retention_deletes_old_events(self, temp_db_path):
        """Test that retention policy deletes old events."""
        reset_audit_log()
        with patch.dict(os.environ, {}, clear=True):
            # Create log with 1 day retention
            log = AuditLog(db_path=temp_db_path, retention_days=1)

        # Log an old event (manually set timestamp)
        old_timestamp = datetime.now(timezone.utc) - timedelta(days=2)
        log._backend.execute_write(
            """
            INSERT INTO audit_events
            (id, timestamp, category, action, actor_id, outcome, event_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "old_event",
                old_timestamp.isoformat(),
                "auth",
                "login",
                "user_1",
                "success",
                "hash123",
            ),
        )

        # Log a new event
        log.log(AuditEvent(category=AuditCategory.AUTH, action="login", actor_id="user_2"))

        # Apply retention
        deleted = log.apply_retention()

        assert deleted == 1

        # Verify old event is gone
        result = log.query(AuditQuery())
        assert len(result) == 1
        assert result[0].actor_id == "user_2"

        log._backend.close_all()

    def test_apply_retention_keeps_recent_events(self, temp_db_path):
        """Test that retention keeps recent events."""
        reset_audit_log()
        with patch.dict(os.environ, {}, clear=True):
            log = AuditLog(db_path=temp_db_path, retention_days=30)

        # Log events
        for i in range(5):
            log.log(
                AuditEvent(category=AuditCategory.AUTH, action=f"action_{i}", actor_id="user_1")
            )

        deleted = log.apply_retention()

        assert deleted == 0

        result = log.query(AuditQuery())
        assert len(result) == 5

        log._backend.close_all()


# ===========================================================================
# Tests: Statistics
# ===========================================================================


class TestStatistics:
    """Tests for audit log statistics."""

    def test_get_stats_empty(self, audit_log):
        """Test getting stats from empty log."""
        stats = audit_log.get_stats()

        assert stats["total_events"] == 0
        assert stats["retention_days"] == 365 * 7

    def test_get_stats_with_events(self, audit_log):
        """Test getting stats with events."""
        audit_log.log(AuditEvent(category=AuditCategory.AUTH, action="login", actor_id="user_1"))
        audit_log.log(AuditEvent(category=AuditCategory.DATA, action="read", actor_id="user_1"))
        audit_log.log(AuditEvent(category=AuditCategory.AUTH, action="logout", actor_id="user_1"))

        stats = audit_log.get_stats()

        assert stats["total_events"] == 3
        assert stats["by_category"]["auth"] == 2
        assert stats["by_category"]["data"] == 1
        assert stats["oldest_event"] is not None
        assert stats["newest_event"] is not None


# ===========================================================================
# Tests: Convenience Functions
# ===========================================================================


class TestConvenienceFunctions:
    """Tests for convenience audit functions."""

    def test_audit_auth_login_success(self, audit_log):
        """Test audit_auth_login with success."""
        event_id = audit_auth_login(
            audit_log, user_id="user_123", ip_address="192.168.1.1", success=True
        )

        assert event_id is not None

        # Verify event was logged
        events = audit_log.query(AuditQuery(actor_id="user_123"))
        assert len(events) == 1
        assert events[0].action == "login"
        assert events[0].outcome == AuditOutcome.SUCCESS

    def test_audit_auth_login_failure(self, audit_log):
        """Test audit_auth_login with failure."""
        event_id = audit_auth_login(
            audit_log,
            user_id="user_123",
            success=False,
            reason="Invalid password",
        )

        events = audit_log.query(AuditQuery(actor_id="user_123"))
        assert len(events) == 1
        assert events[0].outcome == AuditOutcome.FAILURE
        assert events[0].reason == "Invalid password"

    def test_audit_data_access(self, audit_log):
        """Test audit_data_access function."""
        event_id = audit_data_access(
            audit_log,
            user_id="user_123",
            resource_type="document",
            resource_id="doc_456",
            action="read",
            org_id="org_789",
        )

        assert event_id is not None

        events = audit_log.query(AuditQuery(actor_id="user_123"))
        assert len(events) == 1
        assert events[0].category == AuditCategory.ACCESS
        assert events[0].resource_type == "document"
        assert events[0].resource_id == "doc_456"
        assert events[0].org_id == "org_789"

    def test_audit_admin_action(self, audit_log):
        """Test audit_admin_action function."""
        event_id = audit_admin_action(
            audit_log,
            admin_id="admin_1",
            action="delete_user",
            target_type="user",
            target_id="user_to_delete",
            details={"reason": "Policy violation"},
        )

        assert event_id is not None

        events = audit_log.query(AuditQuery(actor_id="admin_1"))
        assert len(events) == 1
        assert events[0].category == AuditCategory.ADMIN
        assert events[0].action == "delete_user"
        assert events[0].details == {"reason": "Policy violation"}


# ===========================================================================
# Tests: Singleton Management
# ===========================================================================


class TestSingletonManagement:
    """Tests for singleton management."""

    def test_reset_audit_log(self, temp_db_path):
        """Test resetting audit log singleton."""
        reset_audit_log()

        # The singleton should be None after reset
        # We can't easily verify the internal state, but we can
        # verify that creating a new instance works
        with patch.dict(os.environ, {}, clear=True):
            log = AuditLog(db_path=temp_db_path)

        assert log is not None
        log._backend.close_all()

    def test_get_audit_log_returns_same_instance(self, temp_db_path, monkeypatch):
        """Test that get_audit_log returns same instance."""
        reset_audit_log()

        # Mock the production guard to allow SQLite
        monkeypatch.setattr(
            "aragora.observability.audit_log.require_distributed_store",
            lambda *args, **kwargs: None,
        )

        with patch.dict(os.environ, {}, clear=True):
            log1 = get_audit_log(db_path=temp_db_path)
            log2 = get_audit_log(db_path=temp_db_path)

        assert log1 is log2

        log1._backend.close_all()
        reset_audit_log()


# ===========================================================================
# Tests: AUDIT_COLUMNS Constant
# ===========================================================================


class TestAuditColumns:
    """Tests for AUDIT_COLUMNS constant."""

    def test_columns_exist(self):
        """Test that all expected columns are defined."""
        expected_columns = [
            "id",
            "timestamp",
            "category",
            "action",
            "actor_id",
            "resource_type",
            "resource_id",
            "outcome",
            "ip_address",
            "user_agent",
            "correlation_id",
            "org_id",
            "workspace_id",
            "details",
            "reason",
            "previous_hash",
            "event_hash",
        ]

        for col in expected_columns:
            assert col in AUDIT_COLUMNS


# ===========================================================================
# Tests: Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_log_event_with_empty_details(self, audit_log):
        """Test logging event with empty details."""
        event = AuditEvent(
            category=AuditCategory.AUTH,
            action="login",
            actor_id="user_1",
            details={},
        )

        event_id = audit_log.log(event)
        assert event_id is not None

    def test_log_event_with_complex_details(self, audit_log):
        """Test logging event with complex details."""
        event = AuditEvent(
            category=AuditCategory.DATA,
            action="update",
            actor_id="user_1",
            details={
                "changes": {"field1": "old", "field2": "new"},
                "nested": {"deep": {"value": 123}},
                "list": [1, 2, 3],
            },
        )

        audit_log.log(event)

        events = audit_log.query(AuditQuery(actor_id="user_1"))
        assert len(events) == 1
        assert events[0].details["changes"]["field1"] == "old"
        assert events[0].details["nested"]["deep"]["value"] == 123

    def test_log_event_with_special_characters(self, audit_log):
        """Test logging event with special characters."""
        event = AuditEvent(
            category=AuditCategory.AUTH,
            action="login",
            actor_id="user_with_'quotes'",
            reason="Failed: Invalid \"password\" <script>alert('xss')</script>",
        )

        audit_log.log(event)

        events = audit_log.query(AuditQuery())
        assert len(events) == 1
        assert events[0].actor_id == "user_with_'quotes'"
        assert "<script>" in events[0].reason

    def test_query_with_no_matching_results(self, audit_log):
        """Test querying with no matching results."""
        audit_log.log(AuditEvent(category=AuditCategory.AUTH, action="login", actor_id="user_1"))

        result = audit_log.query(AuditQuery(actor_id="nonexistent_user"))

        assert len(result) == 0

    def test_row_to_event_with_json_details(self, audit_log):
        """Test converting row with JSON details."""
        # Log an event with details
        event = AuditEvent(
            category=AuditCategory.DATA,
            action="update",
            actor_id="user_1",
            details={"key": "value"},
        )
        audit_log.log(event)

        # Query and verify details are parsed correctly
        events = audit_log.query(AuditQuery(actor_id="user_1"))
        assert events[0].details == {"key": "value"}


# ===========================================================================
# Tests: Module Exports
# ===========================================================================


class TestModuleExports:
    """Tests for module exports."""

    def test_all_exports_available(self):
        """Test that all exports are available."""
        from aragora.audit import log

        assert hasattr(log, "AuditCategory")
        assert hasattr(log, "AuditOutcome")
        assert hasattr(log, "AuditEvent")
        assert hasattr(log, "AuditQuery")
        assert hasattr(log, "AuditLog")
        assert hasattr(log, "audit_auth_login")
        assert hasattr(log, "audit_data_access")
        assert hasattr(log, "audit_admin_action")
        assert hasattr(log, "get_audit_log")
        assert hasattr(log, "reset_audit_log")

    def test_exports_in_all(self):
        """Test that __all__ contains expected exports."""
        from aragora.audit.log import __all__

        expected = [
            "AuditCategory",
            "AuditEvent",
            "AuditLog",
            "AuditOutcome",
            "AuditQuery",
            "audit_admin_action",
            "audit_auth_login",
            "audit_data_access",
            "get_audit_log",
            "reset_audit_log",
        ]

        for item in expected:
            assert item in __all__
