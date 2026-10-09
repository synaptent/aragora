"""
Tests for the Audit Log compliance module.

Covers SOC2-required audit logging functionality:
- AuditLog class with hash chain integrity
- AuditEvent dataclass and serialization
- AuditCategory and AuditOutcome enums
- AuditQuery for filtering
- Export formats (JSON, CSV, SOC2)
- Retention policy enforcement
- Convenience functions for common audit events
"""

from __future__ import annotations

import json
import os
import pytest
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from aragora.audit.log import (
    AuditCategory,
    AuditEvent,
    AuditLog,
    AuditOutcome,
    AuditQuery,
    audit_admin_action,
    audit_auth_login,
    audit_data_access,
    get_audit_log,
    reset_audit_log,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_audit_db():
    """Create a temporary directory for audit database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "audit.db"
        yield db_path


@pytest.fixture
def audit_log(temp_audit_db):
    """Create an AuditLog instance with temp database."""
    # Clear any singleton state
    reset_audit_log()
    # Use environment to ensure SQLite is used
    with patch.dict(os.environ, {"ARAGORA_AUDIT_STORE_BACKEND": "sqlite"}, clear=False):
        log = AuditLog(db_path=temp_audit_db, retention_days=365)
        yield log


@pytest.fixture
def sample_event():
    """Create a sample audit event."""
    return AuditEvent(
        category=AuditCategory.AUTH,
        action="login",
        actor_id="user_123",
        resource_type="session",
        resource_id="sess_abc",
        outcome=AuditOutcome.SUCCESS,
        ip_address="192.168.1.100",
        user_agent="Mozilla/5.0",
        org_id="org_456",
    )


# ============================================================================
# AuditCategory Tests
# ============================================================================


class TestAuditCategory:
    """Tests for AuditCategory enum."""

    def test_all_categories_exist(self):
        """Test that all expected categories are defined."""
        expected = [
            "AUTH",
            "ACCESS",
            "DATA",
            "ADMIN",
            "BILLING",
            "DEBATE",
            "API",
            "SECURITY",
            "SYSTEM",
        ]
        for cat in expected:
            assert hasattr(AuditCategory, cat), f"Missing category: {cat}"

    def test_category_values(self):
        """Test category values are lowercase strings."""
        assert AuditCategory.AUTH.value == "auth"
        assert AuditCategory.ACCESS.value == "access"
        assert AuditCategory.DATA.value == "data"
        assert AuditCategory.ADMIN.value == "admin"
        assert AuditCategory.SECURITY.value == "security"

    def test_category_from_value(self):
        """Test creating category from value."""
        cat = AuditCategory("auth")
        assert cat == AuditCategory.AUTH


# ============================================================================
# AuditOutcome Tests
# ============================================================================


class TestAuditOutcome:
    """Tests for AuditOutcome enum."""

    def test_all_outcomes_exist(self):
        """Test that all expected outcomes are defined."""
        expected = ["SUCCESS", "FAILURE", "DENIED", "ERROR"]
        for outcome in expected:
            assert hasattr(AuditOutcome, outcome), f"Missing outcome: {outcome}"

    def test_outcome_values(self):
        """Test outcome values are lowercase strings."""
        assert AuditOutcome.SUCCESS.value == "success"
        assert AuditOutcome.FAILURE.value == "failure"
        assert AuditOutcome.DENIED.value == "denied"
        assert AuditOutcome.ERROR.value == "error"


# ============================================================================
# AuditEvent Tests
# ============================================================================


class TestAuditEvent:
    """Tests for AuditEvent dataclass."""

    def test_event_creation_minimal(self):
        """Test creating event with minimal required fields."""
        event = AuditEvent(
            category=AuditCategory.AUTH,
            action="login",
            actor_id="user_123",
        )

        assert event.category == AuditCategory.AUTH
        assert event.action == "login"
        assert event.actor_id == "user_123"
        assert event.outcome == AuditOutcome.SUCCESS  # Default
        assert event.id is not None  # Auto-generated
        assert event.timestamp is not None  # Auto-generated

    def test_event_creation_full(self, sample_event):
        """Test creating event with all fields."""
        assert sample_event.category == AuditCategory.AUTH
        assert sample_event.action == "login"
        assert sample_event.actor_id == "user_123"
        assert sample_event.resource_type == "session"
        assert sample_event.resource_id == "sess_abc"
        assert sample_event.outcome == AuditOutcome.SUCCESS
        assert sample_event.ip_address == "192.168.1.100"
        assert sample_event.user_agent == "Mozilla/5.0"
        assert sample_event.org_id == "org_456"

    def test_event_with_details(self):
        """Test event with details dictionary."""
        event = AuditEvent(
            category=AuditCategory.DATA,
            action="update",
            actor_id="user_123",
            details={"old_value": "a", "new_value": "b"},
        )

        assert event.details["old_value"] == "a"
        assert event.details["new_value"] == "b"

    def test_event_with_reason(self):
        """Test event with reason for failure/denial."""
        event = AuditEvent(
            category=AuditCategory.AUTH,
            action="login",
            actor_id="user_123",
            outcome=AuditOutcome.DENIED,
            reason="Invalid credentials",
        )

        assert event.outcome == AuditOutcome.DENIED
        assert event.reason == "Invalid credentials"

    def test_compute_hash(self, sample_event):
        """Test hash computation is deterministic."""
        hash1 = sample_event.compute_hash()
        hash2 = sample_event.compute_hash()

        assert hash1 == hash2
        assert len(hash1) == 32  # SHA256 truncated to 32 chars

    def test_compute_hash_includes_previous(self, sample_event):
        """Test hash changes when previous_hash changes."""
        hash1 = sample_event.compute_hash()

        sample_event.previous_hash = "abc123"
        hash2 = sample_event.compute_hash()

        assert hash1 != hash2

    def test_to_dict(self, sample_event):
        """Test converting event to dictionary."""
        d = sample_event.to_dict()

        assert d["category"] == "auth"
        assert d["action"] == "login"
        assert d["actor_id"] == "user_123"
        assert d["resource_type"] == "session"
        assert d["resource_id"] == "sess_abc"
        assert d["outcome"] == "success"
        assert d["ip_address"] == "192.168.1.100"
        assert d["org_id"] == "org_456"
        assert "timestamp" in d
        assert "id" in d

    def test_from_dict(self):
        """Test creating event from dictionary."""
        data = {
            "id": "evt_123",
            "timestamp": "2026-01-15T10:30:00",
            "category": "auth",
            "action": "logout",
            "actor_id": "user_456",
            "resource_type": "session",
            "resource_id": "sess_xyz",
            "outcome": "success",
            "ip_address": "10.0.0.1",
            "user_agent": "CLI",
            "correlation_id": "corr_abc",
            "org_id": "org_789",
            "workspace_id": "ws_123",
            "details": {"method": "token_expiry"},
            "reason": "",
            "previous_hash": "prev123",
            "event_hash": "hash456",
        }

        event = AuditEvent.from_dict(data)

        assert event.id == "evt_123"
        assert event.category == AuditCategory.AUTH
        assert event.action == "logout"
        assert event.actor_id == "user_456"
        assert event.outcome == AuditOutcome.SUCCESS
        assert event.details["method"] == "token_expiry"
        assert event.previous_hash == "prev123"

    def test_from_dict_with_datetime_object(self):
        """Test from_dict handles datetime objects."""
        now = datetime.now(timezone.utc)
        data = {
            "timestamp": now,
            "category": "system",
            "action": "startup",
            "actor_id": "system",
        }

        event = AuditEvent.from_dict(data)
        assert event.timestamp == now


# ============================================================================
# AuditQuery Tests
# ============================================================================


class TestAuditQuery:
    """Tests for AuditQuery dataclass."""

    def test_query_defaults(self):
        """Test query with default values."""
        query = AuditQuery()

        assert query.start_date is None
        assert query.end_date is None
        assert query.category is None
        assert query.action is None
        assert query.actor_id is None
        assert query.limit == 1000
        assert query.offset == 0

    def test_query_with_date_range(self):
        """Test query with date range."""
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 1, 31, tzinfo=timezone.utc)

        query = AuditQuery(start_date=start, end_date=end)

        assert query.start_date == start
        assert query.end_date == end

    def test_query_with_filters(self):
        """Test query with multiple filters."""
        query = AuditQuery(
            category=AuditCategory.AUTH,
            action="login",
            actor_id="user_123",
            outcome=AuditOutcome.FAILURE,
            org_id="org_456",
        )

        assert query.category == AuditCategory.AUTH
        assert query.action == "login"
        assert query.actor_id == "user_123"
        assert query.outcome == AuditOutcome.FAILURE
        assert query.org_id == "org_456"

    def test_query_with_pagination(self):
        """Test query with pagination."""
        query = AuditQuery(limit=50, offset=100)

        assert query.limit == 50
        assert query.offset == 100

    def test_query_with_search(self):
        """Test query with full-text search."""
        query = AuditQuery(search_text="failed login")

        assert query.search_text == "failed login"


# ============================================================================
# AuditLog Basic Tests
# ============================================================================


class TestAuditLogBasic:
    """Tests for basic AuditLog functionality."""

    def test_log_creation(self, audit_log):
        """Test creating an audit log instance."""
        assert audit_log is not None
        assert audit_log.retention_days == 365

    def test_log_event(self, audit_log, sample_event):
        """Test logging a single event."""
        event_id = audit_log.log(sample_event)

        assert event_id is not None
        assert event_id == sample_event.id

    def test_log_sets_hash_chain(self, audit_log, sample_event):
        """Test that logging sets hash chain values."""
        audit_log.log(sample_event)

        assert sample_event.event_hash != ""
        # First event has empty previous_hash
        assert sample_event.previous_hash == ""

    def test_log_multiple_events_chain(self, audit_log):
        """Test hash chain across multiple events."""
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

        # Second event's previous_hash should equal first event's event_hash
        assert event2.previous_hash == event1.event_hash
        assert event2.event_hash != event1.event_hash


# ============================================================================
# AuditLog Query Tests
# ============================================================================


class TestAuditLogQuery:
    """Tests for AuditLog query functionality."""

    @pytest.fixture(autouse=True)
    def setup_events(self, audit_log):
        """Set up test events."""
        # Auth events
        for i in range(5):
            audit_log.log(
                AuditEvent(
                    category=AuditCategory.AUTH,
                    action="login" if i % 2 == 0 else "logout",
                    actor_id=f"user_{i}",
                    org_id="org_1",
                    outcome=AuditOutcome.SUCCESS if i != 2 else AuditOutcome.FAILURE,
                )
            )

        # Data events
        for i in range(3):
            audit_log.log(
                AuditEvent(
                    category=AuditCategory.DATA,
                    action="update",
                    actor_id="user_0",
                    org_id="org_1",
                    resource_type="document",
                    resource_id=f"doc_{i}",
                )
            )

        # Different org
        audit_log.log(
            AuditEvent(
                category=AuditCategory.AUTH,
                action="login",
                actor_id="user_other",
                org_id="org_2",
            )
        )

    def test_query_all(self, audit_log):
        """Test querying all events."""
        events = audit_log.query(AuditQuery())

        assert len(events) == 9

    def test_query_by_category(self, audit_log):
        """Test filtering by category."""
        events = audit_log.query(AuditQuery(category=AuditCategory.AUTH))

        assert len(events) == 6
        assert all(e.category == AuditCategory.AUTH for e in events)

    def test_query_by_action(self, audit_log):
        """Test filtering by action."""
        events = audit_log.query(AuditQuery(action="login"))

        assert len(events) == 4
        assert all(e.action == "login" for e in events)

    def test_query_by_actor(self, audit_log):
        """Test filtering by actor."""
        events = audit_log.query(AuditQuery(actor_id="user_0"))

        assert len(events) == 4  # 1 login + 3 data updates
        assert all(e.actor_id == "user_0" for e in events)

    def test_query_by_outcome(self, audit_log):
        """Test filtering by outcome."""
        events = audit_log.query(AuditQuery(outcome=AuditOutcome.FAILURE))

        assert len(events) == 1
        assert events[0].outcome == AuditOutcome.FAILURE

    def test_query_by_org(self, audit_log):
        """Test filtering by organization."""
        events = audit_log.query(AuditQuery(org_id="org_1"))

        assert len(events) == 8
        assert all(e.org_id == "org_1" for e in events)

    def test_query_by_resource(self, audit_log):
        """Test filtering by resource type."""
        events = audit_log.query(AuditQuery(resource_type="document"))

        assert len(events) == 3
        assert all(e.resource_type == "document" for e in events)

    def test_query_combined_filters(self, audit_log):
        """Test combining multiple filters."""
        events = audit_log.query(
            AuditQuery(
                category=AuditCategory.AUTH,
                org_id="org_1",
                action="login",
            )
        )

        # Should find login events in org_1
        assert all(e.category == AuditCategory.AUTH for e in events)
        assert all(e.org_id == "org_1" for e in events)
        assert all(e.action == "login" for e in events)

    def test_query_with_limit(self, audit_log):
        """Test query with limit."""
        events = audit_log.query(AuditQuery(limit=3))

        assert len(events) == 3

    def test_query_with_offset(self, audit_log):
        """Test query with offset."""
        all_events = audit_log.query(AuditQuery())
        offset_events = audit_log.query(AuditQuery(offset=3, limit=3))

        # Offset events should be different from first 3
        all_ids = {e.id for e in all_events[:3]}
        offset_ids = {e.id for e in offset_events}
        assert all_ids.isdisjoint(offset_ids)


# ============================================================================
# AuditLog Integrity Tests
# ============================================================================


class TestAuditLogIntegrity:
    """Tests for audit log integrity verification."""

    def test_verify_integrity_empty_log(self, audit_log):
        """Test integrity verification on empty log."""
        is_valid, errors = audit_log.verify_integrity()

        assert is_valid is True
        assert errors == []

    def test_verify_integrity_valid_chain(self, audit_log):
        """Test integrity verification on valid chain."""
        for i in range(5):
            audit_log.log(
                AuditEvent(
                    category=AuditCategory.AUTH,
                    action=f"action_{i}",
                    actor_id="user_1",
                )
            )

        is_valid, errors = audit_log.verify_integrity()

        assert is_valid is True
        assert errors == []

    def test_verify_integrity_with_date_range(self, audit_log):
        """Test integrity verification with date range."""
        for i in range(3):
            audit_log.log(
                AuditEvent(
                    category=AuditCategory.AUTH,
                    action=f"action_{i}",
                    actor_id="user_1",
                )
            )

        start = datetime.now(timezone.utc) - timedelta(hours=1)
        end = datetime.now(timezone.utc) + timedelta(hours=1)

        is_valid, errors = audit_log.verify_integrity(start_date=start, end_date=end)

        assert is_valid is True


# ============================================================================
# AuditLog Export Tests
# ============================================================================


class TestAuditLogExport:
    """Tests for audit log export functionality."""

    @pytest.fixture
    def populated_log(self, audit_log):
        """Populate audit log with events."""
        for i in range(10):
            audit_log.log(
                AuditEvent(
                    category=AuditCategory.AUTH if i % 2 == 0 else AuditCategory.DATA,
                    action="login" if i % 2 == 0 else "update",
                    actor_id=f"user_{i}",
                    org_id="org_1",
                    outcome=AuditOutcome.SUCCESS if i % 3 != 0 else AuditOutcome.FAILURE,
                )
            )
        return audit_log

    def test_export_json(self, populated_log, temp_audit_db):
        """Test JSON export."""
        output_path = temp_audit_db.parent / "export.json"
        start = datetime.now(timezone.utc) - timedelta(hours=1)
        end = datetime.now(timezone.utc) + timedelta(hours=1)

        count = populated_log.export_json(output_path, start, end)

        assert count == 10
        assert output_path.exists()

        with open(output_path) as f:
            data = json.load(f)

        assert data["event_count"] == 10
        assert len(data["events"]) == 10
        assert "export_timestamp" in data

    def test_export_json_with_org_filter(self, populated_log, temp_audit_db):
        """Test JSON export with org filter."""
        output_path = temp_audit_db.parent / "export_org.json"
        start = datetime.now(timezone.utc) - timedelta(hours=1)
        end = datetime.now(timezone.utc) + timedelta(hours=1)

        count = populated_log.export_json(output_path, start, end, org_id="org_1")

        assert count == 10

    def test_export_csv(self, populated_log, temp_audit_db):
        """Test CSV export."""
        output_path = temp_audit_db.parent / "export.csv"
        start = datetime.now(timezone.utc) - timedelta(hours=1)
        end = datetime.now(timezone.utc) + timedelta(hours=1)

        count = populated_log.export_csv(output_path, start, end)

        assert count == 10
        assert output_path.exists()

        # Verify CSV format
        import csv

        with open(output_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 10
        assert "id" in reader.fieldnames
        assert "timestamp" in reader.fieldnames
        assert "category" in reader.fieldnames

    def test_export_soc2(self, populated_log, temp_audit_db):
        """Test SOC2 format export."""
        output_path = temp_audit_db.parent / "soc2_report.json"
        start = datetime.now(timezone.utc) - timedelta(hours=1)
        end = datetime.now(timezone.utc) + timedelta(hours=1)

        summary = populated_log.export_soc2(output_path, start, end)

        assert summary["events_exported"] == 10
        assert summary["integrity_verified"] is True
        assert output_path.exists()

        with open(output_path) as f:
            report = json.load(f)

        assert report["report_type"] == "SOC 2 Type II Audit Log Export"
        assert "audit_period" in report
        assert "integrity" in report
        assert "summary" in report
        assert "security_metrics" in report
        assert "control_evidence" in report

        # Check SOC2 control mappings
        assert "CC6.1_logical_access" in report["control_evidence"]
        assert "CC6.2_access_removal" in report["control_evidence"]
        assert "CC6.3_access_authorization" in report["control_evidence"]
        assert "CC7.2_security_events" in report["control_evidence"]


# ============================================================================
# AuditLog Retention Tests
# ============================================================================


class TestAuditLogRetention:
    """Tests for audit log retention policy."""

    def test_apply_retention_no_old_events(self, audit_log):
        """Test retention when no events are old enough."""
        audit_log.log(
            AuditEvent(
                category=AuditCategory.AUTH,
                action="login",
                actor_id="user_1",
            )
        )

        deleted = audit_log.apply_retention()

        assert deleted == 0

    def test_retention_preserves_recent(self, audit_log):
        """Test that retention preserves recent events."""
        for i in range(5):
            audit_log.log(
                AuditEvent(
                    category=AuditCategory.AUTH,
                    action=f"action_{i}",
                    actor_id="user_1",
                )
            )

        audit_log.apply_retention()
        events = audit_log.query(AuditQuery())

        assert len(events) == 5


# ============================================================================
# AuditLog Statistics Tests
# ============================================================================


class TestAuditLogStats:
    """Tests for audit log statistics."""

    def test_get_stats_empty(self, audit_log):
        """Test stats on empty log."""
        stats = audit_log.get_stats()

        assert stats["total_events"] == 0
        assert stats["by_category"] == {}
        assert stats["retention_days"] == 365

    def test_get_stats_with_events(self, audit_log):
        """Test stats with events."""
        for i in range(5):
            audit_log.log(
                AuditEvent(
                    category=AuditCategory.AUTH if i < 3 else AuditCategory.DATA,
                    action=f"action_{i}",
                    actor_id="user_1",
                )
            )

        stats = audit_log.get_stats()

        assert stats["total_events"] == 5
        assert stats["by_category"]["auth"] == 3
        assert stats["by_category"]["data"] == 2
        assert stats["oldest_event"] is not None
        assert stats["newest_event"] is not None


# ============================================================================
# Convenience Function Tests
# ============================================================================


class TestConvenienceFunctions:
    """Tests for convenience audit functions."""

    def test_audit_auth_login_success(self, audit_log):
        """Test logging successful login."""
        event_id = audit_auth_login(
            audit_log,
            user_id="user_123",
            ip_address="192.168.1.1",
            success=True,
        )

        assert event_id is not None

        events = audit_log.query(AuditQuery(actor_id="user_123"))
        assert len(events) == 1
        assert events[0].category == AuditCategory.AUTH
        assert events[0].action == "login"
        assert events[0].outcome == AuditOutcome.SUCCESS

    def test_audit_auth_login_failure(self, audit_log):
        """Test logging failed login."""
        event_id = audit_auth_login(
            audit_log,
            user_id="user_123",
            ip_address="192.168.1.1",
            success=False,
            reason="Invalid password",
        )

        assert event_id is not None

        events = audit_log.query(AuditQuery(actor_id="user_123"))
        assert len(events) == 1
        assert events[0].outcome == AuditOutcome.FAILURE
        assert events[0].reason == "Invalid password"

    def test_audit_data_access(self, audit_log):
        """Test logging data access."""
        event_id = audit_data_access(
            audit_log,
            user_id="user_456",
            resource_type="document",
            resource_id="doc_789",
            action="read",
            org_id="org_abc",
        )

        assert event_id is not None

        events = audit_log.query(AuditQuery(actor_id="user_456"))
        assert len(events) == 1
        assert events[0].category == AuditCategory.ACCESS
        assert events[0].action == "read"
        assert events[0].resource_type == "document"
        assert events[0].org_id == "org_abc"

    def test_audit_admin_action(self, audit_log):
        """Test logging admin action."""
        event_id = audit_admin_action(
            audit_log,
            admin_id="admin_001",
            action="delete_user",
            target_type="user",
            target_id="user_xyz",
            details={"reason": "Account terminated"},
        )

        assert event_id is not None

        events = audit_log.query(AuditQuery(actor_id="admin_001"))
        assert len(events) == 1
        assert events[0].category == AuditCategory.ADMIN
        assert events[0].action == "delete_user"
        assert events[0].details["reason"] == "Account terminated"


# ============================================================================
# Singleton Tests
# ============================================================================


class TestAuditLogSingleton:
    """Tests for audit log singleton behavior."""

    def test_reset_singleton(self, temp_audit_db):
        """Test resetting singleton state."""
        reset_audit_log()

        # Should start fresh
        with patch.dict(os.environ, {"ARAGORA_AUDIT_STORE_BACKEND": "sqlite"}, clear=False):
            with patch("aragora.observability.audit_log.require_distributed_store"):
                log1 = get_audit_log(db_path=temp_audit_db)
                log2 = get_audit_log()

                # Same instance
                assert log1 is log2

        reset_audit_log()


# ============================================================================
# Edge Cases Tests
# ============================================================================


class TestAuditLogEdgeCases:
    """Tests for edge cases and error handling."""

    def test_event_with_special_characters(self, audit_log):
        """Test event with special characters in fields."""
        event = AuditEvent(
            category=AuditCategory.DATA,
            action="update",
            actor_id="user_with_'quotes'",
            details={"query": 'SELECT * FROM users WHERE name = "O\'Brien"'},
        )

        event_id = audit_log.log(event)
        assert event_id is not None

        events = audit_log.query(AuditQuery())
        assert len(events) == 1
        # details round-trips as a dict; check the stored field value directly
        # (str(dict) would escape the apostrophe in its repr).
        assert "O'Brien" in events[0].details["query"]

    def test_event_with_unicode(self, audit_log):
        """Test event with unicode characters."""
        event = AuditEvent(
            category=AuditCategory.DATA,
            action="update",
            actor_id="user_123",
            details={"message": "Hello, World! Translate: Bonjour le monde"},
        )

        event_id = audit_log.log(event)
        assert event_id is not None

    def test_event_with_empty_details(self, audit_log):
        """Test event with empty details."""
        event = AuditEvent(
            category=AuditCategory.AUTH,
            action="login",
            actor_id="user_123",
            details={},
        )

        event_id = audit_log.log(event)
        assert event_id is not None

    def test_query_empty_results(self, audit_log):
        """Test query that returns no results."""
        events = audit_log.query(AuditQuery(actor_id="nonexistent_user"))

        assert events == []

    def test_large_details_field(self, audit_log):
        """Test event with large details field."""
        large_details = {f"key_{i}": f"value_{i}" * 100 for i in range(100)}

        event = AuditEvent(
            category=AuditCategory.DATA,
            action="bulk_update",
            actor_id="user_123",
            details=large_details,
        )

        event_id = audit_log.log(event)
        assert event_id is not None

        events = audit_log.query(AuditQuery(actor_id="user_123"))
        assert len(events) == 1
        assert len(events[0].details) == 100
